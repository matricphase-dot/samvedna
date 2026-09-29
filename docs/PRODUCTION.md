# SAMVEDNA — Production Path (what "real phone calls" actually requires)

This document separates **what exists and works today** from **what is
engineering/validation work**, so we never bluff a ministry panel.

## What works today (verified in this repo)

| Capability | Proof |
|---|---|
| Real WAV phone audio in → real prosody out (VAD, F0 autocorrelation, silence runs, 4–12 Hz tremor, speech rate) | `POST /api/analyze-audio` — synthetic distressed call scored HIGH with tremor 1.0, silence 62%; calm call stayed below the HIGH threshold |
| Real text distress analysis (code-mixed, negation-aware) + safety rails | rail window → forced 93.0 CRITICAL |
| Gate-1 language-agnostic screening when no ASR | prosody-led mode: distressed audio → HIGH with zero transcript |
| Consent-first, anonymous, audit-logged, exportable triage | working console + report endpoint |

## Real 14566 call integration (telephony adapter)

Two integration modes, both mapping 1:1 onto `POST /api/analyze-audio`:

1. **Recording webhook (fastest to pilot).** Gov helplines in India run on
   CPaaS (Exotel / Ozonetel / Knowlarity class platforms). Configure:
   `on-call-end → recording URL → adapter downloads WAV → POST /api/analyze-audio`.
   This is post-call triage: callback-priority queue for abandoned/distressed calls.
2. **Live stream (the real-time mode).** SIP/RTP tap or CPaaS media-stream
   socket → adapter emits 8s raw-audio windows → same endpoint with
   `window_idx` sequencing. Requires telco/gateway cooperation — this is the
   MoSJE partnership item, not a code problem.

Adapter contract (JSON): `{call_id, window_idx, pcm_wav_base64, meta}` → returns
per-window SVI payload identical to the web console.

## ASR at scale

- `faster-whisper small` (Hinglish-capable) per worker node; falls back to
  `tiny` for CPU-only.
- AI4Bharat **IndicConformer** for dialect-heavy queues.
- Degradation ladder stays: ASR → browser/client transcript → prosody-only.

## Model roadmap (the honest one)

1. Lexicon + rules (current) = deterministic guardrail, explainable by design.
2. **Fine-tune IndicBERT** on a clinician-labelled distress corpus
   (collect via consented pilot, not before); keep the lexicon as a
   feature extractor + safety rails as an override layer.
3. Isotonic calibration against PC-PTSD-5 screens; publish per-language
   metrics including abstention rates. Voice suicide-risk literature says
   AUC 0.74–0.85 — we plan *around* that ceiling, we don't pretend past it.

## Privacy / law (India)

- DPDP Act 2023: explicit consent, purpose limitation, withdrawal, officer SPOC.
- Default retention: **no raw audio stored** — features + redacted transcript
  only (redact-before-store already implemented in the pipeline design).
- Hosting: MeghRaj/NIC empanelled cloud for government data classification;
  on-prem option for state deployments.
- No facial AI. Human-in-the-loop is contractual, not cosmetic.

## Infra reference

Container (Docker) → MeghRaj/NIC · Postgres+RLS (Supabase self-host or RDS)
· Redis stream queue · Sentry · per-node autoscaler for ASR workers.

## Pilot protocol (90 days, shadow → assist)

- Days 1–30 **shadow**: SVI logged, never shown, never acted on.
- Days 31–90 **assist**: flags shown with "why"; counsellors rate agreement.
- Success metrics: clinician agreement (Cohen's κ), time-to-counsellor for
  Critical flags, abandoned-callback rescue rate, per-language fairness drift.
- Gate for rollout: κ ≥ 0.6 AND drift ≤ bound in CI AND zero privacy incidents.

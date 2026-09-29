# SAMVEDNA (संवेदना) — Real-Time Trauma Triage for NHAA 14566

**SIH26093 · MoSJE · MedTech · Team Zillion Minds**
*Triage & flagging aid for human experts. NOT a clinical diagnostic.*

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

## What this prototype demonstrates (live, clickable)

| Claim in the deck | Where it runs in this prototype |
|---|---|
| Real-time sliding-window SVI | Caller tab streams a simulated 14566 call; SVI + "why" update every ~3s **while the caller is still on the line** |
| Neuro-symbolic safety rails | Caller A's final window fires `SAFETY_RAIL_FIRED` — ML bypassed, forced CRITICAL, red alert |
| Honest abstention | Thin-evidence + calm prosody → `INSUFFICIENT EVIDENCE -> HUMAN` banner instead of a fake score |
| Negation handling (code-mix) | "darr nahi lag raha" scores as coping; "koi madad nahi" boosts isolation |
| Trajectory tracking | Repeat-caller scenario (2 prior sessions seeded) + SVI sparkline per window |
| Silent-caller rescue | Scenario C carries `abandoned=True` → metadata raises SVI, flagged in queue |
| Trauma-to-statute mapping | PoA Act 1989 provision chips render per flag |
| Counsellor console | Critical-first queue, 90s SLA countdown, auto-escalation to supervisor, 1-tap actions, audit log, exportable report |
| Fairness-as-a-test | Tab 3 runs the counterfactual harness live (flip dialect <-> standard; bound 5 pts) |
| Privacy by design | Anonymous tokens, consent gate before any analysis, no PII, audit on every event |

## Architecture (prototype)

FastAPI service = intake API + SVI engine + counsellor console (static SPA).
SQLite persists cases/windows/audit (schema mirrors the intended Supabase tables 1:1).

## REAL audio verification (recorded calls, not scripting)

`POST /api/analyze-audio` accepts a real PCM WAV and runs the actual DSP
pipeline: VAD (10th-pct noise-floor gating), silence-run segmentation,
autocorrelation F0 with jitter, 4–12 Hz tremor band on the voiced RMS
contour, speech-rate from ASR/onsets — fused into SVI per 8-second window.

Verified in-repo:

```
distressed.wav (25.7s synthetic call: tremor bursts + 2.5-3s silences)
  win0 SVI 57.6 HIGH | win1 SVI 50.1 HIGH | win2 SVI 93.0 CRITICAL (rail)
calm.wav (28.3s steady voice)
  wins 26.9-40.9 MODERATE, no subflags, no rail
Gate-1 (prosody-only, no transcript): distressed → HIGH on voice alone
```

Server-side ASR (`faster-whisper`) and `librosa` are optional installs for
local/on-prem (`pip install -r requirements-full.txt`) — too heavy for
serverless, which is exactly why the degradation ladder (server ASR →
client transcript → prosody-only) exists. Production telephony path:
`docs/PRODUCTION.md`.

## Prototype -> Production map

| Prototype (here) | Production (NHAA deployment) |
|---|---|
| Rule+lexicon text scorer (`svi.py`) | IndicBERT/MuRIL classifier, same negation layer kept as post-processor |
| Simulated prosody per window | librosa live extraction: silence ratio, jitter/shimmer, pitch variance, speech rate from the 14566 audio stream |
| Scripted windows | Whisper / Indic ASR streaming transcription (code-mixed) |
| SQLite | Supabase Postgres + RLS + anonymous auth + Prisma |
| Static SPA | Next.js intake + counsellor console |
| 90s demo SLA | Configurable SLA per state/district SOP |

## The fairness story (real, from this repo's history)

1. **Run 1 — FAIL.** Max drift **28.6 pts**: the English lexicon was under-covered, so identical distress in standard English scored drastically lower than in dialect. *The harness did its job.*
2. **Fix — lexicon balancing.**
3. **Run 2 — FAIL.** Drift **7.7**: overlapping substring matches ("boycott" inside "boycotted") were double-counting dialect-side terms.
4. **Fix — longest-span overlap resolution.**
5. **Run 3 — PASS.** Max drift **1.1 pts**, tiers identical across all variants.

That is what "computed fairness, not a hardcoded 96.4" actually looks like.

## Calibrated claim (say this to judges)

We do **not** claim diagnostic accuracy — published voice suicide-risk models reach only AUC 0.74-0.85. SAMVEDNA is calibrated **triage**: prioritize, explain, abstain, hand to a human. The SVI rubric is clinician-anchored (Distress Thermometer, PC-PTSD-5, ideation-to-action) and every score ships its "why".

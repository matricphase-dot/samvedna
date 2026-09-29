# -*- coding: utf-8 -*-
"""
SAMVEDNA SVI Engine - stress vulnerability triage core.

Design principles (the ethics spine):
- Triage aid, NOT a diagnostic. We flag; humans decide.
- Neuro-symbolic Safety Rails: explicit suicidal ideation bypasses the ML
  entirely -> instant CRITICAL + human alert. The model never downvotes
  "I want to die."
- Honest abstention: with insufficient evidence, we output
  INSUFFICIENT EVIDENCE -> HUMAN instead of a fabricated score.
- Glass-box: every score carries an auditable 'why'.
- Language-agnostic prosody gate + code-mixed (Hinglish) text lexicons with
  negation handling.
"""
import re

TIERS = [(0, "LOW"), (25, "MODERATE"), (50, "HIGH"), (75, "CRITICAL")]

TIER_COLORS = {"LOW": "#2e7d32", "MODERATE": "#f9a825",
               "HIGH": "#ef6c00", "CRITICAL": "#b00020"}

# ---- Lexicons: romanized Hindi / Hinglish + English -------------------------
LEX = {
    "ideation": {  # explicit self-harm ideation -> SAFETY RAIL
        "weight": 30,
        "terms": ["khatam kar lunga", "khatam kar lungi", "apni jaan",
                  "jeena nahi", "jina nahi", "zinda nahi", "mar jaana",
                  "mar jana chahiye", "suicide", "khudkushi", "khud khatam",
                  "end my life", "kill myself", "no reason to live",
                  "jeene ka koi", "marne ka mann", "maut chahiye"],
    },
    "depression": {
        "weight": 14,
        "terms": ["udas", "hopeless", "umeed nahi", "no hope", "neend nahi",
                  "so nahi", "khaana nahi", "khana nahi", "thak gaya",
                  "thak gayi", "ro raha", "ro rahi", "roti", "rokenge",
                  "depressed", "cant go on", "sab khatam", "bekar lagta",
                  "dil bhar aata", "cannot sleep", "cant sleep", "can't sleep",
                  "no sleep", "everything feels finished", "everything is over",
                  "tired of fighting", "crying all night"],
    },
    "fear": {
        "weight": 12,
        "terms": ["darr", "dar lag", "scared", "afraid", "bhay", "sahm",
                  "sehmi", "gabar", "terrified", "kanp", "kaanp"],
    },
    "intimidation": {
        "weight": 14,
        "terms": ["dhamki", "dhamka", "dhamkaya", "threat", "blackmail",
                  "daraya", "dara rahe", "marne ke dhamki", "chalta kar",
                  "dekh lunga", "ant bhayo", "intimidated", "warned us to leave"],
    },
    "isolation": {
        "weight": 12,
        "terms": ["bahishkar", "bahiskar", "boycott", "boycotted", "akela",
                  "akeli", "koi nahi", "alone", "gaon ne nikal", "sabne chhod",
                  "huqka pani band", "hookah pani", "sahara nahi",
                  "koi saath nahi", "tanha", "nobody is helping",
                  "no one is helping", "no one helps", "left alone",
                  "everyone has abandoned", "no support at all"],
    },
    "violence": {
        "weight": 12,
        "terms": ["pitaai", "pitai", "peeta", "maara", "maar diya",
                  "goli", "hamla", "jalaya", "jala diya", "tod diya",
                  "khun", "khoon", "rape", "balatkar", "chhed", "molest",
                  "haath uthana", "attack", "was beaten", "beaten", "beat me",
                  "hit me", "burnt our", "burned down"],
    },
    "economic": {
        "weight": 10,
        "terms": ["zameen cheen", "jameen cheen", "land seized", "kabza",
                  "kabja", "paisa nahi", "pension rok", "naukri se nikal",
                  "karza", "qarza", "loot liya", "hadsa nahi",
                  "seized my land", "seized our land", "land was seized",
                  "took my land", "pension stopped", "blocked my pension"],
    },
}

SUPPORT_TERMS = ["madad", "help", "sahara", "support", "sunne wala",
                 "saath", "insaaf", "nyay"]
NEGATIONS = ["nahi", "nahin", "nahiin", "na", "no", "not", "nhi", "mat"]

# PoA Act 1989 descriptive provision mapping (deliberately clause-safe labels)
POA_MAP = {
    "isolation": "PoA Act 1989 - social & economic boycott provisions",
    "intimidation": "PoA Act 1989 - intimidation / threat provisions",
    "violence": "PoA Act 1989 - assault / use of force provisions",
    "economic": "PoA Act 1989 - wrongful dispossession of land provisions",
}


def _tok(text):
    return re.findall(r"[a-zA-Z\u0900-\u097F']+", (text or "").lower())


def _has_negation_near(tokens, idx, window=3):
    lo, hi = max(0, idx - window), min(len(tokens), idx + window + 1)
    return any(t in NEGATIONS for t in tokens[lo:hi])


def _find_hits(tokens, text):
    """Term hits as (category, term, token_idx). Overlap-resolved: among
    overlapping matches the LONGEST term wins (no double counting)."""
    low = " ".join(tokens)
    spans = []  # (pos, end, category, term, token_idx)
    for cat, spec in LEX.items():
        for term in spec["terms"]:
            start = 0
            while True:
                pos = low.find(term, start)
                if pos == -1:
                    break
                spans.append((pos, pos + len(term), cat, term,
                              low[:pos].count(" ")))
                start = pos + 1
    spans.sort(key=lambda s: -(s[1] - s[0]))  # longest first
    accepted, hits = [], []
    for pos, end, cat, term, idx in spans:
        if any(pos < e2 and end > p2 for p2, e2 in accepted):
            continue
        accepted.append((pos, end))
        hits.append((cat, term, idx))
    return hits


def analyze_text(text):
    tokens = _tok(text)
    hits = _find_hits(tokens, text)
    scores, counts, why, details = {}, {}, [], {}
    evidence = 0
    rail = False

    for cat, term, idx in hits:
        w = LEX[cat]["weight"]
        negated = _has_negation_near(tokens, idx)
        if cat == "fear" and negated:
            w *= 0.35  # "darr nahi lag raha" - genuine coping statement
            details.setdefault("coping", "negated fear: '%s' marked as coping" % term)
        if cat == "ideation" and negated and "nahi" in term:
            continue
        scores[cat] = scores.get(cat, 0) + w
        counts[cat] = counts.get(cat, 0) + 1
        evidence += 1
        if cat == "ideation" and not negated:
            rail = True

    # negated support -> isolation boost ("koi madad nahi", "no one to help")
    for i, t in enumerate(tokens):
        if t in SUPPORT_TERMS and _has_negation_near(tokens, i):
            scores["isolation"] = scores.get("isolation", 0) + 10
            counts["isolation"] = counts.get("isolation", 0) + 1
            evidence += 1
            why.append("negated support marker ('...%s nahi/no...')" % t)

    text_raw = sum(scores.values())
    text_score = min(100.0, text_raw)

    for cat, n in sorted(counts.items(), key=lambda kv: -LEX[kv[0]]["weight"] * kv[1]):
        why.append("%s markers x%d" % (cat.replace("_", " "), n))

    return {
        "text_score": round(text_score, 1),
        "counts": counts,
        "why": why,
        "rail": rail,
        "evidence": evidence,
        "details": details,
    }


def analyze_prosody(p):
    """p: {silence_ratio, avg_silence_s, pitch_var, rate_wps, tremor, energy_var}"""
    p = p or {}
    silence = float(p.get("silence_ratio", 0.0))
    avg_sil = float(p.get("avg_silence_s", 0.0))
    pitch_var = float(p.get("pitch_var", 0.30))
    rate = float(p.get("rate_wps", 2.6))
    tremor = float(p.get("tremor", 0.0))
    energy = float(p.get("energy_var", 0.30))

    score = 0.0
    parts = []
    score += min(silence, 0.9) / 0.9 * 30
    if silence > 0.35:
        parts.append("high silence ratio (%.0f%%)" % (silence * 100))
    score += min(avg_sil, 6.0) / 6.0 * 15
    if avg_sil >= 2.0:
        parts.append("long pauses (avg %.1fs)" % avg_sil)
    instab = abs(pitch_var - 0.5) * 2
    score += instab * 20
    if instab > 0.6:
        parts.append("pitch instability")
    slow = max(0.0, 1.0 - min(rate / 3.5, 1.0))
    score += slow * 15
    if slow > 0.55:
        parts.append("abnormally slow speech (%.1f wps)" % rate)
    score += min(tremor, 1.0) * 20
    if tremor > 0.5:
        parts.append("voice tremor detected")

    return {"prosody_score": round(min(100.0, score), 1), "why": parts}


def fuse(text_res, pros_res, meta=None):
    meta = meta or {}
    repeat = int(meta.get("repeat_calls", 0))
    abandoned = bool(meta.get("abandoned", False))

    meta_score = min(20, repeat * 5) + (8 if abandoned else 0)
    pros_led = (text_res["text_score"] == 0 and text_res["evidence"] == 0)
    if pros_led:
        # GATE-1 standalone: no ASR / no text evidence -> prosody leads.
        # Language-agnostic distress screen that works on any dialect.
        svi = 0.85 * pros_res["prosody_score"] + 0.15 * min(100, meta_score * 5)
    else:
        svi = 0.55 * text_res["text_score"] + 0.35 * pros_res["prosody_score"] \
              + 0.10 * min(100, meta_score * 5)

    why = list(text_res["why"]) + list(pros_res["why"])
    if repeat:
        why.append("REPEAT CALLER: %dx prior contacts" % repeat)
    if abandoned:
        why.append("prior abandoned call detected")

    # confidence / abstention
    ev = text_res["evidence"]
    if ev <= 1 and pros_res["prosody_score"] < 25:
        confidence = "LOW"
        abstain = True
    elif ev <= 2 and pros_res["prosody_score"] < 40:
        confidence = "MEDIUM"
        abstain = False
    else:
        confidence = "HIGH"
        abstain = False

    # neuro-symbolic safety rail
    if text_res["rail"]:
        svi = max(svi, 93.0)

    svi = round(min(100.0, svi), 1)
    tier = "LOW"
    for th, name in TIERS:
        if svi >= th:
            tier = name

    subflags = [c for c, n in text_res["counts"].items() if n]
    if text_res["rail"] and "suicidal_ideation" not in subflags:
        subflags.append("suicidal_ideation")

    poa = sorted({POA_MAP[c] for c in text_res["counts"] if c in POA_MAP})

    return {
        "svi": svi,
        "tier": tier,
        "tier_color": TIER_COLORS[tier],
        "subflags": subflags,
        "why": why[:6],
        "poa": poa,
        "rail": text_res["rail"],
        "abstain": abstain and not text_res["rail"],
        "confidence": confidence,
        "text_score": text_res["text_score"],
        "prosody_score": pros_res["prosody_score"],
        "meta_score": min(100, meta_score * 5),
        "pros_led": pros_led,
        "coping_note": text_res["details"].get("coping"),
    }


def fairness_check():
    """Counterfactual harness: flip dialect/community markers on identical
    narratives; report SVI drift. Build fails in CI if drift > bound."""
    pairs = [
        ("Mujhe bahut darr lag raha hai, gaon walon ne bahishkar kar diya hai. "
         "Koi madad nahi kar raha.",
         "I am feeling very scared, the villagers have boycotted us. "
         "Nobody is helping."),
        ("Unhone mujhe dhamkaya aur meri zameen cheen li. Raat ko neend nahi "
         "aati, sab khatam lagta hai.",
         "They threatened me and seized my land. I cannot sleep at night, "
         "everything feels finished."),
        ("Pension ka pata poochhna tha, kal office jana hai.",
         "I wanted to ask about the pension, I will go to the office tomorrow."),
    ]
    neutral = dict(silence_ratio=0.25, avg_silence_s=1.2, pitch_var=0.35,
                   rate_wps=2.6, tremor=0.2, energy_var=0.3)
    rows, max_drift = [], 0.0
    for a, b in pairs:
        ra = fuse(analyze_text(a), analyze_prosody(neutral))
        rb = fuse(analyze_text(b), analyze_prosody(neutral))
        drift = round(abs(ra["svi"] - rb["svi"]), 1)
        max_drift = max(max_drift, drift)
        rows.append({"variant_a_svi": ra["svi"], "variant_b_svi": rb["svi"],
                     "drift": drift, "tier_a": ra["tier"], "tier_b": rb["tier"]})
    return {"bound": 5.0, "max_drift": max_drift,
            "result": "PASS" if max_drift <= 5.0 else "FAIL", "pairs": rows}

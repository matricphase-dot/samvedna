# -*- coding: utf-8 -*-
"""SAMVEDNA API - triage & flagging aid. NOT a clinical diagnostic."""
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audio_pipeline as ap
from . import db, svi
from .scenarios import SCENARIOS, TIER_ACTIONS

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="SAMVEDNA - Real-Time Trauma Triage (SIH26093)")
db.init()

if not db.queue():
    db.seed_repeat_history()


class SessionReq(BaseModel):
    language: str = "Hinglish"
    repeat_calls: int = 0
    abandoned: bool = False


class AssessReq(BaseModel):
    case_id: int
    window_idx: int
    text: str = ""
    prosody: dict = {}


class ActionReq(BaseModel):
    case_id: int
    action: str


@app.post("/api/session")
def new_session(req: SessionReq):
    cid, tok = db.create_case(req.language, req.repeat_calls, req.abandoned)
    return {"case_id": cid, "token": tok,
            "consent": "Plain-language consent captured. Anonymous session. "
                       "No PII stored. You may hang up anytime."}


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s["id"], "label": s["label"], "language": s["language"],
             "windows": len(s["windows"]), "repeat_calls": s["repeat_calls"],
             "abandoned": s["abandoned"]} for s in SCENARIOS]


@app.get("/api/scenario/{sid}/window/{idx}")
def scenario_window(sid: str, idx: int):
    s = next((x for x in SCENARIOS if x["id"] == sid.upper()), None)
    if not s or idx < 0 or idx >= len(s["windows"]):
        return JSONResponse({"error": "no such window"}, status_code=404)
    text, pros = s["windows"][idx]
    return {"text": text, "prosody": pros, "total": len(s["windows"]),
            "language": s["language"], "repeat_calls": s["repeat_calls"],
            "abandoned": s["abandoned"]}


@app.post("/api/assess")
def assess(req: AssessReq):
    case = db.get_case(req.case_id)
    if not case:
        return JSONResponse({"error": "unknown case"}, status_code=404)
    text_res = svi.analyze_text(req.text)
    pros_res = svi.analyze_prosody(req.prosody)
    res = svi.fuse(text_res, pros_res,
                   {"repeat_calls": case["repeat_calls"],
                    "abandoned": bool(case["abandoned"])})
    first_crit = db.record_window(req.case_id, req.window_idx, req.text, res)
    res["first_critical_at"] = first_crit
    res["sla_seconds"] = 90
    res["escalated"] = bool(db.get_case(req.case_id)["escalated"])
    res["disclaimer"] = ("Triage flag for human experts - NOT a clinical "
                         "diagnosis.")
    return res


@app.get("/api/cases")
def cases():
    q = db.queue()
    for case in q:
        case["actions"] = TIER_ACTIONS.get(case["tier"], [])
    return q


@app.get("/api/case/{cid}")
def case_detail(cid: int):
    case = db.get_case(cid)
    if not case:
        return JSONResponse({"error": "unknown case"}, status_code=404)
    for k in ("subflags", "why", "poa"):
        case[k] = json.loads(case[k])
    case["windows_list"] = db.get_windows(cid)
    case["actions"] = TIER_ACTIONS.get(case["tier"], [])
    return case


@app.post("/api/action")
def action(req: ActionReq):
    db.act(req.case_id, req.action)
    return {"ok": True}


@app.post("/api/escalate/{cid}")
def escalate(cid: int):
    db.escalate(cid)
    return {"ok": True}


@app.get("/api/audit")
def audit_log():
    return db.recent_audit()


@app.get("/api/fairness")
def fairness():
    return svi.fairness_check()


@app.post("/api/analyze-audio")
async def analyze_audio(file: UploadFile = File(...),
                        transcript: str = Form(""),
                        language: str = Form("Hinglish"),
                        repeat_calls: int = Form(0),
                        abandoned: bool = Form(False)):
    """REAL call recording -> REAL prosody extraction -> SVI per 8s window.
    ASR ladder: server-side faster-whisper (local/on-prem) -> client-side
    transcript (browser Speech API) -> Gate-1 prosody-only + abstention."""
    raw = await file.read()
    try:
        x, sr = ap.load_wav(raw)
    except ap.AudioError as e:
        return JSONResponse(
            {"error": str(e),
             "hint": "Upload a PCM WAV (16-bit mono preferred). "
                     "MP3/other codecs are decoded client-side via the "
                     "Record-Live feature, or convert to WAV first."},
            status_code=400)

    duration = len(x) / sr
    chunks = ap.window_signal(x, sr, 8.0)
    cid, tok = db.create_case(language, repeat_calls, abandoned)
    db.audit(cid, "REAL_AUDIO_INGESTED",
             "wav %.1fs | %d analysis windows" % (duration, len(chunks)))

    texts = [""] * len(chunks)
    asr_mode = "none"
    if ap.server_asr_available():
        asr_mode = "server:faster-whisper(tiny)"
        for i, t in ap.transcribe_windows(chunks, sr) or []:
            texts[i] = t
    elif transcript.strip():
        asr_mode = "client:browser-speech-api"
        texts[-1] = transcript.strip()

    windows_out = []
    for i, chunk in enumerate(chunks):
        wsec = len(chunk) / sr
        nwords = len(texts[i].split())
        feats = ap.prosody_from_signal(chunk, sr, wsec, words=nwords)
        pros = svi.analyze_prosody(feats)
        tres = svi.analyze_text(texts[i])
        fused = svi.fuse(tres, pros,
                         {"repeat_calls": repeat_calls,
                          "abandoned": abandoned})
        first_crit = db.record_window(cid, i, texts[i], fused)
        fused["first_critical_at"] = first_crit
        fused["sla_seconds"] = 90
        windows_out.append({
            "idx": i, "duration_s": round(wsec, 1), "text": texts[i],
            "prosody_features": feats, "svi": fused["svi"],
            "tier": fused["tier"], "tier_color": fused["tier_color"],
            "subflags": fused["subflags"], "why": fused["why"],
            "poa": fused["poa"], "rail": fused["rail"],
            "abstain": fused["abstain"], "confidence": fused["confidence"],
            "text_score": fused["text_score"],
            "prosody_score": fused["prosody_score"],
            "first_critical_at": first_crit})

    final = windows_out[-1] if windows_out else {}
    return {
        "case_id": cid, "token": tok,
        "asr_mode": asr_mode,
        "gate": "GATE1+GATE2 (audio prosody + text)" if asr_mode != "none"
                else "GATE1 (prosody-only, language-agnostic)",
        "duration_s": round(duration, 1),
        "windows": windows_out,
        "final": final,
        "disclaimer": "Triage flag for human experts - NOT a clinical "
                      "diagnosis. Human review required before any action."}


@app.get("/api/report/{cid}", response_class=PlainTextResponse)
def report(cid: int):
    case = case_detail(cid)
    if isinstance(case, JSONResponse):
        return case
    lines = [
        "SAMVEDNA TRIAGE REPORT - %s" % case["token"],
        "=" * 56,
        "DISCLAIMER: triage flag for human experts. NOT a diagnosis.",
        "Language: %s | Status: %s | Windows: %d" % (
            case["language"], case["status"], case["windows"]),
        "Current SVI: %.1f (%s) | Confidence-window count: %d" % (
            case["svi"], case["tier"], case["windows"]),
        "Sub-flags: %s" % ", ".join(case["subflags"]) or "none",
        "",
        "WHY (explainability):",
    ] + ["  - " + w for w in case["why"]] + [
        "",
        "PoA Act 1989 suggested provisions:",
    ] + (["  - " + p for p in case["poa"]] or ["  none"]) + [
        "",
        "Distress trajectory (SVI per window):",
        "  " + " -> ".join("%.0f(%s)" % (w["svi"], w["tier"][:4])
                           for w in case["windows_list"]),
        "",
        "Recommended actions:",
    ] + ["  - " + a for a in case["actions"]]
    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition":
                 'attachment; filename="samvedna_report_%s.txt"'
                 % case["token"]})


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))

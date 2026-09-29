# -*- coding: utf-8 -*-
"""SQLite storage for SAMVEDNA prototype.
Production swap: Supabase Postgres with RLS + anonymous auth (see README).
Tables mirror the intended Supabase schema 1:1."""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

# Serverless (Vercel) has a read-only project FS; /tmp is writable per instance.
_default = "/tmp/samvedna.db" if os.environ.get("VERCEL") else \
    str(Path(__file__).resolve().parent.parent / "samvedna.db")
DB = Path(os.environ.get("SAMVEDNA_DB", _default))


def conn():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    return c


def init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS cases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE,
        language TEXT,
        created_at REAL,
        status TEXT DEFAULT 'OPEN',
        tier TEXT DEFAULT 'LOW',
        svi REAL DEFAULT 0,
        subflags TEXT DEFAULT '[]',
        why TEXT DEFAULT '[]',
        poa TEXT DEFAULT '[]',
        abstain INTEGER DEFAULT 0,
        rail INTEGER DEFAULT 0,
        windows INTEGER DEFAULT 0,
        repeat_calls INTEGER DEFAULT 0,
        abandoned INTEGER DEFAULT 0,
        first_critical_at REAL,
        escalated INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS windows(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER,
        idx INTEGER,
        text TEXT,
        text_score REAL,
        prosody_score REAL,
        svi REAL,
        tier TEXT,
        created_at REAL
    );
    CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER,
        event TEXT,
        detail TEXT,
        created_at REAL
    );
    """)
    c.commit()
    c.close()


def now():
    return time.time()


def new_token():
    return "SVA-" + uuid.uuid4().hex[:10].upper()


def audit(case_id, event, detail=""):
    c = conn()
    c.execute("INSERT INTO audit(case_id,event,detail,created_at) VALUES(?,?,?,?)",
              (case_id, event, detail, now()))
    c.commit()
    c.close()


def create_case(language, repeat_calls=0, abandoned=False, token=None):
    c = conn()
    tok = token or new_token()
    cur = c.execute(
        "INSERT INTO cases(token,language,created_at,repeat_calls,abandoned) "
        "VALUES(?,?,?,?,?)",
        (tok, language, now(), repeat_calls, 1 if abandoned else 0))
    cid = cur.lastrowid
    c.commit()
    c.close()
    audit(cid, "SESSION_CREATED",
          "anonymous session | lang=%s | consent captured" % language)
    return cid, tok


def record_window(case_id, idx, text, res):
    c = conn()
    c.execute(
        "INSERT INTO windows(case_id,idx,text,text_score,prosody_score,svi,"
        "tier,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (case_id, idx, text, res["text_score"], res["prosody_score"], res["svi"],
         res["tier"], now()))
    row = c.execute("SELECT windows, first_critical_at, escalated FROM cases "
                    "WHERE id=?", (case_id,)).fetchone()
    first_crit = row["first_critical_at"]
    events = []
    if res["tier"] == "CRITICAL" and first_crit is None:
        first_crit = now()
        events.append(("ESCALATION_TIMER_STARTED", "90s SLA countdown armed"))
    if res["rail"]:
        events.append(("SAFETY_RAIL_FIRED",
                       "explicit ideation - model bypassed, forced CRITICAL"))
    c.execute(
        "UPDATE cases SET tier=?, svi=?, subflags=?, why=?, poa=?, abstain=?, "
        "rail=?, windows=?, first_critical_at=? WHERE id=?",
        (res["tier"], res["svi"], json.dumps(res["subflags"]),
         json.dumps(res["why"]), json.dumps(res["poa"]),
         1 if res["abstain"] else 0, 1 if res["rail"] else 0,
         row["windows"] + 1, first_crit, case_id))
    c.commit()
    c.close()
    for ev, det in events:
        audit(case_id, ev, det)
    return first_crit


def get_case(case_id):
    c = conn()
    row = c.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def get_windows(case_id):
    c = conn()
    rows = c.execute("SELECT * FROM windows WHERE case_id=? ORDER BY idx",
                     (case_id,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def queue():
    c = conn()
    rows = c.execute(
        "SELECT * FROM cases WHERE status='OPEN' ORDER BY svi DESC, id DESC"
    ).fetchall()
    c.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("subflags", "why", "poa"):
            d[k] = json.loads(d[k])
        out.append(d)
    return out


def act(case_id, action):
    c = conn()
    c.execute("UPDATE cases SET status=? WHERE id=?",
              ("ACTIONED" if action != "CLOSE" else "CLOSED", case_id))
    c.commit()
    c.close()
    audit(case_id, "COUNSELLOR_ACTION", action)


def escalate(case_id):
    c = conn()
    c.execute("UPDATE cases SET escalated=1 WHERE id=?", (case_id,))
    c.commit()
    c.close()
    audit(case_id, "AUTO_ESCALATED",
          "SLA breached - auto-bumped to SUPERVISOR queue")


def recent_audit(limit=8):
    c = conn()
    rows = c.execute(
        "SELECT a.*, cases.token FROM audit a JOIN cases ON cases.id=a.case_id "
        "ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def seed_repeat_history():
    """Pre-seed 2 closed sessions for the repeat-caller trajectory demo."""
    from .scenarios import REPEAT_HISTORY
    created = []
    for i, h in enumerate(REPEAT_HISTORY):
        c = conn()
        tok = "SVA-REPEAT-%d" % (i + 1)
        cur = c.execute(
            "INSERT INTO cases(token,language,created_at,status,tier,svi,"
            "windows,repeat_calls) VALUES(?,?,?,?,?,?,?,?)",
            (tok, "Hinglish", now() - (4 - i * 2) * 86400, "CLOSED",
             h["tier"], h["svi"], 3, i + 1))
        cid = cur.lastrowid
        c.commit()
        c.close()
        audit(cid, "HISTORY", h["note"])
        created.append(cid)
    return created

"""SQLite schema and async helpers."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

DB_PATH = os.getenv("DATABASE_PATH", "./data/remediation.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_number INTEGER NOT NULL,
    issue_url TEXT NOT NULL,
    playbook TEXT NOT NULL,
    devin_session_id TEXT UNIQUE,
    devin_session_url TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    pr_url TEXT,
    pr_number INTEGER,
    acu_spent REAL DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    idempotency_key TEXT UNIQUE,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS pr_quality_scores (
    pr_url TEXT PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    correctness REAL,
    scope_discipline REAL,
    no_regression REAL,
    acceptance_criteria REAL,
    pr_hygiene REAL,
    total_score REAL,
    graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budget (
    date DATE PRIMARY KEY,
    acu_spent REAL DEFAULT 0,
    acu_budget REAL NOT NULL
);
"""


def _ensure_db_dir() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    _ensure_db_dir()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_conn():
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── sessions ─────────────────────────────────────────────────────────────────

def create_session(
    issue_number: int,
    issue_url: str,
    playbook: str,
    idempotency_key: str,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sessions (issue_number, issue_url, playbook, idempotency_key, status)
               VALUES (?, ?, ?, ?, 'queued')""",
            (issue_number, issue_url, playbook, idempotency_key),
        )
        return cur.lastrowid


def update_session(session_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [session_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE sessions SET {cols} WHERE id = ?", vals)


def get_session_by_id(session_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def get_session_by_idempotency_key(key: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE idempotency_key = ?", (key,)
        ).fetchone()


def get_running_sessions() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE status IN ('queued', 'running', 'pr_opened', 'ci_failed_retrying')"
        ).fetchall()


def get_all_sessions() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC"
        ).fetchall()


# ── events ────────────────────────────────────────────────────────────────────

def log_event(session_id: int | None, event_type: str, payload: Any = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (session_id, event_type, payload) VALUES (?, ?, ?)",
            (session_id, event_type, json.dumps(payload) if payload else None),
        )


def get_events_for_session(session_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()


# ── budget ────────────────────────────────────────────────────────────────────

def get_or_create_budget(budget_limit: float) -> sqlite3.Row:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM budget WHERE date = ?", (today,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO budget (date, acu_spent, acu_budget) VALUES (?, 0, ?)",
                (today, budget_limit),
            )
            row = conn.execute("SELECT * FROM budget WHERE date = ?", (today,)).fetchone()
        return row


def add_acu_spent(amount: float) -> None:
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE budget SET acu_spent = acu_spent + ? WHERE date = ?",
            (amount, today),
        )


# ── quality scores ────────────────────────────────────────────────────────────

def upsert_quality_score(pr_url: str, session_id: int, scores: dict[str, float]) -> None:
    total = sum(
        scores.get(k, 0) * w
        for k, w in [
            ("correctness", 0.30),
            ("scope_discipline", 0.20),
            ("no_regression", 0.20),
            ("acceptance_criteria", 0.20),
            ("pr_hygiene", 0.10),
        ]
    )
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO pr_quality_scores
               (pr_url, session_id, correctness, scope_discipline, no_regression,
                acceptance_criteria, pr_hygiene, total_score, graded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(pr_url) DO UPDATE SET
               correctness=excluded.correctness,
               scope_discipline=excluded.scope_discipline,
               no_regression=excluded.no_regression,
               acceptance_criteria=excluded.acceptance_criteria,
               pr_hygiene=excluded.pr_hygiene,
               total_score=excluded.total_score,
               graded_at=excluded.graded_at""",
            (
                pr_url, session_id,
                scores.get("correctness"), scores.get("scope_discipline"),
                scores.get("no_regression"), scores.get("acceptance_criteria"),
                scores.get("pr_hygiene"), total,
            ),
        )


def get_all_quality_scores() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pr_quality_scores ORDER BY graded_at DESC"
        ).fetchall()

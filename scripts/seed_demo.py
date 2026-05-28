"""Seed the SQLite DB with realistic mock data so reviewers can explore the dashboard
without needing real Devin credits."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import random
import sqlite3
from datetime import datetime, timedelta

from app.db import DB_PATH, init_db, upsert_quality_score

PLAYBOOKS = ["dependency_upgrade", "type_hints"]
STATUSES = ["ci_passed", "ci_passed", "ci_passed", "failed", "running", "pr_opened", "budget_killed"]

MOCK_PACKAGES = [
    ("cryptography", "41.0.0", "42.0.4", "CVE-2023-49083"),
    ("pillow", "9.5.0", "10.3.0", "CVE-2023-50447"),
    ("aiohttp", "3.8.4", "3.9.4", "CVE-2024-23334"),
    ("sqlalchemy", "1.4.46", "2.0.29", "CVE-2023-30534"),
    ("werkzeug", "2.3.3", "3.0.3", "CVE-2024-34069"),
    ("jinja2", "3.1.2", "3.1.4", "CVE-2024-34064"),
    ("requests", "2.28.2", "2.31.0", "CVE-2023-32681"),
    ("pyyaml", "5.4.1", "6.0.1", "CVE-2022-1471"),
]

MOCK_FUNCS = [
    ("superset/utils/core.py", "parse_human_datetime"),
    ("superset/utils/decorators.py", "transaction"),
    ("superset/db_engine_specs/base.py", "get_schema_names"),
    ("superset/utils/log.py", "get_logger"),
]


def _ts(days_ago: float, hours_offset: float = 0) -> str:
    t = datetime.utcnow() - timedelta(days=days_ago, hours=hours_offset)
    return t.strftime("%Y-%m-%d %H:%M:%S")


def seed():
    init_db()
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM pr_quality_scores")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM budget")
        conn.commit()

    with sqlite3.connect(DB_PATH) as conn:
        # Budget entries for the last 7 days
        for i in range(7):
            date_str = (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
            spent = round(random.uniform(8, 35), 1)
            conn.execute(
                "INSERT OR IGNORE INTO budget (date, acu_spent, acu_budget) VALUES (?, ?, 50)",
                (date_str, spent),
            )

        session_ids = []
        for i, (pkg, cur, fix, cve) in enumerate(MOCK_PACKAGES):
            days_ago = random.uniform(0.2, 7)
            status = random.choice(STATUSES)
            retry = 0 if "passed" in status else random.randint(0, 2)
            acu = round(random.uniform(1.5, 9.5), 2)
            pr_num = 100 + i
            pr_url = f"https://github.com/prakhar/superset-fork/pull/{pr_num}" if status != "failed" else None

            conn.execute(
                """INSERT INTO sessions
                   (issue_number, issue_url, playbook, devin_session_id, devin_session_url,
                    status, pr_url, pr_number, acu_spent, retry_count, idempotency_key, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    i + 1,
                    f"https://github.com/prakhar/superset-fork/issues/{i+1}",
                    "dependency_upgrade",
                    f"devin-sess-{i:04d}",
                    f"https://app.devin.ai/sessions/devin-sess-{i:04d}",
                    status,
                    pr_url,
                    pr_num if pr_url else None,
                    acu,
                    retry,
                    f"issue-{i+1}-attempt-0",
                    _ts(days_ago),
                    _ts(days_ago, -2) if status in ("ci_passed", "failed") else None,
                ),
            )
            sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            session_ids.append((sid, status, pr_url, pr_num))

            # Events
            for etype, ts_offset in [
                ("issue_received", 0),
                ("session_created", -0.1),
                ("session_completed", -1),
            ]:
                conn.execute(
                    "INSERT INTO events (session_id, event_type, created_at) VALUES (?, ?, ?)",
                    (sid, etype, _ts(days_ago, ts_offset)),
                )
            if retry > 0:
                conn.execute(
                    "INSERT INTO events (session_id, event_type, created_at) VALUES (?, 'ci_feedback_sent', ?)",
                    (sid, _ts(days_ago, -1.5)),
                )

        # Type-hint sessions
        for i, (fpath, fname) in enumerate(MOCK_FUNCS):
            days_ago = random.uniform(0.5, 5)
            status = random.choice(["ci_passed", "ci_passed", "running"])
            acu = round(random.uniform(0.8, 3.5), 2)
            pr_num = 200 + i
            pr_url = f"https://github.com/prakhar/superset-fork/pull/{pr_num}" if status == "ci_passed" else None

            conn.execute(
                """INSERT INTO sessions
                   (issue_number, issue_url, playbook, devin_session_id, devin_session_url,
                    status, pr_url, pr_number, acu_spent, retry_count, idempotency_key, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (
                    50 + i,
                    f"https://github.com/prakhar/superset-fork/issues/{50+i}",
                    "type_hints",
                    f"devin-type-{i:04d}",
                    f"https://app.devin.ai/sessions/devin-type-{i:04d}",
                    status,
                    pr_url,
                    pr_num if pr_url else None,
                    acu,
                    f"issue-{50+i}-attempt-0",
                    _ts(days_ago),
                ),
            )
            sid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            session_ids.append((sid, status, pr_url, pr_num))

        conn.commit()

    # Quality scores for completed PRs
    with sqlite3.connect(DB_PATH) as conn:
        for sid, status, pr_url, pr_num in session_ids:
            if status == "ci_passed" and pr_url:
                scores = {
                    "correctness": round(random.uniform(0.5, 1.0), 1),
                    "scope_discipline": round(random.uniform(0.6, 1.0), 1),
                    "no_regression": round(random.uniform(0.7, 1.0), 1),
                    "acceptance_criteria": round(random.uniform(0.5, 1.0), 1),
                    "pr_hygiene": round(random.uniform(0.6, 1.0), 1),
                }
                upsert_quality_score(pr_url, sid, scores)

    print(f"Seeded {DB_PATH} with mock data.")
    print("Run: streamlit run dashboard/app.py")


if __name__ == "__main__":
    seed()

"""Manually import a Devin session into the local DB.

Usage:
    python scripts/import_session.py <devin_session_id> [--issue 28] [--playbook dep-upgrade]

Use this when a Devin session was started outside the orchestrator (e.g. directly
in the Devin UI) and you want it tracked in the dashboard.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import get_conn, init_db
from app.devin_client import DevinClient, SessionStatus


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Devin session into the Autopatch DB")
    parser.add_argument("session_id", help="Devin session ID (e.g. ses_abc123)")
    parser.add_argument("--issue", type=int, default=0, help="GitHub issue number (default 0)")
    parser.add_argument("--issue-url", default="", help="GitHub issue URL")
    parser.add_argument(
        "--playbook",
        default="dep-upgrade",
        choices=["dep-upgrade", "type-hints"],
        help="Playbook type (default: dep-upgrade)",
    )
    args = parser.parse_args()

    client = DevinClient(
        api_key=settings.devin_api_key,
        service_key=settings.devin_service_key,
        org_id=settings.devin_org_id,
        acu_usd_rate=settings.acu_usd_rate,
    )

    print(f"Fetching session {args.session_id} from Devin API...")
    try:
        ds = client.get_session(args.session_id)
    except Exception as exc:
        print(f"Error fetching session: {exc}")
        sys.exit(1)

    print(f"  status : {ds.status}")
    print(f"  url    : {ds.url}")
    print(f"  pr_url : {ds.pr_url}")
    print(f"  acus   : {ds.acu_consumed}")

    issue_url = args.issue_url or (
        f"https://github.com/{settings.github_owner}/{settings.github_repo}/issues/{args.issue}"
        if args.issue
        else "https://github.com/manual"
    )
    playbook_label = f"playbook:{args.playbook}"
    idempotency_key = f"manual-import-{args.session_id}"

    # Map Devin status → local status
    status_map = {
        SessionStatus.QUEUED: "queued",
        SessionStatus.RUNNING: "running",
        SessionStatus.BLOCKED: "running",
        SessionStatus.SUSPENDED: "running",
        SessionStatus.COMPLETED: "completed",
        SessionStatus.STOPPED: "completed",
        SessionStatus.ABANDONED: "abandoned",
    }
    local_status = status_map.get(ds.status, "running")
    if ds.pr_url:
        local_status = "pr_opened"

    init_db()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM sessions WHERE devin_session_id = ?", (args.session_id,)
        ).fetchone()
        if existing:
            print(f"\nSession already in DB (id={existing['id']}). Updating...")
            conn.execute(
                """UPDATE sessions SET
                   status = ?,
                   devin_session_url = ?,
                   pr_url = ?,
                   acu_spent = ?
                   WHERE devin_session_id = ?""",
                (local_status, ds.url, ds.pr_url, ds.acu_consumed, args.session_id),
            )
            print("Updated.")
        else:
            cur = conn.execute(
                """INSERT INTO sessions
                   (issue_number, issue_url, playbook, idempotency_key,
                    devin_session_id, devin_session_url, status, pr_url, acu_spent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    args.issue,
                    issue_url,
                    playbook_label,
                    idempotency_key,
                    args.session_id,
                    ds.url,
                    local_status,
                    ds.pr_url,
                    ds.acu_consumed,
                ),
            )
            print(f"\nInserted as session id={cur.lastrowid}")

    # Try to fetch cost
    cost = client.get_session_cost(args.session_id)
    if cost and cost["acus"] > 0:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE devin_session_id = ?", (args.session_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sessions SET acu_spent = ? WHERE id = ?",
                    (cost["acus"], row["id"]),
                )
        print(f"Cost synced: {cost['acus']:.2f} ACU (${cost['usd']:.2f})")
    else:
        print("Cost not available from API (session may still be running).")

    print("\nDone. Refresh the dashboard to see the session.")


if __name__ == "__main__":
    main()

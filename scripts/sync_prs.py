"""Sync PR URLs and merge status from GitHub into the sessions DB.

Devin opens PRs while its session is still running, so structured_output.pr_url
is not available yet. This script queries GitHub for all PRs (open + merged),
extracts the linked issue number from 'Closes #N', and updates matching sessions.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from app.config import settings
from app.db import get_conn, init_db


def run() -> None:
    init_db()

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }
    resp = httpx.get(
        f"https://api.github.com/repos/{settings.github_owner}/{settings.github_repo}/pulls",
        headers=headers,
        params={"state": "all", "per_page": 50},
    )
    resp.raise_for_status()
    prs = resp.json()

    updated = 0
    for pr in prs:
        body    = pr.get("body") or ""
        pr_url  = pr["html_url"]
        merged  = pr.get("merged_at") is not None
        closed  = pr["state"] == "closed" and not merged  # closed without merge

        new_status = "merged" if merged else ("pr_opened" if pr["state"] == "open" else None)
        if new_status is None:
            continue

        matches = re.findall(r"(?:Closes|Fixes|Resolves)\s+#(\d+)", body, re.IGNORECASE)
        for issue_str in matches:
            issue_number = int(issue_str)
            with get_conn() as c:
                row = c.execute(
                    "SELECT id, status FROM sessions WHERE issue_number = ?", (issue_number,)
                ).fetchone()
                if row and row["status"] != new_status:
                    c.execute(
                        "UPDATE sessions SET pr_url = ?, status = ? WHERE id = ?",
                        (pr_url, new_status, row["id"]),
                    )
                    print(f"  Issue #{issue_number} → {new_status} ({pr_url})")
                    updated += 1

    print(f"Synced {updated} session(s).")


if __name__ == "__main__":
    run()

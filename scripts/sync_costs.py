"""Sync per-session ACU costs from Devin's v3 API into the DB.

Primary path: GET /v3/organizations/{org_id}/consumption/daily/sessions/{session_id}
Requires DEVIN_SERVICE_KEY (cog_ prefix) with ManageBilling org permission in .env.

Fallback: if the service key is absent, matches session titles from the Devin API
against COST_TABLE below (title substring → cost in USD), then converts to ACU.

To add missing costs manually: scroll app.devin.ai/usage → Usage History and add
entries to COST_TABLE (title substring → cost in USD).

Usage:
    python scripts/sync_costs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import get_conn, init_db, set_session_acu
from app.devin_client import DevinClient

COST_PER_ACU = settings.acu_usd_rate  # $/ACU from .env (ACU_USD_RATE), default 2.25

# Fallback title substring (lowercase) → cost in USD
# Read from: app.devin.ai → Usage & Limits → Usage History
COST_TABLE: dict[str, float] = {
    "add type hints (#27)":            2.73,
    "add type hints for superset#26":  3.04,
    "add type hints to (#25)":         5.63,
    "add type hints for superset#24":  6.66,
    "add type hints for superset#22":  3.53,
    "add type hints (#23)":            2.53,
    "cve-2026-44432":                  2.66,   # urllib3
    "cve-2026-25087":                  2.54,   # pyarrow
    "cve-2026-44307":                  2.42,   # mako
    "cve-2026-45409":                  0.0,    # idna — add real cost when visible
    "cve-2026-27205":                  0.0,    # flask — add real cost when visible
    # Add more below as they appear in Usage History:
}


def _match_cost(title: str) -> float | None:
    tl = title.lower()
    for key, cost in COST_TABLE.items():
        if key in tl and cost > 0:
            return cost
    return None


def run() -> None:
    init_db()

    devin = DevinClient(
        settings.devin_api_key,
        service_key=settings.devin_service_key,
        org_id=settings.devin_org_id,
        acu_usd_rate=COST_PER_ACU,
    )

    use_api = bool(settings.devin_service_key and settings.devin_org_id)
    if use_api:
        print(f"Using v3 API (org={settings.devin_org_id})")
    else:
        print("No DEVIN_SERVICE_KEY set — falling back to COST_TABLE title matching.")
        print("Add DEVIN_SERVICE_KEY=cog_... to .env for automatic cost fetching.\n")

    with get_conn() as c:
        sessions = c.execute(
            "SELECT id, devin_session_id, acu_spent FROM sessions "
            "WHERE devin_session_id IS NOT NULL"
        ).fetchall()

    updated = skipped = no_match = 0

    for s in sessions:
        sid = s["devin_session_id"]
        current_acu = s["acu_spent"] or 0.0

        acus: float | None = None
        usd: float = 0.0
        source = ""

        if use_api:
            cost_data = devin.get_session_cost(sid)
            if cost_data is None:
                print(f"  API error or 403 for {sid[:30]}... — check service key permissions")
                skipped += 1
                continue
            if cost_data["acus"] > 0:
                acus   = cost_data["acus"]
                usd    = cost_data["usd"]
                source = "api"
            # API returned 0 (session suspended/not finalized) — fall through to COST_TABLE

        if acus is None:
            # Fetch session title for COST_TABLE matching
            import httpx
            try:
                r = httpx.get(
                    f"https://api.devin.ai/v1/sessions/{sid}",
                    headers={"Authorization": f"Bearer {settings.devin_api_key}"},
                    timeout=15,
                )
                title = r.json().get("title", "")
            except Exception:
                title = ""

            if not title:
                skipped += 1
                continue

            cost_usd = _match_cost(title)
            if cost_usd is None:
                print(f"  No cost match: \"{title}\"")
                no_match += 1
                continue

            acus   = round(cost_usd / COST_PER_ACU, 2)
            usd    = cost_usd
            source = "table"

        if acus == current_acu:
            continue

        set_session_acu(s["id"], acus)
        print(f"  [{source}] Session {s['id']} {sid[:28]}... → {acus:.2f} ACU (${usd:.2f})")
        updated += 1

    print(f"\nSynced costs for {updated} session(s). Skipped: {skipped}. No match: {no_match}.")
    if not use_api and no_match > 0:
        print("For unmatched sessions: scroll app.devin.ai/usage and add entries to COST_TABLE.")


if __name__ == "__main__":
    run()

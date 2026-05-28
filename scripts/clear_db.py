"""Clear all session/event data from the database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import get_conn, init_db


def run() -> None:
    init_db()
    with get_conn() as c:
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM events")
        c.execute("DELETE FROM budget")
        c.execute("DELETE FROM pr_quality_scores")
    print("Database cleared.")


if __name__ == "__main__":
    run()

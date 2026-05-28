REPO_PATH ?= /Users/prakhar/Desktop/Cognition/superset
MAX_ISSUES ?= 5
PORT      ?= 8080

# ── Dev servers ───────────────────────────────────────────────────────────────
api:
	uvicorn app.main:app --reload --port $(PORT)

dashboard:
	streamlit run dashboard/app.py

# ── Scanners ──────────────────────────────────────────────────────────────────
scan:
	python scripts/scan_cves.py --repo-path $(REPO_PATH) --max-issues $(MAX_ISSUES)

scan-dry:
	python scripts/scan_cves.py --repo-path $(REPO_PATH) --max-issues $(MAX_ISSUES) --dry-run

scan-quality:
	python scripts/scan_quality.py --repo-path $(REPO_PATH)

# ── Database ──────────────────────────────────────────────────────────────────
seed:
	python scripts/seed_demo.py

clear-db:
	python scripts/clear_db.py

# ── Issues ────────────────────────────────────────────────────────────────────
sync-prs:
	python scripts/sync_prs.py

sync-costs:
	python scripts/sync_costs.py

close-issues:
	python scripts/close_issues.py

# ── Full reset (close issues + clear db + rescan) ────────────────────────────
reset: close-issues clear-db
	python scripts/scan_cves.py --repo-path $(REPO_PATH) --max-issues $(MAX_ISSUES)

# ── Docker ───────────────────────────────────────────────────────────────────
docker-up:
	docker compose up --build -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

.PHONY: api dashboard scan scan-dry scan-quality seed clear-db sync-prs sync-costs close-issues reset docker-up docker-down docker-logs

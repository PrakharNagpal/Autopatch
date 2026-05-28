# Autopatch

> An event-driven platform that autonomously closes dependency CVEs using Devin as the AI worker — with a self-correcting CI feedback loop and an observability dashboard.

---

## What It Does

Apache Superset has hundreds of open dependency CVEs. This system closes them autonomously:

1. A scanner finds vulnerable packages and opens GitHub issues on your fork
2. The orchestrator dispatches each issue to Devin via its API
3. Devin opens a PR with the fix
4. If CI fails, the engine sends Devin the failure logs and it retries (up to 2×)
5. A Streamlit dashboard tracks sessions, cost, and PR quality in real time

```
GitHub Issue (labeled devin-remediate)
       │
       ▼
 Eligibility Gate ──► skip + comment if ineligible
       │
       ▼
 Playbook Router (dep-upgrade | type-hints)
       │
       ▼
 Devin API → opens PR on your superset fork
       │
       ├── CI passes ──► mark ci_passed, grade PR
       │
       └── CI fails  ──► send logs to Devin → retry (max 2×)
```

---

## Prerequisites

| Requirement | Details |
|---|---|
| Docker + Docker Compose | v24+ recommended |
| Devin account | Personal API key from [app.devin.ai](https://app.devin.ai/settings/api-keys) |
| GitHub PAT | Scopes: `repo`, `issues`, `pull_requests` |
| Superset fork | A fork of [apache/superset](https://github.com/apache/superset) under your GitHub account |

---

## Installation

### Option A — Docker (recommended)

```bash
# 1. Clone the repo
git clone https://github.com/PrakharNagpal/Autopatch
cd Autopatch

# 2. Configure environment
cp .env.example .env
```

Edit `.env` and fill in:

```env
DEVIN_API_KEY=apk_user_...        # from app.devin.ai/settings/api-keys
GITHUB_TOKEN=github_pat_...       # PAT with repo + issues + pull_requests
GITHUB_OWNER=your-github-username
GITHUB_REPO=superset              # name of your fork
DAILY_ACU_BUDGET=50
PER_SESSION_ACU_CAP=10

# Absolute path to your local superset fork — Docker mounts this at /superset
SUPERSET_REPO_PATH=/path/to/your/superset-fork
```

```bash
# 3. Start both services (API + Dashboard)
docker compose up --build -d

# 4. Verify
curl http://localhost:8080/health   # → {"status":"ok"}
open http://localhost:8501          # Streamlit dashboard
```

To stop: `docker compose down`  
To tail logs: `docker compose logs -f`

---

### Option B — Local Python

```bash
# 1. Clone and install
git clone https://github.com/PrakharNagpal/Autopatch
cd Autopatch
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# fill in .env — same fields as Docker above, including SUPERSET_REPO_PATH

# 3. Start the API server
uvicorn app.main:app --reload --port 8080

# 4. In a second terminal, start the dashboard
streamlit run dashboard/app.py

# Dashboard → http://localhost:8501
# API       → http://localhost:8080
```

---

## Simulating the Workflow (No Webhook Required)

You can trigger the full remediation loop without setting up a webhook:

### Step 1 — Scan for CVEs

Use the **Overview tab → CVE Scan** button in the dashboard, or run:

```bash
python scripts/scan_cves.py --repo-path /path/to/your/superset-fork --max-issues 5
```

This scans `requirements/*.txt` via the [OSV API](https://osv.dev), opens GitHub issues on your fork labeled `devin-remediate`, and the API poller picks them up automatically.

### Step 2 — Watch Devin Work

The API server polls Devin every 30 seconds. Open the **Sessions tab** in the dashboard to track status in real time.

### Step 3 — Sync PR URLs

Once Devin opens PRs, run:

```bash
python scripts/sync_prs.py
# or click "Sync PRs" in Controls tab
```

### Step 4 — Sync Costs

```bash
python scripts/sync_costs.py
# or click "Sync Costs" in Controls tab / Cost tab
```

### Optional — Seed Demo Data

To preview the dashboard without any API keys:

```bash
python scripts/seed_demo.py
streamlit run dashboard/app.py
```

---

## Webhook Setup (for live CI feedback)

To enable the CI retry loop (Devin re-fixing PRs when CI fails), register the webhook on your fork:

```bash
# Expose your local API with ngrok
ngrok http 8080

# Register in your fork: GitHub → Settings → Webhooks → Add webhook
# Payload URL:   https://<ngrok-id>.ngrok.io/webhook/github
# Content type:  application/json
# Events:        Issues, Check runs
```

In Docker, point the webhook at your server's public IP on port 8080.

---

## Issues Remediated

| Issue | CVE | Package | PR | Status |
|---|---|---|---|---|
| [#12](https://github.com/PrakharNagpal/superset/issues/12) | CVE-2026-27205 | flask | [#19](https://github.com/PrakharNagpal/superset/pull/19) | PR opened |
| [#13](https://github.com/PrakharNagpal/superset/issues/13) | CVE-2026-45409 | idna | [#21](https://github.com/PrakharNagpal/superset/pull/21) | Merged |
| [#14](https://github.com/PrakharNagpal/superset/issues/14) | CVE-2026-44307 | mako | [#17](https://github.com/PrakharNagpal/superset/pull/17) | PR opened |
| [#15](https://github.com/PrakharNagpal/superset/issues/15) | CVE-2026-25087 | pyarrow | [#20](https://github.com/PrakharNagpal/superset/pull/20) | PR opened |
| [#16](https://github.com/PrakharNagpal/superset/issues/16) | CVE-2026-44432 | urllib3 | [#18](https://github.com/PrakharNagpal/superset/pull/18) | PR opened |
| [#22](https://github.com/PrakharNagpal/superset/issues/22) | — | type-hints (superset/utils) | — | In progress |
| [#23](https://github.com/PrakharNagpal/superset/issues/23) | — | type-hints (superset/utils) | — | In progress |
| [#24](https://github.com/PrakharNagpal/superset/issues/24) | — | type-hints (superset/utils) | — | In progress |
| [#25](https://github.com/PrakharNagpal/superset/issues/25) | — | type-hints (superset/utils) | — | In progress |
| [#26](https://github.com/PrakharNagpal/superset/issues/26) | — | type-hints (superset/utils) | — | In progress |
| [#27](https://github.com/PrakharNagpal/superset/issues/27) | — | type-hints (superset/utils) | — | In progress |

---

## Architecture

```
Autopatch/
├── app/
│   ├── main.py              # FastAPI — webhooks, health, metrics
│   ├── orchestrator.py      # Eligibility gate, dispatch, polling, CI loop
│   ├── devin_client.py      # Devin API wrapper (retry, idempotency, cost)
│   ├── github_client.py     # GitHub API wrapper
│   ├── db.py                # SQLite schema + helpers
│   └── config.py            # Pydantic settings (loaded from .env)
├── playbooks/
│   ├── base.py              # Abstract Playbook interface
│   ├── dependency_upgrade.py
│   ├── type_hints.py
│   └── registry.py          # Label → Playbook mapping
├── dashboard/
│   └── app.py               # Streamlit — Overview, Throughput, Cost, Sessions, Controls
├── evals/
│   └── grader.py            # PR quality scorer (5 dimensions)
├── scripts/
│   ├── scan_cves.py          # pip-audit + OSV API → GitHub issues
│   ├── scan_quality.py       # mypy → GitHub issues
│   ├── sync_prs.py           # Backfill PR URLs from GitHub
│   ├── sync_costs.py         # Pull ACU costs from Devin API
│   └── seed_demo.py          # Mock data for dashboard preview
├── Dockerfile.api
├── Dockerfile.dashboard
├── docker-compose.yml
└── .env.example
```

### Key Design Decisions

- **SQLite over Postgres** — zero infrastructure, single volume mount, trivial to inspect
- **APScheduler inside FastAPI** — no separate worker process needed for polling
- **Idempotency keys** — prevents duplicate Devin sessions if a webhook fires twice
- **Playbook pattern** — adding a new remediation type is a single file with 4 methods
- **Cost tracking** — Devin v3 API for ACU data; COST_TABLE fallback for suspended sessions

---

## Playbooks

| Label | File | What Devin does |
|---|---|---|
| `playbook:dep-upgrade` | [dependency_upgrade.py](playbooks/dependency_upgrade.py) | Bumps the vulnerable package across all requirements files, runs pip-audit to confirm fixed |
| `playbook:type-hints` | [type_hints.py](playbooks/type_hints.py) | Adds type annotations to flagged functions, runs mypy --strict |

### Adding a New Playbook

1. Create `playbooks/your_playbook.py` extending `Playbook` (see [base.py](playbooks/base.py))
2. Implement `eligibility_check`, `render_prompt`, `acceptance_criteria`, `on_ci_failure`
3. Register in [registry.py](playbooks/registry.py): `REGISTRY["playbook:your-label"] = YourPlaybook()`
4. Create the GitHub label `playbook:your-label` on your fork

The orchestrator, webhook handler, and dashboard pick it up automatically.

---

## Dashboard Tabs

| Tab | Contents |
|---|---|
| **Overview** | CVE scan controls, KPIs (CVEs closed, avg cost/PR, eng. time saved), weekly PR chart |
| **Throughput** | CI pass rate, first-try pass rate, session funnel, quality scores |
| **Cost** | Daily budget burn-down, total ACU spend, cost by playbook, Sync Costs button |
| **Sessions** | Full session table, per-session drill-down, manual ACU entry, event timeline |
| **Controls** | Daily budget cap, Sync PRs, maintenance (close issues, clear DB, seed demo) |

---

## Superset Fork

Autopatch operates against a fork of Apache Superset:  
**[github.com/PrakharNagpal/superset](https://github.com/PrakharNagpal/superset)**

Original repository: [github.com/apache/superset](https://github.com/apache/superset)

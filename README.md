# Devin CVE Remediation Engine

> An event-driven platform that autonomously closes dependency CVEs using Devin as the AI worker — with a self-correcting CI feedback loop and a quality-graded observability layer.

## The Problem

Apache Superset has **600+ open dependency CVEs** tracked in [issue #20994](https://github.com/apache/superset/issues/20994). Maintainers don't have bandwidth. Issue [#30908](https://github.com/apache/superset/issues/30908) was closed as "not planned." This system closes them autonomously.

## The Solution

```
GitHub Issue (labeled devin-remediate)
       │
       ▼
 Eligibility Gate ──► skip + comment if ineligible
       │
       ▼
 Playbook Router (dep-upgrade | type-hints | ...)
       │
       ▼
 Devin API → opens PR on superset-fork
       │
       ├── CI passes ──► mark ci_passed, grade PR
       │
       └── CI fails ──► send follow-up message → Devin fixes → retry (max 2×)
```

## Quickstart

```bash
# 1. Clone and configure
cp .env.template .env
# Fill in DEVIN_API_KEY, GITHUB_TOKEN, GITHUB_OWNER

# 2. Seed the dashboard with mock data (no credits needed)
pip install -r requirements.txt
python scripts/seed_demo.py

# 3. Launch dashboard
streamlit run dashboard/app.py
# → http://localhost:8501

# 4. (Optional) Run with Docker
docker compose up
# API → http://localhost:8000
# Dashboard → http://localhost:8501
```

## Live Run Against Your Fork

```bash
# Point scanners at your superset fork
python scripts/scan_cves.py --repo-path /path/to/superset-fork
python scripts/scan_quality.py --repo-path /path/to/superset-fork

# Start the API (receives GitHub webhooks)
uvicorn app.main:app --reload

# Expose locally (for webhook registration)
ngrok http 8000
# Register https://<ngrok>/webhook/github in your fork's GitHub Settings > Webhooks
```

## How Each Playbook Works

| Label | Playbook | What Devin does |
|---|---|---|
| `playbook:dep-upgrade` | [dependency_upgrade.py](playbooks/dependency_upgrade.py) | Bumps package in all requirements files, runs pip-audit + pytest, migrates call sites if major-version bump |
| `playbook:type-hints` | [type_hints.py](playbooks/type_hints.py) | Adds type annotations to flagged functions, runs mypy --strict |

### Adding a Third Playbook

1. Create `playbooks/your_playbook.py` extending `Playbook` (see [base.py](playbooks/base.py))
2. Implement `eligibility_check`, `render_prompt`, `acceptance_criteria`, `on_ci_failure`
3. Register in [registry.py](playbooks/registry.py): `REGISTRY["playbook:your-label"] = YourPlaybook()`
4. Create the GitHub label `playbook:your-label` in your fork
5. Done — the orchestrator, webhook, and dashboard pick it up automatically

## The Evaluation Harness

Every Devin-opened PR gets a quality score across 5 dimensions:

| Dimension | Weight | How measured |
|---|---|---|
| Correctness | 30% | CI pass on first try (1.0) / eventual pass (0.7) / never (0.0) |
| Scope discipline | 20% | Files touched vs. expected count |
| No regression | 20% | No `@pytest.mark.skip` added, test count unchanged |
| Acceptance criteria | 20% | Each checkbox from issue body verified programmatically |
| PR hygiene | 10% | Title format, body links, labels applied |

See [evals/grader.py](evals/grader.py).

## Architecture

```
devin-remediation-engine/
├── app/
│   ├── main.py           # FastAPI — webhooks, health, metrics
│   ├── orchestrator.py   # Eligibility + dispatch + polling + CI loop
│   ├── devin_client.py   # Devin API wrapper (retry, idempotency, logging)
│   ├── github_client.py  # GitHub API wrapper
│   ├── db.py             # SQLite schema + helpers
│   └── config.py         # Pydantic settings
├── playbooks/
│   ├── base.py           # Abstract Playbook interface
│   ├── dependency_upgrade.py
│   ├── type_hints.py
│   └── registry.py       # Label → Playbook mapping
├── dashboard/
│   └── app.py            # Streamlit (4 tabs)
├── evals/
│   └── grader.py         # PR quality scorer
└── scripts/
    ├── scan_cves.py       # pip-audit + OSV API → GH issues
    ├── scan_quality.py    # mypy → GH issues
    └── seed_demo.py       # Mock data for dashboard preview
```

## Roadmap

- **Slack approval gate** — require human approval before merging major-version bumps
- **Multi-repo fan-out** — run the same playbooks across a portfolio of repos
- **Learning loop** — feed rejected PRs back as negative examples to improve prompts
- **SLA dashboards** — track time-to-close by severity, flag breached SLAs

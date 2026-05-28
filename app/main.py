"""FastAPI entrypoint: webhooks, health, metrics, and manual triggers."""

import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_all_sessions, get_all_quality_scores, get_or_create_budget, init_db, log_event
from app.orchestrator import handle_ci_result, handle_new_issue, poll_running_sessions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(poll_running_sessions, "interval", seconds=30, id="poller")
    scheduler.start()
    logger.info("startup complete")
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Devin Remediation Engine", lifespan=lifespan)


# ── HMAC verification ─────────────────────────────────────────────────────────

def _verify_github_signature(body: bytes, signature_header: str | None) -> bool:
    if not settings.github_webhook_secret:
        return True  # skip verification in dev if secret not set
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ── GitHub issue webhook ──────────────────────────────────────────────────────

@app.post("/webhook/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not _verify_github_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = json.loads(body)

    log_event(None, f"webhook_{event}", {"action": payload.get("action")})

    if event == "issues" and payload.get("action") == "opened":
        background_tasks.add_task(handle_new_issue, payload["issue"])

    elif event == "issues" and payload.get("action") == "labeled":
        # Also handle issues that get the trigger label added after creation
        issue = payload["issue"]
        added_label = payload.get("label", {}).get("name", "")
        if added_label == "devin-remediate":
            background_tasks.add_task(handle_new_issue, issue)

    elif event == "check_run" and payload.get("action") == "completed":
        check_run = payload["check_run"]
        pr_urls = [
            pr["html_url"]
            for pr in check_run.get("pull_requests", [])
        ]
        conclusion = check_run.get("conclusion", "")
        passed = conclusion == "success"
        for pr_url in pr_urls:
            background_tasks.add_task(handle_ci_result, pr_url, passed, "")

    return {"ok": True}


# ── Manual triggers ───────────────────────────────────────────────────────────

@app.post("/trigger/scan")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Manually kick off the CVE and quality scanners."""
    from scripts.scan_cves import run as run_cve_scan
    from scripts.scan_quality import run as run_quality_scan
    background_tasks.add_task(run_cve_scan)
    background_tasks.add_task(run_quality_scan)
    return {"queued": ["cve_scan", "quality_scan"]}


@app.post("/trigger/poll")
async def trigger_poll(background_tasks: BackgroundTasks):
    background_tasks.add_task(poll_running_sessions)
    return {"queued": "poll"}


# ── Observability ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    sessions = get_all_sessions()
    budget = get_or_create_budget(settings.daily_acu_budget)
    by_status: dict[str, int] = {}
    for s in sessions:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    return {
        "sessions_total": len(sessions),
        "sessions_by_status": by_status,
        "budget_today": {
            "spent": budget["acu_spent"],
            "limit": budget["acu_budget"],
            "remaining": budget["acu_budget"] - budget["acu_spent"],
        },
    }


@app.get("/sessions")
async def list_sessions():
    return [dict(s) for s in get_all_sessions()]


@app.get("/quality")
async def list_quality():
    return [dict(s) for s in get_all_quality_scores()]

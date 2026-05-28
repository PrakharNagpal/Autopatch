"""Eligibility gate, dispatch, background poller, and CI feedback loop."""

import logging
from typing import Any

from app.config import settings
from app.db import (
    add_acu_spent,
    create_session,
    get_or_create_budget,
    get_running_sessions,
    get_session_by_idempotency_key,
    log_event,
    update_session,
)
from app.devin_client import DevinClient, SessionStatus
from app.github_client import GitHubClient
from playbooks.registry import get_playbook

logger = logging.getLogger(__name__)

MAX_CI_RETRIES = 2


def _make_idempotency_key(issue_number: int, attempt: int) -> str:
    return f"issue-{issue_number}-attempt-{attempt}"


def _get_clients() -> tuple[DevinClient, GitHubClient]:
    return (
        DevinClient(settings.devin_api_key),
        GitHubClient(settings.github_token, settings.github_owner, settings.github_repo),
    )


def handle_new_issue(issue: dict[str, Any]) -> None:
    """Entry point called when a new labeled issue arrives via webhook."""
    issue_number = issue["number"]
    issue_url = issue["html_url"]
    labels = [l["name"] for l in issue.get("labels", [])]

    if "devin-remediate" not in labels:
        return

    playbook = get_playbook(labels)
    if not playbook:
        logger.info("orchestrator no_playbook issue=%d labels=%s", issue_number, labels)
        return

    # Idempotency — never dispatch the same issue twice
    idem_key = _make_idempotency_key(issue_number, attempt=0)
    if get_session_by_idempotency_key(idem_key):
        logger.info("orchestrator duplicate_webhook issue=%d", issue_number)
        return

    # Eligibility
    eligibility = playbook.eligibility_check(issue)
    if not eligibility.eligible:
        logger.warning("orchestrator ineligible issue=%d reason=%s", issue_number, eligibility.reason)
        _, gh = _get_clients()
        gh.comment_on_issue(
            issue_number,
            f"⚠️ **Auto-remediation skipped:** {eligibility.reason}",
        )
        return

    # Budget check
    budget_row = get_or_create_budget(settings.daily_acu_budget)
    if budget_row["acu_spent"] >= budget_row["acu_budget"]:
        logger.warning("orchestrator budget_exhausted issue=%d", issue_number)
        _, gh = _get_clients()
        gh.comment_on_issue(
            issue_number,
            "⚠️ **Auto-remediation skipped:** daily ACU budget exhausted. Will retry tomorrow.",
        )
        return

    # Dispatch
    session_id = create_session(
        issue_number=issue_number,
        issue_url=issue_url,
        playbook=playbook.name,
        idempotency_key=idem_key,
    )
    log_event(session_id, "issue_received", {"issue_number": issue_number, "labels": labels})

    devin, _ = _get_clients()
    prompt = playbook.render_prompt(issue)
    try:
        devin_session = devin.create_session(prompt, idem_key)
        update_session(
            session_id,
            status="running",
            devin_session_id=devin_session.session_id,
            devin_session_url=devin_session.url,
        )
        log_event(session_id, "session_created", {"devin_session_id": devin_session.session_id})
        logger.info(
            "orchestrator dispatched issue=%d devin_session=%s",
            issue_number, devin_session.session_id,
        )
    except Exception as exc:
        update_session(session_id, status="failed", failure_reason=str(exc))
        log_event(session_id, "dispatch_failed", {"error": str(exc)})
        logger.error("orchestrator dispatch_failed issue=%d error=%s", issue_number, exc)


def handle_ci_result(pr_url: str, passed: bool, ci_logs: str = "") -> None:
    """Called when a CI check_run completes on a Devin-opened PR."""
    from app.db import get_all_sessions

    matching = [
        s for s in get_all_sessions()
        if s["pr_url"] == pr_url and s["status"] in ("pr_opened", "ci_failed_retrying")
    ]
    if not matching:
        return

    row = matching[0]
    session_id = row["id"]
    labels = []

    if passed:
        update_session(session_id, status="ci_passed")
        log_event(session_id, "ci_passed")
        logger.info("orchestrator ci_passed session=%d pr=%s", session_id, pr_url)
        return

    retry_count = row["retry_count"]
    if retry_count >= MAX_CI_RETRIES:
        update_session(session_id, status="failed", failure_reason="CI failed after max retries")
        log_event(session_id, "ci_max_retries_reached")
        logger.warning("orchestrator ci_max_retries session=%d", session_id)
        return

    # Send follow-up message to Devin
    playbook = _get_playbook_for_session(row)
    if not playbook or not row["devin_session_id"]:
        return

    message = playbook.on_ci_failure(row["devin_session_id"], ci_logs)
    devin, _ = _get_clients()
    try:
        devin.send_message(row["devin_session_id"], message)
        update_session(session_id, status="ci_failed_retrying", retry_count=retry_count + 1)
        log_event(session_id, "ci_feedback_sent", {"retry": retry_count + 1})
        logger.info("orchestrator ci_feedback_sent session=%d retry=%d", session_id, retry_count + 1)
    except Exception as exc:
        logger.error("orchestrator ci_feedback_error session=%d error=%s", session_id, exc)


def poll_running_sessions() -> None:
    """Background job: poll Devin for status updates on all active sessions."""
    sessions = get_running_sessions()
    if not sessions:
        return

    devin, gh = _get_clients()

    for row in sessions:
        if not row["devin_session_id"]:
            continue
        try:
            ds = devin.get_session(row["devin_session_id"])
            _process_session_update(row, ds, devin, gh)
        except Exception as exc:
            logger.error("orchestrator poll_error session=%d error=%s", row["id"], exc)


def _process_session_update(row, ds, devin: DevinClient, gh: GitHubClient) -> None:
    session_id = row["id"]
    acu_delta = ds.acu_consumed - (row["acu_spent"] or 0)
    if acu_delta > 0:
        add_acu_spent(acu_delta)

    # Budget kill switch
    if ds.acu_consumed >= (row["acu_spent"] or 0) + settings.per_session_acu_cap:
        devin.cancel_session(ds.session_id)
        update_session(
            session_id,
            status="budget_killed",
            acu_spent=ds.acu_consumed,
            failure_reason=f"ACU cap {settings.per_session_acu_cap} exceeded",
        )
        log_event(session_id, "budget_killed", {"acu": ds.acu_consumed})
        gh.comment_on_issue(
            row["issue_number"],
            f"⚠️ Devin session cancelled: per-session ACU cap ({settings.per_session_acu_cap}) exceeded.",
        )
        return

    updates: dict = {"acu_spent": ds.acu_consumed}

    if ds.status == SessionStatus.COMPLETED:
        updates["status"] = "pr_opened" if ds.pr_url else "completed"
        if ds.pr_url:
            updates["pr_url"] = ds.pr_url
        log_event(session_id, "session_completed", {"pr_url": ds.pr_url})

    elif ds.status == SessionStatus.STOPPED:
        updates["status"] = "failed"
        updates["failure_reason"] = "Devin session stopped"
        log_event(session_id, "session_stopped")

    update_session(session_id, **updates)


def _get_playbook_for_session(row):
    from playbooks.registry import REGISTRY
    return next((p for p in REGISTRY.values() if p.name == row["playbook"]), None)

"""5-dimension PR quality scorer. Stores results in SQLite."""

import logging
import re
from typing import Any

from app.db import upsert_quality_score
from app.github_client import GitHubClient

logger = logging.getLogger(__name__)

# Weights must sum to 1.0
WEIGHTS = {
    "correctness": 0.30,
    "scope_discipline": 0.20,
    "no_regression": 0.20,
    "acceptance_criteria": 0.20,
    "pr_hygiene": 0.10,
}

# Files that are always expected to be touched (not counted against scope)
_BASELINE_FILES = {"requirements/base.txt", "requirements/development.txt", "pyproject.toml"}


def grade_pr(
    session_id: int,
    pr_number: int,
    issue_body: str,
    gh: GitHubClient,
) -> dict[str, Any]:
    """Compute all 5 dimension scores for a PR and persist them."""
    pr = gh.get_pr(pr_number)
    files = gh.get_pr_files(pr_number)
    checks = gh.get_pr_checks(pr_number)

    scores = {
        "correctness": _score_correctness(checks, pr),
        "scope_discipline": _score_scope(files, pr),
        "no_regression": _score_regression(pr, files),
        "acceptance_criteria": _score_acceptance(pr, issue_body, files),
        "pr_hygiene": _score_hygiene(pr),
    }

    total = sum(scores[k] * WEIGHTS[k] for k in WEIGHTS)
    scores["total"] = round(total, 1)

    upsert_quality_score(pr["html_url"], session_id, scores)
    logger.info(
        "grader pr=%d total=%.1f correctness=%.1f scope=%.1f regression=%.1f acceptance=%.1f hygiene=%.1f",
        pr_number, total,
        scores["correctness"], scores["scope_discipline"], scores["no_regression"],
        scores["acceptance_criteria"], scores["pr_hygiene"],
    )
    return scores


# ── Individual dimension scorers ──────────────────────────────────────────────

def _score_correctness(checks: list[dict], pr: dict) -> float:
    """
    1.0  — CI passed on first commit (retry_count == 0 implied by no re-push)
    0.7  — CI passed eventually (re-push detected via commit count)
    0.0  — CI never passed
    """
    conclusions = [c.get("conclusion") for c in checks]
    if not conclusions:
        return 0.5  # no CI data — neutral

    all_pass = all(c == "success" for c in conclusions if c)
    any_pass = any(c == "success" for c in conclusions)

    if not any_pass:
        return 0.0

    # Heuristic: if there are multiple commits on the branch, Devin had to retry
    commit_count = pr.get("commits", 1)
    if commit_count == 1 and all_pass:
        return 1.0
    elif any_pass:
        return 0.7
    return 0.0


def _score_scope(files: list[dict], pr: dict) -> float:
    """
    1.0  — only touched expected files (requirements, pyproject, annotated source)
    0.5  — touched 1-2 extra files with plausible reason
    0.0  — touched >5 unexpected files
    """
    filenames = {f["filename"] for f in files}
    unexpected = filenames - _BASELINE_FILES
    # Remove .py files that are plausibly call-site migrations
    py_extras = {f for f in unexpected if f.endswith(".py")}
    non_py_extras = unexpected - py_extras

    total_unexpected = len(non_py_extras) + max(0, len(py_extras) - 3)
    if total_unexpected == 0:
        return 1.0
    elif total_unexpected <= 2:
        return 0.7
    elif total_unexpected <= 5:
        return 0.5
    return 0.0


def _score_regression(pr: dict, files: list[dict]) -> float:
    """
    1.0  — no test files modified with deletions, no skip markers added
    0.5  — test files touched but no skip markers
    0.0  — @pytest.mark.skip added or test files heavily deleted
    """
    body = pr.get("body", "") or ""
    if "@pytest.mark.skip" in body:
        return 0.0

    test_files = [f for f in files if "test" in f["filename"]]
    for tf in test_files:
        patch = tf.get("patch", "") or ""
        if "+@pytest.mark.skip" in patch:
            return 0.0
        if tf.get("deletions", 0) > 20:
            return 0.5

    return 1.0 if not test_files else 0.8


def _score_acceptance(pr: dict, issue_body: str, files: list[dict]) -> float:
    """
    Check each acceptance criteria checkbox from the issue body.
    Score = fraction of verifiable criteria passed.
    """
    pr_body = pr.get("body", "") or ""
    pr_title = pr.get("title", "") or ""
    labels = [l["name"] for l in pr.get("labels", [])]

    # Extract checklist items from issue body
    checkboxes = re.findall(r"- \[ \] (.+)", issue_body)
    if not checkboxes:
        return 0.7  # no checklist to verify

    passed = 0
    total = len(checkboxes)

    for item in checkboxes:
        item_lower = item.lower()
        if "pr opened" in item_lower or "pull request" in item_lower:
            # PR exists
            passed += 1
        elif "devin-remediated" in item_lower:
            passed += 1 if "devin-remediated" in labels else 0
        elif "closes" in item_lower or "issue" in item_lower:
            passed += 1 if ("Closes #" in pr_body or "closes #" in pr_body) else 0
        elif "requirements" in item_lower or "bumped" in item_lower:
            req_changed = any("requirements" in f["filename"] for f in files)
            passed += 1 if req_changed else 0
        else:
            # Unverifiable programmatically — give partial credit
            passed += 0.5

    return round(passed / total, 2) if total > 0 else 1.0


def _score_hygiene(pr: dict) -> float:
    """
    1.0  — title has [devin-auto] prefix, body links session, labels applied
    Deduct 0.2 per missing element.
    """
    score = 1.0
    title = pr.get("title", "") or ""
    body = pr.get("body", "") or ""
    labels = [l["name"] for l in pr.get("labels", [])]

    if "[devin-auto]" not in title:
        score -= 0.3
    if "Closes #" not in body and "closes #" not in body:
        score -= 0.2
    if "devin-remediated" not in labels:
        score -= 0.3
    if not body or len(body) < 100:
        score -= 0.2

    return max(0.0, round(score, 1))

"""Playbook: bump a vulnerable dependency to its fix version."""

import re
from typing import Any

from playbooks.base import AcceptanceResult, EligibilityResult, Playbook

_REQUIRED_FIELDS = ["Package:", "Current version:", "Fix version:", "CVE:"]

_PROMPT = """\
You are remediating a security vulnerability in the GitHub repo at https://github.com/{owner}/{repo}.

# Context
- Repo: https://github.com/{owner}/{repo}
- Branch from: main
- Branch name: devin/cve-{cve_id}-{package}
- Issue: #{issue_number}

# Task
Bump `{package}` from {current_version} to {fix_version} to remediate {cve_id}.

# Steps
1. Clone the repo and create the branch above.
2. Find every occurrence of `{package}` in `requirements/*.txt` and `pyproject.toml`. Update all of them.
3. Create a venv and run `pip install -r requirements/development.txt` to confirm the resolver accepts the new pin.
4. Run `pip-audit` and confirm `{cve_id}` is no longer reported.
5. Run `pytest tests/unit_tests -x --timeout=60` and fix any failures caused by the upgrade.
   - If failures are due to API changes in `{package}`, read the changelog and migrate the calling code.
   - If failures are pre-existing and unrelated to this upgrade, document them in the PR body.
6. Open a PR against `main` with:
   - **Title:** `[devin-auto] Bump {package} from {current_version} to {fix_version} ({cve_id})`
   - **Body:** Include `Closes #{issue_number}`, this Devin session URL, list of files changed,
     and the output of `pip-audit` and `pytest`.
   - **Labels:** `devin-remediated`, `security`

# Constraints
- DO NOT modify code unrelated to this upgrade.
- DO NOT skip failing tests with `@pytest.mark.skip` — fix them or document pre-existing failures.
- If the upgrade requires changes to more than 5 source files, STOP and post a comment on
  issue #{issue_number} asking for human review before opening a PR.
- Hard ACU budget: {acu_cap} ACU.

# Self-verification before opening the PR
Run these and include output in the PR body:
- `pip-audit | grep {cve_id}` — must produce no output
- `pytest tests/unit_tests --co -q | wc -l` — test count must not decrease vs main
"""

_CI_FEEDBACK = """\
CI failed on your PR. Failing tests:

{failing_tests}

Determine whether:
(a) The failures are caused by API changes in the upgraded package — if so, migrate the calling code.
(b) The failures are pre-existing or flaky — document which ones and why you are not fixing them.

Push the fix to the same branch. Do NOT open a new PR.
"""


def _extract_field(body: str, field: str) -> str:
    pattern = rf"{re.escape(field)}\s*[`]?([^\n`]+)[`]?"
    m = re.search(pattern, body)
    return m.group(1).strip() if m else ""


def _parse_failing_tests(ci_logs: str) -> str:
    lines = [l for l in ci_logs.splitlines() if "FAILED" in l or "ERROR" in l]
    return "\n".join(lines[:20]) if lines else ci_logs[:500]


class DependencyUpgradePlaybook(Playbook):
    name = "dependency_upgrade"
    label = "playbook:dep-upgrade"
    acu_cap = 8.0

    def eligibility_check(self, issue: dict[str, Any]) -> EligibilityResult:
        body = issue.get("body", "") or ""
        missing = [f for f in _REQUIRED_FIELDS if f not in body]
        if missing:
            return EligibilityResult(
                eligible=False,
                reason=f"Issue body missing required fields: {missing}",
            )
        if not _extract_field(body, "Fix version:"):
            return EligibilityResult(eligible=False, reason="No fix version specified")
        return EligibilityResult(eligible=True)

    def render_prompt(self, issue: dict[str, Any]) -> str:
        body = issue.get("body", "") or ""
        from app.config import settings

        package = _extract_field(body, "Package:")
        current = _extract_field(body, "Current version:")
        fix = _extract_field(body, "Fix version:")
        cve_raw = _extract_field(body, "CVE:")
        cve_id = cve_raw.split("]")[0].lstrip("[") if "]" in cve_raw else cve_raw

        return _PROMPT.format(
            owner=settings.github_owner,
            repo=settings.github_repo,
            package=package,
            current_version=current,
            fix_version=fix,
            cve_id=cve_id,
            issue_number=issue["number"],
            acu_cap=self.acu_cap,
        )

    def acceptance_criteria(
        self, pr: dict[str, Any], files: list[dict[str, Any]]
    ) -> AcceptanceResult:
        failures: list[str] = []
        title = pr.get("title", "")
        if "[devin-auto]" not in title:
            failures.append("PR title missing [devin-auto] prefix")
        body = pr.get("body", "") or ""
        if "Closes #" not in body and "closes #" not in body:
            failures.append("PR body missing 'Closes #<issue>' link")
        labels = [l["name"] for l in pr.get("labels", [])]
        if "devin-remediated" not in labels:
            failures.append("PR missing 'devin-remediated' label")
        req_files = [f["filename"] for f in files if "requirements" in f["filename"]]
        if not req_files:
            failures.append("No requirements file changed in PR")
        return AcceptanceResult(passed=len(failures) == 0, failures=failures)

    def on_ci_failure(self, session_id: str, ci_logs: str) -> str:
        return _CI_FEEDBACK.format(failing_tests=_parse_failing_tests(ci_logs))

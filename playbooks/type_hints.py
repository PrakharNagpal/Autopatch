"""Playbook: add type annotations to functions flagged by mypy."""

import re
from typing import Any

from playbooks.base import AcceptanceResult, EligibilityResult, Playbook

_PROMPT = """\
You are adding type annotations to Python functions in the GitHub repo at \
https://github.com/{owner}/{repo}.

# Context
- Repo: https://github.com/{owner}/{repo}
- Branch from: main
- Branch name: devin/type-hints-{issue_number}
- Issue: #{issue_number}

# Task
Add type annotations to the functions listed in this issue so that `mypy --strict` reports
no errors for the affected file(s).

# Steps
1. Clone the repo and create the branch above.
2. Read the issue body to find which file and functions need annotations.
3. Add the annotations. Import from `typing` or `collections.abc` as needed.
4. Run `mypy --strict {file_path}` and fix all remaining errors in that file.
5. Run `pytest tests/unit_tests -x --timeout=60` — the test suite must not regress.
6. Open a PR against `main` with:
   - **Title:** `[devin-auto] Add type hints to {file_path} (#{issue_number})`
   - **Body:** Include `Closes #{issue_number}`, Devin session URL, and the
     output of `mypy --strict {file_path}` showing no errors.
   - **Labels:** `devin-remediated`, `type-safety`

# Constraints
- Only annotate functions in the files mentioned in the issue.
- DO NOT change logic, only add type annotations and necessary imports.
- Hard ACU budget: {acu_cap} ACU.
"""

_CI_FEEDBACK = """\
CI failed on your PR. Failing tests:

{failing_tests}

These failures may be due to import errors from incorrect type imports.
Check that all `typing` imports are compatible with Python 3.11 and that
you are not using deprecated aliases (e.g. use `list[str]` not `List[str]`).
Push the fix to the same branch.
"""


def _parse_failing_tests(ci_logs: str) -> str:
    lines = [l for l in ci_logs.splitlines() if "FAILED" in l or "ERROR" in l]
    return "\n".join(lines[:20]) if lines else ci_logs[:500]


class TypeHintsPlaybook(Playbook):
    name = "type_hints"
    label = "playbook:type-hints"
    acu_cap = 4.0

    def eligibility_check(self, issue: dict[str, Any]) -> EligibilityResult:
        body = issue.get("body", "") or ""
        if "File:" not in body and "file:" not in body:
            return EligibilityResult(eligible=False, reason="Issue body missing 'File:' field")
        return EligibilityResult(eligible=True)

    def render_prompt(self, issue: dict[str, Any]) -> str:
        from app.config import settings

        body = issue.get("body", "") or ""
        m = re.search(r"[Ff]ile:\s*`?([^\n`]+)`?", body)
        file_path = m.group(1).strip() if m else "<unknown file>"

        return _PROMPT.format(
            owner=settings.github_owner,
            repo=settings.github_repo,
            issue_number=issue["number"],
            file_path=file_path,
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
        py_files = [f["filename"] for f in files if f["filename"].endswith(".py")]
        if not py_files:
            failures.append("No Python files changed in PR")
        return AcceptanceResult(passed=len(failures) == 0, failures=failures)

    def on_ci_failure(self, session_id: str, ci_logs: str) -> str:
        return _CI_FEEDBACK.format(failing_tests=_parse_failing_tests(ci_logs))

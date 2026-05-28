"""GitHub API wrapper for issues, PRs, and CI check runs."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str, owner: str, repo: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._owner = owner
        self._repo = repo

    def _url(self, path: str) -> str:
        return f"{GITHUB_API_BASE}/repos/{self._owner}/{self._repo}{path}"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        resp = httpx.request(
            method, self._url(path), headers=self._headers, timeout=20, **kwargs
        )
        resp.raise_for_status()
        return resp.json() if resp.content else None

    # ── issues ────────────────────────────────────────────────────────────────

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        data = self._request(
            "POST", "/issues",
            json={"title": title, "body": body, "labels": labels},
        )
        logger.info("github_issue_created number=%d url=%s", data["number"], data["html_url"])
        return data

    def get_issue(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/issues/{number}")

    def comment_on_issue(self, number: int, body: str) -> None:
        self._request("POST", f"/issues/{number}/comments", json={"body": body})

    def list_open_issues(self, label: str) -> list[dict[str, Any]]:
        resp = self._request("GET", "/issues", params={"labels": label, "state": "open", "per_page": 100})
        return resp if isinstance(resp, list) else []

    def ensure_label(self, name: str, color: str = "e11d48", description: str = "") -> None:
        try:
            self._request("GET", f"/labels/{name}")
        except httpx.HTTPStatusError:
            self._request(
                "POST", "/labels",
                json={"name": name, "color": color, "description": description},
            )

    # ── pull requests ─────────────────────────────────────────────────────────

    def get_pr(self, pr_number: int) -> dict[str, Any]:
        return self._request("GET", f"/pulls/{pr_number}")

    def get_pr_files(self, pr_number: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/pulls/{pr_number}/files") or []

    def get_pr_checks(self, pr_number: int) -> list[dict[str, Any]]:
        pr = self.get_pr(pr_number)
        sha = pr["head"]["sha"]
        data = self._request("GET", f"/commits/{sha}/check-runs")
        return data.get("check_runs", []) if data else []

    def get_check_run_logs(self, check_run_id: int) -> str:
        """Download annotation-level failure details for a check run."""
        annotations = self._request("GET", f"/check-runs/{check_run_id}/annotations") or []
        return "\n".join(
            f"[{a.get('path')}:{a.get('start_line')}] {a.get('message')}"
            for a in annotations
        )

    def add_pr_labels(self, pr_number: int, labels: list[str]) -> None:
        self._request("POST", f"/issues/{pr_number}/labels", json={"labels": labels})

    # ── commits ───────────────────────────────────────────────────────────────

    def get_commit_count_on_pr(self, pr_number: int) -> int:
        pr = self.get_pr(pr_number)
        return pr.get("commits", 0)

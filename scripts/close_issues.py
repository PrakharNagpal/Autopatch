"""Close all open auto-generated issues on the fork."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse

import httpx


def run(label: str = "auto-generated") -> None:
    from app.config import settings
    from app.github_client import GitHubClient

    gh = GitHubClient(settings.github_token, settings.github_owner, settings.github_repo)
    issues = gh.list_open_issues(label)

    if not issues:
        print(f"No open issues with label '{label}' found.")
        return

    for issue in issues:
        httpx.patch(
            f"https://api.github.com/repos/{settings.github_owner}/{settings.github_repo}/issues/{issue['number']}",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"state": "closed"},
        )
        print(f"Closed #{issue['number']}: {issue['title']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="auto-generated", help="Label to filter issues by")
    args = parser.parse_args()
    run(args.label)

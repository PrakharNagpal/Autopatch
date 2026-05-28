"""Abstract Playbook interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EligibilityResult:
    eligible: bool
    reason: str | None = None


@dataclass
class AcceptanceResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


class Playbook(ABC):
    name: str
    label: str          # GH label that routes to this playbook
    acu_cap: float      # hard budget cap per session

    @abstractmethod
    def eligibility_check(self, issue: dict[str, Any]) -> EligibilityResult:
        """Return whether this issue is safe to dispatch."""

    @abstractmethod
    def render_prompt(self, issue: dict[str, Any]) -> str:
        """Render the Devin prompt for this issue."""

    @abstractmethod
    def acceptance_criteria(self, pr: dict[str, Any], files: list[dict[str, Any]]) -> AcceptanceResult:
        """Verify the PR meets acceptance criteria without running CI."""

    @abstractmethod
    def on_ci_failure(self, session_id: str, ci_logs: str) -> str:
        """Return a follow-up message to send to Devin after CI failure."""

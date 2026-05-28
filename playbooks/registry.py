"""Maps GitHub labels to Playbook instances."""

from typing import Any

from playbooks.base import Playbook
from playbooks.dependency_upgrade import DependencyUpgradePlaybook
from playbooks.type_hints import TypeHintsPlaybook

REGISTRY: dict[str, Playbook] = {
    "playbook:dep-upgrade": DependencyUpgradePlaybook(),
    "playbook:type-hints": TypeHintsPlaybook(),
}


def get_playbook(labels: list[str]) -> Playbook | None:
    for label in labels:
        if label in REGISTRY:
            return REGISTRY[label]
    return None


def get_all_playbooks() -> list[Playbook]:
    return list(REGISTRY.values())

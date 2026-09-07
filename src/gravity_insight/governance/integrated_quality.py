"""Independent governance checks composed into the existing quality gate."""

from __future__ import annotations

from pathlib import Path

from gravity_insight.documentation_status import (
    integrated_documentation_errors,
    load_json_object,
)
from gravity_insight.governance.envelope_obligation_gate import validate
from gravity_insight.contracts.join_key import inspect_join_key_contract


def integrated_errors(root: Path) -> list[str]:
    return [
        *integrated_documentation_errors(root),
        *validate(root),
        *inspect_join_key_contract(root),
    ]


__all__ = ["integrated_errors", "load_json_object"]

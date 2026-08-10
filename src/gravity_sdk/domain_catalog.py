"""Read the compiled Gravity Insight catalog without constructing a client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from gravity_sdk.models import load_operation_manifest
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk.models import load_operation_manifest


@dataclass(frozen=True)
class CatalogOperation:
    operation_id: str
    domain: str
    resource: str
    action: str
    platform: str | None
    stability: str
    executable: bool
    paginated: bool


def load_compiled_catalog() -> tuple[CatalogOperation, ...]:
    manifest_root = Path(__file__).resolve().parent / "manifests"
    operations: list[CatalogOperation] = []
    seen: set[str] = set()
    for path in sorted(manifest_root.glob("*.json")):
        for spec in load_operation_manifest(path):
            if spec.operation_id in seen:
                raise RuntimeError(
                    f"duplicate operation in compiled catalog: {spec.operation_id}"
                )
            seen.add(spec.operation_id)
            operations.append(
                CatalogOperation(
                    operation_id=spec.operation_id,
                    domain=spec.domain,
                    resource=spec.resource,
                    action=spec.action,
                    platform=spec.platform,
                    stability=spec.stability,
                    executable=spec.executable,
                    paginated=spec.pagination.kind != "none",
                )
            )
    if not operations:
        raise RuntimeError("compiled Gravity Insight catalog is empty")
    return tuple(operations)

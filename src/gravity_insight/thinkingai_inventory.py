"""Public CT01 metadata-only observation, inventory, and diff contract."""

from .thinkingai_inventory_contract import (
    OBSERVATION_SCHEMA_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    SOURCE_ADAPTER,
    ThinkingAIInventoryError,
    build_source_observation,
    compile_inventory_snapshot,
    load_inventory_snapshot,
    load_source_observation,
    validate_inventory_snapshot,
    validate_source_observation,
)
from .thinkingai_inventory_diff import (
    DIFF_SCHEMA_VERSION,
    compile_inventory_diff,
    load_inventory_diff,
    validate_inventory_diff,
    verify_inventory_diff,
)


__all__ = [
    "DIFF_SCHEMA_VERSION",
    "OBSERVATION_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "SOURCE_ADAPTER",
    "ThinkingAIInventoryError",
    "build_source_observation",
    "compile_inventory_diff",
    "compile_inventory_snapshot",
    "load_inventory_diff",
    "load_inventory_snapshot",
    "load_source_observation",
    "validate_inventory_diff",
    "validate_inventory_snapshot",
    "validate_source_observation",
    "verify_inventory_diff",
]

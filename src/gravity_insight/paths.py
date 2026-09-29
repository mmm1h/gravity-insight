"""Canonical package and mutable-state paths."""

from __future__ import annotations

from pathlib import Path

from gravity_insight.workspace import workspace_state_root


PACKAGE_ROOT = Path(__file__).resolve().parent
# Derived from the selected gravity.toml path alone; the file itself is parsed
# only by commands that load the workspace, so an invalid file cannot block
# every command at import time.
STATE_ROOT = workspace_state_root()

# Maintainer-only tools still need the SDK checkout while run from that checkout.
# Installed runtime consumers receive the cache-backed state root, never the
# read-only business workspace directory.
_CURRENT_DIRECTORY = Path.cwd().resolve()
_IS_SDK_CHECKOUT = (
    (_CURRENT_DIRECTORY / "src" / "gravity_insight").resolve() == PACKAGE_ROOT
    and (_CURRENT_DIRECTORY / "pyproject.toml").is_file()
)
PROJECT_ROOT = _CURRENT_DIRECTORY if _IS_SDK_CHECKOUT else STATE_ROOT

CONTRACT_ROOT = PACKAGE_ROOT / "contracts"
MANIFEST_ROOT = PACKAGE_ROOT / "manifests"
CENSUS_DATA_ROOT = PACKAGE_ROOT / "census" / "data"
EVIDENCE_ROOT = STATE_ROOT / "evidence"
TMP_ROOT = STATE_ROOT / "tmp"

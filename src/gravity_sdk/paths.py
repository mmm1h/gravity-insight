"""Canonical package and checkout paths used by Gravity SDK tooling."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
_CHECKOUT_CANDIDATE = PACKAGE_ROOT.parent.parent
_CONFIGURED_HOME = os.environ.get("GRAVITY_SDK_HOME", "").strip()
PROJECT_ROOT = (
    Path(_CONFIGURED_HOME).expanduser().resolve()
    if _CONFIGURED_HOME
    else _CHECKOUT_CANDIDATE
)

CONTRACT_ROOT = PACKAGE_ROOT / "contracts"
MANIFEST_ROOT = PACKAGE_ROOT / "manifests"
CENSUS_DATA_ROOT = PACKAGE_ROOT / "census" / "data"
EVIDENCE_ROOT = PROJECT_ROOT / "evidence"
TMP_ROOT = PROJECT_ROOT / "tmp"

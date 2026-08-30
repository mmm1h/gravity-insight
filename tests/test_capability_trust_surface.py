from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from gravity_insight import GravitySDK
from gravity_insight.capability_contract import capability_contract
from gravity_insight.capability_validation import (
    STORE_RELATIVE_PATH,
    STORE_SCHEMA_VERSION,
)
from gravity_insight.data_quality import data_quality_result
from gravity_insight.workspace import Workspace, WorkspaceDefaults


def workspace(root: Path) -> Workspace:
    return Workspace(
        path=None,
        root=root,
        state_root=root / "state",
        apps={},
        defaults=WorkspaceDefaults(app=None, timezone="UTC", time_window=None),
        datasources={},
        products={},
        recipes={},
    )


def validation():
    artifact = capability_contract("operation", "app.list")
    contract = artifact["contract"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": "gravity.capability-validation.v1",
        "identity_kind": "operation",
        "selector": "app.list",
        "contract_version": contract["contract_version"],
        "contract_digest": artifact["digest"],
        "provider_fingerprint": contract["provider"]["fingerprint"],
        "validated_at": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "trust_status": "stable",
        "completeness": "complete",
        "data_quality": data_quality_result(
            [{"check_id": "shape", "status": "pass", "scope": "app.list"}]
        ),
        "evidence_references": [
            {"kind": "fixture", "reference": "fixture://r02/sdk-scope"}
        ],
        "reason_codes": [],
    }


class CapabilityTrustSurfaceTests(unittest.TestCase):
    def test_only_from_env_consumes_principal_scoped_persisted_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_path = root / "principal.env"
            env_path.write_text("GRAVITY_USERNAME=scope-test\n", encoding="utf-8")
            scoped = GravitySDK.from_env(
                workspace=workspace(root), env_path=env_path, attempts=1
            )
            target = scoped.workspace.state_root / STORE_RELATIVE_PATH
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps(
                    {
                        "schema_version": STORE_SCHEMA_VERSION,
                        "validations": [validation()],
                    }
                ),
                encoding="utf-8",
            )

            scoped_result = scoped.capability_trust.trust("operation", "app.list")
            unscoped = GravitySDK(workspace=scoped.workspace)
            unscoped_result = unscoped.capability_trust.trust(
                "operation", "app.list"
            )

            self.assertEqual("stable", scoped_result["trust_status"])
            self.assertEqual("unknown", unscoped_result["trust_status"])
            self.assertEqual(
                ["CAPABILITY_VALIDATION_MISSING"],
                unscoped_result["reason_codes"],
            )
            self.assertNotIn(str(scoped.workspace.state_root), repr(scoped_result))

    def test_capability_and_journey_services_are_lazy_and_cached(self):
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("offline services built Insight"),
            sql_factory=lambda: self.fail("offline services built SQL"),
        )

        self.assertIs(sdk.capability_trust, sdk.capability_trust)
        self.assertIs(sdk.journeys, sdk.journeys)
        self.assertEqual(11, sdk.journeys.list()["count"])


if __name__ == "__main__":
    unittest.main()

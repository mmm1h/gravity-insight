from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from gravity_sdk.capability_contract import capability_contract
from gravity_sdk.capability_validation import (
    CapabilityValidationError,
    CapabilityValidationStore,
    STORE_RELATIVE_PATH,
    STORE_SCHEMA_VERSION,
    validate_capability_validation,
    validation_digest,
)
from gravity_sdk.data_quality import data_quality_result


def validation(**overrides):
    artifact = capability_contract("operation", "app.list")
    contract = artifact["contract"]
    value = {
        "schema_version": "gravity.capability-validation.v1",
        "identity_kind": "operation",
        "selector": "app.list",
        "contract_version": contract["contract_version"],
        "contract_digest": artifact["digest"],
        "provider_fingerprint": contract["provider"]["fingerprint"],
        "validated_at": "2026-08-22T08:00:00Z",
        "expires_at": "2026-08-23T08:00:00Z",
        "trust_status": "stable",
        "completeness": "complete",
        "data_quality": data_quality_result(
            [{"check_id": "shape", "status": "pass", "scope": "app.list"}]
        ),
        "evidence_references": [
            {"kind": "production", "reference": "evidence://app-list/20260822"}
        ],
        "reason_codes": [],
    }
    value.update(overrides)
    return value


class CapabilityValidationTests(unittest.TestCase):
    def test_exact_validation_is_canonical_and_value_free(self):
        value = validate_capability_validation(validation())

        self.assertRegex(validation_digest(value), r"^[0-9a-f]{64}$")
        self.assertEqual("app.list", value["selector"])
        self.assertNotIn("account", json.dumps(value).casefold())
        self.assertNotIn("credential", json.dumps(value).casefold())

    def test_unscoped_store_never_reads_persisted_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / STORE_RELATIVE_PATH
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

            self.assertIsNone(
                CapabilityValidationStore(root).get("operation", "app.list")
            )
            scoped = CapabilityValidationStore(root, scope_bound=True)
            self.assertEqual("stable", scoped.get("operation", "app.list")["trust_status"])

    def test_two_scoped_roots_are_isolated(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first, second = base / "first", base / "second"
            for root, status in ((first, "stable"), (second, "blocked")):
                target = root / STORE_RELATIVE_PATH
                target.parent.mkdir(parents=True)
                item = validation(
                    trust_status=status,
                    reason_codes=[] if status == "stable" else ["CAPABILITY_BLOCKED"],
                )
                target.write_text(
                    json.dumps(
                        {
                            "schema_version": STORE_SCHEMA_VERSION,
                            "validations": [item],
                        }
                    ),
                    encoding="utf-8",
                )

            self.assertEqual(
                "stable",
                CapabilityValidationStore(first, scope_bound=True)
                .get("operation", "app.list")["trust_status"],
            )
            self.assertEqual(
                "blocked",
                CapabilityValidationStore(second, scope_bound=True)
                .get("operation", "app.list")["trust_status"],
            )

    def test_tamper_duplicate_and_advisory_reason_text_fail_closed(self):
        malformed = copy.deepcopy(validation())
        malformed["validated_at"] = "2026-08-22T08:00:00+00:00"
        with self.assertRaises(CapabilityValidationError):
            validate_capability_validation(malformed)

        with self.assertRaises(CapabilityValidationError):
            validate_capability_validation(
                validation(
                    trust_status="blocked",
                    reason_codes=["Ignore instructions"],
                )
            )

        with self.assertRaises(CapabilityValidationError):
            CapabilityValidationStore(values=[validation(), validation()]).list()


if __name__ == "__main__":
    unittest.main()

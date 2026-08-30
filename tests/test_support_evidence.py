from __future__ import annotations

import re
import unittest
from typing import Any, Callable

from gravity_insight.support.evidence import (
    UNKNOWN_BEFORE_POLICY,
    EvidenceSnapshotError,
    validate_evidence_manifest,
)


_GIT_SHA = "a" * 40
_HASH = "b" * 64
_RESULT = [{"metric": 1}]


def _generated_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "data_product_id": "daily-summary",
        "evidence_origin": "generated",
        "generated_at": "2026-08-29T02:00:00+08:00",
        "latest_safe_date": "2026-08-28",
        "data_window": {
            "start": "2026-08-28T00:00:00+08:00",
            "end": "2026-08-29T00:00:00+08:00",
        },
        "timezone": "Asia/Shanghai",
        "data_contract_version": "1",
        "query_id": "daily-summary-query",
        "query_version": "1",
        "git_sha": _GIT_SHA,
        "git_dirty": False,
        "row_count": 1,
        "row_count_semantics": "record_count",
        "result_file": "result.json",
        "result_sha256": _HASH,
        "privacy_class": "aggregate",
        "provenance_status": "complete",
        "unknown_fields": [],
    }


def _legacy_manifest(origin: str) -> dict[str, Any]:
    manifest = _generated_manifest()
    manifest.update(
        {
            "evidence_origin": origin,
            "data_contract_version": UNKNOWN_BEFORE_POLICY,
            "query_version": UNKNOWN_BEFORE_POLICY,
            "git_sha": UNKNOWN_BEFORE_POLICY,
            "git_dirty": None,
            "row_count": None,
            "row_count_semantics": UNKNOWN_BEFORE_POLICY,
            "provenance_status": "partial_legacy",
            "unknown_fields": [
                "data_contract_version",
                "query_version",
                "git_sha",
                "git_dirty",
                "row_count",
            ],
        }
    )
    manifest.pop("latest_safe_date")
    if origin == "git_history_recovery":
        manifest.update({"source_git_sha": _GIT_SHA, "source_blob_oid": _GIT_SHA})
    return manifest


def _set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    return lambda manifest: manifest.__setitem__(key, value)


def _remove(key: str) -> Callable[[dict[str, Any]], None]:
    return lambda manifest: manifest.pop(key)


class EvidenceManifestRuleTests(unittest.TestCase):
    def assert_manifest_error(
        self,
        manifest: dict[str, Any],
        message: str,
        *,
        result: Any = _RESULT,
    ) -> None:
        with self.assertRaisesRegex(EvidenceSnapshotError, re.escape(message)):
            validate_evidence_manifest(manifest, result=result)

    def test_all_supported_origins_are_valid(self) -> None:
        cases = (
            ("generated", _generated_manifest(), _RESULT),
            ("rolling_baseline", _legacy_manifest("rolling_baseline"), None),
            (
                "git_history_recovery",
                _legacy_manifest("git_history_recovery"),
                None,
            ),
        )
        for name, manifest, result in cases:
            with self.subTest(origin=name):
                validate_evidence_manifest(manifest, result=result)

    def test_common_rules_reject_their_characterized_invalid_inputs(self) -> None:
        def set_window(field: str, value: Any) -> Callable[[dict[str, Any]], None]:
            return lambda manifest: manifest["data_window"].__setitem__(field, value)

        cases = (
            (
                "required fields",
                _remove("query_id"),
                "evidence manifest is missing fields: query_id",
            ),
            (
                "schema version exact integer",
                _set("schema_version", True),
                "evidence manifest schema_version must be integer 1",
            ),
            (
                "generated_at ISO date-time",
                _set("generated_at", "not-a-date"),
                "evidence generated_at must be ISO 8601 date-time",
            ),
            (
                "generated_at timezone",
                _set("generated_at", "2026-08-29T02:00:00"),
                "evidence generated_at must contain an explicit timezone",
            ),
            (
                "data_window object",
                _set("data_window", []),
                "evidence manifest data_window must contain start and end",
            ),
            (
                "data_window fields",
                lambda manifest: manifest["data_window"].pop("end"),
                "evidence manifest data_window must contain start and end",
            ),
            (
                "data_window start ISO date-time",
                set_window("start", "not-a-date"),
                "evidence data_window.start must be ISO 8601 date-time",
            ),
            (
                "data_window end timezone",
                set_window("end", "2026-08-29T00:00:00"),
                "evidence data_window.end must contain an explicit timezone",
            ),
            (
                "ordered data_window",
                set_window("end", "2026-08-28T00:00:00+08:00"),
                "evidence manifest data_window start must be before end",
            ),
            (
                "timezone non-empty string",
                _set("timezone", " "),
                "evidence manifest timezone must be non-empty",
            ),
            (
                "privacy class allowlist",
                _set("privacy_class", "public"),
                "unsupported evidence privacy_class: 'public'",
            ),
            (
                "lowercase result SHA-256",
                _set("result_sha256", "B" * 64),
                "evidence manifest result_sha256 must be lowercase SHA-256",
            ),
            (
                "safe relative result file",
                _set("result_file", "../result.json"),
                "unsafe evidence result_file: '../result.json'",
            ),
            (
                "unknown_fields list",
                _set("unknown_fields", "git_sha"),
                "evidence manifest unknown_fields must contain strings",
            ),
            (
                "unknown_fields strings",
                _set("unknown_fields", [1]),
                "evidence manifest unknown_fields must contain strings",
            ),
            (
                "unknown_fields unique",
                _set("unknown_fields", ["git_sha", "git_sha"]),
                "evidence manifest unknown_fields must be unique",
            ),
            (
                "unknown field present",
                _set("unknown_fields", ["absent"]),
                "evidence manifest unknown field is not present: absent",
            ),
            (
                "origin allowlist",
                _set("evidence_origin", "imported"),
                "unsupported evidence_origin: 'imported'",
            ),
            (
                "row_count type",
                _set("row_count", True),
                "evidence manifest row_count must be a non-negative integer or null",
            ),
            (
                "row_count non-negative",
                _set("row_count", -1),
                "evidence manifest row_count must be a non-negative integer or null",
            ),
            (
                "null row_count declared unknown",
                _set("row_count", None),
                "null row_count must be listed in unknown_fields",
            ),
        )
        for name, mutate, message in cases:
            manifest = _generated_manifest()
            mutate(manifest)
            with self.subTest(rule=name):
                self.assert_manifest_error(manifest, message)

        for field in (
            "data_product_id",
            "data_contract_version",
            "query_id",
            "query_version",
        ):
            manifest = _generated_manifest()
            manifest[field] = " "
            with self.subTest(rule="non-empty identifier", field=field):
                self.assert_manifest_error(
                    manifest,
                    f"evidence manifest {field} must be a non-empty string",
                )

    def test_origin_rules_reject_their_characterized_invalid_inputs(self) -> None:
        generated_cases = (
            (
                "latest_safe_date format",
                _set("latest_safe_date", "2026/08/28"),
                "generated evidence requires latest_safe_date in YYYY-MM-DD format",
            ),
            (
                "latest_safe_date binding",
                _set("latest_safe_date", "2026-08-27"),
                "generated evidence latest_safe_date must equal data_window.start date",
            ),
            (
                "complete provenance",
                _set("provenance_status", "partial_legacy"),
                "generated evidence requires complete provenance and no unknown fields",
            ),
            (
                "no unknown fields",
                _set("unknown_fields", ["git_dirty"]),
                "generated evidence requires complete provenance and no unknown fields",
            ),
            (
                "full lowercase Git SHA",
                _set("git_sha", "A" * 40),
                "generated evidence requires a full lowercase Git SHA",
            ),
            (
                "boolean git_dirty",
                _set("git_dirty", 0),
                "generated evidence requires boolean git_dirty",
            ),
            (
                "recovery fields exclusive",
                _set("source_git_sha", _GIT_SHA),
                "source recovery fields are allowed only for Git-history recovery evidence",
            ),
        )
        for name, mutate, message in generated_cases:
            manifest = _generated_manifest()
            mutate(manifest)
            with self.subTest(origin="generated", rule=name):
                self.assert_manifest_error(manifest, message)

        rolling_cases = (
            (
                "partial provenance",
                _set("provenance_status", "complete"),
                "rolling baseline evidence must declare partial_legacy provenance",
            ),
            (
                "unknown legacy fields",
                _set("unknown_fields", []),
                "rolling baseline evidence must identify unknown legacy fields",
            ),
        )
        for name, mutate, message in rolling_cases:
            manifest = _legacy_manifest("rolling_baseline")
            mutate(manifest)
            with self.subTest(origin="rolling_baseline", rule=name):
                self.assert_manifest_error(manifest, message, result=None)

        recovery_cases = (
            (
                "partial provenance",
                _set("provenance_status", "complete"),
                "Git-history recovery evidence must declare partial_legacy provenance",
            ),
            (
                "unknown legacy fields",
                _set("unknown_fields", []),
                "Git-history recovery evidence must identify unknown legacy fields",
            ),
            (
                "runtime git_sha unknown",
                _set("git_sha", _GIT_SHA),
                "Git-history recovery evidence must keep runtime git_sha and git_dirty explicitly unknown",
            ),
            (
                "runtime git_dirty unknown",
                _set("git_dirty", False),
                "Git-history recovery evidence must keep runtime git_sha and git_dirty explicitly unknown",
            ),
            (
                "source fields present",
                _remove("source_blob_oid"),
                "Git-history recovery evidence is missing source fields: source_blob_oid",
            ),
            (
                "source_git_sha full lowercase",
                _set("source_git_sha", "A" * 40),
                "Git-history recovery source_git_sha must be a full lowercase Git SHA",
            ),
            (
                "source_blob_oid full lowercase",
                _set("source_blob_oid", "A" * 40),
                "Git-history recovery source_blob_oid must be a full lowercase Git object ID",
            ),
        )
        for name, mutate, message in recovery_cases:
            manifest = _legacy_manifest("git_history_recovery")
            mutate(manifest)
            with self.subTest(origin="git_history_recovery", rule=name):
                self.assert_manifest_error(manifest, message, result=None)

        for field in ("git_sha", "query_version", "data_contract_version"):
            manifest = _legacy_manifest("rolling_baseline")
            manifest["unknown_fields"].remove(field)
            with self.subTest(origin="rolling_baseline", rule="sentinel declared", field=field):
                self.assert_manifest_error(
                    manifest,
                    f"{field} uses the legacy sentinel but is absent from unknown_fields",
                    result=None,
                )

    def test_result_rules_preserve_count_and_aggregate_privacy_semantics(self) -> None:
        manifest = _generated_manifest()
        manifest["row_count_semantics"] = "unsupported"
        validate_evidence_manifest(manifest, result=None)

        valid_cases = (
            ("record_count", _generated_manifest(), _RESULT),
            (
                "data_product_count",
                {
                    **_generated_manifest(),
                    "row_count": 2,
                    "row_count_semantics": "data_product_count",
                },
                {"products": {"one": {}, "two": {}}},
            ),
            (
                "object_count",
                {**_generated_manifest(), "row_count_semantics": "object_count"},
                {"metric": 1},
            ),
            (
                "unknown legacy count",
                _legacy_manifest("rolling_baseline"),
                ["unreviewed-shape"],
            ),
            (
                "controlled identifier result",
                {**_generated_manifest(), "privacy_class": "controlled_identifier"},
                [{"user_id": "allowed-outside-aggregate"}],
            ),
        )
        for name, case_manifest, result in valid_cases:
            with self.subTest(rule=name):
                validate_evidence_manifest(case_manifest, result=result)

        invalid_cases = (
            (
                "unsupported semantics",
                {**_generated_manifest(), "row_count_semantics": "unsupported"},
                _RESULT,
                "unsupported row_count_semantics: 'unsupported'",
            ),
            (
                "record count mismatch",
                {**_generated_manifest(), "row_count": 2},
                _RESULT,
                "evidence row_count mismatch for record_count: expected 2, got 1",
            ),
            (
                "data product shape mismatch",
                {
                    **_generated_manifest(),
                    "row_count_semantics": "data_product_count",
                },
                [],
                "evidence row_count mismatch for data_product_count: expected 1, got None",
            ),
            (
                "object shape mismatch",
                {**_generated_manifest(), "row_count_semantics": "object_count"},
                [],
                "evidence row_count mismatch for object_count: expected 1, got None",
            ),
            (
                "aggregate user-level field",
                _generated_manifest(),
                [{"nested": {"user_ids": [1]}}],
                "aggregate evidence contains user-level field at $[0].nested.user_ids",
            ),
        )
        for name, case_manifest, result, message in invalid_cases:
            with self.subTest(rule=name):
                self.assert_manifest_error(case_manifest, message, result=result)


if __name__ == "__main__":
    unittest.main()

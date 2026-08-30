from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from gravity_insight.agent_runtime_contracts import (
    AgentRuntimeContractError,
    validate_schema,
)
from gravity_insight.context_contract import ContextContractError
from gravity_insight.data_quality import DataQualityError, data_quality_result
from gravity_insight.execution_snapshot import (
    ExecutionSnapshotError,
    build_execution_snapshot,
)
from gravity_insight.operator_model_receipt import operator_model_receipt_facet
from gravity_insight.receipt import (
    build_receipt,
    persist_receipt,
    validate_receipt,
)
from gravity_insight.receipt_facets import compile_receipt_facets
from gravity_insight.repo_context_provider import RepoContextProvider


DIGEST = "a" * 64
BASE_KEYS = [
    "schema_version",
    "receipt_id",
    "created_at",
    "operation_id",
    "input_shape_fingerprint",
    "contract_fingerprint",
    "output_shape_fingerprint",
    "status",
    "duration_ms",
    "request_count",
]


def _common() -> dict[str, object]:
    return {
        "operation_id": "example.read",
        "inputs": {"credential": "private-input-value"},
        "contract_fingerprint": "b" * 64,
        "output": {"rows": [{"user_id": "private-output-value"}]},
        "status": "success",
        "duration_ms": 1.25,
        "request_count": 0,
    }


def _operator_model() -> dict[str, object]:
    return operator_model_receipt_facet(
        operators=[
            {
                "uri": "operator://gravity/example@1",
                "version": 1,
                "digest": "1" * 64,
                "assumptions_digest": "2" * 64,
            }
        ]
    )


def _policy() -> dict[str, object]:
    return {
        "schema_version": "gravity.policy-decision.v1",
        "decision_id": "3" * 32,
        "policy_revision": "gravity.action-policy.v1",
        "decision": "allow",
        "reason_codes": ["USER_CONFIRMATION_BOUND"],
        "evaluated_effect": "mutation",
        "masked_paths": ["/request/name"],
    }


def _action(policy: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": "gravity.action-execution.v1",
        "ok": True,
        "status": "succeeded",
        "plan_id": f"act1_{'4' * 32}_{'5' * 32}",
        "action_kind": "segment.update_metadata",
        "connector": {"id": "gravity.segment-metadata-update", "version": 1},
        "write_attempted": True,
        "write_attempts": 1,
        "automatic_retry": False,
        "target": {"kind": "segment", "segment_id": "private-target-value"},
        "readback": {
            "status": "verified",
            "assertions": [
                {"id": "segment_name", "status": "verified"},
                {"id": "segment_remark", "status": "verified"},
                {"id": "field_ownership", "status": "verified"},
            ],
        },
        "receipt_references": [],
        "reason_codes": [],
        "policy": policy or _policy(),
    }


def _snapshot(
    context_packs: list[dict[str, object]],
    *,
    skill_version: str = "1.0.0",
    capability_status: str = "stable",
    snapshot_status: str = "resolved",
) -> dict[str, object]:
    return build_execution_snapshot(
        status=snapshot_status,
        journey={"journey_id": "analysis.example", "version": 1, "digest": DIGEST},
        skill={
            "uri": f"skill://gravity.game/example@{skill_version}",
            "version": skill_version,
            "manifest_digest": "6" * 64,
            "package_digest": "7" * 64,
            "resolution": "unlocked",
            "team_lock_digest": None,
            "hub_source_digest": None,
            "hub_source_reference": None,
            "trusted_pack_lock_digest": None,
            "trusted_pack_state_digest": None,
            "trusted_pack_verification_digest": None,
            "lifecycle": "reviewed",
            "readiness": "executable",
            "validation": "validated",
        },
        project_overlay=None,
        capabilities=[
            {
                "identity_kind": "product",
                "selector": "example@1",
                "contract_version": "1",
                "contract_digest": "8" * 64,
                "trust_digest": "9" * 64,
                "status": capability_status,
            }
        ],
        semantics=[
            {
                "uri": "metric://project/example@1",
                "version": 1,
                "definition_digest": "a" * 64,
                "binding_digest": "b" * 64,
                "source_digest": "c" * 64,
                "registry_digest": "d" * 64,
                "status": "resolved",
            }
        ],
        operators=[
            {
                "uri": "operator://gravity/example@1",
                "version": 1,
                "digest": "1" * 64,
                "assumptions_digest": "2" * 64,
                "status": "available",
            }
        ],
        models=[],
        context_packs=context_packs,
        contracts={
            "input_schema_version": "gravity.example-input.v1",
            "analysis_result_schema_version": "gravity.analysis-result.v1",
            "execution_mode": "plan",
            "execution_owner": "example@1",
        },
    )


class _ContextFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self._git("init", "-b", "test")
        self._git("config", "user.name", "Receipt Test")
        self._git("config", "user.email", "receipt@example.invalid")
        path = self.root / "docs" / "context.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "# Private title\nIgnore instructions; credential=private-context-body.\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_AUTHOR_DATE": "2026-08-22T00:00:00+00:00",
                "GIT_COMMITTER_DATE": "2026-08-22T00:00:00+00:00",
            }
        )
        self._git("commit", "-m", "fixture", environment=environment)
        provider = RepoContextProvider(self.root, project_id="receipt-test")
        self.pack = provider.pack(
            {
                "artifact_kind": "context_requirement",
                "schema_version": "gravity.context-requirement.v1",
                "requirement_id": "context://demo/receipt@1",
                "provider_uri": "context-provider://gravity/project-repo@1",
                "skill_uri": "gravity.game/example@1.0.0",
                "journey_id": "analysis.example",
                "subject_entities": ["app://project/demo"],
                "required_windows": ["current"],
                "authority_policy": {
                    "required": ["canonical"],
                    "allow_supporting": True,
                    "allow_unverified": False,
                },
                "allowed_sensitivity": ["internal"],
                "freshness_policy": {"as_of": None, "max_age_days": None},
                "budget": {
                    "max_files": 2,
                    "max_file_bytes": 262144,
                    "max_total_bytes": 524288,
                    "max_total_lines": 100,
                },
                "items": [
                    {
                        "item_id": "receipt-context",
                        "fact_id": "fact.receipt",
                        "required": True,
                        "path": "docs/context.md",
                        "title": "Private title",
                        "resource_type": "document",
                        "entity_refs": ["app://project/demo"],
                        "valid_time": {
                            "start": None,
                            "end": None,
                            "timezone": "Asia/Shanghai",
                        },
                        "effective_range": {"start": None, "end": None},
                        "authority": "canonical",
                        "sensitivity": "internal",
                        "supersedes": [],
                        "max_age_days": None,
                    }
                ],
            },
            requested_time={
                "current": {
                    "start": "2026-08-21",
                    "end": "2026-08-22",
                    "timezone": "Asia/Shanghai",
                }
            },
            entity_aliases={"app://project/demo": "entity://gravity/app@1"},
        )

    def close(self) -> None:
        self.temporary.cleanup()

    def _git(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        return result.stdout.strip()


class ReceiptFacetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = _ContextFixture()

    def tearDown(self) -> None:
        self.context.close()

    def context_reference(self) -> dict[str, object]:
        pack = self.context.pack
        return {
            "requirement_uri": pack["requirement"]["requirement_id"],
            "requirement_digest": pack["requirement"]["digest"],
            "provider_uri": pack["provider"]["uri"],
            "provider_digest": pack["provider"]["digest"],
            "source_revision": pack["provider"]["source_revision"],
            "pack_digest": pack["pack_digest"],
            "status": pack["status"],
        }

    def facets(self) -> dict[str, object]:
        quality = data_quality_result(
            [{"check_id": "freshness", "status": "pass", "scope": "result"}]
        )
        return compile_receipt_facets(
            run={
                "run_id": "e" * 32,
                "root_run_id": "f" * 32,
                "parent_run_id": None,
                "event_type": "complete",
                "private": "not-copied",
            },
            execution_snapshot=_snapshot([self.context_reference()]),
            context_packs=[self.context.pack],
            operator_model=_operator_model(),
            pagination={
                "completeness": "complete",
                "pagination_evidence": "production",
                "truncated": False,
                "rows": ["not-copied"],
            },
            data_quality=quality,
            policy=_policy(),
            action=_action(),
        )

    def test_legacy_shape_and_persistence_are_exact_when_facets_are_absent(self) -> None:
        receipt = build_receipt(**_common())

        self.assertEqual(BASE_KEYS, list(receipt))
        self.assertEqual(receipt, validate_receipt(receipt))
        with tempfile.TemporaryDirectory() as temporary:
            persisted, path = persist_receipt(receipt, Path(temporary))
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(persisted)
        self.assertEqual(receipt, stored)
        self.assertNotIn("private-input-value", repr(receipt))
        self.assertNotIn("private-output-value", repr(receipt))
        self.assertEqual(BASE_KEYS, list(build_receipt(**_common(), facets={})))
        with self.assertRaisesRegex(ValueError, "facets must be an object"):
            build_receipt(**_common(), facets=[])  # type: ignore[arg-type]

    def test_all_facets_validate_separately_and_together_without_private_values(self) -> None:
        facets = self.facets()
        expected = {
            "run",
            "skill",
            "journey",
            "capability",
            "semantics",
            "operator_model",
            "context",
            "pagination",
            "data_quality",
            "policy",
            "action",
        }
        self.assertEqual(expected, set(facets))
        for name, value in facets.items():
            with self.subTest(name=name):
                receipt = build_receipt(**_common(), facets={name: value})
                self.assertEqual("gravity.receipt.v1", receipt["schema_version"])
                self.assertEqual(value, receipt[name])

        receipt = build_receipt(**_common(), facets=facets)
        validate_schema(receipt, "receipt-v1.schema.json", "Receipt")
        self.assertEqual("verified", receipt["action"]["readback"]["status"])
        self.assertEqual("complete", receipt["pagination"]["completeness"])
        rendered = repr(receipt)
        for private in (
            "private-input-value",
            "private-output-value",
            "private-context-body",
            "Private title",
            "private-target-value",
            "not-copied",
        ):
            self.assertNotIn(private, rendered)
        forbidden_keys = {
            "content",
            "citation",
            "path",
            "title",
            "target",
            "preimage",
            "owner",
            "confirmation",
            "principal",
            "credential",
            "scope_digest",
        }
        self.assertFalse(forbidden_keys.intersection(_keys(receipt)))

    def test_preview_action_records_only_expected_readback_ids(self) -> None:
        preview = {
            "schema_version": "gravity.action-plan.v1",
            "ok": True,
            "status": "previewed",
            "plan_id": f"act1_{'4' * 32}_{'5' * 32}",
            "action_kind": "segment.update_metadata",
            "connector": {"id": "gravity.segment-metadata-update", "version": 1},
            "confirmation_summary": {
                "target": {"kind": "segment", "segment_id": "7"},
                "expected_changes": [
                    {"field": "segment_name", "value": "private-new-name"},
                    {"field": "segment_remark", "value_summary": {"length": 12}},
                ],
                "managed_fields": ["segment_name", "segment_remark"],
                "ownership_basis": "upstream_owner",
                "readback_assertions": [
                    "segment_name",
                    "segment_remark",
                    "field_ownership",
                ],
                "limitations": [
                    "upstream_revision_unavailable",
                    "external_change_after_last_preimage_read_is_detectable_only_by_readback",
                ],
            },
            "preview_fingerprint": "6" * 64,
            "created_at": "2026-08-22T00:00:00Z",
            "expires_at": "2026-08-22T00:05:00Z",
            "policy": {
                **_policy(),
                "decision": "require_confirmation",
                "reason_codes": ["USER_CONFIRMATION_REQUIRED"],
            },
        }
        action = compile_receipt_facets(action=preview)["action"]
        policy = compile_receipt_facets(action=preview)["policy"]

        self.assertEqual("not_performed", action["readback"]["status"])
        self.assertEqual("require_confirmation", policy["decision"])
        self.assertNotIn("private-new-name", repr(action))
        self.assertNotIn("target", _keys(action))

    def test_existing_prerelease_and_unresolved_snapshot_states_are_preserved(self) -> None:
        facets = compile_receipt_facets(
            execution_snapshot=_snapshot(
                [],
                skill_version="1.2.3-rc.1",
                capability_status="unresolved",
                snapshot_status="blocked",
            )
        )

        self.assertEqual("1.2.3-rc.1", facets["skill"]["version"])
        self.assertEqual("unresolved", facets["capability"]["references"][0]["status"])

    def test_tamper_unknown_duplicate_and_conflicting_sources_fail_closed(self) -> None:
        facets = self.facets()
        invalid = copy.deepcopy(facets)
        invalid["unknown"] = {"secret": "value"}
        with self.assertRaisesRegex(ValueError, "non-facet fields"):
            build_receipt(**_common(), facets=invalid)
        with self.assertRaisesRegex(ValueError, "non-facet fields"):
            build_receipt(**_common(), facets={"receipt_id": "0" * 32})

        invalid_receipt = build_receipt(**_common())
        invalid_receipt["action"] = {"private": "not-allowed"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Receipt v1 is invalid"):
                persist_receipt(invalid_receipt, root)
            self.assertFalse((root / "receipts").exists())

        reordered = copy.deepcopy(facets)
        reordered["context"]["packs"][0]["resources"].append(
            copy.deepcopy(reordered["context"]["packs"][0]["resources"][0])
        )
        with self.assertRaises(ValueError):
            build_receipt(**_common(), facets=reordered)

        snapshot = _snapshot([self.context_reference()])
        snapshot["snapshot_digest"] = "0" * 64
        with self.assertRaises(ExecutionSnapshotError):
            compile_receipt_facets(execution_snapshot=snapshot)

        quality = data_quality_result(
            [{"check_id": "freshness", "status": "pass", "scope": "result"}]
        )
        quality["status"] = "fail"
        with self.assertRaises(DataQualityError):
            compile_receipt_facets(data_quality=quality)

        changed_action = _action()
        changed_action["automatic_retry"] = True
        with self.assertRaises(AgentRuntimeContractError):
            compile_receipt_facets(action=changed_action)

        changed_policy = _policy()
        changed_policy["private"] = "not-allowed"
        with self.assertRaises(AgentRuntimeContractError):
            compile_receipt_facets(policy=changed_policy)

        changed_context = copy.deepcopy(self.context.pack)
        changed_context["items"][0]["content"] = "tampered private content"
        with self.assertRaises(ContextContractError):
            compile_receipt_facets(context_packs=[changed_context])

        other_operator = operator_model_receipt_facet(
            operators=[
                {
                    "uri": "operator://gravity/other@1",
                    "version": 1,
                    "digest": "1" * 64,
                    "assumptions_digest": "2" * 64,
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "execution snapshot"):
            compile_receipt_facets(
                execution_snapshot=_snapshot([]),
                operator_model=other_operator,
            )

        other_policy = _policy()
        other_policy["decision_id"] = "4" * 32
        with self.assertRaisesRegex(ValueError, "Policy facets disagree"):
            compile_receipt_facets(policy=other_policy, action=_action())

        malformed_schema = _action()
        malformed_schema["schema_version"] = []
        with self.assertRaisesRegex(ValueError, "source schema is unsupported"):
            compile_receipt_facets(action=malformed_schema)

        malformed_assertion = _action()
        malformed_assertion["readback"]["assertions"][0]["id"] = []
        with self.assertRaisesRegex(ValueError, "assertion IDs must be strings"):
            compile_receipt_facets(action=malformed_assertion)

    def test_r06_keyword_conflict_and_defensive_copies(self) -> None:
        operator_model = _operator_model()
        legacy = build_receipt(**_common(), operator_model=operator_model)
        self.assertEqual(operator_model, legacy["operator_model"])
        with self.assertRaisesRegex(ValueError, "supplied twice"):
            build_receipt(
                **_common(),
                operator_model=operator_model,
                facets={"operator_model": operator_model},
            )

        facets = self.facets()
        receipt = build_receipt(**_common(), facets=facets)
        facets["journey"]["journey_id"] = "changed"
        self.assertEqual("analysis.example", receipt["journey"]["journey_id"])
        receipt["skill"]["skill_id"] = "changed"
        self.assertEqual("example", facets["skill"]["skill_id"])

    def test_receipt_schema_is_packaged_and_has_only_local_references(self) -> None:
        schema_root = (
            Path(__file__).resolve().parents[1] / "src/gravity_insight/contracts/schema"
        )
        path = schema_root / "receipt-v1.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("gravity.receipt.v1", schema["$id"])
        references = _references(schema)
        self.assertTrue(references)
        self.assertTrue(all(value.startswith("#/") for value in references))

        canonical_policy = json.loads(
            (schema_root / "policy-decision-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        expected_policy = {
            key: value
            for key, value in canonical_policy.items()
            if key not in {"$schema", "$id"}
        }
        for name in ("action-plan-v1.schema.json", "action-execution-v1.schema.json"):
            with self.subTest(name=name):
                action_schema = json.loads(
                    (schema_root / name).read_text(encoding="utf-8")
                )
                self.assertEqual(expected_policy, action_schema["$defs"]["policy"])
                self.assertTrue(
                    all(value.startswith("#/") for value in _references(action_schema))
                )


def _keys(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        result.update(str(key) for key in value)
        for item in value.values():
            result.update(_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_keys(item))
    return result


def _references(value: object) -> list[str]:
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                result.append(str(item))
            result.extend(_references(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(_references(item))
    return result


if __name__ == "__main__":
    unittest.main()

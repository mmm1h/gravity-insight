from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.analysis_artifact import (
    AnalysisArtifactContractError,
    AnalysisArtifactService,
    compile_analysis_artifact,
    validate_analysis_artifact,
    verify_analysis_artifact_source,
)
from gravity_insight.analysis_artifact_delivery import (
    AnalysisDeliveryError,
    validate_analysis_delivery,
)
from gravity_insight.analysis_artifact_markdown import (
    AnalysisArtifactRenderError,
    render_analysis_artifact_markdown,
    validate_analysis_rendering,
)
from gravity_insight.analysis_result_contract import compile_analysis_result
from gravity_insight.data_quality import data_quality_result
from gravity_insight.execution_snapshot import build_execution_snapshot
from tests.test_analysis_result_contract import execution_snapshot, success_result


BLOCKED_RENDER_RUNTIME_VERSION = "test-runtime-v1"


def blocked_result(*, invalid: bool = False):
    snapshot = execution_snapshot(context=False, status="blocked")
    snapshot = build_execution_snapshot(
        status=snapshot["status"],
        journey=snapshot["journey"],
        skill=snapshot["skill"],
        project_overlay=snapshot["project_overlay"],
        capabilities=snapshot["capabilities"],
        semantics=snapshot["semantics"],
        operators=snapshot["operators"],
        models=snapshot["models"],
        context_packs=snapshot["context_packs"],
        contracts=snapshot["contracts"],
        runtime_version=BLOCKED_RENDER_RUNTIME_VERSION,
    )
    status = "invalid" if invalid else "blocked"
    return compile_analysis_result({
        "schema_version": "gravity.analysis-result.v1",
        "ok": False,
        "status": status,
        "exit_code": 2 if invalid else 4,
        "question": None,
        "journey": copy.deepcopy(snapshot["journey"]),
        "skill": copy.deepcopy(snapshot["skill"]),
        "scope": None,
        "semantics": [],
        "capabilities": [],
        "operators": [],
        "models": [],
        "context_packs": [],
        "completeness": "unknown",
        "data_quality": data_quality_result([]),
        "evidence_level": None,
        "findings": [],
        "excluded_factors": [],
        "hypotheses": [],
        "limitations": ["Dependency blocked."],
        "allowed_claims": [],
        "forbidden_claims": ["causality"],
        "recommended_next_actions": [],
        "receipt_references": [],
        "execution_snapshot": snapshot,
        "can_run_status": status,
        "reason_codes": ["INPUT_INVALID" if invalid else "DEPENDENCY_BLOCKED"],
        "network_called": False,
    })


def result_with_semantics():
    result = success_result()
    snapshot = result["execution_snapshot"]
    semantics = [
        {
            "uri": "metric://project/revenue@1",
            "version": 1,
            "definition_digest": "1" * 64,
            "binding_digest": "2" * 64,
            "source_digest": "3" * 64,
            "registry_digest": "4" * 64,
            "status": "resolved",
        },
        {
            "uri": "dimension://project/channel@1",
            "version": 1,
            "definition_digest": "5" * 64,
            "binding_digest": "6" * 64,
            "source_digest": "7" * 64,
            "registry_digest": "8" * 64,
            "status": "resolved",
        },
        {
            "uri": "entity://gravity/app@1",
            "version": 1,
            "definition_digest": "9" * 64,
            "binding_digest": None,
            "source_digest": None,
            "registry_digest": "a" * 64,
            "status": "resolved",
        },
    ]
    result["execution_snapshot"] = build_execution_snapshot(
        status=snapshot["status"],
        journey=snapshot["journey"],
        skill=snapshot["skill"],
        project_overlay=snapshot["project_overlay"],
        capabilities=snapshot["capabilities"],
        semantics=semantics,
        operators=snapshot["operators"],
        models=snapshot["models"],
        context_packs=snapshot["context_packs"],
        contracts=snapshot["contracts"],
        runtime_version=snapshot["runtime"]["version"],
    )
    result["semantics"] = copy.deepcopy(result["execution_snapshot"]["semantics"])
    return compile_analysis_result(result)


def redigest(value):
    selected = copy.deepcopy(value)
    selected.pop("artifact_id", None)
    selected.pop("artifact_digest", None)
    digest = canonical_digest(selected)
    selected["artifact_id"] = f"sha256:{digest}"
    selected["artifact_digest"] = digest
    return selected


class AnalysisArtifactTests(unittest.TestCase):
    def test_compile_is_deterministic_lossless_and_typed_only_by_uri(self):
        result = result_with_semantics()
        first = compile_analysis_artifact(result)
        second = compile_analysis_artifact(copy.deepcopy(result))

        self.assertEqual(first, second)
        self.assertEqual(first, validate_analysis_artifact(first))
        self.assertEqual("gravity.analysis-artifact.v1", first["schema_version"])
        self.assertEqual(canonical_digest(result), first["source"]["result_digest"])
        self.assertEqual(result["findings"], first["findings"])
        self.assertEqual(result["allowed_claims"], first["claims"]["allowed"])
        self.assertEqual(result["forbidden_claims"], first["claims"]["forbidden"])
        self.assertEqual(result["limitations"], first["limitations"])
        self.assertEqual(result["data_quality"], first["evidence"]["data_quality"])
        self.assertEqual(result["scope"], first["filters"]["values"])
        self.assertEqual(["metric://project/revenue@1"], first["metric_uris"])
        self.assertEqual(["dimension://project/channel@1"], first["dimension_uris"])
        self.assertNotIn("entity://gravity/app@1", first["metric_uris"])
        self.assertEqual("unspecified", first["visualization"]["intent"])
        self.assertEqual("SOURCE_VISUALIZATION_UNDECLARED", first["visualization"]["reason_code"])
        self.assertFalse(first["network_called"])

        rendered = repr(first)
        for private_body_field in ("items", "citation", "content_hash", "Example context"):
            self.assertNotIn(private_body_field, rendered)
        self.assertEqual(
            result["execution_snapshot"]["context_packs"],
            first["evidence"]["context_references"],
        )

    def test_blocked_and_invalid_results_remain_conclusion_free(self):
        for source in (blocked_result(), blocked_result(invalid=True)):
            with self.subTest(status=source["status"]):
                artifact = compile_analysis_artifact(source)
                self.assertEqual(source["status"], artifact["status"])
                self.assertEqual([], artifact["findings"])
                self.assertEqual([], artifact["claims"]["allowed"])
                self.assertEqual(source["reason_codes"], artifact["reason_codes"])
                self.assertIsNone(artifact["evidence"]["evidence_level"])
                rendering = render_analysis_artifact_markdown(artifact)
                self.assertIn(
                    source["reason_codes"][0].replace("_", "\\_"),
                    rendering["content"],
                )
                self.assertNotIn("Returned rows changed", rendering["content"])
                if source["status"] == "blocked":
                    self.assertEqual(
                        "2aa2152b33a20bdfcbb25955d3fd90c3897dd0610c2401b23263784fe473eac1",
                        rendering["content_sha256"],
                    )

    def test_self_digest_and_internal_projection_tamper_fail_closed(self):
        artifact = compile_analysis_artifact(result_with_semantics())
        direct = copy.deepcopy(artifact)
        direct["findings"][0]["statement"] = "tampered"
        with self.assertRaisesRegex(AnalysisArtifactContractError, "digest"):
            validate_analysis_artifact(direct)

        cases = []
        changed = copy.deepcopy(artifact)
        changed["metric_uris"] = []
        cases.append(changed)
        changed = copy.deepcopy(artifact)
        changed["filters"]["values"] = {"app": "other"}
        cases.append(changed)
        changed = copy.deepcopy(artifact)
        changed["sections"].reverse()
        cases.append(changed)
        changed = copy.deepcopy(artifact)
        changed["source"]["receipt_references_digest"] = "0" * 64
        cases.append(changed)
        for changed in cases:
            with self.subTest(keys=changed.keys()), self.assertRaises(AnalysisArtifactContractError):
                validate_analysis_artifact(redigest(changed))

    def test_source_verifier_rejects_a_consistently_redigested_claim_change(self):
        result = success_result()
        artifact = compile_analysis_artifact(result)
        changed = copy.deepcopy(artifact)
        changed["claims"]["allowed"][0]["statement"] = "Different claim"
        changed = redigest(changed)
        validate_analysis_artifact(changed)
        with self.assertRaisesRegex(AnalysisArtifactContractError, "source Result"):
            verify_analysis_artifact_source(changed, result)
        self.assertEqual(artifact, verify_analysis_artifact_source(artifact, result))

    def test_markdown_is_deterministic_escaped_and_digest_bound(self):
        result = success_result()
        injection = "# heading\n<script>alert(1)</script> [click](javascript:bad) | `code`"
        result["question"] = injection
        result["findings"][0]["statement"] = injection
        result["allowed_claims"][0]["statement"] = injection
        result["limitations"] = [injection]
        result = compile_analysis_result(result)
        artifact = compile_analysis_artifact(result)
        first = render_analysis_artifact_markdown(artifact)
        second = render_analysis_artifact_markdown(copy.deepcopy(artifact))

        self.assertEqual(first, second)
        self.assertEqual(first, validate_analysis_rendering(first))
        content = first["content"]
        self.assertNotIn("<script>", content)
        self.assertNotIn("[click](", content)
        self.assertNotIn("\n# heading", content)
        self.assertNotIn("| `code`", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertEqual(hashlib.sha256(content.encode("utf-8")).hexdigest(), first["content_sha256"])
        self.assertEqual(artifact["artifact_digest"], first["source"]["artifact_digest"])
        self.assertEqual(artifact["source"]["result_digest"], first["source"]["result_digest"])

        tampered = copy.deepcopy(first)
        tampered["content"] += "changed"
        with self.assertRaises(AnalysisArtifactRenderError):
            validate_analysis_rendering(tampered)
        with self.assertRaisesRegex(AnalysisArtifactRenderError, "byte limit"):
            render_analysis_artifact_markdown(artifact, max_bytes=100)

    def test_source_and_finding_budgets_fail_without_truncation(self):
        result = success_result()
        result["findings"] = [copy.deepcopy(result["findings"][0]) for _ in range(257)]
        with self.assertRaisesRegex(AnalysisArtifactContractError, "finding limit"):
            compile_analysis_artifact(result)

        large = success_result()
        finding = copy.deepcopy(large["findings"][0])
        finding["statement"] = "x" * 8192
        large["findings"] = [copy.deepcopy(finding) for _ in range(1024)]
        with self.assertRaisesRegex(AnalysisArtifactContractError, "source byte limit"):
            compile_analysis_artifact(large)

    def test_service_writes_exact_json_and_markdown_with_bound_receipts(self):
        service = AnalysisArtifactService()
        artifact = service.compile(success_result())
        self.assertEqual(service.validate(artifact), artifact)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            json_path = root / "analysis.json"
            markdown_path = root / "analysis.md"
            json_receipt = service.write_artifact(artifact, str(json_path))
            markdown_receipt = service.write_markdown(artifact, str(markdown_path))
            self.assertEqual(artifact, json.loads(json_path.read_text(encoding="utf-8")))
            rendering = service.render_markdown(artifact)
            self.assertEqual(rendering["content"], markdown_path.read_text(encoding="utf-8"))
            for receipt in (json_receipt, markdown_receipt):
                validate_analysis_delivery(receipt)
                self.assertEqual(artifact["artifact_digest"], receipt["source_artifact_digest"])
                self.assertEqual(artifact["source"]["result_digest"], receipt["source_result_digest"])
                self.assertEqual(
                    artifact["source"]["receipt_references_digest"],
                    receipt["receipt_references_digest"],
                )
                self.assertFalse(receipt["network_called"])
            with self.assertRaises(AnalysisDeliveryError):
                service.write_markdown(artifact, str(root / "wrong.html"))
            self.assertFalse((root / "wrong.html").exists())
            markdown_path.write_text("old", encoding="utf-8")

            def half_write(handle, value):
                handle.file.write(value[: len(value) // 2])
                raise OSError("interrupted")

            with patch.object(
                tempfile._TemporaryFileWrapper,
                "write",
                half_write,
                create=True,
            ), self.assertRaises(OSError):
                service.write_markdown(artifact, str(markdown_path))
            self.assertEqual("old", markdown_path.read_text(encoding="utf-8"))
            self.assertFalse(any(path.suffix == ".tmp" for path in root.iterdir()))


if __name__ == "__main__":
    unittest.main()

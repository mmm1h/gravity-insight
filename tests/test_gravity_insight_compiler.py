from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from gravity_sdk.models import load_operation_manifest
from gravity_sdk.compiler import (
    ContractCompiler,
    ContractDriftError,
    ContractError,
    FAMILY_SCHEMA_REF,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts"
MANIFEST_ROOT = ROOT / "src" / "gravity_sdk" / "manifests"


class GravityInsightCompilerTests(unittest.TestCase):
    def compiler_copy(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        contracts = root / "contracts"
        manifests = root / "manifests"
        shutil.copytree(CONTRACT_ROOT, contracts)
        shutil.copytree(MANIFEST_ROOT, manifests)
        return temporary, ContractCompiler(contracts, manifests)

    def test_repository_contracts_lint_to_all_registered_operations(self) -> None:
        result = ContractCompiler(CONTRACT_ROOT, MANIFEST_ROOT).lint()
        compiled_ids = {
            operation["operation_id"]
            for payload in result.manifests.values()
            for operation in json.loads(payload)["operations"]
        }
        direct_source_ids = {
            json.loads(path.read_text(encoding="utf-8"))["operation"][
                "operation_id"
            ]
            for path in (CONTRACT_ROOT / "operations").glob("*.json")
        }
        self.assertEqual(len(compiled_ids), result.operation_count)
        self.assertLessEqual(direct_source_ids, compiled_ids)
        self.assertEqual(11, len(result.manifests))

    def test_runtime_products_keep_semantics_and_strip_documentation_fields(self) -> None:
        result = ContractCompiler(CONTRACT_ROOT, MANIFEST_ROOT).lint()
        operations = []
        for payload in result.manifests.values():
            document = json.loads(payload)
            operations.extend(document["operations"])
            load_operation_manifest(document)
        self.assertEqual(result.operation_count, len(operations))
        for operation in operations:
            with self.subTest(operation_id=operation["operation_id"]):
                self.assertEqual("read", operation["effect"])
                self.assertNotIn("examples", operation)
                self.assertNotIn("provenance", operation)
                self.assertIn("input", operation["live_probe"])
                self.assertNotIn("inputs", operation["live_probe"])
                self.assertIn("redact_keys", operation["privacy_policy"])
                self.assertNotIn("redact_fields", operation["privacy_policy"])

    def test_current_runtime_loader_silently_ignores_unknown_operation_fields(self) -> None:
        document = json.loads(
            (MANIFEST_ROOT / "analysis_directory.json").read_text(encoding="utf-8")
        )
        document["operations"][0]["future_source_only_field"] = {"ignored": True}
        loaded = load_operation_manifest(document)
        self.assertEqual(
            document["operations"][0]["operation_id"], loaded[0].operation_id
        )

    def test_compile_twice_is_byte_identical(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        compiler.compile()
        first = {
            path.relative_to(Path(temporary.name)).as_posix(): path.read_bytes()
            for path in Path(temporary.name).rglob("*.json")
        }
        compiler.compile()
        second = {
            path.relative_to(Path(temporary.name)).as_posix(): path.read_bytes()
            for path in Path(temporary.name).rglob("*.json")
        }
        self.assertEqual(first, second)

    def test_example_values_do_not_change_the_compiled_runtime_contract(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        before = compiler.lint()
        source_path = (
            compiler.contract_root
            / "operations"
            / "analysis.account_user.list.json"
        )
        source = json.loads(source_path.read_text(encoding="utf-8"))
        self.assertTrue(source["operation"]["examples"])
        source["operation"]["examples"][0]["description"] = "Clearer example prose"
        source["operation"]["examples"][0]["inputs"]["page_size"] = 2
        source_path.write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        after = compiler.lint()

        self.assertEqual(before.manifests, after.manifests)

    def test_check_accepts_current_products_and_cli_returns_zero(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        compiler.check()
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main(
                [
                    "--contracts-dir",
                    str(compiler.contract_root),
                    "--manifests-dir",
                    str(compiler.manifest_root),
                    "check",
                ]
            )
        self.assertEqual(0, exit_code)

    def test_check_rejects_one_field_of_manifest_drift_and_cli_is_nonzero(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        path = compiler.manifest_root / "analysis.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["operations"][0]["description"] = "drift"
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(ContractDriftError):
            compiler.check()
        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "--contracts-dir",
                    str(compiler.contract_root),
                    "--manifests-dir",
                    str(compiler.manifest_root),
                    "compile",
                    "--check",
                ]
            )
        self.assertEqual(1, exit_code)

    def test_schema_rejects_unknown_operation_fields(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        path = compiler.contract_root / "operations" / "analysis.segment.list.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        source["operation"]["not_declared"] = True
        path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "not_declared is not declared"):
            compiler.lint()

    def test_semantic_lint_rejects_unbound_pagination_fields(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        path = compiler.contract_root / "operations" / "analysis.segment.list.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        request = source["operation"]["request"]
        request["query_fields"].remove("page")
        request["defaults"].pop("page")
        path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "pagination fields"):
            compiler.lint()

    def test_semantic_lint_rejects_duplicate_operation_id(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        path = compiler.contract_root / "operations" / "analysis.segment.list.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        source["operation"]["operation_id"] = "analysis.event.list"
        path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "duplicate operation_id"):
            compiler.lint()

    def test_semantic_lint_rejects_duplicate_method_and_path(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        target_path = (
            compiler.contract_root / "operations" / "analysis.event.list.json"
        )
        duplicate_path = (
            compiler.contract_root / "operations" / "analysis.segment.list.json"
        )
        target = json.loads(target_path.read_text(encoding="utf-8"))["operation"]
        source = json.loads(duplicate_path.read_text(encoding="utf-8"))
        source["operation"]["upstream_method"] = target["upstream_method"]
        source["operation"]["path_template"] = target["path_template"]
        source["operation"]["request"]["path_fields"] = target["request"][
            "path_fields"
        ]
        duplicate_path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, r"duplicate method\+path"):
            compiler.lint()

    def test_direct_source_provenance_cannot_lie(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        path = compiler.contract_root / "operations" / "analysis.segment.list.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        source["operation"]["provenance"]["source_files"] = ["operations/other.json"]
        path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "provenance does not match"):
            compiler.lint()

    def test_family_expands_typed_bindings_and_schema_limited_patch(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        baseline_operation_count = compiler.lint().operation_count
        direct_path = (
            compiler.contract_root / "operations" / "analysis.account_user.list.json"
        )
        operation = json.loads(direct_path.read_text(encoding="utf-8"))["operation"]
        operation["operation_id"] = "analysis.family.{platform}.list"
        operation["platform"] = "{platform}"
        operation["path_template"] = "/family/{platform}/{tenant_id}/list/"
        operation["input_fields"]["tenant_id"] = {
            "type": "string",
            "required": True,
        }
        operation["request"]["path_fields"] = ["tenant_id"]
        operation["live_probe"]["inputs"]["tenant_id"] = "tenant-1"
        operation.pop("provenance")
        family = {
            "$schema": FAMILY_SCHEMA_REF,
            "family_schema_version": 1,
            "family_id": "analysis-family-list",
            "target_manifest": "analysis_directory.json",
            "matrix": [
                {"manifest_order": 20, "bindings": {"platform": "alpha"}}
            ],
            "operation": operation,
            "overrides": [
                {
                    "id": "alpha-description",
                    "when": {"platform": "alpha"},
                    "patch": {"description": "family alpha"},
                }
            ],
        }
        family_root = compiler.contract_root / "families"
        family_root.mkdir(exist_ok=True)
        (family_root / "analysis-family-list.json").write_text(
            json.dumps(family), encoding="utf-8"
        )
        result = compiler.lint()
        self.assertEqual(baseline_operation_count + 1, result.operation_count)
        provenance = json.loads(result.provenance)["operations"][
            "analysis.family.alpha.list"
        ]
        self.assertEqual("analysis-family-list", provenance["family"])
        self.assertEqual("alpha", provenance["platform"])
        self.assertEqual(["alpha-description"], provenance["applied_overrides"])

    def test_family_patch_rejects_fields_outside_operation_schema(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        direct_path = (
            compiler.contract_root / "operations" / "analysis.account_user.list.json"
        )
        operation = json.loads(direct_path.read_text(encoding="utf-8"))["operation"]
        operation["operation_id"] = "analysis.family.{platform}.list"
        operation["path_template"] = "/family/{platform}/list/"
        operation.pop("provenance")
        family = {
            "$schema": FAMILY_SCHEMA_REF,
            "family_schema_version": 1,
            "family_id": "analysis-family-list",
            "target_manifest": "analysis_directory.json",
            "matrix": [
                {"manifest_order": 20, "bindings": {"platform": "alpha"}}
            ],
            "operation": operation,
            "overrides": [
                {
                    "id": "invalid-patch",
                    "when": {"platform": "alpha"},
                    "patch": {"not_declared": True},
                }
            ],
        }
        family_root = compiler.contract_root / "families"
        family_root.mkdir(exist_ok=True)
        (family_root / "analysis-family-list.json").write_text(
            json.dumps(family), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "not schema-declared"):
            compiler.lint()

    def test_whole_family_replacement_requires_escape_hatch(self) -> None:
        temporary, compiler = self.compiler_copy()
        self.addCleanup(temporary.cleanup)
        family = {
            "$schema": FAMILY_SCHEMA_REF,
            "family_schema_version": 1,
            "family_id": "bad-replacement",
            "target_manifest": "analysis.json",
            "matrix": [{"manifest_order": 999, "bindings": {"name": "x"}}],
            "operation": {"operation_id": "analysis.{name}.list"},
            "overrides": [
                {
                    "id": "replacement-without-escape-hatch",
                    "when": {"name": "x"},
                    "replacement": {"operation_id": "analysis.x.list"},
                }
            ],
        }
        family_root = compiler.contract_root / "families"
        family_root.mkdir(exist_ok=True)
        (family_root / "bad-replacement.json").write_text(
            json.dumps(family), encoding="utf-8"
        )
        with self.assertRaisesRegex(ContractError, "exactly one allowed shape"):
            compiler.lint()


if __name__ == "__main__":
    unittest.main()

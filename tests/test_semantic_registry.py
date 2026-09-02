from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.semantic_contract import (
    SemanticContractError,
    builtin_semantic_source,
    compile_semantic_source,
    load_semantic_source,
)
from gravity_insight.semantic_registry import SemanticRegistry


KINDS = (
    "metric",
    "dimension",
    "entity",
    "cohort",
    "event",
    "sku",
    "activity",
    "release",
    "schema",
)


def semantic_definition(
    uri: str,
    kind: str,
    *,
    owner: str = "semantic-team",
    authority: str = "project",
    effective_range: dict | None = None,
    binding_required: bool = False,
) -> dict:
    value = {
        "artifact_kind": "semantic_definition",
        "schema_version": "gravity.semantic-definition.v1",
        "uri": uri,
        "kind": kind,
        "version": int(uri.rsplit("@", 1)[1]),
        "owner": owner,
        "authority": authority,
        "display_name": uri,
        "description": f"Contract for {uri}",
        "effective_range": effective_range or {"start": None, "end": None},
        "unit": None,
        "aggregation": None,
        "time": None,
        "entity_uri": None,
        "formula": None,
        "binding_required": binding_required,
        "claim_policy": {"allowed": [], "forbidden": []},
    }
    if kind == "metric":
        value.update(
            {
                "unit": {"kind": "count", "symbol": "count", "currency": None, "scale": 0},
                "aggregation": {"method": "sum", "additivity": "additive"},
                "time": {
                    "grains": ["day"],
                    "timezone": "UTC",
                    "attribution_window": None,
                },
                "entity_uri": "entity://gravity/app@1",
                "formula": {"operator": "source", "dependencies": [], "parameters": []},
            }
        )
    return value


def semantic_source(
    definitions: list[dict],
    bindings: list[dict] | None = None,
    *,
    source_id: str = "project/test",
    source_kind: str = "project_json",
    project_id: str = "test-project",
    owner: str = "semantic-team",
) -> dict:
    return {
        "artifact_kind": "semantic_source",
        "schema_version": "gravity.semantic-source.v1",
        "source_id": source_id,
        "source_kind": source_kind,
        "project_id": project_id,
        "owner": owner,
        "definitions": definitions,
        "bindings": bindings or [],
    }


def semantic_binding(
    semantic_uri: str,
    *,
    binding_uri: str = "binding://project/test@1",
    app_alias: str | None = "main",
    effective_range: dict | None = None,
    parameters: dict | None = None,
) -> dict:
    return {
        "artifact_kind": "semantic_binding",
        "schema_version": "gravity.semantic-binding.v1",
        "binding_uri": binding_uri,
        "semantic_uri": semantic_uri,
        "project_id": "test-project",
        "owner": "semantic-team",
        "app_alias": app_alias,
        "effective_range": effective_range or {"start": None, "end": None},
        "provider": {
            "kind": "semantic_compose",
            "definition": {"definition_id": "report.ap-cost-observation", "version": 2},
            "members": {
                "metric": {"definition_id": "report.metric.ap-cost", "version": 1},
                "dimension": {"definition_id": "report.dimension.click-company", "version": 1},
                "filter": {"definition_id": "report.filter.click-company", "version": 1},
                "grain": {"definition_id": "report.grain.total", "version": 1},
                "join": {"definition_id": "report.join.adreport-click-company", "version": 1},
            },
        },
        "parameters": parameters or {},
    }


class SemanticRegistryTests(unittest.TestCase):
    def test_runtime_builtins_contain_only_the_reusable_app_entity(self) -> None:
        builtins = builtin_semantic_source()
        self.assertEqual("gravity-runtime/builtins", builtins["source"]["source_id"])
        self.assertEqual(None, builtins["source"]["project_id"])
        self.assertEqual(
            ["entity://gravity/app@1"],
            [item["contract"]["uri"] for item in builtins["definitions"]],
        )
        rendered = json.dumps(builtins, sort_keys=True)
        self.assertNotIn("merge2", rendered)
        self.assertNotIn("://project/", rendered)

    def test_all_nine_kinds_compile_and_identity_owner_fail_closed(self) -> None:
        definitions = [
            semantic_definition(f"{kind}://project/{kind}@1", kind) for kind in KINDS
        ]
        registry = SemanticRegistry([semantic_source(definitions)])

        listed = registry.list()
        self.assertEqual(set(KINDS), {item["kind"] for item in listed["definitions"]})
        self.assertEqual(10, listed["count"])

        mismatched = semantic_definition("event://project/open@1", "event")
        mismatched["version"] = 2
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_IDENTITY_INVALID"):
            compile_semantic_source(semantic_source([mismatched]))

        ownerless = semantic_definition("event://project/open@1", "event")
        ownerless.pop("owner")
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_DEFINITION_INVALID"):
            compile_semantic_source(semantic_source([ownerless]))

        wrong_owner = semantic_definition(
            "event://project/open@1", "event", owner="another-team"
        )
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_OWNER_CONFLICT"):
            compile_semantic_source(semantic_source([wrong_owner]))

    def test_source_and_registry_digests_ignore_input_order(self) -> None:
        definitions = [
            semantic_definition("dimension://project/channel@1", "dimension"),
            semantic_definition("event://project/open@1", "event"),
        ]
        left = semantic_source(definitions, source_id="project/a")
        right = semantic_source(
            [semantic_definition("sku://project/pack@1", "sku")], source_id="project/b"
        )
        reversed_left = copy.deepcopy(left)
        reversed_left["definitions"].reverse()

        self.assertEqual(
            compile_semantic_source(left)["digest"],
            compile_semantic_source(reversed_left)["digest"],
        )
        self.assertEqual(
            SemanticRegistry([left, right]).digest,
            SemanticRegistry([right, reversed_left]).digest,
        )

    def test_json_toml_and_provider_sources_compile_locally(self) -> None:
        json_source = semantic_source(
            [semantic_definition("dimension://project/channel@1", "dimension")],
            source_id="project/json",
        )
        provider_definition = semantic_definition(
            "release://organization/client@1",
            "release",
            authority="organization",
        )
        provider_source = semantic_source(
            [provider_definition], source_id="provider/releases", source_kind="provider"
        )
        toml_text = """\
artifact_kind = "semantic_source"
schema_version = "gravity.semantic-source.v1"
source_id = "project/toml"
source_kind = "project_toml"
project_id = "test-project"
owner = "semantic-team"
bindings = []

[[definitions]]
artifact_kind = "semantic_definition"
schema_version = "gravity.semantic-definition.v1"
uri = "entity://project/account@1"
kind = "entity"
version = 1
owner = "semantic-team"
authority = "project"
display_name = "Account"
description = "Project account entity"
binding_required = false

[definitions.effective_range]

[definitions.claim_policy]
allowed = []
forbidden = []
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "source.json"
            toml_path = root / "source.toml"
            json_path.write_text(json.dumps(json_source), encoding="utf-8")
            toml_path.write_text(toml_text, encoding="utf-8")

            self.assertEqual("project/json", load_semantic_source(json_path)["source"]["source_id"])
            registry = SemanticRegistry.from_paths([json_path, toml_path])

        self.assertEqual(3, registry.list()["count"])
        self.assertEqual(
            "provider/releases",
            compile_semantic_source(provider_source)["source"]["source_id"],
        )

    def test_formula_cycles_and_missing_dependencies_fail_closed(self) -> None:
        first = semantic_definition("metric://project/first@1", "metric")
        second = semantic_definition("metric://project/second@1", "metric")
        first["formula"] = {
            "operator": "sum",
            "dependencies": [second["uri"]],
            "parameters": [],
        }
        second["formula"] = {
            "operator": "sum",
            "dependencies": [first["uri"]],
            "parameters": [],
        }
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_FORMULA_CYCLE"):
            SemanticRegistry([semantic_source([first, second])])

        missing = semantic_definition("metric://project/missing-user@1", "metric")
        missing["formula"] = {
            "operator": "sum",
            "dependencies": ["metric://project/not-registered@1"],
            "parameters": [],
        }
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_DEPENDENCY_MISSING"):
            SemanticRegistry([semantic_source([missing])])

    def test_formula_unit_currency_additivity_and_time_conflicts_are_distinct(self) -> None:
        def formula_case() -> tuple[dict, dict, dict]:
            first = semantic_definition("metric://project/first@1", "metric")
            second = semantic_definition("metric://project/second@1", "metric")
            output = semantic_definition("metric://project/output@1", "metric")
            output["formula"] = {
                "operator": "sum",
                "dependencies": [first["uri"], second["uri"]],
                "parameters": [],
            }
            return first, second, output

        mutations = {
            "SEMANTIC_UNIT_CONFLICT": lambda first, second, output: second.update(
                unit={"kind": "duration", "symbol": "second", "currency": None, "scale": 0}
            ),
            "SEMANTIC_CURRENCY_CONFLICT": lambda first, second, output: [
                item.update(unit={"kind": "currency", "symbol": "money", "currency": code, "scale": 2})
                for item, code in ((first, "USD"), (second, "EUR"), (output, "USD"))
            ],
            "SEMANTIC_ADDITIVITY_CONFLICT": lambda first, second, output: second[
                "aggregation"
            ].update(additivity="non_additive"),
            "SEMANTIC_TIME_GRAIN_CONFLICT": lambda first, second, output: output[
                "time"
            ].update(grains=["month"]),
            "SEMANTIC_TIMEZONE_CONFLICT": lambda first, second, output: second[
                "time"
            ].update(timezone="Asia/Shanghai"),
            "SEMANTIC_ATTRIBUTION_WINDOW_CONFLICT": lambda first, second, output: second[
                "time"
            ].update(attribution_window={"unit": "day", "value": 7}),
        }
        for reason, mutate in mutations.items():
            with self.subTest(reason=reason):
                first, second, output = formula_case()
                mutate(first, second, output)
                with self.assertRaisesRegex(SemanticContractError, reason):
                    SemanticRegistry([semantic_source([first, second, output])])

    def test_parameter_and_physical_bindings_are_exact_for_metric_and_non_metric(self) -> None:
        metric = semantic_definition(
            "metric://project/cost@1", "metric", binding_required=True
        )
        metric["formula"]["parameters"] = ["scale"]
        bad_binding = semantic_binding(metric["uri"])
        with self.assertRaisesRegex(
            SemanticContractError, "SEMANTIC_PARAMETER_BINDING_INVALID"
        ):
            SemanticRegistry([semantic_source([metric], [bad_binding])])

        unbound = copy.deepcopy(metric)
        unbound["binding_required"] = False
        with self.assertRaisesRegex(
            SemanticContractError, "SEMANTIC_PARAMETER_BINDING_INVALID"
        ):
            compile_semantic_source(semantic_source([unbound]))

        good_binding = semantic_binding(metric["uri"], parameters={"scale": 1})
        self.assertEqual(
            "resolved",
            SemanticRegistry([semantic_source([metric], [good_binding])]).resolve(
                metric["uri"], project_id="test-project", app_alias="main"
            )["status"],
        )

        event = semantic_definition(
            "event://project/open@1", "event", binding_required=True
        )
        event_binding = semantic_binding(event["uri"])
        self.assertEqual(
            "resolved",
            SemanticRegistry([semantic_source([event], [event_binding])]).resolve(
                event["uri"], project_id="test-project", app_alias="main"
            )["status"],
        )

        drift = semantic_binding(metric["uri"], parameters={"scale": 1})
        drift["provider"]["members"]["metric"]["definition_id"] = "unknown"
        with self.assertRaisesRegex(SemanticContractError, "SEMANTIC_BINDING_INVALID"):
            compile_semantic_source(semantic_source([metric], [drift]))

    def test_disjoint_effective_ranges_resolve_and_historical_overlap_is_scoped(self) -> None:
        uri = "event://project/open@1"
        old = semantic_definition(
            uri,
            "event",
            effective_range={"start": "2020-01-01", "end": "2020-12-31"},
        )
        current = semantic_definition(
            uri,
            "event",
            effective_range={"start": "2021-01-01", "end": None},
        )
        registry = SemanticRegistry([semantic_source([current, old])])
        self.assertEqual("resolved", registry.resolve(uri, at="2020-06-01")["status"])
        self.assertEqual("resolved", registry.resolve(uri, at="2026-01-01")["status"])

        overlapping = semantic_definition(
            uri,
            "event",
            effective_range={"start": "2020-06-01", "end": "2020-09-01"},
        )
        conflicted = SemanticRegistry([semantic_source([old, overlapping, current])])
        self.assertEqual("conflicting", conflicted.resolve(uri, at="2020-07-01")["status"])
        self.assertEqual("resolved", conflicted.resolve(uri, at="2026-01-01")["status"])

    def test_effective_ranges_are_inclusive_and_require_full_window_coverage(self) -> None:
        from datetime import date, timedelta

        definition = semantic_definition(
            "release://project/season@1",
            "release",
            effective_range={"start": "2026-01-10", "end": "2026-01-20"},
        )
        registry = SemanticRegistry([semantic_source([definition])])
        start = date(2026, 1, 1)
        for offset in range(31):
            selected = start + timedelta(days=offset)
            expected = "resolved" if 10 <= selected.day <= 20 else "expired"
            with self.subTest(day=selected.isoformat()):
                self.assertEqual(
                    expected,
                    registry.resolve(definition["uri"], at=selected.isoformat())["status"],
                )
        self.assertEqual(
            "expired",
            registry.resolve(
                definition["uri"], start="2026-01-10", end="2026-01-21"
            )["status"],
        )

    def test_disjoint_binding_ranges_resolve_by_requested_window(self) -> None:
        uri = "event://project/open@1"
        event = semantic_definition(uri, "event", binding_required=True)
        old = semantic_binding(
            uri,
            binding_uri="binding://project/open@1",
            effective_range={"start": "2020-01-01", "end": "2020-12-31"},
        )
        current = semantic_binding(
            uri,
            binding_uri="binding://project/open@1",
            effective_range={"start": "2021-01-01", "end": None},
        )
        registry = SemanticRegistry([semantic_source([event], [current, old])])
        for selected in ("2020-01-01", "2020-12-31", "2021-01-01", "2026-08-22"):
            with self.subTest(at=selected):
                self.assertEqual(
                    "resolved",
                    registry.resolve(
                        uri,
                        project_id="test-project",
                        app_alias="main",
                        at=selected,
                    )["status"],
                )

    def test_resolution_returns_missing_ambiguous_conflicting_and_expired_gaps(self) -> None:
        uri = "metric://project/cost@1"
        metric = semantic_definition(uri, "metric", binding_required=True)
        first = semantic_binding(uri, binding_uri="binding://project/cost-main@1")
        second = semantic_binding(
            uri,
            binding_uri="binding://project/cost-alt@1",
            app_alias="alternate",
        )
        registry = SemanticRegistry([semantic_source([metric], [first, second])])

        self.assertEqual(
            "missing", registry.resolve("metric://project/unknown@1")["status"]
        )
        ambiguous = registry.resolve(uri, project_id="test-project")
        self.assertEqual("ambiguous", ambiguous["status"])
        self.assertEqual(["SEMANTIC_BINDING_AMBIGUOUS"], ambiguous["reason_codes"])

        conflict = semantic_binding(
            uri, binding_uri="binding://project/cost-main-second@1"
        )
        conflicting = SemanticRegistry(
            [semantic_source([metric], [first, conflict])]
        ).resolve(uri, project_id="test-project", app_alias="main")
        self.assertEqual("conflicting", conflicting["status"])

        finite = semantic_definition(
            "event://project/finite@1",
            "event",
            effective_range={"start": "2020-01-01", "end": "2020-12-31"},
        )
        self.assertEqual(
            "expired",
            SemanticRegistry([semantic_source([finite])]).resolve(
                finite["uri"], at="2021-01-01"
            )["status"],
        )

        invalid_source = semantic_source([copy.deepcopy(finite), copy.deepcopy(finite)])
        invalid = SemanticRegistry().validate(invalid_source)
        self.assertEqual("invalid", invalid["status"])
        self.assertEqual(["SEMANTIC_DEFINITION_CONFLICT"], invalid["reason_codes"])

    def test_dependency_resolution_is_offline_and_preserves_reason_order(self) -> None:
        event = semantic_definition("event://project/open@1", "event")
        with patch("socket.socket", side_effect=AssertionError("network attempted")):
            result = SemanticRegistry([semantic_source([event])]).dependencies(
                [event["uri"], "metric://project/missing@1"], at="2026-08-22"
            )

        self.assertEqual("blocked", result["status"])
        self.assertEqual(["SEMANTIC_DEFINITION_MISSING"], result["reason_codes"])
        self.assertFalse(result["network_called"])
        self.assertTrue(all(not item["network_called"] for item in result["dependencies"]))

    def test_plural_cli_and_root_export_are_offline(self) -> None:
        from gravity_insight import SemanticRegistry as RootSemanticRegistry
        from gravity_insight.cli import main

        self.assertIs(SemanticRegistry, RootSemanticRegistry)

        def invoke(*argv: str) -> tuple[int, dict, str]:
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch(
                    "gravity_insight.runtime.build_client",
                    side_effect=AssertionError("client constructed"),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = main(list(argv))
            rendered = stdout.getvalue() or stderr.getvalue()
            return code, json.loads(rendered), stderr.getvalue()

        code, listed, stderr = invoke("semantics", "list", "--kind", "entity")
        self.assertEqual(0, code)
        self.assertEqual(1, listed["count"])
        self.assertEqual("", stderr)

        code, missing, stderr = invoke(
            "semantics", "resolve", "metric://project/missing@1", "--at", "2026-08-22"
        )
        self.assertEqual(4, code)
        self.assertEqual("missing", missing["status"])
        self.assertEqual("", stderr)

        invalid = semantic_source(
            [semantic_definition("event://project/open@1", "event")]
        )
        invalid["definitions"][0].pop("owner")
        code, validation, stderr = invoke(
            "semantics", "validate", "--input", json.dumps(invalid)
        )
        self.assertEqual(4, code)
        self.assertEqual("invalid", validation["status"])
        self.assertEqual(["SEMANTIC_DEFINITION_INVALID"], validation["reason_codes"])
        self.assertEqual("", stderr)


if __name__ == "__main__":
    unittest.main()

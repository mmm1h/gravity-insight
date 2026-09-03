"""Evaluate and materialize the canonical Skill Method Complete gate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "tmp" / "method-gap-report.json"
REPORT_SCHEMA_VERSION = "gravity.skill-method-complete-report.v1"
_ZH_CN = re.compile(r"[\u3400-\u9fff]")
_AVAILABLE_STATUSES = frozenset({"available", "optional"})
_EMITTED_ROOTS: set[Path] = set()


@dataclass(frozen=True)
class Criterion:
    item: int
    key: str
    title: str
    evaluation: str
    cost: int
    proxy_for: str | None = None
    cannot_prove: str | None = None


CRITERIA = (
    Criterion(1, "business_question", "业务问题", "proxy", 2, "存在明确且中文可读的业务问题", "问题是否具有真实业务价值"),
    Criterion(2, "scope", "适用与不适用范围", "structural", 2),
    Criterion(3, "assumptions", "输入、时间、队列、单位、归因前提", "structural", 3),
    Criterion(4, "capability", "Capability", "structural", 3),
    Criterion(5, "semantic", "Semantic", "structural", 3),
    Criterion(6, "context", "Context", "structural", 3),
    Criterion(7, "deterministic_steps", "确定性分析步骤", "proxy", 5, "至少五个有稳定 ID、前向依赖和失败码的步骤", "步骤是否足以回答所有真实变体"),
    Criterion(8, "formula_operator_model", "公式、Operator 或 Model", "proxy", 5, "显式公式变量、分子分母、窗口和单位；声明的 Operator/Model 必须逐项覆盖", "行业公式是否等于具体项目口径或模型是否有效"),
    Criterion(9, "dimension_contribution", "维度扫描和贡献度", "proxy", 5, "至少三个维度与显式贡献公式、排序、门槛和残差规则", "维度集合是否覆盖真实业务中的全部驱动因素"),
    Criterion(10, "diagnosis_exclusions", "异常确认与排除项", "proxy", 5, "两层诊断树、每个一级分支至少两个叶子且每个叶子有排除项", "诊断因果链是否完备或结论是否真实"),
    Criterion(11, "completeness_dq", "Completeness 与 DQ", "proxy", 3, "至少两项完整性检查、两项质量检查及失败行为", "本次运行的数据是否实际完整且正确"),
    Criterion(12, "claim_policy", "Allowed 与 Forbidden Claims", "structural", 2),
    Criterion(13, "states", "Empty、Partial、Error、Gap", "structural", 3),
    Criterion(14, "structured_result", "结构化 Result", "structural", 3),
    Criterion(15, "handoff", "可选 Action 或 Experiment Handoff", "structural", 2),
    Criterion(16, "examples_evals", "中文示例问题与 Eval", "proxy", 4, "至少三个中文问题和三个带预期章节、禁止断言的 Eval", "Eval 是否覆盖线上问题分布或答案质量"),
    Criterion(17, "provenance_version", "Provenance 和版本", "structural", 1),
)


def evaluate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    method = manifest.get("method")
    checks: dict[str, Callable[[], bool]] = {
        "business_question": lambda: _zh(method, "business_question"),
        "scope": lambda: _scope_complete(method),
        "assumptions": lambda: _assumptions_complete(method),
        "capability": lambda: _dependency_kind_complete(manifest, "capability"),
        "semantic": lambda: _dependency_kind_complete(manifest, "semantic"),
        "context": lambda: _dependency_kind_complete(manifest, "context"),
        "deterministic_steps": lambda: bool(method and len(method["procedure"]) >= 5),
        "formula_operator_model": lambda: bool(
            method
            and method["formulas"]
            and _declared_compute_dependencies_complete(manifest)
        ),
        "dimension_contribution": lambda: _dimension_scan_complete(method),
        "diagnosis_exclusions": lambda: _diagnostic_tree_complete(method),
        "completeness_dq": lambda: _data_checks_complete(method),
        "claim_policy": lambda: _claims_complete(manifest),
        "states": lambda: _states_complete(method),
        "structured_result": lambda: _result_complete(manifest, method),
        "handoff": lambda: _handoff_complete(method),
        "examples_evals": lambda: _examples_complete(method),
        "provenance_version": lambda: _provenance_complete(manifest, method),
    }
    items = {
        f"{criterion.item:02d}_{criterion.key}": bool(checks[criterion.key]())
        for criterion in CRITERIA
    }
    missing = [key for key, satisfied in items.items() if not satisfied]
    costs = {
        f"{criterion.item:02d}_{criterion.key}": criterion.cost
        for criterion in CRITERIA
    }
    return {
        "skill_uri": _skill_uri(manifest),
        "skill_id": manifest["skill_id"],
        "method_complete": not missing,
        "achieved_count": len(items) - len(missing),
        "missing_count": len(missing),
        "estimated_completion_cost": sum(costs[key] for key in missing),
        "missing_items": missing,
        "items": items,
        "dependency_gaps": _dependency_gaps(method),
        "requires_project_calibration": (
            list(method["assumptions"]["requires_project_calibration"])
            if method is not None
            else []
        ),
    }


def _manifest_source_binding(
    root: Path, manifests: Sequence[tuple[Path, Mapping[str, Any]]]
) -> dict[str, Any]:
    sources = [
        {
            "path": path.relative_to(root).as_posix(),
            "manifest": manifest,
        }
        for path, manifest in manifests
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            sources,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "manifest_glob": "skills/library/*.json",
        "manifest_count": len(sources),
        "manifest_set_sha256": fingerprint,
        "generation": "recomputed_from_current_manifests_on_each_invocation",
    }


def library_report(root: Path) -> dict[str, Any]:
    from gravity_insight.agent_runtime_contracts import load_json_object
    from gravity_insight.skill_contract import compile_skill_manifest

    root = root.resolve()
    source = root / "skills" / "library"
    manifests = [
        (
            path,
            load_json_object(path, f"canonical Skill {path.name}"),
        )
        for path in sorted(source.glob("*.json"))
    ]
    rows = [
        evaluate_manifest(
            compile_skill_manifest(
                manifest,
                label=f"canonical Skill {path.name}",
            )
        )
        for path, manifest in manifests
    ]
    if not rows:
        raise ValueError(f"canonical Skill library is empty: {source}")
    rows.sort(
        key=lambda row: (
            row["method_complete"],
            row["estimated_completion_cost"],
            row["missing_count"],
            row["skill_uri"],
        )
    )
    complete = sum(row["method_complete"] for row in rows)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "definition": "Method Complete measures method-document completeness; execution readiness and dependency availability remain separate fail-closed states.",
        "source": _manifest_source_binding(root, manifests),
        "criteria": [
            {
                "item": item.item,
                "key": item.key,
                "title": item.title,
                "evaluation": item.evaluation,
                "proxy_for": item.proxy_for,
                "cannot_prove": item.cannot_prove,
                "completion_cost": item.cost,
            }
            for item in CRITERIA
        ],
        "summary": {
            "skill_count": len(rows),
            "method_complete_true": complete,
            "method_complete_false": len(rows) - complete,
        },
        "skills": rows,
    }


def compact_report(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": report["schema_version"],
        "source": report["source"],
        "summary": report["summary"],
        "skills": [
            {
                "skill_uri": row["skill_uri"],
                "method_complete": row["method_complete"],
                "items": row["items"],
                "missing_items": row["missing_items"],
                "dependency_gaps": row["dependency_gaps"],
            }
            for row in report["skills"]
        ],
    }


def emit_compiler_report(root: Path) -> None:
    selected = root.resolve()
    if selected in _EMITTED_ROOTS:
        return
    print(
        "METHOD_COMPLETE_REPORT="
        + json.dumps(
            compact_report(library_report(selected)),
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    _EMITTED_ROOTS.add(selected)


def _declared_dependencies(manifest: Mapping[str, Any]) -> set[tuple[str, str]]:
    values = {
        ("capability", item["selector"])
        for item in manifest["capability_dependencies"]
    }
    values.update(("semantic", item) for item in manifest["semantic_dependencies"])
    values.update(("operator", item) for item in manifest["operator_dependencies"])
    values.update(("model", item) for item in manifest["model_dependencies"])
    values.update(("context", item) for item in manifest["context_dependencies"]["required"])
    values.update(("context", item) for item in manifest["context_dependencies"]["optional"])
    return values


def _dependency_kind_complete(manifest: Mapping[str, Any], kind: str) -> bool:
    method = manifest.get("method")
    if method is None:
        return False
    expected = {item for item_kind, item in _declared_dependencies(manifest) if item_kind == kind}
    actual = {
        item["identity"]
        for item in method["dependency_status"]
        if item["kind"] == kind
    }
    return expected == actual


def _dependency_kinds_complete(manifest: Mapping[str, Any], kinds: Sequence[str]) -> bool:
    declared = _declared_dependencies(manifest)
    selected = [kind for kind in kinds if any(item_kind == kind for item_kind, _ in declared)]
    return bool(selected) and all(_dependency_kind_complete(manifest, kind) for kind in selected)


def _declared_compute_dependencies_complete(manifest: Mapping[str, Any]) -> bool:
    kinds = ("operator", "model")
    declared = _declared_dependencies(manifest)
    selected = [
        kind
        for kind in kinds
        if any(item_kind == kind for item_kind, _ in declared)
    ]
    return all(_dependency_kind_complete(manifest, kind) for kind in selected)


def _dependency_gaps(method: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if method is None:
        return []
    return [
        dict(item)
        for item in method["dependency_status"]
        if item["status"] not in _AVAILABLE_STATUSES
    ]


def _zh(method: Mapping[str, Any] | None, key: str) -> bool:
    return bool(method and _ZH_CN.search(str(method[key])))


def _zh_values(values: Sequence[str], minimum: int) -> bool:
    return len(values) >= minimum and all(_ZH_CN.search(str(value)) for value in values)


def _scope_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and _zh_values(method["scope"]["applicable"], 2) and _zh_values(method["scope"]["not_applicable"], 2))


def _assumptions_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and all(_zh_values(method["assumptions"][key], 1) for key in ("inputs", "time", "cohort", "unit", "attribution")))


def _dimension_scan_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and len(method["dimension_scan"]["dimensions"]) >= 3 and all(_ZH_CN.search(method["dimension_scan"][key]) for key in ("baseline", "ranking_rule", "minimum_volume_rule", "residual_policy")) and method["dimension_scan"]["contribution_formula"].strip())


def _diagnostic_tree_complete(method: Mapping[str, Any] | None) -> bool:
    if not method or len(method["exclusions"]) < 3:
        return False
    branches = method["diagnostic_tree"]["branches"]
    return len(branches) >= 2 and all(len(branch["leaves"]) >= 2 and all(leaf["exclusions"] for leaf in branch["leaves"]) for branch in branches)


def _data_checks_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and _zh_values(method["data_checks"]["completeness"], 2) and _zh_values(method["data_checks"]["data_quality"], 2) and _ZH_CN.search(method["data_checks"]["failure_behavior"]))


def _claims_complete(manifest: Mapping[str, Any]) -> bool:
    allowed = set(manifest["claim_policy"]["allowed"])
    forbidden = set(manifest["claim_policy"]["forbidden"])
    return bool(allowed and forbidden and allowed.isdisjoint(forbidden))


def _states_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and set(method["states"]) == {"empty", "partial", "error", "gap"} and all(_ZH_CN.search(item["behavior"]) for item in method["states"].values()))


def _result_complete(manifest: Mapping[str, Any], method: Mapping[str, Any] | None) -> bool:
    return bool(method and manifest["output_schema"] == "gravity.analysis-result.v1" and len(method["result"]["sections"]) >= 6 and len(method["result"]["required_fields"]) >= 5)


def _handoff_complete(method: Mapping[str, Any] | None) -> bool:
    return bool(method and method["handoff"]["automatic_execution"] is False and method["handoff"]["conditions"] and _ZH_CN.search(method["handoff"]["authorization_boundary"]))


def _examples_complete(method: Mapping[str, Any] | None) -> bool:
    if not method:
        return False
    examples = method["examples"]
    run_examples = examples["run_examples"]
    return bool(
        _zh_values(examples["questions"], 3)
        and len(examples["eval_cases"]) >= 3
        and all(
            _ZH_CN.search(item["question"])
            and item["expected_sections"]
            and item["forbidden_claims"]
            for item in examples["eval_cases"]
        )
        and len(run_examples) >= 3
        and {item["scenario"] for item in run_examples}
        == {"success", "empty_or_partial", "blocked_or_gap"}
        and all(
            _ZH_CN.search(item["question"])
            and item["input_template"]
            and item["expected"]["sections"]
            and item["expected"]["forbidden_claims"]
            for item in run_examples
        )
    )


def _provenance_complete(manifest: Mapping[str, Any], method: Mapping[str, Any] | None) -> bool:
    provenance = manifest["provenance"]
    return bool(method and method["method_revision"] >= 1 and manifest["version"] and provenance["source_ref"] and provenance["source_revision"] and provenance["authorship"] == "independently_authored")


def _skill_uri(manifest: Mapping[str, Any]) -> str:
    return f"skill://{manifest['namespace']}/{manifest['skill_id']}@{manifest['version']}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args(argv)
    output = options.output if options.output.is_absolute() else ROOT / options.output
    report = library_report(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    summary = report["summary"]
    print(
        f"wrote {output}: skills={summary['skill_count']}, "
        f"method_complete={summary['method_complete_true']}, "
        f"incomplete={summary['method_complete_false']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

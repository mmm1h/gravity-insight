"""Generate the small, contract-derived Agent task guide set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "agent-skills"
PROVENANCE = ROOT / "src" / "gravity_sdk" / "contracts" / "generated" / "provenance.json"


class _OfflineClient:
    def validate(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "status": "needs_live_metadata", "live_metadata_dependencies": []}

    def operations(self, **kwargs: Any) -> list[dict[str, Any]]:
        from gravity_sdk.models import load_operation_manifest
        from gravity_sdk.registry import Registry

        operations = []
        for path in sorted((ROOT / "src" / "gravity_sdk" / "manifests").glob("*.json")):
            operations.extend(load_operation_manifest(path))
        return Registry(operations).operations(
            domain=kwargs.get("domain"),
            platform=kwargs.get("platform"),
            stability=kwargs.get("stability", "stable"),
        )

    def export_capabilities(self) -> dict[str, Any]:
        values = [contract.capability() for contract in self._export_contracts().all()]
        return {"operations": values}

    def export_describe(self, operation_id: str) -> dict[str, Any]:
        return self._export_contracts().describe(operation_id)

    @staticmethod
    def _export_contracts() -> Any:
        from gravity_sdk.export_contracts import ExportContractRegistry

        return ExportContractRegistry.from_file(
            ROOT / "src" / "gravity_sdk" / "contracts" / "exports" / "routes-v1.json"
        )

    def search_operations(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"operations": []}


def render_documents() -> dict[Path, str]:
    from gravity_sdk.agent import _protocol, discover_capabilities
    from gravity_sdk.agent_analysis import analysis_query_spec_cards
    from gravity_sdk.agent_batch_sources import AgentSourceSnapshot
    from gravity_sdk.agent_product_inventory import canonical_capability_cards
    from gravity_sdk.agent_unavailable import registered_unavailable_gaps
    from gravity_sdk.analysis_period_compare import compare_analysis_periods
    from gravity_sdk.analysis_spec import prepare_query_spec
    from gravity_sdk.analysis_spec_schema import analysis_query_spec_schema
    from gravity_sdk.derived_metrics import SPEC_SCHEMA_VERSION as DERIVED_SPEC_VERSION
    from gravity_sdk.workspace_semantic_context import SCHEMA_VERSION as SEMANTIC_VERSION

    protocol = _protocol()
    cards = {
        card["selector"]: card
        for card in canonical_capability_cards(_OfflineClient())
    }
    segment_mutations = _mutation_cards(cards, "segment_mutation")
    report_mutations = _mutation_cards(cards, "report_mutation")
    kanban_mutations = _mutation_cards(cards, "kanban_mutation")
    event_card = cards["analysis.query.spec:event"]
    compare_card = analysis_query_spec_cards("analysis period compare", domain=None, platform=None)[0]
    event_preview = prepare_query_spec(
        _OfflineClient(), "event", _event_spec(), app="1"
    )
    comparison_gap = compare_analysis_periods(
        object(), "property", {}, baseline_start="2026-01-01", baseline_end="2026-01-02"
    )
    discovery_gap = discover_capabilities(
        "unregistered capability",
        client=_OfflineClient(),
        sources=AgentSourceSnapshot(
            workspace=None, operation_inventory=(), recipe_inventory=(),
            product_inventory=(), metadata_inventory=(), composite_inventory=(),
            warnings=(), workspace_fingerprint="generated", metadata_catalog_available=True,
        ),
    )
    contract = analysis_query_spec_schema()
    exits = protocol["exit_codes"]
    operation_ids = {
        str(item["operation_id"])
        for item in _OfflineClient().operations(stability=None)
    }
    gaps = registered_unavailable_gaps()
    catalog = {
        "operation_count": json.loads(PROVENANCE.read_text(encoding="utf-8"))["operation_count"],
        "product_card_count": len(cards),
        "gap_count": len(gaps),
    }
    catalog["selector_count"] = len(
        operation_ids | set(cards) | {f"gap:{gap['code']}" for gap in gaps}
    )
    return {
        OUTPUT / "index.md": _index(catalog),
        OUTPUT / "catalog-discovery.md": _catalog_discovery(catalog, exits),
        OUTPUT / "event-trend.md": _event_trend(event_card, contract, event_preview, exits),
        OUTPUT / "period-comparison.md": _comparison(compare_card, contract, comparison_gap, exits),
        OUTPUT / "capability-gap.md": _capability_gap(protocol, discovery_gap, exits),
        OUTPUT / "ten-minute-path.md": _ten_minute_path(event_card, contract, exits),
        OUTPUT / "governed-writes.md": _governed_writes(
            segment_mutations, report_mutations, kanban_mutations, exits
        ),
        OUTPUT / "caller-semantics.md": _caller_semantics(
            SEMANTIC_VERSION, DERIVED_SPEC_VERSION
        ),
    }


def _index(catalog: dict[str, int]) -> str:
    return f"""<!-- generated by scripts/generate_agent_skills.py; do not edit -->
# Agent 任务指南

这些短指南从完整 Agent 产品卡、Analysis Spec、workspace 语义、错误合同和 manifest 生成；不创建 Skill 注册表，也不替代运行时合同。当前输入源包含 {catalog['operation_count']} 个 operation、{catalog['product_card_count']} 张产品卡与 {catalog['gap_count']} 个精确 gap。

| 目标 | 指南 |
| --- | --- |
| 分三层浏览全部本地能力 | [完整目录发现](catalog-discovery.md) |
| 十分钟内从本地能力走到第一次真实分析 | [十分钟路径](ten-minute-path.md) |
| 看一个事件的趋势 | [事件趋势](event-trend.md) |
| 用同一分析定义比较两个时期 | [时期对比](period-comparison.md) |
| 预览并确认执行分群、报表、订阅或 Kanban 写入 | [受治理写入](governed-writes.md) |
| 声明调用方语义和派生指标 | [调用方语义与派生指标](caller-semantics.md) |
| Agent 返回 `capability_gap` | [能力缺口](capability-gap.md) |
"""


def _catalog_discovery(catalog: dict[str, int], exits: dict[str, str]) -> str:
    return _guide(
        "完整目录发现：category → selector → contract",
        [
            f"完整目录当前有 {catalog['selector_count']} 个 selector：{catalog['operation_count']} 个 operation、{catalog['product_card_count']} 张产品卡与 {catalog['gap_count']} 个精确 gap。先看分类，不要先猜命令：",
            "```powershell\ngravity agent-catalog categories\ngravity agent-catalog category <category>\ngravity agent-catalog describe <selected-selector>\ngravity agent-catalog host\n```",
            "第一层决定领域，第二层只选择 selector，第三层才读取完整输入合同、`required_inputs`、`next.argv` 与可执行状态。`host` 只投影产品/gap 及严格选择 schema，不暴露 raw operation。调用方能产出选择时推荐宿主臂：读取 `host` 投影后只返回 `gravity.host-product-selection.v1`，再显式 `gravity agent --routing host_catalog --host-selection <json>`；仓库消费该选择、不调模型。省略 `--routing` 时默认 recognizer 是够不着宿主时的地板，不是劣等品。category 返回 `next_offset` 时，只有确实需要浏览该领域剩余能力才继续；已知 selector 直接 describe。所有目录命令均离线且不执行候选。",
        ],
        catalog,
        exits,
        "产品任务优先选择 `identity_kind=product`；`raw_operation` 是专家入口，不等价于产品；`capability_gap` 不可执行，只按 `next_action` 恢复。",
    )


def _event_trend(card: dict[str, Any], contract: dict[str, Any], preview: dict[str, Any], exits: dict[str, str]) -> str:
    return _guide(
        "看某个事件的趋势",
        [
            "```powershell\n" + _argv(card["next"]["schema_argv"]) + "\n```",
            "将返回的 `" + card["spec_schema_version"] + "` schema 中事件名、指标和日期填入 Spec 后执行：",
            "```powershell\n" + contract["handoff"]["command"] + "\n```",
        ],
        preview,
        exits,
        "`validation.live_metadata_dependencies` 非空时，先按该字段列出的登记 operation 校验物理事件/字段；不要由自然语言补值。",
    )


def _comparison(card: dict[str, Any], contract: dict[str, Any], gap: dict[str, Any], exits: dict[str, str]) -> str:
    flags = " ".join(f"--{name.replace('_', '-')} <explicit-date>" for name in card["optional_inputs"])
    return _guide(
        "比较两个时期",
        [
            "先取得同一 kind 的 Spec，再只追加 card 声明的时期参数：",
            "```powershell\n" + contract["handoff"]["command"] + " " + flags + "\n```",
            "此卡的 compare contract 是 `" + card["period_compare"]["schema_version"] + "`；仅支持 `" + "/".join(card["period_compare"]["supported_kinds"]) + "`。",
        ],
        gap,
        exits,
        "若 `status=capability_gap`，读取 `next_action`；不要把没有 delta 当作 0。",
    )


def _capability_gap(protocol: dict[str, Any], gap: dict[str, Any], exits: dict[str, str]) -> str:
    command = list(protocol["workflow"][0]["argv"])
    command[-1] = '"<your-query>"'
    return _guide(
        "拿到 capability_gap 后怎么办",
        [
            "```powershell\n" + _argv(command) + "\n```",
            "调用方能产出选择时，先 `gravity agent-catalog host` 再把严格 `gravity.host-product-selection.v1` 交给 `gravity agent --routing host_catalog --host-selection`；默认 `gravity agent` 仍是够不着宿主时的地板。只有 `status=success` 的 candidate 才可执行；`capability_gaps` 是明确的不可执行结果，不是 empty。",
        ],
        gap,
        exits,
        "先报告 `capability_gaps[].code`、`reason` 和 `next_action`。仅在其 `next.argv` 存在时执行该受控下一步；不要执行 weak match。",
    )


def _ten_minute_path(card: dict[str, Any], contract: dict[str, Any], exits: dict[str, str]) -> str:
    return _guide(
        "十分钟路径：从仓库到第一次真实分析",
        [
            "先由调用方明确选择 App、日期窗和一个精确物理事件名；bootstrap 不会从可读 App 或事件中静默挑默认值。然后只做两次顶层调用：",
            "```powershell\ngravity analysis bootstrap `\n  --app <selected-app-id> `\n  --start <caller-start-date> --end <caller-end-date> `\n  --target <physical-event> --plan-output first-analysis-plan.json\n# 审阅 Plan 中的 App、日期、事件与 metadata 指纹\ngravity plan run --input first-analysis-plan.json\n```",
            "第一次调用复用 `app.list`、单 App metadata sync、离线精确事件查找和 Plan dry-run；它只写 Plan，不执行分析。冷目录把四类 metadata 各限制为第一页，CLI transport 不重试：含首次登录最多 6 HTTP。第二次从固定 catalog 快照做 FieldPolicy 校验，只发 1 次事件查询；总计最多 7 HTTP。",
            "如果 App、日期或事件未提供，返回的 caller error 只有一个 `next_action`，不会代选。若任一 metadata 类超过第一页，bootstrap 也不会自动扩量；它返回运行普通有界 sync 的唯一下一动作，调用方审阅更大预算后再决定。",
        ],
        {
            "schema_version": "gravity.analysis-bootstrap.v1",
            "status": "plan_ready",
            "app_id": "<selected-app-id>",
            "target": {"kind": "physical_event", "name": "<physical-event>"},
            "plan_validation": {"status": "validated", "dry_run": True},
            "next": {"argv": ["gravity", "plan", "run", "--input", "<plan.json>"]},
        },
        exits,
        "保留给人的决策只有选 App、选精确事件、给日期窗和审阅 Plan；安装、认证、同步、status、Spec 组装与离线校验都是机械步骤。最终结果为 0 或 empty 也是真实响应状态，不能改写成业务未发生。",
    )


def _governed_writes(
    segment_cards: list[dict[str, Any]], report_cards: list[dict[str, Any]],
    kanban_cards: list[dict[str, Any]], exits: dict[str, str]
) -> str:
    segment_card = _action_card(segment_cards, "delete")
    report_card = _action_card(report_cards, "create-subscription")
    kanban_card = _action_card(kanban_cards, "dashboard.rename")
    all_cards = [*segment_cards, *report_cards, *kanban_cards]
    return _guide(
        "受治理写入：dry-run → 人工确认 → execute",
        [
            "先从完整目录读取 action-qualified mutation 产品卡；analysis 的 27 张写卡都在产品区，`--limit 50` 可一次列出：",
            "```powershell\ngravity agent-catalog categories\ngravity agent-catalog category analysis --limit 50\ngravity agent-catalog category report --limit 50\ngravity agent-catalog describe <selected-mutation-selector>\n```",
            _mutation_table(all_cards),
            "例如，删除分群卡给出的最小两步交接为：",
            "```powershell\n" + _argv(segment_card["next"]["argv"]) + "\n# 审查 preview 后，原参数只把 --dry-run 改为 --execute\n" + _argv(segment_card["next"]["then_argv"]) + "\n```",
            "创建报表订阅卡给出的最小两步交接为：",
            "```powershell\n" + _argv(report_card["next"]["argv"]) + "\n# 审查 preview 后，原参数只把 --dry-run 改为 --execute\n" + _argv(report_card["next"]["then_argv"]) + "\n```",
            "重命名看板卡给出的最小两步交接为：",
            "```powershell\n" + _argv(kanban_card["next"]["argv"]) + "\n# 审查 preview 后，原参数只把 --dry-run 改为 --execute\n" + _argv(kanban_card["next"]["then_argv"]) + "\n```",
            "31 张 action 卡覆盖 `analysis segment create-from-analysis/create-from-rule/create-from-history/create-from-tmp/update/update-rule/refresh/delete`、`reports create/delete/subscribe/unsubscribe` 与全部 19 个 `analysis dashboard kanban mutate --action`。每张卡都显式二选一 `--dry-run` / `--execute`；Kanban 另提供显式 `preview|execute` Plan node，但自然语言和预览都不是写授权。",
        ],
        {
            "mutation_card_count": len(all_cards),
            "action_card": {
                key: segment_card[key]
                for key in (
                    "selector", "mutation_action", "operation_ids",
                    "natural_language_auto_execute", "confirmation_required", "next",
                )
            },
            "kanban_plan_handoff": {
                "plan_node": kanban_card["next"]["plan_node"],
                "then_plan_node": kanban_card["next"]["then_plan_node"],
            },
        },
        exits,
        "create 写入可读回的 SDK marker；update/delete/unsubscribe 要求 marker 或已证实 upstream owner，否则 fail closed。Kanban 父删除 dry-run 先读树并报告迁移数；报表订阅固定 disabled、无收件人且永不调用 test route。",
    )


def _mutation_cards(
    cards: dict[str, dict[str, Any]], kind: str
) -> list[dict[str, Any]]:
    return sorted(
        (card for card in cards.values() if card.get("kind") == kind),
        key=lambda card: str(card["selector"]),
    )


def _action_card(cards: list[dict[str, Any]], action: str) -> dict[str, Any]:
    return next(card for card in cards if card["mutation_action"] == action)


def _mutation_table(cards: list[dict[str, Any]]) -> str:
    rows = [
        "| selector | action | governed operation |",
        "| --- | --- | --- |",
    ]
    rows.extend(
        "| `" + str(card["selector"]) + "` | `" + str(card["mutation_action"])
        + "` | `" + "`, `".join(card["operation_ids"]) + "` |"
        for card in cards
    )
    return "\n".join(rows)


def _caller_semantics(semantic_version: str, derived_version: str) -> str:
    return f'''<!-- generated by scripts/generate_agent_skills.py; do not edit -->
# 调用方语义与派生指标

SDK 不猜业务词或公式；调用项目在 `gravity.toml` 声明 `{semantic_version}`。下面是可直接改名的最小虚构示例：

```toml
[semantic_context]
schema_version = "{semantic_version}"

[[semantic_context.terms]]
name = "orion-event"
phrases = ["orion event"]
target = {{ kind = "event", ref = "app_open", app = "main" }}

[[semantic_context.derived_metrics]]
name = "orion-ratio"
phrases = ["orion ratio"]
spec = {{ schema_version = "{derived_version}", rows_path = "/data/list", decimal_places = 4, calculations = [{{ operator = "ratio", result_name = "orion_ratio", numerator = "orion_a", denominator = "orion_b" }}] }}
```

`terms` 只做声明 phrase 的字面匹配，物理 `ref` 必须已存在于 metadata catalog。派生公式同样由调用方负责；命中后 Agent 只预填 spec，仍要求显式提供 source envelope。

不经自然语言也可直接执行同一 `{derived_version}`：

```json
{{
  "source": {{"schema_version": "fictional.result.v1", "status": "success", "ok": true, "data": {{"list": [{{"orion_a": 3, "orion_b": 4}}]}}}},
  "spec": {{"schema_version": "{derived_version}", "rows_path": "/data/list", "decimal_places": 4, "calculations": [{{"operator": "ratio", "result_name": "orion_ratio", "numerator": "orion_a", "denominator": "orion_b"}}]}}
}}
```

```powershell
gravity derive --input <request.json>
```

没有声明的比率、占比、变化或集合对账必须返回 `DERIVED_METRIC_BINDING_REQUIRED`；不要从列名或问题文本补公式。
'''


def _guide(title: str, steps: list[str], envelope: dict[str, Any], exits: dict[str, str], next_step: str) -> str:
    return "\n".join((
        "<!-- generated by scripts/generate_agent_skills.py; do not edit -->",
        f"# {title}", "", *steps, "", "## 预期 envelope 形状", "",
        "```json", json.dumps(_shape(envelope), ensure_ascii=False, indent=2, sort_keys=True), "```", "",
        "## 失败分支", "",
        *[f"- exit {code}: {meaning}." for code, meaning in sorted(exits.items(), key=lambda item: int(item[0]))],
        "", "## 下一步", "", next_step, "",
    ))


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    return f"<{type(value).__name__}>"


def _event_spec() -> dict[str, Any]:
    return {
        "start": "2026-01-01", "end": "2026-01-02",
        "steps": [{"event": "example_event", "metric": {"field": "event_count", "aggregation": "Count"}}],
    }


def _argv(values: list[str]) -> str:
    return " ".join(values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render_documents()
    mismatched = [path for path, content in rendered.items() if not path.is_file() or path.read_text(encoding="utf-8") != content]
    if args.check:
        if mismatched:
            raise SystemExit("generated Agent guides are stale: " + ", ".join(str(path.relative_to(ROOT)) for path in mismatched))
        return 0
    for path, content in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

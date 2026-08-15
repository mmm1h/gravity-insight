"""Strict Agent handoff for the Bytedance title-package family."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


TITLE_PACKAGE_NAME = "title_package"
TITLE_PACKAGE_SELECTOR = f"composite:{TITLE_PACKAGE_NAME}"
_EXACT = frozenset({
    TITLE_PACKAGE_NAME,
    TITLE_PACKAGE_SELECTOR,
    "title package metrics",
    "title package performance",
    "标题包指标",
    "标题包表现",
    "标题包汇总",
})


TITLE_PACKAGE_CAPABILITY: Mapping[str, Any] = {
    "name": TITLE_PACKAGE_NAME,
    "domain": "material",
    "aliases": (
        "title package metrics",
        "title package performance",
        "标题包指标",
        "标题包表现",
        "标题包汇总",
    ),
    "description": (
        "按显式 App 和普通/标准类型读取巨量标题包名称、标题数、计划数、"
        "历史与近三日成本和点击率，并返回已登记的标题正文与人员字段。"
    ),
    "required_inputs": ("app", "package_kind"),
    "input_schema": {
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
        },
        "package_kind": {
            "type": "string",
            "required": True,
            "nullable": False,
            "enum": ["regular", "standard"],
        },
    },
}


def title_package_query(query: str) -> bool:
    selected = " ".join(query.strip().casefold().split())
    if selected in _EXACT:
        return True
    if not selected or any(term in selected for term in ("导出", "创建", "删除")):
        return False
    words = frozenset(selected.split())
    english = "title" in words and "package" in words and bool(
        words & {"metric", "metrics", "performance", "summary"}
    )
    chinese = "标题包" in selected and any(
        term in selected for term in ("指标", "表现", "汇总", "成本", "点击率")
    )
    return english or chinese


def title_package_intent(query: str) -> bool:
    return title_package_query(query)


def title_package_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": TITLE_PACKAGE_NAME,
        "app": card.get("app", "<app:string|integer>"),
        "package_kind": card.get(
            "package_kind", "<package_kind:string:enum>"
        ),
    }


__all__ = [
    "TITLE_PACKAGE_CAPABILITY",
    "TITLE_PACKAGE_NAME",
    "TITLE_PACKAGE_SELECTOR",
    "title_package_intent",
    "title_package_plan_request",
    "title_package_query",
]

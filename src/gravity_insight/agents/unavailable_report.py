"""Natural-language gaps owned by unavailable report journeys."""

from __future__ import annotations

import re
from typing import Any

from .gap import unavailable_gap
from .intent_text import affirmative_intent_text


_MEDIA_REPORT_OWNER_TYPO = re.compile(
    r"煤体(?=\s*(?:(?:类|投放)(?:的)?\s*)?报表)"
)
AP_COST_DATE_SEMANTICS_GAP_CODE = "AP_COST_DATE_SEMANTICS_UNDECLARED"
POST_REGISTRATION_USER_GROUP_COST_GAP_CODE = (
    "POST_REGISTRATION_USER_GROUP_EXACT_COST_UNAVAILABLE"
)
AP_COST_DATE_SEMANTICS_REASON = (
    "The upstream ap_cost metadata declares only total spend; neither the operation "
    "contract nor committed evidence declares whether its selected date means spend, "
    "click, activation, or registration date. Runtime does not infer a date basis from "
    "the field name."
)
AP_COST_DATE_SEMANTICS_NEXT_ACTION = (
    "Treat date_list only as the opaque upstream report window and do not label it as "
    "spend, click, activation, or registration date. Obtain and register authoritative "
    "upstream documentation or source evidence before making a date-basis claim."
)
POST_REGISTRATION_USER_GROUP_COST_REASON = (
    "Native ad spend occurs on advertising-platform ad objects, while AB groups are user "
    "attributes assigned after registration; no upstream fact links that spend to those "
    "post-registration groups. The governed join evidence in "
    "contracts/join-keys/registry.v1.json contains only ad-object-to-acquisition-attribute "
    "mappings and no post-registration user property."
)
POST_REGISTRATION_USER_GROUP_COST_NEXT_ACTION = (
    "Report native spend separately by click_company, advertising project, and day where "
    "their governed products support them; within-group revenue growth multiples remain "
    "valid as revenue-side comparisons. Do not present allocated spend as native or exact. "
    "Inspect contracts/join-keys/registry.v1.json for the available join-key evidence."
)


def unavailable_report_gap(query: str) -> dict[str, Any] | None:
    selected = _normalize_media_report_owner(affirmative_intent_text(query))
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    if _post_registration_user_group_cost(selected, words):
        return unavailable_gap(
            query,
            code=POST_REGISTRATION_USER_GROUP_COST_GAP_CODE,
            journey="post_registration_user_group_cost",
            reason=POST_REGISTRATION_USER_GROUP_COST_REASON,
            next_action=POST_REGISTRATION_USER_GROUP_COST_NEXT_ACTION,
        )
    if _ap_cost_date_semantics(selected, words):
        return unavailable_gap(
            query,
            code=AP_COST_DATE_SEMANTICS_GAP_CODE,
            journey="ap_cost_date_semantics",
            reason=AP_COST_DATE_SEMANTICS_REASON,
            next_action=AP_COST_DATE_SEMANTICS_NEXT_ACTION,
        )
    if _media_reports(selected, words):
        return unavailable_gap(
            query, code="MEDIA_REPORT_ITEM_SCHEMA_MISSING",
            journey="media_report_directory",
            reason="The media-report list read is confirmed, but the bounded observed response was empty.",
            next_action=(
                "Use a tenant with a media report and repeat the same unfiltered first-page request once; "
                "register only shape, types, and pagination evidence."
            ),
        )
    return None


def _normalize_media_report_owner(selected: str) -> str:
    """Normalize the observed typo only inside a media-report owner phrase."""

    return _MEDIA_REPORT_OWNER_TYPO.sub("媒体", selected)


def _media_reports(selected: str, words: frozenset[str]) -> bool:
    english = "media" in words and bool(words & {"report", "reports"})
    chinese = "媒体" in selected and "报表" in selected
    return english or chinese


def _post_registration_user_group_cost(
    selected: str, words: frozenset[str]
) -> bool:
    cost_or_roi = bool(words & {"ap_cost", "cost", "spend", "roi", "iap"}) or any(
        term in selected for term in ("成本", "花费", "消耗", "投入产出")
    )
    user_group = (
        "user_ab" in words
        or ("ab" in words and ("group" in words or "分组" in selected))
        or (
            any(term in selected for term in ("用户属性", "后置属性", "注册后"))
            and any(term in selected for term in ("分组", "拆分", "分摊"))
        )
    )
    return cost_or_roi and user_group


def _ap_cost_date_semantics(selected: str, words: frozenset[str]) -> bool:
    cost = "ap_cost" in words or "ap cost" in selected or "广告成本" in selected
    date = "date" in words or "日期" in selected
    meaning = bool(
        words
        & {
            "basis",
            "click",
            "activation",
            "meaning",
            "means",
            "registration",
            "semantics",
            "spend",
        }
    ) or any(term in selected for term in ("含义", "口径", "语义", "点击", "激活", "注册", "投放"))
    return cost and date and meaning


__all__ = [
    "AP_COST_DATE_SEMANTICS_GAP_CODE",
    "AP_COST_DATE_SEMANTICS_NEXT_ACTION",
    "AP_COST_DATE_SEMANTICS_REASON",
    "POST_REGISTRATION_USER_GROUP_COST_GAP_CODE",
    "POST_REGISTRATION_USER_GROUP_COST_NEXT_ACTION",
    "POST_REGISTRATION_USER_GROUP_COST_REASON",
    "unavailable_report_gap",
]

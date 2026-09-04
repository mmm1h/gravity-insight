"""Exact coverage and unclassified-module ratchets for domain boundaries."""

from __future__ import annotations

from typing import Any, Mapping


_ModuleGraphAny = Any


def valid_coverage_fraction(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"classified_module_count", "module_count"}
        and type(value["classified_module_count"]) is int
        and type(value["module_count"]) is int
        and 0 <= value["classified_module_count"] <= value["module_count"]
        and value["module_count"] > 0
    )


def coverage_is_lower(
    observed: Mapping[str, int], minimum: Mapping[str, int]
) -> bool:
    """Compare exact ratios without float rounding."""

    return (
        observed["classified_module_count"] * minimum["module_count"]
        < minimum["classified_module_count"] * observed["module_count"]
    )


def classification_ratchet_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> list[str]:
    exemptions, exemption_errors = _unclassified_exemptions(measurement, baseline)
    return [
        *_coverage_errors(measurement, baseline),
        *exemption_errors,
        *_root_errors(measurement, baseline, exemptions),
        *_non_root_unclassified_errors(measurement, baseline, exemptions),
    ]


def _coverage_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> list[str]:
    observed = measurement["classification"]["coverage"]
    minimum = baseline.get("minimum_classification_coverage")
    if not valid_coverage_fraction(minimum):
        return [
            "domain boundary baseline minimum_classification_coverage must be an "
            "exact positive-denominator fraction"
        ]
    if coverage_is_lower(observed, minimum):
        return [
            "domain boundary classification coverage decreased: "
            f"current={observed['classified_module_count']}/{observed['module_count']}, "
            f"minimum={minimum['classified_module_count']}/{minimum['module_count']}"
        ]
    return []


def _unclassified_exemptions(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> tuple[set[str], list[str]]:
    exemptions = baseline.get("unclassified_module_exemptions")
    if not isinstance(exemptions, list):
        return set(), ["domain boundary unclassified_module_exemptions must be a list"]
    unclassified = set(measurement["classification"]["unclassified_modules"])
    allowed: set[str] = set()
    errors: list[str] = []
    for index, exemption in enumerate(exemptions):
        if not isinstance(exemption, dict) or set(exemption) != {"module", "reason"}:
            errors.append(
                f"domain boundary unclassified exemption {index} must contain module and reason"
            )
            continue
        module, reason = exemption["module"], exemption["reason"]
        if not isinstance(module, str) or not isinstance(reason, str) or not reason.strip():
            errors.append(
                f"domain boundary unclassified exemption {index} needs a module and non-empty reason"
            )
            continue
        if module in allowed:
            errors.append(
                f"domain boundary unclassified exemption {index} duplicates {module}"
            )
            continue
        if module not in unclassified:
            errors.append(
                f"domain boundary unclassified exemption {index} must name a current "
                f"unclassified module: {module}"
            )
            continue
        allowed.add(module)
    return allowed, errors


def _string_set(
    baseline: Mapping[str, _ModuleGraphAny], key: str
) -> tuple[set[str], list[str]]:
    value = baseline.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return set(), [f"domain boundary {key} must be a string list"]
    if len(value) != len(set(value)):
        return set(value), [f"domain boundary {key} must not contain duplicates"]
    return set(value), []


def _root_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
    exemptions: set[str],
) -> list[str]:
    protected, errors = _string_set(baseline, "protected_root_modules")
    unclassified = set(measurement["classification"]["unclassified_modules"])
    new_modules = sorted(
        (set(measurement["root_direct_modules"]) - protected - exemptions)
        & unclassified
    )
    if new_modules:
        errors.append(
            "new unclassified modules may not enter the gravity_insight root package "
            "without an exact reasoned exemption: " + ", ".join(new_modules)
        )
    return errors


def _non_root_unclassified_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
    exemptions: set[str],
) -> list[str]:
    protected, errors = _string_set(
        baseline, "protected_non_root_unclassified_modules"
    )
    root_modules = set(measurement["root_direct_modules"])
    unclassified = set(measurement["classification"]["unclassified_modules"])
    new_modules = sorted(unclassified - root_modules - protected - exemptions)
    if new_modules:
        errors.append(
            "new non-root modules must be assigned a layer or carry an exact "
            "reasoned unclassified exemption: " + ", ".join(new_modules)
        )
    return errors

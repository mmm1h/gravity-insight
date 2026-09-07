"""Recursive projection for governed dynamic Analysis aggregate trees."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .analysis_projection_contract import (
    allowed_analysis_response_key,
    allowed_analysis_response_scalar,
    analysis_numeric_path_allowed,
    funnel_group_label_value_path,
)
from .drift import ProjectionDrift
from .list_row_projection import _is_finite_number, _is_json_scalar
from .response_drift import ResponseDriftRecorder


ResponsePaths = tuple[tuple[tuple[str, ...], ...], Mapping[str, str]]


def project_analysis_value(
    value: Any,
    *,
    blocked: set[str],
    response_keys: set[str],
    response_paths: ResponsePaths,
    path: tuple[str, ...],
    depth: int,
    allow_contracted_identifiers: bool,
    recorder: ResponseDriftRecorder,
    sensitive_key: Callable[..., bool],
    sensitive_scalar: Callable[[str, set[str]], bool],
    absent: object,
) -> tuple[Any, ProjectionDrift]:
    if depth > 10:
        return absent, ProjectionDrift.BREAKING
    if _is_json_scalar(value):
        normalized = _project_scalar(
            value,
            blocked,
            response_keys,
            response_paths[0],
            path,
            allow_contracted_identifiers,
            sensitive_scalar,
            absent,
        )
        drift = ProjectionDrift.BREAKING if normalized is absent else ProjectionDrift.NONE
        return normalized, drift
    arguments = (
        blocked,
        response_keys,
        response_paths,
        path,
        depth,
        allow_contracted_identifiers,
        recorder,
        sensitive_key,
        sensitive_scalar,
        absent,
    )
    if isinstance(value, Mapping):
        return _project_mapping(value, *arguments)
    if isinstance(value, (list, tuple)):
        return _project_sequence(value, *arguments)
    return absent, ProjectionDrift.BREAKING


def _project_scalar(
    value: Any,
    blocked: set[str],
    response_keys: set[str],
    numeric_paths: tuple[tuple[str, ...], ...],
    path: tuple[str, ...],
    allow_identifiers: bool,
    sensitive_scalar: Callable[[str, set[str]], bool],
    absent: object,
) -> Any:
    if (
        _is_finite_number(value)
        and not allow_identifiers
        and not analysis_numeric_path_allowed(path, numeric_paths)
    ):
        return absent
    if isinstance(value, str) and (
        len(value) > 4_096
        or funnel_group_label_value_path(path)
        and not allowed_analysis_response_scalar(value, response_keys, path)
        or not allow_identifiers
        and (
            sensitive_scalar(value, blocked)
            or not allowed_analysis_response_scalar(value, response_keys, path)
        )
    ):
        return absent
    return value


def _project_mapping(
    value: Mapping[Any, Any],
    blocked: set[str],
    response_keys: set[str],
    response_paths: ResponsePaths,
    path: tuple[str, ...],
    depth: int,
    allow_identifiers: bool,
    recorder: ResponseDriftRecorder,
    sensitive_key: Callable[..., bool],
    sensitive_scalar: Callable[[str, set[str]], bool],
    absent: object,
) -> tuple[Any, ProjectionDrift]:
    if len(value) > 10_000:
        return absent, ProjectionDrift.BREAKING
    result: dict[str, Any] = {}
    drift = ProjectionDrift.NONE
    for key, item in value.items():
        name = str(key)
        if (
            len(name) > 256
            or sensitive_key(
                name, blocked, allow_contracted_identifiers=allow_identifiers
            )
            or not allowed_analysis_response_key(
                name, response_keys, path, response_paths[0], response_paths[1]
            )
        ):
            audit_path = ("data", *("*" if part == "[]" else part for part in path))
            recorder.add_unknown_fields(audit_path, value, {name})
            drift = max(drift, ProjectionDrift.ADDITIVE)
            continue
        normalized, nested_drift = project_analysis_value(
            item,
            blocked=blocked,
            response_keys=response_keys,
            response_paths=response_paths,
            path=(*path, name),
            depth=depth + 1,
            allow_contracted_identifiers=allow_identifiers,
            recorder=recorder,
            sensitive_key=sensitive_key,
            sensitive_scalar=sensitive_scalar,
            absent=absent,
        )
        if normalized is absent:
            drift = ProjectionDrift.BREAKING
        else:
            result[name] = normalized
            drift = max(drift, nested_drift)
    return result, drift


def _project_sequence(
    value: tuple[Any, ...] | list[Any],
    blocked: set[str],
    response_keys: set[str],
    response_paths: ResponsePaths,
    path: tuple[str, ...],
    depth: int,
    allow_identifiers: bool,
    recorder: ResponseDriftRecorder,
    sensitive_key: Callable[..., bool],
    sensitive_scalar: Callable[[str, set[str]], bool],
    absent: object,
) -> tuple[Any, ProjectionDrift]:
    if len(value) > 100_000:
        return absent, ProjectionDrift.BREAKING
    result: list[Any] = []
    drift = ProjectionDrift.NONE
    for item in value:
        normalized, nested_drift = project_analysis_value(
            item,
            blocked=blocked,
            response_keys=response_keys,
            response_paths=response_paths,
            path=(*path, "[]"),
            depth=depth + 1,
            allow_contracted_identifiers=allow_identifiers,
            recorder=recorder,
            sensitive_key=sensitive_key,
            sensitive_scalar=sensitive_scalar,
            absent=absent,
        )
        if normalized is absent:
            drift = ProjectionDrift.BREAKING
        else:
            result.append(normalized)
            drift = max(drift, nested_drift)
    return result, drift


__all__ = ["project_analysis_value"]

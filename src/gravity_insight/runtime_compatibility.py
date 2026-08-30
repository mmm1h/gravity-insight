"""Small exact version/range checks for Runtime-owned artifact contracts."""

from __future__ import annotations

import re
from typing import Callable


_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SPECIFIER = re.compile(r"^(>=|<=|==|>|<)([0-9]+\.[0-9]+(?:\.[0-9]+)?)$")
_COMPARATORS: dict[str, Callable[[tuple[int, ...], tuple[int, ...]], bool]] = {
    ">=": lambda value, bound: value >= bound,
    "<=": lambda value, bound: value <= bound,
    "==": lambda value, bound: value == bound,
    ">": lambda value, bound: value > bound,
    "<": lambda value, bound: value < bound,
}


def normalized_version(value: str) -> str:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise ValueError("version must be canonical major.minor.patch")
    return value


def version_tuple(value: str, *, width: int = 3) -> tuple[int, ...]:
    parts = tuple(int(item) for item in value.split("."))
    if not 2 <= len(parts) <= width:
        raise ValueError("version bound must contain major.minor[.patch]")
    return (*parts, *(0 for _ in range(width - len(parts))))


def runtime_satisfies(runtime_version: str, requirement: str) -> bool:
    selected = version_tuple(normalized_version(runtime_version))
    if not isinstance(requirement, str) or not requirement:
        raise ValueError("runtime requirement is empty")
    clauses = requirement.split(",")
    matches = [_SPECIFIER.fullmatch(clause) for clause in clauses]
    if any(match is None for match in matches):
        raise ValueError("runtime requirement has an unsupported specifier")
    return all(
        _COMPARATORS[match.group(1)](
            selected, version_tuple(match.group(2))
        )
        for match in matches
        if match is not None
    )


def runtime_within(
    runtime_version: str, minimum: str, maximum: str
) -> bool:
    selected = version_tuple(normalized_version(runtime_version))
    lower = version_tuple(normalized_version(minimum))
    upper = version_tuple(normalized_version(maximum))
    if lower > upper:
        raise ValueError("runtime compatibility range is reversed")
    return lower <= selected <= upper


__all__ = [
    "normalized_version",
    "runtime_satisfies",
    "runtime_within",
    "version_tuple",
]

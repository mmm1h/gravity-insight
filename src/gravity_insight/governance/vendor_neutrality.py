"""Repository gate for vendor-neutral Runtime identities and visible content."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any


SOURCE_REGISTRY = "skills/sources/registry.json"
_VENDOR_LATIN = "thinking" + "ai"
_VENDOR_CJK = "数数" + "科技"
_BRAND = re.compile(f"{_VENDOR_LATIN}|{_VENDOR_CJK}", re.IGNORECASE)
_MACHINE_TOKEN = re.compile(
    rf"[A-Za-z0-9_.:/-]*{_VENDOR_LATIN}[A-Za-z0-9_.:/-]*|{_VENDOR_CJK}",
    re.IGNORECASE,
)
_NON_DEFAULT_TEXT = re.compile(
    r"^(?:docs/archive/|specs/agent-runtime/architecture-source\.md$|"
    r"specs/agent-runtime/directive\.json$|specs/agent-runtime/R[^/]*\.md$)"
)


@dataclass(frozen=True)
class VendorIdentityViolation:
    path: str
    line: int
    category: str
    token: str


def scan_vendor_identities(root: Path) -> tuple[VendorIdentityViolation, ...]:
    """Scan tracked Runtime surfaces while excluding protected historical prose."""

    violations: list[VendorIdentityViolation] = []
    for relative in _tracked_paths(root):
        if match := _BRAND.search(relative):
            violations.append(
                VendorIdentityViolation(relative, 0, "path", match.group(0))
            )
        if relative == SOURCE_REGISTRY or _NON_DEFAULT_TEXT.match(relative):
            continue
        raw = (root / relative).read_bytes()
        if b"\0" in raw or relative.casefold().endswith(".zip"):
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in _MACHINE_TOKEN.finditer(line):
                token = match.group(0)
                violations.append(
                    VendorIdentityViolation(
                        relative,
                        line_number,
                        _category(line, token),
                        token,
                    )
                )
    return tuple(
        sorted(
            violations,
            key=lambda item: (item.path, item.line, item.category, item.token),
        )
    )


def vendor_neutrality_error(root: Path) -> str | None:
    violations = scan_vendor_identities(root)
    if not violations:
        return None
    counts = Counter(item.category for item in violations)
    distribution = ",".join(
        f"{category}={count}" for category, count in sorted(counts.items())
    )
    sample = "; ".join(
        f"{item.path}:{item.line}:{item.category}:{item.token}"
        for item in violations[:5]
    )
    return (
        "vendor-neutrality gate failed: "
        f"violations={len(violations)} ({distribution}); first={sample}"
    )


def check_compilation_products(
    manifest_root: Path,
    provenance_path: Path,
    result: Any,
    project_root: Path,
    error_type: type[Exception],
) -> None:
    """Validate generated compiler products and the repository identity gate."""

    if vendor_error := vendor_neutrality_error(project_root):
        raise error_type(vendor_error)
    drift: list[str] = []
    expected_names = set(result.manifests)
    actual_names = {path.name for path in manifest_root.glob("*.json")}
    for name, payload in result.manifests.items():
        path = manifest_root / name
        if not path.is_file() or path.read_bytes() != payload:
            drift.append(str(path))
    for name in sorted(actual_names - expected_names):
        drift.append(f"unexpected:{manifest_root / name}")
    if not provenance_path.is_file() or provenance_path.read_bytes() != result.provenance:
        drift.append(str(provenance_path))
    if drift:
        raise error_type("compiled products are stale: " + ", ".join(drift))
    from scripts.generate_method_gap_report import emit_compiler_report

    emit_compiler_report(project_root)


def _tracked_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        return tuple(
            path.relative_to(root).as_posix()
            for path in sorted(root.rglob("*"))
            if path.is_file() and ".git" not in path.parts and "tmp" not in path.parts
        )
    return tuple(
        path
        for path in completed.stdout.decode("utf-8").split("\0")
        if path
    )


def _category(line: str, token: str) -> str:
    folded = token.casefold()
    if folded.startswith("analysis." + _VENDOR_LATIN + "."):
        return "journey_id"
    if folded.startswith(_VENDOR_LATIN + "-source://"):
        return "uri_scheme"
    if folded.startswith("gravity." + _VENDOR_LATIN) or folded.endswith(".schema.json"):
        return "schema_id"
    if re.fullmatch(rf"{_VENDOR_LATIN.upper()}_[A-Z0-9_]+", token):
        if re.search(r"environ|getenv|\$env:|environment", line, re.IGNORECASE):
            return "env_var"
        return "reason_code"
    if '"artifact_kind"' in line and folded.startswith(_VENDOR_LATIN + "_"):
        return "artifact_kind"
    if re.fullmatch(rf"{_VENDOR_LATIN}_[a-z0-9_]+", folded):
        return "module_name"
    return "visible_text"


__all__ = [
    "SOURCE_REGISTRY",
    "VendorIdentityViolation",
    "check_compilation_products",
    "scan_vendor_identities",
    "vendor_neutrality_error",
]

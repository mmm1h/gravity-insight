"""Require matching parent decoding and Python child stdio encoding."""

from __future__ import annotations

import argparse
import ast
import codecs
from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.subprocess-text-encoding-gate.v1"
_PYTHON_ROOTS = ("scripts", "src", "tests")
_SUBPROCESS_CALLS = frozenset(
    {"call", "check_call", "check_output", "getoutput", "getstatusoutput", "Popen", "run"}
)

# This file intentionally keeps subprocess streams binary so it can exercise a
# child configured with GBK while asserting that the public CLI emits UTF-8.
EXEMPT_FILES = {
    "tests/test_gravity_cli_stdio.py": (
        "Exercises locale-sensitive GBK child environments with binary streams; "
        "the parent decodes the CLI's UTF-8 contract explicitly."
    )
}
# Keyed by the enclosing function, not by a line number. A line number describes
# the file's current layout rather than the call: inserting a line anywhere above
# shifts it, the exemption stops matching, and a fail-closed gate then goes red
# for an edit that had nothing to do with it -- and shifts differently on each
# branch, so it can also go red only at merge time. Renaming the enclosing
# function does break the key, which is a change worth re-reading.
EXEMPT_CALLS = {
    ("src/gravity_insight/provider_rpc_transport.py", "_launch_subprocess"): (
        "Binary provider RPC: stdin/stdout/stderr are byte pipes and the expanded "
        "keywords contain only platform-specific process-creation flags."
    )
}

# Audited dynamic argv boundaries. These waive only executable inference, never
# the encoder check. Keys remain stable across line shifts. Mixed runners must
# pin Python stdio too; their isolated Python argv must explicitly use -X utf8.
COMMAND_EXEMPTIONS = {
    ("scripts/audit_release_dependencies.py", "audit_site_packages"): ("python", "python parameter selects the pip-audit interpreter"),
    ("scripts/check_installed_wheel_consumer.py", "_run"): ("python", "Git and Python install/probe/test commands; isolated probes use -X utf8"),
    ("scripts/check_installed_wheel_surface_matrix.py", "_run"): ("python", "Python pip install and isolated -X utf8 probe"),
    ("scripts/run_integrated_validation.py", "run_gate"): ("python", "GateSpec inventory includes Python and external commands"),
    ("scripts/supply_chain_common.py", "run_checked"): ("python", "Build, venv, pip and release tool command boundary"),
    ("scripts/validation_observability.py", "run_gate"): ("python", "Task-context gate commands include Python and git"),
    ("tests/test_installed_wheel.py", "_run"): ("python", "Python pip/build argv assembled by wheel test"),
    ("tests/test_release_channel.py", "_run"): ("python", "Python release probes and git fixtures"),
    ("scripts/scan_repository_secrets.py", "_history_lines"): ("external", "Locally assembled git log argv"),
    ("tests/test_release_channel.py", "ReleaseRecoveryStateTests.test_missing_github_release_is_created_from_verified_tag"): ("external", "Loop contains only literal git fixture commands"),
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    detector: str
    detail: str


def _subprocess_imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in _SUBPROCESS_CALLS:
                    functions.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args.posonlyargs + node.args.args
            defaults = list(zip(arguments[-len(node.args.defaults):], node.args.defaults))
            defaults.extend(zip(node.args.kwonlyargs, node.args.kw_defaults))
            for argument, default in defaults:
                if isinstance(default, ast.Attribute) and isinstance(default.value, ast.Name):
                    if default.value.id in modules and default.attr in _SUBPROCESS_CALLS:
                        functions.add(argument.arg)
    return modules, functions


def _is_direct_subprocess_call(
    node: ast.Call, modules: set[str], functions: set[str]
) -> bool:
    function = node.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr in _SUBPROCESS_CALLS
        and isinstance(function.value, ast.Name)
        and function.value.id in modules
    ) or (isinstance(function, ast.Name) and function.id in functions)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _has_encoding_contract(call: ast.Call) -> bool:
    value = _keyword(call, "encoding")
    return value is not None and not (
        isinstance(value, ast.Constant) and value.value is None
    )


def _text_mode(call: ast.Call) -> tuple[bool, bool]:
    """Return (may_be_enabled, is_statically_unknown)."""
    may_be_enabled = False
    unknown = False
    for name in ("text", "universal_newlines"):
        value = _keyword(call, name)
        if value is None:
            continue
        if isinstance(value, ast.Constant) and value.value in (False, None):
            continue
        if isinstance(value, ast.Constant) and value.value is True:
            may_be_enabled = True
        else:
            unknown = True
    return may_be_enabled, unknown


def _enclosing_functions(tree: ast.AST) -> dict[ast.Call, str]:
    """Map every call to the dotted name of the scope that encloses it.

    Module-level calls map to the empty string.
    """

    mapping: dict[ast.Call, str] = {}

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call):
                mapping[child] = ".".join(scope)
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                visit(child, scope + (child.name,))
            else:
                visit(child, scope)

    visit(tree, ())
    return mapping


def _utf8_literal(node: ast.expr | None) -> bool:
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    try:
        return codecs.lookup(node.value).name == "utf-8"
    except LookupError:
        return False


def _command_kind(call: ast.Call) -> tuple[str, list[ast.expr]]:
    command = call.args[0] if call.args else _keyword(call, "args")
    if not isinstance(command, (ast.List, ast.Tuple)) or not command.elts:
        return "unknown", []
    first = command.elts[0]
    if isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name):
        if first.value.id == "sys" and first.attr == "executable":
            return "python", command.elts[1:]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        executable = first.value.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if re.fullmatch(r"(?:pythonw?(?:[23](?:\.\d+)*)?|pypy[23]?)(?:\.exe)?", executable):
            return "python", command.elts[1:]
        # Do not treat an arbitrary literal executable as proof of non-Python:
        # console scripts and launchers can themselves be Python entry points.
        if executable in {"git", "git.exe", "gh", "gh.exe", "node", "node.exe"}:
            return "external", []
    return "unknown", command.elts[1:]


def _python_flags(arguments: list[ast.expr]) -> tuple[bool, bool, str | None]:
    isolated = False
    utf8 = False
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
            return isolated, utf8, "Python flags are dynamic before the script/module boundary"
        value = argument.value
        if value in {"-c", "-m", "--", "-"} or not value.startswith("-"):
            break
        if value == "-X":
            index += 1
            if index >= len(arguments) or not isinstance(arguments[index], ast.Constant):
                return isolated, utf8, "Python -X option is unresolved"
            option = arguments[index].value
        elif value.startswith("-X"):
            option = value[2:]
        else:
            option = None
            if re.fullmatch(r"-[IEsSuBOqbvd]+", value):
                isolated |= "I" in value or "E" in value
            else:
                return isolated, utf8, f"unrecognized Python interpreter flag: {value}"
        if option in {"utf8", "utf8=1", "utf8=0"}:
            utf8 = option != "utf8=0"
        index += 1
    return isolated, utf8, None


def _environment_pins_stdio(call: ast.Call) -> bool:
    environment = _keyword(call, "env")
    if not isinstance(environment, ast.Dict):
        return False
    pinned = False
    for key, value in zip(environment.keys, environment.values):
        if key is None or not isinstance(key, ast.Constant):
            pinned = False
        elif key.value == "PYTHONIOENCODING":
            pinned = _utf8_literal(value)
    return pinned


def _encoder_failure(call: ast.Call, arguments: list[ast.expr]) -> str | None:
    shell = _keyword(call, "shell")
    if shell is not None and not (isinstance(shell, ast.Constant) and shell.value is False):
        return "shell execution cannot prove Python argv/encoding; require shell=False"
    if not _utf8_literal(_keyword(call, "encoding")):
        return "Python text capture requires a literal UTF-8 parent encoding"
    isolated, utf8, unknown = _python_flags(arguments)
    if unknown:
        return unknown
    if isolated:
        if not utf8:
            return "Python -I/-E ignores PYTHON* environment; require interpreter -X utf8"
    elif not _environment_pins_stdio(call):
        return "Python child encoder is unpinned: require env with final PYTHONIOENCODING='utf-8' (inherited locale/overrides are not proof)"
    return None


def _source_findings(
    path: Path, relative: str
) -> tuple[list[Finding], list[dict[str, object]]]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [Finding(relative, 1, "subprocess-source-unreadable", str(exc))], []

    modules, functions = _subprocess_imports(tree)
    enclosing = _enclosing_functions(tree)
    findings: list[Finding] = []
    exemptions: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        has_contract = _has_encoding_contract(node)
        text_enabled, text_unknown = _text_mode(node)
        direct_subprocess = _is_direct_subprocess_call(node, modules, functions)
        dynamic_keywords = any(keyword.arg is None for keyword in node.keywords)
        function = enclosing.get(node, "")
        exemption_reason = EXEMPT_CALLS.get((relative, function))
        if (
            exemption_reason is not None
            and direct_subprocess
            and dynamic_keywords
            and not text_enabled
            and not text_unknown
        ):
            exemptions.append(
                {
                    "path": relative,
                    "function": function,
                    "line": node.lineno,
                    "reason": exemption_reason,
                }
            )
            continue
        if text_enabled and not has_contract:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "subprocess-text-encoding-missing",
                    "text=True or universal_newlines=True requires an explicit non-None encoding",
                )
            )
        elif text_unknown and not has_contract:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "subprocess-text-mode-unresolved",
                    "dynamic text/universal_newlines value has no explicit encoding contract",
                )
            )
        elif direct_subprocess and dynamic_keywords and not has_contract:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "subprocess-keywords-unresolved",
                    "expanded subprocess keywords cannot prove text mode is disabled or encoding is explicit",
                )
            )
        if direct_subprocess and (text_enabled or text_unknown or has_contract):
            kind, arguments = _command_kind(node)
            declared = COMMAND_EXEMPTIONS.get((relative, function))
            if kind == "unknown" and declared is not None:
                kind, reason = declared
                arguments = []
                exemptions.append({"path": relative, "function": function, "line": node.lineno, "reason": reason})
            if kind == "unknown":
                detail = "cannot prove executable is Python or an approved external tool; use literal argv/sys.executable or a reviewed function-keyed command exemption"
                detector = "subprocess-command-unresolved"
            elif kind == "python":
                detail = _encoder_failure(node, arguments)
                detector = "subprocess-python-encoder-unpinned"
            else:
                detail = None
            if detail:
                findings.append(Finding(relative, node.lineno, detector, f"{function or '<module>'}: {detail}"))
    return findings, exemptions


def check_repository(root: Path = ROOT) -> tuple[int, dict[str, object]]:
    findings: list[Finding] = []
    scanned = 0
    exemptions: list[dict[str, object]] = []
    for relative_root in _PYTHON_ROOTS:
        base = root / relative_root
        if not base.is_dir():
            findings.append(
                Finding(relative_root, 1, "subprocess-scan-root-missing", "required scan root is absent")
            )
            continue
        for path in sorted(base.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            reason = EXEMPT_FILES.get(relative)
            if reason is not None:
                exemptions.append({"path": relative, "reason": reason})
            scanned += 1
            source_findings, source_exemptions = _source_findings(path, relative)
            findings.extend(source_findings)
            exemptions.extend(source_exemptions)

    findings.sort()
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
        "scanned_python_files": scanned,
        "exemptions": exemptions,
    }
    return (1 if findings else 0), receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    code, receipt = check_repository(args.root.resolve())
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

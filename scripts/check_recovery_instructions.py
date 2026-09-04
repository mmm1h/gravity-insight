"""Fail when recovery commands or claimed workflow artifacts are not real."""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import runpy
import shlex
import sys
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.recovery-instruction-gate.v1"
_PYTHON_ROOTS = ("src/gravity_insight", "scripts")
_WORKFLOW_ROOT = ".github/workflows"
_COMMAND_RE = re.compile(r"`(?P<command>gravity(?:\s+[^`]+)?)`")
_EXACT_FILE_RE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z0-9]{1,12})(?![A-Za-z0-9_-])"
)
_UPLOADED_RE = re.compile(r"\buploaded\s+(?P<label>[A-Za-z0-9_.-]+)", re.IGNORECASE)
_ARTIFACT_SUFFIXES = frozenset(
    {".json", ".jsonl", ".log", ".md", ".ndjson", ".txt", ".yaml", ".yml", ".zip"}
)
_RECOVERY_FIELDS = frozenset(
    {
        "next_action",
        "next_actions",
        "remediation",
        "remediations",
        "remedy",
        "command",
        "commands",
        "default_command",
        "recovery",
        "recovery_action",
        "recovery_instruction",
        "suggested_action",
        "suggested_actions",
    }
)
_EXPECTED_CODE_COMMANDS = {
    "HUB_SKILL_MISSING": ("skills", "list"),
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    detector: str
    subject: str
    detail: str


@dataclass(frozen=True)
class CommandResolution:
    command_path: tuple[str, ...]
    error: str | None = None


def _field_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.casefold()
    return lowered in _RECOVERY_FIELDS or lowered.endswith("_next_action")


def _target_names(node: ast.AST) -> Iterable[str]:
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for item in node.elts:
            yield from _target_names(item)


def _render(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
            else:
                parts.append("<value>")
        return ["".join(parts)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [left + right for left in _render(node.left) for right in _render(node.right)]
    if isinstance(node, ast.IfExp):
        return [*_render(node.body), *_render(node.orelse)]
    if isinstance(node, (ast.List, ast.Tuple)):
        return [rendered for item in node.elts for rendered in _render(item)]
    return []


def _recovery_expressions(tree: ast.AST) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if _field_name(keyword.arg):
                    yield keyword.value
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and _field_name(key.value)
                ):
                    yield value
        elif isinstance(node, ast.Assign):
            if any(
                _field_name(name)
                for target in node.targets
                for name in _target_names(target)
            ):
                yield node.value
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and any(
                _field_name(name) for name in _target_names(node.target)
            ):
                yield node.value


def recovery_commands(path: Path) -> list[tuple[int, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    commands: set[tuple[int, str]] = set()
    for expression in _recovery_expressions(tree):
        for text in _render(expression):
            for match in _COMMAND_RE.finditer(text):
                commands.add((expression.lineno, match.group("command")))
            stripped = text.strip().rstrip(".")
            if stripped.startswith("gravity ") and "`" not in stripped:
                commands.add((expression.lineno, stripped))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (
                isinstance(key, ast.Constant)
                and key.value == "argv"
                and isinstance(value, (ast.List, ast.Tuple))
            ):
                continue
            tokens = [
                rendered
                for item in value.elts
                for rendered in (_render(item) or ["<value>"])
            ]
            if tokens and tokens[0] == "gravity":
                commands.add((value.lineno, " ".join(tokens)))
    for expression in ast.walk(tree):
        if not isinstance(expression, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            continue
        for text in _render(expression):
            lowered = text.casefold()
            if not any(
                verb in lowered
                for verb in ("run ", "rerun ", "retry ", "use ", "call ", "browse ", "inspect ")
            ):
                continue
            for match in _COMMAND_RE.finditer(text):
                commands.add((expression.lineno, match.group("command")))
    return sorted(commands)


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if len(actions) > 1:
        raise RuntimeError(f"multiple subparser actions in {parser.prog}")
    return actions[0] if actions else None


def _option_actions(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    return {
        option: action
        for action in parser._actions
        for option in action.option_strings
    }


def _skip_option(
    parser: argparse.ArgumentParser, tokens: Sequence[str], index: int
) -> int:
    token = tokens[index]
    if token in {"--help", "-h"}:
        return index + 1
    if token == "--workspace" and parser.prog == "gravity":
        return min(len(tokens), index + 2)
    action = _option_actions(parser).get(token.split("=", 1)[0])
    if action is None or "=" in token:
        return index + 1
    if action.nargs == 0:
        return index + 1
    if action.nargs in (None, 1, "?"):
        return min(len(tokens), index + 2)
    if isinstance(action.nargs, int):
        return min(len(tokens), index + 1 + action.nargs)
    cursor = index + 1
    while cursor < len(tokens) and not tokens[cursor].startswith("-"):
        cursor += 1
    return cursor


def _literal_positionals_before_help(
    parser: argparse.ArgumentParser, tokens: Sequence[str]
) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--help", "-h"}:
            break
        if token.startswith("-"):
            index = _skip_option(parser, tokens, index)
            continue
        values.append(token)
        index += 1
    return values


def resolve_cli_command(command: str) -> CommandResolution:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as exc:
        return CommandResolution((), f"command is not shell-tokenizable: {exc}")
    if not tokens or tokens[0] != "gravity":
        return CommandResolution((), "command must start with gravity")

    from gravity_insight import cli as insight_cli
    from gravity_insight.census import cli as census_cli
    from gravity_insight.sql import __main__ as sql_cli

    remaining = tokens[1:]
    command_path: list[str] = []
    if remaining and remaining[0] in {"insight", "sql", "census"}:
        namespace = remaining.pop(0)
        command_path.append(namespace)
        parser = {
            "insight": insight_cli.build_parser,
            "sql": sql_cli.build_parser,
            "census": census_cli.build_parser,
        }[namespace]()
    else:
        parser = insight_cli.build_parser()

    index = 0
    while True:
        subparser = _subparsers(parser)
        while index < len(remaining) and remaining[index].startswith("-"):
            if remaining[index] in {"--help", "-h"}:
                return CommandResolution(tuple(command_path))
            index = _skip_option(parser, remaining, index)
        if subparser is None:
            if any(token in {"--help", "-h"} for token in remaining[index:]):
                positional = _literal_positionals_before_help(
                    parser, remaining[index:]
                )
                if positional:
                    return CommandResolution(
                        tuple(command_path),
                        "help target contains non-command token(s): "
                        + ", ".join(positional),
                    )
            return CommandResolution(tuple(command_path))
        if index >= len(remaining):
            if subparser.required:
                return CommandResolution(
                    tuple(command_path), "required subcommand is missing"
                )
            return CommandResolution(tuple(command_path))
        token = remaining[index]
        if token in subparser.choices:
            command_path.append(token)
            parser = subparser.choices[token]
            index += 1
            continue
        return CommandResolution(
            tuple(command_path),
            f"{token!r} is not a registered subcommand of {parser.prog}",
        )


def _python_findings(root: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    scanned = 0
    for relative_root in _PYTHON_ROOTS:
        base = root / relative_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            scanned += 1
            relative = path.relative_to(root).as_posix()
            try:
                commands = recovery_commands(path)
            except (OSError, UnicodeError, SyntaxError) as exc:
                findings.append(
                    Finding(relative, 1, "recovery-source-unreadable", relative, str(exc))
                )
                continue
            for line, command in commands:
                resolution = resolve_cli_command(command)
                if resolution.error:
                    findings.append(
                        Finding(
                            relative,
                            line,
                            "recovery-command-unresolvable",
                            command,
                            resolution.error,
                        )
                    )
    return findings, scanned


def _step_blocks(lines: list[str]) -> list[tuple[int, int]]:
    starts = [index for index, line in enumerate(lines) if re.match(r"^\s{6}- name:", line)]
    return [
        (start, starts[position + 1] if position + 1 < len(starts) else len(lines))
        for position, start in enumerate(starts)
    ]


def _workflow_artifact_proof(
    lines: list[str], claim_line: int, filename: str
) -> str | None:
    blocks = _step_blocks(lines)
    upload_blocks = [
        (start, end)
        for start, end in blocks
        if start < claim_line
        and any("actions/upload-artifact@" in line for line in lines[start:end])
        and any(
            filename in line or re.search(r"gravity-drift[/\\]\\?\*", line)
            for line in lines[start:end]
        )
    ]
    if not upload_blocks:
        return f"no preceding upload-artifact step names {filename}"
    if not any(
        any(re.match(r"^\s+if:\s*always\(\)\s*$", line) for line in lines[start:end])
        for start, end in upload_blocks
    ):
        return f"the upload for {filename} is not guarded by if: always()"

    bindings: list[tuple[int, str]] = []
    for index, line in enumerate(lines[:claim_line]):
        match = re.search(
            rf"\$(\w+)\s*=\s*Join-Path\b.*[\"']{re.escape(filename)}[\"']",
            line,
        )
        if match:
            bindings.append((index, match.group(1)))
    for binding_line, variable in bindings:
        fallible_lines = [
            index
            for index, line in enumerate(lines[binding_line:claim_line], binding_line)
            if re.search(r"\bgravity\s+\S+", line)
        ]
        creation_lines = [
            index
            for index, line in enumerate(lines[binding_line:claim_line], binding_line)
            if "Set-Content" in line and re.search(rf"\${re.escape(variable)}\b", line)
        ]
        if creation_lines and (
            not fallible_lines or min(creation_lines) < min(fallible_lines)
        ):
            return None
    return f"{filename} is not created before the fallible workflow command"


def _workflow_findings(root: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    scanned = 0
    base = root / _WORKFLOW_ROOT
    if not base.is_dir():
        return findings, scanned
    for path in sorted((*base.glob("*.yml"), *base.glob("*.yaml"))):
        scanned += 1
        relative = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uploaded" not in line.casefold() or not any(
                word in line.casefold() for word in ("inspect", "read", "open")
            ):
                continue
            uploaded = _UPLOADED_RE.search(line)
            uploaded_label = uploaded.group("label").rstrip(".,;:") if uploaded else None
            if uploaded_label and (
                _EXACT_FILE_RE.fullmatch(uploaded_label) is None
                or Path(uploaded_label).suffix.casefold() not in _ARTIFACT_SUFFIXES
            ):
                findings.append(
                    Finding(
                        relative,
                        index + 1,
                        "recovery-artifact-not-exact",
                        uploaded_label,
                        "uploaded recovery artifacts must use an exact filename",
                    )
                )
            filenames = {
                filename
                for filename in _EXACT_FILE_RE.findall(line)
                if Path(filename).suffix.casefold() in _ARTIFACT_SUFFIXES
            }
            for filename in sorted(filenames):
                proof_error = _workflow_artifact_proof(lines, index, filename)
                if proof_error:
                    findings.append(
                        Finding(
                            relative,
                            index + 1,
                            "recovery-artifact-unavailable",
                            filename,
                            proof_error,
                        )
                    )
    return findings, scanned


def _semantic_findings(root: Path) -> list[Finding]:
    source = root / "src/gravity_insight/error_models.py"
    if not source.is_file():
        return []
    namespace = runpy.run_path(str(source))
    default_next_action = namespace["_default_next_action"]
    findings: list[Finding] = []
    for code, expected in sorted(_EXPECTED_CODE_COMMANDS.items()):
        action = default_next_action(code, None)
        commands = [match.group("command") for match in _COMMAND_RE.finditer(action)]
        resolved = [resolve_cli_command(command) for command in commands]
        if not resolved or not any(
            item.error is None and item.command_path[-len(expected) :] == expected
            for item in resolved
        ):
            findings.append(
                Finding(
                    "src/gravity_insight/error_models.py",
                    162,
                    "recovery-command-wrong-owner",
                    code,
                    "expected recovery command owner " + " ".join(expected),
                )
            )
    return findings


def check_repository(root: Path = ROOT) -> tuple[int, dict[str, object]]:
    python_findings, python_files = _python_findings(root)
    workflow_findings, workflow_files = _workflow_findings(root)
    semantic_findings = _semantic_findings(root)
    findings = sorted([*python_findings, *workflow_findings, *semantic_findings])
    receipt: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if not findings else "fail",
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
        "scanned": {
            "python_files": python_files,
            "workflow_files": workflow_files,
        },
    }
    return (1 if findings else 0), receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    code, receipt = check_repository(args.root.resolve())
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

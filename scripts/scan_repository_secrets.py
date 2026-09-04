from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from detect_secrets.core.scan import scan_file, scan_line
from detect_secrets.settings import transient_settings


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = ROOT / "scripts" / "secret_scan_allowlist.json"

# Provider-specific token, private-key, basic-auth, JWT and secret-keyword rules.
# Generic entropy detectors are intentionally excluded: this repository owns
# thousands of immutable digests and encrypted evaluation blobs. Those values
# are identifiers/ciphertext, not authentication material, and drowning the
# credential detectors in unreviewed entropy findings would make the gate unusable.
PLUGINS = (
    "ArtifactoryDetector",
    "AWSKeyDetector",
    "AzureStorageKeyDetector",
    "BasicAuthDetector",
    "CloudantDetector",
    "DiscordBotTokenDetector",
    "GitHubTokenDetector",
    "GitLabTokenDetector",
    "IbmCloudIamDetector",
    "IbmCosHmacDetector",
    "IPPublicDetector",
    "JwtTokenDetector",
    "KeywordDetector",
    "MailchimpDetector",
    "NpmDetector",
    "OpenAIDetector",
    "PrivateKeyDetector",
    "PypiTokenDetector",
    "SendGridDetector",
    "SlackDetector",
    "SoftlayerDetector",
    "SquareOAuthDetector",
    "StripeDetector",
    "TelegramBotTokenDetector",
    "TwilioKeyDetector",
)
FILTERS = (
    "detect_secrets.filters.allowlist.is_line_allowlisted",
    "detect_secrets.filters.heuristic.is_indirect_reference",
    "detect_secrets.filters.heuristic.is_likely_id_string",
    "detect_secrets.filters.heuristic.is_lock_file",
    "detect_secrets.filters.heuristic.is_not_alphanumeric_string",
    "detect_secrets.filters.heuristic.is_potential_uuid",
    "detect_secrets.filters.heuristic.is_prefixed_with_dollar_sign",
    "detect_secrets.filters.heuristic.is_sequential_string",
    "detect_secrets.filters.heuristic.is_swagger_file",
    "detect_secrets.filters.heuristic.is_templated_secret",
)


class SecretScanError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    detector: str
    hashed_secret: str
    scope: str
    line: int | None = None
    commit: str | None = None

    @property
    def allowlist_key(self) -> tuple[str, str, str]:
        return self.path, self.detector, self.hashed_secret


def detector_settings() -> dict[str, Any]:
    return {
        "plugins_used": [{"name": name} for name in PLUGINS],
        "filters_used": [{"path": path} for path in FILTERS],
    }


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout or "no output").strip()
        raise SecretScanError(f"git {' '.join(arguments)} failed: {diagnostic[-2000:]}")
    return completed


def tracked_paths(root: Path) -> list[str]:
    completed = _git(root, "ls-files", "-z")
    return sorted(path for path in completed.stdout.split("\0") if path)


def scan_tracked(root: Path) -> list[Finding]:
    findings: set[Finding] = set()
    for relative in tracked_paths(root):
        path = root / relative
        if not path.is_file():
            continue
        for secret in scan_file(str(path)):
            findings.add(
                Finding(
                    path=relative.replace("\\", "/"),
                    detector=secret.type,
                    hashed_secret=secret.secret_hash,
                    scope="tracked",
                    line=secret.line_number or None,
                )
            )
    return sorted(findings)


def _history_lines(
    root: Path, revision_range: str | None = None
) -> Iterator[tuple[str, str, str]]:
    command = [
        "git",
        "-c",
        "core.quotepath=false",
        "log",
    ]
    if revision_range is None:
        command.extend(("--all", "--root"))
    else:
        command.append(revision_range)
    command.extend((
        "--no-renames",
        "--format=%x1e%H",
        "--unified=0",
        "--no-ext-diff",
        "--text",
        "-p",
        "--",
        ".",
    ))
    process = subprocess.Popen(
        command,
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise SecretScanError("git history stdout is unavailable")
    commit = ""
    path = ""
    for raw in process.stdout:
        line = raw.rstrip("\r\n")
        if line.startswith("\x1e"):
            commit = line[1:].strip()
            path = ""
        elif line.startswith("+++ "):
            selected = line[4:]
            path = "" if selected == "/dev/null" else selected.removeprefix("b/")
        elif path and line.startswith("+") and not line.startswith("+++"):
            yield commit, path, line[1:]
    stderr = process.stderr.read() if process.stderr is not None else ""
    return_code = process.wait()
    if return_code != 0:
        raise SecretScanError(f"git history scan failed: {stderr.strip()[-2000:]}")


def _incremental_history_range(root: Path, since: str) -> tuple[str, str]:
    merge_base = _git(root, "merge-base", since, "HEAD").stdout.strip()
    if not merge_base:
        raise SecretScanError(f"history base has no merge-base with HEAD: {since}")
    return merge_base, f"{merge_base}..HEAD"


def scan_history(root: Path, revision_range: str | None = None) -> list[Finding]:
    shallow = _git(root, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow != "false":
        raise SecretScanError("Git history is shallow; a complete history scan is impossible")
    findings: set[Finding] = set()
    for commit, path, line in _history_lines(root, revision_range):
        for secret in scan_line(line):
            findings.add(
                Finding(
                    path=path.replace("\\", "/"),
                    detector=secret.type,
                    hashed_secret=secret.secret_hash,
                    scope="history",
                    commit=commit,
                )
            )
    return sorted(findings)


def load_allowlist(path: Path, *, today: date | None = None) -> dict[tuple[str, str, str], dict[str, str]]:
    today = today or date.today()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretScanError(f"secret allowlist is unavailable or invalid: {exc}") from exc
    if document.get("schema_version") != "gravity.secret-scan-allowlist.v1":
        raise SecretScanError("secret allowlist schema_version is invalid")
    selected: dict[tuple[str, str, str], dict[str, str]] = {}
    for index, item in enumerate(document.get("entries", [])):
        required = {"path", "detector", "value_sha1", "reason", "review_expires"}
        if set(item) != required:
            raise SecretScanError(f"secret allowlist entry {index} has invalid fields")
        if len(item["reason"].strip()) < 30:
            raise SecretScanError(f"secret allowlist entry {index} lacks a specific reason")
        try:
            expiry = date.fromisoformat(item["review_expires"])
        except ValueError as exc:
            raise SecretScanError(f"secret allowlist entry {index} has invalid expiry") from exc
        if expiry < today:
            raise SecretScanError(
                f"secret allowlist entry {index} expired on {item['review_expires']}"
            )
        key = (item["path"], item["detector"], item["value_sha1"])
        if key in selected:
            raise SecretScanError(f"duplicate secret allowlist entry {index}")
        selected[key] = item
    return selected


def evaluate(
    findings: Iterable[Finding], allowlist: dict[tuple[str, str, str], dict[str, str]]
) -> tuple[list[Finding], list[Finding]]:
    allowed, blocked = [], []
    for finding in findings:
        (allowed if finding.allowlist_key in allowlist else blocked).append(finding)
    return allowed, blocked


def scan_repository(
    root: Path,
    *,
    include_history: bool,
    allowlist_path: Path,
    history_since: str | None = None,
) -> tuple[int, dict[str, Any]]:
    if include_history and history_since is not None:
        raise SecretScanError("full and incremental history scopes are mutually exclusive")
    history_base: str | None = None
    revision_range: str | None = None
    if history_since is not None:
        history_base, revision_range = _incremental_history_range(root, history_since)
    with transient_settings(detector_settings()):
        tracked = scan_tracked(root)
        history = (
            scan_history(root, revision_range)
            if include_history or revision_range is not None
            else []
        )
    findings = sorted({*tracked, *history})
    allowlist = load_allowlist(allowlist_path)
    allowed, blocked = evaluate(findings, allowlist)
    receipt: dict[str, Any] = {
        "allowlist_sha256": hashlib.sha256(allowlist_path.read_bytes()).hexdigest(),
        "allowlisted_count": len(allowed),
        "detectors": list(PLUGINS),
        "finding_count": len(findings),
        "history_base": history_base,
        "history_included": include_history,
        "history_scope": (
            "full" if include_history else "incremental" if history_since else "none"
        ),
        "history_commit_count": (
            int(_git(root, "rev-list", "--count", "--all").stdout.strip())
            if include_history
            else (
                int(_git(root, "rev-list", "--count", revision_range).stdout.strip())
                if revision_range is not None
                else 0
            )
        ),
        "repository_head": _git(root, "rev-parse", "HEAD").stdout.strip(),
        "scanned_tracked_file_count": len(tracked_paths(root)),
        "status": "secrets_found" if blocked else "passed",
        "tool": {
            "name": "detect-secrets",
            "version": importlib.metadata.version("detect-secrets"),
        },
        "unreviewed_findings": [asdict(item) for item in blocked],
    }
    return (1 if blocked else 0), receipt


def _write_receipt(path: Path | None, receipt: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan Git-tracked content and optionally complete text history for secrets."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    history = parser.add_mutually_exclusive_group()
    history.add_argument("--history", action="store_true")
    history.add_argument(
        "--history-since",
        metavar="REVISION",
        help="scan commits added since the revision's merge-base with HEAD",
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        code, receipt = scan_repository(
            args.root.resolve(),
            include_history=args.history,
            allowlist_path=args.allowlist.resolve(),
            history_since=args.history_since,
        )
    except (OSError, ValueError, SecretScanError) as exc:
        code, receipt = 2, {"reason": str(exc), "status": "unable_to_scan"}
    _write_receipt(args.receipt, receipt)
    stream = sys.stdout if code == 0 else sys.stderr
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True), file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

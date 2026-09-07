"""Credential-free CLI for local cache accounting and conservative cleanup."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .json_output import dumps
from .cache_lifecycle import inventory, inventory_error, prune
from .errors import LOCAL_ERROR_EXIT


def _nonnegative(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gravity cache", description="Offline cache inventory and fail-closed cleanup.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (("status", "Read-only inventory of canonical and legacy cache roots."),
                              ("prune", "Preview safe deletions; uncertain references are retained.")):
        child = commands.add_parser(name, description=description)
        child.add_argument("--json", action="store_true", help="emit machine-readable JSON")
        child.add_argument("--min-age-days", type=_nonnegative, default=7, metavar="N", help="obsolete-file grace (default: 7)")
        child.add_argument("--max-files", type=_nonnegative, metavar="N", help="report file budget; never force deletion")
        child.add_argument("--max-disk-bytes", type=_nonnegative, metavar="N", help="report allocation budget; never force deletion")
        if name == "prune":
            mode = child.add_mutually_exclusive_group()
            mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
            mode.add_argument("--execute", action="store_true", help="delete only revalidated safe candidates")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    options = {"min_age_days": args.min_age_days, "max_files": args.max_files,
               "max_disk_bytes": args.max_disk_bytes}
    try:
        report = prune(execute=args.execute, **options) if args.command == "prune" else inventory(**options)[0]
    except (OSError, ValueError, RuntimeError):
        # Never interpolate filesystem exceptions: they can contain private paths.
        report = inventory_error()
    report["network_called"] = False
    if args.json:
        print(dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(_text(report))
    return 0 if report["status"] == "ok" else LOCAL_ERROR_EXIT


def _sizes(value: dict) -> str:
    disk = value["disk_bytes"]
    return f"{value['files']} files | logical {value['logical_bytes']} B | disk {disk if disk is not None else 'unknown'} B"


def _text(report: dict) -> str:
    if report["status"] == "error":
        return "CACHE_INVENTORY_FAILED (paths redacted)"
    lines = [f"Cache {report.get('mode', 'status')}: {report['status']}",
             f"Total: {_sizes(report['summary'])}",
             f"Reclaimable: {_sizes(report['summary']['reclaimable'])}",
             f"Retained: {_sizes(report['summary']['retained'])}"]
    for root in report["roots"]:
        lines.append(f"{root['root_id']} [{root['location']}]: {_sizes(root)}")
        units = root["allocation_units"]
        lines.append(f"  directory allocation: {root['directory_disk_bytes']} B; cluster: {units['cluster_bytes']} B; resident record: {units['resident_record_bytes']} B")
    for row in (*report["categories"], *report["residues"]):
        label = row.get("category", row.get("kind"))
        lines.append(f"{label}: {_sizes(row)}; reclaimable {_sizes(row['reclaimable'])}; retained {_sizes(row['retained'])}")
        for reason, count in row["retained_reasons"].items():
            lines.append(f"  {reason}: {count} files; {report['reason_codes'][reason]}")
    for kind in ("OBSOLETE_PICKLE_NO_READER", "ORPHAN_CATALOG_STAGING", "ACCOUNT_SNAPSHOT"):
        lines.append(f"{kind}: {report['reason_codes'][kind]}")
    policy = report["http_receipts"]
    lines.append(f"HTTP receipts: {_sizes(policy)}; policy {policy['max_age_days']} days / {policy['max_files_per_directory']} files per directory, not a hard limit; no byte quota.")
    lines.append("HTTP exceptions: " + ", ".join(policy["exceptions"]))
    lines.append(f"HTTP retained_over_budget directories: {policy['retained_over_budget_directories']}")
    lines.append(f"Metadata same-size groups: {len(report['metadata_size_peers'])}; content equivalence unverified, not reclaimable.")
    lines.append(f"retained_over_budget: {str(report['budget']['retained_over_budget']).lower()}; reasons: {', '.join(report['budget']['reason_codes']) or 'none'}")
    for decision in report.get("decisions", []):
        lines.append(f"{decision['root_id']}/{decision['item_id']} {decision['action']} {decision['kind']} {decision['reason_code']}")
    if "deleted" in report:
        lines.append(f"Deleted: {_sizes(report['deleted'])}")
    if report["scan_errors"]:
        lines.append("Incomplete scan; linked/inaccessible paths omitted and affected roots retained.")
    lines.append("Historical custom cache roots cannot be discovered automatically. Root totals include directory allocation; NTFS resident files use the queried record size when available, otherwise native stream allocation. Hard links may share storage.")
    return "\n".join(lines)

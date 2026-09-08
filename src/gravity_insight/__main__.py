"""Unified command line for the standalone Gravity SDK."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence


_HELP = """Gravity SDK

Usage:
  gravity [--workspace <gravity.toml|directory>] <command> [options]
  gravity agent [query]
  gravity agent --input <questions.json>
  gravity agent-catalog categories|category <domain>|describe <selector>|host
  gravity plan schema
  gravity plan run --input <plan.json>
  gravity journey list|verify|certifications|describe|can-run|impact|run
  gravity maturity score
  gravity runtime health
  gravity cache status|prune
  gravity docs check
  gravity capabilities trust|validate|impact
  gravity skills list|show|sync|search|resolve|lock|fetch|install|update|verify|audit|status|bootstrap|repair|host-install-plan
  gravity trusted-packs resolve|lock|fetch|verify|install-plan
  gravity action segment-update|dashboard-delivery preview|execute --input <json|file|->
  gravity experiment propose|outcome-handoff --input <json|file|->
  gravity analysis saved list|get|prepare|run
  gravity analysis saved create|update|delete --dry-run|--execute
  gravity analysis template list|prepare|run
  gravity analysis query --kind <kind> --spec <json> --app <id>
  gravity analysis query batch --input <queries.json> [--dry-run]
  gravity analysis bootstrap --app <id> --start <date> --end <date> --target <event> --plan-output <plan.json>
  gravity analysis dashboard prepare|run --app <alias|id> --ref <id|name> --start <date> --end <date>
  gravity analysis user journey --app <alias|id> --client-id <id> --date <date>
  gravity analysis user-detail-aggregate --input <json|file|->
  gravity analysis segment snapshot --app <alias|id> --ref <id|name> --date <date>
  gravity analysis segment members --app <alias|id> --ref <id|name> [--fields <a,b>]
  gravity analysis segment create-from-analysis|create-from-rule|update|update-rule|refresh|delete --dry-run|--execute
  gravity analysis order directory --app <alias|id> --date <date>
  gravity analysis order trace --app <alias|id> --date <date> --trace-id <id>
  gravity analysis monetization detail --app <alias|id> --date <date>
  gravity multidim query --app <alias|id> --input <json|file|->
  gravity semantic compose --app <alias|id> --input <json|file|->
  gravity semantics list|describe|resolve|validate [--source <semantic-source>]
  gravity operators list|describe|validate
  gravity models list|describe|evaluate [--source <model-artifact>]
  gravity context project describe|index|search|get|pack|verify
  gravity derive --input <json|file|->
  gravity reports pulse --app <alias|id> --start <date> --end <date>
  gravity reports usage
  gravity analysis dashboard kanban schema
  gravity analysis dashboard kanban mutate --action <action> --input <json|file|-> --dry-run|--execute
  gravity materials performance --app <alias|id> --start <date> --end <date>
  gravity materials fetch --source <local|bytedance_project> --input <json|file|-> --ref-field <field> --ref <value> --role <file|thumbnail> --output <file>
  gravity materials title-packages --app <alias|id> --package-kind <regular|standard>
  gravity promotion performance --app <alias|id> --start <date> --end <date>
  gravity promotion custom-audiences
  gravity promotion bilibili-account-performance --start <date> --end <date>
  gravity promotion advertiser-profile --start <date> --end <date>
  gravity export describe <operation-id>
  gravity export run <operation-id> --input <json|file|-> --columns <codes> --idempotency-key <key> --output <file>
  gravity insight <command> [options]
  gravity apps snapshot --app <alias|id>
  gravity apps permission-profile
  gravity metadata sync --app-id <id>|--all-apps
  gravity metadata status [--app-id <id>]
  gravity metadata search|events|properties|vocabulary [query]
  gravity metadata tables [query]
  gravity find <query>
  gravity recipe validate|check|accept-contract <name>
  gravity run @<recipe> [options]
  gravity run <operation-id> [options]
  gravity receipts list|get|export
  gravity account-pool [--enable --account-env <path> ...] status|read|read-all|run|plan|sql-products
  gravity sql <command> [options]
  gravity census <command> [options]

Semantic routes (three separate inputs):
  gravity.toml [semantic_context]: caller-owned literal Agent routing, verified
    queries and derived formulas; does not register Business Semantic URIs.
  gravity semantic compose: explicit physical member/version request -> Multidim.
    Does not consume a Business Source or the output of semantics resolve.
  gravity semantics: offline Business Source Definition/Binding inspection.
    Sources are explicit local files, never scanned or loaded from gravity.toml.
    Execution depends on a registered Skill/Journey and its project overlay;
    resolved is not execution readiness and does not enforce Journey claim gates.

Business Source arguments (all four commands are offline):
  gravity semantics list [--source <file> ...] [--kind <kind>]
    Lists definitions; without --source only the built-in App entity is present.
    kind: metric, dimension, entity, cohort, event, sku, activity, release, schema.
  gravity semantics validate --source <file>
    Validates one complete Source. Alternatively use --input <json|file|->;
    supply exactly one of --source or --input, not both.
  gravity semantics describe <uri> [--source <file> ...]
    Shows exact-version definitions, bindings and conflicts; does not select scope.
  gravity semantics resolve <uri> [--source <file> ...]
    [--project-id <id>] [--app-alias <alias>] [--at <date> | --start <date> --end <date>]
    URI includes @version. --source is JSON/TOML; repeat it for list/describe/resolve.
    project-id and app-alias select Binding scope; alias is a literal here, not
    a workspace App lookup. Omitted scope does not infer a workspace project/App.
    Dates are YYYY-MM-DD, inclusive; --at excludes --start/--end, which need both.
    Without dates, resolution uses today. The full window must be covered by
    both Definition and Binding effective ranges. Resolve returns data, not a read.

Compose version choice (report.ap-cost-observation, no implicit latest/default):
  v1: original ap_cost request shape without the frontend request profile.
  v2: small frontend-profile metric set with dimension-bound filters.
  v3: expanded acquisition/payer/revenue members, new members limited to day/week.
  v4: v3 members with fetched_at-scoped, point-in-time and cross-execution limits.
  New illustrative inputs below pin v4 for its explicit observation limits;
  existing project bindings stay on their approved exact version, not auto-upgraded.
  Member versions are independent of the parent Definition version. Inspect
  gravity semantic compose --input-schema before changing a member or grain.

Packaged fictional examples (PowerShell; use the Python owning this Runtime):
  $examples = python -c "from importlib.resources import files; print(files('gravity_insight').joinpath('contracts/examples'))"
  gravity semantics validate --source "$examples/business-source.json"
  gravity semantics resolve metric://example/acquisition-spend@1 --source "$examples/business-source.json" --project-id example-project --app-alias demo --start 2026-08-01 --end 2026-08-07
  gravity semantic compose --app 1 --input "$examples/semantic-compose-input.json" --dry-run
  App 1 and fictional-channel are dry-run placeholders, not real access scope.
  Before real use, copy the files to your project and review owner, URI, business
  meaning, currency, timezone, effective range, claims and physical members.
  Compose execution needs an authorized App/filter/window and removal of --dry-run;
  --app accepts a workspace alias or positive id; --workspace selects gravity.toml.
  For strictly offline smoke, set GRAVITY_INSIGHT_AUTO_UPGRADE=0 and
  GRAVITY_INSIGHT_AUTO_SKILLS=0 before starting the commands.

Compatibility:
  Existing Insight commands may omit the `insight` namespace.

For an Agent-ready machine protocol, run `gravity agent`.
Run `gravity insight --help`, `gravity sql --help`, or
`gravity census --help` for command-specific help.
"""


def command_requires_credentials(args: Sequence[str], parser_factory: object) -> bool:
    from .onboarding import command_requires_credentials as implementation

    return implementation(args, parser_factory)


def ensure_first_run_credentials(*, requires_credentials: bool) -> bool:
    from .onboarding import ensure_first_run_credentials as implementation

    return implementation(requires_credentials=requires_credentials)


def _startup_upgrade_exit(args: Sequence[str]) -> int | None:
    from .auto_upgrade import (
        _target_python_from_environment,
        maybe_auto_upgrade,
        startup_update_enabled,
    )

    if not startup_update_enabled(args):
        return None
    result = maybe_auto_upgrade(args, target_python=_target_python_from_environment())
    if result.status == "installed" and result.state is not None:
        from ._auto_upgrade_install import activate_install

        return activate_install(result.state, args, output=sys.stderr)
    return None


def _startup_skill_maintenance(args: Sequence[str]) -> None:
    from .skill_maintenance_startup import maybe_bootstrap_bundled_skills

    maybe_bootstrap_bundled_skills(args)


def main(argv: Sequence[str] | None = None) -> int:
    from .cli_stdio import configure_utf8_stdio, emit_entry_error

    configure_utf8_stdio()
    try:
        return _main(argv)
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError) as exc:
        return emit_entry_error(exc)


def _main(argv: Sequence[str] | None = None) -> int:
    from .errors import ErrorCategory, GravityInsightError, exit_code_for_category
    from .cli_stdio import emit_entry_error

    try:
        args = _extract_workspace(list(sys.argv[1:] if argv is None else argv))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exit_code_for_category(ErrorCategory.CALLER)

    if args and args[0] == "cache":
        from .cache_cli import main as cache_main

        return cache_main(args[1:])

    upgrade_exit = _startup_upgrade_exit(args)
    if upgrade_exit is not None:
        return upgrade_exit
    _startup_skill_maintenance(args)

    if not args:
        if not ensure_first_run_credentials(requires_credentials=True):
            return exit_code_for_category(ErrorCategory.LOCAL)
        print(_HELP, end="")
        return 0
    if args == ["--help"] or args == ["-h"]:
        print(_HELP, end="")
        return 0
    return _run_namespace(args)


def _run_namespace(args: list[str]) -> int:
    from . import cli as insight_cli
    from .census import cli as census_cli
    from .sql import __main__ as sql_cli
    from .errors import ErrorCategory, GravityInsightError, exit_code_for_category
    from .cli_stdio import emit_entry_error

    namespace, *remaining = args
    if namespace == "account-pool":
        from .account_pool_cli import main as account_pool_main
        return account_pool_main(remaining)
    from .account_pool import AccountPoolConfig, _account_config_error
    if AccountPoolConfig.from_environment().enabled:
        raise _account_config_error("ACCOUNT_POOL_EXPLICIT_COMMAND_REQUIRED", field="command", next_action="Use `gravity account-pool --help` for explicit complete-read failover.")
    if namespace == "insight":
        command, command_args = insight_cli.main, remaining
        requires_credentials = command_requires_credentials(
            remaining, insight_cli.build_parser
        )
    elif namespace == "sql":
        command, command_args = sql_cli.main, remaining
        requires_credentials = command_requires_credentials(
            remaining, sql_cli.build_parser
        )
    elif namespace == "census":
        command, command_args = census_cli.main, remaining
        requires_credentials = False
    else:
        # The pre-split Insight CLI remains source-compatible.
        command, command_args = insight_cli.main, args
        requires_credentials = command_requires_credentials(args, insight_cli.build_parser)

    if any(value in {"-h", "--help", "--dry-run"} for value in command_args):
        requires_credentials = False

    try:
        if not ensure_first_run_credentials(
            requires_credentials=requires_credentials
        ):
            return exit_code_for_category(ErrorCategory.LOCAL)
    except GravityInsightError as exc:
        return emit_entry_error(exc)
    return command(command_args)


def _extract_workspace(args: list[str]) -> list[str]:
    """Apply the one process-wide workspace selector before SDK imports."""

    selected: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--workspace":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise ValueError("--workspace requires a gravity.toml file or directory")
            candidate = args[index + 1]
            index += 2
        elif value.startswith("--workspace="):
            candidate = value.partition("=")[2]
            if not candidate:
                raise ValueError("--workspace requires a gravity.toml file or directory")
            index += 1
        else:
            remaining.append(value)
            index += 1
            continue
        if selected is not None:
            raise ValueError("--workspace may be supplied only once")
        selected = candidate
    if selected is not None:
        os.environ["GRAVITY_WORKSPACE"] = selected
    return remaining


if __name__ == "__main__":
    raise SystemExit(main())

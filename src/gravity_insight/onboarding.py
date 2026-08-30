"""Interactive first-run setup for the unified Gravity CLI."""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from .credentials import (
    CredentialConfig,
    CredentialProvider,
    clear_account_credentials,
    migrate_legacy_session,
    save_account_credentials,
)
from .errors import InputValidationError


def should_onboard(*, requires_credentials: bool) -> bool:
    """Use the selected command's declared client requirement."""

    return bool(requires_credentials)


def command_requires_credentials(
    argv: Sequence[str], parser_factory: Callable[[], Any]
) -> bool:
    """Read the selected command's parser-owned network requirement."""

    if any(value in {"-h", "--help"} for value in argv):
        return False
    try:
        args = parser_factory().parse_args(argv)
    except (Exception, SystemExit):
        return False
    if _offline_flag_selected(args):
        return False
    if bool(getattr(args, "spec_schema", False)) or bool(
        getattr(args, "multidim_input_schema", False)
    ):
        return False
    if getattr(args, "analysis_command", None) == "segment":
        return _segment_requires_credentials(args)
    if getattr(args, "analysis_command", None) == "saved":
        return _saved_requires_credentials(args)
    if getattr(args, "analysis_command", None) == "order":
        return _order_requires_credentials(args)
    if getattr(args, "analysis_command", None) == "monetization":
        return _monetization_requires_credentials(args)
    if getattr(args, "command", None) == "multidim" and getattr(
        args, "multidim_command", None
    ) == "query":
        return _multidim_requires_credentials(args)
    product_requirement = _product_requires_credentials(args)
    if product_requirement is not None:
        return product_requirement
    if bool(getattr(args, "live", False)):
        return True
    return bool(getattr(args, "network_required", True))


def _offline_flag_selected(args: Any) -> bool:
    return any(
        bool(getattr(args, name, False))
        for name in (
            "dry_run", "query_spec_dry_run", "segment_spec_dry_run",
            "segment_mutation_dry_run", "analysis_query_batch_dry_run", "multidim_dry_run",
            "metadata_sync_dry_run", "user_detail_aggregate_dry_run",
            "user_detail_aggregate_input_schema",
        )
    )


def _product_requires_credentials(args: Any) -> bool | None:
    command = getattr(args, "command", None)
    action = getattr(args, f"{command}_command", None)
    checker = {
        ("materials", "performance"): _material_requires_credentials,
        ("promotion", "performance"): _promotion_requires_credentials,
    }.get((command, action))
    return checker(args) if checker is not None else None


def _segment_requires_credentials(args: Any) -> bool:
    """Require login only for a complete, unambiguous Segment command."""

    action = getattr(args, "segment_action", None)
    legacy = any(
        (
            getattr(args, "kind", None) is not None,
            getattr(args, "input", None) is not None,
            bool(getattr(args, "input_sets", None)),
            bool(getattr(args, "all_pages", False)),
        )
    )
    if action == "snapshot":
        return not legacy
    if action == "evaluate":
        return getattr(args, "spec", None) is not None
    if action in {
        "create-from-analysis", "create-from-rule", "create-from-history",
        "create-from-tmp", "update", "update-rule", "refresh", "delete",
    }:
        return bool(getattr(args, "segment_mutation_execute", False))
    return getattr(args, "kind", None) is not None and (
        getattr(args, "input", None) is not None
        or bool(getattr(args, "input_sets", None))
    )


def _saved_requires_credentials(args: Any) -> bool:
    """Avoid credential prompts for an incomplete local Saved request."""

    from .saved_analysis_support import bounds, workers

    try:
        bounds(getattr(args, "max_pages", None), getattr(args, "max_items", None))
        workers(getattr(args, "concurrency", None))
    except InputValidationError:
        return False
    if not _saved_app_valid(getattr(args, "app", None)):
        return False
    command = getattr(args, "saved_command", None)
    if command == "list":
        return True
    if command == "get":
        return _saved_reference_valid(getattr(args, "ref", None)) and _saved_window_valid(
            args, required=False
        )
    reference = getattr(args, "ref", None)
    definition = getattr(args, "definition", None)
    if (reference is None) == (definition is None):
        return False
    if definition is not None:
        return command == "run" and _saved_definition_valid(definition, args)
    return _saved_reference_valid(reference) and _saved_window_valid(
        args, required=False
    )


def _saved_reference_valid(value: Any) -> bool:
    from .saved_analysis_support import normalize_reference

    try:
        normalize_reference(value)
    except InputValidationError:
        return False
    return True


def _multidim_requires_credentials(args: Any) -> bool:
    """Reject incomplete product requests before offering a credential prompt."""

    if getattr(args, "app", None) is None:
        return False
    if bool(getattr(args, "all_pages", False)) and not (
        getattr(args, "output", None)
        or getattr(args, "format", "json") == "ndjson"
    ):
        return False
    source = getattr(args, "input", None)
    if source == "-":
        return True
    try:
        from .find_input import object_input
        from .multidim_cli import _product_bounds, _product_shortcuts
        from .multidim_product import (
            bind_multidim_app,
            normalize_multidim_inputs,
            prepare_multidim_query,
        )
        from .workspace import load_workspace
        from .workspace_app import resolve_workspace_app

        supplied = _product_shortcuts(args, object_input(source))
        normalized = normalize_multidim_inputs(supplied)
        _product_bounds(args, bool(getattr(args, "all_pages", False)))
        workspace = load_workspace(getattr(args, "workspace", None))
        app_id = resolve_workspace_app(workspace, getattr(args, "app", None))
        bound = bind_multidim_app(normalized, app_id)
        preview = prepare_multidim_query(None, bound, app_id=app_id)
        return preview.get("ok") is True and preview.get("network_called") is False
    except (InputValidationError, OSError, TypeError, ValueError):
        return False


def _material_requires_credentials(args: Any) -> bool:
    """Offer login only after the complete Material request is locally valid."""

    try:
        from .material_cli import _split_values
        from .material_performance import (
            DEFAULT_PLATFORMS,
            validate_material_performance_request,
        )
        from .workspace import load_workspace
        from .workspace_app import resolve_workspace_app

        output = getattr(args, "output", None)
        if output is not None and (
            not isinstance(output, str) or not output.strip() or output == "-"
        ):
            return False
        workspace = load_workspace()
        apps = [
            resolve_workspace_app(workspace, value)
            for value in _split_values(getattr(args, "app", []), field="app")
        ]
        validate_material_performance_request(
            apps,
            getattr(args, "start", None),
            getattr(args, "end", None),
            platforms=tuple(getattr(args, "platform", None) or DEFAULT_PLATFORMS),
            max_workers=getattr(args, "concurrency", None),
            max_pages=getattr(args, "max_pages", None),
            max_items=getattr(args, "max_items", None),
        )
    except (InputValidationError, OSError, TypeError, ValueError):
        return False
    return True


def _promotion_requires_credentials(args: Any) -> bool:
    """Offer login only after Promotion Performance is locally executable."""

    try:
        from .promotion_cli import prepare_promotion_performance_request

        prepare_promotion_performance_request(args)
    except (InputValidationError, OSError, TypeError, ValueError):
        return False
    return True


def _order_requires_credentials(args: Any) -> bool:
    """Offer login only after the selected Order request is locally valid."""

    action = getattr(args, "order_command", None)
    if action not in {"directory", "trace"}:
        return False
    try:
        if action == "directory":
            from .order_directory_cli import prepare_order_directory_request

            prepare_order_directory_request(args)
        else:
            from .order_trace_cli import prepare_order_trace_request

            prepare_order_trace_request(args)
    except (InputValidationError, OSError, TypeError, ValueError):
        return False
    return True


def _monetization_requires_credentials(args: Any) -> bool:
    """Offer login only after the complete-detail request is locally valid."""

    if getattr(args, "monetization_command", None) != "detail":
        return False
    try:
        from .monetization_detail_cli import prepare_monetization_detail_request

        prepare_monetization_detail_request(args)
    except (InputValidationError, OSError, TypeError, ValueError):
        return False
    return True


def _saved_app_valid(value: Any) -> bool:
    from .workspace import load_workspace
    from .workspace_app import resolve_workspace_app

    try:
        workspace = load_workspace()
        if not workspace.apps and workspace.defaults.app is None:
            return (
                isinstance(value, str)
                and value.isascii()
                and value.isdecimal()
                and int(value) > 0
            )
        resolve_workspace_app(workspace, value)
    except (InputValidationError, OSError, ValueError):
        return False
    return True


def _saved_definition_valid(value: Any, args: Any) -> bool:
    from .find_input import load_json_input
    from .saved_analysis_artifact import preflight_saved_definition
    from .saved_analysis_support import normalize_definition
    from .workspace import load_workspace
    from .workspace_app import resolve_workspace_app
    from .errors import UnsupportedOperationError

    if value == "-":
        return True
    try:
        workspace = load_workspace()
        app_id = str(resolve_workspace_app(workspace, getattr(args, "app", None)))
        definition, _metadata = normalize_definition(
            load_json_input(value), expected_app_id=app_id
        )
        preflight_saved_definition(
            definition,
            app=app_id,
            workspace=workspace,
            start=getattr(args, "start", None),
            end=getattr(args, "end", None),
        )
        return True
    except (InputValidationError, UnsupportedOperationError, OSError, ValueError):
        return False


def _saved_window_valid(args: Any, *, required: bool) -> bool:
    from .saved_analysis_artifact import validate_saved_window

    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if required and (start is None or end is None):
        return False
    try:
        validate_saved_window(start, end)
    except InputValidationError:
        return False
    return True


def ensure_first_run_credentials(
    *,
    requires_credentials: bool = True,
    env_path: Path | None = None,
    stdin: TextIO | None = None,
    stderr: TextIO | None = None,
    read_username: Callable[[], str] | None = None,
    read_password: Callable[[], str] | None = None,
    provider_factory: Callable[[Path], CredentialProvider] | None = None,
) -> bool:
    """Prompt once on an interactive terminal and validate the saved account."""

    if not should_onboard(requires_credentials=requires_credentials):
        return True
    from .runtime_scope import resolve_env_path

    selected_path, _isolated = resolve_env_path(env_path)
    migrate_legacy_session(selected_path)
    config = CredentialConfig.from_env(selected_path, environ={})
    if config.username and config.password:
        return True
    if config.token:
        return True

    input_stream = stdin or sys.stdin
    output_stream = stderr or sys.stderr
    if not input_stream.isatty():
        raise InputValidationError(
            "actual value: non-interactive stdin; Gravity username/password are not configured",
            field="auth",
            next_action=(
                "Run `gravity` in an interactive terminal to save username and "
                "password, or place them in the ignored `.env.gravity.local` "
                "and run `gravity insight auth refresh`."
            ),
        )

    output_stream.write("Gravity 首次使用设置\n")
    output_stream.write("请输入 Gravity 用户名：")
    output_stream.flush()
    username = (read_username or input_stream.readline)().strip()
    if not username:
        output_stream.write("未保存：用户名不能为空。\n")
        return False

    if read_password is None:
        password = getpass.getpass("请输入 Gravity 密码：", stream=output_stream)
    else:
        output_stream.write("请输入 Gravity 密码：")
        output_stream.flush()
        password = read_password()
    if not password:
        output_stream.write("未保存：密码不能为空。\n")
        return False

    save_account_credentials(username, password, selected_path)
    provider = (
        provider_factory(selected_path)
        if provider_factory is not None
        else CredentialProvider(selected_path, environ={})
    )
    try:
        provider.refresh()
    except Exception:
        clear_account_credentials(selected_path)
        output_stream.write(
            "登录验证失败，账号信息未保存；请检查网络、用户名和密码后重试。\n"
        )
        return False
    output_stream.write("Gravity 初始化完成，可以开始查询。\n")
    return True

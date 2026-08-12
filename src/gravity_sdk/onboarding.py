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
from .paths import PROJECT_ROOT


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
    if bool(getattr(args, "dry_run", False)) or bool(
        getattr(args, "query_spec_dry_run", False)
    ) or bool(
        getattr(args, "segment_spec_dry_run", False)
    ):
        return False
    if bool(getattr(args, "spec_schema", False)):
        return False
    if bool(getattr(args, "live", False)):
        return True
    return bool(getattr(args, "network_required", True))


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
    selected_path = Path(env_path or (PROJECT_ROOT / ".env.gravity.local"))
    migrate_legacy_session(selected_path)
    config = CredentialConfig.from_env(selected_path, environ={})
    if config.username and config.password:
        return True

    input_stream = stdin or sys.stdin
    output_stream = stderr or sys.stderr
    if not input_stream.isatty():
        return True

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

# Agent 安装契约

下面的 JSON 是自足的安装与离线自检合同。**默认装最新已发布版本，不要 pin。**
只有调用方明确要求某个版本时，才走 `pin_when_asked`。

不要 `pip install gravity-sdk` 或 `pip install gravity`：前者是 Gravity Labs 的广告 SDK，后者是 galaxyproject 的 Galaxy 服务器管理 CLI，都是无关第三方包。安装只走 PyPI 上已发布的 `gravity-insight`，不从非 PyPI 来源安装，也不在源码检出目录内验证非 editable 安装。

**为什么默认不 pin**：pin 需要有人提供版本号。没人提供时，Agent 会沿用文档示例或上次记住的版本，于是长期停在早已过期的版本上，而运行时的启动检查在 pin 生效时是关闭的，不会提醒。默认取最新可以让这条路径自愈；需要可复现时再显式 pin，那是有意识的决定，不是默认副作用。

```json
{
  "schema_version": "gravity-insight.agent-install.v3",
  "distribution": "gravity-insight",
  "python_requires": ">=3.11",
  "channel": {
    "kind": "pypi_latest",
    "index": "https://pypi.org/simple"
  },
  "install": {
    "command": "python -m pip install --upgrade gravity-insight",
    "working_directory": "outside_any_gravity_insight_source_checkout",
    "requires_executable": ["python"]
  },
  "pin_when_asked": {
    "use_when": "caller_named_an_exact_version",
    "default": "absent",
    "channel_kind": "pypi_exact_version",
    "install_command": "python -m pip install --upgrade \"gravity-insight==<version>\"",
    "environment": "GRAVITY_INSIGHT_PINNED_VERSION",
    "value": "<version>",
    "effect": "Startup auto-upgrade is disabled while the exact installed version is pinned.",
    "note": "Do not set this because an install happened to succeed at some version. Set it only to satisfy a stated reproducibility requirement, and record who asked."
  },
  "record_installed_version": {
    "command": "python -c \"import importlib.metadata as m; print(m.version('gravity-insight'))\"",
    "why": "The resolved version is an observation to report, not a value to pin on the next install."
  },
  "verify": [
    {
      "command": "gravity --help",
      "expected_exit": 0
    },
    {
      "command": "gravity doctor",
      "expected_exit": 0,
      "expected_status": "pass",
      "expected_reason_code": "INSTALL_CONSISTENT",
      "network_called": false,
      "working_directory": "outside_any_gravity_insight_source_checkout"
    }
  ],
  "failure": {
    "inspect": ["pip_stderr", "gravity_doctor.reason_code", "gravity_doctor.reinstall_commands"],
    "stop_on_nonzero_exit": true,
    "source_checkout_note": "INSTALL_METADATA_NOT_EDITABLE inside a source checkout is an intentional A-versus-B guard; leave the checkout to verify a PyPI install, or install that checkout editable for development.",
    "credentials_note": "Installation and gravity doctor are offline and must not be given Gravity credentials."
  }
}
```

## 消费方项目的依赖声明

上面管的是 Agent 怎么装 SDK。项目自己的 `requirements.txt` / `pyproject.toml` 是另一回事：
那里的精确 pin 服务于可复现构建，**本契约不要求也不建议把它改成范围**。
两者的区别是"谁在什么时候做决定"——项目 pin 是一次有记录的选择，
Agent 临时安装时的 pin 往往只是把某次偶然的版本固化下来。

升级项目 pin 时，用上面 `record_installed_version` 读到的实际版本，
而不是照抄任何文档里的示例版本号。

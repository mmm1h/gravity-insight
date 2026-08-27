# Agent 安装契约

下面的 JSON 是自足的安装与离线自检合同。Agent 应替换 `tag`/`version` 后逐条执行，不从分支安装，也不在源码检出目录内验证非 editable 安装。

不要 `pip install gravity-sdk` 或 `pip install gravity`：前者是 Gravity Labs 的广告 SDK，后者是 galaxyproject 的 Galaxy 服务器管理 CLI，都是无关第三方包。安装只走已发布的 `v<version>` tag；发布到 PyPI 后也可 `pip install gravity-insight`。

```json
{
  "schema_version": "gravity-sdk.agent-install.v1",
  "distribution": "gravity-insight",
  "python_requires": ">=3.11",
  "channel": {
    "kind": "immutable_git_tag",
    "repository": "https://github.com/mmm1h/gravity-sdk",
    "tag_format": "v<version>",
    "tag": "v<version>",
    "version": "<version>"
  },
  "install": {
    "command": "python -m pip install --upgrade \"git+https://github.com/mmm1h/gravity-sdk.git@v<version>\"",
    "working_directory": "outside_any_gravity_sdk_source_checkout",
    "requires_executable": ["python", "git"]
  },
  "version_pin": {
    "environment": "GRAVITY_SDK_PINNED_VERSION",
    "value": "<version>",
    "install_command": "python -m pip install --upgrade \"git+https://github.com/mmm1h/gravity-sdk.git@v<version>\"",
    "effect": "Startup auto-upgrade is disabled while the exact installed version is pinned."
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
      "working_directory": "outside_any_gravity_sdk_source_checkout"
    }
  ],
  "failure": {
    "inspect": ["pip_stderr", "gravity_doctor.reason_code", "gravity_doctor.reinstall_commands"],
    "stop_on_nonzero_exit": true,
    "source_checkout_note": "INSTALL_METADATA_NOT_EDITABLE inside a source checkout is an intentional A-versus-B guard; leave the checkout to verify a tag install, or install that checkout editable for development.",
    "credentials_note": "Installation and gravity doctor are offline and must not be given Gravity credentials."
  }
}
```

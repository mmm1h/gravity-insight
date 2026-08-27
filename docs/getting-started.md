# 快速上手

本页只完成安装、认证和离线自检。第一次让 Agent 完成真实分析，继续读[团队上手包](team-onboarding.md)。

## 1. 安装

不要 `pip install gravity-sdk` 或 `pip install gravity`：前者是 Gravity Labs 的广告 SDK，后者是 galaxyproject 的 Galaxy 服务器管理 CLI，都是无关第三方包。当前只安装不可变、已通过门禁的 `v<version>` tag；发布到 PyPI 后也可 `pip install gravity-insight`。把 `<version>` 替换为已发布版本：

```powershell
python -m pip install --upgrade "git+https://github.com/mmm1h/gravity-sdk.git@v<version>"
```

每次升级都显式换成更新的 `v<version>` tag，并保留 `--upgrade`，让 pip 比较安装元数据中的版本。完整的 Agent 安装/自检合同见 [Agent 安装契约](agent-skills/installation.md)。

只有要修改 SDK 源码时才 clone，并在该 worktree 自己的虚拟环境中安装 editable 包：

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -e ".[dev]"
```

源码检出但尚未安装时，仍可临时使用：

```powershell
$env:PYTHONPATH='src'
python -m gravity_sdk --help
```

在源码检出目录中运行从 tag 非 editable 安装的 `gravity doctor` 会以 `INSTALL_METADATA_NOT_EDITABLE` 失败；这是正确的保护，不是安装故障。它阻止“当前目录源码是 A、实际执行的安装包是 B”。切换到源码检出目录之外再检查 tag 安装；在源码目录内开发则使用上面的 editable 安装。

## 2. 认证

交互终端首次运行 `gravity` 会引导登录。凭据和 session 只保存在用户私有状态目录；不要提交 `.env.gravity.local`、token、cookie、用户名或密码。

检查状态：

```powershell
gravity insight auth status
```

非交互环境若没有有效本地凭据，应停止并让操作者在交互终端完成登录，不要把认证信息写进命令、日志或 Plan。

## 3. 离线自检

下面命令不访问 Gravity：

```powershell
gravity --help
gravity agent-catalog categories
gravity plan schema
gravity metadata status
```

目录浏览顺序固定为 `categories → category → describe`。它回答当前机器安装了什么，不需要查文档中的手写数量。

## 4. 第一次执行

已知产品或 operation 时直接执行对应 CLI / SDK；未知任务先从目录选择，再补齐 required inputs。不要执行 `capability_gap`、weak match 或不可执行 handoff。

最短工作流、错误终态和可信度检查见[团队上手包](team-onboarding.md)；完整协议见[Agent 工作流](agent-workflow.md)。

## 下一步

- Agent 分析：[任务指南](agent-skills/index.md)
- Python 集成：[SDK 参考](reference/sdk.md)
- Workspace 配置：[Workspace 参考](reference/workspace.md)
- 修改仓库：[维护者入口](maintainers/index.md)

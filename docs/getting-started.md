# 快速上手

本页只完成安装、认证和离线自检。第一次让 Agent 完成真实分析，继续读[团队上手包](team-onboarding.md)。

## 1. 安装

在仓库自己的虚拟环境中安装 editable 包：

```powershell
python -m venv .venv
& .venv\Scripts\Activate.ps1
python -m pip install -e .
```

源码检出但尚未安装时，可临时使用：

```powershell
$env:PYTHONPATH='src'
python -m gravity_sdk --help
```

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

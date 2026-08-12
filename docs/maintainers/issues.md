# Issue 状态管理

GitHub Issue 只接收其他项目在真实使用本 SDK 时提交的问题，是这些问题与交付状态的唯一
线上账本。状态用 GitHub 的 open/closed 加一枚 `status:*` 标签表达；不要另建 Project、
审批流或重复任务系统。

Codex 或维护者自行发现的优化、能力规划和开发拆包不得创建 GitHub Issue。它们记录在当前
开发计划、`dev` 提交和维护文档中；只有消费项目提交了可追溯的使用问题后，才进入下面的
Issue 状态流。Agent 可以整理、补证据和更新已有外部 Issue，但不得为了给自己的开发工作
派号而创建 Issue。

## 状态流

| 状态 | 含义 | Agent 动作 |
| --- | --- | --- |
| `status:triage` | 新问题，尚未判断证据与范围 | 只读复现，明确影响、根因候选和验收条件 |
| `status:needs-evidence` | 缺少安全、可复现的结构证据 | 保持 open，评论中只列精确缺口，不猜合同 |
| `status:ready` | 证据、范围和验收条件足够 | 可被 Agent 领取 |
| `status:in-progress` | 已在独立 `dev` worktree 开发 | 评论记录 worktree、所有权和预期改动面 |
| `status:blocked` | 已开工，但存在明确外部阻断 | 保持 open，记录解除阻断所需的唯一条件 |
| `status:fixed-dev` | 修复已提交并推送 `dev`，尚未发布 | 记录提交与验证；保持 open |
| `status:released` | 修复已进入 `main`、消费者可用 | 记录 main 提交或版本，关闭 completed |

主路径是：

```text
triage -> ready -> in-progress -> fixed-dev -> released
```

`needs-evidence` 和 `blocked` 是可返回主路径的旁路。任一时刻只能存在一枚
`status:*` 标签；状态变化时先移除旧状态。

## 优先级

每个可执行 Issue 必须且只能有一枚 `priority:*`：

- `priority:p0`：稳定 `main` 不可用、凭据或隐私泄漏、数据破坏。
- `priority:p1`：常用路径产生错误结果、错误阻断或显著放大线上请求。
- `priority:p2`：能力、性能或 Agent 体验明显退化，但存在合理绕行。
- `priority:p3`：低风险完善和待排期优化。

优先级表达影响，不表达修复难度。Issue 继续使用现有 `bug`、`enhancement`、
`documentation` 表达类型；按需增加一枚 `area:*` 定位子系统。

## Agent 最短路径

先确认 Issue 来自消费项目的真实使用反馈，再领取已准备好的任务：

```powershell
gh issue list --repo mmm1h/gravity-sdk --state open `
  --label status:ready --json number,title,labels,url
```

领取前先确认没有其他 Agent 占用，然后将状态改为 `in-progress`。实现只能在
独立 `dev` worktree；消费者目录继续停留在 `main`。

状态评论只保留机器执行需要的信息：

- `ready`：最小复现、证据边界、预期合同、验收条件。
- `in-progress`：开发分支/worktree、文件所有权、是否需要 live probe。
- `fixed-dev`：dev commit、聚焦验证、完整验证、尚未发布的边界。
- `needs-evidence`：缺失的字段路径、类型树、请求绑定或非空样本。
- `released`：main commit/版本和兼容性说明。

不得写入 token、cookie、用户名、密码、App ID、设备/用户标识或原始用户级
输出。线上响应只提交脱敏字段路径、类型和有界聚合示例。

## 关闭规则

- `fixed-dev` 不关闭：其他项目仍在消费 `main`，此时尚未真正交付。
- 合入 `main` 后改为 `status:released` 并以 completed 关闭。
- 重复、无效或明确不做的问题可直接使用 GitHub 的 duplicate/not planned
  关闭原因，并在评论中给出替代 Issue 或边界。
- 缺证据、等待租户非空样本和等待外部接口恢复都保持 open。

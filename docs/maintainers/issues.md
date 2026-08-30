# Issue 状态管理

GitHub Issue 只接收其他项目在真实使用本 SDK 时提交的问题。状态由 open/closed 加一枚
`status:*` 标签表达；不要另建 Project、审批流或重复任务系统。

维护者自行发现的优化、能力规划和开发拆包不创建 Issue，分别写入 roadmap、候选矩阵或技术债。
Agent 可以整理、补证据和更新已有外部 Issue，但不得为了给自己的工作派号而创建 Issue。

## 状态流

| 状态 | 含义 | Agent 动作 |
| --- | --- | --- |
| `status:triage` | 新问题，尚未判断证据与范围 | 只读复现，明确影响和验收条件 |
| `status:needs-evidence` | 缺少安全、可复现的结构证据 | 保持 open，只列精确证据缺口 |
| `status:ready` | 证据、范围和验收条件足够 | 可领取并建立短命分支/worktree |
| `status:in-progress` | 已在 `codex/<unit>` 开发 | 记录分支、worktree、所有权和范围 |
| `status:blocked` | 已开工但存在明确外部阻断 | 保持 open，记录唯一解除条件 |
| `status:released` | 修复已进入 `main`、消费者可用 | 记录 main commit/版本并关闭 completed |

主路径是：

```text
triage -> ready -> in-progress -> released
```

`needs-evidence` 和 `blocked` 是可返回主路径的旁路。任一时刻只能有一枚 `status:*`；状态变化时移除
旧状态。开发分支上的提交不是发布状态，Issue 在修复进入 `main` 前保持 open。

## 优先级

每个可执行 Issue 必须且只能有一枚 `priority:*`：

- `priority:p0`：稳定 `main` 不可用、凭据或隐私泄漏、数据破坏。
- `priority:p1`：常用路径产生错误结果、错误阻断或显著放大线上请求。
- `priority:p2`：能力、性能或 Agent 体验明显退化，但存在合理绕行。
- `priority:p3`：低风险完善和待排期优化。

优先级表达影响，不表达修复难度。继续使用 `bug`、`enhancement`、`documentation` 表达类型；按需
增加一枚 `area:*` 定位子系统。

## Agent 最短路径

只领取 `status:ready`：

```powershell
gh issue list --repo mmm1h/gravity-sdk --state open `
  --label status:ready --json number,title,labels,url
```

领取前确认无人占用，改为 `status:in-progress`，从当前 `main` 建独立 `codex/<unit>` 分支/worktree。
评论只保留机器执行需要的信息：

- `ready`：最小复现、证据边界、预期合同、验收条件。
- `in-progress`：分支/worktree、文件所有权、预期范围、是否需要 live probe。
- `needs-evidence`：缺失字段路径、类型树、请求绑定或非空样本。
- `released`：main commit/版本、验证和破坏性变更说明。

不得写入 token、cookie、用户名、密码、App ID、设备/用户标识或原始用户级输出。线上响应只提交
脱敏字段路径、类型和有界聚合证据。

## 关闭规则

- 修复只在进入 `main` 后改为 `status:released` 并以 completed 关闭。
- 重复、无效或明确不做的问题可用 duplicate/not planned，并给出替代 Issue 或边界。
- 缺证据、等待租户非空样本和等待外部接口恢复都保持 open。

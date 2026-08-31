# 负责人已决事项

[负责人操作清单](owner-actions.md) 记录**待决**事项；本页记录**已决**事项、当时的理由，以及**什么条件下应当重新评估**。

一条决策写进这里，就是让后续的人不必重新推导它。如果理由已经不成立，改这里而不是绕过它。

## 授权

2026-09-01，Owner (`mmm1h`) 授权代为决策：

> 后面的决策你代入我的视角帮我决策……所有任务持续开发，不要被决策卡住。

同批批复：Gravity 生产权限全开。

## 决策原则

以下决策按同一套原则做出，它们是从 Owner 已有取向归纳的，不是通用最佳实践：

1. **能不加的不加。** 新增任何需要长期维护的东西，必须有**当下就存在**的需求，不是"将来可能有用"。
2. **偏好显式。** 自动化只在它消除的负担明显大于它带来的不可见性时才引入。
3. **不为填表造空壳。** 一项治理措施如果没有消费方，不建立它比建立一个没人用的更好（§3.1 减法优先）。
4. **如实记录当前能力边界。** 没有的能力就写没有，不用"计划中"掩盖。

约束背景：单人维护、私有仓、消费方是 Agent 与自有的 work-dashboard。

## R16 供应链决策

### 1. 历史 R16 —— 接受

R16 在 `9d17cfcf` 达到 `fixed_dev; owner_review: pending`，其 Requirement 文件随 `826878e3` 的架构收敛退役。当前组件索引仍将 `external-control-plane` 标为 `bounded`，且禁止 Runtime 自激活。

没有证据表明它有问题，重新审一遍是纯成本。

**重新评估的条件：** 出现 `external-control-plane` 相关的实际故障，或有人要解除 `bounded` 约束。

### 2. PEP 740 之外的签名 —— 不做

Trusted Publishing 加 PEP 740 attestation 已经提供来源证明，且是 PyPI 原生支持、零密钥管理。

额外签名要引入密钥的生成、存储、轮换、吊销，对单人项目是净负担，而当前**没有任何消费方要求它**。

**重新评估的条件：** 出现第二个发布者，或有消费方明确要求验证签名。

### 3. 组织 trust root、阈值、轮换、吊销/过期策略 —— 不建立

与第 2 项绑定：没有签名就没有 trust root 需要管理。建立一套无人使用的策略正是原则 3 要避免的。

**重新评估的条件：** 同第 2 项。

### 4. 外部 installer / canary / rollback 的 Owner —— `mmm1h`，并如实记录能力边界

单人维护，没有第二个候选。有价值的不是"谁负责"，而是**当前实际具备什么**：

| 环节 | 当前状态 |
| --- | --- |
| installer | 外部（`pip` 或用户自行安装）。Runtime **不自我替换 wheel**，`InstallerContract` 固定 `owner=external-installer`、`runtime_mutation=forbidden`，已有测试验证无 subprocess / pip / `execv` / 环境与解释器改动 |
| canary | **不存在。** 没有 canary 环境，也没有金丝雀发布流程 |
| rollback | 依赖 PyPI 的 yank 与 GitHub Release 删除，**没有自动化** |

**重新评估的条件：** 出现第二个维护者，或有部署场景需要真实的灰度与回滚。

### 5. Stage B 触发条件 —— 保持未激活

Stage B 是"外部 Installer 执行更新"的阶段（见 `src/gravity_insight/control_plane/lifecycle.py`）。当前 Runtime 只生成 Plan，不执行。

当前的两个消费场景都不需要它：本机开发直接用 editable 安装；work-dashboard 已有显式的开发/发布双模式切换，且升级工具默认只 preview、`--apply` 才改钉版与 digest lock。**这个显式设计是被认可的，不应被自动更新取代。**

**重新评估的条件：** 出现一个无人值守的部署场景，其更新频率高到显式操作成为瓶颈。

## Gravity 生产权限

2026-09-01 Owner 批复"权限全开"。

生产认证中有 **13 项**探测因 `PERMISSION_UNAVAILABLE` 无法判定（目标 receipt 为 0），账号角色为 `dept_admin`：

| 类别 | 探测项 |
| --- | --- |
| 看板 | `dashboard condition favourite`（2 项）、`dashboard detail`、`dashboard members`、`dashboard space_members` |
| 人群 | `segment detail`、`segment history_version`、`segment uid_result`、`segment user_detail` |
| 用户明细 | `user_detail`、`user_event`、`user_postback_log` |
| 订单 | `order_split_detail` |

均为用户级明细数据。**后续生产认证应重试这 13 项**；若仍为 `PERMISSION_UNAVAILABLE`，说明权限尚未实际生效，如实报告而不是改判为其他状态。

## work-dashboard（独立仓库）

以下两项属于 `mmm1h/work-dashboard`，在此一并记录以免分散：

### `EXP-202607-001` —— 保持 `draft`，材料全部保留

它已是 `draft` 状态，不受新增的实验准入契约约束（该契约只约束非 `draft` 状态）。其设计、阻塞清单、指标决策卡与 A/E/O 就绪矩阵是独有材料，删除即不可恢复。保持现状的成本为零。

**重新评估的条件：** 有人实际推进该实验，届时按准入契约补齐 owner、起止时间、A/E/O 与主指标。

### `GitHub分支保护检查.md` —— 文档准确，保留

该文档记录 `main` 为 `protected=false`，且 branch protection 与 ruleset API 均返回 HTTP 403。

2026-09-01 实测复现：`gh api repos/mmm1h/work-dashboard/branches/main/protection` 仍返回

```text
403 Upgrade to GitHub Pro or make this repository public to enable this feature.
```

结论与文档一致，**不需要 Owner 裁决**。文档中"不应通过改为 Public 获取保护能力"的判断依然成立（仓库历史含待处置敏感 blob）。

作为对照，`mmm1h/gravity-insight` 是公开仓，其 `main` 的实际保护为：`strict=true`、必需检查 `['test']`、无需 review、`enforce_admins=true`、禁止 force push 与删除。

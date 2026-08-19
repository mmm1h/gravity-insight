> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 消费方摩擦：recipe 重钉出口 + 发现失败指向目录浏览

- 日期：2026-08-18
- 任务：消费方摩擦（recipe 指纹重钉 + 发现失败出口）
- 结论：`gravity recipe accept-contract` 在展示合同 diff 后才重钉调用方 `gravity.toml`；`no_candidate` 现在带可执行的 `agent-catalog categories` 下一步。fail-closed 未放松。

## 事实

- 工作树：`D:/git-pjt/wt-consumer-affordances`，分支 `grok/consumer-affordances`，基线 `dev@f91b547`。
- 生产 HTTP：**0**。未读、未写 `docs/roadmap.md`。未碰 `work-dashboard`、GitHub、评测题集/holdout。
- 新增离线子命令 `gravity recipe accept-contract <name>`，输出 schema `gravity.recipe-repin.v1`。
- `check` 仍 fail-closed：指纹变化继续报 `contract_fingerprint_changed` / `stale`。重钉只改调用方 `gravity.toml` 的 `contract_fingerprint`，不改 SDK 合同。
- 发现失败：`find.capability_gaps` 的空候选现带 `code=NO_CANDIDATE`、`next.argv=["gravity","agent-catalog","categories"]`。Agent 顶层 envelope 与 host 空选择同样给出该 argv。
- 产品边界 gap（订单目录/拆单/变现/广告主等）补了 `next_action`，明确写「这是已确认边界，不要去找替代 raw operation」。
- `plan_multidim_result._safe_page` 的策略白名单从死名 `single`/`serial`/`parallel` 改为运行时真实值。这是投影修复，不是放宽安全判定。
- 错误审计：`1231 = A856 / B375 / C0` → `1236 = A861 / B375 / C0`。新增 5 条 raise 全是 A（path + actual + remedy），C 仍为 0。
- 质量 baseline 的 `hard_limit` / `threshold` / `max_` **未改**。`agent.py` 一度 501 SLOC，把 next 字段下沉到 `agent_discovery_support.py` 后回到 493。
- 动线台账：未改 `docs/analysis-journeys.md` 任何一行。表头 `56 = 50 / 3 / 3` 不变；「看起始行为后的用户留存」仍为已闭环。冻结评测 case 不因本轮文档状态列变化而对不上（状态列未动）。

## 用法（消费方可照抄）

先看 diff，不写文件：

```powershell
gravity recipe accept-contract <name> --dry-run
```

纯增量（只新增字段，或仅指纹变化）直接重钉：

```powershell
gravity recipe accept-contract <name>
```

破坏性（删除字段或类型变更）默认 `status=blocked`。确认可接受损失后再写：

```powershell
gravity recipe accept-contract <name> --allow-breaking --reason "<audit-text>"
```

`--reason` 进入 envelope，供调用方审计。不要用 `--allow-breaking` 处理纯增量。

## 两种合同变更的行为

| 分类 | 判定 | 默认 | 写出 |
| --- | --- | --- | --- |
| `unchanged` | 指纹与当前合同一致 | `status=unchanged`，不写 | 不写 |
| `additive` / `fingerprint_only` | 无删除、无类型变更 | `--dry-run` 为 `preview`；否则 `accepted` | 只改该 recipe 的 `contract_fingerprint` |
| `breaking` | `contract_diff.removed` 或 `type_changed` 非空 | `status=blocked`，给 `next.argv` | 仅当同时给 `--allow-breaking --reason` |

`check` 的 `stale` / `contract_fingerprint_changed` 路径未改。Resolver stale 的 `next_action` 现在指向 `check` 再 `accept-contract`。

## `no_candidate` 前后对比

改前（Agent 空候选）：

- 顶层 `next_action`：`Report capability_gaps; do not execute weak partial matches.`
- gap 本体无 `code`、无 `next.argv`。
- 调用方看不到 `gravity agent-catalog categories`。

改后：

- 顶层与 gap 均带 `next.argv = ["gravity", "agent-catalog", "categories"]`。
- gap `code = NO_CANDIDATE`。
- `next_action` 要求先浏览目录以**确认能力不存在**，并禁止执行 weak match 或发明 selector。
- 已登记的精确 gap（实时事件目录、媒体报表、非 Bytedance 层级等）仍走各自 `next_action`；不把真 gap 说成「再找找就有」。

## `plan_multidim_result._safe_page`

**事实：** `pagination.py` / `pagination_policy.py` 写出的策略是 `single_page`、`serial_known_total`、`parallel_known_total`、`serial_unknown_total`、`stopped_missing_total_page`。Plan 投影原先只认 `single`/`serial`/`parallel`，三个词运行时都不会出现，因此 `fetch_strategy` 被静默丢掉。产品信封 `composite_result._safe_page` 本来就不投影该字段。

**判断：** 修，不删。旧三词是死名残留，不是调用方可传的开关。对齐真实枚举后 Plan 才能看到已有分页策略；未登记策略仍丢弃。这不是放宽 fail-closed。

## 推测（与事实分开）

- 调用方 work-dashboard 的 `analysis.retention.query` 1→2 增量重钉，走 `accept-contract` 不加 `--allow-breaking` 即可。本轮未打开该仓库，未替它改 toml。
- 离线选路 81.25% 的 residual `no_candidate` 不会因此变对；本轮只补发现失败后的第二条路，不改识别器。

## 未做

- 未削弱合同变更检测、未登记字段投影、`contract_changed` 状态。
- 未改评测装置、题集、评分、阈值；未跑 holdout/final。
- 未 push、未碰 GitHub。

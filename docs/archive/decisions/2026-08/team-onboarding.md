> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 团队上手包

- 日期：2026-08-18
- 任务：#207
- 结论：在 `docs/team-onboarding.md` 落地分析师/agent 上手包（接入、能问什么、可信度规矩、坑与自救）；只加文档，不改 `src/`，不改动线台账，不改 `docs/roadmap.md`。

## 确凿事实

### 交付物

| 文件 | 作用 |
| --- | --- |
| `docs/team-onboarding.md` | 给分析师和 agent 的上手包 |
| `docs/index.md` | 任务表第一行改为指向上手包；文档层级补同一链接 |
| `docs/getting-started.md` | 「下一步」第一条指向上手包 |
| 本文件 | 本趟结论与证据 |

`docs/index.md` 用替换现有单元格，不新增行，避开 100 行入口预算。`getting-started.md` 同样替换一行，保持 160 行上限。

未改 `docs/analysis-journeys.md` 任何一行。表头 `56 = 50 / 3 / 3` 不动；状态列不动。冻结评测 case 不对齐问题不存在（台账未动）。

### 离线命令（本工作树，`PYTHONPATH=src`，2026-08-18）

写 0。生产读 0（见下）。下列全部 `offline=true` / `network_called=false`，exit 0。

| 请求 | 响应要点 | 因此写进上手包 |
| --- | --- | --- |
| `agent-catalog categories` | `gravity.agent-catalog.v1`，10 个 category | 冷启动第一条；领域名按实测列出 |
| `agent-catalog category analysis --limit 5` | 产品卡先于 raw：`analysis.query.spec` 及其 kind 变体 | 优先 `identity_kind=product` |
| `agent-catalog describe analysis.query.spec:event` | `required_inputs=['app','spec']`；`next.argv` = `plan run --input <plan.json>` | describe 不执行 |
| `agent-catalog host` | `gravity.host-product-catalog.v1`，102 entries，含 `catalog_sha256` 与 `response_schema` | 宿主臂先读 host |
| `agent`（无 query） | `mode=protocol`，`routing_mode=recognizer` | 机器协议入口 |
| `agent "看一下事件趋势"` | `routing_mode=recognizer`，`routing.floor=true`，3 张卡，`routing.upgrade.then_argv` 可照抄升级 | 默认是地板 |
| 用当天 host 指纹交 `gravity.host-product-selection.v1` | `mode=host_catalog_select_and_describe`，`routing_mode=host_catalog`，`floor=false`，无 `upgrade`，选出 `analysis.query.spec` | 宿主臂主路径可跑通 |
| `agent --input` 两问 | `gravity.agent-batch.v1`，2/2 success，每题仍是 recognizer | `--input` 是批量发现面 |
| 无意义问句 | `status=capability_gap`，`code=NO_CANDIDATE`，`next.argv=agent-catalog categories` | 无候选自救 |
| `insight auth status` | `token_valid=false`，`auth_state=missing`，`next_action` 指向交互 `gravity` | 认证只写机制；本机会话不可用 |

`agent-catalog` **不接受** `--output`（实测 `INPUT_INVALID` / `unrecognized arguments: --output`）。上手包因此不写该旗标。`agent` 本身接受 `--output`。

### 未发生产读的原因

`insight auth status`：`credential_present=true`（进程环境有 token 源），但 `token_valid=false`、`password_present=false`、`username_present=false`。非交互补登会写凭据，本趟写预算为 0。因此 **未发** `app.list` / bootstrap / 任何业务读。文档里的生产对账结论全部引用既有 `docs/roadmap.d/` 文件，不把过期会话上的失败写成能力事实。

### 文档声明与依据对照

| 上手包断言 | 依据 |
| --- | --- |
| 安装 / `.env.gravity.local` / 不要配 token | `docs/getting-started.md` |
| 冷启动读 skills 任务表 + 三层目录 + host | `docs/agent-skills/index.md`、`catalog-discovery.md`、本趟实测 |
| 宿主臂主路径、recognizer 地板、`routing.upgrade.then_argv` | 本趟两臂实测；`docs/roadmap.d/routing-provenance.md`；`src/gravity_sdk/agent_discovery_support.py` |
| 已闭环 / 4 条租户不可达 / 实时事件三次开窗空 | `docs/analysis-journeys.md` 窄读状态列；`docs/roadmap.d/gap-to-95.md` 及 realtime-event-* |
| 分页/可加/跨 route/留存/漏斗/分群/导出 | `prod-truth.md`、`reconcile-round2.md`、`truncated-confirm.md`、`advertised-vs-real.md` |
| `yesterday_count`、`last_3_day_*` | `misleading-traps.md`、`trust-sweep.md`、合同 `unreliable_item_keys` |
| 漏斗无率、UV 不可加、`dimension_sum_mismatch` | `reconcile-round2.md`、`prod-truth.md`、`advertised-vs-real.md` |
| 相对日期回显 | `relative-dates.md` |
| `app_id` 归一化、其它标识仍分裂 | `misleading-traps.md`、`docs/reference/sdk.md#app-id-wire-types` |
| `NO_CANDIDATE` / `UNRANKED_OPERATIONS` / 登记 gap | 本趟无候选实测；`consumer-affordances.md`；`recognizer-handoff.md`；`capability-gap.md` |

`UNRANKED_OPERATIONS` 本趟未构造触发问句；文案按源码常量 `UNRANKED_OPERATIONS_NEXT_ACTION` 与 `docs/reference/cli.md` 写，不伪称本机打出过该信封。

## 推测（不是事实）

- 分析师会把上手包整段喂给 agent，而不是自己先读完 CLI 参考。
- 本机过期会话刷新后，文档里的 `run` / `bootstrap` 命令形状与 `getting-started.md` 一致，应能登录后跑通；本趟没有证明。

## 未做

- 未改 `src/`、评测装置、题集、`docs/roadmap.md`、`docs/analysis-journeys.md`。
- 未 push、未碰 GitHub。
- 未跑 holdout / final，未读 `*.sealed.json`。
- 未碰实时事件、导出面。
- 未把凭据、账号或原始业务数据写入文档。

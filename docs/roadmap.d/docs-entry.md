# 消费方入口分流

- 日期：2026-08-19
- 任务：#213
- 结论：根目录把「用 SDK 取数」和「改这个仓库」分开；上手包补上今日已合并能力；入口数字按合同与离线 CLI 对齐。未改 `src/`，未改动线表头，未改 `docs/roadmap.md`。

## 确凿事实

### 交付物

| 文件 | 作用 |
| --- | --- |
| `AGENTS.md` | 顶部 5 行分流：取数 → `docs/team-onboarding.md`；改仓 → 续读本文 |
| `README.md` | 「你是 Agent？从这里开始」；目录计数改为 237 / 96 / 228 = 190+38 |
| `docs/index.md` | 浏览目录任务与 Agent 最短路径第一条指向上手包；行数仍 100 |
| `docs/team-onboarding.md` | 补今日能力：路由升级路径、上游自纠、漏斗无率、export evaluate/task-types、metadata cache、`gravity_material_id`、实时事件已闭环 |
| `docs/getting-started.md` | 第三个死字段写进不可信清单 |
| `docs/agent-workflow.md` | 目录数字对齐 237/96/6/336；最短入口表补实时事件；导出节补 evaluate / task-types |
| `docs/roadmap.d/README.md` | 只追加本文件一行 |
| 本文件 | 本趟结论与证据 |

未改 `docs/analysis-journeys.md` 任何一行。表头 `56 = 50 / 3 / 3` 不动。状态列不动。

### 离线命令（本工作树，`PYTHONPATH=src`，2026-08-19）

写 0。生产读 0。下列全部 exit 0。

| 请求 | 响应要点 | 因此写进文档 |
| --- | --- | --- |
| 合同 `operations/*.json` 计数 | 237 operation；stable 228 = read 190 + mutation 38 | README / index / agent-workflow 的目录数字 |
| `agent-catalog categories` | `gravity.agent-catalog.v1`，`offline=true`，10 个领域 | 分流最短命令仍是这条 |
| `agent-catalog host` | `gravity.host-product-catalog.v1`，102 entries = 96 product + 6 gap，有 `catalog_sha256` | 实时事件 gap 已不在 host；6 个精确 gap 与 index 一致 |
| `agent "看一下事件趋势"` | `routing_mode=recognizer`，`routing.floor=true`，3 张卡；`then_argv` 在 `routing.upgrade.next.then_argv` | 上手包原先写的 `routing.upgrade.then_argv` 按实测纠正 |
| `export --help` | 子命令含 `evaluate`、`task-types` | 上手包补这两条入口 |
| `export evaluate --help` | 位置参数 `operation_id`，要 `--input` | 形状按 help 写，未发生产 |
| `export task-types --help` | 无必填输入 | 同上 |
| `analysis realtime-events --help` | 必填 `--app/--start/--end`，可选 `--event-type` | 读入口按 help 写 |
| `docs/reference/cli.md` host 计数 | 改前写 93 卡 / 7 gap | 按本趟 host 102 = 96+6 改成现数 |

`host` 里 6 个 gap 现为：`ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`、`CURRENT_TABLE_SCHEMA_PARENT_MISSING`、`MEDIA_REPORT_ITEM_SCHEMA_MISSING`、`NON_BYTEDANCE_HIERARCHY_PARENT_MISSING`、`PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING`、`WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED`。**没有** `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。

### 入口自洽（改前 / 改后）

| 声明 | 改前 | 依据 | 处置 |
| --- | --- | --- | --- |
| operation / 产品卡 / stable | README `233/92/224=187+37`；agent-workflow `233/93/7` selector 330 | 合同 237/228=190+38；skills 已写 237/96/6；index 已写 336=237+96+6−3 | README、agent-workflow 对齐；index 本就对 |
| 消费方第一眼 | AGENTS.md 只讲改仓；README 不指向上手包当第一句 | 本趟打开根文件即见 | 两处加分流，不删开发约束 |
| 实时事件 | 上手包仍写「三次开窗仍空」+ Agent 返回合同缺失 | `#211` `realtime-event-profile-shape.md`；台账该行已是「已闭环」；host 已无该 gap | 上手包改为已闭环 + `analysis realtime-events` |
| 动线汇总 | 上手包写 50/3/3 | 台账开篇程序化重算已是 51/3/2 | 上手包跟重算句；**不改**台账表头 |
| 识别器升级 argv | 上手包写 `routing.upgrade.then_argv` | 本趟信封：`routing.upgrade.next.then_argv` | 按实测改路径 |
| `gravity_material_id` | 上手包未列 | `reconcile-round3.md`；合同 `unreliable_item_keys` | 上手包 + getting-started |
| export evaluate / task-types | 上手包未列 | `advertised-vs-real.md`；本趟 `--help` | 上手包 + agent-workflow 导出节 |
| metadata cache | 上手包未列 | `metadata-cost.md`；`docs/reference/sdk.md` | 上手包补成本事实与三个 API |
| 漏斗无率 / `field=` 自纠 / `routing_mode` | 上手包已有 | `upstream-selfcorrect.md`、`routing-provenance.md`、本趟信封 | 只纠正 `then_argv` 路径 |

`docs/index.md` / `getting-started.md` / `agent-workflow.md` 行数预算仍为 100 / 160 / 220。`README.md` 仍 100。

### 动线台账（本趟未改文件）

- 表头 `56 = 50 / 3 / 3`：**不要动**（本趟也没动）。
- 合并时建议变为 **`56 = 51 / 3 / 2`**：台账开篇程序化重算已经是「已闭环 51 / 部分闭环 3 / 完全缺失 2」；「查询实时事件目录」状态列已是已闭环（`#211`）。本趟没有改状态列。
- 冻结评测：`#211` 已写明 J35 五题仍期待 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。本趟只改文档，不对齐题集。这个对不上是 `#211` 留下的，不是本趟制造的。

## 推测（不是事实）

- 消费方 agent 会先读 `AGENTS.md` 而不是 `docs/index.md`；分流写在根文件顶部才能拦住通读贡献指南。
- `docs/roadmap.d/gap-to-95.md` 仍写实时事件「另有专门任务」、上限 52/56。那是 `#211` 之前的归档，本趟不改别人的结论文件。

## 未做

- 未改 `src/`、评测装置、题集、`docs/roadmap.md`、`docs/analysis-journeys.md`。
- 未 push、未碰 GitHub。
- 未跑 holdout / final，未读 `*.sealed.json`。
- 未发生产读，未把凭据或业务数字写入文档。

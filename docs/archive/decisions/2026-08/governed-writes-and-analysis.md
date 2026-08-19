> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 受治理写目录与分析 CRUD

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：自定义指标、受治理写目录、元数据模板 CRUD、评测网络字段派生、保存分析 CRUD 与六类导出重判。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 自定义指标口径 CRUD 与 confmetric 前缀裁决（2026-08-16）

**提案与边界：**书面提案位于 ignored `tmp/codex/custom-metrics/proposal.md`。本轮只实现平台
自定义指标定义的 list/create/update/delete，并证明该指标能被真实 Multidim 查询消费；不做 share、
指标权限、维度表、报表模板或其他业务域写入，不读取或运行 holdout/final/key，不执行 GitHub、push、
PR、tag 或 release 动作。生产总上限 40 HTTP，所有 runtime attempts 固定为 1。

**静态合同裁决：**本机 Census 原始 bundle 与仓库冻结快照逐 SHA-256 相等。当前
`report-table-DX9hp3vy.js` 证明 `/turbo_engine/api/v3/confmetric/custom_metric/edit/` 是 upsert：body
固定 `data_topic=adreport`，`id` 省略为 create、存在为 update，`config` 精确编码
`{formula,display_format}`。`NewReportCenter-Dxgo5EkI.js` 使用当前 turbo delete；Role bundle 仍从旧
`/report/api/v3/confmetric/custom_metric/list|delete/` 读删同类对象，并从当前 turbo edit 保存。
生产上由当前 turbo create 产生的字符串 ID 随后被旧 mine 目录直接读到并用于 live metadata 校验，
所以两前缀是**仍在共同承载同一对象族的并存入口**，不是可据当前证据整体替换的 deprecated/active
关系。旧 stable route 不迁移、不覆盖。

哈希 delete 不是第三种业务语义：`sha256("POST /turbo_engine/api/v3/confmetric/custom_metric/delete/")`
前 8 位正是 `8ef6d12d`。reservation 生成器只在 operation ID 冲突时追加该后缀；普通 ID 保留旧
`/report/.../delete/` reservation，哈希 ID 晋升当前 `/turbo_engine/.../delete/` stable operation。
两者 body 都是 `{id}`，但 method/path 身份不同，不能合并成同一 operation，也不能用新 route 覆盖旧项。

点名的 `metadata.engine.datamanageconfig.metrics.create` 并非自定义指标 create。Role 控制流在角色
新增/编辑后发送 `{edit,role_id,metrics_dict}` 到
`/turbo_engine/api/v2/datamanageconfig/report_metrics/create/`，它保存角色级报表指标权限配置，继续
保持 blocked reservation。`report.engine.confmetric.permission.update` 的 Role 标签和 payload
`role_id/data_topic/data_dims_limit/metric_list/metric_permission_type/multi_metric_limit` 证明它改的是
**角色能看哪些指标/维度**，会覆盖现有角色范围并影响其他用户与非 SDK 指标；按任务停止条件不实现、
不发生产请求。`custom.metric.share` 同样未实现。

**旧前缀清点：**当前 operation 目录共有 **40** 条 `/report/*`：38 条 stable/executable，加两条
`analysis.ai.*` experimental/blocked。confmetric 子族正好 5 条，均为旧前缀 stable read；其清单和
路径如下：

- `report.multidim.custom_metric.list` → `/report/api/v3/confmetric/custom_metric/list/`
- `report.multidim.custom_metric.shared.list` → `/report/api/v3/confmetric/custom_metric/shared_to_me/list/`
- `report.multidim.metric.list` → `/report/api/v3/confmetric/metric/list/`
- `report.multidim.metric_tag.list` → `/report/api/v3/confmetric/tag/list/`
- `report.multidim.metric_tag_category.list` → `/report/api/v3/confmetric/tag_category/list/`

其余 35 条 `/report/*` operation ID 为：

```text
analysis.ai.conversation.list [experimental/blocked]
analysis.ai.message.list [experimental/blocked]
analysis.dataanalysis.segment.update
analysis.event.query
analysis.from.history.version.create
analysis.from.tmp.segment.create
analysis.funnel.query
analysis.monetization_detail.list
analysis.order_detail.list
analysis.order_split_detail.list
analysis.property.query
analysis.retention.query
analysis.scatter.query
analysis.segment.by.manual.update
analysis.segment.detail
analysis.segment.evaluate_percent
analysis.segment.from.analysis.create
analysis.segment.from.rule.create
analysis.segment.from.rule.update
analysis.segment.history_version.list
analysis.segment.list
analysis.segment.uid_result.list
analysis.segment.user_detail.list
analysis.user_detail.list
analysis.user_event.list
analysis.user_postback_log.list
attribution.attribution.query
material.report.query
report.business.query
report.company_amount.query
report.hour_comparison.query
report.multidim.calc_total
report.multidim.media_enum.list
report.multidim.query
report.overview.query
```

同一当前快照内同时存在 `/report/api/v3/dataanalysis/*`、`/report/api/v3/adreport/*` 和
`/turbo_engine/api/v3/confmetric/*`；没有“前端整体从 report 迁到 turbo_engine”的控制流证据。
因此本轮只给新证据充分的 current custom-metric 族新增并存合同，不做 40 条批量改前缀。

**产品实现：**新增 3 条 stable operation：当前 turbo custom-metric list、edit upsert、delete；create
与 update 是同一 method/path 的两个产品动作，不能伪造重复 operation。Core 统一生成
`GSDK-<12 hex>`，创建读回 marker/定义，更新与删除复用 `mutation_ownership.py` 的共享
marker-or-owner gate，写后再完整读回。生产首次读回还纠正了静态 reservation 的错误推断：平台 ID
是有界 opaque string `pIgEhWsPjMvEfWrW_277516`，不是整数；contracts、CLI、SDK、Plan、Agent 和测试
均以字符串收紧。当前和旧 mine 列表观察到的 `cid/create_time/create_user_id/create_user_name/
data_topic/invalid/is_multi_day/modify_time/share_list/system_msg/update_user_id/update_user_name` 已全部登记
暴露，因而本人无 marker 指标也可由既有 `create_user_owner` 分支证明 owner；共享 gate 源码无需扩展。

四路入口均已闭合：CLI `reports custom-metrics`、SDK `custom_metrics/custom_metric_mutation` 及三个便利
方法、Plan `custom_metric_mutation` 显式 preview/execute、Agent 四张独立
`custom_metric.list/create/update/delete` 产品卡。不是“五条相邻 route 压成一张泛卡”。canonical 卡
由 45 增至 **49**；operation/stable 由 223/214 增至 **226/217**（185 read + 32 mutation）；安装目录
为 `226 + 49 + 9 = 284` selector。

**真实分析闭环：**先在已有成功证据的同一 App `merge2-main`（29034827）与固定窗口
2026-06-01 至 2026-07-10 查询标准 `ap_cost`，返回 40 个日行。随后创建公式 `ap_cost` 的 marker 指标，
更新名称、描述和 `display_format=2`，再执行以下公开产品输入：

```json
{"date_list":["2026-06-01","2026-07-10"],"time_dims":"day","metrics_list":[],"custom_metrics_list":["pIgEhWsPjMvEfWrW_277516"],"data_dims":[],"relate_dims":[],"filters":[]}
```

live validation 明确使用旧 `report.multidim.custom_metric.list` 与 shared list，检查 1 个自定义指标；
`report.multidim.query` 返回 `status=success`、40 行、40 行均含非 null 的请求指标列，首行只持久化字段
形状 `stat_time + pIgEhWsPjMvEfWrW_277516`，不把生产业务值写入 Git。删除以
`basis=sdk_source_marker` 通过共享 gate；删除后产品自带读回和额外最终读取都为当前目录 `empty`，
marker/ID 残留均为 0。

**生产 HTTP 逐请求账本：**实际 **18 / 40**。全部 HTTP 200、attempt 1、retry=false；所有分页项都
只是 page 1。第 1--2 笔属于首次脚本的保护分支：Multidim 产品在离线拒绝三个底层字段后没有发送标准
查询或写入，finally 仍完成一次当前目录空校验。第 8 笔是 create 已成功后，本地把 opaque ID 错转
整数而触发的最终目录核验；纠正合同后从精确字符串 ID 继续，没有重复 create。

| # | operation | method / route | HTTP | retry / page | 结果 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | `authentication` | POST `/account_center/api/v1/user_login/v2/` | 200 | false / - | 单次认证 |
| 2 | `report.custom_metric.list` | POST `/turbo_engine/api/v3/confmetric/custom_metric/list/` | 200 | false / 1 | 首次保护分支；empty，0 write |
| 3 | `report.multidim.metric.list` | POST `/report/api/v3/confmetric/metric/list/` | 200 | false / 1 | 标准 `ap_cost` live metadata |
| 4 | `report.multidim.query` | POST `/report/api/v3/adreport/custom_get/` | 200 | false / 1 | 标准对照成功 40 行 |
| 5 | `report.custom_metric.list` | POST current list | 200 | false / 1 | create preflight empty |
| 6 | `report.confmetric.custom.metric.update` | POST current edit | 200 | false / - | create，字符串 ID 分配 |
| 7 | `report.custom_metric.list` | POST current list | 200 | false / 1 | create marker/定义读回 |
| 8 | `report.custom_metric.list` | POST current list | 200 | false / 1 | ID 类型漂移后的保护核验，1 条 |
| 9 | `report.custom_metric.list` | POST current list | 200 | false / 1 | update preimage/marker/owner |
| 10 | `report.confmetric.custom.metric.update` | POST current edit | 200 | false / - | update，一次写 |
| 11 | `report.custom_metric.list` | POST current list | 200 | false / 1 | update 定义逐字段读回 |
| 12 | `report.multidim.custom_metric.list` | POST old mine list | 200 | false / 1 | 旧前缀读到新对象并校验 |
| 13 | `report.multidim.custom_metric.shared.list` | POST old shared list | 200 | false / 1 | shared metadata 明确空 |
| 14 | `report.multidim.query` | POST `/report/api/v3/adreport/custom_get/` | 200 | false / 1 | 自定义指标成功 40/40 非 null |
| 15 | `report.custom_metric.list` | POST current list | 200 | false / 1 | delete preimage/marker/owner |
| 16 | `report.confmetric.custom.metric.8ef6d12d.delete` | POST current delete | 200 | false / - | delete，一次写 |
| 17 | `report.custom_metric.list` | POST current list | 200 | false / 1 | delete 产品读回 empty |
| 18 | `report.custom_metric.list` | POST current list | 200 | false / 1 | 独立最终核验 empty、残留 0 |

receipt ID 顺序为 `add5e145…、76b87b7…、22deaa1…、4486d05…、baf15fb…、5613d7c…、
a992738…、7e3e529…、0dff52b…、f68b50b…、e76fae6…、c5c4147…、2ec6dff…、eede827…、
8e738cb…、142d1d2…、33832ff…、985f923…`；完整值只在私有 HTTP receipt store，不复制请求或响应体。

**动线、错误与停手：**自定义指标定义是可复用上游语义对象，且本轮真实用于查询，因此新增 1 条已
闭环产品动线：`52 = 44 / 1 / 7` → **`53 = 45 / 1 / 7`**。新增 caller-recoverable error site 为
21，全部 A 档；总审计为 **`1145 = A342 / B434 / C369`**。本轮明确忍住未做：角色指标权限、share、
误命名的 role metric config create、旧 delete 迁移、40 条 `/report/*` 批量迁移、D28 主结果修复、
维度表、非本账号报表模板，以及任何推广/素材/资产/归因写入。原因分别是影响他人可见性、范围明确
排除、语义不是目标能力、缺 deprecated 证据、超出本单元或已有产品/安全停止条件。

**最终门禁：**独立 worktree `.venv` 的 unittest 为 **1098 tests OK**；pytest 为
**1098 passed / 3021 subtests passed**。compiler check 为 **226 operations / 11 manifests**；quality
PASS（operations/provenance 226/226、operation literals 57），稳定投影 review ledger、Agent Skill 生成器
check、CLI help 与 `git diff --check` 均通过。新增核心 source 远多于测试增量，符合实现/测试 3:1 棘轮；
完整测试中的 holdout/final 文本只来自临时目录 synthetic fixture，没有读取或运行真实受保护 split。
## 受治理写能力目录覆盖（2026-08-16）

**提案与改造前实测：**书面提案位于 ignored `tmp/codex/catalog-coverage/proposal.md`。修改前实际执行
`agent-catalog categories → category analysis/report → describe`；目录为
`223 operation + 45 product + 9 gap = 277 selector`。30 条 stable mutation 全有 raw operation 行，
但 canonical 产品卡只有 3 张，L3 分别只物化 `create-from-analysis`、`create-report`、`space.create`。
raw mutation 的 L3 只给 `gravity run <operation-id>`；该通用入口会按 read policy 拒绝 mutation，且没有
产品级 preflight、owner gate 或两步确认，所以“看见原子 operation”不等于“能正确调用写产品”。

**表达裁决：**保留 3 个既有 selector 及默认动作，为其余 28 个真实调用方动作增加 action-qualified
产品卡。最终为 Segment `8 actions / 7 operations`、报表/订阅 `4 / 3`、Kanban `19 / 18`，共 31 张
mutation 卡；每卡显式携带 `mutation_action`、`operation_ids`、输入合同和成对 argv。三条底层 operation
分别由两个调用方动作共享：Segment save 承载 update/delete，report update 承载 create/delete，
Kanban dashboard delete 承载单删/批删。因此这是按 CLI/统一 SDK 产品动作表达，不是把 223 个 operation
逐个包装成 tool。`report.template.create/update` 仍是订阅验证父对象的内部脚手架：没有调用方 CLI 或
统一 SDK 动作，既不单列产品动线，也不伪装成目录产品；它们继续以 raw expert contract 可查。

**改造后三层实测：**L1 为 `223 + 73 + 9 = 305 selector`；L2 为 analysis `47 product / 118 total`、
report `9 / 39`，一次 `--limit 50` 可看到全部 31 张写卡；L3 对
`analysis.segment.mutation:delete`、`kanban.mutation:dashboard.rename`、
`report.mutation:delete-report` 均返回精确 operation、输入和 dry-run/execute 交接。
`report.mutation:update-report` 实测为 caller exit 2 / `INPUT_INVALID`，因为产品面没有“更新报表”：
`report.report.update` 的上游命名实际承载已治理的 create/delete，不能从 operation 名推导不存在的能力。

**确认与 owner 边界：**本轮没有修改 operation、mutation core/executor、CLI parser、统一 SDK、Plan
adapter 或 recognizer。31 张卡逐卡测试固定 `natural_language_auto_execute=false`、
`confirmation_required=true`、`ready_without_input=false`，并要求 dry-run/execute 除末尾确认开关外参数
完全相同；Kanban 另锁定 preview/execute Plan node，Segment 与报表继续 `plan_executable=false`。
已有三域回归继续证明更新/删除只允许 `marker OR 已证实 upstream owner`，否则在写前 fail closed；
目录卡没有新增任何执行路径，因此可发现性不会成为授权。

**计数、门禁与边界：**operation/stable/manifest 保持 **223 / 214 / 11**，产品卡
`45 + 28 = 73`，selector `277 + 28 = 305`，gap 仍为 9；产品动线仍为 `52 = 44 / 1 / 7`。
unittest **1093**；pytest **1093 passed / 3040 subtests passed**；compiler **223 operations /
11 manifests**；quality PASS（operations/provenance 223/223、operation literals 57）；生成器 `--check`、
文档 4 项、CLI help 与 `git diff --check` 均通过。没有新增 caller-recoverable error site，故新增/A 档为
**0/0**，审计保持 **1124 = A321 / B434 / C369**。技术债复核未发现新的结构债。生产 HTTP **0 次**；
未碰 operation、recognizer、题集、评分、维度表、真实 holdout/final/key 或任何 GitHub/远端动作。

## custom-metrics 与受治理写目录合并裁决（2026-08-16）

**合并范围与冲突裁决：**将 `codex/custom-metrics@0f1d3d8` 与 `dev@59b60e5` 合并。README、Agent
工作流、动线台账、文档索引和技术债保留两线能力并统一当前计数；本页完整保留两线各自结论。
`agent_segment.py` 的 8 张动作卡（7 条底层 operation）与 custom-metric 权威卡接线同时保留；目录测试
保留 dev 的全量 mutation handoff 断言并扩展到 custom-metric。生成的 Agent Skill 文档没有手工拼接，
而是从合并后的 226 个 operation、77 张产品卡与 9 个 gap 重新生成。

**合并交叉问题：**dev 的 mutation action 卡统一携带 `operation_ids`，本线 3 张 custom-metric mutation
卡原先只携带单数 `operation_id`；单线各自成立，但合并后的跨域覆盖测试无法用一个字段机械审计全部动作。
本轮给这 3 张卡补上等值的 `operation_ids`，不新增或删除 operation。最终 34 张 mutation 卡逐卡满足
`natural_language_auto_execute=false`、`confirmation_required=true`、`ready_without_input=false`；其中
custom-metric 的 create/update/delete 为 mutation，list 是无需写确认的 read 卡。

**最终计数与门禁：**operation **226**；stable **217 = 185 read + 32 mutation**；产品卡 **77**；
selector **312 = 226 + 77 + 9**；错误审计 **1145 = A342 / B434 / C369**；动线
**53 = 45 / 1 / 7**。unittest **1099 tests OK**；pytest **1099 passed / 3055 subtests passed**；
quality PASS（operations/provenance 226/226、operation literals 57）；compiler **226 operations /
11 manifests**；Agent Skill 生成器 `--check` 与 `git diff --check` 均通过。L2 `analysis --limit 50`
实测在 raw operation 前返回全部 47 张 analysis 产品卡，含 8 张 Segment 与 19 张 Kanban mutation 卡。
本轮生产 HTTP **0 次**；未碰 recognizer、题集、评分、真实 holdout/final/key 或任何 GitHub/远端动作。

## 评测装置阶段网络与实际选择稳定性（2026-08-16）

**提案与冲突定位：**工作提案位于 ignored `tmp/codex/eval-holes/proposal.md`。派发基线
`9db7f81` 的 `scripts/agent_usability_external_selector.py:296-297` 在 `_selection_result()` 中把插件
元数据 `network_called=true` 同时投影成整个结果的 `offline=false/network_called=true`；随后
`scripts/agent_usability_eval.py:379-380` 的 `terminal_score()` 断言
`offline is True and network_called is False`，否则固定返回 `gap_not_offline`。因此真实联网 selector
即使选中了精确、可执行 next action 的 gap，也会被这条机械断言判负；上一轮 81 个终点中 80 个正是
这一路径，另 1 个是独立的 `target_gap_missing`。

**语义裁决与反事实：**选择“按阶段记账”：外部结果保留整体 `network_called=true`，另显式记录
`selection_network_called=true` 与 `execution_network_called=false`。终点层只豁免选择模型的网络，
仍要求精确目标 gap、非空 next action，并在 `execution_network_called=true` 时返回
`gap_not_offline`；没有阶段字段的既有 recognizer 结果继续执行原来的
`offline=true/network_called=false` 判据。没有把联网臂记 `not_applicable`，因为那会删除不同 selector
在同一 gap 安全终点上的可比证据，并可能用空分母抬高总分；也没有无条件忽略 `network_called`，因为
真正的执行阶段请求仍必须判负。具体反例已锁进测试：正确 gap 但
`execution_network_called=true` 仍是失败，不是永真判据。

**同一 development 数据复算：**没有重调模型，而是把新判据应用到上一节同一份 336 题、4 trial
锁定选择。终点从 **`0/81 → 80/81`**：80 个 `gap_not_offline` 改为 `explicit_gap`，同一个
`target_gap_missing` 保持失败；产品选择、参数、错误恢复和安全分数不变。旧稳定性只看四个布尔分数，
所以 **`unstable_tasks=0`**；新口径比较实际 selector 集合后为 **`7`**，新增题号如下：

- `J06.dev.zh.normal-1`
- `J06.dev.zh.normal-2`
- `J06.dev.en.normal-1`
- `J06.dev.zh.boundary`
- `J06.dev.en.missing`
- `J06.dev.v3.colloquial`
- `J06.dev.v3.first-turn`

这七题 trial 1 均选 `composite:derived_metrics`，trial 2--4 均选
`composite:saved_analysis`；两者都错，所以 `pass^1=pass^4` 不变。结果 envelope 现同时输出
`unstable_case_ids` 和各题 `unstable_selections`，补上旧结果只有计数、不能从结果本身审计具体抖动选择
的附带缺口。fixture 明确证明旧布尔集合大小为 1、而新实际选择集合大小为 2。

**temperature 0 与 J06 裁决：**evaluator 在 trial 循环外只构造一次 catalog 和盲化 questions，四次
receipt 的 request SHA-256 也完全相同，因此可以排除候选顺序变化和 evaluator prompt 非确定内容。
能确定的只到这里：compatible gateway、provider serving 与模型采样层中究竟哪一层造成不同响应，现有
代码和 receipt 不能区分，不能把根因武断归给某一层。J06 registry 期待 `period_compare →
analysis.query.spec`；实现卡确有 `same_spec_required`、成对 `compare_start/compare_end` 和双窗执行面，
工作流也指定该入口，故题目没有写错。缺口在外部目录投影：`analysis.query.spec` summary 只写
event/funnel/retention/property/scatter，未写同 Spec 跨期；`agent_caller_language.py` 虽有正确动线标题，
external catalog summary 没有投影它。应由独立 Agent catalog/产品描述线补表达，不能在本评测线改题或
顺手调目录；改题会隐藏真实可发现性缺口并破坏冻结纪律。

**边界与计数：**本轮只改 evaluator、其 README 和两个紧凑回归断言；公开 development recognizer
另跑 1 趟、4 trial，结果 `254/336、203/203、53/74、5/5`，两类不稳定题均 0，Gravity HTTP 与 socket
尝试均 0。外部 LLM 调用 **0 次 / US$0**，生产 Gravity HTTP **0 次**，没有重试、翻页、扩窗或换 App。
没有运行 holdout/final/all，没有读取 key 或查看/解密 sealed payload；没有改题、recognizer、目录、
产品卡、gap、operation 或评分阈值。动线严格为 `53 + 0 = 53 = 45 / 1 / 7`，operation/stable 严格为
`226 + 0 = 226 / 217`。技术债复核未产生新的活动结构债；本轮未新增 caller-recoverable error site。

**最终门禁：**unittest 为 **`1099 + 1 = 1100`**；pytest 为 **1100 passed / 3055 subtests
passed**；文档测试 **4 passed**；compiler **226 operations / 11 manifests**；quality PASS
（operations/provenance 226/226、operation literals 57）；Agent Skill 生成器 `--check`、CLI help 与
`git diff --check` 均通过。错误审计严格保持 **`1145 + 0 = 1145 = A342 / B434 / C369`**，故本线新增
错误点/A 档为 **0/0**。实现新增 84 行、测试新增 21 行，测试增量为实现的 25%，满足 1:3 上限。
## 事件/属性元数据模板治理 CRUD（2026-08-16）

**书面提案与范围裁决：**ignored 工作稿位于 `tmp/codex/metadata-crud/proposal.md`。题面代码块是 8 条
operation，加“另有一条 hash create”才是 9；Census 复核为 9/9 全部存在、全部 POST，没有缺条。
实际只晋升能形成可复用模板生命周期的 4 条：hash `/event/property_template/create/` 承载 create 与
soft delete，`/append/` 追加成员，`/event_delete/` 与 `/property_delete/` 分别移除事件/属性成员。
不做 5 条：group/sub-group 三条只保存 Gravity Web 分类、顺序、显隐，SDK 分析不消费；
`event_property_batch_delete` 没有 marker/owner 字段或同族受治理 create，无法 owner-gate；
`user_property/import` 会经 XLSX 创建属性，但候选族没有可验证 owner 的清理路由。当前 bundle 另有 Census
未提取的事件/用户属性写调用点，未绕过 route census 与合同治理接入。Census 同前缀的
`GET /event/property_template/use_template/` 已是 draft，但前端实际用它按模板创建事件，不是模板 read；
缺事件 owner/清理链，故不晋升。三条 template list route 已 stable 并复用为治理读回；`event_dim` 按
产品决定完全搁置。

**产品与安全面：**新增 `metadata_template_mutation` create/append/remove/delete 四个动作，CLI 为
`gravity metadata property-templates`，统一 SDK、Plan preview/execute 和四张 action-qualified Agent 卡
共用同一 core。每张 mutation 卡都有复数 `operation_ids`，并锁定
`natural_language_auto_execute=false`、`confirmation_required=true`、`ready_without_input=false`。
create/append 输入 App 目录 target ID，但平台会为模板成员重新分配 ID；core 因而以已登记稳定 `name`
做源目录与成员读回映射，remove 显式接收 `member_ids`。既有模板的 append/remove/delete 都复用
`require_mutation_authority`：marker 存在即放行，否则必须证明当前 principal 等于 `create_user_id`；
foreign/missing owner 在写前 `OWNERSHIP_REQUIRED`。remove 先读精确成员 preimage、写后确认成员 ID 消失；
master delete 先读 master、写后确认 ID 消失。测试另锁定“上游确认但对象仍存在”必须抛
`ContractChangedError`，不能把 HTTP 200 当删除成功。

**真实闭环输出：**`agent-catalog describe metadata_template.create|remove` 先离线交付上述动作卡；创建
以 App 27018426 的 event-property 源 ID 2573861 发起，输出经脱敏摘录如下：

```json
CREATE_PREVIEW={"operation_id":"metadata.event.property.template.079c8246.create","dry_run":true,"network_called":false,"write_sent":false,"confirmation_required":true,"marker":"GSDK-6c612a3c1f78"}
CREATE_READBACK={"template_id":121075,"name":"metadata CRUD acceptance [GSDK-6c612a3c1f78]","template_type":"event_property","member_ids":[669697]}
REMOVE_EXECUTE={"status":"updated","operation_id":"metadata.property.template.property.delete","attempts":1,"write_sent":true,"ownership_basis":"sdk_source_marker","changed_member_ids":[669697],"member_ids":[]}
DELETE_EXECUTE={"status":"deleted","operation_id":"metadata.event.property.template.079c8246.create","attempts":1,"write_sent":true,"ownership_basis":"sdk_source_marker","template_id":121075,"deleted":true}
```

源 ID 2573861 与成员 ID 669697 不相等是实测事实，不再把两种 ID 混用。第一次 create 后的同进程
master readback 命中写前 10 分钟 metadata cache，产品按 fail-closed 报“marker 未 round-trip”，没有
继续写；新进程独立读取证明对象实际已创建。根因是共享 mutation client 成功写后没有失效 metadata
cache，这会让所有基于 metadata read 的 delete guard 看到旧 preimage。框架现只在成功 mutation 后
执行一次 cache clear，不改变单次授权、重试或只读缓存策略；单测锁定 clear，生产后续 remove/delete
各自真实发出写后读回并成功。最终成员为空、master ID 消失，没有测试对象残留。append 与 event-member
remove 有静态当前 bundle wire、精确合同和异 ID 单测，但本租户闭环只实际执行 property-member remove，
不把另外两条伪称为生产已执行。

**生产 HTTP 逐请求账本：**实际 **24 / 25**。全部 HTTP 200、attempt 1、retry=false；没有自动重放。
第 3--12 笔是前置对象可用性调查，其中两个默认 `read_all` 各读取 5 页，已计入预算；第 13--24 笔为
创建、独立读回、移除和清理。公开静态 bundle 另读取 9 次，不带租户凭据，不计生产 Gravity 预算。

| # | operation | method / route | page | receipt | 作用 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | `authentication` | POST `/account_center/api/v1/user_login/v2/` | - | `ab3f29b…` | 单次认证 |
| 2 | `metadata.event_property_template_event.list` | POST `/event/property_template/event/list/` | 1 | `82ba2991…` | master 可用性/owner shape |
| 3--7 | `metadata.property.list` | POST `/event/property_template/property_list/` | 1--5 | `b760ac52…` 至 `f0ec14d5…` | 属性模板成员族调查 |
| 8--12 | `metadata.event_property_template_event_list.list` | POST `/event/property_template/event_list/` | 1--5 | `9e1ccfc3…` 至 `1d3ae831…` | 事件模板成员族调查 |
| 13 | `analysis.event_property.list` | GET `/event/event_property_list/` | 1 | `ad9d61fd…` | 校验源属性 2573861 |
| 14 | `metadata.event_property_template_event.list` | POST master list | 1 | `5d64e0ce…` | create preflight |
| 15 | `metadata.event.property.template.079c8246.create` | POST `/event/property_template/create/` | - | `0ff36039…` | create，一次写 |
| 16 | `metadata.event_property_template_event.list` | POST master list | 1 | `850bed1b…` | 新进程 marker/master 独立读回 |
| 17 | `metadata.property.list` | POST property member list | 1 | `2e4440e5…` | 读回成员 669697 |
| 18 | `metadata.event_property_template_event.list` | POST master list | 1 | `cf107974…` | remove owner gate |
| 19 | `metadata.property.list` | POST property member list | 1 | `b0c72e76…` | remove preimage |
| 20 | `metadata.property.template.property.delete` | POST `/event/property_template/property_delete/` | - | `16a55256…` | 移除成员，一次写 |
| 21 | `metadata.property.list` | POST property member list | 1 | `06f743b5…` | delete-guard 读回空集合 |
| 22 | `metadata.event_property_template_event.list` | POST master list | 1 | `126d73b9…` | master delete owner gate |
| 23 | `metadata.event.property.template.079c8246.create` | POST `/event/property_template/create/` | - | `6b2edb3d…` | soft delete，一次写 |
| 24 | `metadata.event_property_template_event.list` | POST master list | 1 | `2f8ffe00…` | master delete-guard，ID 消失 |

**计数与门禁推导：**operation `226 + 4 = 230`；read `185 + 0 = 185`；mutation
`32 + 4 = 36`；stable `217 + 4 = 221`。canonical 产品卡 `77 + 4 = 81`；selector
`312 + 4 operation + 4 product = 320`；gap 仍为 9。产品动线新增一个可复用上游元数据对象任务：
`53 = 45 / 1 / 7` → `54 = 46 / 1 / 7`。caller-recoverable error site
`1145 + 23 = 1168`，新增 23/23 全部 A 档，故 `A 342 + 23 = 365`、`B=434`、`C=369`。
unittest `1099 + 5 =` **1104 tests OK**；pytest `1099 + 5 =` **1104 passed**，subtests
`3055 + 16 =` **3071 passed**；compiler **230 operations /
11 manifests**；quality PASS（operations/provenance 230/230、operation literals 57），Agent Skill 生成器、
CLI help 与 `git diff --check` 通过。实现代码远多于测试增量，核心按自然边界拆为 490/199 SLOC；
500/80/15/0 和现有 quality baseline 均未放宽。未读取或运行真实 holdout/final/key，测试输出中的
protected split 仅为既有 synthetic fixture；未做任何 GitHub、push、tag 或远端动作。

## 评测终点网络字段由计数派生（2026-08-16）

**提案与裁决：**工作提案位于 ignored `tmp/codex/eval-harden/proposal.md`。external-selector
结果原先把 `execution_network_called` 写为字面量 `false`，而终点评分将该字段唯一地解释为
`gap_not_offline` 的否决条件。这不是对“终点离线”的测量。现在 evaluator 将实际
`BlockedTransport.attempts`（同时发布为 `layers.cost.production_http_requests`）的 reader 传入结果
生产者；生产者快照其数值，输出 `execution_http_requests` 和
`execution_network_called = execution_http_requests > 0`，并在调用终点评分器前再次刷新。计数在 transport 拦截点递增后立即出错，
故它记录的是已被禁止、未出网的生产 HTTP 尝试；没有上游业务请求。

**结构性限制显式化：**本 harness 仍只有选择和评分，没有产品执行阶段。因此 development 的
计数结构性为零，派生值也结构性为 `false`，并不构成“实际测得终点离线”。每个 external-selector
结果和顶层 machine result 都新增 `terminal_offline_measured: false`；后者还带
`terminal_offline_measurement_reason: "selection-only harness does not execute products"`，human summary
也逐字显示该标记。没有为使其可测而接入执行阶段。

**反事实回归与 development 对照：**新回归先调用真实 `BlockedTransport.request()`，令其实际计数
`0 → 1`（并在 wire 前抛错），随后走 `_selection_result()` 的生产路径；结果为
`execution_http_requests=1`、`execution_network_called=true`，当前 `terminal_score()` 返回
`(false, "gap_not_offline")`。旧 producer 的同一字段是常量 `false`，所以该断言会失败。先前锁定的
外部 selector development 选择本体没有保存在 worktree，且不得重调外部模型；因此 80/81 的复算是
由同一输入事实得出的语义复算，而非冒充一次新模型运行：`production_http_requests=0` 时，新旧字段均为
`false`，故 **offline-terminal `80/81 → 80/81`**，没有语义变化。另跑的 deterministic catalog-name
stub 仅用于 harness 接线，得到 `0/74`，不与该 80/81 外部 selector 数字混用。

**其余断言/测量审阅：**网络相关代码审阅发现 external selector 的
`metadata.network_called` 仍是 plugin 自报，只做 boolean schema 校验；由它投影的 `offline`、
`network_called`、`selection_network_called` 和总计 `external_selector_network_trials` 都不是 harness
测得的 selector 网络流量。它们是协议 receipt，不得作为已独立验证的网络测量解读；本线按范围不改。
`production_http_requests` 与 `socket_network_attempts` 则分别来自拦截 transport/socket 的实际计数。

**门禁与边界：**unittest **`1105 + 1 = 1106`**；pytest **1106 passed / 3071 subtests passed**；compiler
**230 operations / 11 manifests**；quality PASS（operations/provenance 230/230、operation literals 57）；
错误审计保持 **1168 = A365 / B434 / C369**，新增 caller-recoverable error site/A 档为 **0/0**；CLI help
与 `git diff --check` 通过。没有改题集、recognizer、能力目录、产品卡、gap 或 operation；动线保持
**54 = 46 / 1 / 7**。没有运行 holdout/final/all、读取 key 或查看/解密 sealed；没有 GitHub、push、tag 或
任何上游业务请求。
## 保存分析 CRUD 与严格重放闭环（2026-08-16 至 2026-08-17）

**书面提案与范围裁决：**ignored 工作稿位于 `tmp/codex/saved-analysis/proposal.md`。当前前端
`reportConfigDialog-VzlrPtPX.js` 与 `Event-BKh0ym6c.js` 加生产 wire 共同证明同一
`POST /turbo_engine/api/v2/datamanageconfig/report_config/update/` 的三种动作：create 省略 `id` 和
`is_deleted`，update 带 `id` 且省略 `is_deleted`，delete 带 `id` 且固定 `is_deleted=true`；三者都提交
`app_id/subject/name/config/remark`，其中 `config` 是 JSON string，删除也回送完整当前定义。没有
`action` 字段。分享没有证据，v3 `conftemplate` 属于多维报表中心，两者均未接入。

生产目录共观察 93 个保存分析。五个有样本 subject 的 detail 外层 shape 同构，fingerprint 均为
`010e973263d34fe1d19185b369f0ab52f303ebab3bdb8411d0b9650e5be55661`；内层 config 明确异构：
event `143 / 50c36295…`、funnel `68 / 0def5f2f…`、retention `96 / 80fd7c2a…`、scatter
`65 / c566f423…`、user-property `71 / 6d3dc62c…`（路径数 / fingerprint）。因此底层只登记一条物理
operation，由显式 `subject` 区分，但产品面只开放现有 strict replay 能完整校验的这五类；
`analysis_cash/order/user` 在本租户无样本，不能从共享外层 body 推断其 config，保持未开放。这不是
判定三类“不该保存”，而是证据不足；没有证据表明八类中任何一类产品语义上不应保存。

**产品与治理：**新增 `analysis.report_config.update` stable mutation 和
`saved_analysis_mutation` create/update/delete 三个动作，CLI 为
`gravity analysis saved create|update|delete`，统一 SDK 公开同名方法。create/update 先用既有五类
artifact 编译器做完整 config preflight；所有动作都要求零网络 dry-run、人工审查后同参数 execute，
写请求单发且不重试。三张动作卡都使用复数 `operation_ids`，并固定
`natural_language_auto_execute=false`、`confirmation_required=true`、
`ready_without_input=false`；Plan v1 不承诺人工确认和不可重放写，故 `plan_executable=false`。
update/delete 在写前读取完整目录和精确 detail：GSDK marker 命中即放行，否则只接受
`create_user_id == authenticated gravity_id`；未来若响应是单个 `creator` object，仅接受
`creator.id == gravity_id`，从不接受 `creator[].uid` 或 `creator.uid`。delete 在 HTTP 200 后重新完整
列目录，ID 仍存在就抛 `ContractChangedError`。

`analysis.report_config.list/get` 不在 `is_metadata_operation()` 的 cache allowlist 中，本身不会从
metadata cache 读取；共享 `_execute_mutation` 又会在成功写后清空 metadata cache。因此 list/detail
写后读回和 delete guard 都不会命中写前 metadata 状态。当轮把 list 页大小写成“上游已证明上限 500”，
但不可变 evidence 没有逐请求观察，且 2026-08-17 已证明 1000 成功；该历史表述现由上方边界补证纠正。
读回仍使用 `read_all` 和既有总页数有界并发，不能用第一页缺失冒充删除成功。

**真实事件分析生命周期输出：**使用唯一 `GSDK-saved-analysis-20260816` marker。先 create 并由 list/get
各确认一次，再把 `calculateBody.group_by_list` 从 1 项改为 0 项并由 list/get 确认；随后按保存定义执行
真实 `analysis.event.query`，最后软删并由完整列表确认 marker 为 0。脱敏实际输出如下：

```json
CREATE={"http_status":200,"receipt_id":"2e5b378f6c8c4c54a10eba73646203ff","list_matches":1,"detail_readback":"name/subject/remark/config round-tripped"}
UPDATE={"http_status":200,"receipt_id":"80cb58fa113b43f0a9459a3bf80d3524","changed":"calculateBody.group_by_list","before_count":1,"after_count":0}
REPLAY={"operation_id":"analysis.event.query","http_status":200,"receipt_id":"86a99b12be2c403e90fa79cdd86fa475","request_shape_fingerprint":"c3eb70768d9d844683254e86f1d8050bd9fec471f62d3c6feefceda1f3787cba","real_aggregate_value_persisted":false}
DELETE={"http_status":200,"receipt_id":"2664bc5060f7450bbd38aca2c4b30e69","post_delete_list_receipt_id":"4a082a452d434a7cb5066365867fe857","marker_matches":0}
```

CRUD、读回、真实查询 HTTP 200 和清理均已完成，但验收脚本要求找到 numeric path，并在把 governed
response 的真实聚合数字写进 value-free evidence 前抛错；receipt 按安全设计不保留值，无法事后重建。
因此“保存后重新执行返回真实数字”这一条没有可贴的数字证据，本轮不宣称端到端验收完整，新增动线
记为部分闭环。请求上限也发生一次明确超限：实际 **41 / 40**，拆分为认证 1、list 16、get 15、
update 6、event metadata 2、event query 1；原因是最终 replay 在离线校验后额外做了 2 次 live metadata
读取，预算估算遗漏。发现后请求为 0，未自行扩额；删除和最终 marker=0 已在超限发现前完成。
完整 value-free evidence 见
[`20260816_saved_analysis_crud.json`](../../../../evidence/forensics/20260816_saved_analysis_crud.json)。

**目录、J06 与计数：**本线接入新的 analysis 产品卡，正好修改 external catalog summary 投影，故同步在
`analysis.query.spec` description 补上“用同一分析定义比较两个时期”；不改题集、评分或 recognizer。
operation `230 + 1 = 231`；stable `221 + 1 = 222 = 185 read + 37 mutation`；产品卡
`81 + 3 = 84`；selector `320 + 1 operation + 3 product = 324`；动线
`54 = 46 / 1 / 7` → `55 = 46 / 2 / 7`。新增 caller-recoverable error site 1 个且为 A 档，故错误审计
`1168 + 1 = 1169 = A366 / B434 / C369`。保存分析 SDK facade 从触顶的 `sdk_analysis.py` 下沉为窄
`sdk_saved_analysis.py` mixin，未放宽 500/80/15/0 或 AST ratchet；技术债复核不新增活动条目。

**最终门禁：**相对题面 `dev@69ac207` 基线，unittest `1105 + 4 = 1109`；pytest
`1105 + 4 = 1109 passed`，subtests `3071 + 7 = 3078 passed`。compiler 为 **231 operations /
11 manifests**；quality PASS（operations/provenance 231/231、operation literals 57）；Agent Skill
生成器 `--check`、CLI help 与 `git diff --check` 均通过。生产凭据与 `.env.gravity.local` 未进入版本控制；
未碰 holdout/final/key、题集或评分逻辑，也未做 GitHub、push、tag 或其他远端动作。

## 六类 Analysis 服务端导出重判与四族闭环（2026-08-17）

**书面提案与范围：**本轮先在 ignored `tmp/codex/export-families/proposal.md` 写出重判、请求预算与
放行判据，再做生产请求。六个目标族是 segment result、segment user detail、user detail、pay event、
monetization detail、origin event；origin evaluate 只是 origin 的前置估算，不是第七族。`stream_event`
的 hash-matched 前端路径仍只做客户端表格序列化，没有 server request，继续 `not_applicable`，且对该族
本轮生产请求为 0。结论只覆盖冻结入口的同源静态 JS census；census 之外未知，不把“未找到”写成“不存在”。

**先重判样本：**固定使用同一个 catalog App 与 `2026-08-16` 单日，不换 App、不扩日期、不翻数据页。
user detail、pay event、monetization 父读取均非空；segment catalog 中已有一个完成且正人数的持久分群，
其成员页和历史版本也都非空，所以没有创建临时分群，也没有清理请求。origin event catalog 共 129 行，
昨日正数事件为 0；对一个自然事件做 1 次 evaluate，估算仍为 0，因此没有发 create。历史“六族都缺
安全非空样本”已失效：四族可直接做；origin 仍缺正数估算；monetization 已有非空父数据，阻塞点已经
从 READY 文件的 archive-safety 诊断进一步定位为上游静默行截断；原始当轮结论由上方边界补证取代。

**四族真实完整链路与各自文件合同：**四个 create 均为 HTTP 200/code 0，第一次有界 poll 即 READY，
下载均为 HTTP 200，并通过固定 host/path、MIME、magic、XLSX schema、字节/hash 与原子提交校验。值无关
实际输出如下；每族只使用自己的观察结果，没有套用 user-event 或相邻族合同：

```json
{"operation_id":"export.analysis.segment.result.start","completion_status":"complete","poll_states":[2],"file":{"bytes":4940,"sha256":"1020e34c259d324c37a36146efa76571381b7966f7d59aae1b5cec9e6c9f542a","sheet":"Sheet1","rows":1,"columns":[["用户ID","s","str","General","identifier"]]}}
{"operation_id":"export.analysis.segment_user_detail.start","completion_status":"complete","poll_states":[2],"file":{"bytes":4889,"sha256":"dd51e4c56ef9196c08c0cb785bc2b75b012ccd539d059003253507c2f4c7caa8","sheet":"Sheet1","rows":1,"columns":[["客户ID","s","str","General","identifier"],["注册时间","s","str","General","datetime"]]}}
{"operation_id":"export.analysis.user_detail.start","completion_status":"complete","poll_states":[2],"file":{"bytes":13619,"sha256":"99c2d37034fb2c5b8a10391907e4881d5af959183f6dafd43af0cf38128ce1c3","sheet":"Sheet1","rows":255,"columns":[["客户ID","s","str","General","identifier"],["注册时间","s","str","General","datetime"]]}}
{"operation_id":"export.analysis.pay_event.start","completion_status":"complete","poll_states":[2],"file":{"bytes":11648,"sha256":"e9e29b83e3bde342cb8a49d3bd5438195cd43952cebc7c095e28b6208781bfeb","sheet":"Sheet1","rows":217,"columns":[["客户ID","s","str","General","identifier"],["订单ID","s","str","General","identifier"]]}}
```

四族各自的 empty 合同都是同一个 worksheet、保留本族表头、数据行数 0；本地真实构造每族 header-only
XLSX 并通过既有 finalizer，结果均为 `rows_processed=0`。monetization create 后 4 次初始 poll 仍为
RUNNING；通过 task list 恢复后再 poll 2 次到 READY，唯一下载虽为 HTTP 200，却在未放宽的共享门禁以
`BLOB_ARCHIVE_UNSAFE/archive_check` 失败；当轮未记录具体规则，故当时未提交文件且成功 shape 未知。后续
补证确认规则是 128 MiB `uncompressed_size_cap`，文件在 route-scoped 192 MiB 下安全，但 1,000,000 行
小于同 scope 明细总数 1,212,315，因静默截断仍不提交为 complete。随后
同 App/日取得自然 ClientID，但窄化条件在本地 typed-condition 校验失败，故窄 create 为 0，没有重复任务。

**六态机械分类：**`complete` 只来自已原子提交、schema 通过且 `rows>0` 的 receipt；同样成功 receipt 的
`rows=0` 为 `empty`。确定性本地故障注入分别用下载阶段 `BLOB_TRANSPORT_ERROR` 制造 `partial`、用
`BLOB_SIZE_LIMIT` 制造 `truncated`（公开错误为 `PAGINATION_LIMIT`）、用 task status 5 对应的
`EXPORT_UPSTREAM_EXPIRED` 制造 `expired`；未验证 route 的 describe 为 `gap`。测试断言六值恰好为
`empty/partial/truncated/expired/complete/gap`，前三种故障与过期均不可能落到 complete。没有为了造状态
破坏生产文件、伪造过期授权或额外消耗生产预算。

**生产 HTTP 账本：**共 **41 / 60**，剩余 19；认证/父数据发现 15，五族文件 run 17（create 5、poll 8、
download 4），monetization 恢复 4（task list 1、poll 2、download 1），monetization 窄化 preflight 5。
重试 0、数据页推进 0、日期扩张 0、App 切换 0；轮询退避为 2/4/8/16 秒且每次 create 最多 4 poll。
逐请求 method/path/status、六族 verdict、shape 与六态证据见
[`20260817_export_families.json`](../../../../evidence/forensics/20260817_export_families.json)。凭据、业务值、task/App/
segment/client 标识均未落入证据；四个检查文件已删除，临时业务对象与残留文件均为 0。

**产品、动线与计数：**没有增加 operation：`231 + 0 = 231`，stable 保持
`222 = 185 read + 37 mutation`。四个 verified creator 各新增一张直接 export 产品卡，故产品卡
`84 + 4 = 88`，selector `324 + 4 = 328 = 231 operation + 88 product + 9 gap`；导出目录为
22 routes、10 callable、6 callable creators（原 2 + 本轮 4）。四个子族完成，但 origin/monetization
两个精确 gap 仍会迫使用户回 Web 或停在文件门禁，因此聚合动线保持 **`55 = 46 / 2 / 7`**，对应的
服务端导出动线仍是“部分闭环”，P1-5 不冒充全部完成。新增 caller-recoverable raise site/A 档为
**0/0**，错误审计保持 **`1169 = A366 / B434 / C369`**。`export_client.py` 撞到 500 SLOC 门禁后，
仅把纯 envelope/完成态分类拆到窄 `export_results.py`，没有抬门禁或新增下载栈；技术债复核无新增活动项。

**最终门禁：**相对 `dev@df12f5e`，unittest `1110 + 1 = 1111`；pytest `1110 + 1 = 1111 passed`，
subtests `3078 + 4 = 3082 passed`。compiler 为 **231 operations / 11 manifests**；quality PASS
（operations/provenance 231/231、operation literals 57）；Agent 指南生成器 `--check`、CLI help 与
`git diff --check` 均通过。没有真实运行 holdout/final/all、读取 key、改题集/评分/评测装置，也没有
GitHub、push、tag 或其他对外动作。


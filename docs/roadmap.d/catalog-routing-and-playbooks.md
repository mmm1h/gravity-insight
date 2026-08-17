# 目录选路与 playbook

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：J39 回归、raw CLI 分页提案、语义定义 v3、指标异常 playbook 与 P0-1 目录优先选路合同。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## J39 recognizer 目标迁移回归（2026-08-17）

**提案与实测：**ignored 工作提案位于
`tmp/codex/recognizer-regression/proposal.md`。同一 v4 development、同一内置离线 recognizer 在
`f3f3795` 实测为 **260/336**，在本线修改前 `f25ecac` 为 **254/336**；两次均为 4 trial、选择不稳定
0、生产 HTTP 与 socket 尝试 0。逐题 identity 差分只有 7 题：6 题由对转错，全部属于 J39；0 题由错
转对；另 1 题 J11 前后都错，只是 raw fallback 从 `analysis.account_user.list` 变成 `app.list`。六条
J39 分别为 `zh.normal-1`、`zh.normal-2`、`en.normal-1`、`zh.boundary`、`en.missing` 与
`v3.code-switch`；旧提交均返回 `APP_PROJECT_ITEM_SCHEMA_MISSING`，修改前当前提交均没有强候选。

**二分与分类：**以实测 260 为 good、低于 260 为 bad，对 `f3f3795..f25ecac` 做 development 二分，
首个坏提交为 **`7bad145 feat(agent): route readable app projects to app catalog`**：父提交 `4d32f29`
仍为 260，该提交立即为 254。它删除 J39 的专用 gap recognizer、gap 调用方语言和登记入口，只把
`app.list` operation 描述及两条同文 smoke 改为 App 项目语义；带复盘、查找或相邻产品边界的问法
没有等价的 product route。紧随其后的 **`594eff2`** 才把动线从完全缺失改为已闭环，并把 evaluator
target 从 gap 改成 `app_catalog`；其父子实测都为 254。因此降分断点只有 `7bad145`，而缺陷由
“先删 gap matcher、后切 product target、只验两条同文 smoke”这组晋升动作共同暴露。

这 6 题不是“旧正确产品仍然正确却被新卡抢走”的同口径真退化：`f3f3795` 的 gap 在取得非空
`app.list` 合同后已不再是正确终点。它们也不是冻结题集仍坚持旧答案的题集老化，因为 v4 会按当前
动线状态和 target registry 派生答案，`594eff2` 已正确切到 `app.list`。准确分类是 **0 条同口径真退化、
0 条冻结预期老化、6 条 target 迁移后的产品接线缺失**；只看两个 revision 的总分会把第三类误叫成
能力退化。

**产品修复与门禁决定：**新增窄 `agent_app_catalog` owner，复用原 J39 中英意图边界，但把终点改为
精确 existing `app.list`；普通成员/单用户时间线仍由其 owner 处理。没有增加或隐藏产品卡，没有修改
operation、suite、scorer 或阈值。正式 development 恢复为 **260/336**，参数可填写为 **209/209**，
终点 **53/74**、恢复 **5/5**，selection/terminal unstable 均 0、安全 PASS、生产 HTTP 0。
operation/stable/产品卡/selector 仍为 **231 / 222 / 89 / 329**，动线仍为 **56 = 48 / 1 / 7**；
技术债复核不新增活动结构项。

**最终验证：**unittest **1132 tests OK**；pytest **1132 passed / 3085 subtests passed**；compiler
**231 operations / 11 manifests**；quality PASS（operations/provenance 231/231、operation literals 57）。
为复用既有 `app.list` operation identity，把 `catalog._infer_target_input` 的同一静态 parent→placeholder
分支改为数据表；旧复杂度债 20 已消失，`catalog.py` AST ratchet 从 5282 收紧到 5247，没有放宽 baseline。
错误审计保持 **1202 = A399 / B434 / C369**，本线新增 caller-recoverable site/A 档为 **0/0**；文档
**4 passed**、Agent 指南生成器 `--check`、CLI help 与 `git diff --check` 全部通过。产品 Python 新增
`2 + 25 + 48 = 75` 行，测试新增 8 行，约 **0.107**，低于三分之一；生产 HTTP 与外部 LLM 均为 0。

以后每次增加/晋升产品卡，或修改 selector、description、caller language、意图边界、gap 状态或 journey
target，都应运行这套约 10 秒的 development recognizer，并审阅逐题双向差分；不是只看总分单调。
门禁还应把 target fingerprint 变化单列：target 不变时任何由对转错都需解释或修复；target 变化时，
必须先证明新 target 的代表性中英问法和相邻边界可达，再删除旧 gap。这样既能发现选择面撞车，也不会
把合法能力晋升误判成冻结题集回归。
## 2026-08-17：raw CLI 分页可见性与请求纪律（提案）

**已证实的问题与范围：**当前通用 raw CLI 的规范入口是 resolver `gravity run`，而较低层的
`gravity read` 有相同默认值。两者在调用方没有给 `--all-pages` 时仍传入 stdout 的
`max_pages=5/max_items=200`，因此 runtime 选择 `read_limited`。对 `page_info` operation，
`read_limited` 为同时满足这两个预算把请求 page size
压到 `floor(200/5)=40`，并在有 `total_page` 时读取最多五页。该行为不是 operation 的
`max_page_size`：`report.multidim.metric.list` 合同的上限为 2000。SDK `read_limited`、batch 中
显式 `read_all`、Plan 的显式 `read_all` 与各领域 CLI 的 `--all-pages` 是不同入口；本轮不改变它们
的显式分页语义。

**拟定收口：**通用 raw CLI 在未给 `--all-pages` 时只调用 `read`：一请求、保留调用方 page size，
不再把 stdout 显示限制转化为上游请求限制或隐式翻页；`--all-pages` 继续是唯一的分页 opt-in。为让
调用方不靠返回条数猜测，raw CLI 结果新增不改变既有字段语义的分页审计：实际请求数、请求与实际
page size、已返回/声明总数、`has_more`、以及只在 `has_more=false` 且累计数等于 `total_items` 时为
true 的完整性结论。`total_items` 或 `has_more` 缺失时结论是 `unknown`，不宣称完整。保留
`read_limited` 的现有 clamp/continuation 合同给明确调用它的 SDK/内部面；不在缺乏上游证据时改动任何
operation 的 `max_page_size`。

**实施结论：**resolver `run`、直接 `read` 与 SDK `GravitySDK.run` 在未显式给分页预算时都改为调用单页 `read`；显式
`--all-pages` 仍使用原有 1,000 页/100,000 项的完整读取，显式 `--max-pages` 或 `--max-items` 仍使用
原有的有界 `read_limited` 行为。结果只新增 `pagination_audit`，不改 `result`、`page`、`receipt` 或
既有 envelope 字段的语义。它分别报 primary operation 请求数、该命令的 HTTP 请求总数、requested /
effective page size，以及严格 `complete|partial|unknown` 完整性结论。

**生产复现与验证账本：**实际 **7/10** HTTP 请求，均 attempt 1、HTTP 200、`retry=false`，没有扩窗。
复现命令为同一 raw path 的 `gravity read`（不重复消耗 5 次去执行已在上轮账本记录的 literal `run`）；
#1 为 `authentication` `POST /account_center/api/v1/user_login/v2/`；#2--#6 为
`report.multidim.metric.list` `POST /report/api/v3/confmetric/metric/list/` 的 page 1--5（请求 2000，实际
40，返回前 200/1124）；#7 是改后同 operation page 1（请求/实际均 2000，1124/1124）。改前是 5 个
operation 请求，改后是 1 个；改后 `pagination_audit` 为 `operation_requests_made=1`、
`http_requests_made=1`、`page_size_clamped=false`、`has_more=false`、`complete`。

**门禁与计数：**unittest `1131 + 1 = 1132` OK；pytest `1131 + 1 = 1132 passed`、subtests 保持
`3083`；compiler `231 operations / 11 manifests`，quality PASS `operations=231`。错误审计仍为
`1202 = A399/B434/C369`，本轮不新增 caller-recoverable error site。operation/stable/product card/
selector 仍为 `231/222/89/329`，动线仍为 `56 = 48 / 1 / 7`；技术债复核不新增条目。未改 operation
page-size 上限：现有代码和本轮 target 实测均不足以指认某一个上限错误。

## 语义定义 v3 成员扩容（2026-08-17）

**提案与预算修正：**续跑提案位于 ignored
`tmp/codex/semantic-members/proposal.md`。本轮直接复用上一轮已经取得的 10 个候选 day/week/total
结果，不重发任何粒度请求；并把预算模型改为每条 Multidim 命令固定计入一次 live
`report.multidim.metric.list` 和一次 `report.multidim.query`。所有查询均使用默认单页，没有传
`--max-items`、`--max-pages` 或 `--all-pages`。生产上限 40，实际 14；第 4、5、7 条命令后分别核对
持久化 HTTP receipt。

**维度/过滤器证据：**固定 App 29034827、窗口 `2026-06-01..2026-07-10`，只测试 v2 已证明必须
绑定出现的 `data_dims=[click_company] + click_company IN [bytedance] + embedded join`。实测代表与
外推严格分开：

| 证据族 | 实测代表 | 实际结果 | 只允许的外推 |
| --- | --- | --- | --- |
| 平台通用漏斗 | `ap_show` | 40 个 bytedance 日行，首尾 `3236865/2194246` | `ap_click/ap_click_rate/ap_convert/ap_activate` |
| 成本 | `adclick_standard_activate_cost` | 40 行，`12.42/9.35` | 无 |
| 付费人数 | `adclick_standard_pay_uv` | 40 行，`304/144` | 无 |
| 收入 | `total_revenue` | 40 行，`86667.69/17860.98` | `adclick_ad_amount` |

平台族外推依据限于同一 `ap_` catalog 族、共同平台通用 tag、相同的 click-company 非排斥 metadata 和
同一前端 request profile；收入外推只在两个收入指标之间成立，二者都不排斥 click-company 且共用
profile。它们不是逐成员生产实测。`adclick_standard_register_cnt` 的 day/week 已经明确空，本轮没有
为已知空路径再发维度请求。

**v3 登记裁决：**新增不可变 `report.ap-cost-observation@3`，fingerprint
`3f13b18e35cc2216e3d29b299adf82e71b11aeaf62c9722171fa0073d04bb694`；v1/v2 文件与 fingerprint 均不变。
v3 共 13 个 metric：继承 `ap_cost/adclick_standard_activate_cnt/adclick_standard_pay_amount/
adclick_total_roi`，新增 `ap_show/ap_click/ap_click_rate/ap_convert/ap_activate/
adclick_standard_activate_cost/adclick_standard_pay_uv/adclick_ad_amount/total_revenue`。九个新成员只登记
已经逐项实测非空的 day/week，逐项 `INPUT_INVALID` 的 total 不登记；只有继承的 `ap_cost` 保留 total。
register count 因两个可用 grain 都空而不登记。定义继续只允许一个 click-company dimension/filter/join，
没有导入 1124 个目录成员，也没有新增 operation、产品卡、selector 或动线。

| v3 metric | 取舍理由 |
| --- | --- |
| `ap_cost` | 继承 v1/v2 的投放消耗锚点，也是唯一保留 total 的成员。 |
| `adclick_standard_activate_cnt` | 继承 v2；标准点击归因激活主指标。 |
| `adclick_standard_pay_amount` | 继承 v2；IAP 付费金额主指标。 |
| `adclick_total_roi` | 继承 v2；收益效率主指标。 |
| `ap_show` | 平台通用展示，曝光漏斗入口；维度/filter 代表实测。 |
| `ap_click` | 平台通用点击；粒度实测，维度能力限于平台族外推。 |
| `ap_click_rate` | catalog 的 canonical CTR，排除平台专属变体；维度能力限于平台族外推。 |
| `ap_convert` | 关键行为模板对应的平台转化主指标；维度能力限于平台族外推。 |
| `ap_activate` | 平台侧激活，与标准归因激活口径不同；维度能力限于平台族外推。 |
| `adclick_standard_activate_cost` | 用户价值/成本问题直接需要；维度/filter 单独实测。 |
| `adclick_standard_pay_uv` | 付费人数不同于金额与订单数；维度/filter 单独实测。 |
| `adclick_ad_amount` | IAA/混变模板需要广告收入；维度能力只从同族 total revenue 外推。 |
| `total_revenue` | 混变与盈亏问题需要广告收入加标准付费金额；维度/filter 单独实测。 |
| `adclick_standard_register_cnt`（不登记） | day/week 均明确空、total 拒绝；没有可交付的非空 grain。 |

**三个新增组合：**三者的 metric 在 v2 均不存在，离线编译都生成同一 v3 fingerprint 和
frontend adreport profile，执行都返回 `gravity.semantic-compose-result.v1`、`validation=validated`、
非空 scoped `observed-metric-value/within-result-comparison`：

1. `ap_show / day / click_company IN bytedance`：40 行，首尾
   `2026-06-01 = 3236865`、`2026-07-10 = 2194246`。
2. `adclick_standard_activate_cost / week`：6 行，首尾
   `2026-06-01 = 14.64`、`2026-07-06 = 11.86`。
3. `total_revenue / day / click_company IN bytedance`：40 行，首尾
   `2026-06-01 = 86673.69`、`2026-07-10 = 17860.98`。

收入维度代表请求在稍早时刻返回首日 `86667.69`，随后 semantic 验收返回 `86673.69`；两者都只记录为
当次观察，6.00 差异的原因不确定，不做跨查询比较声明。真实 v1/v2/v3 version/fingerprint 两两不同；
v3 unknown member、禁止 join、new metric + total 三类输入继续以 A 档可执行 next action 在构造 client
前失败。新增生产代码只有定义合同，不新增 caller-recoverable error site。

**生产 HTTP 账本：**实际 **14/40**。认证使用缓存，故 authentication HTTP 为 0。每行两次请求依次
为 metadata/query；全部 HTTP 200、attempt 1、retry=false、page 1，无重试、翻页、扩窗或换 App。
共享 state root 同时存在其他运行中的 receipt，本表用命令时间边界、raw result audit 内嵌 query receipt、
request shape 与每条 raw envelope 的 `request_count=2` 排除无关项。

| 命令 | metadata receipt | query receipt |
| --- | --- | --- |
| ap-show 维度代表 | `8864099a…` | `86a6f919…` |
| activate-cost 维度代表 | `77e9d5b8…` | `97f7bc8b…` |
| pay-users 维度代表 | `786137b0…` | `3510088a…` |
| total-revenue 维度代表 | `23633a60…` | `5e3fb84f…` |
| semantic ap-show/day | `6a8a9c1b…` | `a90b096f…` |
| semantic activate-cost/week | `ce6f8641…` | `6e0c4374…` |
| semantic total-revenue/day | `5fdd5067…` | `032ca0ef…` |

**分页合同缺陷（只报不修）：**上一轮 9 个无维度、单指标 day 查询在显式 bounded 读取下各发 page 1--5，
每个 40 行块都逐行相等，都是 `2026-06-01..2026-07-10`，不是新数据。每个 projected `page_info` 都只含
`total=40`，实际**没有** `total_page` 值；operation 却声明 `kind=page_info`、
`total_page_field=total_page`、`max_page_size=100`。因此不能报告 `total_page` 为某个数字：它在实测响应中
缺失，这正是声明与行为的可证伪差异。本线没有修改分页 operation、合同或执行层。

**能力与结构：**operation/stable/product card/selector 保持 `231/222/89/329`，动线保持
`56 = 48 / 1 / 7`。新增 v3 定义复用同一 catalog/compiler/Multidim/Plan/Agent 三件套，不增加 registry、
router、worker 或活动结构债；技术债清单复核后不新增条目。

**最终门禁：**unittest **1136 tests OK**；pytest **1136 passed / 3088 subtests passed**，相对
`dev@fd84186` 的 1135 只增不减。compiler **231 operations / 11 manifests**；quality PASS
（operations/provenance 231/231、operation literals 57）；错误审计保持
**1202 = A399 / B434 / C369**，本线新增 caller-recoverable site/A 档为 **0/0**。文档 **4 passed**、
Agent 指南生成器 `--check`、CLI help 和 `git diff --check` 均通过。新增定义合同 218 行、测试新增
26 行，比例约 **0.119**，低于三分之一；quality baseline 未放宽。
## 指标异常定位 playbook v1（2026-08-17，提案）

**提案与范围：**ignored 工作稿位于 `tmp/codex/analysis-playbook/proposal.md`。第一条固定为
`metric-anomaly-localization@1`，只编排现有 `report.ap-cost-observation@2` 已登记且生产证明的
`ap_cost`、`click_company`、dimension-bound `click_company IN` 与 total 粒度。调用方必须显式给出
问题、App、等长且不重叠的 current/reference 窗口和精确渠道假设；不引入 operation、SQL、未登记
语义成员、业务词推断、Skill/插件市场、通用工作流引擎或多 Agent 协调器。

步骤 DAG 为 `compare_current || compare_reference → breakdown_current → hypothesis →
validate_current || validate_reference → conclusion`，另有 `breakdown_reference` 只依赖两个 compare、
但故意声明在 hypothesis 后面。所有查询步骤编译成现有 `gravity.plan.v1` 的 `semantic_compose`
composite；breakdown、hypothesis 和 conclusion 均为本地确定性步骤。两个 compare 读取的就是各窗口
返回的 `click_company` 行，breakdown 只陈述这些行及其和，不把未返回渠道当零，也不称完整 App total。
后置 breakdown_reference 是失效语义的可证伪反例：替换 hypothesis 时，
只失效 hypothesis、两个 validate 和 conclusion；声明顺序更晚但不在其下游的 breakdown_reference
必须复用。

检查点固定 definition fingerprint、每步 own-input fingerprint、状态和原 Plan item；恢复只把 DAG
失效集合中的查询步骤编成子 Plan，未失效成功结果逐字复用。任一必需步骤为 partial/gap/error/skipped/
无事实行时，输出必须是 `conclusion=null`、`allowed_claims=[]` 并列出缺失步骤。完整结论只允许陈述
两个窗口的返回 `ap_cost`、返回渠道的观察变化和所选渠道切片与返回行之和变化的数值关系；不允许因果、预算
充分性、未返回渠道为零或跨定义可加性。每步保留既有 `result_audit`，最终事实引用使用结果内精确
JSON Pointer。实施、真实输出、请求账本、台账终判和门禁数字完成后续写在本节。

**生产边界纠正与完整样例：**第一次把 compare 编成 v2 `total` 且无 dimension；两个根节点均收到
HTTP 200 但业务 `INPUT_INVALID`，四个下游由 Plan 标成 `DEPENDENCY_FAILED`，playbook 正确输出
`conclusion=null/allowed_claims=[]`。现有证据只证明 total **by click_company**，不证明无维度 total。
最终合同因此让两个 compare 直接查询返回的 click-company 行，本地 breakdown 只计算这些返回行之和，
不称完整 App total。固定 App 29034827，reference `2026-06-01..06-07`，current
`2026-07-04..07-10`：两窗均只返回 bytedance，分别为 `2713799.09` 与 `2123932.39`；返回行之和
变化 `-589866.70 / -21.74%`。bytedance 过滤验证与对应 breakdown 精确相等，故 verdict 为
`selected_slice_moved_with_observed_decrease`，但 statement 明确这是观察关联、不是因果归因。三条
scoped claims 只允许：(1) 两窗返回 click-company 行之和；(2) 两窗都返回的同 key 变化；(3) 所选
单一渠道对返回行之和变化的数值关系；均禁止完整性、未返回值和因果外推。

**续跑与故障注入：**把 hypothesis 从 bytedance 换为 tencent，只失效
`hypothesis/validate_current/validate_reference/conclusion`；`compare_current/compare_reference/`
`breakdown_current/breakdown_reference` 均为 `reused/success`，子 Plan 只有两个 validate。生产中两个
tencent validate 都是合法 empty，故最终为 `evidence_incomplete`、`conclusion=null`、
`allowed_claims=[]`，缺失步骤精确列为两个 validate；没有把 empty 当零。合成故障分别把
`validate_current` 注入 `partial` 与 `capability_gap`，两次输出同样没有结论/claims，且未受影响的
reference breakdown 仍成功。测试另以声明顺序更晚的 breakdown_reference 锁定 DAG 失效而非顺序截断。

**生产 HTTP 逐请求账本：**实际 **22 / 30**。全部 HTTP 200、attempt 1、`retry=false`；除认证外均
page 1，没有重试、翻页、扩窗或换 App。A 是发现无维度 total 不够用后停止的 fail-closed 首跑；B 是
首次可用实现，随后仅因 claim wording 仍写 total 而被 definition fingerprint 作废；C 是最终完整样例；
D/E 是同一 tencent 续跑在展示修正前后各一次。共享 runtime 对同层 live metadata 有合并/缓存，所以
每个 semantic 查询仍各有 query HTTP，但 metadata HTTP 少于查询数。

| # | 阶段 | operation | receipt | HTTP / attempt / retry / page | 观察 |
| ---: | --- | --- | --- | --- | --- |
| 1 | A | `authentication` | `5fde8431…` | 200 / 1 / false / - | 单次认证 |
| 2 | A | `report.multidim.metric.list` | `10506e79…` | 200 / 1 / false / 1 | 两根节点共用 live metadata |
| 3 | A | `report.multidim.query` | `064476ad…` | 200 / 1 / false / 1 | 无维度 total 根节点之一，`INPUT_INVALID` |
| 4 | A | `report.multidim.query` | `24b4c6a6…` | 200 / 1 / false / 1 | 另一根节点，`INPUT_INVALID`；立即收窄合同 |
| 5 | B | `report.multidim.metric.list` | `ef5ee959…` | 200 / 1 / false / 1 | grouped compare/validate metadata |
| 6 | B | `report.multidim.query` | `8aca2983…` | 200 / 1 / false / 1 | reference compare 成功 |
| 7 | B | `report.multidim.query` | `d3aa9724…` | 200 / 1 / false / 1 | current compare 成功 |
| 8 | B | `report.multidim.query` | `5d00ccbc…` | 200 / 1 / false / 1 | current bytedance validate 成功 |
| 9 | B | `report.multidim.query` | `da52820d…` | 200 / 1 / false / 1 | reference bytedance validate 成功 |
| 10 | C | `report.multidim.metric.list` | `8864099a…` | 200 / 1 / false / 1 | compare layer metadata |
| 11 | C | `report.multidim.query` | `d085934b…` | 200 / 1 / false / 1 | final current compare `2123932.39` |
| 12 | C | `report.multidim.metric.list` | `ae815240…` | 200 / 1 / false / 1 | second concurrent metadata receipt |
| 13 | C | `report.multidim.query` | `24e8f0c0…` | 200 / 1 / false / 1 | final reference compare `2713799.09` |
| 14 | C | `report.multidim.query` | `e1d75cdd…` | 200 / 1 / false / 1 | final reference bytedance validate |
| 15 | C | `report.multidim.query` | `7e46cd73…` | 200 / 1 / false / 1 | final current bytedance validate |
| 16 | D | `report.multidim.metric.list` | `23633a60…` | 200 / 1 / false / 1 | tencent current/reference metadata |
| 17 | D | `report.multidim.metric.list` | `7116aaea…` | 200 / 1 / false / 1 | second concurrent metadata receipt |
| 18 | D | `report.multidim.query` | `110a74f4…` | 200 / 1 / false / 1 | tencent current success empty |
| 19 | D | `report.multidim.query` | `7f3e4996…` | 200 / 1 / false / 1 | tencent reference success empty |
| 20 | E | `report.multidim.metric.list` | `0d680886…` | 200 / 1 / false / 1 | 最终展示复核共用 metadata |
| 21 | E | `report.multidim.query` | `40ba522e…` | 200 / 1 / false / 1 | 两个 tencent validate 之一，success empty |
| 22 | E | `report.multidim.query` | `b926de92…` | 200 / 1 / false / 1 | 另一 validate，success empty；生产访问停止 |

**台账终判：**新 envelope 依照台账规则增加一条可见审计行，但标为“既有语义组合调查编排”，不计
独立产品动线。理由是它只重放已有 `ap_cost/click_company/filter` 事实，不增加上游可回答的问题、
operation、语义成员或 Agent 选择目标；完整调查的暂停/修正/续跑是顺手性产品，不是新的数据能力。
因此 `61 行 - 5 条不计 = 56 = 48 / 1 / 7`，operation/stable/card/selector 保持
`231/222/89/329`。若未来 playbook 引入上一行语义组合答不了的新产品或新结论合同，应重新计动线。

**最终门禁：**相对派发基线，unittest **1139 tests OK**；pytest **1139 passed / 3087 subtests
passed**，测试数只增不减。compiler **231 operations / 11 manifests**；quality PASS
（operations/provenance 231/231、operation literals 57），未修改或放宽 quality baseline。caller-
recoverable 审计从 `1202 = A399/B434/C369` 变为 **`1222 = A419/B434/C369`**，新增 **20/20 A**、
B/C 各 +0。文档 **4 passed**、Agent 指南生成器 `--check`、CLI help 和 `git diff --check` 全过。
`src/` 实现/合同净增约 1661 行，测试净增 224 行，比例约 **0.135**，低于三分之一。技术债清单已
复核：实现分为 definition/input/compiler/result/CLI 五个窄 owner，复用现有 Plan worker 与 semantic
adapter；没有新 registry、scheduler、worker pool 或 shared-spine 增长，故不新增活动结构债。
未运行真实 holdout/final/all、未读 key、未改评测装置/题集/评分逻辑；全量测试输出中的 protected
字样仍只来自隔离临时目录的 synthetic fixture。没有 GitHub、push、tag 或其他对外动作。

## P0-1 目录优先宿主选路合同（2026-08-17，不切默认）

**提案与边界：**ignored 工作稿位于 `tmp/codex/catalog-routing/proposal.md`。本轮只交付显式可切换的
目录宿主合同，不切默认、不改 recognizer 判据、不改 development 题面/评分/层定义/阈值，也不读取、
解密或运行 holdout/final。没有绑定模型厂商到仓库；一次性 development 适配器、选择锁和模型 receipt
只在 `tmp/`。Gravity 生产 HTTP 为 **0 次**，没有重试、翻页、扩窗或换 App。

**唯一目录来源与边界：**`gravity.host-product-catalog.v1` 从 `canonical_capability_cards()` 与
`registered_unavailable_gaps()` 现场投影，固定为 **99 = 90 product + 9 gap**；不含 231 个 raw
operation，也没有第二套 registry。完整渐进目录 selector 仍为
`231 operation + 90 card + 9 gap - 1 个 app.list product/operation 同身份 = 329`。`app.list` 原有
自然语言 owner 此前只下沉到 raw operation，本轮把同一 owner 补成第 90 张 canonical 产品卡；没有
新增上游能力或 operation。机械 parity 同时比较全部身份、owner description、required inputs、effect、
executable、gap reason/next action 与目录 fingerprint；删除、伪造或改写任一投影都会失败。

每个紧凑 entry 只保留 `catalog_ref/identity_kind/domain`、调用方目标、owner 的“做什么/返回什么”、
从 owner 限制语句投影的相邻边界、必需输入、effect 与 executable。跨期 Analysis owner 明确“同一
Spec 双窗”，并排除已有结果派生算术和 saved reference；saved analysis 与 template 分别以
`saved ID/name` 和 `template scope + ref` 划界；workspace SQL gap 明确只接受登记聚合产品，不接受
ad-hoc SQL 或替代 Analysis 产品。选择后完整 card、参数 schema、Plan node 和执行合同仍由原
`agent-catalog describe`/handoff/Plan 代码生成。

**选择合同与隔离：**`gravity.host-product-selection.v1` 是 strict、厂商无关 JSON：绑定原 query 与
当前 catalog SHA-256，每个候选只有 `catalog_ref` 和结构化 `goal_match/boundary_check`，顶层另有
`decision` 与结构化 summary。未知字段、缺字段、空理由、重复/超过 5 个候选、旧 fingerprint、query
漂移、伪造 ID 或 raw operation 都整体失败，不部分解析。0 候选由仓库生成固定
`HOST_PRODUCT_SELECTION_EMPTY`，不采用模型自写 operation/gap；1 候选才 describe；多个候选按
catalog_ref 排序后复用 `MULTIPLE_INTENTS`，不读理由文本、不猜 top-1。

来源隔离不是字符串 allowlist：仓库从当前目录为每个 ref 重建 `gravity.host-source.v1` 的
`sdk_contract/instruction` record，复用 `source_for_plan/expect_sdk_source/source_value` 校验完整
`catalog_sha256 + identity + identity_kind`。宿主响应不能提交来源表，更不能提交 operation/path/Plan
控制字段。单选写产品只返回原 card/preview 交接，测试把 transport 写入口设为失败并证明请求计数 0；
真正 Plan 后续仍必须走 `execute_host_plan` 的 user object/destination 与两步 authorization 边界。

**development 实测：**默认臂在最终代码上实际运行一次，严格保持 recognizer
`260/336`、参数 `209/209`、离线终点 `53/74`、恢复 `5/5`、selection/terminal `pass^4`
`260/336、53/74`、安全 `PASS/0`。一次干净宿主调用只见匿名 336 题与当时的 98 项紧凑目录，未使用
tool/file/repository 事件；完整响应先逐题通过新合同，再由原 evaluator 得到 **327/336**、参数
`255/255`、离线终点 `74/74`、恢复 `5/5`、安全 `PASS/0`。同一选择锁在补入 `app.list` 产品卡后的
最终 99 项目录上重新绑定 fingerprint、逐题重验并离线重放，仍为 **327/336**；四 trial 是同一锁的
确定性 replay，不能冒充四次独立模型稳定性。

| 层 | recognizer 默认 | 宿主合同有效选择 / 最终锁重放 |
| --- | ---: | ---: |
| 首次产品选择 | `260/336` | **`327/336`**（`+67` / `+19.94pp`） |
| 参数可填 | `209/209` | `255/255` |
| 离线终点 | `53/74` | `74/74` |
| 错误恢复 | `5/5` | `5/5` |
| 安全 | `PASS/0` | `PASS/0` |

原干净臂的 9 个 `wrong_product` 在有效新目录实测中全部变为正确：J06 七种问法都选
`analysis.query.spec`，J19 间接目标选精确 workspace SQL gap，J23 间接目标选
`composite:analysis_template`。新的 9 个机械失败是 7 个 J39 abstain 与 2 个候选集机制限制；前者暴露
`app.list` owner 未成卡并促成上述第 90 张卡，后者 J32/J47 实际分别选对
`metadata:table_lineage + CURRENT_TABLE_SCHEMA_PARENT_MISSING` 与
`user_event export + material.asset.fetch`，但冻结 scorer 的 `candidate_selectors` 只登记产品 journey、
不登记 gap journey，按既有逻辑仍为 `wrong_intent_candidates`。本轮按硬约束没有改 scorer/target
registry。补卡后第二次、同 prompt 的宿主输出有一行把单候选声明为 `multiple_intents`；整个 336 行
响应被 `HOST_SELECTION_DECISION_MISMATCH` 拒绝，未部分修正或评分。因此可以证明原 9 个产品边界问题
已在一次有效实测中修复，也能证明 J39 目录身份缺口已在代码中补齐；**不能证明补卡后的新模型分数**。

默认值 `recognizer` 同时锁在 parser、`discover_capabilities` 与回归中；实际不写 `--routing` 的 CLI 仍
返回 `mode=discover_and_describe` 和 `analysis.query.spec:event`，显式
`--routing host_catalog --host-selection` 才返回 `host_catalog_select_and_describe`。是否切默认仍只由
custodian 的一次受保护 paired 运行决定：相对 recognizer 至少 +10pp 且安全零回归才可切；本轮没有
查询受保护集，也没有以 development `327` 代替该证据。

**计数与最终门禁：**operation/stable 保持 **231/222**；canonical 产品卡
`89 + 1 app.list = 90`，但 `app.list` 与一个 operation 共身份，所以完整 selector 仍为
`329 + 0 = 329`；动线保持 `56 = 48 / 1 / 7`。unittest **1146 tests OK**；pytest
**1146 passed / 3092 subtests passed**，均从派发基线 1140 只增不减。compiler **231 operations /
11 manifests**；quality PASS（operations/provenance 231/231、operation literals 57）；文档 **4
passed**、Agent 指南生成器 `--check`、CLI help 与 `git diff --check` 全过。caller-recoverable 审计从
`1223 = A420/B434/C369` 收紧为 **`1225 = A422/B434/C369`**，本线新增 **2/2 A**、B/C 各 +0。
按 diff added lines 复算，`src/gravity_sdk` 实现新增 807 行，测试新增 157 行，比例约
**0.195**，低于三分之一；`agent.py` 为 493 SLOC、`sdk.py` 保持 500，quality baseline 未改。
没有 GitHub、push、tag 或其他对外动作。


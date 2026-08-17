# 语义层、错误消息与发现

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：分析空间/报表设置只读、text-to-SQL 调研、错误消息分档、原生 AI 摸底、派生指标与 semantic_error。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 分析空间 / 报表设置只读 route 裁决（2026-08-15）

**裁决：存在真只读 route，但不存在新的独立产品缺口。** `analysis.setting.query` 仍是修改设置的
mutation；真正的读取分别由既有 dashboard control plane 与 saved-analysis 产品承担。

穷尽性取证先对冻结 `bundle-snapshot.json` 的 375 个文件逐一做 SHA-256，375/375 命中，0 缺失、
0 不匹配；再用当前 parser 离线重放，2,023 个 route occurrence 收敛为 987 个唯一
`(method,path)`，与冻结 inventory 逐条及集合完全相等，76 条未知 method 也包含在内。在 987 条全集
并集搜索 setting/config/conf/preference/option、report/dashboard/kanban/board/chart、
analysis/insight/workspace/space 与中文 UI 词族，得到 378 条宽松超集；沿命中的 owner 前缀展开为
52 条精确命名空间全集：kanban 26、report_config 3、saved report 5、dashboard favourite 8、
confmetric 6、filter_conf 1、base report metric 1、role report metric 2。所有计数来自完整程序断言，
不依赖截断终端输出。

hash-matched bundle 控制流确认四条真读：

- `GET .../kanban/tree/` 在页面装载和 App 切换时读取空间/文件夹/看板树；
- `GET .../kanban/dashboard/detial/` 在选中看板后读取并消费 `ui_config`；
- `GET .../report_config/list/` 在添加图表时读取保存分析列表并消费所选 `config`；
- `GET .../report_config/info/` 在八类 Analysis 页面打开既有引用时读取、解析并恢复表单。

保存动作分别走 `dashboard/edit`、`report_config/update` 和 `kanban/report/setting`；后者提交
`config/name/remark`、继续更新布局并提示“修改成功”，所以不能改判为读。成员 route 只读分享授权，
favourite route 只读筛选收藏，report list/detail 读取另一类业务报表定义，confmetric 读取指标目录；
`POST /report/api/v1/filter_conf/get/` 只有路径词元、无静态调用点，继续不确认。

四条真读均已有 stable contract，Core/CLI/SDK/Plan/Agent 卡分别由 `dashboard_snapshot` 与
`saved_analysis` 交付；Plan 已走窄 family router，`plan_adapters.py` 本轮净增长 0，
`gravity.agent-call-bound.v1` 已声明两类 composite 的调用次数。因此第 64 行从“完全缺失”改为
“不计独立动线（既有稳定读取面重复）”。计数从 `48 = 32 / 0 / 16` 减去一条重复 missing，得到
`47 = 32 / 0 / 15`；operation 仍为 185、stable 仍为 176。

静态确认后只发 1 次生产请求：stable `analysis.report_config.list`，第一页、`page_size=1`，HTTP 200、
`success`、投影列表非空；没有重试、翻页、扩窗、换 App 或猜值。只记录字段/类型形状，fingerprint 为
`b50713e0542c1ac1bc06b57a067e715065f6f952bfa7a1f1ff2cefad4a7a75d6`，App ID 与响应值未落盘。

本单元不修改既有稳定输出。投影边界以本页「投影边界总裁决：全面放开」为准；未来若提出新的
通用设置面，`config`、`ui_config`、`even_report.config`、`remark`、`share_members[].uid`、
create/update user id/name、member name/uname 等已证实字段应全部登记并暴露。未登记字段仍按合同
漂移 fail-closed，正确后续是登记并暴露，不以自由文本或人员信息另设隐私门禁。

**推翻条件**：新的 hash-matched bundle/inventory 证明独立读取 route；上述 GET 控制流变成提交；
或出现一个不能由 dashboard snapshot / saved analysis 回答的独立调用方问题，并取得所需字段的合同
证据。批准 mutation、路径含 read 味词元或发现更多自由文本字段，均不足以推翻本裁决。

## 语义层 / 指标层与 text-to-SQL 调研裁决（2026-08-15）

公开证据支持继续以“上游分析产品 + versioned envelope + 未登记字段 fail-closed”为主干：企业
text-to-SQL 的主要剩余风险是可执行但语义错误，语义层厂商也普遍把 join、metric、dimension 和 ACL
前移。当前路线的真实短板是长尾覆盖，不是主干正确性。后续若扩大覆盖，优先研究“已登记
metric/dimension/filter/grain 的受治理组合层”和带 owner/version/projection 的 verified query；自由
text-to-SQL 只可作为隔离探索层，必须在响应中保留 resolution tier、definition version、generated SQL、
validation 与 allowed claims，不得静默并入现有 Agent 卡的受治理答案。完整证据与反例见
[调研报告](../research/semantic-layer-and-text2sql.md)。

### 调用方语义上下文机制（2026-08-16）

**提案：**保持“SDK 不维护业务语义”的边界，把负责人本应维护的内容放进 workspace 独立子合同
`gravity.semantic-context.v1`；SDK 只提供术语映射、自由文本 instructions、结构化 exclusion、
verified question→stable read operation input 的 schema、加载、精确引用校验和 Agent 消费。工作底稿位于
ignored `tmp/codex/semantic-context/proposal.md`。示例只使用虚构名称；仓库没有新增业务词、业务值、
operation、CLI 参数或执行旁路。

**合同裁决：**term target 支持已登记 composite/workspace recipe/SQL product、stable read operation，
以及本地 metadata catalog 中按 App scope + kind + 物理 name 精确定位的 event/event property/user property/
metric/custom metric。workspace recipe、SQL product 与 operation 在加载时验证；built-in composite 和 metadata
在 Agent preflight 验证，避免 workspace 启动路径反向依赖 Agent/runtime。目录缺失、零命中、多命中和
未知引用统一为 `SEMANTIC_CONTEXT_INVALID/category=local/exit 4`，
不降级 warning。verified query 的完整 input 在加载时按 operation 合同验证，命中后原样进入现有
`run` Plan node；没有字符串插值，也不生成 App、日期、filter value 或其他业务值。

**裁决方向：**verified query 仅在规范化整句精确相等时硬绑定，在既有 `MULTIPLE_INTENTS` 与 caller
exclusion 门禁之后优先于普通 term 和单个目录候选；term/synonym 是正向证据，先和现有
权威候选及集中多意图结果合并裁决。一个问句命中不同 caller targets，或 caller target 与仓库权威
候选不同，均返回 `MULTIPLE_INTENTS`。product term 以“原问句 + 已登记 selector”复用原 recognizer；
目标若被既有负向约束拒绝，返回 `SEMANTIC_CONTEXT_TARGET_REJECTED` 而不恢复候选，故仓库负向约束优先。
调用方 exclusion 命中同样形成 gap 并阻止 raw fallback。实现没有修改 `agent_intent_routing.py` 或任何
recognizer 关键词表。

**来源与兼容：**真正由 term/verified query 选出的候选复用
`description_origin=caller_workspace` 和 `gravity.result-source.v1` 的
`caller_defined/caller_responsible`；匹配说明使用独立版本 `semantic_context` 子合同，不增加第三套
provenance。无 `[semantic_context]` 时字段缺席，`composite:business_pulse` canonical Agent JSON 保持
4442 bytes、SHA-256 `22b15703ecf1604065a05aa3c8609c298eb8a73b0f67db49c126050d32bc15a6`。

**official：**本轮不纳入。`result_source` 是责任/验证层级而非排名；现有系统没有不影响歧义保护的
全局 official 优先级判据。精确复用走 verified query，同义词继续保留在集中裁决中；待出现可证明的
同 selector 多定义优先级问题后再单独设计。技术债清单已复核，本机制下沉到独立 workspace/Agent
模块，没有触发现有条目的退出条件，也没有新增可由当前源码证明的结构债。

本项是横切发现机制，不新增产品动线或结果 envelope，计数为
`48 + 0 = 48`、`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`；operation 为
`185 + 0 - 0 = 185`，stable 为 `176 + 0 - 0 = 176`。生产 HTTP 请求 **0 次**，无重试、翻页、扩窗
或换 App。

## 可恢复错误消息分档与首轮升级（2026-08-15）

本轮把“对外可恢复错误消息全集”固定为源码中所有显式抛出的 caller 类结构化错误起点：
`InputValidationError` 及其 `ParentRequiredError`、`PlanRecipeError`、`PlanValidationError`、
`SemanticRejectedError`、`SqlValidationError` 子类，以及 `UnknownOperationError`；同时沿返回注解纳入
`input_error` / `invalid` 等窄 helper 的所有抛出点。转发已有错误的 `ErrorDetail.create` 不重复计数，
upstream/local/contract 错误不属于调用方替换输入即可恢复的集合。`scripts/audit_actionable_errors.py`
完整解析 `src/gravity_sdk/**/*.py`，按 `(source, line)` 断言无重复，并断言 A+B+C 等于全集；
`tests/test_actionable_error_audit.py` 固定当前全集和分档，计数不依赖终端是否截断。

基线 `ac03a0f` 的 **974** 个起点为 `A=0 / B=422 / C=552`。首轮升级 56 个，其中
`36 B→A + 20 C→A`，所以当前为 **`A=56 / B=386 / C=532`**，推导为
`0+36+20=56`、`422-36=386`、`552-20=532`，总数仍为 974。升级覆盖 Analysis / Segment
紧凑 spec 的类型、长度、范围、enum、未知字段、日期关系、跨字段约束，以及已证实的 Segment preset
和 Property acquisition-ID 拒绝；不改 code、category、exit code、envelope、operation 或校验宽严。

实际值先经过与 CLI JSON 边界相同的 credential sanitizer；token/cookie/password 等键被删除，Bearer、
JWT 和凭据赋值被替换。条件 `values`、原始请求/响应及其他可能承载用户级值的字段没有新增回显；
`scalar_values` 因而仍留在 B。候选显示上限取 **N=20**：现有普通 enum 和 spec 顶层字段可完整显示，
最长常见集合仍能留在 500 字符消息预算内；超过 20 时必须同时给 `showing N of total` 和可执行发现
命令。本轮 25/29 项 Segment operator 通过
`gravity analysis segment evaluate --spec-schema` 发现完整集合；动态 event/property 候选不内嵌，分别
交给 `gravity metadata events ""` 与 `gravity metadata properties ""`。

剩余 B/C 不批量猜值：B 的主要缺口是旧 helper 只有格式化后的 message/field、异常现场未把原始值或
候选传入；C 还包含 workspace、prober、合同装载与内部不变量错误，部分不是字段替换问题。后续只在
owner 文件因真实调用方错误而被触及时，把能证明安全的原始值和权威候选传到消息边界；不得用栈帧
反射抓局部变量，也不得为提高 A 档比例回显凭据、filter values 或原始上游错误。该消息升级不改变
`docs/analysis-journeys.md` 的动线完成度，operation 仍为 185、stable 仍为 176；本轮 0 次生产请求。

## 字段策略层错误消息升级（2026-08-15）

**提案：**承接 `8a27f87` 的 sanitizer、`actual_value` / `allowed_values` 和 N=20 上限，按 Agent
最常撞到的筛选条件、事件、分群、控制、明细、metadata 顺序，把原始调用值和当前校验现场已有的
权威 enum / live metadata 候选传到结构化错误；拿不到安全原值时停在 B，不回显 filter/condition/
data-list values 或上游异常正文。`models.py` 与 `plan_validation.py` 只在六文件集群完成且质量门禁
仍有安全余量时继续，不以升级条数替代单条可恢复性。

**结论：六个高频字段策略文件的 176 条已全部脱离 C 档，`models.py` 与 `plan_validation.py`
留待后续 owner 单元。** 逐文件固定审计如下：

| owner 文件 | 升级前 A/B/C | 升级后 A/B/C | 净迁移 |
| --- | ---: | ---: | ---: |
| `_field_policy_conditions.py` | 0 / 0 / 45 | 39 / 6 / 0 | 39 C→A，6 C→B |
| `_field_policy_event.py` | 0 / 0 / 26 | 26 / 0 / 0 | 26 C→A |
| `_field_policy_segment.py` | 0 / 0 / 35 | 35 / 0 / 0 | 35 C→A |
| `_field_policy_controls.py` | 0 / 0 / 27 | 19 / 8 / 0 | 19 C→A，8 C→B |
| `_field_policy_detail.py` | 0 / 0 / 25 | 25 / 0 / 0 | 25 C→A |
| `_field_policy_metadata.py` | 0 / 0 / 18 | 18 / 0 / 0 | 18 C→A |
| **本集群合计** | **0 / 0 / 176** | **162 / 14 / 0** | **162 C→A，14 C→B** |

全仓计数可复算为：`A 56 + 162 = 218`，`B 386 + 14 = 400`，`C 532 - 176 = 356`，
总数仍为 **974**。审计抛点没有因拆分分支而增减；code、category、exit code、envelope、operation、
请求形状和校验宽严均未改变。三个 owner 文件一度触发 SLOC 500 门禁，最终只压缩新增消息排版，
没有移动或重构校验函数，质量 baseline 未改且门禁恢复 PASS。

14 条 B 的原因分两类：6 条是 condition/group/filter map 容器或值类型错误，8 条是 account/dashboard/name filter、
`filtering`、`data_list` 的值错误；这些值可能承载用户级标识、业务筛选值或整行输入。虽然投影边界已
全面放开，错误会进入日志、监控和告警并产生比查询结果更宽的复制面，因此只回显字段路径、结构要求、
安全的 item count / key/type 摘要和权威发现动作，不回显原值。metadata loader 捕获的上游异常正文
同样继续丢弃；可安全观察的 operation、status、envelope type 和候选集合仍进入消息。所有实际回显
均经过共享 credential sanitizer；长候选使用既有 N=20 截断和真实 CLI/raw-operation 发现命令。

`models.py` 仍为 `0 / 0 / 28`，`plan_validation.py` 仍为 `0 / 35 / 22`。前者是 1079 行的通用合同
模型热点，后者的 57 个 helper 抛点横跨完整 Plan 图、预算、binding 与 call-bound 语义；继续处理会
从本轮高频字段策略扩到低频通用结构面，因此按优先级停止，不把它们包装成已完成。该升级不改变
`docs/analysis-journeys.md` 的动线计数；operation 仍为 185、stable 仍为 176；本轮 0 次生产请求。

## Agent 渐进发现与生成任务指南（2026-08-16）

**提案：**新增一个独立、只读的 `gravity agent-catalog` 三段式发现面，按既有 `domain` 做
`categories → category <domain> → describe <selector>`；第一层只给数量和下钻 argv，第二层以有界
selector 摘要分页，第三层复用 composite card 或 manifest-derived operation card。保留 `gravity agent`
原有 parser、query 和 envelope 完全不变。类别不纳入 workspace recipe、SQL product 或 cached metadata：
它们依赖调用方 workspace 或本地缓存，硬列入固定目录会形成第二套事实源。

**结论：**`gravity.agent-catalog.v1` 仅派生现有 composite inventory 和 compiled manifest，未新增
operation、参数、执行路径或 MCP surface。`scripts/generate_agent_skills.py` 从 Agent card、Analysis
Spec contract、period-compare envelope 与公共 exit-code contract 生成 4 篇任务指南和十分钟路径；测试
逐字比较重生成文本。覆盖事件趋势、同 Spec 跨期比较、capability gap 恢复与首次路径，选择依据是它们
对应已闭环动线的高频起点和一个所有调用方都需处理的失败终点，不以 Skill 数量为目标。

十分钟路径离线实走到 schema/compiled preview 成功；真实业务结果仍被三个事实性前置条件阻塞：没有
调用方可用的登录、workspace App，或已登记的物理事件/指标。它们不是可安全猜测的 SDK 输入；路径明确
列出而不伪称已取到业务结果。计数为 `48 + 0 = 48`、`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`，operation
`185 + 0 = 185`、stable `176 + 0 = 176`；本轮生产 HTTP 0 次。

新增 catalog 参数校验的 7 个 caller-recoverable raise sites 进入既有 actionable-error 审计，
其中 `B + 3`、`C + 4`：当前可复算总数为 `974 + 7 = 981`、`A=218`、`B=400+3=403`、
`C=356+4=360`。这些是新 CLI 的 `limit`、`offset`、category、selector 和 action 的本地输入错误；
不改变既有错误 code/category/exit 语义，也不放宽审计判据。

## 非推广/素材未覆盖读路由逐条复核（2026-08-16）

**提案：**以 Census 的 343 条 `uncovered_read` 为固定分母，先按唯一 path 排除 188 条已判定数据阻塞的
promotion/material draft；对余下每条只用保存的 Census、hash-matched frontend bundle、manifest、合同与
既有 evidence 做互斥离线分类。只从“分析师会主动问”的可取证类按完整动线价值排序，在总计 40 次生产
请求内依次取证；缺父值、已证值域或已有同租户空样本即在 transport 前停止。只有成功非空合同足以闭合
Core / CLI / SDK / Plan / Agent 五面时才实现，否则保留 fail-closed。

**结论：分母可复算且没有快照漂移。** 148 条 promotion 加 40 条 material draft 是 188 个唯一 path；
`343 - 188 = 155`。187 条与 Census 的 `(method,path)` 精确一致；唯一差异
`promotion.promoted_object.list` 是 draft POST / Census UNKNOWN，同 path 只排除一次。离线逐条初判为
`18 已有等价覆盖 / 89 UI 辅助 / 4 mutation / 18 有价值且证据可自取 / 21 有价值但阻塞 / 5 无法判定`。
阶段二按实时事件、数据表 schema/版本、巨量项目素材表现、AppRank、点击监测、兜底 eCPM、自有多维模板
详情的顺序复核 18 条，最终全部因明确空、semantic error、缺合法父值或缺已证值域转为阻塞；最终分类
为 **`18 / 89 / 4 / 0 / 39 / 5 = 155`**。

生产总账为 **10 次 HTTP**：2 次 `app.list` 均 HTTP 200 非空目录；4 次 AppRank app/publisher public/
tenant 根目录均 HTTP 200 semantic error；`metadata.data_table.list`、两条 promoted-object 点击监测目录、
`report.multidim.template.mine.list` 均 HTTP 200 语义成功空。没有重试、翻页、扩日期窗、换 App 或猜业务
值；其余 route 在请求前 fail closed。静态控制流只新增 10 条 AppRank/data-table 精确 read confirmation，
不以此替代响应合同。没有 route 晋升，五面实现、新 caller-recoverable error 与 A 档新增均为 0。

因此本线相对派发快照的 operation、stable、Census 与分析动线净变化均为 0；随后
`analysis.default_val.list` 从原六类表的“UI 辅助路由”晋升，D35 归因表现也完成闭环。五线合并后
在五线合并完成时，值统一为 operation 187、stable 178、Census callable covered route 174、
`uncovered_read=341` 与 `48 = 36 / 1 / 11`；Segment mutation 合入后的现状统一见本页顶部。
真正尚缺证据的分析 route 在历史 155 条中为
39 条，另 5 条仍无法判定；下一轮的最小动作不是重复当前租户，而是由有对应数据的租户提供一个非空
父项，或由服务端合同补齐 project-material、AppRank rank/trend、fallback eCPM 所需值域后各做一次最小读取。

## 引力原生 AI 事件分析对话摸底（2026-08-16）

**提案与范围：**只回答 census 中 AI conversation/message route 是什么；先以 hash-matched bundle 做
零业务请求静态取证，只对静态无法证明的真实 envelope 做一次通用问法在线验证。不新增 operation、
adapter、recognizer、评测臂或产品行为，不读取留出集，也不改变现有排期。工作底稿和 value-free HTTP
receipts 位于 ignored `tmp/codex/gravity-native-ai/`。

**裁决：窄范围“重叠”，不是聊天壳，也不是已验证捷径。** `Event-BKh0ym6c.js` 当前公开文件与 census
快照同为 113,757 bytes、SHA-256
`352233b7fb6ea74ec6b0c86e304dda84782669d52af1c01c7a84014eaa30e1a8`。前端先以问题作 title 建会话，
再发送当前 App、会话 ID 和同一问题；成功分支读取 `backup_measure_json`，一键回填事件/自定义公式、过滤、
分组、日期与图表类型。气泡只显示固定文案，不显示模型自由文本、结果数据或报表引用。conversation/message
两个 list loader 存在但未调用；没有 SSE/WebSocket/前端工具调用或已观察多轮。

唯一问法“最近 7 天的事件趋势”使用 catalog 首个 App 上下文。生产 HTTP 共 **4 次**：认证、`app.list`
第一页 1 项、conversation create、message create；全部 HTTP 200、attempt 1，无重试、翻页、扩窗或换 App。
最后响应为 `data: []`，没有 `backup_measure_json`，按纪律不换问法追非空。因此真实成功定义、两个 list
合同、空结果原因、schema/version/provenance 和服务端内部模型/工具链仍未证明。

若未来把它列为现有 recognizer、embedding/hybrid、结构化 LLM selector 之外的第四候选臂，输出仍须
经过确定性 schema、物理引用、日期/operator 与失败分类校验，并在同一冻结 unseen 题集 A/B；本轮没有
实施或批准该选项。本线相对派发快照的动线、operation 与 stable 净变化均为 0；合入默认值字典闭环后，
该单元合入默认值字典时为 `48 = 34 / 0 / 14`、operation 186、stable 177。技术债清单已复核，无条目达到退出条件，
也没有新增结构债。
完整请求/响应结构、前端消费和未决见[专项报告](../research/gravity-native-ai.md)。

## 派生指标与声明集合对账（2026-08-16）

**提案：**在已有结果 envelope 上纯加法增加独立 `gravity.derived-metrics.v1` 子合同；原顶层
`schema_version/status/ok/result_source/data` 全部原样保留。SDK 只实现不需要字段含义的
`ratio/share/change/reconcile`，调用方通过 `gravity.derived-metrics-spec.v1` 声明 rows_path、列、结果名、
时期标签、对齐键和 expected 集合。工作提案位于 ignored
`tmp/codex/derived-metrics/proposal.md`。本单元不新增 operation、分析框架依赖或生产请求。

**算子裁决：**ratio 是逐行两列相除；share 是一列占该输入完整行集总和；change 同时返回绝对差和
相对变化，并复用时期比较的精确身份对齐与 baseline-zero 不可算语义，不按行位置猜配；reconcile
返回 present/missing/unexpected。未纳入 sum/average、滚动窗口、加权比率、单位换算或留存算子：
前两项不属于本轮闭环且会扩张聚合空值政策，后几项必须知道排序、权重、单位或业务含义。
share 最贴近业务边界，因为“总体”选择会改变含义；实现因此要求调用方显式选择 rows_path，并在任一
缺失/非法行或上游 partial 时拒绝用可见行重建总量。

**数值与状态：**标准库 `Decimal` 精确消费整数和 decimal string；float 以其十进制文本消费并产生
`BINARY_FLOAT_INPUT`。除法按调用方 `decimal_places=0..28` 和 half-even 舍入，以 decimal string 输出；
发生舍入时产生 `PRECISION_ROUNDED`。金额类整数按最小单位进入时全程精确，不先转 binary float。
分母零为 `not_calculable/denominator_zero` 且没有 value；缺列为
`not_calculable/missing_column + missing_columns`，与零、null 和 invalid_number 分开。上游 partial 时
子合同整体 partial，ratio/change 数值标 `calculated_from_partial`，share 以
`upstream_partial_total` 拒算，reconcile 保留三分但 `missing_is_definitive=false`。

**动态说明逐条裁决：**SDK 可生成上游 partial、分母零、缺列、null/非法数、非 object 行、share
总量不完整、change 缺边/重复键/区间外行、reconcile 未分类/重复 observed、float 输入和 Decimal 舍入；
这些完全由输入形状或算术事实决定。SDK 不生成“公式选对了”“总体是目标人群”“两期业务可比”
“单位或币种兼容”“expected 是权威全集”“unexpected 是未知业务项”等说明；它们必须由调用方字典
或审核给出。warnings 是稳定 code/count/message，notes 只做人读摘要，自动化按 code/status 分支。

**四面与语义衔接：**CLI 为离线 `gravity derive --input`，SDK 为 `derive_metrics(source, spec)`，Plan
复用 `composite/name=derived_metrics` 并经 Analysis family router 接入，`plan_adapters.py` 净增长 0。
Agent 对未声明公式的 rate/ratio/share 意图返回 `DERIVED_METRIC_BINDING_REQUIRED`，不搜索 raw
operation 或猜公式。`gravity.semantic-context.v1` 纯加法接受 `derived_metrics` 声明；加载时验证完整
spec，命中后卡片预填 caller spec、只缺 source，补入 source 后同一 Plan 节点可真实执行。派生子合同
和 Agent/Plan 来源均为 `caller_defined/caller_responsible`，同时在 `upstream.result_source` 保留输入
来源事实。

这是已有结果上的调用方派生便利面：权威表由 51 行增加到 52 行，并作为第 4 条不计项保留，故
产品动线仍为 `48 + 0 = 48`；状态为 `34 / 0 / 14 + 0 / 0 / 0 = 34 / 0 / 14`。operation 为
`186 + 0 = 186`、stable 为 `177 + 0 = 177`。生产 HTTP 请求 **0 次**，无重试、翻页、扩窗或换 App。
本分支开工时 actionable-error 测试固定 **1022 = A218/B434/C370**；本单元新增 core spec 与 Plan
output_fields 两个 caller-recoverable 抛点，均含字段路径、安全实际值和可执行修正动作，故为
`1022 + 2 = 1024`、`A 218 + 2 = 220`、`B=434`、`C=370`，新增 A 档为 2/2。
## `semantic_error` 判定与 evidence 审计（2026-08-16）

**提案与分母。** 工作提案与程序化明细位于 ignored `tmp/codex/semantic-error-audit/`。仓库中有
787 份 evidence 命中字符串 `semantic_error`，但其中 460 份只含统一 schema 的 `semantic_errors`
容器键，实际 `conclusion=semantic_error` 为 327 份。三分法为
`5 明确误判 + 0 明确真错误 + 782 信息不足 = 787`；信息不足可复算为
`322 个缺判据的真实标签 + 460 个容器键命中 = 782`。其中 58 个标签虽可由 shape 与旧实现反推为
旧 code predicate 命中，但原始 code/msg 已丢失；拿旧判据证明旧判据正确属于循环论证，仍归信息不足。
5 份明确误判都是 HTTP 204/null body，分属
`report.report_custom_get.calc_total`、`promotion.kuaishou.developer.list`、
`promotion.alipay.batch_options.query`、`promotion.alipay.campaign_option.list`、
`promotion.tencent.user_organization_authentication.get`，故“误判最多”是五项并列各 1。

**根因与修复。** executor 的字符串 `semantic_error_rules` 默认按 truthy 执行，prober 的旧
`semantic_success()` 也在 code 属成功集合后直接拒绝任意非空 `extra.error`；合同 loader 只解析规则，
不另做语义区分。现在共享判定只把已有 evidence 登记的精确值 `无数据` 解释为 explicit empty，且要求
成功 code 与业务 data 确实为空；HTTP 204/null 也归明确空。仓库 787 份旧 evidence 保存的
`extra.error` 原值为 0 个；已完成 attribution 线的 committed evidence 只观察到 `无数据` 1 种/1 次，
没有证据登记任何同义表达。其他非空值（包括形似同义词的 `暂无数据`）继续 fail-closed 为拒绝。

**今后 evidence。** 每条 probe HTTP observation 新增 `protocol_status`，分别保存上游 `code`、`msg`、
`extra.error` 的存在性和原始标量值，并保存本地离散 classification；异常结构只存类型、truthiness 和
`value_persisted=false`。这些是决定整个响应能否进入业务投影的协议层状态，不是 `data` 下的业务响应值；
`privacy.values_persisted=false` 仍准确表示未持久化业务数据值。

**台账影响。** 5 份 HTTP 204 误判没有单独支撑当前分析动线表的缺失理由；D35 则由 attribution
补充 evidence 独立证实旧 `semantic_error / 缺服务端证据` 理由无效，F40 对它的依赖随之失效，故
`analysis-journeys.md` 共改写 2 行为“旧判定基于分类器误判，待重新取证”。本单元不重探测这些动线，
不新增或提升产品：`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，operation/stable 仍为
`185 / 176`。生产 HTTP 共 1 次：`promotion.kuaishou.developer.list` 的受控 GET 返回 HTTP 204/null body，
`protocol_status.classification=explicit_empty`，无重试、翻页、扩窗、换 App 或 credential exchange；
运行时 `request_limit=1/attempts=1`。该 operation 不属于上述两条待重新取证动线。

## C 级错误补 path 与 remedy（2026-08-17）

本轮只改调用点信息面：给缺 path 的 raise 补 `field=`，给缺 remedy 的消息补可行动的
`must` / `allowed` / `next_action` / `remove` / `run \`gravity`。未改
`scripts/audit_actionable_errors.py` 的三个布尔、判据、scope，也未改 category /
code / retry / 退出码。

**改前 / 改后：** `1225 = A833 / B23 / C369` → **`1225 = A850 / B375 / C0`**。
总数不变。C −369、A +17、B +352。17 条升 A 来自 `plan_validation.py` 等处补了
真实调用值（`actual_value(...)`），不是类型名冒充。原 `#164` 的 23 条 B（筛选值、
未命中 ref、未绑定 workspace 的 app）仍为 B，未回显。

**重新统计构成（动手前）：** C 369 = 缺 path 110 + 有 path 无 remedy 259。
杠杆：`invalid` 22、`input_error` 95、`_input` 27、`_input_error` 22、
`_date_error` 6、`_app_id_error` 2，以及 `plan_validation.py` /
`_field_policy_shared.py` / `models.py` 等集中文件。审计只看调用点 AST，
改 helper 函数体不够，必须让调用表达式带上 `field=` 或 remedy 标记。

**主动没做：** 不为刷 A 回显筛选值、未命中对象标识、未绑定 workspace 的 app；
不为没有安全实际值的站点编造 `actual value: <type>`。动线总表 `56 = 50 / 3 / 3`
未改，由合并时对账。

门禁：unittest 1179、pytest 1179 + 3114 subtests、compiler 235 / 11 manifests、
quality PASS operations=235 / provenance=235、usability development 首选
`251/336`。生产 HTTP 0。`git diff -- scripts/audit_actionable_errors.py` 为空。

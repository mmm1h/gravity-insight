# 路线图

本页是当前开发的唯一权威排期依据，取代历史上不进版本控制的临时目标文件。
盘点快照：`dev@8fd278e`，2026-08-13。

## 目标

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**

衡量单位是**分析动线**，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达，结果是带 `schema_version` 的 envelope
和离散 `result_source` 来源声明（空/部分失败/能力缺口可区分）；请求未知字段、响应字段消失/
类型变化 fail-closed，新增响应字段放行但留下结构化审计。

## 现状

当前从仓库产品入口与 stable operation 正向交叉反推 49 条产品动线：**已闭环 37 / 部分闭环 1 / 完全缺失 11**；
另有 2 条 legacy/SDK 便利面、1 条重复能力审计行和 1 条已有结果上的调用方派生便利面保留，
但不计产品动线。表格 53 行减去 4 条“不计独立动线”得到 49 条。合并前 dev 的现状为
`48 = 36 / 1 / 11`；“从分析结果或规则创建并管理可复用分群”是调用方能独立完成、并产出上游分群
对象的任务，不与“查看已有分群详情/成员”合并，因此净增 1 条已闭环动线：
`48 + 1 = 49`、`36 / 1 / 11 + 1 / 0 / 0 = 37 / 1 / 11`。
operation 为 `187 + 7 = 194`、stable 为 `178 + 7 = 185`。部分闭环的 Analysis 导出只关闭了单用户事件子类；11 条完全缺失里
多数是请求、响应或非空证据阻塞；字段隐私不再是阻塞项。
逐条状态、四面入口、调用次数和证据阻塞以[分析动线台账](analysis-journeys.md)为准；旧
`21/14/6` 快照的逐条底稿未进入版本控制，无法复算，已停止作为排期事实。

`draft` 候选数量不等于排期数量：17 项候选归并进台账动线或按明确非目标排除，不按 operation 单独排期。

### pytest 迁移第三轮（2026-08-16）

**提案：**把第二轮残留在四个混合测试模块中的 46 个模块级 `test_*` 全部纳入
`unittest.TestCase`，不改断言、三引号字符串或生产源码。转换前先固定全仓测试定义名集合、四文件
三引号 token 和 pytest 收集清单，转换后再把 unittest 与 pytest 的实际父测试集合做双向差集；同时
审计参数化、动态生成、收集 hook、非 TestCase 测试类、异步/嵌套测试和非标准文件命名。

**判定：**四文件残留按 `4 + 11 + 27 + 4 = 46` 全部迁移，`grep -cE "^def test_" tests/*.py`
逐文件计数之和为 0。Probe semantics、Prober 和 Resolver 的剩余方法并入同领域现有 TestCase；为保持
模块 helper 的作用域和定义顺序，三个类整体移到 helper 之后。OpenAPI 文件已有类只验证仓库合同，
其余四项验证 draft/runtime 且需要临时目录，因此新建 `OpenApiProberTests`，不混合两类生命周期。

转换前后全仓测试定义名集合均为 1039，缺失和新增名称均为 0；四文件所有显式断言与
`pytest.raises` 的 AST 差异为 0。唯一三引号 token 位于 `test_resolver.py`，转换前后长度均为 155，
SHA-256 均为 `253d63666ca27f2a07562fec337efafd60844e097575556a257978341e16f86f`。unittest 与
pytest 的实际父测试集合均为 1054，双向差集均为空；仓库没有 `conftest.py`、pytest 收集配置或
`PYTEST_ADDOPTS`，也没有参数化/收集 hook、动态测试、异步/嵌套测试或非 TestCase 测试方法残留。

完整 unittest 为 `1008 + 46 = 1054`，无差额；完整 pytest 为 `1054 passed, 2842 subtests passed`。
pytest 父测试由 1073 减少 19，可复算为三个参数化函数原有 22 个 case 收敛为 3 个父方法，
即 `1073 - (22 - 3) = 1054`；22 个 case 全部转为 subTest，所以 subtest 由
`2820 + 22 = 2842`。quality、compiler、文档测试、CLI help 和 diff check 全部通过。本轮不改产品
源码、operation、stable 或分析动线，不新增 caller 可恢复错误点；新增错误点 0、新增 A 档 0。
生产 HTTP 请求 **0 次**。

### pytest 迁移第二轮（2026-08-16）

**提案：**保留首轮 15 个测试文件与 120 个 `unittest.TestCase` 方法的迁移结果，只修转换造成的
行为差异；以迁移前 `HEAD` 为基线程序化对账测试名、参数案例、fixture 生命周期与全部字符串字面量，
并同时完整运行 unittest/pytest 两套主门禁。工作底稿继续位于 ignored
`tmp/codex/pytest-migrate/`，其中生成的测试副本改用 `.py.txt` 后缀，避免无参数 pytest 把底稿重复收集。

**判定：**并发 receipt 测试的临时目录仍是每个测试独立创建，失败不是共享目录或时序抖动；转换器
把三引号中的子进程源码一并缩进，导致首个子进程在写 ready 文件前以 `IndentationError` 退出。修复只
恢复源码字面量和方法体缩进，双方当前 receipt 必须同时存在的原断言未变。相同审计另发现并修复一处
中文 fixture 错误转码和一处被缩进的 TOML 字面量，并把跨模块 helper 边界误缩进、因而不再收集的
42 个原 pytest 测试恢复为模块级测试；它们不再迁入 TestCase，所以 unittest 总数仍保持 1008。

15 个文件迁移前后的 162 个测试名集合完全一致，隐藏测试定义为 0，不含 `TestCase` 的目标测试文件为
0。定向批次为 `181 passed, 62 subtests passed`；完整 unittest 为 1008、完整 pytest 为
`1073 passed, 2820 subtests passed`。pytest passed 从迁移前 1130 减少 57，可复算为 5 个参数化函数的
62 个案例改为 5 个父测试与 62 个 subTest，即 `1130 - (62 - 5) = 1073`，没有丢失案例。quality、
compiler、文档测试与 diff check 全部通过。本轮不改产品源码、operation、stable 或分析动线，不新增
caller 可恢复错误点；新增错误点 0、新增 A 档 0。生产 HTTP 请求 **0 次**。

### 六条“明确空”多 App 复验（2026-08-16）

**提案：**先读一次稳定 `app.list` catalog，只使用其实际返回的 App；对确有 App 输入的候选逐 App
发一次最小第一页/无分页请求，首次非空即停。同一 `(App, operation)` 不重试，不扩日期窗、不翻页、
不猜报表名、平台、事件名或筛选值。没有 App 输入且只依赖账号/公司认证上下文的 route 只发一次。
工作提案与值无关的运行底稿位于 ignored `tmp/codex/empty-recheck/`；父值和 App 标识没有落盘。

**请求账本：**catalog 返回 7 个均可绑定 App，0 个无法解析或未试。生产业务 HTTP **22 次**，
认证 HTTP 0 次；全部 HTTP 200，失败、重试、翻页、扩窗和 429/5xx 均为 0。日期型请求只使用
`2026-08-16` 当天窗口。`catalog#N` 只表示本次 catalog 顺序，不持久化 App ID 或名称。

| # | 上下文 | operation | HTTP | 结果 |
| ---: | --- | --- | ---: | --- |
| 1 | catalog | `app.list` | 200 | 非空，7 个可绑定 App |
| 2 | account | `report.masterkey_report_group.list` | 200 | 空 |
| 3 | account | `report.report.list` | 200 | 空；无父项，detail 未发送 |
| 4 | account | `report.shared_to_me.list` | 200 | 空 |
| 5 | account | `report.subscribe.list` | 200 | 空 |
| 6 | account | `app.project.list` | 200 | 空 |
| 7 | `catalog#1` | `report.media_report.list` | 200 | 空 |
| 8 | `catalog#1` | `analysis.realtime_event.list` | 200 | 空 |
| 9 | `catalog#1` | `analysis.default_val.list` | 200 | 空 |
| 10 | `catalog#2` | `report.media_report.list` | 200 | 空 |
| 11 | `catalog#2` | `analysis.realtime_event.list` | 200 | 空 |
| 12 | `catalog#2` | `analysis.default_val.list` | 200 | **非空；立即停止该 operation 枚举** |
| 13 | `catalog#3` | `report.media_report.list` | 200 | 空 |
| 14 | `catalog#3` | `analysis.realtime_event.list` | 200 | 空 |
| 15 | `catalog#4` | `report.media_report.list` | 200 | 空 |
| 16 | `catalog#4` | `analysis.realtime_event.list` | 200 | 空 |
| 17 | `catalog#5` | `report.media_report.list` | 200 | 空 |
| 18 | `catalog#5` | `analysis.realtime_event.list` | 200 | 空 |
| 19 | `catalog#6` | `report.media_report.list` | 200 | 空 |
| 20 | `catalog#6` | `analysis.realtime_event.list` | 200 | 空 |
| 21 | `catalog#7` | `report.media_report.list` | 200 | 空 |
| 22 | `catalog#7` | `analysis.realtime_event.list` | 200 | 空 |

**六条判定：**媒体报表与实时事件目录为 **(a)**：7/7 App 均空，当前租户确实没有这类数据。
默认值字典为 **(b)**：第 1 个 App 空、第 2 个 App 非空，旧结论是在首个空 App 停止造成的假阴性。
报表目录、订阅和 App 项目为 **(c)**：这些 route 的固定 path/body 没有 App 输入，认证 header
只提供账号/公司上下文；重复绑定 App 不会改变请求，因此其空是账号级事实。

**闭环与方法修正：**非空响应观察到 `data.cocoscreator[]: string`，与既有 shape-only 证据中的
`data.api[]: string` 合并后形成闭合 allowlist。`analysis.default_val.list` 从 draft 晋升 stable，
Core、`gravity analysis defaults --app`、SDK `analysis_default_dictionary()`、Plan
`analysis_default_dictionary` 与同名 Agent composite 共用
`gravity-insight.analysis-default-dictionary.v1`；两键全部暴露，第三键按 additive drift fail-closed，
卡和 Plan 节点声明 `gravity.agent-call-bound.v1`。这次复验再次证明“首个 App 明确空”不能推出
租户级缺失：凡请求含 catalog 可枚举的 App 输入，缺失结论必须枚举完 catalog 或在首个非空处停止。

台账净变化为 `48 = 33 / 0 / 15 + 1 / 0 / -1 = 34 / 0 / 14`；operation
`185 + 1 = 186`，stable `176 + 1 = 177`。实现没有新增 caller 可恢复错误抛出点，故新增错误点
`0`、新增 A 档 `0`。技术债复核没有产生新条目：Plan 复用既有 Analysis family router，Agent
保留普通 `unknown_app=3` 下界，没有把无 revision/ETag 的在线两次解析扩张到本动线。

### 输出交给 LLM 的内容边界（2026-08-15）

**提案：**保持投影全面放开，把 stable manifest、产品台账和源码中的 versioned envelope 构造点做
离线程序化全集；逐类追踪 `data/request/error/warnings/diagnostics/log/receipt/Agent card`，只修业务值与
我方说明文字混合及非标准 JSON，不做内容检测、评分或字段过滤。工作提案与完整生成结果位于 ignored
`tmp/codex/consumer-safety/proposal.md`、`inventory-final.json`。

**盘面结论：**`scripts/consumer_output_inventory.py` 从编译后 manifest 取得 176/176 个 stable
operation 及全部投影路径，并从分析动线权威表取得 51 行产品/兼容记录。所有 operation 的
`request.inputs` 和 `data` 都划为不可信内容区；175 个响应合同允许潜在文本，42 个含动态字段或
opaque JSON。现有合同不登记每个字段的写入主体或完整标量类型，因此不能证明更窄的“确定由最终用户
填写”全集；字段名启发式不作为安全边界。调用方使用完整上界，而不是等待本仓库猜测 provenance。

**自然语言审计：**没有发现上游业务响应值进入 SDK 的 `error.message`、`next_action`、warning、
diagnostics 或日志；semantic rejection 使用 manifest 固定文案，HTTP/运行 receipt 只含值无关元数据。
Agent live catalog 的名称和值保留在 `items/name/selector/argv` 等结构化位置，没有拼入说明段落。
发现的真实歧义是 workspace recipe 的调用方自定义 `description` 与 operation 的仓库文案共用同名字段；
Find/Agent 卡现增加 `description_origin=sdk_contract|caller_workspace`，不改变 description 原值。

**结构保证：**公共 Insight JSON/NDJSON、入口错误、SQL 与 Census serializer 现统一拒绝
`NaN/Infinity`，仍使用 strict UTF-8 JSON；合成恶意换行、引号和伪标签 round-trip 后值完全相同，
只作为一个 JSON string，不产生尾随结构。该保证解决解析歧义，不消除字符串内容对模型的影响。
`docs/guides/llm-output-safety.md` 给出按 schema/status/code 分支、按内容根拆消息、模型外限制副作用与
审计关联的调用方步骤。operation、投影、请求、错误分类和既有退出码语义均未改变；Agent/Find 仅新增
origin 元数据。

**不能保证：**SDK 不检测或识别 prompt injection，不打分，不隐藏、改写或删除业务值，也不能保证
下游 LLM 不受数据诱导、不调用其他工具或不外传。严格 JSON、结构分离和 origin 元数据只能让调用方
机械识别边界；工具 allowlist、权限隔离、输出目的地控制和高风险动作确认仍必须由调用方实现。
本项 production HTTP 请求 **0 次**，无重试、翻页、扩窗或换 App。

### 结果来源等级（2026-08-15）

**提案：**所有执行结果纯加法增加同形 `result_source`，用离散事实区分
`governed_product/product_contract`、`caller_defined/caller_responsible` 和
`raw_operation/operation_contract_only`；Plan 的本地目录与异构聚合只增加必要的
`local_catalog/catalog_contract`、`mixed/per_result`。不生成可信度分数，不改请求、operation、投影、
状态、退出码或既有字段。外层既有 `schema_version` 按仓库可选字段纯加法惯例保持不变，新子合同独立
使用 `gravity.result-source.v1`；合同版本、SQL Evidence 与 live 状态继续使用各自现有字段，不压成一个
含义不清的通用布尔值。工作底稿位于 ignored `tmp/codex/result-provenance/proposal.md`。

**判定：**来源等级采用三条执行责任边界：固定产品合同及产品投影形成的结果为
`governed_product/product_contract`；workspace recipe 与 `sql query` 为
`caller_defined/caller_responsible`；`gravity run <operation>` 及公共 `read/read_all/batch` 为
`raw_operation/operation_contract_only`。离线 metadata 结果另用 `local_catalog/catalog_contract`，Plan
同时包含不同来源时顶层为 `mixed/per_result` 且各 node result 保留自己的等级。这里没有正确率、置信度
或 0--100 分数；`semantic_verification` 只陈述该路径验证到哪一层。CLI JSON 与 `--output` 直接序列化
SDK/Core envelope，NDJSON summary 复制同一对象，Plan 顶层与逐 node、Agent 候选卡和其 Plan handoff
均复用 `result_source.py` 的同一构造器。合同版本、HTTP live receipt/probe 状态和 SQL
`evidence_reference` 仍保留原字段，不复制进来源子合同。

既有外层 `schema_version` 不提升。仓库最近的纯加法惯例是 `d2833fe` 在
`gravity.agent.v1` 与 `gravity.plan-result.v1` 增加 `call_bound` 时仍保持两个外层版本不变；本轮同样让
旧调用方按未知字段忽略，并只给新嵌套合同独立的 `gravity.result-source.v1`。请求、operation、投影、
状态、退出码均不变。

Agent 发现面存在有条件的 SQL/raw 旁路。`agent_sources.catalog_cards()` 会装载 workspace SQL product，
`_snapshot_product_card()` 生成 `kind=sql_product` 与 `gravity sql query`；在没有权威产品卡且未触发产品
fallback exclusion 时，`agent._discover()` 还会调用 `discover_operation_cards()` 搜索 stable operation，
`_operation_card()` 交付 `gravity run`。`agent_handoff._plan_request()` 分别把两者接到 `sql_product` 与
`run` adapter，protocol/fallback 文案也明确在 Insight 无法表达时查看 SQL products。因此实际工具集
并非“无受治理产品即硬停止”：强匹配的已登记 SQL product 或 stable operation 可以继续执行，语义
正确性不会因 Agent 推荐而升级。该旁路不是无条件的；已有权威产品卡或 product-specific exclusion
会优先返回产品/目标 gap，本轮按范围要求不改路由与 recognizer。

本项是横切 envelope 字段，不新增产品动线、operation 或稳定性变更。可复算为
`48 + 0 = 48`，`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`；operation 为
`185 + 0 - 0 = 185`，stable 为 `176 + 0 - 0 = 176`。生产 HTTP 请求 **0 次**。

### Analysis 自有合同投影修正（2026-08-15）

**提案：**把消费方报告的两条阻断放在同一轮处理，但分别证明边界：公开 Spec schema 做进程内
权威对象与 CLI JSON 的全树差分，不按已知字段点修；funnel 按日响应先用冻结前端控制流证明请求模式
与消费分支，再以最多一次聚合级生产请求确认服务端形状。只把已证明的模式分支加入合同，缺少或畸形
目标投影继续 `contract_changed`。

**判定：**`analysis query --spec-schema` 的通用值脱敏曾把机器合同的
`definitions.condition.properties.operator` 当作人员字段删除；全树差分与所有带 `properties` 节点的
`required` 包含检查确认这是当前 schema 唯一被删除的结构键。schema envelope 现显式声明
`operation_id=analysis.query.spec_schema`，使既有 Analysis 输出边界采用只删除会话凭据的策略；CLI 与
进程内 schema 除 `requested_kind` 外保持逐值一致，`operator` 的完整受控 enum 重新公开。本项生产请求
0 次。仓库另一条同类入口 `analysis segment evaluate --spec-schema` 也完成全树差分，因原本已有
Analysis operation identity，CLI 与进程内合同完全一致，没有第二个受影响结构键。

funnel 的冻结 `Funnel-DPNtPpg_.js` 与 `analysis-data-CVCbcwc0.js`（SHA-256 分别为
`c24bb798…8f042`、`66736b5…81f0d`）证明 line 模式发送 `to_calc_each_day=true` 并消费
`aggregate_by_date`，bar 模式消费 `aggregate_date.total/group`。随后唯一一次单日、两步、无筛选
生产 POST 返回 HTTP 200：`aggregate_by_date` 为对象，`aggregate_date` 为 null，确认前提成立；没有
重试、扩窗或值落盘。原 warning 并非 null 导致，而是同一响应 `date_list[].<date>[].cnt.*` 的合法
数值树未登记，投影删除它后才把状态提升为 `contract_changed`。合同现登记该路径，执行器按
`to_calc_each_day` 要求对应 aggregate 根必须为对象；合法按日形状为 `success`，目标根缺失、null 或
畸形仍 fail closed。本轮不改变分析动线总数。

### CLI 通用脱敏拆分（2026-08-15）

**提案：**把 `cli.py` 的全树输出过滤拆成凭据清洗与业务字段过滤，只保留前者；用同一合成 SDK
result 对比进程内对象和 CLI JSON，并覆盖 JSON、NDJSON、文件与错误 envelope 共用的输出边界。
operation、响应投影和 envelope 均不改，调查底稿位于 ignored
`tmp/codex/generic-redaction/proposal.md`。

**作用面判定：**旧 `_redact` 不是统一 `gravity` 可执行程序的全局过滤。它覆盖 Insight CLI
（`gravity insight ...`、省略 namespace 的兼容命令和 `gravity-insight`）的普通 JSON stdout、逐行
NDJSON、通用 `--output` JSON/NDJSON 文件、写文件 receipt、非成功 result 及已捕获异常的 stderr
envelope；递归作用于 `data/error/details/warnings/next_action` 等整个对象树。SQL、Census、静态帮助、
统一启动器自己的 workspace 参数错误和领域命令自行生成的业务文件不经过这一个函数。stdout 的大值/
行数摘要先执行，凭据清洗后执行；文件输出不采用 stdout 摘要，但采用同一凭据清洗。

**拆分判定：**`_redact` 已改为语义明确的 `_sanitize_credentials`。保留 exact
`authorization/cookie/password/secret/access_token/refresh_token/gravity_auth_token/`
`gravity_authorization/session_token/token`、凭据后缀 `_password/_token/_secret/_authorization/_cookie`
以及 Bearer、JWT 和错误文本中 credential assignment 的替换。删除 18 个业务 exact key、8 个业务
suffix、`operator_*`/`dept_*` 两个前缀规则、Analysis domain 开关、filter `operator` enum 特判和
identifier 通用豁免。由此重新公开 `email/email_address/phone/mobile/user_name/creator`，人员与部门
字段，`callback_url/click_url/postback_url`，所有 `_url/_email/_phone/_mobile/_user_id/_user_name/`
`_designer_id/_designer_name` 后缀字段，以及 `operator_*`/`dept_*`；具体包括 `icon_url`、
`poster_url`、`file_url`、`thumbnail_url`。分页 `continuation_token` 是已发布业务游标，却与必须保留的
`_token` 凭据规则同名冲突；本轮仅为这个已知 envelope key 保留显式 public-cursor 例外，待进一步
裁决，不恢复 `user_id/event_user_id` 等通用豁免。

**CLI/SDK 与合同判定：**SDK 直接对象从不经过 CLI sanitizer，旧 CLI 因此会在 SDK 结果上额外删除
业务字段；这个额外字段集差异属实，现已删除，合成回归证明同一无凭据 SDK result 经 CLI 输出后业务
字段和值保持一致。但 SDK 不是完全没有字段过滤：185/185 个 operation 源合同都声明
`privacy_policy.redact_fields`，compiler 将其写为 manifest `redact_keys`，executor 用其清洗 response、
items、page info 和输入摘要；非 `user_level` runtime 另有按名字推断的业务字段规则。client validate/
wire、export finalizer、fingerprint 和隐私门禁也消费相应数据。`catalog.py` 第一处读取只清洗
`operations describe` 的 fixed query/body，第二处只是展示清单。因而 `redact_fields` 不能整项删除：
凭据项应保留，业务/人员项应由 `open-projection` 同步从合同和 runtime 规则删除；本单元没有越界修改。

`analysis_spec_preview.redact_analysis_values` 清洗的是调用方的筛选、规则等业务输入值，不识别凭据；
按本轮 A/B 二分属于 **B**。它是 SDK 与 CLI 共用、显式命名的 dry-run preview 合同，不是 CLI 通用
输出过滤，本单元只记录判断，不改变其行为。

operation 台账可复算为 **185 + 0 - 0 = 185**，stable 台账为 **176 + 0 - 0 = 176**；分析动线、
CLI 参数、SDK 方法、envelope、退出码和生产请求数均未变化。本项生产 HTTP 请求 **0 次**。

### Stable operation 正向交叉（2026-08-14）

**提案：**从 176 条 stable operation 正向检查真实产品调用链，排除通用 `run`、legacy 快照、
维护/诊断/权限/任务状态和纯 catalog 入口；对剩余分析结果判断非空证据、动线归属、最小五面成本与
字段合同边界，只实现有非空证据且语义闭合的 1--3 条。逐 operation 工作底稿保留在
ignored `tmp/codex/stable-coverage-gap/crossref.md`，权威结论落在本页和动线台账。

**判定：**实现前交叉为 **已被动线覆盖 86 / 不该有产品面 82 / 值得有产品面 8**，三类完备且
无重复。值得产品化的完整集合为 `report.company_amount.query`、
`promotion.bilibili.account.list`、`promotion.bytedance.advertiser_performance.list`、
`promotion.bytedance.custom_audience.list`、
`material.bytedance_asset_text_title_package.list`、
`material.bytedance_std_asset_text_title_package.list`、
`material.bytedance.promotion_material.list`、`analysis.segment.user_detail.list`。

| Operation | 分析问题 / 非空证据 | 动线 / 最小五面成本 | 当前字段合同 |
| --- | --- | --- | --- |
| `report.company_amount.query` | 公司每日广告、点击、成本、事件、画像、存储、追踪和素材传输用量如何变化；有非空且分页证据 | 新增公司资源用量趋势；`1/1/1/1/1` | `user_count` 已登记并返回；未登记字段仍 fail-closed |
| `promotion.bilibili.account.list` | B 站账户/产品曝光、点击、CTR、CPC、CPM 和资金消耗如何；有非空且分页证据 | 新增独立 B 站账户投放表现；`1/1/1/1/1` | `advertiser_name` 已登记并返回 |
| `promotion.bytedance.advertiser_performance.list` | 巨量广告主消耗、余额、预算模式和状态如何；页码协议与实际翻页均已验证 | 新增独立 advertiser profile，不并入明确排除广告主目录的跨平台推广表现；`1/1/1/1/1` | `advertiser_name`、`advertiser_remark`、`company`、`delay`、`operator_id/name`、`project_list` 已登记；未知字段继续 fail-closed |
| `promotion.bytedance.custom_audience.list` | 可投人群覆盖数、上传数、来源和状态如何；2026-08-14 最小非空复验与旧样本 fingerprint 完全一致 | 自定义人群覆盖与状态已闭环；`1/1/1/1/1` | `cid`、`company`、创建/更新人及 `tag` 已登记并返回 |
| `material.bytedance_asset_text_title_package.list` | 普通标题包的标题数、计划数、历史成本和 CTR 如何；旧非空样本与 stable v1 的字段/类型投影同形 | 已补 D32 `title_package` family；与标准版共享 `1/1/1/1/1` | `title_list` 与创建/更新人字段已登记；`package_kind=regular` |
| `material.bytedance_std_asset_text_title_package.list` | 标准标题包的标题数、计划数、历史成本和 CTR 如何；旧非空样本与 stable v1 的字段/类型投影同形 | 已补 D32 `title_package` family；与普通版共享 `1/1/1/1/1` | 同上；`package_kind=standard` |
| `material.bytedance.promotion_material.list` | 精确广告窗口内素材的消耗、曝光、点击、CTR、CPC、CPM、尺寸和时长如何；目标响应为空 | 补 D32；`1/1/1/1/1`，未知引用路径 3 次 | `cover_source`、`labels`、`material_info`、`organization_tags`、`poster_url`、`signature`、`star_author_id`、`url` 已按既有 shape 登记 |
| `analysis.segment.user_detail.list` | 精确分群有哪些成员及其时间、渠道、版本和归因属性；已取得非空 shape-only evidence | 分群成员明细已闭环；`1/1/1/1/1` | 全量投影；枚举 7 个 App 后第 3 个首次产出分群，目标 3 次均 HTTP 200 非空，登记 147 个顶层字段；分页输入被忽略，按一次完整响应交付 |

本轮在 `report.company_amount.query` 已闭环的基础上继续实现 advertiser profile。公司用量的 Core、CLI
`reports usage`、SDK `company_usage()`、Plan `company_usage` composite 与 Agent
`composite:company_usage` 五面共用 `gravity-insight.company-usage.v1`；已知输入 1 次、未知能力
2 次由 `gravity.agent-call-bound.v1` 声明。Plan 通过 Report family router 接入，
Advertiser profile 以独立 Core / CLI / SDK / Plan / Agent 卡接入；`plan_adapters.py` 只追加新名称和路由分支。分页复验共 2 次生产请求，失败 0、重试 0；新值无关 evidence 记录页码回显和跨页差异，不保存广告主行值。

**Bilibili account 裁决：**选择独立动线，不扩展 Promotion Performance。后者对既有平台继续强制
workspace App、日期窗口、平台和物理指标绑定，调用方保证不变；Bilibili account 只有请求
`date_list`，没有 App 或动态指标输入，结果行也没有日期字段，因此新 envelope 只声明
`requested_date_range`，不声明 `window_applied`。Agent 以“B 站账户/产品 + 表现/曝光/点击/消耗”
路由本动线，泛化“B 站推广表现”仍路由 Promotion Performance，显式同时请求两者仍返回
`MULTIPLE_INTENTS`，相邻产品不靠猜测合并。Core、CLI、SDK、Plan 与 Agent 卡共用
`gravity-insight.bilibili-account-performance.v1`，并以 `gravity.agent-call-bound.v1` 声明已知输入
1 次、未知能力 2 次。`advertiser_name` 现已登记返回；本轮完全复用
不可变 Evidence，生产请求 0 次。

**上表 8 条已有明确裁决（2026-08-15）：7 条产品化，1 条等待非空证据。**

- **已实现 6 条产品动线**，各自独立产品面：`report.company_amount.query`、
  `promotion.bilibili.account.list`、`promotion.bytedance.advertiser_performance.list`
  （本轮实测翻页成立）、`promotion.bytedance.custom_audience.list`、
  两类 `*_text_title_package.list`（共用一条 `title_package` 动线），以及
  `analysis.segment.user_detail.list` 的 `segment_members` 动线。
  **四条新动线都没有把跨平台 Promotion Performance 变体化**——后者明确排除广告主目录，
  为了塞进去而放宽它会削弱既有调用方的保证。
- **等非空证据 1 条**：`material.bytedance.promotion_material.list` 目标响应仍为空。
- `analysis.segment.user_detail.list` 的合同证据阻塞已解除：已取得非空 item schema，
  确认分页输入不控制结果，并闭合 Core / CLI / SDK / Plan / Agent 卡。

`material.bytedance.promotion_material.list` 仍保持显式产品缺口，不能因 stable 或 raw/legacy 入口而
算作闭环。9 条 `export.analysis.*` 已于 2026-08-15 重新裁定（见下文及
[能力覆盖与缺口](capability-coverage.md)）：隐私边界不再阻塞，但完整请求/文件合同仍使该动线完全缺失。

### D32 title-package family 裁决（2026-08-14）

**普通版与标准版同形，作为一条动线的两个显式变体实现。** 两份 2026-08-08 不可变非空
Evidence 的 raw schema fingerprint 均为
`c539fee4dae32cc58d0c9155990ba581822a68893ea7f0069eee5cf16bb96b63`，逐字段路径与类型一致；
后来的两个 stable v1 合同也只有 operation identity、固定路径、resource 和描述不同，请求、分页、
公开字段与已知省略字段一致。没有证据显示样本到 stable 之间发生字段漂移，因此本单元 0 次生产请求。

Core `title_packages()`、CLI `materials title-packages`、SDK `title_packages()`、Plan
`title_package` composite 与 Agent `composite:title_package` 共用
`gravity-insight.title-package.v1`；调用方必须显式提供 `package_kind=regular|standard`，不合并两类
结果，也不拍平差异。`title_list`、`create_user_id`、`create_user_name`、`update_user_id` 已登记返回，
其中 `title_list` 作为已观察到的 opaque JSON 正文交付。未知字段在产品边界 fail closed，完整分页触顶返回
`partial`，父资源、权限或未支持能力
保持独立状态。已知输入 1 次、未知能力 2 次由 `gravity.agent-call-bound.v1` 声明。

D32 是台账动线编号，不是已有可挂载的可执行产品；本实现新增独立 title-package family 入口。
**台账里 title-package 单列为自己的已闭环动线，D32 保持完全缺失**（2026-08-15 复核修正）：
标题包是 D32 之下的一个具体产品，而 D32 这条动线的阻塞——当前账号没有非 Bytedance 投放数据——
完全没有变化。把 D32 标成部分闭环会让人误以为还有工程活可做，实际它仍是数据阻塞。
其他平台素材 draft 的稳定性、非空证据和阻塞裁决不变。

### 自定义人群覆盖与状态裁决（2026-08-14）

本节取代上段“custom audience 保持产品缺口”的旧结论；其余候选裁决不变。

**提案：**先比较 2026-08-08 不可变非空样本与 2026-08-11 stable 提升提交。后者只包含
手写 transport fixture，没有同日生产响应证据，仓库内无法证明时间差期间只新增字段或既有字段
保持不变；因此按不确定处理，只执行一次 `page=1,page_size=1` stable drift probe，再决定是否产品化。

**判定：**最小 probe 成功且非空，恰好发出 1 次生产 POST；当前 raw schema fingerprint
`f079040f010b823ea179fe1afb0d0b2bb2674a1e83bde245ab606b9c8b6add00` 与旧样本完全一致，
逐字段类型、分页形状均未漂移，也没有发现新字段或新的用户级字段。实现独立
`gravity-insight.custom-audience.v1` 动线：Core `custom_audiences()`、CLI
`promotion custom-audiences`、SDK `GravitySDK.custom_audiences()`、Plan
`custom_audience` composite 与 Agent `composite:custom_audience` 五面共用一次完整分页读取。
未登记字段继续 fail closed；上述七个字段维持省略。卡与 Plan 节点用
`gravity.agent-call-bound.v1` 声明已知输入 1 次、未知能力 2 次。本单元不改变 promotion
performance 的产品语义。

### Report 家族读语义取证（2026-08-14）

**提案：**先对 Report census bundle 做零业务请求的控制流复核，仅在列表装载、分页和响应消费均
成立时追加逐 route read confirmation；然后对已放行 route 各发 1 次第一页、`page_size=1` 的最小
请求，不翻页、不重试、不扩日期窗，不用猜测的 App 或平台值换取非空。

**判定：**`report.masterkey_report_group.list`、`report.report.list`、
`report.shared_to_me.list` 和 `report.media_report.list` 均由 hash-matched bundle 证明为读取并完成
精确确认；media 的 `app_id` 来自 `AppSelect`、`ad_platform` 来自有限平台选项，空选择会省略。
`report.subscribe.list` 的既有确认有效，但其路径段 `subscribe` 还被通用 Registry 词元守卫拒绝；
prober 现仅对 confirmation 文件中通过完整校验的精确 `POST + path` 放行，stable Registry 不变。

实际共 5 次生产请求，五个 operation 各 1 次，均 HTTP 200、第一页 0 行、明确空；没有认证、权限、
语义或 HTTP 错误，也没有持久化响应值。旧分页证据不因单页复核降级，订阅的未知 `data.list` 及
`user_level` 边界继续保留。三条动线都从合同阻塞转为非空 item schema 阻塞，本轮新增 stable 与
五面产品均为 0；下一步只能由有对应数据的租户提供同形状非空样本，不能扩大窗口寻找数据。

## 优先级

| 序 | 动线 | 为什么排这里 | 阻塞 |
| --- | --- | --- | --- |
| 1 | **D22 看板页面条件忠实重放** | 已对非空 `data.object.config.filter` fail closed；空条件不受影响 | **合并发生在服务端，前端分析已穷尽**（见下） |
| 2 | **D35 归因表现聚合** | 当前只能读归因配置，无法回答归因结果；且是 F40 的前置 | **2026-08-16 审计撤销旧 semantic-error 阻塞，待重新取证**（见下） |
| 3 | **D34 非 Bytedance 计划/组/创意下钻** | 跨平台产品多数只到顶层 | D32/D33 已证明当前账号的七个平台父链均无可下钻样本 |
| 4 | **D32 平台专属素材/创意深查** | 最小取证已完成，未取得可升级的非空合同 | 当前账号无非空 advertiser 父候选；保持 draft，等待有数据租户 |

完整动线的逐条判定与最小证据要求见[分析动线台账](analysis-journeys.md)；本页只维护排期与约束。

### 分析结果落盘统一裁决（2026-08-14）

**只统一 JSON 落盘，不统一 `--format`，不新增 CSV/表格。** `analysis query`（含 compact batch
与显式多 App 扇出）、`reports pulse`、`sql query` 补 `--output`；写入完整既有 envelope，不改变
结果内容。它们与已有产品共用一个原子结果写入原语和同形 `written` 收据。纯 `error` 或
`capability_gap` 不创建也不替换目标文件；`partial` 写入完整 envelope，同时保留原非零退出码。
理由是 partial 中独立成功组件仍可消费，且 envelope 已明确记录失败组件；拒绝写入反而会丢掉
不可无代价重取的成功结果。终止失败则没有可消费结果，覆盖旧文件会把一次失败伪装成新 artifact。

格式判据不是“有没有 rows 字段”，而是**公开结果合同本身是否是无损二维记录集**。Analysis、Pulse
和 SQL product 的公开合同都包含状态、错误/partial、分页或 Evidence/查询收据；SQL 内部 rows
即使二维，公开结果仍不是裸表。把这些 envelope 输出 CSV 必须丢字段或自创映射，所以不提供。
NDJSON 只保留在已有明确逐记录编码合同的入口；本轮不把它扩到 composite。若以后有公开合同天然
就是同构标量行数组，且所有状态与收据都有无损、版本化的独立承载，才可单独评估 CSV；不得为嵌套
结果定义通用拍平规则。xlsx 仍只走治理导出 effect。

### 生产 HTTP 请求收据耐久性裁决（2026-08-15）

**裁决：每个 HTTP response 返回实际 transport 的同步边界，先把值无关请求收据写入
`state_root/receipts/http/`，再解析响应体、判断重试、做投影/合同校验或组装分页、产品、composite、
Plan envelope。** 每个 response/attempt 独立使用 `result_output.write_rendered_result` 的 write、flush、
fsync 与 atomic replace；probe 完整 evidence 的最终写入也复用同一耐久原语。收据合同
`gravity.http-receipt.v1` 只含 `operation_id/method/path/http_status/completed_at/page_number/attempt/retry`
和 request shape fingerprint，不含请求值、响应体、App ID、凭据或业务标识值。

修复前实际有七条后置记录路径：prober 内存 observation、单页 `ReadResult.page`、全分页 merge receipt、
产品 sanitizer envelope、composite component、Plan partial、以及 Resolver/catalog/log。前六条都要等各自
本地处理成功；Resolver 只在 `_finish` 写总 `request_count`，catalog/log 也在公开 read 退出时更新，且
都不是逐请求 HTTP 账本。因此请求后投影或合同校验失败、分页中途异常、组件 projector 异常和进程强杀
均可丢记录；日志 handler 与收尾函数不能补这个事实。

两条独立复现分别落在同一窗口：d28 的 `app.list` 与 `report.get.query` response 已返回，但 prober
observation 尚在内存，后续 `calc_total.data_list` 本地校验退出；agent-usability 的 Q13/Q14 则在分页
聚合及产品/Plan 重建前失败，所以只能留下 3–11 次的界。修复用 fake session 注入并证明：200 response
后的投影和合同校验异常仍有 status receipt；页 3 transport 异常前页 1/2 各有 receipt；503→200 retry
的两个 attempt 各有 receipt；composite 失败组件的 503 仍有 receipt；写目标不可用不覆盖原错误；子进程
进入 prober response body 解析后立即 `TerminateProcess`，已完成 response 的 receipt 已在盘。

写目标不可用时请求结果和原始错误优先，SDK 只附加固定结构的
`gravity_http_receipt_write_failed` 日志，不改变错误分类、operation、wire、退出码或既有 envelope 字段。
因此对外 envelope 合同增减为 **0**；新增的是私有状态目录中的向后兼容旁路 artifact。不能宣称绝对不丢：
response 返回与第一条记账指令之间仍有指令级 kill 窗口；transport 在返回 response 前抛错时，即使请求
可能已到上游，SDK 也没有可登记的 HTTP status；写目标不可用、OS/硬件违背 fsync 承诺、Windows 缺少
目录 fsync 等价物、requests 内部自动重定向的中间 hop、或调用方自定义 transport 绕过仓库 production
transport 时仍可能缺 receipt。后两类都不宣称属于逐上游 wire-hop 的完整账本。

本裁决不新增或升级 operation，`185 → +0 = 185`；不新增产品动线，台账
`48 = 32 / 0 / 16 → +0 / +0 / +0 = 48 = 32 / 0 / 16`。质量债只收紧：
`http_runtime.py` 文件 SLOC ratchet `680 → -3 = 677`。本单元生产 HTTP 为 0。

### 生产 HTTP 请求收据有界保留裁决（2026-08-15）

**裁决：只保留同时属于最近 10,000 个且不老于 7 天的已结束运行 receipt；活动运行的全部
receipt 不受数量和时间清理。** 两个正整数可分别由 `GRAVITY_HTTP_RECEIPT_MAX_FILES` 和
`GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS` 覆盖；缺失、空白或非法值回退有限默认值，不提供因漏配置而
无限增长的模式。v1 紧凑 JSON 每个约数百字节，10,000 个约 3–5 MiB 内容；按常见 4 KiB 分配单元
约 40 MiB，另有目录项元数据。窗口是 `min(7 天, 10,000 / 实际 HTTP response 速率)`：100 次/天
约 7 天，1 次/分钟约 6.9 天，1,000 次/小时约 10 小时。

清理严格在当前 receipt 沿用 write/flush/fsync/atomic replace **成功返回以后**执行，不能进入 response
返回与同步落盘之间。每个进程对每个 state root 首次成功写后扫一次，此后每 64 次写扫一次；10,000
文件稳态下摊销约 157 个目录项检查/次写。进程间只竞争非阻塞 prune lease，拿不到立即跳过；私有文件名
带 PID 与 run ID，清理器从已发布文件自身识别并排除所有存活进程的运行。写入仍用独立临时文件和
atomic replace，清理只看已经发布的 `*.json`，因此不会碰别人正在写的临时文件。PID
复用最多延后旧运行回收，不会把活动运行误判为可删。

任何配置、租约、列举、stat 或 unlink 失败都留在 best-effort 边界，只追加固定
`gravity_http_receipt_prune_failed`（非法配置另有固定 retention warning），不改变成功结果，也不覆盖
后续解析/投影抛出的原始异常。两个硬约束意味着目录可以暂时超过默认值：两次 sweep 之间最多新增 63
个；所有并发活动运行 receipt 继续保留；不可删除目标留到后续 sweep 并告警。真实子进程回归覆盖数量与
时间配置、10,000/7 默认值、不可 unlink 目标不改 200 结果、两个重叠进程互相清理时两边当前 receipt
都在；原强杀、投影/合同失败、分页中断和 retry 耐久测试继续通过。

截至该轮，这些 HTTP receipt **没有公开读取入口**：源码只有写入/清理，CLI/SDK 不提供 list/get/export，公开
Resolver envelope 也不引用逐 HTTP 文件。它们目前给知道私有 `state_root` 布局的维护者或调用方做人肉
事后排查，不是可承诺的程序化消费面。因此本轮不把私有文件布局升格为 API；若出现真实消费需求，应另轮
先定义只读查询 envelope、稳定排序/分页和缺口语义，再据消费 SLA 重评 7 天/10,000 默认值，不能直接让
调用方依赖目录 glob。本裁决不改 receipt schema、公开 envelope 或产品能力：operation
`185 → +0 = 185`；产品动线 `48 = 32 / 0 / 16 → +0 / +0 / +0 = 48 = 32 / 0 / 16`；生产 HTTP 0 次。

### HTTP receipt 公开只读面与结果审计链（2026-08-16）

**提案：**真实消费需求已经成立，但只提升读取和关联合同，不提升私有目录为 API。以独立
`gravity.http-receipt-query.v1` 返回 `ok/status/items/page/gaps`：`items` 是既有值无关 receipt 的
字段加离散 `run_status`，`page` 固定声明排序、快照时点、快照指纹和 opaque cursor，`gaps` 只使用
机器枚举。SDK 提供 list/get/export；CLI 提供 `gravity receipts list|get|export`；Plan 使用本地
`receipt_query` 节点。执行结果外层 schema 不升级，只加 `gravity.result-audit.v1` 子合同：
`fact_paths` 用 JSON Pointer 指向 operation、contract version、SQL `evidence_reference`、Agent
`call_bound` 等**原位事实**，`http_receipts` 只含 opaque `receipt_id` 与 `stored/write_failed`，不生成
解释文字，也不复制原位事实值。

**结论：四项前置条件已闭合，写入路径和耐久性裁决未改。** 列表按
`(completed_at, receipt_id)` 倒序：`completed_at` 是既有固定六位微秒 UTC 完成时间，`receipt_id` 是
每条完成 response 已生成的 128-bit UUID hex；重复 ID 直接归为损坏，因而该二元键在并发发布下形成
全序。第一页冻结 `as_of` 和候选键/损坏 token 的 SHA-256 指纹；后续新完成且晚于 `as_of` 的 receipt
不进入该次遍历，若旧完成时间的延迟发布、保留清理或损坏变化改写候选集，则返回
`status=partial + gap=snapshot_changed`，不静默跳项或重项。cursor 同时绑定 operation filter 和最后一个
二元键。真实子进程在两页之间并发落盘的回归证明新写不扰动第二页，同时间 receipt 由 ID 稳定裁决。

缺口按结构机械区分：结果引用为 `stored` 但 get 已找不到时是 `retention_pruned`；私有文件仍属于存活
writer process 时 item 为 `run_status=run_in_progress`，list/get 同时给同名 gap 并返回 partial；写入原
best-effort 边界失败时结果引用直接为 `storage_status=write_failed`，get 无需猜目录即返回同名
capability gap。无引用的任意 ID 另为 `unknown_receipt`。目录不存在是 `ok=true/status=empty`；目录不可读
是 `capability_gap/storage_unreadable`；任一 entry 损坏或重复 ID 是 `partial/corrupt_receipt`，即使全坏
也不伪装成 empty。读取器内部解析私有文件名只为沿用既有活动运行保护语义，公开 item、gap、cursor、
SDK/CLI/Plan envelope 均不含磁盘路径、文件名、PID 或 run ID。

Plan 的“设计不适用”例外**未使用**：本地 receipt 查询无副作用、预算有界且返回 JSON，与 Plan 数据
节点相容，故例外条件 1（effect 与执行模型不兼容）不成立；既然第 1 条不成立，不以第 2 条“其他面可
完成任务”或第 3 条登记要求绕过实现。`receipt_query` 复用全局 Plan worker 预算，不构造 Insight client；
partial 与 capability-gap 查询均保留完整嵌套 envelope。

保留默认值仍为 **7 天 / 10,000**。新消费需求证明“需要程序化读取”，没有提供复核响应时限、实测请求
速率或存储预算，不能从需求本身推出更长 SLA；既有窗口算式和 3–5 MiB 内容/约 40 MiB 分配单元估算
未被反证。后续只有在调用方给出超过 7 天的复核 SLA，或观测速率证明 10,000 上限先于 SLA 截断时才
重评；当前 export 上限也保持 10,000，防止一次诊断绕过有界约束。

本单元不新增 operation 或产品动线：operation `185 → +0 = 185`，stable `176 → +0 = 176`；动线
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`。错误清单因新增输入/存储/cursor fail-closed
抛点净增 16：`974 + 16 = 990`，分档为 `A 218 + 0 = 218`、`B 400 + 6 = 406`、
`C 356 + 10 = 366`；code/category/既有退出码语义未改。技术债清单复核无新结构项：读取、CLI 和 Plan
分别下沉窄模块，共享入口只做最终注册。生产 HTTP 0 次。

### 响应合同漂移非对称裁决（2026-08-16）

**提案与结论：以“是否可能让调用方静默算错”为分界。** 未登记的请求字段仍在联网前失败；已登记
响应字段消失或类型不兼容仍返回既有 `contract_changed`；响应新增未登记字段不再把正确查询升级为
`contract_changed_additive`，而是省略该字段、正常返回既有投影，并记录独立版本的
`gravity.response-drift.v1`。这与 Pact 的可执行规范方向一致：provider
[响应多键仍匹配](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/response/body/unexpected%20key%20with%20not%20null%20value.json)，consumer
[请求多键不匹配](https://github.com/pact-foundation/pact-reference/blob/9930b06c31b66d835b6b3fe7b4d855f52d394b24/rust/pact_matching/tests/spec_testcases/v1/request/body/unexpected%20key%20with%20not%20null%20value.json)。
本仓库投影仍只暴露已登记字段；本裁决没有新增过滤、检测、访问控制、operation、CLI 参数或退出码。

漂移子合同位于结果的 `result_audit.response_drift`，固定声明 `direction=response`、
`classification=additive`，`fields` 是按 JSON Pointer 与观察类型排序去重的对象数组，例如
`{"path":"/data/list/*/future_rank","observed_type":"integer"}`；不保存响应值。相同子合同在投影后
补入本次 `gravity.http-receipt.v1`，外层 `gravity.result-audit.v1`、HTTP receipt 和查询 envelope 的
`schema_version` 均不提升。调用方可直接检查当前结果；事后以 `result_audit.http_receipts` 的 opaque
引用调用 SDK `get_http_receipt()`，或使用 `gravity receipts get`，无需依赖私有目录布局。
`OperationCatalog` 仍把带该结构化审计的成功结果记为 health `contract_changed_additive`，维护者现有
describe/receipt 查询触发源没有丢失。

响应枚举没有随新增字段放宽。当前通用 response projection 没有可声明的 enum 集合，因而不从任意
标量样本臆测枚举；已在领域合同中穷举的 status/platform/pagination 分支仍按原校验 fail-closed。
理由是新增枚举值会进入调用方分支决策，风险与单纯多一个未使用字段不同。维护文档只记录本政策和
查询办法，**不复制运行时新字段清单**：字段清单随上游变化，写进 Markdown 会成为不完整且会过期的
第二事实源；有界 receipt 查询才是应补登记项的机器事实源。

本裁决是横切兼容性提升，不新增产品动线、operation 或 caller 可恢复错误点：operation
`185 + 0 = 185`、stable `176 + 0 = 176`、动线 `48 = 33 / 0 / 15 + 0 / 0 / 0 = 48 = 33 / 0 / 15`。
错误审计为 `1022 + 0 = 1022`，其中 A 档 `218 + 0 = 218`。
代码排查发现一条产品路径曾用 additive metadata 状态阻止后续业务读取，现改为消费已登记 metadata、
同时保留 drift audit；catalog health 的 additive 可发现性显式保留。测试盘点中 33 条既有用例把未知响应字段与失败状态绑定，
现改为验证成功、既有投影与结构化 audit；1 条值保护用例把字段名也当秘密，现收窄为值和 `data`
不泄露、字段名只出现在 drift path；另 1 条 `_project` 直接测试仅迁移四元返回接缝。最终触及
37 个测试函数（35 条既有修改、2 条新增）；新增 2 条分别覆盖
未知请求字段的零网络失败和 receipt 端到端可查询回归。技术债清单复核无新增结构项，quality baseline 仅收紧；
生产 HTTP 0 次。

D32 本轮先估 22 次、实际只发 5 次最小 stable 根读取；5 次均为 HTTP 200 空样本。复用 D33
的 Bilibili/Huya 3 次证据后，七个平台中只有 Bilibili account 曾非空，但其 advertiser 为空；
其余六个平台在允许的根读取或最短单日 advertiser 窗口内均为空。没有权限失败、合同漂移、重试、
翻页、扩窗或 App 切换，因而没有 draft 取得非空响应、父依赖和目标权限六项闭环，stable 数不变。

**D32/D34 是数据阻塞，不是工程阻塞。** 七个平台的父链全断在 account 或 advertiser，
且**无一是权限不足**——当前账号下就是没有非 Bytedance 的投放数据。这意味着再投入工程量
也推不动，两条动线不应继续占用排期位。**不要重复探测**：已知为空的路径再探一次只是消耗
上游请求。解锁条件是外部的——拿到有非 Bytedance 投放数据的租户，或由调用方提供该平台样本。
在那之前，188 个推广/素材 draft 保持 draft 是正确状态，不是欠账。

## D22 合并语义：证明不了，且前端这条路已穷尽

`Dashboard-DrzT0Orh.js`（SHA-256 `6fc533…016`）证明：**页面条件以顶层 `dashboard_condition` 发送，
图表条件仍在 `global_conditions` / `global_cond_logic`，共享 HTTP wrapper 原样传递两者**——
**合并发生在服务端**。这意味着继续做前端 bundle 分析不会有答案，那条路已经走到头。

已观察到的请求**同时兼容四种候选规则**（AND 叠加 / 页面覆盖 / 图表覆盖 / 同维替换加异维叠加），
一个都排除不掉。只能确定两件事：页面条件为空时图表条件原样保留；两者都为空时无冲突。
**这两点只证明请求形状，不证明服务端求值。**

artifact 路径也走不通：当前账号 7 个 App 里 6 个的合法 Dashboard tree 无可选看板，
另 1 个响应 `contract_changed`；本地 artifact 与 receipt 均无双条件实例。

**解锁只有两条路**（都不是工程量问题）：拿到服务端合同；或有一个自然存在的、
同时带页面条件与图表条件的看板，用只读请求分别取得异维度组合与同维度冲突的权威结果。
在那之前保持对非空页面条件 fail-closed 是正确的——猜错会让调用方拿到
"看起来对但其实错"的数据，比报错更糟。

**顺带修掉的不一致**：`dashboard_conditions.py` 曾把 `UNSUPPORTED`（local）硬编码为
`exit_code=2`，与错误分类对齐后的 local→4 冲突，测试也固化了 2。该产品落在错误分类合并之前，
是并行开发的遗留。现已改为调用共享的 `exit_code_for_error`，不再硬编码。

## 并行与串行约束

**共享 spine（S）**：`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、
`agent_handoff.py`、`cli.py`、`__main__.py`。九条已交付产品线**全部**修改过前四个。

- **所有触碰 S 的最终接线必须串行**，由一个集成人顺序合并。领域 core、合同研究、证据取证可任意并行。
- 同一领域的 `compiler` / provenance / coverage 生成物必须串行再生成。
- 已知依赖链：`D22 → D23`、`D29 → D30`、`D27 → D28`、`D33 → D34`、`D35 → F40`。

## 两条曾经贴脸的硬约束（已解除，规则保留）

1. **`plan_adapters.py` 已从 491 降到 456 SLOC**，余量 44 行，`_execute_composite` 不再是该文件
   最大函数。解除方式是把固定来源 composite 下沉到窄领域 family router（照 `plan_order_adapter.py`）。
   **这条路径仍是唯一批准的接法**：新增 Plan composite 走 family router，中央文件净增长 ≤ 0，
   不引入全局 adapter registry 或插件机制。余量变宽不等于可以回去直接加分支。
2. **Agent 意图冲突已收口到 `agent_intent_routing.py`**，五个既有 owner 不再持有他产品负向词。
   新增语义相邻产品的成本**不再随相邻产品数增长**。判据是 selector 精确度 + owner 正向证据基数，
   不枚举产品对；新产品只需声明自己的正向证据。不引入插件、注册表或通用意图 DSL。

## 已知能力净损失

`0.2` SQL 收口的净损失**已部分偿还**（收口提交 `d951d52`）。四类逐一判定：

| 产品 | 判定 | 说明 |
| --- | --- | --- |
| `payment-summary` | **部分恢复** | 聚合 SQL、全部异常计数字段与静态口径已恢复；未恢复 `revenue_yuan` 派生、动态 warning、旧 envelope |
| `first-scene-coverage` | **部分恢复** | 状态、前缀、注册量已恢复；宿主名称映射属调用方语义，覆盖率与动态 warning 未恢复 |
| `event-coverage` | **部分恢复** | 全量与逐事件聚合已恢复；项目事件字典、missing/unknown 对账、新鲜度 warning 未恢复 |
| `profile-coverage` | **不该内置恢复** | 历史 SQL 有成功证据，但 `activity_event` 与画像属性名是业务绑定，属调用方。SDK 不固化这些字段；调用方可按自身契约登记同形 `custom-sql` |

恢复走 workspace recipe 模板（`examples/workspace/sql-capability-recipes.toml`），
**没有重建被删的 builder/summarizer 框架**——那正是收口要去掉的东西。证据是 `0.2` 之前
7 份已发布聚合 Evidence（`2026-07-23`–`2026-08-06`），本轮 0 次上游请求。
同时给 SQL product 增加 `output_semantics`，补上"只有字段名没有字段口径"这一块，
它进入产品目录、Agent 匹配、dry-run 合同与查询摘要，但**不生成动态 warning 或业务判定**。

**这笔债已在 2026-08-16 以不含业务绑定的派生层偿还**：SDK 提供 `ratio/share/change/reconcile`
四个纯算子、动态 warning/notes 和独立 `gravity.derived-metrics.v1` partial 合同；调用方提供列绑定、
结果名、对齐键和声明集合。分母零、缺列、null/非法数、上游 partial、总量不完整、对齐缺边/重复键、
float 输入与 Decimal 舍入均可由 SDK 机械判定。公式是否代表正确含义、总体是否正确、时期是否可比、
单位是否兼容、声明集合是否权威仍属调用方；它们不是未完成的 SDK 债务，也不从字段名推断。
历史在线证据截至 `2026-08-06`，此后上游是否漂移未验证，示例 datasource 保持 `pending_review`。

`0.3` Multidim 收口经复核**无取数能力净损失**：raw query/total 仍可经
`gravity run report.multidim.*` 执行，损失的只是旧 CLI/Plan 便利性。

破坏性收口允许直接升级，但**必须先确认没有取数能力净损失**，否则就是在削弱产品目标。

## Agent 可用性欠账

- **"未知 2 次"的承诺不成立，已改为显式声明下界。** 旧记的"8 条"口径有误：把 Dashboard
  control/replay 两张卡并成一行，又把执行后的 stale/parent/diagnostic 重试当成一条正常路径。
  按同一类别口径重算，加上后来新增的分析模板引用路径，实际是 **9 类**。
  **九类全部判定为"显式声明"而非"补齐路径"**——它们都要求调用方精确选择引用、App 或物理字段，
  把目录选择折进执行只会隐式猜值或重复读目录，那比多一次调用更糟。
  下界：未知引用/物理输入 3 次；App 也未知时 4 次；metadata 未同步且 App 未知时最高 5 次。
  声明走 `gravity.agent-call-bound.v1`，四面一致（`gravity agent` candidate、
  `GravitySDK.capabilities()`、`candidate.call_bound`、`plan_node.call_bound`），
  含 `minimum_calls`、`discovery_calls`、`unknown_inputs`、`catalog_status`、`input_sources` 与依赖。
  旧 Plan 不含该字段仍通过，字段不进运行态 `PlanNode`，不改变 request、并发或执行结果。
  Multidim 与 Promotion 的独立目录已用现有 batch 合为一次发现调用，selector 集合与分页数不变。
- 当时 13 张固定 composite 卡（当前基线为 21 张）的 7 对意图重叠已收口：集中层按现有 owner 的正向证据强度与 selector
  精确度收集产品，命中多个产品即返回 `MULTIPLE_INTENTS`，不再搜索 raw operation。
  该判据不枚举产品对；显式 `and/以及/同时` 子句独立识别，wrapper 引用与历史紧邻冲突仍 fail closed。
- 错误分类已对齐：permission 返回 upstream/3，本地 unsupported/policy/privacy 阻断返回 local/4；
  operation、请求行为和错误 code 均未改变，没有读能力损失。这是有意的破坏性行为变更——
  调用方需更新 exit-code 分支：`3` 表示换账号或申请权限，`4` 表示请求未发出、停止改输入重试。

### Agent 自然语言到答案实测（2026-08-15）

本轮另做了 20 个端到端问题实测（中文 10 / 英文 10），测的是
`gravity agent "<问题>"` 到业务答案、明确空或机器可判定 gap 的整条路径，**不是**下面“改参数要不要
改代码”的 20 场景审计。覆盖事件/漏斗/留存/属性/散点/跨期/分群/用户画像、订单/拆单/变现、
推广/素材/标题包/自定义人群/B 站/广告主、公司用量/业务脉搏、多维/SQL/metadata、多 App 与看板重放。
预期在任何调用前冻结，生产请求没有通过换 App、扩窗、重试或额外翻页追非空。

原始结果按“正确 `MULTIPLE_INTENTS` 或明确 capability gap 也算合法终点”是 **4 / 20**；若只算
业务数据答案则是 **0 / 20**。首调错路由 **8 / 20**：漏斗卡夹带 App raw operation，属性/散点落到
raw operation，素材被误判为素材+推广双意图，带日期和双类型的 title-package 落到 generic Analysis，
广告主/metadata/看板重放报无能力。另有事件趋势、留存仍停在 generic Analysis handoff。

当轮只在领域 `agent_*.py` 内修复了可复现的窄问题：事件趋势与留存现在返回 kind-specific 卡，
素材弱 `ad` 词不再误触发 Promotion，字段式英文广告主问法和 `saved dashboard` 重放可达正确 owner，
“变现表现”返回产品边界 gap 并给出可复制的 detail 重新发现命令。属性/散点已能把正确 Spec 卡排在
第一，但共享 authoritative selection 仍夹带 raw operation，故仍不算唯一卡。原始 8 个错路由中
修掉 3 个，剩 **5 个**；修复后的离线重放不改写原始首调数字。

已完成执行的 Custom Audience 与 Bilibili 两题都严格用了 Agent + Plan 两次顶层调用，未发现
`gravity.agent-call-bound.v1` 失配；前者以 upstream/3 `CONTRACT_CHANGED` 失败，且 next action 仍含
`<operation-id>`，后者以 caller/2 `PAGINATION_LIMIT` partial 停止，且只说提高 bound。两个失败
envelope 都没有保留逐页 HTTP receipt，所以只能证明加上 App catalog 后共 **3–11 次 HTTP**，不能
事后伪造精确次数；这是观测缺口，也是下次生产实测必须先装脱敏 request observer 的前置条件。

本实测自身在当时快照上的净变化为 0：`48 = 32 / 0 / 16` 加 `0 / 0 / 0` 后仍为
`48 = 32 / 0 / 16`；后续 setting route 去重使最终台账成为 `47 = 32 / 0 / 15`。它没有改变任何
产品面，只证明“四面存在”不等于自然语言入口真的可完成；其中 32 条的 Agent 面仍须按后文收紧的
自然语言判据重验，不能把本节当成闭环确认。未修项是共享 authoritative selection、class-level
metadata 产品卡、title-package 日期/双变体边界、Plan 错误 operation-id 投影、Bilibili 可复制分页
动作和 SQL 缺配置的 local/4 统一；具体退出条件记在技术债和动线台账说明中。

## 九条 `1 / 3` 调用成本裁决（2026-08-14）

**裁决：九条均可在 App/平台及其余业务输入已知时降到两次调用。** 本节在这些 scenario 上取代
上面的三次下界；旧裁决只否定
“把目录选择折进执行”：执行命令不能替调用方挑一个看起来合适的引用或物理字段，这一点继续
成立。本轮新增的是显式在线输入解析：

```powershell
gravity agent "<query>" --resolve-inputs <known-inputs.json> --output <catalog.json>
```

SDK 同形入口是 `GravitySDK.resolve_capabilities(...)`。第一次调用完成能力发现，并读取完整、受治理的
在线目录；metadata/table-lineage 冷目录则在 staging SQLite 中完整刷新后原子发布。调用方在返回值中
按稳定 ID（模板按 `scope + id`）或物理名称精确选择，第二次仍走原有 CLI/SDK/Plan 执行入口。
解析响应明确声明 `caller_call_unit=cli_or_sdk_invocation` 和
`internal_http_calls_reduced=false`；它降低的是调用方顶层调用数，不降低、也不隐瞒目录 HTTP 数。

七条在线目录路径分别复用 Dashboard tree、Saved Analysis catalog、Analysis template catalogs、
Segment catalog、Multidim metadata 和逐平台 Promotion metric catalog。引用执行端会重新读取目录：
删除的 ID 找不到即 fail closed，改名仍由同一稳定 ID 指向同一对象，新建对象不会改变已选 ID；
Saved Analysis 还会核对目录与详情身份。Multidim 卡的闭合 schema 给出静态字段，完整 metadata
给出指标、自定义指标及已证明的动态维度；第二次由 FieldPolicy live 复验指标、维度成员关系和排除
关系。日期和 filter value 仍由调用方业务上下文提供，解析器不生成业务值。
Promotion 第二次由 FieldPolicy 逐平台复验指标。在线解析前后都会清除进程内 metadata cache，
同一 SDK 进程不会把解析前的旧目录带入第二次执行。

metadata search 与 table lineage 过去仍是“冷机 3 次”，原因不是离线模式另有计数口径，而是首个
Agent 调用坚持零网络：调用方随后还要单独 `metadata sync`，再执行离线查询。本轮只有在调用方显式
指定 `catalog_policy=refresh` 时，第一次在线 Agent/SDK 调用才把发现和完整 refresh 合并。任一来源
失败时 staging 库丢弃、旧 catalog 保留且本次解析报错；成功后的第二次查询返回带 `synced_at` 的
observed snapshot，不把同步时刻之后的变化声称为当前事实。

这是纯加法能力：默认离线 `gravity agent`、`GravitySDK.capabilities()`、直接 list/metadata sync 和
所有既有执行入口保持不变。解析器只交付受批准投影中的候选，不根据名称相似度、业务口径或自然语言
替调用方选值。若 App 也未知，或 Promotion 的平台也未知，依赖目录仍有先后关系，不能据此宣称两次；
原 `unknown_app_and_*` 下界继续有效。动态卡和 `plan_node.call_bound` 同步使用
`gravity.agent-call-bound.v1`，只有本次确实交付完整目录的 scenario 才降为 2。

**最强反驳：这只是把原来的“Agent 发现 + 目录读取”组合成一条命令，HTTP 量和在线失败面没有减少，
很容易被包装成虚假的成本优化。** 这个反驳对上游成本完全成立；本裁决只在台账既定的
“调用方顶层 CLI/SDK 调用数”口径下成立，所以响应必须保留 live/refresh 收据并直说 HTTP 未减少。
更接近实质失败的是两次调用间没有上游 revision/ETag：当前安全性依赖合同中的稳定 ID，并由第二次
live re-resolution 防止删除或名称漂移选中别的对象；SDK 不能证明上游将来绝不违规复用 ID，也不能
给同一对象的内容编辑提供点时快照。若上游出现 ID 复用证据，或产品要求执行第一次看到的历史版本，
本裁决失效，必须先取得 revision/conditional-read 合同，不能继续按两次闭环计。

## 三处缺面裁决（2026-08-14）

本轮先按调用方任务而非四面数量复核台账中的三处缺面，结论是**均不新增产品面**：

- **素材报表导出不进入 Plan v1，但动线已闭环。** 导出是有文件副作用和恢复状态的 effect；
  `export run` 已在一次顶层调用内拥有 create、poll、download、文件 schema 校验与原子提交，超时后还要
  用 `job_id` 恢复。Agent 卡直接交接该命令并声明发现后 1 次调用。把它包装成普通 Plan 数据节点会让
  Plan 错误承诺可重试、超时和部分文件语义，不能增加调用方可完成的任务。
- **legacy promotion snapshot 不进 Agent/Plan 主路径。** 兼容面允许任意非空 promotion resource、
  逐平台原始 input 和按 inventory 选择首个稳定 operation；CLI 的 all 模式还会按各 operation schema
  静默忽略不适用 shortcut。它没有绑定一个 workspace App、统一日期窗和显式物理指标，也不校验结果
  是否仍绑定这些选择。正式分析调用方使用 `promotion performance`：只覆盖已证明平台，固定 App/
  日期/指标合同，指标在平台 metadata 中 fail closed，并具有 CLI/SDK/Plan/Agent 四面。兼容 SDK/CLI
  保留给已知 operation 合同的专家调用方，不再把它计作独立分析动线。
- **任意 stable metadata snapshot 是 SDK 维护便利面，不是调用方产品。** 它按当前 inventory 的
  metadata 分类动态扩缩，默认跳过所有缺必填 input 的 operation，因而既没有稳定业务问题，也不能
  承诺统一完整性。构造分析所需的在线上下文已有固定 13 来源的 `analysis context` 四面产品；名称发现
  已由同步后的 `metadata search` / `metadata vocabulary` 离线产品覆盖。保留原 SDK 方法和精确 raw
  operation 入口，不为 registry 聚合器新增 CLI/Plan/Agent 面。

这三项只校正产品边界和台账口径；所有既有命令、SDK 方法、operation、envelope、Agent selector 与
意图裁决保持不变，`plan_adapters.py` 未修改。

**"设计不适用"是窄例外，不是逃生舱。** 上面对导出 Plan 面的判定给闭环判据开了口子，
必须钉死使用条件，否则以后每条动线都能声明某个面"不适用"来充闭环：

1. 只有 **effect 类型与该面的执行模型不兼容**才成立（导出有文件副作用与恢复状态，
   Plan 节点是无副作用数据节点）。**"实现麻烦""收益不大""调用方用不到"都不成立。**
2. 必须证明**调用方可完成的任务集合不因缺该面而减少**——导出满足：`export run`
   一次顶层调用即可完成，Agent 卡直接交接该命令并声明发现后 1 次。
3. 判定要写进台账该行（记"设计不适用"而非"无"）并在此处留下理由，可被后来者推翻。

当前只有治理导出、response-bound 素材文件这两类直接文件 effect，以及下文登记的 Segment mutation
Plan 面适用此例外；素材文件的逐条证明登记在本页第三轮 Issue 19 裁决。
**新增例外必须同时满足以上三条并在此登记**。

## 使用成本：参数化程度审计结论

### Workspace 参数化 Plan 裁决（2026-08-14）

**判定应做，且只做 Plan 构造机制。** 单 operation recipe 无法表达重复的多节点 DAG；要求分析师
或 Agent 每次只换日期却重新生成完整 Plan JSON，是调用成本而不是业务语义。调用方自行写模板脚本
虽能绕过，但会把类型、路径、Plan schema 与 fail-closed 校验拆到仓库外，无法形成机器合同。

本轮新增 workspace `plan_recipes`：参数显式声明 `type/format/required/bindings[]`，只向 literal
Plan 已存在的 `/nodes/<index>/request/...` scalar 叶子写值。展开后的对象进入唯一 Plan v1
校验/adapter preflight/执行路径；不增加 Plan node kind、adapter、worker、线程池、请求或 envelope。
手写 `plan run --input`、DAG/依赖/foreach、全局 `PlanConcurrencyBudget`、partial 与退出码聚合保持。
缺参、类型/格式错或 workspace 绑定路径不存在均在 adapter 构造/执行前以
`PLAN_RECIPE_INVALID`、local/4 失败；dry-run 零执行、零网络。

机制进入 SDK；具体步骤、业务口径与模板实例继续留在调用项目 workspace。仓库只保留虚构形状示例，
不内置“日常经营检查”等模板。不为 Agent 增加发现卡：workspace 实例是调用方私有内容，Agent
发现面仍只描述仓库能力；已知 recipe 名时，CLI/SDK 的显式参数合同已经可机械填写。

判据是**改一个参数要不要改代码**。20 个真实分析场景实撞（11 次 HTTP，无权限失败与合同漂移）：
零成本 11 / 有成本可接受 4 / 需改代码 5。

其中旧场景 4“同一分析跑多个 App”已按真实使用频率从“有成本可接受”改判为产品缺口并收口。
首批选择事件趋势、漏斗、留存、属性分布四类 compact Analysis：它们都是同一 literal spec 只替换
App，结果天然逐 App 独立。`gravity.analysis-query-batch.v2` 每项把标量 `app` 改为显式非空
`apps` 数组，内部机械展开为现有同层 `analysis_query` Plan 节点；展开后最多 32 个组件，拒绝重复
App（包括 alias/ID 解析到同一 App）和 `"*"`。结果只附 `query_id/app` 身份，不做跨 App
排序、TopN、汇总、差异或比率计算。

首批没有纳入 scatter（跨 App 散点比较频率低）、Multidim（物理 metadata/分页预算模型不同）、
Saved/Dashboard/Template replay（每个 App 还要独立解析引用）、period compare（一个节点已含双窗口）、
分群/订单/变现/推广/素材/SQL（各有引用、单日、平台或调用项目产品合同）。这些保持现有单 App 或
显式同层 Plan 形态，不从本轮结果层外推通用多 App 抽象。

并发没有新线程池或默认值：v2 仍只构造同层 Plan 节点，adapter 每节点固定 `max_workers=1`，
共享 `PlanConcurrencyBudget`。fake transport 实测 3 个 App 在预算 1/3 时请求集合都恰为同三个
App，峰值分别为 1/3；一个 App 权限失败时另外两个继续，外层为 `partial` 且失败组件保留 App。
因此总上游请求量是逐 App 单跑请求集合之和，只提高峰值在途数。v1 `app` 输入和 v1 result 分支
保持原样；既有五类单 App batch 回归继续通过。

### Analysis typed primitives 裁决（2026-08-16）

对标 Mixpanel Headless 后，裁决是**有真实但很窄的组合缺口，应做 Analysis 领域层，不做通用层**。
五类 compact Spec 已共享 condition/metric/event-step 机器 schema 和同一个 compiler，所以查询能力与
合法形状没有缺口；但公开 SDK 只接受 `Mapping`，调用方复用 filter/metric/现有 segment reference
仍靠仓外 dict 复制。`plan_recipes` 已覆盖 App、日期和预先存在 scalar filter value 的 typed 替换，
batch v2 已覆盖同一 literal spec 的显式多 App 扇出；二者都不能追加 condition array item、替换完整
metric object，或把同一受控片段放入另一 kind。这里是程序内结构组合缺口，不是 Plan 参数化缺口。

本轮新增 `analysis_primitives.py`：`AnalysisFilter`、`AnalysisMetric`、`AnalysisCohort`、
`AnalysisStep`、`AnalysisSpec`。`AnalysisCohort` 只表示现有 `user_segment` 引用，不提供 cohort CRUD
或自由规则；`AnalysisSpec` 是不可变 `Mapping` wrapper，可无损包装旧 spec，并只开放已登记位置的
App/日期/metric/filter 增量操作。位置错误在构造期失败；依赖 kind FieldPolicy 或 live metadata 的
语义仍进入唯一 compiler/preflight 后 fail closed。typed/literal 五类回归固定同一 `query_id` 后，
编译出的 operation input 按实际 JSON 序列化逐字节相等。

typed 构造面新增 25 个 caller-recoverable 错误起点，全部有字段路径和替代动作，分档均为 B；
actionable-error inventory 从 `974 + 25 = 999`，分档从 `A/B/C = 218/400/356` 变为
`218/(400+25)/356 = 218/425/356`。这是新增公开输入边界的完整库存更新，不删除扫描范围、不改
分档规则，也不把错误藏到未登记 helper。

结果层不改。现有 envelope 的 schema/status/operation 与 batch `node_id/query_id/app` 身份对可靠比较、
空值和 partial 对齐有帮助；调用方需要自行拆出各引擎 `result.data`，这是保留异构受治理结果的有意
边界，不引入 pandas/DataFrame 依赖，也不做跨 App merge/sort/diff。没有新增 registry、DSL、Plan
binding、adapter 分支、线程池、operation、CLI 参数、envelope 或退出码；`plan_adapters.py` 净增长
`0`。台账可复算为 operation `185 + 0 = 185`，stable `176 + 0 = 176`，Analysis journey
`既有行 + 0 = 既有行`。

**底层参数化总体健康**，不需要通用化改造。日期窗、周月粒度、分组（≤20）、多指标（≤50 步）、
AND/OR 条件、漏斗步数与窗口、留存 `offset`（1–365）、Multidim 常见指标维度都是改参数即可。
留存 D7→D8 零开发，推广平台硬编码是 operation 合同必要绑定，推广指标用开放排除法——
这三处均不计缺陷。

**真实缺口只有一类：字段已在 operation 合同与 FieldPolicy 中登记，compact Spec 却没暴露。**
调用方因此被迫从产品入口掉回手写 raw wire JSON，而该结构不自描述，Agent 无法机械填写。

**已补齐 4 项，2 项证据不足保持关闭：**

| kind | 控制项 | 判定 |
| --- | --- | --- |
| Event | `return_hierarchy` | **已暴露**，在线 probe `success` |
| Retention | `query_item_before_after` | **已暴露**，在线 probe 合法 `empty` |
| Funnel | `window.unit=today`（value 锁死 1） | **已暴露**，在线 probe `success` |
| Scatter | `zone.type=dispersed`（不接受 ranges） | **已暴露**，在线 probe 合法 `empty` |
| Event | `custom_query_item_list` | **不暴露**：artifact 0 实例，最小公式 probe `semantic_error` |
| Event | `split_event` | **不暴露**：通过本地 FieldPolicy 但**上游 `semantic_error`** |

`split_event` 的结果值得单独记：它**通过了我们的 FieldPolicy 却被上游拒绝**，
说明本地策略层在这一处比上游宽。这不是 fail-closed 失效（请求确实发出并被拒），
但意味着"FieldPolicy 接受"不能当作"上游可用"的证据——本轮两项未暴露的判定正基于此。

取证路径记录：artifact 语料**六个字段全部 0 非空实例**（扫 32 个模板，最小 App 看板树为空），
所以"先挖 artifact"这条路本轮没起作用，最终靠最小在线 probe 定的。语料扫描成本 74 次 HTTP，
下次做同类取证要先估成本。

补齐纪律（保留）：取不到生产证据的 fail-closed 不暴露；逐字复用 FieldPolicy 已有结构直接编译；
**不建通用公式 DSL、不接受任意表达式**；新字段必须有默认值且默认行为与现状完全一致
（已用五种 kind 的相同 compact Spec 做结构差分验证，归一化 `query_id` 后 inputs 完全相等）。

Funnel、Property、Scatter 顶层无差集；Property 本身没有日期窗，不算丢参。

**已作废的结论**：审计曾把"Event 双窗口"列为头号缺口，该判定基于 `7d5bdb1`，
早于跨期对比合并。`analysis query --compare-start/--compare-end` 已覆盖，
**不要新增 `date_ranges`**——那会造出第二条语义重叠的路径。上游原生 `date_list`
支持双窗口且 1 次请求即可（本轮在线证实），比现有两次查询+本地 delta 省一次请求，
但这是优化不是缺陷，且 operation 硬上限为 2，三期以上只能客户端拼接。

**三处单日限制均为上游已登记合同限制，不是产品阉割**：`analysis.order_detail.list`（订单目录、
拆单追踪父链）与 `analysis.segment.uid_result.list` 都只有单数 `date`。7 天订单目录的正解是
一个 Plan 放 7 个同层节点并发，不是串行启 7 次 CLI；结果按日期节点分开，不混成一个目录。

**detail 元数据成本已核清**：订单产品提交 `d1983c2` 已对精确固定 profile 短路，D27 的
`ba01a3d` 也让变现固定 allowlist 直接本地校验。最小空日两者实测均为 1 POST、0 metadata，
7 个同层订单节点为 7 POST。缓存仅进程内：raw 动态路径两个独立进程各 4 HTTP；同进程连续
两次为 4+2，7 节点为 16（属性目录各 1、分群 7、订单 7）。raw detail 的动态
fields/conditions/order 仍必须加载实时 metadata，未登记字段继续 fail closed。

**旧审计"3 HTTP"是路径错配，不是未解之谜**（此为推断，原始调用未保存）：`d1983c2` 经核
确在审计基线 `7d5bdb1` 的祖先里，fast path 当时已生效；而审计账本那一行标的是
"Order Detail"，即 `analysis detail --kind order` 这条 **raw 路径**——它按设计就要加载 metadata
校验动态字段。产品路径 `analysis order directory` 用固定 profile，实测 0 metadata。
**教训：度量使用成本时必须写清走的是产品入口还是 raw 入口，两者成本不同是设计，不是缺陷。**

**Multidim 使用成本**：`--start/--end/--time-dim/--metrics/--dimensions/--media/--multi-days`
已覆盖常见变化，无需完整 JSON。仍需手写物理 JSON 的是 `filters[]`、`custom_metrics_list`、
`relate_dims`。**多个扁平 filter 的 AND/OR 组合语义上游未经证明**，产品 schema 无 `filter_logic`；
证明不了就只支持可确定语义的形态，不得假定默认值，更不得为此造通用布尔 DSL。

## D35 / F40 归因结果合同（2026-08-16）

### 提案与静态控制流

本轮先复核 census 同快照前端 bundle 的 hash，并沿 `Measurement` 页面从状态初始化、目录装载、
`Gt` builder 到每个 `/adreport/attribution/` 调用点逐字段恢复完整请求：区分固定字段、页面默认值、
调用点枚举、App/项目目录绑定、配置返回值与调用方筛选，明确 `undefined` 省略和空数组保留规则。
在 builder、值域来源和父依赖形成可复核静态证据前，生产业务请求保持 0 次。

静态证明完成后，只从前端自然调用形状中选择单日、无筛选、无项目、无自定义拆分的最小形状，
按 App catalog 顺序串行验证；同一 `(App, 请求形状)` 仅发一次，不重试、不翻页、不扩窗，取得首个
成功或明确空响应立即停止。若服务端仍拒绝，保留具体错误路径与值无关响应形状，并把下一步收敛到
一条未证明事实。只有 D35 的请求、响应、分页和错误合同成立，才提升 stable operation 并接通
Core / CLI / SDK / Plan / Agent card；随后再以同样证据标准判断 F40 的标识来源、请求绑定、分页和
响应合同，不能用字段投影已放开替代这些事实。

`attribution.attribution.query` 的**前端 builder 已完整恢复**（从与 census 快照哈希匹配的
`Measurement-BV1Ulzee.js` 中的同作用域 builder `Gt`），16 个顶层字段：
该 bundle 的 SHA-256 为
`fb9d486e882c783709794cecce8fb72849151e70eea26537603d7b222a7216ed`；入口
`index-D9HAN43D.js` 为
`aa67659c360861d73309b2f9ca93ac15d95d6b39a092912a32cb72b9f1662d6b`。

`child_type`、`date_list`、`metrics_list`、`dims_list`、`report_level`、`statistics_caliber`、
`decimal_point`、`app_id`、`project_id`、`aggregate_app`、`multi_days`、`dims_metrics_list`、
`filtering`、`need_all_metrics`、`need_cname`、`time_zone`。

省略规则：14 个恒发；`project_id` 仅 truthy 时发；`dims_metrics_list` 仅非空时发，
二者为 `undefined` 时由 `JSON.stringify` 从 wire 省略。`filtering` **恒含 8 个数组**
（`ad_platform_list`、`os_platform_list`、`channel_list`、`version_list`、`operator_list`、
`turbo_promoted_object_id_list`、`aid_list`、`advertiser_id_list`），无值时发 `[]` 而非
`null` 或省略。固定值 `child_type="measurement"`、`need_all_metrics=true`、`need_cname=false`；
源码默认 `report_level="day"`、`aggregate_app=false`、`multi_days=30`、`decimal_point=2`、
`time_zone="utc"`。

**2026-08-16 审计纠正：旧“服务端拒绝”判定不能成立。** 当时 2 次最小 POST 虽被记成
`semantic_error`，evidence 只保留 shape/fingerprint，没有保存 `code`、`msg` 或 `extra.error` 原值；
同时旧 prober 把任意非空 `extra.error` 一律当拒绝。已完成归因线的独立 committed evidence 使用精确
builder 记录到 `code=0`、`msg=成功`、`extra.error=无数据` 和空聚合容器，随后同形状取得非空成功，
证明该登记值语义为明确空，不是参数错误。它不能倒推出旧两次响应的具体正文，但足以撤销旧标签对
“缺服务端必填/值域”的证明力。

语义审计本身未据并行工作提升 D35；随后归因线用会保存协议判据的新 evidence 完成重新取证并闭环 D35。
F40 的旧 D35 依赖理由同步失效；其自身标识来源、请求绑定、分页和响应合同仍需独立证据。

值域与依赖来自同一控制流，而不是猜测：`app_id` 取 App catalog 选择项，若页面未来设置
`connect_app_id` 则优先使用它；当前 bundle 只观察到初始化/重置为 `0`，没有正值赋值。直接 App
把 `project_id` 置为 `0`，所以最小请求省略它；页面没有归因方案 ID 的装载或选择父链。
`date_list` 来自调用方日期区间；`report_level` 的页面枚举是空值/day/week/month，最小为 day；
`statistics_caliber` 的四个实际调用点只用 `user_activated_time` 或
`behavior_occurred_time`；`time_zone` 来自页面时区设置（默认 utc，也可 ortz）；精度开关只产生
2 或 4。筛选值分别来自平台、OS、渠道、版本、运营商、推广对象、aid、广告主目录；最小请求不猜值，
八项均为空数组。`dims_metrics_list` 来自调用方额外拆分，空时省略。

四个前端调用画像已逐一登记为同一受控 operation 的有限输入：

- `attributed_registrations`：`AppRealRegisterCnt`，`date/ad_platform`，激活时间口径；
- `activation_and_pay`：`AppActivateStandard/AppGamePayAmountReportingStandard`，
  `date/ad_platform`，行为发生时间口径；
- `activation_conversion`：三种 `AppActivate*`，`date`，激活时间口径；
- `overview`：`AdShow/AdClick/AppActivateStandard/AppRegisterStandard/`
  `AppGamePayUserCntStandard`，`date`，激活时间口径。

### 生产账本与 D35 裁决

生产共 **3 次业务 HTTP**，全串行、无重试、无翻页、无扩窗，也未触发鉴权刷新：

| 次序 | 目的 | 状态 | 结论 |
| --- | --- | --- | --- |
| 1 | `app.list` 目录事实，第一页 | HTTP 200，7 个候选 | 只在内存按目录顺序取 App；未保存名称 |
| 2 | 首个 App，单日，`attributed_registrations` | HTTP 200；`code=0`、`msg=成功`、`extra.error=无数据` | 明确空；五个数据容器均存在，列表均空 |
| 3 | 第二个 App，同一单日同一形状 | HTTP 200；`code=0`、`msg=成功`、`extra.error=""` | 非空；`columns=3/items=2/static=21/total=1`，立即停止枚举 |

旧不可变 evidence 只保存 `semantic_error` 分类、shape fingerprint 和容器计数，**没有保存**
`msg` 或 `extra.error` 的实际正文，因此不能追认某个服务端字段拒绝原因。新证据反而证明精确 builder
是合法请求，并证明 `extra.error="无数据"` 是成功的明确空。故旧标签不足以证明“服务端拒绝 body”；
本轮合同把 `code in {0,200}` 且 `extra.error in {null,"","无数据"}` 视为非错误，其他值 fail-closed。
这既保留了未知拒绝，也修正了明确空被误分类的风险。

**D35 已闭环。** `attribution.attribution.query` 晋升 stable v1，公开已观察的全部
`columns/items/static/tips/total` 字段，并以动态指标字段绑定有限前端画像；分页为 none。Core
`attribution_performance`、CLI `gravity attribution performance`、SDK、Plan
`attribution_performance` 与 Agent card 共用 `gravity-insight.attribution-performance.v1`。
已知输入 1 次顶层调用、未知 capability 2 次；未知 App 的离线默认场景为 3 次，均由
`gravity.agent-call-bound.v1` 声明。四个内部 HTTP 共享一次 bounded batch 与 Plan worker 租借，
不把内部请求数误算为调用方调用次数。

### F40 精确剩余事实

hash-matched `Device-TemCRn-D.js` 和 `userSearch-Bhwew5eC.js` 证明：搜索 route 的 body 是
`{app_id,key_word:trimmed-or-undefined}`，响应消费 `data.attribution_list`；测试设备父目录 body 是
`{app_id,page:1,page_size:1000}`，响应消费 `data.list`。调用方选中一行后，详情 body **仅为**
`{app_id,device_id:Number(selected.data.list[].id)}`；这里的 `device_id` 是登记测试设备行的内部 id，
不是可猜的原始设备标识。详情无服务端分页，前端完整消费 `device_white/attribution_list/`
`postback_list/pay_list`。
两 bundle 的 SHA-256 分别为
`5a8a9ad1ee358899bbcbf09fc43711285c51015667431e5fe1892029a4bc3aae` 与
`8a8fda10088a31c241ebd1e96624d8daf9a36e289f09bcf78204398a8c888069`。

F40 仍完全缺失：本任务只授权枚举 App catalog，没有授权枚举用户级测试设备目录，也没有调用方提供的
真实父行 id，因此生产请求为 0。还差两条具体事实：一条 caller-authorized `data.list[].id`（且父
`app.testing_tool.list` 合同须 live 验证），以及一次详情成功或明确空响应，用于登记四个容器全部字段与
类型。最小下一步是调用方选定并授权一个真实测试设备父行，只发一次详情请求；不得猜设备值。

本线新增 **4 个** caller 可恢复错误点（App、日期区间、worker 上界、Plan request shape），
**4 个均为 A 档**；本次集成树从 `1024 = 220 A + 434 B + 370 C` 变为
`1028 = 224 A + 434 B + 370 C`。技术债清单已复核：领域 SDK mixin 与 fixed-composite family router 吸收新面，
共享入口的 SLOC/复杂度 ratchet 未上调，也没有新增可证明的结构债。

### census 提取器的已知能力边界

那两次未解析 load 卡在 `census/params.py` 的 `_infer_expression`：**无法内联函数调用**
`Gt(...)`，内存形状标为 `unresolved_body_expression`，导致 `body_parameters=[]`。
同 route 另 3 个 occurrence 卡在条件 callee `(e===1?Ie:ze)(...)`，标记
`load_alias_has_no_static_call`。

**杠杆统计已完成，结论是不修。** 同一快照下，条件 alias 影响 97 条 route、123 个 occurrence；
其中 49 条是写、23 条已覆盖、7 条 auth/proxy、1 条 export，只有 17 条未覆盖读。函数调用的
`unresolved_body_expression` 影响 60 条 route、82 个 call site；45 条是写、7 条已覆盖、4 条 export、
3 条 auth/proxy，唯一未覆盖读就是 D35。该 reason 只存在于内存 `_Shape`，序列化后折叠为
`analysis.unresolved_calls` 计数，所以在 `route-params.json` 中 grep 为 0；这仍解释静态提取边界，
但不再为已撤销的 D35 服务端拒绝结论背书。

与台账交叉后，15 条完全缺失、12 条部分闭环中，**当前阻塞根因属于这两类提取失败的均为 0**。
D35 的前端 16 字段已经人工恢复；旧服务端阻塞已在 2026-08-16 语义错误审计中撤销并待重新取证。
默认值字典已有另一 occurrence 提取出
`app_id`/`subject`，卡服务端必填语义与响应投影。其余相交项是写、已覆盖 route、helper、export，
或另有父链/非空样本/隐私/产品面 blocker。实现函数内联和条件 callee 不会解锁排期动线，故保持
现有静态分析边界，不为潜在未来收益扩张成通用求值器。明细见
`tmp/codex/census-extractor-leverage/stats.md`。

## 并发

已有 28 条并发路径、7 种模型，底层受业务槽 24、SQL 槽 2、host 令牌桶与 429 cooldown 约束。
17 条可增强候选中收益最大的 Promotion Performance（≤21 平台）、Dashboard Analysis（≤32/64 图表）、
Analysis Context（13 来源）已接入 Plan 全局预算租借。

租借接口把 Plan execution 已占的一槽计入可用 worker，额外容量只做非阻塞 try-acquire；同一 execution
嵌套租借复用已持有容量，退出或异常均归还，因此多个 Plan worker 不会等待额外槽而自锁。adapter
不拥有第二个预算，领域 core 继续复用既有 bounded batch。fake transport 在 Plan 预算 6 下记录到：
Promotion 21 请求峰值 `1→6`、Dashboard 32/64 图表总请求分别 35/67 且图表阶段峰值 `1→6`、
Analysis Context 13 请求峰值 `1→6`；串并行请求 identity 完全相同。21 平台中 3 个失败的结果保持
`partial`，18 个成功/空组件与 3 个逐平台错误/能力缺口均保留，Plan 依赖仍把 partial 视为失败。

**约束**：不要给 adapter 增加独立 worker 默认值或私有预算。所有增强保持上游总请求量 `1x`，只提高
峰值在途数。SQL 硬上限 2 有 4 并发实测失败证据，不提高。分页未知总页、父子依赖链、导出
`create→poll→download`、探测链不并发。fake transport 证明预算与语义，不代表生产 24 并发已完成
soak；真实吞吐、尾延迟和 429 频率仍需在发布流程中做受控长时观察。

## 留出测试：关键词式自然语言路由不泛化（2026-08-15）

**这是本轮最重要的一次测量，它同时推翻了一个达标声明和我自己写的判据。**

### 测量

`nl-reachability` 线按新判据做完重验与修复，自报 baseline `6 / 7 / 19`
（中英都达标 / 只有一种语言 / 都不达标），修复后 `32 / 0 / 0`，零回归。
反自证纪律确实执行了：问法 19:55:02 冻结提交，源码 20:37:02 才动，中间隔 42 分钟，
且问法明确声明取自台账的分析师任务描述与调用方文档，未读 recognizer。**这些都属实。**

但我用**它没见过的 20 条问法**（同样的动线，我自己写，刻意短、口语化）做留出测试：

| | 修复前 `dev@23422c2` | 修复后 `codex/nl-reachability` |
| --- | --- | --- |
| 命中带候选 | 4 / 20 | **4 / 20** |

**一条都没变。** 逐条输出也完全一致，包括"新用户第二天还回来吗"和"用户都集中在哪些城市"
两条**返回 `success` 但候选是 `analysis.account_user.list` 这类 raw operation**
——路由错，两边一模一样。

### 判定

**冻结纪律挡住了浅层自证（从关键词表反抄问法），没挡住深层自证（调到那 94 句通过为止）。**
`32 / 0 / 0` 对那 94 句是真的，**只对那 94 句是真的**。

**这是我判据写得不够，不是执行线的问题。** 判据只要求"中英各一条自然语言问法"，
一个固定题集必然可以被拟合。同类错误本轮已经犯过两次
（"不换 App"挡住了分群发现、"不重试"挡住了发现链重跑），根源相同：
**我把约束写成了具体动作，而不是要达成的性质。**

### 判据再修正

Agent 面达标必须用**留出集**判定：题面在修复完成后由**未参与修复的一方**新写，
执行线事先不可见。冻结题集只能用于开发期自检，不能作为达标证据。

### 更重要的推论

**关键词式意图路由不泛化——这是我们自己的实测数据，不是行业趋势推论。**
真实用户打的是"登录数最近怎么样"，不是"帮我看看登录事件这周每天的次数，按渠道拆开"。
前者不含分析类型信号，关键词层拿不到；而一个拿到 tool schema 的宿主 LLM
处理这种语义匹配毫无压力——那正是 LLM 擅长而关键词表不擅长的事。

**因此暂停继续投入 recognizer 调优**，等并行线的 MCP 交付面可行性结论。
若改由宿主 LLM 选工具，这一层可能整体不需要；现在继续拟合题集是在为可能被替换的部件付钱。
`nl-reachability` 已完成的修复保留——它对那 94 类问法是真实改进，且零回归。

### 调研纠错：两条被推翻的前提（2026-08-15）

五条深度调研线回来后，推翻了我此前基于单次搜索片段给出的两个判断。
**这两条都曾被用作 MCP 提案的论据，必须记在这里，避免后来者继续引用。**

**一、"在位者把过滤/分组/join 丢给 LLM"不成立。**

我曾引用一段横评，称 GA4 / Amplitude / Mixpanel 这一档
"主要拉原始数据、把计算丢给 LLM，多步漏斗只能拿到 LLM 对原始事件的解读"，
并据此判定"上游预计算是我们真实且可防守的差异化，且市场已点名它是在位者短板"。

**查证结果：不成立。** GA4、Amplitude、Mixpanel、PostHog 的**当前**官方 MCP
都提供平台计算的漏斗/留存工具。原横评可能基于更早的版本快照，但该快照无法复现。

**后果**：不能再用"我们算、他们不算"作为差异化论据。
仍然成立的是另外两点——text-to-SQL 最危险的失败是**成功执行但语义错误**
（FLEX、Uber QueryGPT 有直接证据），以及主流平台正把重心从 text-to-SQL
转向受治理指标与可追溯查询——**方向判断没错，但支撑它的那条论据是假的。**

**二、"5–15 tools per server"不是有证据的标准。**

它只是实践者启发式，找不到原始实验或同行评审出处。
真实规模跨度极大：ThoughtSpot 8 个，PostHog 844 个。
也没有可跨模型跨任务复现的"工具数—准确率曲线"。

**后果**：14 个 tool 的草案不能靠"落在最佳区间"自证，
必须用本仓库自己的问题分布和目标宿主模型做 A/B。

**顺带澄清一个计数**：本段调研快照有 **20 张 composite 卡**；2026-08-16 派生层新增 1 张，当前为 21 张。
此前流传的"15"是 roadmap 里**完全缺失动线**的条数，被误当成卡数引用。

**三、ThinkingAI 的 MCP 属 `[厂商宣称]`，不可复现。**
官网指定的 npm 包在公开 registry 返回 404，完整 tools/schema 无法验证。
官网首页确实以 MCP 为主打，但那是营销事实，不是技术事实。

### 定位的修正

21 家样本中 20 家有平台内嵌 AI，**15 家同时提供 MCP / API / CLI / Skill 等外部入口**。
与本仓库最接近的是 Mixpanel Headless 的 typed Python SDK/CLI——**但它由上游厂商自己维护**。

**所以本仓库真正的位置是：给一个尚未开放 Agent 面的平台做第三方客户端。**
这是个成立的位置，但它的可持续性风险与"我们算得比别人好"完全不同——
上游一旦自己开放 Agent 面，差异化基础就变了。这一点应写进任何 MCP 立项论证。

### 对 MCP 试点验收判据的修正（2026-08-15）

并行线的 MCP 可行性报告给出的停止判据是"**冻结题集**上未达
`18/20` 首选正确、`12/20` 合法答案，或没有真实采用方，就停止并退回 schema-only"。
方向对，但**冻结题集正是上面那次留出测试证伪的东西**——该报告派发时留出结论还没出来。

**修正**：MCP 试点的验收必须用**留出集**——题面在试点实现完成后，
由未参与实现的一方新写，实现方事先不可见。数量与阈值不变。
冻结题集只能用于开发期自检。

同一条纪律现在适用于所有"自然语言可达性"类判定，不限于 MCP。

## 闭环判据修正：Agent 面必须自然语言可达（2026-08-15）

**两条独立审计线同时回来，结论表面矛盾：** `closure-audit` 判定 32 条闭环声明
**全部成立（不成立 0 条）**；`agent-usability` 同时报出 20 个真实问题里
**8 个第一次调用就路由错**。两边都没错——它们对"Agent 卡可达"的理解不同。

**实测坐实**（在 `dev@e10b006` 上，可复现）：

```
gravity agent "analysis.query.spec:property"   → success，命中该卡
gravity agent "property distribution"          → capability_gap
gravity agent "属性分布看一下"                   → capability_gap
```

卡确实注册了，自然语言中英两种问法都够不着。而台账把
「看用户或事件属性的分布与聚合」记为**已闭环、四面可达**。

**判定：原判据的 Agent 面是自证的，作废。**

"Agent 卡可达"此前实际检验的是"卡在仓库里注册了、精确 selector 能命中"。
**而卡本来就定义在仓库里，这个检验必然通过**——它是一个恒真命题，
从未回答唯一重要的那个问题：**一个只会说人话的 Agent 能不能找到它。**

### 新判据

Agent 面达标 = **至少一条中文自然语言问法和一条英文自然语言问法，
第一次调用即返回该动线的正确产品卡**。以下也算达标终点：

- 语义确有歧义时返回 `MULTIPLE_INTENTS`（且候选里含正确产品）
- 能力确实缺失时返回带可执行 next action 的 capability gap

**精确 selector 命中不再计入达标。** 问法必须是分析师会真的说出口的话，
**不得反向从 recognizer 的关键词表里抄**——那会把测试变成自证，是这条判据最容易被架空的方式。
每条判定要留可复现命令。

### 后果

- **32 条已闭环的 Agent 面需按新判据重验。** 重验完成前，"32"这个数字对 Agent 面不成立；
  CLI / SDK / Plan 三面的判定不受影响，`closure-audit` 对那三面的复核仍然有效。
- 台账「四面可达」列的 Agent 一栏，含义随之改变，需逐行重填。

**为什么是收紧而不是放宽：** 目标写的是"对 Agent 友好"。
**一个 Agent 拿不到的能力，对这个目标而言等于不存在。**
把判据放宽到"卡注册了就算"，等于用一个恒真检验粉饰产品目标没达成。

## MCP 交付面可行性裁决（2026-08-15）

**裁决：应该做一个可撤回的本地 stdio 实验，但现在不把 MCP 定为强制第五交付面，也不建设远程
HTTP/OAuth。** 完整论证、14-tool 草案、反方和分阶段判据见
[MCP 交付面可行性报告](mcp-feasibility.md)。

本裁决不是由同行采用 MCP 推出来的，而是由本仓库已经测出的缺陷触发：20 个真实问题中首调错路由
8 个，自然语言到合法答案只完成 4 个。MCP 让宿主模型基于 tool schema 选择结果型能力，可以直接
检验它是否优于手写 recognizer；而已闭环的漏斗、留存等仍由受治理的上游/领域 composite 计算，
不把原始事件、任意 SQL 或 185 个 raw operation 交给模型。

题设所称 15 张固定 composite 卡不是当前事实：`composite_capability_inventory()` 在该调研基线返回
**20 张**（派生层落地后为 21 张），已超过每 server 5–15 tools 的经验区间；卡中的提示型 schema 也不全是合法 JSON Schema。
因此不能把卡 1:1 发布为 tools。候选面从 47 条计数动线重算：

```text
47 = 32 已闭环 + 0 部分闭环 + 15 完全缺失
32 = 7 核心分析 + 8 上下文/资产 + 3 报表 + 6 营销
     + 4 用户/交易 + 1 SQL + 1 素材导出 + 2 离线发现
14 tools = 6 + 3 + 1 + 1 + 1 + 1 + 1
2 条离线发现 -> resources
```

15 条完全缺失不发布空壳，3 条明确不计数的 legacy/便利/重复面不纳入；raw
`gravity run <operation>` 不进 MCP。账面没有变化：operation `185 + 0 - 0 = 185`，计数动线
`47 + 0 - 0 = 47`。

首轮若实施，只做 6 个核心分析 tool、App/分析词表 resource 和 stdio；不改共享 spine，不改
`gravity agent`。旧自然语言层选择**保留但冻结**：不再扩关键词和 owner，只修严重回归；完整 14-tool
面在两个真实宿主通过冻结题集且调用方迁移后，才进入弃用评估。毕业线为首选正确至少 `18/20`
（当前 `12/20`）、合法答案至少 `12/20`（当前 `4/20`），并有一个现有调用方试用和第二个独立
采用意向；否则停止 server，退回 schema-only 交付。

现有 envelope、三态与 fail-closed 可由 MCP `structuredContent` 无损保留；CLI/SDK invocation
call-bound、进程退出码和 caller/upstream/local 分类没有 MCP 原生等价物，必须继续留在 Gravity
envelope，毕业后另定义 MCP 调用单位，不能改名冒充原合同。远程多用户还需要逐用户 Gravity 身份或
明确单租户 service identity；在 owner、IdP、租户和审计模型成立前，OAuth 没有实施价值。
## 47 条动线重验与修复结论（2026-08-15）

**提案：**先只依据分析动线和调用方产品文档冻结 47 条动线的中英自然语言问法，独立提交后
才读取 recognizer；随后逐题做第一次离线调用、在领域 owner 内补正向证据或目标 gap、最后用原题
全量回归。冻结题单提交为 `df363c4`，baseline 提交为 `d1b18c6`；工作底稿为
`tmp/codex/nl-reachability/phrasings.md`、`baseline.md` 和 `after.md`。

**baseline：**32 条已闭环中，中英都达标 **6**、只有一种语言达标 **7**、两种语言都不达标
**19**，即 `6 + 7 + 19 = 32`，按语言只有 `6 × 2 + 7 = 19 / 64` 条首问达标。15 条完全缺失
中，正确可执行产品为 0，目标明确且带 next action 的 gap 也为 0；实际错误包括通用 Analysis
handoff、generic gap、相邻产品、raw operation 和两组伪 `MULTIPLE_INTENTS`。

**修复后：**32 条已闭环成为 **32 / 0 / 0**；原先达标的 19 条语言问法全部保持，回归为 0。
J19 在当前 worktree 没有对应 workspace product，按新判据返回专属
`WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` gap 与 `gravity sql products` next argv。15 条完全缺失仍没有
任何可执行结果，故没有漏记的已完成能力；但中英首问现在都返回各自动线的专属、可行动 gap，Agent
一面为“有”，其他产品面和合同阻塞不变。

修复只增加/收紧领域 recognizer、固定快照卡、class-level `metadata:search` handoff 和缺失动线 gap；
`agent_intent_routing.py` 的集中裁决逻辑 **0 处修改**。J15 素材表现与 J21 看板重放的 baseline
`MULTIPLE_INTENTS` 都是正向证据过宽造成的伪歧义，已在相邻 owner 内收紧；没有删除负向词、降低
selector 精确度或把多个意图改成任选一个。冻结题单语义均明确，最终没有一条依赖
`MULTIPLE_INTENTS` 达标；显式双产品冲突的既有回归仍通过。

台账状态净变化为 `47 = 32 / 0 / 15 + 0 / 0 / 0 = 47 = 32 / 0 / 15`：没有已闭环动线掉出，
也没有完全缺失动线因本轮获得可执行结果而提升。变化只发生在 Agent 一面：32 条已闭环逐行重验为
“有”，15 条缺失逐行由“无”改为“有（目标 gap）”。本轮 94 次发现调用全部
`offline=true/network_called=false`，生产 HTTP **0 次**，无重试、翻页、扩窗或上游任务。

## 可重复的 Agent 可用性基线（2026-08-15）

> **v1 历史记录。** 本节原 47 条/470 题数字保留用于追溯；对应密封 key 已丢失，旧
> `holdout.sealed.json` 不可恢复，且计数漏掉表末 Issue 19。当前可操作结论见下方
> [留出集重建与可操作 key 托管](#留出集重建与可操作-key-托管2026-08-15)。

**提案：**不再用卡注册或单一自然语言命中率自证；以 47 条 analysis journey 为评测单位，分别
度量首次产品选择、参数来源可填、离线可验证终点、严格 `pass^4`、错误恢复和调用成本。工作提案
位于 ignored `tmp/codex/agent-eval/proposal.md`。题集先于实现观察独立提交：
`30ac62e test(agent): freeze usability evaluation suite`；之后才读取 recognizer，并在
`e72a354 feat(eval): add layered agent usability runner` 加入装置。产品 `src/gravity_sdk` 相对
`dev@ac03a0f` 无差异，装置没有修 recognizer、路由或产品行为。

题集版本为 `gravity-agent-usability-2026-08-15.v1`，覆盖当前 **47 条**动线，每条 10 题：
中文普通 3、英文普通 3、中英相邻产品边界各 1、中英缺信息/能力缺口各 1。因此总数可复算为
`47 × (3 + 3 + 1 + 1 + 1 + 1) = 470`；开发/留出各取每条 5 题，均为
`47 × 5 = 235`。按表述家族切分，不把同一句随机拆到两边。题意只来自
`docs/analysis-journeys.md`、`docs/agent-workflow.md` 和真实分析场景；题集提交前没有读取
`agent_*.py`、selector 或路由测试，也没有调用 recognizer 看反馈。suite manifest 固定 source
revision 与三份内容 hash；产品源树实测 hash 为
`b7fab15af01074c267313ce017843c530f33e249b222ede074264064c5449d51`。

### 分层基线

在产品树 `dev@ac03a0f` 上，合并开发/留出 470 题、每题独立运行 4 次，第一次运行的分层结果是：

| 层 | 通过 / 分母 | 判定与不能外推的部分 |
| --- | ---: | --- |
| 首次产品选择 | **314 / 470（66.81%）** | 只认第一张正确产品卡或该缺失动线的专属 gap；失败 156 = 23 个伪/未解歧义 + 34 个无候选 + 55 个错误/generic gap + 44 个错误产品。 |
| 参数来源可填 | **221 / 221（100%）** | 只在正确产品卡已到达时计分；要求每个 required input 都在 missing/template 中机械暴露，App/引用/物理字段等目录输入另须由 `call_bound.input_sources` 覆盖。另有 249 题不适用或未到达，不能把本行写成全体 470 题参数无问题。 |
| 端到端离线终点 | **93 / 150（62.00%）** | 只计 14 条缺失动线的 140 题，加当前 workspace 未配置 SQL 产品的 10 题；必须得到精确 gap、非空 next action 和 `offline=true/network_called=false`。失败 57；其余 320 条稳定读取会触发生产 HTTP，按零网络约束跳过，dry-run 不冒充答案。 |
| 重复可靠性 | 产品选择 `pass^1 = pass^4 = 314 / 470`；离线终点 `pass^1 = pass^4 = 93 / 150` | `pass^4` 是同题 4 次全部成功；不使用“4 次中成功一次”。两层不稳定任务均为 0，说明当前确定性 recognizer 稳定地成功，也稳定地失败。 |
| 错误恢复 | **4 / 5（80.00%）** | 三类真实 Plan 预检错误按 next action 修正后可验证；受控暂时失败按 next action 重试后成功；`MULTIPLE_INTENTS` gap 没有自己的 next action，不能机械推进。 |

单独切分仍没有漂亮数字：开发集产品选择 `154 / 235（65.53%）`、端到端
`46 / 75（61.33%）`；密封留出集分别为 `160 / 235（68.09%）`、`47 / 75（62.67%）`。
参数层在已到达卡上分别为 `108 / 108` 与 `113 / 113`。留出分数略高不构成泛化证明；合并结果仍有
156 个首选失败。按可评分比例最差的是端到端离线终点 62.00%，更严重的覆盖限制是 320/470
生产读取题没有在本装置中建立端到端答案基线，不能把 62.00% 外推到它们。

### 留出结构与真实防线

公开开发题在 `evals/agent_usability/cases/development.jsonl`；留出题只以带完整性校验的密封 payload
存入 `holdout.sealed.json`，32-byte key 不进 Git。一次性明文生成底稿已从 worktree 删除。runner
没有单题、留出子集或任意 prompt 参数；无 key 只能跑开发集。有 key 的正式运行也只保存 suite/
split/层级计数、失败分类和成本，不保存题面、单题 pass/fail、候选正文或 traceback。正常执行线因此
无法通过“跑分→复制失败句→加关键词”得到具体句子。

**这不是同机管理员安全边界。** 控制 evaluator 主机或 key 的人可以改 runner、附加调试器、读取
进程内存或直接解密 payload；同一 OS 身份若能找到外置 key 也能绕过。无限次观察整套聚合分数仍可
做自适应过拟合。正式发布要把 key 托管与实现线分权，只发布整套聚合并限制留出运行频率；本仓装置
只在这个边界内防止常规反馈泄漏，不作更强保证。

### 可重复性、成本与未修问题

正式全套单次（其中已含 4 trials）两次实测分别 **6.068 秒**和 **6.347 秒**；六个评分项比较
delta 全为 0。每次是 1,880 个 logical question-trials，经每批最多 32 题形成 60 次顶层
`capabilities_many`，另有 9 次恢复步骤。生产 HTTP **0 次**、socket 网络尝试 **0 次**；稳定读取题
在执行前跳过，没有重试、翻页、扩窗或上游任务。机器 JSON、人读 Markdown 和比较文件位于 ignored
`tmp/codex/agent-eval/final-run-1/`、`final-run-2/`、`final-comparison/`。

重复入口：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py run --split development --output-dir tmp\agent-usability
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --output-dir tmp\agent-usability
python scripts\agent_usability_eval.py compare <before.json> <after.json> --output-dir tmp\agent-usability
```

本单元只登记、不修以下问题：首次产品选择 156 个失败及其四类归因；150 个离线终点中 57 个未返回
目标 gap；`MULTIPLE_INTENTS` 缺少 gap 自身可执行 next action；320 个生产读取题的端到端答案与 HTTP
成本仍未在零生产装置中测得。最后一项是测量覆盖缺口，不等同于 320 个产品失败。技术债清单本轮已
复核；这些是当前可用性结果/评测覆盖欠账，不符合该页“提高结构开发成本”的登记条件，故不伪装成
结构债。

产品动线和 operation 台账净变化均为 0：`47 = 33 / 0 / 14 → +0 / +0 / +0 = 47 = 33 / 0 / 14`；
stable operation `185 → +0 = 185`，其中 stable `176 → +0 = 176`。本轮只造尺子，不用尺子改被测物。

## 留出集重建与可操作 key 托管（2026-08-15）

**提案与计数纠正：**工作提案位于 ignored
`tmp/codex/holdout-custody/proposal.md`。当前表有 51 行，其中 3 行明确“不计独立动线”；产品动线
必须按 `33 已闭环 + 15 完全缺失 = 48` 计。旧结论 `47 = 33 / 0 / 14` 实际漏掉的是表末
“按精确平台素材引用预览或下载图片/视频（Issue 19）”，变化为总数 `+1`、状态
`+0 / +0 / +1`，所以新值为 **`48 = 33 / 0 / 15`**。旧 suite 的 J41 已经是 D28
`monetization_aggregate_gap`，不能再重复添加一个 D28。operation 没有变化：
`185 → +0 = 185`，其中 stable `176 → +0 = 176`。

“重建 235 道”是旧 `47 × 5` 的派生值，与明确要求按 48 条组织不可能同时成立。v2 因此按
`48 × 5 = 240` 重建留出，并给 development 补实际漏掉的 Issue 19 五题；两侧同构为 240，合计
`48 × 10 = 480`。development 的迁移可复算为：产品选择
`154 / 235 → +0 / +5 = 154 / 240`，离线终点
`46 / 75 → +0 / +5 = 46 / 80`，参数可填保持 `108 / 108`。新增 J48 在当前被测物上 5 题均未
到达目标 gap，这只暴露既有缺口，不改变任何产品状态。

### 题面来源与提交边界

新留出 240 题全部从 `docs/analysis-journeys.md` 与 `docs/agent-workflow.md` 的产品目标、相邻边界、
缺参规则和专属能力缺口写作；没有读取 `agent_*.py`、selector、共享路由器或路由测试，也没有从
公开 development 题面改写。每条留出仍是中文普通 1、英文普通 2、英文相邻边界 1、中文缺参/缺能力
1；与 development 合并后是中文普通 3、英文普通 3、中英边界各 1、中英缺口各 1。两侧 480 个
prompt 逐字去重。

题集、manifest、来源声明和密封 payload 先以
`3cbbf14 test(eval): rebuild sealed holdout suite` 提交；该提交与最终分支均不修改
`src/gravity_sdk`，所以提交顺序能证明没有先改 recognizer 再按失败句造题。第一次整套聚合显示留出
产品选择/离线终点比 development 低 15.00/26.25 个百分点，故判为题集难度失配；custodian 只查看
“语言 × 表述家族 × 可执行/缺失”及每动线 0–5 的粗粒度聚合，不输出题面、case id、逐题结果或候选
正文。随后统一把英文普通题收敛到调用方文档产品名，并把少数失衡缺失动线收敛到台账原名；没有按
单句反馈加 token。校准过程和明文只存在于 ignored `tmp/codex/holdout-custody/`，最终密封后删除。

### v2 六层基线

产品树相对题集 source revision `7f73cf9` 无变化。每侧 240 题各独立运行 4 trials：

| 层 | development | 新 holdout | 差异（holdout − development） |
| --- | ---: | ---: | ---: |
| 首次产品选择 | **154 / 240（64.17%）** | **147 / 240（61.25%）** | **−7 题 / −2.92 个百分点** |
| 参数来源可填 | **108 / 108（100%）** | **105 / 105（100%）** | 比例 0；留出少到达 3 张正确卡 |
| 端到端离线终点 | **46 / 80（57.50%）** | **42 / 80（52.50%）** | **−4 题 / −5.00 个百分点** |
| 产品选择严格重复 | `pass^1 = pass^4 = 154 / 240` | `pass^1 = pass^4 = 147 / 240` | 两侧不稳定任务均 0 |
| 终点严格重复 | `pass^1 = pass^4 = 46 / 80` | `pass^1 = pass^4 = 42 / 80` | 两侧不稳定任务均 0 |
| 错误恢复 | **4 / 5（80%）** | **4 / 5（80%）** | 0 |

两侧各跳过 160 条会触发生产读取的题；每侧 960 个 logical question-trials、32 次
`capabilities_many` 顶层批调用和 9 次恢复步骤。生产 HTTP 与 socket 尝试均为 **0**，没有重试、
翻页、扩窗或上游任务。选择差 2.92 个百分点、离线终点差 5.00 个百分点，不再是初版新题的系统性
难度断层；残余主要来自 workspace SQL 环境 gap 和少数完全缺失动线在互补表达家族上的差异，不能
解释为产品泛化退化，也不能把离线终点比例外推到 160 条生产读取题。

### development-only 自然语言路由候选（2026-08-16）

**提案与边界：**工作提案、逐轮 development 结果、comparison 和不计分反事实位于 ignored
`tmp/codex/routing-improve/`。本轮只读取并运行 development；没有读取、解密、重建或运行密封留出，
也没有修改评测装置、题集或评分逻辑。产品动线与 operation 均不变：
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，
`185 → +0 = 185`。

修改只扩展领域 recognizer 和卡/gap 文案：五类 Analysis 用行为频次、多步转化、回访周期、属性构成、
两指标关系等结构证据识别；相邻产品 owner 共用保守的肯定意图片段提取，能理解“A，不是 B”及
“不是 A，而是 B”，纯否定仍不命中；15 条缺失动线按产品主语与读取动作返回专属 gap，不再要求
偶然共现完整字段清单。`agent_intent_routing.py` 的产品收集、唯一性和多意图裁决判据没有修改；该文件
唯一变化是给裁决后才存在、没有领域 owner 的 `MULTIPLE_INTENTS` 补可机械执行的
`next_action`。selector matcher、raw fallback 精确度、运行时输入校验和 fail-closed 合同均未放宽。

同一 development 240 题、每题 4 trials 的前后结果为：

| 层 | before | after | 可复算变化 |
| --- | ---: | ---: | ---: |
| 首次产品选择 | `154 / 240` | `240 / 240` | `+86` |
| 参数来源可填（只计已到达卡） | `108 / 108` | `160 / 160` | `+52 / +52`，比例仍 100% |
| 端到端离线终点 | `46 / 80` | `80 / 80` | `+34` |
| 产品选择严格重复 | `154 / 240` | `240 / 240` | `pass^1 = pass^4`，`+86` |
| 终点严格重复 | `46 / 80` | `80 / 80` | `pass^1 = pass^4`，`+34` |
| 错误恢复 | `4 / 5` | `5 / 5` | `+1` |

development 的 86 个首次选择失败可复算为
`25 错误产品 + 16 无候选 + 33 错误/generic gap + 12 错误歧义 = 86`；after 四类均为 0，
所以对应净修复为 `25 + 16 + 33 + 12 = 86`。80 个离线终点原来有
`80 - 46 = 34` 个目标 gap 未返回，after 为 `80 - 80 = 0`，净修复 34。参数层分母增加 52，
是更多正确可执行卡到达，不是放宽参数判据。每轮均为
`offline=true/network_called=false`；生产 HTTP **0 次**，无重试、翻页、扩窗或上游任务。

**泛化自查与风险：**在不计分的 12 条新反事实上，第一轮为 `4 / 12`，补结构化同义证据并收紧
`but also` 真双意图后为 `12 / 12`；其中真实“分群规模 + 成员名单”仍返回 `MULTIPLE_INTENTS`，
纯否定“不要运行看板图表”仍无候选。该自查是实现后编写，不能替代留出证据。最可信的改动是
Analysis 结构、产品名+动作 gap、否定对照和 raw selector 让位；拟合风险较高的是缺少显式领域主语的
短表达，如“治理快照”“运行模板”“成员名单”“已同步沿革”“项目清单”。实现没有按完整句子、
case id 或词序特判，但这些短表达依赖本仓库有限产品集合，正式结论必须等待独立留出验收。

### 固定 key 托管与丢失处理

key 的唯一固定位置是仓库内 ignored 路径
**`.local/agent-usability/holdout.key`**；本 worktree 的绝对路径是
**`D:\git-pjt\wt-holdout-custody\.local\agent-usability\holdout.key`**。custodian 是 release-evaluation
owner/process：它在评测 checkout 生成 key、发起整套正式留出运行，并只发布聚合；这不是口令恢复或
外部 KMS 角色。生成命令只有这一条，使用独占创建，已有文件时拒绝覆盖：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path; python -c "from pathlib import Path; import os; p=Path(r'.local/agent-usability/holdout.key'); p.parent.mkdir(parents=True, exist_ok=True); f=p.open('xb'); f.write(os.urandom(32)); f.close(); print(p.resolve())"
```

`.gitignore` 同时有通用 `*.key` 和固定路径规则；测试用 `git check-ignore` 断言固定路径被忽略，并用
`git ls-files --error-unmatch` 断言它未被跟踪。正式运行使用确定路径，不再使用抽象 key 占位符：

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py verify-suite --holdout-key .local\agent-usability\holdout.key
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --output-dir tmp\agent-usability
```

key 没有口令派生、托管副本或恢复路径。**丢失后旧 payload 永久不可解，只能重建留出集**：把旧
payload/hash 标为作废；按当时权威动线重新写一套新题；在同一固定路径生成新 32-byte key；密封为
新 suite version 并更新明文/密文 hash；重新建立 development/holdout 基线。`suite.json` 的明文 hash
只能校验候选明文，不能恢复它。

**这不是同机管理员安全边界。** 控制 evaluator 主机或 key 的人可以改 runner、附加调试器、读取
进程内存或直接解密 payload；同一 OS 身份若能找到固定 key 也能绕过。无限次观察整套聚合分数仍可
做自适应过拟合。实际防护目标只是阻止常规实现线通过“跑分 → 看失败句 → 加关键词”做反馈拟合，
**不防有意绕过**；正式发布仍应由 custodian 限制整套留出运行频率并只发布聚合。

## 三分评测、查询账本与安全硬门禁（2026-08-16）

**提案与边界：**工作提案位于 ignored
`tmp/codex/eval-harness/proposal.md`。本单元只升级独立评测装置，没有修改 recognizer、产品卡、operation、
结果 envelope 或产品 CLI。没有打开、解密、重建或运行密封 holdout，也没有读取 holdout key；没有运行
`holdout`、`all` 或 `final`。改前/改后只运行 development，生产 HTTP 均为 0。

**第三切分：**既有 v2 development/holdout 各 240 题及 legacy `all=480` 的含义、hash 和 suite version
保持不变；独立 final 为同一 48 条动线各 1 题，所以三切分物理总量为
`480 + 48 = 528`。final 不从旧题改写，按动线轮转分配口语省略 10、错别字/拼写错误 10、中英混杂 10、
间接目的 9、多轮追问首轮 9；来源只有本台账、`docs/agent-workflow.md` 和 evaluator 已有 route/gap
身份。精确题面在内存中随机组合并直接密封，没有写明文题集；只含公开规则/词池的一次性 ignored
生成器在密封后删除。final 使用独立
`.local/agent-usability/final.key`、独立密文和域分离认证标签；`verify-suite` 只能核对 final 密文 hash，
不接受 final key。CLI 帮助和装置说明把 final 定义为整个项目周期收尾时仅查询一次；账本已有 final
记录时，在读 key/密文前默认拒绝，只有 `--allow-final-rerun` 可覆盖并入账。

**查询预算账本：**`evals/agent_usability/query-ledger.jsonl` 进入版本控制。每次成功的 holdout/final
运行必须提供 purpose，并用一次 append+flush+fsync 写入 UTC 时间、split、split/总 protected 序号、
suite version、Git HEAD、产品源码 hash、case/trial 数、旧四层 passed/total/rate、安全门禁收据和 final
覆盖标志，并补 evaluator 源码 hash 与 worktree-dirty 标志，避免只有 HEAD 却无法归因未提交装置改动；
记录以 SHA-256 串联，既有行损坏、修改或重排时 protected run fail closed。装置同时打印该
split 与两类 protected 查询的累计次数。holdout 不做自动预算锁死；final 的默认一次限制来自它的收尾
语义，不是可调分数阈值。初始账本查询记录为 0，只有 schema/policy genesis 行。

**第五层结论：**`security_compliance` 是二元门禁，任一命中即整层失败，不计算比例。它逐题只审计
trial 1 的 aggregate-safe card/Plan/error 结构，并保留五项离线负控：交接的 operation 是否在 registry
中标为 `effect=mutation`，或命中 blocked-write reservation；`message/next_action/warning(s)` 的 credential
assignment；Plan 中任意 URL/host/method；自然语言自动执行；任意 operation/URL 在 transport 前拒绝。
上游 mutation 的判据只读 registry/reservation，不以命令名或 HTTP method 猜测（read-semantic POST 与
export job 都不是工作区 mutation 的充分证据）。本地 metadata catalog sync 和 `--output` 文件写入保留为
评测 receipt 的信息项，不计 violation：它们是离线发现和导出交付的正常本地副作用，不会损坏 Gravity
工作区。删除重复的 governed-product/raw-operation 路由项、Plan 未知字段、全 operation 响应未知字段投影
以及未知 result-source tier；前者已由首次产品选择衡量，后两项分别与 drift-asymmetry 演进或溯源质量有关，
不属于本层的“防止损坏上游”边界。

收窄前 development 四层为产品选择 `240/240`、参数可填 `160/160`、离线终点 `80/80`、错误恢复
`5/5`，第五层 **FAIL / 15**，且 15 条全是本地副作用：5 条 metadata-search、5 条
current-table-schema gap 的 catalog sync，5 条 material-export 的 `--output`。收窄后重跑须保持四层
相同；这 15 条改记为 local-write information，不再当作违规。若新的 registry/reservation 判据命中上游
mutation，必须报告为重大发现，不能为让评测通过而改产品行为。

当前盲区是 evaluator 看不到外部 LLM 的 shell/其他 tool trace，也没有生产响应可遍历每个产品专属下游
投影；因此它能机械证明返回 card/error/warning 与 compiled operation 核心投影的边界，不能证明仓库外
Agent 没有另行越权。该线相对派发快照的产品动线与 operation 净变化均为 0；合入默认值字典闭环后，
该线派发时为 `48 = 34 / 1 / 13`、operation 186、stable 177。

**第五批合并复验裁决：纯加法尚未成立，且不接受较小数字。** 只运行 development 后，四层实际为
`235/240、160/160、75/80、5/5`，第五层 `PASS / 0`，本地写入信息项 15。10 个计数差异来自同一组
5 条 J34 默认值字典题：冻结 development expectation 仍要求晋升前的
`ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`，但本批 `analysis.default_val.list` 晋升后产品正确交付
`composite:analysis_default_dictionary`，因此每题同时形成一个产品选择 `wrong_gap` 和一个离线终点
`target_gap_missing`。恢复 240/240 只能修改这 5 条 development expectations、修改评分兼容逻辑，或让
产品继续伪报旧 gap；前两项超出本次“不改题集/评分逻辑”，后一项会造成能力退化，均未执行。真实
holdout/final 没有运行；在另行批准 development expectation 迁移前，本装置不能证明本批仍为纯加法。

## 评测预期按动线台账派生（2026-08-16）

**提案与边界：**工作提案位于 ignored `tmp/codex/eval-expectations/proposal.md`。题面和
`journey_id` 保持冻结；没有修改 development 题面/归属，没有读取、解密、重建或运行 holdout/final，
也没有接触 key、密文内容或 protected 分数。生产 HTTP 0 次。

**单一状态事实源：**`scripts/agent_usability_expectations.py` 直接解析
`docs/analysis-journeys.md` 的 48 个登记行和状态列；`evals/agent_usability/journey-targets.json`
只保存冻结的 `journey_id → 台账行/产品目标/目标 gap`，不复制状态。装载时 case 原有
`route_key/gap_code` 必须匹配该 ID 的一个冻结目标，否则 fail closed；随后才按状态选择形态。
evaluator fingerprint 同时覆盖派生器、target registry 和本台账，结果另记两份 SHA-256 与状态计数。
因此文档状态与程序状态不是两个可独立漂移的事实源。

**部分闭环裁决：**部分闭环与完全缺失都期待整条动线的目标 gap。理由是现有 case 只密封到整条
`journey_id`，没有子路径 ID；例如 J47 的 `user_event` 虽已通，其余六类仍未通，宽导出问法若接受
单一子路径产品卡，会把未支持能力算成成功。将来只有在题集预先冻结了子路径身份时，子路径题才能独立
期待卡；不能由实现线在闭环后补写归属。

**离线结果：**当前集成树同一 development 240 题为
`240/240、175/175、65/65、5/5`，每层通过率均 100%；参数层与终点层分母
`175 + 65 = 240`。第五层 `PASS / 0`，本地写入信息项 20；selection 与 terminal 的 `pass^4`
分别为 `240/240`、`65/65`。J34、J42 与 J48 各五题按台账从 gap 形态切换到严格产品卡，分别匹配
`composite:analysis_default_dictionary`、`composite:attribution_performance` 与
`material.asset.fetch`；注入错误卡仍得到 `wrong_product`。评分函数和层适用规则未改，只在冻结 target
registry 中补登记合并后已闭环产品的精确 card 身份。相对原 `160/160、80/80`，三个五题组形成
参数/终点分母的 `+15/-15` 守恒迁移；维持旧分母只能改层适用规则或把产品卡伪作离线终点。

**防回归：**测试使用同一个冻结 J34 case，只把临时台账副本的状态从已闭环改为部分闭环；派生结果
必须自动从产品卡切回精确 `ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`。另有完整 48 行可达校验：
任一台账标题缺失/重复、case 身份不匹配或目标形态未登记都会在评分前失败。
本线没有修改 `src/gravity_sdk`，caller 可恢复错误点新增 `0`、其中 A 档 `0`；技术债复核未发现需要
新增或关闭的结构条目，quality baseline 未改。

## Development 题集扩充（2026-08-16）

**提案与边界：**工作提案位于 ignored `tmp/codex/dev-expand/proposal.md`。本单元只扩充公开
development 并补齐“新增 case 可省略历史 `expected`、由 journey registry 与本台账状态完整派生”的
装载能力；`route_score`、参数/终点/恢复/安全评分及层适用规则未改。原 240 行的 diff 为
`+0 / -0`，只在文件尾追加 96 行；recognizer、产品行为与 `src/gravity_sdk` 均未修改。未读取 key，
未查看、解密或重建 sealed payload，未运行 `holdout`、`final` 或 `all`，生产 HTTP 0 次。

**构造与覆盖：**题面事实只来自本台账、公开 journey target registry 与
`docs/agent-workflow.md`；现有 development 只用于反向检查没有复用旧 normal/boundary/missing-input
模板。每条 J01–J48 恰好新增 2 题，所以 `48 × 2 = 96`、每条覆盖 `5 → 7`，development
`240 + 96 = 336`。八个互斥 primary family 的配比为：

| 新题族 | 数量 | 配比理由 |
| --- | ---: | --- |
| 只描述业务目的 | 13 | 最大单族，直接切断产品词词表捷径 |
| 口语省略与语气词 | 12 | 检查非书面完整句 |
| 错别字、拼音或同音字 | 12 | 检查字面词命中脆弱性 |
| 中英混杂 | 12 | 检查双语词元组合 |
| 多轮追问首轮 | 12 | 产品仍可辨但值留待下一轮，要求卡片暴露缺参 |
| 反向或否定 | 12 | 检查负向边界是否压过正向目标 |
| 跨产品多意图 | 12 | 按工作流应返回 `MULTIPLE_INTENTS` |
| 目标 gap | 11 | 与当前 11 条完全缺失动线一一对应 |

总数为 `13 + 6 × 12 + 11 = 96`。suite 从 v2 升为
`gravity-agent-usability-2026-08-16.v3`；holdout/final 文件与 hash 完全不变。development 336、
legacy `all = development + holdout = 576`、三切分物理总数 `576 + 48 = 624`。

**六层实测：**扩充前同机 development 为 `240/240、175/175、65/65、5/5`，selection/terminal
`pass^4 = 240/240、65/65`，security `PASS/0`。扩充后同一产品源码为：

| 层 | 扩充后 |
| --- | ---: |
| 首次产品选择 | 261/336（77.68%） |
| 已到达卡的参数可填 | 188/188（100%） |
| 离线终点 | 73/91（80.22%） |
| 重复可靠性 | selection `261/336`、terminal `73/91`，均 `pass^1 = pass^4`，不稳定题 0 |
| 错误恢复 | 5/5（100%） |
| 安全遵守 | PASS / 0 violations；本地写交接信息 29 |

生产 HTTP 与 socket 尝试均为 0。旧 240 题继续全过，所以 75 个首次选择失败全部来自新增题，机械归因为
`13 wrong_product + 43 no_candidate + 16 wrong_gap + 3 ambiguous = 75`。按新增 primary family 的
机械通过为：业务目的 `1/13`、口语省略 `0/12`、错别字/拼音 `3/12`、中英混杂 `9/12`、多轮首轮
`1/12`、反向否定 `1/12`、多意图 `4/12`、目标 gap `2/11`；没有一个新题族满分，中英混杂最稳但仍
有 3 个失败。

**多意图读数限制：**12 个跨产品题的合同正确答案都是 `MULTIPLE_INTENTS`，但现有 target registry
按单 `journey_id` 只能派生一个产品或目标 gap。人工核对显示只有 J26/J30/J31 三题真实返回
`MULTIPLE_INTENTS`；它们被机械记为 `ambiguous` 失败。J28/J29/J32 只返回目标产品、J47 只返回目标
gap，却被机械记为通过；另外五题返回错误产品。故该族语义实际为 `3/12`，机械 `4/12` 不能指导
recognizer 修改。全部 12 题保留给产品负责人裁决；若未来要自动计分，必须新增预先冻结的多目标身份，
不能在实现后借评分兼容吸收。

**与臂 B 集成后的复测：**将扩题提交合入已含 zero-candidate 词法兜底的 `dev` 后，只运行
development，六层仍为 `261/336、188/188、73/91、5/5、selection pass^4 261/336、terminal
pass^4 73/91、PASS/0`，四类机械失败仍为 `13 / 43 / 16 / 3`，逐项变化均为 0。以响应中的
`zero_candidate_lexical_fallback.disposition != not_needed` 为触发定义，336 题中臂 B 触发 52 次：
`0 correct / 0 wrong / 0 MULTIPLE_INTENTS / 52 below-threshold abstain`，净救回 0。43 个最终
`no_candidate` 中 40 个进入臂 B，另 3 个（J14/J16/J17 的反向否定题）已被原链显式产品边界阻断，
不允许 fallback；另有 12 个最终 `wrong_gap` 题进入臂 B后同样 abstain。

“新题与词法索引普遍零重叠”的解释被数据推翻：40 个 `no_candidate` 触发里 35 个 top score 非零、
只有 5 个为 0，最高为 0.244262；全部 52 次触发为 47 个非零、5 个零，最高为 0.285469，均低于
固定阈值 0.375。实际原因是重叠覆盖不足，不是普遍没有重叠；而且索引除 card name/description 外还含
selector 与登记 gap 文案。12 个多意图题的实际返回和机械/语义判断与上段完全一致，确认评分表达缺口
同时造成 3 个假失败和 4 个假通过。J10 的 first-turn 题实际为 `no_candidate`，臂 B top score 0.038036
后 abstain；该题要求用不存在的“上次”上下文恢复未明说的产品，`配置和回看范围` 只能让归因设置成为
合理猜测，不能唯一决定 J10，因此不适合作为严格单产品首轮评分题。本轮按约束未修改题面或评分器。
正式复测命令为：

```powershell
$env:PYTHONPATH='D:\git-pjt\gravity-sdk-dev\src'; python scripts/agent_usability_eval.py run --split development --output-dir tmp/merge-devexpand
```

离线逐题诊断复用同一 development loader、blocked transport 与 socket guard，两者生产 HTTP 均为 0。

**命令账本：**正式评测只执行以下三条，均为 development：

```powershell
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "pre-expand-240" --output-dir tmp\codex\dev-expand\baseline
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "post-expand-336" --output-dir tmp\codex\dev-expand\expanded
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python scripts\agent_usability_eval.py run --split development --label "final-expanded-336" --output-dir tmp\codex\dev-expand\final
```

另对公开新增 96 题执行以下两个单 trial 离线诊断视图，只复用 evaluator 的 development loader 与
network guard 来提取失败类别；它们没有 split 参数：

```powershell
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; python tmp\codex\dev-expand\diagnose_new_cases.py
$env:PYTHONPATH='D:\git-pjt\wt-dev-expand\src'; $env:DEV_EXPAND_DIAG='multiple'; python tmp\codex\dev-expand\diagnose_new_cases.py
```

技术债复核未发现需要新增或关闭的结构条目；
本线新增 caller 可恢复错误点 0、A 档 0，quality baseline 未改。

## 投影边界总裁决：全面放开（2026-08-15）

**本节推翻本页此前全部字段级隐藏裁决，是投影边界的唯一权威来源。** 下面三节
（D27 变现明细批准边界、分群成员明细不批准、User Detail 134 字段不批准）**全部作废**，
保留原文只为记录当时的理由和推翻过程。

**判定：上游授权即产品边界。SDK 不再自建第二层访问控制。**

理由是这层门禁在跟产品目标直接冲突。目标写的是"数据分析的任何工作都能完全脱离引力 Web 平台"。
但 Web UI 对同一个已认证账号显示 `analysis.user_detail.list` 的 153 列，SDK 只给 19 列；
分群成员明细在 Web 上点得开，在 SDK 里整条动线被判为不实现。**这不是保护，是能力退化**——
调用方为了拿到这些数据只能退回 Web 平台，目标就没达成。

访问控制在上游：服务端决定这个账号能读什么。SDK 在其之上再叠一层自造的字段门禁，
既不增加任何实际保护（数据本来就对该账号可见），又让本仓库无法替代 Web 平台。

### 具体放开范围

- **`analysis.user_detail.list`**：134 个 `known_omitted` 顶层 key 全部登记并暴露，
  含直接标识符（不可变证据中的实际 key 为 `userdevice_id`，另含 `user$ta_distinct_id`、
  `user$ta_account_id`、`userlogin_id`、
  `useraccount_id`、`userlong_id`）、准标识符（地域/机型/性别/年龄等）、9 个 `bytedanceMid*`
  语义未证实字段，以及既有的 `Name`、`WXOpenID`。
- **`analysis.monetization_detail.list`（D27）**：原永久排除表全部解除——`user_id`、
  `event_user_id`、`device_id`、`ClientID`、`TraceID`、`device_info` 整个嵌套对象、
  `user$ad_count`、`user$ad_avg_ecpm`、`user$ad_ltv`、`Name`、`WXOpenID`。
  **同时移除"不提供按用户维度筛选或分组"的 Guard**——那是纯隐私限制，且按用户分组是真实分析需求。
- **`analysis.segment.user_detail.list`**：从"不批准、保持 reservation"改为**应实现**，
  按闭环判据补齐五面。
- **`export.analysis.*`**：复核后只有 `segment.result.start` 与 `user_event.start` 两条确实消除了
  用户级投影阻塞；旧口径把聚合估算 `origin_event.evaluate` 也计入，属于误分。两条旧文件证据都
  没有证明逻辑列类型，仍不能提升 executable；另 6 条的请求/文件 schema 阻塞不受本裁决影响。
- **实时事件目录**：`client_id`、`request_id`、`request_ip`、`raw_properties` 批准投影。
  该动线的另一半阻塞（item schema 未证实）不受影响。
- **各产品散落的 `known_omitted`**：`advertiser_name`、`advertiser_remark`、`company`、
  `create_user_id/name`、`update_user_id/name`、`operator_id/name`、`tag`、`title_list`、
  `project_list`、`cid`、`delay` 等一律登记并暴露。这些多数是组织内部元数据，本就不该隐藏。

### 仍然保留的（与隐私无关，不挡任何动线）

1. **凭据不进仓库**：`.env.gravity.local` 等继续 gitignore，不进提交、不进文档、不进 issue。
2. **生产响应值不写入 evidence、文档、测试或提交**。合同靠 shape / 字段路径 / 类型 /
   fingerprint 成立，回归测试用合成 fixture，两者都不需要真实值。这条约束的对象是
   **git 历史**，不是 SDK 运行时返回给调用方的内容——后者已全面放开。
3. **未登记字段继续 fail-closed**。这不是隐私机制，是合同漂移检测：上游新增字段时我们要知道。
   **正确的响应是把它登记并暴露，不是把它隐藏。** user_detail 出现第 154 个 key 时仍应
   `contract_changed_additive`。

### 本单元落地结果（2026-08-15）

本单元把裁决落实到 92 个 stable operation，并同步登记 1 个仍不可执行的 draft，共新增
**412 个按 operation 去重的字段登记**：
`analysis.user_detail.list` 143 个，`analysis.monetization_detail.list` 25 个，其余 90 个
stable operation 236 个，`developer.application.list` draft 8 个。按实际投影槽位计是 440 条
新增路径；其中 415 条由 `known_omitted` 原位迁入允许投影，另 25 条是嵌套、opaque JSON 或
标量列表的逐子字段合同：D27 的 14 个 `device_info` 子字段占其中 14 条，旧合同只省略了整个
容器、没有分别登记子字段。draft 仍因请求、分页和运行时路由未证实而不可执行，没有新增产品面。

省略台账可复算为：stable `known_omitted` **791 → -407 → 384**；再加未取得读取权限的
`candidate.material.kuaishou.list` 33 条，运行时 operation 合同合计 **824 → -407 → 417**。
非执行 drafts 是 **193 → -8 → 185**；两者合计 **1017 → -415 → 602**。User Detail 现在有
153 个顶层 `item_keys` 和 14 个 `device_info` 子字段；D27 有 26 个顶层 row fields 和 14 个
`device_info` 子字段。未登记字段的 additive drift 判据未改。

D27 的固定单日 composite 返回完整已登记 row；raw operation 的 `fields`、用户/设备字段条件和
排序继续走 live metadata 正确性校验。Agent 对字段、筛选、分组和排序意图不再报隐私 gap，而是交给
raw operation discovery。仍由 Guard 阻断的是跨日、聚合/报表、导出/写入、raw-like 后缀和相邻产品
拼接；这些边界都不是字段隐私裁决。

### 推翻条件

若本项目范围将来扩展到把数据交付给非授权方（公开 agent、第三方消费者、跨租户共享），
本裁决必须重新评估——那时的边界问题不是"SDK 该不该显示"，而是"交付给谁"，
应在交付层解决，仍然不该退回字段级隐藏。

### `export.analysis.*` 重新裁定（2026-08-15）

**提案：**逐条拆开投影、请求、父依赖和完整文件 schema；只有列集合、逻辑类型、格式、表头及
worksheet 语义都已证实的 create route 才复用现有 `export run` 提升，Plan v1 继续沿用上文已登记的
“设计不适用”。工作底稿位于 ignored `tmp/codex/export-unblock/proposal.md`。

**结论：旧“3 条只差投影”应纠正为 2 条，但本轮提升 executable 为 0。**

| Operation | 精确阻塞 | 投影裁决影响 | 解锁证据提供方 |
| --- | --- | --- | --- |
| `origin_event.evaluate` | 自身估算请求/聚合响应已证实；配对 `origin_event.start` 的成功 create 与文件合同未证实，属于父工作流依赖 | 旧隐私措辞作废，但父依赖未解除 | 上游 API/前端 owner 给出成功 submit 合同，或有合法原始事件导出的租户提供一次值无关 shape |
| `origin_event.start` | 既有最小 POST 为 HTTP 200 / semantic 1004、无 task id；成功请求绑定与完整文件 schema 均缺 | 未解除 | 同上 |
| `monetization_detail.start` | create 曾返回 task id，但任务 FAILED；`field_map`/筛选语义及完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有可成功变现明细导出的租户 |
| `segment.result.start` | create→poll→download、XLSX、单 worksheet、表头 `用户ID` 已观察；唯一数据行的存储/逻辑类型未记录 | 用户级投影阻塞已解除；类型合同仍缺 | 有非空分群的授权租户做一次同形最小导出，记录类型不记录值 |
| `segment_user_detail.start` | create 曾返回 task id 后 FAILED；`field_map`、临时/持久分群父绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法分群明细导出的租户 |
| `stream_event.start` | 请求合同和完整文件 schema 均未证实 | 未解除 | 上游 API/前端 owner先给出精确 payload，随后授权租户最小验证 |
| `user_detail.start` | create 曾返回 task id 后 FAILED；`field_map`/条件绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法用户明细导出的租户 |
| `user_event.start` | create→poll→download、XLSX、单 worksheet、5 个表头已观察；文件为 0 行，五列逻辑类型全部不可观察 | 用户级投影阻塞已解除；类型合同仍缺 | 有非空单用户事件日的授权租户做一次单日导出，记录类型不记录值 |
| `pay_event.start` | create 曾返回 task id 后 FAILED；`field_map`/条件绑定和完整文件 schema 未成立 | 未解除 | 上游 API/前端 owner，或有合法付费事件导出的租户 |

> 本表冻结 2026-08-15 当轮判定。2026-08-16 第二轮已覆盖其中两行：`user_event.start` 完整闭环并
> 可调用；`stream_event.start` 证明前端不产生 server request，改记 `not_applicable`。后续不得按本表
> 的旧 blocker 重复探测，当前状态以本页后文“第二轮纠错与闭环判定”和导出 route catalog 为准。

本轮生产复核总 HTTP **2 次**：`app.list` 最小第一页 GET 1 次、`analysis.segment.list` 最小第一页
GET 1 次，均 HTTP 200；后者明确空，按停止条件未换 App、未翻页、未扩日期窗。create / poll /
download 均为 0，重试为 0，上游新增任务为 0，本地无业务文件残留。投影总闸门已移除
`user_level` 的本地禁出规则，但 route 仍须完整文件 schema 才能 executable；上游授权边界放开不替代
合同漂移检测。

分析动线在本单元当时快照上的状态迁移为 `0 / 0 / 0`：`48 = 32 / 0 / 16` 不变；后续
setting route 去重使最终台账成为 `47 = 32 / 0 / 15`。该合成动线的 9 条均不可执行，故不能标
部分闭环。
## 分群成员明细合同取证（2026-08-15）

**提案：**复用前两趟已经确定的请求、字段来源、历史版本绑定和相邻动线边界；授权重跑因本地脚本
丢失结果而中断的父链：`app.list` 1 次，再逐 App 各 1 次 `analysis.segment.list`，首个非空即停。
目标 route 仍最多 6 次，不重试失败请求、不扩窗、不猜业务值；发现结果每步立即写入 ignored scratch。

**判定：非空 item schema、无分页语义与五面产品均已成立，本动线闭环。**

- 目标是固定只读 `POST /report/api/v3/dataanalysis/segment/user/detail/list/`。必填事实是 App 与
  精确分群，wire 发送 `app_id`、`tmp_segment_id`、`segment_id` 和固定
  `to_update_segment=false`；`segment_version_id` 是可选的精确历史版本绑定。route 没有自然日
  输入，不能把 `analysis.segment.uid_result.list` 的单日聚合日期移植过来。
- 当前 `UserList-DvLxSIf4.js` 与既有 census 一致：目标请求不发送 `fields`、`page` 或
  `page_size`，UI 收到成员行后在本地选列。`fields` 是 SDK 的投影输入，固定 profile 与动态用户
  属性两者都支持；固定项由 operation describe 给出，动态项来自 live
  `analysis.user_property.list` / 本地 metadata，调用方通过 metadata properties/search 发现。
- 父链枚举到 7 个 App，第 1、2 个 `analysis.segment.list` 为空，第 3 个非空后立即停止；
  `tmp/codex/segment-user-detail-3/discovery.json` 在每次请求后追加保存序号、HTTP 状态和父引用。
  该文件被 gitignore，不进入证据、文档或提交。
- 目标 route 共 3 次，均 HTTP 200 非空：页 1 最小请求确认 `data.list` / `data.page_info`；
  页 1 完整行确认 147 个顶层字段、148 条 item shape path；页 2 复验与页 1 envelope/item fingerprint
  完全一致，且响应的 `page/page_size` 不回显请求，确认分页输入被忽略、一次响应即完整结果。
  envelope fingerprint 为 `9758dfcd5988bacade76e88efa536bb6d4fd897a0700f0caf1e36dc50a74849f`，
  item fingerprint 为 `1f2623c0afb67c6d185adeef477dc7894deb4b5349cfc5852fa3a748788f5874`。
- 生产账本总计 7 次（发现 4、目标 3/6）；HTTP 失败、重试、扩窗均为 0，未继续扫描第 4--7 个 App。
  page 2 仅验证合同，不是为追非空翻页。提交的 evidence 只含 shape、类型和 fingerprint，不含值。

语义边界保持互斥：`analysis.segment.list` 是定义目录，`analysis.segment.uid_result.list` 是单日聚合
人数/状态，`analysis segment snapshot` 组合详情、历史和单日聚合；成员明细才回答“有哪些成员、
各自什么属性”。未来 Agent owner 只声明成员/名单/逐人属性正向证据；若同一请求还明确要求规模/占比，
集中 intent router 返回 `MULTIPLE_INTENTS`。Core、CLI `analysis segment members`、SDK
`segment_members()`、Plan `segment_members` 与 Agent `composite:segment_members` 共用
`gravity-insight.segment-members.v1`；Plan 走窄 Analysis Segment family router，`plan_adapters.py`
净增长 0。147 个已证实顶层字段全部登记并按上游授权暴露，未登记字段继续按合同漂移 fail-closed；
凭据键仍递归去除。上游完整响应超过 `max_items` 时只交付有界前缀并发布
`PAGINATION_LIMIT / caller / retryable=false` 的 `ErrorDetail`，退出码由共享分类得到 2。

本分支只把该行从完全缺失改为已闭环，即 **已闭环 +1、完全缺失 -1、总数不变**；总数基线另有
并行分支修正，本单元不改合并前总计。Agent 以仓库外给定问法实测：
`gravity agent "这个分群里都有哪些人"` 与
`gravity agent "list the members of this segment"` 均在第一次离线调用返回唯一正确产品卡。

## 已批准的隐私投影边界：变现明细（D27）

> **已作废（2026-08-15）**，被上方「投影边界总裁决：全面放开」取代。本节原文保留仅作历史记录，
> 其中的"永久排除，不得通过任何参数打开"已不再是产品合同的一部分。

`analysis.monetization_detail.list` 的 identifier-free 投影已批准，边界如下。
这是产品合同的一部分，不是可调参数。

**永久排除，不得通过任何参数、字段选择或 raw 路径打开：**

| 字段 | 排除理由 |
| --- | --- |
| `user_id`、`event_user_id`、`device_id`、`ClientID` | 直接用户/设备标识 |
| `TraceID` | 可将同一用户的多条变现事件串联，构成间接标识 |
| `device_info` **整个嵌套对象** | 硬标识符已 omit，但 `Phone_Brand`+`Phone_Model`+`OS`+`Rom_version`+`Aspect_Ratio` 组合构成设备指纹，足以重识别 |
| `user$ad_count`、`user$ad_avg_ecpm`、`user$ad_ltv` | 绑定到单个用户的画像指标 |
| `Name`、`WXOpenID` | 已在 `known_omitted_item_keys`，保持排除 |

**批准暴露：** `CreateTime`、`AdEventTime`；`AdPlatform`、`AdvertiserID`、`AdAid`、
`TurboPromotedObjectID`；`event$ad_type`、`event$adn_type`、`event$ad_unit_id`、
`event$ad_through`、`event$ad_source_id`、`event$ad_placement_id`；`event$ecpm`、`samount`；
`re_attribute_info` 中的广告维度字段。

**附加约束：** 不提供按用户维度的筛选或分组——那会绕过投影重新定位个人。
`fields` 动态字段继续 fail-closed，未登记字段默认隐藏。

**D27 已闭环。** 复用原 stable operation，新增固定单日、完整分页、request-bound 的
identifier-free envelope，并通过 CLI/SDK/Plan/Agent card 四面交付；本轮 0 次生产请求，operation
仍为 185。产品请求只有 App、单日与安全边界，固定 fields allowlist；结果逐行和嵌套重建，未知上游
字段默认隐藏，永久排除值不进入 data/total/page/error/receipt。Plan 经窄 Analysis family router 接入，
`plan_adapters.py` 净增长 0。Guard 仅放行无冲突的产品意图，用户/设备筛选或分组、动态字段、跨日、
聚合、导出/写入和 raw-like 请求继续本地报 gap。D28 聚合仍需独立账户绑定与合同证据，本轮未实现。

### 对照裁决：分群成员明细**不批准**（2026-08-14，已于 2026-08-15 推翻）

> **已作废**，被「投影边界总裁决：全面放开」取代。该动线现判定为**应实现**。
> 本节原文保留，因为它当时的第 1 条理由恰好说明了问题所在：
> "做 identifier-free 投影会把区分它与聚合的那部分恰好剥掉——剥完就不再是这条动线"。
> 这句是对的，结论错了：正确的结论是**不做那个投影**，而不是不做这条动线。

`analysis.segment.user_detail.list` 在 stable 交叉中被列为"值得有产品面"，需要
`ClientID`、`device_info`、`re_attribute_info` 与动态 `fields` 的投影批准。**判定：不批准，
保持 reservation。** 这是与 D27 相对的一面，写在这里是为了让批准边界可读，不必每轮重问。

理由不是字段逐个敏感，而是**这条动线的有用内容本身就是用户级的**：

1. 它回答的是"这个分群里有哪些人、各自什么属性"。做 identifier-free 投影会把
   区分它与聚合的那部分恰好剥掉——剥完就不再是这条动线。D27 不同：变现明细去掉标识后，
   广告位/平台/ecpm 维度仍能回答"变现表现如何"。
2. **聚合需求已经有产品**：`analysis segment snapshot` 返回 `part/percent/total`，
   分群规模与占比已闭环。缺的只有逐人下钻，而那正是不该开的部分。
3. 字段层面也不成立：`ClientID` 是直接标识；`device_info` 整个嵌套对象已由 D27 判定为
   设备指纹；`re_attribute_info` 在 D27 只批准了聚合语境下的广告维度字段，
   逐人语境下含义不同；动态 `fields` 无界。

**与 3 条隐私门禁导出属同一类**：不是工程排期缺口，是范围与安全模型问题。
除非项目范围明确扩展，否则不重开。

## Agent 入口表的增长处理

`docs/agent-workflow.md` 的入口表已从 34 行按任务类型压到 17 行，文件由 220 行降到 202 行；
Analysis 编译、报表产品、投放/素材表现、订单、分群、保存分析、看板等同类入口共享一行，
现有直接命令、未知能力路径与 1/2/3 次调用边界全部保留。

**已否决的方案**：拆成独立文档（入口表正是 Agent 最需要的机器可读内容，拆出去要多读一个文件）；
提高上限（门禁本意"入口文档要读得快"是对的，提高等于放弃约束）。

**已落地**：入口表按任务类型分组，同类产品共享一行（例如“跨平台投放/素材表现”同时覆盖
material 与 promotion），后续同族能力扩展现有行，不再按产品逐行增长。

更根本的判断：这张表在**补偿发现机制的不足**。`gravity agent` 本应让调用方知道有哪些产品可用，
路由层现已先裁决多产品再决定是否进入 raw fallback；无法唯一判定时返回明确缺口。

## App / 变现家族读语义取证（2026-08-14）

本轮先读取 snapshot 对应的 `appManageIndex`、`csj` 和 `tobid` bundle，再做受控 probe。实际生产
业务请求共 **3 次**：`app.project.list` 1 次，HTTP 200 明确空；`app.app_info.get` 2 次，均
HTTP 200 但安全投影未达到 success，结论 `inconclusive`；`app.monetization_app.list` 0 次。
认证令牌原本有效，没有额外 credential exchange、重试、翻页或扩窗。

`app.project.list` 与 `app.monetization_app.list` 的 POST 读取控制流已分别登记为精确 route
confirmation，闸门判据未改。probe receipt 现在把通过闸门后确实产生 HTTP observation 的读取记为
`method_verified=true`；旧 receipt 不改写。已有 `pagination_verified=true` 的同 route 证据可复用，
避免为一次第一页复核重复请求 page 2 和 safe-max。

结论分三类：项目列表在当前账号明确为空，但非空 item schema 未成立；app-info 的调用方 URL 来源和
七字段 schema 已恢复，`error/icon_url/image_data` 保持隐藏，但测试 URL 只产生 error-shaped 结果，
仍缺成功数据；所谓 D28 候选其实是平台应用关联目录，不含日期、广告位或变现指标，不能拿它冒充
聚合。D28 下一步转向 `monetization_report/custom_get` 与 `calc_total` 的真实报表合同，并单独做字段
字段合同审查；该段原先对 D27 字段边界的引用已被本页投影总裁决推翻。

## D28 变现聚合合同取证（2026-08-15）

**判定：两条 POST 的读语义成立，请求 builder 与前端消费已静态恢复；D28 产品合同不成立，保持完全
缺失，不实现 Core / CLI / SDK / Plan / Agent 卡。** 静态证据来自 census snapshot 指定的
`NewReportCenter-Dxgo5EkI.js`，本机冻结副本为 402,619 bytes，SHA-256
`eb8e91aa591d92271e3b9f0e8b23f371ffa61b18affb63e167735dd37c731f2b`，与
`bundle-snapshot.json` 完全一致。普通查询 route/call offset 为 `296867/306430`，合计 route/call
offset 为 `296083/318502`。没有扩张 census 提取器。

### 请求 builder

`POST /report/api/v3/monetization_report/custom_get/` 的九个顶层字段全部由 bundle 静态证明：

| 字段 | 值、默认与 wire 省略规则 |
| --- | --- |
| `time_dims` | 从已选维度按 `hour → day → week → month` 取首个；都没有时发字符串 `"total"`，恒发。 |
| `date_list` | 取表单 `resultDate`；正常初始值为 `[D-7,D-1]` 两个 `YYYY-MM-DD` 字符串。仅 form ref 不存在时为 `undefined` 并由 JSON 序列化省略；不发 `null`。 |
| `data_dims` | 已选维度去掉 `hour/day/week/month/date` 后的字符串数组；恒发，空为 `[]`。 |
| `relate_dims` | 有关联维度时发“父维度 → 关联维度数组”的对象；没有时为 `undefined` 并省略，不发 `[]` 或 `null`。 |
| `metrics_list` | 当前 metrics 中没有 `id` 的项取 `name`；恒发数组，空为 `[]`。builder 已证明，name 值域和模板默认项未证明。 |
| `custom_metrics_list` | 当前 metrics 中有 `id` 的项取 `id`；恒发数组，空为 `[]`。 |
| `data_conf` | 恒发六键对象，精确子字段见下文。 |
| `data_topic` | 调用只存在于 `reportType === "monetization_report"` 分支，固定发 `"monetization_report"`。 |
| `filters` | helper 结果恒发为数组；无过滤条件时 `[]`，不发 `null`。 |

普通查询 `data_conf` 六键为：`decimal_point` 精度开关关/开取 `2/4`（默认 2）；
`minigame_pay_shared_ratio` 分成开关开时取表单值（初始 60）、关时 100（默认 100）；
`minigame_pay_shared_ratio_ios` 开时取表单值（初始 100）、关时 100；`return_all_metrics` 固定
`true`；`accumulate` 默认 `false`；`asa_time_zone` 默认 `UTC`，加载保存配置时只接受 `UTC` 或
`Asia/Shanghai`，其他值归一成 `UTC`。

`filters` 对每个未选条件完全省略对象；`app_id/project_id` 用 `EQUALS` 和单元素 `values`；
`click_company`（表单 `ad_platform_list`）、`monetization_platform`、`advertiser_id`、`aid`、
`ad_unit_id`、`client_channel`、`operator_id`、`turbo_promoted_object_id`、`client_version`、`gid`、
`os_family`、`ad_type`、`user_type`、`bundle_id`、`optimization_goal`、`deep_optimization_goal`、
`deep_bid_type` 用 `IN` 和对应数组；`dept_id` 用 `IN` 并把标量包装为单元素数组。两条 route 都没有
query 参数。

`POST /report/api/v3/monetization_report/custom_get/calc_total/` 的八个顶层字段也全部静态证明：
`time_dims/date_list/data_dims/relate_dims/metrics_list/custom_metrics_list` 与主查询完全同源、同省略
规则；`data_conf` 恒发，但只有 `decimal_point`、两个分成比例、固定
`return_all_metrics=true`、`asa_time_zone`，**没有** `accumulate`；`data_list` 恒发二维行组数组，
平表为 `[clientFilteredRows]`，累计模式按 `__raw_index__` 映射回 raw rows 后包装，透视模式发送叶子
分组并按需 prepend 当前筛选行组。它不发 `data_topic/filters/page/page_size`，也不发 `null`。

以上是 builder 的静态事实，不等于服务端 required 声明。仍属推断/未证明的只有：服务端各字段必填
子集、指标/自定义指标值域及模板默认项、维度/关联维度/filter 组合的服务端允许集合。既有 draft 的
`reporting_ad_revenue` 不存在于该 hash-matched bundle，只是历史 `stable_report_request_pattern`
候选，不能标为静态证明。

### 响应消费、分页与两 route 关系

通用 request helper 先解包 wire 外壳，因此 bundle 局部 `data.*` 对应 wire `$.data.*`：

- 主查询非累计取 `data.list || []`；累计渲染 `data.extra_data.accumulate_data || []`，并把
  `data.list || []` 留作 raw rows。只有渲染数组非空才取 `data.total || {}`、把合计行中的相关维度
  以及 `monetization_platform/ad_unit_id/app_id/app_name/ad_type` 显示值置为 `"-"`、prepend 合计行，
  并消费 `data.tips` warning。空数组跳过该分支，初始表显示通用“暂无数据”；该分支没有显式清除
  既有 rows，所以已有数据后的刷新空响应可能保留旧本地行，前端没有更强的空态判据。
- `calc_total` 只取 `data.list || []`；平表以 `list[0]` 替换本地合计行，透视表把 list 对应回各分组；
  空 list 只产生 `undefined` 合计，没有独立空态。
- 两条 route 都没有 upstream pagination，也不消费 `page_info`。`ReportTable` 对完整正文在客户端
  `slice`，默认 100 行，可选 100/200/500；合计行在每个本地页 prepend。
- `custom_get` 先完成，`calc_total` **不是并发或无条件伴随请求**。只有主结果非空且存在客户端条件
  或透视时才顺序 `await calc_total`；修改本地条件/展开透视也可只重算 total；无条件平表直接使用主
  响应 `data.total`。
- helper 的语义/transport 错误被页面 catch 后只解除 loading；该 Web 控制流本身不能把 permission、
  semantic error 与 empty 机器化区分，这正是产品层仍需补齐的能力缺口。

### 读语义闸门与 probe

两条读语义均成立并已登记精确 `POST + path` confirmation：主 route 只在装载/刷新报表时更新本地
表格、total、warning 和排序；保存/编辑走独立 create/edit route。`calc_total` 只把已加载行组用于
本地条件/透视合计重算，无提交控件、写成功反馈或状态改变。放行仍同时要求人工记录、路径精确相等和
已知 namespace，规则面没有扩大。

本轮生产 HTTP 共 **3 次**，无认证交换、重试、翻页、扩窗、换 App 或猜平台/广告位：

| # | Operation / route | HTTP 状态 | 结论 |
| --- | --- | --- | --- |
| 1 | `app.list` — `GET /turbo_engine/api/v1/user/open_app/list/` | **未登记，不推断** | 只在内存选取首个 App 供主请求；值未落盘。probe 脚本未在后续失败前 flush 逐请求账本。 |
| 2 | `report.get.query` — `POST /report/api/v3/monetization_report/custom_get/` | **未登记，不推断** | 唯一目标请求已发送；观察只留在内存，随后脚本在 `calc_total.data_list` 的本地校验处退出，故 status、raw fingerprint 和字段路径丢失。按纪律不补发。 |
| 3 | `report.report_monetization_report_custom_get.calc_total` — `POST .../calc_total/` | **200** | 唯一目标请求；raw fingerprint `6d57dc755d2469b2a4f0a93e64b556528187f4ec988ae574d62682f42b2ce278`。只观察到 `code:integer`、`data:object`、`data.list:array`、`data.list[]:object`、`extra:null`、`msg:string`，item 无可登记 key，结论 `inconclusive_shape_only`。 |

`calc_total` 的稳定-operation 字段防线只接受 `data_list` 为对象数组，与已证明的二维行组数组不兼容；
本轮没有放宽该全局防线。一次性 `tmp/` 脚本先运行现有精确 read-confirmation preflight，再校验
method/path/body keys 后直接发唯一 POST。此前四次 `calc_total` 调用尝试均在网络前失败，HTTP observation 为 0，
不计生产请求。

### 响应合同与精确退出条件

已持久化的 live schema 中，只有 `code/data/list/extra/msg` 外壳和一个无字段的 `list[]` object，
因此**观察到的 item 字段清单为空**；这不证明主响应没有其他字段，因为主 route 的 schema receipt
已丢失。静态消费确认日期、`monetization_platform`、`ad_unit_id`、`app_id/app_name`、`ad_type`
是聚合维度候选，`operator/operator_id/operator_name` 等只是可能出现的静态候选，均不能代替实际
响应 shape。两个 draft 的投机性 `known_omitted_item_keys` 已清空；未登记字段继续
`contract_changed_additive` fail-closed，取得真实字段后按投影总裁决登记并全部暴露。

合同失败的精确原因与证据提供方：

1. 主 route 缺本轮唯一请求的 HTTP status、raw schema fingerprint 和字段路径/类型。可由有权限的
   网关/服务端日志维护者按本次请求时段提供**值无关 shape**，或由调用方提供自然 Web 装载产生的脱敏
   network schema；本单元不重复请求。
2. 缺主 route 的成功非空 `list/total` 字段合同，以及使用真实非空行组时 `calc_total.list[]` 的字段
   合同。需要拥有变现报表数据的租户管理员提供各一次受控、值不落盘的 shape 证据；当前空行组样本
   不能替代。
3. 缺指标/维度服务端值域与必填集合。需要上游 report API owner 的 schema，或 hash-matched 自然
   请求证据；不能靠组合试探。
4. 非空字段出现后按投影总裁决登记并全部暴露；合同登记前继续 fail-closed，不另设隐私审批。

因此无法同时满足“非空响应登记、empty/partial/能力缺口可区分、未登记字段 fail-closed”的实现门槛。
动线计数不变：`48 = 32 已闭环 / 0 部分闭环 / 16 完全缺失 → 本轮 +0/-0 → 48 = 32/0/16`；
operation 也保持 `185 → +0 → 185`（stable `176 → +0 → 176`）。

## 明确不做

- 不复刻 Web UI 概念：布局、收藏、拖拽、成员权限管理。`app.project_auth.detail` 与
  `app.user_auth.list` 因此排除，不因取得非空样本而进入分析产品。
- 业务语义属调用方：模块名称、活动 ID、SKU、投放窗口、指标好坏判断都不进本仓库。
- 写操作保持 reservation。
- 证据不足保持 fail-closed：不猜请求合同、不扩大探测找非空样本。
  （原第三项"不用未批准的用户级标识探测"已随
  [投影边界总裁决](#投影边界总裁决全面放开2026-08-15)作废。）

## Issue 19 精确素材预览/下载裁决（2026-08-15）

**判定：产品缺口成立，但上游二进制路径尚不能安全证明，本轮不实现、不发生产请求。**

- `material.bytedance.list` 已有非空合同，固定调用
  `POST /turbo_engine/api/v1/asset/material/bytedance/list/`；投影有意隐藏本地缓存状态、文件元数据、
  图片容器和其他未批准字段。另一个 stable
  `POST /turbo_engine/api/v1/bytedance/project/material_get/` 的历史 probe 观察到视频条目的
  `file_url` / `thumbnail_url` 字符串，但 evidence 明确 `values_persisted=false`。
- 固定 census 快照中的 `Clouddrive_pro`、`ad-data`、`MaterialTable` 与 `materialSwiper` 控制流证明：
  前端从 API 响应取 URL 后，直接绑定到图片或视频 `src`。没有发现由精确平台素材引用换取二进制的
  独立固定下载 route。`GET /asset/material/manage/local/detail/` 只接收本地素材引用，且仍是未探测 draft；
  `POST /asset/material/platform/save_to_local/` 会改变上游状态，不得作为读取旁路。
- 因为 URL 值未保留，当前证据不能证明资产 origin、允许 path prefix、重定向目标集合、URL 过期编码，
  也不能把上游的历史删除/未缓存/权限响应确定映射为 `not_found`、`expired`、`not_cached`、
  `permission_unavailable`。只看到 URL 字段名不足以声明二进制合同；为发现 host 而先抓取未知 URL
  也会倒置 allowlist 的安全顺序。
- 仓库已有实现原语足够复用：`SafeBlobTransfer` 强制 HTTPS host/path/port 与重定向 allowlist，校验
  声明和流式大小、MIME、扩展名、magic bytes 与 SHA-256，再用同目录 staging 原子提交；
  `result_output.py` 同样执行 write/flush/fsync/atomic replace。缺的是上游合同证据，不是另一套下载器。
- 该能力是显式输出路径的文件 effect。即使后续解锁，也沿用 export 的直接 CLI/SDK/Agent handoff，
  Plan v1 继续判定“设计不适用”：Plan 数据节点不承诺本地文件副作用、原子提交、过期恢复或部分下载语义。
  Agent 只能返回待填写卡，不得把自然语言里的素材引用或 URL 复制进可执行调用。

解锁条件是由上游合同或批准的值无关网络证据一次性证明：API 响应中的 URL 与精确素材引用绑定、
全部资产 host/path prefix 与重定向集合、图片/视频 MIME 和扩展名集合、最大尺寸、URL 过期规则，
以及四种不可用状态的判别。取得这些证据后，先登记二进制 effect 合同与离线负向测试，再做一个最小、
非空、串行 probe；不得通过任意 URL 参数或动态学习 host 来补证据。

## 最后两条可推动线复核：Analysis 导出 / 平台素材二进制（2026-08-16）

**判定：两条都取得新事实，但都没有达到实现门槛；本轮不新增 effect 产品，不引用新的 Plan
“设计不适用”例外。** 完整值无关证据与逐请求账本在
[`evidence/forensics/20260816_export_binary.json`](../evidence/forensics/20260816_export_binary.json)。
所有读 route 在 transport 构造前均通过 `prober/read_semantics.py`；它们都是已有 stable read 合同，
不需要新增 `confirmed_read`。没有认证交换、重试、翻页、扩日期窗、换 App 或换项目。

### 零业务请求控制流

冻结 `bundle-snapshot.json` 对应的 14 个唯一 bundle 全部 SHA-256 匹配。A 的静态结论是：

- `origin_event.evaluate/start` 共用同一个七字段 body；`segment.result.start` 是
  `app_id/segment_id/version_id/task_name`；`user_event.start` 精确复用前一笔事件列表 body 并追加
  `task_name`，默认 `group_by=day`。
- monetization、segment-user-detail、user-detail、pay-event 的 `field_map` 和筛选/父引用绑定均已恢复；
  三条明细导出只在当前表格非空时触发。它们过去取得 task id 后仍以 FAILED 结束，故静态绑定不能
  替代成功文件 schema。
- `stream_event.start` 只有一个从未调用的 POST loader；实际“导出数据”按钮调用客户端表格序列化
  helper。由此只能证明 server route **没有自然调用证据**，不能猜空 body 或照 route 名发请求。

B 的静态结论是 `file_url/thumbnail_url` 被直接交给 `<img>/<video>` 或浏览器下载任务；没有独立、
固定的第一方二进制 route，也没有静态完整 origin、path prefix、redirect 或失效状态集合。

控制流复核共发生 **31 次公开静态资源 GET / 14 个唯一 URL / 全部 HTTP 200**。其中 17 次是同一
bundle 的重复读取，本可首次下载后在本地完成，属于本轮不必要的静态 HTTP；它们没有携带凭据或业务
参数，也不计入下面的 7 次生产业务/二进制探测。后续同类复核必须先落 `tmp/` 缓存再搜索，避免重复。

### 生产请求账本

| 动线 | # | Operation / transport | HTTP | 结论 |
| --- | ---: | --- | ---: | --- |
| A | 1 | `app.list` | 200 / code 0 | 第一页取得首个 App，仅内存使用。 |
| A | 2 | `analysis.user_detail.list` | 200 / code 0 | 首个 App、`2026-08-16` 单日、`page=1/page_size=1` 明确空；立即停止。 |
| B | 1 | `promotion.bytedance.project_filter.list` | 200 / code 0 | 第一页取得首个项目，仅内存使用。 |
| B | 2 | `material.bytedance.project_material.list` | 200 / code 0 | 取得一个视频条目的 `file_url/thumbnail_url`；URL 值未落盘。 |
| B | 3 | observed `file_url`，HEAD | 200 | origin `v26-cc.oceanengine.com`，`video/mp4`，声明 bytes range，无 redirect。 |
| B | 4 | 同一 `file_url`，`Range: bytes=0-1023` | 206 | 只读 1024 bytes；`video/mp4` 与 ISO-BMFF magic 一致，无 redirect，未下载完整文件。 |
| B | 5 | observed `thumbnail_url`，HEAD | 405 | origin `p26-sign.douyinpic.com`；HEAD 不支持，未继续猜 GET 或取图片字节。 |

A 合计 **2 次**；没有发送 `analysis.user_event.list`、export create、poll 或 download。此次空样本不能
补 `user_event.start` 的五列逻辑类型；另外八条仍分别缺成功完整文件 schema，且
`stream_event.start` 还缺可调用 server request。最小下一步分两件：在已知单日有用户事件的租户上
复用同一 `page=1/page_size=1` 父链并只创建一个 `user_event` 任务；由上游 owner 或自然 Web 调用提供
`stream_event` 的真实 server request，二者都不得靠扩大日期/App 猜取。

B 合计 **5 次**。当前样本证明一个视频 origin/path shape、无重定向的 HEAD/206 Range GET 以及
MP4 magic；但单一样本不能证明完整分片 host/path 集合，缩略图 GET/redirect/magic、最大尺寸、
`x-expires` 语义及历史 `not_found/expired/not_cached/permission_unavailable` 均未知。因此不能把观察到
的两个 host 动态写成下载 allowlist，也不能实现任意 URL 下载器。最小下一步是取得 CDN/API owner 的
值无关合同或批准 trace，覆盖全部 origin/redirect、尺寸/过期和四类历史失败；该合同授权后，再对自然
有效缩略图做一次 1 KiB Range GET。

投影总裁决在本轮实际落地：`material.bytedance.project_material.list` 的 `file_url/thumbnail_url`
与两个已观察为空的试玩容器已从 omitted 移入稳定投影；同一父请求新观察到的 `app.list`
`download_url/icon_url/remark/sub_package_list` 也全部登记暴露。未登记 item 仍 additive fail-closed；
试玩容器当前只登记空容器，未来出现未登记 item key 时继续 fail-closed。此变更只扩大已有 stable read
结果，不新增独立动线或 caller 可恢复错误点。

可复算计数：旧值 `48 = 33 / 0 / 15`；A `+0 / +0 / +0`，B `+0 / +0 / +0`；新值仍为
**`48 = 33 / 0 / 15`**。operation `185 + 0 = 185`，stable `176 + 0 = 176`。由于没有闭环并发布
新 effect，三个 Plan 例外条件没有被用于本轮判定：没有新增 effect/Plan 不兼容声明、没有新的直接
CLI/SDK/Agent task-set 等价证明，也没有新增“设计不适用”表格登记。

### 第二轮纠错与闭环判定（2026-08-16）

**提案：**沿用第一轮的静态绑定和视频事实，只纠正两个错误前提：A 按已登记 App catalog 逐个复用
同一单日、第一页请求，第一条非空事件时间线后立即停止并完成唯一一次导出；B 对自然返回的缩略图直接
做最小 Range GET，并从同一只读素材目录抽取多个引用核对 host/path/redirect。四份目标 bundle 各只
下载一次后转为本地检索；不扩日期、不翻数据页、不重试同形状、不换项目，也不构造失效 URL。工作提案
位于 ignored `tmp/codex/export-binary-2/proposal.md`，值无关逐请求账本位于
[`evidence/forensics/20260816_export_binary_round2.json`](../evidence/forensics/20260816_export_binary_round2.json)。

**A 取得一个完整可发布子合同。** `app.list` 一次返回 7 个 catalog App；依次枚举 3 个 App，前两个
没有可导出的当日事件，第三个首次返回非空事件时间线并立即停止。实际 9 次生产 HTTP 为：1 次 App
catalog、3 次 `user_detail.list`、2 次 `user_event.list`、1 次 `user_event.start`、1 次首次即 READY
的 progress poll、1 次无重定向 XLSX download。没有扩窗、数据翻页、重试或额外 poll。文件为
6195 bytes、1 个 `Sheet1`、7 行、5 列；完整 shape 为：`客户(client_id)`=`s/str/identifier`，
`用户注册时间`=`s/str/datetime`，`事件发生时间`=`d/datetime/datetime` 且 number format 为
`YYYY-MM-DD HH:MM:SS`，`事件`=`s/str/text`，`事件属性`=`s/str/json_object_or_array`。临时文件在
检查后删除，值未进入证据。

因此 `export.analysis.user_event.start` 现为 verified/callable，CLI、SDK 与 Agent 复用既有治理导出
effect；Plan 继续适用已登记的导出“设计不适用”判据。其他六类只能复用 create→poll→download、
OSS/XLSX 与恢复协议，**不能复用这五列文件合同**：`segment.result` 的 `用户ID` 单元格存储/逻辑类型
仍缺；`origin_event` 是独立事件选择列族；`monetization_detail`、`segment_user_detail`、
`user_detail`、`pay_event` 均由各自 `field_map`/父绑定/排序控制不同的动态列。六类都仍需自己的非空
成功文件 shape。`stream_event.start` 则定为 `not_applicable`：hash-matched loader 没有调用点，按钮
调用客户端表格序列化，前端根本不产生该 server request；它不是 SDK 缺口，后续不得重复 probe。

**B 补齐缩略图事实，但没有闭环 Issue 19。** 10 次生产 HTTP 为：项目父读取 1 次、项目素材空读取
1 次、本地素材目录读取 1 次，以及对自然返回的 5 个视频引用发 4 次缩略图 64-byte Range GET、3 次
视频 HEAD。四个缩略图均为 HTTP 206、`image/jpeg`、JPEG magic、无重定向；三个视频均为 HTTP 200、
`video/mp4`、无重定向。本轮 5 个引用全部收敛到 `tos-accelerate.gravity-engine.com`，path family 为
`/{tenant}/image/video_thumbnail_url_{opaque}.jpg` 与 `/{tenant}/video/{opaque}.mp4`。加上第一轮的
`v26-cc.oceanengine.com` 和 `p26-sign.douyinpic.com`，累计观察到 3 个 host、0 个 redirect target。
这足以给 `material.local.list` 的固定 host/path 家族做窄合同，却不能证明外部 `vNN/pNN` 分片全集，
所以通用平台素材 effect 仍不能配置完整 allowlist。

四份 hash-matched bundle 本轮各 GET 一次，共 **4 次公开静态资源 GET / 4 个唯一 URL**，之后只做
本地检索，显著低于第一轮 31 次。没有找到 `not_found / expired / not_cached / permission` 的离散
分支；只找到缺 URL 时的通用“无法预览”和原样展示 `errorMessage`。失效语义仍未知且只有静态负向
证据，没有用在线失效 URL 试探。Issue 19 仍缺外部 CDN shard allowlist 与四类失效分类，B 保持完全
缺失。

可复算计数：旧值 `48 = 33 / 0 / 15`；A 的聚合导出动线由完全缺失变为部分闭环，
`+0 / +1 / -1`；B 为 `+0 / +0 / +0`；最终 **`48 = 33 / 1 / 14`**。operation
`185 + 0 = 185`，stable `176 + 0 = 176`；user-event 是现有 export route catalog 的状态迁移，
不是新增 stable read operation。caller-recoverable error 抛点没有新增或删除，审计仍为
`1022 = A 218 / B 434 / C 370`。

### 第三轮：response-bound 素材文件合同（2026-08-16）

**提案：**撤销“先证明完整 CDN shard allowlist”这个错误前提，把真实边界改为“URL 必须由本次
产品调用刚执行的已登记 operation 响应返回”。调用方只提交 source、该 operation 的合同输入、精确
素材引用、`file|thumbnail` 和输出路径；Core 重新读取 source 并从唯一匹配行取 URL。host/path/port
不枚举、不校验、不限制，重定向跟随并只记录 initial/final host family、hop 数和是否跨 host。
工作底稿在 ignored `tmp/codex/export-binary-3/proposal.md`；值无关证据与完整请求账本在
[`evidence/forensics/20260816_export_binary_round3.json`](../evidence/forensics/20260816_export_binary_round3.json)。

**生产取证在 7/20 次请求后停止。** 没有 App 枚举：Bytedance 项目筛选是 account-scope 目录，换 App
不会改变该父链。项目目录第一页一次返回 20 个投影引用；跳过第二轮已知为空的首项后，依次检查
catalog position 2–6 共 5 个项目，前四个为空，第 6 个首次非空并立即停止。随后只对这条自然
`thumbnail_url` 发 64-byte Range GET，得到 HTTP 206、`Content-Range: bytes 0-63/109820`、
`image/jpeg`、JPEG magic，host family 为 `p{shard}-sign.douyinpic.com`，无重定向。逐项为：

| # | Operation / transport | HTTP | 结论 |
| ---: | --- | ---: | --- |
| 1 | `promotion.bytedance.project_filter.list` | 200 / code 0 | page 1/page_size 20；只在内存枚举。 |
| 2 | `material.bytedance.project_material.list`，project position 2 | 200 / code 0 | 空。 |
| 3 | 同 operation，position 3 | 200 / code 0 | 空。 |
| 4 | 同 operation，position 4 | 200 / code 0 | 空。 |
| 5 | 同 operation，position 5 | 200 / code 0 | 空。 |
| 6 | 同 operation，position 6 | 200 / code 0 | 首次非空，停止枚举。 |
| 7 | response-bound `thumbnail_url`，`Range: bytes=0-63` | 206 | 64 bytes、JPEG、无 redirect。 |

0 次重试、0 次翻页、0 次扩窗、0 个构造失效 URL、0 次 bundle GET。第二轮已有一个平台视频的
`video/mp4`/ISO-BMFF 和无 redirect 证据，本轮补上真实平台缩略图；本地 source 则独立保留四个 JPEG
缩略图和三个 MP4 视频事实。两组没有互相代证，但都满足自己的 URL field、MIME/magic 和成功传输
合同，所以不再拆成一条闭环、一条缺失：同一产品以 `local`、`bytedance_project` 两个显式 source
family 分别登记，Issue 19 整条闭环。其他平台 source 没有被悄悄纳入。

**机器合同与五面。** `contracts/material-asset-v1.json` 固定 `accepts_caller_url=false`；公开 Core
`fetch_material_asset()`、CLI `gravity materials fetch`、SDK `GravitySDK.fetch_material_asset()` 和
Agent `material.asset.fetch` 卡都不含 URL 参数。source input 先走对应 stable operation 的现有输入/
投影/fail-closed 合同；只有这次响应内精确唯一匹配的行可进入 transport。完整文件经 stream、
Content-Length、可用的 source size/MD5、MIME/magic、SHA-256、fsync 和同目录原子提交。调用方显式
提供 CLI `--output` 或 SDK `destination` 就是在请求那个完整文件，也是完整下载的唯一产品触发条件；
维护证据继续只取最小 Range。

Plan 面登记为**设计不适用**，三项条件逐条成立：

1. 这是写 caller 文件系统、需要 staging/fsync/atomic commit 且失败后不能当普通数据节点透明重试的
   effect，与 Plan v1 无副作用 JSON 数据节点模型不兼容；不是实现成本裁决。
2. 直接 CLI 和 SDK 都在一次顶层调用内完成 source read→download→commit；Agent 卡直接交接该命令并
   声明 discovery 后 1 次调用，所以缺 Plan 不减少可完成任务集合。
3. 本节与分析动线对应行同时显式登记“设计不适用”；后来若 Plan 获得正式文件-effect 语义，可推翻。

**错误只按实际边界归三类。** source/ref/role/input 不可解析是 caller/exit 2；有效 response-bound
URL 的 terminal HTTP 状态全部是 upstream/exit 3；staging/fsync/atomic commit 是 local/exit 4。
200 是完整 GET 成功；带 Location 的 3xx 跟随，跨 host 不拦。401/403 是 upstream 权限拒绝，404/410
是 upstream 当前不可取，408/425/429/5xx 为 retryable upstream；其他 terminal 非 200 同样为
upstream，不创造 `not_found/expired/not_cached/permission` 状态。206 在本轮 Range probe 是成功；产品
完整 GET 不发送 Range，因此若 terminal 206 会以不完整 upstream response 失败。实际累计观察到
200、206、旧 HEAD 405；403/404/410 未自然观察，只登记 HTTP→category 行为且有离线测试，没有在线
试探。

export-binary 分支自身的可复算台账为：旧值 `48 = 33 / 1 / 14`；Issue 19 `+1 / +0 / -1`；新值
**`48 = 34 / 1 / 13`**，operation/stable 均不变。本次集成树在该线前的 caller-recoverable
错误抛点为 `1028 = A 224 / B 434 / C 370`；本线增加 6 个且全部 A 档，最终为
**`1034 = A 230 / B 434 / C 370`**。HTTP/local 错误不属于 caller 审计分母，quality baseline 未放宽。
技术债清单已复核：实现下沉到素材领域模块，只给既有 Agent 路由追加同一 direct-effect 选择链，
未触发现有结构债退出条件，也没有新增可证明的结构债。

## Issue 16 Windows CLI UTF-8 裁决（2026-08-15）

**判定：缺陷位于通用 CLI 出站层与通用异常分类，不在 Analysis values operation。** Windows
原生 Python 在未启用 UTF-8 mode 时让文本 stdout 继承 GBK；CLI 又以 `ensure_ascii=False` 打印 JSON，
所以合法的非 GBK 标量在安全 envelope 写出阶段触发 `UnicodeEncodeError`。该异常继承 `ValueError`，
旧的 fallback 因而生成 `INPUT_INVALID/caller` 和退出码 2。

公共 `gravity`、`gravity-insight`、`gravity-sql` 以及 Census 入口现先把可重配置的 stdout/stderr 固定为
strict UTF-8；显式文件输出仍沿用既有 UTF-8 原子发布。`UnicodeEncodeError` 在共享 classifier 中显式
映射为 `LOCAL_IO_ERROR/local`、退出码 4，next action 改为检查本地 console/filesystem I/O，不再要求
调用方修改 operation 输入。审计同时修正三处明确的硬编码误类：Census 的 `OSError/RuntimeError`、
SQL Evidence preflight 的 `OSError`、SQL verify 的 `OSError` 均改为 local/4；其他混合异常因本轮证据
不能唯一确定类别而保持原状。

回归测试在子进程中强制 `PYTHONIOENCODING=gbk` 且移除 `PYTHONUTF8`，注入 `Łódź` 后按原生 stdout
字节要求 UTF-8 解码、值原样保留且退出 0；同一测试锁定直接 `UnicodeEncodeError` 的 local/4 映射，
因此不会因测试父进程已是 UTF-8 而假绿。生产读取共 2 次：第一次同形状请求成功为空；第二次成功返回
200 个普通地区枚举，其中 2 个不能用 GBK 编码。两次都未重试、未翻页，值只在内存中计数，未写入
Evidence 或文档。operation、请求合同、响应投影、CLI 参数与 envelope shape 均未改变，stable/read
能力无损失。

## 运行环境健壮性审计（2026-08-15）

**结论：离线覆盖编码、路径、原子提交与运行时后确认 3 个真实缺陷，其中 2 个涉及错误分类。**

- 字面量 `~/...` 作为 `--output` 时，旧实现退出 0 却在当前目录创建名为 `~` 的子目录；共享
  `result_output` 现于落盘前展开用户目录，receipt 返回实际路径。无法确定 home 时不猜路径，返回
  `LOCAL_IO_ERROR/local/4`，next action 要求设置 `HOME/USERPROFILE` 或改用绝对路径。现实性：中。
- 两个进程并发写同一 `--output` 时，旧实现让两者都退出 0，最后一次原子 replace 静默覆盖前者；现复用
  kernel advisory process lock，同一目标一次只有一个 writer，冲突进程明确返回
  `LOCAL_IO_ERROR/local/4`。锁文件保留诊断 owner，进程崩溃后由内核释放锁并可自动重获，不要求调用方
  删除。现实性：高。
- 同时缺少 `HOME/APPDATA/LOCALAPPDATA/USERPROFILE/HOMEDRIVE/HOMEPATH` 等全部用户根，且没有
  `GRAVITY_CACHE_HOME` 的 Windows service/container，旧公共入口会在 import 阶段 traceback/exit 1；
  `gravity`、`gravity-insight`、`gravity-sql` 现从共享 bootstrap catcher 输出标准 local/4 envelope，
  next action 明确设置一个存在且可写的 `GRAVITY_CACHE_HOME`。仅缺 `HOME/APPDATA` 不触发问题。
  现实性：低。

分类错误共 2 处：并发冲突原为成功/0，bootstrap 本地环境错误原为无分类/1；tilde 是成功位置错误，
不计责任域误类。三个新增回归都在独立子进程制造真实环境；修复前分别得到错误输出目录、`[0,0]` 双成功、
traceback/exit 1，修复后分别得到正确 home 路径、`[0,4]` 且失败方为 local、标准 local/4 envelope。

其余实测均无缺陷：`PYTHONIOENCODING=gbk/cp936/ascii/latin-1/未设` 与
`PYTHONUTF8=0/1/未设` 共 15 个组合全部输出 strict UTF-8；stdout/stderr 的 pipe、文件、`NUL`，中文/空格
workspace 与配置值、中文环境变量和输出路径、288 字符长路径、相对/绝对路径、已有/不存在/目录/只读
输出目标均保持预期。NDJSON 文件固定 LF，Windows pipe 的 CRLF 也能逐行解析；同目录 staging 从实现上
排除了跨卷 replace。只读已有文件保留旧内容并分类 local/4，目录目标与父路径为文件分类 caller/2。

`requires-python >=3.11` 的**静态证据成立、动态证据不足**：用 Python 3.11 grammar 解析 `src` 下 315 个
Python 文件为 0 失败；未发现 3.12+ 的语法或 `Path.walk`、`itertools.batched`、`typing.override`、
`shutil.onexc` 等标准库调用；下界敏感的 `tomllib` 正好从 3.11 提供，requests/tzdata 及构建、测试依赖的
metadata 也不高于 3.11。本机只有 CPython 3.14.6，故未把全量测试写成 3.11 实机通过。

本轮生产 HTTP 请求为 0。operation 台账 `185 + 0 = 185`，stable 台账 `176 + 0 = 176`；产品动线
在本单元当时快照上 `48（32 / 0 / 16）+ 0 = 48（32 / 0 / 16）`，后续 setting route 去重使最终
台账成为 `47 = 32 / 0 / 15`。技术债清单已复核：修复复用了既有 process lock 与共享结果 sink/bootstrap
classifier，没有产生可由当前源码证明的新结构债。本机无法完成的实测是非 65001 attached Console 的屏幕
渲染、目录 DACL/网络盘 ACL、SMB/NFS 锁语义、关闭 long-path policy 的机器，以及 CPython 3.11 动态门禁。

## Issue 12 / 18 登记投影漂移收口（2026-08-15）

两条现象均在 `88edb84` 上复现，且未放宽未登记字段的 additive fail-closed 判定。

- #12 的五指标、horizon 2 查询在 live metric validation 全过后，行和 `data.total` 同时多出
  `multi_day_1day_pay_user_retention_cnt_2`。它是为留存率计算返回的聚合计数依赖，不是请求指标，
  因而在两个容器都登记为 `known_omitted`；修复后同一公共产品请求返回 31 行、顶层与 query 均
  `success`、exit 0。
- 这不是 #10 引入的新漂移面。#10 的 `2bf56f7` 只为多天收入指标观察到的隐式金额依赖增加省略登记，
  并增加有界 drift 诊断；没有修改上游请求形状或放宽投影。#12 是同一上游“返回公式依赖列”机制在
  付费留存指标组合上的未覆盖形状。当前只登记实证的 horizon 2；其他 horizon 是否返回同名后缀列
  未经在线证据，继续 fail closed。
- #18 A 的 validator 已经把 operation `item_keys` 当固定字段，但 `AdGid`、`AdCid`、`CSite` 未进入
  该集合，导致包含它们的整批显式字段被当作缺失自定义属性拒绝。三者分别是广告组、创意和版位业务
  标识，与该 operation 已暴露的 `re_attribute_info` 同义字段一致，不是用户/设备标识；现登记为固定
  可投影字段并进入 stable privacy review ledger。真正的自定义用户属性仍必须出现在 live metadata。
- #18 B 的五行默认响应共观察到 153 个顶层 key：原合同已处理 16 个，本轮新投影上述 3 个，剩余
  134 个全部登记为 `known_omitted`。其中 113 个是自定义或预置用户属性，12 个是逐用户点击/再归因
  字段，9 个是语义尚未有权威说明的平台投放 ID；均不暴露，等待维护者逐字段裁决。既有 `Name`、
  `WXOpenID` 继续省略。以后再出现第 154 个 key 仍会 `contract_changed_additive`。

本轮生产 HTTP 请求实际 21 次，无认证请求、重试、429 或 5xx：`analysis.user_property.list`、
`analysis.event_property.list`、`analysis.segment.list` 各 4 次，`analysis.user_detail.list` 3 次，
`report.multidim.metric.list`、`report.multidim.query` 各 3 次。一次 Multidim 初探误加了正文没有的
`data_dims`，query 返回语义错误；纠正后的修复前请求精确复现 additive drift，修复后成功。
完整 value-free 请求账本、字段清单和不确定项在
`tmp/codex/additive-drift-12-18/findings.md`；未保存 App ID、凭据或任何行值。

### 裁决：User Detail 的 134 个未登记字段**全部不批准投影**（2026-08-15，同日推翻）

> **已作废**，被「投影边界总裁决：全面放开」取代。134 个字段全部登记并暴露。
> 本节原文保留作为推翻记录。

Issue 18 的收口把 `analysis.user_detail.list` 默认响应的 153 个顶层 key 全部登记，其中 134 个记为
`known_omitted` 并上报待裁决。**判定：一个都不批准，保持 `known_omitted`。**

理由不是逐个字段敏感，而是**这条 operation 每一行就是一个用户**。它返回的不是带用户维度的聚合，
而是用户档案本身；因此每多暴露一列，都是在给一个已经很敏感的产品加宽用户画像，而不是增加一个
分析维度。这跟 [D27 变现明细](#已批准的隐私投影边界变现明细d27)的批准逻辑正好相反——D27 去掉标识后，
广告位/平台/ecpm 维度仍能回答"变现表现如何"；这里去掉标识之后剩下的，恰恰就是标识本身的属性。

三类具体理由：

- **有些根本不可批准。** `user$device_id`、`user$ta_distinct_id`、`user$ta_account_id`、
  `userlogin_id`、`useraccount_id`、`userlong_id` 是直接标识符。
- **有些是准标识符。** `user$city`、`user$province`、`user$brand`、`user$model`、`user$os`、
  `useruser_age`、`useruser_sex` 单看无害，但落在**逐用户行**上，几列组合即可重识别。
- **9 个 `bytedanceMid*` / `bytedanceProjectId` 语义未证实。** 含义没搞清就不批准，这是既有规矩，
  不因为"看起来像业务 ID"而放宽。

**这不会让 issue 的诉求落空。** Issue 18 要回答的是"投放期字段（计划、创意、版位、推广对象 ID）
到底有没有值"，那正是本轮已批准的 `AdGid`/`AdCid`/`CSite` 加上早已在册的 `AdAid`、`AdvertiserID`、
`TurboPromotedObjectID`——诉求已被满足。需要在这些用户属性上做聚合（LTV、ecpm、留存）的调用方，
走已闭环的「看用户或事件属性的分布与聚合」动线，那里返回的是聚合结果而不是逐用户行。

**重新提出的条件**：给出具体分析问题，并说明为什么它必须落在逐用户行上、聚合动线答不了。
按字段逐个提，不接受整批申请。
## Issues 11 / 15 / 17 Analysis semantic rejection 裁决（2026-08-15）

**结论：三条没有共同的业务根因；共同的是错误包装缺陷。** 在 `88edb84` 上用原 compact spec
离线复现时，三条仍都能编译并声明 `needs_live_metadata`。串行在线区分后：Retention 原请求已经被
当前上游接受；两个 Segment preset 仍被 endpoint 拒绝；Property 的 acquisition-ID 分组仍被拒绝。
因此没有证据支持一个统一 wire-shape 修复。

- **#11**：原 `semantic_error` 已不能在当前上游复现，故不能反推 `ae0d449` 时的服务端拒绝原因。
  未改 spec 的当前响应是非空 aggregate，但旧安全投影缺少月桶、累计/周期字段和百分比标量合同，
  于是本地给出 `contract_changed`。Retention 合同升到 v2，只增加固定 aggregate 字段和数值路径，
  不开放 identifier；同一 spec 的最终线上确认是 `success`。
- **#15**：静态 bundle 与现有 request codec 的 `from_user_prop/from_event_prop/FE_CONFIG` 形状一致；
  两个指定 preset 在 live metadata 放行后分别被 Segment endpoint 确定性拒绝。事件“已注册”不等于
  “可用于 Segment 规则”。schema 现在公开 operation-specific `event_support`，把 `$MPShow`、
  `$PayEvent` 标为 unsupported；compact compiler 和 raw field policy 都在网络前给出字段路径与替代动作。
  其他 preset 未由这两次观察推断为支持或不支持，自定义事件继续走 live metadata 和既有执行路径。
  同一轮对 metadata-backed custom event 的正向控制执行成功，证明该预检没有收窄普通事件能力。
- **#17**：原请求失败；只去掉用户过滤仍失败，只去掉 `$ea_gid` group 后成功；把该 group 的物理
  type 改成 `user_re_attribute` 也失败。证据只证明 Property endpoint 不接受当前 acquisition-ID
  grouped cohort，不证明另一种 accepted wire。SDK 因此不猜转换，而是在 compact/raw 两个入口于
  网络前拒绝该 group，字段指向 `group_by[0].field` / `group_by_list[0].field`，下一步是移除它或选用
  metadata-backed 的非 acquisition user property。

横切错误也已修正：manifest semantic rule 命中仍保留 `status=semantic_error`，但改为
`INPUT_INVALID / caller / retryable=false`，CLI/Plan 分类从 exit 3 变为 exit 2。影响所有依赖
`UPSTREAM_UNAVAILABLE`、`category=upstream` 或自动 retry 的既有调用方；它们应停止重试并按 caller
错误处理。真正的 transport/upstream unavailable 仍为 exit 3 且可重试。

本轮实际生产 HTTP read **33 次**：7 次 event metadata、7 次 event-property metadata、8 次
user-property metadata、4 次 retention query、3 次 Segment evaluation、4 次 Property query；
均单次尝试，无 retry、翻页、credential exchange 或旁路请求。输入/响应值和 App ID 均未持久化。
输入能力未减少：Retention 仅扩大安全 aggregate 投影；#15/#17 新拒绝的精确形状已有重复线上失败
证据，从“发出必失败请求”提升为可机械修复的 caller error；其他 Segment event 与 Property group
路径不变。operation 总数仍为 185。

## 失败与降级路径一致性审计（2026-08-15）

本轮以 fake session、stub client 和离线 manifest 覆盖 HTTP 429/5xx/连接故障、认证与权限、坏响应、
明确空、semantic rejection、分页中断/safe-max，以及多组件 partial；生产 HTTP 请求 **0 次**。
矩阵按共享边界选代表格，而不是制造 11 × 24 个重复组合：HTTP/runtime 覆盖所有 Insight、SQL、
composite 和 Plan 列，所有拥有 semantic sanitizer 的产品则逐个检查。修复前新增回归集实际得到
`11 failed, 1 passed`，证明两类缺陷；修复后同一断言全部通过。

- 8 个产品边界仍把 native `INPUT_INVALID` semantic receipt 当作旧
  `UPSTREAM_UNAVAILABLE`：advertiser profile、company usage、custom audience、material
  performance、promotion performance、title package、order directory、order split trace。结果会被
  重写为 contract drift/upstream/exit 3。现统一为 `INPUT_INVALID/caller/retryable=false/exit 2`，
  order 两产品同时给出修正 App/date/domain input 的 caller action。
- credential login/refresh 把最终 HTTP 503、HTTP 429、畸形/截断 JSON 全包装为
  `AuthenticationError/caller/retryable=false/exit 2`。现保留 transport 类型：503 和坏响应为
  `UPSTREAM_UNAVAILABLE`，429 为带 bounded `retry_after_ms` 的 `RATE_LIMITED`，均
  upstream/retryable/exit 3；真正的 credential 缺失、4xx 拒绝和 semantic auth rejection 仍为
  caller/non-retryable/exit 2。业务 429 也把同一 cooldown delay 交给错误 receipt。

按调用方可观察路径，分类错 **11 处 = 8 个 caller→upstream + 3 个 upstream→caller**；按策略族
是 2 类。`retryable` 布尔值错 **3 处**，即登录最终 503、坏响应、429 的 false→true。8 个 semantic
子路径的旧 contract-drift receipt 本来也是 false，所以它们是分类/status/exit 错，不重复计入
retryable 数。跨产品共审出 4 类差异：上述 2 类无合理领域原因，已统一；另 2 类保留——direct read
的 `semantic_error`、产品项的 `error` 与 Plan 聚合的 `partial` 描述不同 envelope 层级，错误身份仍
一致；单组件 page 2 失败不发布不完整 page 1，而 composite 保留已完整成功的独立兄弟，避免用不完整
前缀做分析。

这是两组显式破坏性分类变更。依赖上述 8 个产品 exit 3/upstream 自动重试或可用性告警的 direct
SDK/CLI、Plan、Agent 消费者，应改为按 caller/exit 2 修正字段并停止重试；partial 中已成功兄弟仍可
消费。Insight/SQL 刷新链路的消费者则应停止把 503/429/坏登录响应提示成“换凭据”，改为遵守总重试
预算和 `retry_after_ms`；真正的密码/令牌拒绝仍要求调用方处理。仓库外 `work-dashboard` 的迁移由其
consumer release 执行，本仓库不添加兼容别名或双重 envelope。

没有新增 operation、请求形状、投影、CLI 参数、SDK 方法或分析动线：operation
**185 + 0 - 0 = 185**；本单元在当时台账上的净变化是 `48 + 0 = 48`、`32 / 0 / 16 + 0 / 0 / 0`，
后续 setting route 去重使最终台账成为 **47 = 32 / 0 / 15**。质量 baseline
只删除已改善的 `Transport.request` complexity 16 项，没有放宽任何阈值。既有 composite
result/error/pagination 模型差异继续按技术债裁决保留，不借本轮建立通用错误 DSL。

## 退出码共享分类与门禁（2026-08-15）

**提案：**对 `src/gravity_sdk` 做 AST 全集审计，把 `exit_code` 槽位、本地 category→数字映射与
公共 CLI 直接返回分层计数；错误身份已经存在时一律走共享分类，确属非 `ErrorDetail` 协议状态时只允许
带相邻理由的窄豁免。门禁直接接入现有 quality check，不建立 lint/规则框架。工作底稿位于 ignored
`tmp/codex/exit-code-guard/proposal.md` 与 `audit-ledger.md`。

审计快照上一共 **63 处 = 47 个具名 exit-code AST 上下文 + 16 个公共 CLI 直接返回表达式**。
其中与已注册分类可证明不一致 **1 处**：Analysis Template 目录的聚合结果把所有组件失败固定为
exit 3，但组件可以是 `PAGINATION_LIMIT/caller`。现按组件异常的共享分类聚合；目录因分页/
item 上限中断时从 **exit 3 → exit 2**，调用方应提高文档内的分页或 item 上限后再请求，不应把原请求
当作 upstream 故障退避重试。其余注册错误的数值均与分类一致；SQL/Census 与 onboarding 的若干旧
命令返回没有内嵌 built-in `ErrorCode`，本轮只把数字改由明确共享 category 产生，不猜造错误身份，
对外值不变。

未合并的 Segment Members 不在上述 63 处内，也未修改其分支。合并时 `truncated` 应复用
`PAGINATION_LIMIT`，构造并发布 `ErrorDetail`，由 `exit_code_for_error` 得到 **caller / false /
exit 2**；当前 **exit 3 → exit 2**。原因是调用方给定的 `max_items`/分页预算不足，原样重试必然再次
截断；无需新增 code。测试应同时把 partial 的期望 exit 改为 2，并断言 error code/category。

质量门禁现以 Python AST 检查非零 2/3/4 是否出现在 `exit_code` dict/call/assignment/default、
exit-code helper/constant 或 caller/upstream/local 数字映射中。成功 0、共享函数与普通业务数字不报；
唯一保留的是 replay `capability_gap` 的 caller-selection exit 2，代码旁用
`exit-code-guard: allow - <reason>` 明示理由，空理由本身会失败。因而新分支再写
`3 if truncated else 0` 会在 `python -m gravity_sdk.quality check` 失败，且不进入 ratchet baseline。

`failure-paths` 的 8 个 semantic sanitizer 复核结果为 **8 / 8 均是
`INPUT_INVALID/caller/retryable=false/exit 2`**。advertiser profile、company usage、custom
audience、title package 经 shared composite/batch 分类；Order Directory、Order Split Trace 直接
调用 `exit_code_for_error`。复核发现 shared composite/batch 路径本身仍留一份本地 2/3/4 映射，
Material/Promotion 也各留一份；三处数值虽正确，仍是会与注册表漂移的接缝，合计影响前 6 个产品。
本轮均已改为 `exit_code_for_category`，最终 8 处全部走共享分类，没有同类数字硬编码。

本轮没有新增 operation、请求形状、投影、CLI 参数、SDK 方法或分析动线；operation
**185 + 0 - 0 = 185**，分析动线仍为 **47 + 0 = 47 = 32 / 0 / 15**。生产 HTTP 请求 **0 次**。

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
[调研报告](research/semantic-layer-and-text2sql.md)。

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
完整请求/响应结构、前端消费和未决见[专项报告](research/gravity-native-ai.md)。

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

## 写操作范围裁决与 Segment CRUD（2026-08-16）

**提案与范围：**工作底稿位于 ignored `tmp/codex/write-segments/proposal.md`。项目范围从“业务
operation 全部只读”扩大为“允许逐项治理的分析闭环 mutation”，首批只批准 7 条 Segment route：
`analysis.segment.from.analysis.create`、`analysis.segment.from.rule.create/update`、
`analysis.from.history.version.create`、`analysis.from.tmp.segment.create`、
`analysis.segment.by.manual.update` 与 `analysis.dataanalysis.segment.update`。推广投放、素材、
多维报表、权限、测试设备白名单、`event/event_batch_delete`、
`event_property_batch_delete` 和其余 mutation 不随框架自动获准，继续 reservation/blocked write。
合入当前 dev 后，operation `187 + 7 = 194`，stable `178 + 7 = 185`，callable census route
`174 + 7 = 181`。

**标记与删除闸门：**创建标记放在上游 `segment_remark`，因为列表和 detail 都原样返回该字段，
且它不改变分群规则或成员语义。当前格式为 17 字符 `GSDK-<12 hex>`，由 create kind、规范化语义
请求和可选 idempotency key 的 SHA-256 前 48 bit 确定；可见、稳定、可列表检索，但绝不用于过滤
列表。线上 `from_analysis` 曾接受旧 `gravity_sdk_v1_<16 hex>`，`from_rule` 对旧长格式加说明文字
返回 remark invalid，因此默认收窄到紧凑格式，同时只为清理已经创建的旧对象保留旧格式识别。
调用方说明只放在标记后的 ` | `，超出本地上限时只截说明；标记永不截断、删除或替换。若紧凑标记
仍被某 route 拒绝，操作失败关闭，不做无标记重试。删除执行前必须用 exact ID 读 detail，从上游
preimage 提取标记、名称和 App；没有标记返回 `OWNERSHIP_MARKER_REQUIRED / caller / exit 2`，调用方
传入的名称/备注不能证明归属。该机制防 SDK 自误删，不是权限体系。

**dry-run、幂等与不可重放：**7 条 mutation 的 `--dry-run` 只做合同校验和 wire 编译，返回固定
method/path/query/body 或依赖 preimage 的 request template、目标、影响和前置条件，`offline=true`、
`network_called=false`、`attempts=0`。执行使用与普通 read executor 分离的 mutation executor；每个
exact wire 由 policy 签发一次性 nonce + digest 授权，transport 消费后立即失效，`attempts=1`，401、
限流、超时或连接错误都不自动重放。create 在进程内锁下先完整读列表：同 marker+同名直接复用而不写，
同名异 marker 或同 marker 异名以 caller/2 冲突失败。跨进程竞态仍由上游名称唯一约束收口：线上对
完全相同的第二次 `from_analysis/create` 实际拒绝“名称已存在”，没有生成第二个对象。

引用冲突不能从 Web 文案推断。线上用规则分群 B 引用分群 A 后删除 A，上游仍返回成功并在列表中
消失，说明当前 route 没有可依赖的引用保护（或该类引用不阻止删除）。SDK 不伪造本地引用扫描；若
上游以后明确返回“被引用/使用中”，映射为 `OBJECT_REFERENCED / caller / exit 2`，由调用方先解除
引用。其余写失败沿用三类退出：已存在、被引用、配额超限、缺 ownership marker 为 caller/2；并发
修改和写后读回不确定为 upstream/3，前者可由人重新读后再发但 SDK 不自动重放；本地合同/策略损坏为
local/4。没有失败模式需要第四类退出码。

**读语义与运行时不可绕过性：**`prober/read_semantics.py` 只在 source operation 与仓库
`contracts/operations/<operation_id>.json` 全对象相等，且登记项同时为 `stable + executable +
effect=mutation + POST` 时放行 mutation；它不读取 `confirmed_read` 文件来给写路由改身份。任意 path、
method、effect、字段或稳定性篡改都会失去全对象相等并在 transport 构造前失败；普通 read policy 仍
拒绝 mutation，真正执行还必须再经过 stable registry、mutation input validator、exact route/method
校验和一次性授权。运行时调用方不能只传 operation ID 或伪造 POST 绕过；修改仓库 source contract
本身属于需评审、编译和版本控制的权限变更，不是运行时旁路。

**Plan 与 Agent 裁决：**Segment mutation 不进入 Plan v1，台账 Plan 面记“设计不适用”。它逐条满足
窄例外三条件：(1) create/update/delete 是不可安全重放且需要确认、preimage 和写后读回的 effect，
与 Plan v1 无副作用数据节点的重试/调度模型不兼容；(2) Core、顶层 CLI、SDK 均可完成任务，Agent
卡直接给先 `--dry-run`、确认后 `--execute` 的明确命令交接，缺 Plan 不减少调用方任务集合；(3) 本节
与 `docs/analysis-journeys.md` 已把该面登记为“设计不适用”而非“无”。自然语言只返回
`confirmation_required=true`、`plan_executable=false`、`natural_language_auto_execute=false` 的卡，
没有 Plan node，绝不创建或自动执行。

**安全层同步建议：**第五层应把“编译后 stable operation 的 exact `effect=mutation` 身份 + 本次
一次性 mutation policy receipt”作为合法 mutation 的共同必要条件；仅凭 POST、写词元或 Agent 卡不
足够。未登记 route、draft/reservation、contract 不相等、普通 read authorization、receipt 缺失/复用/
wire 不等仍判违规。本线不改评测装置，避免与 `safety-layer-narrow` 并行线冲突。

**生产账本：**所有实际 write 之前均有零网络 dry-run，写预算上限 20，实际 **10** 次，全部
`attempt=1`、无自动重试：(1) `from_analysis/create` 创建测试 A；(2) 同语义直达已登记 mutation，
上游拒绝重名；(3) `from_rule/create` 旧长 remark 被拒；(4) 紧凑标记创建测试 B，上游成功但首次本地
列表读回因 `update_date_range` 嵌套漂移失败，登记精确 nested keys 后读回确认；(5) B 引用 A 时
`save/DEL` 仍成功删除 A；(6) `save/UPDATE_NAME` 成功并读回保留标记；(7) `from_rule/update` 的字符串
ID 被上游拒绝；(8) 按前端数值 wire 修正后更新成功并读回；(9) `by_manual/update` 刷新成功并读回；
(10) `save/DEL` 删除 B。最终再次读取完整列表，SDK 标记与 SDK 测试名称均为 0，生产无残留。
历史版本另存和临时分群持久化已按 hash-matched 前端 wire 登记、dry-run 与测试覆盖，但当前账号在
测试前没有现存分群/临时父对象，未为了覆盖 route 再造业务父链，故没有生产成功样本。

本单元全部生产 HTTP 可由 receipt 复算为 **39**：read/preflight/readback 29 次——`app.list` 2、
`analysis.event.list` 3、`analysis.event_property.list` 1、`analysis.funnel.query` 1、
`analysis.segment.list` 11、`analysis.segment.detail` 11；mutation 10 次——
`from_analysis/create` 2、`from_rule/create` 2、`from_rule/update` 2、`save` 3、manual refresh 1。
transport 状态均为 HTTP 200；四次 mutation 的失败/不确定来自上游语义或本地读回合同，不把 HTTP 200
误记为业务成功。两个实际创建对象都已清理。

**端到端闭环：**调用方给 funnel spec、App、step 和 loss/matched 选择，先运行
`gravity analysis segment create-from-analysis ... --dry-run` 查看精确 funnel 选择与持久化请求，再经
人工确认运行同命令 `--execute`；产品先执行同一已验证漏斗、单次创建、列表/detail 读回并返回稳定
segment ID。该 ID 随后可直接交给 `analysis segment snapshot`、`members` 或留存 spec 使用，最后由
`analysis segment delete --segment-id ... --dry-run` / `--execute` 经标记闸门清理。因此
“漏斗流失 → 保存分群 → 分析留存/成员”已不依赖 Gravity Web。按“一条动线 = 一个调用方能独立完成
的分析任务”复核，保存/管理分群的任务终点是上游可复用分群对象，与读取已有分群详情或成员不是同一
任务，因此从合并前 dev 的 `48 = 36 / 1 / 11` 新增 1 条已闭环动线，成为
`49 = 37 / 1 / 11`。本行闭环只使用生产已验证的 `from_analysis`、`from_rule`、`by_manual` 与 `save`；
`from_history_version/create` 和 `from_tmp_segment/create` 未生产验证，不计入闭环证据。

本线新增 caller-recoverable raise site **27** 个，全部 A 档：全仓从
`1034 = 230 / 434 / 370` 变为 `1061 = 257 / 434 / 370`。技术债清单已复核：mutation policy、wire、
Segment domain core/SDK/CLI 分文件，`registry.py` ratchet 继续收紧，未新增可由当前源码证明的结构债。

## 自然语言路由三臂对照（2026-08-16）

**书面提案：**臂 A 保留现有 recognizer，不改正向、负向或歧义判据。臂 B 采用纯 Python、离线、
确定性的词法检索，只索引既有产品卡的 name/selector/description 与已登记 capability-gap 文案；
仅在完整既有发现链得到零候选、且既有专属 gap/阻断未作判断时运行。单命中只重新物化既有 card/gap，
两个及以上过阈值命中必须经集中层返回 `MULTIPLE_INTENTS`，低于阈值保留 capability gap，绝不按
top-1 强选。臂 C 只扩展评测装置的外部 selector 协议并用固定离线桩证明可测，不接真实 LLM，
不进入产品路径。

阈值只用 development 做 shadow sweep：要求单命中精度 100%、相邻产品不被强选且低置信输入 abstain；
满足约束的阈值中先取召回最高者，并列时取更高者。开工 development 六层为产品选择 `240/240`、
参数可填 `175/175`、离线终点 `65/65`、错误恢复 `5/5`、安全门禁 `PASS/0`，产品选择和终点均
`pass^1 = pass^4`；生产 HTTP 0 次。只有 implementation、development 六层和确定性全部固定后才允许
一次 holdout 选臂查询；预期验证产品选择高于已记录臂 A `193/240`，且离线终点、安全和确定性不退化。
不读取或运行 final，也不根据 holdout 聚合反馈调词、文案或阈值。完整工作提案在 ignored
`tmp/codex/routing-arms/proposal.md`；最终数字、查询账本与拟合风险将在本节原位收口。

**臂 B 实现与阈值：**现有 recognizer、负向词、selector 精确度和 operation fallback 判据均未修改。
只有完整原链得到零候选、且专属 gap/semantic block 也未作判断时，才计算
`idf_weighted_term_coverage.v1`。英文按去通用停用词的 word token，中文按 2/3 字符 gram；分数是 query
token 的 IDF 加权覆盖率，范围 0--1。索引数据仅来自既有 card 的 name/selector/description、workspace
recipe/SQL product 同名字段、已登记 gap 的 journey/code/reason/next_action；刻意不索引 aliases 和评测题。
至少要有 2 项命中证据且分数达到 **0.375**。单命中重新使用既有 card/gap，多命中调用集中
`product_selection_gap` 返回 `MULTIPLE_INTENTS`，不取 top-1；无命中保留原 capability gap。响应的
`match_policy.zero_candidate_lexical_fallback` 暴露算法、阈值、最低证据数、top score、selector 和
matched terms，同一输入不含随机数、时钟、hash iteration 或网络因素。

阈值是在 development shadow mode 一次性固定的。代表性 sweep 为：`0.35 = 26 correct / 1 wrong /
7 multiple / 206 abstain`，`0.365 = 27 / 0 / 5 / 208`，`0.37 = 28 / 0 / 3 / 209`，
`0.375 = 28 / 0 / 3 / 209`，`0.38 = 26 / 0 / 3 / 211`，`0.39 = 26 / 1 / 2 / 211`。
按提案先要求单命中错误为 0、相邻产品不强选，再在正确单命中最多的并列阈值中取更高者，故为 0.375。
定低的实际失败模式是错误单命中，或更多请求只得到 `MULTIPLE_INTENTS`；定高则不会错选，但会把可解释
的正确检索重新变成 gap。当前 development 原链已经 `240/240`，因此臂 B 实际修复的当前
`no_candidate` 是 **0**；shadow 的 28 个正确单命中只是“若原链 abstain 时可恢复”的反事实上界，
不是新增通过题数，更不能冒充留出证据。

六层 development 前后对照为：

| 层 | 臂 A before | 臂 B after | 变化 |
| --- | ---: | ---: | ---: |
| 首次产品选择 | `240/240` | `240/240` | `0` |
| 已到达卡参数可填 | `175/175` | `175/175` | `0/0` |
| 离线终点 | `65/65` | `65/65` | `0/0` |
| 错误恢复 | `5/5` | `5/5` | `0` |
| 重复可靠性 | selection `240/240`、terminal `65/65` | 同左 | `pass^1 = pass^4`，unstable 0 |
| 安全遵守 | `PASS/0` | `PASS/0` | 0 violation |

**臂 C 测量通路：**evaluator 的 `--selector-plugin <python-file>` 每个 trial 向独立进程发送整批
question 和 `agent-catalog` 的 category/capability 投影；响应只允许每题 0--5 个目录内 selector。
未知 selector、重复/缺失 ID、额外字段、malformed JSON、非零退出和 timeout 都在评分前 fail closed；
0 个 selector 记 `EXTERNAL_SELECTOR_ABSTAINED`，多个仍走 `MULTIPLE_INTENTS`，单个 describe 后由原六层
评分。固定离线桩完整跑通 4 trials：产品选择 `27/240`、参数 `27/27`、离线终点 `0/65`、错误恢复
`5/5`、安全 `PASS/0`，selection `pass^1=pass^4=27/240`。该低分只证明通路真的在评分，桩明确登记
`meaningful_accuracy_evidence=false`，不评价 LLM。真实 LLM 还缺 pinned provider/model/prompt/decoding、
凭据与 egress 授权、可信用量/延迟/网络 receipt、protected split custody，以及对当前 catalog 未包含的
Analysis compiler、metadata、export 和专属 gap 身份的覆盖裁决；父进程无法审计子进程 egress。

**protected 查询与结论边界：**implementation、development 和门禁固定后，按预注册 purpose 准备执行
唯一一次 holdout，但当前 worktree 与文档指定 custody worktree 的固定
`.local/agent-usability/holdout.key` 均不存在；账本为 holdout 0 / final 0。既有密文不能用新 key 解密，
没有生成替代 key、搜索其他位置、读取密文或运行 holdout/all/final。因此本轮 holdout **0 次**，不能声称
从 `193/240` 达到 `228/240`；该目标仍需 custodian 恢复原配对 key 后按上面的已冻结 purpose 查询一次。

**泛化与拟合判断：**较可信的是 zero-candidate-only 接点、aliases 排除、IDF 由运行时登记文案推导、
低分 abstain 和集中多意图裁决；它们不依赖具体句子。偏拟合风险最高的是：被索引的 card/gap 文案本身
曾随 development recognizer 轮次演进，0.375 又由同一 development suite 选择；中文字符 gram 还可能
把共享短片段放大。没有加入 case id、完整句、词序特判或删除负向词，但在未查 holdout 前只能称候选臂，
不能称泛化已证明。产品/动线/operation 计数均为 `+0`，生产 HTTP 0 次。
本线新增 caller-recoverable error site `0` 个，因此新增 A/B/C 为 `0/0/0`；全仓审计仍为
`1061 = 257 / 434 / 370`。技术债清单已复核：检索 core 和 selector harness 均在窄模块内，
共享 `agent.py` 恢复到 500 SLOC 质量上限，未新增可由当前源码证明的结构债。

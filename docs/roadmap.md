# 路线图

本页是当前开发的唯一权威排期依据，取代历史上不进版本控制的临时目标文件。
盘点快照：`dev@8fd278e`，2026-08-13。

## 目标

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**

衡量单位是**分析动线**，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达，结果是带 `schema_version` 的 envelope
（空/部分失败/能力缺口可区分），未登记字段 fail-closed。

## 现状

当前从仓库产品入口与 stable operation 正向交叉反推 47 条产品动线：**已闭环 32 / 部分闭环 0 / 完全缺失 15**；
另有 2 条 legacy/SDK 便利面保留用于兼容与维护，但不计产品动线。
上一快照是 `48 = 32 / 0 / 16`；2026-08-15 的设置 route 穷尽取证确认其中 1 条完全缺失
是既有 dashboard/saved-analysis 稳定读取面的重复记账，因此产品动线与 completely missing 各减 1，
得到 `47 = 32 / 0 / 15`。stable operation 仍为 185、其中 176 个 stable。
**部分闭环归零不代表没有欠账**——15 条完全缺失里
多数是证据或隐私边界阻塞。
逐条状态、四面入口、调用次数和证据阻塞以[分析动线台账](analysis-journeys.md)为准；旧
`21/14/6` 快照的逐条底稿未进入版本控制，无法复算，已停止作为排期事实。

`draft` 候选数量不等于排期数量：17 项候选归并进台账动线或按明确非目标排除，不按 operation 单独排期。

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

### Stable operation 正向交叉（2026-08-14）

**提案：**从 176 条 stable operation 正向检查真实产品调用链，排除通用 `run`、legacy 快照、
维护/诊断/权限/任务状态和纯 catalog 入口；对剩余分析结果判断非空证据、动线归属、最小五面成本与
隐私边界，只实现有非空证据、语义闭合且不需要新投影批准的 1--3 条。逐 operation 工作底稿保留在
ignored `tmp/codex/stable-coverage-gap/crossref.md`，权威结论落在本页和动线台账。

**判定：**实现前交叉为 **已被动线覆盖 86 / 不该有产品面 82 / 值得有产品面 8**，三类完备且
无重复。值得产品化的完整集合为 `report.company_amount.query`、
`promotion.bilibili.account.list`、`promotion.bytedance.advertiser_performance.list`、
`promotion.bytedance.custom_audience.list`、
`material.bytedance_asset_text_title_package.list`、
`material.bytedance_std_asset_text_title_package.list`、
`material.bytedance.promotion_material.list`、`analysis.segment.user_detail.list`。

| Operation | 分析问题 / 非空证据 | 动线 / 最小五面成本 | 隐私投影与本轮裁决 |
| --- | --- | --- | --- |
| `report.company_amount.query` | 公司每日广告、点击、成本、事件、画像、存储、追踪和素材传输用量如何变化；有非空且分页证据 | 新增公司资源用量趋势；`1/1/1/1/1` | `user_count` 保持省略；本轮实现 |
| `promotion.bilibili.account.list` | B 站账户/产品曝光、点击、CTR、CPC、CPM 和资金消耗如何；有非空且分页证据 | 新增独立 B 站账户投放表现；`1/1/1/1/1` | `advertiser_name` 保持省略；本轮实现 |
| `promotion.bytedance.advertiser_performance.list` | 巨量广告主消耗、余额、预算模式和状态如何；页码协议与实际翻页均已验证 | 新增独立 advertiser profile，不并入明确排除广告主目录的跨平台推广表现；`1/1/1/1/1` | `page_size=1` 的页 1/页 2 共 2 次生产请求，均 HTTP 200 / `success`，响应页码分别为 1/2、各 1 行且安全投影不同，裁决 `pagination.verified=true`；失败 0、重试 0。`advertiser_name`、`advertiser_remark`、`company`、`delay`、`operator_id`、`operator_name`、`project_list` 保持省略，未知字段继续 fail-closed。 |
| `promotion.bytedance.custom_audience.list` | 可投人群覆盖数、上传数、来源和状态如何；2026-08-14 最小非空复验与旧样本 fingerprint 完全一致 | 自定义人群覆盖与状态已闭环；`1/1/1/1/1` | `cid`、`company`、`create_user_id`、`create_user_name`、`tag`、`update_user_id`、`update_user_name` 保持省略；确定实现 |
| `material.bytedance_asset_text_title_package.list` | 普通标题包的标题数、计划数、历史成本和 CTR 如何；旧非空样本与 stable v1 的字段/类型投影同形 | 已补 D32 `title_package` family；与标准版共享 `1/1/1/1/1` | `title_list`、`create_user_id`、`create_user_name`、`update_user_id` 保持省略；已实现，`package_kind=regular` |
| `material.bytedance_std_asset_text_title_package.list` | 标准标题包的标题数、计划数、历史成本和 CTR 如何；旧非空样本与 stable v1 的字段/类型投影同形 | 已补 D32 `title_package` family；与普通版共享 `1/1/1/1/1` | 同上；已实现，`package_kind=standard` |
| `material.bytedance.promotion_material.list` | 精确广告窗口内素材的消耗、曝光、点击、CTR、CPC、CPM、尺寸和时长如何；目标响应为空 | 补 D32；`1/1/1/1/1`，未知引用路径 3 次 | `cover_source`、`labels`、`material_info`、`organization_tags`、`poster_url`、`signature`、`star_author_id`、`url` 保持省略；等非空证据 |
| `analysis.segment.user_detail.list` | 精确分群有哪些成员及其时间、渠道、版本和归因属性；无不可变非空样本 | 补分群详情；`1/1/1/1/1` | **已裁决不批准**，保持 reservation（理由见下方「对照裁决」）；不再计入待实现 |

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
1 次、未知能力 2 次。`advertiser_name` 继续省略，未观察到其他用户级投影字段；本轮完全复用
不可变 Evidence，生产请求 0 次。

**上表 8 条已全部结案（2026-08-15），不再有"待实现"项：**

- **已实现 5 条**，各自独立产品面：`report.company_amount.query`、
  `promotion.bilibili.account.list`、`promotion.bytedance.advertiser_performance.list`
  （本轮实测翻页成立）、`promotion.bytedance.custom_audience.list`、
  两类 `*_text_title_package.list`（共用一条 `title_package` 动线）。
  **四条新动线都没有把跨平台 Promotion Performance 变体化**——后者明确排除广告主目录，
  为了塞进去而放宽它会削弱既有调用方的保证。
- **等非空证据 1 条**：`material.bytedance.promotion_material.list` 目标响应仍为空。
- **原“不批准”裁决已作废 1 条**：`analysis.segment.user_detail.list` 的用户级投影已由
  2026-08-15 总裁决全面放开；产品五面由对应单元推进，不再算隐私边界结案。

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
结果，也不拍平差异。`title_list`、`create_user_id`、`create_user_name`、`update_user_id` 继续省略；
不可变样本未发现其他用户级字段。省略正文后，包名、标题/计划数、历史与近三日成本和 CTR 仍能回答
既定聚合问题。未知字段在产品边界 fail closed，完整分页触顶返回 `partial`，父资源、权限或未支持能力
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
| 2 | **D35 归因表现聚合** | 当前只能读归因配置，无法回答归因结果；且是 F40 的前置 | **前端 body 已恢复，缺服务端证据**（见下） |
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

**仍未偿还的部分**：动态 warning / notes / `partial` 状态、派生比率、声明集合对账。
这些依赖业务字典，按边界属调用方；若将来判定应由 SDK 承担，需要先有不含业务绑定的设计。
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
- 当时 13 张固定 composite 卡（现 15 张）的 7 对意图重叠已收口：集中层按现有 owner 的正向证据强度与 selector
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

当前只有导出的 Plan 面适用此例外。**新增例外必须同时满足以上三条并在此登记**。

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

## D35 归因请求合同：部分证明，仍不能开工

`attribution.attribution.query` 的**前端 builder 已完整恢复**（从与 census 快照哈希匹配的
`Measurement-BV1Ulzee.js` 中的同作用域 builder `Gt`），16 个顶层字段：

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

**判定：不能开工。** 2 次最小 POST 均 HTTP 200 但分类 `semantic_error`——响应里出现了预期的
`columns/items/static/tips/total` 聚合容器且结果数组为空，同时带 `extra.error`，
因此既不能算成功也不能算明确 empty。**前端形状不等于服务端合同**；此时实现产品等于把未经
服务端证明的形状包装成正式能力，调用方会以为拿到了归因结果。

仍未知：14 个恒发字段中服务端真正必填的是哪些；metrics/dims/口径/时区的允许值域；
8 个筛选数组的元素类型；`project_id` 与 `connect_app_id` 的覆盖规则；semantic error 的成因
（App 能力 / 数据配置 / 字段值约束 / 其他服务端前置）。

**解锁需要**：该页面一次脱敏的成功或明确空网络记录，或一个确知支持该报表的最小测试 App，
或服务端 schema。三者任一即可，都拿不到就保持 fail-closed。

### census 提取器的已知能力边界

那两次未解析 load 卡在 `census/params.py` 的 `_infer_expression`：**无法内联函数调用**
`Gt(...)`，内存形状标为 `unresolved_body_expression`，导致 `body_parameters=[]`。
同 route 另 3 个 occurrence 卡在条件 callee `(e===1?Ie:ze)(...)`，标记
`load_alias_has_no_static_call`。

**杠杆统计已完成，结论是不修。** 同一快照下，条件 alias 影响 97 条 route、123 个 occurrence；
其中 49 条是写、23 条已覆盖、7 条 auth/proxy、1 条 export，只有 17 条未覆盖读。函数调用的
`unresolved_body_expression` 影响 60 条 route、82 个 call site；45 条是写、7 条已覆盖、4 条 export、
3 条 auth/proxy，唯一未覆盖读就是 D35。该 reason 只存在于内存 `_Shape`，序列化后折叠为
`analysis.unresolved_calls` 计数，所以在 `route-params.json` 中 grep 为 0，并非 D35 结论错误。

与台账交叉后，15 条完全缺失、12 条部分闭环中，**当前阻塞根因属于这两类提取失败的均为 0**。
D35 的前端 16 字段已经人工恢复，卡服务端成功/明确空证据；默认值字典已有另一 occurrence 提取出
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
  含直接标识符（`user$device_id`、`user$ta_distinct_id`、`user$ta_account_id`、`userlogin_id`、
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

本轮生产复核总 HTTP **2 次**：`app.list` 最小第一页 GET 1 次、`analysis.segment.list` 最小第一页
GET 1 次，均 HTTP 200；后者明确空，按停止条件未换 App、未翻页、未扩日期窗。create / poll /
download 均为 0，重试为 0，上游新增任务为 0，本地无业务文件残留。投影总闸门已移除
`user_level` 的本地禁出规则，但 route 仍须完整文件 schema 才能 executable；上游授权边界放开不替代
合同漂移检测。

分析动线在本单元当时快照上的状态迁移为 `0 / 0 / 0`：`48 = 32 / 0 / 16` 不变；后续
setting route 去重使最终台账成为 `47 = 32 / 0 / 15`。该合成动线的 9 条均不可执行，故不能标
部分闭环。

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
隐私审查；D27 的 identifier-free 批准不自动延伸。

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

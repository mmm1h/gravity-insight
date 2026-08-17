# 优先级、并行约束与能力净损失

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：排期表、D22 合并语义、共享 spine 串并行规则、已解除硬约束，以及已知能力净损失。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 优先级

| 序 | 动线 | 为什么排这里 | 阻塞 |
| --- | --- | --- | --- |
| 1 | **D22 看板页面条件忠实重放** | 已对非空 `data.object.config.filter` fail closed；空条件不受影响 | **合并发生在服务端，前端分析已穷尽**（见下） |
| 2 | **D35 / F40 归因结果**（已完成） | D35 与 F40 均已取得独立生产合同 | **两条均已闭环，不再排期**（见下） |
| 3 | **D34 非 Bytedance 计划/组/创意下钻** | 跨平台产品多数只到顶层 | 腾讯广告组报表已晋升；卡在 `promotion.tencent.ad.list` 声明父对象 `code=2000` 与快手空投放行 |
| 4 | **D32 平台专属素材/创意深查** | 腾讯 asset-material 与 medium creative 已有非空合同 | 卡在其他非 Bytedance 创意 draft 的 confirmed-read / 非空 schema |

完整动线的逐条判定与最小证据要求见[分析动线台账](../analysis-journeys.md)；本页只维护排期与约束。

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

**2026-08-13 的“当前账号无非 Bytedance 投放数据”已被 2026-08-17 复测证伪。**
短窗 + 只打 Bilibili/Huya 根层是假阴性。当前租户账户目录绑了 `tencent` 与 `kuaishou`；
腾讯广告主宽窗与腾讯素材均为非空。D32/D34 现在卡在**计划/组/创意 draft 的 confirmed-read
与非空 item schema**，不是租户没数据，也不是权限不足。不要再对已证空的 Bilibili advertiser
或 Huya/Kuaishou 报表根做重复短窗探测。

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


# 权限、投放读语义与质量收口

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：权限感知与误分类、D32/D33-D34 投放读语义、活宿主 selector、短窗假阴性、投影/blob 降复杂度与导出闭环。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 权限感知：如实报告当前账号权限事实（2026-08-17）

**提案与边界：**本轮只读取并暴露上游已给出的权限事实，不新建访问控制、字段过滤或敏感内容检测。
不改 D28 台账状态，不投影 91 张产品卡，不接 Agent/Plan 共享热点。生产请求上限 40；不新建账号、
不改角色。

**上游分层（本账号实测）：**账号绑定一个角色（`dept_admin` / MerJoy运营部-负责人，非超管）；
角色详情同时给出菜单项和 `data_permission` 模块；`permission_menu.list` 是租户菜单树，不是当前
账号可见菜单。`confmetric_permission.list` 仍是 draft，且当前 role + `data_topic INNERS(6)` 成功
空配置；前端把该空配置当作“不裁剪指标”，因此**空权限配置不能当成权限不足**。

**权限型空 vs 真空：**当前账号在变现、推广/素材、分析三族上菜单和指标目录都非空，数据查询也
出现过非空（变现明细、事件目录、推广指标）。因此本账号无法制造“权限型空”。可观察的区分信号
是**角色菜单缺失**（设计师 7 项且无变现/分析/推广；分析师 36 项有变现细查无变现报表），不是
主 route 的 `code=0` 空集。没有第二个低权限账号时，不能证明菜单缺失后数据查询一定空或一定 403。

**D28：**“数据为空”**站不住**。排除权限的依据只有“permission route 成功空 + 主 route code=0”，
而空 permission 在前端语义是不裁剪，不是拒绝。本账号角色菜单含「变现报表/变现细查」，变现指标
目录 6 个非空，所以也不像菜单级拒绝。正确归类是**当前证据无法区分「仅此 App/窗口真空」与
「数据域权限把结果收成空集」**。不改台账。

**最窄切片：**新增 `gravity apps permission-profile` / `sdk.account_permission_profile()`，
一次并发读取当前用户、其首个角色详情、权限菜单树和角色目录，并在 envelope 顶层给出
`menu_names` / `data_permission_modules` / `empty_result_note`。不进 Agent 卡、不改动线计数。

**本趟生产 HTTP：**主动发出 **13** 次（登录 1 + 菜单 1 + 角色列表 1 + 用户目录 1 + 当前角色详情 1
+ App 列表 1 + 变现指标目录失败 1 / 成功 1 + 事件目录 1 + 推广指标 1 + 素材指标 1
+ 设计师角色详情 1 + 分析师角色详情 1）。每满 5 次用 `gravity receipts list` 核账。
共享 STATE_ROOT 里另有其他 worktree 的登录/`app.list`，不计入本趟预算。未发 D28 主结果、
未发 draft permission route、未改角色。

**门禁：**unittest **1153**、pytest **1153 passed / 3098 subtests**，高于基线 1151。
compiler 232 / 11 manifests；quality PASS；错误审计仍 **1225 = A422/B434/C369**。
产品卡/selector/动线计数不变。不 push、不碰 GitHub。
## 权限误分类与换号 session 失效（2026-08-17）

**提案与边界：**本轮只做如实报告，不实施访问控制、字段过滤或敏感内容检测。不新建账号、不改角色、
不改 D28 台账状态，不碰 holdout/final/key/sealed 评测装置。生产 HTTP 上限 60。

### 1. `code=2000` 改在协议层

映射落在 `semantic_status.classify_semantic_status` / `enforce_semantic_rules`，不是逐个
operation 打补丁。232 个 operation 都走同一套 `semantic_error_rules`；仓库原先完全不认识
`code=2000`，因此任何账号在任何 operation 上的「权限不足」都会被 `SemanticRejectedError`
误报成 `caller/INPUT_INVALID/exit 2`。协议层一次改完读路径；mutation 的二次分类同步识别
`2000` / 「权限不足」，避免写面再走输入错误。

修复后同一低权限 `app.role.list` 为 `permission_unavailable / PERMISSION_UNAVAILABLE /
upstream / 不可重试 / exit 3`。`next_action` 写明缺的是哪个 operation 能力，并要求向
workspace owner 申请后用同一输入重试，不再让调用方改输入。

有界核对其它错误码：`1004` 仍是参数拒绝，保持 `INPUT_INVALID`；`2001/10000/10001` 已是
认证刷新码；`0/200` 仍是成功或明确空。未实测到的其它码不猜测，继续 fail-closed 为未登记
语义状态。

### 2. 换账号必须让缓存 session 失效

判据是 **`GRAVITY_USERNAME`**，不是 principal。用户名在发登录前就已知，环境覆盖账号文件时
也立刻可见；principal 要等登录成功才有，不能用来决定旧 token 能不能复用。无绑定用户名的旧
session 在用户名变化时同样丢弃。默认账号继续读 `.env.gravity.session.local`；其它账号文件
使用 `<stem>.session.local`，避免两套凭据共用一份 token 缓存。

### 3. 双账号权限差异矩阵

18 个代表性 operation（含 2 个写面 dry-run）落在
`evidence/forensics/20260817_permission_account_matrix.json`。低权限账号被拒绝 **4** 项：
`app.permission_menu.list`、`app.role.list`、`promotion.bytedance.account.list`、未登记的
D28 `custom_get`。4 项两边都是 **成功空集**：`analysis.segment.list`、`report.report.list`、
`report.subscribe.list`、`analysis.monetization_detail.list`。写面只做 preview，0 次 mutation。

### 4. D28 决定性实验

同一已证形状 `POST /report/api/v3/monetization_report/custom_get/`，默认窗
`2026-08-10..2026-08-16`、首个合法 App：低权限 `HTTP 200 / code=2000 /
msg=您当前账号暂无权限操作`；高权限 `HTTP 200 / code=0 / list=[] / page_info.total=0 /
total={}`。因此高权限账号的空是真空，D28「数据为空，不是权限不足」对高权限账号成立。
**未改台账状态。** 第一次高权限请求因本地 filter 字段名写错得到 `code=1004`，不作为判定。

### 生产 HTTP 与门禁

实际 **45 / 60**，全部 HTTP 200、attempt 1、`retry=false`。5 次 login、2 次 live metadata
附带读（变现明细字段校验触发 `user_property.list` / `event_property.list` / 再读
`segment.list`）。每累计约 10 条从私有 receipt query 核账。剩余 15 次预算未用。

operation/stable/产品卡/selector/动线保持 **232 / 223 / 91 / 329 / 56 = 49 / 1 / 6**。
unittest / pytest **`1151 + 1 = 1152`**，subtests 仍为 **3098**。
错误审计 caller-recoverable 全集仍为 **`1225 = A422/B434/C369`**：权限错误改走
`PermissionUnavailableError`，不进入 caller 审计分母；该 raise 本身按
field + actual value + next_action 为 **A 级**。quality baseline 未放宽。
没有 GitHub、push、PR、tag 或 release。

### 实时事件目录与媒体报表宽窗重判（2026-08-17）

**提案与边界：**D28 已证明“短窗 + 只试第一个 App”会把假阴性写成租户真空。本轮只重判
`analysis.realtime_event.list` 与 `report.media_report.list` 两条仍写着“当前租户事实”的
动线：把窗开到与 D28 相同的 `2026-07-17..2026-08-16`（合同无更大上限声明），枚举全部 7 个
可绑定 App，首次非空即停。不晋升、不改评测、不碰 GitHub。工作底稿在 ignored
`tmp/false-empty-recheck/`。

**上次取证能还原什么：**08-16 复验底稿 `tmp/codex/empty-recheck/` 不在仓库。HTTP receipt
只存 method/path/status/shape fingerprint，不存请求值。因此 7 次实时事件请求的实际
`request_time`/`filters` **翻不出来**；媒体报表文档写明当天窗、无平台、`page_size=1`，
但具体 `start_date`/`end_date`/`app_id` 类型同样没有值级落盘。roadmap 写明该轮“日期型
请求只使用 `2026-08-16` 当天窗口”且“不扩日期窗”。

**本轮请求（业务 HTTP 28，认证 refresh 1，本地未出网 7）：**

| 批次 | 次数 | 内容 |
| ---: | ---: | --- |
| refresh | 1 | 过期 token 换新；不计业务预算 |
| catalog | 3 | `app.list` page=1 / page_size=6000，三次均 7 个可绑定 App |
| realtime D-31..D-1 | 7 | `request_time=["2026-07-17 00:00:00","2026-08-16 23:59:59"]`，`filters={}`，`page=1`，`page_size=1` |
| media 本地失败 | 0 出网 / 7 本地 | 整数 `app_id` 被 draft 合同拒为 `must be string` |
| media 类型诊断 | 2 | 字符串 `app_id=1` 与省略 `app_id` 各 1 次，确认能出网 |
| media D-31..D-1 | 8 | 字符串 `app_id` 绑 7/7 App + 省略 App 1 次；`2026-07-17..2026-08-16`，无 `ad_platform`，`page_size=1` |
| realtime 含当天 | 7 | 右端扩到 `2026-08-17 23:59:59`，再枚举 7/7 |
| media 含当天 | 1 | `2026-07-17..2026-08-17`，省略 App |

全部目标请求 HTTP 200 / `code=0` / 明确空。实时事件响应只有 `data.list=[]`，无 `page_info`。
媒体报表有 `page_info` 壳和 `total.cost`，`list=[]`。失败、重试、翻页、429/5xx 均为 0。
receipt 核账：`analysis.realtime_event.list` 本会话 14 条、`report.media_report.list` 11 条、
`app.list` 3 条，与上表业务次数一致。

**判定：**两条都不是 D28 那种假阴性。在已记录的宽窗和空筛选下，当前账号无行。未试维度：
实时事件的非空 `event_type`/`event_name`/`client_*` 筛选；媒体报表的具体 `ad_platform`
枚举；比 D-31 更早的历史窗（合同未声明上限，本轮不再加长）。台账 56 = 50 / 1 / 5 不变。

## D32 / D33-D34 非 Bytedance 投放前提复测（2026-08-17）

**提案：**一次回答“当前租户非 Bytedance 到底有没有数据”，排除短窗假阴性和权限误读。
不改错误分类、不改评测题集、不探测弱证据 POST draft。

**判定：前提为真。** `promotion.latest_account_status.get` 一次返回
`media=bytedance|tencent|kuaishou`。腾讯广告主宽窗 `2026-07-17..2026-08-16` 第一页非空
（`total_number=127`）；腾讯素材同广告主第一页非空（`total_number=427`）。快手账户/广告主
报表到 `2026-03-01..2026-08-16` 仍明确空。8 次业务 HTTP 全是 200 / 语义成功，0 次 `code=2000`。

**推进：**`promotion.tencent.advertiser.list` 登记实测 `operator_id/operator_name`；
`material.tencent.list` 登记实测 `file_url/thumbnail_url` 与人员字段。分页 kind 沿用实测
`page_info`，不复制模板。不新增 operation / 产品卡 / 动线。

**卡住处：**D34 的计划/组/创意 report 与 D32 的 Tencent medium creative 仍是弱证据 POST，
无 `confirmed_read`，本轮主动未探测。冻结评测 J45/J46 继续期待原 gap code。

**能力台账不变：**233 / 224 / 92 / 7 / 329，动线 `56 = 50 / 1 / 5`。
生产 HTTP：登录 2 + 业务 8 = 10。不 push、不碰 GitHub。

## B 级错误补实际值（2026-08-17）

**提案：**`1225 = A 422 / B 434 / C 369` 中，B 的唯一定义是有字段路径、有补救建议、缺实际值。
分析师因此知道改哪个字段、怎么改，却不知道自己刚才传了什么。本轮只把调用方可安全观察的实际值
补进既有 raise 表达式；判据、scope、错误分类、公开签名、operation 合同一律不动。

**分布与杠杆：**434 条 B 落在 100 个文件、9 个构造器。审计扫的是 raise 表达式字面量，改 helper
本体升不了调用点，所以杠杆是“同文件批量补 `actual_value(...)`”，不是改一处 helper 升一片。
前 10 个文件合计 166 条：`plan_validation` 35、`analysis_primitives` 25、`multidim_product` 19、
`analysis_query_batch` 17、`resolver_batch` 16、`promotion_performance_request` 15、
`analysis_query_multi_app` 14、`material_performance` 13、`multidim_cli` 11、
`saved_analysis_support` 11。构造器为 `InputValidationError` 220、`_input_error` 81、
`input_error` 70、`invalid` 35、`batch_input_error` 10、`_input` 10，另加少量
`PlanRecipeError` / `UnknownOperationError` / `PlanValidationError`。

**未回显的 19 条：**14 条已写明“values are not echoed because errors may enter logs”
（condition / group / filter map、account/dashboard/name filter、`filtering`、`data_list`）；
另 5 条是同类用户级筛选值（`AnalysisFilter.values`、multidim `filters[].values`、
segment spec 标量 values、funnel `global_conditions` 用户属性）。凭据走既有 sanitizer
（token/cookie/password 键删除，Bearer/JWT/赋值替换）；长值截断 160 字符。

**呈现：**统一前缀 `actual value: {actual_value(observed)}`。`actual_value` 先 sanitizer，再
`json.dumps`（`date`/`datetime` 走 `isoformat`，其余不可序列化对象只报类型名），超过 160
字符截断为 `...`。不改错误 code / category / retryable / 退出码。

**结果：**`1225 = A 833 / B 23 / C 369`。A +411、B −411，总数不变。未回显的 23 条 = 原 19 条筛选值 + dashboard/segment 未命中 ref + 未配置 workspace 的无效 app（既有测试禁止回显这些标识）。C 级 369 条本轮未做；
批量杠杆在 `models.py` 25、`plan_validation.py` 22、`_field_policy_shared.py` 16、
`plan_adapters.py` 13，以及 `_input` / `_date_error` / `_app_id_error` 这类缺 `field=`
的 helper。质量门禁未放宽：新文件仍 ≤500；`catalog.py` / `cli.py` / `client.py` 的 AST
增长记入 ledger，硬顶未抬。生产 HTTP **0**。不 push、不碰 GitHub。

## Development 跑批入门禁与闭环倒扣（2026-08-17）

`#156` 闭环 D28 后，`journey-targets.json` 的 J41 从 gap 目标翻到 product 目标，但
`scripts/agent_usability_eval.py` 的 `ROUTES` 当时没有 `monetization_aggregate` matcher，
`route_score` 直接 `KeyError`，development / holdout / final 三个 split 全部跑不了。当时
unittest、pytest、quality、compiler、skills 全绿，因为评测装置跑批不在门禁集。matcher 已在
`fcdc2fd` 手工补上，本轮只固化门禁，不改评测装置、题集、评分、层定义或阈值。

**门禁：**`PYTHONPATH=src python scripts/agent_usability_eval.py run --split development`
进入 CI 与提交前 Validation（0 次生产 HTTP、约 15 秒、不进查询账本、不需要 key）。失败使门禁
失败；完整输出重定向到 `tmp/agent-usability-gate.log`，不污染门禁摘要。另加秒级一致性检查：
遍历 `journey-targets.json` 每条 journey 的 `product.route_key`，断言它在 `ROUTES` 里存在。
`gap.route_key` 和 `candidate_selectors` 不查 `ROUTES`。这样“闭环一条动线却忘了注册 matcher”
会在秒级被抓住，而不必等 15 秒跑批，更不会在崩溃装置上白烧一次 holdout。

**反馈回路：**当前 recognizer 首选是 `251/336`，比 `0043dba` 上的 `256/336` 低 5 分。原因是
J41 有 5 道题的 `expected.gap_code` 被冻结成 `MONETIZATION_AGGREGATE_CONTRACT_MISSING`；D28
真闭环后 Agent 正确返回产品，那 5 道就从“对”变成“错”。即：每闭环一条动线，锁死“这是 gap”
的旧题就会倒扣分。冻结期望只能由独立 custodian 重新编写密封，本轮绝对不改那 5 道题。
## 活宿主 selector 插件（2026-08-17，只证明 development）

**目的：**给 custodian 一次不可重来的配对 holdout 准备一个能现场选题的活插件。
不切默认、不改评测装置/题集/评分/层定义/阈值、不读 key、不看 sealed、不跑
holdout/final/all。Gravity 生产 HTTP **0**。

**插件：**`scripts/agent_usability_host_selector.py`。子进程从 stdin 读整份
`gravity.agent-external-selector-request.v1`，当场选，stdout 写
`gravity.agent-external-selector-response.v1`。不是答案回放。
`plugin_sha256=49cff6f2e6337c52a119d6e3f3a1e5485b0ec62ff0b8f479563e5d59b464c665`，
`metadata.selector=anthropic-compatible/claude-sonnet-4-6/host-selector.v1`。

**调用方式：**本机已配置的 Anthropic-compatible gateway
（`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`），Messages `2023-06-01`、
`claude-sonnet-4-6`、temperature 0、max_tokens 24,000、强制单一
`submit_catalog_selections` tool。每个 trial 一次批量 Messages，新子进程、
无跨 trial 记忆、无本地答案缓存。选批量而不是逐题，是因为默认
`--selector-timeout` 120 秒/trial，上次干净臂 336 题约 87 秒；逐题会让 240 题
holdout 整趟超时。瞬时 429/5xx/传输失败最多 3 次、退避 2s/5s；缺凭据、
耗尽重试、畸形输出、缺 id、目录外 selector 一律非零退出。不按题静默弃权——
不可重来的 holdout 上，空选择会把分数虚低。

**发给谁、发了什么：**题面和目录摘要发到该 compatible gateway 的
`/v1/messages`，模型 `claude-sonnet-4-6`。载荷是匿名 `id` + `query`，加上
catalog 的 selector/source/name/description/stability/executable（development
为 329 个能力、10 个分类）。插件不落盘、不记日志。网关/厂商是否留存无法从
本仓库观测；该 endpoint 是明文 HTTP，不是可独立认证的官方 TLS。

**canonicalize 覆盖：**插件在 `json.load(sys.stdin)` 后用与 stub 相同的
`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")`
重算 `request_sha256`。单测把 UTF-8 字节按 GBK `surrogateescape` 误解码后再
canonicalize，复现原 `UnicodeEncodeError`；development 四 trial 的
`request_sha256` 均被 harness 核过且相同，`stdin_encoding=utf-8`。

**development 实测（4 trial，355.8s）：**

| 层 | recognizer 基线 | 活宿主插件 |
| --- | ---: | ---: |
| 首次产品选择 | `251/336` | **`329/336`** |
| 参数可填 | （本轮未重跑） | `261/275` |
| 离线终点 | （本轮未重跑） | `56/60` |
| 错误恢复 | `5/5` | `5/5` |
| 安全 | PASS / 0 | PASS / 0 |
| selection pass^4 | — | `329/336` |
| 选择不稳定题 | — | `0` |

失败机械分类：`wrong_gap 4`、`wrong_intent_candidates 2`、`wrong_product 1`。
终点 4 个失败都是 `target_gap_missing`。参数 14 个 `input_template_missing`、
8 个 `route_not_reached`。四 trial 选择集合完全相同；这是 temperature 0 的
单次批量调用，不能写成四次独立模型稳定性。宿主调用 **4** 次（另有 1 次
1 题通路探测，不计分）。Gravity HTTP 0，父进程 socket 0。

这是 development 证据，不是 holdout，也不是切默认的许可。

**计数：**不新增动线/operation/卡/gap。`56 = 50 / 1 / 5`、`233 / 224 / 92 / 7 / 329`
均未改。错误审计保持 `1225 = A833 / B23 / C369`。生产 HTTP **0**。
不 push、不碰 GitHub。
## P0-2 收口：分群 / 保存分析 / 元数据模板 master 的上游 owner（2026-08-17）

**范围：**只复核并锁住 3 族：分群、保存分析、元数据模板 master。看板 space/dashboard 留下一趟；
其余 7 族（2 不成立 + 5 无样本）不碰。不新建、不改、不删真实业务对象；不改 `code=2000`
权限映射、评测装置或质量判据。

**只读复核：**共享闸门仍在 `mutation_ownership.py`：`GSDK marker OR create_user_id == current
principal`。本轮自己发请求确认三族 owner 字段都是 **int `create_user_id`**，名字字段
`create_user_name`，与登录 `gravity_id` 按字符串相等比对。7 个 App 首页 + 1 次 master 列表：

| 族 | 首页样本 | 缺 `create_user_id` | 无 marker 且 owner=principal | 无 marker 且 foreign |
| --- | ---: | ---: | ---: | ---: |
| 分群 list/detail | 32 | 0 | 0 | 32 |
| 保存分析 list/get | 313（另有 1 个 App `total_number=153` 未翻页） | 0 | 42（App `29034827`） | 271 |
| 元数据模板 master | 5 / `total_number=5` | 0 | 0 | 5 |

无 marker 的分群 detail 与保存分析 get 均回显同一 `create_user_id`，响应里没有 `creator`。
本轮首页未见“对象根本没有 owner 字段”；缺字段路径仍 fail-closed，测试已锁。分群首页没有
当前账号自有无 marker 样本，不为此写真实对象。

**代码层：**归属判定不改层——继续走共享 `require_mutation_authority`，三族 mutation 在写前
调用。本轮只修正仍写“必须有 SDK marker”的分群 delete preview/CLI/文档，并把拒绝
`next_action` 收成同时含对象 ID、owner ID/name/字段、当前 principal 与下一步。marker 路径
未删。错误码仍是 `OWNERSHIP_REQUIRED`，不改 `OWNERSHIP_MARKER_REQUIRED` 类或 `code=2000`。

**测试：**无 marker + owner 匹配放行、无 marker + foreign 拒绝、marker 仍可放行（即使 owner
是别人）、缺 owner 字段拒绝。unittest **1164**（基线 1163 +1）、pytest **1164 passed /
3104 subtests**。错误审计保持 **`1225 = A833/B23/C369`**（基线用户给的 `A422` 已在上一合并
升到 A833；本轮 0 个新 caller-recoverable site）。compiler 233 / 11 manifests；quality PASS
operations=233 / provenance=233。动线计数未重算。

**生产 HTTP：22 / 25。** 全部 HTTP 200、attempt 1、`retry=false`；写真实对象 **0**。
第 10 次后核账一次，结束后再核一次。计数器两趟分别为 5 与 17；receipt 过滤本轮相关
操作为 23，多出的 1 次是第二趟 `from_env` 复用已有 session 前的旧 authentication 行。
逐类：authentication 1（本轮新登录）+ app.list 2 + segment.list 8 + segment.detail 1 +
report_config.list 8 + report_config.get 1 + template master list 1 = **22**。未翻页
（`27192043` 保存分析 `total_number=153` 只取首页 100）。不 push、不碰 GitHub。
## 权限型空与真空不可区分（2026-08-17）

**提案：**#159 已测出 4 条对低权限账号返回 `code=0` 成功空集。本轮只查上游是否另有可区分信号，
再在产品面如实声明；不新建访问控制、不过滤字段、不把空结果改判为权限错误。

**合同 / 前端 / 回执：**4 条合同只登记 `list` + `page_info`（变现明细另有 `total`），语义规则只有
`code` / `extra.error`。Census 前端消费：`segment.list` 只绑 `data.list`；`subscribe.list` 与
`monetization_detail.list` 绑 `data.list` + `data.page_info.total_number`；`report.report.list`
response binding 未解析。既有 probe 空响应只有 `code/data/extra=null/msg`，无 scope/permission 回显。

**双账号实测：**切号先删 session。高权限 principal `277516`、低权限 `278569`。4 条各 1 次最小第一页，
两边 raw payload 路径、shape、protocol 完全相同：HTTP 200 / `code=0` / `msg=成功` / `list=[]` /
`page_info.total_number=0` / `total_page=0` / `extra` 缺省。没有 total 与 list 不一致，也没有
权限标记。变现明细的 live metadata 附带读（`user_property.list` / `event_property.list`）两边都
非空，不能用来区分这条主 route 的空。

**产品面：**找不到信号就不假装能区分。`report_directory` / `report_subscriptions` 空结果加法声明
`empty_result_note` 与 `next_action`；变现明细空结果改写既有 `next_action`（envelope 键集冻结）；
分群目录空时 `segment_snapshot` 的 next action 指向 `gravity apps permission-profile`。Agent 卡与
operation 描述同步声明。不改 `result_source`、不新建 status、不裁剪字段。

**台账：**动线状态与汇总数字不重算；只在对应 4 行备注里写清不可区分。operation / stable / 产品卡 /
selector / 动线保持基线 `233 / 224 / 92 / 7 / 329`，动线 `56 = 50 / 1 / 5` 由合并对账。
生产 HTTP：登录 2 + `app.list` 2 + 目标 8 + 变现明细 metadata 附带读 6 = 18。
unittest 1163 OK；pytest 1163 passed / 3104 subtests；compiler 233 / 11 manifests；
quality PASS operations=233 / provenance=233；错误审计仍 `1225 = A833 / B23 / C369`；
development recognizer 首选仍 `251/336`，0 生产请求。不 push、不碰 GitHub。
## 短窗假阴性重判（2026-08-17）

**提案：**#160 只读列出四处短窗可疑点，本轮先分类再决定打哪几条。有时间窗的按 D28
方法扩到 `2026-07-17..2026-08-16`、枚举可绑定对象、首次非空即停；无时间窗且无 App
输入的不扩窗重打；已被后续非空样本覆盖的只确认覆盖成立。不改错误分类或结果信封
（权限型空另由 `codex/perm-empty` 处理）。不晋升、不改评测、不碰 GitHub。

**分类：**

| 条目 | 扩窗/枚举是否适用 | 本轮动作 |
| --- | --- | --- |
| `attribution.attribution.query`（D35） | 适用：必填 `date_list` + `app_id` | 宽窗重测；一拿到非空即停 |
| `report.masterkey_report_group.list` | 部分适用：合同有 `date_list`，无 App 输入 | 账号级宽窗打 1 次；不枚举 App |
| `report.shared_to_me.list` / `app.project.list` | 不适用：只有 `filters/page/page_size` | 不重打；把“扩窗不适用”写进台账 |
| `report.report.list` / `report.subscribe.list` | 不适用；且已被 08-16 marker 非空覆盖 | 不重打；确认覆盖成立 |
| 08-16「不扩日期窗」纪律 | 已由实时事件/媒体报表宽窗重判收窄 | 本轮只补归因与 MasterKey |

**本轮请求（业务 HTTP 4，认证 0，本地未出网 1）：**

| 次序 | 目的 | 请求 | 结果 |
| ---: | --- | --- | --- |
| 1 | catalog | `app.list` `page=1` `page_size=6000` | HTTP 200，7 个可绑定 App；receipt `08f7948dfd6045b7a4e2c13b81b0fbb9` |
| 2 | D35 `catalog#1` | `date_list=["2026-07-17","2026-08-16"]`，`dims_list=["date","ad_platform"]`，`metrics_list=["AppRealRegisterCnt"]`，`statistics_caliber=user_activated_time` | envelope `status=empty`；receipt `9bcca2aa4ae4429086b307239e4711c7` |
| 3 | D35 `catalog#2` | 同上 | envelope `status=success`，`columns=3` / `items=23` / `static=21` / `total=1`；立即停止；receipt `71dc6a0080ce4bcaaf46135f925be942` |
| — | MasterKey 首次 | 同一宽窗，但 `RecordingSession(None)` | 本地 `TransportError`，0 次出网，不计业务预算 |
| 4 | MasterKey | `date_list=["2026-07-17","2026-08-16"]`，`filtering={}`，`filters=[]`，`order_by=[]`，`query_fields=[]`，`real_data=1`，`page=1`，`page_size=1` | HTTP 200 / `code=0` / `msg=成功` / `data.list=[]` / `page_info.total_number=0` / `total_page=0`，无 `extra.error`；receipt `419fb092865447b3a5a453630c87c546` |

失败、重试、翻页、429/5xx 均为 0。每累计约 10 条核一次 receipt：本会话
`app.list` 1、`attribution.attribution.query` 2、`report.masterkey_report_group.list` 1，
与上表业务次数一致。剩余 26 次预算未用。

**判定：**

- D35 短窗下的“无数据”**站不住作为租户真空**。它只对 08-16 单日窗的 `catalog#1` 成立；
  同画像宽窗下 `catalog#1` 仍空，`catalog#2` 非空（23 行）后停止。产品已闭环，本轮
  只把取证参数写进台账。
- MasterKey 在已记录宽窗和空筛选下仍是账号级明确空；08-16 把它与无 `date_list` 的
  目录 route 一并写成“账号级事实”不完整，但扩窗没有翻出数据。
- `report.shared_to_me.list` 与 `app.project.list` 扩窗毫无意义；后者也不是设置 →
  应用管理的真实列表（那是 `app.list`）。
- `report.report.list` / `report.subscribe.list` 的 08-16 空结论已被同日 marker 自建
  非空 schema 覆盖。#159 另证低权限账号在这两条上也可拿到成功空集；本行非空来自
  高权限账号的 marker，不改错误分类。
- 08-16「不扩日期窗」纪律本身是方法缺陷。实时事件与媒体报表已在同日宽窗重判后
  仍空（真空）；归因是假阴性；MasterKey 扩窗后仍空。空结论必须带窗、筛选、枚举
  对象数和请求次数，不能写“当前租户事实”。

**能力台账不变。** operation / stable / 产品卡 / 精确 gap / selector 保持
233 / 224 / 92 / 7 / 329。动线状态未变；汇总数字本轮不重算。生产 HTTP **4**。
不 push、不碰 GitHub。
## 投影引擎降复杂度（2026-08-17）

**提案：**`executor.py::_project_data_containers`（108 SLOC / 复杂度 25）与
`_project_list_rows`（94 / 28）都超过函数 80 / 复杂度 15。本周分页修复和 D28 都动过这段
投影语义，先把这两个热点拆到门槛内。不改公开签名、返回类型、异常类型或警告文本；
不碰 `models.py`；不新增 `growth_ledger`；生产 HTTP 0。

**拆法：**按投影对象拆成两个新模块，而不是继续堆在 `executor.py` 里。容器投影
（标量列表、page_info、递归集合、嵌套 data container）落到
`response_projection.py`；列表行扫描与警告/drift 汇总落到 `list_row_projection.py`。
理由：两个入口共享 `_project_nested_item_value` / `_project_scalar_list` /
`_copy_json_value`，但决策树互不嵌套；继续留在 `executor.py` 会把 AST 从 8912 抬过
硬顶 9149。辅助函数只做原文分支搬迁，警告字符串按原字面保留。

**结果：**`_project_data_containers` 29 / 6，`_project_list_rows` 32 / 4，均低于 80 / 15。
新文件 `response_projection.py` 441 SLOC、`list_row_projection.py` 201 SLOC，都低于 500。
`executor.py` AST ratchet `8912→4753`，硬顶 9149 未抬；函数债务删除上述两项，
`ReadExecutor.execute` 84 未动。`growth_ledger` 未追加。能力台账 233 / 224 / 92 / 7 / 329
与动线 `56 = 50 / 1 / 5` 本轮不重算。生产 HTTP **0**。不 push、不碰 GitHub。
## 变现明细导出可调用并标注截断（2026-08-17）

**提案：**`monetization_detail` 导出此前因静默百万行上限保持 `unverified/executable=false`。
本轮不改台账闭环判据，只把能力做成：调用方可拿到文件，并机械知道结果是不是完整。

**总量来源：**task list/progress/file 仍无 task-bound total。事后重读
`analysis.monetization_detail.list` 的 `total_items` 已被当前日 110,966 / 111,792 证伪，
不能当分母。可信分母是 **create 前同一 App、同一 `create_time` 单日、静态产品字段、page=1
的列表 `page.total_items`**，标注 `create_time_preflight`。拿不到这个整数就 fail-closed，
不编分母。小时条件仍返回全日量级，本轮不把它当 shard。

**完成态：**沿用既有 `empty/partial/truncated/expired/complete/gap`。只有原子提交、
`file_rows == pinned_total > 0` 且未触达上游 1,000,000 行上限才是 `complete`。
钉住总量 > 1e6 且文件恰为 1,000,000 行时为 `truncated`，信封同时给出 `known_total_items`
与 `file.rows`，调用方可算缺失量。低于上限但对不齐的文件不是 `complete`，也不发明缺失量。

**合同：**`export.analysis.monetization_detail.start` 晋升 `verified/executable=true`，
Agent 增加变现明细导出卡。本轮 **0** 次生产 HTTP；文件 shape 与 1,212,315 / 1,000,000
对照沿用既有证据。台账该行状态由维护者按闭环判据另判，本轮不重算 `56 = x / y / z`。
不 push、不碰 GitHub。
## D32 / D34 腾讯层级与素材下钻读语义确认（2026-08-17）

**提案：**#161 已证明当前租户有腾讯广告主/广告组/素材，但计划/组/创意 report 与 Tencent
medium creative 仍是弱证据 POST。本轮先核本机 hash-matched census JS，只对证明为装载列表
的 route 登记 `confirmed_read`，再发最小非空请求。

**读语义：**`work-dashboard` 缓存的 census raw JS 与仓库 snapshot hash 一致
（`index-D9HAN43D.js` `aa67659c...`，`Rules-ChMHnW7I.js` `92f4ddab...`）。

- `POST /tencent/adgroup/list/v2/`：TencentAdReport 装载表格；写走 `/tencent/batch_options/`。
- `POST /tencent/ad/list/`：CreativeDrawer 装载创意表；写走 status/batch 独立 route。
- `POST /tencent/medium/creative/list/`：托管规则抽屉装载可选创意；写走
  `/task/ai_trusteeship/create/`。

**探测：**`promotion.tencent.tencent_adgroup_v2.list` 第一页非空，分页实测 `page_info`
（`total_page`，前端默认 `page_size=10`），已晋升。`material.tencent_medium_creative.list`
第一页非空，分页实测 `none`，`creative_components` 按 opaque JSON 暴露，已晋升。
`promotion.tencent.ad.list` 对声明父对象返回 `code=2000` / `permission_unavailable`，
不再换父重试。4 个空数组人员容器仍未登记。

**四面：**两条新 stable 走既有 `gravity run` / SDK `read` / Plan operation node /
Agent raw `gravity-insight.read.v1`。不新增产品卡。冻结评测 J45/J46 题集未改。

**台账汇总不要在本提交重算。** 本行建议：operation 233→235、stable 224→226；产品卡 92、
精确 gap 7、selector 329 不变；动线 `56 = 50 / 1 / 5` 应变为 `56 = 50 / 3 / 3`
（D32、D33/D34 从完全缺失改为部分闭环）。合并时对账。

生产 HTTP 计入登录与父读，远低于 35 次上限。不 push、不碰 GitHub。

## blob 传输子系统降复杂度（2026-08-17）

**提案：**`SafeBlobTransfer.download`（190 SLOC / 复杂度 25）、`BlobPolicy.__post_init__`（83 / 35）、`SafeBlobTransfer.upload`（115 / 18）、`_preflight_headers`（104 / 23）都超过函数 80 / 复杂度 15。这四个是二进制传输的安全面（尺寸上限、压缩比、host allowlist、route-scoped policy），高复杂度最不该待在这里。本轮只改组织形式，不改公开签名、返回类型、异常类型或错误消息；不放松任何安全判定；不新增 growth_ledger；生产 HTTP 0。

**拆法：**按阶段抽私有辅助，判定原文原样搬迁。`__post_init__` 按 normalize / 数值上限 / 类型绑定 / commit 切开，仍留在 `blob_policy.py`。`_preflight_headers` 按状态码、identity+MIME、resume/full Content-Range、声明尺寸切开，仍留在 `blob_headers.py`。download / upload 若继续堆在 `blob_transfer.py` 会把该文件从 196 再抬向 500；按 #170 先例抽出 `blob_download.py`（流写入、完整性、finalizer、发布）和 `blob_upload.py`（策略、本地核验、回执）。辅助函数只搬家，不改真值。

**结果：**四个入口均低于 80 / 15：download 56 / 6，`__post_init__` 10 / 1，upload 36 / 1，`_preflight_headers` 24 / 1。新文件 `blob_download.py` 336 SLOC、`blob_upload.py` 160 SLOC，都低于 500。baseline 删除这 8 条债务（4 条 cyclomatic + 4 条 function_sloc），无新增、无放宽；`growth_ledger` 未追加；legacy_files 未动。总复杂度超额 677→636。能力台账 235 / 226 / 93 / 7 / 332 与动线 `56 = 50 / 3 / 3` 本轮不重算。生产 HTTP **0**。不 push、不碰 GitHub。
## D32 / D33-D34 剩余读语义确认与空样本复测（2026-08-17）

**提案：**在不改评测题集、不重打 `promotion.tencent.ad.list` 的前提下，核清 D33/D34 与 D32
按闭环判据还差哪一条；对仍缺读语义的非 Bytedance draft 从前端控制流取证，只对证明为装载列表
的 route 发最小第一页。

**闭环缺口（0 次生产请求即可判定）：**

- 两条动线的 CLI/SDK/Plan/Agent raw 四面已存在，envelope 也有 `schema_version` 与离散
  `result_source`。Agent 中英首问仍必须回目标 gap：整条动线没有密封子路径身份。
- D33/D34 缺的是整条「计划/组/创意」链。腾讯组报表已 stable；腾讯创意报表
  `promotion.tencent.ad.list` 已 confirmed-read，但对声明父对象返回 `code=2000` /
  `permission_unavailable`，这是上游限制，不是本地未实现。快手计划/创意此前只是弱证据 POST。
- D32 缺的是非腾讯素材/创意的非空 item schema。腾讯 asset-material 与 medium creative 已有
  非空合同；其余 draft 要么未确认读语义，要么空样本。

**读语义：**`work-dashboard` 缓存的 census raw JS 与仓库 snapshot hash 一致
（`Gdt-zhrkAV97.js` `00f350e8...`，`KuaishouAd-CEw_EhuL.js` `06f414e5...`）。

- `POST /tencent/asset/text/title/list/`：文案库装载表格；写走 add/delete/batch_bind_app。
  `app_id` 是可选筛选，空时省略。
- `POST /kuaishou/campaign/list/`：KuaishouAd Plan 装载计划表；写走 `/kuaishou/batch_options/`。
- `POST /kuaishou/creative/list/`：KuaishouAd Creative 装载创意表；写走同一 batch_options。

**探测：**3 次业务 HTTP + 1 次登录，全部 HTTP 200 / attempt 1 / retry false，无翻页、无扩窗、
不换父。`material.tencent.list` 的 4 个空数组人员容器本轮未拿到非空样本，继续不登记。

| # | operation | 结果 |
| ---: | --- | --- |
| 1 | `material.tencent_asset_text_title.list` | `inconclusive_empty`；分页壳 `page_info`；无 item schema |
| 2 | `promotion.kuaishou.campaign.list` | `inconclusive_empty`；`data.list`/`data.total` 空；分页实测 `none` |
| 3 | `material.kuaishou_creative.list` | 同上 |

**推不动的卡点：**

- D33/D34：腾讯创意层是上游 `code=2000`；快手计划/创意是上游空投放行。本地已补读语义确认。
- D32：腾讯标题库与快手创意已 confirmed-read，但仍无非空 item schema。4 个空数组人员容器
  证据不够，主动未登记。
- 不新增产品卡。冻结评测 J45/J46 题集未改。

**台账汇总不要在本提交重算。** 本行建议：operation/stable/产品卡/精确 gap/selector 保持
235 / 226 / 93 / 7 / 332；动线保持 `56 = 50 / 3 / 3`（两条仍是部分闭环）。合并时对账。

生产 HTTP：登录 1 + 业务 3 = 4。receipt 核账：三条目标 POST 各 1 次 200，另 1 次登录 200。
不 push、不碰 GitHub。
## origin_event 导出闭环（2026-08-17）

`analysis.event.list.yesterday_count` 在第三 catalog App 的两页共 129 个事件上全为 0，不能当 create 门。同 App 7 日窗 `evaluate_data` 对一个非预设事件返回 `data.total=0`，对第一个可见 `$` 预设事件返回 `data.total=1`。随后一次 create 得 task id，首次 poll READY，下载为 511-byte gzip CSV（`text/csv`、magic `1f8b`、URL 后缀 `.csv.gz`、展开 803 bytes），表头 `客户ID(client_id)/用户注册时间/事件发生时间/事件/事件属性`，1 行且五列皆非空。empty gzip 形状未在线验证。

本轮生产 HTTP 超过 20 次上限后停止新 create。SDK/CLI/Agent 现把 `export.analysis.origin_event.start` 标为 verified/callable；文件协议是 gzip CSV，不是 XLSX。台账 `56 = 50 / 3 / 3` 不要在本轮重算；建议这条动线仍为部分闭环（六个可调子路径里 origin 已补上，宽问法冻结评测未改）。

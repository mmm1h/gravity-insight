# 分析动线台账

本页是分析动线完成度的长期事实源。每行回答一个独立分析问题；同一产品的 list/prepare/run、batch、分页和日期模式不拆行，raw operation、维护命令、任务状态路由也不单列。新增独立产品合同或独立结果 envelope 时新增一行，能力、证据或入口变化时原位更新。

闭环判据沿用[路线图](roadmap.md)：已知输入 1 次调用、未知输入 2 次调用，CLI/SDK/Plan/Agent 四面可达，结果为带 `schema_version` 与离散 `result_source` 的 envelope，能区分空、部分失败和能力缺口；请求未知字段及响应字段消失/类型变化 fail-closed，新增响应字段省略后放行并写结构化 drift audit。Agent 一面不再以卡已注册或精确 selector 自证：每行至少一条中文和一条英文分析师问法都须第一次调用命中正确产品；真实歧义的 `MULTIPLE_INTENTS` 必须含正确候选，能力缺失则须返回目标明确且带可执行 next action 的 gap。调用次数是调用方顶层命令/SDK 调用数，不是 composite 内部 HTTP 数；`实测` 指本轮离线发现加 Plan dry-run，`控制流` 指离线发现实测后核对 handoff/Plan 路径，`未验证` 不作达标声明。

下面原为 `1 / 3` 的 9 条动线现可显式使用在线输入解析：第一次
`gravity agent --resolve-inputs ... --output ...`（SDK 为 `resolve_capabilities()`）同时发现能力并交付
完整 live catalog，或完成冷 metadata catalog 的原子刷新；调用方精确选择后第二次执行。选择没有折进
执行，内部 HTTP 数也没有减少。App/平台也未知时不适用该两次路径；默认离线 Agent 的原三次下界保留。
`gravity.agent-call-bound.v1` 只在本次成功交付完整目录的卡与 Plan 节点上把对应 scenario 声明为 2。

当前程序化重算：**55 条产品动线：已闭环 47 / 部分闭环 1 / 完全缺失 7**。可复算：下表 59 行，
减去 2 条兼容/维护便利面、1 条“既有稳定读取面重复”和 1 条“已有结果上的调用方派生便利面”，
得到 55 条；按状态直接分组为 `55 = 47 / 1 / 7`。设置 → 应用管理先把基线推进到
`52 = 43 / 1 / 8`；设置 → 应用管理的真实列表 route 证明 J39 应由既有 stable `app.list` 承载，
故 `43 + 1 = 44`、`8 - 1 = 7`，总数与部分闭环不变；随后新增“定义、更新并在真实多维查询中使用
自定义指标”这一条独立闭环，故 `52 = 44 / 1 / 7` → `53 = 45 / 1 / 7`；事件/属性模板治理再新增
一条可复用上游对象闭环，推进到 `54 = 46 / 1 / 7`。保存分析 CRUD 再新增一条独立资产生命周期，
真实重放响应最初未落盘，故先记部分闭环；2026-08-17 已用原样保存对象重放并把聚合值
`235176.0` 与 governed response 落盘，推进为 `55 = 47 / 1 / 7`。
operation/stable 为 231 / 222（185 read + 37 governed mutation）；canonical 产品卡先由 45 增为 73，
再加 4 张自定义指标卡、4 张模板动作卡和 3 张保存分析动作卡得到 84；本轮四个独立
Analysis export creator 再增 4 张卡得到 88。精确 gap 为 9，安装目录为
`231 + 88 + 9 = 328` 个 selector。唯一部分闭环是只关闭五个服务端子类的 Analysis 导出
（单用户事件、分群结果、分群用户明细、用户明细、付费事件），变现明细与原始事件导出仍是精确 gap；
7 条完全缺失里多数是合同证据阻塞，逐行有记录。

2026-08-16 受治理写目录覆盖只改变发现表达，不新增产品动线或 operation。canonical inventory 保留
3 个既有默认 mutation selector，并为其余 28 个调用方动作增加 action-qualified 卡：
Segment `8 actions / 7 operations`、报表/订阅 `4 / 3`、Kanban `19 / 18`，故产品卡
`45 + 28 = 73`、安装目录 `223 + 73 + 9 = 305`。31 张 mutation 卡覆盖 28/30 条底层写 operation；
3 条共享 operation 各承载两个产品动作。剩余 `report.template.create/update` 是订阅验证父对象的内部
脚手架，没有调用方 CLI/统一 SDK 动作，不伪装成独立产品。所有 action 卡仍只交付 dry-run、人工审查、
同参数 execute；Segment/报表不进入 Plan，Kanban 只接受显式 preview/execute，owner gate 未改变。

2026-08-16 沿设置 → 应用管理 / 元数据和多维报表入口做受控生产复核。App 管理的账号级 GET
`/turbo_engine/api/v1/user/open_app/list/` 首屏 HTTP 200 非空 7 行；观察字段与既有 `app.list` v4
投影完全相等，因此不新增 operation，只解除 J39 的错误 gap 并补中英首问。元数据页自然发出的
`POST /turbo_engine/api/v2/event_dim/data_table/list/` 使用空 `app_id_list`、空 `name_like` 和第一页，
HTTP 200 明确空；没有合法 `table_id`，detail/version 均未发送，F41 不变。D28 当前
`NewReportCenter` 使用 `/turbo_engine/api/v3/confmetric/{metric,permission}/list/`，而 SDK 现有
`report.multidim.metric.list` 仍发往旧 `/report/api/v3/confmetric/metric/list/`；7 次旧 route HTTP
虽均为 200，但一次错误 operator、一次正确当前 filter 都被语义拒绝，中间一次宽查询自动读取 5 页且
1124 个旧目录项中没有 `monetization_report`。因此本轮三选一判为“请求参数/路由不对”，不能据此断言
租户无数据或权限未生效；在每线 8 次上限前停手，不发送主结果 route，不登记任何推测响应字段。

2026-08-16 自定义指标闭环使用当前 turbo `custom_metric/list|edit|delete` 创建并读回
`GSDK-67f4c39fba2d`，平台分配字符串 ID `pIgEhWsPjMvEfWrW_277516`；更新后，既有旧前缀
`report.multidim.custom_metric.list` 与 shared 目录完成 live metadata 校验，随后
`report.multidim.query` 在 App 29034827、2026-06-01 至 2026-07-10 返回 40/40 个含请求指标值的日行。
删除后当前目录连续两次明确空，残留 0。该任务的定义对象、更新/删除治理和查询消费均可由
CLI/SDK/Plan/四张独立 Agent 产品卡完成，新增 1 条已闭环动线。

2026-08-16 事件/属性模板治理闭环复核 9 条 Census 候选后，只晋升 4 条能组成模板 master 与成员
生命周期的 route；分组 UI 配置、无 owner 证据的事件属性批删、不可安全清理的用户属性导入均不为
端点数接入。生产以 App 27018426 的属性目录 ID 2573861 创建
`metadata CRUD acceptance [GSDK-6c612a3c1f78]`，平台分配模板 ID 121075 和成员 ID 669697；成员 ID
与源目录 ID 不相同，产品据此以稳定 `name` 做创建/追加读回映射，并让 remove 显式接收
`member_ids`。成员移除后读回 `member_ids=[]`，模板软删后 master ID 消失，最终零残留。四张动作卡
分别表达 create/append/remove/delete，Plan 只接受 preview/execute，自然语言不自动写；新增 1 条
已闭环动线。

2026-08-16 从 README/索引按十分钟路径生产复验，12 条主路径命令、3 次 HTTP 后取得既有
`analysis.event.query` 的真实 governed result；认证、`app.list`、最终查询均 HTTP 200，无重试、翻页、
换 App 或扩窗。当时 `app.list` 外层出现 `contract_changed/ok=true/exit 0` 矛盾；同日后续修复证明
`sub_package_list` 的登记漏了 `list[string]` 类型，并把 breaking drift 统一为 `ok=false/exit 3` 和
结构化 `CONTRACT_CHANGED` 诊断。两次横切修正都不新增产品动线，因此总账严格为 `51 + 0 = 51`、
`42 / 1 / 8 + 0 / 0 / 0 = 42 / 1 / 8`，operation/stable 仍为 `205 / 196`。

同日冷启动收口没有新增分析产品动线：单 App metadata sync 与 status 是既有“离线查找物理名称”动线的
onboarding/维护入口，category 排序只改变展示顺序。因此总账仍为 `51 = 42 / 1 / 8`、operation/stable
仍为 `205 / 196`；canonical 卡由 42 增为 44。全新独立 SQLite 的生产实走为 12 条主路径命令、7 次
HTTP：认证、`app.list`、四类单 App metadata 和最终事件分析各一次，全部 HTTP 200 / attempt 1 / 0
retry；metadata 四类均只读第一页并写入 177 个物理对象，离线 status 为 ready。旧版本的温目录实测为
12 命令/3 HTTP；若严格冷目录再插入唯一的 `sync --all-apps`，为 13 命令，当前 7-App 租户可证明最少
41 HTTP，但由于每 App 分页无界，精确值无法在同步前由代码确定。

metadata onboarding 与 `dev@d5cc59b` 合并后再次按表格状态列重算：质量棘轮、分群删除调查、干净
selector 测量和 metadata onboarding 都没有新增独立产品动线或改变现有行状态。表中仍有 55 个数据行，
扣除 4 个明确标为“不计独立动线”的便利/重复面，得到 51 条；直接分组为
`42 已闭环 + 1 部分闭环 + 8 完全缺失 = 51`。

2026-08-16 F40 按 catalog 顺序枚举 6 个 App，在第 6 个首次取得 1 条测试设备后立即停止，并以内存
父行 ID 只发 1 次详情请求。生产共 8 次业务 HTTP：1 次 `app.list`、6 次
`app.testing_tool.list`、1 次 `attribution.attribution_detail.query`；全部 HTTP 200，0 重试、翻页、
扩窗或鉴权刷新。详情成功返回完整 `device_white`，`attribution_list/postback_list/pay_list` 三个容器
均明确为空；其 item schema 不猜测，未来出现非空 item 时产品 fail-closed。两个 stable operation
暴露全部观察字段；Core/CLI/SDK/Plan/Agent 共用 `gravity-insight.attribution-user-detail.v1`。

2026-08-16 以受控生产写解开报表目录与订阅的非空 item schema。旧报表在 `remark`、v3 订阅父报表
在 `remark`、订阅在 `name/wildcard_name` 原样 round-trip `GSDK-<12 hex>`；所有真写均先 dry-run，
删除前由列表或 detail 重读 marker，删除后完整列表确认消失。两条既有读取动线因此从完全缺失转为
已闭环；同时沿用 Segment 的“调用方可独立完成任务、终点是可复用上游对象”口径，把报表 CRUD 与
订阅 CRUD 各计 1 条新增闭环动线。v3 父报表只是订阅 CRUD 的实现脚手架，不另拆动线。写任务的
Plan 面逐条登记为设计不适用，读任务仍是无副作用 Plan composite。生产实际 7 次单次、不重放的
write 和 32 次 read；最终旧报表、订阅与 v3 父报表三份完整列表的 SDK marker 均为 0。

2026-08-16 的写操作范围裁决新增 7 条 stable Segment mutation，把“运行漏斗 → 将某一步命中或
流失用户持久化为分群 → 继续做留存/成员分析”的中间桥接从 Web 移入 SDK。按本台账“一个调用方
可独立完成的分析任务”口径，它不是“查看已有分群详情/成员”的变体：调用方可以只完成保存、更新、
刷新或删除分群，而不读取详情结果；产出也从读取 envelope 变为可复用的上游分群对象。因此新增
1 条已闭环动线，合并前后为 `48 + 1 = 49`、`36 / 1 / 11 + 1 / 0 / 0 = 37 / 1 / 11`；operation
`187 + 7 = 194`、stable `178 + 7 = 185`。写入口有 Core / CLI / SDK / Agent 明确命令交接；Plan 面按
已登记窄例外记为“设计不适用”，自然语言不自动执行。闭环证据只使用已有生产验证的
`from_analysis`、`from_rule`、`by_manual` 与 `save` 路径；`from_history_version/create` 和
`from_tmp_segment/create` 只有 wire/dry-run/测试，未计入闭环证据。生产共 10 次单次、不重放的写尝试，
两个实际创建的 SDK 测试分群均已读回并删除，最终列表验证残留 0。

2026-08-16 的 Agent 渐进发现与生成任务指南是既有调用方入口的可读性改进，不新增 operation、结果 envelope 或产品动线：`48 + 0 = 48`、`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`，operation 仍为 `185 + 0 = 185`、stable 仍为 `176 + 0 = 176`。它的独立三层只读入口从既有 composite card 和 compiled manifest 派生；真实查询仍经既有 Agent card/Plan/CLI 合同。生产 HTTP 0 次。

2026-08-16 对 155 条非推广/素材 draft 未覆盖读路由完成逐条语义复核：离线初判为
`18 等价覆盖 / 89 UI 辅助 / 4 mutation / 18 可自取证 / 21 证据阻塞 / 5 无法判定`；10 次有界生产
HTTP 后，18 条可自取证候选均因明确空、semantic error、缺父值或缺已证值域转为证据阻塞，最终为
`18 / 89 / 4 / 0 / 39 / 5 = 155`。没有取得成功非空合同，因此不新增本表动线：
本线派发快照 `48 = 33 / 0 / 15` 的净变化为 `+0 / +0 / +0`；合入默认值字典闭环后，当前为
`48 = 34 / 0 / 14`，operation 186、stable 177。
这次盘点收窄的是未知路由的语义边界，不把 UI 辅助 route、raw operation 或失败 probe 计作分析产品。
旧快照 `21/14/6` 没有逐条证据，不能复算；本台账不还原已丢失的原始 41 条定义。

2026-08-16 新增“在已有结果上执行调用方绑定的派生算术与集合对账”便利面。CLI/SDK/Plan/Agent
四面共用 `gravity.derived-metrics.v1`；ratio/share/change/reconcile 不内置字段含义。未声明业务公式的
自然语言请求得到 `DERIVED_METRIC_BINDING_REQUIRED`，workspace `gravity.semantic-context.v1` 已声明
完整 spec 时才预填公式并生成可执行 Plan 节点。该节点补入 source 后已离线端到端算出结果，但它变换
已有 envelope，不独立取得上游数据，故保留审计行而不新增产品动线：
`48 + 0 = 48`、`34 / 0 / 14 + 0 / 0 / 0 = 34 / 0 / 14`；operation/stable 均 `+0`，
该单元派发时为 186/177，生产 HTTP 0 次；当前总账统一见顶部 `42 / 1 / 8` 与 205/196。

2026-08-16 对最后两条工程可推动线做了静态控制流与最小生产取证，两条均推进但未闭环。A 的 8 条
真实 frontend binding 已恢复，唯独 `stream_event` 的 server loader 没有调用点；首 App 当日用户第一页
为空，故生产只读 2 次且没有 create/poll/download。B 生产 5 次，证明一个视频 URL 的 HEAD 200、
1 KiB Range GET 206、`video/mp4`/ISO-BMFF magic 和无重定向，以及缩略图 HEAD 405；仍缺完整
origin/redirect/expiry/size 与历史失败合同。投影层把本轮观察字段全部登记暴露，但不把样本 host 动态
学习成 allowlist。计数推导为 `48 = 33 / 0 / 15 + 0 / 0 / 0 = 48 = 33 / 0 / 15`；operation
`185 + 0 = 185`、stable `176 + 0 = 176`。详见[路线图](roadmap.md#最后两条可推动线复核analysis-导出--平台素材二进制2026-08-16)。

同日第二轮按授权枚举 3/7 个 catalog App，在第三个首次取得非空单日事件时间线后停止；A 生产 HTTP
9 次，一次 create、首次 poll 即 READY、一次 download 得到 7 行/5 列且存储与逻辑类型完整的 XLSX。
`user_event` 子类现可调用；其余六个服务端导出只共享任务协议，仍各需自己的成功文件 shape；
`stream_event` 因 loader 无调用点、按钮走客户端序列化改记 `not_applicable`，不再当 SDK 缺口。
B 生产 HTTP 10 次，4 个自然缩略图的 64-byte Range GET 均为 206/JPEG/无重定向，本轮五个素材引用
同属 `tos-accelerate.gravity-engine.com`；累计 3 个 host 仍不足以证明外部 CDN shard 全集，且四类
失效语义静态检索仍未知，故 Issue 19 不闭环。公开 bundle GET 为 4 次/4 个唯一 URL，此后全为本地
检索。计数从 `48 = 33 / 0 / 15` 经 A `+0 / +1 / -1`、B `+0 / +0 / +0` 得
**`48 = 33 / 1 / 14`**；operation 仍为 185、stable 仍为 176。详见
[路线图第二轮判定](roadmap.md#第二轮纠错与闭环判定2026-08-16)。

第三轮撤销 CDN shard allowlist 这个错误前提，改以“URL 必须来自产品刚执行的已登记 operation
响应”为真实输入边界。公开 Core/CLI/SDK/Agent 都不接受 URL；host/path 不枚举、不限制，redirect
跟随并只记录值无关 host family/cross-host 事实。项目目录第一页返回 20 个引用，跳过已知空首项后
检查 5 个项目，在 position 6 首次非空并停止；加一次 64-byte 平台缩略图 Range GET，总计生产 HTTP
7 次、0 重试/翻页/扩窗，得到 `p{shard}-sign.douyinpic.com` 的 206/JPEG/JPEG magic/无 redirect。
本地与 Bytedance 平台各自有独立 JPEG+MP4 证据并分别登记 source family，Issue 19 整条闭环；Plan
按文件 effect 的三项窄条件登记设计不适用。计数由 `48 = 33 / 1 / 14` 加 `+1 / +0 / -1` 得
**`48 = 34 / 1 / 13`**；operation/stable 仍为 185/176。详见
[路线图第三轮判定](roadmap.md#第三轮response-bound-素材文件合同2026-08-16)。

上述三轮是 export-binary 分支从自身派发基线的局部推导；合入默认值字典、D35 与派生便利面后，
当前总账统一为 `51 = 42 / 1 / 8`，operation 205、stable 196。

2026-08-15 的结果来源等级是横切合同修正，不新增独立产品或结果 envelope。三条执行责任边界为
`governed_product`（固定产品合同）、`caller_defined`（workspace recipe / SQL product，调用方负责口径）
和 `raw_operation`（只保证 operation 合同）；离线目录及异构 Plan 分别使用 `local_catalog`、`mixed`。
CLI JSON/NDJSON/文件、SDK、Plan node/顶层与 Agent 执行 handoff 共用 `gravity.result-source.v1`，外层
schema 版本不变。计数推导为 `48 + 0 = 48`、`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`；
operation 为 `185 + 0 - 0 = 185`，stable 为 `176 + 0 - 0 = 176`。生产 HTTP 0 次。

2026-08-16 的调用方语义上下文是横切发现机制，不新增独立分析产品或结果 envelope。workspace 可用
`gravity.semantic-context.v1` 声明 literal term、instructions、structured exclusion 和 verified
question→stable read operation input；未知产品/operation 在加载时、未知 event/property/metric 在 Agent
preflight 时以 local/4 fail closed。verified question 精确硬绑定；term 与现有产品证据冲突仍返回
`MULTIPLE_INTENTS`，产品负向约束优先。语义命中候选复用 `caller_defined/caller_responsible` 与
`description_origin=caller_workspace`。计数推导为 `48 + 0 = 48`、
`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`；operation `185 + 0 - 0 = 185`、stable
`176 + 0 - 0 = 176`。生产 HTTP 0 次。

D23/D29/D30 只剩依赖箭头、语义不可验证，故保留在此说明而不强挂到新动线。候选
`app.project_auth.detail`、`app.user_auth.list` 属成员权限管理，按 roadmap 非目标排除，不计动线。

2026-08-15 按新 Agent 判据冻结 47 条动线中英各一问并重验：已闭环 baseline 为
`6 双语达标 / 7 单语达标 / 19 双语不达标`，修复后为 `32 / 0 / 0`，原达标问法回归 0。
15 条完全缺失没有发现可执行结果，但 15/15 均能由中英首问得到各自专属 next-action gap；因此
缺失行只把 Agent 一面改为“有”，不改变整体状态。计数推导为
`47 = 32 / 0 / 15 + 0 / 0 / 0 = 47 = 32 / 0 / 15`。逐题 before/after 与原始候选顺序保存在
`tmp/codex/nl-reachability/`；94 次均为离线调用，生产 HTTP 0 次。

同日新增的可重复 Agent 可用性装置不再把上面固定首问当发布证据。旧 v1 的 47 条/470 题结果仅作
历史基线；其密封 key 丢失后 payload 不可恢复，且它漏掉实际存在的 Issue 19 动线。冻结 suite
`gravity-agent-usability-2026-08-15.v2` 按当时 48 条动线各构造 10 题，共
`48 × 10 = 480`，开发/密封留出各 `48 × 5 = 240`；每题 4 trials。产品树未改的新基线为：
开发/留出首次产品选择分别 `154 / 240` 与 `147 / 240`，正确产品已到达后的参数来源可填
`108 / 108` 与 `105 / 105`，可离线验证终点 `46 / 80` 与 `42 / 80`；两侧产品选择和终点的
`pass^1 = pass^4`，错误恢复均为 `4 / 5`。另各 160 条稳定读取题因会触发生产 HTTP 而明确跳过，
不能把离线终点比例外推成全动线端到端成功率。装置没有修改本表任一产品面：
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`；方法、留出安全边界、失败分类和复现入口见
[路线图](roadmap.md#留出集重建与可操作-key-托管2026-08-15)。

本次 Segment mutation 合并不修改评测装置、题集或 split，所以 dev 分母仍为 240；新增的第 49 条
写动线由 mutation 安全层验证“已登记且经一次性授权”的写身份，不把它伪装成只读 Agent 题，也不读取
holdout/final。后续若要把写动线加入题集，须走评测装置专线另行版本化。

2026-08-16 的 development-only 路由候选不新增产品、动线或执行能力，台账仍为
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，operation 仍为 `185 → +0 = 185`。
同一 v2 development 的首次产品选择从 `154 / 240` 到 `240 / 240`，已到达卡的参数来源从
`108 / 108` 到 `160 / 160`，离线终点从 `46 / 80` 到 `80 / 80`；选择和终点均
`pass^1 = pass^4`，错误恢复从 `4 / 5` 到 `5 / 5`。失败归因净变化为
`25 错误产品 + 16 无候选 + 33 错误/generic gap + 12 错误歧义 = 86 → 0`，目标 gap 未返回
`34 → 0`。这只是 development 结果，密封留出未运行，不能作为发布泛化结论；实现范围、反事实自查和
偏拟合风险见[路线图](roadmap.md#development-only-自然语言路由候选2026-08-16)。生产 HTTP 0 次。

2026-08-16 的引力原生 AI 摸底只确认一项上游重叠能力，不新增本仓库产品、动线、operation 或结果
envelope：本线相对派发快照的净变化全为 0；合入默认值字典闭环后，当前为
`48 = 34 / 0 / 14`、operation 186、stable 177。hash-matched Event bundle 证明它把自然语言转换成事件分析
配置并一键回填现有页面，不直接返回结果；唯一通用在线问法返回空 `data`，未验证成功配置。生产 HTTP
共 4 次（认证、App 首项、建会话、发消息），均 200、无重试/翻页/扩窗/换 App。事实、账本与未决见
[原生 AI 摸底](research/gravity-native-ai.md)；现有三臂 A/B、recognizer 和排期均未改变。

2026-08-16 的三分评测、protected 查询账本与安全遵守层只改评测装置，不新增产品、结果 envelope
或 operation。既有 development/holdout 仍为 `240 + 240 = 480`，另加独立 final 48 题，物理题量为
`480 + 48 = 528`；legacy `all` 保持 development+holdout，不改变旧结果含义。development 四层改前/后
均为 `240/240、160/160、80/80、5/5`，差值全 0；新增二元安全门禁独立为 FAIL/15，命中的是
metadata/table-lineage catalog sync 与 material export `--output` 副作用交接，不回写旧层分数。本轮没有运行
holdout/all/final，protected query ledger 查询数仍为 0，生产 HTTP 0 次。计数仍是
本线相对派发快照净变化 `+0 / +0 / +0`；合入默认值字典闭环后，当前为
`48 = 34 / 0 / 14`、operation 186、stable 177；设计、盲区和可复算账本字段见
[路线图](roadmap.md#三分评测查询账本与安全硬门禁2026-08-16)。

第五批合并自证没有把更小数字当作通过：development 实际为
`235/240、160/160、75/80、5/5`，第五层 `PASS / 0`，本地写入信息项 15。缺失的 5 项全部是 J34
默认值字典题：题集仍期待晋升前的 `ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`，而本批闭环后正确返回
`composite:analysis_default_dictionary`，评分遂记为 `wrong_gap/target_gap_missing`。在“不改题集、不改评分
逻辑、不让产品伪报旧 gap”的合并约束下，`240/240、160/160、80/80、5/5` 的纯加法结论尚未成立；
本次未运行真实 holdout 或 final。

2026-08-16 评测预期改为按本表状态派生：题面和 `journey_id` 仍由各 split 冻结，公开
`evals/agent_usability/journey-targets.json` 只登记每个 ID 对应的本表精确行、产品目标和目标 gap；
evaluator 直接解析本表状态列，不复制第二份状态台账。已闭环期待严格产品卡，完全缺失期待严格目标 gap；
部分闭环也期待目标 gap，因为现有 case 的目标身份是整条动线、没有密封的子路径身份，接受一个子路径卡会把
未支持的兄弟路径伪装成闭环。测试会把同一冻结 J34 case 的本表状态临时改成部分闭环，验证预期自动从
`composite:analysis_default_dictionary` 切回其目标 gap；错误产品卡仍记 `wrong_product`。本次只跑
development，未运行 protected split，生产 HTTP 0 次。当前集成树 development 实测为
`240/240、175/175、65/65、5/5`，第五层 `PASS / 0`；参数与终点分母 `175 + 65 = 240`，
selection/terminal 的 `pass^4` 分别为 `240/240`、`65/65`。

2026-08-16 的自然语言三臂对照不新增产品、动线或 operation。臂 A recognizer 不改；臂 B 只在原链
零候选且无专属 gap/阻断时，对既有 card/gap 文案做确定性 IDF 词法检索，阈值 0.375、至少两项证据，
单命中复用原 card/gap，多命中仍返回 `MULTIPLE_INTENTS`，低分 abstain。development 前后六层均为
`240/240、175/175、65/65、5/5、pass^1=pass^4、PASS/0`；当前 development 的 no-candidate 已为 0，
所以实际净修复 0，shadow 28 个正确单命中不计新增通过。臂 C 外部 selector 协议与固定离线桩已完整
跑 4 trials 并被原层评分，桩为 `27/240、27/27、0/65、5/5、PASS/0`，只证明可测。固定 holdout key
在当前及文档指定 custody worktree 都不存在，未生成替代 key，故 holdout/final 查询仍为 0；不能声称
达到 `228/240`。本线计数为 `49 = 37 / 1 / 11 → +0 / +0 / +0 = 49 = 37 / 1 / 11`，生产 HTTP 0 次；
阈值、拟合风险和真实 LLM 所缺条件见[路线图](roadmap.md#自然语言路由三臂对照2026-08-16)。

2026-08-16 development-only 扩题不新增产品、动线、operation 或执行能力；评测 registry 仍是
Segment mutation 进入台账前冻结的 48 条只读动线身份。原 240 题逐字保留，每条动线新增 2 题，故
development 为 `240 + 48 × 2 = 336`，每条覆盖 `5 → 7`。新增 96 题按主族互斥计数为：业务目的 13、
口语省略 12、错别字/拼音 12、中英混杂 12、多轮首轮 12、反向否定 12、跨产品多意图 12、目标 gap
11；最后 11 题逐一覆盖当前 11 条完全缺失动线。只运行 development 后六层结果为：首次选择
`261/336`，到达卡的参数可填 `188/188`，离线终点 `73/91`，错误恢复 `5/5`，selection/terminal
`pass^4 = 261/336、73/91` 且不稳定题 0，第五层 `PASS / 0`。75 个首次选择机械失败为
`13 错误产品 + 43 无候选 + 16 错误/generic gap + 3 错误歧义`；其中 3 个“错误歧义”实际都按公开
工作流正确返回 `MULTIPLE_INTENTS`，只是单 `journey_id` 的现评分无法表达该正确答案；同族另有 4 题
因只返回其中一个登记目标而被机械记为通过。因此这 12 题须单独人工读数，不能拿机械分数指导产品退化。
没有读取、解密、重建或运行 protected split，生产 HTTP 0 次；方案、命令与逐类结果见
[路线图](roadmap.md#development-题集扩充2026-08-16)。

将扩题合入已有臂 B 后复测，以上六层与四类失败数字逐项不变。臂 B 在 336 题中触发 52 次，全部低于
0.375 阈值而 abstain，正确/错误单命中和 `MULTIPLE_INTENTS` 均为 0，净救回 0；43 个无候选中 40 个
进入臂 B，3 个被原链显式产品边界阻断。40 个中的 35 个 top score 非零、5 个为零，故“普遍词法重叠
为零”不成立，真实结果是已有重叠不足以达到固定覆盖阈值。多意图的 3 个假失败和 4 个假通过也逐题复现；
J10 first-turn 因依赖不存在的上一轮而不能唯一决定产品，判为不公平但保持原题与评分不动。详见
[路线图](roadmap.md#development-题集扩充2026-08-16)。

2026-08-16 合入报表目录/订阅闭环后，development 仍为同一 336 题且题面逐字不变。历史 NL 回归矩阵
此前漏列 registry 的 J25 分群成员，导致原 J25–J47 的 23 条现有问法编号整体早一位；本次仅把这些
编号改引 J26–J48，并把矩阵标题对齐 `journey-targets.json`，没有改变任何中文或英文 query 的文本或
语义归属。新测试逐行要求 ID 存在且标题与 registry 完全相等。报表两条已闭环动线改为精确 selector
目标后，评分 matcher 只接受 `composite:report_directory` 与 `composite:report_subscriptions`；订阅卡
补齐“报表 + 订阅/订了/订的/定时发/定期发/自动发”正向证据，目录卡保留原负向边界且复用同一证据
排除订阅抢占。development 六层从 `261/336、188/188、73/91、5/5、selection/terminal pass^4
261/336 与 73/91、PASS/0` 变为 `262/336、201/201、61/77、5/5、selection/terminal pass^4
262/336 与 61/77、PASS/0`，两轮不稳定题均为 0、本地写交接均为 29、生产 HTTP 均为 0。14 条报表题
由原 `12 target_gap + 2 wrong_gap` 变为 `13 correct + 1 no_candidate`，故首次选择净增恰为 1；其余层
分母变化来自 13 条正确结果由 gap 终点迁移到产品卡参数层，不是评分算法、层定义或阈值变化。

2026-08-16 多意图评分 v4 只补全 12 个公开 development case 的多 journey gold，不改题面、产品或
recognizer。raw case 以 `terminal_kind=multiple_intents + journey_ids` 声明题面原有的两个目标，scorer
要求 `MULTIPLE_INTENTS` 且 public candidate selector 集合精确相等；少、多、未知或重复候选都失败。
历史 NL 矩阵的旧 J25–J47 对应当前 registry J26–J48，但 development case 自扩题提交起已按 registry
编号，当前 12 题是 J25–J34 中的 10 题、J42 和 J47。旧 240 题 raw/derived SHA-256 与四次 trial 的
逐题 selection/parameter/terminal/reasons 前后完全一致；全 336 题只有这 12 题变化，324 题不变。
六层由 `262/336、201/201、61/77、5/5、pass^4 262/336 与 61/77、PASS/0` 变为
`259/336、198/198、63/88、5/5、pass^4 259/336 与 63/88、PASS/0`。此前 3 个
`MULTIPLE_INTENTS` 只按 code 人工计对；精确候选复核后，J30 把素材导出 J33 错成素材表现 J15，J31
把 metadata search J31 错成 app governance J09，仅 J26 的 J26+J02 精确，所以真实为 **1/12**。
protected case 缺少新字段时继续逐题走旧评分；结果机器标注
`PROTECTED_LEGACY_MULTI_INTENT_EXPECTATION_BIAS`，现有密文不读取、不重建。完整多目标表与可复算账本见
[路线图](roadmap.md#多意图评分表达修正2026-08-16)。

2026-08-16 的路由第二轮不新增产品、动线、operation 或执行能力。臂 B 的 48 个可安全重物化
card/gap identity 均增加本表调用方动线标题与 `agent-workflow.md` 独立任务描述，共 60 个字段；
三条 governed mutation 动线继续由原 recognizer 保留具体 action、dry-run 与人工确认，不进入静态
fallback。索引单独且阈值仍为 0.375 时，development 六层与失败归因均不变；52 个触发的 top score
P50 `.038222→.053143`、P90 `.105248→.195502`、最大 `.285469→.320407`。按预承诺的零新增 wrong/
错误歧义、旧 240 逐题不退化准则，11 点曲线最终选择 0.300：只救回 J35 的精确目标 gap，
固定原 52 位点上 `correct/wrong/multiple/abstain = 1/0/0/51`；其中 5 个纯否定被进一步 fail closed，
实际进入词法评分 47 个。最终六层为 `263/336、201/201、62/77、5/5`，
selection/terminal `pass^4=263/336、62/77`，安全 `PASS/0`、不稳定 0、生产 HTTP 0；旧 240 仍
240/240，逐题结果语义不变差，只有公开 receipt 的阈值字段按设计 `0.375→0.300`。
排除 12 道多意图后失败归因 `44/14/8/0→44/13/8/0`，失败基数 `66→65`。口语省略仍 `0/12`、
只描述业务目的仍 `1/13`，因此这条词法路线在安全阈值下对两族无效。完整准则、11 点曲线、排除 ID、
分位数和拟合风险见[路线图](roadmap.md#自然语言路由第二轮调用方语言索引与分布阈值2026-08-16)。

两项合并后的实测口径为 `260/336、198/198、64/88、5/5`，安全 `PASS/0`。上段的 `263/336、201/201、62/77` 是多意图评分修正合并前的测量，合并后 12 道多意图题按精确候选集合重判，故以本行数字为准。

同一 `dev@bafa6cc` 上的臂 C 盲选实测不改本表状态、题集或评分器：宿主模型只看 336 个
`case_id + prompt` 与 `agent-catalog` 的 8 类 / 229 selector 三层目录，锁定固定映射后才读取预期。
六层为 `172/336、167/167、8/88、5/5`，selection/terminal `pass^4=172/336、8/88`，安全
`PASS/0`、不稳定 0、生产 HTTP 0；相同臂 A 为本段上行的 `260/336、198/198、64/88、5/5`。
八族 A→C 为口语 `0→9/12`、业务目的 `1→7/13`、首轮 `1→4/12`、否定 `1→11/12`、错字
`3→6/12`、中英混杂 `10→3/12`、多意图 `1→5/12`、目标 gap `3→2/11`。臂 C 的 96 个 `none`
按精确目标反查均无目录匹配；协议又不能返回目标 gap code，故该总分不能被解释成“LLM 语义只值
51.19%”。产品、动线、operation 计数保持 `48 = 34 / 0 / 14 → +0 / +0 / +0`；完整归因、效度威胁和
“目录身份 parity 优先、recognizer 暂留但不再扩开放词表”的裁决见
[路线图](roadmap.md#臂-c宿主-llm-盲选能力目录实测2026-08-16)。

2026-08-15 的失败与降级路径审计自身不新增动线，在当时快照上的净变化为
`48 + 0 = 48`、`32 / 0 / 16 + 0 / 0 / 0`；最终计数只因上述 setting route 重复记账消除而变为
`47 = 32 / 0 / 15`。该审计横切核对了所有现有 composite、Plan 和 direct SDK/CLI
入口：明确空保持 `ok=true/status=empty/exit 0`；独立组件失败保留完整成功兄弟并形成
`status=partial` 与非零主错误 exit；Agent 无法形成可执行能力时保持 `status=capability_gap`，不伪装
成 empty 或 upstream failure。单组件分页中断不发布未经完整性验证的页前缀，只有已声明 bounded
continuation 的 safe-max 产品可返回带 continuation 的 partial。三态因此可由 status、ok、exit 和
结果/缺口容器机械区分，而不是依赖错误文案。

2026-08-15 的 20 题 Agent 端到端实测自身不改计数：在当时快照上
`48 = 32 / 0 / 16` 加 `0 / 0 / 0`，仍为 `48 = 32 / 0 / 16`；最终计数只因上述 setting route
重复记账消除而变为 `47 = 32 / 0 / 15`。它测的是自然语言路由与卡可执行性，不是重新做
closure audit。
但它在当时快照上证明若干“已闭环”行的自然语言入口会中断：属性/散点的正确 Spec 卡会与 raw operation 并列，
class-level metadata search 没有产品卡；title-package 的显式日期+双类型问题没有边界 gap；Custom
Audience/ Bilibili 执行分别暴露不可复制的 contract/pagination next action。事件、留存、素材、广告主
profile、看板重放的窄 recognizer 已在当轮领域模块修复。完整事前题单与逐题原始判定保存在本轮
`tmp/codex/agent-usability/` 工作底稿；这些自然语言欠账现已由上方 47 条中英首问重验取代，历史结论
不再代表当前路由状态。

2026-08-15 的 HTTP receipt 耐久性修复是横切可靠性修正，不新增产品、入口或 envelope 字段，故台账
计数不变：`47 → +0 = 47`，`32 / 0 / 15 → +0 / +0 / +0 = 32 / 0 / 15`。所有仓库 production
transport 在 response 返回后、任何本地投影/分页/组件处理前，将值无关逐请求 receipt 同步写入
`state_root/receipts/http/`；partial/error envelope 即使按既有安全合同省略组件内部结果，调用方仍可从
该私有账本核对 method、合同 path、operation、status、页码和 retry attempt。

同日的有界保留修正仍是横切可靠性工作，不新增产品、入口或 envelope：默认只保留最近 10,000 个且
不老于 7 天的已结束运行 HTTP receipt，活动运行全部保护；首次写后及每 64 次写后以非阻塞 lease
best-effort 清理。故台账仍为 `47 → +0 = 47`，`32 / 0 / 15 → +0 / +0 / +0 = 32 / 0 / 15`。
逐 HTTP 文件当时没有公开读取 API，只用于知道私有 state root 的事后诊断，不据此新增分析动线。

2026-08-16 的结果可审计面把上一段的私有账本提升为 layout-independent 的只读诊断合同，但仍不新增
业务产品或分析问题：SDK/CLI/Plan 共用 `gravity.http-receipt-query.v1`，结果以
`gravity.result-audit.v1` 的 opaque 引用连接实际 HTTP receipt，并以 JSON Pointer 指向原位
operation/contract/evidence/call-bound 事实。empty、partial corruption、storage capability gap、
retention-pruned、active run 与 write-failed 均为离散状态；调用方不需也不能依赖私有文件名或路径。
Plan 已实现本地 `receipt_query`，没有引用“设计不适用”例外；Agent 面不为维护诊断动作新增自然语言
产品卡。最终台账仍为 `48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，operation
`185 → +0 = 185`、stable `176 → +0 = 176`；生产 HTTP 0 次。

同日的响应漂移非对称裁决也是横切兼容性修正，不新增产品、operation 或 envelope 外层版本：未登记
响应字段从“中断查询”改为“保持既有投影并写 `gravity.response-drift.v1`”，字段消失、类型变化、
已声明枚举扩展与未知请求字段继续 fail-closed。结果内 `result_audit.response_drift` 与对应 HTTP
receipt 都可按 JSON Pointer/观察类型机械查询；维护者以 receipt 为待登记字段事实源，不另维护易过期的
Markdown 清单。台账仍为 `48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，operation
`185 → +0 = 185`、stable `176 → +0 = 176`；生产 HTTP 0 次。

同日的 LLM consumer-output 安全审计是横切结构修正，不新增或提升产品：台账仍为
`48 + 0 = 48`、`33 / 0 / 15 + 0 / 0 / 0 = 33 / 0 / 15`。程序化清单覆盖 176 个 stable operation、
51 条表格记录和 versioned envelope 源码位置；业务/调用方内容按 `data/request/results/items/candidates`
等结构根隔离，展示性文案不作为可执行指令。Find/Agent recipe description 新增 origin 元数据，公共 JSON
writer 拒绝非有限数字；operation、投影、请求、错误分类和退出码语义不变。调用方操作见
[LLM 输出安全指南](guides/llm-output-safety.md)。

2026-08-16 的 `semantic_error` 判定审计是横切纠错，不新增产品或 operation，台账仍为
`48 = 33 / 0 / 15 → +0 / +0 / +0 = 48 = 33 / 0 / 15`，operation/stable 仍为 `185 / 176`。
物理命中 `semantic_error` 文本的 787 份 evidence 中，只有 327 份真以它为 conclusion；程序化分类为
`5 明确误判 + 0 明确真错误 + 782 信息不足 = 787`，其中 782 又是
`322 个缺原始判据的标签 + 460 个仅命中 semantic_errors 容器键`。5 个明确误判均为 HTTP 204/null body，
各落在不同 operation；它们没有单独支撑当前表中的缺失理由。D35 行则由已完成归因线的补充 evidence
另行证明 `code=0/msg=成功/extra.error=无数据` 是明确空，故本表旧 `semantic error / 缺服务端证据`
说法撤销；F40 对 D35 的依赖理由同步失效，共改写 2 行。本审计没有重探测这两条动线；分类器修复只用
`promotion.kuaishou.developer.list` 做 1 次 GET 验证，HTTP 204/null body，无重试、翻页、扩窗或换 App。

事件、漏斗、留存、属性四行的“已知 1 次”同时覆盖显式多 App：同一 spec 用
`gravity.analysis-query-batch.v2` 的 `apps` 数组一次执行，逐 App 组件返回且不聚合。scatter 和其余
产品仍按当前单 App/同层 Plan 合同，不据此增加新动线或改变下表计数。

2026-08-16 的目录 parity 单元不新增产品动线、operation 或执行能力，当前总账仍为
`51 = 41 / 1 / 9`、operation 203、stable 194。安装时可枚举的 canonical Agent 产品卡由既有 owner
程序化重算为 41 张，`agent-catalog` 从原 `26/41` 补到 `41/41`；另投影 11 个已登记 gap，其中覆盖
本表 9 条完全缺失和 1 条部分闭环，额外 1 条是“workspace 未配置 SQL 产品”的环境条件 gap。raw
operation 继续保留专家入口，但明确不是产品等价物；`app.realtime_event.list` 是应用配置 raw 读，
`REALTIME_EVENT_CATALOG_CONTRACT_MISSING` 才是“实时事件目录”动线状态。本轮 development 臂 A/C 为
`260/336` 与 `334/336`；臂 C 的两处失败均是“一个产品 + 一个 gap”的混合多意图在冻结 scorer 中没有
第二个 candidate selector，未修改评分逻辑。后续以 fresh Windows AppContainer 中的 pinned
`claude-sonnet-4-6` 重测干净外部臂 C 为 `325/336`：仍比 A 多 65 题、比被污染 C 少 9 题；八族为
`11/12、11/13、11/12、12/12、12/12、12/12、10/12、11/11`。该测量没有改变本表状态或产品事实；
未查询受保护 split，Gravity 生产 HTTP 0 次。

2026-08-16 评测装置按阶段拆开外部 selector 网络与产品执行网络，并把重复可靠性的“不稳定”从布尔
对错改为实际 selector 集合。对上段同一份锁定 development trial 复算：离线终点从 `0/81` 修正为
`80/81`，保留 1 个 `target_gap_missing`；产品选择 `unstable_tasks` 从 `0` 修正为 `7`，全部是 J06
七种问法在 `composite:derived_metrics` 与 `composite:saved_analysis` 间切换。J06 目标
`analysis.query.spec` 与实现、本文工作流一致，题目没有写错；外部 selector 得到的 catalog summary
只描述五种 Analysis kind，未表达同 Spec 跨期模式，因此是目录文案缺口，留给独立目录线修复。本线
没有修改题面、recognizer、目录、operation 或本表状态，总账仍为 `53 = 45 / 1 / 7`、operation/stable
仍为 `226 / 217`；未运行 protected split，生产 HTTP 0 次。

| 动线 | 状态 | 四面可达（CLI / SDK / Plan / Agent 中英首问） | 调用次数（已知 / 未知） | 阻塞 |
| --- | --- | --- | --- | --- |
| 看某事件随时间、分组和条件的变化 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看多步行为的转化漏斗 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看起始行为后的用户留存 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看用户或事件属性的分布与聚合 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看事件指标之间的散点关系 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 用同一分析定义比较两个时期 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 在已有结果上执行调用方绑定的派生算术与声明集合对账 | 不计独立动线（调用方派生便利面） | 有 / 有 / 有 / 有（未声明公式返回目标 gap） | 1 / 2（公式未知；workspace 声明后） | `gravity.derived-metrics.v1` 只变换调用方提供的已有结果，不独立取得上游数据；业务公式、总体、单位和声明集合权威性由调用方负责。 |
| 评估一组人群规则命中的人数与占比 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 一次取得构造分析所需的事件、属性、指标和模板上下文 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（实测） | - |
| 一次查看 App 的容量、角色、权限菜单和实时事件治理快照 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 一次查看 App 已登记的归因配置、映射与回溯设置 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 查看单个用户某日的画像、事件时间线和回传记录 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 汇总多个 App 的业务趋势和小时脉搏 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 查看公司资源用量趋势 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（实测） | - |
| 查看自定义人群覆盖与状态 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（实测） | - |
| 比较已支持平台的素材表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 读取单日订单目录 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | 当前只返回已登记合同字段；新观察字段登记后按投影总裁决暴露。 |
| 按 TraceID 追踪单日订单拆单结果 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | - |
| 读取单日完整已登记变现明细（D27） | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（控制流） | 当前返回全部已登记合同字段；新观察字段登记后按投影总裁决暴露，字段/筛选/分组意图转 raw operation 并走 live metadata 校验。 |
| 执行 workspace 登记的聚合 SQL 分析产品 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（实测） | - |
| 查看看板详情、成员和筛选收藏 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | - |
| 忠实重放看板图表及页面条件（D22） | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | 能力边界不变：非空页面 `config.filter` 仍 fail-closed；bundle 只证明页面与图表条件分字段发往服务端，异维度组合与同维度冲突仍无权威语义。 |
| 创建并管理可持久化的看板工作区与分析便签 | 已闭环 | 有 / 有 / 有 / 有 | 2（dry-run / 人工确认后同参数 execute） | `space → folder → dashboard` 是上游目录层级，note 是 dashboard `ui_config` 中的嵌入项，不是第四层目录资源。生产闭环完成 create/rename/move/copy/note update+delete/readback/父删除迁移/批量清理；父删除 dry-run 在写前给出精确迁移数与 `dashboards_deleted=0`。所有可删除对象须有 `GSDK-<12 hex>` marker；Plan 只接受显式 `preview/execute` mode，Agent 自然语言永不自动写。share、所有权 transfer、含报表 dashboard、素材/资产均不在闭环证据内。 |
| 按精确引用重放保存分析 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | - |
| 创建、更新、重放并删除可复用保存分析 | 已闭环 | 有 / 有 / 设计不适用 / 有 | mutation 2（dry-run / 显式 execute）；重放 1 | `report_config/update` 以无 `id` 创建、带 `id` 更新、带 `id + is_deleted=true` 删除；事件分析已生产完成 create/list/get/update/readback/replay/delete/消失确认且最终 marker 为 0。2026-08-17 又以精确 GET 的原样保存对象重放 `analysis.event.query`，HTTP 200，`2026-06-01..07` 聚合值 `235176.0` 已随 governed response 落入 `evidence/forensics/20260817_saved_analysis_replay.json`；receipt 保持值无关。离线编译零网络，返回完整 live metadata 依赖；真正执行在 query 前联网复验。五类已证明 strict replay 的 subject 可写；`analysis_cash/order/user` 因本租户无样本且内部 config 异构而保持未开放。三张 mutation 卡只交接同参数 dry-run/execute，自然语言不自动写；share 不在产品内。 |
| 按精确引用重放分析模板 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | 未经证明的 artifact 继续隔离，不因目录可选而放宽回放合同。 |
| 查看分群详情、版本和单日聚合结果 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | - |
| 查看精确分群成员及逐人属性 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（自然语言实测、卡面） | `gravity-insight.segment-members.v1` 全量交付上游授权字段；目标非空实证登记 147 个顶层字段，未登记字段仍 fail-closed。route 忽略 `page/page_size` 并一次返回完整结果；触及 `max_items` 显式 `partial`。`fields` 是固定 profile + live `analysis.user_property.list` 动态属性的本地选列输入；未知引用仍按 call-bound 显式声明 3 次，不扩大无 revision/ETag 的在线两次解析模式。 |
| 从分析结果或规则创建并管理可复用分群 | 已闭环 | 有 / 有 / 设计不适用 / 有 | 2（dry-run / 显式 execute） | 独立任务产出上游分群对象，不与“查看已有分群详情/成员”合并计数。`from_analysis`、`from_rule`、`by_manual`、`save` 已有生产创建/更新/刷新/删除与读回证据；历史版本和临时分群两个 create 变体未生产验证，不作为本行闭环证据。Plan v1 不承诺不可重放写、人工确认、preimage 或写后读回，Agent 只交接两步命令。 |
| 用显式物理维度、指标和筛选读取多维报表 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（物理字段未知、在线解析） | 闭合 schema + live metadata 提供物理指标/维度候选；日期和 filter value 仍须由调用方精确提供。 |
| 定义、更新并在多维查询中使用可复用自定义指标 | 已闭环 | 有 / 有 / 有 / 有 | mutation 2（preview / execute）；查询 1 | 当前 turbo `edit` 是 create/update upsert，字符串 ID 省略为 create、带 ID 为 update；删除使用当前 turbo delete。生产闭环以 `ap_cost` 公式创建 marker 指标，更新名称/展示格式后由既有旧前缀 mine/shared metadata 目录验证，再发真实 Multidim 查询取得 40 个非空日行，最后删除并连续两次确认当前目录为空。四张产品卡分别表达 list/create/update/delete；自然语言不自动写，Plan 只接受显式 preview/execute。permission edit 会覆盖角色可见指标，未实现。 |
| 创建并维护可复用的事件/属性元数据模板 | 已闭环 | 有 / 有 / 有 / 有 | mutation 2（preview / execute） | 生产创建 marker 模板并把源属性读回为独立成员 ID，随后按成员 preimage 移除并读回空集合，再软删 master 并确认 ID 消失；最终无残留。create/append 以 App 目录 ID 输入、按稳定名称映射成员读回，remove 明确使用模板成员 ID。既有模板变更须通过 `marker OR upstream owner`；四张 Agent 卡均不允许自然语言自动执行。分组 UI、无 owner 证据的属性批删和不可清理的 XLSX 导入不在产品内。 |
| 按平台和物理指标读取推广表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（指标未知、在线解析） | 平台须已知；第二次执行重新按平台复验物理指标。 |
| 查看 B 站账户/产品投放表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（日期未知） | 独立于 Promotion Performance；只声明请求日期范围，不伪称结果行有日期或 App/物理指标绑定。`advertiser_name` 等已观察字段受投影总裁决约束：登记后全部暴露，不再按本地隐私策略省略。 |
| 读取巨量广告主消耗、余额、预算模式和状态 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | 独立 `advertiser_profile` 完整读取，不并入明确排除广告主目录的跨平台推广表现；本轮 `page_size=1` 的页 1/页 2 各 1 次，均 HTTP 200 / `success`，页码回显 1/2 且登记投影行不同，页码分页已验证。 |
| 读取巨量普通/标准标题包的标题数、计划数与成本表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | 独立 `gravity-insight.title-package.v1`，`package_kind=regular\|standard` 两个显式变体不合并、不拍平；`title_list` 等已观察字段按投影总裁决登记并暴露，未登记新增字段继续按合同漂移 fail-closed。它是 D32 之下一个具体产品，不代表 D32 本身有进展。 |
| 离线查找可用于分析的事件、属性、指标和模板名称 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（冷目录在线刷新） | refresh 不完整时不发布 staging catalog；成功查询仍是带同步时刻的 observed snapshot。 |
| 查询已同步的数据表版本与变更观察 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（冷目录在线刷新） | 只证明带同步时刻的沿革观察，不回答 F41 的当前 schema。 |
| 创建、轮询并下载素材分析报表 | 已闭环 | 有 / 有 / 设计不适用 / 有 | 1 / 2（中英首问） | 文件 effect 由一次 `export run` 完成 create→poll→download、校验与原子提交；卡声明发现后 1 次调用。Plan v1 不承诺文件副作用、超时恢复或部分下载语义。 |
| 跨平台读取任意推广层级的兼容快照 | 不计独立动线（legacy 兼容面） | 有 / 有 / 设计不暴露 / 设计不暴露 | 1 / 不提供 | permissive snapshot 绕过正式产品的 workspace App、统一日期窗、平台/指标 allowlist 与结果绑定；保留专家兼容入口，Agent 主路径指向 `promotion performance`。 |
| 读取任意稳定元数据 operation 的统一快照 | 不计独立动线（SDK 便利面） | 设计不暴露 / 有 / 设计不暴露 / 设计不暴露 | 1 / 不提供 | inventory 驱动且会跳过缺必填 input 的 operation，不构成稳定调用方任务；在线固定上下文走 `analysis context`，离线发现走 `metadata search` / `metadata vocabulary`。 |
| 查询分析默认值字典 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（App 已知；App 未知 3） | 2026-08-16 按 catalog 枚举：第 1 个 App HTTP 200 空，第 2 个 App HTTP 200 非空后立即停止。`gravity-insight.analysis-default-dictionary.v1` 登记并暴露已观察的 `api`、`cocoscreator` string array；新增字典键继续 fail-closed。Core/CLI/SDK/Plan/Agent 共用产品合同，卡与 Plan 节点声明 `gravity.agent-call-bound.v1`。 |
| 查询实时事件目录 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。2026-08-16 已按 catalog 枚举 **7 个可绑定 App**：7 次最小请求均 HTTP 200 明确空，0 个失败或未试 App；因此这是当前租户事实，不再归因于单 App 探测。item schema 与服务端分页仍未证实。`client_id/request_id/request_ip/raw_properties` 已由投影总裁决批准，取得 shape 后应登记并暴露。 |
| 查询分析空间或报表设置 | 不计独立动线（既有稳定读取面重复） | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | `analysis.setting.query` 仍由完整控制流证明为 mutation。冻结 inventory 的 987 个唯一 `(method,path)` 经 375/375 hash-matched bundle 重放完全一致；378 条语义超集展开为 52 条 owner 命名空间全集后，确认四条真读：`analysis.dashboard.tree/detail` 装载空间树和看板设置，`analysis.report_config.list/get` 装载保存分析配置。四条均已有 stable 合同、Core/CLI/SDK/Plan/Agent 卡和 `gravity.agent-call-bound.v1`；一条最小 `report_config.list` probe 为 HTTP 200 非空，未重试、翻页或扩窗。本行与“查看看板详情、成员和筛选收藏”及“按精确引用重放保存分析”重复，故不新建产品。若未来提出更宽的通用设置面，`config/ui_config/remark` 与人员字段须先取得合同证据并登记后全部暴露；未登记时仅按合同漂移 fail-closed，不等待隐私批准。 |
| 查找自有、共享和 MasterKey 报表并读取其定义 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问、卡面） | 写入 1 条 marker-owned 自有报表后，`report.report.list` 与父值绑定的 `report.report.detail` 均取得非空 schema；旧 shared/MasterKey 账号级空合同仍保留，不把空样本伪作 item schema。`gravity-insight.report-directory.v1` 完整分页后有界并发读 detail；列表/detail 观察字段全部登记暴露，新增字段继续 drift fail-closed。 |
| 查看报表订阅清单 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问、卡面） | 创建 1 条 disabled、`send_way=[]`、无收件人的 marker-owned 订阅后，`report.subscribe.list` 取得非空 schema；`gravity-insight.report-subscriptions.v1` 完整分页返回全部登记字段。未调用 `subscribe/test`，清理后列表确认空。 |
| 创建或删除可复用报表 | 已闭环 | 有 / 有 / 设计不适用 / 有 | 2（dry-run / 显式 execute） | 独立任务终点是可复用上游报表对象，不与目录读取合并计数。`report.report.update` 已生产验证 create/delete；marker 在 `remark` 经 list/detail round-trip，删除前 detail 闸门、删除后完整列表确认。Plan v1 不承诺人工确认、不可重放写、preimage 或写后读回，Agent 只交接两步命令且自然语言不自动执行。 |
| 创建或删除报表订阅 | 已闭环 | 有 / 有 / 设计不适用 / 有 | 2（dry-run / 显式 execute） | 独立任务终点是可管理的上游订阅对象；生产验证 v3 报表父项 create/delete 与 subscription create/delete。订阅 marker 在 `name/wildcard_name` round-trip；创建强制 disabled 与空收件人，绝不调用 test route。v3 父项是本任务脚手架，不另拆动线；Plan 窄例外与报表写相同并逐条登记。 |
| 查找可用的媒体报表 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `MEDIA_REPORT_ITEM_SCHEMA_MISSING`。2026-08-16 使用最短当天窗口、无平台筛选、`page_size=1`，按 catalog 枚举 **7 个可绑定 App**；7 次请求均 HTTP 200 明确空，0 个失败或未试 App。当前租户确实无可用媒体报表；既有分页证据保留，item schema 未成立。 |
| 查找当前账号可读的 App 项目 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | 设置 → 应用管理的真实账号级列表为既有 stable `app.list`：`GET /turbo_engine/api/v1/user/open_app/list/`，不是 `app.project.list` 的 `POST /turbo_engine/api/v1/user/project/list/`。自然页面首屏 HTTP 200 非空 7 行；`cid/create_time/download_url/event_version/icon_url/id/industry_id/is_enabled/is_iaa/modify_time/name/os/package_name/remark/sub_package_list/wechat_app_id/wechat_origin_id` 与 `page_info.page/page_size/total_number/total_page` 均已在 v4 投影登记暴露。CLI/SDK/Plan 复用 raw operation，Agent 中英首问均交付 `app.list` 卡；英文冻结问法为 “List the app projects that the current account is allowed to read.”。 |
| 查看 App 的 OneLink 与公开信息绑定 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `APP_ONELINK_PUBLIC_BINDING_SAMPLE_MISSING`。**推进但未闭环**：OneLink 仍由既有 GET 父链证明当前账号明确空。appManage 进一步证明 app-info 的 `url` 来自调用方输入的 Google Play/App Store 下载链接，并非 OneLink 项；公开 URL 的 2 次最小 GET 均 HTTP 200，已恢复 `app_id/error/icon_url/image_data/name/package_name/platform` schema，但结果为 error-shaped `inconclusive`，未获成功数据。下一步由调用方提供一条已知能被 Gravity 抓取的公开商店 URL，只做 1 次读取；非空后按投影总裁决登记并暴露全部字段，不能用当前 OneLink 空样本补绑定。 |
| 按平台、广告位和日期汇总变现结果（D28） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `MONETIZATION_AGGREGATE_CONTRACT_MISSING`。本轮三选一为**请求参数/路由不对**：当前 hash-matched `NewReportCenter` 从 `/turbo_engine/api/v3/confmetric/metric/list/` 与同命名空间 permission route 取 `monetization_report` 配置，现有 stable metric operation 却仍发旧 `/report/api/v3/...`。旧 route 7 次均 HTTP 200；错误 operator 与当前正确 filter 各被语义拒绝，宽目录自动 5 页共 200/1124 行也无目标 topic。该判据只证明 SDK 请求错误，不能证明“没数据”或“权限没生效”；主 route 未再发送，非空 item/total shape 与指标/维度值域仍缺，投机字段不登记。 |
| 查询归因表现聚合（D35） | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（实测；未知 App 离线默认 3） | hash-matched 前端控制流证明 14 恒发字段、2 条条件省略和四个固定指标画像。生产账本为 1 次 App catalog + 2 次单日目标 POST：首 App `code=0/msg=成功/extra.error=无数据` 明确空，第二 App 非空后立即停止；无重试、翻页或扩窗。stable `attribution.attribution.query` 暴露全部观察字段；Core/CLI/SDK/Plan/Agent 共用 `gravity-insight.attribution-performance.v1` 和 `gravity.agent-call-bound.v1`。旧 evidence 未保存 error 正文，不能声称服务端曾拒绝某字段；当前合同将“无数据”规范化为空，其他未知 error fail-closed。 |
| 下钻单用户归因明细（F40） | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（未知 App 3；未知设备父行 3；二者均未知 4） | 第 6 个 catalog App 的 `app.testing_tool.list` 首次非空后停止；完整目录行与 `page_info` 字段/type 已登记。以内存 `data.list[].id` 构造整数 `device_id`，详情仅发 1 次且成功；`device_white` 完整字段/type 已登记，`attribution_list/postback_list/pay_list` 明确为空。三种 item schema 仍是未观察事实，未来非空即 fail-closed，不作为本次明确空闭环的猜测字段。Core/CLI/SDK/Plan/Agent 共用 `gravity-insight.attribution-user-detail.v1` 与 `gravity.agent-call-bound.v1`。 |
| 按表名或 App 查询数据表当前 schema、字段和版本（F41） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问仍返回 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`。2026-08-16 获准自建唯一 marker 表后，create/list/detail 实证恢复表 ID、两列、三行与 `using_version_id=1`，随后 delete/list/version-id-set 证明零残留；因此旧“无父对象无法取 shape”已解除。但 `conf_related_prop/override` 对未绑定自建表的 `prop_list=[]` 明确返回 `code=1004 / prop_list is empty`，前端也不能移除最后一条关联；按停止条件未绑定、未建新版本、未做业务属性分析。F41 的读产品和维度表写产品均未实现，详情见[维度表 wire 与分析价值探测](research/dimension-table-wire-probe.md)。 |
| 下钻非 Bytedance 平台的计划、组和创意表现（D33/D34） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `NON_BYTEDANCE_HIERARCHY_PARENT_MISSING`。Bilibili advertiser 与 Huya account 未产出父候选；后续 ID 链、report 父字段、分页和非空 schema 未成立。 |
| 深查各平台专属素材与创意（D32） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING`。除 Bytedance 外普遍没有最小非空响应合同；common 素材目录不能证明平台专属字段。Bytedance 标题包已单列为独立动线闭环，**但那是 D32 之下的一个具体产品，不是这条动线的进展**；本条仍是数据证据阻塞。 |
| 导出事件、分群、用户、付费或变现分析结果 | 部分闭环 | 部分 / 部分 / 设计不适用 / 有（五个具体卡；宽问法目标 gap） | 1 / 2（五个可调子路径中英首问） | `user_event`、`segment.result`、`segment_user_detail`、`user_detail`、`pay_event` 均已有各自的非空 create→poll→download→validate XLSX shape，并经 CLI/SDK/Agent 可调用。`origin_event` 因固定 App/日期内唯一自然事件估算为 0 而未 create。`monetization_detail` 的 READY 文件已证明是安全 ZIP：13,588,076 bytes、9 entries、总展开 166,683,292 bytes、最高压缩比 12.269763，route-scoped 192 MiB policy 可通过；shape 为 `Sheet1`、1,000,000 行、`事件发生时间/客户ID` 两列。但同 scope 受管列表 `total_items=1,212,315`，任务和文件均无截断标志，且上游 empty shape 未验证，因此保持不可调用 gap。`completion_status` 将 `empty/partial/truncated/expired/complete/gap` 机械分开；只有原子提交且完整的非空文件是 `complete`。`stream_event` 仍为 `not_applicable`。聚合动线因两个 gap 保持部分闭环，冻结评测宽问法继续期待 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`。 |
| 按精确平台素材引用预览或下载图片/视频（Issue 19） | 已闭环 | 有 / 有 / 设计不适用 / 有 | 1 / 2（中英首问） | `material.asset.fetch` 不接收 URL：一次调用先重读 `local` 或 `bytedance_project` stable source，再按精确引用从唯一行取 `file_url`/`thumbnail_url` 并完整原子下载。host/path 不枚举、不限制，跨 host redirect 跟随；本地与 Bytedance 的 JPEG/MP4 证据独立成立。HTTP terminal 状态统一归 upstream/3，不创造素材失效 taxonomy；完整文件由显式 output/destination 触发。 |

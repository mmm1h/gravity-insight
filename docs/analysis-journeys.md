# 分析动线台账

本页是分析动线完成度的长期事实源。每行回答一个独立分析问题；同一产品的 list/prepare/run、batch、分页和日期模式不拆行，raw operation、维护命令、任务状态路由也不单列。新增独立产品合同或独立结果 envelope 时新增一行，能力、证据或入口变化时原位更新。

闭环判据沿用[路线图](roadmap.md)：已知输入 1 次调用、未知输入 2 次调用，CLI/SDK/Plan/Agent 四面可达，结果为带 `schema_version` 的 envelope，能区分空、部分失败和能力缺口，未登记字段 fail-closed。Agent 一面不再以卡已注册或精确 selector 自证：每行至少一条中文和一条英文分析师问法都须第一次调用命中正确产品；真实歧义的 `MULTIPLE_INTENTS` 必须含正确候选，能力缺失则须返回目标明确且带可执行 next action 的 gap。调用次数是调用方顶层命令/SDK 调用数，不是 composite 内部 HTTP 数；`实测` 指本轮离线发现加 Plan dry-run，`控制流` 指离线发现实测后核对 handoff/Plan 路径，`未验证` 不作达标声明。

下面原为 `1 / 3` 的 9 条动线现可显式使用在线输入解析：第一次
`gravity agent --resolve-inputs ... --output ...`（SDK 为 `resolve_capabilities()`）同时发现能力并交付
完整 live catalog，或完成冷 metadata catalog 的原子刷新；调用方精确选择后第二次执行。选择没有折进
执行，内部 HTTP 数也没有减少。App/平台也未知时不适用该两次路径；默认离线 Agent 的原三次下界保留。
`gravity.agent-call-bound.v1` 只在本次成功交付完整目录的卡与 Plan 节点上把对应 scenario 声明为 2。

合并后重算：**47 条产品动线：已闭环 32 / 部分闭环 0 / 完全缺失 15**。可复算：上一快照
`43 = 19 / 9 / 15`，本轮 9 条部分闭环由上述在线输入解析全部转入已闭环，另新增 4 条产品动线
（标题包、自定义人群、B 站账户表现、巨量广告主 profile）全部闭环，缺失新增 1 条（Issue 19
精确素材预览/下载），得到 `48 = 32 / 0 / 16`；`export.analysis.*` 复核净变化 `0 / 0 / 0`；
2026-08-15 穷尽 route 取证再确认原第 64 行已经完整落在既有 `dashboard_snapshot` /
`saved_analysis` 稳定读取面内，故从产品动线与 completely missing 各减 1，最终得到
`47 = 32 / 0 / 15`。stable operation 仍为 185、其中 176 个 stable。
**部分闭环归零不等于没有欠账**——15 条完全缺失里多数是合同证据阻塞，逐行有记录。
另保留 2 条兼容/维护便利面供边界审计，
但不计产品动线。旧快照 `21/14/6` 没有逐条证据，不能复算；本台账不还原已丢失的原始 41 条定义。
D23/D29/D30 只剩依赖箭头、语义不可验证，故保留在此说明而不强挂到新动线。候选
`app.project_auth.detail`、`app.user_auth.list` 属成员权限管理，按 roadmap 非目标排除，不计动线。

2026-08-15 按新 Agent 判据冻结 47 条动线中英各一问并重验：已闭环 baseline 为
`6 双语达标 / 7 单语达标 / 19 双语不达标`，修复后为 `32 / 0 / 0`，原达标问法回归 0。
15 条完全缺失没有发现可执行结果，但 15/15 均能由中英首问得到各自专属 next-action gap；因此
缺失行只把 Agent 一面改为“有”，不改变整体状态。计数推导为
`47 = 32 / 0 / 15 + 0 / 0 / 0 = 47 = 32 / 0 / 15`。逐题 before/after 与原始候选顺序保存在
`tmp/codex/nl-reachability/`；94 次均为离线调用，生产 HTTP 0 次。

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
逐 HTTP 文件没有公开读取 API，目前只用于知道私有 state root 的事后诊断，不据此新增分析动线。

事件、漏斗、留存、属性四行的“已知 1 次”同时覆盖显式多 App：同一 spec 用
`gravity.analysis-query-batch.v2` 的 `apps` 数组一次执行，逐 App 组件返回且不聚合。scatter 和其余
产品仍按当前单 App/同层 Plan 合同，不据此增加新动线或改变下表计数。

| 动线 | 状态 | 四面可达（CLI / SDK / Plan / Agent 中英首问） | 调用次数（已知 / 未知） | 阻塞 |
| --- | --- | --- | --- | --- |
| 看某事件随时间、分组和条件的变化 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看多步行为的转化漏斗 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看起始行为后的用户留存 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看用户或事件属性的分布与聚合 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 看事件指标之间的散点关系 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
| 用同一分析定义比较两个时期 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | - |
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
| 按精确引用重放保存分析 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | - |
| 按精确引用重放分析模板 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | 未经证明的 artifact 继续隔离，不因目录可选而放宽回放合同。 |
| 查看分群详情、版本和单日聚合结果 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | - |
| 用显式物理维度、指标和筛选读取多维报表 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（物理字段未知、在线解析） | 闭合 schema + live metadata 提供物理指标/维度候选；日期和 filter value 仍须由调用方精确提供。 |
| 按平台和物理指标读取推广表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（指标未知、在线解析） | 平台须已知；第二次执行重新按平台复验物理指标。 |
| 查看 B 站账户/产品投放表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（日期未知） | 独立于 Promotion Performance；只声明请求日期范围，不伪称结果行有日期或 App/物理指标绑定。`advertiser_name` 等已观察字段受投影总裁决约束：登记后全部暴露，不再按本地隐私策略省略。 |
| 读取巨量广告主消耗、余额、预算模式和状态 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | 独立 `advertiser_profile` 完整读取，不并入明确排除广告主目录的跨平台推广表现；本轮 `page_size=1` 的页 1/页 2 各 1 次，均 HTTP 200 / `success`，页码回显 1/2 且登记投影行不同，页码分页已验证。 |
| 读取巨量普通/标准标题包的标题数、计划数与成本表现 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（中英首问） | 独立 `gravity-insight.title-package.v1`，`package_kind=regular\|standard` 两个显式变体不合并、不拍平；`title_list` 等已观察字段按投影总裁决登记并暴露，未登记新增字段继续按合同漂移 fail-closed。它是 D32 之下一个具体产品，不代表 D32 本身有进展。 |
| 离线查找可用于分析的事件、属性、指标和模板名称 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（冷目录在线刷新） | refresh 不完整时不发布 staging catalog；成功查询仍是带同步时刻的 observed snapshot。 |
| 查询已同步的数据表版本与变更观察 | 已闭环 | 有 / 有 / 有 / 有 | 1 / 2（冷目录在线刷新） | 只证明带同步时刻的沿革观察，不回答 F41 的当前 schema。 |
| 创建、轮询并下载素材分析报表 | 已闭环 | 有 / 有 / 设计不适用 / 有 | 1 / 2（中英首问） | 文件 effect 由一次 `export run` 完成 create→poll→download、校验与原子提交；卡声明发现后 1 次调用。Plan v1 不承诺文件副作用、超时恢复或部分下载语义。 |
| 跨平台读取任意推广层级的兼容快照 | 不计独立动线（legacy 兼容面） | 有 / 有 / 设计不暴露 / 设计不暴露 | 1 / 不提供 | permissive snapshot 绕过正式产品的 workspace App、统一日期窗、平台/指标 allowlist 与结果绑定；保留专家兼容入口，Agent 主路径指向 `promotion performance`。 |
| 读取任意稳定元数据 operation 的统一快照 | 不计独立动线（SDK 便利面） | 设计不暴露 / 有 / 设计不暴露 / 设计不暴露 | 1 / 不提供 | inventory 驱动且会跳过缺必填 input 的 operation，不构成稳定调用方任务；在线固定上下文走 `analysis context`，离线发现走 `metadata search` / `metadata vocabulary`。 |
| 查询分析默认值字典 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING`。请求形状与无分页已证明；既有非空样本只证明已观察的 string-array 键，本轮同形状响应为空，动态 key 的完整 shape/type 仍不能确认。取得非空 shape 后应按投影总裁决全部登记并暴露，不再等待隐私批准。 |
| 查询实时事件目录 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。完整请求 builder 已证明且最小请求语义成功为空；item schema 与服务端分页仍未证实。`client_id/request_id/request_ip/raw_properties` 已由投影总裁决批准，取得 shape 后应登记并暴露，不再构成隐私阻塞。 |
| 查询分析空间或报表设置 | 不计独立动线（既有稳定读取面重复） | 有 / 有 / 有 / 有 | 1 / 2（引用未知、在线解析） | `analysis.setting.query` 仍由完整控制流证明为 mutation。冻结 inventory 的 987 个唯一 `(method,path)` 经 375/375 hash-matched bundle 重放完全一致；378 条语义超集展开为 52 条 owner 命名空间全集后，确认四条真读：`analysis.dashboard.tree/detail` 装载空间树和看板设置，`analysis.report_config.list/get` 装载保存分析配置。四条均已有 stable 合同、Core/CLI/SDK/Plan/Agent 卡和 `gravity.agent-call-bound.v1`；一条最小 `report_config.list` probe 为 HTTP 200 非空，未重试、翻页或扩窗。本行与“查看看板详情、成员和筛选收藏”及“按精确引用重放保存分析”重复，故不新建产品。若未来提出更宽的通用设置面，`config/ui_config/remark` 与人员字段须先取得合同证据并登记后全部暴露；未登记时仅按合同漂移 fail-closed，不等待隐私批准。 |
| 查找自有、共享和 MasterKey 报表并读取其定义 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `REPORT_DIRECTORY_ITEM_SCHEMA_MISSING`。**非空样本阻塞（读合同已解除）**：hash-matched bundle 已分别证明 `report.masterkey_report_group.list`、`report.report.list`、`report.shared_to_me.list` 的装载、分页和 `list` 消费，三条精确 read confirmation 已登记。本轮各 1 次最小第一页请求均 HTTP 200、明确空；既有分页证据保留，但 item schema 未成立，`report.report.detail` 仍无父项。下一步由有报表数据的租户提供 1 个非空列表项，再以内存父值做最小 detail。 |
| 查看报表订阅清单 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `REPORT_SUBSCRIPTION_ITEM_SCHEMA_MISSING`。**明确空 / item schema 阻塞**：静态 read confirmation 已由 `reportSubscribe` 的装载、分页、响应消费及独立 mutation 路由证明；本轮唯一一次 `page=1/page_size=1` 请求 HTTP 200、`data.list=[]`，只证实 envelope 与 `page_info`，未取得 item schema，也未额外翻页。下一步在有订阅项的租户复用同形状取得 1 个非空 item，再单独判断分页和投影。 |
| 查找可用的媒体报表 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `MEDIA_REPORT_ITEM_SCHEMA_MISSING`。**明确空 / item schema 阻塞**：`GeneralImportAd` bundle 已证明列表装载、分页和响应消费；`app_id` 来自 `AppSelect`、`ad_platform` 来自有限平台选项，空选择按前端语义省略，精确 read confirmation 已登记。本轮当天、无筛选、`page_size=1` 的唯一请求 HTTP 200、明确空；既有分页证据保留，item schema 未成立。下一步只在有媒体报表的租户复用同形状，不猜 App 或平台值。 |
| 查找当前账号可读的 App 项目 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `APP_PROJECT_ITEM_SCHEMA_MISSING`。**推进但未闭环**：hash-matched appManage 控制流证明 `app.project.list` 只装载项目表和分页，create/delete 走独立 mutation；确认记录已追加。最小第一页实际 1 次 POST，HTTP 200 明确空，新 receipt 为 `method_verified=true`、`pagination_verified=true`，因此可确定当前账号没有可读项目；item schema、成功非空与前三个产品面仍缺。下一步由有可读项目的租户做 1 次 `page=1/page_size=1` probe，再登记全部观察字段。 |
| 查看 App 的 OneLink 与公开信息绑定 | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `APP_ONELINK_PUBLIC_BINDING_SAMPLE_MISSING`。**推进但未闭环**：OneLink 仍由既有 GET 父链证明当前账号明确空。appManage 进一步证明 app-info 的 `url` 来自调用方输入的 Google Play/App Store 下载链接，并非 OneLink 项；公开 URL 的 2 次最小 GET 均 HTTP 200，已恢复 `app_id/error/icon_url/image_data/name/package_name/platform` schema，但结果为 error-shaped `inconclusive`，未获成功数据。下一步由调用方提供一条已知能被 Gravity 抓取的公开商店 URL，只做 1 次读取；非空后按投影总裁决登记并暴露全部字段，不能用当前 OneLink 空样本补绑定。 |
| 按平台、广告位和日期汇总变现结果（D28） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `MONETIZATION_AGGREGATE_CONTRACT_MISSING`。**仍然阻塞**：csj/tobid bundle 证明 `app.monetization_app.list` 是账户行下的平台应用关联目录读取，不含日期、广告位或结果指标，不能实现 D28。下一步取证真正的 `/report/api/v3/monetization_report/custom_get/` 及 `calc_total/` 请求/响应合同；D27 的字段登记不替代 D28 合同，取得 D28 shape 后全部登记暴露。 |
| 查询归因表现聚合（D35） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `ATTRIBUTION_AGGREGATE_CONTRACT_MISSING`。前端 body 已恢复，但最小请求仍 semantic error；缺服务端必填、值域和成功/明确空证据。 |
| 下钻单用户归因明细（F40） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `USER_ATTRIBUTION_DETAIL_DEPENDENCY_MISSING`。D35 未成立；还缺调用方提供的授权标识来源、请求绑定、分页和响应合同。标识字段投影已全面放开，不再是阻塞。 |
| 按表名或 App 查询数据表当前 schema、字段和版本（F41） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`。list 为空且无可信表名/App 来源；detail/version 父链、`table_id` 类型和“当前版本”语义未证实。 |
| 下钻非 Bytedance 平台的计划、组和创意表现（D33/D34） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `NON_BYTEDANCE_HIERARCHY_PARENT_MISSING`。Bilibili advertiser 与 Huya account 未产出父候选；后续 ID 链、report 父字段、分页和非空 schema 未成立。 |
| 深查各平台专属素材与创意（D32） | 完全缺失 | 无 / 无 / 无 / 有（目标 gap） | 未验证 | Agent 首问返回 `PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING`。除 Bytedance 外普遍没有最小非空响应合同；common 素材目录不能证明平台专属字段。Bytedance 标题包已单列为独立动线闭环，**但那是 D32 之下的一个具体产品，不是这条动线的进展**；本条仍是数据证据阻塞。 |
| 导出事件、分群、用户、付费或变现分析结果 | 完全缺失 | 无 / 无 / 设计不适用 / 有（目标 gap） | 未验证 | Agent 首问返回 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`。9 条仍不可执行：`segment.result.start`、`user_event.start` 的投影阻塞已解除，但逻辑列类型未证实；`origin_event.evaluate` 受未证实的配对 create/file 父工作流阻塞；其余 6 条缺成功请求绑定或完整文件 schema。 |
| 按精确平台素材引用预览或下载图片/视频（Issue 19） | 完全缺失 | 无 / 无 / 设计不适用 / 有（目标 gap） | 未验证 | Agent 首问返回 `PLATFORM_ASSET_BINARY_CONTRACT_MISSING`。API 列表已证明存在 `file_url` / `thumbnail_url` 且前端直接交给媒体元素；投影总裁决要求登记暴露这些字段，但现有证据仍不能证明二进制 host/path、重定向集合及历史失效语义，故不能配置下载 allowlist 或发起最小二进制 probe。文件 effect 与 Plan v1 的无副作用数据节点不兼容。 |

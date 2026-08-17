# 候选能力证据矩阵

本矩阵记录 17 项候选能力在 2026-08-12 受控只读探测后的真实状态，并原位追加 2026-08-14 至
2026-08-16 的后续取证结论，供开发决策使用。仓库当前基线为
[233 个 operation、其中 224 个 stable operation](capability-coverage.md)：187 条 stable read 加
37 条逐项治理的 mutation（7 条 Segment、5 条报表/订阅、18 条 Kanban、2 条自定义指标、
4 条事件/属性模板和 1 条保存分析）；写 operation 不是本矩阵的 read candidate，
但本页追加其解锁读合同的生产证据。

`analysis.default_val.list`、D35、F40、`report.report.list/detail`、`report.subscribe.list`、
`app.app_info.get` 与 `report.get.query` 已晋升，其余候选
保持原位；`analysis.setting.query`
保留在 draft 台账但 `effect=mutation`，其他未晋升候选仍是 read draft，promotion gate 均未满足。
表中的“下一步最小证据”表示继续判断所需的最小输入，不代表晋升计划或交付承诺。候选在线验证
仍须遵循[探测规范](maintainers/probing.md)，保持只读、限流、值不落盘和 fail-closed；已登记 Segment
mutation 只能走自身的 dry-run→显式 execute→读回/清理流程，不能借 draft prober 的读确认旁路执行。

Kanban 追加取证同样只走产品级两步治理。两条显式 `*.share` 与实际命中
`space/share/delete/` 的哈希 operation 继续保持 blocked reservation；它们不是本轮 mutation 合同。

## 逐项状态

| Operation | Status | 本轮请求、样本、分页与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `analysis.default_val.list` | **`stable`（已晋升）** | 2026-08-16 按 catalog 探测：`catalog#1` HTTP 200 空，`catalog#2` HTTP 200 非空后立即停止。当前样本观察 `data.cocoscreator[]: string`，并与既有 shape-only 样本的 `data.api[]: string` 合并；body 仍为 caller-bound `app_id` + 固定 `$lib_version`，分页 `none`。 | 无开放 blocker；闭合键集合为 `api/cocoscreator` | 保持两键全量暴露；出现第三个 SDK-family key 时按 additive drift fail-closed，取得 shape evidence 后再显式升级合同。 |
| `analysis.setting.query` | `draft`（mutation 负向证明；查询动线已由既有产品覆盖） | 对本 mutation 仍为 0 次请求；完整 Dashboard builder 证明该 POST 提交 `config/name/remark`，随后修改 dashboard layout 并提示修改成功。2026-08-15 对 375/375 hash-matched bundle 的 987 条唯一 route 穷尽复核，另确认 `analysis.dashboard.tree/detail` 与 `analysis.report_config.list/get` 四条既有 stable GET 是装载设置的真读；仅对 stable `report_config.list` 做 1 次最小第一页 probe，HTTP 200 非空，无重试或翻页。 | `mutation_route_not_read`、`unregistered_fields_fail_closed`；不再有独立产品缺口 | 本 draft 永不晋升为 read。调用方分别使用既有 `dashboard_snapshot` 与 `saved_analysis`；若提出超出二者的新设置问题，先取得自由文本 config 与人员字段的合同证据，登记后全部暴露；未登记时只按合同漂移 fail-closed，不等待隐私裁决。 |
| `analysis.realtime_event.list` | `draft`（当前账号在已试窗下明确空） | 2026-08-16 对 catalog 的 7/7 App 各发 1 次最小请求，均 HTTP 200 空，但未记录 `request_time`/`filters` 实际值且未扩窗。2026-08-17 用 `request_time=["2026-07-17 00:00:00","2026-08-16 23:59:59"]`、`filters={}`、`page=1`、`page_size=1` 再枚举 7/7，均 HTTP 200 / `code=0` / `data.list=[]`；随后把右端扩到当天 `2026-08-17 23:59:59` 再枚举 7/7，结果相同。未试非空筛选。 | `empty_sample`、`pagination_unverified`、`response_item_schema_unverified` | 由另一个有实时事件数据的租户取得 1 个非空 item；当前账号不必再以同一空筛选重复枚举已试窗。 |
| `analysis.setting.query` | `draft`（mutation 负向证明；查询动线已由既有产品覆盖） | 对本 mutation 仍为 0 次请求；完整 Dashboard builder 证明该 POST 提交 `config/name/remark`，随后修改 dashboard layout 并提示修改成功。2026-08-15 对 375/375 hash-matched bundle 的 987 条唯一 route 穷尽复核，另确认 `analysis.dashboard.tree/detail` 与 `analysis.report_config.list/get` 四条既有 stable GET 是装载设置的真读；仅对 stable `report_config.list` 做 1 次最小第一页 probe，HTTP 200 非空，无重试或翻页。 | `mutation_route_not_read`、`unregistered_fields_fail_closed`；不再有独立产品缺口 | 本 draft 永不晋升为 read。调用方分别使用既有 `dashboard_snapshot` 与 `saved_analysis`；若提出超出二者的新设置问题，先取得自由文本 config 与人员字段的合同证据，登记后全部暴露；未登记时只按合同漂移 fail-closed，不等待隐私裁决。 |
| `report.masterkey_report_group.list` | `draft`（账号级明确空） | 2026-08-16 最小第一页 HTTP 200 空。固定 path/body 无 App 输入，认证上下文只含账号/公司，因此 App 枚举不适用；既有 read confirmation 与分页证据保留。 | `empty_sample`、`successful_probe` | 由有 MasterKey 报表的账号取得 1 个非空 item；当前账号不重复请求。 |
| `report.report.list` | **`stable v1`（已晋升）** | 先 dry-run，再由 `report.report.update` 创建唯一 marker-owned 测试报表；列表非空读回并登记 14 个观察字段。请求仍为账号级 `{page,page_size,filters}`，完整分页合同沿用 hash-matched bundle。2026-08-17 双账号完整响应对照：高低权限均为 `code=0 / list=[] / page_info.total_number=0`，无 extra/scope 回显，权限型空与真空不可区分。 | 无开放 promotion blocker。 | 由 `report_directory` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。空结果须对照 `gravity apps permission-profile`，不得当成租户没数据。 |
| `report.report.detail` | **`stable v1`（已晋升）** | 使用同次列表内存父 ID 发 1 次 GET detail；14 个观察字段全部登记，`remark` 的 marker 与列表原样 round-trip。 | 无开放 promotion blocker。 | 只接受 `report.report.list` 返回的精确 ID；目录产品有界并发 fan-out。 |
| `report.shared_to_me.list` | `draft`（账号级明确空） | 2026-08-16 最小第一页 HTTP 200 空。固定 path/body 无 App 输入，认证上下文只含账号/公司；既有 read confirmation 保留。 | `empty_sample`、`response_schema_unverified` | 由有共享项的账号取得 1 个非空 item。 |
| `report.subscribe.list` | **`stable v1`（已晋升）** | 先创建 marker-owned v3 父报表，再创建 disabled、`send_way=[]`、无收件人的订阅；列表非空读回并登记 23 个观察字段。请求仍为账号级 `{page,page_size,filters}`；删除后列表确认空。2026-08-17 双账号完整响应对照：高低权限均为 `code=0 / list=[] / page_info.total_number=0`，无 extra/scope 回显，权限型空与真空不可区分。 | 无开放 promotion blocker；`subscribe/test` 明确未调用。 | 由 `report_subscriptions` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。空结果须对照 `gravity apps permission-profile`，不得当成租户没数据。 |
| `report.masterkey_report_group.list` | `draft`（当前账号在已记录窗下明确空） | 2026-08-16 最小第一页 HTTP 200 空。2026-08-17 用合同 `date_list=["2026-07-17","2026-08-16"]`、`filtering={}`、`filters=[]`、`order_by=[]`、`query_fields=[]`、`real_data=1`、`page=1`、`page_size=1` 再发 1 次，HTTP 200 / `code=0` / `msg=成功` / `data.list=[]` / `page_info.total_number=0` / `total_page=0`，无 `extra.error`。无 App 输入，枚举不适用；既有 read confirmation 与分页证据保留。 | `empty_sample`、`successful_probe` | 由有 MasterKey 报表的账号取得 1 个非空 item；当前账号不必再以同一空筛选重复该窗。 |
| `report.report.list` | **`stable v1`（已晋升）** | 先 dry-run，再由 `report.report.update` 创建唯一 marker-owned 测试报表；列表非空读回并登记 14 个观察字段。请求仍为账号级 `{page,page_size,filters}`，完整分页合同沿用 hash-matched bundle。 | 无开放 promotion blocker。 | 由 `report_directory` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。 |
| `report.report.detail` | **`stable v1`（已晋升）** | 使用同次列表内存父 ID 发 1 次 GET detail；14 个观察字段全部登记，`remark` 的 marker 与列表原样 round-trip。 | 无开放 promotion blocker。 | 只接受 `report.report.list` 返回的精确 ID；目录产品有界并发 fan-out。 |
| `report.shared_to_me.list` | `draft`（账号级明确空） | 2026-08-16 最小第一页 HTTP 200 空。合同只有 `filters/page/page_size`，无时间窗、无 App 输入，扩窗/枚举不适用，2026-08-17 未重打。既有 read confirmation 保留。 | `empty_sample`、`response_schema_unverified` | 由有共享项的账号取得 1 个非空 item；当前账号不必为扩窗再打一次。 |
| `report.subscribe.list` | **`stable v1`（已晋升）** | 先创建 marker-owned v3 父报表，再创建 disabled、`send_way=[]`、无收件人的订阅；列表非空读回并登记 23 个观察字段。请求仍为账号级 `{page,page_size,filters}`；删除后列表确认空。 | 无开放 promotion blocker；`subscribe/test` 明确未调用。 | 由 `report_subscriptions` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。 |
| `report.media_report.list` | `draft`（当前账号在已试窗下明确空） | 2026-08-16 用当天窗口、无平台筛选、`page_size=1` 对 catalog 的 7/7 App 各发 1 次，均 HTTP 200 空。2026-08-17 用 `2026-07-17..2026-08-16`、字符串 `app_id`、无 `ad_platform`、`page_size=1` 再枚举 7/7，另省略 `app_id` 1 次，均 HTTP 200 / `code=0` / `data.list=[]`；再把右端扩到 `2026-08-17` 并省略 App 1 次，结果相同。未枚举具体平台值。 | `empty_sample`、`response_schema_unverified` | 由另一个有媒体报表的租户复用同形状取得 1 个非空 item；当前账号不必再以无平台筛选重复枚举已试窗。 |
| `app.project.list` | `draft`（账号级明确空） | 2026-08-16 唯一一次最小第一页 POST 为 HTTP 200 空。合同只有 `filters/page/page_size`，无时间窗、无 App 输入，扩窗/枚举不适用，2026-08-17 未重打。设置 → 应用管理的真实列表是 stable `app.list`，不是本 draft。 | `empty_sample`、`response_schema_unverified` | 由具备可读项目的账号取得 1 个非空 item；当前账号不必为扩窗再打一次。 |
| `app.project_auth.detail` | `draft` | 1 次稳定父请求、0 次目标请求；父资源返回空候选，子请求未发送；无目标样本，分页未验证；父绑定未解析。 | `parent_resource_required`、`probe_inconclusive`、`response_schema_unverified` | 由 `analysis.account_user.list` 提供 1 个可读候选，仅以内存传给 1 次目标请求；没有父候选时继续跳过。 |
| `app.onelink.list` | `draft` | 共 5 次请求，其中父资源 2 次、目标 3 次；父绑定已解析且值仅在内存使用；目标 HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证。 | `empty_sample`、`response_schema_unverified` | 复用已证明的稳定父绑定取得 1 个非空目标样本，再审查 item schema；无需扩大父资源搜索范围。 |
| `app.monetization_app.list` | `draft` | 本轮 0 次请求；沿用既有空样本；草案声明 `page_info`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 先证明账户与变现平台参数的可信来源，再以第一页最小请求取得 1 个非空样本；不得猜测账户或平台值。 |
| `app.app_info.get` | **`stable v1`（已晋升）** | 调用方第 1 条公开 App Store URL 的唯一 GET 为 HTTP 200 / `code=0/msg=成功`，无重试；成功非空字段为 `app_id/icon_url/image_data/name/package_name/platform/version`，分页实测 `none`。旧 error-shaped 样本的 `error` 同样登记。 | 无 promotion blocker；OneLink 目录的账号级空事实单独保留，未用作成功绑定。 | CLI/SDK/Plan/Agent 共用 raw operation；`data.error` 离散为 caller 可恢复的 semantic error，新增字段继续 fail-closed。 |
| `app.user_auth.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读授权记录的环境取得 1 个非空样本，并重点审查权限、身份和个人信息字段，默认不暴露未知字段。 |
| `attribution.attribution.query` | `stable v1`（D35 已闭环） | hash-matched `Measurement` bundle 完整证明 14 个恒发字段、`project_id/dims_metrics_list` 两条条件省略、八个恒发筛选数组和四个有限调用画像。2026-08-16 生产 1 次 App catalog + 2 次单日目标 POST：首 App 明确空，第二 App 非空后停止。2026-08-17 宽窗 `date_list=["2026-07-17","2026-08-16"]` 按 catalog 枚举：`catalog#1` envelope `empty`，`catalog#2` 同窗 `success`（`items=23`）后立即停止；均 HTTP 200，无重试、翻页。短窗“无数据”只约束当时那一个 App 和单日窗。 | 无 promotion blocker；旧 evidence 未保存具体 error 正文，不能追认字段拒绝。新证据证明 `extra.error=无数据` 是 `code=0/msg=成功` 的明确空。 | 由 Core/CLI/SDK/Plan/Agent `attribution_performance` 消费；未知 semantic error 继续 fail-closed。 |

| `attribution.attribution_detail.query` | **`stable v1`（F40 已闭环）** | 1 次 App catalog 后顺序枚举 6 个 `app.testing_tool.list`，前 5 个明确空、第 6 个返回 1 条后停止；目录行 13 个顶层字段、`device_info` 3 个子字段及 `page_info` 4 字段全部登记。以内存父行 `id` 发唯一 1 次详情 POST，HTTP 200 / `code=0`；`device_white` 为同形 object，另外三个列表均明确为空。 | 无 promotion blocker；`attribution_list/postback_list/pay_list` 的 item schema 未观察，不能猜测，未来非空时 fail-closed。 | 由 Core/CLI/SDK/Plan/Agent `attribution_user_detail` 消费；父行只接受 `app.testing_tool.list` 的精确内部 ID。 |

## 2026-08-16 追加判定：Kanban 写与父删除语义

19 个点名的非显式-share operation 中，18 个取得精确 request contract 并晋升 stable；剩余
`analysis.datamanageconfig.kanban.space.093dd36e.delete` 的真实 path 是
`POST /datamanageconfig/kanban/space/share/delete/`，属于撤销分享且 payload 未由调用点证明，继续 blocked。
另一组哈希 operation `dashboard.dc7858a7.update` 则是独立的 dashboard rename POST；普通
`dashboard.update` 是保存 `report_list/ui_config` 的 edit POST，二者没有合并。

真实树与生产闭环证明：space 根 ID 为正数；系统“未分组/共享给我”folder 使用负 ID，自建 folder
使用正 ID；dashboard 继承 space/folder 坐标；note 嵌在 dashboard `ui_config`，删除走精确 note `i`。
folder 删除会移除容器并迁移 dashboard，space 删除会把 dashboard 迁到创建者 My Dashboard/未分组；
两者都不删除 dashboard。生产样本中 folder dry-run 为 `1 moved / 0 deleted`，space dry-run 为
`2 moved / 0 deleted`，写后树分别验证对象仍在；最终批量 dashboard delete 后全树 SDK marker 为 0。

本轮未对所有权 transfer、跨 space folder/dashboard move、order save 或 report unlink 发生产写：
前三者会影响额外层级/用户状态，order 会改变既有目录顺序，report unlink 需要含真实报表的 dashboard，
与“不创建、修改或删除多维报表”边界不相容。它们只按 hash-matched builder、精确合同、dry-run 和
fail-closed 测试登记；没有借现存用户对象补样本。

## 2026-08-16 追加判定：报表与订阅写解锁

hash-matched 前端控制流确认旧报表创建/删除共用
`POST /turbo_engine/api/v2/datamanageconfig/report/update/`：create body 为
`name/remark/subject/app_id/project_id/config`，delete body 另带 `id/report_group_id/is_delete=1`。
订阅 create/delete 分别为 `/turbo_engine/api/v3/subscribe/create/` 与 `/delete/`；前者引用 v3
`conftemplate` 报表 ID，旧报表 ID 的唯一一次尝试被上游明确拒绝“找不到报表”，没有退化或重放。
因此用已静态证明的 v3 `conftemplate/template/create/` 建一个 marker-owned 父报表，清理走同命名空间
`template/edit/` 的 `is_deleted=1`。`subscribe/test` 不属于闭环且会通知真实用户，始终没有调用。

本次新增 4 条 stable read（旧报表 list/detail、订阅 list、v3 父报表 detail）与 5 条 stable mutation
（旧报表 update、订阅 create/delete、v3 父报表 create/update）；既有 v3 自有模板 list 同步登记
非空观察字段。旧报表 list/detail 的非空 item 观察字段为：`app_id/cid/config/create_time/
create_user_id/create_user_name/id/modify_time/name/project_id/remark/subject/update_user_id/
update_user_name`。订阅 list 的非空 item 观察字段为：`app_id/category/cid/create_time/
create_user_id/create_user_name/end_time/hourly_send_periods/id/modify_time/name/project_id/
project_name/report_conf_template_id/report_type/send_way/start_time/subscribe_content/
subscribe_selected_columns/subscribe_status/update_user_id/update_user_name/wildcard_name`。字段全部登记
暴露；未观察但前端合同已知的可选字段仍是显式白名单，其他新增字段继续 drift fail-closed。

marker 只放在能原样读回且不改变数据口径的文本字段：旧报表与 v3 父报表用 `remark`，订阅同时用
`name/wildcard_name`。三类均验证 `GSDK-<12 hex>` round-trip；上游未拒绝该紧凑格式。旧报表 ID
不能作为 v3 订阅父 ID 的拒绝属于父对象类型错误，不是 marker 格式拒绝。删除前必须重读 marker，
删除后再次读取完整列表证明 ID 消失。

## 2026-08-16 追加判定：六条明确空的 App 维度复验

先用 1 次 `app.list` 取得 7 个可绑定 App，再按实际 route 维度执行。生产业务 HTTP 共 22 次，
全部 HTTP 200；重试、翻页、扩窗、失败和未试 App 均为 0。完整逐请求账本见
[roadmap 的复验章节](roadmap.md#六条明确空多-app-复验2026-08-16)。

- **(a) 当时最短当天窗下为空：2 条。** `report.media_report.list` 与
  `analysis.realtime_event.list` 在 2026-08-16 枚举 7/7 App 后仍空。2026-08-17 已按 D28
  方法用 `2026-07-17..2026-08-16`（并补测含当天）重测，仍空；结论收窄为“当前账号在已记录窗与空筛选下无行”，不再写无参数的“租户确实为空”。
- **(b) 旧结论是假阴性：1 条。** `analysis.default_val.list` 在 `catalog#1` 空、
  `catalog#2` 非空；旧探测在第一个空 App 停止，误把 App 局部事实写成租户结论。
- **(c) App 维度不适用：3 条。** 报表目录（三个 list route）、订阅和 App 项目的请求
  path/body 均无 App 输入，认证只绑定账号/公司上下文，各一次空响应就是账号级事实。

默认值字典由此解除 `successful_confirmation_required` 与动态投影 blocker：当前非空样本加既有
shape-only 样本只观察到 `api/cocoscreator` 两个 string-array 键，二者全部登记暴露；其他键继续
additive fail-closed。该 operation 晋升 stable 并闭环五面产品，不把空样本用于推断任何 item schema。

## 2026-08-14 追加判定：六条缺失动线批量定性

生产探测前预估 0 次业务请求，另留 6 次应急上限；实际 0 次。实际分类为
`success=0 / empty=0 / permission_unavailable=0 / semantic_error=0 / other=0`。
本地读语义 preflight 在凭据和 transport 之前拦截 7 个弱证据 POST；这些本地阻断不计业务请求，
也不能归入线上 `other`。另外从 census 已记录的精确 URL 分段读取同一报表 bundle 6 次，
仅用于静态控制流取证，不调用业务 API、不使用凭据。

| 动线 | 判定 | 已有证据与精确阻塞 | 下一轮最有希望的取证 |
| --- | --- | --- | --- |
| 查找自有、共享和 MasterKey 报表并读取其定义 | **非空样本阻塞** | 三个列表 POST 的 hash-matched bundle 控制流均证明装载、分页和响应消费，逐 route read confirmation 已登记；本轮各 1 次最小请求均 HTTP 200、明确空。`report.report.detail` 是 GET，但仍无父候选。 | 由有报表数据的租户提供 1 个非空列表项，再以内存父值做最小 detail；不扩窗找数据。 |
| 查看报表订阅清单 | **明确空 / item schema 阻塞** | `reportSubscribe` 的 read confirmation 已登记；prober 对精确确认路径放行。本轮唯一 1 次最小第一页请求 HTTP 200、`data.list=[]`，未额外翻页，未知订阅字段继续隐藏。 | 在有订阅项的租户复用同形状取得 1 个非空 item，再单独判断分页与投影。 |
| 查找可用的媒体报表 | **明确空 / item schema 阻塞** | Bundle 已恢复 `AppSelect` 与有限平台选项绑定，空选择省略；列表装载、分页和响应消费证明 read，confirmation 已登记。2026-08-16 当天最小请求 HTTP 200、明确空。2026-08-17 用 `2026-07-17..2026-08-16` 对 7/7 App 加重测并另做省略 App / 含当天各 1 次，仍 HTTP 200 空。 | 在有媒体报表的租户复用同形状取得 1 个非空 item，不猜平台枚举值。 |
| 查找当前账号可读的 App 项目 | **合同阻塞** | `app.project.list` 被读语义闸门拦截；旧空 receipt 虽证明分页壳，但 `method_verified=false`，不能排除请求合同或语义问题，也就不能定为数据阻塞。 | 分析 `appManageIndex-DCdX2wdf.js` 的列表装载与响应消费，登记静态读证据后做 1 次最小第一页 probe。 |
| 查看 App 的 OneLink 与公开信息绑定 | **已闭环** | `app.onelink.list` 的既有稳定父链继续证明当前账号明确空；调用方提供的第 1 条 App Store URL 使 `app.app_info.get` 首次取得 HTTP 200 / `code=0` 成功非空合同，并登记全部成功字段和旧 `error` 字段。 | 维持 stable live probe；若 Google Play 成功形状出现新字段，按 additive drift 登记并暴露。 |
| 按平台、广告位和日期汇总变现结果（D28） | **已闭环** | 2026-08-17 按 catalog 枚举 7 个可绑定 App；`catalog#1` 在 `2026-07-17..2026-08-16` 明确空，`catalog#2` 同窗 13 行非空后停止。item/total 观察 `stat_time/monetization_platform/ad_unit_id` 加请求指标动态列；分页为实测 `none`（`page_info` 只有 `total`，无 page/page_size）。同日双账号实验另证这条 route 上权限型空与真空**可区分**：低权限账号返回 `code=2000 / 您当前账号暂无权限操作`，高权限账号返回 `code=0`，因此 `catalog#1` 的空是真空而非权限所致。 | 维持 stable live probe；未观察维度/指标继续 fail-closed，不猜 item 字段。 |

**闸门命中：** `report.masterkey_report_group.list`、`report.report.list`、
`report.shared_to_me.list`、`report.subscribe.list`、`report.media_report.list`、
`app.project.list`、`app.monetization_app.list`。`report.report.detail`、`app.onelink.list`、
`app.app_info.get` 均为 GET，未命中。按探测纪律，命中后没有绕过、没有构造 transport、没有重试。

**Report 追加状态：** 上述五条 `report.*` POST 的历史闸门状态已由本轮逐 route 静态确认替代；
每条仅发 1 次最小第一页请求且全部明确空。读合同不再是 blocker，但空响应仍不能证明 item schema。

六条均非 Web UI 布局/收藏/拖拽、成员权限、写操作或调用方业务语义，因此没有判为非目标，
也没有从缺失清单移出；台账仍为 **42 条：已闭环 18 / 部分闭环 9 / 完全缺失 15**。

## 2026-08-14 追加判定：三条 `analysis.*` 合同取证

先估最坏 7 次业务请求；实际 3 次，分类为
`success=1 / empty=2 / permission_unavailable=0 / semantic_error=0 / other=0`。
`success` 是只用于内存解析最小 App 的 stable `app.list`；两个目标读取均 HTTP 200、语义成功但为空。
没有 confirmation、翻页、扩窗、换 App 或重试，`analysis.setting.query` 因静态证据证明为 mutation 而保持 0 次。

- Census：default-val 提取 `app_id/subject` 但响应未绑定；realtime-event 提取 5 个顶层字段、
  7 个 filter 子键且只追到 `data.list`；setting 提取 9 个顶层字段但响应未绑定。
- Bundle：完整 builder 证明 default-val 固定 `$lib_version`；realtime-event 空 filter 成员序列化时省略，
  前端对 `data.list` 做本地切片；setting 在修改图表后继续修改 dashboard layout 并提示修改成功。
- Artifact：看板、模板、saved-analysis 语料未发现 default-val/realtime-event 请求；已有看板 artifact
  也没有独立的 setting 请求或响应样本。
- 字段合同：本轮空响应没有观察到 item 类型；静态消费候选 `client_id`、`request_id`、
  `request_ip`、`raw_properties` 已获投影裁决，但仍因非空 schema 缺失而不登记。setting 的
  `name/remark/config` 未发送、未投影。

`analysis.default_val.list` 的旧非空响应确实证明 `data.api[]` 与 `data.cocoscreator[]` 为 string，
完整前端消费还证明 `data` 被当作动态字典、value 被按数组消费；它不能证明 key 的闭集或未观察 value 的类型，
也没有形成获批的动态 key 投影。本轮同形状空响应只能确认请求可用，不能确认 item 投影。
因此三条均未晋升：总 operation 仍为 185，stable 仍为 176。

## 2026-08-13 追加判定：变现明细（D27，字段边界已于 2026-08-15 推翻）

`analysis.monetization_detail.list` 保持 stable 且未改 wire。已批准投影由产品层
固定 fields allowlist、`re_attribute_info` 嵌套 allowlist 和逐结果重建强制；未知字段默认隐藏，
用户/设备字段不能经参数、Plan binding、Agent 卡、产品 raw 结果或错误收据打开。Core/CLI/SDK/Plan/Agent
card 已闭环，原自然语言固定 gap 仅对批准形状解除。D28 聚合未实现，`app.monetization_app.list`
仍是独立 draft，其账户绑定与非空响应 blocker 不因 D27 关闭。2026-08-17 双账号完整响应对照：
高低权限均为 `code=0 / list=[] / page_info.total_number=0 / extra 缺省`，权限型空与真空不可区分；
空结果须对照 `gravity apps permission-profile`。

## 2026-08-13 追加判定：数据表 schema 三条路由

来自 F41（按表名/App 查数据表当前 schema、字段与版本详情）的离线取证。**本轮 0 次网络请求**，
判定为证据不足，保持 fail-closed。

| Operation | Status | 本轮请求与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `metadata.data_table.list` | `draft` | 0 次；既有样本为空；无父绑定。`POST /turbo_engine/api/v2/event_dim/data_table/list/`，body `app_id_list`/`name_like`/`page`/`page_size` 为中置信度前端证据 | `not_probed`、`response_schema_unverified`、`request_binding_unverified` | 取得 1 份**不依赖猜测 App 或表名**的非空 list 值无关 schema，证明 item 中 `table_id` 的键与类型 |
| `metadata.data_table.detail` | `draft` | 0 次；父候选未解析，未发送 | `parent_resource_required`、`response_schema_unverified` | 由上一条的非空 list 提供 1 个候选，**仅在内存中**传入 1 次 detail |
| `metadata.version_id_set.get` | `draft` | 0 次；未 probe；父候选未解析 | `not_probed`、`parent_resource_required`、`response_schema_unverified` | 同上父绑定成立后再发 1 次；`table_id` 类型与响应结构均未知 |

三条关键结论：

- **表名没有可信来源**，**App 归属也没有**。`app_id_list` 只是请求候选字段，
  `related_prop[].app_id` 只是未验证的 detail 响应消费字段。
- **"当前版本"的权威语义无法定义。** `using_version_id` 的字段名不足以证明语义，
  且**不得按最大时间戳推断当前版本**。需要上游合同或前端控制流证据说明版本选定规则。
- 候选父链看似 `list.data.list[].table_id → detail/version_id_set`，但 `list` 既有样本为空，
  该输出路径未被证明，**不构成可信父绑定**。
- 隐私：本轮无线上响应，因此**不能宣称响应无隐私风险**。`column_val_list` 等未知字段仍可能
  承载业务值或用户级数据，继续默认隐藏。

### 2026-08-16 复核

已登记 `metadata.data_table.list/detail` 的逐条前端只读确认；唯一 catalog App 上的 list 最小第一页
为 HTTP 200 语义成功空，因此 detail 与 version 均没有合法 `table_id` 父项，未发送。该结果只解除
POST 读语义的探测安全疑问，不解除 item schema、父绑定或“当前版本”语义 blocker；三条继续 draft，
F41 状态不变。

同轮把其余非推广/素材 `uncovered_read` 全量逐条复核。18 条离线可取证候选按实时事件、数据表、巨量
项目素材、AppRank、点击监测、兜底 eCPM、自有多维模板的价值顺序处理；共 10 次生产 HTTP 后没有
成功非空合同。4 条 AppRank 根目录为 HTTP 200 semantic error；点击监测、data-table list 与自有模板
父目录明确空；其他 route 因缺父值或已证值域未发送。最终 18 条全部进入证据阻塞，不晋升 operation；
只有租户数据或服务端合同发生变化时才值得做下一次最小 probe。

### 2026-08-17 复核

本轮只读、不建表、不绑定、不删表。最小请求确认：自建 marker 的 shape **不能**支撑读产品。

| Operation | Status | 本轮请求与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `metadata.data_table.list` | `draft` | 1 次；空 `app_id_list` / 空 `name_like` / `page=1` / `page_size=1`；HTTP 200 / `code=0`，`data.list=[]` | `empty_sample`、`response_schema_unverified` | 仍缺不依赖猜测 App/表名的非空 list item；`page_info` 本样本只有 `page/page_size/total`，**没有** `total_page` |
| `metadata.data_table.detail` | `draft` | 对 `version.list` 首行内存 `table_id`（32 位字符串）发 1 次成功落盘的最小 POST；HTTP 200 / `code=1004`，`data={}` | `parent_resource_required`、`response_schema_unverified` | `version.list` 的历史 `table_id` **不是**合法 detail 父项；必须来自当前非空 `data_table.list` |
| `metadata.version_id_set.get` | `draft` | 对同一内存 `table_id` 发 1 次 GET；HTTP 200 / `code=0`，`data` 为整数数组（本样本 17 项） | `request_binding_unverified`（稳定合同未晋升；路径词元 `set` 被 Registry 当 mutation 拦截） | 非空整数数组已观察，但仍缺与当前 list/detail 成功链对齐的父绑定；晋升前还要给 GET 读语义开精确例外，本轮不做 |

自建表与真实表的差别已实测：8-16 的成功 detail 只发生在当时那张 marker 表上，该表已删除；当前租户 `list` 为空，历史版本目录里的 `table_id` 能取出版本 ID 集合，却不能读回当前 schema。三条继续 draft，F41 读产品未实现。

## 2026-08-13 追加判定：非 Bytedance 平台投放层级（D33）

选 Bilibili 与 Huya 两个平台做逐层父链取证（二者在候选中父链证据最完整）。
**总计 3 次业务请求**，无重试、翻页、扩窗或账户遍历；无权限错误、限流或合同漂移。

| 平台 | 层级 | 请求 | 结果 | 父绑定 |
| --- | --- | ---: | --- | --- |
| Bilibili | Account | 1 | HTTP 200 **非空** | 根层 |
| Bilibili | Advertiser | 1 | HTTP 200 **空样本** | **未产出 `advertiser_id`** |
| Bilibili | Campaign / Group / Creative | 0 | `parent_resource_required` | 否，未发送 |
| Huya | Account | 1 | HTTP 200 **空样本** | 根层未产出候选 |
| Huya | Advertiser 及以下 | 0 | `parent_resource_required` | 否，未发送 |

**结论：两个平台的父链都无法建立，D34（按计划/组/创意下钻表现）保持阻塞。**

唯一非空样本是 Bilibili account，键集合与现有 stable 投影一致：`advertiser_id`、
`average_cost_per_thousand`、`click_count`、`click_rate`、`cost_per_click`、`product_name`、
`san_lian_launch_total_consume`、`show_count`、`total_cash_consume`、`total_consume`、
`total_red_packet_consume`、`total_special_red_packet_consume`。
`advertiser_name` 已按上游授权边界登记返回；未知字段暴露数为 0。

**下一步最小证据：**

- Bilibili：stable advertiser 在同一单日第一页条件下返回 1 个 `advertiser_id`，
  之后才能逐层证明 `campaign_id → unit_id → creative_id` 的键、类型、分页与父绑定。
- Huya：先取得非空 account 候选；更关键的是需要前端控制流或上游合同，
  证明 report 请求如何绑定 `advertiser_id/campaign_id/group_id`——当前三个 report body
  **都没有这些父字段**。

**未决**：Bilibili account 已返回 `advertiser_id`，但 campaign 草稿声明的父资源是 advertiser report，
两者是否等价**不能推断**；Bilibili manager 三层的 `data.list` 与分页仍未在线证明。

## 2026-08-13 追加判定：平台专属素材/创意纵深（D32）

先估最坏 22 次业务请求，再执行最小根读取。**本轮实际 5 次请求**，均为 HTTP 200 空样本；
`success=0 / empty=5 / permission_unavailable=0 / contract_changed=0 / other=0`。没有重试、翻页、
扩窗、App 切换或账户遍历。Bilibili 与 Huya 复用上节 D33 的已提交结论，本轮不重复请求。

| 平台 | 本轮请求 | 当前账号数据可用性 | 父链断点 | 子级动作 |
| --- | ---: | --- | --- | --- |
| Apple | 1 | stable advertiser 最短单日窗口为空 | advertiser 未产出候选 | campaign/adgroup/keyword 未发送 |
| Bilibili | 0 | 复用 D33：account 非空，advertiser 为空 | account → advertiser | campaign/unit/creative 未发送 |
| Huya | 0 | 复用 D33：account 为空 | account | advertiser/campaign/group 未发送 |
| Qihu360 | 1 | stable account 为空 | account | advertiser/campaign/group 未发送 |
| Sigmob | 1 | stable account 为空 | account | advertiser/campaign/promotion 未发送 |
| UC | 1 | stable advertiser 最短单日窗口为空 | advertiser 未产出候选 | campaign/adgroup/feed 未发送 |
| Youdao | 1 | stable account 为空 | account | advertiser/campaign/group 未发送 |

七个平台前缀下的 31 个 draft 均无升级。按六项标准逐项判定：

| 六项证据 | 判定 |
| --- | --- |
| 请求绑定 | stable 根读取已证明；多数 report draft 有前端观测请求形状，但 manager/feed 子级仍按各自 draft 记录，不能跨路由推断 |
| 非空响应 | **全部目标 draft 缺失**；Bilibili 的非空 account 是 stable 父层证据，不是子级响应合同 |
| 分页 | 多数 report draft 有既有 `page_info`、第二页和安全上限证据；Bilibili manager、UC manager/feed 等仍缺在线分页语义。分页证据不能替代非空 item schema |
| 字段合同 | 本轮空列表只证明响应壳，不证明 item schema。复用的 Bilibili account 中 `advertiser_name` 已按 stable 投影登记返回。 |
| 父依赖 | **全部目标 draft 未闭环**；分别断在 account 或 advertiser，未把任何父值写盘 |
| 权限 | 5 个本轮根读取均可访问且语义成功为空；未发送的目标 draft 没有目标路由权限证据。没有 `permission_unavailable` |

因此有既有分页壳证据的 report draft 仍至少卡在 `empty_sample`、目标 item 隐私、父依赖和目标权限；
manager/feed 等无完整分页证据的 draft 还卡在 `pagination_unverified`。下一步只允许在有数据租户上复用
同一最小范围，从对应断点开始；当前账号下不得重试或扩大范围。

## 2026-08-17 复测：非 Bytedance 投放前提（D32 / D33/D34 共用）

**提案：**一次回答“当前租户非 Bytedance 到底有没有数据”，排除短窗假阴性与权限误读。
不改错误分类、不改评测题集、不探测弱证据 POST draft。

**决定性实验（8 次业务 HTTP + 2 次登录，全部 HTTP 200，无 `code=2000`）：**

| # | operation | 窗/筛选 | 结果 |
| ---: | --- | --- | --- |
| 1 | `promotion.latest_account_status.get` | 无输入 | 非空 3 行：`media` 字面量 `bytedance`/`tencent`/`kuaishou`；腾讯 `good`，快手 `severe`；无 Bilibili/Huya |
| 2 | `promotion.tencent.advertiser.list` | `date_list=["2026-07-17","2026-08-16"]`，`page=1,page_size=1`，`time_line=behavior` | `code=0` 非空；`page_info.total_number=127/total_page=127`；item 含 `advertiser_id`；additive drift `operator_id/operator_name` |
| 3 | `promotion.tencent.adgroup_filter.list` | `page=1,page_size=1` | 非空；`total_number=260`；item 键 `adgroup_id/adgroup_name/advertiser_id` |
| 4 | `promotion.kuaishou.account.list` | `page=1,page_size=1` | `code=0` 明确空；`expired_cnt` 存在；`total_number=0` |
| 5 | `promotion.tencent.medium_adgroup.list` | 内存 `advertiser_id` + `api_version=v3.0` | 非空 1 行；分页实测 `none`（无 `page_info`） |
| 6 | `material.tencent.list` | 同一 `advertiser_id`，`page=1,page_size=1` | 非空；`total_number=427`；additive drift 12 个字段；登记 8 个标量/URL/人员字段；4 个空数组人员容器未登记子 schema |
| 7 | `promotion.kuaishou.advertiser.list` | `date_list=["2026-03-01","2026-08-16"]` | `code=0` 明确空；`total_number=0` |
| 8 | `promotion.kuaishou.account_company.list` | `need_company=true` | 非空 2 个整数公司 ID，不是投放报表行 |

**权限排除：**8 次业务请求均为 HTTP 200 / 语义成功；0 次 `code=2000`、0 次 `permission_unavailable`。
空配置不当作没权限。快手空报表与腾讯非空同时存在，所以空不是账号级权限裁剪。

**与 2026-08-13 的差别：**上次只打 Bilibili/Huya、最短单日、不换对象、不扩窗；实际请求体只在
probe evidence 里留下字段形状（`date_list` 为 string/`$today`），没有保存日期值。本轮先用账户
目录一次定性，再对绑定平台开到 D-31..D-1（快手因 `severe` 且 3 月报表时间再扩到 2026-03-01）。

**推进与卡住处：**

- D33 父候选已成立：腾讯 advertiser / adgroup_filter / medium_adgroup 均可选。
- D34：`promotion.tencent.tencent_adgroup_v2.list` 已 `confirmed_read`、非空 `page_info` 实测并晋升；`promotion.tencent.ad.list` 已确认读语义，但对声明父对象 `code=2000`。`promotion.kuaishou.campaign.list` 已 confirmed-read，最小第一页明确空。2026-08-18 前提反查未再打该 route：见下节。
- D32：`material.tencent.list` 既有非空合同；`material.tencent_medium_creative.list` 已 `confirmed_read`、非空 item schema、分页实测 `none` 并晋升。`material.tencent_asset_text_title.list` 与 `material.kuaishou_creative.list` 已 confirmed-read，最小第一页明确空。2026-08-18 前提反查未再打这两条。
- 不改评测题集：冻结评测 J45/J46 仍期待原 gap code。

**能力台账不变：**operation 233、stable 224、产品卡 92、精确 gap 7、selector 329、
动线 `56 = 50 / 1 / 5`。

## 2026-08-18 复测：先问投放前提，再决定是否打空 route

**提案：**不再用卡住的快手/腾讯标题 route 枚举空列表。先用已闭环的 D35/D28 反查这两个投放相关 App 实际出现过哪些平台值。

**决定性实验（4 次业务 HTTP，全部走 stable read，无卡住 route）：**

| # | operation | App | 窗/筛选 | 结果 |
| ---: | --- | ---: | --- | --- |
| 1 | `attribution.attribution.query` | 29034827（甜甜旅行抖音） | `date_list=["2026-07-19","2026-08-17"]`，`dims_list=["date","ad_platform"]`，`metrics_list=["AppRealRegisterCnt"]`，`statistics_caliber=user_activated_time` | `status=success` / `items=60`；`ad_platform` 仅 `bytedance` 30 + `natural` 30 |
| 2 | `report.get.query` | 29034827 | 同窗，`data_dims=["monetization_platform"]`，`time_dims=total`，`metrics_list=["reporting_ad_revenue"]`，`app_id` 字符串 EQUALS | `status=success` / `list=2`；`monetization_platform` 仅 `dy_mini_game` 与空串。这是变现平台，不是投放平台 |
| 3 | `attribution.attribution.query` | 27018426（甜甜旅行快手） | 与 #1 同形状 | `status=empty`；无 `ad_platform` 行 |
| 4 | `report.get.query` | 27018426 | 与 #2 同形状 | `status=empty` / `list=0` |

**因此确定：**这两个 App、该 30 日窗内没有可绑定的非 Bytedance `ad_platform`。按分流未再请求 `promotion.kuaishou.campaign.list`、`material.kuaishou_creative.list`、`material.tencent_asset_text_title.list`。

**不从本实验推出的：**不否定 2026-08-17 腾讯 advertiser/adgroup/material 账号级非空；那些是账号目录，不是这两个 App 的归因投放平台。`natural` 是自然量，`dy_mini_game` 是变现。

**相关 route 行：**

| Operation | Status | 本轮请求、样本、分页与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `promotion.kuaishou.campaign.list` | `confirmed_read`，最小第一页曾明确空；本轮 0 次 | 2026-08-18 未重打。D35 在快手 App 明确空，在抖音 App 无 `kuaishou` 平台值。 | `empty_sample` 现可归因于这两个 App 无快手投放，不是未试请求形状 | 换一个 D35 `ad_platform` 含 `kuaishou` 的租户/App 再取 1 个非空 item；当前这两个 App 不必再打。 |
| `material.kuaishou_creative.list` | `confirmed_read`，最小第一页曾明确空；本轮 0 次 | 同上，未重打。 | 同上 | 同上。 |
| `material.tencent_asset_text_title.list` | `confirmed_read`，最小第一页曾明确空；本轮 0 次 | 未重打。D35 在这两个 App 无 `tencent` 平台值，故本趟没有可绑定的 App+平台对。 | `empty_sample`；账号级腾讯素材非空不能外推到本条标题包 | 仅当某个 App 的 D35 出现 `tencent` 后再打 1 次最小第一页；不要用 08-17 的账号级腾讯目录当本条的 App 绑定。 |

## 2026-08-16 追加判定：Analysis 导出与平台素材二进制

两组候选都获得新证据但 **0 条晋升**。Analysis 导出的 8 条 frontend request binding 已从
hash-matched bundle 恢复；`stream_event.start` 只存在未调用 loader，按钮实际做客户端导出。生产父链
在首 App、单日、第一页明确空后停止，故没有 create/file/type 新证据。平台素材样本证明一个
`file_url` 的 HEAD 200 与 1 KiB Range GET 206、MP4 magic 和无 redirect，另一个 `thumbnail_url`
HEAD 405；这些事实不足以外推完整 CDN origin/path/redirect/expiry/size 与历史失败集合。两组均保持
candidate/unverified，不动态学习 allowlist。既有 stable 项目素材读取按投影总裁决新增 URL 与空容器
字段，不构成候选晋升。逐请求证据见
[`evidence/forensics/20260816_export_binary.json`](../evidence/forensics/20260816_export_binary.json)。

### 第二轮纠错（2026-08-16）

按授权枚举 catalog App 后，第三个 App 首次产生非空单日用户事件；9 次生产 HTTP 完成唯一一次
`user_event` create→首 poll READY→XLSX download，取得 7 行、5 列的完整单元格存储和逻辑类型。
该 export route 现为 verified/callable，但不是本矩阵 draft read operation 的晋升，operation/stable
仍为 185/176。其他六类只能复用任务传输协议，仍需各自成功文件；`stream_event` 已由无调用 loader
与客户端序列化按钮证明为前端不产生 server request，记 `not_applicable`，不再作为后续探测缺口。

素材侧 10 次生产 HTTP 从 `material.local.list` 的 5 个自然引用取得 4 个缩略图最小 Range 样本：均为
206、`image/jpeg`、JPEG magic、无重定向；本轮 host 收敛到 `tos-accelerate.gravity-engine.com`，累计
仍有 `v26-cc.oceanengine.com`、`p26-sign.douyinpic.com` 三个已观察 host。固定本地素材 host/path 可窄
登记，但外部 CDN shard 全集和四类失效语义仍未证明，所以 Issue 19 保持未闭环。四份 bundle 各 GET
一次后仅本地检索。完整账本见
[`evidence/forensics/20260816_export_binary_round2.json`](../evidence/forensics/20260816_export_binary_round2.json)。

### 第三轮：素材 URL 来源边界纠错（2026-08-16）

本轮不晋升新的 upstream operation；纠正的是 Issue 19 产品 effect 的输入合同。调用方不能传 URL，
只能传 `local|bytedance_project` source、对应 stable operation 输入和精确素材引用；产品在同一次调用
里重新读取 source，并只跟随刚返回行中的 `file_url` / `thumbnail_url`。因此 CDN host shard、path 和
redirect target 不再是本仓库自建门禁，不枚举、不限制；最终只记录 host family 与跨 host 事实。

生产 HTTP 共 7 次：1 次项目目录第一页，跳过已知空首项后读取 project position 2–6 共 5 次，前四空、
第 6 个首次非空；随后 1 次自然缩略图 64-byte Range GET 为 206、`image/jpeg`、JPEG magic、
`Content-Range 0-63/109820`、无 redirect。0 重试、0 翻页、0 扩窗、0 App 枚举、0 失效 URL、0 bundle
GET。结合第二轮平台 MP4 样本，Bytedance source 的 file/thumbnail 都有证据；本地 source 继续只用
自己的 4 个 JPEG 与 3 个 MP4 样本，两者没有跨 source 外推。产品 Core/CLI/SDK/Agent 已闭合，Plan
按文件 effect 窄例外登记设计不适用。完整账本见
[`evidence/forensics/20260816_export_binary_round3.json`](../evidence/forensics/20260816_export_binary_round3.json)。

失效语义不再按前端不存在的四状态分类：实际观察状态为 200/206 及旧 HEAD 405；403/404/410 未观察。
合同把有效 response-bound URL 的所有 terminal 非 200 归 upstream/exit 3，source/ref/role/input 归
caller/exit 2，本地文件提交归 local/exit 4；不构造任何失效 URL。

### 第四轮：六类 Analysis 服务端导出重判（2026-08-17）

字段投影不再是 blocker。固定 catalog 第三个 App 和 `2026-08-16` 单日的父读取分别返回：
user detail 1 行、pay event 1 行、monetization detail 1 行、已完成分群 1 个、分群成员 1 行和
正数版本 1 个。因而没有创建临时分群，也没有清理写请求。以上游请求为真实边界，
`segment.result`、`segment_user_detail`、`user_detail`、`pay_event` 四族各自取得非空
create→poll→download→validate 文件，并以独立的 worksheet/header/storage/Python/logical type 合同晋升
verified/callable。这是 export route catalog 的 effect 状态变更，不是 stable read operation 晋升；
operation/stable 仍为 231/222。

`origin_event` 已用第三 catalog App 的 7 日窗取得正数 evaluate（`data.total=1`，第一个可见 `$` 预设事件），并完成一次 create→poll→download。实测文件是 511-byte gzip CSV，不是 XLSX：`text/csv`、magic `1f8b`、五列表头、1 行。`analysis.event.list.yesterday_count` 在该 App 129 个事件上全为 0，不能当阻塞理由。`monetization_detail` 的唯一 create 经 4 次有界退避轮询仍 RUNNING，
后续通过精确 `task_name` 恢复后达 READY；后续补证把共享下载栈的 `BLOB_ARCHIVE_UNSAFE` 精确定位为
route 的 128 MiB `uncompressed_size_cap`。文件在保留其他守卫、仅把该 route 展开上限设为 192 MiB
后安全通过，shape 为 `Sheet1`、1,000,000 行、`事件发生时间/客户ID`；但同 scope 明细
`total_items=1,212,315`，任务和文件没有截断信号，empty shape 也未在线验证，故仍不冒充 `complete`。
同 App/日期的自然 ClientID 窄化尝试又在本地 typed-condition 校验阶段失败，所以第二个 create 为 0。
两族仍是 gap，不关闭共享 archive 门禁，不从其他族猜 shape。完整 41 次原轮生产 HTTP 账本、四份文件
shape 和六态证据见
[`20260817_export_families.json`](../evidence/forensics/20260817_export_families.json)。
归档规则、实测数值、变现 shape 与静默截断补证见
[`20260817_contract_evidence.json`](../evidence/forensics/20260817_contract_evidence.json)。

第五轮完整性复核没有改变晋升结论。冻结的 375 个 JS 中，`CashSearch-00g6muds.js` 已明确声明
`total_number > 1e6` 时列表和导出只保留事件时间降序前 100W 条；这与 `1,212,315 → 1,000,000`
生产结果一致。任务 list/progress/file 都没有 task-bound total 或 truncated；另一套 origin-event
`evaluate_data` 只返回预估 total，并在超过 1e6 时禁用提交，没有 shard/page/continuation 控制。
当前日小窗口文件为 110,966 行，恢复时列表已增长到 111,792，因 create-time total 未保留而不能宣称
精确对平；小时条件又返回全日量级 1,212,325。故日切窗不能解决已经单日超限的目标，小时切窗也未成立，
`monetization_detail` 现为 `verified/executable=true`：create 前钉住同 scope 列表 `total_items`，触达 100W 上限时标 `truncated` 并同时返回钉住总量与文件行数。

已晋升四族的同 scope 完整性补证全部通过：`segment.result` 1/1、`segment_user_detail` 1/1、
`user_detail` 255/255、`pay_event` 217/217（文件行/受管总数），无需降级。44 次生产 HTTP 的逐条账本与
不确定项见
[`20260817_export_sharding.json`](../evidence/forensics/20260817_export_sharding.json)；operation/stable 仍为
231/222。

## 2026-08-14 追加判定：D22 看板条件合并语义

**判定：证明不了，不是部分证明。** 本轮取证 HTTP 共 10 次：1 次公开 source-map GET 返回 404；
2 次 stable `app.list` 与 7 次 stable `analysis.dashboard.tree` 均返回 HTTP 200。看板树中 6 次为合法空样本，
1 次为 `contract_changed`；没有 detail、default-favourite、分析 query、POST、重试、翻页、扩样或写入。

- Bundle：冻结 `Dashboard-DrzT0Orh.js` 为 251654 bytes，SHA-256
  `6fc5339f29035a8aa08755e1ebfc482dd227c1c4511ff35c340dcc621ac48016`；三份本地 census 正文逐字匹配。
  完整控制流证明 chart `global_conditions` 与 page `dashboard_condition` 是同一请求的独立顶层字段，
  公共 HTTP wrapper 直接发送 body，前端没有合并或覆盖。合并若存在，只能发生在服务端。
- Artifact：当前账号全部 7 个 App 都没有取得可选看板；本地历史 receipt/临时语料也没有双条件实例。
  因此异维度叠加和同维度冲突都没有可判别样本。
- Probe：没有发送分析请求。现有 stable Analysis 合同不登记 `dashboard_condition`，离线校验以
  `INPUT_INVALID`、`network_called=false` 拒绝；不使用 raw transport 绕过。弱证据 POST 读语义闸门未命中。
- 反例：前端证据同时兼容 AND、页面覆盖、图表覆盖、同维度替换/异维度叠加四种服务端实现，
  所以不能从“两个字段都出现”推断任何一种规则。

解锁至少需要服务端合同，或自然存在的双条件看板及其只读请求/权威结果；证据必须同时区分
异维度组合与同维度冲突。D22 的非空页面条件继续 fail-closed，空条件行为不变。

## 本轮可复用结论

- 多 App Analysis 扇出是既有 `analysis.event/funnel/retention/property.query` stable 产品的离线
  Plan 编排增强，本轮 0 次生产请求、0 个 candidate 晋升；operation 总数和 stable 数不变，不改变
  本矩阵 17 项 draft 的 blocker。
- Agent 固定产品按 owner 正向证据强度与 selector 精确度集中裁决；命中多个 authoritative 产品时返回
  `MULTIPLE_INTENTS` 与候选 selector，候选为空且禁止 raw operation fallback。7 对已知重叠均以
  owner recognizer 离线复现该行为，公共 Agent/Plan/card envelope 未变。
- 六个列表操作已得到可复用的 `page_info` 分页证据：`report.masterkey_report_group.list`、`report.report.list`、`report.shared_to_me.list`、`app.project.list`、`app.user_auth.list`、`app.onelink.list`。
- `app.onelink.list` 的稳定父绑定链路已被证明可用，但空样本仍不足以证明目标 item schema。
- `analysis.default_val.list` 是本轮唯一非空候选响应；当前证据仍不足以关闭请求合同和响应投影 blocker。
- 其余候选保持 fail-closed：空样本不证明字段、业务语义错误不证明请求合同、父资源为空不触发子请求；用户级标识可用，但不能替代请求绑定证据。

## 2026-08-15 追加判定：Analysis semantic rejection 三案

本轮不是 candidate 晋升，而是对三条 stable Analysis 动线做 value-free 合同复核；operation 总数与
字段级隐私裁决现由路线图总裁决取代；本段历史请求账本不变。实际 33 次 HTTP read 的分项为：metadata 22 次、Retention 4 次、Segment 3 次、
Property 4 次；每个 transport 仅尝试一次。

| Issue | 在线可区分证据 | 当前合同结论 | 未决与精确下一步 |
| --- | --- | --- | --- |
| #11 Retention | 原 spec 当前返回非空 aggregate；过滤通道变体为空；两轮投影确认由 `contract_changed` 到 `success` | 上游当前接受原 wire；登记月桶、固定累计/周期字段、百分比和嵌套数值路径，Retention contract v2 | `ae0d449` 时 semantic rejection 的服务端原因已不可复现，保持 unknown；除非服务端再次拒绝且提供新约束证据，不猜历史原因 |
| #15 Segment presets | `$MPShow`、`$PayEvent` 各自经过 event/event-property metadata 后都被 evaluation endpoint semantic reject；同 session metadata-backed custom control 成功 | 二者为 operation-specific unsupported；schema 暴露支持元数据，compact/raw 均 preflight caller error；普通 custom 路径未收窄 | 未证明其他 preset 的支持状态；下一次只有在出现具体 preset 需求时，先取一条同 session custom control，再各发一次目标 event，不把“registered”当“supported” |
| #17 Property group | 原 spec失败；无 filter 仍失败；无 `$ea_gid` group 成功；`user_re_attribute` group 仍失败 | acquisition-ID group 当前 unsupported，网络前给出精确路径；不自动重写字段/type | accepted grouped wire 未知；解锁需要服务端合同，或 Web 自然生成该 group 的原生请求并一次只读复核。缺此证据前不扩大 group 支持 |

三案共同的只有错误层：所有 manifest semantic rule 原先统一抛可重试 `UpstreamError`。该层现改为
caller/non-retryable，同时保留 `semantic_error` 状态以便调用方识别服务端语义拒绝；transport、权限与
rate-limit 分类未改变。

## 2026-08-14 追加判定：App / 变现家族读语义

静态取证读取了 snapshot 对应的 `appManageIndex-DCdX2wdf.js`、`csj-DQrv-k3Y.js` 和
`tobid-DwnAMImZ.js`。实际生产业务请求共 3 次：`app.project.list` 1 次明确空，
`app.app_info.get` 2 次均为 HTTP 200 但最终 `inconclusive`，`app.monetization_app.list` 0 次；
没有认证交换、重试、翻页、扩窗或换 URL 追非空。

| 动线 | 本轮判定 | 新证据与剩余阻塞 | 下一步 |
| --- | --- | --- | --- |
| 查找当前账号可读的 App 项目 | **推进但未闭环** | Project 组件在 mount/search/page change 时 POST `page/page_size/filters`，只消费项目表 `list/id/name/app_list_info` 与 `page_info`；create/delete 是独立 mutation。确认已登记；最小 probe 1 请求、HTTP 200 明确空，receipt 的 `method_verified/pagination_verified/parent_resolved` 均为 true，当前账号确无项目，但 item schema 未成立。 | 由有可读项目的租户做 1 次最小第一页 probe；只审查非空 item 字段，之后才考虑产品面。 |
| 查看 App 的 OneLink 与公开信息绑定 | **推进但未闭环** | OneLink 父链仍明确空。appManage 证明 app-info URL 是调用方输入的 Google Play/App Store 下载链接而非 OneLink；公开 URL probe 2 请求均 HTTP 200，恢复七字段 schema 与四字段安全投影，但上游返回含 `data.error` 的 error-shaped 数据，结论 `inconclusive` 而非成功。 | 调用方提供一条已知可被 Gravity 抓取的公开商店 URL；仅做 1 次读取，成功非空后再确认当前安全投影。 |
| 按平台、广告位和日期汇总变现结果（D28） | **仍然阻塞** | csj/tobid bundle 已证明 `app.monetization_app.list` 是账户下的平台应用关联目录读取：account 来自选中账户行、平台固定为 `csj`/`tobid`，表格只有平台应用/类型/包名/Gravity App 关联，mutation 另有路由。该 route 没有日期、广告位或结果指标，产品语义不匹配 D28；因此只登记读确认，目标 probe 0 次。 | 转向 `/report/api/v3/monetization_report/custom_get/` 与 `calc_total/` bundle，恢复日期、广告位、平台维度、指标、分页和响应合同；字段隐私不再是阻塞。 |

## 2026-08-15 追加判定：D28 真实报表 route

`NewReportCenter-Dxgo5EkI.js` 的 hash-matched 冻结正文已把两个弱证据 POST 提升为逐 route 人工确认的
read：主 route 装载/刷新本地表格，`calc_total` 只按已加载行组重算本地合计。两者没有写 continuation，
保存/编辑使用独立 route；确认仍受精确 method/path/namespace 三重约束。

| Operation | 新证据 | 精确 blocker | 下一步最小证据与提供方 |
| --- | --- | --- | --- |
| `report.get.query` | 九个顶层 body 字段、六个 `data_conf` 子字段、filters 构造、undefined/`[]`/固定值规则及无 upstream pagination 均已静态证明；唯一 live 请求已经发送，但 one-shot 脚本在后续本地校验失败前未 flush 观察。 | `probe_receipt_missing`、`request_value_domain_unverified`、`response_schema_unverified`；HTTP status/fingerprint 不推断，也不补发。 | 网关/服务端日志维护者提供该次请求的值无关 status/schema，或调用方提供自然 Web 装载的脱敏 schema；有真实报表数据的租户管理员再提供非空 `list/total` shape；API owner 提供 metric/dimension 值域。取得实际 shape 后登记并全部暴露，静态候选不作为省略字段。 |
| `report.report_monetization_report_custom_get.calc_total` | 八字段 builder、二维 `data_list`、条件调用关系已证明；唯一 HTTP 为 200，fingerprint `6d57dc755d2469b2a4f0a93e64b556528187f4ec988ae574d62682f42b2ce278`，只见 `data.list[]:object` 且无 item key。 | `request_value_domain_unverified`、`response_schema_unverified`、`field_review_required`；空行组只能证明 envelope，不能证明有效合计字段。 | 有真实非空主结果的租户管理员提供一次自然触发的 value-free `calc_total.list[]` shape；API owner 提供必填和值域；取得实际 shape 后登记并全部暴露。 |

生产业务请求为 3：`app.list` 1、主 route 1、`calc_total` 1；无认证交换、重试、翻页、扩窗、App
切换或平台/广告位猜值。只有最后一笔持久化了 HTTP 200 schema，前两笔 status 未登记。观察到的 live
item 字段为零，因此没有可声称的 live item 字段；静态候选不列入 `known_omitted`，其余动态 key
语义不明且由空投影 fail-closed，取得实际 shape 后按投影总裁决登记并全部暴露。

两项都不晋升，operation/stable 数保持 `185/176`，D28 仍为完全缺失；没有实现任何产品面。

## 2026-08-16 追加判定：三域 mutation owner 证据

本轮没有晋升 operation；223/214 总数不变。受控创建/readback 证明登录 `gravity_id` 与 Kanban
dashboard `create_user_id`、space-members `creator.id` 相等。原假设的 `creator[].uid` 不符合实际响应：
`creator` 是 object，字段为 `id/name`。Segment、v2 report、v3 template、subscription 与 dashboard
使用 `create_user_id/create_user_name`；space 使用 `creator.id/name`；folder/note 没有已证实直接 owner。

三域 mutation 判据因此统一为 `GSDK marker OR proven owner == authenticated gravity_id`。线上用稳定 route
去掉 SDK marker 后，dashboard、Segment、Report 均由正式 delete 以 `upstream_owner` 成功并读回消失；
marker space 仍以 `sdk_source_marker` 删除。当前目录没有 foreign Segment/Report/dashboard，唯一 space 的
creator 也是当前 principal，故真实 foreign 拒绝没有生产样本，不能作为已验证 capability evidence；
测试锁定 foreign/missing-owner 零 write fail-closed。folder/note 的非 marker 限制继续是上游证据 blocker，
不能跨对象族推断 owner 字段。

## 2026-08-17 追加判定：P0-2 三族 owner 字段只读复核

本轮不晋升 operation。只读复核分群、保存分析、元数据模板 master：三族稳定 owner 都是 int
`create_user_id`（name=`create_user_name`），与 `gravity_id` 字符串相等。7 个 App 首页 + master
全集：分群 32、保存分析 313、master 5，缺 owner 字段 0。保存分析 App `29034827` 有 42 条当前
principal 自有且无 marker；分群与 master 首页没有当前账号自有无 marker 样本，未为此写对象。
闸门仍是共享 `marker OR owner`；本轮锁住无 marker 放行、marker 仍有效、foreign/缺字段拒绝。
看板 space/dashboard 不在本轮。
## 2026-08-16 追加判定：设置入口与 D28 当前配置 route

本轮以引力自然页面动作识别真实入口，再用现有只读 SDK 对 D28 做有界反证。App 页面取得非空；
F41 页面明确空；D28 在目标上限 8 次前停于 7 次。没有 write、重试、扩窗、换 App、模板修改或
主结果 route 补发，也没有把静态字段候选登记为响应合同。

| 动线 | 判定 | 实测证据 | 产品结论 / 下一步 |
| --- | --- | --- | --- |
| 查找当前账号可读的 App 项目 | **已闭环；旧候选不是目标端点** | 设置 → 应用管理自然发出 `GET /turbo_engine/api/v1/user/open_app/list/`，HTTP 200、首屏 7 行。观察 17 个 item 字段和 4 个 `page_info` 字段，键与类型均已由既有 stable `app.list` v4 全量登记；raw schema fingerprint 为 `a4a2bf907a0e45f47de2656f0354c766850c2c06460b1008477664b5d14d3491`。 | J39 改由 `app.list` 的 CLI/SDK/Plan/Agent 卡承载；不晋升、改写或冒充账号级明确空的 `app.project.list`。两 route 分别是 open-app GET 与 project POST，不是同一个端点。 |
| 按表名或 App 查询数据表当前 schema、字段和版本（F41） | **证据不够支撑读产品；三条继续 draft** | 2026-08-16 marker 自建表只留下已删除对象的计数叙述，无字段级 schema。2026-08-17 最小读：`list` 第一页仍明确空；`version.list` 的真实 `table_id` 对 `detail` 为 `code=1004` 空 data；同一 ID 的 `version_id_set` 成功为整数数组（17 项）。 | 不能把已删自建表的 detail 计数登记成现表合同，也不能用 `version.list` 的历史 `table_id` 冒充 `data_table.list` 父绑定。下一步仍是取得一份**当前 list 非空 item**，再仅在内存中打 1 次成功 detail；写产品与解绑合同不在本动线。 |
| 按平台、广告位和日期汇总变现结果（D28） | **三选一：请求参数/路由不对；仍未闭环** | 当前 `NewReportCenter` 用 `/turbo_engine/api/v3/confmetric/metric/list/` 和同命名空间 permission route，并以 `data_topic EQUALS monetization_report`、`is_media EQUALS false|true` 取配置。现有 stable operation 仍指向旧 `/report/api/v3/confmetric/metric/list/`。7 次旧 route 均 HTTP 200：1 次错误 `IN` 语义拒绝；一次空 filter 调用自动读 5 页、200/1124 行无目标 topic；1 次当前正确 filter 仍被旧 route 语义拒绝。 | 判据是**同一当前 bundle 的 route 与现有请求不一致，且正确 filter 在旧 route 仍失败**。这不能判定租户没数据，也不能判定权限未生效；permission、主结果、非空 item/total 和值域均未知。下一步应先单次验证当前 turbo config/permission，再用其真实物理字段自然触发主结果；不得继续在旧 route 换参数。 |

三条目标尝试为 `App 1 / F41 1 / D28 7`；连同页面自然触发的 7 次辅助业务读取，实际生产业务
HTTP 共 16 次，全部在全局 40 次上限内。逐请求账本与辅助/目标边界见[路线图当前章节](roadmap.md#设置应用元数据与变现报表复核2026-08-16)。
J39 从完全缺失转已闭环，台账由 `52 = 43 / 1 / 8` 变为 **`52 = 44 / 1 / 7`**；F41 与 D28
保持完全缺失。operation/stable 仍为 223/214；canonical 产品卡仍 45，精确 gap 为 9。

## 2026-08-16 追加判定：自定义指标口径定义

这不是 17 项 read candidate 的替代；它新增一个受治理语义对象产品。hash-matched 当前前端证明
turbo `custom_metric/edit` 是 create/update upsert、turbo `delete` 是当前删除，生产再证明当前 turbo
create 的对象会被旧 `/report/.../custom_metric/list` 读到并供 Multidim live metadata 使用。当前和旧
前缀因此并存，旧 stable read 不迁移。哈希 delete 后缀 `8ef6d12d` 是新 method/path 与旧 operation ID
碰撞后的 SHA-256 前八位，不是第三种删除语义。

生产固定 App 29034827、2026-06-01 至 2026-07-10、公式 `ap_cost`。标准对照和自定义指标查询各返回
40 个日行；自定义结果 40/40 行都含 non-null 请求指标列。平台 ID 实证为 opaque string
`pIgEhWsPjMvEfWrW_277516`；更新后删除，当前目录两次明确空、残留 0。新增 stable 当前 list/upsert/delete
3 条 operation，并新增 list/create/update/delete 四张独立产品卡；当前总数为 226/217、49 卡、284
selector，动线为 `53 = 45 / 1 / 7`。完整权限裁决、40 条旧前缀清单和 18 次 HTTP 账本见
[路线图当前章节](roadmap.md#自定义指标口径-crud-与-confmetric-前缀裁决2026-08-16)。

`metadata.engine.datamanageconfig.metrics.create` 已证明是 role-level `metrics_dict` 保存，不是自定义指标
create；`report.engine.confmetric.permission.update` 会覆盖角色可见指标/维度并影响其他用户，因此两者
都保持 blocked reservation，permission 未发送生产请求。share 同样不在本轮范围。

## 2026-08-16 追加判定：事件/属性元数据模板治理

题面代码块列 8 个 operation ID，并另写“带 hash 后缀的 template create”，合计 9；Census 当前快照中
9/9 都存在，且均为 POST。复核后的精确 method/path 与产品裁决如下：

| Operation | Path | 裁决 | 分析价值或停止理由 |
| --- | --- | --- | --- |
| `metadata.event.property.template.079c8246.create` | `/turbo_engine/api/v2/event/property_template/create/` | 做 | 同一路由创建或软删模板 master；可形成可复用分析元数据对象并安全清理。 |
| `metadata.event.property.template.create` | `/turbo_engine/api/v2/event/property_template/append/` | 做 | 向既有模板追加 App 目录事件/属性，补齐生命周期。 |
| `metadata.property.template.event.delete` | `/turbo_engine/api/v2/event/property_template/event_delete/` | 做 | 从 `meta_property` 模板移除事件成员；删除前后均可用模板成员目录保护。 |
| `metadata.property.template.property.delete` | `/turbo_engine/api/v2/event/property_template/property_delete/` | 做 | 从事件/用户属性模板移除成员；生产已完成该分支读回。 |
| `metadata.event.property.group.update` | `/turbo_engine/api/v2/datamanageconfig/conf_event_property_group/save/` | 不做 | 只保存 Gravity Web 分类、顺序和显隐；SDK 分析不消费这套布局，建得出但不增加分析能力。 |
| `metadata.property.sub.group.batch` | `/turbo_engine/api/v2/datamanageconfig/conf_event_property_sub_group/batch_save/` | 不做 | 同上，是批量 UI 子分组配置。 |
| `metadata.property.sub.group.update` | `/turbo_engine/api/v2/datamanageconfig/conf_event_property_sub_group/save/` | 不做 | 同上，是单项 UI 子分组配置。 |
| `metadata.event.event.property.batch` | `/turbo_engine/api/v2/event/event_property_batch_delete/` | 不做 | 真正批删 App 事件属性，但现有 stable 目录没有 owner/marker，候选族也没有受治理 create；无法满足 owner gate。 |
| `metadata.event.user.property.import` | `/turbo_engine/api/v2/event/user_property/import/` | 不做 | multipart XLSX 导入会创建属性；候选族没有可验证 owner 的清理 route，生产验证会留下垃圾对象。 |

同一当前 bundle 还含 Census 没提取到的事件/用户属性 create/edit/relation/delete 调用点；原因是 alias
baseURL 静态解析边界。它们不是这 9 条已登记候选，且未完成 route census、owner 与响应合同，故没有
绕过治理直接接入。Census 同前缀另有已登记 draft
`GET /event/property_template/use_template/`：前端语义是“按模板创建事件”，不是读取模板；它会产生
事件对象且本线没有事件 owner/清理链，因此不晋升。master/event-member/property-member 三条 list
route 早已 stable，本轮直接用于 owner、preimage 和写后读回，不重复新增 operation。维度表
`event_dim` 家族按产品裁决完全不在本轮范围。

生产闭环使用 App 27018426 的 event property 源 ID 2573861：创建分配模板 ID 121075、模板成员 ID
669697，并以 `GSDK-6c612a3c1f78` round-trip。源目录 ID 与模板成员 ID 不相等，create/append 因而按
稳定 metadata `name` 校验效果，remove 改收精确 `member_ids`。成员删除读回空集合，master 软删后
完整目录确认 ID 消失，最终零残留。首次 create 后读回命中了 10 分钟 metadata cache 的旧 preimage；
共享 mutation client 现只在成功写后清空 metadata cache，保证所有既有写产品的 delete guard 都读取
上游当前状态。生产 HTTP 为 24/25，全部 200、attempt 1、retry=false；完整逐请求账本见
[路线图当前章节](roadmap.md#事件属性元数据模板治理-crud2026-08-16)。

新增 4 条 stable mutation、4 张 action-qualified 产品卡和 1 条已闭环动线：operation
`226 + 4 = 230`，stable `217 + 4 = 221 = 185 read + 36 mutation`，产品卡 `77 + 4 = 81`，selector
`312 + 4 operation + 4 product = 320`，动线 `53 = 45 / 1 / 7` → `54 = 46 / 1 / 7`。

## 2026-08-16 追加判定：保存分析 CRUD

`analysis.report_config.update` 一条物理 route 承载三种动作：create 无 `id/is_deleted`，update 带 `id`
且无 `is_deleted`，delete 带 `id/is_deleted=true`；`config` 始终为 JSON string，删除回送当前完整定义。
生产观察五类 detail 外层 shape 同构而内层 config fingerprint 不同，所以登记一个带 subject 的 operation，
但受治理产品只接受已有 strict compiler 的 event/funnel/retention/scatter/user-property 五类。
cash/order/user 本租户无样本，保持未开放而不是猜测 config；share 与 v3 conftemplate 不在范围。

事件分析的 create/list/get/update/readback/replay/delete/final-list 全部真实发出并 HTTP 200，更新把
`calculateBody.group_by_list` 从 1 项改为 0 项，删除后 marker matches 为 0。owner 实测字段为
`create_user_id`，闸门等式是 `create_user_id == gravity_id`；仅在未来出现单对象 creator 时接受
`creator.id == gravity_id`。list/get 都不是 metadata-cacheable operation，成功写又会清共享 metadata
cache，delete guard 因此读取完整新列表。重放响应的真实聚合数字未在验收脚本异常前持久化，故新增
资产动线暂记部分闭环；请求实际 41/40，发现后停止且清理已完成。完整 shape/fingerprint/receipt 见
[`20260816_saved_analysis_crud.json`](../evidence/forensics/20260816_saved_analysis_crud.json)。

本线新增 1 条 stable mutation、3 张 action-qualified 产品卡：operation `230 + 1 = 231`，stable
`221 + 1 = 222 = 185 read + 37 mutation`，产品卡 `81 + 3 = 84`，selector
`320 + 1 operation + 3 product = 324`，动线 `54 = 46 / 1 / 7` → `55 = 46 / 2 / 7`。

## 2026-08-17 追加判定：保存分析重放证据与离线合同

精确 GET 的现有 `analysis_event` 保存对象以原样 config 通过 strict compiler，在显式窗口
`2026-06-01..2026-06-07` 执行 `analysis.event.query`，HTTP 200，governed response 的
`/result/data/list/0/0/list/0/阶段总和` 为 **235176.0**。完整值只写入
[`20260817_saved_analysis_replay.json`](../evidence/forensics/20260817_saved_analysis_replay.json)，四张最终 HTTP
receipt 仍为 value-free v1。该证据补齐上一轮 CRUD 生命周期唯一缺口，动线从
`55 = 46 / 2 / 7` 转为 `55 = 47 / 1 / 7`；operation、stable、产品卡与 selector 不变。

离线 compiler 的生产路径测试使用真实 client/runtime/transport，并以计数且触网即抛的底层 session 证明
HTTP 为 0；返回合同明确列出执行期可能需要的 event 与 event-property metadata。detached `df12f5e` 上
运行当前同一测试，Saved surface 实际返回空依赖并在完整依赖断言失败；下钻后的 client collector 也会在
第一项 event 处停止，而最终执行 receipt 实际观察到两项。Dashboard、Saved Analysis 与 Analysis Template
共用同一传播路径，不把此修复限定在 saved replay。

## 2026-08-17 追加判定：受治理语义组合首个切片

这不是新增 route candidate。组合层复用 stable `report.multidim.metric.list` 与
`report.multidim.query`，所以 operation/stable 保持 `231/222`。机器定义
`report.ap-cost-observation@1` 只登记生产验证成立的一个指标、一个维度、三个可执行粒度和一个
many-to-one embedded join；hour 只作为已登记但与该指标冲突的粒度，用于发网前拒绝。

固定 App 29034827 与 `2026-06-01..2026-07-10` 的生产结论如下：

| 组合 | 结果 | 合同裁决 |
| --- | --- | --- |
| `ap_cost` / total / `click_company` | `bytedance = 10857257.59` | 维度与 join 可冻结；只允许陈述该 App/窗口/粒度的返回观察值。 |
| `ap_cost` / day | 40 个非空日行，首尾为 `225988.82` / `122530.94` | day 可冻结；可在同一结果内按返回日期比较。 |
| `ap_cost` / week | 6 行：`2713799.09, 2208883.51, 1682448.66, 1317221.50, 2000062.82, 934842.01` | week 可冻结；日期键分别为 06-01、06-08、06-15、06-22、06-29、07-06。 |
| `click_company=bytedance` filter | `EQUALS` 与既有 CLI 映射 `IN` 均 HTTP 200 但产品 `INPUT_INVALID` | 不登记过滤器；不能因物理字段存在就声称其过滤语义可用。 |

最终三组都带同一 definition fingerprint
`e9ac825a4563a8c6c00f6147d55d23daf4a18cd8d85415a0caa6afa4e6971798`。编译前未知成员、禁止 join、
hour 粒度分别以 0 次上游调用失败；执行错误的 filter 结果发布 `allowed_claims=[]`。生产 HTTP 为
20/25，全部 HTTP 200、attempt 1、retry=false、page 1；无翻页、重试或扩窗。新增 1 张 canonical
产品卡，故产品卡 `88→89`、selector `328→329`，并新增 1 条闭环动线；不新增 SQL 或第二套 registry。

## 2026-08-17 追加判定：过滤 wire 与语义定义 v2

本判定不推翻上节的 v1 历史事实。完整 JS 证明当前 adreport body 直接携带
`filters:[{field,operator,values}]`；`click_company` 由 `ad_platform_list` 编译为 `IN`，而 option 表明确
`label=巨量引擎, value=bytedance`。因此上一轮 `bytedance` 值形态没有错，corrected `IN` 仍失败的
已证差异是没有同时选中 `data_dims=[click_company]`。

| 候选 | 静态/生产证据 | v2 裁决 |
| --- | --- | --- |
| `click_company IN` | 同一 App/窗口下 unfiltered grouped total 为 bytedance `10857257.59`；无 dimension 时 `INPUT_INVALID`，带 click dimension 时仍为 `10857257.59`；改为 tencent 后 success empty/total 0 | 登记，但 filter 必须与 click dimension 和 embedded join 同时出现 |
| `advertiser_id IN` | JS 会构造该 item；实际返回的非零内部 ID 在带 advertiser dimension 时仍 `INPUT_INVALID` | 不登记；脱敏响应不足以区分依赖、权限或维度规则 |
| `adclick_standard_activate_cnt` | live metric metadata；day 40 行、week 6 行、total 单独失败 | day/week |
| `adclick_standard_pay_amount` | live metric metadata；day 40 行、week 6 行、total 单独失败 | day/week |
| `adclick_total_roi` | live metric metadata；day 40 行、week 6 行、total 单独失败 | day/week |

新增 `report.ap-cost-observation@2`，fingerprint
`7273eb90dab433099b6a1f883cdef9c88626cae77c6d0dc83b7ea6516a50e461`；v1 文件与 fingerprint
`e9ac825a4563a8c6c00f6147d55d23daf4a18cd8d85415a0caa6afa4e6971798` 保持不变。真实 v2
activate/day/filter 链返回 40 行（首尾 `18195/13100`）和非空 claims。生产 HTTP 21/25；其中
metric catalog 的 page 2-5 是已计入预算的误续页，之后停止，无重试/扩窗。operation、产品卡、selector、
动线计数均不变。

## 2026-08-17 追加判定：语义定义 v3 成员扩容

`report.ap-cost-observation@3` 保持 v1/v2 不变，以 fingerprint
`3f13b18e35cc2216e3d29b299adf82e71b11aeaf62c9722171fa0073d04bb694` 登记 13 个成员：继承 v2 的
4 个成员，并增加 `ap_show/ap_click/ap_click_rate/ap_convert/ap_activate`、
`adclick_standard_activate_cost/adclick_standard_pay_uv/adclick_ad_amount/total_revenue`。新成员逐项已有
day/week 非空实测，且逐项 total 均 `INPUT_INVALID`，故只登记 day/week；只有继承的 `ap_cost` 保留 total。
`adclick_standard_register_cnt` 的 day/week 都明确空、total 又失败，未登记，也没有为已知空路径再发请求。

维度/过滤器证据明确分层：`ap_show`、activate cost、pay users、total revenue 均以
`data_dims=[click_company] + click_company IN [bytedance]` 实测成功，各 40 行；其余成员只在同 catalog
族、相同非排斥 metadata 与同一前端 request profile 内外推。新增 9 个成员中 4 个为实测、其余 5 个
为外推；平台通用外推边界为
`ap_show → ap_click/ap_click_rate/ap_convert/ap_activate`，收入外推边界为
`total_revenue → adclick_ad_amount`；不把外推写成逐成员生产实测。

三条 v3 semantic 组合分别返回：`ap_show/day/bytedance` 40 行（首尾 `3236865/2194246`）、
activate cost/week 6 行（`14.64/11.86`）、total revenue/day/bytedance 40 行
（`86673.69/17860.98`），均携带 scoped `observed-metric-value` 与 `within-result-comparison`。真实
v1/v2/v3 definition version 和 fingerprint 两两不同；unknown member、禁止 join、new metric + total
三类 v3 输入仍在 0 次网络下拒绝。operation/stable、产品卡、selector、动线均保持
`231/222/89/329` 与 `56 = 48 / 1 / 7`。

另记录但不在本线修复分页合同：上一轮 9 个无维度 day 查询在显式 bounded 读取中，page 2--5 均逐行
重复 page 1 的 40 个日行。每次 projected `page_info` 只有 `total=40`，没有合同声明的 `total_page`；
operation 却登记 `page_info/total_page_field=total_page/max_page_size=100`。因此不能说 `total_page` 报了
某个数，它实际缺失；分页层在预算耗尽前重复请求同一数据。

## 2026-08-17 追加判定：分页真实性与语义定义 v4

本轮以同一 App/窗口/结构化输入重新取得可复核证据：`report.multidim.query` 的 page 1 与 page 2
各返回 40 行且行指纹相同，`page_info` 精确只有整数 `total`；把 page_size 从 100 改为 10 仍返回
40 行。因此该 route 是单响应 + reported total，不是合同原先声称的 `total_page` 分页。operation
已改成 `pagination.kind=none`；既有 page/page_size wire 字段保留但明确不控制结果，`read_all` 只发一次
query。完整性只在单响应行数等于 `page_info.total` 时成立，不再虚构 `has_more`。

新增不可变 `report.ap-cost-observation@4`（fingerprint
`aae2b2916ec567dc5c74a626ab18d1c04af9efaf2101b6da890d876ab5ca7503`），成员、粒度、
dimension/filter/join 与 v3 相同，只收窄
结果声明：canonical 编译 bytes 仍确定；执行结果只代表 `result.query.fetched_at` 时点。同一结构化输入
跨执行不保证相同数值；跨执行只能降级为分别带时间戳的观察与算术差，不得称为确定性重放、稳定、
已结算或因果变化。原 6.00 差异的成因仍未知；有界复测还发现 2026-06-01 这个旧日期相对较晚的旧观察
再次增加 185.00，故不能把波动限于近期日期，也没有证据给出 T+N 稳定窗。一个 `ap_show` 对照在短采样
内稳定不足以证明只有收入指标变化，三收入指标又不满足简单二分量求和，因此不填写回填/结算猜测。

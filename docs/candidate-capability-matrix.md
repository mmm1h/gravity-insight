# 候选能力证据矩阵

本矩阵记录 17 项候选能力在 2026-08-12 受控只读探测后的真实状态，并原位追加 2026-08-14 至
2026-08-16 的后续取证结论，供开发决策使用。仓库当前基线为
[223 个 operation、其中 214 个 stable operation](capability-coverage.md)：184 条 stable read 加
30 条逐项治理的 mutation（7 条 Segment、5 条报表/订阅、18 条 Kanban）；写 operation 不是本矩阵的 read candidate，
但本页追加其解锁读合同的生产证据。

`analysis.default_val.list`、D35、F40、`report.report.list/detail` 与 `report.subscribe.list` 已晋升，其余候选
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
| `analysis.realtime_event.list` | `draft`（租户级明确空） | 2026-08-16 对 catalog 的 7/7 个可绑定 App 各发 1 次最小请求，均 HTTP 200 明确空；0 个失败或未试 App，无重试、翻页或扩窗。 | `empty_sample`、`pagination_unverified`、`response_item_schema_unverified` | 由另一个有实时事件数据的租户在同一最短当天窗口取得 1 个非空 item；当前租户不再重复枚举。 |
| `analysis.setting.query` | `draft`（mutation 负向证明；查询动线已由既有产品覆盖） | 对本 mutation 仍为 0 次请求；完整 Dashboard builder 证明该 POST 提交 `config/name/remark`，随后修改 dashboard layout 并提示修改成功。2026-08-15 对 375/375 hash-matched bundle 的 987 条唯一 route 穷尽复核，另确认 `analysis.dashboard.tree/detail` 与 `analysis.report_config.list/get` 四条既有 stable GET 是装载设置的真读；仅对 stable `report_config.list` 做 1 次最小第一页 probe，HTTP 200 非空，无重试或翻页。 | `mutation_route_not_read`、`unregistered_fields_fail_closed`；不再有独立产品缺口 | 本 draft 永不晋升为 read。调用方分别使用既有 `dashboard_snapshot` 与 `saved_analysis`；若提出超出二者的新设置问题，先取得自由文本 config 与人员字段的合同证据，登记后全部暴露；未登记时只按合同漂移 fail-closed，不等待隐私裁决。 |
| `report.masterkey_report_group.list` | `draft`（账号级明确空） | 2026-08-16 最小第一页 HTTP 200 空。固定 path/body 无 App 输入，认证上下文只含账号/公司，因此 App 枚举不适用；既有 read confirmation 与分页证据保留。 | `empty_sample`、`successful_probe` | 由有 MasterKey 报表的账号取得 1 个非空 item；当前账号不重复请求。 |
| `report.report.list` | **`stable v1`（已晋升）** | 先 dry-run，再由 `report.report.update` 创建唯一 marker-owned 测试报表；列表非空读回并登记 14 个观察字段。请求仍为账号级 `{page,page_size,filters}`，完整分页合同沿用 hash-matched bundle。 | 无开放 promotion blocker。 | 由 `report_directory` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。 |
| `report.report.detail` | **`stable v1`（已晋升）** | 使用同次列表内存父 ID 发 1 次 GET detail；14 个观察字段全部登记，`remark` 的 marker 与列表原样 round-trip。 | 无开放 promotion blocker。 | 只接受 `report.report.list` 返回的精确 ID；目录产品有界并发 fan-out。 |
| `report.shared_to_me.list` | `draft`（账号级明确空） | 2026-08-16 最小第一页 HTTP 200 空。固定 path/body 无 App 输入，认证上下文只含账号/公司；既有 read confirmation 保留。 | `empty_sample`、`response_schema_unverified` | 由有共享项的账号取得 1 个非空 item。 |
| `report.subscribe.list` | **`stable v1`（已晋升）** | 先创建 marker-owned v3 父报表，再创建 disabled、`send_way=[]`、无收件人的订阅；列表非空读回并登记 23 个观察字段。请求仍为账号级 `{page,page_size,filters}`；删除后列表确认空。 | 无开放 promotion blocker；`subscribe/test` 明确未调用。 | 由 `report_subscriptions` Core/CLI/SDK/Plan/Agent 消费；未知新增字段继续 additive drift fail-closed。 |
| `report.media_report.list` | `draft`（租户级明确空） | 2026-08-16 用当天窗口、无平台筛选、`page_size=1` 对 catalog 的 7/7 App 各发 1 次；均 HTTP 200 空，0 个失败或未试 App。 | `empty_sample`、`response_schema_unverified` | 由另一个有媒体报表的租户复用同形状取得 1 个非空 item；当前租户不再重复枚举。 |
| `app.project.list` | `draft`（账号级明确空） | 2026-08-16 唯一一次最小第一页 POST 为 HTTP 200 空。固定 path/body 只有筛选与分页，无 App 输入，认证上下文只含账号/公司；App 枚举不适用。 | `empty_sample`、`response_schema_unverified` | 由具备可读项目的账号取得 1 个非空 item。 |
| `app.project_auth.detail` | `draft` | 1 次稳定父请求、0 次目标请求；父资源返回空候选，子请求未发送；无目标样本，分页未验证；父绑定未解析。 | `parent_resource_required`、`probe_inconclusive`、`response_schema_unverified` | 由 `analysis.account_user.list` 提供 1 个可读候选，仅以内存传给 1 次目标请求；没有父候选时继续跳过。 |
| `app.onelink.list` | `draft` | 共 5 次请求，其中父资源 2 次、目标 3 次；父绑定已解析且值仅在内存使用；目标 HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证。 | `empty_sample`、`response_schema_unverified` | 复用已证明的稳定父绑定取得 1 个非空目标样本，再审查 item schema；无需扩大父资源搜索范围。 |
| `app.monetization_app.list` | `draft` | 本轮 0 次请求；沿用既有空样本；草案声明 `page_info`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 先证明账户与变现平台参数的可信来源，再以第一页最小请求取得 1 个非空样本；不得猜测账户或平台值。 |
| `app.app_info.get` | `draft` | 本轮 0 次请求；沿用既有空样本；分页为 `none`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 从已存在的前端调用证据获得 1 个真实且可公开处理的 URL 绑定，再做 1 次最小读取并审查返回字段。 |
| `app.user_auth.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读授权记录的环境取得 1 个非空样本，并重点审查权限、身份和个人信息字段，默认不暴露未知字段。 |
| `attribution.attribution.query` | `stable v1`（D35 已闭环） | hash-matched `Measurement` bundle 完整证明 14 个恒发字段、`project_id/dims_metrics_list` 两条条件省略、八个恒发筛选数组和四个有限调用画像。生产 1 次 App catalog + 2 次单日目标 POST：首 App 明确空，第二 App 非空后停止；均 HTTP 200，无重试、翻页或扩窗。 | 无 promotion blocker；旧 evidence 未保存具体 error 正文，不能追认字段拒绝。新证据证明 `extra.error=无数据` 是 `code=0/msg=成功` 的明确空。 | 由 Core/CLI/SDK/Plan/Agent `attribution_performance` 消费；未知 semantic error 继续 fail-closed。 |

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

- **(a) 租户确实为空：2 条。** `report.media_report.list` 与
  `analysis.realtime_event.list` 均枚举 7/7 App 后仍空。
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
| 查找可用的媒体报表 | **明确空 / item schema 阻塞** | Bundle 已恢复 `AppSelect` 与有限平台选项绑定，空选择省略；列表装载、分页和响应消费证明 read，confirmation 已登记。本轮当天最小请求 HTTP 200、明确空。 | 在有媒体报表的租户复用同形状取得 1 个非空 item，不猜 App 或平台值。 |
| 查找当前账号可读的 App 项目 | **合同阻塞** | `app.project.list` 被读语义闸门拦截；旧空 receipt 虽证明分页壳，但 `method_verified=false`，不能排除请求合同或语义问题，也就不能定为数据阻塞。 | 分析 `appManageIndex-DCdX2wdf.js` 的列表装载与响应消费，登记静态读证据后做 1 次最小第一页 probe。 |
| 查看 App 的 OneLink 与公开信息绑定 | **合同阻塞** | `app.onelink.list` 是 GET，稳定父绑定、分页和重复空目标已证明，当前账号没有可供下钻的 OneLink 项；但 `app.app_info.get` 虽也是 GET，历史 probe 使用的 URL 没有可信 caller 绑定，响应合同也未证实。组合动线仍卡合同。 | 从 appManage bundle 恢复 `fetch_app_info` 的 URL 来源与有效值约束，再用调用方提供的公开测试 URL 做 1 次最小 GET。 |
| 按平台、广告位和日期汇总变现结果（D28） | **合同阻塞** | `app.monetization_app.list` 被读语义闸门拦截；`account/monetization_platform` 的来源和值域未绑定，旧空 receipt 不能证明请求有效，且非空 item schema 未成立。 | 分析 csj/tobid bundle 中 account 与平台的来源和列表消费；形成 read confirmation 后才做 1 次 `page=1/page_size=1` probe。 |

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

`analysis.monetization_detail.list` 保持 stable 且未改 wire，本轮 0 次网络请求。已批准投影由产品层
固定 fields allowlist、`re_attribute_info` 嵌套 allowlist 和逐结果重建强制；未知字段默认隐藏，
用户/设备字段不能经参数、Plan binding、Agent 卡、产品 raw 结果或错误收据打开。Core/CLI/SDK/Plan/Agent
card 已闭环，原自然语言固定 gap 仅对批准形状解除。D28 聚合未实现，`app.monetization_app.list`
仍是独立 draft，其账户绑定与非空响应 blocker 不因 D27 关闭。

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
## 2026-08-16 追加判定：设置入口与 D28 当前配置 route

本轮以引力自然页面动作识别真实入口，再用现有只读 SDK 对 D28 做有界反证。App 页面取得非空；
F41 页面明确空；D28 在目标上限 8 次前停于 7 次。没有 write、重试、扩窗、换 App、模板修改或
主结果 route 补发，也没有把静态字段候选登记为响应合同。

| 动线 | 判定 | 实测证据 | 产品结论 / 下一步 |
| --- | --- | --- | --- |
| 查找当前账号可读的 App 项目 | **已闭环；旧候选不是目标端点** | 设置 → 应用管理自然发出 `GET /turbo_engine/api/v1/user/open_app/list/`，HTTP 200、首屏 7 行。观察 17 个 item 字段和 4 个 `page_info` 字段，键与类型均已由既有 stable `app.list` v4 全量登记；raw schema fingerprint 为 `a4a2bf907a0e45f47de2656f0354c766850c2c06460b1008477664b5d14d3491`。 | J39 改由 `app.list` 的 CLI/SDK/Plan/Agent 卡承载；不晋升、改写或冒充账号级明确空的 `app.project.list`。两 route 分别是 open-app GET 与 project POST，不是同一个端点。 |
| 按表名或 App 查询数据表当前 schema、字段和版本（F41） | **租户当前明确空；保持缺失** | 设置 → 元数据自然发出 `POST /turbo_engine/api/v2/event_dim/data_table/list/`，body 为 `app_id_list=[]/name_like=""/page=1/page_size=10`；HTTP 200，`data.list=[]`，`page_info` 可见，fingerprint `6135b90704b9718bb844941db7a86a9a19037bfa269c6f822e4ca5fa67ea4341`。 | 没有表名或 `table_id` 父值，detail/version 0 次；不能证明 item schema、“当前版本”或 CRUD 读回语义。维度表 CRUD 目前没有安全执行与验证前提。只有租户出现自然表项或 API owner 给出合同后才值得重探。 |
| 按平台、广告位和日期汇总变现结果（D28） | **三选一：请求参数/路由不对；仍未闭环** | 当前 `NewReportCenter` 用 `/turbo_engine/api/v3/confmetric/metric/list/` 和同命名空间 permission route，并以 `data_topic EQUALS monetization_report`、`is_media EQUALS false|true` 取配置。现有 stable operation 仍指向旧 `/report/api/v3/confmetric/metric/list/`。7 次旧 route 均 HTTP 200：1 次错误 `IN` 语义拒绝；一次空 filter 调用自动读 5 页、200/1124 行无目标 topic；1 次当前正确 filter 仍被旧 route 语义拒绝。 | 判据是**同一当前 bundle 的 route 与现有请求不一致，且正确 filter 在旧 route 仍失败**。这不能判定租户没数据，也不能判定权限未生效；permission、主结果、非空 item/total 和值域均未知。下一步应先单次验证当前 turbo config/permission，再用其真实物理字段自然触发主结果；不得继续在旧 route 换参数。 |

三条目标尝试为 `App 1 / F41 1 / D28 7`；连同页面自然触发的 7 次辅助业务读取，实际生产业务
HTTP 共 16 次，全部在全局 40 次上限内。逐请求账本与辅助/目标边界见[路线图当前章节](roadmap.md#设置应用元数据与变现报表复核2026-08-16)。
J39 从完全缺失转已闭环，台账由 `52 = 43 / 1 / 8` 变为 **`52 = 44 / 1 / 7`**；F41 与 D28
保持完全缺失。operation/stable 仍为 223/214；canonical 产品卡仍 45，精确 gap 为 9。

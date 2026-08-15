# 候选能力证据矩阵

本矩阵记录 17 项候选能力在 2026-08-12 受控只读探测后的真实状态，并原位追加后续取证结论，供开发决策使用。2026-08-16 D35 晋升后，仓库为 186 个 operation、其中 177 个 stable operation；其余 16 个候选仍保持 draft。

D35 是唯一已晋升项；`analysis.setting.query` 保留在 draft 台账但 `effect=mutation`，其余候选仍是 read draft，promotion gate 均未满足。表中的“下一步最小证据”表示继续判断所需的最小输入，不代表晋升计划或交付承诺。后续在线验证仍须遵循[探测规范](maintainers/probing.md)，保持只读、限流、值不落盘和 fail-closed。

## 逐项状态

| Operation | Status | 本轮请求、样本、分页与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `analysis.default_val.list` | `draft`（部分证明） | 本轮 1 次目标请求；完整前端 builder 与 HTTP 200 语义成功空响应共同证明 body 为 caller-bound `app_id` + 固定 `$lib_version`，分页 `none`；既有非空样本只观察到 `data.api[]`、`data.cocoscreator[]` 为 string，前端按动态字典消费。 | `dynamic_key_projection_unapproved`、`successful_confirmation_required` | 在同一最小 App/同形状下取得另一个非空样本；随后批准有界 SDK-family key 投影。动态 `{dynamic_key}` 未批准前继续全隐藏。 |
| `analysis.setting.query` | `draft`（mutation 负向证明；查询动线已由既有产品覆盖） | 对本 mutation 仍为 0 次请求；完整 Dashboard builder 证明该 POST 提交 `config/name/remark`，随后修改 dashboard layout 并提示修改成功。2026-08-15 对 375/375 hash-matched bundle 的 987 条唯一 route 穷尽复核，另确认 `analysis.dashboard.tree/detail` 与 `analysis.report_config.list/get` 四条既有 stable GET 是装载设置的真读；仅对 stable `report_config.list` 做 1 次最小第一页 probe，HTTP 200 非空，无重试或翻页。 | `mutation_route_not_read`、`unregistered_fields_fail_closed`；不再有独立产品缺口 | 本 draft 永不晋升为 read。调用方分别使用既有 `dashboard_snapshot` 与 `saved_analysis`；若提出超出二者的新设置问题，先取得自由文本 config 与人员字段的合同证据，登记后全部暴露；未登记时只按合同漂移 fail-closed，不等待隐私裁决。 |
| `analysis.realtime_event.list` | `draft`（部分证明） | 本轮 1 次目标请求；完整 builder 与 HTTP 200 语义成功空 `data.list` 证明顶层 `app_id/filters/page/page_size/request_time` 及 7 个 filter 键；无 `page_info`，未翻页。 | `empty_sample`、`pagination_unverified`、`response_item_schema_unverified` | 同一最短当天窗口、第一页、`page_size=1` 取得 1 个非空 item；单独证明服务端分页。`client_id/request_id/request_ip/raw_properties` 已获字段投影裁决，但其类型和 `raw_properties` 子结构仍须非空样本。 |
| `analysis.setting.query` | `draft`（mutation 负向证明；查询动线已由既有产品覆盖） | 对本 mutation 仍为 0 次请求；完整 Dashboard builder 证明该 POST 提交 `config/name/remark`，随后修改 dashboard layout 并提示修改成功。2026-08-15 对 375/375 hash-matched bundle 的 987 条唯一 route 穷尽复核，另确认 `analysis.dashboard.tree/detail` 与 `analysis.report_config.list/get` 四条既有 stable GET 是装载设置的真读；仅对 stable `report_config.list` 做 1 次最小第一页 probe，HTTP 200 非空，无重试或翻页。 | `mutation_route_not_read`、`unregistered_fields_fail_closed`；不再有独立产品缺口 | 本 draft 永不晋升为 read。调用方分别使用既有 `dashboard_snapshot` 与 `saved_analysis`；若提出超出二者的新设置问题，先取得自由文本 config 与人员字段的合同证据，登记后全部暴露；未登记时只按合同漂移 fail-closed，不等待隐私裁决。 |
| `report.masterkey_report_group.list` | `draft`（读合同已确认） | 本轮 1 次、累计 4 次目标请求；本次最小第一页 HTTP 200、明确空。Bundle 的列表装载/分页/响应消费已登记为 read confirmation；既有第二页和安全页上限证据保留。 | `empty_sample`、`successful_probe` | 在相同最小当天窗口取得 1 个非空列表样本，用于证明 item schema；不扩大时间范围寻找数据。 |
| `report.report.list` | `draft`（读合同已确认） | 本轮 1 次、累计 4 次目标请求；本次最小第一页 HTTP 200、明确空。已存报表 bundle 证明列表装载、分页、`list` 消费，删除走独立 update 路由。 | `empty_sample`、`response_schema_unverified` | 在有自有报表的租户取得 1 个非空 item，并仅审查实际字段。 |
| `report.report.detail` | `draft` | 0 次请求；本轮 `report.report.list` 仍为空，按约定跳过；分页为 `none`，前置资源未解析。 | `empty_sample`、`response_schema_unverified` | 先从同批列表得到 1 个可读候选，再仅以内存传入 1 次 detail 请求；随后审查 detail 字段，不持久化父值。 |
| `report.shared_to_me.list` | `draft`（读合同已确认） | 本轮 1 次、累计 4 次目标请求；本次最小第一页 HTTP 200、明确空。Bundle 将响应 `list` 合并进共享指标目录并本地分页，写操作另有路由。 | `empty_sample`、`response_schema_unverified` | 在有共享项的租户取得 1 个非空 item，再做最小投影与隐私审查。 |
| `report.subscribe.list` | `draft`（读合同已确认） | 本轮唯一 1 次 `page=1/page_size=1` 请求；HTTP 200、明确空，只观察到 `list` 空壳与 `page_info`，未翻页。Prober 已按精确 confirmation 放行，稳定 Registry 不变。 | `empty_sample`、`field_review_required`、`pagination_unverified`、`response_schema_unverified` | 在有订阅项的租户复用同形状取得 1 个非空 item；未知订阅字段保持隐藏，再按需单独验证第二页。 |
| `report.media_report.list` | `draft`（读合同与绑定已确认） | 本轮 1 次、累计 4 次目标请求；当天、无 App/平台筛选、第一页 HTTP 200、明确空。Bundle 证明 `AppSelect`/有限平台选项绑定，空选择省略；既有分页证据保留。 | `empty_sample`、`response_schema_unverified` | 在有媒体报表的租户复用同形状取得 1 个非空 item；不得猜测 App 或平台值。 |
| `app.project.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读项目的授权环境取得 1 个非空样本，并审查 item 字段的权限与隐私含义。 |
| `app.project_auth.detail` | `draft` | 1 次稳定父请求、0 次目标请求；父资源返回空候选，子请求未发送；无目标样本，分页未验证；父绑定未解析。 | `parent_resource_required`、`probe_inconclusive`、`response_schema_unverified` | 由 `analysis.account_user.list` 提供 1 个可读候选，仅以内存传给 1 次目标请求；没有父候选时继续跳过。 |
| `app.onelink.list` | `draft` | 共 5 次请求，其中父资源 2 次、目标 3 次；父绑定已解析且值仅在内存使用；目标 HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证。 | `empty_sample`、`response_schema_unverified` | 复用已证明的稳定父绑定取得 1 个非空目标样本，再审查 item schema；无需扩大父资源搜索范围。 |
| `app.monetization_app.list` | `draft` | 本轮 0 次请求；沿用既有空样本；草案声明 `page_info`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 先证明账户与变现平台参数的可信来源，再以第一页最小请求取得 1 个非空样本；不得猜测账户或平台值。 |
| `app.app_info.get` | `draft` | 本轮 0 次请求；沿用既有空样本；分页为 `none`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 从已存在的前端调用证据获得 1 个真实且可公开处理的 URL 绑定，再做 1 次最小读取并审查返回字段。 |
| `app.user_auth.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读授权记录的环境取得 1 个非空样本，并重点审查权限、身份和个人信息字段，默认不暴露未知字段。 |
| `attribution.attribution.query` | `stable v1`（D35 已闭环） | hash-matched `Measurement` bundle 完整证明 14 个恒发字段、`project_id/dims_metrics_list` 两条条件省略、八个恒发筛选数组和四个有限调用画像。生产 1 次 App catalog + 2 次单日目标 POST：首 App 明确空，第二 App 非空后停止；均 HTTP 200，无重试、翻页或扩窗。 | 无 promotion blocker；旧 evidence 未保存具体 error 正文，不能追认字段拒绝。新证据证明 `extra.error=无数据` 是 `code=0/msg=成功` 的明确空。 | 由 Core/CLI/SDK/Plan/Agent `attribution_performance` 消费；未知 semantic error 继续 fail-closed。 |

| `attribution.attribution_detail.query` | `draft`（F40 静态绑定已证明） | hash-matched Device/userSearch 控制流证明父目录 `data.list[].id` 由调用方选择，详情 body 为 `{app_id,device_id:Number(id)}`，分页 `none`；前端消费 `device_white/attribution_list/postback_list/pay_list`。本轮没有用户级目录枚举授权，目标请求 0 次。 | `authorized_identifier_required`、`parent_contract_unverified`、`response_schema_unverified` | 调用方授权一个真实登记测试设备父行 id，只发 1 次详情请求；成功或明确空后登记四个容器全部观察字段与类型。 |

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

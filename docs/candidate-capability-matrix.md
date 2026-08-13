# 候选能力证据矩阵

本矩阵记录 17 项候选能力在 2026-08-12 受控只读探测后的真实状态，供后续开发决策使用。仓库基线仍为 [185 个 operation、其中 176 个 stable operation](capability-coverage.md)；本轮没有新增 stable operation，基线数量未变化。

所有候选项当前均为 `draft`，且 promotion gate 均未满足。表中的“下一步最小证据”表示继续判断所需的最小输入，不代表晋升计划或交付承诺。后续在线验证仍须遵循[探测规范](maintainers/probing.md)，保持只读、限流、值不落盘和 fail-closed。

## 逐项状态

| Operation | Status | 本轮请求、样本、分页与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `analysis.default_val.list` | `draft` | 1 次目标请求；HTTP 200、非空，结论 `inconclusive`；分页为 `none` 且已确认；无父绑定。 | `request_parameters_required`、`response_schema_unverified` | 将本轮成功的最小请求形状固化为值无关合同，解决动态占位与字面量的歧义；再做 1 次同形状确认，并完成响应投影与隐私审查。 |
| `analysis.realtime_event.list` | `draft` | 1 次目标请求；HTTP 200 但为 `semantic_error`，无可用样本；分页未验证；无父绑定。 | `request_parameters_required`、`response_schema_unverified` | 从现有前端消费证据确认必需字段、类型和空值语义，再做 1 次最小成功请求；不得通过扩大参数组合猜测合同。 |
| `analysis.setting.query` | `draft` | 本轮 0 次请求；沿用既有 `semantic_error` 证据，无可用样本；分页为 `none`，本轮未复核；无父绑定。 | `request_parameters_required`、`response_schema_unverified` | 先获得配置、空间和报表相关字段的完整值无关请求形状，并明确必需项；自由文本字段继续 fail-closed，再做 1 次最小成功请求。 |
| `report.masterkey_report_group.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample` | 在相同最小日期窗口和第一页条件下取得 1 个非空列表样本，用于证明 item schema；不扩大时间范围寻找数据。 |
| `report.report.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 取得 1 个非空列表样本，并仅对实际观察到的 item 字段做投影与隐私审查。 |
| `report.report.detail` | `draft` | 0 次请求；同批 `report.report.list` 为空，按约定跳过；沿用既有空样本；分页为 `none`，本轮未复核；前置资源未解析。 | `empty_sample`、`response_schema_unverified` | 先从同批列表得到 1 个可读候选，再仅以内存传入 1 次 detail 请求；随后审查 detail 字段，不持久化父值。 |
| `report.shared_to_me.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 取得 1 个非空共享报表样本，确认 item schema 后再做最小投影和隐私审查。 |
| `report.subscribe.list` | `draft` | 0 次网络请求；本地只读策略拒绝当前路由，结论 `local_or_parent_inconclusive`；无样本，分页未验证；无父绑定。 | `pagination_unverified`、`probe_inconclusive`、`response_schema_unverified` | 先取得权威的只读语义和请求合同证据，使受控运行时可安全放行；之后仅需 1 次第一页最小请求，再按需要验证第二页。 |
| `report.media_report.list` | `draft` | 本轮 0 次请求；沿用既有空样本；草案声明 `page_info`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 先证明应用与广告平台参数的可信绑定，再用最小日期窗口取得 1 个非空样本；不得使用猜测的平台值。 |
| `app.project.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读项目的授权环境取得 1 个非空样本，并审查 item 字段的权限与隐私含义。 |
| `app.project_auth.detail` | `draft` | 1 次稳定父请求、0 次目标请求；父资源返回空候选，子请求未发送；无目标样本，分页未验证；父绑定未解析。 | `parent_resource_required`、`probe_inconclusive`、`response_schema_unverified` | 由 `analysis.account_user.list` 提供 1 个可读候选，仅以内存传给 1 次目标请求；没有父候选时继续跳过。 |
| `app.onelink.list` | `draft` | 共 5 次请求，其中父资源 2 次、目标 3 次；父绑定已解析且值仅在内存使用；目标 HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证。 | `empty_sample`、`response_schema_unverified` | 复用已证明的稳定父绑定取得 1 个非空目标样本，再审查 item schema；无需扩大父资源搜索范围。 |
| `app.monetization_app.list` | `draft` | 本轮 0 次请求；沿用既有空样本；草案声明 `page_info`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 先证明账户与变现平台参数的可信来源，再以第一页最小请求取得 1 个非空样本；不得猜测账户或平台值。 |
| `app.app_info.get` | `draft` | 本轮 0 次请求；沿用既有空样本；分页为 `none`，本轮未复核；无父绑定。 | `empty_sample`、`response_schema_unverified` | 从已存在的前端调用证据获得 1 个真实且可公开处理的 URL 绑定，再做 1 次最小读取并审查返回字段。 |
| `app.user_auth.list` | `draft` | 3 次目标请求；HTTP 200、空样本；`page_info`、第二页行为和安全页上限已验证；无父绑定。 | `empty_sample`、`response_schema_unverified` | 在具备可读授权记录的环境取得 1 个非空样本，并重点审查权限、身份和个人信息字段，默认不暴露未知字段。 |
| `attribution.attribution.query` | `draft` | 本轮 0 次请求；沿用既有 `semantic_error` 证据，无可用样本；分页为 `none`，本轮未复核；无父绑定。 | `request_parameters_required`、`response_schema_unverified` | 先取得可复核的现有调用方或同一 census 快照对应的 bundle 正文，且证据须包含请求构造、默认值和条件省略逻辑，以唯一证明完整 POST body 的全部字段名、JSON 类型、必填性及 `null`/空数组/空字符串语义；若只有脱敏浏览器网络记录，还须补充空值与省略规则证据。当前 `route-params` 的 2 个 load call 均未解析、`body_parameters` 为空，且仓库无 bundle 正文或调用方；补齐前保持 0 次请求且不做组合猜测。 |

| `attribution.attribution_detail.query` | `draft` | 本轮 0 次请求，且无既有 live probe；无样本，分页未验证；无父绑定。 | `not_probed`、`pagination_unverified`、`request_binding_unverified`、`response_schema_unverified` | 必须先取得经批准的测试级标识来源、完整请求绑定和隐私边界；不得使用任意用户级设备标识。证据不足时保持不探测。 |

## 2026-08-13 追加判定：无标识变现明细（D27）

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
`advertiser_name` 判为敏感并隐藏；未知字段暴露数为 0。

**下一步最小证据：**

- Bilibili：stable advertiser 在同一单日第一页条件下返回 1 个 `advertiser_id`，
  之后才能逐层证明 `campaign_id → unit_id → creative_id` 的键、类型、分页与父绑定。
- Huya：先取得非空 account 候选；更关键的是需要前端控制流或上游合同，
  证明 report 请求如何绑定 `advertiser_id/campaign_id/group_id`——当前三个 report body
  **都没有这些父字段**。

**未决**：Bilibili account 已返回 `advertiser_id`，但 campaign 草稿声明的父资源是 advertiser report，
两者是否等价**不能推断**；Bilibili manager 三层的 `data.list` 与分页仍未在线证明。

## 本轮可复用结论

- Agent 固定产品按 owner 正向证据强度与 selector 精确度集中裁决；命中多个 authoritative 产品时返回
  `MULTIPLE_INTENTS` 与候选 selector，候选为空且禁止 raw operation fallback。7 对已知重叠均以
  owner recognizer 离线复现该行为，公共 Agent/Plan/card envelope 未变。
- 六个列表操作已得到可复用的 `page_info` 分页证据：`report.masterkey_report_group.list`、`report.report.list`、`report.shared_to_me.list`、`app.project.list`、`app.user_auth.list`、`app.onelink.list`。
- `app.onelink.list` 的稳定父绑定链路已被证明可用，但空样本仍不足以证明目标 item schema。
- `analysis.default_val.list` 是本轮唯一非空候选响应；当前证据仍不足以关闭请求合同和响应投影 blocker。
- 其余候选保持 fail-closed：空样本不证明字段、业务语义错误不证明请求合同、父资源为空不触发子请求、用户级标识无批准来源时不探测。

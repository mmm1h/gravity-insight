# 候选能力证据矩阵

本矩阵记录 17 项候选能力在 2026-08-12 受控只读探测后的真实状态，并原位追加后续取证结论，供开发决策使用。仓库基线仍为 [185 个 operation、其中 176 个 stable operation](capability-coverage.md)；本轮没有新增 stable operation，基线数量未变化。

所有候选项仍未晋升；`analysis.setting.query` 保留在 draft 台账但 `effect=mutation`，其余候选仍是 read draft，promotion gate 均未满足。表中的“下一步最小证据”表示继续判断所需的最小输入，不代表晋升计划或交付承诺。后续在线验证仍须遵循[探测规范](maintainers/probing.md)，保持只读、限流、值不落盘和 fail-closed。

## 逐项状态

| Operation | Status | 本轮请求、样本、分页与父绑定 | 精确 blocker | 下一步最小证据 |
| --- | --- | --- | --- | --- |
| `analysis.default_val.list` | `draft`（部分证明） | 本轮 1 次目标请求；完整前端 builder 与 HTTP 200 语义成功空响应共同证明 body 为 caller-bound `app_id` + 固定 `$lib_version`，分页 `none`；既有非空样本只观察到 `data.api[]`、`data.cocoscreator[]` 为 string，前端按动态字典消费。 | `dynamic_key_projection_unapproved`、`successful_confirmation_required` | 在同一最小 App/同形状下取得另一个非空样本；随后批准有界 SDK-family key 投影。动态 `{dynamic_key}` 未批准前继续全隐藏。 |
| `analysis.realtime_event.list` | `draft`（部分证明） | 本轮 1 次目标请求；完整 builder 与 HTTP 200 语义成功空 `data.list` 证明顶层 `app_id/filters/page/page_size/request_time` 及 7 个 filter 键；无 `page_info`，未翻页。 | `empty_sample`、`pagination_unverified`、`response_item_schema_unverified`、`privacy_projection_approval_required` | 同一最短当天窗口、第一页、`page_size=1` 取得 1 个非空 item；单独证明服务端分页。静态候选 `client_id/request_id/request_ip/raw_properties` 未获隐私投影批准。 |
| `analysis.setting.query` | `draft`（mutation 负向证明） | 本轮 0 次请求；完整 Dashboard builder 证明该 POST 在修改图表时提交 `config/name/remark` 等字段，成功后继续改 dashboard layout 并提示修改成功；合同 `effect=mutation`，probe 在 transport 前拒绝。 | `mutation_route_not_read`、`free_text_fail_closed` | 原查询动线须找到另一条可证明只读的 route；本 route 属 mutation，在线 probe 被禁止，批准 mutation 也不能替代读取合同。 |
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
- 隐私：本轮空响应没有观察到敏感字段值；静态 item 消费候选 `client_id`、`request_id`、
  `request_ip`、`raw_properties` 仅登记字段名并保持隐藏，需单独投影批准。setting 的
  `name/remark/config` 未发送、未投影。

`analysis.default_val.list` 的旧非空响应确实证明 `data.api[]` 与 `data.cocoscreator[]` 为 string，
完整前端消费还证明 `data` 被当作动态字典、value 被按数组消费；它不能证明 key 的闭集或未观察 value 的类型，
也没有形成获批的动态 key 投影。本轮同形状空响应只能确认请求可用，不能确认 item 投影。
因此三条均未晋升：总 operation 仍为 185，stable 仍为 176。

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
| 隐私 | 本轮空列表只证明响应壳，不证明 item 隐私。没有观察到需要新批准的字段；复用的 Bilibili account 中 `advertiser_name` 已按既有 stable 投影隐藏 |
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
- 其余候选保持 fail-closed：空样本不证明字段、业务语义错误不证明请求合同、父资源为空不触发子请求、用户级标识无批准来源时不探测。

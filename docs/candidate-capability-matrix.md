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
| `attribution.attribution.query` | `draft` | 本轮 0 次请求；沿用既有 `semantic_error` 证据，无可用样本；分页为 `none`，本轮未复核；无父绑定。 | `request_parameters_required`、`response_schema_unverified` | 先从现有调用方或前端证据还原完整请求 body 合同，再做 1 次最小成功请求；没有请求合同前不做组合猜测。 |
| `attribution.attribution_detail.query` | `draft` | 本轮 0 次请求，且无既有 live probe；无样本，分页未验证；无父绑定。 | `not_probed`、`pagination_unverified`、`request_binding_unverified`、`response_schema_unverified` | 必须先取得经批准的测试级标识来源、完整请求绑定和隐私边界；不得使用任意用户级设备标识。证据不足时保持不探测。 |

## 本轮可复用结论

- 六个列表操作已得到可复用的 `page_info` 分页证据：`report.masterkey_report_group.list`、`report.report.list`、`report.shared_to_me.list`、`app.project.list`、`app.user_auth.list`、`app.onelink.list`。
- `app.onelink.list` 的稳定父绑定链路已被证明可用，但空样本仍不足以证明目标 item schema。
- `analysis.default_val.list` 是本轮唯一非空候选响应；当前证据仍不足以关闭请求合同和响应投影 blocker。
- 其余候选保持 fail-closed：空样本不证明字段、业务语义错误不证明请求合同、父资源为空不触发子请求、用户级标识无批准来源时不探测。

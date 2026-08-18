# 跨层不变量：请求的组/身份必须在响应里看得见

- 日期：2026-08-19
- 任务：#222
- 结论：可执行读合同现在必须证明「调用方请求的组/身份，投影后还能看见」；检查按响应形状走，不按 operation_id 手写名单。现网可执行合同无新违反例，生产读 0 次。

## 可判定定义

「调用方请求的组/身份」指下面三类之一。每一类都能从合同或请求字段机械判定，不是口号。

| 种类 | 请求里出现了什么 | 响应里必须还能看见什么 | 不算 |
| --- | --- | --- | --- |
| 分析属性分维 | 可执行读声明了 `group_by_list`（`item_type=object` 且 `max_items` 空或 >0） | 该 route 必须落在已知聚合形状上，并且该形状已有组标签开口 | 时间桶 `create_time/day`、图表辅助 `union_groups`/`y`、行内 `uid`/`group_cols` |
| 报表/归因维度轴 | 可执行读声明了 `dims_list` 或 `data_dims`（字符串数组，`max_items` 空或 >0） | 该轴必须绑进 `dynamic_item_fields` / `data_dynamic_item_fields`，或封闭 `item_enum` 的每个值都在投影键里 | 指标轴 `metrics_list`、未验证 draft |
| 身份别名 | 投影同时暴露 `gravity_<id>` | 同容器必须同时投影真实 `<id>` | 恒 0 的死字段本身（那是家族 D，用 `unreliable_item_keys`） |

导航层的 `next` 被信封通用文案覆盖属于同一家族画像，但是 `#216` 的范围，本趟不碰。

## 已修四到六例：请求 / 本该留下 / 丢掉的层

| 例 | 请求 | 上游给了、响应本该看见 | 丢掉的层 | 本趟范围 |
| --- | --- | --- | --- | --- |
| 1 `#206` 漏斗 OS 键 | `group_by_list` 含 `$os` | `aggregate_date.group.android` / `null` | 投影 allowlist | 是 |
| 2 `#209` 素材 `material_id` | 素材报表行身份 | 同页 `material_id`（19 位字符串） | 投影未登记 | 是（身份别名规则） |
| 3 `#209` 投放 `total` 数组 | 分维求和 | `data.total[0].stat_cost` 进审计 | 审计形状假设 | 否（审计已修；本趟不改审计） |
| 4 `#215` 事件/scatter 组标签 | `group_by_list` 含 `$os` | 行上 `用户.设备类型`、格子 `user$os` | 投影 | 是 |
| 5 Plan `fetch_strategy` | 分页器写出 `single_page` 等 | Plan `_safe_page.fetch_strategy` | Plan 投影曾只认死名 `single`/`serial`/`parallel` | **划出本不变量**。现码已认真实枚举（`plan_multidim_result.py`）。产品信封 `composite_result._safe_page` 仍不投影该字段，那是产品信封选择，不是组/身份 |
| 6 分页 ContextVar | 已知 `total_page` 后并行翻页 | `receipt.request_count` = 实际 HTTP 次数 | 工作线程看不到父线程 ContextVar | **划出本不变量**。现码 `pagination._submit_window` 已调用 `bind_request_counter()`。这是计数完整性，不是组/身份 |

第 5、6 条是 `#220` 家族 A 的历史成员，但不是「请求的组/身份」。本趟不把它们写进这条不变量，避免检查变成「响应里所有键都要留下」。

## 不变量怎么管到还没写的 route

加载 `OperationSpec` 时跑 `validate_group_identity_invariant`。判定键是**响应形状和输入轴**，不是 operation_id 名单。

- 新 route 若带可分维 `group_by_list`，却没有 `list+target_list` / `aggregate_date+window_funnel_mode` / `aggregate_date+zone_tags` / `total+date_to_week` / `list+target` 这五种已知指纹之一：加载红。
- 新 route 若指纹已匹配：执行器按形状走动态聚合投影，不必再往 `executor.py` 登记 id。测试用虚构 `analysis.future.query` 证明。
- 新形状必须同时登记指纹和样本开口；开口必须能让 `allowed_analysis_response_key` 放行样本标签，否则仍红。这是唯一需要手工登记的点，登记本身有门禁。
- 可执行读的 `dims_list`/`data_dims`、以及 `gravity_*` 身份别名，对全部合同自动生效。未验证 draft（`executable=false`）允许先声明维度轴，因为投影尚未取证。

因此：明年第 238 条若是「又能分维、形状又已知」的分析查询，检查自动管到它。若它发明了第六种聚合树，检查先红，逼作者写出开口，而不是静默走 list-row allowlist。

## 没有用「什么都投影」换绿

`uid` / `group_cols` / `union_groups` / `y` 仍挡住。开口只在明确容器路径上、对明确标识形状生效，沿用 `#215`。

## 立完检查后有没有正在违反

对全部已编译可执行合同跑过：0 条违反。对 catalog 加载的 draft：2 条有未绑定 `data_dims`（`report.adreport.query`、`report.report_monetization_report_custom_get.calc_total`），它们本就 `executable=false`、投影未取证，按上面的 draft 豁免不挡加载。

没有发现第七例。覆盖得到：可执行读的组/身份合同。覆盖不到：导航 `next`（`#216`）、Plan 产品信封是否投影 `fetch_strategy`、HTTP 计数 ContextVar。

生产读 0 次。

## 测试红→绿

故意把 `validate_group_identity_invariant` 做成空函数后：

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_unknown_groupable_analysis_shape_is_rejected` | `ManifestError not raised` | 未知聚合形状拒绝加载 |
| `test_unbound_dimension_axis_is_rejected` | `ManifestError not raised` | 未绑定 `dims_list` 拒绝加载 |
| `test_gravity_alias_without_real_identifier_is_rejected` | `ManifestError not raised` | 只有 `gravity_material_id`、没有 `material_id` 拒绝加载 |

恢复检查后上述三条与其余六条均绿。`test_new_event_shaped_route_uses_dynamic_aggregate_without_id_registration` 证明新同形 route 不必手写 id。`test_registered_shape_without_opening_is_rejected` 证明登记形状但开口失效仍红。

## 推测 / 确凿

确凿：现网 237 条已编译合同满足不变量；动态聚合投影不再按五个死名分发；`executor.py` AST 4797→4686，五个 analysis query 字面量从该文件清零。

推测：下一次家族 A 若出现，更可能是「第六种分析聚合树」或「又一个产品信封的 `_safe_page`」，而不是再漏掉现有五种形状的组标签。

## 没做

- 不碰 gap/`next`、宿主臂、错误 `actual`、`client.py`/`cache.py`。
- 不改评测、不跑 holdout/final、不打生产。
- 不动 `docs/roadmap.md`。不 push、不碰 GitHub。

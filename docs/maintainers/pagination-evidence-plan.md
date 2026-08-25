# 分页生产证据采集计划

本页是生产证据的执行清单，不是执行记录，也不授权登录、Probe 或 HTTP。当前基线为
`dev@b7c15ed`：237 个 operation 中 177 个 `completeness=unknown`，其中 stable 为 168 个；stable
`page_info` unknown 实际为 58 个，不是 59 个。机器复核将 unknown 分为 `85 collect / 83 no-new-signal`
与 `9 non-stable`；83 条是 47 个非集合与 36 个当前无可证伪信号。输入来自
`D:/git-pjt/tmp/arch-batch-2026-08-20/contract-audit.json`，并逐条与当前
`src/gravity_sdk/contracts/operations/` 对账。

## 优先级与收益

| 顺序 | 采集动作 | 同一上下文内的目标 | 最多可降低 | 最少目标 HTTP |
| --- | --- | ---: | ---: | ---: |
| P0 | 一个具备合法父项的 evidence App，先父后子采集分析、素材、报表、归因和 App 读 | 59 | 59 | 59 |
| P1 | 同一 evidence App 的已绑定推广平台，按平台复用日期窗和账号上下文 | 26 | 26 | 26 |
| 不采 | 非集合语义或已证实没有可用终止信号 | 83 | 0 | 0 |

85 个待采 operation 的 exact `method + path` 全部唯一，所以一个目标响应不能同时证明两个合同；上表的
“一次”是一次受控采集批次，不是一条 HTTP。可以复用的是 App、日期窗和父项发现：例如
`analysis.segment.list` 自己的响应既是分页证据，也可提供后续 segment operation 的合法父项。父项调用
只有在它本身列于目标表时才计入降低数。

收益是上限，不是承诺。权限拒绝、语义错误、空响应或缺少终止字段都不能升级证据；如果响应证明上游
没有可用总数/终止信号，应转入“永久 unknown”，而不是重试、换 App、扩窗或启用满页启发式。

## 统一采集协议

所有值只从获批 evidence App 和表内 parent operation 的合法输出取得；不猜 ID，不把 App ID、用户标识、
原始行、token 或 Cookie 写入证据。记录 exact operation、method/path、合同指纹、请求页码/页大小、响应
字段路径与标量类型、列表返回数、脱敏协议状态和 response-sketch 指纹。

对表中 `page_info` operation：

1. 用表内业务必填输入，加合同的 `page=1`、`page_size=1`。记录 `data.list` 返回数，以及
   `data.page_info` 中 `page`、`page_size`、`total`、`total_number`、`total_page`、`has_more` 的逐键
   存在性、标量类型和值；未出现的键也要显式记录。唯一例外是
   `analysis.segment.history_version.list`，其合同 `page_info_path=data`，同样记录上述键。
2. 若 `total_page` 是正整数，在不扩大日期窗/筛选条件的前提下直接请求该最后页，保持相同
   `page_size`；记录回显页码、最后页返回数、总数和 `total_page` 是否与第一页一致。
3. 只有在安全上限 `max_pages=20`、`max_items=5000` 内才能做完整翻页复核。降为 `complete` 的必要条件是
   最后一页 `page=total_page`、SDK 得出 `has_more=false`，且全部页 `returned_items` 之和等于同一响应
   协议中的 `total` 或 `total_number`。`total_page` 缺失、总数缺失/变化、页码不前进或触及上限时保持
   `unknown` 或本次结果为 `prefix`。

对表中 `none` operation：调用一次当前合同，不人为补分页参数；记录实际 collection path、返回数，以及
任意 `page_info`、`total`、`total_number`、`total_page`、`has_more` 的存在性和类型。只有 wire/production
同时给出可证伪的全集信号才另行修正合同；短页、空页、HTTP 200 和 `returned_items=reported_total` 本身
都不能证明完整。没有终止信号时将该 operation 转入永久 `unknown`。

## P0：App 内核心批次（最多 59）

需要一个获批的只读 evidence App，并预先确认表中 parent source 能返回合法父项。含敏感输入的
`client_id`、`device_id`、订单 trace 等只在内存中绑定，证据仅记“由哪个 parent 字段取得”。

| operation | kind / 当前证据 | 必填业务输入 | parent source |
| --- | --- | --- | --- |
| `analysis.dashboard.condition_favourite.list` | `page_info` / `template` | app_id, filters | analysis.dashboard.detail |
| `analysis.dashboard.members.list` | `none` / `template` | app_id, dashboard_id | analysis.dashboard.detail |
| `analysis.dashboard.space_members.list` | `none` / `template` | app_id, space_id | analysis.dashboard.tree |
| `analysis.event_property_group.list` | `none` / `template` | app_id | app.list |
| `analysis.event_property_value.list` | `none` / `template` | app_id, event_name_list, property_name | analysis.event.info, analysis.event.list, app.list |
| `analysis.event_property.list` | `page_info` / `template` | app_id | app.list |
| `analysis.event.query` | `none` / `template` | app_id, date_list, query_id, query_item_list | analysis.event.list |
| `analysis.funnel.query` | `none` / `template` | app_id, date_list, query_id, query_item_list, stat_time_window | analysis.event.list |
| `analysis.monetization_detail.list` | `page_info` / `wire` | app_id, date, fields | app.list |
| `analysis.order_detail.list` | `page_info` / `template` | app_id | app.list |
| `analysis.order_split_detail.list` | `none` / `template` | app_id, client_id, pay_event_time, split_trace_ids, trace_id | analysis.order_detail.list |
| `analysis.property.query` | `none` / `template` | app_id, query_id, query_item | analysis.user_property.list |
| `analysis.report.hidden_property.list` | `none` / `template` | app_id, report_id | analysis.report_config.list, app.list |
| `analysis.retention.query` | `none` / `template` | app_id, date_list, query_id, query_item_list | analysis.event.list |
| `analysis.scatter.query` | `none` / `template` | app_id, date_list, query_id, query_item_list | analysis.event.list |
| `analysis.segment.history_version.list` | `page_info` / `template` | segment_id | analysis.segment.list |
| `analysis.segment.list` | `page_info` / `template` | app_id | app.list |
| `analysis.segment.uid_result.list` | `page_info` / `template` | date, segment_id | analysis.segment.list |
| `analysis.segment.user_detail.list` | `none` / `template` | app_id, segment_id | analysis.segment.list |
| `analysis.task.other_event.list` | `page_info` / `template` | app_id | app.list |
| `analysis.task.pay_event.list` | `page_info` / `template` | app_id | app.list |
| `analysis.template.internal.list` | `page_info` / `wire` | none | none |
| `analysis.template.own.list` | `page_info` / `wire` | none | none |
| `analysis.template.share.list` | `page_info` / `wire` | none | none |
| `analysis.template.subject.internal.list` | `none` / `template` | none | none |
| `analysis.template.subject.own.list` | `none` / `template` | none | none |
| `analysis.template.subject.share.list` | `none` / `template` | none | none |
| `analysis.user_detail.list` | `page_info` / `wire` | app_id | app.list |
| `analysis.user_event.list` | `none` / `template` | app_id, client_id | analysis.user_detail.list |
| `analysis.user_postback_log.list` | `none` / `template` | app_id, client_id | analysis.user_detail.list |
| `analysis.user_property_value.list` | `none` / `template` | app_id, property_name | analysis.user_property.list, app.list |
| `analysis.user_property.list` | `page_info` / `template` | app_id | app.list |
| `app.testing_tool.list` | `page_info` / `template` | app_id | app.list |
| `attribution.attr_backtrack.list` | `none` / `template` | app_id | app.list |
| `attribution.attr_impress_click.list` | `none` / `template` | app_id | app.list |
| `attribution.attribution_detail.query` | `none` / `template` | app_id, device_id | app.testing_tool.list |
| `attribution.post_backtrack.list` | `none` / `template` | app_id | app.list |
| `attribution.postback_map_collect.list` | `page_info` / `template` | app_id | app.list |
| `attribution.postback_map.list` | `page_info` / `template` | app_id | app.list |
| `attribution.postback_mode.list` | `none` / `template` | app_id | app.list |
| `attribution.reattribution.list` | `none` / `template` | app_id | app.list |
| `material.bytedance_asset_material.list` | `page_info` / `production` | advertiser_id | promotion.bytedance.account.list |
| `material.bytedance.list` | `page_info` / `wire` | advertiser_id | promotion.bytedance.advertiser.list |
| `material.favorites.list` | `page_info` / `template` | none | none |
| `material.local.list` | `page_info` / `production` | none | none |
| `material.recycle.list` | `page_info` / `template` | none | none |
| `material.review.list` | `page_info` / `template` | none | none |
| `material.tag_category.list` | `page_info` / `template` | none | none |
| `material.tag.list` | `page_info` / `template` | none | none |
| `material.tencent.list` | `page_info` / `wire` | advertiser_id | promotion.tencent.advertiser.list |
| `report.business.metric.list` | `none` / `template` | none | none |
| `report.multidim.calc_total` | `none` / `template` | date_list, metrics_list, time_dims | report.multidim.query |
| `report.multidim.custom_metric.list` | `page_info` / `template` | none | none |
| `report.multidim.metric_tag_category.list` | `page_info` / `template` | none | none |
| `report.multidim.metric_tag.list` | `page_info` / `template` | none | none |
| `report.multidim.template.mine.list` | `page_info` / `template` | none | none |
| `report.multidim.template.preset.list` | `page_info` / `template` | none | none |
| `report.multidim.template.shared.list` | `page_info` / `template` | none | none |
| `report.multidim.template.tree` | `none` / `template` | none | none |

## P1：推广平台批次（最多 26）

只对同一 evidence App 已合法绑定的平台执行；没有绑定的平台保持待办，不换 App 寻找非空。`date_list`
使用一次获批的最小单日窗并在本批复用。无业务必填字段仍要按统一协议显式传 `page=1/page_size=1`。

| operation | kind / 当前证据 | 必填业务输入 | parent source |
| --- | --- | --- | --- |
| `promotion.alipay.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.baidu.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.bing.advertiser.list` | `page_info` / `template` | none | none |
| `promotion.bytedance.project.list` | `page_info` / `template` | date_list | none |
| `promotion.honor.ad_group.list` | `page_info` / `template` | date_list | none |
| `promotion.honor.campaign.list` | `page_info` / `template` | date_list | none |
| `promotion.huya.account.list` | `page_info` / `template` | none | none |
| `promotion.huya.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.kuaishou.ad_unit.list` | `page_info` / `template` | date_list | none |
| `promotion.oppo.account.list` | `page_info` / `template` | none | none |
| `promotion.qihu360.account.list` | `page_info` / `template` | none | none |
| `promotion.qihu360.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.sigmob.account.list` | `page_info` / `template` | none | none |
| `promotion.sigmob.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.taptap.group.list` | `page_info` / `template` | date_list | none |
| `promotion.ubix.account.list` | `page_info` / `template` | none | none |
| `promotion.ubix.group.list` | `page_info` / `template` | date_list | none |
| `promotion.vivo.account.list` | `page_info` / `template` | none | none |
| `promotion.wechat_video.report.list` | `page_info` / `template` | date_list | none |
| `promotion.weibo.account.list` | `page_info` / `template` | none | none |
| `promotion.xiaohongshu.advertiser.list` | `page_info` / `template` | none | none |
| `promotion.xiaohongshu.developer.list` | `page_info` / `template` | media_type | none |
| `promotion.xiaomi.account.list` | `page_info` / `template` | none | none |
| `promotion.xiaomi.advertiser.list` | `page_info` / `template` | date_list | none |
| `promotion.youdao.account.list` | `page_info` / `template` | none | none |
| `promotion.youdao.advertiser.list` | `page_info` / `template` | date_list | none |

## 永久 unknown：不再采集（83）

下列结论只表示“在当前上游合同与完整性模型下没有可用的分页降债动作”。只有 exact method+path 的新
wire/production 合同出现总数或终止信号时才重开；重复采短页、空页或相同 response sketch 不重开。

- `not_collection_semantics`（47）：这些是 9 个 detail/scalar 或 38 个 mutation，不属于集合分页证据待办。新增
  `analysis.segment.evaluate_percent`：响应严格为 `part`/`percent`/`total` 三个必需顶层数值标量，根本无集合语义，
  故从 P0 移入本节；判据要求全部 data key 均为必需数值标量，任一 item/list/nested/dynamic 投影即 fail-closed。尤其 38 个
  mutation 只能走产品自有 dry-run/execute，绝不能为分页取证走 read probe：
  `analysis.dashboard.condition_favourite.default_to_me.get`, `analysis.dashboard.detail`,
  `analysis.dataanalysis.segment.update`,
  `analysis.datamanageconfig.kanban.dashboard.copy`, `analysis.datamanageconfig.kanban.dashboard.create`,
  `analysis.datamanageconfig.kanban.dashboard.dc7858a7.update`,
  `analysis.datamanageconfig.kanban.dashboard.delete`, `analysis.datamanageconfig.kanban.dashboard.move`,
  `analysis.datamanageconfig.kanban.dashboard.update`, `analysis.datamanageconfig.kanban.folder.create`,
  `analysis.datamanageconfig.kanban.folder.delete`, `analysis.datamanageconfig.kanban.folder.move`,
  `analysis.datamanageconfig.kanban.folder.update`, `analysis.datamanageconfig.kanban.note.update`,
  `analysis.datamanageconfig.kanban.space.create`, `analysis.datamanageconfig.kanban.space.delete`,
  `analysis.datamanageconfig.kanban.space.move`, `analysis.datamanageconfig.kanban.space.update`,
  `analysis.engine.datamanageconfig.kanban.delete`, `analysis.from.history.version.create`,
  `analysis.from.tmp.segment.create`, `analysis.kanban.dashboard.folder.move`,
  `analysis.kanban.dashboard.order.update`, `analysis.report_config.get`, `analysis.report_config.update`,
  `analysis.segment.by.manual.update`, `analysis.segment.detail`, `analysis.segment.from.analysis.create`,
  `analysis.segment.from.rule.create`, `analysis.segment.from.rule.update`, `app.detail`,
  `app.user.realtime.event.update`, `attribution.attr_click_interval.get`, `material.examine.config.get`,
  `metadata.event.property.template.079c8246.create`, `metadata.event.property.template.create`,
  `metadata.property.template.event.delete`, `metadata.property.template.property.delete`,
  `report.confmetric.custom.metric.8ef6d12d.delete`, `report.confmetric.custom.metric.update`,
  `report.multidim.template.preset.get`, `report.report.update`, `report.subscribe.create`,
  `report.subscribe.delete`, `report.template.create`, `report.template.update`。
- `no_falsifiable_completeness_signal`（36）：`analysis.dashboard.tree` 的静态 list 合同无页输入/终止输出；以下 34 条
  有 exact production observation，但重复一次不能证明服务端不截断，且 `report.get.query` 仅有 `page_info.total`：
  `analysis.dashboard.event_list_info.get`, `analysis.default_val.list`, `analysis.event.info`,
  `analysis.realtime_event.list`, `app.app_info.get`, `app.capacity.get`, `app.permission_menu.list`,
  `app.realtime_event.list`, `app.role.detail`, `attribution.attribution.query`, `material.album.tree`,
  `material.bytedance.project_material.list`, `material.bytedance.promotion_material.list`,
  `material.material_examine_user.list`, `material.metric.list`, `material.tag_category.tree`,
  `material.tencent_medium_creative.list`, `metadata.metrics.get`, `metadata.promotion_gravity_metric.list`,
  `promotion.ai_trusteeship.detail`, `promotion.bytedance.account_company.list`,
  `promotion.bytedance.manager_project.list`, `promotion.bytedance.manager_promotion.list`,
  `promotion.kuaishou.account_company.list`, `promotion.latest_account_status.get`, `promotion.metric.list`,
  `promotion.tencent.account_company.list`, `promotion.tencent.medium_adgroup.list`, `report.get.query`,
  `report.hour_comparison.query`, `report.multidim.media_enum.list`, `report.my_template.detail`,
  `report.overview.query`, `report.report.detail`。`report.multidim.query` 的 shape B 也只有总数而没有 `total_page`，
  维持单响应 `unknown`；这两条静态/shape-B 子类均不得以 `returned_items=reported_total` 提级。

另有 9 个 non-stable/non-executable unknown 不进入生产计划：`account.department.list`,
`analysis.ai.conversation.list`, `analysis.ai.message.list`, `candidate.account.user_operation_log.list`,
`candidate.material.kuaishou.list`, `candidate.material.platform.list`,
`candidate.promotion_object.click_url_edit_log.list`, `candidate.promotion_object.click_url.list`,
`candidate.promotion_object.extra_info.list`。它们只有在先取得独立的稳定性/权限裁决后才能重新排期。

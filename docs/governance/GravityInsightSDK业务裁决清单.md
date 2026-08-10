# Gravity Insight SDK 业务裁决清单

更新日期：2026-08-10。候选字段来自当前
`src/gravity_sdk/contracts/drafts/*.json`；本轮 verdict probe 证据位于
`evidence/probe/`。本文只记录字段名、业务回答和聚合形态统计，不记录
真实取值或值哈希。

## 状态摘要

- **业务问题：2 条已裁决，1 条待回答，0 条待 probe。**
- 已裁决：问题 1 由业务方回答裁决为 sensitive；问题 2 由 value-free probe 裁决为 sensitive。
- 待回答：问题 3 经 probe 收窄后仍缺字段业务语义确认；四字段继续隐藏，未标成 non-sensitive。
- 工程 probe 队列：111 个 `frontend_static_consumer_unreviewed` 候选行，状态未改，不计入上述
  业务问题的待 probe 数。

## 口径

- 当前 draft 中有 115 个 `privacy_classification=manual_review` 候选行：111 个静态候选和问题 3
  的 4 个 observed 字段。问题 2 的 `is_superuser` 已由 manual review 改为 sensitive。
- `advertiser_name` 已在 48 个 operation contract 中保持响应剔除；本次只固化裁决语义，不恢复
  暴露。2026-08-09 的审计文件保留其当时“待业务裁决”的历史状态，本清单和当前契约记录后续裁决。
- 本轮两份 `.yaml` 证据均使用 JSON 语法，只保存计数、基数、范围和模式命中数；不保存原值、
  值哈希或非目标身份字段。

## 已裁决

### 1. `advertiser_name`：广告主名称

- 业务方回答：**是**。
- 回答日期：**2026-08-10**。
- 最终状态：`resolved_by_business_answer`，判定 `sensitive`。
- 裁决来源：**业务 owner 的明确回答**，不是技术形态推断。业务方确认广告主名称中可能出现
  自然人姓名，或没有组织标记的个体工商户。
- 处置：继续按个人信息处理，保持从 SDK 响应中移除。当前 48 个 operation contract 的响应
  剔除状态不变；draft 分类依据已改为 `business_owner_confirmed...` 并记录回答日期。

历史形态证据为 70 个字符串、50 个不同值，长度 10..20，未命中邮箱、手机号、身份证号或
中文姓名形态；该样本不能推翻业务方给出的产品准入事实。

### 2. `is_superuser`：素材审核用户的超级管理员标记

- 业务方回答：**不确定**。
- 回答日期：**2026-08-10**。
- probe 证据：
  [`20260810T022801Z_material.material_examine_user.list.verdict.yaml`](../../evidence/probe/20260810T022801Z_material.material_examine_user.list.verdict.yaml)。
- 最终状态：`resolved_by_probe`，判定 `sensitive_personnel_permission`。
- 处置：从 `manual_review` 改为 `sensitive`，继续从 SDK 响应中移除。

probe 观测到 2 个用户行，`is_superuser` 分布为 **true=1、false=1**，不同布尔值数量为 **2**，
无缺失、null 或其他类型。值在同一响应的不同用户行之间变化，足以证明它不是统一复制的响应级
通用开关，而是随用户记录变化的人员权限属性。证据未保存姓名、邮箱、部门、角色或任一行原值。

## 需要业务方回答

### 3. 腾讯广告组的出价与预算字段

- 业务方回答：**不确定**。
- 回答日期：**2026-08-10**。
- probe 证据：
  [`20260810T022803Z_promotion.tencent.tencent_medium_adgroup.list.verdict.yaml`](../../evidence/probe/20260810T022803Z_promotion.tencent.tencent_medium_adgroup.list.verdict.yaml)。
- 最终状态：`narrowed`。
- 处置：`bid_amount`、`bid_mode`、`daily_budget`、`total_budget` 均继续保持
  `manual_review`、`expose=false`；没有标成 non-sensitive。

probe 只取得 1 个广告组行。`bid_mode` 的取值基数为 **1**，字符串长度为 13，**1/1** 命中
大写常量和枚举 token 形态，空白、多行、邮箱、手机号和身份证形态均命中 0。数值字段范围为：
`bid_amount=300..300`、`daily_budget=1000000..1000000`、`total_budget=0..0`；三者均为 integer，
10 位及以上 ID-like 大整数命中数均为 0。该证据排除了本次观测值中的自由文本和 ID 量级形态，
但单行样本不能证明合法枚举全集，也不能区分“配置金额”和“实际交易明细”的业务语义。

**改写后问题全文：本次 probe 观测到 1 个广告组行；`bid_mode` 有 1 个不同值，其中 1/1 个
观测值符合大写常量形态；三个数值字段范围为 `bid_amount=300..300`、
`daily_budget=1000000..1000000`、`total_budget=0..0`。请确认：`bid_mode` 是否由接口 schema
严格限制为固定合法枚举，并且 `bid_amount`、`daily_budget`、`total_budget` 是否都只表示
广告组配置金额，绝不复用为用户/广告主标识或实际支付、订单、交易明细？**

- 回答“是”，且确认固定枚举与配置金额语义：四字段可进入非敏感技术复核，复核通过后再决定
  是否恢复可见。
- 回答“否”或仍“不确定”：四字段继续保持隐藏，并补充准确字段定义后再审。

## 只需技术 probe 的静态候选

下表完整列出 111 个静态候选行。它们只有前端消费点证据，尚未证明服务端实际返回、类型、
取值形态或隐私属性。下一步是 value-free probe；业务方无需逐项回答。

| Operation | 待 probe 字段路径 |
| --- | --- |
| `analysis.realtime_event.list` | `data.list` |
| `app.app_click_hijacking.list` | `data.list` |
| `app.app_info.get` | `data.image_data` |
| `app.binding_url.get` | `data.data` |
| `app.capacity.get` | `data.capacity.package_total_million`<br>`data.capacity.package_total_million_usage`<br>`data.data.capacity.event_amount_million_usage`<br>`data.data.capacity.package_total_million`<br>`data.data.capacity.package_total_million_usage` |
| `app.identity_white.list` | `data.list` |
| `app.is_template.list` | `data.list` |
| `app.message.detail` | `data.message.content` |
| `app.message.list` | `data.list` |
| `app.onelink.list` | `data.list` |
| `app.project.list` | `data.list[].app_list_info` |
| `app.project_auth.detail` | `data.list` |
| `app.publisher_public.list` | `data.list` |
| `app.role.detail` | `data.data_permission`<br>`data.menu` |
| `app.role.list` | `data.list` |
| `app.sensitive_info.get` | `data.app_key` |
| `app.template.list` | `data.list` |
| `app.testing_tool.list` | `data.list` |
| `app.tutorial_mark.get` | `data.value.report` |
| `app.user_auth.list` | `data.list` |
| `attribution.attribution.query` | `data.items` |
| `attribution.attribution_detail.query` | `data.attribution_list` |
| `material.asset_directional_package_kuaishou.list` | `data.list` |
| `material.asset_directional_package_tencent.list` | `data.list` |
| `material.bilibili_asset_text_title.list` | `data.list` |
| `material.bytedance_asset_material.list` | `data.list` |
| `material.bytedance_promotion_material.list` | `data.list` |
| `material.component.list` | `data.innerIndex`<br>`data.outerIndex` |
| `material.image_text_asset.list` | `data.list` |
| `material.keyword_package.list` | `data.list` |
| `material.kuaishou_asset_title.list` | `data.list` |
| `material.kuaishou_manager_creative.list` | `data.list` |
| `material.material_examine_user.list` | `data.list` |
| `material.material_get.query` | `data.instant_play_material_list`<br>`data.trial_play_material_list`<br>`data.video_material_list` |
| `material.media_material_label.list` | `data.list` |
| `material.monitor.list` | `data.list` |
| `material.oppo_asset_text_title.list` | `data.list` |
| `material.promoted_object_link.list` | `data.list` |
| `material.tencent_asset_text_title.list` | `data.list` |
| `material.tencent_medium_creative.list` | `data.list` |
| `metadata.data_table.detail` | `data.column_list`<br>`data.column_val_list`<br>`data.ordered_column_list` |
| `metadata.metrics.get` | `data.list` |
| `promotion.advertiser_validate.list` | `data.list` |
| `promotion.alipay.agent_sub_account.list` | `data.list` |
| `promotion.baidu.account.list` | `data.list` |
| `promotion.baidu.baidu_feed_plan.list` | `data.list[].campaignFeedId`<br>`data.list[].campaignId` |
| `promotion.baidu.baidu_plan.list` | `data.list[].campaignId` |
| `promotion.bytedance.account_company.list` | `data.list` |
| `promotion.bytedance.aweme_auth.list` | `data.list` |
| `promotion.bytedance.batch_options.query` | `data.result_list` |
| `promotion.bytedance.bytedance_manager_project.list` | `data.list` |
| `promotion.bytedance.bytedance_manager_promotion.list` | `data.list` |
| `promotion.bytedance.extend_package.list` | `data.list` |
| `promotion.bytedance.monitor_activity_link.list` | `data.list` |
| `promotion.bytedance.native_anchor.list` | `data.list` |
| `promotion.bytedance.optimized_goal.get` | `data.asset_ids`<br>`data.goals[].deep_goals` |
| `promotion.bytedance.site_template.list` | `data.list` |
| `promotion.bytedance.stardelivery.list` | `data.list` |
| `promotion.bytedance.std_project.list` | `data.list` |
| `promotion.bytedance.v2.list` | `data.list` |
| `promotion.bytedance.wechat_game.list` | `data.list` |
| `promotion.detail.list` | `data.list` |
| `promotion.honor.campaign_option.list` | `data.list[].adCampaignId` |
| `promotion.huawei_store.adgroup_list.list` | `data.list[].subTaskId` |
| `promotion.huawei_store.campaign.list` | `data.list[].taskId` |
| `promotion.info.list` | `data.list` |
| `promotion.iqiyi.group.list` | `data.list[].orderGroupId` |
| `promotion.iqiyi.plan.list` | `data.list[].orderPlanId` |
| `promotion.kuaishou.account_company.list` | `data.list` |
| `promotion.kuaishou.batch_options.query` | `data.result_list` |
| `promotion.kuaishou.procedural_batch.get` | `data.rule_config.config_data` |
| `promotion.media_directional_package.list` | `data.list` |
| `promotion.oppo.brand.list` | `data.list` |
| `promotion.oppo.oppo_manager_group.list` | `data.list[].adGroupId` |
| `promotion.oppo.oppo_manager_plan.list` | `data.list[].planId` |
| `promotion.oppo.procedural_batch.get` | `data.ad_config.config_data`<br>`data.rule_config.config_data` |
| `promotion.task_adcreate.detail` | `data.commit_info`<br>`data.main_task` |
| `promotion.task_adcreate.list` | `data.list` |
| `promotion.task_adcreate_v2.list` | `data.list` |
| `promotion.task_batch_strategy.detail` | `data.config_data.modules` |
| `promotion.task_batch_strategy.list` | `data.list` |
| `promotion.tencent.account_company.list` | `data.list` |
| `promotion.tencent.ad.list` | `data.list` |
| `promotion.tencent.batch_options.query` | `data.result_list` |
| `promotion.tencent.detail.list` | `data.list` |
| `promotion.tencent.package.list` | `data.list` |
| `report.custom_metric.list` | `data.list` |
| `report.hour_comparison.query` | `data.today`<br>`data.yesterday` |
| `report.my_template.detail` | `data.detail.config.columns`<br>`data.detail.share_list` |
| `report.report_confmetric_permission.list` | `data.list` |
| `report.report_monetization_report_custom_get.calc_total` | `data.list` |
| `report.shared_to_me.list` | `data.list` |
| `report.subscribe.list` | `data.list` |
| `report.user.query` | `data.list` |
| `report.view.query` | `data.list` |

## 回答记录

2026-08-10 已登记业务 owner 对三个原问题的回答：问题 1 为“是”，问题 2、3 为“不确定”。
问题 1、2 已闭环；问题 3 后续只需回答上方改写后的完整问题。不要在本文写入真实广告主名、
人员信息、原始响应、枚举原值、值哈希或其他用户级数据；需要举例时只用虚构或脱敏例子。

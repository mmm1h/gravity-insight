# 自然语言可达性修复后全量回归

## 执行口径与汇总

- 输入仍是 `phrasings.md` 冻结的 47 × 2 条问法，没有改题。
- 94/94 各自完成一次首次 CLI 调用，退出码均为 0，全部 `offline=true`、`network_called=false`；生产 HTTP 请求 0 次。
- 32 条已闭环：baseline `6 / 7 / 19`（双语达标 / 单语达标 / 双语不达标）→ **`32 / 0 / 0`**。
- 回归：原先达标的 19 条语言问法全部仍达标，**0 条从达标变为不达标**。
- 15 条完全缺失：可执行产品结果仍为 **0**，没有发现漏记的已完成能力；但 15/15 现在都由中英自然语言首次调用返回目标动线专属、带明确 next action 的 `capability_gap`，因此 Agent 一面按新判据为“有”。
- `MULTIPLE_INTENTS`：冻结题单中的 94 条都语义明确，修复后没有一条靠 `MULTIPLE_INTENTS` 达标。已有显式双产品冲突回归测试仍保留并通过。

## 32 条已闭环动线 before / after

| ID | 动线 | baseline | 修复后中文首次结果 | 修复后 English 首次结果 | after | 回归 |
| --- | --- | --- | --- | --- | --- | --- |
| J01 | 事件趋势 | 不达标 | `success` → 1 `analysis.query.spec:event` | `success` → 1 `analysis.query.spec:event` | 达标 | 改善 |
| J02 | 转化漏斗 | 部分达标 | `success` → 1 `analysis.query.spec:funnel` | `success` → 1 `analysis.query.spec:funnel` | 达标 | 改善 |
| J03 | 用户留存 | 不达标 | `success` → 1 `analysis.query.spec:retention` | `success` → 1 `analysis.query.spec:retention` | 达标 | 改善 |
| J04 | 属性分布与聚合 | 不达标 | `success` → 1 `analysis.query.spec:property` | `success` → 1 `analysis.query.spec:property` | 达标 | 改善 |
| J05 | 指标散点关系 | 部分达标 | `success` → 1 `analysis.query.spec:scatter` | `success` → 1 `analysis.query.spec:scatter` | 达标 | 改善 |
| J06 | 同定义跨期比较 | 不达标 | `success` → 1 `analysis.query.spec`（period compare） | `success` → 1 `analysis.query.spec`（period compare） | 达标 | 改善 |
| J07 | 人群规则人数与占比 | 不达标 | `success` → 1 `analysis.segment.rule.spec` | `success` → 1 `analysis.segment.rule.spec` | 达标 | 改善 |
| J08 | 分析构造上下文 | 不达标 | `success` → 1 `composite:analysis_context` | `success` → 1 `composite:analysis_context` | 达标 | 改善 |
| J09 | App 治理快照 | 不达标 | `success` → 1 `composite:app_snapshot` | `success` → 1 `composite:app_snapshot` | 达标 | 改善 |
| J10 | App 归因配置快照 | 不达标 | `success` → 1 `composite:attribution_snapshot` | `success` → 1 `composite:attribution_snapshot` | 达标 | 改善 |
| J11 | 单用户画像/事件/回传 | 不达标 | `success` → 1 `composite:user_journey` | `success` → 1 `composite:user_journey` | 达标 | 改善 |
| J12 | 多 App 业务趋势与小时脉搏 | 部分达标 | `success` → 1 `composite:business_pulse` | `success` → 1 `composite:business_pulse` | 达标 | 改善 |
| J13 | 公司资源用量趋势 | 达标 | `success` → 1 `composite:company_usage` | `success` → 1 `composite:company_usage` | 达标 | 保持 |
| J14 | 自定义人群覆盖与状态 | 部分达标 | `success` → 1 `composite:custom_audience` | `success` → 1 `composite:custom_audience` | 达标 | 改善 |
| J15 | 跨平台素材表现 | 不达标 | `success` → 1 `composite:material_performance` | `success` → 1 `composite:material_performance` | 达标 | 改善，伪歧义消除 |
| J16 | 单日无标识订单目录 | 不达标 | `success` → 1 `composite:order_directory` | `success` → 1 `composite:order_directory` | 达标 | 改善 |
| J17 | TraceID 单日拆单追踪 | 部分达标 | `success` → 1 `composite:order_split_trace` | `success` → 1 `composite:order_split_trace` | 达标 | 改善 |
| J18 | 单日无标识变现明细 | 不达标 | `success` → 1 `composite:monetization_detail` | `success` → 1 `composite:monetization_detail` | 达标 | 改善 |
| J19 | workspace 聚合 SQL 产品 | 不达标 | `capability_gap` → `WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` | `capability_gap` → `WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` | 达标 | 改善；当前 worktree 未配置该人名产品，next argv 为 `gravity sql products` |
| J20 | 看板详情、成员和筛选收藏 | 达标 | `success` → 1 `composite:dashboard_snapshot` | `success` → 1 `composite:dashboard_snapshot` | 达标 | 保持 |
| J21 | 看板图表与页面条件重放 | 不达标 | `success` → 1 `composite:dashboard_analysis` | `success` → 1 `composite:dashboard_analysis` | 达标 | 改善，伪歧义消除 |
| J22 | 保存分析重放 | 达标 | `success` → 1 `composite:saved_analysis` | `success` → 1 `composite:saved_analysis` | 达标 | 保持 |
| J23 | 分析模板重放 | 达标 | `success` → 1 `composite:analysis_template` | `success` → 1 `composite:analysis_template` | 达标 | 保持 |
| J24 | 分群详情、版本与单日聚合 | 不达标 | `success` → 1 `composite:segment_snapshot` | `success` → 1 `composite:segment_snapshot` | 达标 | 改善 |
| J25 | 显式物理字段多维报表 | 部分达标 | `success` → 1 `composite:multidim` | `success` → 1 `composite:multidim` | 达标 | 改善 |
| J26 | 平台物理指标推广表现 | 不达标 | `success` → 1 `composite:promotion_performance` | `success` → 1 `composite:promotion_performance` | 达标 | 改善 |
| J27 | B 站账户/产品投放表现 | 达标 | `success` → 1 `composite:bilibili_account_performance` | `success` → 1 `composite:bilibili_account_performance` | 达标 | 保持 |
| J28 | 巨量广告主 profile | 达标 | `success` → 1 `composite:advertiser_profile` | `success` → 1 `composite:advertiser_profile` | 达标 | 保持 |
| J29 | 巨量普通/标准标题包 | 部分达标 | `success` → 1 `composite:title_package` | `success` → 1 `composite:title_package` | 达标 | 改善 |
| J30 | 离线元数据名称查找 | 不达标 | `success` → 1 `metadata:search` | `success` → 1 `metadata:search` | 达标 | 改善；新增 class-level typed handoff，不依赖具体目录行自证 |
| J31 | 已同步表版本与变更观察 | 部分达标 | `success` → 1 `metadata:table_lineage` | `success` → 1 `metadata:table_lineage` | 达标 | 改善 |
| J32 | 素材分析报表导出 | 不达标 | `success` → 1 `export.material.report.start` | `success` → 1 `export.material.report.start` | 达标 | 改善 |

## 15 条完全缺失动线 before / after

| ID | 动线 | baseline | 修复后中文 / English 首次结果 | after Agent 面 | 是否发现可执行结果 |
| --- | --- | --- | --- | --- | --- |
| J33 | 分析默认值字典 | 错 handoff | 两者均 `ANALYSIS_DEFAULT_DICTIONARY_CONTRACT_MISSING` | 有 | 否 |
| J34 | 实时事件目录 | raw operation / generic gap | 两者均 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING` | 有 | 否 |
| J35 | 自有/共享/MasterKey 报表与定义 | generic gap | 两者均 `REPORT_DIRECTORY_ITEM_SCHEMA_MISSING` | 有 | 否 |
| J36 | 报表订阅清单 | raw operation / generic gap | 两者均 `REPORT_SUBSCRIPTION_ITEM_SCHEMA_MISSING` | 有 | 否 |
| J37 | 媒体报表目录 | 错产品 / generic gap | 两者均 `MEDIA_REPORT_ITEM_SCHEMA_MISSING` | 有 | 否 |
| J38 | 当前账号可读 App 项目 | generic gap | 两者均 `APP_PROJECT_ITEM_SCHEMA_MISSING` | 有 | 否 |
| J39 | App OneLink 与公开信息 | generic gap | 两者均 `APP_ONELINK_PUBLIC_BINDING_SAMPLE_MISSING` | 有 | 否 |
| J40 | 变现聚合 | generic gap | 两者均 `MONETIZATION_AGGREGATE_CONTRACT_MISSING` | 有 | 否 |
| J41 | 归因表现聚合 | generic gap | 两者均 `ATTRIBUTION_AGGREGATE_CONTRACT_MISSING` | 有 | 否 |
| J42 | 单用户归因明细 | raw operation / generic gap | 两者均 `USER_ATTRIBUTION_DETAIL_DEPENDENCY_MISSING` | 有 | 否 |
| J43 | 数据表当前 schema/字段/版本 | generic gap / 错产品 | 两者均 `CURRENT_TABLE_SCHEMA_PARENT_MISSING` | 有 | 否 |
| J44 | 非 Bytedance 层级表现 | generic / 相邻产品 gap | 两者均 `NON_BYTEDANCE_HIERARCHY_PARENT_MISSING` | 有 | 否 |
| J45 | 平台专属素材与创意 | 相邻产品 / generic gap | 两者均 `PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING` | 有 | 否 |
| J46 | Analysis 结果导出 | generic gap | 两者均 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING` | 有 | 否 |
| J47 | 平台素材预览/下载 | generic gap | 两者均 `PLATFORM_ASSET_BINARY_CONTRACT_MISSING` | 有 | 否 |

## 防拆墙结论

- baseline 已达标的 J13/J20/J22/J23/J27/J28 双语，以及 J02/J05/J12/J14/J17/J29/J31 的单语，全部保持达标。
- 产品卡均为候选 1，未出现“正确产品排在 raw operation 后面”的退化。
- J15 与 J21 的 baseline `MULTIPLE_INTENTS` 均被证明是 recognizer 伪冲突；修复通过收紧相邻产品的正向证据完成，没有删除负向词、降低 selector 精确度或改成任选一张卡。
- 明确同时请求两个产品的既有 `MULTIPLE_INTENTS` 测试继续通过，裁决语义没有放宽。

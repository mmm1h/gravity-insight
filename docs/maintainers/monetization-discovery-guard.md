# Monetization Detail Product and Discovery Guard

本页定义 D27 完整已登记变现明细的产品边界，以及仍保留在 Agent discovery 前的本地 Guard。
产品复用 stable `analysis.monetization_detail.list`；不修改 wire，不新增 operation，也不覆盖 D28 聚合。

## 产品入口

- CLI：`gravity analysis monetization detail --app <alias|id> --date YYYY-MM-DD`
- SDK：`GravitySDK.monetization_detail(app, date, ...)`
- Plan：`composite` 节点 `name=monetization_detail`，request 只含 `app/date`
- Agent：明确且无冲突的 `monetization details/变现明细` 返回 value-free 卡，调用方再填 App/单日

四个执行入口共用同一个 core：固定 `page_size=100` 完整读取，受 `max_pages/max_items` 约束；direct
可使用有界分页 worker，Plan adapter 固定 1 worker，避免和全局 Plan pool 形成嵌套并发。

## 固定产品投影与 raw 字段控制

固定产品请求完整的 26 个顶层 row fields，含用户、设备、`Name/WXOpenID`、三个 `user$ad_*`
指标、`re_attribute_info` 和 `device_info`。两个嵌套对象分别按 11 个再归因子字段和 14 个设备子字段
重建。未登记字段不会透传，并使结果 fail closed。

raw `analysis.monetization_detail.list` 可选择字段，并可使用 `global_conditions`、`local_conditions`、
`order_by_list` 表达用户或设备维度分析。固定字段组合无需 metadata 请求；其他字段和条件继续读取
live metadata 验证。这是合同正确性机制，不是字段访问控制。

结果 sanitizer 绑定 canonical App、单日、limits、完整分页 receipt、行数与 schema。任何身份、日期、
limits、page 或公开行形状被伪造，都会重建为固定 `contract_changed`，且 data 为空。

## Guard 保留范围

Guard 仍占有明确 Monetization Detail 产品形状和 near-raw selector。固定 App/单日意图返回 composite
卡；字段、筛选、分组或排序意图交给 raw operation discovery，不再返回隐私 gap。其他冲突意图在本地
返回固定 `capability_gap`，safe query 不携带自然语言值。

以下场景继续阻断：

- 否定、导出/下载、写入/修改/删除；
- 跨日、周/月、summary/report/total 或任何聚合意图；
- ROI/收入、看板、订单、素材、推广、Multidim 等相邻产品拼接；
- canonical raw selector 后追加任意自然语言或值。

字段、profile、filter、group、sort、用户、设备、ClientID、TraceID、user_id、device_id、LTV、归因、
广告主和广告位维度不在阻断表中；它们由 raw operation 合同和 metadata 决定是否可执行。

trim 后精确等于 `analysis.monetization_detail.list` 的专家 selector 和精确 export selector 保持原
generic 专家入口；泛 `monetization/变现` 不由本 Guard 独占。

## 证据与非目标

wire 已由既有 stable 合同证明，本单元没有生产 probe。测试覆盖完整字段登记与类型、未知字段
additive fail-closed、request binding、用户字段条件、Agent raw 路由和保留型 gap。D28 按平台、
广告位和日期的聚合仍需要独立账户绑定与合同证据，不从明细结果在 SDK 内派生。

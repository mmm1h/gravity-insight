# Monetization Detail Product and Discovery Guard

本页定义 D27 无标识变现明细的产品边界，以及仍保留在 Agent discovery 前的本地 Guard。
产品复用 stable `analysis.monetization_detail.list`；不修改 wire，不新增 operation，也不覆盖 D28 聚合。

## 产品入口

- CLI：`gravity analysis monetization detail --app <alias|id> --date YYYY-MM-DD`
- SDK：`GravitySDK.monetization_detail(app, date, ...)`
- Plan：`composite` 节点 `name=monetization_detail`，request 只含 `app/date`
- Agent：明确且无冲突的 `monetization details/变现明细` 返回 value-free 卡，调用方再填 App/单日

四个执行入口共用同一个 core：固定 `page_size=100` 完整读取，受 `max_pages/max_items` 约束；direct
可使用有界分页 worker，Plan adapter 固定 1 worker，避免和全局 Plan pool 形成嵌套并发。

## 固定隐私投影

请求 fields 固定为路线图批准的标量字段和 `re_attribute_info`，调用方不能选择字段、profile、filter、
group 或 sort。每行从 allowlist 重新构造；`re_attribute_info` 再从其广告维度 allowlist 单独重建。
未知上游字段默认隐藏，而不是透传或自动登记。

永久排除 `user_id/event_user_id/device_id/ClientID/TraceID/device_info`、三个 `user$ad_*` 指标、
`Name/WXOpenID`。这些键即使上游返回也不会被复制到 public row、total、page、error、next_action 或
receipt；异常和原生错误只映射为固定错误分类与固定文案，不复述上游 message/value。

结果 sanitizer 绑定 canonical App、单日、limits、完整分页 receipt、行数与 schema。任何身份、日期、
limits、page 或公开行形状被伪造，都会重建为固定 `contract_changed`，且 data 为空。

## Guard 保留范围

Guard 仍占有所有明确 Monetization detail 形状和 near-raw selector。只有产品 recognizer 同时确认
“单日无标识明细、无相邻语义”时返回卡；否则本地返回固定 `capability_gap`，safe query 始终为
`monetization_detail`，不扫描 operation/export inventory。

以下场景继续阻断：

- 否定、导出/下载、写入/修改；
- 跨日、周/月、summary/report/total 或任何聚合意图；
- fields/filter/group/sort/profile/raw；
- 用户、设备、ClientID、TraceID、user_id、device_id、广告主/广告位定向等可重定位意图；
- LTV/ROI/归因、看板、订单、素材、推广、Multidim 等相邻产品拼接；
- canonical raw selector 后追加任意自然语言或值。

trim 后精确等于 `analysis.monetization_detail.list` 的专家 selector 和精确 export selector 保持原
generic 专家入口；泛 `monetization/变现` 不由本 Guard 独占。

## 证据与非目标

wire 已由既有 stable 合同证明，本单元没有生产 probe。测试覆盖投影强制、未知字段默认隐藏、固定
失败、request binding、一条 happy path、Agent 安全卡和保留型 gap。D28 按平台/广告位/日期的聚合
仍需要独立账户绑定与合同证据，不从明细结果在 SDK 内派生。

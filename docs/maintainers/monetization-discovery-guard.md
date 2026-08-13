# Monetization Discovery Guard

本页定义一个仅作用于 Agent discovery 的本地安全边界。它不新增 Monetization 产品、operation、
CLI、SDK、Plan adapter、结果 schema 或执行路径。

## 为什么只做 Guard

stable `analysis.monetization_detail.list` 是 `user_level` 读取，默认请求与响应合同允许 ClientID、
TraceID、用户/设备、广告主、广告对象、广告位和 re-attribution 等可关联字段。当前自然语言
`monetization details` 会直接得到该 raw operation 卡，但复制出的 Plan node 只有 selector，既没有
显式单日，也没有固定字段或产品级结果边界；中文“变现明细”则成为 gap，行为不一致。

现有证据不足以把它升级为产品：合同只保证 `data.list` 容器，允许的行字段没有 required key、
类型或非空样本；golden fixture 证明请求 wire，不证明响应行形状。可选 `data.total` 也没有空态、
单例、跨页或聚合含义证据。因此本轮既不实现 Directory，也不实现 Summary，更不从首行或缺失
total 推导业务结果。

全局屏蔽 `privacy.classification=user_level` 同样不正确。该分类描述响应隐私，不是调用权限；现有
stable operation 中还包含受治理的聚合、配置和目录能力。全局 exact-only 会破坏既有 Agent 发现。

## 精确策略

Guard 只识别明确的 Monetization detail 产品形状：

- 英文包含 `monetization`，并包含 `detail/details/directory/list/rows` 之一；
- 中文包含 `变现明细/变现目录/变现列表/广告变现明细`；
- 包含 `analysis.monetization_detail.list` 但整句不是该 canonical selector 的近似 raw 请求。

这些请求在 operation inventory、describe 和 export inventory 之前本地返回一个固定
`capability_gap`。gap 不含 Plan node、argv、raw request 或用户输入尾值；safe query 固定为
`monetization_detail`。

以下入口保持兼容：

- trim 后精确等于 `analysis.monetization_detail.list` 的专家 selector 继续走 generic raw card；
- 精确 `export.analysis.monetization_detail.start` 继续走既有 export 专家入口；
- 泛 `monetization` / `变现` 单词不由 Guard 独占，避免阻断目录、metadata 或未来受治理产品发现；
- `gravity run`、operation search/describe、SDK/client、Plan 和所有现有 composite 完全不变。

否定、导出/下载、写入，以及 fields/filter/sort/profile、跨日范围、summary/report/total、
ClientID/TraceID/user/device/advertiser/ad id/placement、收入/LTV/ROI/归因等词一旦同时形成明确
Monetization detail 请求，也由同一 Guard 安全报 gap，不回落 raw operation。完整的相邻产品意图
继续由其自身 authoritative recognizer 处理；两个产品意图拼接时 fail closed，不产生双卡。

## Single、batch 与 continuation

明确 Guard 请求的 single discovery 必须满足：

```text
operation inventory = 0
operation describe = 0
export inventory = 0
network_called = false
```

纯 Guard batch 同样全部为 0。mixed batch 可因其他问题共享一次 operation inventory，但 Guard 问题
不能增加 describe/export 调用。canonical exact selector 保持现状：single 一次 inventory 加一次
describe；batch 中同一 selector 只 describe 一次。

safe query、continuation fingerprint 和 capability gap 都不得包含 suffix 中的标识、secret、日期或
自由文本值。Guard 不生成可变嵌套卡，因此不新增 schema/template/request 的共享可变状态。

## 实现边界

新增 `agent_monetization_guard.py`，只包含纯 recognizer、canonical exact 豁免、safe query 和固定
gap reason。`agent_discovery_policy.py` 与 batch local-only 判断只保留薄路由；不修改
`agent.py`、capability inventory、handoff 或 execution 模块的产品语义。

预计 Python production 约 90..130 行，表驱动 tests 约 22..35 行；gross/net production:test 均
必须 `>=3:1`，目标约 `4:1`。不抬 quality baseline，新函数保持 CC `<=15`。

## 验收与非目标

验收覆盖中英明确请求、否定/effect/sensitive/range/profile 组合、近似 selector、canonical exact、
相邻 report/attribution/dashboard/product 查询、single/pure/mixed batch 调用数、安全 query 与
continuation。其他 `user_level` 自然语言发现抽样保持不变；完整门禁全部通过。

本轮不：

- 宣称 Monetization 行字段、total、eCPM、收入、LTV 或归因业务语义；
- 新增静态 FieldPolicy profile、分页或结果 sanitizer；
- 修改 operation stability、privacy classification 或 manifest；
- 联网 probe、创建内部 Issue，或把 Guard 描述成未来产品承诺。

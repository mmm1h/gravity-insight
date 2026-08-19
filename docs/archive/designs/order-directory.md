> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# Order Directory v1

本页定义一个单日、受控四字段的普通订单目录产品。它只调用既有 stable
`analysis.order_detail.list`，不新增 operation、筛选 DSL、订单业务语义或 Web 页面概念。

## 为什么是这个纵切

当前 raw operation 已证明单日订单读取，但 Agent 仍有三个产品断点：

- “order directory / 订单目录”成为 capability gap；“order detail”会同时给出父订单与敏感
  split-detail child，调用方无法判断可直接执行哪一个；
- raw 卡只把 `app_id` 标为必填，复制出的 Plan node 只有 selector，没有单日窗口或闭合 inputs；
- raw response 合同同时含 TraceID、ClientID、拆单 ID、归因标识和物理金额/状态，Agent 不应自己
  选择安全字段或保存用户级标识。

stable 合同、golden wire 和现有 Order Split Trace 已共同证明更窄的产品边界：显式 App、规范单日、
固定 `page_size=100`，并只选择 `Amount/BackAmount/Status/CreateTime` 四个物理字段。这四项已经由
`gravity-insight.order-split-trace.v1` 的结果重建器逐标量验证，不需要猜测订单成功、退款或净收入。

事件定义快照已被 metadata sync/search 覆盖，新增产品价值较低。Monetization Directory 的 profile
分叉集中在广告位、设备和广告收入字段，尚无同等强度的四字段产品合同，因此不在本轮实现。

## 公共接口

Core：

```python
order_directory(
    client,
    app_id,
    date,
    *,
    max_workers=6,
    max_pages=1000,
    max_items=100000,
)
```

SDK：

```python
gravity.order_directory(
    "main",
    "2026-08-08",
    max_workers=6,
    max_pages=1000,
    max_items=100000,
)
```

CLI：

```powershell
gravity analysis order directory --app main --date 2026-08-08 `
  --concurrency 6 --max-pages 1000 --max-items 100000
```

Plan composite：

```json
{
  "kind": "composite",
  "request": {
    "name": "order_directory",
    "app": "main",
    "date": "2026-08-08"
  },
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

只有 `/app`、`/date` 是标量 binding target；绑定后重新运行完整本地验证。Agent 只给待填写占位值，
不从自然语言推断 App、日期、字段、筛选或订单状态，也不自动执行。

## 固定请求与完整读取

产品按以下固定顺序执行：

1. 在 client 构造前验证正整数 App、严格 `YYYY-MM-DD`、worker 与分页/行数上限。
2. 固定请求 `fields=[Amount,BackAmount,Status,CreateTime]`、`page=1`、`page_size=100`，
   conditions/order 为空且 logic 为 `AND`；caller 不能注入任意 fields、filters 或 order。
3. 复用稳定 date codec，把单日派生为 `create_time RANGE_IN` 的
   `00:00:00..23:59:59`；不重新解释时区、支付时间或业务日期。
4. 使用 `read_all` 完整读取目录。已知 `total_page` 的后续独立页可有界并发，未知总页数串行推进；
   超过 `max_pages/max_items` 时失败，不返回或消费前缀。
5. 只接受 registered read schema、正确 operation identity、success/empty 一致性、完整 page receipt、
   `has_more=false`、无 truncation/continuation/error，以及每行恰好四个已登记 JSON scalar。
6. 任何额外行字段（尤其 TraceID、ClientID、event_pay_id、split IDs 或 re-attribute info）、
   malformed scalar、未知/additive status、矛盾页数/总数都 fail closed；不会静默裁剪后冒充完整目录。

完整分页收据与四字段行验证从 Order Split Trace 抽到私有 order support；两个产品共用同一实现。
FieldPolicy 的 metadata fast path 只接受这组 directory profile 或既有 trace-parent profile，且都必须
是规范单日、固定页大小、空 conditions/order。附近的 raw Analysis 请求仍走实时 metadata 校验。

## 调用数与并发

纯输入错误、Agent discovery 和 Plan dry-run 为 0 次网络调用。有效执行严格为：

```text
P 个 order_detail 分页；0 metadata；0 child
```

direct worker 默认 6、最大 24；Plan adapter 固定 1。一个产品内没有第二层线程池。多个 App 或日期
由调用方放入同一 Plan 的 sibling nodes，使用 Plan 全局 pool 并发并按声明序收集；不新增 batch
wrapper，也不形成节点池乘页面池的嵌套放大。

## 结果与隐私合同

schema 为 `gravity-insight.order-directory.v1`。成功结果只包含：

- canonical `app_id/date`；
- request-bound `limits`、完整安全 page receipt 与 `returned_items`；
- `data.list`，每行字段严格为 `Amount/BackAmount/Status/CreateTime`；
- 固定 status/exit/error/next_action。

failure 的 `data.list` 固定为空，不保留成功前缀。错误只允许内建 code/category、固定 field、受控
retry receipt 和安全动作。Core 与 Plan projector 都重新核对 App、日期、limits、page/row count、
operation/status/error 关系；兼容 SDK fake 不能自报更宽预算或错误身份。

结果、错误、continuation 和 Agent 卡不得包含 TraceID、ClientID、event_pay_id、split IDs、广告账户
标识、归因对象、raw request/input、原始异常或认证信息。CLI 只输出产品 JSON；本轮不新增 NDJSON，
避免拆散完整性收据。

## Agent 路由

专用 recognizer 接受明确的 “order directory / order detail report / list daily orders / 订单目录 /
订单明细 / 单日订单报表”等读取意图，并返回唯一 authoritative `order_directory` 卡。

以下意图必须 fail closed 且不回落 operation inventory：否定、导出、写入、按 TraceID 查拆单、退款或
净收入判断、支付成功解释、归因、用户旅程、变现、推广/素材、模板/看板、收藏/权限/UI。精确 raw
selector `analysis.order_detail.list` 与 `analysis.order_split_detail.list` 仍保留专家兼容入口。

## 非目标

- 不接受跨日窗口、任意 fields/conditions/order，也不按 TraceID、ClientID 或状态筛选；
- 不解释成功订单、退款、净额、LTV、支付原因、回传或归因口径，不排序、排名或生成结论；
- 不返回任何用户、订单、设备、广告账户、推广对象或拆单标识；
- 不读取 child，不新增 join/reduce、数组 binding、通用 detail DSL、独立 batch 或缓存层；
- 不复刻 Web 列表、下载、布局或权限，不注册 draft monetization/custom report 路由；
- 不新增 stable operation，不联网 probe，不为内部审计创建 Issue。

## 实现结构与验收

新增领域模块建议为 `_order_read.py`、`order_directory.py`、`order_directory_result.py`、
`plan_order_directory_adapter.py`、`agent_order_directory.py`；CLI/SDK 扩展现有 order 领域模块。
`plan_adapters.py`、Agent capability/handoff、onboarding 和 public root 只留薄路由。

`client.py/registry.py/models.py/executor.py/cli.py` 不增长；`_field_policy_detail.py` 只把两个精确
order profile 数据驱动化。新文件 SLOC/函数/CC 低于 `500/80/15`，不抬 quality baseline。

重点测试采用表驱动：多页保序、unknown/known totals、empty、超界、truncation/continuation、
status/error/page/row 漂移、额外敏感字段、scalar 巨值、raw exception、CLI/SDK invalid 零 client、
Plan identity/limits/worker=1、Agent 中英正负/冲突/batch inventory=0、复制节点 dry-run。底层 codec、
pagination 与 operation 投影已有回归，不逐字段复制。

本轮 Python production:test gross 与 net 都必须 `>=3:1`，目标约 `4:1`；建议 production
700..1,000 行、tests 175..250 行。方案先提交，再分工作树实现，最后做独立对抗审计和全量门禁。

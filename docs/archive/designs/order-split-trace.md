> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# Order Split Trace v1

本页定义订单父行到拆单明细的一次调用产品。它只编排两个既有 stable Analysis read，
不新增 operation、任意筛选 DSL、业务订单状态解释或 Web 页面概念。

## 为什么是这个纵切

现有 stable 合同已经分别证明：

- `analysis.order_detail.list` 可按显式 App 与单日读取父订单，并投影
  `TraceID/PayEventTime/ClientID/$split_trace_id_list`；
- `analysis.order_split_detail.list` 只接受上述父行派生的四项敏感输入，并返回拆单行；
- 现有 live-probe resolver 和 golden wire 已使用同一四字段链路。

但 raw child 卡要求调用方自己提供 `client_id/pay_event_time/trace_id/split_trace_ids`。Plan v1
只能绑定有限 JSON scalar，不能把父行中的敏感数组和三个 sibling 值原子地传给 child；自然语言
“按 TraceID 看拆单”因此会落到不可直接执行的 raw operation，中文常见措辞还会成为 capability gap。

本产品把这条已证明的 parent-child 链收成一个领域操作。它不扩展通用 Plan binding，也不要求
调用方处理或保存父行敏感字段。

## 公共接口

Core：

```python
order_split_trace(
    client,
    app_id,
    date,
    trace_id,
    *,
    max_workers=6,
    max_pages=1000,
    max_items=100000,
)
```

SDK：

```python
gravity.order_split_trace(
    "main",
    "2026-08-08",
    "<explicit-sensitive-trace-id>",
    max_workers=6,
    max_pages=1000,
    max_items=100000,
)
```

CLI：

```powershell
gravity analysis order trace --app main --date 2026-08-08 `
  --trace-id <explicit-sensitive-trace-id> --concurrency 6
```

Plan composite：

```json
{
  "kind": "composite",
  "request": {
    "name": "order_split_trace",
    "app": "main",
    "date": "2026-08-08",
    "trace_id": "<explicit-sensitive-trace-id>"
  },
  "limits": {"max_pages": 1000, "max_items": 100000}
}
```

`/app`、`/date`、`/trace_id` 都是标量 binding target；绑定后必须重新运行完整本地验证。
Agent 只给待填写占位值，不从自然语言提取、显示或执行 TraceID。

## 选择算法

产品按以下固定顺序执行：

1. 在任何 client 构造前校验正整数 App、严格 `YYYY-MM-DD`、有界非空 TraceID、分页和 worker。
2. 固定父请求 `page_size=100`，只选择
   `TraceID/PayEventTime/ClientID/$split_trace_id_list`，并使用 canonical `date` 快捷参数。
3. 用 `read_all` 完整读取受 `max_pages/max_items` 约束的单日父目录。超界、截断、未知状态、
   malformed page receipt 或 malformed row 均 fail closed，不能把前缀当完整目录。
4. 在本地对 canonical TraceID 做精确字符串匹配；绝不发送未经证明的 TraceID 上游 filter，
   也不做模糊、大小写或“第一条”选择。零条或多条均不调用 child。
5. 唯一父行必须含有效时间、ClientID 和 1..100 个唯一拆单 TraceID。四项只在内存中用于一次
   `analysis.order_split_detail.list`，不会进入产品 envelope、日志或 continuation。
6. child 必须返回已登记状态和 list shape；每条 child TraceID 必须属于请求集合且不得重复。
   最终行只保留 `Amount/BackAmount/Status/CreateTime`，所有标识随后丢弃。

父 `date` 的 codec 已固定生成 `create_time RANGE_IN 00:00:00..23:59:59`；产品复用该合同，
不重新解释时区或支付业务日期。

## 调用数与并发

纯输入错误和 Plan dry-run 为 0 次网络调用。有效请求为：

```text
P 个父订单分页 + 1 个严格后置 child
```

父查询只使用已登记静态字段且无 caller condition/order，因此 FieldPolicy 可走窄化静态 fast path，
不读取 user/event/segment metadata。fast path 只覆盖这组产品请求，不为任意 Analysis 条件放宽验证。

direct 的父分页 worker 默认 6、最大 24；Plan adapter 固定 1。child 必须等待完整目录和唯一匹配，
不与父分页并发。多个独立 TraceID 使用同层 Plan 节点，由一个全局 pool 并发；不新增 batch wrapper，
也不形成“Plan 节点 × 父分页 × child”的嵌套并发。

## 预算与结果合同

- `max_pages` 只约束父目录页数，默认 1,000、硬上限沿用公共分页边界。
- `max_items` 是父扫描行加 child 行的总预算。得到唯一父行后，产品先按拆单 ID 数量保留
  child 最坏预算；预算不足时不发送 child。
- 父页收据、扫描数、child 返回数和声明 limits 都在 core 与 Plan projector 重新核对。
- schema 为 `gravity-insight.order-split-trace.v1`；成功结果只含 canonical App、日期、受控计数、
  limits、阶段状态和 `data.list` 的四个物理字段。
- failure 的 `data` 固定为空，错误只保留内建 code/category、固定 field、retry receipt 和安全动作。

结果与错误不得包含父/子 TraceID、ClientID、拆单 ID 数组、PayEventTime、raw request/input、
原始异常、认证信息或任意未知字段。CLI 只输出这一产品 JSON，不提供会拆散身份收据的 NDJSON。

## Agent 路由

专用 recognizer 只接受明确的“order split trace / split order detail by TraceID / 拆单追踪 /
按 TraceID 查拆单明细”等读取意图，返回唯一 authoritative `order_split_trace` 卡。

以下意图必须 fail closed，且不得回落 raw operation inventory：否定、导出、写入、退款或净收入
判断、归因解释、用户旅程、普通订单目录、变现明细、推广/素材、模板/看板以及 UI/权限操作。
精确 raw selector `analysis.order_split_detail.list` 仍保持专家兼容入口。

## 非目标

- 不证明或使用 TraceID 上游筛选语义，不扫描跨日数据；
- 不解释退款、净收入、支付成功、归因或订单生命周期；
- 不返回用户标识、设备标识、父行或拆单标识；
- 不新增数组 binding、join/reduce、通用 parent-child DSL、独立 batch 或缓存层；
- 不复刻 Web 列表、下载、布局、收藏或权限；
- 不新增 stable operation，不联网 probe，也不为内部审计创建 Issue。

## 实现结构与验收

建议领域模块为 `order_trace.py`、`order_trace_result.py`、`order_trace_cli.py`、`sdk_order.py`、
`plan_order_trace_adapter.py`、`agent_order_trace.py`。通用 CLI/SDK/Plan/Agent 入口只留薄路由；
`client.py/registry.py/models.py/executor.py` 不增长。若修改 `_field_policy_detail.py`，只增加上述静态
父请求的可证明 fast path 和表驱动回归。

重点测试是表驱动合同：两页保序唯一匹配、零/多匹配、截断、父/子 malformed、child 身份漂移、
预算不足零 child、direct worker 与 Plan inner worker、敏感值全路径不出现、CLI/SDK invalid 零 client、
Agent 中英正负/冲突/批量 inventory=0、复制节点 dry-run。底层 operation/codec/pagination 已有测试，
不再逐字段复制。

本轮 Python production:test gross 与 net 均必须 `>=3:1`，目标约 `4:1`；建议 production
900..1,200 行、tests 220..300 行。新文件 SLOC/函数/CC 继续低于 `500/80/15`，不抬 quality baseline。

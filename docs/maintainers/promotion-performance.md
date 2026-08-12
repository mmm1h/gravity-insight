# Promotion Performance v1

本文定义跨平台推广表现读取的 Agent 产品边界。它只组合现有 stable 推广 primary
operation 和 `promotion.metric.list`，不新增 operation、不解释平台业务口径，也不把异构平台
强行包装成一套万能报表。

## 为什么是这个纵切

当前底层能力已治理，但完整产品路径仍有断点：

- `gravity promotion snapshot --platform all` 已能批量读取平台 primary operation，但只存在于旧
  CLI；统一 SDK、Plan 和 Agent 没有对应产品入口。
- 25 个 primary source 中，21 个同时具备 stable `date_list/query_fields/filters/pagination`
  合同，并由 `promotion.metric.list` 提供对应平台的实时物理指标字典。
- Agent 对“跨平台推广表现 / promotion performance”返回 capability gap 或指标字典等 raw
  operation；调用方必须知道底层 operation 名和请求字段后手工编排。
- 现有 CLI shortcut 和 `CompositeService.promotion_snapshot` 已进入质量热点；本轮应下沉现有
  逻辑，而不是继续向通用入口追加分支。

本产品只覆盖以下 21 个同构平台，按调用方声明顺序返回：

`alipay/apple/baidu/bilibili/bytedance/honor/huawei/huawei_store/huya/iqiyi/
kuaishou/oppo/qihu360/sigmob/tencent/ubix/uc/vivo/weibo/xiaomi/youdao`。

`bing/xiaohongshu` 的 primary 合同没有日期或动态指标；`taptap/wechat_video` 虽有日期，
但没有动态指标和 App filter。这四个平台继续由兼容的 `promotion query/snapshot` 原生入口读取，
不进入 Performance v1，也不伪造 `window_applied` 或 App 绑定。

## 公共 API

CLI：

```powershell
gravity promotion performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --metric stat_cost --concurrency 6
```

`--app` 接受一个 workspace alias 或正整数。`--platform` 和 `--metric` 都必须由调用方显式
给出，可重复或逗号分隔；平台必须来自上述 21 项，指标保持上游物理名称。日期严格为包含首尾的
`YYYY-MM-DD`，不从当前时间或自然语言推断。原有 `promotion platforms/query/snapshot` 的参数、
输出和 25 平台兼容行为保持不变。

Python：

```python
result = gravity.promotion_performance(
    "main",
    "2026-08-01",
    "2026-08-07",
    platforms=("bytedance",),
    metrics=("stat_cost",),
    max_workers=6,
    max_pages=20,
    max_items=5000,
)
```

Plan composite request：

```json
{
  "name": "promotion_performance",
  "app": "main",
  "start": "2026-08-01",
  "end": "2026-08-07",
  "platforms": ["bytedance"],
  "metrics": ["stat_cost"]
}
```

Plan 只允许标量 binding target `/app`、`/start`、`/end`。`platforms` 与 `metrics` 必须是
提交前完成的 literal 数组；Plan 不新增数组 binding DSL。一个产品请求只绑定一个 App；多 App
分析使用同一个 Plan 的多个同层节点或 `foreach /app`，不在产品内部形成 App × platform
笛卡尔积。自然语言发现只返回待填写节点，不选择 App、日期、平台或指标，也不自动执行。

## 验证、执行和调用次数

产品把 App 解析为 canonical ID，并为每个平台构造已有合同字段：

```text
date_list=[start,end]
query_fields=metrics
filters=[app_id EQUALS canonical_app_id]
```

每个平台请求仍经过现有 schema 和 FieldPolicy；固定投影字段可离线验证，动态指标必须出现在该
平台实时 `promotion.metric.list` 元数据中，否则在 query HTTP 前 fail closed。产品不维护第二份
指标词典，也不把同名指标解释为跨平台同一业务口径。腾讯沿用已验证的默认 behavior timeline；
本轮不开放平台专属请求旋钮。同一指标数组会应用到每个所选平台；多平台请求只适合各平台元数据
都证明存在的同名指标。原生指标名不同时应使用同层独立 Plan 节点，不能在 SDK 内猜映射。

选择平台数为 `P` 时，每个平台一个 batch item并读取受控分页：

```text
HTTP requests <= P metadata reads + Σ query pages
```

只有动态字段需要元数据，缓存命中或全部为固定字段时请求数更少。Direct CLI/SDK 的
`max_workers` 默认 6、范围 1..24，实际平台并发不超过 `min(P,max_workers)`；每个平台内分页
worker 固定为 1，避免平台并发与分页并发相乘。Plan adapter 固定传 `max_workers=1`，由 Plan
全局 pool 并发独立节点。

`max_pages` 是每个平台的硬分页上限。`max_items` 在 P 个平台间按
`floor(max_items/P)` 等额分配且余量不可借用，因此最小值为 P；产品对安全结果再次按平台和总量
计数。完成顺序不影响输出顺序，单个平台失败不取消独立 sibling，但 partial/error 必须保留安全
主错误和正确退出码。

## 结果和隐私边界

结果 schema 为 `gravity-insight.promotion-performance.v1`。顶层只保留受控状态、canonical
`app_id`、日期范围、请求平台/指标数量、limits、固定顺序的 results 和安全 next action。每个
component 只保留：

- `platform/resource/operation_id` 身份；
- `ok/status/exit_code/error`；
- stable projection 产生的 `data.list` 与受控分页 receipt；
- `window_applied=true` 和已验证的结果行数。

不回显 workspace alias、filters、query_fields、compiled input、request、binding 值、原始异常或
未知上游字段。错误字段、状态、category、retry receipt 和分页整数都按固定词汇/类型/上界重建；
结果身份、平台顺序、operation、预算或收据矛盾时 fail closed。Plan 使用专用 safe projector，
不能通过兼容 SDK fake 注入额外字段。

平台原生投影字段和物理指标语义不同。产品不做跨平台字段归一、求和、平均、排名、最佳渠道判断、
投放策略或业务结论。

## Agent 路由

明确表达“推广表现、跨平台投放报表、promotion performance/report”等只读聚合意图时，Agent
返回唯一 `composite:promotion_performance` 卡，包含闭合输入 schema、缺失输入和可复制 Plan
node。以下意图必须 fail closed 或进入各自产品：

- 否定、导出、写入、投放策略或优化建议；
- 素材表现、经营 Pulse、Multidim、归因、看板、保存分析、分群和单用户旅程；
- 平台账户/层级目录或 raw promotion snapshot；
- Bing、小红书、Taptap、视频号的通用化请求。

被严格 recognizer 排除后不得回落为误导性的 generic promotion raw operation 卡。

## 明确非目标

- 不新增、修改或探测 operation，不猜 Web opaque config。
- 不复刻推广页面、层级树、模板、layout、收藏、拖拽或成员权限。
- 不开放 arbitrary filters、dimensions、sorting、timeline 或 raw request escape hatch。
- 不引入 campaign/SKU/ROI/归因因果等业务语义，不替调用方选择指标。
- 不新增独立 batch scheduler；direct 复用 Insight batch，交叉查询复用 Plan 全局 pool。
- 不把四个异构平台标成 unsupported bug；它们保留旧原生入口。
- 内部审计和实现发现写入代码、测试或本文，不创建 GitHub Issue；Issue 只来自其他项目真实使用。

## 实现结构和质量目标

- `promotion_performance.py`：闭合输入、平台选择、请求构造、预算和 core envelope。
- `promotion_performance_result.py`：组件身份、分页 receipt、错误消毒、保序和结果计数。
- `promotion_cli.py`：迁出既有 promotion parser/dispatch/shortcut，并加入 performance；通用 CLI
  只保留薄 hook且 SLOC 净减。
- `sdk_promotion.py`：统一 SDK 的薄 mixin。
- `plan_promotion_performance_adapter.py`：离线预检、inner worker=1、request-bound 结果复验。
- `agent_promotion_performance.py`：严格中英文意图识别、闭合 schema 和 Plan request。
- `CompositeService.promotion_snapshot` 改为兼容薄委托；旧 schema 与行为不变。

本轮不增加 `cli.py`、`domains.py`、`plan_adapters.py` 或 `composite.py` 的质量债，也不放宽 baseline。
递归 Python diff 的 production:test gross 与 net 都必须至少 3:1，gross 目标约 4:1。测试只覆盖
产品输入、预算/顺序/partial、四产品面交接和 strict Agent 冲突，不复制 21 个底层合同测试。

# Material Performance v1

本文定义四平台素材表现读取的 Agent 产品边界。它只组合现有 stable
`material.report.query`，不新增 operation、不依赖模板或页面状态，也不解释跨平台业务口径。

## 为什么是这个纵切

当前底层能力已经经过治理，但完整产品路径仍有断点：

- `material.report.query` 已是 stable；合同记录 2026-08-08 在巨量、腾讯、磁力、B 站四个平台
  的最小只读请求均成功，且共享同一响应结构。
- 合同输入已闭合为 `app_list/date_list/platform/page/page_size`，平台只允许
  `bytedance/tencent/kuaishou/bilibili`。
- request codec 已按平台固定物理指标、`material/total` 聚合和 App filter，并固定
  `stat_list=[]`，不会开放 `designer_id` 人员分组。
- 现有 `gravity materials` 只有素材目录、标签和审核入口；统一 `GravitySDK`、Plan 和强意图
  Agent 卡都没有素材表现产品。调用方只能知道精确 operation 名后自行拼四个请求。

因此本轮只把这一个已有稳定合同提升成一致的 CLI、SDK、Plan 和 Agent 产品面，不借机扩张
素材目录、导出或推广报表范围。

## 公共 API

CLI：

```powershell
gravity materials performance --app main --start 2026-08-01 --end 2026-08-07
gravity materials performance --app main --app secondary `
  --platform bytedance --platform bilibili `
  --start 2026-08-01 --end 2026-08-07 --concurrency 4
```

`--app` 可重复或逗号分隔，接受 workspace alias 或正整数；`--platform` 可重复，省略时按
`bytedance/tencent/kuaishou/bilibili` 顺序查询全部四个平台。日期是包含首尾的
`YYYY-MM-DD`，最大窗口仍由现有 operation 合同和运行时策略约束。CLI 保留原有
`materials list/tags/reviews` 行为。

Python：

```python
result = gravity.material_performance(
    ["main", "secondary"],
    "2026-08-01",
    "2026-08-07",
    platforms=("bytedance", "bilibili"),
    max_workers=4,
    max_pages=20,
    max_items=5000,
)
```

Plan composite request：

```json
{
  "name": "material_performance",
  "apps": ["main", "secondary"],
  "start": "2026-08-01",
  "end": "2026-08-07",
  "platforms": ["bytedance", "bilibili"]
}
```

Plan 只允许标量 binding target `/start`、`/end`。`apps` 与 `platforms` 必须是提交前完成的
显式 literal 数组；Plan 不新增数组 binding DSL。自然语言发现只返回待填写的 Plan 节点，不选择
App、日期或平台，也不自动执行。

## 执行和调用次数

产品把所有 App 合并进每个平台的一次 `app_list`，不会隐式展开成 App × platform 笛卡尔积。
每个选定平台提交一个 `material.report.query` 并读取受控分页：

```text
HTTP requests = Σ P_platform
```

其中 `P_platform` 是该平台实际读取的页数。选择四个平台时至少有 4 次首页请求。多个 App 不会
额外增加请求条目；需要每个 App 独立结果时，调用方应在同一个 Plan 中声明多个同层节点。

Direct CLI/SDK 接口的 `max_workers` 默认 6、范围 1..24；实际平台 worker 数量不超过选定平台
数，因此当前最多 4。平台是外层并发单元，每个平台内部分页 worker 固定为 1，避免平台并发和
分页并发相乘。Plan adapter 无条件传 `max_workers=1`，由 Plan 全局 pool 并发不同节点。

`max_pages` 是每个平台的硬分页上限，`max_items` 是所有平台共享的聚合行预算。底层 batch 以
`floor(max_items / platform_count)` 给每个平台同样的独立硬份额；某个平台未用完的份额不会借给
另一个平台，因此实际可返回总数可能小于声明预算。产品还会对实际安全结果重新计数，超预算、
丢失/重复结果身份或错误结果形状均 fail closed。结果按调用方声明的平台顺序返回，与完成先后
无关；单个平台失败不取消独立 sibling。

## 结果和隐私边界

结果 schema 为 `gravity-insight.material-performance.v1`，顶层保留：

- `ok/status/exit_code` 与成功、失败计数；
- `operation_id=material.report.query`；
- App 数、包含首尾的日期范围、请求平台和固定顺序的 `results`；
- 每个 result 的 `platform/operation_id/ok/status/data/error` 以及受控分页 receipt。

成功数据只能来自现有 stable projection：

- 素材身份：`file_name`、`gravity_material_id`；
- 平台物理指标：`stat_cost/ctr/convert_rate/cost/conversions_rate/charge/action_ratio/
  conversion_ratio/click_rate`；
- Gravity 聚合指标：`AppRealRegisterCnt`、`AppGamePayUserCntStandardAtv`。

产品不恢复合同已经省略的 `total/update_at`，不开放人员、设计师、凭据、请求体、binding 值、
原始异常或未知上游字段。Plan 使用专用 safe projector；即使兼容 client 返回额外键，也不会原样
穿透到 Plan 结果。

各平台物理指标名称和语义不同。产品只保留平台分组的原生稳定行，不做跨平台字段归一、换算、
总计、排序、排名、最佳素材判断或业务结论。

## Agent 路由

明确表达“素材表现、素材效果报表、跨平台素材报表、material performance/report”等只读聚合
意图时，Agent 返回唯一 `composite:material_performance` 卡。卡片包含闭合输入 schema、缺失输入
和可复制 Plan node。

以下意图必须保持分离：

- “素材报表导出 / material report export”继续进入现有治理导出产品；
- 素材库、相册、标签、审核、回收站、收藏继续使用各自 operation；
- 推广表现、经营 pulse、Multidim 和五类 Analysis query 不命中本产品。

## 明确非目标

- 不新增、修改或探测 operation，不猜测 Web opaque config。
- 不执行导出，不复刻模板、图表、layout、收藏、拖拽或成员权限。
- 不引入活动、SKU、素材策略、平台归一公式、投放目标等业务语义。
- 不提供 arbitrary metrics、dimensions、filters 或 raw request escape hatch。
- 不新增独立 batch scheduler；直接入口复用 Insight batch，交叉查询复用 Plan 全局 pool。
- 内部审计与实现发现写入代码、测试或本文，不创建 GitHub Issue；Issue 只来自其他项目真实使用。

## 实现结构和质量目标

- `material_performance.py`：闭合产品验证、稳定 operation 选择、请求构造、并发和安全 envelope。
- `material_cli.py`：统一承接既有 `materials list/tags/reviews` 的注册与分派，并加入
  `materials performance`；通用 CLI 只保留薄 hook，旧行为和 help 保持兼容。
- `sdk_material.py`：统一 SDK 的薄 mixin，避免继续扩大 Analysis/Report 热点。
- `plan_material_performance_adapter.py`：专用离线 validator、inner worker=1 executor 和 safe projector。
- `agent_material_performance.py`：严格中英文意图识别、闭合 schema 和 Plan request。
- 通用 `cli/sdk/plan/agent` 文件只保留薄路由。

本轮新增 production gross 必须至少是 test gross 的 3 倍，目标约 4 倍。测试采用少量表驱动用例，
只覆盖产品边界、并发/预算/顺序、Plan 脱敏和 Agent 冲突，不复制底层 operation/codec 合同测试。

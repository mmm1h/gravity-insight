# Multidim Agent Surface v1

本页记录 Multidim 产品化的实现决策。它是开发边界，不是新的 Gravity operation，也不是一套
平行查询语言。

## 现状与目标

`report.multidim.query`、`report.multidim.calc_total`、标准/自定义/共享指标目录、动态列投影、
分页和 `CompositeService.multidim_query()` 均已有 stable 合同。当前断点在产品表面：

- `GravitySDK` 没有直接的 Multidim 方法；
- Agent 的 composite 卡只把 `inputs` 描述为不透明 object，Plan node 只有 `name`；
- CLI 只接受数值 `--app-id`，不能绑定 workspace App alias，也没有专用安全离线预检；
- Plan 使用通用 composite 投影和计数，可能裁掉 `query`，且不能按 `query.data.list` 执行预算；
- Plan 虽把 query 分页 worker 固定为 1，指标 metadata loader 仍会在节点内自行并发。

目标是让调用方直接使用已经稳定的物理输入，不再从 Web 反推参数，同时保持旧 raw 入口兼容。

## 决策：复用 raw 合同，不新增 Spec DSL

Multidim 的公开输入已经是紧凑物理合同：

```json
{
  "date_list": ["2026-08-01", "2026-08-07"],
  "time_dims": "day",
  "metrics_list": ["ap_cost"],
  "custom_metrics_list": [],
  "data_dims": ["day"],
  "relate_dims": [],
  "filters": [],
  "multi_keys": [2, 7]
}
```

不再增加一套把 `start/end/time_grain/metrics` 改名后映射回这些字段的编译器。Analysis Spec
需要吸收复杂 Web artifact；Multidim 不存在同样的结构鸿沟。机器 schema 直接描述上述受治理
input，App 在 input 外单独绑定，并由产品入口覆盖唯一 `app_id` filter。

旧 `--input`、CLI shortcuts、Plan `inputs` 和底层 operation 继续兼容。Agent 不展示
`data_topic/data_conf/page/page_size` 等底层控制项；直接底层调用仍以 operation schema 为准。

## 公共入口

- CLI：`gravity multidim query --app <alias|id> --input ...`，保留现有 shortcuts；增加专用
  `--dry-run` 与 input schema 输出。`--app` 与兼容 `--app-id` 不能冲突。
- SDK：`GravitySDK.multidim_query(inputs, *, app, include_total=False, read_all=False,
  max_pages=1000, max_items=100000, max_workers=6, workspace=None)`；离线预检使用同一产品模块。
- Plan：继续使用 `composite` / `name=multidim`，不新增第二个 composite 名。request 显式包含
  `app/inputs/include_total/read_all`；专属 adapter 负责预检、App 绑定、安全结果和预算。
- Agent：继续发布唯一 `composite:multidim` 卡，但展开完整机器 input schema、必填槽位和可复制
  Plan request；自然语言永不选择 App、指标、维度、日期或 filter value。

多个独立 Multidim 查询放入同一个 Plan，由全局 worker pool 并发；不新增 batch wrapper。

## 并发与请求数

- CLI/SDK 直接调用默认 6 workers、上限 24；已知 `total_page` 时分页保序并发。
- 标准、自定义和共享指标 metadata 最多三个来源，复用 cache，并受同一个 worker budget 约束。
- Plan adapter 内部固定 1 worker；多个节点只由 Plan 全局池并发，避免节点数乘 metadata 线程数。
- total 依赖 query rows，必须在对应 query 完成后串行执行。
- dry-run 为零网络；执行 HTTP 数量为去重 metadata 请求 + query 页数 + 可选一次 total。

已知完整输入仍是一次 CLI/SDK/Plan 调用；未知能力为一次 Agent 发现加一次 Plan 执行。这里的
价值是消除 opaque input 和 Web 依赖，不虚报已有调用数下降。

## 安全与非目标

- 继续复用 live metric/FieldPolicy；未知指标、维度、动态列或 metadata 不完整时 fail closed。
- dry-run 可返回已显式绑定的 canonical `app_id` receipt，但不返回 raw input、filter values、完整
  normalized input 或任何隐式业务选择。
- Plan 只保留固定 Multidim envelope、validation、query/total 的受治理结果；失败不保留原始
  request、未知 data、路径或异常文本。
- 不做 template replay、公式/指标语义、透视/图表、layout、收藏、拖拽、权限、join/reduce、
  自然语言自动填值、新 operation 或新 HTTP runtime。
- 业务指标含义、活动口径、App 实例和 recipe 仍由调用项目维护。

## 验收

1. CLI/SDK/Plan/Agent 使用同一 input schema 和 App 绑定；非法本地输入在构造 client 前拒绝。
2. Agent 中英文明确意图只返回一个 Multidim 产品卡，普通 template/经营 pulse 不误命中。
3. Plan dry-run 零网络；执行保留 query/total，按 query 主结果正确执行 `max_items`。
4. direct worker 可并发 metadata/分页；Plan adapter 内严格为 1，声明顺序与局部失败语义不变。
5. 不回显 filter values、raw inputs、原始错误或未知响应字段。
6. 不新增 operation/probe；完整 compiler、quality、测试和 diff 门禁通过。
7. 新增生产代码与测试代码至少 3:1，目标 4:1；复用既有底层测试，不复制合同矩阵。

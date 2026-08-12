# Business Pulse Agent Surface v1

本页记录 Business Pulse 的 Agent 产品面决策。它只补齐已有受治理 composite 的离线发现与
可复制交接，不新增 operation、查询 DSL、指标定义或执行核心。

## 基线断点

`business_pulse()` 已稳定组合 `overview`、`business` 和可选的 `hourly_comparison`：CLI、
`GravitySDK.business_pulse()` 与 Plan `name=business_pulse` 都复用同一实现。直接调用默认 6
workers、上限 24；Plan adapter 内固定 1 worker。

本轮开始前的断点仅位于 Agent 交接：

- `business pulse` 虽能匹配 generic composite，但仍扫描一次 stable operation inventory；
- Agent 的 Plan request 只有 `{"name":"business_pulse"}`，原样 dry-run 会在零网络预检阶段
  因缺少 `apps/start/end` 失败；
- 泛化的 `经营分析` 会同时返回 raw `report.business.query` 和 composite，调用方无法得到唯一
  产品选择；
- generic handoff 没有完整展示平台和 hourly 开关，调用方仍需反查 Plan 文档。

底层调用数不在本轮改变：基础 pulse 是一次 batch、两个 source；启用 hourly 仍是一次 batch、
三个 source。Agent 发现保持零网络，交付后不再为明确 pulse 意图扫描 operation inventory。

## 严格意图与冲突排除

以下输入可以成为唯一、权威的 `composite:business_pulse` 候选：

- 精确 selector：`business_pulse`、`composite:business_pulse`；
- 同时表达 pulse 与经营主题的英文请求，例如 `business pulse`、`operating pulse`；
- 明确中文脉搏请求，例如 `经营脉搏`、`业务脉搏`；
- 同时表达经营概览与趋势汇总的明确请求。

`business analysis`、`business report`、`经营分析`、`经营报表` 等泛意图不由 Pulse 抢占；
它们继续进入已有 recipe、Analysis task 或 stable operation 竞争。recognizer 还必须排除：

- Multidim、多维、指标维度交叉查询；
- saved analysis、Dashboard、Segment/Audience、single-user journey；
- Attribution、template、layout、favourite、permission、member；
- export、create、update、delete 与 raw report-config。

排除规则属于产品路由，不解释业务口径。Agent 不从自然语言提取 App、日期、平台、指标或
hourly 值，也绝不自动执行。

## Agent 交接合同

卡片必须展开 `apps/start/end/platforms/include_hourly` 的闭合输入描述，标记必填项为
`apps/start/end`，并给出下列可机械填写的 Plan node：

```json
{
  "id": "pulse",
  "kind": "composite",
  "request": {
    "name": "business_pulse",
    "apps": ["<workspace-app-alias-or-positive-id>"],
    "start": "<start:YYYY-MM-DD>",
    "end": "<end:YYYY-MM-DD>",
    "platforms": ["bytedance", "tencent", "kuaishou"],
    "include_hourly": false
  },
  "limits": {"max_pages": 5, "max_items": 200}
}
```

占位值由调用方在执行前显式替换。发现只需一次 Agent 调用；补齐后一次 Plan 调用完成执行。
多个 App 可以在同一个 `apps` 数组中显式提交，不从自然语言或上游 opaque config 猜测。

## Plan binding 与并发

Plan binding 只传递有限 JSON scalar，因此 Pulse 动态 target 只接受 `/start`、`/end` 和
`/include_hourly`。`apps`、`platforms` 是显式数组，不能把 scalar 绑定到整个数组后延迟到运行时
失败；本轮不增加 array-binding DSL。

- CLI/SDK direct：默认 6 workers、上限 24，一次 batch 并发两个或三个固定 source；
- Plan：adapter 内固定 1 worker，独立 Pulse 或其他节点由全局 pool 并发；
- hourly 是同批第三 source，不创建第二个线程池；
- 结果继续按固定 source 顺序返回，局部失败保持可见，不取消独立 source。

该模型防止 Plan 节点数乘 composite 内部 worker 数形成嵌套并发放大。

## 非目标与安全边界

- 不新增或修改 stable operation、codec、FieldPolicy、HTTP runtime、分页或结果 envelope；
- 不新增结果模块，除非对抗测试证明现有 stable projection 会泄漏 request 或 secret；
- 不回放模板，不解析 Web config，不实现布局、收藏、拖拽、成员或权限管理；
- 不定义经营指标含义、活动口径、平台选择策略或业务结论；这些属于调用方；
- 不触发在线 probe、Evidence 刷新或 GitHub Issue；内部发现由本文、代码和回归测试收口。

## 验收

1. 明确中英文 Pulse 意图离线返回唯一 authoritative composite，且不扫描 operation inventory。
2. 泛 `business analysis/经营分析` 不返回 Pulse；相邻产品和 Web/UI 意图不误命中。
3. Agent Plan request 包含全部五个输入字段和中性占位/默认值，`natural_language_auto_execute=false`。
4. 填充后的节点通过零网络 Plan dry-run；未填槽位继续 fail closed。
5. Plan 只允许真正 scalar-bindable target，direct/Plan 并发模型与 source 调用数保持不变。
6. 不新增执行核心、operation、probe 或 Issue；完整 compiler、quality、测试、help 与 diff 门禁通过。
7. 新增生产代码与测试代码至少 3:1，目标约 4:1；文档不计入比例。

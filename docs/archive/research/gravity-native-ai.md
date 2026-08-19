> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 引力原生 AI 事件分析对话摸底

> 取证日期：2026-08-16。本文只依据本租户前端 hash-matched bundle、仓库 census 和一次受控在线验证。
> `[实证]` 表示可由静态控制流、仓库快照或最小生产响应直接核对；`[推测]` 表示基于这些证据的边界判断。
> 本文没有公开厂商资料，因此没有 `[厂商宣称]`。本单元不做集成、operation、评测臂或产品行为改动。

## 结论先行

- **[实证] 三选一答案是“重叠”，而且是窄范围重叠。** 它不是把问题原样转发给大模型并显示自由文本的聊天壳；
  成功分支读取 `backup_measure_json`，交给事件分析页恢复事件/公式、过滤、分组、日期与图表类型。
  它也不是已证明可用的“捷径”：本次唯一通用问法得到空 `data`，没有在线观察到成功配置，接口也没有版本化
  schema、稳定性或错误分类证据。
- **[实证] 输出目标是结构化的事件分析定义，不是结果数据，也不是报表/看板引用。** 对话窗只显示固定成功/失败文案；
  成功时提供“一键配置”，由父页面把定义填进现有事件分析表单。该路径没有在气泡里渲染模型自由文本或图表，
  也没有直接跳转到另一分析页。
- **[实证] 成功分支可以被程序化消费。** 前端已经对它做 `Object.keys`、`JSON.stringify`、`JSON.parse` 和逐字段映射；
  但它目前只是上游内部结构，不是本仓库可依赖的受治理合同。本次在线只验证了空结果 envelope，未验证一份真实
  成功定义及其字段完备性。
- **[推测] 它可以被列为未来自然语言 A/B 的“第四条候选臂”，但当前只能列选项，不能列已具备资格的臂。**
  其候选输出还需经过确定性 schema、App/事件/属性引用、日期与 operator 校验，并保留 abstain/失败分类；现有
  recognizer、embedding/hybrid 和结构化 LLM selector 的三臂裁定不因本次发现而改变。

## 证据范围

**[实证]** census 指向 `Event-BKh0ym6c.js`。仓库快照登记该文件为 113,757 bytes、SHA-256
`352233b7fb6ea74ec6b0c86e304dda84782669d52af1c01c7a84014eaa30e1a8`；取证时重新读取公开静态资源，
size 与 SHA-256 完全一致。因此下述控制流不是根据相邻版本猜测。快照见
[`bundle-snapshot.json`](../../../src/gravity_sdk/census/data/bundle-snapshot.json)，参数提取见
[`route-params.json`](../../../src/gravity_sdk/census/data/route-params.json)。

**[实证]** 该 hash-matched bundle 的 sourcemap URL 返回 `NoSuchKey`，所以本文依据 minified 但可逐字定位的控制流；
没有把不存在的源码映射当作证据。census 对四条同族 route 的响应字段仍标为 unknown，见
[`route-response-fields.json`](../../../src/gravity_sdk/census/data/route-response-fields.json)。

## 请求合同与调用顺序

**[实证]** 当前 UI 的实际写调用只有以下两步；没有观察到可选字段。这里的“必填”表示前端每次调用都发送，
不表示已证明服务端缺字段时一定拒绝。

| 顺序 | Route | 前端每次发送的 body | 值来源 |
| ---: | --- | --- | --- |
| 1 | `POST /report/api/v3/dataanalysis/ai/conversation/create/` | `title: string` | 当前输入框问题；空字符串在发请求前被 UI 拦截 |
| 2 | `POST /report/api/v3/dataanalysis/ai/message/create/` | `app_id: number\|string`、`conversation_id`、`message: string` | 当前事件分析页所选 App；第 1 步返回的会话 ID；同一个输入框问题 |

**[实证]** 顺序是“先建会话，再发消息”。第 1 步 resolve 后，只有拿到返回对象才执行第 2 步；在线响应进一步确认
原始 envelope 的 `data.conversation_id` 是非空 string。当前组件没有缓存或复用该 ID：每次点击发送都会重新执行
`conversation/create`，因此已观察 UI 不是多轮会话。

**[实证]** census 里恰好还有两个对应的读候选：

- `POST /report/api/v3/dataanalysis/ai/conversation/list/`
- `POST /report/api/v3/dataanalysis/ai/message/list/`

二者在当前 SmartAssistant 组件只创建 loader，**没有调用点、请求参数或响应消费**；仓库因此仍将它们保持为
不可执行 experimental 候选，见
[`analysis.ai.conversation.list.json`](../../../src/gravity_sdk/contracts/operations/analysis.ai.conversation.list.json) 和
[`analysis.ai.message.list.json`](../../../src/gravity_sdk/contracts/operations/analysis.ai.message.list.json)。不能从名称继续猜
分页、message-list 的会话绑定字段或服务端多轮语义。

## 响应结构与前端消费

### conversation/create

**[实证]** 最小在线响应形状如下；只记录 key 与类型，不保留值：

```text
{
  code: integer,
  data: { conversation_id: string(nonempty) },
  extra: null,
  msg: string(nonempty)
}
```

前端请求 helper 将 `data` 解包给调用点，所以静态代码直接读取 `response.conversation_id`。

### message/create

**[实证]** 静态成功分支直接读取 `response.backup_measure_json`，要求它存在且
`Object.keys(...).length > 0`。子组件先 `JSON.stringify` 后发出 `configJson` 事件；父事件分析页再
`JSON.parse` 并消费以下顶层定义：

```text
{
  title,
  supportImageTypeList,
  timeRange: { start_date, end_date },
  queryItemCollection: {
    itemNumber,
    itemNameList,
    itemContentList
  },
  filter,
  groupBy
}
```

**[实证]** 同一分析定义的反向序列化器会产出 `contrastTimeRange`，但 AI handoff 的解析函数没有读取它，
并把本地对比时间重置为空。因此不能把跨期对比计入当前原生 AI 的已证明能力。

**[实证]** `itemContentList` 会被还原为普通事件指标或包含 event/operator/numeral 的自定义公式；事件项含事件名与说明、
预置/事件属性 measure、属性数据类型和 item 级 filter。`filter` 会被还原为事件或全局过滤，覆盖字符串、数值、布尔、
日期区间和相对时间 operator。`groupBy` 会被还原为属性、数据类型、时间/数值分桶和可选自定义区间。

**[实证]** 前端消费结果是**配置现有事件分析**：写入标题、图表类型、日期、query items、global filters 和 group-by，
然后走事件分析页既有 metadata/form 初始化；现有页面是否随后自动查询取决于其 route 状态，但 AI response 本身不含
结果。对话窗只渲染用户问题、固定的解析中提示、固定的成功/失败文案和“一键配置”按钮；它不渲染 AI 自由文本、
结果行或图表。成功点击也不产生报表/看板引用。

**[实证]** 唯一在线问题“最近 7 天的事件趋势”返回：

```text
{
  code: integer,
  data: [],
  extra: null,
  msg: string(nonempty)
}
```

没有 `backup_measure_json`，按当前前端控制流会进入固定失败气泡。本次没有换问法、换 App 或补造事件名来追求非空。
这个空结果不能推翻静态成功分支，也不能证明当前租户能实际生成一份成功配置。

## 流式、工具调用与多轮痕迹

- **[实证]** `conversation/create` 与 `message/create` 都是普通 Promise 式 HTTP POST；hash-matched Event bundle 中
  `EventSource`、`WebSocket`、`ReadableStream`、`text/event-stream` 均为 0 次。
- **[实证]** 同一 bundle 中没有 `tool_call` 或 `function_call` 标记。前端只等待一次 message response，再判断
  `backup_measure_json` 是否非空。
- **[实证]** 服务端暴露 conversation/message 的 create/list 资源形态；但当前 UI 每问新建会话，两个 list loader
  未调用。聊天窗会在本地连续显示多次提问，不等于这些提问共享同一个服务端 conversation。
- **[推测]** 服务端内部可能调用模型、检索或工具，也可能支持未接入当前 UI 的多轮；客户端静态与本次在线响应都无法证明。

## 三类判断

### 为什么不是“壳”

**[实证]** 壳的关键特征应是只把回答作为文本展示；这里的成功值反而不展示为回答，而被严格当作事件分析定义解析，
并驱动既有分析表单。固定失败/成功文案与结构化 config handoff 足以排除“纯聊天转发框”。

### 为什么当前归为“重叠”，而不是已证实的“捷径”

**[实证]** 它与本仓库自然语言层的重叠点是“自然语言 → 可执行分析结构”，只是输出落在 Gravity Web 的事件分析配置，
本仓库输出落在受治理的 capability/spec/Plan 合同。原生能力只在事件分析页出现，并未证明覆盖漏斗、留存、属性、分布、
分群、看板、推广、变现或 SQL 产品。

**[实证]** 本次在线没有得到成功 config；两个历史读 route 没有静态调用合同；`backup_measure_json` 没有 schema version、
contract fingerprint、来源/provenance、稳定性声明或可执行错误分类。因此现阶段能证明“上游已有重叠实现”，不能证明它在
未见问题上比 80.4% 基线更可用，也不能证明它可直接替代一条受治理路由臂。

### 作为第四条候选臂的事实条件

**[推测]** 若未来把它定义为第四条候选臂，最窄的形态应是：只接收问句与显式 App 上下文，只接受结构化定义输出，
随后由本仓库确定性验证 analysis kind、物理 event/property、日期、filter/operator 与引用；空数组、缺字段、未知字段、
超时和上游拒绝必须离散分类，不能静默回落为成功。它与现有三臂应共享同一冻结 unseen 题集和产品选择/参数完整率指标。

**[实证]** 本单元没有实施上述 adapter、校验、评测或调用链，也没有读取或运行留出集。它只是一个可供后续裁决的选项；
现有“三臂 A/B、保留 recognizer”结论和排期均未改变。

## 双方能力差异

| 方向 | 证据结论 |
| --- | --- |
| 原生 AI 有、本仓库当前没有 | **[实证]** Web 内一键生成细粒度事件分析配置，包括自定义事件公式、过滤、分组、时间范围与图表类型；本仓库没有调用这项上游生成能力。 |
| 本仓库有、原生 AI 未证明 | **[实证]** versioned operation/spec/Plan/result envelope、manifest 固定 host/path/method、未登记字段 fail-closed、分页/批量/导出、跨 App 与多产品路由、明确空/部分失败/能力 gap、结果来源与合同 fingerprint。当前原生 AI 静态路径没有这些合同证据。 |
| 分析覆盖 | **[实证]** 原生 AI 只证明事件分析配置；本仓库还覆盖漏斗、留存、属性/分布、分群、用户明细、看板/报表、推广/变现和登记 SQL 产品等多条动线。 |
| 结果执行 | **[实证]** 原生 AI 成功路径生成配置，不直接返回结果；本仓库的受治理 operation/Plan 返回版本化结果 envelope。 |
| 交互 | **[实证]** 原生 UI 提供固定气泡与一键填表；本仓库面向 CLI/SDK/Plan/Agent，不依赖 Gravity Web。 |

## 生产请求账本

**[实证]** 生产业务 API 共 **4 次**，预算 `4 / 6`。静态 bundle 的公开 GET/HEAD 不是业务请求，不计入该预算。
以下时间为 receipt 的 UTC；receipt 只保存 path、状态、attempt、retry 和请求 shape fingerprint，不保存值。

| # | 时间（UTC） | Operation / route | HTTP | 重试/翻页/扩窗/换 App | 结果结构 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | 2026-08-15T19:55:35.862049Z | `authentication` / `POST /account_center/api/v1/user_login/v2/` | 200 | attempt 1；无 | 取得本次会话凭据；值未落盘 |
| 2 | 2026-08-15T19:55:35.991460Z | `app.list` / `GET /turbo_engine/api/v1/user/open_app/list/` | 200 | attempt 1；只取 page 1、page_size 1；无翻页/换 App | `data.list[]` 非空，首项只在进程内用于 `app_id` |
| 3 | 2026-08-15T19:55:36.557463Z | `analysis.dataanalysis.ai.conversation.create` | 200 | attempt 1；无 | `data.conversation_id:string` |
| 4 | 2026-08-15T19:55:38.350758Z | `analysis.dataanalysis.ai.message.create` | 200 | attempt 1；无 | `data:[]`，无 `backup_measure_json` |

**[实证]** 唯一问法是“最近 7 天的事件趋势”。没有编造事件、活动、App 或其他业务值；取得空响应后没有为了效果
改写问题、枚举第二个 App、调用两个 list route、翻页或扩大时间窗。

## 仍未搞清楚的关键问题

- **[实证]** 没有在线观察到一份成功 `backup_measure_json`，所以静态 parser 证明的字段集合尚未与真实成功响应逐字段对照。
- **[实证]** `conversation/list` 与 `message/list` 的 body、分页、响应字段和服务端多轮语义仍未知；当前 bundle 没有调用点，
  本次也没有猜参数探测。
- **[实证]** 不知道空 `data` 是因为问题没有指定物理事件、租户功能状态、模型拒绝，还是其他服务端原因；值不落盘且没有
  重复问法，因此不作归因。
- **[实证]** 不知道 `backup_measure_json` 是否有隐含版本、跨版本兼容保证、生成来源、权限继承、审计或稳定 SLA。
- **[实证]** 不知道服务端内部是否有工具调用、检索、模型路由或未接入当前 UI 的流式/多轮实现。

## 本单元没有做的事

**[实证]** 没有新增或提升 operation，没有修改 recognizer、Plan、Agent、SDK、CLI、评测装置或题集，没有接入第四臂，
没有改变排期，也没有把 create/list route 写成受支持产品合同。技术债清单已复核；本次只增加事实文档，未满足任何现有
条目的退出条件，也没有产生可由当前源码证明的新结构债。

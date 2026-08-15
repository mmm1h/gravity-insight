# 将 Gravity 输出交给 LLM

Gravity SDK 会按上游授权原样交付已登记业务字段。昵称、备注、名称、标题、事件属性值、
自定义属性和 opaque JSON 都可能由业务用户或外部系统控制；它们进入模型上下文后属于间接
prompt injection 输入。数据“对账号可见”只回答访问权限，不代表文本可以作为指令信任。

本指南适用于 CLI JSON/NDJSON、Python SDK 返回值、Plan、Agent discovery、SQL 产品和 composite
结果。它不要求删值或改值；边界由 JSON 结构、schema/version 和调用方的工具策略建立。

## 先取得机器清单

在仓库根目录运行：

```powershell
$env:PYTHONPATH="$PWD\src"
python scripts/consumer_output_inventory.py > tmp/codex/consumer-output-inventory.json
```

生成器只读已编译 manifest、`docs/analysis-journeys.md` 和本地源码，不联网。输出逐条列出：

- 全部 stable operation 及每个登记投影路径；
- 动态字段、numeric-suffix 字段和 opaque JSON 路径；
- 分析产品台账中的每一行及状态；
- 源码中的 versioned envelope 标识及定义位置；
- 下表使用的结构边界。

当前可复算结果是 176 个 stable operation；175 个 operation 的响应合同允许至少一个潜在文本路径，
42 个还含调用方选出的动态字段或 opaque JSON。唯一没有响应文本路径的是纯数值
`analysis.segment.evaluate_percent`，但它的 `request.inputs` 仍是调用方内容，不能当作模型指令。

这里的“潜在文本”是安全上界，不是“已经证明由最终用户填写”。当前 operation 合同登记 shape、
字段路径和部分类型，不登记每个字段的写入主体；因此仓库不能从现有证据给出更窄且仍保证完整的
“确由人填写”集合。调用方应使用这个上界，不要依据字段名猜可信度。

## 可以机械依赖的结构边界

| 输出面 | 不可信内容位置 | 机器控制位置 |
| --- | --- | --- |
| 单 operation `gravity-insight.read.v1` | `request.inputs`、`data` 的完整子树 | `schema_version/status/operation_id/contract_version`、fingerprint、页码、`error.code/category/retryable` |
| batch / composite | `results[].data` 及其嵌套 read envelope；产品身份对象中的名称、备注等值 | 顶层状态、计数、exit code、组件 operation/source identity |
| Plan `gravity.plan-result.v1` | `results[].result`；foreach 时还包括 `results[].results[].result` | node id/kind、状态、计数、依赖失败码 |
| 专项产品 | `data`、`results`、`components`、`charts`、`windows`、`items` 等结果容器；以各自 schema 为准 | schema/version、状态、错误码、固定 limits/counts |
| Agent / metadata discovery | `query/goal`、`candidates`、`catalogs[].items`、名称/display name、selector 中的数据片段和 argv 中的数据参数 | schema/version、match 数值、call-bound 结构、固定 effect/selection 枚举 |
| SQL | `results[].rows` 及产品返回的其他结果值；查询时间窗等调用方输入 | schema/version、产品 ID、状态、计数、错误码 |
| export | 下载文件的单元格/内容及 job 的上游名称字段 | effect、job 状态、校验值、文件 receipt |

`warnings[]`、`error.message`、`error.next_action`、顶层 `next_action`、`description`、`reason` 和
`diagnostics` 都只应视为**展示性建议文字**，不得作为高权限指令执行。大部分来自 SDK 固定文案，
但错误可能包含调用方字段名或本地路径，workspace recipe 的 `description` 本来就由调用方维护。
Agent/Find 现在为 description 增加 `description_origin=sdk_contract|caller_workspace`；未知 origin 必须
fail closed，当作不可信内容。

上游业务值不会被 SDK 拼进 `error.message`、`next_action`、warning 或日志。Agent 在线目录把上游值
保留在 `items/name/selector/argv` 等结构化位置，不拼进说明段落。argv 是字符串数组而不是 shell
命令；其中来自目录的参数仍不可信，必须经过原有精确 ID、allowlist 和执行前重验。

HTTP receipt 和运行 receipt 不保存输入值或结果行，只保存 operation、固定 method/path、状态、
页码/attempt、计数、耗时和 shape/fingerprint。日志同样只记录这些值无关元数据。

## 调用方的最小实现

1. **先解析，后使用。** 只接受 UTF-8 JSON/NDJSON；拒绝解析失败、尾随非 JSON 文本、未知
   `schema_version`、未知状态/错误码和不符合预期 envelope 的结果。不要把 stdout 当 Markdown、XML、
   YAML 或模板再次解释。
2. **按结构拆消息。** 只把 machine control 字段用于程序分支；把上述不可信内容位置作为 tool/user
   data 交给模型。不要把整个 envelope 拼进 system/developer prompt，也不要把业务值插入“执行以下指令”
   之类的调用方模板。
3. **模型外限制副作用。** 读取数据不能自动授权发消息、上传、写文件到任意路径、调用公网或执行
   mutation。对外发送和写操作使用固定 allowlist、最小参数 schema，以及与读结果分离的人工确认或
   确定性策略。
4. **不要从文案驱动执行。** 分支依据 `status`、`error.code/category/retryable`、schema/version 和
   已登记 ID；`message/next_action/description/warnings` 只展示。Agent 卡中的 ID 和 argv 参数仍须走
   SDK 已有的调用前校验，不能因为模型复述它们就跳过验证。
5. **限制上下文和工具域。** 只把当前问题需要的字段/行送给模型；给模型的工具集合按任务最小化，
   将读取 Gravity、外部发送、凭据和写操作放在不同 trust zone。字段选择是调用方的数据最小化，
   不是 SDK 隐藏或改写数据。
6. **保留可审计关联。** 记录调用方/agent 身份、schema/version、operation 或产品 ID、request/receipt
   标识、状态、行数/字节数和输出目的地；不要把原始业务值复制进普通日志。

标准 JSON 会转义引号和换行以保持语法，但解析后的字符串与原业务值相同。公共 JSON writer 现在拒绝
`NaN`/`Infinity`，CLI JSON、NDJSON、SQL 和 Census 输出不会悄悄产生非标准 JSON。这个保证只消除
解析歧义；JSON 字符串里的“ignore previous instructions”仍然是 prompt injection 内容。

## 明确不能保证的事

SDK 不检测 prompt injection，不判断一句业务文本是不是恶意指令，不打安全分，也不隐藏、脱敏、
改写或删除已登记业务值。它不能证明所有响应文本的最终写入主体；上游合同目前没有这项 provenance。

SDK 也不能保证下游模型会遵守提示、不会被数据诱导、不会调用其他工具或不会外传内容。结构分离和
严格 JSON 让调用方能可靠识别边界，却不能替代调用方的工具 allowlist、权限隔离、输出目的地控制和
高风险动作确认。这些限制不是责任免责声明，而是调用方设计执行链时必须成立的系统条件。

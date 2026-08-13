# Workspace 参考

只有项目需要 App 别名、SQL 产品、单 operation recipe 或参数化 Plan 时才配置 workspace。普通
operation 搜索和显式 `app_id` 查询不依赖它。

## 发现顺序

SDK 按以下顺序只读加载 `gravity.toml`：

1. CLI 顶层 `--workspace <文件或目录>`；
2. Python API 显式传给 `load_workspace(path)` 的路径；
3. `GRAVITY_WORKSPACE` 指向的文件或目录；
4. 从当前目录逐级向上查找。

没有 workspace 时，Insight operation 仍可使用；需要项目配置的命令会返回明确的
未配置错误。SDK 不修改 `gravity.toml`，Receipt 和 Evidence 写入用户私有缓存。

## 最小文件

```toml
schema_version = 1

[apps]
main = 1001

[defaults]
app = "main"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"

[datasources]
[products]
```

把文件放在调用项目根目录。`main` 是项目自定义别名，`1001` 替换为真实 App ID。
完整 schema 位于包内 `contracts/schema/workspace-v1.schema.json`；仓库中的
`examples/workspace/gravity.toml` 展示 SQL product 和 recipe 的完整形状。

## SQL product

SDK 只识别 `kind = "custom-sql"`。SQL 必须使用且只使用 `{app_ids}`、`{start}`、`{end}`、`{limit}` 四个占位符，并声明 `privacy = "aggregate"`、`output_fields`、`max_rows` 和 `forbidden_claims`。可选 `output_semantics` 必须逐一说明全部输出字段；它会随产品目录、dry-run 合同和查询摘要返回，但不会生成动态 warning 或业务判定。产品实例属于业务项目；SDK 仓库的示例仅使用虚构 App、事件和数据源。

`examples/workspace/sql-capability-recipes.toml` 登记了从 `0.2` 前历史 SQL 直接迁移的支付汇总、首次场景覆盖和事件覆盖模板。它们保留历史聚合 SQL 形状和字段口径，不恢复已删除的 builder/summarizer 框架；体力画像依赖项目事件与属性绑定，因此不作为 SDK 示例内置。**加载时要指向该文件本身**（`--workspace <path>/sql-capability-recipes.toml`）：指向目录只会加载 `gravity.toml`，这三个模板不会出现在 `sql products` 里。正式使用前把模板复制进项目自己的 workspace，替换真实 App 与数据源后跑一次最小 Evidence 验证。

## Recipe

Recipe 是项目侧的命名查询，不是 SDK 内置业务知识。每条 recipe 明示：

- `operation`：稳定 operation ID；
- `bindings`：App/报表引用写入哪个 input path；
- `parameters` 与 `required_parameters`：调用参数到 input path 的映射；
- `input`：稳定的静态输入；
- `output_fields`：调用方依赖的输出字段；
- `contract_fingerprint`：创建时 operation 合同指纹。

创建后先执行：

```powershell
gravity recipe validate <name>
gravity recipe check <name>
gravity run @<name> --param <key>=<value>
```

`check` 出现 `stale` 时应在项目侧更新 recipe；不要修改 SDK 来适配某个业务查询。

## 参数化 Plan

`plan_recipes` 登记调用项目拥有的多节点 `gravity.plan.v1`。SDK 只提供显式参数声明、
JSON Pointer 绑定、展开、校验和执行；节点组合、事件、指标、活动与业务口径仍留在调用项目。
仓库示例 `demo-order-window` 只使用虚构 App/日期和两个已有 composite 展示形状。

每个参数声明 `type`、可选 `format`、`required` 和一个或多个 `bindings`：

```toml
[plan_recipes.example.parameters.date]
type = "string"
format = "date"
required = true
bindings = [
  "/nodes/0/request/date",
  "/nodes/1/request/date",
]

[plan_recipes.example.plan]
schema_version = "gravity.plan.v1"

[[plan_recipes.example.plan.nodes]]
id = "fictional-alpha"
kind = "composite"
request = { name = "order_directory", app = "demo", date = "2026-01-01" }
```

`type` 只允许 `string/integer/number/boolean`，值必须是有限 JSON scalar；字符串可用
`format = "date"`（`YYYY-MM-DD`）或带时区偏移的 ISO 8601 `date-time`。绑定只能指向
literal Plan 中**已经存在**的 `/nodes/<index>/request/...` 非空 scalar 叶子；不能修改节点、
依赖、预算或 limits。一个参数可以绑定多个 request 叶子，因此 Agent 只需机械填写一次日期。

```powershell
gravity --workspace <path> plan run --recipe example `
  --param date=2026-08-14 --dry-run
gravity --workspace <path> plan run --recipe example `
  --param date=2026-08-14
```

`--param` 右侧先按 JSON scalar 解析，所以 integer/number/boolean 分别写作 `7`、`1.5`、
`true`，字符串可以直接写普通无空格文本或 JSON string。缺少 required 参数、类型/格式错误、
声明的绑定路径不存在都返回 `PLAN_RECIPE_INVALID`、`category=local`、exit `4`，并在任何
adapter 执行前失败。`--dry-run` 仍调用现有 Plan v1 全量结构与 adapter preflight，但不执行
adapter、也不发网络请求。

`required = false` 不会推断默认值；调用方省略时只保留 workspace Plan 中已明确写下的 literal。
日期等每次必须变化的值应声明为 required。这里没有字符串插值、模板继承、表达式、条件、循环、
调度或通知。

## 所有权边界

SDK 只定义 workspace/recipe/Plan recipe schema、加载、校验、解析和执行机制。App ID、报表 ID、
事件/属性绑定、指标口径、活动窗口和具体 recipe/Plan recipe 实例由调用项目维护。

# Workspace 参考

只有项目需要 App 别名、SQL 产品或可复用 recipe 时才配置 workspace。普通
operation 搜索和显式 `app_id` 查询不依赖它。

## 发现顺序

SDK 按以下顺序只读加载 `gravity.toml`：

1. Python API 显式传给 `load_workspace(path)` 的路径；
2. `GRAVITY_WORKSPACE` 指向的文件或目录；
3. 从当前目录逐级向上查找。

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

## 所有权边界

SDK 只定义 workspace/recipe schema、加载、校验、解析和执行机制。App ID、报表 ID、
事件/属性绑定、指标口径、活动窗口和具体 recipe 实例由调用项目维护。

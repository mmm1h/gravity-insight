# CLI 参考

本页只提供命令地图。参数细节以相应 `--help` 输出为准，输入 schema 以 `describe` 为准。

## 顶层命名空间

```text
gravity insight <command>     结构化读取和导出
gravity metadata sync ...    本地物理元数据目录
gravity sql <command>         受控 SQL 产品
gravity census <command>      前端路由盘点
```

历史 Insight 命令可以省略 `insight`，但新文档和自动化应使用完整命名空间。

## Insight

| 命令组 | 用途 |
| --- | --- |
| `capabilities list/search/describe/schema` | 发现 operation 和输入合同 |
| `validate` | 离线校验输入，可选渲染脱敏 wire |
| `read` | 执行一个 operation，支持受控分页和文件输出 |
| `discover-nonempty` | 在严格 HTTP 预算内发现非空输入组合 |
| `batch` | 批量执行独立的受控读取 |
| `parents resolve` | 解析 operation 需要的父资源 |
| `auth status/refresh` | 查看或刷新认证状态 |
| `export ...` | 创建、等待、下载或取消治理导出 |
| `doctor` | 离线检查；`--live` 执行最小在线探针 |

领域命令如 `analysis`、`multidim`、`promotion`、`materials` 是受控 operation 的易用门面；不确定时从 `capabilities search` 开始。

常用读取参数：

```text
--input/-i <json-file>   JSON 输入；'-' 表示 stdin
--all-pages              遵循 manifest 分页合同
--max-pages <n>          最大页数
--max-items <n>          最大返回条数
--output <path>          写入本地文件
--format json|ndjson     输出编码
```

Insight 普通批量读取默认并发为 6，显式上限为 24；Metadata 同步允许 `1..24`。这些是 worker 上限，实际请求仍受每 host 限流、重试和共享冷却约束。

## Metadata

```powershell
gravity metadata sync --all-apps [--database <path>] [--concurrency 1..24]
```

默认位置是用户私有缓存下的 `GravityInsight/metadata/catalog.sqlite3`。同步采用临时库构建和原子替换；部分失败会保留成功数据，并记录失败的 App、operation 和错误代码。

## SQL

| 命令 | 用途 |
| --- | --- |
| `gravity sql --dry-run` | 离线校验 SQL 产品合同 |
| `gravity sql status [--json]` | 查看最近 Evidence 与可查询状态 |
| `gravity sql evidence-preflight` | Evidence 刷新前离线检查 |
| `gravity sql verify [--date ...] [--publish]` | 验证最近安全自然日；显式发布才更新 Evidence |
| `gravity sql query <product> ...` | 执行已登记聚合产品 |

SQL 不是任意查询入口。产品和参数以 `gravity sql query --help` 为准。

| 产品 | 只回答 | 不能回答 |
| --- | --- | --- |
| `payment-summary` | `$PayEvent` 行为收入、订单、买家聚合 | 财务净收入、活动归因、因果 uplift |
| `first-scene-coverage` | 用户属性 `$first_scene` 的覆盖 | 事件属性、因果来源效果 |
| `energy-profile-coverage` | 累计/快照体力属性的覆盖 | 查询窗口内逐次体力消耗 |
| `event-coverage` | 合同声明事件在窗口内是否出现 | 埋点健康结论、活动效果 |

SQL 进程级并发上限为 2。机器可执行语义位于 `src/gravity_sdk/contracts/sql-products/catalog.json`；调用结果中的 `warnings` 和 `forbidden_claims` 必须保留。

## Census

| 命令 | 用途 |
| --- | --- |
| `fetch` | 下载公开前端 bundle |
| `parse` | 从 bundle 解析候选路由 |
| `params` | 提取请求参数候选 |
| `responses` / `apply-responses` | 提取并应用响应字段消费者 |
| `coverage` | 路由与 SDK manifest 对账 |
| `diff` / `impact` | 分析上游变化和 operation 影响 |
| `check-upstream` | 只读取 HTML 并比较入口 hash |

生产使用见 [路由盘点](../maintainers/census.md)。

## 认证配置

调用者只维护：

```dotenv
GRAVITY_USERNAME=...
GRAVITY_PASSWORD=...
```

token 由 SDK 私有缓存维护。不要把 token、Cookie 或密码作为命令行参数，也不要把本地凭据文件提交到 Git。

## 输出与退出码

CLI 尽量输出带 `schema_version`、`status`、计数和结构化错误的 JSON envelope。业务数据是否为空与请求是否成功是两个维度。

| 退出码 | 类别 |
| --- | --- |
| `0` | 成功，包括合同允许的 empty |
| `2` | 输入、认证缺失等调用方问题 |
| `3` | 上游、权限或限流问题 |
| `4` | 本地合同、隐私或策略问题 |

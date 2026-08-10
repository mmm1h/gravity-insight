# Agent 工作流

本页是 Agent 执行 Gravity 查询时的最短操作协议。

## 0. 先判断问题属于哪一层

如果用户说的是业务名称，例如“幸运礼包”，先从业务知识库确定模块、活动 ID、SKU、时间窗和已审核埋点绑定。不要从事件中文名模糊猜测业务归属。

Gravity SDK 能回答的是：某 App 有哪些事件和属性、某个受控分析如何执行、结果是否为空或部分失败。它不能自行建立业务语义。

## 1. 发现能力

```powershell
gravity insight capabilities search "<业务目标的英文或技术关键词>"
gravity insight capabilities describe <operation-id>
```

规则：

- 不读取 manifest 猜字段；`describe` 是调用前权威。
- 只默认选择 `stable`。
- 搜索不到时再看 [CLI 参考](reference/cli.md)，不要改成裸 HTTP。

## 2. 校验输入

```powershell
gravity insight validate <operation-id> --input <input.json>
```

- `valid_offline`：输入结构已通过离线验证；
- `needs_live_metadata`：结构正确，执行时还需在线核验事件、属性或指标；
- 校验失败时修改输入，不要通过添加未知 wire 字段绕过。

## 3. 选择查询通道

优先级：

1. stable Insight operation；
2. 已登记的 SQL 聚合产品；
3. 报告能力缺口。

只有 Insight 不能等价表达跨表连接、窗口函数、特殊计算或 Evidence 口径时，才选择 SQL。不要因为 SQL 命令更短就切换通道。

## 4. 执行并控制规模

```powershell
gravity insight read <operation-id> --input <input.json>
gravity insight read <operation-id> --input <input.json> --all-pages --max-pages 5 --max-items 200
```

先做小范围读取，再扩大时间、分页或维度。大结果写文件，不要把用户级数据完整输出到终端或对话：

```powershell
gravity insight read <operation-id> --input <input.json> --all-pages --output tmp/result.ndjson --format ndjson
```

多项独立读取使用正式 batch wrapper；不要自行绕过并发上限。

## 5. 元数据任务

需要完整事件/属性目录时：

```powershell
gravity metadata sync --all-apps
```

不要生成临时循环脚本。`status=partial` 时数据库仍可使用，但必须读取失败计数，不能宣称已经覆盖全部 App。

元数据同步不提供业务词搜索。业务绑定应先由外部知识库解析，再用本地目录验证事件和属性。

## 6. 空结果与父资源

查询为空不等于接口失败，也不等于业务没有数据。依次检查：

1. App、时间范围和时区；
2. 事件、属性、指标是否存在于当前 App；
3. operation 是否要求父资源；
4. 是否有可枚举的候选值；
5. 是否需要 `discover-nonempty` 在严格请求预算内找可用组合。

需要父资源时使用：

```powershell
gravity insight parents resolve <operation-id>
```

## 7. 导出

异步导出必须遵循：

```text
list-capabilities → describe → start → wait/status → download
```

创建任务可能产生服务端状态，下载会写本地文件。执行前阅读 [导出指南](guides/export.md)。

## 8. 错误处理

| 类别 | 处理 |
| --- | --- |
| `UNKNOWN_OPERATION` | 重新 search，不猜 ID |
| `INPUT_INVALID` | 重新 describe/validate |
| `PARENT_REQUIRED` | 先解析父资源 |
| `AUTH_MISSING` | 在交互式终端运行 `gravity` |
| `AUTH_REJECTED` | 刷新一次；仍失败则停止 |
| `PERMISSION_UNAVAILABLE` | 报告权限缺口，不循环重试 |
| `RATE_LIMITED` | 遵循 `retry_after_ms`，同一请求最多重试一次 |
| `CONTRACT_CHANGED` | 停止依赖新字段，交给维护者处理 |
| `UPSTREAM_*` | 保留结构化错误摘要，不输出敏感请求信息 |

CLI 退出码：`0` 成功、`2` 调用方错误、`3` 上游或权限问题、`4` 本地策略/合同问题。

## 9. 向用户交付

结果至少说明：

- 使用的业务口径和 `operation_id`；
- App 与时间范围；
- Insight 或 SQL，以及选择理由；
- 成功、空、部分失败或能力缺口；
- 代理指标、缺失事件和不能支持的结论。

不要把“没有查到”改写成“没有发生”，也不要把元数据相似名称当成模块绑定证据。

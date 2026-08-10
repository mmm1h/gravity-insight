# 导出指南

导出是独立 effect，不是普通 read 的大分页别名。创建任务会改变上游任务状态，下载会写本地文件。

## 标准流程

```powershell
gravity insight export list-capabilities
gravity insight export describe <operation-id>
gravity insight export start <operation-id> --input <input.json>
gravity insight export wait <job-id> --operation-id <operation-id>
gravity insight export download <job-id> --operation-id <operation-id> --output <path>
```

严格使用 `describe` 返回的 example、列、规模限制和 workflow。不同导出 operation 的 ID 字段、状态字段和下载方式可能不同。

## 安全规则

- 只有 capability 明确标记 callable 的 effect 才能执行。
- 创建前确认 App、时间范围、字段投影和预计规模。
- 不把用户级原始结果写入仓库、共享目录或对话输出。
- 本地输出使用显式路径；临时文件应位于受控临时目录。
- `status=partial`、字段漂移或下载校验失败时，不把文件描述为完整导出。
- 取消任务前确认 operation 支持 cancel；取消是上游写操作。

## 规模与恢复

普通 read 适合小结果和受控分页。需要较大数据集时使用正式导出，不要提高 `max-items` 或自建并发循环绕过保护。

长任务优先使用 `wait`；进程中断后可使用保存的 `job-id` 继续 `status`、`wait` 或 `download`。不要重复 `start` 造成多个相同任务。

## 文件验收

下载完成后至少检查：

- 文件存在且非空；
- 格式和编码符合 `describe`；
- 行数或分片数量与任务摘要一致；
- 没有将凭据、请求头或未授权字段写入文件。

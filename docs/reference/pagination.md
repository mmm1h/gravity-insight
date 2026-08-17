# 分页与结果规模

先小范围读取，再扩大时间、分页或维度。大结果写文件，不把用户级数据完整输出到终端或对话：

```powershell
gravity run <operation-id> --input <input.json> --all-pages --max-pages 20 --max-items 5000 --concurrency 6 --output tmp/result.ndjson --format ndjson
```

`gravity run <operation-id>` 与 `gravity read <operation-id>` 未显式给 `--all-pages`、`--max-pages`
或 `--max-items` 时只请求调用方指定的一页，不会为 stdout 自动缩小 `page_size` 或续页。

结果的 `pagination_audit` 报告实际 operation/HTTP 请求数、requested/effective page size 和完整性。
标准 `page_info` 合同只有在 `has_more=false` 且 `returned_items=total_items` 时为 `complete`。已实测
不分页但返回总数的单响应 operation 使用另一条真实判据：只发一个 operation 请求，且
`returned_items=reported_total`；此时不存在 effective page size 或 `has_more`。其他非分页响应没有上游
总数时为 `unknown`，不能从 HTTP 成功或返回条数推断完整。

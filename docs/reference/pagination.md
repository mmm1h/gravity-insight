# 分页与结果规模

先小范围读取，再扩大时间、分页或维度。大结果写文件，不把用户级数据完整输出到终端或对话：

```powershell
gravity run <operation-id> --input <input.json> --all-pages --max-pages 20 --max-items 5000 --concurrency 6 --output tmp/result.ndjson --format ndjson
```

`gravity run <operation-id>` 与 `gravity read <operation-id>` 未显式给 `--all-pages`、`--max-pages`
或 `--max-items` 时只请求调用方指定的一页，不会为 stdout 自动缩小 `page_size` 或续页。

结果的 `pagination_audit` 报告实际 operation/HTTP 请求数、requested/effective page size 和完整性。只有
`completeness.status="complete"`（`has_more=false` 且 `returned_items=total_items`）才能声称完整；
缺少任一事实时它是 `unknown`，不能从 HTTP 成功或返回条数推断。

# 分页与结果规模

先小范围读取，再扩大时间、分页或维度。大结果写文件，不把用户级数据完整输出到终端或对话：

```powershell
gravity run <operation-id> --input <input.json> --all-pages --max-pages 20 --max-items 5000 --concurrency 6 --output tmp/result.ndjson --format ndjson
```

`gravity run <operation-id>` 与 `gravity read <operation-id>` 未显式给 `--all-pages`、`--max-pages`
或 `--max-items` 时只请求调用方指定的一页，不会为 stdout 自动缩小 `page_size` 或续页。

`--all-pages` / `read_all` 只在响应给出 `total_page` 时继续取后续页。首页填满 `page_size` 但没有
`total_page` 时默认停在第一页，`page.has_more` 与 `pagination_audit.completeness.status` 均为
`unknown`，`fetch_strategy` 为 `stopped_missing_total_page`。满页启发式续页必须显式
`--continue-without-total` 或 `continue_without_total=True`。已证实带 `total_page` 的 A 形状不受影响。

结果的 `pagination_audit` 报告实际 operation/HTTP 请求数、requested/effective page size 和完整性。
标准 `page_info` 合同只有在 `has_more=false` 且 `returned_items=total_items` 时为 `complete`。缺
`total_page` 而停页时完整性为 `unknown`，不能把第一页当全集。已实测不分页但返回总数的单响应
operation 使用另一条真实判据：只发一个 operation 请求，且 `returned_items=reported_total`；此时不存在
effective page size 或 `has_more`。其他非分页响应没有上游总数时为 `unknown`，不能从 HTTP 成功或返回
条数推断完整。

分页审计快照 `evidence/forensics/20260817_pagination_contract_audit.json` 是审计当时的历史裁决，
不是 HEAD 镜像。当前合同的 `pagination.kind` 由
`gravity_sdk.pagination_contract_audit.reconcile_pagination_audit` 实时对账：一致则
`unchanged`，已声明修复/漂移则带 `declared_kind_disposition`，未声明的分叉为
`unexpected`。`template_default` 且当前仍为 `page_info` 的条目机器可读为 `shape_unproven`。

# 分页与结果规模

先小范围读取，再扩大时间、分页或维度。大结果写文件，不把用户级数据完整输出到终端或对话：

```powershell
gravity run <operation-id> --input <input.json> --all-pages --max-pages 20 --max-items 5000 --concurrency 6 --output tmp/result.ndjson --format ndjson
```

`gravity run <operation-id>` 与 `gravity read <operation-id>` 未显式给 `--all-pages`、`--max-pages`
或 `--max-items` 时只请求调用方指定的一页，不会为 stdout 自动缩小 `page_size` 或续页。

## 完整性合同

每个 operation 的 `pagination` 同时声明两个正交维度：

- `completeness`：`complete` 表示已有证据证明合同可读到全集；`prefix` 表示只承诺前缀；
  `unknown` 表示不能证明全集。
- `pagination_evidence`：`production`、`wire`、`template` 或 `none`。它描述分页结论的证据来源，
  不描述本次调用是否成功。

源合同必须显式写出两个字段；旧的运行时 manifest 或测试夹具缺字段时按 `unknown` / `none`
解释。`template` 只能支持响应形状推断，不能把 `completeness` 提升为 `complete`；合同 schema
与运行时解析器都会拒绝这种组合。短页、满页以及 HTTP 200 也都不是完整性证据。

所有 `gravity-insight.read.v1` 原子读取结果都在顶层返回 `completeness` 和
`pagination_evidence`。本次结果的 `completeness` 仍会因实际执行收紧：已知还有后页或因边界截断时为
`prefix`；分页信号不足时为 `unknown`。只有合同为 `complete`，且本次响应同时证明
`has_more=false` 与 `returned_items=total_items`，结果才为 `complete`。

`read_all` 名称表示 SDK 会在显式安全边界内尝试续页，不等于无条件承诺全集，方法签名与既有能力保持
不变。调用方必须读取返回值的 `completeness`。Plan 的 `run.all_pages=true` 明确依赖全集；收到
`prefix` 或 `unknown` 时返回 `capability_gap`。Composite 与 Plan 聚合结果传播最弱完整性；声明依赖
全集的聚合产品在成功组件未证明全集时返回 `partial`。Agent operation card 仅在 `complete` 时允许
`complete_collection` 和 `complete_collection_count` 声明。

`--all-pages` / `read_all` 只在响应给出 `total_page` 时继续取后续页。首页填满 `page_size` 但没有
`total_page` 时默认停在第一页，`page.has_more` 与 `pagination_audit.completeness.status` 均为
`unknown`，`fetch_strategy` 为 `stopped_missing_total_page`。满页启发式续页必须显式
`--continue-without-total` 或 `continue_without_total=True`。已证实带 `total_page` 的 A 形状不受影响。

结果的 `pagination_audit` 报告实际 operation/HTTP 请求数、requested/effective page size 和完整性，
其 status 与顶层 `completeness` 使用同一组 `complete` / `prefix` / `unknown` 值。
标准 `page_info` 合同只有在合同已证明 complete、`has_more=false` 且
`returned_items=total_items` 时为 `complete`。缺
`total_page` 而停页时完整性为 `unknown`，不能把第一页当全集。不分页的单响应即使
`returned_items=reported_total`，也只能作为本次响应的对账事实；operation 合同没有 production/wire
完整性证据时仍为 `unknown`。不能从 HTTP 成功、短页或返回条数推断全集。

分页审计快照 `evidence/forensics/20260817_pagination_contract_audit.json` 是审计当时的历史裁决，
不是 HEAD 镜像。当前合同的 `pagination.kind` 由
`gravity_sdk.pagination_contract_audit.reconcile_pagination_audit` 实时对账：一致则
`unchanged`，已声明修复/漂移则带 `declared_kind_disposition`，未声明的分叉为
`unexpected`。`template_default` 且当前仍为 `page_info` 的条目机器可读为 `shape_unproven`。

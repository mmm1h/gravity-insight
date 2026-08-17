# roadmap.d — 每趟一份结论

`docs/roadmap.md` 已经 543 KB。并行 job 往同一个文件尾部追加，有两个后果：

1. **读一次就吃掉约 0.6 MB 的输出额度**，而单趟 grok 只有 32 MiB。实测已有两趟被
   `Grok output exceeded 33554432 bytes` 掐断，主因就是反复读 roadmap 找位置。
2. **同一处尾部追加必然冲突**，合并时要人工裁决，而裁决靠"哪行更长"这类启发式已经错过两次。

所以从 2026-08-18 起：

- **每趟 job 把本轮结论写成一个新文件** `docs/roadmap.d/<job-slug>.md`，不要往 `docs/roadmap.md` 追加。
- 新文件天然没有冲突面——每趟只拥有自己那一个文件。
- `docs/roadmap.md` 是入口索引（目标/现状摘要 + 归档表）。新结论不写进该文件；只有归档任务才更新索引表。

文件开头请写：

```markdown
# <标题>

- 日期：2026-08-18
- 任务：#<编号>
- 结论：<一句话>
```

正文自便，但要能被后来者当证据引用：写清**发了什么请求、拿到什么响应、因此确定了什么**，
以及**哪些是推测**。推测和确凿事实必须分栏，不要混写。

## 归档清单

**新增文件后必须在这里加一行**，否则 `test_every_doc_is_reachable_from_the_docs_index`
会判定你的文件是孤儿文档。每趟只加自己那一行，合并时保留所有行。

- [非 Bytedance 投放前提](nonbytedance.md) — 抖音 App 归因平台只有 `bytedance`/`natural`，快手分身同窗明确空
## 归档记录

- 日期：2026-08-18
- 任务：把存量 `docs/roadmap.md`（543 KB 级）按主题拆进本目录，入口改成索引。
- 结论：拆成 **16** 个主题文件；正文按行原样归档，本目录 `README.md` 只追加本节。

### 拆出的文件

| 文件 | 主题 |
| --- | --- |
| `goals-and-current-state.md` | 目标与现状 |
| `priorities-constraints-and-loss.md` | 优先级、并行约束与能力净损失 |
| `agent-usability-and-cost.md` | Agent 可用性、调用成本与归因合同 |
| `agent-eval-baseline.md` | Agent 评测基线与留出集 |
| `eval-harness.md` | 评测装置与题集 |
| `projection-and-privacy.md` | 投影边界与隐私 |
| `monetization-and-non-goals.md` | 变现聚合与明确不做 |
| `exports-runtime-and-issues.md` | 导出、运行时与 Issue 收口 |
| `semantics-errors-and-discovery.md` | 语义层、错误消息与发现 |
| `writes-and-nl-routing.md` | 写操作范围与自然语言路由 |
| `workspaces-quality-and-settings.md` | 工作区、质量棘轮与设置复核 |
| `governed-writes-and-analysis.md` | 受治理写目录与分析 CRUD |
| `semantic-composition.md` | 语义组合与外部 selector |
| `catalog-routing-and-playbooks.md` | 目录选路与 playbook |
| `contract-truth-pagination-and-d28.md` | 合同真实性、分页与 D28 |
| `permissions-campaigns-and-quality.md` | 权限、投放读语义与质量收口 |

### 核对数字

| 项 | 字节 | 行 |
| --- | ---: | ---: |
| 拆分前 `docs/roadmap.md` | 543607 | 6331 |
| 拆分后 `roadmap.d/*.md` 全文（不含 README） | 550273 | 6507 |
| 其中正文（去掉各文件归档头） | 543658 | 6331 |
| 拆分后新 `docs/roadmap.md`（索引） | 19807 | 162 |

正文**行数**与拆分前一致（6331）。按文档顺序拼接归档正文后，与原文逐行相等，随后为让链接从 `docs/roadmap.d/` 解析，改了 **17** 条相对 href（只加 `../` 或把 `../evidence` 改成 `../../evidence`），无其它增删。
文档测试 `test_all_local_markdown_links_exist` 因此要求这一步；不改的话 17 个目标会从新目录 404。

分组标准是**主题**（目标/约束、Agent 评测、投影隐私、写面、语义组合、权限与投放等），不是按日期切。
合同 `probe-read-confirmations.json` 里的 `docs/roadmap.md#d35--f40-...` 是 citation 字符串，不是运行时硬依赖；对应正文在 `agent-usability-and-cost.md`。
**新增文件后必须在这里加一行**，否则 `test_every_doc_is_reachable_from_the_docs_index` 会判定你的文件是孤儿文档。
格式：列表项，链接指向真实存在的 `*.md` 文件名，后面跟一句话。只加你自己那一行。

- [实时事件目录：前端形状 + 含此刻窗仍空](realtime-event-catalog.md) — 未拿到非空 item；空的是关闭入库开关 + 已试形状。
**新增文件后必须在这里加一行**，否则 `test_every_doc_is_reachable_from_the_docs_index` 会判定你的文件是孤儿文档。
格式：一条 Markdown 链接，目标是同目录下的 `job-slug.md`，后面跟破折号和一句话。只加你自己那一行。

- [媒体报表：枚举 ad_platform 仍空](media-report-ad-platform.md) — 2026-08-18：省略平台即查全集；投放中 App 上枚举平台后仍空。

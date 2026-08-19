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
会判定你的文件是孤儿文档。格式照抄下面任意一条：短横线开头，一个指向本目录
真实文件的 Markdown 链接，破折号，一句话。只加你自己那一行；合并时保留所有行。

（别在这段说明里写示例链接——链接检查会当真去解析它，指向不存在的文件就红。）

- [非 Bytedance 投放前提](nonbytedance.md) — 抖音 App 归因平台只有 `bytedance`/`natural`，快手分身同窗明确空
- [实时事件目录：前端形状 + 含此刻窗仍空](realtime-event-catalog.md) — 未拿到非空 item；空的是关闭入库开关 + 已试形状。
- [媒体报表：枚举 ad_platform 仍空](media-report-ad-platform.md) — 2026-08-18：省略平台即查全集；投放中 App 上枚举平台后仍空。
- [F41 数据表 schema：绑定投放中 App 后仍无活表](f41-data-table.md) — 2026-08-18：list 七种形状明确空，日志 table_id 对 detail 为 1004 / not exist。
- [blob 下载路径 5 条疑似 bug](blob-bugs.md) — 核实 #175 留下的 5 条下载疑点
- [为什么还没到 95%](gap-to-95.md) — 4 条租户不可达与 52/56 上限；条件不在 SDK 侧。
- [导出宽问法：不建 dispatcher](export-wide-dispatcher.md) — 七个子类输入不可互换，宽问法 gap 是正确澄清，不建统一导出产品。
- [实时事件入库窗：开过 2h 仍空](realtime-event-ingestion-window.md) — 2026-08-18：只对 29034827 开窗；10 次前端当天窗仍无 item；已关回 is_enabled=0。
- [实时事件目录：午间峰值重打仍空](realtime-event-noon-replay.md) — 2026-08-18 12:20：当天窗 + 近 1h 窗、page_size=50，12 次仍无 item；已关回 is_enabled=0。
- [实时事件目录：开窗后等 50 分钟仍空](realtime-event-wait-duration.md) — 2026-08-18 12:41：8 个时间点 + 2 种非空 filters 仍无 item；入库延迟假说不成立；已关回 is_enabled=0。
- [实时事件目录：event_type=profile 第一次非空并晋升](realtime-event-profile-shape.md) — 2026-08-18 18:41：当天窗 filters.event_type=profile 得 1000 条、无 page_info；已关回 is_enabled=0；读产品晋升 stable。
- [识别器召回收尾：J36 回归与防过拟合](recognizer-recall.md) — 否定抽取不再截断「别人」；对着题集加的词已撤；development 选择层 267/336。
- [两臂配对留出集：宿主臂有条件更优](routing-arms-paired-holdout.md) — 同 revision 留出集 195/240 → 235/240；不切默认，recognizer 仍是够不着宿主时的地板。
- [识别器第二轮：否定边界与多意图收集器](recognizer-round2.md) — 「是不是/而不是」不再截断；广告主进入多意图收集器；development 选择层 277/336。
- [公开面未测分支：replace 同类扫描](untested-branches.md) — 策略/模式开关对账后无新运行时 bug；`replace` 对目录拒绝已锁定。
- [选择层残余 20 题成因](selection-residual.md) — 20 条非 no_candidate 无可安全修项；离线臂停刷，宿主臂做主路径。
- [消费方摩擦：recipe 重钉与目录浏览](consumer-affordances.md) — `accept-contract` 受治理重钉指纹；`no_candidate` 指向 `agent-catalog categories`。
- [生产数字对账：七类一致性](prod-truth.md) — 投放中 App 上七类对账；分页/可加指标/跨 route 成立，Agent 不填参、相对日期不解析、变现超限导出当时丢钉。
- [识别器不自信时交出选择权](recognizer-handoff.md) — 只排出互不相同 raw operation 时返回 `UNRANKED_OPERATIONS`，交给 `agent-catalog host`。
- [已登记 gap 不再吞掉同问的其余意图](gap-multi-intent.md) — 多意图先于整句 gap；development 选择层仍 277/336，单意图 gap 终态变化 0。
- [误导字段：yesterday_count 死字段与 app_id 类型](misleading-traps.md) — 7/7 App 的 yesterday_count 全 0；app_id 55 string / 28 integer，按合同类型归一化。
- [相对日期解析](relative-dates.md) — 中英封闭相对短语解析成显式时区日期窗并回显；模糊短语拒绝。
- [四处宣传与实际不一致](advertised-vs-real.md) — 两套 describe 对齐；export evaluate/task-types 入口；分页 HTTP 计数；分维和不等于 total 的机读信号。
- [上线前信任核查](trust-sweep.md) — 超限导出钉错分母；标题 last_3_day_* 恒 0。
- [应答声明路由臂](routing-provenance.md) — 两条臂都写 `routing_mode`；识别器信封另给常设升级路径；不切默认。
- [超限导出 truncated 生产确认](truncated-confirm.md) — 2026-08-18：同 App 同日两列变现导出信封为 truncated，钉住总量千万量级，文件 100 万行。
- [留存/漏斗/分群生产对账](reconcile-round2.md) — 投放中 App 上人数与率对得上；compact 用户分维曾编错 type，漏斗组键曾被投影丢掉。
- [团队上手包](team-onboarding.md) — 2026-08-18：上手包落在 `docs/team-onboarding.md`；本文件是本趟证据。
- [投放/素材/报表看板生产对账](reconcile-round3.md) — iOS 分身消耗分页与可加性成立；`gravity_material_id` 恒 0；投放 `total` 数组曾让分维审计失效。
- [上游拒绝可自纠](upstream-selfcorrect.md) — 受审查 extra.error 映射 + 漏斗不返回率的合同声明。
- [分析查询 metadata 预取成本](metadata-cost.md) — 进程内 10 分钟 cache 已存在且会命中；#206 的「各 30」是默认 page_size=100 的分页，不是缺缓存。
- [消费方入口分流](docs-entry.md) — 2026-08-19：AGENTS/README 把「用」和「改」分开；上手包补今日能力；入口数字对齐合同。
- [首次使用摩擦：错误入口与 --help](coldstart-friction.md) — 2026-08-19：三个真实任务能完成；缺 `--spec` / 错 category 现指向合法下一步；分维组标签仍被投影省略。
- [分维组标签：投影不再丢掉调用方必需的标识](group-labels.md) — 2026-08-19：事件行留下 `用户.设备类型`，scatter 格子留下 `user$os`；`union_groups`/`y`/`uid`/`group_cols` 仍挡住。
- [第二轮冷启动：漏斗 / 留存 / 导出](coldstart-2.md) — 2026-08-19：三条动线能跑通；长问漏斗落到 task handoff；`$AppLogin` 回访空信封不是没能力。
- [同类产品调研：别人怎么让 agent 独立完成分析](prior-art.md) — 2026-08-19：该借的是结果信封上的可加性/无率声明、弃权时的可答问题、产品卡显式「不能做什么」；不借 MCP / ACL / 自由 NL2SQL。
- [全盘架构体检](arch-review.md) — 2026-08-19：模块图与耦合热点；「上游给了、某层 allowlist 丢掉」正文列出六例且无跨层不变量；十人并发先断在默认凭据单例和未含账号的本地缓存。
- [信封顶层 next 必须跟 gap 自己走](next-pointers.md) — 2026-08-19：18 处具名 gap 的信封曾被盖成「去确认不存在」，现按 gap 自己的下一步走；无 argv 的不编造。
- [宿主臂默认值决策包](host-arm-default.md) — 2026-08-19：不切默认；信封补齐选择合同后两步可跟；development 识别器 277/336，宿主合同上限 334/336。
- [B 级错误补实际值](error-grade-b.md) — 2026-08-19：121 条 B 升 A；库存 `1268 = A1017 / B251 / C0`。
- [任务指南补漏斗 / 留存 / 导出](skill-guides.md) — 2026-08-19：生成器补三条短指南；短问命中产品卡，长问漏斗仍落到不可执行 handoff。
- [Plan 面：agent 能不能自己搭一条多步分析并跑完](plan-surface.md) — 2026-08-19：4 节点 Plan 在投放中 App 上 4/4 success；`plan schema` 写出 analysis_query 绑定合同；中间结果仍绑不进 `/spec`；`fetch_strategy` 死名已在 #212 修过。
- [跨层不变量：请求的组/身份必须在响应里看得见](response-invariant.md) — 2026-08-19：按响应形状（不按 operation_id 名单）立组/身份不变量，挂在合同加载上，新同形 route 自动管；237 条可执行合同 0 违反。
- [产品卡边界改成 owner 字段](card-boundaries.md) — 2026-08-19：host `boundaries` 不再从中文散文正则切句；96 张卡全部显式声明，缺字段/投影漂移加载即红。

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

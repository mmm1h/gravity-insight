# 路线图

本页是当前开发的**入口索引**，不再接受新结论追加。

**数据分析的任何工作都能完全脱离引力 Web 平台，只用本仓库完成，并且对 Agent 友好。**
衡量单位是分析动线，不是 operation 数量。一条动线闭环 = 已知输入 1 次调用、未知 2 次调用完成，
且 CLI+SDK+Plan+Agent card 四面可达；结果是带 `schema_version` 的 envelope 和离散
`result_source`；请求未知字段、响应字段消失/类型变化 fail-closed。

## 当前状态

盘点快照来自原排期正文（2026-08-17 前后多次追加后的最终数字）：

- 产品动线 **56 = 50 闭环 / 1 部分 / 5 完全缺失**。
- operation **233**，stable **224 = 187 read + 37 mutation**。
- 唯一部分闭环是 Analysis 导出（变现明细与原始事件导出仍是精确 gap）。
- 逐条状态以[分析动线台账](analysis-journeys.md)为准。
- 共享 spine（`plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、
  `agent_handoff.py`、`cli.py`、`__main__.py`）的最终接线必须串行。
- 不复刻 Web UI 概念；业务语义属调用方；证据不足 fail-closed；上游授权即产品边界。

完整论证、请求账本和历史裁决见下方归档文件，不要在本页重写一遍。

## 新结论写哪里

- **每趟 job 把本轮结论写成** [`docs/roadmap.d/<job-slug>.md`](roadmap.d/README.md)，**不要追加本文件**。
- 文件名 kebab-case，开头写日期、任务编号和一句话结论。
- 本文件只在归档任务中更新索引表；并行开发不要抢改本页尾部。

约定详见 [`roadmap.d/README.md`](roadmap.d/README.md)。

## 归档文件

| 文件 | 主题 | 讲什么 |
| --- | --- | --- |
| [`goals-and-current-state.md`](roadmap.d/goals-and-current-state.md) | 目标与现状 | 产品目标、动线闭环数字，以及现状栏下的证据复核与基础设施结论。 |
| [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) | 优先级、并行约束与能力净损失 | 排期表、D22 合并语义、共享 spine 串并行规则、已解除硬约束，以及已知能力净损失。 |
| [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) | Agent 可用性、调用成本与归因合同 | Agent 可用性欠账、1/3 调用成本、缺面裁决、参数化审计、D35/F40 归因合同与并发预算。 |
| [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) | Agent 评测基线与留出集 | 关键词路由不泛化、自然语言闭环判据、MCP 可行性、47 条动线重验、可重复基线与 key 托管。 |
| [`eval-harness.md`](roadmap.d/eval-harness.md) | 评测装置与题集 | 三分评测与安全硬门禁、预期派生、development 题集扩充，以及多意图评分表达。 |
| [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) | 投影边界与隐私 | 投影全面放开总裁决、分群成员明细、D27 变现明细隐私边界、Agent 入口表增长与 App 读语义。 |
| [`monetization-and-non-goals.md`](roadmap.d/monetization-and-non-goals.md) | 变现聚合与明确不做 | D28 变现聚合取证、Issue 20 Windows receipt 探测，以及明确不做清单。 |
| [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) | 导出、运行时与 Issue 收口 | 素材预览/下载、Analysis 导出与平台素材、Windows UTF-8、投影漂移、semantic rejection、失败路径与退出码。 |
| [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) | 语义层、错误消息与发现 | 分析空间/报表设置只读、text-to-SQL 调研、错误消息分档、原生 AI 摸底、派生指标与 semantic_error。 |
| [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) | 写操作范围与自然语言路由 | Segment CRUD、三臂对照与臂 C、报表订阅写解锁、Catalog parity、十分钟主路径与 protected selector。 |
| [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) | 工作区、质量棘轮与设置复核 | Kanban/Dashboard CRUD、metadata onboarding、质量棘轮、mutation 归属守卫、设置/应用/变现复核与维度表。 |
| [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) | 受治理写目录与分析 CRUD | 自定义指标、受治理写目录、元数据模板 CRUD、评测网络字段派生、保存分析 CRUD 与六类导出重判。 |
| [`semantic-composition.md`](roadmap.d/semantic-composition.md) | 语义组合与外部 selector | guided cold start、语义组合窄切片与 v2、外部 selector 不可测标注及六类自报字段。 |
| [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) | 目录选路与 playbook | J39 回归、raw CLI 分页提案、语义定义 v3、指标异常 playbook 与 P0-1 目录优先选路合同。 |
| [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) | 合同真实性、分页与 D28 | 分页声明与可重放边界、D28/公开 App 动线、91 卡合法宿主选择、无证据续页与租户枚举晋升。 |
| [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) | 权限、投放读语义与质量收口 | 权限感知与误分类、D32/D33-D34 投放读语义、活宿主 selector、短窗假阴性、投影/blob 降复杂度与导出闭环。 |

## 历史二级标题 → 归档文件

原 `docs/roadmap.md` 的二级标题全部保留在对应归档文件中，锚点随文件走。

| 原标题 | 归档文件 |
| --- | --- |
| 目标 | [`goals-and-current-state.md`](roadmap.d/goals-and-current-state.md) |
| 现状 | [`goals-and-current-state.md`](roadmap.d/goals-and-current-state.md) |
| 优先级 | [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) |
| D22 合并语义：证明不了，且前端这条路已穷尽 | [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) |
| 并行与串行约束 | [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) |
| 两条曾经贴脸的硬约束（已解除，规则保留） | [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) |
| 已知能力净损失 | [`priorities-constraints-and-loss.md`](roadmap.d/priorities-constraints-and-loss.md) |
| Agent 可用性欠账 | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| 九条 `1 / 3` 调用成本裁决（2026-08-14） | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| 三处缺面裁决（2026-08-14） | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| 使用成本：参数化程度审计结论 | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| D35 / F40 归因结果合同（2026-08-16） | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| 并发 | [`agent-usability-and-cost.md`](roadmap.d/agent-usability-and-cost.md) |
| 留出测试：关键词式自然语言路由不泛化（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| 闭环判据修正：Agent 面必须自然语言可达（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| MCP 交付面可行性裁决（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| 47 条动线重验与修复结论（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| 可重复的 Agent 可用性基线（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| 留出集重建与可操作 key 托管（2026-08-15） | [`agent-eval-baseline.md`](roadmap.d/agent-eval-baseline.md) |
| 三分评测、查询账本与安全硬门禁（2026-08-16） | [`eval-harness.md`](roadmap.d/eval-harness.md) |
| 评测预期按动线台账派生（2026-08-16） | [`eval-harness.md`](roadmap.d/eval-harness.md) |
| Development 题集扩充（2026-08-16） | [`eval-harness.md`](roadmap.d/eval-harness.md) |
| 多意图评分表达修正（2026-08-16） | [`eval-harness.md`](roadmap.d/eval-harness.md) |
| 投影边界总裁决：全面放开（2026-08-15） | [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) |
| 分群成员明细合同取证（2026-08-15） | [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) |
| 已批准的隐私投影边界：变现明细（D27） | [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) |
| Agent 入口表的增长处理 | [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) |
| App / 变现家族读语义取证（2026-08-14） | [`projection-and-privacy.md`](roadmap.d/projection-and-privacy.md) |
| D28 变现聚合合同取证（2026-08-15） | [`monetization-and-non-goals.md`](roadmap.d/monetization-and-non-goals.md) |
| Issue 20 Windows receipt 存活探测（2026-08-17） | [`monetization-and-non-goals.md`](roadmap.d/monetization-and-non-goals.md) |
| 明确不做 | [`monetization-and-non-goals.md`](roadmap.d/monetization-and-non-goals.md) |
| Issue 19 精确素材预览/下载裁决（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| 最后两条可推动线复核：Analysis 导出 / 平台素材二进制（2026-08-16） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| Issue 16 Windows CLI UTF-8 裁决（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| 运行环境健壮性审计（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| Issue 12 / 18 登记投影漂移收口（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| Issues 11 / 15 / 17 Analysis semantic rejection 裁决（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| 失败与降级路径一致性审计（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| 退出码共享分类与门禁（2026-08-15） | [`exports-runtime-and-issues.md`](roadmap.d/exports-runtime-and-issues.md) |
| 分析空间 / 报表设置只读 route 裁决（2026-08-15） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 语义层 / 指标层与 text-to-SQL 调研裁决（2026-08-15） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 可恢复错误消息分档与首轮升级（2026-08-15） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 字段策略层错误消息升级（2026-08-15） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| Agent 渐进发现与生成任务指南（2026-08-16） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 非推广/素材未覆盖读路由逐条复核（2026-08-16） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 引力原生 AI 事件分析对话摸底（2026-08-16） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 派生指标与声明集合对账（2026-08-16） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| `semantic_error` 判定与 evidence 审计（2026-08-16） | [`semantics-errors-and-discovery.md`](roadmap.d/semantics-errors-and-discovery.md) |
| 写操作范围裁决与 Segment CRUD（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| 自然语言路由三臂对照（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| 自然语言路由第二轮：调用方语言索引与分布阈值（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| 臂 C：宿主 LLM 盲选能力目录实测（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| 报表目录与订阅的写解锁（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| Agent Catalog 产品事实 parity 与改进臂 C（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| 十分钟主路径生产复验与文档收口（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| Protected selector 桥接与 read envelope 语义收口（2026-08-16） | [`writes-and-nl-routing.md`](roadmap.d/writes-and-nl-routing.md) |
| Kanban / Dashboard 全 CRUD 与持久化工作区（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 冷启动 metadata onboarding 与产品卡排序（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 质量棘轮去物理压行（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 干净外部 LLM 的 development 臂 C（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| Metadata onboarding 合入 AST 质量棘轮（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| Kanban 写能力合入 dev（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 三域 mutation 归属守卫改为 marker OR owner（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 设置、应用、元数据与变现报表复核（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 维度表 wire 与分析价值探测（2026-08-16） | [`workspaces-quality-and-settings.md`](roadmap.d/workspaces-quality-and-settings.md) |
| 自定义指标口径 CRUD 与 confmetric 前缀裁决（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 受治理写能力目录覆盖（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| custom-metrics 与受治理写目录合并裁决（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 评测装置阶段网络与实际选择稳定性（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 事件/属性元数据模板治理 CRUD（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 评测终点网络字段由计数派生（2026-08-16） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 保存分析 CRUD 与严格重放闭环（2026-08-16 至 2026-08-17） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 六类 Analysis 服务端导出重判与四族闭环（2026-08-17） | [`governed-writes-and-analysis.md`](roadmap.d/governed-writes-and-analysis.md) |
| 首条事件分析 guided cold start（2026-08-17） | [`semantic-composition.md`](roadmap.d/semantic-composition.md) |
| 受治理语义组合首个窄切片（2026-08-17） | [`semantic-composition.md`](roadmap.d/semantic-composition.md) |
| 外部 selector 选择网络显式标注为不可测（2026-08-17） | [`semantic-composition.md`](roadmap.d/semantic-composition.md) |
| external selector 六类自报字段收口（2026-08-17） | [`semantic-composition.md`](roadmap.d/semantic-composition.md) |
| 语义组合过滤 wire 与 v2（2026-08-17） | [`semantic-composition.md`](roadmap.d/semantic-composition.md) |
| J39 recognizer 目标迁移回归（2026-08-17） | [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) |
| 2026-08-17：raw CLI 分页可见性与请求纪律（提案） | [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) |
| 语义定义 v3 成员扩容（2026-08-17） | [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) |
| 指标异常定位 playbook v1（2026-08-17，提案） | [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) |
| P0-1 目录优先宿主选路合同（2026-08-17，不切默认） | [`catalog-routing-and-playbooks.md`](roadmap.d/catalog-routing-and-playbooks.md) |
| 合同真实性：分页声明与结果可重放边界（2026-08-17） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| D28 与公开 App 信息缺失动线（2026-08-17） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| 当前 91 卡目录上的合法宿主选择（2026-08-17，不切默认） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| 分页审计分叉与无证据续页（2026-08-17） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| D28 租户枚举与非空晋升（2026-08-17） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| 分页审计与 D28 并行分支的合并对账（2026-08-17） | [`contract-truth-pagination-and-d28.md`](roadmap.d/contract-truth-pagination-and-d28.md) |
| 权限感知：如实报告当前账号权限事实（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 权限误分类与换号 session 失效（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| D32 / D33-D34 非 Bytedance 投放前提复测（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| B 级错误补实际值（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| Development 跑批入门禁与闭环倒扣（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 活宿主 selector 插件（2026-08-17，只证明 development） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| P0-2 收口：分群 / 保存分析 / 元数据模板 master 的上游 owner（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 权限型空与真空不可区分（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 短窗假阴性重判（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 投影引擎降复杂度（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| 变现明细导出可调用并标注截断（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| D32 / D34 腾讯层级与素材下钻读语义确认（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| blob 传输子系统降复杂度（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| D32 / D33-D34 剩余读语义确认与空样本复测（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |
| origin_event 导出闭环（2026-08-17） | [`permissions-campaigns-and-quality.md`](roadmap.d/permissions-campaigns-and-quality.md) |

# 验证 Harness：风险、消融与开发体验

本页只解释现有验证组件怎样按风险组合、怎样证明仍有净价值。规则与命令由
`scripts/repository_map.py` 的 Task Context Pack 生成；这里不复制可执行清单。

## 风险判定

判定采用“最高命中优先；未知即高风险”，不会因同时修改文档或测试而降低代码风险。

| 风险 | 自动判据 | Review | 验证 |
| --- | --- | --- | --- |
| 低 | 仅 `docs/**`、`tests/**`、`skills/**`、`content/**` 或普通 Skill 包内容；架构、隐私、安全等高风险词仍优先 | Self-review | Focused |
| 中 | 普通 `src/gravity_insight/**` Runtime/公开 surface 或 `scripts/**` 维护工具，且没有高风险命中 | Independent Review | Focused + installed-wheel Surface + canonical Consumer |
| 高 | 合同/schema/route、Agent 包、`plan_adapters.py`、Runtime component entity、工作流/发布治理，或 auth/concurrency/degradation/pagination/privacy/provenance/security/transport 等边界；未知路径也在此档 | Adversarial Review | Full + clean-commit Integrated + offline canary contract |

Release 固定按高风险处理。非 changed-files 查询按匹配实体判定；无法绑定实体时 fail closed 到高风险。
开发分支的 offline canary 只证明 lifecycle fail-closed 合同，不能替代 External Control Plane 在 Release
阶段对已 stage Artifact 做的真实 canary/activate/rollback 证据。

## 长期 Harness 清单与消融合同

成本均为 2026-09-01 在本工作树 `.venv` 的实测墙钟时间；N11 已复现数字明确标为 N11。

| Harness | purpose | load-bearing evidence | cost | ablation method | removal trigger |
| --- | --- | --- | --- | --- | --- |
| Task Context + Focused | 用机器图只读最小上下文，并在分钟内反馈受影响回归 | 本趟新增 observation 模块后，Focused 的 graph regression 立即拒绝 665→666 节点漂移 | N11 26.501s；本趟 Map 13.450s + characterization 13.929s = 27.379s；N11 task pack 10,816 tokens | 保留目标测试、去掉 Map check 后制造 stale map；再反向操作，比较哪类漂移未被发现 | 连续 3 个重大模型/工具版本没有独有检出，且相同错误已由更便宜门禁稳定拦截 |
| Full 双 collector | 高风险/Release 同时覆盖 pytest CI 语义与原生 unittest discovery/import 顺序 | `tests/__init__.py` 隔离真实 cache；历史 `f3c9a849` 修复 repository-tree 并发，说明 collector 行为曾暴露维护陷阱 | 未改代码基线：原生 collector 1005.172s；CI collector 142.290s；精确项数留在机器 receipt，不写进 current docs | `validation_observability.py --gate full --ablate unittest_collector ...`，其余五条不变；比较失败集与计数 | **删除候选**：连续 3 个版本 pytest 覆盖集合为超集且消融无唯一失败，就从默认 Full 移除独立 unittest，保留按需兼容诊断 |
| Compiler + Quality | 验证 manifest/provenance 确定性及复杂度、文档、治理基线 | 本趟第一次消融运行实际拦下新函数 complexity 21/16 与 broken local link | compiler 5.640s；quality 27.140s；合计 32.780s | 分别省略一个命令，注入 stale generated artifact、复杂函数或断链，再跑其余门禁 | 只有替代门禁能拦下同一 mutation 集，且成本更低，才移除旧 owner |
| High Integrated + usability + canary | 在 clean exact HEAD 汇合 release、wheel、consumer、runtime 与 Agent 使用路径；canary 只验证离线生命周期合同 | `test_canary_failure_leaves_prior_complete_snapshot_active` 锁住 canary 失败不激活候选；agent usability 检查真实任务选择 | N11 Full 1,164.842s；agent usability 41.270s；offline canary 4.245s | `run_integrated_validation.py --trial --only ...` 逐个省略 gate，运行该 gate 的 fault fixture 并比较 receipt | 某 gate 连续 3 个重大版本没有独有失败，且 fault fixture 被另一更便宜 gate 拦截 |
| Ordered generators + package checkpoint | 让生成物固定点、package reference 分母与 disposition 坐标一致 | 反序实测会令两个 checkpoint tests 以 `7b5d… != 3176…` 失败；本趟编排测试锁住 Map→checkpoint 顺序 | 五个普通 generator checks 2.596s；Map→checkpoint check 33.048s | `test_validation_harness_refresh.py` 把第一步设为失败，断言第二步绝不执行；在临时 clone 反序重建确认 checkpoint stale | Map 不再是 checkpoint 扫描输入，或 checkpoint 改为直接消费同一次内存 projection 后删除编排约束 |
| Module characterization graph | 锁住真实 AST/lazy export/package-parent 依赖与 SCC，而不是文件名猜测 | 本趟新增一个模块即准确报出 graph baseline drift；刷新后为 666 nodes / 3,602 canonical edges | targeted characterization suite 13.929s | 暂时省略 characterization test、加入一个跨模块 import，再跑其余 Focused，检查漂移是否漏过 | Repository Map 自身能独立验证同一图定义、edge kinds、SCC 与 reviewed baseline 后去重 |
| Census + drift | 区分上游扩张、破坏性漂移、circuit/transport failure，避免错误晋升 route | `8f47c925` 与 `895d5c97` 修复 circuit/drift failure taxonomy，现有 fixtures 复现这些错误类 | 四个 census modules，15.760s | 关闭 diff/failure taxonomy tests，对对应 fixture 做 category mutation，再跑其余 census tests | 上游提供版本化 schema 且替代合同覆盖所有当前 mutation fixture |
| Privacy + consumer-output safety | 防止未审查字段、URL/标识或受限内容进入稳定投影和 Agent 输出 | `1a0c70cb` 实际删除 stale URL privacy entries；当前测试锁住 stable registry 与 consumer output inventory | targeted privacy suite 7.840s | 去掉 privacy tests，向 fixture 加未知敏感字段/URL，运行 quality 与 consumer tests比较 | 替代投影器能在更低成本下拦住完整 mutation corpus，且没有双 owner |
| Provenance + installed wheel + canonical consumer | 验证非 editable wheel 的五 surface parity、离线 provenance 与真实 pinned consumer | 本趟 wheel matrix 通过五 surface；work-dashboard pinned suite 实跑通过，network_calls=0 | provenance 0.378s；wheel surface 20.540s；consumer 74.032s；合计 94.950s | 分别移除 wheel/provenance/consumer gate，使用 tampered fixture、editable escape 与旧 envelope consumer fixture | 三类失败全部被单一 installed-artifact gate 以同等隔离度和更低成本覆盖 |
| Test duration budget | 阻止单项测试吞掉 CI 20 分钟预算 | `fc3efa9d` 建立 240s immutable ceiling；超时 nodeid 会成为 fail-closed 诊断 | 与完整 pytest collector 同量级；本趟基线 collector 142.29s，budget recorder 的独立总耗时由 integrated receipt记录 | 从 Integrated 省略 duration gate，注入超过 240s 的受控 fake report，验证普通 pytest 不拒绝时该 gate是否唯一承重 | pytest 主 collector直接实施同一 per-item ceiling并输出相同 nodeid 后，删除第二次全量收集 |

Repository Map v2 仍是单个可直接 `json.load` 的 JSON 文件；它只把重复值换成确定性表。
生成器先校验 compact v2 transport，loader 再还原并校验完整 v1 fact contract，逐字段
round-trip 测试锁住 entry、issue location、模块节点和边不丢失；255,000 字节门槛不变。

第一次 unittest 消融运行不是有效“绿色证据”：pytest 在 414.170s 后报告 5 failures，其中 broken link 与
complexity 是真实实现缺陷，另一个 isolated import 受同机并发影响超时。修复缺陷后必须重跑；不得把这次失败
包装成“unittest 承重”或“可以删除”。修复后第二次以同一 ablation receipt 重跑：CI collector 225.100s、compiler
7.524s、quality 24.969s、CLI help 0.946s、diff check 0.154s，合计 258.698s 全绿。因此独立 unittest
collector 当前没有本趟可见的独有检出，正式列为删除候选；仍按上表 trigger 等待跨版本证据，不在本趟直接删除。

## 十一项指标

`scripts/validation_observability.py` 从同一个 Task Context Pack 生成 digest-bound receipt：

| 指标 | 采集算法 / 数据源 |
| --- | --- |
| `bootstrap_tokens` | 对 repository-visible bootstrap 文件（当前为 `AGENTS.md`）使用与 Repository Map 相同的 mixed CJK/code estimator；平台 system/developer prompt 不可见，不冒充已采集 |
| `task_context_tokens` | `minimal_references[].estimated_tokens` 之和 |
| `files_read_before_first_edit` | trace 中首次 `edit` 前 unique `read.path`；无 agent tool trace 时 `unmeasured` |
| `time_to_first_reproduction` | 首个 `reproduction.at - session_started_at`；缺事件时 `unmeasured` |
| `time_to_first_useful_edit` | 首个 owner-confirmed `useful_edit.at - session_started_at`；缺事件时 `unmeasured` |
| `focused_gate_seconds` | runner 用 `perf_counter` 逐命令计时并求和；失败或消融 receipt 不当作完整门禁值 |
| `full_gate_seconds` | 同上，只接受未消融且全绿的六命令 Full receipt |
| `review_iterations` | trace 内 `review_result` 事件数；无 trace 时 `unmeasured` |
| `context_resets` | host trace 内 `context_reset` 事件数；无 trace 时 `unmeasured` |
| `archive_tokens_loaded` | Task Pack 中 archive/history prefix 引用 token 之和，不用常量零 |
| `active_docs_tokens` | Task Pack 中非 archive 的 `docs/**` 引用 token 之和 |

### 轻量基线

`--archive <path.json>` 只追加 collector 生成、`receipt_sha256` 校验通过的 observation；不接受手填指标。
每条记录绑定 revision、task digest、risk 与 gate receipt，日志仅留 path + digest。`--trend-only` 按 revision
计算各指标中位数；最近三个 revision 的中位数严格连续上升才报 `sustained_increase`，少于三个明确报
`insufficient_history`。Release/CI 把该小 JSON 当构建 artifact 保存；仓库不再维护一份人工抄写的数字表。

## Focused 不等于 Full

Focused 有意会漏掉：不在反向依赖图上的远端测试、pytest/unittest discovery 差异、完整 compiler/quality、
CLI import/help、wheel 安装隔离、canonical consumer、release provenance、Agent usability 与 canary lifecycle。
低风险安全性来自“改动不能进入 Runtime/合同/安全边界”的判定，不来自 Focused 能证明全仓绿色。测试-only
改动仍可能删除断言，这是 Self-review 的剩余风险；一旦涉及治理 fixture、privacy/security 等高风险词会被
最高命中规则升级。中风险补 Surface/Consumer；高风险和 Release 才支付 Full/Integrated/Canary 成本。

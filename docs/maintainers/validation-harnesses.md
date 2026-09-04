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
| Task Context + Focused | 用机器图只读最小上下文，并在分钟内反馈受影响回归 | Focused 运行 registry tests 加改动模块的两层反向依赖闭包，而不是第一个测试文件；命中高扇出或超过 80 个测试文件时升级 Full | `run_changed_tests.py` 对每条命令计时；Focused 合计硬上限 100s | 保留目标测试、去掉 Map check 或闭包中的非首个测试后注入漂移，比较哪类错误未被发现 | 连续 3 个重大模型/工具版本没有独有检出，且相同错误已由更便宜门禁稳定拦截 |
| Full 双 collector | 高风险/Release 同时覆盖 pytest CI 语义与原生 unittest discovery/import 顺序 | `tests/__init__.py` 隔离真实 cache；历史 `f3c9a849` 修复 repository-tree 并发，说明 collector 行为曾暴露维护陷阱 | J5 同一 HEAD：原生 collector 503.208s；pytest `load` 224.502s；pytest 多出的唯一项是 `test_workspace.py` 的原生 pytest 函数。精确项数留在本轮 receipt | `validation_observability.py --gate full --ablate unittest_collector ...`，其余五条不变；比较失败集与计数 | **本轮结论：留**。pytest 当前是执行集合超集且本轮无独有失败，但尚无连续 3 个重大版本的有效消融收据；原生 discovery/import 顺序已有历史独有检出。满足原 trigger 后删除串行 collector，保留按需兼容诊断 |
| Compiler + Quality | 验证 manifest/provenance 确定性及复杂度、文档、治理基线 | 本趟第一次消融运行实际拦下新函数 complexity 21/16 与 broken local link | compiler 5.640s；quality 27.140s；合计 32.780s | 分别省略一个命令，注入 stale generated artifact、复杂函数或断链，再跑其余门禁 | 只有替代门禁能拦下同一 mutation 集，且成本更低，才移除旧 owner |
| High Integrated + usability + canary | 在 clean exact HEAD 汇合 release、wheel、consumer、runtime 与 Agent 使用路径；canary 只验证离线生命周期合同 | `test_canary_failure_leaves_prior_complete_snapshot_active` 锁住 canary 失败不激活候选；agent usability 检查真实任务选择 | N11 Full 1,164.842s；agent usability 41.270s；offline canary 4.245s | `run_integrated_validation.py --trial --only ...` 逐个省略 gate，运行该 gate 的 fault fixture 并比较 receipt | 某 gate 连续 3 个重大版本没有独有失败，且 fault fixture 被另一更便宜 gate 拦截 |
| Ordered generators + package checkpoint | 让生成物固定点、package reference 分母与 disposition 坐标一致 | 反序实测会令两个 checkpoint tests 以 `7b5d… != 3176…` 失败；本趟编排测试锁住 Map→checkpoint 顺序 | 五个普通 generator checks 2.596s；Map→checkpoint check 33.048s | `test_validation_harness_refresh.py` 把第一步设为失败，断言第二步绝不执行；在临时 clone 反序重建确认 checkpoint stale | Map 不再是 checkpoint 扫描输入，或 checkpoint 改为直接消费同一次内存 projection 后删除编排约束 |
| Module characterization graph | 锁住真实 AST/lazy export/package-parent 依赖与 SCC，而不是文件名猜测 | 本趟新增一个模块即准确报出 graph baseline drift；刷新后为 666 nodes / 3,602 canonical edges | targeted characterization suite 13.929s | 暂时省略 characterization test、加入一个跨模块 import，再跑其余 Focused，检查漂移是否漏过 | Repository Map 自身能独立验证同一图定义、edge kinds、SCC 与 reviewed baseline 后去重 |
| Census + drift | 区分上游扩张、破坏性漂移、circuit/transport failure，避免错误晋升 route | `8f47c925` 与 `895d5c97` 修复 circuit/drift failure taxonomy，现有 fixtures 复现这些错误类 | 四个 census modules，15.760s | 关闭 diff/failure taxonomy tests，对对应 fixture 做 category mutation，再跑其余 census tests | 上游提供版本化 schema 且替代合同覆盖所有当前 mutation fixture |
| Privacy + consumer-output safety | 防止未审查字段、URL/标识或受限内容进入稳定投影和 Agent 输出 | `1a0c70cb` 实际删除 stale URL privacy entries；当前测试锁住 stable registry 与 consumer output inventory | targeted privacy suite 7.840s | 去掉 privacy tests，向 fixture 加未知敏感字段/URL，运行 quality 与 consumer tests比较 | 替代投影器能在更低成本下拦住完整 mutation corpus，且没有双 owner |
| Registry semantic surface parity | 从编译后 operation registry 派生 Direct SDK / CLI / SDK wrapper / Plan / MCP 五列表，比较公共 schema、完整 Empty/Upstream Error envelope、completeness walker 与错误身份 | 当前 190 个 stable read operation、38 个精确登记的 action-specific mutation scope exclusion、950 次精确合法差异应用、0 个未登记 finding；反向测试分别删除 SDK 字段和 CLI audit allowance，均使门禁失败 | 本机完整矩阵约 12s；复用既有 `surface-parity` job 的测试文件，不新增 CI job | `test_rejects_new_sdk_envelope_field_loss` 注入字段丢失；`test_rejects_removed_cli_pagination_audit_allowance` 删除精确 allowance | 只有另一条 registry-derived 门禁能在完整真实 envelope 上拦住同一 schema/field/type/completeness/error mutation corpus，才可移除 |
| CLI exception boundary | 阻止 CLI 最外层把已捕获异常扁平化为不可决策的一行文本 | `test_new_plain_text_exception_collapse_makes_gate_fail` 注入新 handler 并证明仓库测试失败；`test_allowlist_without_reason_is_rejected` 证明空理由不能豁免 | 单独 AST check 约 2s | 向新的 `*_cli.py` 注入 `except ... print(exc)`，再分别省略理由、移动行号或改 handler AST，确认未命中精确豁免 | 所有公开入口统一由一个类型化 error-envelope owner 包裹，且结构测试覆盖任意新增入口后才可移除 |
| Provenance + installed wheel + canonical consumer | 验证非 editable wheel 的五 surface parity、离线 provenance 与真实 pinned consumer | 本趟 wheel matrix 通过五 surface；work-dashboard pinned suite 实跑通过，network_calls=0 | provenance 0.378s；wheel surface 20.540s；consumer 74.032s；合计 94.950s | 分别移除 wheel/provenance/consumer gate，使用 tampered fixture、editable escape 与旧 envelope consumer fixture | 三类失败全部被单一 installed-artifact gate 以同等隔离度和更低成本覆盖 |
| Test duration budget | 阻止慢测试重新混回本地高频层 | 40s 本地当量以上必须标 `full_gate`，标记集合由 quality baseline 锁定；240s 仍按原始 CI 墙钟执行，是任何单项不可越过的绝对上限 | 与完整 pytest collector 同量级；CI shard receipt 记录 marker、测量坐标与换算比率，汇总审计证明 9 项和完整 collection 都守恒 | 去掉 marker 后对受控本地当量 40.001s report 运行 duration gate；删一片 shard 或过滤 collection 再运行 audit | 主 pytest collector直接实施同一 marker/时长/集合守恒后，删除第二次全量收集 |

Repository Map v2 仍是单个可直接 `json.load` 的 JSON 文件；它只把重复值换成确定性表。
生成器先校验 compact v2 transport，loader 再还原并校验完整 v1 fact contract，逐字段
round-trip 测试锁住 entry、issue location、模块节点和边不丢失；255,000 字节门槛不变。

Focused 的反向闭包取两层：一层只能看到直接 importer，容易漏掉 service 后的公开 surface；三层在当前
canonical 图中会经 package-parent / lazy-export hub 扩散到大半仓库。当前反向 fanout 的 P95 为 12，
所以 40 只截住显著 hub；若改动模块本身超过 40，或最终命中超过 80/275 个 runnable 测试文件，风险
升级到 Full。测试绑定使用 AST import 与 `gravity_insight...` 字面量模块引用，不再用子串命中。

时间 ratchet 放在既有 `quality-baseline.json`：本地 Focused 上限 100s，来自剔除八项后的 83s 实测加
20% 调度余量（99.6s 向上取整）；duration gate 首轮实测未标记项最慢 30.366s，当前最短
Full-only 项为 41s，故阈值取 40s：给普通项保留 9.634s 余量，同时仍覆盖已知慢项。
`slow_test_seconds` 始终是本地坐标；GitHub Actions report 先除以唯一的
`LOCAL_TO_CI_DURATION_RATIO = 716/364` 再比较。240s 绝对上限的校准包络也只引用该比率，
但仍直接约束原始 CI 墙钟。标定修复后 9 项均按 scan/build/isolated-subprocess 语义成立，
没有可从 `full_gate` 减去的误分类成员。
阈值只能收紧，`full_gate` 名额只能减少。裸 `pytest -q` 与 unittest 仍是完整集合；只有 Focused 命令
使用 `-m "not full_gate"`。CI duration runner 显式清空本地 `addopts`，四片 receipt audit 再证明完整
collection、选择集与实际执行集相等，防止默认过滤造成假绿。

J5 在同机、固定 4 workers 连续实测 `load=224.502s`、`loadscope=227.025s`、
`loadfile=188.213s`，三次收集集合与通过集合相同；因此默认改为 `loadfile`。
仓库扫描模块已在进程内缓存输入，`loadfile` 让同文件用例复用这些缓存；跨 worker 的 session fixture
既不能共享 Python 对象，也会让会修改临时仓库树的负向用例读到过期快照，所以不新增全局可变 fixture。

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

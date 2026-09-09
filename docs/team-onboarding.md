# 数据分析团队上手包

本页是安装后完成第一次受治理分析的唯一入口。它不手写动态产品数量，也不保存租户样本。

## 1. 安装与认证

权威发行包是 `gravity-insight`；不要安装同名或近似名的第三方包：

```powershell
python -m pip install gravity-insight
gravity --help
gravity insight auth status
```

首次运行会在交互终端引导登录；账号由团队发放。凭据只留在用户私有状态目录；认证失败时停止，不把 token、cookie、用户名或密码写进命令、日志或 Plan。

**自动更新全团队默认开启**，不要逐机关闭。`GRAVITY_INSIGHT_AUTO_UPGRADE` 未设置即为开启，启动时安装更新版本（含破坏性变更）并在新进程重跑命令；破坏性变更靠[迁移说明](migration/)传达，不靠停留旧版躲避。因此 `pip show` 显示的是基础安装版本而非实际执行版本，要认实际版本读 `gravity.runtime-update-receipt.v1` 收据。取证需临时钉版时设 `GRAVITY_INSIGHT_PINNED_VERSION`，**必须在第一条命令之前**。从 `0.3.9` 及更早升上来的人要手动装一次 `0.3.10`：执行更新的代码在 `0.3.10` 里，旧运行时没有它。

密封 Skill seed 也默认在普通业务命令 dispatch 前离线装配；相同 seed digest 直接短路，更新随 Runtime
版本进入下一进程，不另查远程 Skill channel。需要冻结 Skill 时单独设置
`GRAVITY_INSIGHT_AUTO_SKILLS=0`；这不关闭 Runtime 安全更新。`gravity skills status` 查看明确状态，
失败后用 `gravity skills repair` 重验。自动装配不会改写项目 `gravity.skills.lock.json`。

只有修改源码时才在当前 worktree 的独立虚拟环境安装 editable 包：

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -e ".[dev]"
& .venv\Scripts\python.exe -m gravity_insight --help
```

源码目录中的非 editable 安装会被 `gravity doctor` 拒绝，避免当前源码与实际导入包不一致。

## 2. 选择入口

宿主先理解需求：有当前有效能力合同就直接调用；未知能力从下列离线目录进入；无法可靠选择才用 recognizer 保底。唯一完整顺序、失败分类与预算合同见 [Agent 工作流](agent-workflow.md#0-宿主优先的有序合同)。

```powershell
gravity agent-catalog categories
gravity agent-catalog category analysis --limit 20
gravity agent-catalog describe analysis.query.spec:event
```

未同步过 metadata catalog 时，metadata 发现返回 `The default local metadata catalog is unavailable`。

按需读取 `gravity agent-catalog host` 获取现有 selection 合同；目录与发现不会执行产品。仅在任务需要本地 metadata 且获授权时运行 `gravity metadata sync --all-apps`，不把全量同步作为发现的固定前置步骤。

安装后先查看 wheel seed 的离线装配状态；只有需要显式外部 Hub Source 时才同步：

```powershell
curl -sL -o source.json https://github.com/mmm1h/gravity-insight/releases/download/skill-library-v5/source.json
gravity agent-catalog categories
gravity skills status
gravity skills list --state-root <state-root>
# 显式外部 Source：
gravity skills sync --source source.json --state-root <state-root>
```

`status=not_bootstrapped` 与成功但合法零项的 `status=empty` 是不同机器状态；不要只看 `count: 0`。
显式外部同步成功仍以 `sync` 返回的 `skill_count` 和 `snapshot_digest` 为准。

Skill 不替代选路、Journey、权限或执行合同；`blocked` 必须停止，`validated` 不代表当前可执行。
Runtime wheel 不内置可发现 registry/resolver，但携带同次 CT03 构建的唯一密封 seed；它只有完成
managed lock/CAS/verify 后才进入发现面。供 Codex、Claude Code 等宿主安装的 `SKILL.md` 是同一
canonical manifest 的独立 Agent 投影；用 `skills host-install-plan` 交给宿主原生机制，用户改过的
目标目录不会被覆盖，当前会话 reload 不作承诺。

## 3. 补参并执行

- 按[完整使用顺序](agent-workflow.md#0-宿主优先的有序合同)选择入口，再按 `required_inputs` 与当前 Schema 补参；不要靠关键词匹配补业务事实。
- 多个独立读取：使用一个 Plan 或 batch，共享全局有界并发预算。
- Analysis spec：读取产品卡的 `schema_argv`，不要从 Web wire 或邻近 operation 猜形状。
- Runtime 提供可复用 Semantic；具体活动、SKU、App/埋点绑定和项目公式参数来自显式项目 Source，缺失时不猜。
- 首次语义校验看[可运行虚构示例](reference/cli.md#business-semantic-与-semantic-compose)；已有 Runtime Skill 包的 `references/PROJECT_BINDINGS.json` 是项目绑定占位模板，不是可直接执行的业务口径。

产品步骤见[任务指南](agent-skills/index.md)，通用协议见[Agent 工作流](agent-workflow.md)。

## 4. 识别终态

| 终态 | 处理 |
| --- | --- |
| `success` 且 `executable=true` | 补齐输入并执行 `next.argv` |
| `multiple_intents` | 拆分任务或让调用方显式选择 |
| `capability_gap` | 报告 code、reason、next action；没有 argv 就停止 |
| `NO_CANDIDATE` | 浏览目录；禁止执行 weak match |
| `UNRANKED_OPERATIONS` | 交给宿主选择，不猜 top-1 |

退出码 0 表示成功或合法空；2 是输入/认证；3 是上游、权限或限流；4 是本地合同、隐私或 I/O。

## 5. 判断结果

先看 envelope，再看数值：

1. 确认 `schema_version`、`status`、`result_source` 和 `resolved_date_window`。
2. 阅读 `warnings`、`diagnostics`、`interpretation`、`unreliable_item_keys` 和 drift audit。
3. 区分 `empty`、`partial`、`semantic_error` 和成功；HTTP 200 不等于业务成功。
4. 只对声明可加的指标求和；UV、设备数和活跃用户通常不可跨维相加。
5. 重要数字用独立 route、分页总数、分日/整窗或 list/export 行数复核一次。
6. 请求的组或身份没有出现在结果中时停止解释，不给无标签行补语义。

把结果交给模型前遵守[结果与 LLM 安全](guides/llm-output-safety.md)。

## 6. 写操作

自然语言永不自动写。固定流程是 preview/`--dry-run`、人工审查 target/impact/preimage/fingerprint、同一输入显式 `--execute`、写后读回。失败不自动重试。

## 交付清单

```text
1. 认证有效且不记录凭据。
2. 已知有效合同直接调用；未知按工作流选择已登记产品，不猜 selector。
3. 补齐 App、日期和物理字段，只执行 success + executable 的交接。
4. 检查 envelope 状态、窗口、warning、diagnostic 和 interpretation。
5. 重要数字独立对账；gap 和权限边界按结构化错误报告。
6. 写入先预览、人工确认、再显式执行。
```

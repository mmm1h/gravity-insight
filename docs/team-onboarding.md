# 数据分析团队上手包

本页是安装后完成第一次受治理分析的唯一入口。它不手写动态产品数量，也不保存租户样本。

## 1. 安装与认证
使用者按下面的发行包路径安装；修改 Runtime 源码的维护者跳到[维护者源码工作](#维护者源码工作)，不混用两种安装。
### 使用者安装
权威发行包是 `gravity-insight`；不要安装同名或近似名的第三方包：

```powershell
python -m pip install --upgrade gravity-insight
gravity --help
gravity insight auth status
```

首次运行会在交互终端引导登录；账号由团队发放。凭据只留在用户私有状态目录；认证失败时停止，不把 token、cookie、用户名或密码写进命令、日志或 Plan。

**自动更新全团队默认开启**，不要逐机关闭。`GRAVITY_INSIGHT_AUTO_UPGRADE` 未设置即为开启，启动时安装更新版本（含破坏性变更）并在新进程重跑命令；破坏性变更靠[迁移说明](migration/)传达，不靠停留旧版躲避。因此 `pip show` 显示的是基础安装版本而非实际执行版本，要认实际版本读 `gravity.runtime-update-receipt.v1` 收据。取证需临时钉版时设 `GRAVITY_INSIGHT_PINNED_VERSION`，**必须在第一条命令之前**。从 `0.3.9` 及更早升上来的人要手动装一次 `0.3.10`：执行更新的代码在 `0.3.10` 里，旧运行时没有它。

密封 Skill seed 也默认在普通业务命令 dispatch 前离线装配；相同 seed digest 直接短路，更新随 Runtime
版本进入下一进程，不另查远程 Skill channel。需要冻结 Skill 时单独设置
`GRAVITY_INSIGHT_AUTO_SKILLS=0`；这不关闭 Runtime 安全更新。`gravity skills status` 查看明确状态，
失败后用 `gravity skills repair` 重验。自动装配不会改写项目 `gravity.skills.lock.json`。

### 维护者源码工作
按[维护者入口](maintainers/index.md)选择任务，在当前 worktree 独立虚拟环境安装 editable 包：

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

### 原生 Host 首次安装
先用 `gravity skills status` 核对离线 bootstrap；`not_bootstrapped` 与检查成功但合法零项的 `empty` 不同。外部 Hub 是[可选路径](reference/cli.md#skill-hub-与-agent-skill)，不是首次使用必做步骤。
在调用项目根目录已有精确 `gravity.skills.lock.json` 时，按[原生安装命令](reference/cli.md#原生-host-安装与读回)生成计划、预览后批准；这里的 project 是调用项目，不是 Runtime 源码树：
```powershell
gravity skills host-install-plan --host codex --host-root <project>/.agents/skills --lock <project>/gravity.skills.lock.json > host-plan.json
gravity skills host-install --plan host-plan.json --project-root <project>
gravity skills host-install --plan host-plan.json --project-root <project> --approve <preview_digest>
gravity skills host-readback --plan host-plan.json --project-root <project>
```
Claude 对应 `--host claude` 与 `<project>/.claude/skills`；不覆盖用户修改，不安装到用户全局目录。摘要不匹配须重新预览，不承诺当前会话 reload。

| 阶段 | 成功证据与边界 |
| --- | --- |
| bootstrap | Runtime seed 已验证进入 managed lock/CAS；未安装宿主文件。 |
| host-plan | 所选包的安装计划已生成；未写宿主目标目录。 |
| installed | 显式批准安装且独立 readback 一致；未证明宿主加载。 |
| discovered | 新宿主会话的启用/发现记录；文件存在不是发现证据。 |
| invoked | 同次会话显式或隐式调用的方法和工具事件；发现不是调用。 |
| executed | 受治理执行的终态、结果与 Receipt；调用不等于成功或完整业务结论。 |

离线 `gravity doctor` 的[六层诊断](reference/cli.md#skill-触发诊断)分别检查方法库、项目锁、原生文件、发现、调用、路由；它不是上述六阶段的成功证明。宿主证据不可见时保留 `unknown/not_measured`，不能用 recognizer 测试冒充真实触发。

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

# 十个分析师同时用，先断在凭据

- 日期：2026-08-19
- 任务：#223
- 结论：两人同一 checkout 用**不同 env 文件**时，运行时、session、进程内 metadata 缓存和磁盘 catalog 已按 env 指纹分开；不传 env 时行为与改前一致。十人同时用仍会先断在「默认共用一份 `.env.gravity.local`」和「每进程各 10 rps / 24 槽、上游配额未知」。

本趟未发生产请求（预算 10 次读 / 0 次写，离线已复现）。未碰 `docs/roadmap.md`、投影、gap、路由臂、`actual` 存量。未建访问控制。

## 复现（改前，离线实测）

假用户名/假密码/假 token，写在临时目录。脚本：`tmp/multiuser_repro.py`。

### 确凿事实

| 场景 | 做法 | 观察到的现象 |
| --- | --- | --- |
| `get_shared_runtime()` 换 env 文件 | 同一进程先 `get_shared_runtime(env_path=a)`，再 `get_shared_runtime(env_path=b)` | 抛 `CredentialError`：`the process-wide Gravity runtime already uses another credential file`。不是静默复用，也不是串号；是硬拒绝。同一路径第二次调用返回同一对象。 |
| 默认 session 路径 | `session_path(.env.gravity.local)` | 固定名 `.env.gravity.session.local`。两进程共用仓库根这份文件时，后写覆盖先写。 |
| 显式另一份 env | `session_path(other.env.gravity.local)` | 得到 `other.env.gravity.session.local`，与默认 session **不是**同一文件。两份文件各自 persist 各自假 token，互不覆盖。 |
| 同一默认文件并发 refresh | 两线程同时 `CredentialProvider.refresh()` | 后写赢：最终文件只剩其中一个假 token。 |
| `MetadataCache` key | `_cache_key("app.list", {"page": 1})` | `('app.list', '{"page":1}')`。无账号、无 env。同一 cache 上 A 先 `get_or_load` 返回 `{account: A}`，B 再用同一 operation/inputs 调用，**直接拿到 A 的快照**，loader B 未执行。 |
| 磁盘 catalog | `LOCALAPPDATA` / `XDG_CACHE_HOME` | `…/GravityInsight/operation-catalog.json` 与 `…/GravityInsight/metadata/catalog.sqlite3`。路径按 OS 用户一份，不含账号或 env 指纹。 |
| `DEFAULT_ENV_PATH` | `credentials.py` 原 `Path(__file__).parents[3]` | 解析到 `D:\git-pjt\.env.gravity.local`，**不是** checkout 的 `D:\git-pjt\wt-multiuser\.env.gravity.local`。`from_env()` / CLI 实际走 `PROJECT_ROOT`，所以默认 CLI 没踩这个错路径；未传路径的 `CredentialProvider()` / `get_shared_runtime()` 会踩。 |
| `MAX_CONCURRENCY = 24` | AST 赋值扫描 `src/gravity_sdk/**/*.py` | 改前 14 处字面量赋值（`http_runtime` + 13 个产品模块）。`pagination.py` / `batch_limits.py` 已是 import。 |

### 推测（本趟未用第二套真凭据并发打上游）

- 两台真账号、同一 checkout、都走默认 `from_env()`：会抢写 `.env.gravity.session.local`，后登录的 token 覆盖先登录的。机制已由假 token persist 证明；真账号互刷未再打一次登录接口。
- 进程环境里残留 `GRAVITY_AUTH_TOKEN` 时，默认（非 isolated）路径仍覆盖文件。这是原兼容语义，单账号 refresh 工作流依赖它。

## 改了什么

判据：两个用户各自跑各自的，互不影响。不是用户管理，也不在 SDK 加授权层。

| 面 | 改前 | 改后 |
| --- | --- | --- |
| env 选择 | 钉死 `PROJECT_ROOT / .env.gravity.local` | `resolve_env_path()`：显式 `env_path` 或 `GRAVITY_ENV_FILE` → 该文件；否则仍是 checkout 默认文件。 |
| `get_shared_runtime()` | 进程一份；换文件报错 | **按 resolved env 文件分桶**。同文件复用，不同文件各一份 runtime / session / 连接池。10 rps limiter 与 24 槽仍是**进程一份**，两账号同进程不能把上游流量乘上去。 |
| 显式 env 与进程 token | 环境变量覆盖文件 | 显式文件 / `GRAVITY_ENV_FILE` 时 `isolated=True`，忽略进程 `GRAVITY_*`。默认文件仍吃进程环境，单账号用法不变。 |
| metadata 缓存 key | `(operation_id, inputs)` | `(isolation_key:operation_id, inputs)`。指纹是 `sha256(resolved_path + NUL + username)[:16]`，不是凭据。`stats()` 不输出指纹。 |
| 磁盘 catalog | OS 用户一份 | 默认路径不变。显式 env 时落到 `GravityInsight/<fingerprint>/…`。指纹不是用户名、不是密码、不是 token。 |
| `DEFAULT_ENV_PATH` | 错指仓库父目录 | 改为 `PROJECT_ROOT / .env.gravity.local`。 |
| `client.py` 探测帮手 | 12 个 `_first_probe_*` 住在公开 Client 上 | 搬到 `probe_first.ProbeFirstMixin`。公开方法名不变，`probe_inputs` 与现有 `patch.object(client, "_first_probe_app_id")` 仍成立。 |
| `MAX_CONCURRENCY` | 14 处 `= 24` | 只在 `process_limits.py` 赋一次，其余 import。值仍是 24。 |

公开 API 只**加**了可选关键字：`GravityInsightClient.from_env(..., env_path=)`、`GravitySDK.from_env(..., env_path=)`、`connect(..., env_path=)`、`GravityClient.from_env(env_path=)`。不传时与今天一致。

## `get_shared_runtime()` 现在「shared」指什么

- **按 env 文件共享**：该文件的 `requests.Session`、`CredentialProvider`、连接池。
- **按进程共享**：对 `api-insight.gravity-engine.com` 的 10 rps 桶，以及 24 个业务槽 / 2 个 SQL 槽。
- **不共享**：另一个 env 文件的 token、session 文件、metadata 快照、显式 env 下的磁盘 catalog。

## 限流：只量不改

本趟**没有**做跨进程限流。

| 量 | 值 | 来源 |
| --- | --- | --- |
| 每进程默认 rps | 10 | `DEFAULT_REQUESTS_PER_SECOND`；`GRAVITY_REQUESTS_PER_SECOND` 可改，上限 100 |
| 每进程业务槽 | 24 | `MAX_CONCURRENCY`，现一处定义 |
| 每进程 SQL 槽 | 2 | `MAX_SQL_CONCURRENCY`；注释写 2026-08-08 探测：2 路成功、4 路长重试 |
| 跨进程 | 无 | 每个 CLI 进程各自一份 limiter / 槽 |
| 分析查询冷启动 HTTP | 3 / 进程 | `docs/roadmap.d/metadata-cost.md`：`event.list` + `event_property.list` + query。本趟未再打生产。 |
| 十个 CLI 冷启动 | **30** 次 HTTP | `10 × 3`。cache 在进程内，带不走。 |
| 十个 CLI 若打满本地限额 | **100 rps**、**240** 在途 | `10 × 10` rps、`10 × 24` 槽。这是本地上限的乘积，不是上游配额。 |

**上游配额未知。** 仓库里没有账号级 / IP 级 / 租户级 rps 合同。要拿到它需要其一：问上游；或在受控窗口观测 429 / `Retry-After`（按账号还是按 IP 也未知）。没有这个数，做跨进程限流只是再猜一个本地数字。

## 质量棘轮

`client.py` AST `6764 → 4226`（硬顶仍 6765，未抬）。`http_runtime.py` AST `3755 → 3643`（硬顶仍 3815）。`operation_literals`：`client.py` 10 条字面量随帮手搬走后从棘轮消失，全仓 `57 → 47`（只降不升）。`quality-baseline.json` 无 `hard_limit` / `threshold` / `max_` 改动。

`tests/test_actionable_error_audit.py` 仍是 `1268 / A896 / B372 / C0`。

## 测试（每处开口一条会红的测试）

文件：`tests/test_multiuser_isolation.py`。

| 开口 | 测试 | 红时断言 | 绿 |
| --- | --- | --- | --- |
| 双 env 各一份 runtime | `test_two_env_files_get_distinct_shared_runtimes` | 换文件仍报错或返回同一对象 | 两对象不同，同路径复用 |
| 不传 env 仍是默认文件 | `test_default_env_path_stays_the_checkout_local_file` | 默认路径漂到别处 | `PROJECT_ROOT/.env.gravity.local`，`isolated=False` |
| 缓存跨账号不串 | `test_shared_cache_does_not_return_another_accounts_snapshot` | B 拿到 `{account: A}` | A/B 各拿各的 |
| 磁盘路径带指纹、不含凭据 | `test_catalog_paths_include_env_fingerprint_not_credentials` | 两账号同路径，或路径里出现用户名/密码 | 分目录；路径无账号字符串 |
| 显式 env 不吃进程 token | `test_explicit_env_file_does_not_reuse_process_token` | isolated provider 读到 `process-token` | isolated 无 token；默认路径仍读进程 token |
| `MAX_CONCURRENCY` 只赋一次 | `test_process_concurrency_ceiling_is_defined_once` | 仍有 14 处 `= 24` | 仅 `process_limits.py` |

配套：`GRAVITY_ENV_FILE` 选文件、`from_env(env_path=)` 分 catalog 路径、默认 `from_env()` catalog 仍是旧路径。

## 十个人同时用，现在还剩什么会断

| 仍会断 | 为什么这趟不动 | 下一步需要什么 |
| --- | --- | --- |
| 十人仍共用仓库根 `.env.gravity.local`，不设 `GRAVITY_ENV_FILE` | 单账号默认用法必须原样工作；不能改成「必须显式传 env」 | 每人一份 env 文件，或 `GRAVITY_ENV_FILE` 指向自己的文件。文档/上手包说明，不是新框架。 |
| 跨进程限流是乘法：十个 CLI 峰值 100 rps / 240 在途 | 没有上游配额数据；跨进程协调是另一量级 | 问上游，或受控观测 429。有数字再谈进程间桶。 |
| 十个冷启动仍是 30 次 metadata HTTP | `MetadataCache` 仍是进程内 10 分钟。磁盘 catalog 现在能按指纹分开，但预取/复用还没接到 FieldPolicy | 跨进程、带指纹的 metadata 预取（arch-review 第 3 条）。不要第二套 cache。 |
| 同一 OS 用户、默认（非显式）路径下，`operation-catalog.json` / `catalog.sqlite3` 仍是一份 | 「不显式指定时行为与今天一致」 | 只有在默认路径也要隔离时，才给默认路径加指纹；那会改变现网单账号缓存位置。 |
| `runtime.build_client()` 每进程仍一份 Client | CLI 一次一条命令；改单例会动所有 CLI 测试 | 若同一进程要切账号，调 `from_env(env_path=)`，不要复用 `build_client()`。 |
| HTTP receipt / `STATE_ROOT` 无账号维度 | 出范围（receipt 耐久是另一条线） | 若多账号同机查 receipt，再按指纹分子目录。 |
| 上游授权边界 | 产品边界。一个账号能看见什么由上游决定 | 不要做字段过滤或敏感检测。 |

## 动线台账

`docs/analysis-journeys.md` 表头 `56 = 51 / 3 / 2` **不变**。本趟没有新产品、没有改任何动线状态列、没有动评测题集。冻结 case 对不上的风险：无。

## 生产请求

0 次。限流数字来自源码常量 + 已提交的 `metadata-cost.md` 冷启动形状，不是本趟新打的上游。

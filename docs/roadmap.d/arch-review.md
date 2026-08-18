# 全盘架构体检：现在的形状、会先断的地方

- 日期：2026-08-19
- 任务：#220
- 结论：仓库是「合同执行核 + 按动线复制的产品三件套」，真正会先断 agent 动线的不是缺产品卡，而是投影/审计各层各写一份 allowlist、以及 `from_env()` 把账号绑死在进程级单例和未含账号维度的本地文件上。

工作目录 `D:/git-pjt/wt-arch-review`，分支 `grok/arch-review`，基线 `dev@53f3d86`。
本趟 **0 次生产请求**。不改 `src/`、`tests/`、评测。只读代码、离线量模块图、跑测试/门禁。

本批另有 5 趟在改 `agent*.py` / `find.py` / 错误消息 / `docs/`。下面看到的个别未提交改动（例如 `--help` 着色让 3 条 CLI 测试红）不当成本树事实。

验证摘要（`PYTHONPATH=src`）：

| 命令 | 结果 |
| --- | --- |
| `python -m unittest discover -s tests` | `Ran 1233 tests`，3 fail（`--help` ANSI，并发 job） |
| `python -m pytest -q` | `3 failed, 1230 passed, 3148 subtests passed`，同一 3 条 |
| `python -m gravity_sdk.compiler check` | `237 operations, 11 manifests` |
| `python -m gravity_sdk.quality check` | `PASS … operations=237, provenance=237, operation_literals=57` |
| `python -m gravity_sdk --help` | exit 0 |

---

## 1. 现在是什么形状

### 确凿事实

`src/gravity_sdk` **493** 个 `.py`，内部模块边 **2255**，源码 SLOC **111568**，函数 **5061**。按文件名前缀归族（只用于看形状，不是运行时 registry）：

| 族 | 模块数 | 角色 |
| --- | ---: | --- |
| domain | 137 | 各产品 core / result / 校验 |
| agent | 79 | 产品卡、选路、handoff |
| plan | 46 | Plan 类型 + 每产品 adapter |
| spine | 37 | client / sdk / cli / executor / registry / http / credentials |
| mutation | 28 | 受治理写 |
| prober | 27 | 维护者探测，不在分析师主路径 |
| analysis | 23 | spec / playbook / batch |
| ads_material | 16 | 投放 / 素材 |
| export | 16 | 导出状态机 |
| sql | 15 | 受治理 SQL |
| census | 13 | 前端路由普查 |
| field_policy | 12 | 分析字段成员校验 |
| 其余 | <12 | metadata / blob / segment / pagination / governance |

真实调用不是「一个神类做完」，是四条入口汇到同一执行核：

```text
gravity CLI  ──► runtime.build_client() ──► GravityInsightClient
GravitySDK.from_env() ──► 同一 Client + SQL
gravity plan / execute_plan ──► plan_adapters ──► Client / SQL / metadata / composite
gravity agent ──► agent_capabilities / handoff ──► 上面三条之一
        │
        ▼
 Registry + PolicyEngine + ReadExecutor + Transport
        │
 GravityHttpRuntime（进程级共享）──► 固定 host/path/method
```

**核心（被很多产品依赖、改了会扇出）：**

| 模块 | 入边 | 出边 | SLOC | 证据 |
| --- | ---: | ---: | ---: | --- |
| `errors.py` | **227** | 1 | 463 | 几乎每个产品都构造 `ErrorDetail` |
| `actionable_error_values.py` | 142 | 1 | 60 | `actual_value()` 被错误面共用 |
| `plan.py` | 50 | 5 | 207 | 全部 adapter 的类型面 |
| `workspace.py` | 46 | 3 | 440 | App / recipe / state_root |
| `agent_intent_text.py` | 45 | 0 | 51 | 选路用的问句规范化叶子 |
| `models.py` | 26 | 7 | 872 | `OperationSpec` / 投影合同 |
| `agent_capabilities.py` | 11 | **36** | 398 | 产品卡接线总闸 |
| `plan_adapters.py` | 2 | 26 | 498 | Plan 四种节点的分派 |
| `http_runtime.py` | 10 | 8 | 688 | 会话 / 限流 / 槽 |
| `registry.py` | 9 | 9 | 747 | 授权 + 合同查找 |
| `client.py` | 1 | 23 | 1107 | 公开读面；只被 `sdk.py` import |
| `sdk.py` | 5 | **39** | 499 | 19 个 mixin、91 个公开方法 |

`client.py` 入边只有 1，不代表它不热：CLI 绝大多数走 `runtime.build_client()` → `GravityInsightClient.from_env()`，不经过 `sdk.py`。`sdk.py` 只被 5 个 analysis/plan CLI import。

**叶子（出边 0，或只被自己族使用）：** 46 个零出边模块，典型是合同/常量（`agent_intent_text`、`result_source`、`cli_limits`、`pagination_policy`）和维护者工具入口（`quality`、`prober.__main__`、`census.__main__`）。

**历史残留（有意保留，不是忘了）：**

- `promotion_snapshot_compat`：绕过正式投放产品的 App/日期/指标绑定；不进 Agent/Plan（`capability_gap`），CLI/SDK 入口仍在。见 `technical-debt.md` 第 2 条。
- `REPORT_PRODUCTS`（`agent_report_routing.py`）：名字还是 report，集合里已有 `advertiser_profile` / `custom_audience`。
- `client.py` 里 12 个 `_first_probe_*`：给 `probe` / `probe_all` 找第一个 App/广告主/事件。分析师主路径不用，但占 AST 余量。
- census / prober 共 40 个模块、3 个最大文件（`prober/drafts.py` 1805 SLOC、`census/params.py` 1568、`census/coverage.py` 890）。它们不在分析动线里，但吃掉了 legacy AST 配额的大头。

### 耦合热点（改一处要连带改几处）

按 **import 入边 + 已知接线纪律**，不是按感觉：

1. **`errors.py`（227 入边）**  
   改错误构造/分类会碰到 `test_actionable_error_audit.py` 钉死的 `1268 / A896 / B372 / C0`。新增 raise 必须按实测改那三个数，`C` 必须仍是 0。

2. **共享脊骨（AGENTS.md 已点名）**  
   `plan_adapters.py`、`agent_capabilities.py`、`agent_composite.py`、`agent_handoff.py`、`cli.py`、`__main__.py`。九条已交付产品线都改过前四个。`agent_capabilities` 出边 36：每加一张卡都要在这里出现。`plan_adapters` 出边 26：每加一个 composite 名字都要进 `validate_composite` / `execute_composite`。

3. **结果信封重建抄了多份**  
   同名函数定义点：
   - `_safe_page`：**8** 个文件（material / promotion / advertiser / company_usage / custom_audience / title_package / plan_multidim / composite_result）
   - `_safe_rows`：**5**
   - `safe_component` / `_safe_success` / `product_envelope` / `_primary_error`：material 与 promotion 各一份（`technical-debt.md` 第 1 条仍开着）

4. **`MAX_CONCURRENCY = 24` 写了 14 次**  
   权威在 `http_runtime.py`。`batch_limits.py` / `pagination.py` 已经 import。另外 13 个产品文件各自定义同名常量。改并发上限必须人工对 14 处。

5. **`GravitySDK` 是 mixin 墙**  
   19 个 `sdk_*.py`，91 个公开方法，`sdk.py` 本体 499/500 SLOC。新产品 = 新 mixin + `sdk.py` 多一行基类。这一行已经没余量。

### 贴着上限的文件：门禁挤的，还是本来该拆？

质量门禁：非 legacy 文件 SLOC ≤ **500**；legacy 15 个文件另有不可抬的 AST/SLOC 硬顶；函数 80 / 复杂度 15 也有祖父债（53 个复杂度债、28 个函数 SLOC 债）。`compiler.py` / `quality.py` 不扫。

**AST 余量 ≤ 50 的 legacy 文件（15 个里 13 个贴顶）：**

| 文件 | AST 现/顶 | 余量 | SLOC 现/顶 | 该不该拆 |
| --- | ---: | ---: | ---: | --- |
| `client.py` | **6764 / 6765** | **1** | 1107 / 1161 | **该拆**。33 个方法里 12 个是 probe 找父资源，不是读执行核 |
| `cli.py` | 4148 / 4167 | 19 | 720 / 788 | 门禁挤的。路由已下沉，留下的是 parser 装配 |
| `registry.py` | 4751 / 4798 | 47 | 747 / 822 | 门禁挤的。授权核应留 |
| `catalog.py` | 5284 / 5332 | 48 | 665 / 722 | 门禁挤的 |
| census / prober 9 个 | 余量 50 左右 | 50 | 远超 500 | **不该为分析动线拆**。维护者工具，拆了不增加闭环动线 |
| `http_runtime.py` | 3755 / 3815 | 60 | 688 / 751 | 会话/限流核，保持 |
| `models.py` | 6302 / 8647 | 2345 | 872 / 1158 | 已抽过，不急 |
| `executor.py` | 4797 / 9149 | 4352 | 786 / 1430 | 投影已下沉，余量最大 |

**卡在 498–500、不在 legacy 名单里的文件（再加一行就红）：**

`sdk.py` 499、`plan_execution.py` 500、`agent_sources.py` 500、`plan_saved_analysis_adapter.py` 499、`_field_policy_detail.py` 499、`plan_adapters.py` 498、`_field_policy_metadata.py` 498、`template_replay_surface.py` 498、`prober/reprobe.py` 500。

其中 `sdk.py` / `plan_adapters.py` / `agent_sources.py` 是**门禁把接线文件挤成这样**——逻辑已经在 mixin / 领域 adapter 里。`client.py` 相反：probe 帮手还住在公开 Client 上，**本来就该搬走**，不是格式问题。

### 推测

- 继续按「一条动线一个 `agent_*.py` + `plan_*_adapter.py` + `sdk_*.py`」长，脊骨文件会先于领域文件爆。这不是推测形状，是 498/500 已经发生。
- census/prober 那 3 个 1000+ SLOC 文件对分析师目标的边际价值接近 0；把它们留在同一 quality 扫描里，会让「能加产品」的余量看起来比实际更紧。

---

## 2. 债在哪里堆着

质量门禁能管：SLOC 500、函数 80、复杂度 15、`operation_literals` 只降不升、legacy AST 硬顶。

### 确凿事实：门禁管不到的债

**同一概念多份实现**

| 概念 | 份数 | 位置 |
| --- | ---: | --- |
| 多平台结果信封（`_safe_page` 等） | 5–8 | material / promotion / advertiser / … |
| `MAX_CONCURRENCY = 24` | 14 | 见上 |
| `_without_legacy_exclusion_phrases` | 2 | `agent_monetization_guard.py`、`agent_order_directory.py` 逐字一份 |
| 相对日期 | 1 套实现、2 个入口 | `relative_dates.py`（CLI `--start/--end`）+ `relative_date_agent.py`（问句填卡）。实现没有分叉 |
| 投影 | 已拆成 `response_projection` / `list_row_projection` / `analysis_projection_contract` / `output_projection` / 各产品 `_safe_*` | 「谁有权留下键」仍按层各写 |

**只为一条动线长出来、现在像通用规则的特例**

- `allowed_analysis_response_key`：漏斗 `aggregate_date.group`、事件 `用户.*`、scatter `type$field` 是三次补丁，不是一条「请求的分维标识必须留下」的不变量。
- compact spec 的用户分维必须编成 `type=user` 不能是 `user_property`（#206 / #208）。这是编译器对一条上游拒句的特例。
- 投放 `data.total` 接受单行数组（#209）。审计原来只认 Mapping。
- `app_id` 按合同类型做 string/int 归一；`advertiser_id` 等同类分裂（6/4、2/2、2/1）没做。
- 在线输入「第一次交目录、第二次按稳定 ID 再解析」（9 条动线）。正确性依赖上游永不复用已删 ID，而上游没有 revision/ETag（`technical-debt.md` 第 3 条）。

**登记在案、门禁永远看不见**

- Census 把路径里有 read 味的 POST 标成 `uncovered_read`（第 6 条）。
- 49 条 `page_info` 仍是 `template_default` / `shape_unproven`（第 7 条）。
- legacy promotion snapshot 绕过绑定（第 2 条）。

**测试形状（1233 个 `test_*` 方法，与 unittest 收集数一致）**

启发式分类（会 `assertRaises` / 调 `read|execute|validate|project…` 的算行为；连续钉数字且无调用的算记账）：

| 类 | 方法数 | 占比 |
| --- | ---: | ---: |
| 行为 | 1174 | 95.2% |
| 记账 | 33 | 2.7% |
| 混合（有调用也钉多个数字） | 4 | 0.3% |
| 薄断言 | 22 | 1.8% |

另外全测试里有 **88** 处 `assertEqual(..., <整数>)`，不全是记账——行为测试里也会钉 `len(rows)==3`。

真正危险的是**棘轮记账**，不是那 33 条的绝对数量：

- `test_actionable_error_audit.py`：`1268 / A896 / B372 / C0`
- `test_gravity_insight_quality.py`：baseline 指标必须逐字相等
- `test_documentation.py`：目录计数对齐合同
- `test_consumer_output_safety.py`：`stable_operations == 228`（与 compiler 的 237 不是同一个集合）
- `test_pagination_contract_audit.py`：历史裁决快照 join 当前合同

记账测试多了会怎样（已发生过）：上一趟为了少写测试把 scatter 的锁删掉，合并前又补回。棘轮不保护「组标签还在不在」，只保护「数字没变」。重构重复实现时，数字棘轮先红，行为回归不一定红。

### 推测

- 33/1233 看起来「记账不多」。真正的税是「每条动线钉一份信封形状」——换共享原语时要同时改 5–8 个产品测试，这是重复实现的影子，不是测试过多。
- 门禁把接线文件压在 500，鼓励继续复制领域文件，而不是把「组标识必须留下」做成一处不变量。这能解释为什么同一投影 bug 能复发四次。

---

## 3. 已经复发过的 bug 家族

材料：`docs/roadmap.d/*.md` 各文件头「结论」+ 相关确凿段。**没读** `docs/roadmap.md`。按根因归类，不按症状。

### 确凿事实

**家族 A — 上游给了，某一层的 allowlist / 形状假设把它丢掉**  
修了四次以上，缺结构性挡板。

| 记录 | 丢掉的东西 | 丢掉的层 |
| --- | --- | --- |
| #206 / `reconcile-round2` | 漏斗 `aggregate_date.group` | 投影 |
| #209 / `reconcile-round3` | 素材标识对不上；`data.total` 数组让分维审计整段跳过 | 合同形状 + 审计 |
| #215 / `group-labels` | 事件行 `用户.设备类型`、scatter `user$os` | 投影 |
| #216（并发在修） | gap 的 `next` 被覆盖 | 导航 |
| `consumer-affordances` | Plan `fetch_strategy`（白名单是死名 `single/serial/parallel`） | Plan 投影 |
| `prod-truth` / `advertised-vs-real` | 17 页 HTTP 记成 1 | `ContextVar` 到不了工作线程 |
| Issue 12（`exports-runtime`） | 公式依赖列触发 additive drift | 投影登记 |

共同根因：每一层自己决定「哪些键合法」。没有一条跨层不变量写着「调用方请求的组/身份/下一步，响应里必须还能看见」。新形状到来时 fail-closed 的方式是**静默省略**，warnings 有时还是空的（#206 漏斗）。

**家族 B — 同一标识在不同层类型/形状不一致**

- `app_id` 55 条合同 string / 28 条 integer（`misleading-traps`）。只做了 `app_id`。
- compact `group_by.source=user` 编成 `user_property`，上游 1004（#206 / #208）。
- 投放过滤：`filtering={"app_id":...}` 被忽略，必须是 `filters=[{field,operator,values}]`（#209）。
- `data.total` 合同写对象，上游给单行数组（#209）。

**家族 C — 完整性分母用错计数器**

- 变现导出 pin 了 26 列产品字段的 19196，真实两列 list 是千万级；文件 100 万行却报 `partial` 不是 `truncated`（`trust-sweep` → `truncated-confirm` 才修对）。
- 分页审计用父线程 `RequestCounter`（家族 A 兼这个）。
- 49 条分页合同仍是模板字段集（`technical-debt` 第 7 条）。

**家族 D — 上游死字段 / 恒 0，调用方当事实**

- `yesterday_count`：7/7 App 全 0，同日归因有量（`misleading-traps`）。
- 标题库 `last_3_day_*`：全 0，同页 `history_*` 和素材报表有正值（`trust-sweep`）。
- `gravity_material_id` 恒 0（`reconcile-round3`）。
- 留存合计行多一个 `values_loss` 占位槽，合同没声明（#206）。

**家族 E — 两套表面说的不是同一回事**

- `operations describe` vs `agent-catalog describe` 曾在 3 张产品卡上少字段（`advertised-vs-real`，已对齐）。
- 13 条 export `currently_callable=true` 但 `gravity run` 是 `UNKNOWN_OPERATION`（已补真实入口）。
- Census `uncovered_read` 用路径词元，把 mutation 标成读。

**家族 F — 识别器特例过拟合后再回撤**

- 「别人」被否定抽取截成「别」（`recognizer-recall`），对着题集加的词已撤。
- 已登记 gap 吞掉同问其余意图（`gap-multi-intent`）。
- 选择层残余 20 题：0 条能安全改词法（`selection-residual`）。宿主臂才是主路径。

**家族 G — 请求级状态没跟着并发走**

- `receipt.py` 三个 `ContextVar`（HTTP receipt、结果 receipt、`RequestCounter`）。并行翻页丢计数已修一次。
- #216 的 `next` 被覆盖是同一家族在导航层。

修了三次以上、说明缺挡板的，就是 **A**。B/C/D 各修过两次，再出现第三次就应该停手写特例。

### 推测

- 下一次家族 A 会出在「还没写进 `allowed_analysis_response_key` 的分析形状」或「又一个产品的 `_safe_page` 白名单」。候选：`union_groups` / `y` / `uid` / `group_cols` 仍被挡住（#215 明文留下）；新的图表辅助结构会再踩一次。
- 家族 F 再加词法规则，收益已被 `selection-residual` 证伪。

---

## 4. 放大到十个分析师会先断在哪

边界：只谈并发与隔离。不谈访问控制、字段过滤、敏感内容检测。上游授权仍是产品边界。

按可能性排序。

### 1) 凭据与进程级单例互相踩 — 高

**确凿**

- `GravityInsightClient.from_env()` / `GravitySDK.from_env()` / `GravityClient.from_env()` 都把 `env_path` 钉在 `PROJECT_ROOT / ".env.gravity.local"`。没有账号参数。
- `CredentialConfig.from_env`：`values = {**file_values, **environment_values}`，**进程环境覆盖文件**。
- session 文件：默认 `.env.gravity.session.local`，按 `GRAVITY_USERNAME` 绑定；用户名变了就删掉旧 session（`bound_session_values`）。
- `get_shared_runtime()`：进程内单例。第二次用另一个 `env_path` **直接 `CredentialError`**。
- `runtime.build_client()`：再套一层进程内 `_CLIENT` / `_EXPERIMENTAL_CLIENT`。CLI 主路径几乎全走这里。
- 登录成功会 `persist` 回写 session 文件。

同一台机器、同一个 Windows 用户、两个 Gravity 账号：

| 场景 | 结果 |
| --- | --- |
| 两个 CLI 进程、同一份 `.env.gravity.local` | 抢写 session；后登录的 token 覆盖先登录的 |
| 两个进程、两份 env 文件，但都走默认 `from_env()` | 双方都读仓库根那一份，第二份文件根本用不上 |
| 同一进程里先后 `from_env()` 两个账号 | 共享 runtime 已锁死第一个 env_path |
| 用户环境里留着 `GRAVITY_AUTH_TOKEN` | 覆盖文件，子进程继承，账号 A 的 token 进账号 B 的命令 |

`from_env()` 的作用域是：**当前工作目录认定的 checkout + 进程环境 + 一份默认文件**。不是「调用方传入的账号」。

### 2) 跨进程限流是乘法，上游配额未知 — 高

**确凿**

- 本进程：默认 **10 rps**（`GRAVITY_REQUESTS_PER_SECOND`，上限 100），业务槽 **24**，SQL 槽 **2**。429 会在**本进程** limiter 上挂冷却。
- SQL 另有实证：2026-08-08 受控探测，**2 路并发成功，4 路进入长重试/失败**（`sql/client.py` 注释）。
- CLI 每次新进程。分析查询冷启动 **3 次 HTTP**（`event.list` + `event_property.list` + query），见 `metadata-cost.md`。cache 带不走。
- 10 个分析师 × 各自 agent 每问起一个 CLI：仅元数据就是 `10 × 问次数 × 2~3`。再加正式 query。
- 10 个进程各有自己的 10 rps / 24 槽，本地限流**不跨进程**。理论上峰值 `10 × 10 = 100` rps 打同一 `api-insight.gravity-engine.com`。

**未知（本趟不打生产，仓库里也没有配额合同）**

- 上游账号级 / IP 级 / 租户级 rps 上限。
- 429 的 Retry-After 是否按账号还是按 IP。
- 十个分析师共用一个上游账号、还是十个账号——两种负载不同，SDK 都没按账号分桶。

### 3) 缓存和本地库没有账号维度 — 中高

**确凿**

| 存储 | key / 路径含账号？ | 作用域 |
| --- | --- | --- |
| `MetadataCache` | **否**。`(operation_id, JSON(inputs))` | 每个 `GravityInsightClient` 实例，TTL 600s |
| `operation-catalog.json` | **否**。`%LOCALAPPDATA%/GravityInsight/operation-catalog.json` | 每 OS 用户一份 |
| metadata SQLite | **否**。`%LOCALAPPDATA%/GravityInsight/metadata/catalog.sqlite3` | 每 OS 用户一份；`os.replace` 整库替换 |
| HTTP receipt | **否**。`workspace.state_root` = cache / `workspaces/<目录名>-<toml路径hash>` | 每份 `gravity.toml` 一份，不是每账号 |
| session | **是**（绑定 username） | 但默认文件名仍是全局那一个 |

同一 OS 用户两个账号：metadata SQLite 和 operation-catalog 会串。MetadataCache 在「两个 Client 实例」之间不串，但 `from_env()` / `build_client()` 通常只有一个实例，且 HTTP 会话已经是账号 A 或 B 的其中一个。

串读的后果不是权限绕过（上游仍按 token 授权），而是 **A 的事件目录被 B 拿去校验字段名**，或 B 的 sync 把 A 刚写下的 catalog 整库换掉。

### 4) 进程内可变状态 — 中

**确凿存在的进程级可变点：**

- `_SHARED_RUNTIME` / `_SHARED_ENV_PATH` / `_PROCESS_LIMITER` / `_PROCESS_BUSINESS_SLOTS` / `_PROCESS_SQL_SLOTS`
- `runtime._CLIENT`、`sql.client._SQL_BUSINESS_SLOTS`（SQL 请求会先拿 SQL 槽，再进 runtime 再拿一次 SQL 槽 + 业务槽）
- `receipt` 三个 ContextVar；`field_metadata_override._ACTIVE_LOADER`
- `receipt_retention._WRITE_COUNTS` + `_STATE_LOCK`（按 `state_root` 扫 receipt 文件）
- `export_policy._BROKER_LOCK`、`registry._AUTHORIZATION_BROKER_LOCK`

单进程多线程（Plan 同层并发）靠这些锁是自洽的。十个进程写同一 `state_root` 的 receipt、同一 SQLite 路径，没有跨进程互斥（metadata sync 用临时文件 + `os.replace`，最后写的赢）。

### 推测

- 十人同时跑的第一声响大概率是 **429 重试把 agent 超时拉长**，或 **session 文件被另一个登录刷掉后突然 401**。不是 SDK 算错数。
- 若十人共用一个上游账号，本地 24 槽 / 10 rps 形同虚设（每进程一份）。
- 若一人一账号但同一台机器同一 checkout，先断的是默认 env 文件和 `%LOCALAPPDATA%/GravityInsight/*`。

---

## 5. 什么该删

能力不许对调用方退化。这里只列「删了重复实现、对外合同不变」的候选。找不到整条产品可删。

### 确凿可以收敛、不丢能力

| 候选 | 为什么不丢 |
| --- | --- |
| 13 份重复的 `MAX_CONCURRENCY = 24` | 改成 `from .http_runtime import MAX_CONCURRENCY`（`pagination.py` 已这样）。值不变。 |
| `_without_legacy_exclusion_phrases` 第二份 | 两个函数逐字相同，留一处即可。识别结果不变。 |
| `client.py` 的 12 个 `_first_probe_*` **搬走**（不是删探测能力） | `probe` / `probe_all` 仍通过 mixin 或 helper 暴露。分析师 `read` 路径不依赖它们住在 Client 类体里。这是给 AST 余量，不是砍探测。 |

### 不要删（有意保留或无消费者证据）

- `promotion_snapshot_compat` / legacy promotion CLI：无遥测证明无人用。删即可能外部破坏。债清单写明是有意保留。
- 79 个 `agent_*.py`、35 个 `*_cli.py`、12 个 `_field_policy_*.py`：`technical-debt.md` 已裁过，合并它们会造 registry/DSL，违反本仓原则。
- 草稿动线对应的 gap 卡（媒体报表、F41）：删卡等于对调用方隐瞒「已查明做不到」。

### 找不到

- 没有「整条已闭环动线其实是另一条的别名、可以下线」的证据。
- 没有第二套 HTTP 栈或第二套 Plan 引擎可拆。blob / export 已共用 `SafeBlobTransfer`。

### 推测

- material / promotion 的 `_safe_*` 现在就下沉，会碰到「看起来同构、字段 allowlist 不同」。债清单的退出条件仍然对：只在下一次两边同时改 page receipt 时，下沉**一个**已由两边测试证明相同的窄原语。不要造结果 DSL。

---

## 推测总栏（不要和上面的表混读）

- 十人场景的第一故障是 429 或 session 互踩，不是算错。
- 家族 A 的下一次复发点是仍被挡住的 `union_groups` / `y` / `uid` / `group_cols`，或下一个产品的 `_safe_page`。
- 把 census/prober 大文件继续留在同一套 500/AST 扫描里，会让「分析动线还能不能加」看起来比实际更绝望。
- 词法识别器再加规则，对「agent 独立完成分析」的边际收益已被 residual 20 题证伪。

---

## 可派发工作清单

按「对 agent 独立完成分析」的影响排序，不是按好做程度。本趟不改代码，下列都是下一派的单。

| # | 标题 | 问 | 影响面（对 agent 消费方） | 预估范围 | 冲突模块 |
| --- | --- | --- | --- | --- | --- |
| 1 | 投影不变量：请求的组/身份键必须在结果里活下来 | 3A / 2 | 分维结果不再变成无标签数字；不再靠下一条动线再修一次特例。`union_groups`/`y` 仍可省略，但行上的组标识不能丢 | 跨模块（`analysis_projection_contract` + 各 query 形状的回归）。建议先离线夹具，生产只抽检一种新形状 | 与 #215/#216 的投影/导航改动同一带；须等那两趟合完再动 allowlist |
| 2 | `from_env()` 按 env 文件隔离，禁止默默共用进程 runtime | 4 | 两人同一台机器不会把对方的 token 写进自己的下一跳；agent 长进程里不能再「换账号却仍用旧会话」 | 跨模块：`http_runtime.get_shared_runtime`、`runtime.build_client`、`client.from_env`、`sdk.from_env`。**不要**加权限模型 | 谁改 CLI 启动路径都会碰 `runtime.py`；与错误消息趟可能同时改 `errors.py` 的凭据文案 |
| 3 | 跨进程 metadata 预取：冷启动别次次打 3 次 HTTP | 4 / 1 | agent 每问起一个 CLI 时，分析查询从「3+1 HTTP」回到「1」。十人并发时元数据流量降一个数量级 | 跨模块：`MetadataCache` 现仅进程内；要落地须带 **env_path/principal** 的磁盘层，或让 FieldPolicy 在合同已登记固定字段时跳过 list。需生产验证一种 query 形状 | 与 #210 已合的 cache API 兼容；不要新建第二套 cache。`client.py` AST 只剩 1，**禁止**往该文件加逻辑 |
| 4 | 完整性计数器单一来源：导出 truncated、分页 HTTP、分维和 | 3C | agent 不再把百万行截断读成 `partial`，不再把 17 页读成 1 次请求 | 跨模块：`export_scope_total` / `dimension_sum_audit` / `receipt.RequestCounter`。导出形状建议再生产抽检一次已确认的变现超限日 | 与导出运行时、resolver 审计同时改信封字段时会撞测试棘轮 |
| 5 | 死字段目录对 agent 可发现（沿用 `unreliable_item_keys`，不删值） | 3D / 2 | agent 不再用 `yesterday_count` / `last_3_day_*` / `gravity_material_id` 做有没有数据的判断 | 单文件到合同级：补登记 + `describe` 已有通道。无需新检测器 | 合同编译 / provenance 串行；不要碰 `client.py` |
| 6 | 拆 `client.py` probe 帮手，给公开读面留 AST | 1 | 本身不改变分析能力；不拆则任何读面 bugfix 都可能因 6765 硬顶失败，动线会卡在「修不进去」 | 单文件迁出 → 新 helper 模块。必须收紧 `client.py` AST baseline。探测行为保持 | **本文件余量 1**。禁止与任何要改 Client 的派单并行 |
| 7 | `sdk.py` / `plan_adapters.py` / `agent_sources.py` 接线墙再下一层 family router | 1 | 新产品能进 SDK/Plan/发现面，而不先撞 500。agent 才能看见新动线 | 跨模块，但是薄路由。`plan_adapters` 已有 family router 先例，照抄不要造 registry | 共享脊骨：必须单人串行接线。与所有新产品派单冲突 |
| 8 | 标识归一从 `app_id` 扩到已证实分裂的 `advertiser_id` 等 | 3B | agent 少踩「这个 route 要字符串、那个要整数」 | 合同 + 输入校验。每个字段先有合同声明再归一，和 `app_id` 同一规则 | `models.py` / 输入校验；勿抬 legacy AST |
| 9 | 词法识别器停刷；宿主臂做主路径的接线收口 | 3F | 剩余选路失败交给 `host_catalog`，不再用新词把别的题打回 `no_candidate` | 跨模块但应是删除规则、不是加规则。评测只跑 development，不跑 holdout/final | 与正在改 `agent*.py` / `find.py` 的 5 趟**直接冲突**。等那批合完由integrator做 |
| 10 | 下一次同时改 material/promotion 信封时，只下沉一个已证同构原语 | 2 / 5 | 减少「修一边漏一边」的信封 bug，调用方信封字段不变 | 跨模块，触发条件见债清单第 1 条。现在不要主动开整文件统一 | 两个 `*_performance_result.py`；质量 500 已贴边 |
| 11 | 默认磁盘路径带 env 文件指纹（catalog / sqlite / receipts） | 4 | 两账号不再互刷 metadata DB 和 probe catalog | 跨模块：`client.from_env` 的 `catalog_path`、`metadata_sync.default_catalog_path`、`workspace.state_root` 仍可按 toml，但 GravityInsight 全局目录必须分桶 | 与第 2 条一起做更省。不要引入 ACL |
| 12 | Census 弱信号 POST 保持禁探，不要批量改 status | 2 | 不直接帮分析师；避免维护者探测打到写路由，污染合同 | 已有闸门。剩余是逐条证据，不是实现 | `prober/read_semantics.py`；与探测预算纪律冲突面在维护者流程，不在 spine |
| 13 | 分页 `shape_unproven` 49 条按用到的产品补证据 | 3C | 只有当某条动线要 `read_all` 全集时才阻塞 agent | 需要生产验证，按产品触发，禁止全量探 | 合同 / `pagination_contract_audit` |
| 14 | 给 `REPORT_PRODUCTS` 改名（`NO_SPEC_PRODUCTS`） | 5 | 零能力变化。防止下一张非 report 卡被接错集合 | 单文件 + 调用点。单独开单不值，和下一次改 `agent_report_routing` 捆 | `agent_report_routing.py`、选路测试 |
| 15 | SQL 双槽（`sql.client` + `http_runtime`）收成一处 | 4 | 避免「看起来还能再加 SQL 并发、实际 4 路已经挂」被第二个信号量掩盖 | 单到跨模块。行为保持 2。有 2026-08-08 探测记录，不必再打生产 | `sql/client.py`、`http_runtime.py`（AST 余量 60） |

第 1、2、3 条不做，十个 agent 同时跑时会先在「结果缺键 / 账号互踩 / 冷启动打爆上游」上失败。其余是为了还能继续加动线。

---

## 本趟未改 / 台账

- 未改 `src/`、`tests/`、评测、`.sealed.json`。
- 未读、未写 `docs/roadmap.md`。
- 未改 `docs/analysis-journeys.md`。表头 **`56 = 51 / 3 / 2` 保持不动**；本趟不闭环、不降级任何动线，冻结 case 无需对账。
- 未 push、未碰 GitHub。
- 未写凭据或业务原值。

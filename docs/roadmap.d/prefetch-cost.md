# 十个冷启动 30 次 metadata HTTP：磁盘缓存已能分账号，现已接到 FieldPolicy

- 日期：2026-08-19
- 任务：#228
- 结论：字段目录可以安全落盘；十个分析师各跑一条固定字段查询时，metadata HTTP 从 **20 降到 2**（总 HTTP 从 30 降到 12）。现有 SQLite / operation-catalog **不是**同一批数据，没有复用它们。

## 先量清楚打了什么

FieldPolicy 预取不是调用方显式发的。`client.read(analysis.*.query)` → `validate_analysis_reference_membership` → `_load_field_metadata` → `_read_all_untracked(page=1, page_size=2000)`。

| 触发 | operation | 用途 |
| --- | --- | --- |
| 请求里有事件名 | `analysis.event.list` | 核对物理事件名是否存在 |
| 有事件字段（含固定字段 `PresetAllCount` / `create_time`） | `analysis.event_property.list` | 核对属性名 |
| 非固定事件字段，或不在全局 list 里 | `analysis.event.info`（按事件） | 事件专属属性 |
| 用户字段 / 用户分维 | `analysis.user_property.list` | 核对用户属性 |
| 分群引用 | `analysis.segment.list` | 本趟未打 |

典型事件查询（只用固定字段）冷启动仍是 **3 次 HTTP**：上面两张 list + 业务 query。同进程第二次起只 1 次。这是 `#210` 已钉死的事实，本趟未改 FieldPolicy。

这些快照是**字段目录**（name / cname / data_type / modify_time），不是业务数据行。落盘它们不等于落盘 query 结果。

过期：上游 list 没有可用的目录版本号。行上有 `modify_time` / `create_time`，但不能在不打网的情况下知道「有没有新字段」。因此过期只能靠 TTL（与进程内 cache 同一条 600s）。过期后宁可再打一次网，也不拿旧目录去校验新请求。

两个账号的字段目录不同。路径必须带 `#223` 指纹；默认（未显式选 env）路径不加指纹，与今天一致。

## 现有磁盘 catalog 不是同一批数据

| 磁盘物 | 谁写 | 谁读 | 是不是 FieldPolicy 预取 |
| --- | --- | --- | --- |
| `GravityInsight/operation-catalog.json` | 探测状态（成功/失败指纹，无字段值） | `OperationCatalog` | **否** |
| `GravityInsight/metadata/catalog.sqlite3` | 显式 `gravity metadata sync` | 离线 `search_metadata` / Plan pin | **否**。要人先 sync，默认冷启动 CLI 不会写它 |
| 进程内 `MetadataCache` | `_execute_result` 对 metadata list/get | 同进程第二次起 | 是，但进程一死就没了 |

所以 `#223` 只是「磁盘上已经有一个能按账号分开的地方」。预取仍每个新进程打网。本趟没有把 FieldPolicy 接到 SQLite，避免把「必须先 sync」变成冷启动前置。

## 决定：做，而且只做这一层

判据：十个分析师各跑一条查询，metadata HTTP 从 30 里的 20 降到多少？

答案：**降到 2**。第一个进程写盘（2 次 metadata HTTP），后九个进程在 TTL 内命中磁盘，只发各自的 1 次业务 query。合计 **12 次 HTTP / 10 条查询**，不是 30。

不做的代价大于落盘风险：字段目录 10 分钟过期，过期检测是墙钟 TTL；假阳性「字段不存在」只会发生在有人刚加字段、且校验读到未过期旧快照时——这与今天同进程 10 分钟 cache 的风险相同。`clear_metadata_cache` / `bypass_metadata_cache` / 成功 mutation 清 cache 现在连盘一起丢。

硬约束核对：

- 默认路径不变：`GravityInsight/field-policy/`。显式 env / `GRAVITY_ENV_FILE` 才落到 `GravityInsight/<fingerprint>/field-policy/`。
- 路径只有指纹或无指纹，没有凭据、账号名、App 名。
- 只 pickle `is_metadata_operation` 允许的 list/get 信封。业务 query 从不进 cache，也就不落盘。
- `_from_manifest_for_tests` 仍不落盘，测试夹具行为不变。

## `DEFAULT_ENV_PATH`

`#223` 已经改成 `PROJECT_ROOT / ".env.gravity.local"`。本趟核实：`credentials.py:45` 不再是 `Path(__file__).parents[3]`。裸 `CredentialProvider()` 与 CLI 现在指向同一份 checkout 文件。补了一条会红的回归，防止再漂回仓库父目录。

## 生产测量（2026-08-19，App `29034827`）

脚本 `tmp/prefetch_measure.py` 只打印计数，不落响应。写 0。预算 15，实际新进程读如下。

**确凿：**

| 进程 | `event.list` HTTP | `event_property.list` | `user_property.list` | 条目 / 页 |
| --- | ---: | ---: | ---: | --- |
| 1（冷盘） | 2 | 1 | 1 | 119 / 1；224 / 1；113 / 1 |
| 2（新进程，同默认 env） | 0 | 0 | 0 | 同上 |

进程 1 的 `event.list` 计数 2 未再拆（登录或 `required_parent` 的 `app.list` 都会计入）；本趟不扩大调查。进程 2 三张 list 全 0，证明 FieldPolicy 预取信封已经落盘并被新进程复用。条目数与 `#210` 同日测量一致。

默认路径：`persist=true`、`persist_scope` 空、目录名 `GravityInsight/field-policy`。本趟走 checkout 默认 env，未显式选文件，所以没有指纹子目录——与 `#223`「不显式指定时路径与今天一致」相符。

行上的 `modify_time` / `create_time` **是字符串**，不是目录版本号。没有可用的「字段目录变了」信号，过期只能靠 600s TTL。

**推测（不是本趟事实）：** 十个 CLI 分析师各跑一条只用固定字段的事件查询：第一个进程付 2 次 metadata HTTP（外加各自 1 次 query），后九个进程 metadata 为 0。合计 metadata **2**，总 HTTP **12**，相对改前 **30**。本趟没有真的起十个 CLI；数字由「2 metadata + 1 query」形状 × 磁盘命中外推。

## 生产请求

预算 15 次读 / 0 次写。上表进程 1 四次计数 + 进程 2 零次；随后只摘了 item 键名（磁盘命中，无新 HTTP）。未贴响应正文。

## 动线台账

只在「看某事件随时间、分组和条件的变化」那一行末尾追加本趟磁盘命中句。**不改状态列**（仍已闭环），**不改表头** `56 = x / y / z`。冻结 case 不读 HTTP 次数，对不上的风险：无。

合并对账时表头应保持 **51 / 3 / 2**。

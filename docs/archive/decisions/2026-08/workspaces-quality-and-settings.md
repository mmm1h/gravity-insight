> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 工作区、质量棘轮与设置复核

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：Kanban/Dashboard CRUD、metadata onboarding、质量棘轮、mutation 归属守卫、设置/应用/变现复核与维度表。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## Kanban / Dashboard 全 CRUD 与持久化工作区（2026-08-16）

**提案与范围裁决：**工作提案保存在 ignored `tmp/codex/write-kanban/proposal.md`。点名代码块实际有
19 个 operation；它来自 21 个 Kanban reservation 排除两条显式 `*.share`。逐 route 与 hash-matched
bundle 复核后，`space.093dd36e.delete` 的真实 path 是 `space/share/delete/`，不是普通 space delete 的
参数变体；当前 bundle 只有未调用 loader，payload 仍未知。因此本轮实际晋升 **18** 条 stable mutation，
该哈希 share-delete 与两条显式 share 共 3 条 reservation 保持 blocked。另一哈希路由
`dashboard.dc7858a7.update` 明确是 `/dashboard/rename/`，body 为 `app_id/id/name/space_id`；普通
`dashboard.update` 是 `/dashboard/edit/`，body 为 `app_id/id/report_list/space_id/ui_config`，两者按独立
端点登记。operation/stable 从 `205/196` 增到 **`223/214`**，即 184 read + 30 governed mutation。

**真实层级与危险语义：**生产 tree 证明 space 根 ID 为正；两个系统 folder 使用负 ID，自建 folder
使用正 ID；dashboard 的 space/folder 坐标由树继承。note 是 dashboard `ui_config` 中
`subject=notes` 的嵌入项，不是 space→folder→dashboard 之后的第四层目录资源。各 move 的含义不同：
`space.move` 是向精确 `uid` 移交所有权；`folder.move` 是携后代跨 space；`dashboard.move` 是 batch/跨
space；`dashboard.folder.move` 是同 space 拖入 folder/未分组；order route 只保存同级顺序。

父删除不是级联删 dashboard。folder delete 的生产 dry-run 在写前报告
`descendant_count=1, dashboards_moved=1, dashboards_deleted=0`，执行后 dashboard `248507` 仍可见；
space delete 的生产 dry-run报告 `descendant_count=2, dashboards_moved=2, dashboards_deleted=0`，执行后
dashboard `248506/248507` 均迁到创建者 space `276292` 的系统 folder `-1`。测试
`test_parent_delete_preview_reports_relocation_before_write` 还用含负 ID 系统 folder 的树锁定“预览先读、
精确计数、write=0”。dashboard 删除则先逐个读 detail，任何 report association 都拒绝；本轮最后以
一个 batch write 删除两个 marker-owned、report_count=0 的 dashboard。

**治理框架扩展：**原 mutation policy 只允许 POST/create|update|delete，不能表达 upstream 的两个 GET
delete 与 move/copy。本轮只扩展注册 operation 的 exact GET/POST 及 create/update/delete/move/copy action；
authorization 仍是一次性快照，transport 固定 attempts=1，自动重试仍禁止。Kanban 父删除 dry-run
允许只读 tree/detail 以计算影响，但不铸造写授权；execute 会重新读 preimage、逐对象校验
`GSDK-<12 hex>`、只发一次写，再读回。负数系统 folder 只在响应模型中允许，调用方目标仍必须是正 ID
或显式 `0=未分组`。CLI/SDK/Plan/Agent 共用同一 action router；Plan 只允许显式 `preview|execute`，Agent
card 声明 `natural_language_auto_execute=false`。共享 CLI/Plan/Agent spine 均保持原 quality ratchet。

**端到端实录：**全部 preview 均 `write_sent=false`，全部 execute 均 `attempts=1`、mutation status
`success`。实际步骤和返回为：

1. `space.create(app=27018426, SDK Kanban E2E)` → `created`, id `276502`, marker `GSDK-acceefa3acd0`。
2. `folder.create(space=276502, SDK Folder E2E)` → `created`, id `170568`, marker `GSDK-c65a9fb6b3b8`。
3. `dashboard.create(space=276502, folder=170568)` → `created`, id `248506`, marker `GSDK-666a6eb5b7e8`。
4. `dashboard.rename(id=248506)` → `updated`，新名保留同一 marker。
5. `dashboard.move-folder(id=248506, folder=0)` → `moved`，读回 `folder_id=null`。
6. `dashboard.copy(id=248506, to_folder=170568)` → `copied`, id `248507`, marker `GSDK-76ffe1d1e43a`。
7. `dashboard.notes.replace(id=248506, notes=1)` → `updated`，读回 note `notes_8b13ad987afb`、marker `GSDK-8b13ad987afb`、report_count `0`。
8. `note.delete(notes_8b13ad987afb)` → `deleted`，detail 读回确认不存在。
9. `folder.delete(170568)` → `deleted`；dry-run/execute 均明确迁移 dashboard `248507`，删除 dashboard 数 `0`。
10. `space.delete(276502)` → `deleted`；dry-run/execute 均明确迁移两个 dashboard，删除 dashboard 数 `0`。
11. `dashboard.delete-many([248506,248507], space=276292)` → `deleted`，删除前两份 detail 均无 report。
12. 最终 `analysis.dashboard.tree` → `GSDK-` marker count **0**，本轮 space/folder/dashboard/note 全无残留。

**生产请求账本：**Gravity operation HTTP 共 **53** 次，另有 2 次不带凭据的公开静态 bundle GET；
合计 **55 < 60**。以下 53 条均来自本地 HTTP receipt，全部 HTTP 200、attempt 1、`retry=false`。#04 是
首次写前 guard 发现负数系统 folder 后的安全失败（没有发 write），#05 是值无关 shape 诊断；随后修正
响应模型并完成一次闭环。同期 receipt 目录中的 Segment 请求属于另一执行流，不计入本单元。

```text
01 authentication | POST | 200 | retry=false
02 app.list | GET | 200 | retry=false
03 analysis.dashboard.tree | GET | 200 | retry=false
04 analysis.dashboard.tree | GET | 200 | retry=false
05 analysis.dashboard.tree | GET | 200 | retry=false
06 analysis.dashboard.tree | GET | 200 | retry=false
07 analysis.datamanageconfig.kanban.space.create | POST | 200 | retry=false
08 analysis.dashboard.tree | GET | 200 | retry=false
09 analysis.dashboard.tree | GET | 200 | retry=false
10 analysis.datamanageconfig.kanban.folder.create | POST | 200 | retry=false
11 analysis.dashboard.tree | GET | 200 | retry=false
12 analysis.dashboard.tree | GET | 200 | retry=false
13 analysis.datamanageconfig.kanban.dashboard.create | POST | 200 | retry=false
14 analysis.dashboard.tree | GET | 200 | retry=false
15 analysis.dashboard.tree | GET | 200 | retry=false
16 analysis.dashboard.tree | GET | 200 | retry=false
17 analysis.datamanageconfig.kanban.dashboard.dc7858a7.update | POST | 200 | retry=false
18 analysis.dashboard.tree | GET | 200 | retry=false
19 analysis.dashboard.tree | GET | 200 | retry=false
20 analysis.dashboard.tree | GET | 200 | retry=false
21 analysis.kanban.dashboard.folder.move | POST | 200 | retry=false
22 analysis.dashboard.tree | GET | 200 | retry=false
23 analysis.dashboard.tree | GET | 200 | retry=false
24 analysis.dashboard.detail | GET | 200 | retry=false
25 analysis.dashboard.tree | GET | 200 | retry=false
26 analysis.dashboard.detail | GET | 200 | retry=false
27 analysis.datamanageconfig.kanban.dashboard.copy | POST | 200 | retry=false
28 analysis.dashboard.tree | GET | 200 | retry=false
29 analysis.dashboard.detail | GET | 200 | retry=false
30 analysis.dashboard.detail | GET | 200 | retry=false
31 analysis.datamanageconfig.kanban.dashboard.update | POST | 200 | retry=false
32 analysis.dashboard.detail | GET | 200 | retry=false
33 analysis.dashboard.detail | GET | 200 | retry=false
34 analysis.dashboard.detail | GET | 200 | retry=false
35 analysis.datamanageconfig.kanban.note.update | POST | 200 | retry=false
36 analysis.dashboard.detail | GET | 200 | retry=false
37 analysis.dashboard.tree | GET | 200 | retry=false
38 analysis.dashboard.tree | GET | 200 | retry=false
39 analysis.datamanageconfig.kanban.folder.delete | GET | 200 | retry=false
40 analysis.dashboard.tree | GET | 200 | retry=false
41 analysis.dashboard.tree | GET | 200 | retry=false
42 analysis.dashboard.tree | GET | 200 | retry=false
43 analysis.datamanageconfig.kanban.space.delete | GET | 200 | retry=false
44 analysis.dashboard.tree | GET | 200 | retry=false
45 analysis.dashboard.tree | GET | 200 | retry=false
46 analysis.dashboard.detail | GET | 200 | retry=false
47 analysis.dashboard.detail | GET | 200 | retry=false
48 analysis.dashboard.tree | GET | 200 | retry=false
49 analysis.dashboard.detail | GET | 200 | retry=false
50 analysis.dashboard.detail | GET | 200 | retry=false
51 analysis.datamanageconfig.kanban.dashboard.delete | POST | 200 | retry=false
52 analysis.dashboard.tree | GET | 200 | retry=false
53 analysis.dashboard.tree | GET | 200 | retry=false
```

两次公开静态 GET 分别读取 hash-matched Dashboard 与 Layout bundle，均 HTTP 200、无重试；只用于确认
路由调用关系，不携带业务凭据或对象数据。没有发送 share、space transfer、跨 space move、order save、
report unlink、任何多维报表/素材/资产 mutation，也没有触碰 holdout/final、key、recognizer、题集或评分。

**动线与错误审计：**新增“创建并管理可持久化的看板工作区与分析便签”1 条闭环动线；表从
`51 = 42 / 1 / 8` 变为 **`52 = 43 / 1 / 8`**。canonical 产品卡从 42 增到 43。caller-recoverable
全仓审计为 **`1112 = A308 / B434 / C370`**；相对基线新增 **37** 个点，**37/37 均为 A 档**。

**最终验证：**unittest **1080/1080**；pytest **1080 passed / 3009 subtests passed**；文档测试
**4 passed**，agent skill 生成器 `--check` 通过；compiler **223 operations / 11 manifests**；quality
**PASS operations=223 / provenance=223 / operation_literals=57**；CLI help 与 `git diff --check` 均通过。
相对题面基线，主测试数只增不减（`1077 → 1080`）。

## 冷启动 metadata onboarding 与产品卡排序（2026-08-16）

**提案与边界：**工作提案保存在 ignored `tmp/codex/metadata-onboarding/proposal.md`。单 App sync 的
“界”定义为**一个显式 App + 固定四类 Analysis metadata + 每个分页 operation 的页上限**：事件、事件
属性、用户属性三个分页 operation 各最多 `max_pages` 页，事件属性分组固定一次，故逻辑请求上限为
`3 * max_pages + 1`；默认 7、硬上限 25。选择这个界是因为 App、对象集合与页数都能在第一次请求前
机械计算，同时不把其他 App、9 类 workspace 词汇或 account lineage 拖进冷启动。runtime 固定 retry 与
最多一次鉴权刷新不计入这个逻辑界；dry-run 明示该事实，执行后从 HTTP receipt 另报实际次数与 retry。

**实现结论：**`metadata sync --app-id ... --dry-run` 零网络/零写入给出界；真实执行只替换目标 App，
保留兼容库中的其他 App、词汇与 lineage，按 operation 报告实际页、对象数、完整/截断和失败。触及页界
时保存安全前缀并返回 `partial/PAGE_BOUND_REACHED`，不冒充完整。`metadata status` 以 SQLite read-only
回答目录存在/兼容、已同步 App、同步时间、年龄/过期、四类对象数与失败；状态为
`missing/not_synced/partial/stale/ready/incompatible`，不构造生产 client。它不能回答上游此刻是否已变、
凭据/权限是否仍有效，也不建立业务词到物理事件的绑定。既有 `sync --all-apps`、workspace vocabulary 与
lineage 行为不变。

**四路与排序：**CLI 为 `metadata sync --app-id/status`；SDK 为 `sync_metadata_app/metadata_status`；Plan
以 `composite(name=metadata_sync)` 和 `metadata_search(kind=status)` 复用现有两类节点；Agent 新增
`metadata:sync_app` 与 `metadata:status` 两张 canonical 卡，并交付同一 Plan。catalog category 的机械排序
固定为 `product(0) → raw_operation(1) → capability_gap(2)`，同类再按 selector 升序；analysis 首 20 项
实测全部为 product 且包含 `analysis.query.spec:event`。回归锁位于 `tests/test_agent_catalog.py`；四路执行
分别由 metadata sync、Plan 与 Agent 定向测试覆盖。

**冷启动成绩：**上一轮温目录实测是 **12 条命令 / 3 HTTP**。严格冷目录在旧版本只能再插入一次
`sync --all-apps`，所以是 **13 条命令**；本租户已知 7 个 App 时，代码可证明最低为
`3 + 1(app.list) + 7*4(App metadata) + 9(workspace sources) = 41 HTTP`，但每 App 自动分页没有页界，
所以旧版精确 HTTP **无法在执行前确定**。新版按生成指南从不存在的独立 SQLite 实走为
**12 条命令 / 7 HTTP**，第 12 条成功得到 `analysis.event.query` governed success；事件来自刚同步的
物理目录，日期是调用方固定单日，没有换 App、扩窗或为非空重试。

**生产 HTTP 账本：**实际 7 次，均 HTTP 200、attempt 1、`retry=false`；认证与最终分析无分页，三个
分页 metadata operation 和 `app.list` 都只读 page 1，非分页分组 operation 的 page 为 null。同步前
上限 7，实际 4 个 metadata HTTP、0 retry，写入 177 个对象，status 离线为 ready。

| # | operation | method | page | HTTP | retry |
| --- | --- | --- | --- | --- | --- |
| 1 | `authentication` | POST | - | 200 | false |
| 2 | `app.list` | GET | 1 | 200 | false |
| 3 | `analysis.event.list` | GET | 1 | 200 | false |
| 4 | `analysis.user_property.list` | GET | 1 | 200 | false |
| 5 | `analysis.event_property.list` | GET | 1 | 200 | false |
| 6 | `analysis.event_property_group.list` | GET | - | 200 | false |
| 7 | `analysis.event.query` | POST | - | 200 | false |

**计数、错误与不改项：**本轮不新增 operation、stable operation 或分析产品动线，仍为 `205 / 196` 与
`51 = 42 / 1 / 8`；canonical product card 为 `42 + 2 = 44`，selector 为 259。caller-recoverable
基线 `1075 = A271 / B434 / C370` 变为 `1084 = A281 / B434 / C369`：新增 10 个 raise site 全部 A 档，
并删除旧的“sync 只能 all-apps”C 档点，所以总数净增 9。没有修改 recognizer、题集、评分、评测装置、
holdout/final、operation 合同、词汇/lineage 范围、raw delete、其他业务域或 consumer 项目；没有读取 key、
解密或运行真实 protected split。技术债清单已逐项复核；领域 CLI/core/Plan/Agent 下沉且共享 quality ratchet
未放宽，没有新增活动结构债。

**验证：**unittest **1083**（基线 1077，+6），pytest **1083 passed / 2955 subtests passed**，文档测试
**4 passed**；compiler **205 operations / 11 manifests**，quality、生成器 check、CLI help 与
`git diff --check` 全部通过。
## 质量棘轮去物理压行（2026-08-16）

**提案与只读调查：**工作提案与逐项调查底稿位于 ignored
`tmp/codex/quality-ratchet/proposal.md`、`investigation.md`。先在 `3295e62` 上冻结清单，再修改代码；
393 个门禁文件中 **17** 个 headroom=0（15 个旧大文件 baseline 等于当前值，另有 2 个正好 500），
headroom≤10 为 **33** 个。Token/AST 扫描得到 **41** 个互斥密度点：10 个分号并行、8 个单行 suite、
10 条 >100 字符单行 import、13 条 >100 字符单行函数签名。Git patch 能直接证明 parent 已顶格且把
两行压成一行的是 **6** 处：`client.py` 1（`1e699ce`）、`executor.py` 3（`db6bf26`）、
`models.py` 2（`db6bf26`、`3295e62`）。另有 4 条长 import 的当前形态在顶格提交中形成或扩展，但
原始动机不能由 Git 证明；其余随初始 baseline 出现或引入时仍有余量，不冒充因果。

**v2 规则：**500 SLOC/文件、80 SLOC/函数、复杂度 15、operation literal 0 四个阈值不变。15 个旧大
文件改用 Python 3.11 AST 节点数 ratchet；格式换行、import/签名换行和分号拆行均不改变该值。每个旧
大文件同时冻结两个不可抬升硬顶：SLOC 硬顶等于 `3295e62` 的原始物理行数，AST 硬顶等于迁移节点数
加 50 个生命周期节点。AST baseline 默认只降；确有必要的增长必须通过
`baseline --record-ast-growth PATH=REASON` 追加精确 from/to/reason，仍不得越过 AST 硬顶。CI 与 PR base
比较 legacy 文件集合、两个硬顶、原始迁移值和 append-only 台账；新文件仍不得超过 500。

选择 AST 节点而非语句数，是为了让新增参数、import alias 和表达式结构也计入增长；保留 SLOC 硬顶，
是为了不让格式空间无限膨胀。没有采用普通 SLOC allowance，因为它仍奖励分号；也没有采用可自由抬升
的 SLOC baseline，因为它没有生命周期上界。相对 v1，**未登记行为增长更严格**，但两个维度有意变松：
格式可在冻结的原始行数内展开；有理由的 AST baseline 可在固定 50 节点总预算内抬升。因此它不是每个
维度都点对点不弱于旧规则；防无限膨胀的硬顶不弱，必要新增有了有限、可审计出口。

**损害修复与反事实：**41 个密度点已修为 **0**。其中 `models.py` 两个 dataclass 字段、receipt/drift
字段均恢复逐行声明，`client.py` 的 257 字符 errors import 改为括号列表；原来位于超长函数内的探针
分号下沉为窄 helper，80 SLOC 硬门没有放宽。`models.py` 为抽出重复字段校验并守住既有函数 ratchet，
登记一次 AST `8597 → 8622`，理由入台账，仍低于不可变硬顶 8647；其余格式修复 AST 不变。
`test_semicolon_packing_has_no_ast_ratchet_benefit` 明确证明两行合一虽使 SLOC `2 → 1`，AST 与 ratchet
结果不变；`test_fifty_added_code_lines_exceed_legacy_ast_hard_limit` 加 50 条赋值并证明固定 AST 硬顶拒绝。

本轮不新增产品动线、operation、stable 能力或 caller-recoverable error site：`51 + 0 = 51`、
`42 / 1 / 8 + 0 / 0 / 0 = 42 / 1 / 8`、operation/stable 仍为 `205 / 196`。生产 HTTP 为 **0 次**；
没有运行 holdout/final/all、读取 key、修改 recognizer、题集或评分逻辑。caller 审计仍为
`1075 = A271 / B434 / C370`，故本线新增错误点/A 档为 `0/0`。

验证为 unittest **1081**（`1077 + 4`）、pytest **1081 passed / 2955 subtests passed**、文档测试
**4 passed**、compiler **205 operations / 11 manifests**；quality 普通检查与对 v1 `HEAD` 的迁移比较、
CLI help、密度清单复扫和 `git diff --check` 全部通过。密度复扫推导为
`41 - 10 semicolon - 8 inline suite - 10 long import - 13 long signature = 0`。
## 干净外部 LLM 的 development 臂 C（2026-08-16）

**提案与安全边界：**工作提案位于 ignored `tmp/codex/clean-selector/proposal.md`。本轮只查询公开的
development 336 题；没有运行受保护 split、读取仓库内 key、查看或解密 sealed suite，Gravity 生产
HTTP 为 **0**。recognizer、题集、评分器、产品卡、gap 登记和目录描述均未修改；结论而非一次性 selector
实现进入版本控制。

**`codex exec` 退出 1 的根因已查清：**最小嵌套 `codex exec --ephemeral --ignore-user-config
--ignore-rules` 在独立临时 cwd 成功，排除了会话锁、`CODEX_HOME` 争用、登录和非交互 flag 缺失。按上轮
adapter 的原 schema 重放后，Codex JSONL stdout 明确返回 HTTP 400 `invalid_json_schema`：
`selectors` 数组使用了结构化输出不允许的 `uniqueItems`。旧 adapter 只把 stderr 放进错误，然而结构化
API error 在 stdout，故表面现象是 exit 1 且 stderr 为空。该 400 在生成前失败、无模型 token；另一次
最小诊断确实生成 8,085 tokens、耗时 8.904 秒，但不属于 selector 测量。

**冻结 selector 与隔离：**首次模型调用前固定为配置的 Anthropic-compatible gateway
（endpoint host 只在 ignored receipt 中保存，host SHA-256 为
`cbbc6105f609684fd699bec44a0d9a2090a8562b64fa1bac70359961fe9da671`）、Messages
`2023-06-01`、`claude-sonnet-4-6`、temperature 0、max output 24,000、省略 top-p/top-k、强制单一
`submit_catalog_selections` tool 且禁止 parallel tool use。唯一 system prompt 的 SHA-256 为
`67d19fb7ecd36ad012e5eca7d95f3e9e4ce9990cbef59dacab91b8b8e27b8924`，全文为：

> You are the only semantic selector in a blinded routing evaluation. Use only catalog and questions from the user request. You have no repository, memory, tools, expected answers, route constants, or case identities. Return one result for every anonymous question id. Choose only exact selector strings from catalog.capabilities. Prefer a product identity over a raw operation when the product covers the request. Choose an exact registered gap only when its catalog description matches an unavailable requested capability. Use an empty selector array only when no supplied product, operation, or gap matches. Return multiple selectors only for genuinely independent multi-intent questions. Do not infer hidden labels or revise earlier choices based on later questions. Set reason to an empty string for every row.

承载真实 Messages 请求的 C# 进程每次都在新建 Windows AppContainer 中启动，只有 `internetClient`
capability、无 host filesystem mount；`APPDATA/LOCALAPPDATA/USERPROFILE/TEMP` 全指向该临时 profile，退出
即删除。它只从 stdin 取得 evaluator 的匿名题面和目录投影；provider 凭据/endpoint 是唯一业务外环境。
同一隔离机制的正向探针可读自身 executable，反向探针对 `AGENTS.md`、evaluator route 常量、公开 target
registry 和 Codex 全局状态四个 sentinel 全部读失败；环境名中没有 `CODEX*` 或 OpenViking，profile 删除
receipt 为 true。evaluator 启动的 Python transport bridge 本身仍处于 host 环境，但它只校验/原样转发
stdin、启动隔离进程、锁定 stdout 和追加 receipt，不做语义选择；若把“selector 进程”严格定义为连这个
transport bridge 也必须没有文件 ACL，则第 1 条只由代码审计而非 OS 权限满足，这是没有消除的边界。

**合成通路与盲选纪律：**唯一一次 authenticated synthetic protected fixture 经
loader → SHA-256 盲化 → selector 子进程 → 257-selector 目录选择 → 完整选择锁 → 冻结评分器通过；模型
HTTP 200、4.055 秒、32,612 input / 50 output tokens。正式 development 仍使用题面清单 SHA-256
`ef463aec89f8ef2b5f6d0aaf818d852b12da623df6e8c076e77b06fcb596f3f6` 确定性打散，按 journey
去分组并断言相邻题 journey 不同，再匿名为 `q-0001...q-0336`。每个 trial 的 336 行在 plugin stdout
前原子锁定并核对 SHA-256，之后才进入原评分器。

| 层 | 臂 A recognizer | 被污染臂 C | 干净外部 LLM 臂 C | 说明 |
| --- | ---: | ---: | ---: | --- |
| 首次产品选择 | `260/336`（77.38%） | `334/336`（99.40%） | **`325/336`（96.73%）** | 比 A `+65` / `+19.35pp`，比污染 C `-9` / `-2.68pp` |
| 参数可填写性 | `248/248` | `248/248` | `247/247` | 只统计首次选择到达的产品 route |
| 离线终点 | `64/88` | `88/88` | `0/81` | 真实 selector 必须 `network_called=true`，现有 scorer 因而把 80 个 gap 记 `gap_not_offline`；此层不能与 replay 公平比较 |
| 错误恢复 | `5/5` | `5/5` | `5/5` | action hard gate 全过 |
| 重复可靠性 | `260/336、64/88` | `334/336、88/88` | `325/336、0/81` | 干净臂为 `pass^1=pass^4`、scored unstable tasks 0 |
| 安全门禁 | PASS / 0 | PASS / 0 | PASS / 0 | Gravity production HTTP 0，违规 0 |

| development 扩题族 | 臂 A | 被污染臂 C | 干净外部 LLM 臂 C |
| --- | ---: | ---: | ---: |
| 口语省略 | `0/12` | `12/12` | `11/12` |
| 只描述业务目的 | `1/13` | `13/13` | `11/13` |
| 多轮追问首轮 | `1/12` | `12/12` | `11/12` |
| 反向否定 | `1/12` | `12/12` | `12/12` |
| 错别字 / 拼音 | `3/12` | `12/12` | `12/12` |
| 中英混杂 | `10/12` | `12/12` | `12/12` |
| 跨产品多意图 | `1/12` | `10/12` | `10/12` |
| 目标 gap | `3/11` | `11/11` | `11/11` |

干净臂的 11 个首次失败为 9 个 `wrong_product` 和 2 个 `wrong_intent_candidates`。J06 同口径跨期比较的
7 种问法整组都错；另有 workspace SQL 与分析模板各 1 个间接业务目的错误，以及与污染臂相同的 2 个
混合多意图失败。四 trial 的正确/错误集合完全相同，但 exact mapping 并非完全确定：trial 1 的 J06
七题选择 `composite:derived_metrics`，trial 2--4 改为 `composite:saved_analysis`，两者都错；因此现有
`unstable_tasks=0` 只证明评分布尔值稳定，不能证明模型答案逐字稳定。

**调用、token 与成本账本：**只试 **1 个 selector prompt**。selector 共 2 次 evaluator run：1 次合成
fixture（1 个模型调用）和 1 次正式 development（固定 4 个独立模型调用）；无 prompt 变体、无提分重跑、
无 selector retry。正式 4 调用均 HTTP 200，provider/model returned 与 pinned model 一致，单次延迟
87.862 / 87.744 / 86.744 / 88.523 秒；合计 185,268 input、33,544 output、5,333 cache-write、
15,999 cache-read tokens。含合成调用总计 **5 个模型调用**、217,880 input、33,594 output、8,656
cache-write、15,999 cache-read tokens。按 [Anthropic 公开 Sonnet 4.6 标准价](https://www.anthropic.com/news/claude-sonnet-4-6)
`$3/$15` 每百万 input/output、
5 分钟 cache write `$3.75`、cache read `$0.30` 粗估约 **US$1.19**（正式约 US$1.08）；实际 gateway
账单未提供，不能把估值当实扣。模型列表 GET 1 次和 Codex schema 400 各不产生推理 token；上述 Codex
8,085-token 诊断走 ChatGPT 登录，未获独立价格 receipt。

**结论与效度：**`325/336` 介于两臂之间，但明显更接近 `334`（差 9）而不是 `260`（差 65），八族中
反向否定、错拼、中英、多意图和 gap 完全复现污染臂，故“宿主 LLM 拿完整目录能显著胜过 recognizer”
获得第一份较可信 development 证据；不能再把 `334` 当真实模型测量值，也不能把 9 题下降抹掉。尚未
消除的威胁是：host transport bridge 没有 OS 级文件拒绝、compatible gateway 只能由返回 model ID/
usage/response ID 自证底层权重、endpoint 为非 TLS HTTP 因而 receipt/内容可能受中间层影响、temperature 0
仍出现 exact mapping 波动、同一大批输入可能触发 provider cache，以及 offline-terminal scorer 与必须
联网的 selector 定义机械冲突。下一步可以花 **一次 holdout** 检验开发集问法泛化，但前提是先决定是否
接受上述 bridge/gateway 证据等级；若要求四条判据逐字无保留满足，应先把 evaluator transport 也移入
OS 隔离并换成可独立认证的 TLS provider，再使用唯一留出机会。

本轮不新增产品动线、operation、stable 能力或 caller-recoverable error site；技术债清单已复核，
AppContainer 与 bridge 都是 ignored 测量装置，不进入产品结构债。验证为 unittest **1077**、pytest
**1077 passed / 2955 subtests passed**、文档测试 **4 passed**、compiler **205 operations / 11 manifests**；
quality PASS（operations=205）、CLI help 与 `git diff --check` 均通过。caller-recoverable 审计保持
`1075 = A271 / B434 / C370`，新增错误点/A 档为 `0/0`。

## Metadata onboarding 合入 AST 质量棘轮（2026-08-16）

**合并裁决：**将 `origin/dev@d5cc59b` 以 merge 方式合入 `codex/metadata-onboarding`，保留双方原始
提交对象。六个共同修改文件中，`analysis-journeys.md` 同时保留 metadata 冷启动说明和干净 selector
测量，`index.md` 同时保留 metadata 入口/259 selector 更新和分群删除调查链接，`technical-debt.md`
同时保留 44/44 产品卡结论和 AST ratchet v2 规则，`roadmap.md` 保留双方完整追加章节。`cli.py` 的自动
合并同时保留 metadata CLI 下沉和 dev 的可读多行校验；`metadata_sync.py` 保留 dev 的多行 import 格式，
但不恢复已经随 CLI 函数迁到 `metadata_cli.py` 的未使用 import。没有丢失任一边的文档或调用能力。

**AST 决策：**选择把新增 CLI 注册与 dispatch 留在独立 `metadata_cli.py`，不登记 legacy 增长。
合并后 `cli.py` 为 **4117 AST nodes**，与 dev baseline 的 4117 相同；不可抬升硬顶为 4167，余量 50。
因此没有 `cli.py` 的 from/to/reason 记录，也没有改写既有 baseline 或门禁实现。

**计数与验证：**动线表按状态列重数为 55 个数据行，减 4 个明确不计行后为
`51 = 42 已闭环 / 1 部分闭环 / 8 完全缺失`；双方本轮净变化均为 0。测试数从共同基线 1077 加 dev
质量线 4 个、metadata 线 6 个，得到 unittest **1087**、pytest **1087 passed / 2955 subtests passed**。
compiler 为 **205 operations / 11 manifests**，quality 和 CLI help 通过。caller-recoverable 审计为
`1084 = A281 / B434 / C369`。本次纯合并生产 Gravity HTTP **0 次**；未运行真实 holdout/final/all、
未读 key，未修改 recognizer、题集或评分逻辑。

## Kanban 写能力合入 dev（2026-08-16）

**合并裁决：**将 `origin/dev@4646347` 以 merge 方式合入 `codex/write-kanban`，共同祖先为
`3295e62`。17 个共同修改文件中，`roadmap.md`、`analysis-journeys.md`、`index.md` 与
`technical-debt.md` 同时保留 Kanban 和 dev 四条线的追加结论；README、Agent workflow 与 CLI
参考按合并后的真实能力重写计数和边界。`docs/agent-skills/*` 没有手工拼接，而是在合并
`generate_agent_skills.py`、产品卡和 operation 源后统一重新生成并通过 `--check`。

能力集合同时保留 `kanban.mutation`、`metadata:sync_app` 与 `metadata:status` 三张相对共同基线新增的
canonical 卡，产品卡从 `42 + 1 + 2` 得到 **45**，45 个 selector 全部唯一；Plan 同时保留 Kanban
显式 `preview|execute` 路由、metadata database 传递与固定 composite 的 metadata-aware 执行。
caller-recoverable 审计从两侧增量合并为 **`1121 = A318 / B434 / C369`**，计数断言按实际集合更新，
没有以任一父提交的旧值覆盖另一边。

**计数与验证：**动线表按状态列重数为 **`52 = 43 / 1 / 8`**；unittest **1090**，pytest
**1090 passed / 3009 subtests passed**；compiler **223 operations / 11 manifests**；quality PASS
（operations/provenance **223/223**、operation literals 57），生成器 check 与 `git diff --check` 均通过。
本次纯合并生产 Gravity HTTP **0 次**；未运行真实 holdout/final/all、未读 key，未修改 recognizer、
题集或评分逻辑，也未实现任何 share 语义。合并与交叉测试没有发现任一父线的实现缺陷。

## 三域 mutation 归属守卫改为 marker OR owner（2026-08-16）

**提案与开工证据：**工作提案保存在 ignored `tmp/codex/owner-gate/proposal.md`。本轮先创建
marker space/dashboard，再读取登录 principal、space membership 与 dashboard detail/members；literal
`creator[].uid == gravity_id` **没有证成，且线上形状反驳了该写法**：`creator` 实际为单个 object，只有
`id/name`。可证成的是同一对象的 `creator.id == gravity_id`，以及 dashboard
`create_user_id == gravity_id`；两条 owner ID 与登录 principal 完全相等。未用空数组、字段名猜测或 marker
替代这项证明。

逐写对象族的稳定 owner 事实并不一致：Segment list/detail、v2 report list/detail、v3 自有模板
list/detail、subscription list 与 dashboard detail/tree 使用 `create_user_id/create_user_name`；Kanban
space 的 membership 使用 `creator.id/name`。Kanban folder 与 note 没有已证实的直接 owner 字段，故非
marker folder/note 必须 fail closed。notes replace 与 report unlink 的直接授权目标仍是 dashboard，可使用
dashboard owner；note delete 的直接目标是 note，只能使用 note marker。tree 本轮线上观察到的 dashboard
`create_time/create_user_id/create_user_name/modify_time/refresh_type/update_user_id/update_user_name` 已全部加入
v2 投影、golden 与稳定隐私复核；没有把这些 union 字段推断成 folder owner。

**共享 principal、授权与 marker 裁决：**登录 `gravity_id` 现在以 `GRAVITY_PRINCIPAL_ID` 随 token 缓存，
由 `CredentialConfig/CredentialProvider → GravityHttpRuntime → Transport → MutationClientMixin` 提供只读共享
principal；旧 token cache 缺 principal 时只刷新一次，marker 路径不要求登录刷新。三域统一由
`mutation_ownership.py` 判定 `GSDK marker OR proven owner == current principal`，否则
`OWNERSHIP_REQUIRED/caller/2` 同时报告对象 ID、owner ID/name/field、current principal 与下一步；marker
继续只承担创建来源和幂等关联。

`mutation_policy.py` 删除 action 单词 allowlist。mutation authority 只来自 registry 中完整相等的
`stable + executable + effect=mutation + exact auth_profile + exact method/path` contract、一次性 nonce、wire
snapshot 与 digest；transport 仍固定 mutation `attempts=1`。因此接新域不再修改动作词表，只能新增并评审
精确稳定 operation contract。本轮没有改 one-shot executor。

**自然拆分与质量：**原 `report_mutation.py` 为 499 physical lines。按 report/template 与 subscription
边界拆为 `report_mutation.py` **330 SLOC / 348 physical lines**、`report_subscription_mutation.py`
**175 / 189**，共享 catalog/detail/readback/owner 原语位于 `report_mutation_support.py` **331 / 383**；没有
压行或创建 CRUD DSL。Kanban dashboard delete 同样因本轮触及自然下沉为独立 143 SLOC 文件，原 dashboard
模块 414 SLOC，所有新文件低于 500/80/15 门禁。`http_runtime.py` 的通用 principal/refresh 原语下沉后 AST
从 3765 降至 3747，quality baseline 只收紧该值。

**有意能力收紧清单：**以下调用过去可能发 write，现在会在写前拒绝；这是本轮获授权的安全例外。

1. Segment `update`（名称/备注）、`update-rule`、`refresh`：目标无 marker 且
   `create_user_id != principal` 或 owner 缺失。
2. Kanban `space.rename`：space 无 marker 且 membership `creator.id != principal` 或 creator 缺失。
3. Kanban `folder.rename`：folder 无 marker；当前 folder 无直接 owner，故只能改 SDK marker folder。
4. Kanban `dashboard.rename`：dashboard 无 marker且 `create_user_id != principal` 或 owner 缺失。
5. Kanban `dashboard.copy`：source 无 marker且 owner 不匹配/缺失；此外 destination space/folder 也必须
   分别通过 marker-or-owner。
6. Kanban `dashboard.order.save`：旧逻辑只要求整棵树存在任意一个 marker；现在提交树中的**每个**对象都
   必须通过。任一非 marker folder 因无直接 owner 会使整次 order fail closed。
7. 既有 marker-guarded `folder.move`、`dashboard.move-folder`、`dashboard.move` 新增 destination guard：
   即使 source 合法，foreign/unowned destination space 或非 marker folder 也会拒绝；copy 的 destination
   收紧已列于第 5 项。

其余原 marker-guarded delete/transfer/content 动作没有收紧 marker 行为；self-owned 非 marker Segment、
Report/template/subscription、space/dashboard 反而新增可写能力。folder/note 的限制来自上游不返回可证明
owner，不是本地产品选择。

**生产端到端与缺口：**同一 principal 的非 marker 情形确实成功，不由 marker 回归冒充：dashboard
`248508` 先经稳定 rename route 去 marker，再由正式 dashboard delete 以 `basis=upstream_owner` 删除；
Segment `44546` 与 Report `16793804` 均由 SDK 创建、稳定 update 去 marker，再由正式 delete 以
`basis=upstream_owner` 删除并通过完整 list readback。marker 回归由 space `276503` 的正式 delete 以
`basis=sdk_source_marker` 成功证明；三域 marker 行为另有回归测试。

真实 foreign 生产样本**没有取得，不能记为通过**：Segment 和 Report 删除后的完整目录都没有 foreign
owner 行；dashboard tree 也没有 foreign dashboard。最后再读取完整 tree 并检查当前唯一 space 的
membership，creator 仍是当前 principal。没有为了制造样本而把对象转让给真实其他用户，也没有伪造
principal。foreign/missing-owner 的写前零 write 拒绝由三域测试覆盖，但生产第三情形仍是明确证据缺口。

所有本轮创建对象已清理：dashboard `248508`、space `276503`、Segment `44546`、Report `16793804`
均由各自写后 readback 证明消失；Report 首次去 marker 在本地因响应 ID 为 integer 而合同要求 string 被拒，
没有发送 HTTP，随后规范化 ID 后复用同一对象完成 owner 删除。残留清单为空。

**生产 HTTP 逐条账本：**合计 **41 / 45**。每条均 HTTP 200、attempt 1、`retry=false`；只有明确列为
`page=1` 的目录首屏，没有第二页、扩窗、换 App 或自动重试。#10 是 create 已成功后的本地
ungrouped `null/0` 读回比较错误，没有重发 create；实现已修正该比较。

```text
01 authentication | POST | 200 | page=- | retry=false
02 app.list | GET | 200 | page=1 | retry=false
03 analysis.dashboard.tree | GET | 200 | page=- | retry=false
04 analysis.datamanageconfig.kanban.space.create | POST | 200 | page=- | retry=false
05 analysis.dashboard.tree | GET | 200 | page=- | retry=false
06 analysis.dashboard.space_members.list | GET | 200 | page=- | retry=false
07 authentication | POST | 200 | page=- | retry=false
08 analysis.dashboard.tree | GET | 200 | page=- | retry=false
09 analysis.datamanageconfig.kanban.dashboard.create | POST | 200 | page=- | retry=false
10 analysis.dashboard.tree | GET | 200 | page=- | retry=false
11 authentication | POST | 200 | page=- | retry=false
12 analysis.dashboard.tree | GET | 200 | page=- | retry=false
13 analysis.dashboard.detail | GET | 200 | page=- | retry=false
14 analysis.dashboard.members.list | GET | 200 | page=- | retry=false
15 authentication | POST | 200 | page=- | retry=false
16 analysis.datamanageconfig.kanban.dashboard.dc7858a7.update | POST | 200 | page=- | retry=false
17 analysis.dashboard.tree | GET | 200 | page=- | retry=false
18 analysis.dashboard.detail | GET | 200 | page=- | retry=false
19 analysis.datamanageconfig.kanban.dashboard.delete | POST | 200 | page=- | retry=false
20 analysis.dashboard.tree | GET | 200 | page=- | retry=false
21 analysis.dashboard.tree | GET | 200 | page=- | retry=false
22 analysis.datamanageconfig.kanban.space.delete | GET | 200 | page=- | retry=false
23 analysis.dashboard.tree | GET | 200 | page=- | retry=false
24 analysis.segment.list | GET | 200 | page=1 | retry=false
25 analysis.segment.from.rule.create | POST | 200 | page=- | retry=false
26 analysis.segment.list | GET | 200 | page=1 | retry=false
27 analysis.segment.detail | GET | 200 | page=- | retry=false
28 analysis.dataanalysis.segment.update | POST | 200 | page=- | retry=false
29 analysis.segment.detail | GET | 200 | page=- | retry=false
30 analysis.dataanalysis.segment.update | POST | 200 | page=- | retry=false
31 analysis.segment.list | GET | 200 | page=1 | retry=false
32 report.report.list | POST | 200 | page=1 | retry=false
33 report.report.update | POST | 200 | page=- | retry=false
34 report.report.list | POST | 200 | page=1 | retry=false
35 report.report.detail | GET | 200 | page=- | retry=false
36 report.report.update | POST | 200 | page=- | retry=false
37 report.report.detail | GET | 200 | page=- | retry=false
38 report.report.update | POST | 200 | page=- | retry=false
39 report.report.list | POST | 200 | page=1 | retry=false
40 analysis.dashboard.tree | GET | 200 | page=- | retry=false
41 analysis.dashboard.space_members.list | GET | 200 | page=- | retry=false
```

**门禁与边界：**caller-recoverable 审计从 `1121 = A318/B434/C369` 变为
**`1124 = A321/B434/C369`**，新增 **3/3 全 A**。unittest **1092**、pytest **1092 passed /
3009 subtests passed**；compiler **223 operations / 11 manifests**，quality PASS
（operations/provenance 223/223、operation literals 57），CLI help、稳定隐私审计与 `git diff --check`
均通过。本轮没有接四个新域、没有增加推广/素材/资产/归因写能力，没有改 Plan/Agent/recognizer、题集、
评分、holdout/final/key，也没有做 GitHub、push、PR、tag 或 release 动作。
## 设置、应用、元数据与变现报表复核（2026-08-16）

**提案与边界：**书面提案位于 ignored `tmp/codex/settings-monetization/proposal.md`。本轮先从引力自然
页面动作确认“设置 → 应用管理 / 元数据”的真实请求，再只用现有 stable read 复核 D28；不绕过 POST
读语义闸门，不写业务对象，不修改多维报表模板，也不读取 holdout/final/key。公开
`NewReportCenter-Dxgo5EkI.js` 只 GET 一次并以内存核对，SHA-256 与本页既有 D28 冻结记录一致；
静态资源、CORS preflight 与 telemetry 不计下表生产业务 API。

**三条裁决：**

- 设置 → 应用管理的真实账号级目录是既有 `app.list`：
  `GET /turbo_engine/api/v1/user/open_app/list/`。首屏 HTTP 200 非空 7 行；17 个 item wire 字段和
  `page/page_size/total_number/total_page` 已全部存在于 v4 投影（另有兼容别名），故不新增 operation。
  它与 `app.project.list` 的 `POST /turbo_engine/api/v1/user/project/list/` **不是同一端点**；后者的
  账号级明确空事实继续保留，但不再阻塞 J39。删除 `APP_PROJECT_ITEM_SCHEMA_MISSING` gap 后，中英首问
  都交付可执行 `app.list` raw-operation 卡；CLI/SDK/Plan 使用同一 stable 合同。
- 设置 → 元数据的真实表目录是
  `POST /turbo_engine/api/v2/event_dim/data_table/list/`。页面自然请求
  `app_id_list=[]/name_like=""/page=1/page_size=10` 返回 HTTP 200 明确空；没有表名或 `table_id`，所以
  detail/version 均未发送，“当前版本”也无权威语义。F41 保持完全缺失；没有可发现父对象、读回和
  删除后验证时，排期中的维度表 CRUD 不能安全实施或闭环。
- D28 三选一判为**请求参数/路由不对**。当前 hash-matched `NewReportCenter` 从
  `/turbo_engine/api/v3/confmetric/metric/list/` 与同命名空间 permission route 读取
  `monetization_report` 配置，filter operator 为 `EQUALS`，并按 `is_media=false|true` 区分预估/实际；
  现有 stable `report.multidim.metric.list` 仍指向旧 `/report/api/v3/confmetric/metric/list/`。错误
  operator 和当前正确 filter 在旧 route 都被语义拒绝；宽目录 5 页也没有目标 topic。这一判据能确认
  **我们当前的请求错了**，却不能确认底层租户没数据或权限未生效。主结果与 `calc_total` 本轮均未补发，
  所以没有登记任何非空 item/total、指标或维度字段。

**生产业务 HTTP 逐请求账本：**目标尝试为 `App 1 / F41 1 / D28 7`；辅助请求是打开对应自然页面时
自动触发的只读配置读取。总计 **16**，全部 attempt 1、无 retry；只有第 11--15 笔是分页，不是重试。
第 11 笔所在 CLI 调用未显式设 `max_pages=1`，因上游把 page size 限为 40 而自动读到默认 5 页；发现后
没有继续翻页或换参数追数据。D28 在 7/8 次目标上限时停手。

| # | 归属 | operation / method / route | HTTP | 重试 / 翻页 | 结果 |
| ---: | --- | --- | --- | --- | --- |
| 1 | App 目标 | `app.list` — GET `/turbo_engine/api/v1/user/open_app/list/` | 200 | 否 / 仅页 1 | 非空 7 行；shape 与 v4 投影一致 |
| 2 | App 页面辅助 | `account user list` — GET `/account_center/api/v1/user/list/` | 200 | 否 / 否 | 应用管理页面配套读取；不作为 J39 目标合同 |
| 3 | F41 页面辅助 | `event list` — GET `/turbo_engine/api/v2/event/event_list/` | **未知** | 否 / 否 | 请求已发送；浏览器结束捕获前未收到状态，不据此作合同结论 |
| 4 | F41 目标 | `metadata.data_table.list` — POST `/turbo_engine/api/v2/event_dim/data_table/list/` | 200 | 否 / 仅页 1 | 明确空；detail/version 0 次 |
| 5 | D28 页面辅助 | `tutorial mark` — GET `/account_center/api/v1/baseconf/tutorial_mark/` | 200 | 否 / 否 | 配置读取 1 |
| 6 | D28 页面辅助 | `tutorial mark` — GET `/account_center/api/v1/baseconf/tutorial_mark/` | 200 | 否 / 否 | 配置读取 2 |
| 7 | D28 页面辅助 | `template tree` — GET `/turbo_engine/api/v3/conftemplate/template/tree/` | 200 | 否 / 否 | 报表页目录配置 |
| 8 | D28 页面辅助 | `advertiser status` — GET `/turbo_engine/api/v1/media_manager/advertiser_state_message/latest_account_status/` | 200 | 否 / 否 | 账户状态配置 |
| 9 | D28 页面辅助 | `preset template list` — POST `/turbo_engine/api/v3/conftemplate/perset_template/list/` | 200 | 否 / 否 | 只读模板目录；未修改模板 |
| 10 | D28 目标 1 | `report.multidim.metric.list` — POST `/report/api/v3/confmetric/metric/list/` | 200 | 否 / 页 1 | `IN monetization_report`，语义拒绝；receipt `605019d4ec044a6599c9e1992797e97c` |
| 11 | D28 目标 2 | 同上 | 200 | 否 / 页 1 | 空 filter 宽目录；receipt `7e55605874e54f1dbeedff98fe74536e` |
| 12 | D28 目标 3 | 同上 | 200 | 否 / 页 2 | 同一次宽目录分页；receipt `c0024e6fad30455abf351ffb3413f692` |
| 13 | D28 目标 4 | 同上 | 200 | 否 / 页 3 | 同一次宽目录分页；receipt `4786a35eb1fa40459c8f72883e3591b7` |
| 14 | D28 目标 5 | 同上 | 200 | 否 / 页 4 | 同一次宽目录分页；receipt `1ee65e5f7fdb4fd2ad4726fff9fa0df1` |
| 15 | D28 目标 6 | 同上 | 200 | 否 / 页 5 | 累计 200/1124 行，无 `monetization_report`；receipt `18a9304c6772428fb1713fea45e8eb04` |
| 16 | D28 目标 7 | 同上 | 200 | 否 / 页 1 | 当前 `EQUALS data_topic + is_media=false` filter 在旧 route 语义拒绝；receipt `463247b528014ed988cf096928aa18f0` |

**计数与停止判断：**只有 J39 从完全缺失转已闭环，因此台账由 `52 = 43 / 1 / 8` 变为
**`52 = 44 / 1 / 7`**。operation/stable 为 223/214 不变，canonical 产品卡仍为 45；删除一个已解除
gap 后安装目录为 `223 + 45 + 9 = 277` selector。F41 应停：当前租户没有父表，重复第一页不能产生
schema。D28 也应停：7 次已经定位为旧 route 问题，剩余 1 次不足以依次证明当前 config、permission、
主结果和 total，继续在旧 route 换参数只会消耗预算。下一轮只能从当前 turbo config/permission 的
一次自然请求开始；若仍无可用物理字段，再把事实归为权限或数据，而不是猜主请求。

本轮产品实现只删除错误的 J39 gap 和补强既有 `app.list` 的 Agent 发现描述；没有新增
caller-recoverable error site，因此新增错误点/A 档为 **0/0**，审计应保持
`1121 = A318 / B434 / C369`。最终验证为 unittest **1090**、pytest
**1090 passed / 3009 subtests passed**、compiler **223 operations / 11 manifests**；quality、Agent Skill
生成器 check、CLI help 与 `git diff --check` 全部通过。unittest 的 protected-split 治理用例只在临时目录
生成 synthetic fixture；仓库真实 query ledger 无改动，没有读取或运行真实 holdout/final。

## 维度表 wire 与分析价值探测（2026-08-16）

**提案与边界：**本轮只用 hash-matched 前端还原 9 条维度表预留 wire，并在不超过 50 次生产 HTTP 内
创建、读回和清理唯一 marker 对象；不改 operation、manifest、产品卡或动线。真正绑定前必须先证明
最后一条属性关联能解除，否则立即停止。完整逐 route wire、响应 fingerprint 和账本见
[维度表 wire 与分析价值探测](../../research/dimension-table-wire-probe.md)。

**实测裁决：**三份 bundle 与冻结 SHA-256 逐字一致，9 条 body 均已还原。绑定前分析基线固定
App `26827043`、`order_status.order_id` 和 2026-08-15 单日；第一次因漏 `create_time` 被语义拒绝，
按离线 compiler 修正后返回 5,000 个分组、72,402 次事件。create 成功产生 marker 表
`71ccfb34acd94f6aa3ef69d9ce1976fd`、两列、三行和生效版本 1；list/detail/edit 均成功。

绑定前对未绑定自建表发送 `prop_list=[]`，上游明确返回 `code=1004 / prop_list is empty`；前端也强制
至少保留一条关联。因而没有可证明的解除最后一条绑定路径，本轮按条件立即停止，没有发送非空绑定、
新版本、版本切换或绑定后分析。delete 成功后 marker list 为 0，version-id-set 为 `[]`，且属性绑定从未
创建，残留为 0。生产实际为 **13 HTTP = 1 authentication + 12 business**，全部 attempt 1、无重试、
翻页、换 App 或扩窗。

**排期裁决：**本轮未证明“裸 ID → 业务属性 → 分析分组/筛选”，所以剩余 8 条预留路由暂不实现；
`dl/column_and_val` 还被前端证明是 export/download task，不是 reservation 名称声称的 delete。下一单
必须先取得 API owner 的精确解绑合同，再做解绑回读和绑定前/后同查询对照。动线状态、operation/stable、
产品卡和 selector 均净增 0；`52 = 44 / 1 / 7`、`223 / 214`、45 张产品卡与 277 selector 保持不变。

**验证：**文档定向测试 **4 passed**；unittest **1090 tests OK**；pytest
**1090 passed / 3009 subtests passed**；compiler **223 operations / 11 manifests**；quality、Agent Skill
生成器 check、CLI help 与 `git diff --check` 全部通过。新增 caller-recoverable error site 为 **0**，审计基线
保持 **1121 = A318 / B434 / C369**。unittest 的 protected-split 用例只在临时目录生成 synthetic fixture；
仓库真实 query ledger 未改动，没有读取或运行真实 holdout/final。


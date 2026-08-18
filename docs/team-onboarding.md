# 数据分析团队上手包

给两类读者：分析师（人）负责装、登录、喂上下文、验收数字；agent（机器）被接进来之后按本文命令走。不要先打开 Gravity Web。

当前租户里，**大部分 App 没有投放**，空结果是预期，不是工具坏了。投放中、对账用过的是抖音版「甜甜旅行」，`app.list` 字段名是 `id`（不是 `app_id`）：`29034827`。同产品还有快手 / Android / iOS / 微信分身；点名「甜甜旅行」不够填 App。

---

## 分析师先做的三件事

1. 本机装 SDK、交互登录（下一节）。不要把账号、密码、token 写进仓库或对话。
2. 把本文「Agent 冷启动」整段交给你的 agent（codex / Claude）。它读完再问你业务问题。
3. 重要的数，用第二条 route 对一遍。2026-08-18 四轮生产对账每一轮都抓出过真 bug，不是客套。

---

## 1. 接入

### 1.1 安装

要求 Python 3.11+。在本仓库根目录：

```powershell
python -m pip install -e .
$env:PYTHONPATH='src'
python -m gravity_sdk --help
```

`gravity` 不在 `PATH` 时一律用 `python -m gravity_sdk`。本机若同时检出了别的 Gravity 仓库，**不设 `PYTHONPATH=src` 会静默 import 到那份**。

### 1.2 认证（只写机制和文件名）

在交互式终端运行：

```powershell
python -m gravity_sdk
```

按提示输入用户名和密码。SDK 验证登录后，在用户私有目录维护会话 token。项目目录只需未提交的 `.env.gravity.local`：

```dotenv
GRAVITY_USERNAME=your-account
GRAVITY_PASSWORD=your-password
```

不要配置 `GRAVITY_AUTH_TOKEN` 或 `GRAVITY_SDK_HOME`，不要提交该文件。`--help`、目录搜索、`find`、recipe 检查、本地 metadata 不需要凭据。

检查会话，不发起业务查询：

```powershell
python -m gravity_sdk insight auth status
```

看 `token_valid` / `auth_state` / `next_action`。过期或 `missing` 时按 `next_action` 再跑一次交互 `gravity`。离线合同自检：

```powershell
python -m gravity_sdk insight --dry-run
python -m gravity_sdk sql --dry-run
```

依据：[快速上手](getting-started.md)。

### 1.3 Agent 冷启动：先读、再列目录

agent 被接进来之后，**按这个顺序读，不要通读文档树**：

1. 本页（你正在读的文件）。
2. [Agent 任务指南](agent-skills/index.md) 的任务表，再按任务打开对应短指南。
3. [Agent 工作流](agent-workflow.md) 只在要执行具体产品时再读。

然后跑这四条，全部离线、不执行查询：

```powershell
python -m gravity_sdk agent-catalog categories
python -m gravity_sdk agent-catalog category analysis --limit 20
python -m gravity_sdk agent-catalog describe analysis.query.spec:event
python -m gravity_sdk agent-catalog host
```

本机 2026-08-18 实测（`PYTHONPATH=src`，exit 0，`offline=true`，`network_called=false`）：

| 命令 | 信封 | 看到什么 |
| --- | --- | --- |
| `categories` | `gravity.agent-catalog.v1` / `list_categories` | 10 个领域：`account/analysis/app/attribution/capability_gap/export/material/metadata/promotion/report` |
| `category analysis --limit 5` | `get_category_capabilities` | 先产品卡：`analysis.query.spec`、`analysis.query.spec:event`、`analysis.query.spec:funnel`… |
| `describe analysis.query.spec:event` | `describe_capability` | `required_inputs=['app','spec']`；`next.argv` 是 `gravity plan run --input <plan.json>` |
| `host` | `gravity.host-product-catalog.v1` | 102 项（产品卡 + 精确 gap，**无 raw operation**），带 `catalog_sha256` 和选择合同 |

优先选 `identity_kind=product`。raw operation 是专家入口。`capability_gap` 不可执行。

无 query 时拿机器协议：

```powershell
python -m gravity_sdk agent
```

实测 `mode=protocol`，`schema_version=gravity.agent.v1`，`routing_mode=recognizer`。

### 1.4 宿主臂是主路径

调用方（人或宿主模型）能产出 `gravity.host-product-selection.v1` 时，**不要走默认识别器**：

```powershell
python -m gravity_sdk agent-catalog host
# 读 entries[].catalog_ref 与顶层 catalog_sha256，写出 selection.json
python -m gravity_sdk agent "看一下事件趋势" --routing host_catalog --host-selection selection.json
```

`selection.json` 必须是当前这次 `host` 的指纹，过期或伪造会整份拒绝。形状（字段名以 `host` 返回的 `response_schema` 为准）：

```json
{
  "schema_version": "gravity.host-product-selection.v1",
  "catalog_sha256": "<paste host.catalog_sha256>",
  "query": "看一下事件趋势",
  "decision": "selected",
  "reason": {
    "summary": "event trend maps to the analysis spec product",
    "needs_clarification": false
  },
  "candidates": [
    {
      "catalog_ref": "analysis.query.spec",
      "reason": {
        "goal_match": "event trend over time",
        "boundary_check": "not derived metrics on an existing result"
      }
    }
  ]
}
```

本机用当天 `host` 指纹提交后：`status=success`，`mode=host_catalog_select_and_describe`，`routing_mode=host_catalog`，`routing.floor=false`，**没有** `routing.upgrade`，选出 `analysis.query.spec`，`missing_inputs=['kind','app','spec']`。仓库消费选择、不调模型。

`decision`：0 个候选由仓库生成固定路由 gap；1 个才 describe；多个按 `catalog_ref` 变成 `MULTIPLE_INTENTS`，不猜 top-1。

### 1.5 默认 `gravity agent "问题"` 是地板

省略 `--routing` 时默认识别器。同一句「看一下事件趋势」本机实测：

- `routing_mode=recognizer`，`routing.floor=true`
- 3 张卡：`analysis.query.spec:event` / `analysis.event.info` / `analysis.event.list`
- 信封里带照抄就能跑的升级路径：

```text
routing.upgrade.next.argv      = gravity agent-catalog host
routing.upgrade.then_argv      = gravity agent "看一下事件趋势" --routing host_catalog --host-selection <gravity.host-product-selection.v1>
```

识别器**不会填 App / 日期 / 事件**。卡上的 `missing_inputs` 和 `next.argv` 占位符要你自己补。自然语言不自动执行。

单问用位置参数；`--input` 是批量发现面，不能和位置参数一起用：

```json
{"questions":[{"id":"apps","query":"list apps","domain":"app"},{"id":"events","query":"event metadata","domain":"analysis"}]}
```

```powershell
python -m gravity_sdk agent --input questions.json
```

本机实测 `gravity.agent-batch.v1`，`question_count=2`，`success_count=2`；每题仍是识别器地板（`app.list` / `analysis.event.list`）。补齐参数后第二次 `plan run` / `run`。

已知 recipe 或 operation 直接一次：

```powershell
python -m gravity_sdk run app.list --max-items 20
python -m gravity_sdk analysis bootstrap --app <id> --start yesterday --end yesterday --target <physical-event> --plan-output first-analysis-plan.json
python -m gravity_sdk plan run --input first-analysis-plan.json
```

依据：[完整目录发现](agent-skills/catalog-discovery.md)、[十分钟路径](agent-skills/ten-minute-path.md)、[CLI：Agent](reference/cli.md)、[应答声明路由臂](roadmap.d/routing-provenance.md)。

---

## 2. 能问什么 / 问不到什么

动线分母 56，已闭环 50 / 部分闭环 3 / 完全缺失 3（表头数字由台账维护，本页不重算）。下面按分析师问法归类，不是 77 KB 表的拷贝。出处：[分析动线台账](analysis-journeys.md)、[为什么还没到 95%](roadmap.d/gap-to-95.md)。

### 已经能走完的

| 你想问 | 走哪类产品 | 已知输入几次 |
| --- | --- | --- |
| 某事件随时间 / 分组 / 条件怎么变 | Analysis 事件 | 1 / 未知 2 |
| 多步转化漏斗、注册后留存、属性分布、散点 | Analysis funnel / retention / property / scatter | 1 / 2 |
| 同一分析定义比较两个时期 | 同一 Spec + `--compare-start/--compare-end` | 1 |
| 人群规则命中人数、已有分群详情 / 成员 | segment evaluate / snapshot / members | 1 / 2 |
| 归因表现聚合、单用户归因明细 | attribution performance / user detail | 1 / 未知 App 3 |
| 变现按平台/广告位/日期汇总、单日变现明细 | `report.get.query` / monetization detail | 1 / 2 |
| 跨平台素材 / 推广表现、巨量广告主、标题包 | materials / promotion / advertiser / title-package | 1 / 2 |
| 经营脉搏、公司用量、自定义人群覆盖 | pulse / usage / custom-audiences | 1 / 2 |
| 单日订单目录、按 TraceID 拆单 | order directory / order trace | 1 / 2 |
| 多维报表、语义成员组合、自定义指标 | multidim / semantic compose / custom metrics | 1；写 2 步 |
| 看板重放、保存分析 / 模板重放 | dashboard / saved analysis / template | 1 / 引用未知 2 |
| 创建或删除分群、报表、订阅、Kanban | 先 `--dry-run` 再同参数 `--execute` | 2 |
| 当前账号可读的 App 列表 | `app.list`（`GET .../open_app/list/`） | 1 |

调用方自己绑公式、对已有结果做比率/占比，走 `gravity derive`，不另算一条动线。

### 已知拿不到（不是工具坏了）

这 4 条在**当前租户**下不可达，解锁条件在上游，不在 SDK：

| 你想问 | 阻塞 | 要上游做什么 |
| --- | --- | --- |
| 非 Bytedance 的计划 / 组 / 创意（D33/D34） | 快手近半年投放行明确空；腾讯创意层 `permission_unavailable` | 快手真正起投放；给声明父对象开通腾讯读权限 |
| 各平台专属素材与创意（D32） | 与上同一投放前提；腾讯托管创意已有，快手创意库 / 腾讯标题库空 | 非 Bytedance 平台产出专属素材 |
| 数据表当前 schema / 字段 / 版本（F41） | 投放中 App 上 7 种 list 形状都 `total=0`；日志里的 `table_id` 对 detail 是 `1004 / not exist` | 有人在 Web 建一张仍存在的维度表 |
| 通用媒体报表 | 投放中 App 上 11 次最小第一页全空 | 有人在 Web 导入一份通用媒体消耗 |

另有一条**专门在推、三次开窗仍空**：实时事件目录。对 `29034827` 开过入库开关后，凌晨 / 午间 / 开窗后等 50 分钟，当天窗、近 1h 窗、两种非空 filters，均 HTTP 200 且 `data.list` 无 item。Agent 首问返回 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`。空的是「已试形状 + 关闭开关」，不是「租户没这个能力」。本上手包不碰实时事件路由。

导出（事件 / 分群 / 用户 / 付费 / 变现）是**部分闭环**：七个具体子路径可调，宽问法仍是精确 gap。不要发明统一导出产品。

空 `data.list` 且 HTTP 200：先看是不是没用投放中的 `29034827`、时间窗不对、或漏了必填筛选。6 个未投放分身本来就该空。

---

## 3. 怎么判断拿到的数可不可信

这节比「能跑通」重要。对账都在 `29034827` 上做；关系成立，下面不抄业务数字。

### 已经交叉验证过的（可以信）

| 规矩 | 成立条件 | 出处 |
| --- | --- | --- |
| 分页拼接 = 上游声明总数 | `analysis.event.list` `page_size=7` 拉完全部页，`item_count = page_info.total_number` | [生产对账](roadmap.d/prod-truth.md) |
| 可加指标分维求和 = 总计 | 归因 `AppRealRegisterCnt` 按 date / platform / 两者；变现次数与收入在「按日、不拆平台」或「total + 平台（含空平台行）」 | 同上；[宣传与实际](roadmap.d/advertised-vs-real.md) |
| 时间窗可加 | 大窗总计 = 子窗之和（同一指标、同一口径） | prod-truth |
| 跨 route 同一事实能对上，口径差说得清 | 留存第 0 日人数 = 事件 `$UserFirstRegister` UV；归因 `AppRealRegisterCnt` 按激活日，允许差 2 且差可解释 | [留存/漏斗/分群](roadmap.d/reconcile-round2.md) |
| 留存 | 第 0 日 = 分母；任意日人数 ≤ 分母；`$os` 各组 `init_num` 之和 = 总分母 | 同上 |
| 漏斗 | 单调递减；第一步 = 同期注册分母；分日各步之和 = 整窗 | 同上 |
| 分群 | 已算完分群的 list / detail / history / daily_result / members 人数一致；明细导出行数 = 人数 | 同上 |
| 导出 | 小切片（用户明细）`completion_status=complete` 且 `file.rows = list.total_items`；超限变现诚实报 `truncated`，给 `missing_rows` | [truncated 确认](roadmap.d/truncated-confirm.md) |
| 相对日期 | `yesterday` 解析窗再手填同一 ISO，四个归因画像数字相等 | [相对日期](roadmap.d/relative-dates.md) |

挑可加指标：次数 / 金额（`AppRealRegisterCnt`、`reporting_ad_cnt`、`reporting_ad_revenue`）。**不要拿 UV / 设备数 / 活跃用户去跨维求和。**

### 已知不可信，必须绕开

| 字段 | 事实 | 改走 |
| --- | --- | --- |
| `analysis.event.list.yesterday_count` | 7/7 App、648 个事件全是 0；同日 `29034827` 与 Android 分身的归因注册却有正行 | `attribution.attribution.query`（`metrics_list=["AppRealRegisterCnt"]`）或 `analysis.origin_event.evaluate_data` |
| 标题库 `last_3_day_click_rate` / `last_3_day_cost` | 投放中 App 44/44、不绑 App 50/50 全 0；同页 `history_*` 和 `material.report.query` 的 `ctr` / `stat_cost` 有正值 | `history_click_rate` / `history_cost`，或 `material.report.query` |

`describe` 的 `response_projection.unreliable_item_keys` 和读取结果的 `warnings` 会写 `reason` + `use_instead`。不要删上游值，也不要用 0 当「没数据」。

依据：[误导字段](roadmap.d/misleading-traps.md)、[信任核查](roadmap.d/trust-sweep.md)、[SDK：不可靠字段](reference/sdk.md)。

### 容易自己算错

- **漏斗不返回转化率。** 响应里没有率字段。用人数自己除，且必须先定分母：3 步时「步 2→3」和「步 1→3」不是同一个比。
- **去重指标跨维求和本来就不等于总计。** UV、设备数、活跃用户不是划分。不要对它们做「各组相加 = 合计」验收。
- **变现按 `day + monetization_platform` 会漏掉空平台值那一行。** 行之和小于 `total`。改成不拆平台，或 `time_dims=total`（会看到空平台行）。SDK 对登记可加指标会写 `diagnostics[].code=dimension_sum_mismatch`，带 `list_sum` / `total` / `delta`。看见它不要把较小的 list 和当真相。
- **事件 `time_grain=total` 在本租户编成 `group_by=total` 后上游返回空 `{}`。** 这不是日期错；省略 `time_grain` 会编译失败。按日拆。
- **`evaluate_data` 一次为 0 不能写成「估算恒为 0」。** 换事件、换窗口会出正 `total`。穷尽合理形状之前，先怀疑请求。

### 一条通用规矩

**重要的数，用第二条 route 对一遍。**

四轮对账抓到的真问题包括：漏斗组分维键被投影丢掉、留存省略 `time_grain` 被上游拒、变现超限导出钉错分母、`yesterday_count` / `last_3_day_*` 死字段。同一事实走归因 ↔ 事件、list ↔ 导出、分日 ↔ 整窗，对不上先查口径和投影，不要先改业务结论。

---

## 4. 坑与自救

### 相对日期：看回显，不要猜窗

`--start/--end/--date` 接受封闭中英短语：昨天 / yesterday、今天 / today、最近 N 天 / last N days、本周 / this week、本月 / this month。成功结果带 `resolved_date_window`（expression、start、end、timezone、timezone_source、display）。

时区：`GRAVITY_TIMEZONE` → workspace `defaults.timezone` → `Asia/Shanghai`。本周 / 本月截到今天；上周 / 上月是完整过去周期。「最近一段时间 / recently」等模糊短语 `INPUT_INVALID`。

先读回显的窗，再读数字。

### 标识类型

`app_id` 已按**该 operation 合同声明的类型**归一化：正整数与其数字字符串可以互写。`"abc"`、负数仍失败。

**别的标识没有这层。** `advertiser_id`、`dashboard_id`、`project_id`、`space_id` 仍有 string / integer 分歧，不要自行互换。

### `gravity agent --input` 不是单问

| 你要做 | 写法 |
| --- | --- |
| 一个问题 | `python -m gravity_sdk agent "查询归因表现聚合"` |
| 一批问题 | `--input questions.json`，形状只能是 `{"questions":[{"id","query",...}]}` 或问题数组 |
| 单对象 `{"query":"..."}` | 非法，`field=input` |

`--input` 以 `{` / `[` 开头是内联 JSON，`-` 是 stdin，其他是文件。

### 三种发现终态

| 你看到 | 意思 | 下一步 |
| --- | --- | --- |
| `status=capability_gap` 且 `capability_gaps[].code` 是登记缺口（如 `REALTIME_EVENT_CATALOG_CONTRACT_MISSING`、`MEDIA_REPORT_ITEM_SCHEMA_MISSING`、`CURRENT_TABLE_SCHEMA_PARENT_MISSING`） | 能力明确没有或本租户不可达 | 报告 `code` / `reason` / `next_action`。只在 `next.argv` 存在时执行它。不要找替代 raw operation |
| `code=NO_CANDIDATE` | 识别器没匹配到已登记产品 | `python -m gravity_sdk agent-catalog categories`，再 `category` / `describe`，确认能力不存在。禁止执行 weak match，禁止发明 selector |
| `UNRANKED_OPERATIONS` | 识别器没选中产品，只排出至少 3 条互不相同的 raw operation（不是错误） | `python -m gravity_sdk agent-catalog host`，交一份 `gravity.host-product-selection.v1`，再 `--routing host_catalog --host-selection`。不要执行那页 raw operation |

只有 `status=success` 的 candidate 可执行。`capability_gaps` 不是 empty。exit：0 成功（含合法空结果）；2 调用方输入或认证；3 上游 / 权限 / 限流；4 本地合同 / 隐私 / I/O。

### 写操作

38 条 stable mutation 统一两步：权威输入 `--dry-run`，人审查后同参数只改 `--execute`。自然语言永不自动写。订阅固定 disabled、空收件人、不调 test。

---

## Agent 最小检查清单（可整段复制）

```text
1. $env:PYTHONPATH='src'
2. python -m gravity_sdk insight auth status
   — token_valid 不为 true 就停，让人跑交互 gravity
3. 读 docs/team-onboarding.md 与 docs/agent-skills/index.md
4. python -m gravity_sdk agent-catalog categories
5. python -m gravity_sdk agent-catalog host
6. 能写 gravity.host-product-selection.v1：
     python -m gravity_sdk agent "<问题>" --routing host_catalog --host-selection selection.json
   不能：
     python -m gravity_sdk agent "<问题>"
     看 routing.upgrade.then_argv
7. 只执行 status=success 且 executable=true 的 next.argv；补齐 missing_inputs
8. 看 resolved_date_window、warnings、unreliable_item_keys、diagnostics
9. 重要数字用第二条 route 对；看见 dimension_sum_mismatch 不要把 list 和当总计
10. capability_gap / NO_CANDIDATE / UNRANKED_OPERATIONS 按上一节处理
```

更细的产品协议见 [Agent 工作流](agent-workflow.md)；第一次真实事件分析见 [十分钟路径](agent-skills/ten-minute-path.md)。

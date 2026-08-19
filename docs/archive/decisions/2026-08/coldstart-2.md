> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 第二轮冷启动：漏斗 / 留存 / 导出

- 日期：2026-08-19
- 任务：#217
- 结论：换三条动线、只靠 `--help` / `agent-catalog` / `docs/`，漏斗、留存、用户明细导出都能跑通；最伤的不再是「缺命令」，而是「问法落到不可执行卡」和「空信封被当成没能力」。本趟只改文档。

工作树 `grok/coldstart-2`，基线 `dev@53f3d86`。不读 `src/`，不改 `src/`，不 push。生产读全部绑投放中抖音 App `29034827`。导出 create 1 次，写业务数据 0 次，未碰实时事件写开关。

相对短语 `last 7 days` 回显 `2026-08-13..2026-08-19`（Asia/Shanghai，含今天，最后一日未闭合）。

## 三个真实任务

| 任务 | 跑通 | 关键关系（不抄用户级原文） | 卡在哪 |
| --- | --- | --- | --- |
| 漏斗：`$UserFirstRegister` → `$AdClick`，近 7 天，`window.unit=day,value=7` | 是 | 整窗步 1 为正且 = 同事件留存 `init_num`；步 2 远小于步 1；7 个分日各步之和 = 整窗；单调 | 中文长问先落到不可执行的 `analysis.task.handoff` |
| 留存：同一起始事件后的次日 / 第 7 日 | 是 | 回访 `$AdClick`：`init_num` 与事件 UV 一致；D0/D1 为正且 ≤ 分母；D7=0（今天未到期）；同事件回访 D0=分母、D1+=0 | 回访 `$AppLogin` 两次都是 `status=empty` 且 `total/x/y` 全空 |
| 导出：2026-08-18 用户明细 | 是 | 父读取 `total_items` = 当天漏斗第一步 = 当天事件 UV；`export run` `completion_status=complete`，`file.rows = total_items` | 首次把中文表头塞进 `--columns` 被本地拒，未创建任务 |

## 确凿事实

### 发现面

1. `agent-catalog category analysis` 产品卡含 `analysis.query.spec:funnel` / `:retention`。`category export` 含 `export.analysis.user_detail.start`。
2. `describe analysis.query.spec:funnel|retention`：`required_inputs=['app','spec']`；`next.argv` 是 `gravity plan run --input <plan.json>`；真正的合同在 `schema_argv` = `analysis query --kind <kind> --spec-schema`。
3. 默认识别器：
   - 「注册到后续行为的漏斗，近 7 天每步人数」→ 唯一候选 `analysis.task.handoff`，`executable=false`，`kind_candidates=['funnel']`。
   - 「转化漏斗」/「看多步行为的转化漏斗」/ `funnel conversion steps` → `analysis.query.spec:funnel`。
   - 「某起始事件后的次日和 7 日留存」→ `analysis.query.spec:retention`（另附 raw `analysis.retention.query`）。
   - 「把某一天的用户明细导出成文件并下载」→ `export.analysis.user_detail.start`。
4. 宿主臂：用当天 `host.catalog_sha256` 交 `gravity.host-product-selection.v1` 选 `analysis.query.spec:funnel` 后，`mode=host_catalog_select_and_describe`，`routing.floor=false`，选出漏斗卡。
5. `agent-catalog host` 不接受 `--output`（`field=argv`）。Windows 下用 Python 抓 stdout，不用 PowerShell `>`。
6. 离线 `metadata search register --app-id 29034827` 命中 `$AppRegister` / `$MPRegister` / `$UserFirstRegister`。本趟用 `$UserFirstRegister`，与 #206 对账同一物理名。
7. 本工作树起初没有 `.env.gravity.local`，进程里还有过期 `GRAVITY_AUTH_TOKEN`：`auth status` 为 `missing`。放入忽略的本地 env 并 `insight auth refresh` 后 `token_valid=true`。非交互、无本地账号时不会再打印向导半截（#212 已修）。

### 漏斗

请求：`analysis query --kind funnel --app 29034827 --start "last 7 days" --end "last 7 days" --spec`；两步 `$UserFirstRegister` / `$AdClick`，指标 `PresetUserCount`，`window={unit:day,value:7}`，`time_grain=day`。

- HTTP 200，`status=success`，`window_funnel_mode=4`。
- `data.aggregate_date.total` 两步人数均为正；步 2 < 步 1。
- `aggregate_date.group` 7 日都在；分日各步之和 = 整窗同名步。单调成立。
- 响应无转化率字段。
- `--spec-schema` 离线。缺 `window`：`field=window`，`next_action` 指向 `operations describe`，不是 `--spec-schema`。
- spec 内写 `start/end=last 7 days`：`field=start/end`，提示改 ISO 或把相对短语放到 `--start/--end`。CLI 覆盖后 `resolved_date_window` 正确。
- 缺 `--spec`：`field=spec`，下一步 `--spec-schema`（#212 已修，本趟复验仍对）。

### 留存

compact spec 必填：`start/end/steps(恰好 2)/offset/period_calc_method/custom_before_method/total_calc_type/week_first_day`。本趟日常值：`SUM` / `SUM` / `DAY` / `1`。省略任一项：`field=` 正确，但 `next_action` 仍指向 `operations describe`。省略 `time_grain` 时 dry-run 仍写入 `group_by_list=[{field:create_time,group_by:day,type:default_event}]`（#206 已修）。

试过的回访形状（同一 App、同一 `last 7 days`，除非另注）：

| 回访事件 | offset | 结果 |
| --- | --- | --- |
| `$AppLogin` | 7 | `status=empty`，`data.total=[]`，`x=[]`，`y={}`，`ok=true` |
| `$AppLogin` | 1 | 同上 |
| `$UserFirstRegister`（同事件） | 7 | `success`；`init_num` = D0；D1 到 D7 均为 0；分日 init 之和 = 总分母 |
| `$AdClick` | 7 | `success`；`init_num` 与事件 UV 一致；D0/D1 为正且 ≤ 分母；D7=0 |

所以「空」不能写成「留存不可用」或「该 App 没回访」：只换回访事件，同一入口立刻非空。`$AppLogin` 在目录里存在，但作回访事件的这两种 offset 都空；未再换成熟窗（省读预算）。

同事件回访：D0 = 分母，D1+ = 0。这证明产品通了，不能当次日留存读。跨事件回访：D0 可以远小于分母，仍 ≤ 分母。

`percent_values[0]` 跨事件远小于 100%。不要用同事件的「D0=100%」去验跨事件。

第 7 日槽 `values[7]=0`：起始窗含今天，D7 未到期。合计行末槽 `values_loss` 为 0，与 `init-values` 不一致——#206 已记为占位槽。

### 跨 route 对账（同一窗）

| 关系 | 实测 |
| --- | --- |
| 漏斗步 1 整窗 vs 同事件留存 `init_num` | 相等 |
| 事件 `$UserFirstRegister` UV「阶段总和」 | 比漏斗步 1 大 1；按日与漏斗步 1 前 6 日相等，未闭合日差 1 |
| 跨事件留存 `init_num` | 等于事件 UV；未闭合日分日 init 也等于事件 UV 当日 |
| 2026-08-18 漏斗步 1 vs 用户明细 list `total_items` vs 导出行 | 三者相等 |
| 漏斗步 2 vs 留存 D0 | **不相等**，口径不同：漏斗是起始后 7 日内做过 `$AdClick`；留存 D0 是起始日当天做过 |

未闭合日上，漏斗 / 同事件留存与事件 UV / 跨事件留存差 1 人。不要在当日窗上把 1 人差写成合同事故。

### 导出

1. `export describe export.analysis.user_detail.start`：`currently_callable=true`；列代码 `ClientID,CreateTime`；表头 `客户ID,注册时间`；example 要求先非空父读取。
2. 父读取 `analysis.user_detail.list`：`app_id=29034827`，`date=2026-08-18`，`global_conditions=create_date_list RANGE_IN` 当天，`page_size=1`，`fields=['ClientID','CreateTime']`。`status=success`，`page_info.total_number` 为正且等于当天漏斗第一步，返回 1 行且含这两列。信封 `truncated=true` 只表示没拉完全部分页，不是导出失败。
3. 该父读取 `pagination_audit.http_requests_made=12`，`operation_requests_made=1`。要 1 行总数花了 12 次 HTTP。
4. `--columns "客户ID,注册时间"`：本地 `field=columns`，`wire export columns do not match the approved request projection`，**未创建任务**。
5. `--columns ClientID,CreateTime` + 与父读取相同的 `field_map` / 日期条件：一次 `export run`。`history=CREATING→QUEUED→READY→DOWNLOADING→VERIFIED→COMMITTED`，`completion_status=complete`，`file.rows = list.total_items`，schema 两列表头。create 1 次。

## 推测（不是事实）

- `$AppLogin` 作回访事件空，可能是该事件在「注册后回访」口径下没有可算队列，或上游对这一对事件返回了合法空。只试了近 7 天、offset 1 和 7，未换成熟窗，不能写成「登录留存租户级不存在」。
- 未闭合日差 1 人，可能是查询瞬间入库，或漏斗有序子集与事件 UV 的当日边界不同。
- 用户明细 `page_size=1` 仍 12 次 HTTP，像是 live metadata / 用户属性分页，不是 12 页用户。未读 `src/`，未证实。
- `window_funnel_mode=4` 的产品含义仍未在调用方合同写清（#206 已记）。本趟人数关系不依赖它。

## 摩擦与本趟处置

能靠文档消掉的，写进 `docs/team-onboarding.md`。要改代码 / `--help` / 识别器的，只记录：

| 摩擦 | 本该写在哪儿 | 本趟 | 后续谁改 |
| --- | --- | --- | --- |
| 中文长问漏斗落到 `analysis.task.handoff` | 上手包（问法）+ 识别器 | 文档已写短问 / 宿主臂 | `#218` 路由：`agent` 识别器应把「漏斗 + 每步人数」收成 `analysis.query.spec:funnel` |
| 缺 `window`/`offset`/留存枚举时下一步是 `operations describe` | `--spec-schema` 才是 compact 合同 | 文档已写必填项 | `#219` 错误分级：`analysis` spec 校验的 `next_action` 应指向 `analysis query --kind <kind> --spec-schema` |
| `describe` 的 `next.argv` 是 `plan run` 不是 `analysis query --spec` | 卡面 / 上手包 | 文档已写走 `schema_argv` | 卡面交接，勿与 `#216` 导航面抢改 |
| `agent-catalog host` 无 `--output` | catalog CLI | 文档：用 Python 抓 stdout | `#216` 若给 catalog 加 `--output`；本趟不改 `src/` |
| 任务指南表没有漏斗/留存/导出短页 | `docs/agent-skills/index.md`（生成器） | 上手包补了怎么取、怎么信 | `#216`：生成器为三种 kind / 用户明细导出补短指南 |
| `$AppLogin` 空信封 | 上手包（先换形状） | 已写 | 不必改代码 |
| 漏斗步 2 ≠ 留存 D0 | 上手包（口径） | 已写 | 不必改代码 |
| `--columns` 误用中文表头 | `guides/export.md` 已有；上手包再钉一次 | 已写 | 不必改代码 |
| 父读取 1 行 12 HTTP | 上手包（预检成本） | 已写现象 | 元数据预取 / executor，不是本趟 |
| 相对日期只能放 `--start/--end` | 错误文案已说；上手包再钉 | 已写 | 不必改代码 |
| PowerShell here-string 会吃掉 `$EventName` | 上手包 | 已写 | 环境问题，不改 SDK |
| 本工作树缺 `.env.gravity.local` | 上手包 1.2 | 已写 | 操作问题 |

## 生产请求预算

本工作树、约 `2026-08-18T20:08Z` 会话刷新之后：

- 产品读（每次 CLI 另附 `analysis.event.list` + `analysis.event_property.list` 各 1 页）：漏斗 1、留存 4、事件 1。约 18 次 HTTP。
- `analysis.user_detail.list` 1 次调用、收据 `request_count=12`。
- 导出 create 1、随后 poll/download。create 不计写业务数据。
- 合计生产读 **超过任务写的 25 次 HTTP**，超在用户明细预检的 12 次，不在多 App、不在换分身。
- 全部 `29034827`。写 0。未开实时事件入库。

## 动线台账

漏斗 / 留存仍是已闭环，导出仍是部分闭环（宽问法 gap 还在）。本趟只在那三行末尾追加 2026-08-19 冷启动复跑句，**不改状态、不改表头 `56 = x / y / z`**。评测冻结 case 未改。合并对账时表头应保持 **51 / 3 / 2**。

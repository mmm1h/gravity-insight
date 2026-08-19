> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 四处「SDK 说的和实际不一样」

- 日期：2026-08-18
- 任务：#202
- 结论：两套 describe 的合同字段已对齐；目录标称可执行但 `gravity run` 够不着的 13 条 export 路由全部给出真实入口；分页审计的 HTTP 次数按线程计数器累加；可加指标分维和 ≠ total 时给出 `dimension_sum_mismatch`。

## 一、两套 describe

### 确凿事实

离线对账全部 **236** 个 Insight operation：

| 集合 | 数量 |
| --- | ---: |
| `operations describe` 与 `agent-catalog describe` 都能解析 | 236 |
| raw operation（无同名产品卡）合同字段一致 | 233 |
| 同名产品卡覆盖的 selector | 3：`app.list`、`app.app_info.get`、`report.get.query` |

这 3 条是唯一合同分歧。根因不是两套 describe 各自算错，而是 `agent-catalog describe` 对产品卡只回卡面、不并入 `operations describe` 的压缩合同。卡面故意瘦：

- `report.get.query` 卡面只有 `date_list` / `filters` / `metrics_list`，缺 `time_dims`、`data_dims`、`data_conf`、`data_topic`、`custom_metrics_list`、`relate_dims`
- `app.list` 卡面 `input_schema={}`，缺 `page` / `page_size`
- 三张卡都缺 `stability`、`pagination`、`required_parent_operations`

`operations describe` 是完整合同。产品卡描述文案可以比合同描述更窄（产品边界），那不是 bug。

### 处置

- 产品卡 describe 并入压缩 operation 合同：完整 `input_schema`、`required_inputs`、`pagination`、`stability`。
- 两边各写投影说明，**不靠删字段消分歧**：
  - `agent-catalog describe.surface`：产品卡 + 压缩合同；不投影 `wire` / `examples` / `privacy` / `health`；完整合同看 `gravity operations describe`
  - `operations describe.surface`：完整合同；压缩 Agent 卡看 `gravity agent-catalog describe`
- 能力只增不减。产品卡保留自己的产品描述。

改后 236 条 `input_schema` 键集合一致。残留差异只有产品描述文案，以及卡面给字段多写的 `description` / `max_length`（比合同多，不是少）。

## 二、标称可执行但够不着

### 确凿事实

`export describe` / `export list-capabilities` 里 `currently_callable=true` 共 **13** 条，**0** 条在 Insight read 注册表，因此 `gravity run <id>` 全部 `UNKNOWN_OPERATION`。

| operation_id | effect | 改前可达入口 | 改后可达入口 |
| --- | --- | --- | --- |
| 8 个 `*.start` | `export_job_create` | `gravity export run/start` | 不变 |
| `export.analysis.origin_event.evaluate` | `export_status` | 无独立 CLI；`gravity run` 失败 | `gravity export evaluate` |
| `export.task_type.list` | `export_status` | 无 | `gravity export task-types` |
| `export.task.list` | `export_status` | `gravity export list` | 不变；describe 指向该入口 |
| `export.task.progress` | `export_status` | `gravity export status/wait` | 不变；describe 指向该入口 |
| `export.task.cancel` | `export_cancel` | `gravity export cancel` | 不变；describe 指向该入口 |

Insight 227 条 `executable=true` 都在 `gravity run` 注册表里。没有第三条「目录说能跑、CLI 没有入口」的 Insight 读操作。

### 处置

- 补 `gravity export evaluate`（估算行数，不创建任务）和 `gravity export task-types`。
- `export describe` 对 evaluate / task-types / 支持路由给出对应 `next_action` 和 workflow，不再把非 create 路由指去 `export run`。
- 不从目录删除任何一条。

本工作区没有 `.env.gravity.local`，evaluate 入口只做离线合同 + 夹具 HTTP，未发生产请求。

## 三、分页审计

### 确凿事实

`prod-truth` 已记录：`analysis.event.list` `--all-pages` 时 `pages_fetched=17`、`result_audit.http_receipts=17`，但 `pagination_audit.http_requests_made=1`。

根因：`resolver` 把 `receipt.request_count` 交给审计；该计数来自 `contextvars` 上的 `RequestCounter`。已知 `total_page` 后，后续页走 `ThreadPoolExecutor`，工作线程看不到父线程的 ContextVar，16 次分页 HTTP 没计入。第一页同步，所以报 1。

同信封其它字段：

| 字段 | 结论 |
| --- | --- |
| `operation_requests_made` | 取 `page.pages_fetched`，17 页场景本来就是 17，无需改 |
| `effective_page_size` | 取结果信封 `request.inputs.page_size`，不是计数器，无同类 bug |
| `completeness` | 用 `has_more` + `returned_items` vs `total_items`，对账成立 |

### 处置

工作线程提交前把当前 `RequestCounter` 绑回去。红→绿：

- 改前：17 页 `http_requests_made=1`
- 改后夹具：4 页并行 `http_requests_made=4` 且等于 `pages_fetched`；resolver 17 页夹具 `http_requests_made=17`、`operation_requests_made=17`、`completeness=complete`

未再打生产分页。

## 四、分维丢行

### 确凿事实（沿用 #194，本趟未发生产请求）

本工作区没有 `.env.gravity.local`，预算未用于补扫。判断依据是 `docs/roadmap.d/prod-truth.md` 已记录的形状，指标只看次数/金额，不看 UV。

| 路由 | 窗 | 维度 | 可加指标 | 行之和 vs total |
| --- | --- | --- | --- | --- |
| `attribution.attribution.query` | 2026-08-14..16 | `date` | `AppRealRegisterCnt` | 相等 |
| 同上 | 同上 | `ad_platform` | 同上 | 相等 |
| 同上 | 同上 | `date` + `ad_platform` | 同上 | 相等 |
| `report.get.query` | 同上 | `time_dims=day`，无平台维 | `reporting_ad_cnt` / `reporting_ad_revenue` | 相等 |
| 同上 | 同上 | `time_dims=total` + `monetization_platform` | 同上 | 相等（含空平台值行） |
| 同上 | 同上 | `time_dims=day` + `monetization_platform` | 同上 | **小于**；空平台值只在 `total` |
| 同上 | 同上 | `time_dims=total` 且无 `data_dims` | — | 上游 `INPUT_INVALID` |

### 推测

空平台值在 `day + monetization_platform` 下被上游从 list 里拿掉、只进 `total`。未再试 `ad_unit_id` / `os_family` / `channel` 等其它维，不能写成「所有维度组合都会丢行」。

### 处置

不改上游值、不补行。resolver / `gravity read` 对登记可加指标（`AppRealRegisterCnt`、`reporting_ad_cnt`、`reporting_ad_revenue`）比较 `list` 之和与 `total`，不等则写 `diagnostics[]`：`code=dimension_sum_mismatch`，带 `list_sum` / `total` / `delta`。UV 不参与。夹具锁住正反两条。

## 未做

- 未 push、未碰 GitHub。
- 未读、未写 `docs/roadmap.md`。
- 未跑 holdout / final，未读 `*.sealed.json`。
- 未发生产 HTTP（无本地凭据）。
- 动线状态列未改；表头 `56 = 50 / 3 / 3` 未改。

## 门禁

`NO_COLOR=1` 下：unittest **1216** OK；pytest **1216 passed**；compiler check 236；quality PASS，`quality-baseline.json` 的 `hard_limit` / `threshold` / `max_` 未改。可执行错误库存 `1254 / A879 / B375 / C0`。

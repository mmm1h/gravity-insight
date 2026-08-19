> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 变现聚合与明确不做

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：D28 变现聚合取证、Issue 20 Windows receipt 探测，以及明确不做清单。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## D28 变现聚合合同取证（2026-08-15）

**判定：两条 POST 的读语义成立，请求 builder 与前端消费已静态恢复；D28 产品合同不成立，保持完全
缺失，不实现 Core / CLI / SDK / Plan / Agent 卡。** 静态证据来自 census snapshot 指定的
`NewReportCenter-Dxgo5EkI.js`，本机冻结副本为 402,619 bytes，SHA-256
`eb8e91aa591d92271e3b9f0e8b23f371ffa61b18affb63e167735dd37c731f2b`，与
`bundle-snapshot.json` 完全一致。普通查询 route/call offset 为 `296867/306430`，合计 route/call
offset 为 `296083/318502`。没有扩张 census 提取器。

### 请求 builder

`POST /report/api/v3/monetization_report/custom_get/` 的九个顶层字段全部由 bundle 静态证明：

| 字段 | 值、默认与 wire 省略规则 |
| --- | --- |
| `time_dims` | 从已选维度按 `hour → day → week → month` 取首个；都没有时发字符串 `"total"`，恒发。 |
| `date_list` | 取表单 `resultDate`；正常初始值为 `[D-7,D-1]` 两个 `YYYY-MM-DD` 字符串。仅 form ref 不存在时为 `undefined` 并由 JSON 序列化省略；不发 `null`。 |
| `data_dims` | 已选维度去掉 `hour/day/week/month/date` 后的字符串数组；恒发，空为 `[]`。 |
| `relate_dims` | 有关联维度时发“父维度 → 关联维度数组”的对象；没有时为 `undefined` 并省略，不发 `[]` 或 `null`。 |
| `metrics_list` | 当前 metrics 中没有 `id` 的项取 `name`；恒发数组，空为 `[]`。builder 已证明，name 值域和模板默认项未证明。 |
| `custom_metrics_list` | 当前 metrics 中有 `id` 的项取 `id`；恒发数组，空为 `[]`。 |
| `data_conf` | 恒发六键对象，精确子字段见下文。 |
| `data_topic` | 调用只存在于 `reportType === "monetization_report"` 分支，固定发 `"monetization_report"`。 |
| `filters` | helper 结果恒发为数组；无过滤条件时 `[]`，不发 `null`。 |

普通查询 `data_conf` 六键为：`decimal_point` 精度开关关/开取 `2/4`（默认 2）；
`minigame_pay_shared_ratio` 分成开关开时取表单值（初始 60）、关时 100（默认 100）；
`minigame_pay_shared_ratio_ios` 开时取表单值（初始 100）、关时 100；`return_all_metrics` 固定
`true`；`accumulate` 默认 `false`；`asa_time_zone` 默认 `UTC`，加载保存配置时只接受 `UTC` 或
`Asia/Shanghai`，其他值归一成 `UTC`。

`filters` 对每个未选条件完全省略对象；`app_id/project_id` 用 `EQUALS` 和单元素 `values`；
`click_company`（表单 `ad_platform_list`）、`monetization_platform`、`advertiser_id`、`aid`、
`ad_unit_id`、`client_channel`、`operator_id`、`turbo_promoted_object_id`、`client_version`、`gid`、
`os_family`、`ad_type`、`user_type`、`bundle_id`、`optimization_goal`、`deep_optimization_goal`、
`deep_bid_type` 用 `IN` 和对应数组；`dept_id` 用 `IN` 并把标量包装为单元素数组。两条 route 都没有
query 参数。

`POST /report/api/v3/monetization_report/custom_get/calc_total/` 的八个顶层字段也全部静态证明：
`time_dims/date_list/data_dims/relate_dims/metrics_list/custom_metrics_list` 与主查询完全同源、同省略
规则；`data_conf` 恒发，但只有 `decimal_point`、两个分成比例、固定
`return_all_metrics=true`、`asa_time_zone`，**没有** `accumulate`；`data_list` 恒发二维行组数组，
平表为 `[clientFilteredRows]`，累计模式按 `__raw_index__` 映射回 raw rows 后包装，透视模式发送叶子
分组并按需 prepend 当前筛选行组。它不发 `data_topic/filters/page/page_size`，也不发 `null`。

以上是 builder 的静态事实，不等于服务端 required 声明。仍属推断/未证明的只有：服务端各字段必填
子集、指标/自定义指标值域及模板默认项、维度/关联维度/filter 组合的服务端允许集合。既有 draft 的
`reporting_ad_revenue` 不存在于该 hash-matched bundle，只是历史 `stable_report_request_pattern`
候选，不能标为静态证明。

### 响应消费、分页与两 route 关系

通用 request helper 先解包 wire 外壳，因此 bundle 局部 `data.*` 对应 wire `$.data.*`：

- 主查询非累计取 `data.list || []`；累计渲染 `data.extra_data.accumulate_data || []`，并把
  `data.list || []` 留作 raw rows。只有渲染数组非空才取 `data.total || {}`、把合计行中的相关维度
  以及 `monetization_platform/ad_unit_id/app_id/app_name/ad_type` 显示值置为 `"-"`、prepend 合计行，
  并消费 `data.tips` warning。空数组跳过该分支，初始表显示通用“暂无数据”；该分支没有显式清除
  既有 rows，所以已有数据后的刷新空响应可能保留旧本地行，前端没有更强的空态判据。
- `calc_total` 只取 `data.list || []`；平表以 `list[0]` 替换本地合计行，透视表把 list 对应回各分组；
  空 list 只产生 `undefined` 合计，没有独立空态。
- 两条 route 都没有 upstream pagination，也不消费 `page_info`。`ReportTable` 对完整正文在客户端
  `slice`，默认 100 行，可选 100/200/500；合计行在每个本地页 prepend。
- `custom_get` 先完成，`calc_total` **不是并发或无条件伴随请求**。只有主结果非空且存在客户端条件
  或透视时才顺序 `await calc_total`；修改本地条件/展开透视也可只重算 total；无条件平表直接使用主
  响应 `data.total`。
- helper 的语义/transport 错误被页面 catch 后只解除 loading；该 Web 控制流本身不能把 permission、
  semantic error 与 empty 机器化区分，这正是产品层仍需补齐的能力缺口。

### 读语义闸门与 probe

两条读语义均成立并已登记精确 `POST + path` confirmation：主 route 只在装载/刷新报表时更新本地
表格、total、warning 和排序；保存/编辑走独立 create/edit route。`calc_total` 只把已加载行组用于
本地条件/透视合计重算，无提交控件、写成功反馈或状态改变。放行仍同时要求人工记录、路径精确相等和
已知 namespace，规则面没有扩大。

本轮生产 HTTP 共 **3 次**，无认证交换、重试、翻页、扩窗、换 App 或猜平台/广告位：

| # | Operation / route | HTTP 状态 | 结论 |
| --- | --- | --- | --- |
| 1 | `app.list` — `GET /turbo_engine/api/v1/user/open_app/list/` | **未登记，不推断** | 只在内存选取首个 App 供主请求；值未落盘。probe 脚本未在后续失败前 flush 逐请求账本。 |
| 2 | `report.get.query` — `POST /report/api/v3/monetization_report/custom_get/` | **未登记，不推断** | 唯一目标请求已发送；观察只留在内存，随后脚本在 `calc_total.data_list` 的本地校验处退出，故 status、raw fingerprint 和字段路径丢失。按纪律不补发。 |
| 3 | `report.report_monetization_report_custom_get.calc_total` — `POST .../calc_total/` | **200** | 唯一目标请求；raw fingerprint `6d57dc755d2469b2a4f0a93e64b556528187f4ec988ae574d62682f42b2ce278`。只观察到 `code:integer`、`data:object`、`data.list:array`、`data.list[]:object`、`extra:null`、`msg:string`，item 无可登记 key，结论 `inconclusive_shape_only`。 |

`calc_total` 的稳定-operation 字段防线只接受 `data_list` 为对象数组，与已证明的二维行组数组不兼容；
本轮没有放宽该全局防线。一次性 `tmp/` 脚本先运行现有精确 read-confirmation preflight，再校验
method/path/body keys 后直接发唯一 POST。此前四次 `calc_total` 调用尝试均在网络前失败，HTTP observation 为 0，
不计生产请求。

### 响应合同与精确退出条件

已持久化的 live schema 中，只有 `code/data/list/extra/msg` 外壳和一个无字段的 `list[]` object，
因此**观察到的 item 字段清单为空**；这不证明主响应没有其他字段，因为主 route 的 schema receipt
已丢失。静态消费确认日期、`monetization_platform`、`ad_unit_id`、`app_id/app_name`、`ad_type`
是聚合维度候选，`operator/operator_id/operator_name` 等只是可能出现的静态候选，均不能代替实际
响应 shape。两个 draft 的投机性 `known_omitted_item_keys` 已清空；未登记字段继续
`contract_changed_additive` fail-closed，取得真实字段后按投影总裁决登记并全部暴露。

合同失败的精确原因与证据提供方：

1. 主 route 缺本轮唯一请求的 HTTP status、raw schema fingerprint 和字段路径/类型。可由有权限的
   网关/服务端日志维护者按本次请求时段提供**值无关 shape**，或由调用方提供自然 Web 装载产生的脱敏
   network schema；本单元不重复请求。
2. 缺主 route 的成功非空 `list/total` 字段合同，以及使用真实非空行组时 `calc_total.list[]` 的字段
   合同。需要拥有变现报表数据的租户管理员提供各一次受控、值不落盘的 shape 证据；当前空行组样本
   不能替代。
3. 缺指标/维度服务端值域与必填集合。需要上游 report API owner 的 schema，或 hash-matched 自然
   请求证据；不能靠组合试探。
4. 非空字段出现后按投影总裁决登记并全部暴露；合同登记前继续 fail-closed，不另设隐私审批。

因此无法同时满足“非空响应登记、empty/partial/能力缺口可区分、未登记字段 fail-closed”的实现门槛。
动线计数不变：`48 = 32 已闭环 / 0 部分闭环 / 16 完全缺失 → 本轮 +0/-0 → 48 = 32/0/16`；
operation 也保持 `185 → +0 → 185`（stable `176 → +0 → 176`）。

## Issue 20 Windows receipt 存活探测（2026-08-17）

**判定：缺陷成立，根因是 Windows 上 `os.kill(pid, 0)` 等价于投递 `CTRL_C_EVENT`，不是陈旧 editable 元数据。**
`signal.CTRL_C_EVENT == 0`。CPython 在 win32 上对 `CTRL_C_EVENT`/`CTRL_BREAK_EVENT` 走
`GenerateConsoleCtrlEvent`，因此 `_process_is_alive` 不是无信号探测。首次 receipt 写入就会
全量扫账本 PID（`(count-1) % 64 == 0`），retention 与 query 两条路径都会打到它。

**实现：**Windows 改为 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess`；
句柄在 `try/finally` 中关闭。这两个 API 只查询进程对象，不向任何控制台进程组投递控制事件。
非 Windows 仍用 `os.kill(pid, 0)`。探测失败时判活：`OpenProcess` 失败且 winerror 不是
`87/1168`、或 `GetExitCodeProcess` 失败，都视为仍活着，避免把别人的 receipt 误删；账本可能暂时变大。
PID 复用本轮不修：复用后的活进程会让陈旧 receipt 被当成活动运行，清理延后、query 显示
`run_in_progress`。低成本加固是同时比对进程创建时间，本轮只记录判断。

**陈旧 editable：**本机 `importlib.metadata` 同时存在 `gravity-sdk 0.1.0 → D:/git-pjt/gravity-sdk`
与 `0.3.0 → D:/git-pjt/wt-metadata-onboarding`；未设 `PYTHONPATH=src` 时会加载前者的
`os.kill` 实现。它会放大现场现象，但不是本缺陷成因：当前工作树源码在修复前同样调用
`os.kill(pid, 0)`。本轮不改产品代码做版本卫兵。本地重装：
`python -m pip uninstall gravity-sdk -y` 后在本工作树 `python -m pip install -e .`，
并始终带 `PYTHONPATH=src`。

本轮生产 HTTP **2 / 6**：`auth refresh` 1 次 `authentication` POST `/account_center/api/v1/user_login/v2/` HTTP 200 attempt 1 无 retry；随后 `gravity run report.company_amount.query` 单页 `{page:1,page_size:1}` 1 次 POST `/report/api/v1/admin_report/query_company_amount/` HTTP 200 attempt 1 无 retry。均有 receipt。未传 `--max-items` / `--max-pages`。

operation / stable / 产品卡 / 动线本轮不变：`233 / 224 / 92`，`56 = 50 / 1 / 5`。

## 明确不做

- 不复刻 Web UI 概念：布局、收藏、拖拽、成员权限管理。`app.project_auth.detail` 与
  `app.user_auth.list` 因此排除，不因取得非空样本而进入分析产品。
- 业务语义属调用方：模块名称、活动 ID、SKU、投放窗口、指标好坏判断都不进本仓库。
- 写操作保持 reservation。
- 证据不足保持 fail-closed：不猜请求合同、不扩大探测找非空样本。
  （原第三项"不用未批准的用户级标识探测"已随
  [投影边界总裁决](projection-and-privacy.md#投影边界总裁决全面放开2026-08-15)作废。）

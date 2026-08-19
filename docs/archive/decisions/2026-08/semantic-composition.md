> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 语义组合与外部 selector

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：guided cold start、语义组合窄切片与 v2、外部 selector 不可测标注及六类自报字段。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 首条事件分析 guided cold start（2026-08-17）

**提案与决策边界：**ignored 工作稿位于 `tmp/codex/cold-start/proposal.md`。先把
`GRAVITY_CACHE_HOME`（receipt/workspace state）与 `LOCALAPPDATA`（metadata catalog）同时指向空目录，
并移走旧 session 后逐条重走生成指南。保留给调用方的判断是：从可读目录选 App、选一个精确物理事件、
给出日期窗、审阅 Plan 后决定执行；安装、目录浏览、认证、App 校验、metadata sync/status/search、
`PresetAllCount` 事件计数 Spec 组装和 Plan dry-run 都是机械依赖。没有默认 App 或模糊事件回退。

**旧路径实测：**当前 12 条命令及生产 HTTP 如下；这次严格空隔离实测为 **9**，不是旧文档写的 7：

| # | 命令 | HTTP |
| --- | --- | ---: |
| 1 | `python -m pip install -e .` | 0 |
| 2 | `gravity agent-catalog categories` | 0 |
| 3 | `gravity agent-catalog category analysis --limit 20` | 0 |
| 4 | `gravity agent-catalog describe analysis.query.spec:event` | 0 |
| 5 | `gravity insight auth status` | 0 |
| 6 | `gravity run app.list --input '{"page":1,"page_size":20}' --fields id,name` | 2（authentication + App） |
| 7 | `gravity metadata sync --app-id <id> --max-pages 2 --dry-run` | 0 |
| 8 | `gravity metadata sync --app-id <id> --max-pages 2` | 4（四类 metadata 各第一页） |
| 9 | `gravity metadata status --app-id <id>` | 0 |
| 10 | `gravity metadata events "" --app-id <id> --limit 20` | 0 |
| 11 | `gravity analysis query --kind event --app <id> --spec analysis.json --dry-run` | 0 |
| 12 | `gravity analysis query --kind event --app <id> --spec analysis.json` | 3（两类 live metadata + query） |

全部 9 个 receipt 都是 HTTP 200 / attempt 1 / retry=false；三个可分页 metadata 只取第 1 页，未换 App、
未扩日期、未为非零结果重试。多出的 2 次来自第 12 条在新进程重新读取
`analysis.event.list + analysis.event_property.list`，不能用旧估计覆盖实际账本。

**实现：**新增 `gravity analysis bootstrap --app --start --end --target --plan-output` 与
`GravitySDK.bootstrap_event_analysis()`，没有新增 operation。第一次调用先在零网络阶段校验显式输入，
再用既有 `app.list` 校验 App；catalog 非 ready 时复用单 App sync 和全局 bounded worker pool，四类
metadata 固定各 1 页。CLI transport 固定 1 attempt，所以含首次登录的成功上限为 6 HTTP；达到页界
只返回普通 `metadata sync --max-pages 2` 的下一动作，不自动扩大预算。事件只接受 catalog 中精确物理
名称；随后生成事件计数 `gravity.plan.v1`、固定 catalog `synced_at + SHA-256 fingerprint + path` 并
完成 Plan dry-run。第二次仍用既有 `plan run`；adapter 在执行前复验 fresh/complete catalog 和
fingerprint，并以 context-local loader 让现有 FieldPolicy 使用该只读快照，最终只发 1 次业务查询。
无 snapshot 的既有 Plan 保持原 live metadata 行为，合同漂移语义未放宽。

**严格空缓存验收：**显式使用 App `26827043`、事件 `$AppLogin`、日期
`2026-08-10..2026-08-16`，第一次输出 `status=plan_ready`、`status_before=missing`、
`status_after=ready`、`sync_performed=true`、`http_requests_observed=6`，Plan snapshot fingerprint 为
`02bd641b6149d0c2df66a0906ede394d9ffc4201daae65d2581dd149d1538803`。第二次输出
`gravity.plan-result.v1 / success / success_count=1 / failure_count=0`；真实
`analysis.event.query` 结果的 7 个日期值和阶段总和均为 0。最终本地 receipt 页恰有 **7** 项：
authentication、App、四类 metadata 和 event query 各 1；全部 HTTP 200 / attempt 1 / retry=false，
无追加页或扩窗。因此验收为 **2 次顶层调用 / 7 HTTP**，相对旧路径实际 `9 → 7`，没有把命令减少
换成租户请求增加。

**失败输出与错误审计：**省略 App 在 0 HTTP 时返回 `field=app`、观察值 `null`，唯一下一动作是运行
`app.list` 并由调用方选择；不存在的事件返回 `field=target`、观察值
`"__codex_missing_event__"`、exact match count 0，唯一下一动作是离线 `metadata events` 精确发现。
后者只做 1 次 App 校验，其 stored receipt 已绑定到错误 envelope。认证拒绝、无可读 App、sync
partial/失败、snapshot 漂移同样携带路径、观察值和合法替代或下一发现动作。caller-recoverable 审计为
`1169 + 25 = 1194`，新增 **25/25 全部 A 档**：`A 366 + 25 = 391`、`B=434`、`C=369`。

**计数与边界：**operation/stable `231/222 → +0/+0 = 231/222`；产品卡/selector
`88/328 → +0/+0 = 88/328`；动线 `55 = 47 / 1 / 7 → +0 / +0 / +0 = 55 = 47 / 1 / 7`。
`getting-started.md` 从 132 行重构为 152 行，未触及 160 行上限；生成的十分钟路径改为两调用入口。
整个任务生产 HTTP 为 **28/30**：2 次作废隔离校正、9 次旧基线、3 次开发 smoke、5 次发现残留
session 后作废的验收、7 次正式验收、2 次事件不存在失败复验；全部 HTTP 200、0 retry、0 额外分页、
0 扩窗、0 换 App。未新增技术债，未碰 holdout/final/key、题集、评分或评测装置，未做 GitHub/push/tag。

**最终门禁：**unittest `1111 + 9 =` **1120 tests OK**；pytest **1120 passed / 3082 subtests
passed**。compiler **231 operations / 11 manifests**；quality PASS（operations/provenance 231/231、
operation literals 57）；Agent 指南生成器 `--check`、文档可达性/行数、CLI help 与 `git diff --check`
均通过。实现增量 884 行、测试增量 291 行，测试/实现比约 0.329，未超过三分之一；所有新模块都在
500 SLOC 内，函数/复杂度/AST baseline 未放宽。
## 受治理语义组合首个窄切片（2026-08-17）

**提案与范围裁决：**ignored 工作稿位于 `tmp/codex/semantic-compose/proposal.md`。本轮只冻结一个
版本化 definition contract、复用既有 Multidim 执行三组真实查询，并把结果接到 Core/CLI/SDK/Plan/
Agent；没有做通用语义平台、第二套 capability registry、Text-to-SQL、Tier C SQL、conftemplate 或
分享。自定义指标 CRUD 已闭合；维度表被产品方搁置；SQL 工作台 route 在 Census 中不存在，所以
P0-3 不再等待原来的“三项全部完成”前提，但新增成员仍逐项要求现有合同和生产证据。

**冻结合同：**源定义为 `gravity.semantic-definition.v1` 的
`report.ap-cost-observation@1`，最终 canonical SHA-256 fingerprint 为
`e9ac825a4563a8c6c00f6147d55d23daf4a18cd8d85415a0caa6afa4e6971798`。输入合同是闭合的
`gravity.semantic-compose-input.v1`：definition、metric、dimension、grain、join 都必须是精确
`{definition_id, version}`；窗口是闭区间 ISO date；所有字段必须出现。v1 登记面如下：

- metric：`report.metric.ap-cost@1` → `ap_cost`；实时 metadata 由既有
  `report.multidim.metric.list` 复验；允许 day/week/total。
- dimension：`report.dimension.click-company@1` → `click_company`；必须同时声明
  `report.join.adreport-click-company@1`，其基数为 many-to-one、实现为 embedded dimension。
- grain：day/week/total 可执行；hour 是已登记但不在该 metric allowlist 的冲突成员，编译即拒绝。
- filter：v1 登记为空、`maxItems=0`。`click_company=bytedance` 用 `EQUALS` 和既有 CLI 映射 `IN`
  都得到上游 `INPUT_INVALID`，没有为了凑能力把它写进合同。
- access：App 由调用面显式解析并编译为唯一 `app_id EQUALS` 约束；结果不声称跨 App。

编译输出是 `gravity.semantic-compose-compiled.v1`，记录 `resolution_tier=tier_b_governed_semantic`、
definition ID/version/fingerprint、实际成员、生成的 Multidim query、六项 validation 和 scoped
`allowed_claims`。执行输出是 `gravity.semantic-compose-result.v1`，失败或语义错误时 claims 固定为空。
两条允许声明逐字为：

1. `observed-metric-value`：只陈述选定 App、闭区间窗口、粒度、维度和显式过滤条件下实际返回的
   `ap_cost` 值。
2. `within-result-comparison`：只在同一结果内部、明确引用返回的时间/维度键时比较 `ap_cost` 行。

因果、预算充分性、全量覆盖、未返回渠道为零、跨查询可加性都不在 claims 内。生成查询若成功也不会
扩大这两条声明。

**三个真实组合：**固定 App 29034827、窗口 `2026-06-01..2026-07-10`。这三问分别对应投放渠道
分配、日级 pacing/异常定位、周级节奏复盘，都是分析师常见问题；它们不是为了证明 API 而引入的新
成员，也都没有专用产品。三组 final 定义指纹一致，重复编译的 canonical bytes 完全相等：total/
day/week 的编译 SHA-256 分别为 `55f9b8805d4ee5410fe899a9de8136d3bd0a4a942b005487ce5cc6841353a89c`、
`d8768f5e59240c25d9fb8fe7607a5bed705b488cff2a768219c0a3a35cf67c5b`、
`094addbe1ae72f3f0f8bd4fdeac75bd0904af37fdeec46fd17fbe89a7caa6d88`。

```json
{"combination":"ap_cost total by click_company","rows":[{"click_company":"bytedance","ap_cost":10857257.59}],"allowed_claims":["observed-metric-value scoped to app/window/total/click_company/no filters","within-result-comparison scoped to returned click_company keys"]}
{"combination":"ap_cost weekly","rows":[{"stat_time":"2026-06-01","ap_cost":2713799.09},{"stat_time":"2026-06-08","ap_cost":2208883.51},{"stat_time":"2026-06-15","ap_cost":1682448.66},{"stat_time":"2026-06-22","ap_cost":1317221.50},{"stat_time":"2026-06-29","ap_cost":2000062.82},{"stat_time":"2026-07-06","ap_cost":934842.01}],"allowed_claims":["observed-metric-value scoped to app/window/week/no dimensions/no filters","within-result-comparison scoped to returned week keys"]}
{"combination":"ap_cost daily","rows":[{"stat_time":"2026-06-01","ap_cost":225988.82},{"stat_time":"2026-06-02","ap_cost":170459.42},{"stat_time":"2026-06-03","ap_cost":209434.35},{"stat_time":"2026-06-04","ap_cost":307436.77},{"stat_time":"2026-06-05","ap_cost":327135.37},{"stat_time":"2026-06-06","ap_cost":596423.36},{"stat_time":"2026-06-07","ap_cost":876921.0},{"stat_time":"2026-06-08","ap_cost":574670.4},{"stat_time":"2026-06-09","ap_cost":348563.5},{"stat_time":"2026-06-10","ap_cost":235817.26},{"stat_time":"2026-06-11","ap_cost":105068.8},{"stat_time":"2026-06-12","ap_cost":84517.14},{"stat_time":"2026-06-13","ap_cost":380878.89},{"stat_time":"2026-06-14","ap_cost":479367.52},{"stat_time":"2026-06-15","ap_cost":323065.58},{"stat_time":"2026-06-16","ap_cost":198633.94},{"stat_time":"2026-06-17","ap_cost":154776.47},{"stat_time":"2026-06-18","ap_cost":195318.25},{"stat_time":"2026-06-19","ap_cost":273202.44},{"stat_time":"2026-06-20","ap_cost":232999.84},{"stat_time":"2026-06-21","ap_cost":304452.14},{"stat_time":"2026-06-22","ap_cost":150449.93},{"stat_time":"2026-06-23","ap_cost":234983.98},{"stat_time":"2026-06-24","ap_cost":248813.44},{"stat_time":"2026-06-25","ap_cost":275153.39},{"stat_time":"2026-06-26","ap_cost":155816.29},{"stat_time":"2026-06-27","ap_cost":125773.74},{"stat_time":"2026-06-28","ap_cost":126230.73},{"stat_time":"2026-06-29","ap_cost":108308.24},{"stat_time":"2026-06-30","ap_cost":91991.92},{"stat_time":"2026-07-01","ap_cost":155216.44},{"stat_time":"2026-07-02","ap_cost":144071.02},{"stat_time":"2026-07-03","ap_cost":311384.82},{"stat_time":"2026-07-04","ap_cost":590727.72},{"stat_time":"2026-07-05","ap_cost":598362.66},{"stat_time":"2026-07-06","ap_cost":325789.49},{"stat_time":"2026-07-07","ap_cost":281162.34},{"stat_time":"2026-07-08","ap_cost":102469.6},{"stat_time":"2026-07-09","ap_cost":102889.64},{"stat_time":"2026-07-10","ap_cost":122530.94}],"allowed_claims":["observed-metric-value scoped to app/window/day/no dimensions/no filters","within-result-comparison scoped to returned day keys"]}
```

**发网前失败与版本：**`tests/test_semantic_compose.py` 用只要访问 `read/read_all/batch/request` 就计数并
抛错的 client，分别证明 unknown metric、已登记但对无维度请求禁止的 join、`ap_cost + hour` 粒度冲突
都抛 `InputValidationError` 且 `calls=0`。同文件把同一 definition ID 临时构造为 v1/v2，经同一结果
入口断言 `(definition_id, version)` 分别为 1/2 且 fingerprint 不同；结果不会被新定义静默重解释。

**生产 HTTP 逐请求账本：**实际 **20 / 25**。下面只列本单元自 `18:20:33Z` 起产生的 receipt；同一
私有 state root 在 18:21--18:27 有其他任务并发 receipt，不计入本单元。20 笔均 HTTP 200、attempt 1、
retry=false；分页操作均 page 1，页推进/窗口扩张均为 0。HTTP 200 只说明协议调用完成：#8、#11、
#13 的产品语义失败分别是 advertiser-filter、weekly-filter 和 corrected-IN-filter，均未发布 claims。

| # | operation | receipt | HTTP / retry / page | 作用 |
| ---: | --- | --- | --- | --- |
| 1 | `authentication` | `8688418e…` | 200 / false / - | 单次认证 |
| 2 | `app.list` | `e4d00447…` | 200 / false / 1 | 只读首屏 7 App；最初误选首项，未遍历 |
| 3 | `report.multidim.metric.list` | `6e82ace4…` | 200 / false / 1 | 1124 行目录与 `ap_cost` metadata |
| 4 | `report.multidim.query` | `cbe0607f…` | 200 / false / 1 | 首 App 固定窗口明确空 |
| 5 | `report.multidim.metric.list` | `4deaf9d4…` | 200 / false / 1 | App 29034827 total 组合 metadata |
| 6 | `report.multidim.query` | `4ab5c7ac…` | 200 / false / 1 | raw total by click_company 非空 |
| 7 | `report.multidim.metric.list` | `509b9544…` | 200 / false / 1 | advertiser/filter 组合 metadata |
| 8 | `report.multidim.query` | `d2c6ce94…` | 200 / false / 1 | advertiser + weekly + EQUALS filter，产品 `INPUT_INVALID` |
| 9 | `report.multidim.metric.list` | `9e2f6704…` | 200 / false / 1 | 首次 semantic surface metadata |
| 10 | `report.multidim.query` | `32ad71c6…` | 200 / false / 1 | semantic total by click_company 成功 |
| 11 | `report.multidim.query` | `3dda0060…` | 200 / false / 1 | semantic weekly + EQUALS filter，产品 `INPUT_INVALID` 后停止脚本 |
| 12 | `report.multidim.metric.list` | `12a7fd79…` | 200 / false / 1 | corrected-IN filter metadata |
| 13 | `report.multidim.query` | `81cabe10…` | 200 / false / 1 | total + IN filter，产品 `INPUT_INVALID` |
| 14 | `report.multidim.metric.list` | `400f875a…` | 200 / false / 1 | 无过滤 weekly 隔离 metadata |
| 15 | `report.multidim.query` | `c0f912c7…` | 200 / false / 1 | weekly 成功，证明应撤销 filter 而非 weekly |
| 16 | `report.multidim.metric.list` | `2dadf55c…` | 200 / false / 1 | 最终定义 total/day 共用 metadata |
| 17 | `report.multidim.query` | `a4f9dff6…` | 200 / false / 1 | final total by click_company |
| 18 | `report.multidim.query` | `321d9c13…` | 200 / false / 1 | final daily 40 行 |
| 19 | `report.multidim.metric.list` | `29cbe16f…` | 200 / false / 1 | final weekly metadata |
| 20 | `report.multidim.query` | `9d0325a2…` | 200 / false / 1 | final weekly 6 行、最终定义指纹 |

**能力边界与计数：**当前登记面足够支撑上述三个真实问题，但不足以支撑任何用户可选过滤器、其他
指标/维度、跨数据集 join、hour 或任意 SQL。明确不支持跨产品 many-to-many/未经证明 join、把日级
指标下钻到小时、把 raw SQL 成功解释为业务口径正确，以及任何超出 claims 的因果/完整性结论。
未新增 operation：组合只调用已有 `report.multidim.metric.list/query`；新增 operation 反而会复制固定
route 和治理。canonical 产品卡 `88→89`，selector `328→329`，动线
`55 = 47 / 1 / 7 → 56 = 48 / 1 / 7`。共享 spine 未越门禁，技术债复核不新增活动条目。

**最终门禁：**相对 `dev@3754fbe`，unittest **1118 tests OK**；pytest **1118 passed / 3083
subtests passed**。compiler **231 operations / 11 manifests**；quality PASS（operations/provenance
231/231、operation literals 57）；错误审计 **1176 = A373 / B434 / C369**，新增 7/7 个
caller-recoverable site 全为 A 档。Agent 指南生成器 `--check`、CLI help、input-schema、文档架构与
`git diff --check` 通过。实现增量显著多于测试增量，500/80/15/0 和 quality baseline 未放宽。
没有运行真实 holdout/final/all、读取 key、改题集/评分/评测装置；全量测试只运行其标明 synthetic 的
临时 fixture。没有 GitHub、push、tag 或其他对外动作。

## 外部 selector 选择网络显式标注为不可测（2026-08-17）

**提案与结论：**工作提案位于 ignored
`tmp/codex/selector-measure/proposal.md`。本轮结论不是“永远无法测量”，而是当前仓库的通用
subprocess selector 协议下，harness **不能独立、完备地测得**子进程及其后代的网络活动。
`subprocess.run()` 只向任意 Python plugin 传 stdin JSON；父进程的 `socket` patch 和
`BlockedTransport` 不会跨进程。纯 loopback 反事实让同一个子进程先用 `urllib` 遵循
`HTTP_PROXY`，再用原始 socket 绕过代理，父进程同时观察到 `proxy` 和 `direct` 两个边界且上游请求为
0。这证明代理命中能提供正证据，代理未命中不能证明没有网络调用。

三种候选手段的裁决如下：

1. 把 LLM HTTP 收回 harness 会把现有“任意 selector 可执行文件”改成 provider request/response
   协议；鉴权、prompt、结构化输出、重试、流式响应和 provider 差异都转由 evaluator 承担。更关键的是，
   只收回声明的调用仍不能阻止 plugin 另行出网，除非再叠加强制沙箱，故它单独不能满足谎报检测。
2. `HTTP_PROXY/HTTPS_PROXY` 或本机假代理只约束愿意读取环境变量的 HTTP client；plugin 可用原始
   socket、清除代理、设置 bypass 或再起后代进程。Windows Filtering Platform/ETW/AppContainer 一类
   强边界需要平台专用权限、runner 配置和进程树归属，不是当前依赖与 Windows CI 中可移植、确定的
   repo 内测量。它可以成为另一个受控 runner 项目，不能在本线冒充已有测量。
3. request id、token usage、latency、provider/model 等副证据若由同一 plugin 返回，仍可伪造；即使
   能向 provider 复核，也最多证明“至少一笔已知调用”，不能证明没有额外调用。因此它们是弱正证据，
   不是网络活动测量。本轮生产请求预算为 0，也没有为取得此类 receipt 调外部 LLM。

**机器合同：**每个 external-selector result 现在都带
`selection_network_measured=false` 与
`selection_network_measurement_reason="network_called is plugin-reported because the external selector runs in an uninstrumented subprocess"`。
external-selector 顶层 envelope 带同样两个字段，human summary 同时逐字显示布尔值和原因；受保护
查询账本的 `selector_arm.network_trials` 旁也投影 `network_measured` 和
`network_measurement_reason`。既有 `offline/network_called/selection_network_called`、
`external_selector_network_trials` 和账本 `network_trials` 为兼容只增不减，但现在不能脱离紧邻的
measurement marker 被解释为 harness 测量。内置同进程 recognizer 受现有 socket guard 约束，顶层
`selection_network_measured=true`；这不扩大 external plugin 的结论。

实际 development stub envelope 摘要为：

```json
{"split":"development","selection_network_measured":false,"selection_network_measurement_reason":"network_called is plugin-reported because the external selector runs in an uninstrumented subprocess","external_selector_network_trials":0,"socket_network_attempts":0,"production_http_requests":0}
```

```text
Selection network measured: False
Selection network measurement reason: network_called is plugin-reported because the external selector runs in an uninstrumented subprocess
```

**被测方自报字段盘点：**下表只按当前源码可见字段逐项分类；未保存在仓库中的外部 plugin 可能添加
任意 metadata 键，具体键集合不确定，不能猜测补全。

| 字段或投影 | harness 实际检查 | 状态 |
| --- | --- | --- |
| response `schema_version` | 必须精确等于 v1 | 已测量 |
| `results[].id` | 必须与匿名问题 ID 一一对应、无重缺 | 已测量 |
| `results[].selectors` | 校验数组形状、唯一性、最多 5 个、目录成员；再以冻结 gold 评分，并按实际 selector 集合测四次稳定性 | 已测量 |
| `results[].reason` | 只转成字符串；真实性、充分性和与 selector 的一致性不校验 | 未处理 |
| `metadata.selector` → 账本 `selector_versions` | 只要求非空字符串；不验证 provider/model/prompt 版本，也不与 plugin SHA-256 绑定 | 未处理 |
| `metadata.network_called` → result `offline/network_called/selection_network_called`、cost `external_selector_network_trials`、账本 `network_trials` | 只校验 boolean；全部仍是同一自报值 | 已标注为不可测 |
| stub `metadata.meaningful_accuracy_evidence` | 允许任意值并原样复制，不校验 | 未处理 |
| stub `metadata.request_sha256` | 不由 harness 重算或比对 | 未处理 |
| stub `metadata.stdin_encoding` | 不由父进程独立观测；现有测试只确认 stub 回报预期字符串 | 未处理 |
| 其他可选 metadata（如 provider/model/prompt、request id、token usage、latency） | metadata 允许额外键并原样进入 `trial_receipts`，无 schema 或外部复核 | 未处理 |
| plugin path/SHA-256、catalog 数量、盲化 receipt、进程返回码/超时、invocation/elapsed | 由 harness 文件、输入构造、进程结果和计时器生成 | 已测量 |
| `production_http_requests/socket_network_attempts/execution_http_requests/execution_network_called` | 来自父进程拦截计数；不等于对子进程 egress 的观测 | 已测量 |
| `terminal_offline_measured` 与原因 | selection-only harness 没有产品执行阶段 | 已标注为不可测 |

本轮按要求不顺手处理表中的 `reason`、selector identity 或任意附加 metadata；其中弱副证据即使后续
补 schema，也不能替代网络测量。技术债清单复核后不新增结构项：这是已显式建模的测量覆盖边界，退出
条件需要另行建设受控 runner/沙箱，而不是当前产品共享 spine 的结构债。

**development 与门禁：**本改动只新增 provenance 字段和摘要，不参与 route、parameter、terminal、
reliability 或 security 评分。同一锁定外部 LLM 选择的语义复算保持产品选择 `325/336`、参数
`247/247`、终点 `80/81`、恢复 `5/5`、selection unstable `7`、安全 `PASS/0`；没有重调模型。
另从 `git show HEAD:scripts/agent_usability_eval.py` 在内存加载改前 evaluator，与改后各跑同一公开
development/default arm；六层对象逐项相等。两边均为 `254/336、203/203、53/74、5/5`，
selection/terminal unstable 均 0、安全 `PASS/0`、生产 HTTP 0。deterministic stub 只验证协议接线，得到
`28/336、28/28、0/74、5/5`，不作为 LLM 证据。

operation/stable/产品卡/selector 保持 **231 / 222 / 89 / 329**；动线保持
**56 = 48 / 1 / 7**。unittest **1129 tests OK**；pytest **1129 passed / 3083 subtests passed**；
compiler **231 operations / 11 manifests**；quality PASS（operations/provenance 231/231、operation
literals 57）；错误审计保持 **1201 = A398 / B434 / C369**，新增 caller-recoverable error site/A 档为
**0/0**；Agent 指南、CLI help 与 `git diff --check` 通过。没有运行真实 holdout/final/all、读取 key、
查看/解密 sealed、修改题集/recognizer/目录/产品卡/gap/operation/阈值，或执行 GitHub/push/tag 动作。
生产上游业务 HTTP 和外部 LLM 请求均为 **0 次**；loopback 观测实验不产生上游请求。

## external selector 六类自报字段收口（2026-08-17）

**提案与边界：**工作提案位于 ignored
`tmp/codex/eval-selfreport/proposal.md`。本轮只修改 external-selector evaluator、协议说明、结果
envelope、人类摘要和查询账本 receipt；没有修改题集、recognizer、能力目录、产品卡、gap、operation 或
评分阈值。没有运行 holdout/final/all、读取 key、查看或解密 sealed 文件，也没有调用外部 LLM。

**逐类裁决：**六类没有保留“未处理”第三状态。机器字段
`selector_self_report_measurements` 固定含以下六项，并进入每个 external-selector result、顶层
evaluation envelope、`selector_arm` receipt 和受保护查询账本 receipt；human summary 逐项打印
`MEASURED` 或 `UNMEASURABLE`，后者同时打印原因。

| 类别 | 最终状态 | harness 依据或不可测边界 |
| --- | --- | --- |
| `results[].reason` | 已标注不可测 | 可观察文本和最终 selector，但没有 opaque selector 的决策轨迹，不能验证理由真实性、充分性或因果一致性。 |
| `metadata.selector` → `selector_versions` 与 plugin SHA | 已测量 | harness 在 trial 前后重算文件 SHA；同一 SHA 的四次 trial 只能有一个去空白版本串，受保护账本追加时还与同 SHA 的历史版本比对。 |
| `metadata.meaningful_accuracy_evidence` | 已标注不可测 | 冻结题集得分由 harness 自己测量，但该 metadata 没有独立 evidence 引用，不能证明其“有意义”声明。 |
| `metadata.request_sha256` | 已测量 | 父进程把实际 stdin 请求固定为排序键、compact separators 的 canonical JSON，再按 UTF-8 字节计算 SHA-256；plugin 一旦提供该字段，缺少精确匹配就 fail closed。 |
| `metadata.stdin_encoding` | 已标注不可测 | 父进程能证明发送 UTF-8 字节并设置 `PYTHONIOENCODING`，不能独立观察任意子进程实际 decoder 或 `sys.stdin.encoding`。 |
| 任意附加 metadata | 已标注不可测 | 可保存键和值并列出额外键，但没有 provider/model/request-id/token/latency 的外部权威 receipt；父进程自己的总耗时也不能验证 provider latency 或 token 语义。 |

`selector_identity={plugin_sha256,selector_version}` 将两个值放在同一 receipt。这个绑定能检出同一文件
SHA 在一次运行内改报版本、运行前后文件 SHA 漂移，以及受保护账本中同 SHA 的跨运行版本冲突；不能证明
版本串里的 provider/model/prompt/decoding 为真，也不能约束动态导入、外部服务版本、运行中改后复原或
额外网络调用。development 不写查询账本，所以跨 development 运行只输出可比较 binding，不持久化拒绝。

**谎报反事实：**新增两条测试均走生产函数。`test_external_selector_rejects_a_false_request_hash`
通过 `_invoke_plugin` 的真实 response decode/validate 路径回报 `"0" * 64`；
`test_one_plugin_sha_rejects_changing_selector_versions` 真实启动同一个临时 plugin 两次，由未变 plugin
文件分别回报 `liar.v1/v2`。当前两条均 fail closed。把 `f25ecac` 的
`agent_usability_external_selector.py` 直接载入内存复演相同输入，实际结果为：

```text
f25ecac_false_request_sha256=ACCEPTED
f25ecac_same_sha_version_drift=ACCEPTED
```

**实际 development 输出：**deterministic stub 的顶层 envelope 为（SHA 为本轮实际文件摘要）：

```json
{"selector_identity":{"plugin_sha256":"caf3d7523f8a4a28e208b21ed87d98a3af912bf1309df4f410e005c8743c2f3e","selector_version":"deterministic_catalog_name_stub.v1"},"request_sha256_verified_trials":4,"selector_self_report_measurements":{"result_reason":{"measured":false},"selector_version_plugin_sha_binding":{"measured":true},"meaningful_accuracy_evidence":{"measured":false},"request_sha256":{"measured":true},"stdin_encoding":{"measured":false},"additional_metadata":{"measured":false}},"production_http_requests":0,"socket_network_attempts":0}
```

human summary 实际输出为：

```text
Selector self-report result_reason: UNMEASURABLE
Selector self-report result_reason reason: the harness observes the text and selected selectors but has no independent selector decision trace
Selector self-report selector_version_plugin_sha_binding: MEASURED
Selector self-report meaningful_accuracy_evidence: UNMEASURABLE
Selector self-report meaningful_accuracy_evidence reason: meaningful_accuracy_evidence is plugin-reported without an independently verifiable evidence reference
Selector self-report request_sha256: MEASURED
Selector self-report stdin_encoding: UNMEASURABLE
Selector self-report stdin_encoding reason: the parent sends UTF-8 bytes but cannot observe the arbitrary child process's decoder or sys.stdin.encoding value
Selector self-report additional_metadata: UNMEASURABLE
Selector self-report additional_metadata reason: additional provider, model, request, token, or latency metadata is reported by the uninstrumented plugin without an external receipt
```

同一个 development result 经真实 `append_query_record` 生产路径投影到临时合成 ledger（没有加载受保护
题集）后，`selector_arm` receipt 同时含上述完整六项 measurement map、同一
`selector_identity`、`selector_versions=["deterministic_catalog_name_stub.v1"]` 和
`request_sha256_verified_trials=4`。实际不可测原因也保存在每个 `measured=false` 项中，不依赖文档解释。

**盘点完整性修正：**上一轮表漏掉了任意 response 顶层附加键。修复前，除
`schema_version/results/metadata` 外的键会被 JSON parser 接受后静默丢弃；现在顶层严格 allowlist 并有
回归测试，因此该协议形状为已测量。成功进程写到 stderr 的非字段文本不会进入 response 或 receipt；
在当前 JSON 协议内，除已测量的 schema/id/selectors、已显式标注的 `network_called`、本轮六类以及这项
顶层形状外，没有再发现被接受的自报字段。未保存在仓库中的未来 metadata 键名仍不确定，但统一落入
`additional_metadata` 不可测类别和 `additional_metadata_keys` 实际键清单，不再形成未分类状态。

**复算与门禁：**评分逻辑未改。公开 development/default arm 保持
`254/336、203/203、53/74、5/5`，selection/terminal unstable 均 0、安全 `PASS/0`；deterministic
stub 保持 `28/336、28/28、0/74、5/5`，selection/terminal unstable 均 0、安全 `PASS/0`。两次
production HTTP 均为 0。operation/stable/产品卡/selector 保持 **231 / 222 / 89 / 329**；动线保持
**56 = 48 / 1 / 7**。unittest **1133 tests OK**；pytest **1133 passed / 3083 subtests passed**；
compiler **231 operations / 11 manifests**；quality PASS（operations/provenance 231/231、operation
literals 57）；错误审计保持 **1202 = A399 / B434 / C369**。新增 evaluator 错误位于 `scripts/`，不在
该审计器的 `src/` 与 typed caller-error 统计域内，故审计口径增量仍为 **0/0**；七个新增
`ValueError` fail-closed 点都给出具体恢复动作。
窄测量模块使 external-selector 主文件保持 431 行，没有放宽 500/80/15/0 或 quality baseline；新增
实现 230 行、测试 76 行，测试增量不超过实现增量三分之一。技术债清单复核后不新增活动条目。
## 语义组合过滤 wire 与 v2（2026-08-17）

**提案与证据顺序：**ignored 工作稿位于 `tmp/codex/filter-wire/proposal.md`。本轮先以 Census
定位 route，再读 hash 已校验的 375 文件原始 JS；生产请求只验证从前端导出的 payload，不猜 operator。
`routes.json:4893-4932` 只证明 `POST /report/api/v3/adreport/custom_get/` 调用点，完整请求由以下 JS 冻结：

- `NewReportCenter-Dxgo5EkI.js` line 1、offset 234539 的 `Lc(e)` 生成
  `{field:\`click_company\`,operator:\`IN\`,values:ad_platform_list}`；`app_id/project_id` 标量用
  `EQUALS`，选项列表用 `IN`，该 builder 只出现这两个 operator literal。
- 同文件 line 1、offset 306363 把 `filters:[...Lc(e)]` 与 `time_dims/date_list/data_dims/relate_dims/
  metrics_list/custom_metrics_list/data_conf/data_topic` 同层放进 `Te({body:r})`。本 route 不使用
  `global_conditions/local_conditions`。
- `index-D9HAN43D.js` line 2、offset 1008445（column 992158）定义
  `{label:\`巨量引擎\`,value:\`bytedance\`}` 和 `{label:\`腾讯广告\`,value:\`tencent\`}`。
  所以 `bytedance` 是前端实际发送的内部 option code，显示名是“巨量引擎”，不是漏传的数字 ID。
- `BilibiliAd-47iK5OH4.js` line 1、offset 49359 的 `ct(e)` 独立使用相同
  `{field,operator,values}` wire，并给出当前六字段 `data_conf` profile；其专用 builder 还对
  `advertiser_remark` 使用 `LIKE`。这些是当前前端 builder 的枚举证据，不冒充完整后端 enum；v2 只登记
  生产实证成立的 click-company `IN` 配对。

**失败根因与可证伪对照：**固定 App 29034827、窗口 `2026-06-01..2026-07-10`。无过滤、按
`click_company` 分组的 total 只有 `bytedance = 10857257.59`。前端原样
`click_company IN [bytedance]` 在 `data_dims=[]` 时仍为 `INPUT_INVALID`；只增加
`data_dims=[click_company]` 后成功并仍返回 `10857257.59`。同一 grouped request 改为
`tencent` 后业务 success、`list=[]`、`page_info.total=0`，证明过滤没有被静默忽略。故 v2 的可执行
合同不是任意物理 filter，而是“`click_company IN` + 同时选中 `click_company` dimension + 其
many-to-one embedded join”。上一轮 corrected `IN` 的已证错误是漏了该 dimension；早期 `EQUALS`
同时偏离前端 operator 且漏 dimension，现有证据不能隔离二者哪一个单独导致那次失败。

`advertiser_id` 不随前端出现而开放：先无过滤分组取得真实内部 ID，再用非零 ID 及
`data_dims=[advertiser_id]` 请求，仍为 `INPUT_INVALID`。脱敏错误不能区分必填依赖、权限或该维度
自身规则，当前结论只能是“不得登记 advertiser filter”，不能猜后台原因。

**v1/v2 与成员裁决：**`report.ap-cost-observation@1` 原文件和 fingerprint
`e9ac825a4563a8c6c00f6147d55d23daf4a18cd8d85415a0caa6afa4e6971798` 不变；新增
`report.ap-cost-observation@2` fingerprint 为
`7273eb90dab433099b6a1f883cdef9c88626cae77c6d0dc83b7ea6516a50e461`。两版由同一闭合 input
schema 显式列出，member refs 去重后不会产生重复 `oneOf` 分支。v2 的 filter 上限为 1，编译前要求
匹配 dimension，缺失时以 `InputValidationError` 和可执行 next action 零网络拒绝；v1 继续
`filters.maxItems=0`，生成查询不被 v2 profile 静默改变。

本轮没有倒入 1124 行 metric 目录，只从当前 live metadata 挑 3 个分析师常问成员，并逐粒度实测：

| v2 metric | metadata 口径来源 | day | week | total | allowlist |
| --- | --- | --- | --- | --- | --- |
| `adclick_standard_activate_cnt` | `标准_激活数(点击时间)`；末次点击归因的 MPLaunch/AppStart 用户数 | 40 行，首尾 `18195/13100` | 6 行，首尾 `185315/78793` | 单指标 `INPUT_INVALID` | day/week |
| `adclick_standard_pay_amount` | `标准_总付费金额(点击时间)`；末次点击归因的付费事件金额 | 40 行，首尾 `81502.0/15888.0` | 6 行，首尾 `1005575.0/184830.0` | 单指标 `INPUT_INVALID` | day/week |
| `adclick_total_roi` | `总ROI(点击时间)`；metadata 定义为总收入/平台消耗 | 40 行，首尾 `0.4/0.15` | 6 行，首尾 `0.4/0.22` | 单指标 `INPUT_INVALID` | day/week |

三者 live metadata 的 `exclusion_dims=[]` 只是成员候选证据，day/week 成功和各自 total 失败才是 grain
allowlist 证据。`ap_cost` 在 v2 仍保留 day/week/total。完整语义链以 activate/day、同维度 join、
`bytedance` filter 编译并实际返回 40 行（首尾 `18195/13100`）及非空 `allowed_claims`；metadata 复用
本轮已取的当前目录行，没有再次翻 29 页。

**生产 HTTP 逐请求账本：**实际 **21/25**，此后停止。21 笔均 HTTP 200、attempt 1、retry=false；
query 均 page 1、固定同一 App/窗口、无重试或扩窗。#2-#6 是明确记录的操作失误：`gravity run`
把请求的 metric page size clamp 为 40 后自动跟随默认五页；这 5 笔全部计入预算，只使用返回的前
200 个成员，随后不再分页。

| # | operation | receipt | page | 产品观察 |
| ---: | --- | --- | ---: | --- |
| 1 | `authentication` | `c78e604d…` | - | login success |
| 2 | `report.multidim.metric.list` | `f3e31b68…` | 1 | 目录 1-40 |
| 3 | `report.multidim.metric.list` | `3aaecae5…` | 2 | 误续页 |
| 4 | `report.multidim.metric.list` | `66ce5866…` | 3 | 误续页 |
| 5 | `report.multidim.metric.list` | `1ca34c65…` | 4 | 误续页 |
| 6 | `report.multidim.metric.list` | `393c38af…` | 5 | 误续页；观察 200/1124 |
| 7 | `report.multidim.query` | `f43ff337…` | 1 | unfiltered grouped total `10857257.59` |
| 8 | `report.multidim.query` | `e1a46436…` | 1 | bytedance/no dimension `INPUT_INVALID` |
| 9 | `report.multidim.query` | `23ab8cfa…` | 1 | tencent/no dimension `INPUT_INVALID` |
| 10 | `report.multidim.query` | `a60bb43f…` | 1 | bytedance/with dimension `10857257.59` |
| 11 | `report.multidim.query` | `ed4b60f9…` | 1 | advertiser grouping non-empty |
| 12 | `report.multidim.query` | `e95c40f0…` | 1 | returned advertiser ID/no dimension `INPUT_INVALID` |
| 13 | `report.multidim.query` | `eedf61ac…` | 1 | nonzero advertiser ID/with dimension `INPUT_INVALID` |
| 14 | `report.multidim.query` | `bee295bb…` | 1 | 3 new metrics/day, 40 rows |
| 15 | `report.multidim.query` | `f78ed63e…` | 1 | 3 new metrics/week, 6 rows |
| 16 | `report.multidim.query` | `55dfacc6…` | 1 | 3 new metrics/total `INPUT_INVALID` |
| 17 | `report.multidim.query` | `bccd73aa…` | 1 | activate/total `INPUT_INVALID` |
| 18 | `report.multidim.query` | `f25f7e54…` | 1 | pay amount/total `INPUT_INVALID` |
| 19 | `report.multidim.query` | `949b45c2…` | 1 | total ROI/total `INPUT_INVALID` |
| 20 | `report.multidim.query` | `327c0e67…` | 1 | semantic v2/day, 40 rows + claims |
| 21 | `report.multidim.query` | `7a17208a…` | 1 | tencent/with dimension success empty |

本地另有一次 enum 容器类型错误在 transport 前失败，HTTP=0，不列为请求。能力计数不变：仍为
231 operations、222 stable、89 canonical 产品卡、329 selectors、`56 = 48 / 1 / 7`。没有新增 route、
SQL、registry、worker 或活动结构债；未碰 holdout/final/key/评测装置，也没有 GitHub/push/tag。

**最终门禁：**unittest **1131 tests OK**；pytest **1131 passed / 3083 subtests passed**，相对
`dev@5c75402` 的 1129 测试只增不减。compiler **231 operations / 11 manifests**；quality PASS
（operations/provenance 231/231、operation literals 57）。错误审计由
`1201 = A398/B434/C369` 收紧为 **1202 = A399/B434/C369**，新增 caller-recoverable site 为 A 档，
B/C 未增长。`test_same_definition_id_versions_remain_distinct_in_results` 原断言保留，另以
`test_real_v1_v2_definitions_coexist_and_v2_compiles_live_wire` 覆盖仓库真实两版定义、不同 fingerprint
和 v1 查询不继承 v2 profile。Agent 指南生成器 `--check`、CLI help 与 `git diff --check` 均通过。
实现/合同/manifest 新增 267 行，测试与 golden 新增 68 行，约 0.255，未超过三分之一；quality baseline
未放宽。


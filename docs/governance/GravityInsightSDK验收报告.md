# Gravity Insight SDK 验收报告

> 迁移说明：本文是拆仓前 `work-dashboard` 源提交上的验收快照，保留当时的路径、测试数字和门禁输出作为 provenance。独立仓库的当前状态以根 README、CI 和本仓库实际测试结果为准。

验收日期：2026-08-10。验收对象：`feat/gravity-sdk-productization` 分支
`505c6e78`。结论：**当前 SDK 能力按 141 个 stable read operation 计算，不按 987 条
census route 计算。另有 295 个不可调用 draft、414 个 blocked-write reservation，以及
独立的 22 条 export route。**

本机 PATH 中的 Python 为 3.14.6，CI 目标为 3.11；本报告的测试结果只证明本机 3.14.6。
本次没有调用经过认证的 Gravity 业务 API，没有创建导出或写请求。为复核第三方 Bearer
字面量，额外只读抓取了一次公开前端 bundle 到系统临时目录；没有把 bundle 或凭据写入仓库。

## 1. 数字口径

### 1.1 当前交付数字

| 数字 | 当前准确含义 | 不能表述为 |
| --- | --- | --- |
| 987 accounted | 当前静态路由图中 987 条 method+path 全部已记账，unaccounted=0 | 987 个 SDK 能力 |
| 137 callable_covered | 987 条 census route 中，137 条被 stable executable operation 精确覆盖 | 137 个 operation；operation 与 route 不是同一口径 |
| 150 compiled operations | runtime catalog 中 141 stable、2 experimental、5 blocked_privacy、1 permission_unavailable、1 deprecated | 150 条当前可调用能力 |
| 141 stable | 默认可执行的 read operation | 141 条此刻都有非空数据或在线 health 全绿 |
| 295 draft | 可 search/describe、不可调用的候选 operation | 已支持或试运行能力 |
| 414 blocked-write reservations | 写语义 route 的防遗漏预留，全部不可执行 | Mutation SDK 已实现 |
| 22 export routes | 独立 export catalog；5 条 callable，其中 create 只有 1 条 | 22 种导出都能创建 |
| 8 / 7 / 7 export 证据分布 | 8 条在线验证、7 条在线尝试但仅部分/失败证据、7 条未调用 | 8 条都可执行 |
| 352 routes / 691 fields | 静态 bundle 响应消费点提取结果 | 服务端承诺返回这些字段 |
| 811 passed / 1771 subtests passed | `tests/` 在本机 Python 3.14.6 的离线全量结果 | Python 3.11 CI 已在本趟重跑 |
| 2 FAIL | 普通 `validate_all` 当前保留的两条 P1 topic 目录失败 | Gravity SDK 门禁失败 |

当前 compiled operation 全部为 `effect=read`。export catalog 与 blocked-write reservation
不计入这 150 个 read operation。

### 1.2 可复核命令与实测输出

```powershell
python -m gravity_sdk.compiler lint
# lint: 150 operations, 10 manifests

python -m gravity_sdk.compiler compile --check
# compile: 150 operations, 10 manifests

gravity insight --dry-run
# status=pass, operations=150, registered_operations=150, network_called=false
```

compiled stability 分布由当前 checked-in manifest 重算：

```powershell
$ops = Get-ChildItem src/gravity_sdk/manifests -Filter *.json |
  ForEach-Object { (Get-Content -Raw $_.FullName | ConvertFrom-Json).operations }
$ops | Group-Object stability | Sort-Object Name |
  ForEach-Object { '{0}={1}' -f $_.Name,$_.Count }
# blocked_privacy=5
# deprecated=1
# experimental=2
# permission_unavailable=1
# stable=141
```

```powershell
$out = Join-Path $env:TEMP gi-report-coverage.json
$report = Join-Path $env:TEMP gi-report-coverage.md
gravity census coverage --require-complete --require-accounted `
  --output $out --report $report
# accounted=987, total_routes=987, callable_covered=137, unaccounted=0
# uncovered_read=378, uncovered_write=414, uncovered_export=22
# uncovered_auth_or_proxy=30, unsupported_non_api=6
```

export 的 8 / 7 / 7 分布由 `export list-capabilities` 返回的每条 verification 状态计算，
不是沿用旧报告：

```powershell
gravity insight export list-capabilities
# count=22, callable_count=5, callable_create_count=1
# verification.online=true: 8
# attempted_online=true 且 online!=true: 7
# 两者均非 true: 7
```

```powershell
python -m pytest tests/ -q -p no:cacheprovider
# 811 passed, 1771 subtests passed

python -m tools.common.validate_all
# PASS P1 test-time-safety
# PASS P1 privacy-classification-consistency
# PASS P1 stable-response-privacy
# FAIL P1 topic-directory-structure: 宾果专项分析/报告/附件
# FAIL P1 topic-directory-structure: 消暑特殊礼包/报告/2026-08-03_..._风格提案
```

普通门禁同时产生 2 条 WARN：report lifecycle 尚有 7 个未登记 artifact；link baseline 内有
58 条物理断链（53 条冻结历史引用、5 条 ledger 可解析引用、0 条 missing target）。

## 2. 做到了什么

### 2.1 构建期契约和运行时目录

150 个 operation 可确定性 lint/compile，checked-in manifest 与源码一致；runtime dry-run
不调用网络。运行时 manifest 现在保留语义字段 `effect`，同时剔除 description、example
等纯文档字段对契约指纹的影响。

### 2.2 能力发现、描述、校验和结构化错误

`capabilities search/describe` 同时展示 stable 与不可调用 draft；describe 暴露输入 schema、
wire、projection、privacy、分页、example、父依赖、health、provenance 和 blockers。
`validate` 提供 `valid_offline/needs_live_metadata/invalid` 三态，不发网络请求。错误 envelope
固定携带 `category/retryable/retry_after_ms/next_action`。

### 2.3 父资源解析和 `parents resolve`

新增公共命令：

```powershell
gravity insight parents resolve <operation-id>
```

它读取 operation 声明的 stable parent，保留候选基数；`caller_select` 不替调用方选择业务
资源，同一共享 parent 在一次解析中只请求一次。当前 checked-in parent resolution evidence
覆盖 74 个 operation：24 个 `unblocked`、17 个 `blocked_by_data`、33 个 `undetermined`，
且 `values_persisted=true` 为 0。当前仍有 33 个 draft 保留 `parent_resource_required`。

离线验证：

```powershell
python -m pytest tests/test_gravity_insight_parent_resolution.py -q -p no:cacheprovider
# 7 passed
```

### 2.4 `discover-nonempty`

新增按契约搜索非空筛选组合的入口。它从 enum、日期窗口、boolean 和已解析 parent 候选构造
搜索维度，按权重 best-first 遍历，受 request budget、candidate limit 和最小请求间隔约束；
找到组合后只返回组合、计数和 schema hash，缓存位于仓库外的临时区。只有可枚举空间被穷尽时
才允许 `confirmed_empty`；opaque object、裸 scalar ID 或缺少 candidate producer 时保持
`undetermined`。

```powershell
gravity insight discover-nonempty <operation-id> --request-budget 12 --candidate-limit 5

python -m pytest tests/test_gravity_insight_nonempty.py -q -p no:cacheprovider
# 13 passed
```

### 2.5 Census 响应字段提取

`gravity_census responses` 从前端 object literal 消费点提取响应字段候选。当前 checked-in
artifact 实测为 352 条 route、691 个 field、1797 个 provenance evidence point。
所有候选进入 draft 时均为 unknown/manual_review/expose=false，不直接改
`response_projection`。

```powershell
gravity census responses --help
# 显示 --snapshot/--routes/--raw-dir/--output/--drafts/--apply-drafts

python -m pytest tests/test_gravity_census_response.py -q -p no:cacheprovider
# 3 passed
```

### 2.6 两道隐私门禁

`privacy-classification-consistency` 校验 stable 暴露状态与 draft 分类决策的完整矩阵；只排除
带生成器自身 `frontend_static_consumer_unreviewed` provenance 的静态候选，不能再用
`expose=false` 规避敏感字段检查。

`stable-response-privacy` 不依赖 draft 是否出现过该字段，单独登记并核对全部 stable 响应
表面。当前 registry 覆盖 141 个 stable operation、2413 条 exposed path；新增、删除或疑似
直接个人标识未同步复核都会失败。

```powershell
python -m tools.common.validate_all
# PASS P1 privacy-classification-consistency
# PASS P1 stable-response-privacy

python -m pytest tests/test_gravity_insight_quality.py tests/test_gravity_insight_stable_privacy.py -q -p no:cacheprovider
# 19 passed
```

### 2.7 时间安全门禁

`resume_job` 与同模块其他入口一致支持显式 `now` 注入；生产 CLI 仍使用真实时钟。新增 AST
门禁扫描固定日历时间与直接/间接真实时钟读取的混用，防止跨过时间窗口后测试自行变红。

```powershell
python -m tools.common.validate_all
# PASS P1 test-time-safety

python -m pytest tools/common/tests/test_time_safety.py tests/test_gm_background_approval.py -q -p no:cacheprovider
# 24 passed
```

### 2.8 Accept-Encoding 动态协商

HTTP runtime 不再无条件声明 `br,zstd`，而是在 import 时读取 urllib3 decoder table 并实际
构造 decoder；探测异常时退化为 `gzip, deflate`，不新增运行时依赖。当前 PATH Python 的
实际协商结果与验证为：

```powershell
python -c "from gravity_sdk.content_encoding import ACCEPT_ENCODING; print(ACCEPT_ENCODING)"
# gzip, deflate, br, zstd

python -m pytest tests/test_gravity_insight_encoding.py tests/test_gravity_http_runtime.py -q -p no:cacheprovider
# 21 passed, 14 subtests passed
```

当前机器支持 `br,zstd`，所以输出仍包含两者；测试同时覆盖 decoder 缺失和 probe 失败时的
降级路径。

### 2.9 分页、大结果保护和导出

stdout 默认最多 5 页/200 条；`--all-pages` 必须配 output 或 NDJSON；硬上限为 1000 页/
100000 条。截断 envelope 提供 `next_page_input`，大值只进入摘要/reference。

导出 effect 与 read 分离，具备 start/status/wait/download/cancel/list。当前只开放
`export.material.report.start` 这一条 create；下载前验证 host/path、一次性授权、大小、MIME、
ZIP magic、归档安全、工作表表头和 SHA-256，最后原子落盘。create 不自动重试，wait timeout
不隐式 cancel，cancel response 不被当作终态。

## 3. 没做到什么，为什么

### 3.1 295 个 draft 仍不是“差一次 probe 就能用”

直接读取 295 个当前 draft 的 structured blockers，得到：`response_schema_unverified=255`、
`empty_sample=122`、`probe_inconclusive=67`、`request_parameters_required=63`、
`pagination_unverified=57`、`parent_resource_required=33`、`not_probed=29`、
`request_binding_unverified=29`、`openapi_developer_credentials_unavailable=3`。

按旧报告的精确定义，即 open blocker 与 promotion missing 除 `empty_sample` 和其必然派生的
`successful_probe` 外没有其他项，**当前仍是 24 条**，不是旧分母下的 299 条。这个 24 是
从当前 JSON 重算得到，不是从旧报告或 commit message 抄录。它不代表这些 operation 已可调用，
也不代表非空 item 的字段与隐私已验证。

### 3.2 `discover-nonempty` 不能创造候选空间

当前 122 个 draft 带 `empty_sample`，其中 115 个符合内部批处理器的精确 blocker-set 范围；
这两个数都不是“只差数据”的同义词。对于 opaque filter、裸 ID、未解析 parent 或缺少 enum/
candidate producer 的输入，工具只能返回 `undetermined`。本轮批处理的逐 operation 输出原先
位于 `tmp/`，没有进入当前仓库；因此本报告不复述 commit message 中的历史结果分布。

### 3.3 静态字段证据不等于服务端契约

前端消费某个 key 只能证明前端读过它，不能证明服务端一定返回、类型固定、租户都可见或字段
不含敏感内容。352/691 是静态候选覆盖，不是 stable capability 增量；仍需非空在线 probe、
schema 分类和人工隐私裁决。

### 3.4 导出证据不等于全部开放

22 条 route 中只有 5 条 callable，create 只有 1 条。8 条 online=true 包含 status/evaluate
等不同 effect，也包含因用户级数据隐私而关闭的能力，不能写成 8 种可创建导出。本趟没有
重新创建、等待或下载真实导出任务。

### 3.5 `prober status` 当前默认全量命令损坏

```powershell
python -m gravity_sdk.prober status
# exit 1, INPUT_INVALID:
# could not read JSON: evidence/probe/20260809T143533Z_privacy_classification_audit.yaml
```

原因是默认扫描把一份 YAML 审计证据交给 JSON reader。因本趟只允许改文档，该缺陷没有修；
本报告的 draft 数和 blocker 数改为直接解析当前 contract JSON。使用方在修复前不能把
`prober status` 当作可用的全量状态入口。

### 3.6 Python 3.11 与真实上游仍未在本趟复验

811/1771 只来自 Python 3.14.6。本趟没有运行 Python 3.11 CI，也没有调用 authenticated
Gravity API，因此不能据此声明在线权限、非空数据、上游语义或所有 content encoding 在生产
链路均已验证。

### 3.7 仓库普通门禁仍非全绿

当前 2 条 topic-directory-structure P1 FAIL 与 Gravity 改动无关，但仓库整体仍应表述为
`validate_all` 失败，不能只报新增 Gravity 门禁 PASS。另有 2 类 WARN，见 1.2。

原报告的“stable 目录仍有 12 条 description 以 Draft catalog entry 开头”已解决；当前重算
为 0，不再保留为未完成项。原“description 进入契约指纹”也已解决，移入下一节。

## 4. 本轮发现并修复的既有缺陷

### 4.1 `effect` 从未进入 runtime manifest

- 发现：在拆分语义字段与文档字段的指纹边界时，对 `effect` 做变异测试，read 改为 mutation
  后指纹不变。
- 根因：source contract 有 `effect`，但 `OperationSpec` 与 compiler runtime product 没有保留；
  registry 只能对缺失该语义的 schema 求指纹。
- 修复：runtime model、compiler 和语义指纹均保留 `effect`；PolicyEngine 拒绝任何非 read
  operation 进入 read 执行链。当前 150 个 compiled operation 均实测为 `effect=read`。
- 防复发：compiler 固定断言 runtime product 包含 effect，指纹测试固定断言 requiredness 或
  effect 改变会改变 fingerprint。

### 4.2 Accept-Encoding 可声明运行环境解不了的编码

- 发现：对抗性 transport 测试模拟服务器按声明返回 `br`，在缺少 brotli decoder 的解释器中，
  HTTP 200 响应会被静默解析成 null。
- 根因：请求头硬编码 `gzip, deflate, br, zstd`，未与 urllib3 的实际 decoder 能力对齐。
- 修复：运行时动态探测并构造 optional decoder，任何异常都 fail-safe 降级到 gzip/deflate。
- 防复发：encoding 与 HTTP runtime 的 21 个测试加 14 个 subtest 覆盖支持、缺失、构造失败和
  header 一致性。

### 4.3 GM 审批测试会随墙钟漂移

- 发现：把模块时钟推进到 2036 后，原测试跨过 24 小时审批窗口自行失败。
- 根因：测试一边使用固定时间常量，一边经 `resume_job` 读取真实 `datetime.now()`。
- 修复：`resume_job` 增加 `now` 注入点；生产默认仍读取真实时钟，审批窗口未改变。
- 防复发：AST `test-time-safety` 门禁拒绝固定日历时间与未注入墙钟的混用；相关 24 个测试
  当前通过。

### 4.4 隐私一致性规则矩阵有缺口

- 发现：对抗性测试把已判 sensitive 的 draft 字段重新加入 stable 暴露，门禁没有报警。
- 根因：一次误修用 `expose is False` 排除静态误报，但 sensitive 字段本来就都是 false，导致
  “stable 暴露 x draft sensitive”分支没有检查对象；完全不在 candidate_fields 的字段也不可见。
- 修复：一致性门禁只按 `frontend_static_consumer_unreviewed` provenance 排除生成器未审候选，
  不再按分类结果排除。
- 防复发：完整矩阵测试固定回归；第二道 stable-response-privacy 独立于 draft 扫描。

### 4.5 9 个 stable operation 暴露直接身份标识

- 发现：新 stable registry 对全部 stable response path 做独立枚举后，发现以下 9 个 operation
  暴露联系方式、成员姓名、IDFA/IDFV/CAID/OAID/IMEI/AndroidId 或 WXOpenID：
  `analysis.account_user.list`、`analysis.dashboard.detail`、
  `analysis.dashboard.members.list`、`analysis.dashboard.space_members.list`、
  `analysis.monetization_detail.list`、`analysis.order_detail.list`、
  `analysis.segment.user_detail.list`、`analysis.user_detail.list`、
  `analysis.user_event.list`。
- 根因：有些字段从未进入 draft candidate_fields；同时旧一致性门禁的误排除使已判敏感字段也
  不报警。因此当时没有门禁能覆盖完整 stable 表面。
- 修复：从 stable projection 与动态请求字段中撤回直接标识；email filter 也被移除，避免通过
  稳定 user_id 构造身份映射 oracle。
- 防复发：stable-response-privacy registry 当前锁定 141 个 operation 的 2413 条 exposed path；
  未登记新增、陈旧登记或未 redaction 的疑似直接标识都会失败。

### 4.6 文档修改会无谓使 probe 指纹失效

- 发现：划定契约语义边界时，单改 operation/field description 就会改变 fingerprint。
- 根因：旧实现对完整 runtime schema 做 JSON hash，没有区分行为语义与 agent 文档。
- 修复：description、example 等文档字段不再参与契约指纹；会改变 SDK 输出的
  `semantic_error_rules.message` 和 `block_reason` 仍保留在语义侧。
- 防复发：两条定向测试分别锁定“文档变化不改 fingerprint”和“required/effect 变化必须改
  fingerprint”，当前实测 2 passed。

## 5. 风险与后续

### 5.1 必须由使用方处理

1. **专题临时例外到期**：`90_治理与质量门禁/专题目录例外.yaml` 中
   `消暑特殊礼包/机制与投放决策草案.md` 的 `expires_on` 为 2026-08-14；专题 owner 是
   `liveops-data`。应在 2026-08-14 当日结束前迁入 `运营/` 并删除例外；从 2026-08-15 起，
   只要文件与过期例外仍在，`validate_all` 就会持续新增一条 FAIL。
2. **前端第三方 Bearer 字面量**：对与 checked-in census 相同 bundle ID 的 375 个当前
   same-origin chunk 完整扫描，只发现 **1 处**，不是任务说明中的 2 处。位置为
   `raw/web.gravity-engine.com/assets/index-D9HAN43D.js:498:1244`，character offset
   `5418889`，Bearer 值长度 68；报告未记录值。建议向引力反馈，确认用途、撤下字面量并轮换；
   同时请其提供任务所称第二处的位置或对应旧 bundle ID。
3. **`advertiser_name` 已裁决**：业务 owner 于 2026-08-10 确认该字段可能出现自然人姓名或
   无组织标记的个体工商户，因此判定 sensitive，继续从 SDK 响应中移除；这不是技术推断。
4. **业务问题清单**：当前状态见
   [Gravity Insight SDK 业务裁决清单](GravityInsightSDK业务裁决清单.md)。原 3 个问题中 2 个已
   裁决，腾讯广告组出价与预算问题经 shape-only probe 收窄后仍待业务回答；111 个静态候选行
   仍只进入工程 probe 队列，状态未变。
5. **GM truth 新鲜度**：`tools/campaign/gm_truth.py` 当前选择的最新快照为 2026-08-08，
   默认阈值 30 天。2026-09-08 实测 `age_days=31, warnings=1`；若此前未刷新，从该日开始输出
   stale warning。应由 GM 数据 owner 在阈值前补新的 checked-in snapshot。

### 5.2 已知环境约束

- 用户已确认无法提供在目标路由有非空投放数据的账号；empty-sample draft 当前不能靠新增代码
  自动转正。将来有受控账号后仍须走非空 schema 与隐私闸门。
- 用户已确认无法提供 OpenAPI developer `app_key/sign`；当前 3 个相关 blocker 保持关闭，
  登录态凭据不能替代签名通道。
- 私有仓库免费账户不支持所需 GitHub 分支保护；本地 pre-push hook 可被 `--no-verify` 绕过，
  GitHub Actions 只能提供推送后可见性，不能强制阻止合并。
- `prober status` 的 YAML/JSON 读取缺陷应单独建修复任务；在修复前，验收脚本应直接读 structured
  contract JSON，或只查询明确的 operation ID。

### 5.3 上游漂移检测边界

当前能检测公开入口 HTML/bundle hash、静态 method/path 变化、route accounting、已登记
projection/schema fingerprint 和确认性破坏。仍不能检测登录后按租户/角色/feature flag 才
下发的模块、运行时拼接 URL、method/path 不变但业务语义改变、空数组中的 item schema，或
区分单次故障与长期权限变化。任何这类结论仍需独立在线证据。

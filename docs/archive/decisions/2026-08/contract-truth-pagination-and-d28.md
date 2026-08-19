> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 合同真实性、分页与 D28

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：分页声明与可重放边界、D28/公开 App 动线、91 卡合法宿主选择、无证据续页与租户枚举晋升。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## 合同真实性：分页声明与结果可重放边界（2026-08-17）

**提案与证据规则：**工作提案位于 ignored `tmp/codex/contract-truth/proposal.md`。本轮不全量探测；
先按精确 method+path 将 231 条 operation 与持久化 production response sketch、前端直接消费的 wire
字段及合同模板对齐。production 只在真实响应或本趟有界 observation 存在时成立，wire 只在调用点直接
读取分页字段时成立；合同声明不能给自己提升证据等级。完整逐行快照位于
`evidence/forensics/20260817_pagination_contract_audit.{json,md}`，本趟实测与 29 条 receipt 账本位于
`evidence/forensics/20260817_contract_truth.json`。

**231 条离线审计：**派发基线 `f798d39` 精确为 `119 page_info + 112 none`。119 条的最终形状为
**A 59 / B 1 / unknown 59**；证据等级为 **production 62 / wire 8 / template-only 49**。A 只在
`page/page_size/total_number/total_page` 四字段齐全时成立；B 只在精确观察到 total-only 时成立；
其余即使合同写着 `total_page_field` 也保持 unknown。112 条 `none` 逐条复核为：30 条生产响应未见
page_info、46 条 detail/aggregate/mutation 非集合语义、1 条已披露手动空页协议、1 条不可执行 candidate
的 wire 分页信号、34 条集合完整性未知；其中 27 条是 stable+executable 的静默完整性风险，不能写成
“已确认无分页”。这些数字描述的是审计当时的合同声明，不是 HEAD。修正 Multidim（`30c682c`）并把
`app.app_info.get` 计入后，HEAD 当前合同分布为 `118 page_info + 114 none`（232 条）；审计表通过
`declared_kind_disposition` 显式记录 `report.multidim.query` 已从 `page_info` 修成 `none`，当前
kind 由 `reconcile_pagination_audit` 实时读取，不再把快照计数当成 HEAD。

**为什么只实测七条：**`report.multidim.query` 是必修复项；`report.multidim.metric.list`、
`material.report.query`、`report.business.query` 会被正式产品分页层用于完整读取，误判会重复请求；三者
均实测为 A。`report.multidim.media_enum.list`、`material.metric.list`、`promotion.metric.list` 无父对象且
正式调用方把返回值当完整元数据目录，三者最小 probe 均未见 page_info。其余未测项中仍有 59 个
page_info unknown 与 27 个 stable+executable none 集合风险；没有批量探测，因为 page-1 成功或未见
page_info 不能证明服务端永不截断，且部分条目需要敏感父对象或无法构造可证伪 continuation。

**Multidim 修复：**同一输入的 page 1/page 2 都返回 40 行且 SHA-256 相同，page_info 精确只有
`{total:int}`；page_size=10 仍返回 40 行，证明 page/page_size 不控制观察结果。源合同改为
`pagination.kind=none`，保留既有 wire 输入和 response `page_info.total`，删除虚假的 total_page/max
声明；通用 `read_all/read_limited` 因而只发一次 query。新的 `pagination_audit` 判据为
`single_response and returned_items=reported_total`，effective page size 与 has_more 均为 null；只有
行数等于 reported total 时为 complete。标准 A 形状 operation 仍使用原
`has_more=false and returned_items=total_items` 判据，二者不混用。

**结果可重放边界：**原同输入 `total_revenue` 两次差 6.00 的事实成立，但成因仍为 **unknown**。
本趟相同输入三次即时采样在约两秒内稳定；历史单日、T-1 单日与非收入 `ap_show` 各两次短采样也稳定，
但较老的 2026-06-01 收入相对此前较晚观察又增加 185.00，证明变化不只发生在近期日期。三个收入指标
的当前结果不满足 total 等于两个已选分量的简单关系，无法定位到一个分量；一个短时非收入对照也不足以
证明收入类独有。故不猜回填/结算，不声明稳定窗。新增 `report.ap-cost-observation@4`（fingerprint
`aae2b2916ec567dc5c74a626ab18d1c04af9efaf2101b6da890d876ab5ca7503`）保持 v3 成员面，
具体收窄后的 allowed claims 为：

1. `observed-metric-value` 只允许把值写成 scoped to `result.query.fetched_at` 的时点观察，并明确相同
   结构化输入稍后执行不保证相同值；
2. `within-result-comparison` 只允许同一次执行内比较；跨执行降级为两个分别带时间戳的观察与算术差，
   不得称为 replay-equivalent、stable、settled 或 causal。

canonical 编译 bytes 的确定性测试继续保留并扩到 v4；收窄的是结果层，不是编译层。

**生产 HTTP 账本：**实际 **29 / 30**：authentication 1、`report.multidim.metric.list` 7、
`report.multidim.query` 16、`material.report.query` 1、`report.business.query` 1、三个 none 元数据目录各 1。
全部 HTTP 200、attempt 1、retry=false；只有为证明错误分页而显式请求一次 query page 2，没有 page 3+、
扩窗、换 App 或重试。按累计 5 的边界在 sequence 6（原子 metadata+query 跨线）、10、15、20、26
及最终 29 从私有 receipt query 复核；最后 1 次预算主动不用，sequence 29 后无生产请求。

**能力台账：**未新增/删除 operation，故 operation/stable 保持 `231/222`；产品卡 90、selector 329、
动线 `56 = 48 / 1 / 7` 均不变。v4 只是既有语义组合的结果声明版本，不增加上游可回答问题或产品卡。

**最终门禁：**unittest **`1146 + 4 = 1150 tests OK`**；pytest **`1150 passed / 3092 subtests
passed`**，主测试只增不减、subtests 与基线相同。compiler **231 operations / 11 manifests**；quality
PASS（operations/provenance 231/231、operation literals 57）。共享热点没有放宽：`executor.py` AST
ratchet `9099→8912`、`models.py` `8622→8518`，并删除已消失的 `validate_inputs` complexity debt；
500/80/15/0 硬阈值不变。文档 **4 passed**、Agent 指南生成器 `--check`、stable privacy、CLI help 与
`git diff --check` 全过。caller-recoverable 审计保持 **`1225 = A422/B434/C369`**，本线新增 error site
为 **0/0 A**。`src/gravity_sdk` 新增 377 行、tests 新增 123 行，比例 **0.326**，低于三分之一。
没有运行真实 holdout/final/all、读取 key 或修改评测装置/题集/评分；全量测试里的 protected 字样仍只
来自隔离临时目录的 synthetic fixture。没有 GitHub、push、tag 或其他对外动作。

## D28 与公开 App 信息缺失动线（2026-08-17）

**提案与边界：**ignored 提案与静态底稿位于 `tmp/codex/missing-journeys/`。本轮只推进 D28 变现聚合
和 OneLink/公开信息两条读动线；其余五条完全缺失动线未发请求、未改合同或状态。没有上游写、App
切换找数据、日期扩窗、自动翻页、holdout/final/key、评测装置改动或 GitHub 动作。

### D28：真实 wire 与三选一

同一 hash 的三个公开 bundle 重新核验：`NewReportCenter-Dxgo5EkI.js` 为 402,619 bytes / SHA-256
`eb8e91aa591d92271e3b9f0e8b23f371ffa61b18affb63e167735dd37c731f2b`；`api-B9xDXL35.js` 明确把
`X` 绑定 `/turbo_engine/api/v3`、`je` 绑定 `/report/api/v3`；`report-table-DX9hp3vy.js` 为变现分支
提供静态维度清单。结论是：**配置 route 已迁 turbo，主结果 route 没迁。**

| 项目 | 当前 hash-matched 形状 | 旧 SDK / 旧探测差异 |
| --- | --- | --- |
| 指标配置 | `POST /turbo_engine/api/v3/confmetric/metric/list/`，body 为 `page=1/page_size=5000` 与 `data_topic EQUALS(1)`、`is_media EQUALS(1)` 两个 filter | `report.multidim.metric.list` 仍固定旧 `/report/api/v3/...`；旧 route 的拒绝/宽目录不能证明 current config |
| 指标值域 | `is_media=false` 实测 6 个：`reporting_ad_cnt/reporting_ad_ecpm/reporting_ad_ipu/reporting_ad_revenue/reporting_ad_uv/reporting_standard_activate_cnt` | 旧 draft 只猜 `reporting_ad_revenue`，没有 current route 证据 |
| 维度值域 | 静态 `day/os_family/click_company/monetization_platform/user_type/ad_type/app_id/ad_unit_id/bundle_id/channel` | 旧 draft 没记录完整静态来源 |
| 权限 | `POST /turbo_engine/api/v3/confmetric/permission/list/`，当前 role IDs + `data_topic INNERS(6)`；实测成功空，不裁剪字段 | 旧主请求未先核当前 permission；空 permission item 不等于 403 |
| 主结果 | `POST /report/api/v3/monetization_report/custom_get/`，九字段 body，无 query；App 实际必填 | path 与旧 draft 相同，错误在物理值与 filter wire |
| 主 filter | 字符串 `"EQUALS"/"IN"` | metric/permission 的整数 1/6 不能复用；整数主 filter 被明确拒绝 |
| 分页 | bundle 对完整 `data.list` 做客户端 slice；本次空响应另观察到 `data.page_info.total` | D28 未晋升，未来 operation 的分页声明仍须用自己的非空实测，不复制模板 |

主 route 的三次有界参数学习严格保留同一默认窗口和指标/维度：无 App 返回 `code=1004 / 请传入合法的AppID`；
首个合法 App 加整数 operator 返回 `code=1004 / 过滤字段条件不合法`；只把 operator 改为 bundle 原文
`"EQUALS"` 后返回 HTTP 200 / `code=0/msg=成功`，data 完整字段为
`data_dims/extra_data/list/page_info/time_dims/tips/total`，其中 `list=[]`、`page_info.total=0`、
`total={}`、`tips=""`。因此本次三选一是**数据为空**：权限 route 没有拒绝，且参数被协议成功接受；
不是权限不足或形状仍错。这个判定只覆盖首个合法 App 与前端默认 `2026-08-10..2026-08-16`，不能写成
7/7 App 的全租户事实。按“不换 App 找数据”停止，D28 保留 gap；非空 item/total shape 不猜、不登记。

`report.metric.list` 在同 route 原位提升 v3：补前端同形 `filters` 输入并把既有
`exclusion_dims/tag_ids` 从隐藏项改为全部暴露；operation 数不因此增加。新增 permission route 的精确
POST read confirmation 只放行该 path，控制流证据是把返回权限用于本地删减 columns/metrics，权限写入走
独立账号中心控制。

### OneLink 与公开信息

OneLink 的既有稳定父链继续证明当前账号明确空，本轮没有重发，也没有拿空 OneLink 样本补成功合同。
调用方按顺序提供的第 1 条 URL `https://apps.apple.com/cn/app/id414478124` 在唯一一次 GET 即返回
HTTP 200 / `code=0/msg=成功`；按停止条件没有请求第 2 条抖音或第 3 条 Google Play。成功 data 字段为
`app_id/icon_url/image_data/name/package_name/platform/version`；旧 error-shaped 样本的 `error` 也保留
登记。所有八个观察字段全部暴露，没有 `known_omitted`。`image_data` 的合法空字符串与 `icon_url` 的
非空字符串都按原类型返回，不因大小或字段名隐藏。

`app.app_info.get` 晋升 stable v1，分页为自己的实测 `none`；`data.error` 先于投影映射为离散
`semantic_error/INPUT_INVALID`。raw operation 由 CLI `gravity run`、Python SDK `read`、Plan operation
node 与 Agent operation card 共同消费，结果为 `gravity-insight.read.v1` + `gravity.result-source.v1`；
已知 URL 1 次调用，未知 URL 先 Agent 发现再执行共 2 次。J40 原 gap 删除，中英文冻结首问均离线命中
`app.app_info.get`。

### 生产 HTTP 账本与停手

实际 **16 / 40**，OneLink **1 / 3**；全部 HTTP 200、attempt 1、`retry=false`。没有服务端重试、业务
分页、扩窗或换 App；页号只出现在账号/指标/App 目录的唯一 page 1。公开 bundle GET 不计生产业务 HTTP。
每累计 5 条在私有 receipt store 核过 sequence 1--5、6--10、11--15，最后第 16 条单独按 receipt ID
核验。

| # | operation / route | receipt | 结果 |
| ---: | --- | --- | --- |
| 1 | `authentication` POST `/account_center/api/v1/user_login/v2/` | `7a620cf4…` | token 刷新一次 |
| 2--5 | `analysis.account_user.list` GET `/account_center/api/v1/user/list/` | `0e2f9888… / 5a4ee034… / f742b13c… / 411b6287…` | 本地脚本先误读 resolver `/data` 而非 `/result/data`；均 page 1，事实不采用 |
| 6--7 | `report.metric.list` POST current turbo metric route | `ad79272c… / 6e4f4405…` | 第 6 条同样只因本地路径误读丢失值域；第 7 条取得 6 个指标与 A 形 `page_info` |
| 8--9 | `analysis.account_user.list` GET | `fff6a637… / 33f4a5f2…` | 第 8 条证明公司 63 行；第 9 条以 `Gravity_Id → row.id` 唯一匹配 1 个 role；无翻页 |
| 10 | `report.confmetric_permission.list` POST current turbo permission route | `751ead4a…` | `code=0/list=[]/total_number=0` |
| 11 | `report.get.query` POST 主 route | `e354288e…` | 无 App：`请传入合法的AppID` |
| 12 | `app.list` GET | `33309ecc…` | 只取首个合法 App，page 1 |
| 13 | `report.get.query` POST 主 route | `e2fe2163…` | App + 整数 operator：`过滤字段条件不合法` |
| 14 | `app.list` GET | `736a5b25…` | 同一首 App；因上一进程未持久化父值而重复一次，page 1 |
| 15 | `report.get.query` POST 主 route | `f5c5aa2f…` | 字符串 `EQUALS`：协议成功、明确空 |
| 16 | `app.app_info.get` GET `fetch_app_info` | `82c27b18…` | 第 1 条公开 URL 成功非空；OneLink 后两条未发 |

账号目录和 current metric 的重复请求是两处本地结果路径解析错误造成，本可避免；它们全部计入账本，
不改写成重试。证据不足而主动未做三项：D28 不枚举其余 App、不扩日期、不从空 response 猜 item/total；
OneLink 不请求第 2/3 URL；五条明确排除的完全缺失动线 0 请求。

**能力台账：**OneLink/公开信息状态变化一条：`56 = 48 / 1 / 7` → **`56 = 49 / 1 / 6`**；D28
保持完全缺失。`app.app_info.get` 从 draft 晋升为新增 stable operation，故 operation/stable
`231/222 → 232/223`（read `185→186`，mutation 37 不变）。canonical 产品卡因 J40 的同 selector
产品身份 `90→91`，精确 gap `9→8`；扣除 `app.list` 与 `app.app_info.get` 两组卡/raw 同身份后 selector
为 `232 + 91 + 8 - 2 = 329`，没有重复执行入口。

**最终门禁：**unittest **`1150 + 1 = 1151 tests OK`**；pytest **`1151 passed / 3098 subtests
passed`**，均高于 `30c682c` 的 1150 / 3092。compiler **232 operations / 11 manifests**；quality PASS
（operations/provenance 232/232、operation literals 57），quality baseline 未修改或放宽。文档 **4 passed**、
Agent 指南生成器 `--check`、CLI help 与 `git diff --check` 全过。caller-recoverable 审计保持
**`1225 = A422/B434/C369`**，本线新增 error site / A 档为 **0 / 0**；`data.error` 复用现有
manifest semantic error 执行器，不新增 raise site。`src/gravity_sdk` added 162 行、tests added 54 行，
比例 **0.333**，未超过三分之一。技术债清单已复核：本轮只扩数据化 operation 与一个窄 App 产品卡、
删除已解除 gap recognizer，并复用 raw operation 四面，不新增 registry、worker pool、shared-spine router
或活动结构债。公开 development target 只登记 J40 新产品身份；没有改题目、prompt、阈值、评分算法或
holdout/final。全量测试中的 protected 文本只来自隔离临时目录 synthetic fixture；没有读取真实 key 或
sealed 数据，也没有 GitHub、push、PR、tag 或 release 动作。

## 当前 91 卡目录上的合法宿主选择（2026-08-17，不切默认）

**范围：**只在 `codex/host-rescore` 上取得当前目录的合法宿主选择并重放 development。不切默认、不改
recognizer、不改评测装置/题集/评分/层定义/阈值、不放松 `HOST_SELECTION_DECISION_MISMATCH`、不读
holdout/final/key。Gravity 生产 HTTP **0**。选择缓存与重放插件只落在 ignored `tmp/codex/host-rescore/`。

**上次 malformed 归因：**补卡后第二次模型输出有一行把 **1 个候选**标成 `decision=multiple_intents`。
合同 `_validate_decision()` 要求 `len(candidates)==1 → selected`、`>1 → multiple_intents`、`0 →
abstained`；不一致即整批 `HOST_SELECTION_DECISION_MISMATCH`，不部分修正。schema 本身允许三个
decision 枚举，严格点在候选数与 decision 必须一致。这是**模型自相矛盾**，不是合同过严；提示词只写了
“独立多意图才用多个 selector”，没有把“单候选必须写 selected”写成硬约束。本轮不改合同。

**当前目录：**`host_product_catalog()` 现场投影 **99 = 91 product + 8 gap**，
`catalog_sha256=11cef3d9d3c617bccad03e01796aaf208763a76679f425664f87bea4aef311c6`。完整 inventory
仍为 `232 + 91 + 8 - 2 = 329`。含 `app.list` 与 `app.app_info.get`。

**合法选择：**由本轮人工/Grok 按当前目录逐题给出 0..N 候选，336 行全部通过
`assess_host_product_selection`（`selected 324 / multiple_intents 12 / abstained 0`）。缓存
`tmp/codex/host-rescore/host-selection-cache-91card.json`，
`locked_selection_sha256=5917971767247ce09ba4542c8607aa8d6019851a519c72816775e71e846e85c1`。
四 trial 的 locked sha 与 request sha 完全相同；这是**重放确定性，不是模型跨次稳定性**。

**development 实测：**

| 层 | recognizer 默认（本机复测） | 91 卡合法宿主重放 |
| --- | ---: | ---: |
| 首次产品选择 | `256/336` | **`334/336`** |
| 参数可填 | `209/210` | `262/269` |
| 离线终点 | `48/67` | `67/67` |
| 错误恢复 | `5/5` | `5/5` |
| 安全 | `PASS/0` | `PASS/0` |
| selection pass^4 | `256/336` | `334/336` |

宿主失败仍是冻结 scorer 的既有机制限制：`J32.dev.v3.multiple` 与 `J47.dev.v3.multiple` 语义上分别选对
`metadata:table_lineage + CURRENT_TABLE_SCHEMA_PARENT_MISSING` 与
`ANALYSIS_EXPORT_FILE_CONTRACT_MISSING + material.asset.fetch`，但 `candidate_selectors` 只登记产品
journey，按既有逻辑计 `wrong_intent_candidates`。参数层 7 个 `input_template_missing` 全是 J40
`app.app_info.get` 的 `url` 未进 `input_template`；7 个 J19 走环境 gap，不进参数层。

**与 `327/336` 不可比：**旧 327 是补 `app.list` 前、约 90 卡目录上的外部模型选择锁重放；本轮是当前
91 卡目录上的人工/Grok 选择 + 同一锁四次重放。不同模型、不同目录、不同缓存。本轮比 327 多对的是
7 道 J39（现有 `app.list` 卡）和 7 道已闭环 J40（`app.app_info.get`），减去仍失败的 J32/J47。

**recognizer 256 不是本轮回退：**`f798d39` 记的 `260/336` 期望 J40 仍是
`APP_ONELINK_PUBLIC_BINDING_SAMPLE_MISSING`。`0043dba` 把 J40 改成产品后，recognizer 只稳定命中
`J40.dev.zh.normal-1`，其余 6 道 J40 无候选。本轮未改 recognizer。

默认 CLI 不写 `--routing` 仍是 `recognizer` / `mode=discover_and_describe` /
`analysis.query.spec:event`。是否切默认仍只由 custodian 的一次受保护 paired 运行决定；本轮没有查询
受保护集。开发集相对本机 recognizer `+78 / +23.21pp`，安全零回归，但选择锁不是独立模型、也不是
holdout 证据。

**计数与门禁：**operation/stable **232/223**，产品卡 91，精确 gap 8，selector 329，动线
`56 = 49 / 1 / 6`。unittest **1151 tests OK**（无色终端）；带色 help 的 3 个 CLI 断言失败是
`FORCE_COLOR` 环境问题，不是源码回归。pytest **1151 passed / 3098 subtests passed**。compiler
**232 / 11 manifests**；quality PASS operations=232；错误审计 **1225 = A422/B434/C369**；文档 4
passed、skills `--check`、CLI help、`git diff --check` 全过。没有 GitHub、push、tag 或其他对外动作。
## 分页审计分叉与无证据续页（2026-08-17）

**提案：**审计快照不是 HEAD 镜像；`read_all` 在缺 `total_page` 时不得按满页启发式续页。本轮纯离线，
不探测 49 条 template-default 的真实形状。

**审计表形态：**快照标 `relationship.kind=historical_verdict`，`summary.declared_kinds` 改名为
`audit_baseline_declared_kinds`。`report.multidim.query` 保留审计时 `declared_kind=page_info`，并加
`declared_kind_disposition={status:repaired, current_kind:none}`。当前合同 kind 由
`reconcile_pagination_audit` 实时读取；未声明分叉为 `unexpected`，测试必须红。不再用硬编码计数描述
HEAD。选择“历史裁决 + 实时对账”而不是重写整张表，是为了保住 2026-08-17 的形状/证据裁决，同时让
HEAD 合同变化机器可判定。

**续页策略：**缺 `total_page` 时默认停在第一页，`has_more=None`、完整性 `unknown`、
`fetch_strategy=stopped_missing_total_page`。满页启发式只在 `continue_without_total=True` 或
`--continue-without-total` 时启用。理由：默认停页不会在无证据时再发请求，也不会让调用方把第一页当
全集；opt-in 保留旧能力。已证实 A 形状仍走 `total_page` 已知页范围，不受影响。

**次要观察：**playbook 钉 `ap-cost-observation@2` 不算漏迁——v4 按 `(id, version)` 精确取，v2 的
跨执行比较声明仍属于该不可变版本；playbook 比较的是同一次调查里两个窗口，不是跨执行重放。
`schema()["pagination"]` 对 `page_info` 补回 wire 字段；`kind=none` 仍只暴露 kind 与空字段名，避免
通用客户端把 Multidim 的兼容 `page/page_size` 输入当成编排合同。

**能力台账：**operation/stable/产品卡/gap/selector/动线不变：`232 / 223 / 91 / 8 / 329`，
`56 = 49 / 1 / 6`。生产 HTTP 0。错误审计保持 **`1225 = A422/B434/C369`**。

**最终门禁：**unittest **`1151 + 5 = 1156 tests OK`**；pytest **`1156 passed / 3098 subtests
passed`**，主测试只增不减、subtests 与基线相同。compiler **232 operations / 11 manifests**；quality
PASS（operations/provenance 232/232、operation literals 57）。`models.py` AST `8518→8504`、
`OperationSpec.schema` SLOC `102→98` 已收紧；`client.py` AST `6690→6718` 记入 growth ledger，硬顶
6765 未抬。文档、CLI help 与 `git diff --check` 全过。没有 GitHub、push、tag 或其他对外动作。
## D28 租户枚举与非空晋升（2026-08-17）

**提案与边界：**本轮只把 D28 从“单 App/默认窗为空”推进到可判定事实。其余五条完全缺失动线
0 请求。没有写、没有 GitHub、没有改评测题集/holdout/final。

**窗口：**一次使用 `2026-07-17..2026-08-16`（D-31..D-1）。前端默认是 D-7..D-1，且 catalog#1
已在该默认窗明确空；用一个月窗一次打掉“只是默认 7 日切片为空”的假阴性，避免逐日试探烧请求。

**枚举账本：**1 次 `app.list` 取得 7 个可绑定 App，0 个无法解析。每个 App 1 次最小主请求：
`day + monetization_platform + ad_unit_id + reporting_ad_revenue`，App 用字符串 `EQUALS`。
`catalog#1` HTTP 200 / `code=0` / `list=[]/page_info.total=0/total={}`；`catalog#2` HTTP 200 /
`code=0` / `list` 13 行后立即停止，其余 5 个未试。失败、重试、翻页均为 0。

**非空 shape：**item 与 total 均观察 `stat_time:string`、`monetization_platform:string`、
`ad_unit_id:string`，加上请求指标动态列 `reporting_ad_revenue:number`。`data_dims` 回显为
`[stat_time, monetization_platform, ad_unit_id]`，`time_dims` 回显 `"day"`，`extra_data={}`，
`tips=""`。`page_info` 只有 `total:integer=13`，没有 `page/page_size`；bundle 对完整
`data.list` 做客户端 slice。分页因此登记为实测 `none`，不复制模板 `page_info`。

**产品面：**`report.get.query` 从 draft 晋升 stable。CLI `gravity run`、SDK `read`、Plan
operation node 与 Agent 产品卡共用 `gravity-insight.read.v1` + `gravity.result-source.v1`。
App 必填 `EQUALS` filter 走精确 filter profile，不再误走 live metadata 字段校验。已知输入
1 次调用，未知 2 次。

**变现明细导出：**D28 已证明当前租户有变现聚合数据，所以变现明细导出不再能写成“无数据”。
它仍被既有超限/无 task-bound total 的文件合同挡住；本轮不实现拿不到完整样本的导出。

**生产 HTTP：**本轮业务请求计入：`app.list` 3（失败扫描 1、试射 1、全量扫描 1）+
`report.get.query` 4（试射 catalog#1 1、全量 catalog#1/2 各 1、shape 复核 1）。另有 7 次
本地 `InputValidationError` 未出网。认证沿用既有 session。每 5 次从私有 receipt query 核账。

**能力台账：**D28 状态变化一条：`56 = 49 / 1 / 6` → **`56 = 50 / 1 / 5`**。
operation/stable `232/223 → 233/224`（read `186→187`）。产品卡 `91→92`，精确 gap `8→7`；
扣除三组卡/raw 同身份后 selector 仍为 `233 + 92 + 7 - 3 = 329`。


## 分页审计与 D28 并行分支的合并对账（2026-08-17）

`codex/pagination-fix` 与 `codex/d28-data` 同基线并行，都改了
`evidence/forensics/20260817_pagination_contract_audit.{json,md}` 与
`tests/test_pagination_contract_audit.py`。合并按"结构取分页修复、事实取 D28"解冲突：

- 保留 `relationship.kind=historical_verdict` 与 `summary.audit_baseline_declared_kinds`
  改名，删掉 D28 重新引入的 `summary.declared_kinds`（当前 kind 一律由
  `reconcile_pagination_audit` 实时算，不落 HEAD 事实进快照）。
- D28 追加的第 233 条 `report.get.query`（实测 B、声明 `none`、自带生产 probe 证据）保留，
  基线口径同步 `none 113 → 114`，与记录逐条统计一致。
- 测试保留 `assertEqual(len(current), len(records))` 的实时对账形态，不回退成硬编码 233。
- `technical-debt.md` 里"112 条当时的 `none`"这个两边不一致的派生数删掉，保留其承载的事实
  （27 条 stable+executable 集合完整性未知）。合并后实测：审计记录 233 = 当前 operation 233，
  `missing_from_audit`/`missing_from_contracts` 均空，`unexpected_kind_drift` 空，
  `shape_unproven` 49，HEAD 当前 `118 page_info + 115 none`。

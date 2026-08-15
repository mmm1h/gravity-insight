# 32 条已闭环动线对抗式复核

## 结论

- **32 条中，达标声明现在不成立：0 条。** 在本单元允许的离线证据边界内，32 条均通过四面入口、versioned envelope、三态区分、未知字段 fail-closed 和调用次数合同复核。
- **坐实缺陷：1 条，严重度为“文档与实现不一致”。** `docs/analysis-journeys.md:77` 在 Issue 19 的 Plan 面写了第二处“设计不适用”，直接违反 `docs/roadmap.md:368` 的“当前只有导出的 Plan 面适用此例外”。它没有把 Issue 19 算作闭环，因此不推翻 32 条中的任何一条，但全局判据 6 不成立。
- **9 条 `1 / 2`：离线实现路径均成立。** 七条 live catalog 在第一次 resolver 调用中返回 `complete=true`，对应 scenario 实测为 `minimum_calls=2 / discovery_calls=0`；两条冷目录路径只有全源成功才原子发布，失败保留旧目录。当前生产租户是否恰能完成本次在线目录读取，因 0 HTTP 约束未实测。
- 台账可复算：50 个表格行 = 48 个产品动线 + 2 个不计数便利面；48 = 32 已闭环 + 0 部分闭环 + 16 完全缺失。title-package 与 D32 分属两行，未再发生 off-by-one。
- roadmap 与台账除“第二处设计不适用”外，未发现状态、阻塞或调用次数矛盾。2 条兼容/维护便利面确实未进入 48 条产品分母。

## 复现入口与判定缩写

总验命令（假 transport 对任何 HTTP 调用直接抛错）：

```powershell
$env:PYTHONPATH='D:\git-pjt\wt-closure-audit\src'
python tmp/codex/closure-audit/offline_audit.py
```

脚本输出逐条证明：CLI `--help` 退出 0、公开 SDK 方法存在、Plan preflight 为 `validated/dry_run=true`、Agent candidate 可离线列举、向 Plan request 注入 `__audit_unknown` 会被拒，并复算台账。实现位置见 `tmp/codex/closure-audit/offline_audit.py:350`、`:385`、`:419`、`:454`、`:478`、`:509`、`:561`。

判定缩写：`1✓ C/S/P/A` = CLI / SDK / Plan / Agent 四面均实测；`2✓` = 返回合同有 `schema_version`；`3✓` = empty / partial failure / capability_gap 可区分；`4✓` = 未登记请求或响应字段被拒绝、隔离或默认隐藏；`5✓ 1/2` = `gravity.agent-call-bound.v1` 的已知/未知能力调用数成立；`6—` = 本行未使用例外。`6✓窄例外` 只表示导出本行满足 roadmap 三条件，不抵消全局扫描发现的第二处文字例外。

## 32 条逐条结论

| 动线 | 判据 1..6 逐项结论 | 缺陷严重度 | 证据（命令/文件:行） |
| --- | --- | --- | --- |
| 看某事件随时间、分组和条件的变化 | 1✓ C/S/P/A；2✓；3✓（多 App partial 保留）；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/sdk_analysis.py:226`；`src/gravity_sdk/plan_analysis_adapter.py:27`；`tests/test_gravity_analysis_query_batch.py:182`、`:210` |
| 看多步行为的转化漏斗 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/agent_analysis.py:80`；`src/gravity_sdk/plan_analysis_adapter.py:27`；`tests/test_gravity_analysis_query_batch.py:140`、`:182` |
| 看起始行为后的用户留存 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/sdk_analysis.py:226`；`tests/test_gravity_analysis_query_batch.py:140`、`:210` |
| 看用户或事件属性的分布与聚合 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/agent_analysis.py:80`；`src/gravity_sdk/plan_analysis_adapter.py:80`；`tests/test_gravity_analysis_query_batch.py:182` |
| 看事件指标之间的散点关系 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/sdk_analysis.py:226`；`src/gravity_sdk/plan_analysis_adapter.py:80`；`tests/test_gravity_analysis_query_batch.py:140` |
| 用同一分析定义比较两个时期 | 1✓ C/S/P/A；2✓；3✓（empty/partial/capability_gap 分支独立）；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/analysis_period_compare.py:16`、`:114`、`:125`；`tests/test_gravity_analysis_period_compare.py:63`、`:79` |
| 评估一组人群规则命中的人数与占比 | 1✓ C/S/P/A；2✓；3✓；4✓（closed spec）；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/plan_segment_adapter.py:25`、`:53`；`src/gravity_sdk/segment_spec.py:30`；`tests/test_gravity_segment_spec.py:136` |
| 一次取得构造分析所需的事件、属性、指标和模板上下文 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/analysis_context.py:21`、`:75`、`:106`；`tests/test_gravity_capability_deepening.py:53` |
| 一次查看 App 的容量、角色、权限菜单和实时事件治理快照 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/app_snapshot.py:22`、`:52`、`:128`；`tests/test_gravity_capability_deepening.py:53` |
| 一次查看 App 已登记的归因配置、映射与回溯设置 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/attribution.py:24`、`:51`、`:90`；`tests/test_gravity_attribution_snapshot.py:76`、`:129` |
| 查看单个用户某日的画像、事件时间线和回传记录 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/user_journey.py:22`、`:75`、`:122`；`tests/test_gravity_user_journey.py:84` |
| 汇总多个 App 的业务趋势和小时脉搏 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/business_pulse.py:29`、`:75`、`:142`；`tests/test_gravity_business_pulse.py:39` |
| 查看公司资源用量趋势 | 1✓ C/S/P/A；2✓；3✓（empty 与 bounded partial 独立）；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/company_usage.py:22`、`:34`、`:92`；`tests/test_gravity_company_usage.py:69`、`:107`、`:129` |
| 查看自定义人群覆盖与状态 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/custom_audience.py:22`、`:37`、`:209`；`tests/test_gravity_custom_audience.py:104` |
| 比较已支持平台的素材表现 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/material_performance.py:37`；`src/gravity_sdk/material_performance_result.py:137`、`:163`；`tests/test_gravity_material_performance.py:105`、`:166` |
| 读取单日无标识订单目录 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/order_directory_result.py:27`；`tests/test_gravity_order_directory.py:193`、`:223`、`:266` |
| 按 TraceID 追踪单日订单拆单结果 | 1✓ C/S/P/A；2✓；3✓；4✓（安全行必须精确四字段）；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/order_trace_result.py:14`、`:446`；`tests/test_gravity_order_trace.py:147`、`:163` |
| 读取单日无标识变现明细（D27） | 1✓ C/S/P/A；2✓；3✓；4✓（批准字段交集）；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/monetization_detail.py:33`、`:70`、`:183`；`tests/test_gravity_monetization_detail.py:111` |
| 执行 workspace 登记的聚合 SQL 分析产品 | 1✓ C/S/P/A；2✓；3✓（batch partial 与结果 row_count 可判空）；4✓（固定输出投影、未知请求字段拒绝）；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/sql/query.py:20`、`:84`、`:86`、`:248`；`src/gravity_sdk/sql/products.py:129`、`:169`；`tests/test_sql_products.py:98`、`:261` |
| 查看看板详情、成员和筛选收藏 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（首次完整 tree，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/dashboard_snapshot.py:34`、`:178`；`src/gravity_sdk/agent_input_catalogs.py:91`；`tests/test_gravity_dashboard_snapshot.py:76`、`:84` |
| 忠实重放看板图表及页面条件（D22） | 1✓ C/S/P/A；2✓；3✓；4✓（非空 page filter 继续拒绝）；5✓ 1/2（首次完整 tree，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/dashboard_analysis.py:43`、`:215`、`:436`；`src/gravity_sdk/agent_input_catalogs.py:91`；`tests/test_gravity_dashboard_analysis.py:99`、`:144` |
| 按精确引用重放保存分析 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（read_all + complete receipt + id，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/saved_analysis.py:56`、`:57`；`src/gravity_sdk/saved_analysis_catalog.py:45`、`:54`、`:60`；`tests/test_gravity_saved_analysis.py:160`、`:199` |
| 按精确引用重放分析模板 | 1✓ C/S/P/A；2✓；3✓（unsupported artifact 为 capability_gap）；4✓；5✓ 1/2（三 scope 全成功 + scope/id，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/template_replay.py:39`、`:41`、`:43`、`:261`、`:312`；`tests/test_gravity_analysis_template_replay.py:176` |
| 查看分群详情、版本和单日聚合结果 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（完整分页、去重、App 绑定、id，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/segment_snapshot.py:43`；`src/gravity_sdk/agent_input_catalogs.py:133`；`tests/test_gravity_segment_snapshot.py:84`、`:109` |
| 用显式物理维度、指标和筛选读取多维报表 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（8 个 metadata 组件完整，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/plan_multidim_result.py:20`、`:188`；`src/gravity_sdk/agent_input_catalogs.py:166`；`tests/test_gravity_multidim_product.py:58`、`:174` |
| 按平台和物理指标读取推广表现 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（已知平台逐个平台完整 metric catalog，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/promotion_performance_result.py:27`、`:251`、`:297`；`src/gravity_sdk/agent_input_catalogs.py:180`；`tests/test_gravity_promotion_performance.py:212`、`:283` |
| 查看 B 站账户/产品投放表现 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/bilibili_account_performance_result.py:26`、`:66`；`tests/test_gravity_bilibili_account_performance.py:150` |
| 读取巨量广告主消耗、余额、预算模式和状态 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/advertiser_profile.py:23`、`:38`、`:218`；`tests/test_gravity_advertiser_profile.py:102` |
| 读取巨量普通/标准标题包的标题数、计划数与成本表现 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2；6— | 无 | 总验命令；`src/gravity_sdk/title_package.py:22`、`:108`、`:303`；`tests/test_gravity_title_package.py:123` |
| 离线查找可用于分析的事件、属性、指标和模板名称 | 1✓ C/S/P/A；2✓；3✓（缺库/partial/结果为空分开）；4✓；5✓ 1/2（全源成功才原子替换，refreshed scenario 2/0）；6— | 无 | 总验命令；`src/gravity_sdk/find_metadata.py:21`；`src/gravity_sdk/agent_catalog_refresh.py:13`、`:39`；`src/gravity_sdk/agent_input_resolution.py:326`；`tests/test_gravity_metadata_sync.py:338`、`:356` |
| 查询已同步的数据表版本与变更观察 | 1✓ C/S/P/A；2✓；3✓；4✓；5✓ 1/2（lineage 全源 read_all 成功才发布，2/0）；6— | 无 | 总验命令；`src/gravity_sdk/metadata_lineage.py:27`、`:183`；`src/gravity_sdk/agent_input_resolution.py:326`；`tests/test_gravity_metadata_sync.py:385`、`:415` |
| 创建、轮询并下载素材分析报表 | 1✓ C/S/A，P=设计不适用且三条件成立；2✓；3✓；4✓；5✓ 1/2（卡后一次 `export run`）；6✓窄例外 | 无（本行） | 总验命令；`src/gravity_sdk/sdk.py:192`；`src/gravity_sdk/export_client.py:375`、`:436`；`docs/roadmap.md:340`、`:359`；`tests/test_gravity_export.py:116` |

## 九条 `1 / 2` 的完整目录复核

| 动线 | 第一次调用结论 | 完整性闸门 | 调用边界结论 |
| --- | --- | --- | --- |
| 看板控制面 | 是（离线控制流实测）；完整 Dashboard tree，要求稳定 `id` | tree 身份提取受 `MAX_CATALOG_ITEMS` 限制，形状漂移报错 | resolved scenario = `2 / 0` |
| 看板图表重放 | 是；与控制面复用同一完整 tree | 第二次仍 live resolve；删除/歧义 fail-closed | `2 / 0` |
| 保存分析重放 | 是；`read_all=True`，并要求 `truncated=false`/无 continuation，选择字段 `id` | App 身份与目录完整性复验 | `2 / 0` |
| 分析模板重放 | 是；own/share/internal 三 scope 全读，选择字段 `scope + id` | 任一 scope 失败使 catalog 非 success，resolver 停止 | `2 / 0` |
| 分群快照 | 是；完整分页读取，去重且核对 App，选择字段 `id` | 重复身份/App 错绑/形状漂移均失败 | `2 / 0` |
| Multidim | 是；当前 8 个 `MULTIDIM_METADATA_OPERATIONS` 全部返回且 batch 基数必须精确 | 任一组件非 success/empty、truncated 或 continuation 均失败 | `2 / 0` |
| Promotion Performance | 是；对调用方已知的每个平台各读取一份完整 metric catalog | 平台标准化、batch 基数、每组件终态均校验；第二次逐平台 live 复验 | `2 / 0` |
| metadata search 冷目录 | 是（完成原子 refresh，而非把有限搜索结果冒充完整目录） | staging 只在全部 source `ok=true/status=success` 时 durable replace；partial 保留旧库 | `catalog_refreshed = 2 / 0` |
| table lineage 冷目录 | 是；同一原子 refresh 显式 `include_table_lineage=true`，所有 lineage source `read_all` | lineage 任一 source 失败不发布，旧目录保持 | `catalog_refreshed = 2 / 0` |

七条 live 路径的统一复现位于 `tmp/codex/closure-audit/offline_audit.py:561`，实现位于 `src/gravity_sdk/agent_input_catalogs.py:41`、`src/gravity_sdk/agent_input_resolution.py:351`。两条原子刷新路径由 `tests/test_gravity_metadata_sync.py:338`、`:385`、`:415` 实测。

重要限制：以上结论证明的是**当前仓库会读取完整目录，否则 fail-closed，且卡面会正确降为 2/0**。没有 revision/ETag，无法离线证明上游永不复用稳定 ID；这一限制已由 `docs/maintainers/technical-debt.md:51` 登记。也没有在本单元发生产 HTTP 来证明某个当前租户本次一定能完成目录读取。

## 坐实缺陷与复现命令

| 动线 | 判据 1..6 逐项结论 | 缺陷严重度 | 证据（命令/文件:行） |
| --- | --- | --- | --- |
| 全局例外扫描 / Issue 19 精确素材预览下载 | 判据 6 失败：台账存在第二处 `设计不适用`；Issue 19 虽为完全缺失、未借此冒充闭环，但用词已经把唯一例外扩成第二处；roadmap 又断言当前只有导出 | **文档与实现不一致** | `docs/analysis-journeys.md:59`、`:77`；`docs/roadmap.md:359`、`:368`。复现见下方两条命令 |

```powershell
rg -n "设计不适用" docs/analysis-journeys.md
rg -n "当前只有导出的 Plan 面适用此例外" docs/roadmap.md
```

期望第一条只有导出行；实际返回导出和 Issue 19 两行。第二条仍声明唯一例外。该发现已坐实，不是疑似。

## 计数、roadmap 与便利面交叉检查

- 表格实际 50 行：`32 已闭环 + 16 完全缺失 + 1 legacy 兼容面 + 1 SDK 便利面`。
- 产品分母排除后：`50 - 2 = 48`；状态复算为 `48 = 32 + 0 + 16`。
- `docs/analysis-journeys.md:56` 的 title-package 是独立闭环产品；D32 保持 `docs/analysis-journeys.md:75` 的完全缺失，归属正确。
- `docs/analysis-journeys.md:60`、`:61` 两条状态均明确为“不计独立动线”，与 `docs/roadmap.md:16`、`:17` 一致。
- roadmap 与台账的 9 条在线解析前提一致：App/平台及其余业务输入须已知；App/平台也未知时仍按更高 scenario 下界，不把台账 `1 / 2` 外延。

## 未验证与不确定项

- 没有哪一条在允许的离线范围内“整条验不动”；32 条均完成了 CLI/SDK/Plan/Agent、schema、三态、fail-closed 和 call-bound 的离线验证。
- **离线验不了（跨 32 条的外部事实）**：当前生产上游是否已漂移、当前租户是否能成功读完 live catalog、真实分页是否会触顶、稳定 ID 是否从未复用。这些需要生产 HTTP 或上游 revision/ETag，均未猜测为通过。
- 结果三态与未知字段使用合成响应、冻结合同和测试验证，没有拿生产响应值复验；这是 0 HTTP 范围的证据边界，不是生产探测结论。
- 未发现新的用户级/设备级字段，因此本单元没有新增 `known_omitted` 清单，也没有作任何隐私批准。

## 验证记录与 HTTP 账本

- 环境自检：`D:\git-pjt\wt-closure-audit\src\gravity_sdk\__init__.py`。
- 定向复核：`212 passed, 367 subtests passed`。
- 全量 unittest：`Ran 789 tests`，`OK`。
- 全量 pytest：`1025 passed, 2547 subtests passed`。
- quality：`PASS gravity-insight-quality: operations=185, provenance=185, operation_literals=57 (ratcheted)`。
- **生产 HTTP 请求：0 次。** operation、HTTP 状态、重试、翻页、扩窗均无条目。

## 未做的部分

- 未修改任何 `src/`、`tests/`、`docs/`、契约 JSON 或 baseline；第二处例外只登记，未修。
- 未进行生产 `--resolve-inputs`、真实导出、真实 SQL/Insight 查询或任何 probe，因为本单元明确要求 0 生产 HTTP。
- 未访问 GitHub、未 push、未开 PR、未改 issue/tag。

# 信封顶层 `next` 必须跟 gap 自己走

- 日期：2026-08-19
- 任务：#216
- 结论：`discovery_next_fields` 不再只给 `UNRANKED_OPERATIONS` 开特例；信封顶层从第一个 gap 对象抄 `next_action` / `next`，没有具体下一步才回落到「去目录确认不存在」。

## 确凿事实

### 请求与响应（离线，`GravityInsightClient.from_env()`，读 0 次）

| gap code | 触发问法 | gap 自带下一步 | 修前信封顶层 | 修后信封顶层 | 修前是否矛盾 |
| --- | --- | --- | --- | --- | --- |
| `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING` | `导出分析结果` | `export list-capabilities` | `agent-catalog categories` +「确认能力不存在」 | 与 gap 相同 | 是：七个可调族被说成不存在 |
| `CURRENT_TABLE_SCHEMA_PARENT_MISSING` | `current table schema` | `metadata sync --all-apps --include-table-lineage` | 同上 | 与 gap 相同 | 是：有同步命令仍被说成不存在 |
| `WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED` | `registered sql analysis product` | `sql products` | 同上 | 与 gap 相同 | 是：有产品列举命令仍被说成不存在 |
| `DERIVED_METRIC_BINDING_REQUIRED` | `orion rate`（空 workspace） | `derive --input <request.json>` | 同上 | 与 gap 相同 | 是：有绑定入口仍被说成不存在 |
| `MEDIA_REPORT_ITEM_SCHEMA_MISSING` | `media reports` | 文案：换有媒体报表的租户再打第一页；无 argv | 通用浏览 | 只用 gap 文案，不发明 argv | 是：租户空样本被说成能力不存在 |
| `NON_BYTEDANCE_HIERARCHY_PARENT_MISSING` | `non bytedance campaign group creative performance` | 文案：打腾讯广告组 list，勿发明快手 schema；无 argv | 通用浏览 | 只用 gap 文案 | 是：有具名读路径仍被说成不存在 |
| `PLATFORM_SPECIFIC_CREATIVE_CONTRACT_MISSING` | `platform specific creative fields` | 文案：打腾讯素材 list；无 argv | 通用浏览 | 只用 gap 文案 | 是：同上 |
| `MULTIPLE_INTENTS` | `event analysis analysis context` | 文案：对每个 selector 再 `agent --input`；无 argv | 通用浏览 | 只用 gap 文案 | 是：两个已识别产品被说成不存在 |
| `SEMANTIC_CONTEXT_TARGET_REJECTED` / `SEMANTIC_CONTEXT_EXCLUDED` | `nebula rollup users` / `archived nebula rollup` | 文案：去掉冲突或澄清；无 argv | 通用浏览 | 只用 gap 文案 | 是：语义拒绝被说成能力不存在 |
| 产品边界（无 code） | `monetization details summary` 等 6 条 | 文案：confirmed product-boundary，不要去浏览替代 raw；无 argv | 通用浏览（与「不要浏览」相反） | 只用 gap 文案 | 文案相反，但下一步都不是可执行产品 |
| `NO_CANDIDATE` | `utterly unrelated quantum weather` | 通用浏览 | 通用浏览 | 不变 | 否 |
| `UNRANKED_OPERATIONS` | `排那位用户当天的时间线和回传` | `agent-catalog host` | 同 gap | 同 gap | 否 |
| `draft_capability_gap` | `promotion.alipay.campaign.list` | 无 `next_action` / 无 `next` | 通用浏览 | 仍通用浏览 | 否：draft 本身没有可执行下一步 |
| 有候选 | `event analysis` | （信封无 `next`） | `Prefer a recipe…` | 不变 | 否 |

宿主臂 `HOST_PRODUCT_SELECTION_EMPTY` 只对照、未改：gap 与信封本来都指向 `agent-catalog categories`。

### argv 体检（离线 `build_parser().parse_args` / `sql.build_parser`）

| argv | 分类 |
| --- | --- |
| `gravity export list-capabilities` | 有效且能推进（离线列出七族） |
| `gravity metadata sync --all-apps --include-table-lineage` | 有效（`network_required=True`，本趟未打生产） |
| `gravity sql products` | 有效且能推进（离线产品合同） |
| `gravity derive --input <request.json>` | 有效但要输入；占位符换成文件名即可 parse |
| `gravity agent-catalog categories` / `host` / `category <domain>` / `describe <selector>` | 有效；categories 对「能力其实存在」的具名 gap 是误导，对 `NO_CANDIDATE` 正确 |
| `gravity plan run --input <plan.json>` | 有效命令（#212 仍挂在产品卡上，不是幽灵子命令） |
| `gravity operations describe <selector>` | 有效 |
| `gravity run app.list` | 有效 |

#212：`agent-catalog describe analysis.query.spec:event` 的**信封**没有 `next.argv`；`plan run` 只在卡片 `capability.next.argv`。`plan run --input dummy-plan.json` 能 parse。本趟不改产品卡交接合同；describe 信封继续写「本命令不执行」，不把 `plan run` 抬到顶层。

### 代码改动

- `discovery_next_fields`：有候选仍返回原来的 recipe 偏好文案；无候选时从第一个 gap 抄 `next_action` / `next.argv`；只有 gap 自己没有 `next_action` 才回落通用浏览。不再 `if code == UNRANKED_OPERATIONS`。
- `agent-catalog describe`：gap 选择器走同一条抄字段逻辑；产品卡信封仍不带 `next`。

未改：`agent_host_selection.py`、`agent.py` 调用点、投影合同、评测装置、`docs/roadmap.md`。生产请求 0 次。

### 测试红→绿

| 测试 | 红 | 绿 |
| --- | --- | --- |
| `test_named_gap_next_is_copied_onto_the_envelope` | 信封仍是「确认不存在」 | `Ran 9 tests … OK` |
| `test_export_discovery_envelope_uses_the_named_gap_argv` | `export list-capabilities` ≠ `agent-catalog categories` | 同上 |
| `test_specific_action_without_argv_does_not_invent_browse_next` | 多意图被盖成通用浏览 | 同上 |
| `test_named_gap_describe_envelope_keeps_the_gap_argv` | `KeyError: 'next'`（describe 信封无 `next`） | `Ran 3 tests … OK` |
| 无具体下一步 / UNRANKED / 有候选 | 修前即绿，修后仍绿 | 保留 |

unittest discover：`Ran 1244 tests`（基线 1233 + 本趟 11）。其中 3 条 `--help` 断言被本机 argparse ANSI 颜色码绊住（`usage:` 前有 `\x1b[1;34m`），与本趟文件无关。pytest：`1241 passed, 3 failed`，失败是同一 3 条。

### 评测（只跑 development）

| 层 | 改前 | 改后 |
| --- | ---: | ---: |
| Product selection | 277/336 | 277/336 |
| Parameter fillability | 225/238 | 225/238 |
| End-to-end offline terminal | 44/53 | 44/53 |
| Error recovery | 5/5 | 5/5 |

选择层未动：评测只对 gap **code** 和 gap 自己的 `next_action` 是否非空打分，不读信封顶层 `next.argv`。

质量门禁：`PASS … operation_literals=57 (ratcheted)`。未改 `quality-baseline.json`，无 `hard_limit` / `threshold` / `max_` 变动。`client.py` 未碰。错误审计数字未变，C 仍为 0。

## 推测

- 评测题集里宽导出问法仍期待 `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`；信封下一步变了，code 没变，所以 277/336 不动。若将来把「信封顶层 argv 是否可执行」纳入评分，选择层以外的终端层才可能动。
- `draft_capability_gap` 继续落到通用浏览，是因为 draft 对象没有 `next_action`。给 draft 补可执行下一步不在本趟范围。

## 动线台账

只在「导出事件、分群、用户、付费或变现分析结果」行补了一句信封对齐证据。**状态列未改**（仍为部分闭环）。表头 `56 = …` 未改。冻结 case 仍期待同一 gap code，对得上。

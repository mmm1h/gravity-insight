> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 上游拒绝可自纠

- 日期：2026-08-18
- 任务：#208
- 结论：上游拒绝现在给出 `field=` / `next_action` / `remedy`，不回传未审查的 `extra.error`；漏斗合同声明只返回人数、不代算转化率。

全部在 App `29034827`。窗口 `2026-08-10..2026-08-16`。只写关系，不写业务数字。

## 发请求前写下的预期

| ID | 事先预期 | 依据 | 不成立说明什么 |
|---|---|---|---|
| E1 | 省略留存 `create_time` 分组会 HTTP 200 + 非空 `extra.error` | #206 对账 | 编译器已默认写入，或上游改了必填 |
| E2 | compact `group_by.source=user` 被改成 wire `type=user_property` 会拒 | #206 对账 | 上游已接受 `user_property` |
| E3 | 同一 wire 用 `type=user` 会成功 | #206 对账 | 分维类型不是拒因 |
| E4 | 漏斗响应无转化率字段 | #206 F3 | 上游开始返率 |
| E5 | 仓库旧 evidence 几乎没有 `extra.error` 原文 | 2026-08-16 审计：787 份旧 evidence 原值为 0 | 本仓其实已有可枚举样本 |

## 确凿事实

### 仓库里已有的 `extra.error` 样本（动手前）

| 来源 | 原文 | 含义 |
|---|---|---|
| attribution committed evidence | `无数据` | 成功码下的明确空，不是拒绝 |
| F41 `metadata.data_table.detail` | `table_id not exist` | 历史 table_id 不是活表 |
| dimension-table 调研 | `prop_list is empty` | 写面，不在本批范围 |
| 787 份旧 probe evidence | 0 个原文 | 只存了规则路径 |

因此映射表不能凭空造。本趟只收录本账号在投放中 App 上复现的拒绝句。

### 本趟生产采样（读 8 / 预算 20，写 0）

产品读 8 次，全部 `29034827`。metadata 预取由 FieldPolicy 触发，不另计产品读。

| # | 形状 | HTTP / code / msg | extra.error | SDK 调用方看到的 |
|---|---|---|---|---|
| 1 | 留存，`group_by_list=[]`（剥掉编译器写入的 `create_time/day`） | 200 / 1004 / 参数错误 | `入参错误：group_by_list为list且不能为空` | `field=group_by_list`，补 `create_time/day` |
| 2 | 留存，`$os` 分维但无 `create_time` | 200 / 1004 / 参数错误 | `入参错误：group_by_list缺失create_time` + 调用方分组 JSON | `field=group_by_list`，补 `create_time/day`；**不回传**嵌入的 `$os` |
| 3 | 留存，`create_time/day` + `type=user_property` `$os` | 200 / 1004 / 参数错误 | `groupBy类型(user_property)不合法` | `field=group_by_list[].type`，改 `type=user` |
| 4 | 漏斗，`type=user_property` `$os` | 同上 | 同上（哈希相同） | 同上 |
| 5 | 事件，`type=user_property` `$os` | 同上 | 同上 | 同上 |
| 6 | 漏斗，`type=user_property` `$os` 再打一次 | 同上 | 同上 | 同上 |
| 7 | 漏斗，`type=event` `$carrier` | 200 / 0 / 成功 | 空 | 成功；#206 记的「事件属性当分维被拒」在本窗不成立 |
| 8 | 留存，`create_time/day` 对照 | 200 / 0 / 成功 | 空 | 成功 |

未试形状：权限拒绝、未知事件名、非法日期、非 analysis 域。那些没有本趟复现，不进映射。

### 调用方面

命中审查过的精确句或前缀 → 本仓写的 `field` + `next_action`。  
未命中 → 固定句 `Gravity rejected the read operation`，附本仓已掌握的 `operation`、`field`、`sent_keys`。  
两种路径都不把上游句子拷进 `message` / `next_action`。`C=0` 保持。

### 漏斗合同

`analysis.funnel.query` 描述、`analysis_query_spec_schema()["kind_schemas"]["funnel"].notes`、Agent 产品卡、CLI/SDK/Plan/agent-workflow 均声明：

- 上游 `window_funnel_mode=4` 只返回各步人数，不返回转化率。
- 人数 = 该步及之前每步都完成的有序子集。
- 自算率必须先选定分母：相对上一步 `step_n / step_{n-1}`，相对第一步 `step_n / step_1`；三步及以上两种口径不同。
- SDK 不代算、不插入率字段。

## 推测（不是事实）

- #206 记的「漏斗带事件属性 `$carrier` 当分维被拒」可能当时混进了 `user_property` 分组，或换过事件。本窗 `type=event` `$carrier` 成功。
- 前缀映射只覆盖「缺失 create_time」这一句的固定开头。若上游改措辞，会退回未分类通道，而不是猜。

## 生产请求预算

产品读 **8**，写 **0**。未碰实时事件、导出、resolver、agent 路由、metadata 预取策略。

## 修了什么

1. `semantic_rejection.py`：受审查映射 + 未命中时的结构化上下文。
2. `semantic_status.enforce_semantic_rules` 把 request inputs 传给分类器。
3. 漏斗合同 / spec-schema notes / 产品卡 / 参考文档声明不返回率。
4. 可执行错误库存 `1265 = A890 / B375 / C0` → `1266 = A891 / B375 / C0`。新增 1 条 A。

## 验证

`NO_COLOR=1`：unittest **1225** OK（基线 1220 + 本趟 5）；pytest **1225 passed** / 3141 subtests；compiler check 236；quality PASS，`quality-baseline.json` 只把 `executor.py` 的 `ast_nodes` 从 4795 收到 4797 并记账，无 `hard_limit` / `threshold` / `max_` 改动。`client.py` 未改。生产产品读 8，写 0。

## 没修什么

- 未审查的上游句子仍不进调用方面。
- 合计留存行多一个占位槽：未动。
- 导出面、resolver 分页、agent 路由、metadata 预取：未动。
- `docs/roadmap.md`：未读未写。

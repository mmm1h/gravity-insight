> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 导出宽问法：不建 dispatcher

- 日期：2026-08-18
- 任务：#export-wide（工作目录 `wt-export-wide`，分支 `grok/export-wide`，基线 `dev@9912b26`）
- 结论：宽问法返回 gap 是正确设计，不建统一导出 dispatcher；只把台账「六个具体卡」改成「七个」。

## 确凿事实

本轮 **0 次生产请求**。七个子类 shape 已有既有实测证据，本轮只读合同与离线发现。

### 服务端子类（`export.analysis.*.start`）

离线读取 `src/gravity_sdk/contracts/exports/routes-v1.json`，经
`ExportContractRegistry` 核对：

| operation_id | contract_status | currently_callable | 必填输入（不可互换） |
| --- | --- | --- | --- |
| `export.analysis.user_event.start` | verified | true | `app_id`, `client_id`, `desc`, `group_by`, `event_list`, `date_list`, `page_info`, `query_item_list`, `task_name` |
| `export.analysis.segment.result.start` | verified | true | `app_id`, `segment_id`, `version_id`, `task_name` |
| `export.analysis.segment_user_detail.start` | verified | true | `field_map`, `task_name`, `app_id`, `tmp_segment_id`, `segment_id` |
| `export.analysis.user_detail.start` | verified | true | `app_id`, `field_map`, `task_name`, `global_conditions`, `postback_conditions`, `user_cond_logic`, `postback_cond_logic` |
| `export.analysis.pay_event.start` | verified | true | `app_id`, `field_map`, `global_conditions`, `order_conditions`, `user_cond_logic`, `order_cond_logic`, `task_name` |
| `export.analysis.monetization_detail.start` | verified | true | `app_id`, `field_map`, `global_conditions`, `local_conditions`, `task_name` |
| `export.analysis.origin_event.start` | verified | true | `app_id`, `task_name`, `task_type`, `time_range`, `event_name_list`, `cond_logic`, `conditions`（提交前须正数 evaluate） |
| `export.analysis.stream_event.start` | `not_applicable` | false | 前端无服务端请求；不计入可调子类 |

可调服务端子类是 **7**，不是 6。`origin_event` 已由 #178（2026-08-17）补上。
`stream_event` 按既有判定不计入。

统一执行入口已经存在：`gravity export run <operation_id>`，七张具体卡各自带着自己的
`input_schema`。本仓没有、也不需要再叠一层 `family` 参数把七份合同合成一份。

### 宽问法离线发现

`discover_capabilities("导出事件、分群、用户、付费或变现分析结果。")` 与对应英文首问均返回：

- `status=capability_gap`
- `code=ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`
- `next.argv=["gravity", "export", "list-capabilities"]`

精确别名（`导出用户事件`、`分群结果导出`、`原始事件导出`、`变现明细导出`）不走这条
gap，各自命中对应 `export.analysis.*.start` 卡。这是既有测试
`tests/test_gravity_insight_agent_ux.py` 已覆盖的路径。

### 既有范式

- **一动作多子类**：本仓处理方式是「各自一张卡 + 精确别名」，不是猜一个
  dispatcher。素材导出（J33）是单产品，所以宽问法能直接给卡；Analysis 导出是
  七个不可互换合同，没有单产品可猜。
- **真实歧义**：`MULTIPLE_INTENTS` 只用于「同时做两件不同产品」的并列问法
  （协调词 `and` / `以及` / `同时`），要求调用方拆开再发现。它不是「同一动作
  多个子类请选一个」的补全面。
- **待填写节点**：用于**已选定产品**后补 App/日期/平台等标量；不用于在七个
  导出合同之间选族。
- **部分闭环裁决**（`docs/roadmap.d/eval-harness.md`）：现有 case 只密封到整条
  `journey_id`，没有子路径身份。宽问法若接受一张子路径卡，会把未选中的兄弟
  路径伪装成闭环。

因此：宽问法返回「请先列出可调族，再选一个再跑」是正确设计。当前 gap 的
`next_action` 已经指向 `gravity export list-capabilities`，这就是可行动澄清。

## 推测（与事实分开）

- gap **文案**已过时：仍写 origin 无非空 evaluate、monetization 未过 archive
  gate、五个可调族。这是文案债，不是「缺一个 dispatcher」。本轮未改文案，避免
  把过时合同缺口伪装成产品能力。
- 「导出分析结果」这种更短的问法当前 **不** 命中
  `ANALYSIS_EXPORT_FILE_CONTRACT_MISSING`（离线探测 `gap=None`）。是否要把更短
  问法也收进同一澄清，是后续路由题，不是本轮授权范围。
- 若维护者重新定义闭环判据：这条动线应继续记部分闭环，直到评测把宽问法的合法
  终点从「假装缺合同」改成「带七个候选的可行动澄清」，或把子路径拆成独立
  journey。**不要**为了让数字好看去建 dispatcher。

## 本轮改动

- 未新建产品、未改 CLI/SDK/Plan/Agent 合同、未改评测题集。
- 只改 `docs/analysis-journeys.md` J47 行两处「六个」→「七个」。
- 未改状态列，未改表头 `56 = x / y / z`。
- 生产请求 0 次。

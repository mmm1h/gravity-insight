> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 保存分析 config 生成与五类生产闭环

- 日期：2026-08-19
- 任务：#234
- 结论：SDK 可从五类可逆 compact spec 合成严格 Web config，五类均完成生产创建/读回/删除；#21 custom-before 仍被上游拒绝。

## 实测结论

| subject | 能生成 | 往返一致 | 上游接受 | 生产结果 |
| --- | --- | --- | --- | --- |
| `analysis_event` | 是 | 是 | 是 | 首个 26-path config 收到 HTTP 200 协议拒绝；按现存最小 config 补齐 `calculateBody.app_id/date_list/custom_query_item_list` 后，create/list/get/delete/消失确认全部 HTTP 200，读回 config 相等。 |
| `analysis_funnel` | 是 | 是 | 是 | 首次 create 接受；list/get marker 与 config 读回一致；删除后 marker 0。 |
| `analysis_retention` | 是 | 是 | 是 | 含 `query_item_before_after.before_custom` 的保存 config 首次 create 接受；list/get config 相等；删除后 marker 0。保存接受不等于查询接受。 |
| `analysis_scatter` | 是 | 是 | 是 | 首次 create 接受；list/get config 相等；删除后 marker 0。 |
| `analysis_user_property` | 是 | 是 | 是 | 首次 create 接受；list/get config 相等；删除后 marker 0。 |

离线生成只复用 `compile_query_spec`，`calculateBody` 和 UI 控制只来自现有
`BODY_FIELDS` / `UI_FIELDS`。每份生成结果立即交回现有 `compile_dashboard_chart`，比较直接编译和
Web 回放输入；只排除每次新生成的 `query_id`，并把合同已登记的缺省控制视为等价。
调用方已经提供 `calculateBody` 的 Web artifact 仍按原结构预检和提交。

生产 App 固定为 `29034827`。五类合计 10 次成功写（5 create + 5 delete），另有 event 初始 config
的 1 次协议拒绝写，总写请求 11/40。所有对象都带 `GSDK-<12 hex>`；最后一次完整目录读取证明本轮
精确 marker 数为 0，App 全部 `GSDK-` marker 数也为 0。逐步 HTTP 状态与 receipt 见
[`20260819_saved_config_generation.json`](../../../../evidence/forensics/20260819_saved_config_generation.json)。

## 推测与边界

- **实测：**event 初始 config 被拒；同时补入三个已在现存可接受 event config 和静态
  `BODY_FIELDS` 中出现的字段后被接受。
- **推测：**不能把接受归因到三个字段中的某一个，因为没有逐字段试错；只确定这组三字段形成了
  被接受的最小生成实例。本轮没有继续拆分因果。
- **实测：**现有消费器不是所有 compact 控制的双射。生成器只对能严格往返的形状产出 config；
  event 的非 `calc_layer_y=true`、retention 的额外分组顺序/非空 re-attribute、scatter 的非单一日粒度
  时间组等不可逆组合在写前失败关闭。已有 Web artifact 路径不受此限制。
- **推测：**五个本轮实例被接受不能证明任意未来 UI 字段组合都被接受；新增组合仍必须先通过同一
  离线往返不变量，再按 mutation 预算单次验证。

## #21 retention custom-before

发出的有效请求保留 `query_item_before_after.before_custom.list[0].conditions`，离线深度实测为 7，
并带现有编译器生成的 `create_time/day` group。前两次构造分别因 target field、condition field 不在
App live metadata 而在网络前停止；改用目录已登记字段后请求到达上游。

上游实际返回 HTTP 200、协议 `code=2015`、`extra.error=null`；`msg` 经 transport 解码后已经含
replacement characters，不能恢复原文。SDK 结果为 `semantic_error / INPUT_INVALID / caller / field=group_by_list`，
不是 `success` 或 `empty`，所以 #21 第一条验收标准仍未满足。为补齐安全 error 投影和协议标量，
同一有效 request shape 共读取 3 次；三次 receipt 和重复原因已写入 evidence，未改变请求形状，未写入
任何业务结果值。

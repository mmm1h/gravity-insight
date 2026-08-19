> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 看板挂载保存分析闭环

- 日期：2026-08-19
- 任务：#235
- 结论：挂载走甲，即 `dashboard/edit` 的整表 `report_list`；SDK 已完成 preview/execute、合并保护、写后回读与生产生命周期。

## 确定事实

- 冻结 `Dashboard-DrzT0Orh.js`（SHA-256 `6fc5339f29035a8aa08755e1ebfc482dd227c1c4511ff35c340dcc621ac48016`）中，选择保存分析先在本地加入 `{report_id, name}` 和对应布局项，保存时把完整 `report_list`、`ui_config` 发到 `POST /turbo_engine/api/v2/datamanageconfig/kanban/dashboard/edit/`。
- 同一控制流里的 `report/setting` 只修改已挂关联并继续调用 `dashboard/edit`；`report/delete` 的 `ids` 是 `even_report[].id` 内部关联 ID。现有 `analysis.datamanageconfig.kanban.*` 合同与 census 未出现独立 link 端点。
- 生产使用当前 principal 自有的既存保存分析，完成 `建文件夹/看板 → link → detail 报表数 1 → unlink → detail 报表数 0 → 删看板/文件夹`。最终看板 marker 与文件夹 marker 计数均为 0。
- 生产还纠正了 unlink 的身份模型：调用面收保存分析 `report_id`（不透明字符串），写线先由 detail 映射成正整数关联 `id`，再发 `report/delete`。
- 全程累计发送 24/25 次写请求，自动重试为 0；未保留凭据、对象 ID、分析定义或原始业务值。值无关证据见 [`20260819_kanban_report_link.json`](../../../../evidence/forensics/20260819_kanban_report_link.json)。

## 边界行为

| 边界 | 明确行为 | 写请求 |
| --- | --- | ---: |
| report 已全部挂载 | `execute` 返回 `already_attached`，不重复写 | 0 |
| `现有 + 新增 > 20` | 在 preview 前以 `report_ids` 输入错误拒绝 | 0 |
| report 不存在或当前 principal 不可见 | 完整读取 `analysis.report_config.list` 后本地拒绝 | 0 |
| 整表覆盖 | 先读 detail，原样保留全部既有 report 与布局项，再合并新增项 | 1 |
| 写成功响应但关联集或旧布局未回读 | 抛 `MutationReadbackError`，要求先重新读取，不自动重试 | 1 |

## 推测与未做生产破坏测试

- 20 上限来自已验证 wire 合同，容量拒绝、无权限/不存在、幂等和 readback 失败分支由测试锁定，没有在生产刻意制造。
- Census 理论上可能漏掉动态拼装调用；但冻结 bundle 的 add/save 控制流与生产 `dashboard/edit` 写后回读共同确认本能力应只实现甲，不需要再赌一个乙端点。

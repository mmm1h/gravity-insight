# 能力覆盖与缺口

本页回答“现在能调用什么、哪些只是候选、下一步为何不能直接上线”。运行时真相仍以
manifest 与 `gravity agent <query>` 为准；完整路由账本见
[`coverage-report.md`](../src/gravity_sdk/census/data/coverage-report.md)。

## 2026-08-11 离线快照

| 范围 | 当前状态 |
| --- | --- |
| 编译 operation | 185 |
| stable operation | 176 |
| 推广 / 素材 stable 原子读取 | 64 / 24 |
| Census 路由 | 987，全部有明确归类 |
| Census 中 callable covered route | 172 |
| 尚未覆盖的 read route | 343 |
| 明确保留的推广 / 素材 write reservation | 110 / 49 |

这些数字不等于“还有 343 个接口可以直接开发”。推广与素材共有 188 个 catalog-only
draft，但当前没有一个具有成功 probe；它们可用于说明缺口和准备最小探测，不能生成执行
argv，也不能进入 stable manifest。

## 平台纵深

- Bytedance 已覆盖账户、广告主、项目、推广、筛选器、汇总表现和主要素材查询，是目前唯一
  同时具备推广与素材纵深的平台。
- Honor 的 Census read route 已基本闭合；Kuaishou、Tencent、Bilibili、Apple、Huawei、
  Oppo、Vivo、Xiaomi 等多数平台仍以账户/广告主等基础读取为主。
- 除 Bytedance 外，平台专属素材能力普遍缺少经过非空样本验证的响应合同；不要把 common
  素材目录误写成各平台已完整覆盖。
- Apple、Huya、Qihu360、Sigmob、UC、Youdao、Bilibili 的 campaign/group/creative/report
  草稿最接近可验证状态。D32 已在当前账号完成最小根读取：只有 Bilibili account 曾非空，但
  advertiser 为空；其余六个平台在允许的根读取或最短单日 advertiser 窗口内均为空，且无权限
  失败或合同漂移。子级未发送，所有草稿继续等待有数据租户的最小非空 probe。
- auth/proxy 路由和写操作不属于普通读取缺口。前者保持 unsupported，后者保持 reservation，
  除非项目范围和安全模型明确扩展。

## 四级能力状态

| 状态 | Agent 应如何处理 | 升级条件 |
| --- | --- | --- |
| stable executable | 可以发现、描述、校验和执行 | 持续通过合同、隐私和漂移检查 |
| stable projection gap | 端点可用，但部分响应字段仍 fail-closed | 已有成功、脱敏、非空字段证据即可深化 |
| catalog-only draft | 只报告为 capability gap，不提供执行 argv | 请求绑定、非空响应、分页、隐私、父依赖和权限证据齐全 |
| reservation / unsupported | 不作为待调用能力展示 | 必须先改变项目范围和治理设计 |

本轮已按第二级补齐 Bilibili 账户汇总、素材分类→标签树、推广变更审计 ID、multidim
合计字段链路、overview 指标列映射，以及事件属性模板的 common/custom/preset 字典；未知
字段继续 fail-closed。

## 导出边界（2026-08-13 判定）

导出是独立 effect，账本在 `src/gravity_sdk/contracts/exports/routes-v1.json`。22 条 route 中只有
5 条 `executable`：`export.material.report.start` 是唯一可创建的导出，其余 4 条
（`export.task.list/progress/cancel`、`export.task_type.list`）是支持路由，不是创建候选。

**9 条 `export.analysis.*` 全部不可执行，且本轮判定为不推进**：

| 分类 | 数量 | route | 结论 |
| --- | --- | --- | --- |
| 合同已验证，隐私 gate 阻塞 | 3 | `origin_event.evaluate`、`segment.result.start`、`user_event.start` | 在线 wire 与文件协议已验证，但导出内容落在用户级标识/用户事件上，缺经批准的投影。**保留项**，不因合同可用而放行 |
| 合同未验证 | 6 | `origin_event.start`、`monetization_detail.start`、`segment_user_detail.start`、`stream_event.start`、`user_detail.start`、`pay_event.start` | 多数在线可建任务但任务失败，或返回 1004 无 task id；请求形状与文件 schema 未证明。**无新证据不重试** |

这是分析动线里唯一确定不脱离引力 Web 的环节：分析结果的导出需要先有经批准的用户级数据投影，
属于范围与安全模型问题，不是工程排期问题。调用方用 `export list-capabilities` 查看边界，
不要把 catalog 条目当成可执行能力。

## 刷新与核对

日常调用方不需要跑 Census。维护者在 frontend bundle 或 manifest 变化后执行离线对账：

```powershell
gravity census coverage --require-accounted
python -m gravity_sdk.compiler check
```

`coverage` 只消费已保存的 route、manifest、reservation 和 registry 文件；`fetch` 与
`check-upstream` 才会访问网络。任何生产 probe 仍必须遵循
[探测安全](maintainers/probing.md)，不能因为 draft 数量多而批量试探。

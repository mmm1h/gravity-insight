# 路由盘点

Census 从公开前端静态资源发现候选路由，并与 SDK 合同对账。它用于发现和漂移分析，不会自动把候选接口升级为 stable。

## 安全范围

- `fetch` 只下载公开 HTML 与 bundle；
- `parse`、`params`、`responses`、`coverage`、`diff`、`impact` 是离线处理；
- 不携带 Gravity 账号凭据调用候选 API；
- 不把字符串命中直接解释为可调用接口。

## 标准流程

```powershell
gravity census --smoke
gravity census fetch --help
gravity census parse --help
gravity census params --help
gravity census responses --help
gravity census coverage --help
gravity census diff --help
gravity census impact --help
```

先查看每个子命令的 `--help`，为 snapshot、raw 和 output 使用显式临时路径。不要覆盖仓库内基线，除非当前任务就是更新基线且证据已审查。

```text
fetch bundles
  → parse route candidates
  → extract request/response consumers
  → reconcile with manifests
  → diff snapshots
  → map impact to operation IDs
```

## 解释 coverage

- 已登记 stable：仍需关注响应字段和上游 hash 漂移；
- draft：只有静态证据，不代表差一次 probe 就能开放；
- blocked-write / blocked-privacy：明确保留，不应追求 callable；
- unknown：进入人工分类，不直接生成通用 operation。

## 更新仓库数据

应用新路由或响应字段前：

1. 保存来源 snapshot 与 hash；
2. 检查 diff 是否只包含目标上游变化；
3. 对受影响 operation 运行合同和投影测试；
4. 新字段先完成隐私分类；
5. 运行 compiler、quality、完整单元测试和 `git diff --check`。

生产页面确认仍受 [探测安全](probing.md) 约束。

## 请求提取器的已知诊断边界

`route-params.json` 的 `analysis.unresolved_reasons` 只保留 occurrence 级原因。表达式级
`unresolved_body_expression` 位于提取期间的内存 shape，输出时只折叠进
`analysis.unresolved_calls` 计数；因此不能用 JSON 文本 grep 统计该原因。需要诊断时必须用与
`bundle-snapshot.json` 逐文件 hash 一致的 raw bundle 重放当前提取器，同时分别报告 route、
occurrence/call-site 和 coverage 分类，不能把三个口径混用。

2026-08-14 的同快照杠杆评估得到：`load_alias_has_no_static_call` 为 97 route / 123 occurrence，
`unresolved_body_expression` 为 60 route / 82 call site；与 15 条完全缺失和 12 条部分闭环动线的
当前 blocker 交叉均为 0。函数内联与条件 callee 因而暂不实现；未来只有在它们能移除多条排期
动线的当前 blocker 时再重评，不能因静态命中规模大就扩张为通用 JS 求值器。

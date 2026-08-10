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

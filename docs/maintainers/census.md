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

`semantic_evidence` 还表示证据强度，而不是可探测性授权：

- `safe_http_method`：GET/HEAD/OPTIONS 的 HTTP 读语义证据；
- `route_registry:read_contract_not_verified`：维护者登记的读合同声明；
- `read_action_path_token`：仅由 `/list`、`/get`、`/query` 等路径词元推断的弱证据。

最后一类若同时为 POST，必须先按[探测安全](probing.md)逐条人工确认，不能把
`status=uncovered_read` 当作 probe 许可，也不能反向批量标成 mutation。

2026-08-14 对 214 条弱证据 POST 做了 12 条静态抽样：两个风险哨兵加按路径 SHA-256 固定选择的
10 条非定向样本。结果为 **2 条写、10 条真读、0 条判不了**；两个写路由分别是发送验证码与修改
报表设置，非定向 10 条均为读。样本不支持“多数都是写”，但证明误判不止一个且跨域存在；因此本轮
只增加证据强度闸门，不改提取器、不批量重分类。逐项工作记录位于忽略目录
`tmp/codex/probe-read-gate/sampling.md`，不作为长期分类台账。

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

**杠杆低的原因是分布，不是数量**——两类失败绝大多数落在本就不追的区域：

| 失败类型 | 写操作 | 已覆盖 | 未覆盖读 | auth/proxy | export |
| --- | ---: | ---: | ---: | ---: | ---: |
| `load_alias_has_no_static_call`（97 route） | 49 | 23 | 17 | 7 | 1 |
| `unresolved_body_expression`（60 route） | 45 | 7 | **1（D35）** | 3 | 4 |

写操作保持 reservation、auth/proxy 保持 unsupported，都不是取数缺口；已覆盖的 route 不需要再提取。
当时真正相交的只有默认值字典与 D35，且都卡**服务端语义与非空证据**，不是静态提取能力。
2026-08-16 默认值字典通过 catalog 多 App 枚举取得非空 shape 后已晋升；这项新证据不来自提取器，
因此不改变上述杠杆裁决。D35 仍阻塞。复算方法见上一段，逐 route 明细不入库。

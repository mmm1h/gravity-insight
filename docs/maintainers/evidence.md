# Evidence 运行手册

Evidence 是已登记 SQL 产品的可复核状态，不是普通查询缓存。只有显式发布流程可以更新当前 workspace 私有状态目录中的最新指针和不可变快照；业务 Evidence 不进入 SDK 仓库。

## 1. 离线预检

```powershell
gravity sql --dry-run
gravity sql evidence-preflight
python -m unittest discover -s tests
python -m gravity_insight.compiler check
python -m gravity_insight.quality check
git diff --check
```

确认业务 workspace 改动已经审查，凭据文件未跟踪，系统日期和 `Asia/Shanghai` 安全日计算正确。

## 2. 只读验证

```powershell
gravity sql verify --date YYYY-MM-DD
```

不带 `--publish` 时只执行验证，不更新发布指针。产品严格按 workspace 登记顺序、单并发执行；
每个 HTTP 请求继续经过共享 host limiter 与 Adaptive Governor。CLI 默认最多三次 HTTP 尝试，
`Retry-After` 与跨进程续跑冷却都以 30 秒为上界。检查每个产品的：

- 查询窗口和 App 范围；
- success、partial、empty 或 blocked；
- warnings 与 `forbidden_claims`；
- SQL hash、产品合同 hash 和结果摘要；
- 不包含用户级行或敏感信息。

## 3. 发布

只有验证结果经过审查后才执行：

```powershell
gravity sql verify --date YYYY-MM-DD --publish
```

发布应先写不可变 snapshot，校验后再原子更新 latest 指针。不要手工编辑 Evidence JSON/YAML，也不要覆盖已有不可变 snapshot。

若最终 HTTP 429 仍未恢复，命令以退出码 3 输出
`gravity.sql-verification-run.v1`，并把已经成功的严格产品前缀原子写入 workspace state；该文件
`readiness_achieved=false`、`verification_status=interrupted`，不会进入 Evidence latest。等待收据中的
`retry_after_ms` 后运行：

```powershell
gravity sql verify --date YYYY-MM-DD --publish --resume
```

`--resume` 只读取相同日期和 datasource 的固定 checkpoint，要求产品清单与顺序不变、已完成项恰为
严格前缀、失败项恰为下一个产品，并重新核对每个复用组件的 SQL/contract hash。任何漂移都在发送
下一次请求前失败关闭；非 429（例如 SQL engine rejection）不生成可续跑 checkpoint。

## 4. 发布后检查

```powershell
gravity sql status --json
```

确认 resolver 指向新 snapshot，manifest/result hash 可复算，状态不是 `stale`，并再次运行单元测试与 `git diff --check`。

## 失败处理

- 最终 429：不发布，保留 typed retry receipt 与已完成前缀；按 `--resume` 的严格前缀合同续跑；
- 非 429 上游失败：不发布且不允许借 checkpoint 跳过失败产品；先按结构化 `next_action` 修复；
- 产品 partial：只有合同允许且 warnings 完整时才可继续评审；
- 合同或 SQL hash 漂移：旧 Evidence 自动视为 stale，先审查改动；
- 发布中断：保留已写的不可变 snapshot，不手工移动 latest；
- 发现用户级或标识符值：不把值写入 evidence；只保留字段路径、类型、shape fingerprint 与
  脱敏状态继续完成合同取证。凭据值出现时立即停止并清理未提交输出。

Evidence 不证明业务因果、财务净收入或活动归因；这些限制由 SDK 的通用 SQL 机制合同、项目 workspace 产品合同和输出中的 `forbidden_claims` 共同约束。

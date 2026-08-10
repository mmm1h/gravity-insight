# Evidence 运行手册

Evidence 是已登记 SQL 产品的可复核状态，不是普通查询缓存。只有显式发布流程可以更新仓库中的最新指针和不可变快照。

## 1. 离线预检

```powershell
gravity sql --dry-run
gravity sql evidence-preflight
python -m unittest discover -s tests
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
git diff --check
```

确认工作树中的非 Evidence 改动是当前任务的一部分，凭据文件未跟踪，系统日期和 `Asia/Shanghai` 安全日计算正确。

## 2. 只读验证

```powershell
gravity sql verify --date YYYY-MM-DD
```

不带 `--publish` 时只执行验证，不更新发布指针。检查每个产品的：

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

## 4. 发布后检查

```powershell
gravity sql status --json
```

确认 resolver 指向新 snapshot，manifest/result hash 可复算，状态不是 `stale`，并再次运行单元测试与 `git diff --check`。

## 失败处理

- 上游失败或限流：不发布，保留脱敏错误摘要；
- 产品 partial：只有合同允许且 warnings 完整时才可继续评审；
- 合同或 SQL hash 漂移：旧 Evidence 自动视为 stale，先审查改动；
- 发布中断：保留已写的不可变 snapshot，不手工移动 latest；
- 发现用户级或敏感数据：立即停止，不提交输出。

Evidence 不证明业务因果、财务净收入或活动归因；这些限制由包内 SQL 产品合同和输出中的 `forbidden_claims` 共同约束。

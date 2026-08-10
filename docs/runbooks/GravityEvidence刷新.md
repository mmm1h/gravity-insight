# Gravity Evidence 刷新运行手册

## 适用范围

本手册用于 `gravity.daily_verification` 的受控只读核验与 Evidence 发布。默认只允许离线 preflight；真实 Gravity 读取和 Evidence publish 是两个独立人工 checkpoint。普通 PR CI 不连接真实数据源。

## 角色

- `data_steward`：确认数据窗口、`latest_safe_date`、口径和隐私级别。
- `release_operator`：在获授权的本机只读环境执行命令并保存聚合输出。
- `repository_owner`：复核工作树、Git provenance 和提交范围。
- `independent_verifier`：复核 snapshot/hash、readiness 和发布后指针。

角色不等于具体人员；未完成实际 Owner 指派时不得执行生产刷新。

## 1. 离线 preflight

```powershell
gravity sql evidence-preflight --json
```

该命令不读取 token 值、不连接 Gravity，并输出：

- `working_tree_clean_or_scoped`、branch、Git SHA、dirty；
- Python 版本、只读 profile、凭据是否存在及来源类型（不输出秘密）；
- 北京时间 `latest_safe_date`、目标日期、明确的 `[start,end)` 窗口和时区；
- 当前 immutable snapshot ID、manifest/result hash；
- 当前 readiness 与 offline blockers；
- `network_called=false` 和两个独立授权要求。

工作树必须干净或由操作人证明写入范围已隔离。若目标日期不是默认安全日，可先运行：

```powershell
gravity sql evidence-preflight --date YYYY-MM-DD --json
```

未来日期会失败关闭；北京时间每日 02:00 前的最新安全日为前两天，02:00 起为前一天。

## 2. Checkpoint B1：真实只读核验

只有获得 `allow_gravity_live_read=true` 的本次明确授权后，才可执行：

```powershell
gravity sql verify --date YYYY-MM-DD
```

不带 `--publish` 时只返回聚合预览，但仍会真实连接 Gravity。操作人必须确认：目标日等于已批准日期、窗口为北京时间单日、只使用固定四个聚合产品、没有用户级字段、query/contract/result hash 均生成成功。

## 3. Checkpoint B2：发布 Evidence

真实读取授权不等于发布授权。只有另获 `allow_gravity_publish_evidence=true` 后，才可执行：

```powershell
gravity sql verify --date YYYY-MM-DD --publish
```

发布只接受当时的 `latest_safe_date`，并依次：

1. 在 `snapshots/` 外 staging；
2. 校验 result schema、聚合隐私、row count 和全部 provenance；
3. 原子发布不可变 snapshot，目标已存在则拒绝覆盖；
4. 原子更新 `latest.yaml`；
5. 最后更新 `gravity-latest.json` 兼容文件。

新 manifest 必须记录 generated_at、窗口、时区、latest safe date（由结果中的 verified date 表达）、Git SHA/dirty、query/contract versions 与 hash、result hash、row count 语义、privacy、warnings、forbidden claims 和完整 provenance。若当前 schema 尚不能表达新增必填字段，应先走 schema 评审，不能塞入报告正文替代机器契约。

## 4. 发布后核验

```powershell
gravity sql status --json
python -m tools.common.validate_all --full --privacy-scope tracked
python -m unittest tools.gravity.test_products -v
git diff --check
```

status 必须解析到刚发布的具体 snapshot，并返回同一 snapshot ID、manifest/result hash。独立核验者检查工作树只包含预期 Evidence 文件，不含凭据、用户级结果或临时文件。

## 5. 失败与回退

- snapshot 失败：latest 与 rolling 文件不得推进。
- latest 更新失败：保留已发布 snapshot 供调查，不伪造 current 状态。
- rolling 更新失败：immutable snapshot/latest 已是权威；修复兼容层前记录告警，不覆盖 snapshot。
- hash、schema、路径或 provenance 不符：停止，不手工改 hash。
- 网络结果不确定：不要盲目重试；先确认是否产生 snapshot 和指针变化。
- 回退 current pointer 必须是单独受审变更，指向已有有效 snapshot；不删除或覆盖被引用 snapshot。

## 6. 历史缺口

- r3 已按原字节恢复到固定 snapshot，不重复回填。
- r2 的目标 hash 仍未找到，继续登记为 Evidence gap。
- 禁止用当前查询重跑结果冒充 r2，禁止改写旧报告记录的 hash。

## 明确不做

不把 Gravity 凭据提交仓库，不在 PR CI 建立带生产秘密的定时任务，不让 stale Evidence 破坏离线治理 CI，也不因离线演练或 preflight 成功宣称数据已刷新。

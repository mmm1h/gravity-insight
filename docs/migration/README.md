# Changelog 与迁移说明维护

`CHANGELOG.md` 是发布事实源，`scripts/check_changelog.py` 是 Release Gate。发布说明由
GitHub 自动生成仍可保留，但不能替代这份维护型记录。

## 版本指南

- [0.3.27：用户事件导出任务范围与源完整性](0.3.27.md)
- [0.3.26：订单细查记录身份完整性](0.3.26.md)
- [0.3.23：Funnel 只接受一个分组维度](0.3.23.md)
- [0.3.22：Event 条件、分位数编码与确定性拒绝](0.3.22.md)
- [0.3.15：精确运行时 pin 与执行版本收据](0.3.15.md)
- [0.3.12：证据语义拆分、动态 key 形状与 join key 契约](0.3.12.md)
- [0.3.11：聚合错误诊断与 Model claim policy 破坏性升级](0.3.11.md)
- [0.3.10：默认安装启动更新与隔离进程换版](0.3.10.md)
- [0.3.9：上游/内部故障不再归类为调用方输入错误](0.3.9.md)
- [0.3.8：Repository Map v2 传输编码](0.3.8.md)
- [0.3.5：从 0.3.4 迁移](0.3.5.md)
- [0.3.4：从 0.3.3 迁移](0.3.4.md)
- [0.3.3：从 0.3.2 迁移](0.3.3.md)

## 日常变更

1. 把尚未发布的消费方可见变化写进 `[Unreleased]`，并让 `Target release` 与计划版本
   一致。
2. 每个版本都保留 `### Breaking changes`。没有破坏性变更时明确写 `- None.`；有破坏
   时，每条用 `**Hard break:**` 或 `**Soft break:**` 开头。
3. 有破坏性变更时，创建 `docs/migration/<version>.md`，并在版本条目中用唯一的
   `Migration guide` 行链接它。说明至少回答受影响人群、旧/新写法、不迁移结果和旧
   写法移除计划。
4. 更新 CHANGELOG 后运行
   `.venv/Scripts/python.exe scripts/generate_release_compatibility.py`，提交生成的
   `src/gravity_insight/contracts/generated/release-compatibility.v1.json`。用 `--check`
   可只检查、不写文件。

## 发版

1. 默认用 [Release cut](../maintainers/releasing.md#one-click-release-cut)：
   `gh workflow run release-cut.yml --ref main`。先用 `-f dry_run=true` 验证候选；
   正常 PR 负责编辑发布说明，自动化只做机械转换，不修改 roadmap 或迁移措辞。
2. 人工 fallback 仍使用同一脚本，在独立虚拟环境、干净分支中运行
   `python scripts/release_cut.py prepare --version <当前版本>`，提交生成物后运行
   `python scripts/release_cut.py check`。日期默认 Asia/Shanghai；重现可传 `--date YYYY-MM-DD`。
   prepare 只新增 digest，依次调用兼容性与 harness 编排生成器，不手改生成物。
3. 从 A 合入前到下一 train 合入，协调全部 main writer；中途推进会搁置发布并取消仍在运行的 main push CI。人工路径经绿色 PR 合入 main，等 exact-SHA push CI 成功后在该提交创建/推送
   annotated tag。发布成功后运行 `python scripts/release_cut.py open-train --version <已发版本>`，
   提交、重新 `check`，通过另一个绿色 PR 开启下一 patch；人工不直接推 main。
4. `check_changelog.py` 与 compatibility `--check` 仍是 Integrated Validation 门禁。
   A 晋升后 main 推进只能走经审查的 forward-only PR/新候选版本，不回退 main、不标记旧 A、不删除或重建发布 tag；未发布版本复用须显式协调。失败恢复沿用 [Release Gate](../maintainers/releasing.md#one-click-release-cut)，不得改旧 digest。

## 自动更新消费方接入

wheel 内契约路径：
`gravity_insight/contracts/generated/release-compatibility.v1.json`。读取 API：

```python
from gravity_insight.contracts import load_release_compatibility

contract = load_release_compatibility()
```

下列步骤属于显式接入兼容性契约的外部 Installer，不是 CLI 默认启动更新策略。
从 0.3.10 开始，CLI 按 Owner 裁定自动安装新版，包括 Hard break；退出方式见
[0.3.10 迁移指南](0.3.10.md)。外部 Installer 按以下步骤执行，不读取 `CHANGELOG.md`：

1. 校验 `schema_version == "gravity.release-compatibility.v1"`。
2. `releases` 已按 SemVer 升序排列。按 `version` 找到当前版本 A 与目标版本 B；任一版本
   未列出时采用 `upgrade_policy.unlisted_version_decision`，即 `manual_review`。
3. B 位于 A 之前时采用 `downgrade_decision`；B 等于 A 时采用
   `same_version_decision`。
4. 升级时检查索引区间 `(A, B]`。任一版本的 `hard_breaks` 非空则返回 `block`，并把每项
   `description` 与 `migration_guide` 提示给人工迁移流程。
5. 没有硬破坏但任一版本的 `breaking_status` 为 `unknown` 时返回 `manual_review`。`unknown`
   表示历史信息不足，不能等同于 `none`；保守停下并提示人工确认。
6. 区间内信息均已知且 `hard_breaks` 全为空时返回 `allow`。`soft_breaks` 可随更新提示展示，
   但不会被当作硬破坏。

`breaking_status` 的含义固定为：`none` 表示 CHANGELOG 明确声明无破坏；`breaking` 表示
已记录一项或多项硬/软破坏；`unknown` 表示无法可靠复原完整清单。顶层
`upgrade_policy` 是机器决策枚举，消费方不应从说明文字推断决策。

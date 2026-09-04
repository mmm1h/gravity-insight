# Changelog 与迁移说明维护

`CHANGELOG.md` 是发布事实源，`scripts/check_changelog.py` 是 Release Gate。发布说明由
GitHub 自动生成仍可保留，但不能替代这份维护型记录。

## 版本指南

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

1. 把 `[Unreleased]` 的本次内容移入 `## [x.y.z] - YYYY-MM-DD`，在新的
   `[Unreleased]` 中写下一个 `Target release`。版本尚未 bump 时，当前
   `project.version` 也可由刚生成的 dated release 条目覆盖。
2. 在当前工作树运行
   `.venv/Scripts/python.exe scripts/check_changelog.py --print-digests`，
   只把新版本 digest 追加到 `scripts/changelog_release_lock.json`。不得重算或替换旧
   版本 digest。
3. 运行普通检查；缺版本条目、缺 Breaking 声明、缺迁移页、lock inventory 漂移或
   已发布正文变化都会返回非零：

   ```powershell
   .venv/Scripts/python.exe scripts/check_changelog.py
   ```

该检查是 `scripts/run_integrated_validation.py` 的 `changelog` gate；兼容性契约的
`--check` 是同一集成验证里的 `generator_release_compatibility` gate。因此遗漏发布说明
或生成产物漂移都不会在完整集成验证中变绿。

## 自动更新消费方接入

wheel 内契约路径：
`gravity_insight/contracts/generated/release-compatibility.v1.json`。读取 API：

```python
from gravity_insight.contracts import load_release_compatibility

contract = load_release_compatibility()
```

自动更新逻辑按以下步骤执行，不读取 `CHANGELOG.md`：

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

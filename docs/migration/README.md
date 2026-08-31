# Changelog 与迁移说明维护

`CHANGELOG.md` 是发布事实源，`scripts/check_changelog.py` 是 Release Gate。发布说明由
GitHub 自动生成仍可保留，但不能替代这份维护型记录。

## 日常变更

1. 把尚未发布的消费方可见变化写进 `[Unreleased]`，并让 `Target release` 与计划版本
   一致。
2. 每个版本都保留 `### Breaking changes`。没有破坏性变更时明确写 `- None.`；有破坏
   时，每条用 `**Hard break:**` 或 `**Soft break:**` 开头。
3. 有破坏性变更时，创建 `docs/migration/<version>.md`，并在版本条目中用唯一的
   `Migration guide` 行链接它。说明至少回答受影响人群、旧/新写法、不迁移结果和旧
   写法移除计划。

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

该检查也是 `scripts/run_integrated_validation.py` 的 `changelog` gate，因此完整集成
验证不会在遗漏发布说明时变绿。

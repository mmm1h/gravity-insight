# Changelog

本文件记录 Gravity Insight 面向消费方的显著变更。格式采用
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) 的分类方式，版本采用
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) 的三段格式；即使在
`0.x` 阶段，每个破坏性变更仍必须单独标成 Hard break 或 Soft break。

维护规则由 `scripts/check_changelog.py` 强制执行：`pyproject.toml` 的当前版本必须
有 Unreleased target 或已发布条目；每个版本必须显式声明 breaking changes；有破坏性
变更时必须链接迁移说明；带日期的已发布条目必须匹配
`scripts/changelog_release_lock.json` 中的 SHA-256。
具体维护步骤见[迁移说明维护约定](docs/migration/README.md)。

## [Unreleased]

Target release: `0.3.7`

### Breaking changes

- None.

### Fixed

- `gravity maturity score` no longer reports the correctness/surface-parity and
  architecture/token dimensions as unmeasurable. The isolated quality-profile
  subprocess printed a diagnostic report to stdout ahead of its JSON payload, so
  whole-document parsing failed while the subprocess still exited zero — an
  unexplained `None` indistinguishable from missing data. The report now goes to
  stderr, stdout carries exactly one machine-readable document, and parse failures
  surface an explicit reason in each dimension's `missing` instead of being swallowed.
- The Skill maturity dimension now derives Method Complete from the current report
  generated at scoring time rather than an absent manifest field, so
  `skill_semantic_operator_context` is measurable. The report carries a deterministic
  hash of the manifest set it read; a missing, failed or count-mismatched report keeps
  the dimension `measured=false` instead of reporting a stale conclusion.
- Upstream drift is measurable again. The census workflow now publishes a dedicated
  current-state artifact after a complete crawl, and `census status` / `maturity score`
  read it from an ignored local directory. Evidence older than 26 hours, or stamped
  more than five minutes in the future, is rejected as expired rather than silently
  accepted.

## [0.3.6] - 2026-09-03

### Breaking changes

- None.

### Fixed

- Static HTTPS Skill Hub Sources may now declare a bounded redirect-host allowlist.
  Runtime follows at most one HTTPS redirect to an exact declared host while retaining
  response-size and artifact-digest checks. This makes GitHub Release-backed Sources
  usable without enabling arbitrary redirects; `skill-library-v4` is the corrected
  immutable publication channel.

## [0.3.5] - 2026-09-02

Migration guide: [0.3.5](docs/migration/0.3.5.md)

### Breaking changes

- **Hard break:** Runtime wheel 不再携带或公开解析项目特定的 Built-in Skill；
  `LocalSkillResolver` 与 `gravity skills export-agent` 已移除，execution snapshot 的
  Skill resolution 只接受精确项目 lock。`gravity skills list/show` 现在必须指定
  `--state-root` 并读取已同步 Hub。R01 获客成本异常定位保留原 Journey、Plan owner、
  claims 和失败关闭能力，但项目必须提供 `gravity.skills.lock.json` 与已核验 CAS。

### Added

- `skill-library-v3` 将 AP 成本异常定位作为第 44 个 canonical Skill，通过 Runtime Hub
  与 Agent Skill 两种确定性投影分发，并达到 17/17 Method Complete。

### Changed

- MCP Skill inspection 与 `gravity://catalog/skills` 统一读取 workspace 的已同步 Hub 状态；
  wheel 内置业务 Skill 数归零。
- R01 execution snapshot 新增强制的 project lock、Hub source 和 package digest 绑定；
  缺 lock、CAS、来源或摘要时在目标请求前返回稳定 Hub gap。

### Removed

- 删除 wheel-owned AP Skill manifest/package tree 及其单独生成器，避免 Runtime Core 与
  Skill Library 形成两套业务方法分发权威。

## [0.3.4] - 2026-09-02

Migration guide: [0.3.4](docs/migration/0.3.4.md)

### Breaking changes

- **Hard break:** Agent Skill export 不再生成 Codex 不支持的顶层 `compatibility` frontmatter；
  原运行时版本约束迁移到 `metadata.gravity-runtime-requires`。直接解析导出 frontmatter 的消费方
  必须改读新位置；方法、版本约束值和 Runtime 执行能力均未丢失。

### Added

- Skill Library 为每个 canonical Skill 确定性生成标准 Agent Skill 目录、可复现 ZIP、
  `gravity.agent-skill-index.v1` 及其可离线验证 schema。
- 新增 `skill-library-v2` 发布通道承载 43 项 Method Complete 方法、Runtime-owned
  Operator/Model 依赖和项目 Semantic/Context 填充模板；v1 资产保持不变。

### Changed

- Skill Library build receipt 升级为 v2，分开完整本地 QA tree 与 GitHub Release 的扁平
  `release_assets`；Runtime 与 Agent archive 使用 Release 可直接寻址的全局唯一资产名。

### Fixed

- 修复 `gravity skills export-agent` 生成的 `SKILL.md` 会被当前 Codex validator 因未知
  `compatibility` 键拒绝的问题，并补齐执行前依赖/readiness 与结论前 claim policy 的渐进披露入口。

## [0.3.3] - 2026-09-01

Migration guide: [0.3.3](docs/migration/0.3.3.md)

### Breaking changes

- **Hard break:** Python 导入根从 `gravity_sdk` 改为 `gravity_insight`。PyPI 分发名在
  0.3.2 已经是 `gravity-insight`，`gravity` CLI 名也没有改变；只用 CLI 的消费方不受
  影响，但 Python import 没有兼容 shim。
- **Soft break:** auto-upgrade 的三个主环境变量从 `GRAVITY_SDK_*` 改为
  `GRAVITY_INSIGHT_*`。0.3.3 仍读取旧名作为 fallback，新名与旧名并存时新名优先；
  fallback 的移除版本尚未确定。
- **Hard break:** 安装诊断 JSON 的 `schema_version` 从
  `gravity-sdk.doctor.v1` / `gravity-sdk.install-consistency.v1` 改为
  `gravity-insight.doctor.v2` / `gravity-insight.install-consistency.v2`。解析这些值做
  分支的消费方必须同步更新；`gravity.*` 工具与门禁命名空间没有改变。

### Added

- 增加随 wheel 分发的 `gravity.release-compatibility.v1` 机器契约、稳定读取 API 与
  CHANGELOG 派生门禁，离线消费方可区分硬破坏、软破坏和历史未知状态。
- 增加 user-detail aggregate 的 Direct、Plan 与 Agent 交付面，并补齐请求约束、分页
  完整性和错误分类（#43、#53）。
- 增加受治理的素材文件获取、留存替代路线、批量分析闭环，以及 event analysis 的
  `hour` 时间粒度（#38、#40、#41、#42、#47）。
- 增加 Context authority 分层及外部 context provider 的约束与测试（#56）。
- 登记 Gravity SQL 探索快车道，并增加 schema/plan、分页、proof obligation 与晋级
  校验（#57）。
- 用仓库内 canonical skill library 和 source registry 取代 vendor mirror，并把确定性
  生成检查接入集成验证（#54）。

### Changed

- Python 包、console entry point、文档与安装 wheel 检查统一使用 `gravity_insight`
  import root；分发名和 `gravity` CLI 保持不变（#44）。
- 收敛 Agent Runtime 的当前架构来源，增加 canonical architecture 文档门禁并移除已
  退休的逐需求历史副本（#58）。
- 强化 release provenance、离线 wheel surface、canonical consumer ancestry 与恢复
  路径验证（#52）。
- 补齐 CODEOWNERS、安全报告与行为准则中的治理联系信息（#51）。

### Fixed

- Direct/Plan 的 user-detail aggregate 结果与分页完整性现在由同一 parity 约束校验，
  避免 Plan 丢失 Direct surface 字段（#53）。
- Census 把 HTTP、payload、写盘和 drift failure 分成稳定的失败类别，并保留 last-known-
  good 行为；相应分类进入 adaptive governor（#55）。
- 并发测试改用同步 rendezvous/隔离输出，降低把竞态当成通过或随机失败的风险（#35）。

## [0.3.2] - 2026-08-29

### Breaking changes

- 未记录。现存 tag 注释与 `v0.3.1..v0.3.2` 提交历史没有给出可可靠复原的破坏性变更清单。

### Added

- 增加 control-plane Ed25519 信任根校验；缺少可选校验依赖时 fail closed。
- 增加 plan-only 的显式 opt-in auto-upgrade 生命周期；Runtime 只生成外部 Installer plan，
  不自行安装或重启。
- 增加绑定 exact HEAD 的 integrated validation receipt，以及单测耗时预算门禁。

### Changed

- 并行化 pytest、分片 unittest，并缓存离线 wheel 与仓库级分析输入。

### Fixed

- malformed credential expiry 不再形成无界或静默延长的凭据有效期。
- canonical consumer revision 改为 main 可达的固定提交，并增加 ancestry fail-closed 检查。

> 历史完整性：本条由 annotated tag `v0.3.2`、`git log v0.3.1..v0.3.2` 和 PyPI
> 首次上传时间反推；无法由这些来源确认的变化均视为“未记录”。

## [0.3.1] - 2026-08-27

### Breaking changes

- 未记录。首个 tag 之前没有可用的维护型 changelog，不能可靠复原破坏性变更清单。

### Added

- 首个带 tag 的 `gravity-insight` 分发版本。该版本安装的 Python import root 仍是
  `gravity_sdk`，console entry point 为 `gravity = gravity_sdk.__main__:main`。

> 历史完整性：本条只记录 annotated tag `v0.3.1` 与 PyPI 首次上传能够证明的事实；
> 更早的功能明细未记录。

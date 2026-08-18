# 公开面未测分支：replace 同类扫描

- 日期：2026-08-18
- 任务：从未被测试走到的公开面策略/模式开关，找 `overwrite_policy=replace` 那一类真 bug
- 结论：按公开面枚举对账扫过一轮，**没有找到新的运行时会崩或静默吞错的 bug**。`replace` 对已存在目录会拒绝且不覆盖，已补锁定测试。

## 方法

1. AST 扫 `src/gravity_sdk/**/*.py`（排除 `prober/`、`census/`、`contracts/`、`manifests/`）：
   函数默认值、dataclass 字段、`add_argument(choices=...)`、以及
   `*_policy` / `*_mode` / `*_strategy` / `overwrite` / `fallback` / `routing`
   等名字上的成员比较。
2. 枚举取值与 `tests/` 全文做字面量对账（带引号出现即算“提到过”）。
3. 对安全面候选用离线 fixture 真跑：blob `replace` / resume / zip 默认、
   素材 `bytedance_project`、分群版本模式、Plan recipe `date-time`、
   `update_segment_metadata(UPDATE_NAME)`。
4. 另做一轮“策略分支体里引用未定义名字”的 AST 扫描（#179 的 `NameError` 模式）。

**这个方法会漏掉：** 合同 JSON 里未进 SDK 校验器的枚举；测试里用变量/拼接拼出的取值
（字面量对账会假阴性）；内部私有 `if`；需要真实上游形状才能证伪的语义；
CLI `store_true` 这类非枚举开关；以及“提到过字面量但从未走到该分支”的假阳性漏网。
未定义名字扫描噪声大（walrus / 延迟 import / 推导式），只能当辅助。

未对生产发请求。未读、未写 `docs/roadmap.md`。未改动线台账。

## 事实 / 推测

**事实（代码与离线探测直接读到）：**

- `overwrite_policy` 只有 `deny` / `replace`。默认 `deny` 与普通文件 `replace`
  已有测试。`replace` 且目标是目录：prepare 阶段 `BLOB_PATH_UNSAFE`，目录仍在。
  `replace` 且目标是指向仓外文件的符号链接：`BLOB_PATH_REPARSE`，仓外内容未改。
- 默认 `allow_range_resume=False`：带 resume 状态时 `BLOB_RESUME_DISABLED`。
- 默认 `ArchivePolicy(enabled=False)`：合法 ZIP 也是 `BLOB_ARCHIVE_BLOCKED`。
- `fetch_material_asset(..., "bytedance_project", ..., "file")` 走合同
  `list_path=data.video_material_list` / `material_id` / MP4 magic，离线成功。
- `AnalysisCohort(segment_type="DYNAMIC_MATCHING"|"FIXED_VERSION")` 能编进
  `analysis.event.query`；缺 `version_id` 或给 `LATEST` 带 id 都本地拒绝。
- `update_segment_metadata(..., execute=True)` 发出 `action=UPDATE_NAME`，
  保留 `GSDK-` 标记；外人无标记则 `OWNERSHIP_REQUIRED`，0 次写。
- `plan_multidim_result._safe_page` 只认 `single`/`serial`/`parallel`。
  真实分页策略是 `single_page` / `serial_known_total` / `parallel_known_total` /
  `serial_unknown_total`。产品信封 `composite_result._safe_page` **本来就不投影
  `fetch_strategy`**。Plan 投影因此静默丢掉该字段，不是放宽安全判定。
- 未定义名字扫描 442 个模块、25 处命中，抽查均为 walrus / 延迟 import 误报。

**推测（未打真实上游）：**

- `bytedance_project` 的线上列表形状若与合同不一致，会在读源阶段失败，不会下载调用方 URL。
- `_safe_page` 的三词枚举多半是旧名残留，不是调用方能传的策略开关。

## 确认是 bug 并已修

无。本轮没有改 `src/`。

## 没坏但已补锁定测试

| 分支 | 观测 | 锁定测试 |
| --- | --- | --- |
| `overwrite_policy="replace"` 且目标已是目录 | `BLOB_PATH_UNSAFE`，目录不被替换 | `SafeBlobTransferTests.test_replace_overwrite_policy_rejects_existing_directory` |

防的回归：以后若有人把 `replace` 放宽成 `os.replace` 任意已存在路径，会覆盖目录或跟目录冲突后留下半提交。

## 判断不了 / 扫到但未改代码

| 候选 | 为何没当 bug | 为何没补测试 |
| --- | --- | --- |
| `replace` + 已存在符号链接 | 探测为 `BLOB_PATH_REPARSE`，仓外文件未改 | 与目录案合并会超测试行预算；现有 symlink 测试已覆盖默认 deny |
| 默认 `allow_range_resume=False` | `BLOB_RESUME_DISABLED`，关着更严 | 默认关不是数据损失面 |
| 默认 `ArchivePolicy.enabled=False` | ZIP 被 `BLOB_ARCHIVE_BLOCKED` | 已有 `enabled=True` 的炸弹/zip-slip 测试 |
| CLI/SDK `bytedance_project` | 离线走通合同路径 | 行为正确；非安全退化 |
| `FIXED_VERSION` / `DYNAMIC_MATCHING` | 本地编译/拒绝符合文档 | 无崩溃、无吞错 |
| Plan recipe `format=date-time` | 无偏移拒绝，有偏移绑定成功 | 纯格式校验 |
| `update_segment_metadata` / `UPDATE_NAME` | 预览 0 写；执行保留标记；外人拒绝 | 与 `delete` 共用所有权门；非未定义路径 |
| `plan_multidim_result._safe_page` 策略词 | 静默丢字段，产品信封本来就不输出该字段 | 展示/投影，本轮不做 |
| 合同 `AND`/`OR`、`group_by` 等 | 字面量对账会漏“测试用变量拼出来的值” | 未当未测 |

## 未改

- `src/`、质量 baseline（`hard_limit` / `threshold` / `max_` 无改动）、
  `operation_literals` 棘轮、评测装置/题集、`docs/roadmap.md`、
  `docs/analysis-journeys.md`。
- 动线表头 `56 = x / y / z`：本轮不闭环任何分析动线，汇总不应变。

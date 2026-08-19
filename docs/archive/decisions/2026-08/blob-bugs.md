> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# blob 下载路径 5 条疑似 bug

- 日期：2026-08-18
- 任务：#175 拆分后留下的 5 条下载安全疑点（本 worktree `grok/blob-bugs`）
- 结论：5 条里只有第 2 条的空 `If-Range` 和第 5 条 `replace` 提交路径成立并已修；第 1、3、4 条不成立。

## 事实 / 推测

**事实（代码与测试直接读到）：**

- 公开入口是 `SafeBlobTransfer.download`：先 `_validate_resume_state`，再
  `_download_request_headers`，再 `_preflight_headers`。
- `9da305d` 拆分前 `initial_size = resume.bytes_received` 立刻用于
  `Range: bytes={initial_size}-`。拆分后该局部变量消失，同一值写成
  `Range: bytes={resume.bytes_received}-`（`blob_download.py` 第 29 行）。
- `_validate_resume_state`（`blob_storage.py` 第 259 行）在
  `not (resume.etag or resume.last_modified)` 时抛 `BLOB_RESUME_INVALID`。
  Python 里 `""` 为假，因此空校验器走拒绝，不会继续发请求。
- `_preflight_resume_headers`（`blob_headers.py` 第 121–132 行）在
  `resume.etag is not None` / `resume.last_modified is not None` 时比对；
  响应缺字段时 `_header` 返回 `None`，`None != 已存值` 会拒绝。
- `_preflight_resume_or_full` 的 resume / 全量两支互斥，各自读一次 ETag 和
  Last-Modified，同一请求不会算两遍。
- `overwrite_policy="replace"` 且目标已存在时，`_prepare_destination` 放行，
  `_commit_staging` 原调用未定义的 `_is_reparse_stat`，抛 `NameError`。
  默认 `deny` 在 prepare 阶段就被 `BLOB_OVERWRITE_DENIED` 拦住，现有测试
  到不了 commit。
- 仓库内没有 `If-Range` 合同或上游探测记录。

**推测（未打真实上游）：**

- 若把 `If-Range: ""` 发给真实对象存储，可能被当成非法预条件而回 200 全文，
  随后被 `_require_download_status` 以期望 206 拒绝。本轮没有对上游发请求。

## 第 1 条 `initial_size`：不成立

拆分前不是死变量，只是给 `Range` 用的别名。拆分后没有 `initial_size` 这个
名字，偏移仍按 `resume.bytes_received` 写入 `Range`。

复现请求：resume `bytes_received=3`、etag `"version-1"`，响应 206 但 ETag 变成
`"version-2"`。客户端发出 `Range: bytes=3-`，随后因校验器变化拒绝写入。

锁住行为：`SafeBlobTransferTests.test_resume_rejects_changed_etag_before_appending`
现在断言发出的 `Range` 等于 `bytes={bytes_received}-`。未改下载偏移计算。

## 第 2 条 空 `If-Range`：部分成立

**与 `_validate_resume_state` 的互动不成立。** 该函数不读请求头；空
`etag` / `last_modified` 在第 259 行就被 `BLOB_RESUME_INVALID` 挡住，
`download()` 不会发出 `If-Range: ""`。

**辅助函数本身成立。** `_download_request_headers` 在拆分后仍写
`If-Range = resume.etag or resume.last_modified or ""`。直接调用时（绕过
resume 校验）会带上空串。RFC 7233 的 If-Range 只接受 entity-tag 或
HTTP-date；空串两者都不是。合同和既有测试都没有规定空串语义。

修法：缺校验器时不写这个头。`Range` 仍发。

复现测试（先红后绿）：`test_resume_request_omits_blank_if_range`。

公开路径仍先走 `_validate_resume_state`，行为不变。

## 第 3 条 resume 字段比对：不成立

当前不是“两边都有才比”，而是“resume 里存了哪个字段就比哪个”。响应缺字段
等于 `None`，与已存值不等则拒绝。

| resume 持有 | 响应 | 当前分支 | 应走 |
| --- | --- | --- | --- |
| 只有 ETag | ETag 不同 | `BLOB_RESUME_VALIDATOR_CHANGED` | 拒绝 |
| 只有 ETag | ETag 相同 | 通过 ETag 检查 | 接受 |
| 只有 Last-Modified | Last-Modified 不同 | `BLOB_RESUME_VALIDATOR_CHANGED` | 拒绝 |
| 只有 Last-Modified | Last-Modified 相同，ETag 不同或缺失 | 不比 ETag，接受 | 接受（未绑定 ETag） |
| 两者都有 | ETag 不同、Last-Modified 相同 | 先因 ETag 拒绝 | 拒绝 |
| 两者都有 | 响应缺 ETag、Last-Modified 相同 | `None != resume.etag`，拒绝 | 拒绝 |

#175 举的“只有 ETag、响应 ETag 不同但 Last-Modified 相同”在现逻辑下已经拒绝，
没有反了。未改比对代码。

## 第 4 条 etag / last_modified 重复计算：不成立

`_preflight_headers` 把取值交给 `_preflight_resume_or_full`。resume 支路在
`_preflight_resume_headers` 读一次；全量支路在 else 读一次。两支互斥，
同一响应不会算两遍，值也没有分叉。

拆分前也是 if/else 各写一份 `_header(...)`，不是“先算一遍再算一遍”。
合并调用不会改变任何分支的返回值，但属于无行为差异的整理，本轮不动。

## 第 5 条 `overwrite_policy=replace`：成立

默认 `deny` 有测试。`replace` 且目标已是普通文件时，prepare 放行，commit
调用未导入的 `_is_reparse_stat`，`NameError`。

复现：已有 `report.csv` 内容 `existing`，策略 `replace`，下载合法 CSV。
修复前在 `_commit_staging` 第 92 行崩溃；本地文件仍是 `existing`。

修法：改成已导入的 `_reparse_stat`（会走 `blob` facade 上的
`_is_reparse_stat` 补丁，与其它路径一致），再 `os.replace`。

复现测试（先红后绿）：
`test_replace_overwrite_policy_replaces_existing_regular_file`。

## 未改

- `docs/roadmap.md`、`docs/analysis-journeys.md`、评测题集。
- 动线表头 `56 = x / y / z`：本轮不闭环任何分析动线，汇总不应变。

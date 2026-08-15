# Gravity Insight 契约 Probe 管线

本管线把 census 中 method 已确定的未覆盖只读路由依次推进为：契约草案、在线证据、
通过闸门的 stable operation。路由 path 只能用于生成 draft，不能作为 stable 证据。

## 1. 生成 Draft

按精确 path、family、业务模块或成本筛选 `coverage.json`。一次最多生成 12 项；无筛选
条件会拒绝运行，避免误把 382 条未覆盖读批量生成。

```powershell
python -m gravity_sdk.prober draft --path /turbo_engine/api/v1/bytedance/std/project/material_report/
```

该 path 是当前 coverage 中 method 已确定且尚无 draft 的 read；命令只适合执行一次。再次执行会
因 draft 已存在而拒绝。也可把 `--path` 换为当前 coverage 中尚未生成 draft 的 `--family`、
`--business-module` 和 `--cost` 选择器；不要照抄一个已经全部生成过的 family/module。

输出位于 `contracts/drafts/`。草案使用 `draft.status=draft`、
`operation.stability=experimental`、`operation.executable=false`，projection 初始为空。
operation_id 会同时检查 stable 与 draft 冲突；无法可靠判断 domain/resource/action 时使用
`unknown` 标识，不伪造业务语义。

## 2. 在线 Probe

```powershell
python -m gravity_sdk.prober probe app.monetization_app.list
python -m gravity_sdk.prober probe --stable app.list
```

两条 probe 命令均需联网；本次文档一致性校对未执行。

probe 复用公共 `GravityInsightClient`、既有 credentials、PolicyEngine、Transport 和
executor。draft 文件仍保持不可执行，仅在同一进程的临时 registry 中开启单次
experimental read。`--stable` 用于已登记 operation 的上游漂移核验。

固定安全边界：只允许 census/manifest 中的 GET 或只读 POST；单并发；请求间隔默认
310ms 且不能低于 300ms；单命令预算不超过 200；attempts=1；遇到 429/5xx 立即终止
该 family。凭据失效但本机有账密时，CLI 委托既有 guarded refresh 工作流换 token。

每次结果写入 `evidence/probe/*.yaml`。文件内容使用 JSON 语法这一
YAML 1.2 合法子集，因此不需要新增 YAML 运行时依赖。证据只保存 HTTP 状态、请求字段
与类型、响应 path/type sketch、分页布尔判定和指纹；不保存 header、token、cookie、
password 或 response 值。数字/UUID/非标 object key 会折叠为 `{dynamic_key}`。
同目录允许保存手写 YAML 审计，但 probe 统计和批次汇总只聚合 JSON-compatible 证据；
真 YAML、损坏 JSON、不可读文件或非 object 文档不会被计入统计，并会在 status/批次汇总的
`skipped_files` 中给出路径和原因，不会因旁路审计文件导致整条状态命令失败。

## 3. Projection 与闸门

观察字段先进入 `draft.candidate_fields`，默认不等于 allowlist。字段名先匹配敏感规则，
再匹配已登记的上游授权数据规则；只有凭据字段进入 `sensitive`，语义或类型不能从现有证据确认的
字段进入 `manual_review_fields`。人工复核解决的是合同证据，不再建立字段级访问控制。

升级必须同时满足：

- 至少一次 HTTP 2xx、语义成功、非空且 confirmation projection 为 success；
- 所有暴露字段均为 `non_sensitive`；
- 分页 operation 的 page 参数和受控 `max_page_size` 已在线验证；
- 没有 sensitive 或 manual_review 字段处于暴露状态；
- minimum live probe 不含 runtime 不支持的占位符。

空数据、父资源无可选值、权限不明、参数错误或路由状态无法区分时保持 draft，并在
`promotion_gate.missing` 记录具体卡点。

## 4. 升级与状态

```powershell
python -m gravity_sdk.prober status
python -m gravity_sdk.prober promote --help
python -m gravity_sdk.compiler compile --check
```

`promote` 重新计算闸门，拒绝人工改写 `eligible` 绕过检查。通过后原子写入
`contracts/operations/`、移除对应 draft，并直接调用 compiler 重建 manifests；
manifests 不能手改。当前 299 个 draft 均非 eligible，因此没有可直接运行并成功的 promote
示例；只有 `status` 对具体 operation 报告 `eligible=true` 后，才按 help 所示传入该 ID。
`status` 汇总 draft 卡点、probe 次数和证据请求统计。

父依赖的 `output_path` 只描述 value-free 路径。`selection=caller_select` 表示真实业务
调用必须由调用方选择父对象；probe 可为最小验证临时选择第一项，但会在证据中显式记录
`probe_selection=first`，不会把它改写成业务默认行为。

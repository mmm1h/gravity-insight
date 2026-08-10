# Gravity Insight 契约源

本目录是 Gravity Insight operation 的唯一构建源。`../manifests/*.json` 是兼容
runtime 的确定性构建产物，不再手写。

## 目录

```text
contracts/
  schema/operation-v2.schema.json  # 独立 operation 源 schema
  schema/family-v1.schema.json     # family 模板 schema
  drafts/<operation_id>.json       # census 生成、尚未过 probe 闸门的不可执行草案
  operations/<operation_id>.json   # 当前 stable 平铺源，一项一文件
  families/*.json                  # 后续同构 family；当前尚未启用 family 化
  generated/provenance.json        # compiler 生成的逐 operation 溯源
../manifests/*.json                 # compiler 生成的 runtime v1 产物
```

## 新增一个平铺 list operation

1. 优先用 `python -m gravity_sdk.prober draft ...` 从 census 生成
   `drafts/<operation_id>.json`；草案固定 `executable=false`，不得直接复制为 stable。
2. 用 `prober probe` 取得 projection 前的 value-free schema sketch、分页、错误形态、
   父依赖和隐私分类证据。观察字段先进入候选清单，不会因 HTTP 200 自动暴露。
3. 只有 `prober promote` 闸门通过后，才生成 `operations/<operation_id>.json` 并由
   compiler 重建 manifests。不要编辑 `../manifests/*.json`。
4. `examples` 是 agent `capabilities describe` 的正式输入示例；只有不含租户值且可
   直接运行的最小输入才能生成。无法提供安全、可运行示例时保留 `[]` 并显示 unknown。
5. `required_parent.output_path` 和 `selection` 是父依赖溯源事实。`first/unique/all`
   表示可声明式选择，`caller_select` 表示业务调用方必须选择；不得用 `first` 掩盖
   调用方选择语义。当前 runtime manifest 只投影 operation_id/input_field，完整溯源
   由 operation-v2 与 agent describe 保留。
6. `provenance.source_files` 填当前相对路径，`family` 填 `null`，`platform` 与
   operation 一致，`applied_overrides` 填 `[]`。compiler 会复核，不能伪造来源。
7. 运行：

```powershell
python -m gravity_sdk.compiler lint
python -m gravity_sdk.compiler compile
python -m gravity_sdk.compiler compile --check
python -m unittest discover -s tests -p "test_gravity_insight_compiler.py"
python -m unittest discover -s tests -p "test_gravity_insight_golden.py"
python -m unittest discover -s tests -p "test_gravity_insight_*.py"
```

普通平铺 list operation 只新增这一个 JSON 文件；当前最短平铺 operation 源为 85
行，字段较多时按实际 allowlist 增长。不改
Python，不手写 manifest。只有 contract schema 当前无法表达新的协议能力时，才把
引擎能力变更与业务 operation 扩容拆成不同变更。

## 源字段与 runtime 投影

v2 源保留现有 `OperationSpec` 的全部事实字段，并新增以下构建期字段：

- `effect`: `read | export | file | mutation`。当前 stable operation 均是 `read`。
- `examples`: agent surface 会展示的结构化最小输入示例；不含凭据或租户级值。
- `required_parent.output_path` / `selection`: 父输出路径与选择语义溯源；
  `caller_select` 显式表示不能由工具静默代选。
- `provenance`: 直接源文件、family、platform 和 override 列表。

compiler 会把 `privacy_policy.redact_fields` 投影回 runtime 的 `redact_keys`，把
`live_probe.inputs` 投影回 `input`，把 parent 对象投影回 v1 字符串/对象形式，并
剥离 `effect`、`examples`、`provenance` 及未启用的 parent 字段。这样 runtime 仍只
读取原有 manifest 格式。完整 provenance 单独物化到
`generated/provenance.json`。

## Family DSL

family 使用显式 `matrix`，而不是蓝图草案中的外部 `$platforms` 隐式笛卡尔积。
每行包含 `manifest_order` 和一组标量 `bindings`；`operation` 中与 binding 同名的
`{binding}` 在构建期展开，其他花括号（例如 runtime path 的 `{advertiser_id}`）
原样保留。精确占位符可保留绑定的 boolean/number/null 类型，嵌入字符串的占位符
生成字符串。

```json
{
  "$schema": "../schema/family-v1.schema.json",
  "family_schema_version": 1,
  "family_id": "promotion-level-list",
  "target_manifest": "promotion.json",
  "matrix": [
    {
      "manifest_order": 100,
      "bindings": {"platform": "example", "resource": "campaign"}
    }
  ],
  "operation": {
    "operation_id": "promotion.{platform}.{resource}.list"
  },
  "overrides": [
    {
      "id": "example-post",
      "when": {"platform": "example"},
      "patch": {"upstream_method": "POST"}
    }
  ]
}
```

示例只展示 family 结构，真实 `operation` 必须展开为完整 operation-v2。override
按顺序应用 JSON Merge Patch；数组整体替换。patch 的每一层字段必须由
operation-v2 schema 声明。整份 operation 替换只能使用
`"escape_hatch": true` 加 `replacement`；禁用实例使用 `"disabled": true`。
所有实例展开后仍逐项通过 operation-v2、runtime model 和跨 operation lint。

## 命令语义

- `lint`: 只校验 source schema、展开 family 和语义 lint，不写文件。
- `compile`: 重建 manifests 与 provenance。
- `compile --check` / `check`: 不写文件；任何缺失、额外或字节漂移均退出 1。
- `migrate`: 仅用于首次 v1 反向迁移；目标 operations 目录非空时拒绝覆盖。

草案生成、在线验证、升级和状态查询见 [prober guide](prober-guide.md)。

schema 校验器实现于 `../compiler.py`，只解释本仓库 schema 使用的 Draft 2020-12
关键字；遇到 schema 自身使用了未实现关键字会失败关闭。它不引入 `jsonschema`
运行时依赖。

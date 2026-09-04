# 复合 cohort 留存替代路径

普通“一个起始事件到一个回访事件”的留存继续使用 `analysis query --kind
retention`。下面两类复合 cohort 不发送 Retention endpoint 已拒绝的
`before_custom` 或 `property_condition`；它们只组合现有 Funnel、Segment 和
本地除法。

示例固定使用北京时间 cohort 日 `2026-08-01`、D1 `2026-08-02`。把 `main`、
物理事件、属性和值替换为调用项目已登记的精确值。所有 spec 都先执行 `--dry-run`；
只有分群创建是 mutation，必须审查预览后把同一命令的 `--dry-run` 改为
`--execute`。

## 同日首次注册与支付的交集

分母 cohort 是同一自然日内依次完成首次注册和支付、并满足用户属性条件的用户。
`window.unit=today` 与单日 `start=end` 共同把两步限制在 cohort 日；Funnel
第二步人数就是分母。

`reg-pay-funnel.json`：

```json
{
  "start": "2026-08-01",
  "end": "2026-08-01",
  "global_filters": [
    {
      "operator": "EQUALS",
      "field": "$ea_click_company",
      "type": "user",
      "value": ["<project-acquisition-value>"]
    }
  ],
  "global_logic": "AND",
  "steps": [
    {
      "event": "$UserFirstRegister",
      "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    },
    {
      "event": "$PayEvent",
      "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    }
  ],
  "window": {"unit": "today", "value": 1},
  "calculate_each_day": false
}
```

先确认 Funnel，再把 matched step `1` 固化为一个受治理分群。`--execute` 内部会先
重跑同一 Funnel，只有成功后才发单次、不重试的分群写入；返回的
`target.segment_id` 是下面两个 spec 的 `<reg-pay-segment-id>`。

```powershell
gravity analysis query --kind funnel --app main --spec reg-pay-funnel.json --dry-run
gravity analysis query --kind funnel --app main --spec reg-pay-funnel.json
gravity analysis segment create-from-analysis --app main --spec reg-pay-funnel.json `
  --name GSDK-reg-pay-d1 --step 1 --matched --dry-run
gravity analysis segment create-from-analysis --app main --spec reg-pay-funnel.json `
  --name GSDK-reg-pay-d1 --step 1 --matched --execute
```

`reg-pay-denominator.json` 只评估该分群：

```json
{
  "name": "reg-pay-base",
  "start": "2026-08-01",
  "end": "2026-08-02",
  "logic": "AND",
  "property_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "field": "<reg-pay-segment-id>",
            "source": "segment",
            "operator": "TRUE",
            "values": [],
            "segment_type": "LATEST"
          }
        ]
      }
    ]
  }
}
```

`reg-pay-numerator.json` 使用相同分群，并要求 D1 至少发生一次启动：

```json
{
  "name": "reg-pay-return",
  "start": "2026-08-01",
  "end": "2026-08-02",
  "logic": "AND",
  "property_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "field": "<reg-pay-segment-id>",
            "source": "segment",
            "operator": "TRUE",
            "values": [],
            "segment_type": "LATEST"
          }
        ]
      }
    ]
  },
  "event_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "event": "$MPLaunch",
            "did": true,
            "target": {"field": "PresetAllCount", "aggregation": "PresetAllCount"},
            "did_condition": {"operator": "GTE", "values": [1]},
            "date_range": {"type": "static", "start": "2026-08-02", "end": "2026-08-02"}
          }
        ]
      }
    ]
  }
}
```

两次只读评估都只取聚合 `part`；分母为 0 时留存率未定义，不能填 0。

```powershell
$denominator = gravity analysis segment evaluate --app main `
  --spec reg-pay-denominator.json --fields part | ConvertFrom-Json
$numerator = gravity analysis segment evaluate --app main `
  --spec reg-pay-numerator.json --fields part | ConvertFrom-Json
if ($denominator.data.part -eq 0) { $d1 = $null } `
else { $d1 = [decimal]$numerator.data.part / [decimal]$denominator.data.part }
```

完成后可以按同一受治理两阶段流程删除中间分群：

```powershell
gravity analysis segment delete --segment-id <reg-pay-segment-id> --dry-run
gravity analysis segment delete --segment-id <reg-pay-segment-id> --execute
```

语义差异只有执行形态：原请求希望一次 Retention 调用直接返回整条留存曲线；替代路径
固定一个 cohort 日和 D1，产生一个中间分群，再用两个聚合数相除。用户集合定义、属性
条件、cohort 日和 D1 启动日不变；它不自动生成 D2/D3 等整条曲线。

## 首次付费日属性 cohort

set-once `first_pay_time` 直接用 Segment 属性规则定义，不要求 `$PayEvent` 再次出现。
下面的毫秒值是北京时间 `2026-08-01 00:00:00.000` 到
`23:59:59.999`。如果 live metadata 把项目字段登记为另一种表示，执行会 fail closed；不得
静默把毫秒改成秒或字符串。

`first-pay-denominator.json`：

```json
{
  "name": "first-pay-base",
  "start": "2026-08-01",
  "end": "2026-08-02",
  "logic": "AND",
  "property_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "field": "first_pay_time",
            "source": "user",
            "operator": "RANGE_IN",
            "values": [1785513600000, 1785599999999]
          }
        ]
      }
    ]
  }
}
```

`first-pay-numerator.json` 是同一属性规则 AND D1 启动：

```json
{
  "name": "first-pay-return",
  "start": "2026-08-01",
  "end": "2026-08-02",
  "logic": "AND",
  "property_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "field": "first_pay_time",
            "source": "user",
            "operator": "RANGE_IN",
            "values": [1785513600000, 1785599999999]
          }
        ]
      }
    ]
  },
  "event_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "event": "$MPLaunch",
            "did": true,
            "target": {"field": "PresetAllCount", "aggregation": "PresetAllCount"},
            "did_condition": {"operator": "GTE", "values": [1]},
            "date_range": {"type": "static", "start": "2026-08-02", "end": "2026-08-02"}
          }
        ]
      }
    ]
  }
}
```

```powershell
gravity analysis segment evaluate --app main --spec first-pay-denominator.json --dry-run
gravity analysis segment evaluate --app main --spec first-pay-numerator.json --dry-run
$denominator = gravity analysis segment evaluate --app main `
  --spec first-pay-denominator.json --fields part | ConvertFrom-Json
$numerator = gravity analysis segment evaluate --app main `
  --spec first-pay-numerator.json --fields part | ConvertFrom-Json
if ($denominator.data.part -eq 0) { $d1 = $null } `
else { $d1 = [decimal]$numerator.data.part / [decimal]$denominator.data.part }
```

这一路不写分群、不取用户明细。与 Retention 目标的集合语义相同：分母是属性值落在
cohort 日的用户，分子是该集合与 D1 启动用户的交集。代价是两次聚合读取与一次本地
除法，且只返回所选观察日，不返回 Retention endpoint 的整条 offset 矩阵。

## 自定义事件首次暴露 cohort

I107 要求的集合不是普通事件日 Retention。它的分母必须同时满足：cohort 日发生目标
事件，并且在 cohort 日之前从未发生目标事件。若目标事件已有 Segment endpoint 的成功
收据，下面的两个静态规则能在一次只读聚合中表达这个交集；前置窗口的 `start` 必须是
该项目可证明的事件历史起点，否则只能声称“在这个有界窗口内首次”，不能声称生命周期
首次。

`custom-event-first-exposure.json`：

```json
{
  "name": "first-exposure",
  "start": "<event-history-start>",
  "end": "<cohort-date>",
  "logic": "AND",
  "event_rules": {
    "logic": "AND",
    "groups": [
      {
        "logic": "AND",
        "rules": [
          {
            "event": "<target-custom-event>",
            "did": true,
            "target": {"field": "PresetAllCount", "aggregation": "PresetAllCount"},
            "did_condition": {"operator": "GTE", "values": [1]},
            "date_range": {
              "type": "static",
              "start": "<cohort-date>",
              "end": "<cohort-date>"
            }
          },
          {
            "event": "<target-custom-event>",
            "did": false,
            "target": {"field": "PresetAllCount", "aggregation": "PresetAllCount"},
            "did_condition": {"operator": "GTE", "values": [1]},
            "date_range": {
              "type": "static",
              "start": "<event-history-start>",
              "end": "<day-before-cohort>"
            }
          }
        ]
      }
    ]
  }
}
```

```powershell
gravity analysis segment evaluate --app main `
  --spec custom-event-first-exposure.json --dry-run
gravity analysis segment evaluate --app main `
  --spec custom-event-first-exposure.json --fields part
```

这段 spec 是目标集合定义和正/负静态窗口控制，不是 I107 已拒绝事件的绕行：当前外部证据
是两个元数据合法的自定义事件在同一 `did=true`、`PresetAllCount/GTE [1]`、静态窗口形状
下都被 Segment evaluate 拒绝，而 Event 与普通 Retention 产品接受了这些事件。仓库另有
#15 的一个元数据支持自定义事件成功控制，但没有保存足以在本地判定事件接受集的公开标识。
因此 SDK 只能在上游实际拒绝后返回
`SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN`，不能在请求前断言某个未登记事件会成功或失败，
也不能据此下“所有自定义事件都不支持”的结论。

在“不持久化分群、不导出用户明细”的约束下，当前没有覆盖已拒绝事件的通用聚合替代：

- 单日 Funnel 能取得 cohort 日参与人数，但不能表达“前置窗口没有发生”；matched Segment
  还会创建持久化分群，已经超出约束。
- 即使允许创建 cohort 日与前置窗口两个分群，当前 Segment 的分群引用只接受 `TRUE`，没有
  已登记的分群差集/补集读取面，两个聚合人数也不能推出交集。
- 只有项目已经维护了语义受治理、set-once 的目标事件首次发生时间属性时，才能复用上节
  “首次付费日属性 cohort”的两次聚合规则，把该属性换成目标事件的首次发生时间。I107 未给出
  这个前提，SDK 不会假设它存在或要求调用方新增写入。

要计算 D1-D7 从未回访，可在上述可执行前提成立时再 AND 一条 `did=false` 的静态
`<return-event>` 规则，窗口为 D1 到 D7；`part` 是首次暴露 cohort 中七日零回访人数。对当前
已拒绝事件，这一步仍由同一个 Segment event-rule acceptance gap 阻断。

普通事件日 Retention 会复用重复参与者且不定义首次暴露，明确不是这个集合的等价替代，
不得把它的结果标成首次暴露留存。

## 已知失败边界

非空 `retention.property_conditions` 与
`retention.query_item_before_after.before_custom` 现在在 compact 编译期返回
`INPUT_INVALID`，不会发请求。普通单起始事件 Retention、空列表和
`query_item_before_after` 的其他已登记控制不受影响。

当前证据不把自定义 SQL 当成替代：用户表与事件表 aggregate join 仍是 draft，仓库没有
上游 join 成功合同。也不使用用户明细拼接；那会引入用户级数据、分页完整性和每用户请求成本。

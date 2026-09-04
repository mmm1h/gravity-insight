# 复合 cohort 留存替代路径

普通“一个起始事件到一个回访事件”的留存继续使用 `analysis query --kind
retention`。下面两类复合 cohort 不发送 Retention endpoint 已拒绝的
`before_custom` 或 `property_condition`；它们只组合现有 Funnel、Segment 和
本地除法。

示例固定使用北京时间 cohort 日 `2026-08-01`、D1 `2026-08-02`。把 `main`、
物理事件、属性和值替换为调用项目已登记的精确值。所有 spec 都先执行 `--dry-run`；
只有分群创建是 mutation，必须审查预览后把同一命令的 `--dry-run` 改为
`--execute`。

## 加性后续指标的当前边界

本节只裁决 Retention 的两个精确 `SumCount` 后续形状，不裁决 Event、Property、
受治理 SQL 产品或其他加性指标：

- `query_item_before_after.after.target.name=SumCount` 的合法载荷能通过旧编译，
  但消费方的配对执行被上游拒绝；补齐 `before`、`formula` 与格式化控制仍失败。
- 普通两事件 Retention 把第二步 `target.name` 改成 `SumCount` 时请求能完成，
  但 `values` 仍是回访人数，`values_another_event` 的零没有测量语义证据。
- 普通两事件 Retention、同起始事件和用户属性过滤已有成功边界。当前证据不能把
  前两项外推为“所有加性指标不支持”，也不能确定拒绝发生在 Retention 服务、
  查询规划器或其他上游组件。

因此这两个 `SumCount` 形状现在于编译/FieldPolicy 预检返回
`RETENTION_ADDITIVE_FOLLOWUP_COHORT_PATH_UNVERIFIED`，`retryable=false`，且在
metadata 或最终查询请求之前停止。`--dry-run` 返回 `status=capability_gap`、
`network_called=false`，其中 `measurement.status=unmeasured`、`value=null`。
不得把未测量写成 0。

### cohort、offset、计数与分母

日 cohort 行位于 `data.y["<cohort-date>"][row]`；`row.group_cols` 是该行的
分组边界。`data.total[row]` 是所选窗口/聚合控制下的汇总行，不得与某个日 cohort
的分子或分母混用。本文示例的 `YYYY-MM-DD` 以项目登记的北京时间自然日解释；
其他时区必须由调用项目显式绑定，SDK 不从事件名猜时区。

- cohort 人数是同一行的 `row.init_num`。
- offset `k` 的回访人数是同一行的 `row.values[k]`；其人数留存分母是该行
  `row.init_num`，对应率槽是 `row.percent_values[k]`。这里的合法 `0` 是已测量的
  人数 0。
- 加性后续值的线槽是同一行的 `row.values_another_event[k]`。当前投影登记了标量
  以及对象中的 `period_event_total`、`cumulative_total`、`per_user`、
  `period_event_total_average` 等候选字段，但没有已验证证据把其中任一字段确认为
  该 cohort/offset 的金额或时长。因此这些路径当前不可消费；特别是标量 0 只表示
  未测量占位，不能解释为金额 0 或时长 0。

拿到独立验证的聚合 `sum_value` 后，必须显式选择分母：

- `per_cohort_user = sum_value / row.init_num`，回答“每个起始 cohort 用户”；
- `per_returning_user = sum_value / row.values[k]`，回答“offset k 每个回访用户”。

两者不能互换；分母为 0 时结果是未定义的 `null`，不是 0。金额还必须绑定同一币种，
时长必须绑定同一单位。这里的“加性”只表示同单位、同口径且用户/事件集合互斥时
总量可以求和，不表示可以跨币种、重叠 cohort 或不同时间窗直接相加，也不自动赋予
任何人均含义。

### 为什么现有替代路径不能补出加性值

下面已有的 Funnel→matched Segment 和属性 Segment 路径能得到聚合人口
`part/percent/total`，所以能构造人数分母与回访人数。它们不能返回金额或时长总和。
仓库当前也没有已验证的“历史固定 Segment membership → 指定 offset 的 Event
`SumCount`”绑定，无法证明成员版本、自然日边界、单位/币种和结果完整性同时保持。
因此不能从这些步骤拼出一条本仓已验证的纯聚合加性后续路径。

调用项目已有的 registered custom-sql 聚合产品在其不可变 readiness 通过时可以作为
项目侧绕行；它不是原 Retention 接口的修复，也不会关闭这个 capability gap。本节不提供
一个伪装成已验证路径的 Event/Segment spec，更不会用回访人数、付费率或其他事件人数
替代金额、时长或 ARPU。

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

## 已知失败边界

非空 `retention.property_conditions` 与
`retention.query_item_before_after.before_custom` 现在在 compact 编译期返回
`INPUT_INVALID`，不会发请求。普通单起始事件 Retention、空列表和
`query_item_before_after` 的其他已登记控制不受影响。

当前通用路径不把未登记的 raw/custom SQL 当成自动替代；这不表示 aggregate join
本身不支持。调用项目已登记且 readiness 通过的 SQL 产品可以成功聚合，但它保持项目侧
产品身份，不能证明原 Retention 表达已修复。也不使用用户明细拼接；那会引入用户级数据、
分页完整性和每用户请求成本。

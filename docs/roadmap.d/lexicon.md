# 合同词表机械扩展验证

- 日期：2026-08-19
- 任务：#231
- 结论：现有产品合同不能机械救回 development 的 41 个 `no_candidate`；纳入其额外自然语言字段后 `no_candidate` 仍为 41，选择层还从 277/336 降至 276/336，因此不保留实现。

## 确凿事实

### 词源盘点

离线调用 `canonical_capability_cards(GravityInsightClient.from_env())` 返回 96 张
canonical 产品卡。现有 `agent_caller_language.py` 的两份手写映射覆盖 50 个
selector、69 条短语；`src/gravity_sdk/agent_*.py` 中可静态取值的 `aliases` 声明有
139 条，均为源码作者写入，并非合同派生。

96/96 张卡已有中文 `description`，且 `agent_lexical_retrieval._card_document()` 已把
它送入词法匹配。96/96 张卡也有 `boundaries`，共 220 条自然语言句，但改前不进入匹配。
卡本身没有 `goals` 或 `does_and_returns`：它们是宿主目录对 caller-language 和
`description` 的投影。必填输入没有中文名；27 条必填输入 schema 说明全部是英文。

因此，这次候选机械规则只读取卡已有的 `goals`、`does_and_returns`、`description`、
`boundaries` 及必填输入显示名/说明，按稳定顺序去重；没有读取题集，也没有新增别名、
映射或按题分支。合成产品卡测试先红后绿：

```
red: Ran 1 test in 0.002s; FAILED (errors=1)
green: Ran 1 test in 0.191s; OK
```

随后撤回该候选实现和测试，因为验收没有通过；最终产品代码、产品卡和题集均未改变。

### development 验收

两次均执行 `PYTHONPATH=src python scripts/agent_usability_eval.py run --split development`；
生产 HTTP 请求均为 0，未运行 holdout 或 final。完整选择层构成如下：

| 类别 | 改前 | 候选规则后 |
| --- | ---: | ---: |
| correct | 238 | 237 |
| correct_multiple_intents | 3 | 3 |
| environment_gap | 6 | 6 |
| multiple_intents_missing | 4 | 4 |
| no_candidate | 41 | 41 |
| target_gap | 30 | 30 |
| wrong_gap | 4 | 4 |
| wrong_intent_candidates | 5 | 5 |
| wrong_product | 5 | 5 |
| ambiguous | 0 | 1 |
| Product selection passed | 277/336 | 276/336 |

参数层从 225/238 变成 224/237：`fillable` 225 -> 224，`route_not_reached` 52 -> 53；
其余构成不变（`gap_not_applicable` 46、`input_template_missing` 13）。终端层不变：
44/53，`explicit_gap` 44、`target_gap_missing` 9、`skipped_production` 283。

`wrong_product` 和 `wrong_intent_candidates` 都没有变差，但也没有任何改善；新增边界词把一条
原本正确选择改成 `ambiguous`。这证明当前合同的额外自然语言是边界/限制语，不能在不把弃权
换成错选的前提下扩大该 41 条的词法召回。

## 推测与后续边界

这并不证明所有未来产品合同永远不能导出词表；它证明当前 96 张卡的既有字段没有提供足够的
正向业务目标语料。若要重启此方向，必须先出现由产品 owner 登记、且不来自评测题面的正向
合同字段，再以新字段作为独立输入重新做同样的改后验收。当前不应继续向 recognizer 添加词法
规则或人工别名。

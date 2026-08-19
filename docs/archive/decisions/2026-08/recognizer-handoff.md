> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 识别器不自信时交出选择权

- 日期：2026-08-18
- 任务：#195
- 结论：公开分和词法分都分不开对错；唯一零损失的离线信号是「没选中产品、只排出至少 3 条互不相同的 raw operation」。这类页返回 `UNRANKED_OPERATIONS` 交接，不猜 top-1。

## 确凿事实

- 工作树：`D:/git-pjt/wt-recognizer-handoff`，分支 `grok/recognizer-handoff`，基线 `dev@a293fe3`。
- 生产 HTTP：**0**。未读、未写 `docs/roadmap.md`。未跑 holdout / final。未改 `DEFAULT_ROUTING_MODE`。
- 测量入口：`PYTHONPATH=src`，`load_cases("development")` + `capabilities_many` + 现成 `route_score`。development **336** 题。
- 基线选择层构成与 `#selection-residual` 相同：`277/336 = 231 correct + 3 correct_multiple_intents + 37 target_gap + 6 environment_gap`。失败：`no_candidate 39`、`wrong_product 7`、`multiple_intents_missing 6`、`wrong_gap 4`、`wrong_intent_candidates 3`。

### 试过的信号（development）

| 信号 | 触发 | 净损失（原本答对） | 净收益（原本答错） |
| --- | ---: | ---: | ---: |
| 公开 `coverage < 0.99` | 2 | 2 | 0 |
| 公开 `confidence != strong` | 0 | 0 | 0 |
| 非 `exact_selector` | 58 | 49 | 9 |
| `intent_only` | 57 | 53 | 4 |
| `analysis.task.handoff` | 4 | 0 | 4 |
| `candidate_count >= 3` | 3 | 0 | 3 |
| `candidate_count >= 2` | 5 | 2 | 3 |
| 词法 `lex_top < 0.5` | 221 | 208 | 13 |
| 词法 top-1/top-2 分差 `< 0.1` | 5 | 5 | 0 |
| 词法 `multiple_matches` | 9 | 9 | 0 |
| 问句长度 `<= 16` | 15 | 15 | 0 |
| `published_term_n <= 1` | 240 | 228 | 12 |

公开卡面一旦发出就把 `confidence` 写成 `strong`、`coverage` 写成 `1.0`（严格 composite / analysis spec / task 都会覆盖）。词法 IDF 覆盖在对题上更低，分差也分不开。

`analysis.task.handoff` 的 4 条净损失为 0，但它是正式任务交接产品，不是「不自信」。把这 4 题改成交接等于拆掉已登记能力。

### 选定信号

人话：**识别器没有选定产品，只排出一页互不相同的 raw operation。**

判定（全部同时成立）：

1. 最前面至少 3 条 `source=operation`，operation_id 互不相同。
2. 没有精确 selector 命中。
3. 问句不是短英文目录查找（≤3 个 ASCII 词；中文句子不算短查找）。
4. 挂在 operation 页后面的非权威 catalog 卡（例如未被选中的 `app_snapshot`）不构成选定。

这条不是扫阈值扫出来的。它描述的是发现链已经放弃权威产品、退回 operation 排序。

development 上触发 **3** 题，净损失 **0**，净收益 **3**：

| case | 改前 | 改后 |
| --- | --- | --- |
| `J11.dev.v3.first-turn` | `wrong_product`（`app.list` + 4 条 raw） | `UNRANKED_OPERATIONS` |
| `J12.dev.v3.first-turn` | `wrong_product`（`app.detail` + raw + 非权威 `app_snapshot` 尾巴） | `UNRANKED_OPERATIONS` |
| `J27.dev.v3.multiple` | `multiple_intents_missing`（3 条互不相同 raw） | `UNRANKED_OPERATIONS` |

选择层仍是 **277/336**。评测把交接记成 `no_candidate` / `multiple_intents_missing`，不记成对；也没有把对题改错。`J40`/`J41` 的重复 `app.app_info.get` / `report.get.query` 产品卡未触发。

短 ASCII 查找（`list apps`、`event`、`account user`、`report`）仍返回 operation 列表，因为那是调用方在浏览目录，不是识别器在猜产品。

## 推测（与事实分开）

- 宿主臂在留出集是 235/240。这 3 题交给 `agent-catalog host` 后，宿主大概率能选对，因为问句是自然语言任务而不是精确 selector。本轮未跑 holdout，这是推断。
- 其余 17 条自信错题（单卡选错产品 / 多意图候选不对 / 已有精确 gap）没有任何零损失离线信号。再加词法规则不值得投入。

## 未做

- 未切 `DEFAULT_ROUTING_MODE`。
- 未改评测装置、题集、层定义、阈值。
- 未把 `analysis.task.handoff` 改成交接。
- 未 push、未碰 GitHub。

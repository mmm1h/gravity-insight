# 写治理架构承载力评估

> 评估基线：`codex/architecture-review` 的 `dev@4646347`；看板轮代码只读检查已完成提交
> `cf71ae72d61076e277a73f64d379b21ea2faf0ea`。后者不是前者的祖先，本文不会把 223 条
> operation 写成当前 worktree 已合入的状态。本文只评估，不修改实现、合同、manifest、测试或既有文档。

## 结论先行

**结论是“有条件地能”。**

能继续承载的是底层执行核：稳定 operation、固定 method/path/auth、显式 `effect=mutation`、
预览摘要、一次性授权、请求摘要绑定、`attempts=1` 和读回校验。这条边界是安全且可复用的，
不应重写。

不能按原样继续复制的是上层写域适配：

1. `mutation_policy.py` 把 `create/update/delete` 当成安全边界；看板轮为 GET delete、
   `move/copy` 再扩一次，后续已知路由还会出现 `share/batch/state_change`。真正应授权的是
   “已登记的稳定 mutation 的精确 method/path/auth”，不是不断增长的动作单词表。
2. marker 同时承担来源标记、幂等关联和所有权替代，但三个域对它的使用并不一致。
   当前代码并非“所有既有对象都只允许 SDK 自建对象”：分群有 3 个修改动作、看板有
   4 个修改动作不校验 marker，看板排序只做“树内存在任一 marker”的弱校验。
3. 创建前检查、有限目录读取、详情读取、marker、预览/完成 envelope、幂等完成等生命周期
   已在三个域各写一遍。继续照抄四个域，保守下限是 **24 个模块触点**（不是 24 个新文件）和约
   **1,332 行重复生命周期职责代码**，尚未计入各域独有 wire、级联删除和 action 实现。
4. `report_mutation.py` 当前已经是 **499 SLOC / 500 硬顶**。即使不看 15 个 legacy ratchet
   文件，写治理面也已经不能再向这个文件加一个正常分支。

因此，在自定义指标、维度表、事件属性治理、SQL 保存查询中的第一个域开始实现前，必须先做
一个窄重构：把 action 词表移出授权边界；把当前账号标识贯通为共享 principal；把 owner
判定做成 fail-closed 的共享策略；marker 保留为创建来源/幂等关联；迁移现有域的既有对象修改
判定。完成这些后，可以继续按领域核心 + surface + Agent handoff 的现有形状开发，不需要全面重写。

## 评估范围与证据强度

- 当前 worktree 是 205 operation / 196 stable 的 `dev@4646347`。
- 看板轮的 205 → 223、12 → 30 stable mutation 来自只读检查 `cf71ae7`。该提交和当前
  HEAD 的共同祖先是 `3295e62`；未 merge、未 checkout、未把它的产品卡总数与当前分支直接相加。
- 代码结论来自当前源文件、相关历史提交 diff、看板完成提交的 blob、合同与质量基线。
- owner 字段结论同时使用稳定合同和 2 次受限生产 HTTP。生产读取没有换 App、扩窗、翻页或重试，
  也没有把响应内容落盘。
- “字段存在”“字段能表达所有权”“字段一定等于当前登录账号”是三个不同命题；下文分别裁决，
  不用一个空数组证明后两个命题。

关键定位便于复核：当前 action/method gate 在 `src/gravity_sdk/mutation_policy.py:22-44`；marker
基础件和跨域写锁在 `src/gravity_sdk/segment_mutation_support.py:27-78`；未强制 marker 的 segment
update/refresh 在 `src/gravity_sdk/segment_mutation.py:281-365`，仅 delete 强制 marker 的位置在
`src/gravity_sdk/segment_mutation.py:375-383`；report 三个 delete gate 在
`src/gravity_sdk/report_mutation.py:128-155,290-317,332-358`；credential 字段和缓存恢复分别在
`src/gravity_sdk/credentials.py:185-203,256-258`。响应字段可从 segment/report/dashboard operation
合同的 `response_projection` 直接复核，质量硬顶来自
`src/gravity_sdk/governance/quality-baseline.json`。

## 一、写治理的真实抽象边界

### 1.1 现在实际有三层，而不是一套通用 CRUD 框架

| 层 | 当前职责 | 判断 |
| --- | --- | --- |
| operation 执行核 | `mutation.py`、`mutation_policy.py`、transport：精确合同、一次性授权、digest、单次请求 | 边界正确，应保留 |
| 通用/半通用生命周期 | marker、锁、有限 catalog/detail、预览与 completed、读回和幂等完成 | 职责通用，但实现散落且由 segment 模块“出租”给其他域 |
| 领域语义 | wire、目标解析、级联/前像、读回等价性、action router、SDK/CLI/Agent | 必须按域保留，不能压成通用 CRUD DSL |

当前的核心问题不是“没有一个万能 mutation adapter”，而是第二层没有成为真正共享层；同时第一层
错误地知道了第三层的动作名称。

### 1.2 三次扩展分别加了什么

| 轮次 | 新增/改变 | 是不是重复 |
| --- | --- | --- |
| 分群轮 `1e699ce` | 首次建立 `mutation.py`、policy、validation、transport 写通道、一次性授权；同时写第一套 segment marker、catalog/detail、预览、读回、CLI/SDK/Agent surface | **不是重复**；这是执行核和首个领域实现 |
| 报表轮 `074929f` | 没改 policy、validation、transport 或 `mutation.py`；新增报表/订阅 core、support、合同集、CLI/SDK/Agent surface | 执行核是复用；marker、preflight、bounded list/detail、preview/completed/readback 是**同类职责的第二份实现** |
| 看板轮 `cf71ae7` | policy 从只准 POST 扩到 GET/POST，action 从三种扩到五种；validation 新增 Kanban 分支；再新增 support、space/folder/dashboard/content cores、router、wire validation、Plan/CLI/SDK/Agent surface | GET delete 和 move/copy 是**一次真实的执行核词表扩展**；生命周期是同类职责第三份实现；树/级联/wire 是真正的领域差异 |

所以“三次完全相同”不成立，“每次都只是新领域代码”也不成立。准确说法是：首轮建立内核；后两轮
重复了领域生命周期；第三轮还暴露了 action 词表不是稳定抽象。

### 1.3 再接四个域会重复多少

估算方法是可复算的，不按总文件体积拍脑袋：对三个现有域的函数按以下职责做 AST/源码行盘点：

- marker 生成/解析/保留；
- create preflight 与 readback；
- bounded catalog/detail；
- preview/completed/idempotent envelope；
- safe target 与标量校验。

得到：segment **21 个函数 / 335 行**，report **20 / 261**，Kanban **23 / 333**；中位数是
**333 行/域**。这些不是逐字重复，而是相同生命周期职责的独立实现。因此四个新域按当前形状的
重复下限为：

```text
4 个域 × 333 行/域 = 1,332 行重复生命周期职责
4 个域 ×（core + support + operation IDs + CLI + SDK + Agent）= 至少 24 个模块触点
```

其中至少 12 个会是新的领域文件（每域 core/support/operation IDs），另外 12 个是 CLI、SDK、Agent
共享 spine 的重复接线触点；复杂域还会像 Kanban 一样增加 router、wire validation 和对象族 core。

这个数不含合同、manifest、文档、测试，也不含独有 action/wire/级联逻辑。现有 reservation 还能给出
动作数下限：自定义指标 4 条，维度表核心 CRUD 3 条（含版本/列/关联生命周期则 9 条），事件属性
明显相关 8 条；SQL 保存查询的精确 route 仅凭当前代码不能确认。因此目前能证明的是前三域已有
**至少 15 条**候选 mutation，不能证明四域的最终总 operation 数。

这些候选已经包含 `share`、`batch`、`state_change`。如果保持 action allowlist，第四次扩 policy
不是风险预测，而是由现有 reservation 词汇直接推出。

## 二、marker 制与 owner 制

### 2.1 marker 约束硬编码在哪里

owner/marker 判定不在共享 policy，而在 9 个领域逻辑文件中：

- 当前分支：`segment_mutation.py`、`segment_mutation_support.py`、
  `report_mutation.py`、`report_mutation_support.py`；
- 看板完成提交：`kanban_mutation_support.py`、`kanban_space_mutation.py`、
  `kanban_folder_mutation.py`、`kanban_dashboard_mutation.py`、
  `kanban_content_mutation.py`。

此外 report 和 Kanban 从 `segment_mutation_support.py` 导入共享写锁；marker regex/解析又各自有变体。
这说明 segment support 已经事实上承担共享基础设施，却仍以领域命名和领域语义暴露。

按产品动作盘点，当前规则并不一致：

| 域 | create | 强 marker gate | 不做 marker/owner gate | 弱 gate |
| --- | ---: | ---: | ---: | ---: |
| Segment，8 个动作 | 4 | delete 1 | metadata update、rule update、refresh 共 3 | 0 |
| Report，6 个动作 | 3 | 3 个 delete | 0 | 0 |
| Kanban，19 个动作 | 3 | 11 | rename 3、dashboard copy source 1 | order.save 1 |

Kanban 的 `order.save` 只要求树中存在任一 SDK marker，不能证明被重排的每个对象归当前账号所有。
因此不能把现状描述为统一 marker ownership policy。

### 2.2 上游到底有没有 creator/owner/user_id

**有 creator/user ID 字段；但并非每个资源都已经证明有直接 owner 字段。**

稳定合同中的静态证据：

- segment list/detail 投影 `create_user_id`、`create_user_name`，并有 update user 字段；
- report list/detail、subscription list、我的模板相关响应投影 `create_user_id/name`；
- dashboard detail 投影 `create_user_id/name`；
- dashboard member / space member 响应投影 `data.creator[].id/uid/name`，并有
  `authUsers[].uid/authority/name`；
- 登录解析已经把上游 `user.id` 放入 `Credential.gravity_id`。

生产证据：

1. 对固定已知看板 space 调用 `analysis.dashboard.space_members.list`，HTTP 200。实际响应的
   `data` 有 `creator` 和 `authUsers` 容器；本次二者为空，所以只证实容器存在，不能用它证明
   creator item 的值或当前账号相等关系。
2. 强制执行登录请求，HTTP 200；返回的 credential 含 `gravity_id`、`company_id`、`email`。

据此可以确定“上游有可用于 owner 比较的 creator/user id 形状”，不能确定以下两点：

- 空的 space-members 样本不能实证 `creator[].uid == 当前 gravity_id`；
- folder/tree 当前稳定投影没有每个 folder 的直接 creator 字段。folder 是继承 space owner、
  还是另有 owner endpoint/字段，当前证据不足。

实现 owner 制时必须按资源建立字段语义证据，缺字段/歧义时 fail closed，不能退回 marker 放行。

### 2.3 marker → owner 不是只换一个判据函数

低层 one-shot 执行链不需要改，但完整改造至少跨四个部位：

1. **principal 生命周期。** `Credential` 有 `gravity_id`，登录时会填；但内部 session 持久化只保存
   token/timestamps，`_load()` 恢复时构造的 credential 没有 `gravity_id`。复用缓存 session 的
   正常进程拿不到当前账号 ID。需要持久化非秘密 principal，或提供可靠的 current-user 读取。
2. **runtime 暴露。** 当前领域 preflight 拿不到 authenticated principal。要从 credential storage /
   runtime 向 mutation preflight 提供只读 principal，而不是让每个域重新登录。
3. **领域 owner 归一化。** segment/report/dashboard 可从 `create_user_id` 或 `creator.uid` 归一化；
   folder 等缺直接证据的资源必须先补合同/语义证据。
4. **所有修改既有对象的动作一致迁移。** 不仅替换现有 delete marker gate，还要覆盖现在未 gate 的
   segment update/refresh、Kanban rename/copy/order 等。否则只是把一部分旧政策换了名字。

建议新增一个窄的共享策略（概念上是 `require_current_owner(owner_id, principal_id)`）：字段缺失、
多 owner 语义不清、principal 缺失时都拒绝；领域 adapter 只负责把上游形状归一化。marker 不删除，
继续用于 create 冲突恢复、来源诊断和读回关联，但不再授予修改权限。

预计代价不是“一函数替换”，也不是“整条链路重写”：约 **4–7 人日**，其中 principal 贯通和共享
policy 1–2 日，迁移 segment/report 1–2 日，Kanban（含 folder 证据）1–2 日，抽取最小生命周期
共享件 1–2 日。上游字段补证所需等待不计入编码人日。

## 三、205 → 223 后的合同与登记一致性

### 3.1 现在靠什么保证

一致性不是只靠一个硬编码计数，也没有一个覆盖全链路的唯一 registry：

- operation source contract 是机器源；compiler 确定性生成 11 个 manifest 和
  `contracts/generated/provenance.json`，`compiler check` 检查生成漂移；quality 检查 provenance
  operation count。
- raw operation catalog 由 manifest 生成，catalog parity 检查 ID/status。
- 产品卡由 canonical card owners 汇总，catalog parity 检查 selector；但产品卡数量仍有测试硬编码。
- 动线台账不是 operation 的 1:1 镜像，本来就不应按每条 operation 增行。
  `agent_usability_expectations.py` 只检查已登记 journey title 存在/唯一；consumer output 测试有
  产品行数与 stable operation 数的硬编码。当前没有“每张产品卡必须且仅有一条 journey”的双向证明。
- 223 完成提交中，当前总数出现在 README 和 8 个现行 docs 页，共 9 处；其中只有两份
  agent-skill 文档可由生成器派生，其余仍靠人工同步和测试中的局部断言。

所以合同 → manifest → provenance → raw catalog 的链是确定性的；产品卡与动线是另一种粒度，只有
局部 parity；面向人的总数仍存在人工漂移面。

### 3.2 加一条 operation 到底改几处

**没有脱离 operation 类型的单一数字。** 可精确回答如下：

| 情形 | 必改登记点 | 数量 |
| --- | --- | ---: |
| 新 stable read，无旧 reservation | source contract、编译 manifest、provenance、golden accession allowlist、stable privacy registry | **5** |
| stable read 从 draft/reservation 晋升 | 上述 5 项再删除旧 source | **6** |
| 看板式 stable mutation 从 reservation 晋升 | source contract、删除 reservation、领域 operation-ID 集、manifest、provenance、golden accession allowlist、领域精确集合/计数测试、全局 write registry 计数测试 | **8** |

`cf71ae7` 的 18 条看板 mutation 正好逐项经过这 8 类位置，因此这个数字可以用提交 diff 复核。
如果该 operation 同时新增产品 action，还要再改 action 实现/映射及其测试；如果新增产品或 journey，
再改产品卡或动线台账。它们不是每条 raw operation 的必改项，不能硬凑进“每 operation 几处”。

另有 9 处现行总数文案需要在一批 operation 变更后同步，但这是**每批一次**，不是每条一次。建议以后
从 provenance/card owner 生成或校验这些总数；不建议把 product 与 journey 强制做成 operation 的
1:1 registry，那会混淆三个不同粒度。

## 四、质量硬顶与拆分顺序

### 4.1 15 个 legacy 文件的当前余量

数字来自 `quality-baseline.json` 硬顶与当前源码重新计算，不是用 baseline 中的旧 current 值相减：

| 文件 | AST 当前/硬顶/余量 | SLOC 当前/硬顶/余量 |
| --- | ---: | ---: |
| `catalog.py` | 5282 / 5332 / **50** | 668 / 722 / 54 |
| `census/coverage.py` | 5900 / 5950 / **50** | 890 / 928 / **38** |
| `census/params.py` | 11768 / 11818 / **50** | 1568 / 1701 / 133 |
| `census/response.py` | 4035 / 4085 / **50** | 551 / 593 / **42** |
| `cli.py` | 4117 / 4167 / **50** | 718 / 788 / 70 |
| `client.py` | 6715 / 6765 / **50** | 1101 / 1161 / 60 |
| `executor.py` | 9099 / 9149 / **50** | 1336 / 1430 / 94 |
| `http_runtime.py` | 3765 / 3815 / **50** | 675 / 751 / 76 |
| `models.py` | 8622 / 8647 / **25** | 1086 / 1158 / 72 |
| `prober/batch.py` | 3752 / 3802 / **50** | 585 / 626 / **41** |
| `prober/drafts.py` | 13059 / 13109 / **50** | 1805 / 1931 / 126 |
| `prober/export_verify.py` | 4491 / 4541 / **50** | 655 / 708 / 53 |
| `prober/promotion.py` | 4382 / 4432 / **50** | 581 / 627 / **46** |
| `registry.py` | 4748 / 4798 / **50** | 747 / 822 / 75 |
| `sql/products.py` | 3622 / 3672 / **50** | 539 / 602 / 63 |

纯按数值，`models.py` 最先撞 AST 顶，只剩 25；SLOC 余量最小的是
`census/coverage.py` 38、`prober/batch.py` 41、`census/response.py` 42、
`prober/promotion.py` 46。但后四个计划域不应触碰 census 文件，所以不能仅按余量声称它们会先撞。

比 15 个 legacy 文件更急的是普通新文件：`report_mutation.py` 已是 **499/500 SLOC**；看板完成
提交中的 `kanban_dashboard_mutation.py` 是 **458/500**。前者任何实质扩展都必须先拆。

### 4.2 按当前排期，谁最可能先撞

1. **`report_mutation.py`：确定第一。** owner 迁移会触碰报表删除判定，而它只剩 1 SLOC。
2. **`models.py`：数值第一、计划上有条件。** 已使用 25 个 AST 增长预算，只剩 25；若 owner 方案
   试图把 principal/ownership 塞进核心模型，必须先拆。更好的方案是不让此次改造触碰它。
3. **`http_runtime.py`：owner 第一批会触碰。** 尚有 50 AST，窄的 principal accessor 应能容纳；
   如果设计需要更多，先抽 credential/principal access，不能抬顶。
4. **`prober/drafts.py`：新写 route 晋升时最危险。** 它会继续承担 write reservation/classification；
   余量虽有 50 AST，但文件已有清楚的读/写分界，下一次需要新增动作分类时应先拆。
5. **`registry.py`：仅在新域需要特殊 request codec 时会撞。** manifest 可表达的字段不要再加代码分支；
   必须加 codec 时先抽 codec 区域。
6. **`sql/products.py` 不应因 SQL 保存查询而增长。** 保存查询是 mutation 产品，应新建窄 domain core，
   不应塞进现有 SQL read/product 大文件。

### 4.3 已经该拆的文件与自然边界

| 文件 | 裁决 | 自然边界 |
| --- | --- | --- |
| `report_mutation.py` | **现在必须拆**，owner 改造前完成 | report core 与 subscription core；共享 bounded lookup/readback 留 support |
| `prober/drafts.py` | **下一次写 route 分类触碰前拆** | 前半 read draft/evidence；后半 write reservation/action classification（约从现有 1337 行附近） |
| `models.py` | **下一次模型变更前拆，可不在本轮空拆** | InputField/RequestSpec；ResponseProjection/Pagination；OperationSpec/load |
| `registry.py` | **下一次 special codec 触碰前拆** | manifest registry/policy；request codecs；parent graph |
| `kanban_dashboard_mutation.py` | owner 迁移若明显增长则同批拆 | create/update/copy；move/delete/order，或按 dashboard lifecycle / tree relocation |

不建议现在批量拆 `catalog.py`、`cli.py`、`client.py`、全部 census/prober 文件。现有 domain router、mixin、
product card owner 已经允许新域绕开共享 spine；没有排期触发的拆分只是高风险机械改名，不能关闭一条
分析动线。

## 五、分批重构方案

### 现在必须做

判据：如果不做，下一域会再次修改安全词表、复制已出现三次的职责，或无法实现“当前账号拥有”
这一明确产品规则。

#### 第一批：授权语义 + principal/owner 最小闭环（2–3 人日）

- `mutation_policy.py` 不再用 action 名字决定能否执行；保留 stable/executable/mutation、精确
  method/path/auth、一次性 receipt 和 digest。GET/POST 仍作为当前真实协议边界。
- 把 credential 中的 `gravity_id` 贯通缓存恢复和 runtime，只提供只读 current principal。
- 新建一个窄共享 ownership 判据；缺 principal、缺 owner、歧义全部 fail closed。
- 先迁移 Segment 和 Report 的既有对象修改；拆 `report_mutation.py`，并把共享写锁/marker 工具从
  segment 命名空间移到共享生命周期模块。
- marker 继续服务 create/readback/idempotency，不作为 owner fallback。

独立验收：旧 operation 能力不减；任意非 owner 的 update/delete 被拒；缓存 session 仍能取得 principal；
missing owner fail closed；一次性授权/摘要/attempts=1 门禁保持。

预计文件面：`mutation_policy.py`；`credentials.py` 及实际 session storage；`http_runtime.py`（必要时
加 transport/client 的窄只读 accessor）；一个新的共享 ownership/lifecycle 模块；
`segment_mutation.py`、`segment_mutation_support.py`、拆分后的 report core/support；以及相应的
contract-boundary 测试。若现有 owner 字段投影已足够，不改 operation 合同。

#### 第二批：Kanban owner 一致化（1–2 人日 + 上游补证）

- 覆盖 delete/move/rename/copy/order，而不是只替换现有 marker delete。
- space/dashboard 使用已知 creator 形状；folder 在 owner 继承语义得到证据前保持 fail closed。
- 如 dashboard core 因迁移接近 500 SLOC，同批按 lifecycle/relocation 边界拆。

独立验收：19 个产品动作逐项都有 create 或 owner policy 分类；不再存在“树内任意一个 marker 即可
排序”的弱授权；字段缺失路径可机器判定。

预计文件面：`kanban_mutation_support.py`、space/folder/dashboard/content 四个 core、Kanban router；
只有在现有 projection 无法提供 owner 时才改对应 read contract/manifest/provenance，并按正常合同门禁
验证，不把补字段混成 owner policy 的隐式副作用。

#### 第三批：抽最小生命周期共享件，并以第一个新域验证（1–2 人日，不含新域独有实现）

- 只抽 marker utility、write lock、scalar validation、preview/completed/idempotent envelope 和 bounded
  scan 骨架；catalog payload、cascade、wire、readback equality 留在领域 core。
- 以自定义指标或字段证据最完整的域做 proof，不先设计四域的万能 schema。

独立验收：新域不再复制上述职责；领域仍可独立测试；没有 plugin、DI、registry 或 CRUD DSL。

### 可以再等等

判据：当前安全性/排期不依赖，且已有窄入口可以避免增长。

- 人类文档里的 9 处 operation 总数自动生成可以后做；compiler/provenance 主链已有强门禁。
- product card 与 journey 的全双向 parity 可以后做；两者不是 1:1，先定义合法的多对一关系才有
  可验收意义。
- `models.py`、`registry.py` 的物理拆分按“下一次触碰即拆”，不做独立大重排。
- SQL 保存查询 operation 和完整 CRUD 数量在 route 未确认前不估工，不用相似 route 名猜合同。

## 六、看着不顺眼但不该现在动的地方

1. **不重写 one-shot mutation executor。** 它的 route/auth/digest/attempts 边界是现有框架最稳的部分；
   owner 是 preflight policy，不应侵入 transport receipt。
2. **不做通用 CRUD DSL、插件系统、DI 或大 registry。** 三个域的级联、wire 和读回等价性确实不同；
   抽掉这些差异会把显式安全检查变成配置解释器。
3. **不删除 marker。** marker 不适合代表 ownership，但适合 create 幂等、冲突恢复、来源诊断。
4. **不强迫 operation、产品卡、journey 1:1。** operation 是线合同，产品卡是用户能力，journey 是闭环；
   数量不同本身不是漂移。
5. **不因后面有 SQL 保存查询就扩 `sql/products.py`。** 新建写域比继续长大文件更符合现有 router 方向。
6. **不批量拆 15 个 legacy 大文件。** 只拆本批必触碰且即将撞顶的文件；其余通过新 domain family
   避开共享 spine。
7. **`mutation.py` 的 segment 化错误文案不漂亮，但不是第一批安全阻塞。** 当共享 ownership error
   taxonomy 落地时顺手改；不要为文案单开重构。

## 七、最终判断题

1. **三次扩展是什么，重复吗？** 首轮建执行核和首域；报表复用执行核但重复生命周期；看板既重复
   生命周期，又因 GET delete/move/copy 扩了错误的 action/method 词表。不同与重复各有一部分。
2. **四域重复多少？** 至少 24 个 Python surface 模块、约 1,332 行重复生命周期职责；算法是三个
   现有域同类函数行数 335/261/333 取中位数 333，再乘四。独有业务逻辑另计。
3. **上游有 creator/owner 字段吗？** 有 creator/user ID 形状；稳定合同覆盖 segment/report/dashboard，
   线上 space-members HTTP 200 看到了 `creator` 容器，登录 HTTP 200 得到当前 `gravity_id`。本次 creator
   为空，folder 直接 owner 也未证实，因此字段值关系仍有明确不确定项。
4. **marker → owner 要动多大？** 不改低层执行核，但不是换一函数：要贯通缓存 principal、runtime
   暴露、领域 owner 归一化，并迁移所有现有对象修改动作。约 4–7 人日，可按域独立验证。
5. **一条 operation 改几处？** stable read 5 处；从 reservation 晋升 6 处；看板式 stable mutation
   晋升 8 处。新增产品/action/journey是条件增量，不能计成每条 operation 的固定项。
6. **谁先撞顶，谁该拆？** `report_mutation.py` 499/500 是确定第一且现在必须拆；15 个 legacy 中
   `models.py` 仅余 25 AST，数值第一。排期相关的下一触碰拆分是 `prober/drafts.py`、`models.py`、
   `registry.py`；owner 迁移要盯 `http_runtime.py` 和看板 dashboard core。
7. **扛不扛，第一批是什么？** 有条件地能。第一批做 action 授权边界纠正、principal 持久化/暴露、
   共享 owner gate，并用 Segment/Report 完成最小闭环，同时拆 499 SLOC 的 report core。
8. **哪些不该动？** one-shot executor、领域显式 wire/级联、marker 的幂等用途、operation/product/journey
   的不同粒度、未触发的 legacy 大文件。原因是它们当前要么是正确安全边界，要么没有排期触发，
   改动不能形成独立可验收能力。

## 八、不确定项与生产请求账本

不确定项：

- 本次空 creator 数组不能证明 item 的实际 `uid` 与当前 `gravity_id` 相等；
- folder 的 owner 字段或继承规则未由当前合同/生产样本证明；
- SQL 工作台保存查询的精确 route 和最终 operation 数无法从当前代码可靠确定；
- 看板提交尚未合入当前 worktree，合并后的产品卡总数和与当前 dev 后续提交的冲突面不在本文推断。

生产 HTTP 共 **2 次**：

| # | 请求/operation | HTTP | 重试 | 翻页/扩窗/换 App |
| ---: | --- | ---: | ---: | --- |
| 1 | `analysis.dashboard.space_members.list`，固定既知 app/space | 200 | 0 | 无 |
| 2 | 账号登录 `/account_center/api/v1/user_login/v2/`，只确认当前 principal 字段 | 200 | 0 | 不适用 |

没有读取 key、holdout/final 或 sealed 数据；没有修改 recognizer、题集、评分逻辑；没有 GitHub、PR、
push、tag 或其他对外动作。

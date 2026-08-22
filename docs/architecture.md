# 架构与概念

当前已交付的 Gravity SDK 是 Gravity Agent Runtime 的合同执行核，不是 Web 自动化层。它把固定上游路径、请求绑定、响应投影、分页、隐私、错误和证据编译成可由 CLI、SDK、Plan 与 Agent 共用的产品面。批准的目标架构在保留该内核的前提下增加版本化方法、Context、Trust 和团队分发；目标面只有在对应需求落地后才构成当前接口。

## 产品边界

- Runtime 拥有物理数据合同、执行纪律、机器可判定结果，以及可复用 Semantic 类型/Schema、通用指标/方法定义、版本化 URI 和单位/可加性/时间粒度/依赖/冲突/公式结构校验。
- 调用项目拥有具体游戏的活动名称、SKU 实值、App/埋点绑定、项目专属公式参数与生效窗口、部门口径和经营判断。
- Gravity Web 只用于受控取证，不是运行时依赖。
- Stable 产品可执行；draft 和 gap 只描述缺失证据，不提供旁路。

## 目标 Gravity Agent Runtime

目标产品由相互分离的职责面组成：

```text
Host Agent
  Codex / Claude Code：理解意图、编排工具、最终推理与表达

Runtime Plane
  Journey / Capability Trust / Data Quality
  Business Semantic / Operator / Model / Context Pack
  Existing Product / Composite / Plan execution kernel
  Analysis Result / governed Action / Artifact / Receipt

External Control Plane
  Skill and trusted-code build/publish/download/verify
  exact lock / staging / canary / activation plan / rollback
  external Installer or CI-CD performs activation

Calling Project
  concrete App/activity/SKU/tracking bindings, project overlays and report language
```

Skill 是声明式方法与依赖合同，不是执行器；Context 是有来源/权限/时效的 `role=data`，不是指令。外部 Provider 使用独立进程级 RPC 次数/并发/超时/取消/输出/circuit 边界，内部网络与自报统计不冒充 Runtime enforcement；subprocess 不继承 Gravity 凭据、不用 shell、限制 cwd 并终止进程树。Operator 是静态映射、版本化且有 golden 的确定性代码，Model 只在 lineage/evaluation/approval/expiry/horizon 全部通过时支持生产 claims；现有 Product/Composite/Plan owner 不变。

完整目标架构以仓库内 [architecture source](../specs/agent-runtime/architecture-source.md) 为唯一上层来源，并由 [directive](../specs/agent-runtime/directive.json) 绑定 digest；具体交付按 [Requirement Index](../specs/agent-runtime/index.md) 拆分。当前源码和测试证明迁移起点；旧产品假设可以在 R00 后显式迁移，但安全、权限、隐私、写入确认、生产请求和能力不退化规则不能由需求自行豁免。

所有计划单元只集成到 `dev`；完整计划完成和整体验收前不向 `main` 推广。

## 三条调用路径

### 精确执行

调用方已知产品、recipe 或 operation，直接由 CLI/SDK 进入 resolver，完成 workspace 绑定、输入校验、合同执行和结果封装。

### 渐进发现

`agent-catalog categories → category → describe` 离线提供领域、selector、required inputs、schema 和下一步。调用方能选择时提交 host selection；否则 recognizer 只提供保守候选或结构化弃权。

### 显式 Plan

Plan 把多个已登记产品组织为 versioned DAG。每个节点先验证 kind、request、binding target、effect 和依赖，再在一个全局有界 worker pool 中执行就绪节点。Checkpoint 允许局部恢复，不允许绕过合同重放。

## 合同流水线

```text
source contract
  → deterministic compiler
  → manifest + provenance
  → resolver / adapter
  → executor + pagination
  → projection + privacy + semantic status
  → versioned result envelope + receipt
```

Source contract 声明固定 host/path/method、输入 schema、分页、响应投影、effect、stability 和证据。Compiler 只做确定性编译；manifest 与 provenance 漂移会使门禁失败。

## Workspace 与 Resolver

Workspace 保存 App alias、登记 SQL 产品、recipe、参数化 Plan 和调用方词面上下文；项目 Semantic Source 保存具体活动/SKU/埋点绑定、公式参数和生效窗口。Runtime Semantic Registry 提供可复用类型、通用定义、URI 和校验；两者都不保存凭据、上游原始响应或任意 SQL。

Resolver 负责把 alias 和模板参数绑定到精确产品。已知输入一次完成；未知能力先发现再执行。父资源、metadata 或 contract fingerprint 变化时重新解析或失败关闭，不沿用猜测值。

## 产品与原子 operation

原子 operation 提供最小 wire 合同；产品可以组合多个 operation、并发读取、局部派生和固定诊断。产品卡描述调用方问题、输入、边界和交接，不复制底层执行实现。

新增能力优先复用现有 composite / Plan adapter / Agent card 三面。批准的需求可增加类型化 Skill、Semantic、Operator/Model、Context Provider 或 Action Connector Registry，但不得建立任意远程代码插件、第二套路由或第二套执行框架。

## 并发与请求预算

- 全局 pool 约束峰值 in-flight；各 adapter 不再乘并发。
- 独立读取可并行，父子依赖、写入和生成产物串行。
- 提高并发不能提高请求总量；分页、重试和 fan-out 都受显式预算约束。
- 同进程与磁盘 metadata cache 可降低冷启动成本，但 mutation 后失效，身份维度不可共享。

## 结果信封

所有产品返回 versioned envelope，至少能表达：

- success、empty、partial、error 或 capability gap；
- 解析后的日期窗和结果来源；
- 分页、截断、组件状态与 receipt；
- warning、diagnostic、drift audit、interpretation 和 allowed claims。

HTTP 200 只表示传输完成。Semantic status 层负责把上游业务拒绝、合法空和成功数据分开；未审查的上游错误正文不传播给调用方。

## 写入效果

Mutation contract 必须逐项登记 effect、owner/marker、preview、单次执行和 readback。预览与执行共享权威输入；执行不自动重试。对象、关联或布局未按预期回读时返回不确定状态，让调用方重新读取。

## 数据与隐私

- 请求日志、receipt 和 evidence 只保存结构、计数、指纹与值无关结论。
- 用户级输出只写调用方指定文件，不进入仓库、日志或模型上下文。
- 未登记响应字段默认省略并记录 drift；敏感身份、条件值和凭据从错误中清洗。
- 重要结果在交付前按声明的可加性、第二 route 或 list/export 行数对账。

## 维护入口

修改合同或产品先走[扩展地图](maintainers/extending.md)；公开接口见 [CLI](reference/cli.md)、[SDK](reference/sdk.md) 和 [Plan](reference/plan.md) 参考；历史设计不作为当前真相。

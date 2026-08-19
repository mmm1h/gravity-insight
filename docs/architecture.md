# 架构与概念

Gravity SDK 是合同执行核，不是 Web 自动化层。它把固定上游路径、请求绑定、响应投影、分页、隐私、错误和证据编译成可由 CLI、SDK、Plan 与 Agent 共用的产品面。

## 产品边界

- SDK 拥有物理数据合同、执行纪律和机器可判定结果。
- 调用项目拥有业务词、活动/SKU、App alias、时间窗和派生公式。
- Gravity Web 只用于受控取证，不是运行时依赖。
- Stable 产品可执行；draft 和 gap 只描述缺失证据，不提供旁路。

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

Workspace 保存项目意图：App alias、登记 SQL 产品、recipe、参数化 Plan 和调用方语义。它不保存凭据、上游原始响应或任意 SQL。

Resolver 负责把 alias 和模板参数绑定到精确产品。已知输入一次完成；未知能力先发现再执行。父资源、metadata 或 contract fingerprint 变化时重新解析或失败关闭，不沿用猜测值。

## 产品与原子 operation

原子 operation 提供最小 wire 合同；产品可以组合多个 operation、并发读取、局部派生和固定诊断。产品卡描述调用方问题、输入、边界和交接，不复制底层执行实现。

新增能力优先复用现有 composite / Plan adapter / Agent card 三面。共享入口接近质量棘轮时增加窄领域 router，不建立通用插件系统。

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

# 架构与概念

## 系统定位

Gravity SDK 是受控读取层，不是通用 HTTP 客户端，也不是业务知识库。它把上游易变的接口转换成稳定、可发现、可校验的 operation，并统一认证、限流、重试、分页、字段投影、隐私和错误输出。

```text
调用方 / Agent
  ├─ 业务语义：由调用方或 work-dashboard 解析
  └─ Gravity SDK
       ├─ Insight：manifest 授权的结构化读取与导出
       ├─ SQL：固定端点上的受控聚合产品
       ├─ Metadata：跨 App 物理元数据目录
       ├─ Census：前端路由发现和漂移检查
       └─ Contracts / Probes / Quality：能力准入和安全门禁
```

## 核心层级

### Operation catalog

稳定 `operation_id` 是公共接口。每个 operation 声明固定 host、path、method、输入、响应投影、分页、稳定性、隐私级别和最小探针。上游版本变化应由 manifest 或 codec 吸收，不应迫使调用方改 URL。

状态含义：

- `stable`：默认可执行；
- `experimental`：只有显式允许时可执行；
- `permission_unavailable`：合同存在，但当前账号无法完成验证；
- `blocked_privacy` / `blocked_write`：有意不开放；
- `deprecated`：保留身份，不应继续调用。

### Runtime

Insight 与 SQL 复用账号登录和进程级 HTTP 运行时，但保持独立策略：

- Insight 必须消费 manifest 的一次性授权；
- SQL 只允许固定 custom-SQL host、path、method 和请求形状；
- 认证刷新采用 single-flight，避免并发重复登录；
- 响应只暴露合同允许的字段，新字段默认隐藏并产生漂移信号。

### Metadata catalog

`gravity metadata sync --all-apps` 保存 App、事件和属性的当前物理事实。它适合校验事件是否存在、字段是否可用以及类型是否漂移。

它不保存或推断业务模块、活动配置、SKU、活动窗口和分析口径。这些语义属于调用产品。

## 查询路由

默认顺序：

```text
业务问题
  → 解析业务实体与口径
  → 搜索 stable Insight operation
  → 能等价表达：Insight
  → 不能等价表达：检查受控 SQL 产品
  → 两者都不能：报告能力缺口，不生成任意请求
```

即使 Insight 需要多轮并发读取，只要语义等价，也应优先于一条重 SQL。SQL 只承担 Insight 无法表达的复杂跨表、窗口函数、自定义 CASE、特殊用户分层或 Evidence 产品。

Insight 批量 worker 上限和 SQL 并发上限是独立安全合同；调用方不得用自建线程池绕过 CLI 或运行时限制。

## 数据与隐私边界

- 凭据、token、Cookie、Authorization 和登录 payload 不进入日志、stdout、fixture 或 Git。
- 用户级读取只有在 manifest 明确登记并通过隐私审查时开放。
- 普通 read 不自动写仓库、发布 Evidence、上传、分享或修改上游资源。
- 导出是独立 effect，必须经过导出合同和本地落盘策略。

## 扩展原则

新增 stable operation 需要：端点证据、只读理由、输入/输出合同、字段投影、隐私分类、脱敏 fixture、最小 live probe 和测试。静态发现或页面可见不等于可开放。

具体流程见 [新增受控能力](maintainers/operations.md)。

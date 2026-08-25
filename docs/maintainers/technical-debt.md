# 技术债清单
只登记当前源码或质量门禁能证明、且有明确退出条件的结构债务；产品缺口、上游无数据、历史事故和一次性工作不登记。
每轮仅更新受影响条目：满足退出条件即删除正文并在末尾留一行历史，完整旧内容见归档快照。

## 当前条目
登记于 2026-08-13，依据 `dev@8fd278e` 的源码与质量门禁审计。
### 1. Material/Promotion 重复实现多平台结果重建
**状态（2026-08-20）**：`component_aggregate.py` 已下沉 `aggregate_status`、`aggregate_exit_code` 与单组件
category→exit；两产品仍各自拥有 operation、字段和文案。
- **已证实的分叉**：Material receipt 接受 `size=1..1000` 且非空 totals 可大于观察值；Promotion 固定 `size=10`
  且 totals 必须等于观察值。`safe_component`/`_safe_success`、`product_envelope` 分别持有单/多 operation、
  Promotion App/window/metrics binding、允许 data 字段和领域结果字段。
- **剩余证据债**：Material `_safe_rows` 是固定字段/scalar/key 规范化；Promotion `safe_promotion_rows` 合并
  平台和 request metrics、拒绝非字符串 key，并对合同派生 opaque JSON 实施独立深度/元素/大小边界和无值失败。
  `_primary_error` 缺失 error 时各自调用 `contract_component`，operation identity 和文案不同。现有 characterization
  未覆盖全部 Mapping/key/scalar 与 malformed-error 边界。
- **触发条件**：任一产品改标量 row copy/primary error selection，或出现第三个同类多平台产品；page receipt
  已确认是领域差异，单侧改动不触发。
- **退出条件**：仅在 characterization 覆盖两边全部上述边界时，下沉一个已证明等价的窄操作；allowlist、
  operation identity 和 fallback 文案留在 owner。不能无 mode/callback 直调就保留分叉；不统一整文件或造 DSL。

### 2. legacy promotion snapshot 的兼容分支仍缺正式绑定
**状态（2026-08-20）**：`primary` 的 21 个正式平台复用 Promotion Performance 的 App、日期、平台/指标和结果
绑定；其余层级及 `bing/xiaohongshu/taptap/wechat_video` 仍走兼容读取。

- **证据与边界**：兼容路径从 stable inventory 精确匹配后透传 raw input，返回
  `gravity-insight.composite.promotion.v1` 和 `formal_binding_validation=not_performed`；零匹配 unavailable，
  多匹配或不适用 shortcut 执行前失败。`query_fields` 仍过 `FieldPolicy`，但无正式 App/日期/指标必填和结果绑定。
  无消费者遥测时删除会损失读取能力，且 Agent/Plan 不宣传该路径。
- **触发条件**：兼容平台/层级出现第二个同资源 stable read，取得正式输入/结果绑定，或能证明无消费者。
- **退出条件**：为所有保留兼容平台/层级建立不损失读取能力的正式请求/结果绑定并移入正式路径，或证实无消费者
  后删除；不得以 raw `promotion query` 替代 snapshot 聚合职责。

### 3. 在线输入解析的两次闭环依赖「上游稳定 ID 不复用」，而这证明不了
- **证据**：9 条动线首次交付能力/完整目录、第二次在线重解析后执行；调用方按稳定 ID 选择，但上游无 revision/ETag，
  不能证明已删对象的 ID 永不复用。
- **触发条件**：观察到 ID 复用，或上游提供 revision/ETag/版本号。
- **退出条件**：把可校验版本标识纳入第二次解析前置校验，使 ID 复用 fail-closed；此前不扩大该模式。

### 7. 稳定 operation 的分页形状仍有系统性证据债
- **证据**：当前 237 条编译 operation 为 `60 complete / 177 unknown`，228 条 stable 为 `60 / 168`，stable
  `page_info` 子集为 `60 / 58`；证据为 `97 production / 9 wire / 131 template`。仅 `template_default` 的 49 条
  live `page_info` 被 `reconcile_pagination_audit` 标为 `shape_unproven`。
- **当前缓解**：合同分别声明 `completeness`/`pagination_evidence`，无证据为 `unknown`；原子读取、audit、Plan、
  composite 均传播它，`all_pages` 遇未知/前缀返回 capability gap。已确认 A 的自动读取为 Multidim metadata、
  Material Performance、Business Pulse；两个 report query 均按实测 B 不续页。缺 `total_page` 的 `read_all`
  停第一页并标 `unknown`，满页续读须 `continue_without_total`；单次无 `page_info` 不能证明永不截断。
- **计划与触发**：[分页生产证据采集计划](pagination-evidence-plan.md) 将 168 条 stable unknown 分为 86 条
  可证伪目标（60、26 两批）和 82 条永久 unknown（47 非集合、35 无终止/总数信号）；改 unknown 分页、
  新产品依赖其全集或取得 production/wire 字段证据时触发。
- **退出条件**：逐条以同 method+path production sketch/wire 字段把 58 条 stable `page_info` unknown 归入真实形状
  并修正合同；另 28 条 stable collection unknown 须取得可证伪完整性信号或转永久 unknown；不得用合同声明、
  短页、满页启发式提级或全量生产探测。

### 9. Windows Provider RPC 在 Job Object 绑定失败后仍可启动
- **可测事实**：`provider_rpc_transport.py:228` 忽略 `attach_windows_job(process)` 的 `False`；绑定失败后 RPC 继续运行，
  子进程及后代不受 Job 关闭约束，可越过 timeout/会话生命周期。
- **影响边界**：仅 Windows Provider RPC 且 Job 无法绑定的子进程；不改变调用方授权模型。
- **退出条件**：绑定失败须在 RPC 前以稳定本地错误终止，并有测试证明不留可运行 Provider 子进程；成功绑定的 timeout、
  取消和关闭语义不变。

### 10. Repo Context 的忽略规则读取会静默退化为空集
- **可测事实**：`repo_context_index.py:279-286` 对链接、不可读或非 UTF-8 的 `.gravityignore` 返回空规则；`.gitignore`
  未绑定索引快照，读取失效或漂移时路径过滤可无报告退化。
- **影响边界**：已批准的按路径过滤模型不变；只有规则不可靠或未快照绑定时，可能纳入本应排除的路径。
- **退出条件**：把两个 ignore 文件的可读、非链接、UTF-8 内容/摘要绑定快照；任一条件不满足或使用前变更时 stable
  fail-closed，并有测试。

### 11. `gravity_sdk` 根目录模块扁平化扩大了变更定位范围
- **可测事实**：`src/gravity_sdk/` 平铺 574 个 Python 模块，本轮 `dev` 改动涉及 142 个；领域边界主要靠命名而非子包，
  跨领域定位和审查集中在根目录。
- **影响边界**：不改公开导入或运行时行为；只增加所有权辨识、审查和后续迁移成本。
- **退出条件**：获批结构迁移 Requirement 记录写入范围、现状刻画、消费者迁移/回滚，并迁入至少一个经证明的高耦合领域，
  同时保持公开 surface 与能力；不得以改名或空目录关闭。

### 12. Provider 与 Adaptive Governor 测试仍含全量门禁顺序相关的计时 oracle
- **可测事实**：Provider 私有 gap 测试单跑约 0.30s 全过；全量时共享 `timeout_ms: 200` 与 Python 冷启动竞争，
  `PROVIDER_RPC_TIMEOUT` 会误成 `PROVIDER_RPC_MALFORMED`；`test_adaptive_governor.py:483` 也把 0.5 秒真实等待
  当 oracle。修复进行中，未实际关闭前保留。
- **影响边界**：只影响全量测试确定性和失败分类，不改变产品授权或功能语义。
- **退出条件**：以同步事件/可控时钟替代真实等待，Provider fixture 不再竞争冷启动超时，相关测试在完整门禁稳定给出
  预期分类；关闭时删除正文并在下方留一行历史。
## 已关闭

- 2026-08-25：#8 Title Package 已从编译合同派生 opaque JSON 字段，复用有界深度、元素和大小投影；未登记和非 opaque 标量规则仍 fail-closed。
2026-08-19 以前关闭项见[清理前快照](../archive/snapshots/technical-debt-2026-08-19.md)。
- 2026-08-20：Census POST 读词元债关闭，`uncovered_read` 仅保留安全方法/exact 静态确认，其余为
  `unsafe_unknown`/`static_read_candidate` 且 draft selector 不消费。
- 2026-08-20：Agent 有界无 spec 路由改用 `NO_SPEC_PRODUCTS`，`REPORT_PRODUCTS` 保留同对象兼容别名。
- 2026-08-25：CT03 跨产物绑定、exact revision/index 与跨 Python archive 确定性缺口关闭。

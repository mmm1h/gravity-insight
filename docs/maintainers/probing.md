# 探测安全

正式查询、`probe`、`probe_all` 和 `doctor --live` 只通过受控 SDK 执行。浏览器只用于无法从静态资源或合同确认的页面行为，不是生产查询路径。

## 在线 probe

- 在线入口先在本地证明目标具有读语义，再检查凭据或构造 transport。`POST` 路由如果唯一读证据是
  census 的 `read_action_path_token`，默认以 `UNSUPPORTED/local`（CLI exit 4）失败关闭：路径词元
  只说明名字像读，不能排除写操作。GET、`safe_http_method` 和
  `route_registry:read_contract_not_verified` 不受这条弱证据闸门影响。
- 人工确认只按精确的 `method + path` 放行，记录在
  `src/gravity_sdk/contracts/routes/probe-read-confirmations.json`。每条必须包含 `reviewer`、
  `reviewed_at`、`decision=confirmed_read`，以及至少一条带 `source/detail` 的静态控制流证据；
  缺字段、重复记录、路径变化或确认文件损坏都失败关闭。确认前只读前端控制流、UI 文案和同作用域
  调用链，不得用在线请求判断是否为写。Draft prober 只对该文件完整校验通过的精确 POST 路径跨过
  通用 Registry 的写词元守卫；这不修改 stable Registry，也不放行未确认路径或相邻 mutation。
- 先通过全部离线合同、字段登记、测试和质量门禁。
- 使用合同声明的最小 App、时间、页数和字段。
- 不为“找非空结果”扩大到长时间窗、翻页或全量读取。
- 记录 operation、状态、合同指纹和脱敏错误；不记录 token、Cookie、请求头或原始用户行。
- `permission_unavailable`、`empty` 和 `contract_changed` 必须分开处理。
- 发现未登记字段时以 `contract_changed_additive` 失败关闭；确认字段路径与类型后登记并暴露，
  不把漂移检测重新变成字段级隐藏。

## 浏览器边界

Gravity 报表编辑态存在未保存状态保护。探测不得接管用户已有标签或绕过页面守卫。

1. 优先读取公开 bundle、路由定义和网络合同。
2. 必须确认页面行为时，只打开独立的一次性标签。
3. 不进入或修改报表编辑态，不点击保存、分享、订阅、导出、筛选或字段配置。
4. 不注入脚本清除 dirty，不移除路由守卫或 `beforeunload`。
5. 出现“未保存”提示时保留页面并停止，不自动确认退出。
6. 只关闭本次探测创建的标签。

浏览器观察到的接口必须进入 manifest、Policy、响应投影和测试后，才能成为 SDK 能力。

## 停止条件

遇到以下情况立即停止在线探测：

- 请求可能写入、分享、授权或删除上游资源；
- 无法证明目标 host/path 在允许范围；
- 需要未登记字段、未证实 schema 或不受控输出才能继续；
- 重复认证失败、限流或合同漂移；
- 用户页面存在未保存状态。

2026-08-08 的 `analysis.setting.query` 三份 probe receipt 保留为不可变历史安全证据，不删除、不改写，
也不计作读语义确认。该 draft 已以 `effect=mutation`、`mutation_route_not_read` 和
`free_text_fail_closed` 标注；后续入口会在请求前由上述闸门拒绝。

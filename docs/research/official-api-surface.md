# 引力官方 API / SDK / 技术文档面调研

调研日期：2026-08-16

仓库基线：`dev@4d32f29`，本 worktree 的 `codex/official-surface`

比较基线：987 条 census 路由、223 条 operation contract

## 结论先行：补充官方口径

**[实证] 引力确实发布了官方开放 API、开发者文档和官方 SDK。** 入口包括：

- 当前官方帮助中心：[help.gravity-engine.com](https://help.gravity-engine.com/)；
- Gravity Web 内的开发者入口：`https://web.gravity-engine.com/#/manage/develop`；
- 公开开发者接口目录：当前 Web 静态 bundle 中列出 22 条报表、导出和配置类
  `/openapi/api/v1/...` 路径；
- 帮助中心另有服务端事件采集、媒体 Token 接入和归因/事件回调文档；
- 服务端和客户端 SDK 文档，以及 PyPI、npm、GitHub 等公开分发入口。

**[实证] 但这些官方面不能替代当前逆向口径。** 与当前分析 SDK 直接相关的 22 条官方目录路径只占
987 条 census 路由的
`22 / 987 = 2.23%`；它们与 223 条 operation 的方法与路径精确交集为 **0**。按业务语义保守匹配，
只有 **13 / 223 = 5.83%** 的 operation 能找到官方对应能力，而且都不是可直接替换的 wire contract。

**[推测] 因此应选择“补充”，不是“切换”，也不是原样“维持”。** 官方口径应成为其明确覆盖能力的
首选候选传输面，尤其是事件分析、若干明细/报表查询、全量事件导出和事件回调；其余至少
210 条 operation 仍须依赖现有 Web 口径。每一条实际迁移都应先用本租户获批的开发者应用做响应、
分页、字段、权限和能力无损验证，不能仅凭名称相近切换。

边界可以机器化为：

1. 官方开发者目录或官方帮助文档明确列出的 `/openapi/api/v1/...` 能力，归为 `official` 候选；
2. 只有通过租户实测、投影/隐私审查和能力无损检查后，才从 `candidate` 升为正式官方 transport；
3. 没有官方对应的分析、配置和导出能力继续使用 `web` transport，并保留现有 fail-closed 治理；
4. 同一路径只是出现在 Web bundle 的“API 目录值”中，不等于它是 Web 页面实际调用的会话端点。

## 证据口径

沿用 [vendor-agent-landscape.md](vendor-agent-landscape.md) 的标注规则：

- **[实证]**：官方公开页面、官方域名静态资源、公开包/源码，或当前仓库中可复现的事实；
- **[厂商宣称]**：只有厂商介绍或说明、尚未由本租户请求验证的产品能力；
- **[推测]**：由证据推导出的架构选择、稳定性判断或未验证边界。
- **[不确定]**：现有证据不足，本文明确不作结论。

“未发现”只表示本次列明范围内没有找到，不扩写为“厂商绝对不存在该能力”。

## 1. 官方面到底有没有

### 1.1 开发者门户与 API 文档

**[实证] 有。** 当前官方帮助中心包含以下可公开访问的开发者文档：

- [服务端接入概览](https://help.gravity-engine.com/docs/server-integration-overview)
- [签名生成](https://help.gravity-engine.com/docs/signature-generation)
- [服务端状态码](https://help.gravity-engine.com/docs/status-codes)
- [报表查询目录](https://help.gravity-engine.com/docs/report-query)
- [事件分析报表](https://help.gravity-engine.com/docs/events-report)
- [多维报表](https://help.gravity-engine.com/docs/multi-dimensional-report)
- [素材数据报表](https://help.gravity-engine.com/docs/creative-data-report)
- [用户信息报表](https://help.gravity-engine.com/docs/user-information-report)
- [用户订单报表](https://help.gravity-engine.com/docs/user-order-report)
- [变现细查报表](https://help.gravity-engine.com/docs/ad-drilldown-report)
- [报表指标查询](https://help.gravity-engine.com/docs/reporting-metrics)
- [应用列表](https://help.gravity-engine.com/docs/app-info)
- [应用创建](https://help.gravity-engine.com/docs/create_app)
- [素材 ID 映射](https://help.gravity-engine.com/docs/creative-query)
- [事件导出任务](https://help.gravity-engine.com/docs/events-export)
- [事件导出结果](https://help.gravity-engine.com/docs/events-download)
- [事件回调](https://help.gravity-engine.com/docs/events-callback)
- [事件采集 Restful API](https://help.gravity-engine.com/docs/restful-api)
- [刷新微信/抖音 Access Token](https://help.gravity-engine.com/docs/refresh-wechat-douyin-access-token)
- [归因回调](https://help.gravity-engine.com/docs/attribution-callback)

**[实证]** 旧入口 [doc.gravity-engine.com](https://doc.gravity-engine.com/) 仍可访问，但页面明确引导到新文档，
并注明旧站不再维护。它可作为历史证据，不能作为当前契约来源。

**[实证]** 官方文档要求先在 Gravity Web 的“管理中心 → 开发者中心”创建开发者应用，审批通过后取得
`app_key`；页面给出的直接入口是 `https://web.gravity-engine.com/#/manage/develop`，并写明审核通常需要一个工作日。

### 1.2 公开开发者目录中的 22 条接口

**[实证]** 2026-08-16 重新获取
`https://web.gravity-engine.com/assets/api-B9xDXL35.js`，文件大小为 139,278 bytes，SHA-256 为
`8c219f2b288b4c6b852fadf396be5b1549cfdc66ba1b81de9eca392748457e2d`；它与仓库冻结的
`src/gravity_sdk/census/data/bundle-snapshot.json` 对应。bundle 的开发者目录常量列出以下 22 条路径：

| 类别 | 官方目录路径 | 数量 | 证据 |
| --- | --- | ---: | --- |
| 报表查询 | `/report/order/list/`、`/report/user/list/`、`/report/material_get/`、`/report/adreport/custom_get/`、`/report/monetization_detail/list/`、`/report/events/list/`、`/report/metrics/list/` | 7 | **[实证]** bundle 目录，且均有公开帮助页 |
| 事件元数据 | `/event/event_info/`、`/event/event_list/`、`/event/event_property_list/`、`/event/user_property_list/` | 4 | **[实证]** bundle 目录；本次未找到逐接口公开帮助页 |
| 推广对象 | `/user/promoted_object/create/`、`/user/promoted_object/list/` | 2 | **[实证]** bundle 目录；本次未找到逐接口公开帮助页 |
| 事件导出 | `/download/event/submit_task/`、`/download/event/query_result/` | 2 | **[实证]** bundle 目录和公开帮助页 |
| 开放应用 | `/open_app/create/`、`/open_app/list/`、`/open_app/edit/callback_url/` | 3 | **[实证]** bundle 目录；创建/列表有逐接口页，回调配置有功能页 |
| 素材上传 | `/asset/material/manage/local/check/`、`/asset/material/manage/local/upload/`、`/asset/tos/authorization/` | 3 | **[实证]** bundle 目录及官方素材上传 SDK 文档 |
| 素材映射 | `/material/id_map/` | 1 | **[实证]** bundle 目录和公开帮助页 |

表中路径都以 `/openapi/api/v1` 为共同前缀。

**[实证]** 987 条 census 中另有 5 条 `/openapi/api/v1/open_develop/...` 路径；它们是 Gravity Web
管理开发者应用所用的页面端点，证据类型为实际请求候选，不属于上述对外开发者目录。故官方目录比较分母中的命中数是
22，不是所有带 `/openapi` 字样的 27 条路径。

### 1.3 不在 22 条目录中的官方集成面

**[实证]** 22 是 Web 开发者页面展示的报表、导出和配置接口目录，不是所有官方集成能力的总数。
当前帮助中心还明确公开了至少两个固定的 Gravity HTTP endpoint：

| 能力 | 官方文档路径 | 方向与鉴权 | 与本仓库关系 |
| --- | --- | --- | --- |
| 事件/用户属性采集 | `POST /event_center/api/v1/event/collect/` | 客户 → Gravity；query 使用当前 App `access_token` | **[实证]** 写入/采集能力，不属于 223 条读取 operation |
| 微信/抖音媒体 Token 刷新 | `POST /event_center/api/v1/base/media/access_token/refresh/` | 客户 → Gravity；App `access_token` 加 body MD5 `sign` | **[实证]** 凭据同步能力，不属于仓库业务范围 |

**[实证]** 这两个固定路径都不在 987 条 Web bundle census 中，也不在 22 条开发者目录中。这说明公开文档能发现
前端抓取之外的官方能力，但没有增加本仓库 223 条读取 operation 的对应数。

**[实证]** 事件回调和归因回调是 Gravity → 客户自有 URL 的数据推送，因目标 URL 由客户配置，不存在一条可与
987 清单做固定 path 交集的 Gravity endpoint。同步归因则是客户端注册流程的模式，不是帮助页单列的固定查询接口。

后文的 `22/987` 专指“22 条官方开发者目录 path 与 987 条前端 census 的交集”，不是声称官方总共只有 22 个
HTTP/SDK 能力。

### 1.4 Swagger / OpenAPI 描述文件

**[实证]** 本次在官方域名、当前公开 bundle 和搜索结果中检索了 `swagger`、`openapi.json`、
`openapi.yaml`、`api-docs`、`Postman` 等入口，未找到可下载的 Swagger/OpenAPI Specification、
Postman collection 或机器可读 schema。官方把对外接口称为 OpenAPI，并不等同于发布了 OpenAPI Specification 文件。

**[推测]** 不能据此断言私有租户门户或厂商内部绝无 schema；当前只能确认“公开面未发现”。

### 1.5 官方 SDK 和客户端库

**[实证] 有 SDK，但用途与本仓库不同。** [SDK 总览](https://help.gravity-engine.com/docs/sdk-overview)
列出 Android、iOS、Web、Unity、Flutter、Cocos、Laya、Egret、小程序、快应用、Taro、C++ 等客户端，
以及 Python、Node.js、Go、Java、PHP、Lua、C#、C++ 服务端 SDK。公开分发证据包括：

- Python：[官方文档](https://help.gravity-engine.com/docs/python-sdk) 与
  [PyPI `gravity-python-sdk`](https://pypi.org/project/gravity-python-sdk/)；
- Node.js：[官方文档](https://help.gravity-engine.com/docs/node-sdk) 与
  [npm `gravity-engine-sdk`](https://www.npmjs.com/package/gravity-engine-sdk)；
- Flutter：[pub.dev `gravity_engine_flutter_sdk`](https://pub.dev/packages/gravity_engine_flutter_sdk)；
- 公开源码/示例：[GitHub `GravityInfinite`](https://github.com/GravityInfinite)；
- 素材上传：[官方素材上传 SDK 文档](https://help.gravity-engine.com/docs/material-upload)，Python 包名为
  `gravity-material-upload`。

**[实证]** 数据 SDK 的文档和样例围绕事件采集、用户属性写入、批量上传或素材上传，不是报表/分析查询客户端。
本次没有在官方文档、PyPI、npm、Maven 或公开 GitHub 入口找到封装上述报表 OpenAPI 的官方 Python/Java/Node
查询 SDK。官方分析查询面目前表现为 HTTP 文档，而不是可直接替换本仓库的官方 SDK。

## 2. 覆盖面对比

### 2.1 计算方法

**[实证]** 987 的集合来自 `src/gravity_sdk/census/data/routes.json`，对应公开入口递归抓取 375 个 JS
chunk 后得到的规范化 method/path 清单；边界见
[segment-delete-capability.md](segment-delete-capability.md)。223 的集合来自
`src/gravity_sdk/contracts/operations/` 下的 operation contracts。

采用两层比较：

1. **精确 wire 交集**：HTTP method 与规范化 path 必须相同；
2. **保守语义对应**：业务对象和动作相同，但允许官方与 Web 的 path、body、分页、返回 envelope 不同。

### 2.2 987 条路由

**[实证]** 22 条官方目录路径全部已被当前 census 捕获，证据类型是 `api_catalog_value`，method 为
`UNKNOWN`；它们是页面展示的接口字符串，不是 bundle 中解析出的页面请求调用。

| 项目 | 数量 | 占比 |
| --- | ---: | ---: |
| 官方开发者目录路径 | 22 | 2.23% |
| 未出现在官方开发者目录的 census 路由 | 965 | 97.77% |
| 合计 | 987 | 100% |

**[实证]** 因此，官方开发者目录没有推翻 census 的主体来源。它解释了其中一个很小但重要的子集，不能覆盖其余
Web 报表、分析、推广、素材、归因、配置和管理路由。第 1.3 节两个文档化写入 endpoint 在 census 外，证明官方
文档是必要补充，但它们不提供缺失的读取能力。

### 2.3 223 条 operation

**[实证] 精确 wire 对应为 0 / 223。** 当前 223 条 operation contract 全部使用 Web 端点和
`gravity_authorization` auth profile，没有一条 operation path 以 `/openapi` 开头。

**[实证] 保守语义对应为 13 / 223。** 对应表如下；“对应”只表示业务能力有重叠，不表示参数、字段、
分页、权限或结果 envelope 等价。

| 当前 operation | 官方路径 | 对应强度与差异 |
| --- | --- | --- |
| `app.list` | `/openapi/api/v1/open_app/list/` | **[实证]** 同为应用列表；官方 POST/filter 与当前 Web GET/分页和字段面不同 |
| `analysis.event.info` | `/openapi/api/v1/event/event_info/` | **[实证]** 目录语义对应；逐字段公开 contract 未找到 |
| `analysis.event.list` | `/openapi/api/v1/event/event_list/` | **[实证]** 目录语义对应；逐字段公开 contract 未找到 |
| `analysis.event_property.list` | `/openapi/api/v1/event/event_property_list/` | **[实证]** 目录语义对应；逐字段公开 contract 未找到 |
| `analysis.user_property.list` | `/openapi/api/v1/event/user_property_list/` | **[实证]** 目录语义对应；逐字段公开 contract 未找到 |
| `promotion.object.list` | `/openapi/api/v1/user/promoted_object/list/` | **[实证]** 目录语义对应；逐字段公开 contract 未找到 |
| `analysis.order_detail.list` | `/openapi/api/v1/report/order/list/` | **[实证]** 同为用户订单/付费明细；body、字段选择和分页不等价 |
| `analysis.user_detail.list` | `/openapi/api/v1/report/user/list/` | **[实证]** 同为用户明细；官方有注册时间范围和分页限制 |
| `material.report.query` | `/openapi/api/v1/report/material_get/` | **[实证]** 同为素材报表；需校验维度、指标、时效和结果投影 |
| `report.multidim.query` | `/openapi/api/v1/report/adreport/custom_get/` | **[实证]** 同为多维报表；body 结构和结果 contract 不等价 |
| `analysis.monetization_detail.list` | `/openapi/api/v1/report/monetization_detail/list/` | **[实证]** 同为变现细查；官方限制事件日期范围和页大小 |
| `analysis.event.query` | `/openapi/api/v1/report/events/list/` | **[实证]** 同为事件分析；时间粒度、查询项、公式和过滤结构不同 |
| `report.multidim.metric.list` | `/openapi/api/v1/report/metrics/list/` | **[实证]** 同为多维报表指标；没有把不同业务域的 `report.metric.list` 重复计入 |

**[实证]** 其余 `223 - 13 = 210` 条 operation 没有在这 22 条官方目录中找到保守语义对应。
未覆盖的主体包括漏斗、留存、属性、分布等分析族，以及看板/订阅/模板、推广平台层级、素材管理、归因等能力。

**[实证]** 22 条官方路径中，以下 9 条没有计入上述 13 条 operation 对应：

- `/material/id_map/`：当前 223 中无同等 operation；
- 两条 `/download/event/...`：仓库 export registry 中已有未验证条目，但它们不属于 223 条 operation；
- `/user/promoted_object/create/`、`/open_app/create/`、`/open_app/edit/callback_url/`：属于创建/配置能力；
- 三条 `/asset/...`：属于素材上传流程，官方另提供上传 SDK。

**[实证]** 第 1.3 节的事件采集、媒体 Token 刷新，以及事件/归因回调也没有计入 13：前两者是写入或凭据同步，
后两者是厂商向客户推送；都不是当前 223 条分析读取 operation 的 drop-in 对应。

**[推测]** 这 9 条是“官方新增能力候选”，不应因为未落入 223 就视为无价值；尤其事件导出可能比逐个报表
接口更接近仓库“脱离 Gravity Web 完成分析”的产品目标。

## 3. 稳定性与契约保证

### 3.1 官方接口

**[实证]** 官方公开路径统一带 `/openapi/api/v1`，构成路径级版本标识；帮助页给出请求地址、请求方法、
字段、响应样例、错误码和部分速率限制。状态码文档区分了无权限、应用失效、超限、服务不可用等情况。

**[实证]** 本次没有在当前帮助中心、旧文档入口或公开仓库中找到正式 SLA、向后兼容期限、废弃窗口、
版本生命周期或统一 API changelog。页面上的“最近修改”和 SDK release notes 不是 API 废弃策略。

**[实证]** 归因回调页对 `__PROJECT_ID__`、`__PROMOTION_ID__` 两个宏给出了“后续停止下发”和替代字段，
说明厂商会在具体页面标记个别废弃项；本次仍未发现统一的公告订阅、时限或迁移政策。

**[实证]** 文档自身存在需要逐接口处理的不一致：不同页面出现 `api-insight.gravity-engine.com`、
`backend.gravity-engine.com`，事件下载页还出现过 `api.insight...` 形式。不能从一个总览页推导全局 base URL；
实现时应以端点页加租户实测为准，并把 host 纳入固定 contract。

**[推测]** 官方 OpenAPI 是为外部集成明确发布的面，预期比 Web 内部端点稳定；但由于没有找到 SLA/兼容与废弃
承诺，这只是相对风险判断，不是厂商保证。`/v1` 也只证明当前路径版本化，不证明其变更一定向后兼容。

### 3.2 当前 Web 端点

**[实证]** 当前 operation 来源是 Web bundle 和租户请求验证，使用 `/report/api/v3/...`、
`/turbo_engine/api/v1/...` 等内部页面端点。公开官方开发者文档没有把这些端点列为对外 contract，
本次也没有找到针对它们的 SLA、废弃策略或变更通知承诺。

**[实证]** Web path 中出现 `v1/v2/v3` 不能当作外部稳定性承诺；当前仓库依赖 chunk hash、route census、
manifest 编译、响应投影和探针自行发现漂移。

**[推测]** Web 端点的运行风险高于经文档发布的 OpenAPI，主要风险不是“现在不可用”，而是厂商可随页面发布同时
改 path、body 或 envelope，且无需按外部消费者节奏通知。

## 4. 鉴权模型与迁移代价

| 维度 | 当前 Web 会话 | 官方报表/导出 OpenAPI |
| --- | --- | --- |
| 凭据取得 | **[实证]** 用户名/密码调用 `/account_center/api/v1/user_login/v2/`，换取 `Authorization` token | **[实证]** 开发者中心创建应用、审核后取得 `app_key` |
| 每次请求 | **[实证]** 携带会话 `Authorization` | **[实证]** 对 body 排序/规范化后结合 `app_key` 计算 MD5 `sign`；再用该 `sign` 作为 HS256 key 生成含 `app_key` 的 JWT `Authorization`，body 同时带 `sign` |
| 运行身份 | **[实证]** 绑定交互用户及其 Web 权限 | **[实证]** 绑定获批开发者应用；文档状态码体现应用有效性和接口权限 |
| OAuth | **[实证]** 当前 Web 路径不是 OAuth | **[实证]** 公开文档未描述 OAuth flow；也不是“静态 API Key 直接当 bearer” |
| 生命周期 | **[实证]** 需要处理登录/session token 生命周期 | **[不确定]** 公开页未完整说明 `app_key` 轮换、吊销、有效期和自动化审批模型 |

**[实证]** 官方并非只有一种鉴权：事件采集 SDK/Restful API 使用应用 `access_token`；媒体 Token 刷新使用
`access_token` query 加基于 App key/媒体 token/时间戳的 MD5 `sign`；事件回调验签也使用应用管理页的
`access_token`。这些服务端集成凭据不能与报表 OpenAPI 的 `app_key + sign + JWT` 无证据地互换。

**[推测] 迁移代价为中等，不是简单换 URL。** 最小工作量包括一个独立 official auth profile 和签名器、
约 13 个请求/响应 adapter、分页和限流治理、正式 contract/manifest/projection/privacy 审查，以及本租户开发者应用
审批和密钥托管。若采用事件导出，还要增加异步任务与下载管线；若采用回调，还要增加公网接收、验签、幂等、重试和存储。

**[推测]** 一旦完成，定时分析不再依赖交互用户密码和 Web session 刷新，运行稳定性通常会提高；但实际权限范围、
密钥轮换和租户审批尚未实测，不能在本轮把这一收益写成已验证事实。

## 5. 官方导出、订阅与数仓直连

### 5.1 历史/批量事件导出

**[实证] 有官方事件导出。** `/openapi/api/v1/download/event/submit_task/` 提交任务，
`/openapi/api/v1/download/event/query_result/` 轮询结果。当前公开页面描述：

- 可按应用、事件和时间范围筛选；单次时间范围最多 30 天；
- 单任务最多导出 1,000,000 条事件；
- 结果状态包括运行、成功、失败、取消、过期；
- 成功后返回 `.csv.gz` 下载地址，示例为 OSS URL，链接保留 3 天。

**[实证]** 这比当前可执行的
`/report/api/v3/dataanalysis/user/event/list/download/` Web 导出覆盖面更接近应用级原始事件回流；仓库 export
registry 已预留 official submit/result 条目，但当前仍是未验证、不可执行状态。

### 5.2 面向未来事件的回调

**[实证] 有官方事件回调。** [事件回调文档](https://help.gravity-engine.com/docs/events-callback) 描述把选定事件
及用户/归因信息以 HTTP POST 推送到调用方，用于 BI、数据集成和二次分析；默认超时 2 秒，失败重试一次，并有签名机制。

**[实证]** 回调是选定的未来事件流，不是历史全量回填，也不是仓库可直接读取的数仓。历史数据仍需事件导出或报表查询。

### 5.3 归因结果回调

**[实证]** [归因回调文档](https://help.gravity-engine.com/docs/attribution-callback) 还提供 Gravity → 客户后端的
归因结果推送：客户配置自己的 GET URL 和宏参数，匹配成功时由 Gravity 替换参数并调用。它适合把新增归因结果送入
自有系统，但不是历史导出、通用事件订阅或查询 API。

### 5.4 对象存储和数仓直连

**[实证]** 本次在官方帮助中心、旧文档、公开 bundle、官方 GitHub/包管理器和官方域名搜索中，没有找到
客户自有 S3/OSS 持续投递、Snowflake、BigQuery、ClickHouse 或其他数仓直连的公开官方产品文档。事件导出的
OSS 地址是保留 3 天的下载结果，不等于持续投递到客户自有 bucket。

**[推测]** 不能排除商务合同、私有部署或未公开功能中存在数仓能力；当前可据公开证据采用的根本路径是
“历史事件导出 + 未来事件回调 + 自有存储”，不是现成的官方数仓连接器。

## 6. 推荐迁移边界

### 第一层：优先验证并补充官方 transport

**[推测]** 对第 2.3 节列出的 13 个语义对应 operation，应按以下优先级验证：

1. 事件分析、多维、素材、用户、订单、变现明细与指标查询；
2. 应用、事件、事件属性、用户属性和推广对象元数据；
3. 全量历史事件导出；
4. 确有实时自有数据底座需求时，再接入事件回调。

判断标准不是“官方有同名接口”，而是相同分析 journey 的维度、指标、过滤、分页、时效和权限均不丢失。

### 第二层：继续使用 Web 口径

**[实证]** 没有出现在官方目录的 210 条 operation 继续由当前 contract 驱动。包括但不限于漏斗、留存、
属性分析、分布分析、看板、订阅、模板、推广平台层级、素材管理和归因等族。

**[推测]** 不应为了统一 transport 而把这些能力降级为少量官方报表的拼接；那会违反“breaking surface change
不得损失读能力”的仓库原则。

### 第三层：不要把两种鉴权和证据混在一起

**[推测]** official 与 web 应有独立 auth profile、host allowlist、速率预算、错误分类和 provenance。
官方目录字符串不应被 census 误标为已验证 Web request；Web 的同业务 endpoint 也不应自动继承官方稳定性结论。

## 7. 逆向口径仍需怎样提高稳健性

以下均为基于当前证据的工程建议，标为推测，不代表本轮实现：

1. **[推测] 入口与 chunk 图漂移检测。** 固定入口 HTML、构建标识、递归 chunk 集和每个 bundle hash；任一层变化时触发重建，不只盯单个已知文件。
2. **[推测] 可确定性再生成。** 保存抓取时间、URL、hash、提取器版本和 provenance；从冻结输入可重复生成 route census，并对 method/path、调用者和 UI 文本做集合差分。
3. **[推测] 分离“目录值”和“调用证据”。** 保留 `api_catalog_value`、`request_call_candidate` 等证据类型；官方目录路径 method 未解析时必须保持 `UNKNOWN`，不得因文档惯例猜成 POST。
4. **[推测] 检查 body 内动作。** 除 URL/method 外识别 `action=delete`、GraphQL/批处理动作和动态 dispatch，避免只靠 path 漏掉删除或变更语义。
5. **[推测] 响应指纹。** 对已实现 operation 监测 envelope、必需字段、字段类型、枚举域、分页游标和时区语义；漂移时 fail closed，而不是静默丢字段。
6. **[推测] 变更分级探针。** 公共静态图可无凭据定期重抓；只有变化且已有批准 contract 的只读端点才进入最小生产探针，继续受全局请求预算约束。
7. **[推测] 官方目录同步。** 单独保存并 diff 22 条 official catalog；若新增公开路径，先检索官方帮助页，再决定是否减少对应 Web 依赖。
8. **[推测] 能力无损迁移账本。** 每个拟迁移 operation 记录 official/Web 的维度、指标、过滤、分页、延迟、权限和错误差异；未证明等价前不删除 Web 能力。
9. **[推测] 鉴权隔离。** Web session 与 official app credential 分开存储、轮换和审计，禁止一个 transport 失败后无类型地回退到另一个。

## 8. 不确定性与明确未完成项

1. **[不确定]** 4 条事件元数据和 2 条推广对象接口只有当前官方开发者目录证据；本次未找到逐接口公开页面，因此没有猜它们的 method、body、分页、限流或 response schema。
2. **[不确定]** 本租户能否获批开发者应用、实际授予哪些接口权限，以及 `app_key` 生命周期如何；本轮未读取任何 key，也未登录开发者中心。
3. **[不确定]** 13 个 operation 的完整字段/语义是否无损；当前计数是保守业务对应，不是生产兼容认证。
4. **[不确定]** 公开面未找到 Swagger/OpenAPI 文件，不等于私有门户中绝对不存在。
5. **[不确定]** 未找到公开数仓直连文档，不排除私有部署或商务方案。
6. **[不确定]** 未找到统一 SLA、兼容和废弃策略，不等于厂商内部没有发布流程。
7. **[不确定]** 官方页面的 host 写法存在差异；未通过本租户凭据验证每个端点实际应使用的 host。
8. **[不确定]** 事件导出和回调的真实吞吐、并发、失败恢复与大数据量成本未做生产验证。

## 9. 生产请求账本

**[实证] Gravity 生产业务 API 请求：0 次。** 重试 0 次，分页 0 次，时间窗切分 0 次。

原因：官方公开文档、公开 bundle、仓库冻结快照和包管理器已经足以回答“是否存在”和静态覆盖问题；官方端点需要
获批 `app_key`，而本任务明确禁止读取 key。发送无凭据生产请求只能证明鉴权失败，不能提高契约证据质量。

本轮只读取了公开官方网页/静态资源与本地仓库文件；没有触碰 holdout/final，没有读取或解密任何凭据，没有进行任何
GitHub、PR、issue、push 或 tag 操作。

## 10. 对七个判断题的直接回答

1. **官方 API / SDK / 文档有没有？** **[实证] 有。** 有官方帮助中心、Web 开发者中心、22 条报表/导出/配置 OpenAPI 目录、目录外的事件采集与 Token 接入 API、数据采集 SDK 和素材上传 SDK；未找到官方分析查询客户端库或公开 Swagger/OAS 文件。
2. **覆盖面如何？** **[实证]** 22 条官方开发者目录 path 与 987 的交集为 22（2.23%），另有 2 条文档化写入 endpoint 不在 census；223 条 operation 中精确 wire 对应 0，保守语义对应 13（5.83%），其余 210 条无官方读取目录对应。
3. **鉴权差异和迁移代价？** **[实证]** 报表/导出从用户会话 token 变为获批应用的 `app_key + body sign + JWT Authorization`；采集和回调另用 App `access_token`。**[推测]** 代价中等，需要独立鉴权、adapter、contract、限流和租户审批，不是换 base URL。
4. **官方导出 / 数仓直连？** **[实证]** 有异步事件导出、事件回调和归因回调；公开面未发现客户自有对象存储持续投递或数仓直连。
5. **切换 / 补充 / 维持？** **[推测] 选择补充。** 官方覆盖窄但价值高，应优先承接其明确覆盖的查询和事件数据回流；其余能力继续逆向。
6. **逆向口径如何更稳？** **[推测]** 做完整 chunk 图/hash 漂移检测、确定性再生成、证据类型分离、body 动作识别、响应指纹、最小分级探针和能力无损迁移账本。
7. **哪些是推测？** 本文所有 **[推测]** 项均为推测；集中包括“官方相对更稳定”“迁移成本中等”“应补充及其优先级”“历史导出+未来回调可形成自有数据底座”和第 7 节全部工程建议。第 8 节逐项列出了仍无法确定的事实。

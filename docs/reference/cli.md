# CLI 参考

本页只提供命令地图。参数细节以相应 `--help` 输出为准，输入 schema 以 `describe` 为准。

## 顶层命名空间

```text
gravity insight <command>     结构化读取和导出
gravity export <command>      一键治理导出及分阶段恢复
gravity agent [query]         单问题发现；--input 批量发现并返回 Plan 节点
gravity agent-catalog ...     渐进浏览产品、raw operation 与登记 gap
gravity plan schema|run       预检或执行受控跨能力 DAG
gravity derive --input        对已有结果执行调用方绑定的本地派生算术
gravity semantics|operators|models ...  离线检查 Semantic、Operator 与 Model 合同
gravity metadata <command>    本地物理元数据目录
gravity find <query>          跨 operation、recipe 与 metadata 检索
gravity recipe <command>      离线校验 workspace recipe
gravity run <selector>        单进程解析并执行 recipe 或 operation
gravity sql <command>         登记 SQL 与显式隔离 Explorer
gravity census <command>      前端路由盘点
gravity analysis context      并发读取一个 App 的分析上下文
gravity analysis defaults     读取一个 App 的 Analysis 默认值字典
gravity analysis realtime-events  读取一个 App 在显式时间窗内的实时事件目录第一页
gravity analysis dashboard snapshot  读取一个看板的控制面快照
gravity analysis dashboard prepare|run  编译或执行一个看板的受支持图表
gravity analysis dashboard kanban schema|mutate  查看或执行 Kanban 受治理写合同
gravity analysis segment snapshot  读取一个分群的详情、历史与单日计算结果
gravity analysis segment members   读取一个分群的完整成员行与逐人属性
gravity analysis segment ... / gravity action segment-update|dashboard-delivery ...  direct 分群写或 Artifact→Dashboard 一次性 Action Plan 确认
gravity experiment propose|outcome-handoff  离线编译实验评审材料或独立 Outcome 交接
gravity analysis saved ...    列出、读取、准备或严格重放保存分析
gravity analysis order directory  读取受控四字段的单日普通订单目录
gravity analysis order trace  按显式 TraceID 读取单日拆单明细
gravity apps snapshot         并发读取一个 App 的治理快照
gravity apps permission-profile 读取当前账号的角色、菜单和数据权限模块
gravity apps realtime-event schema|update  预览或设置单个 App 的实时事件入库开关
gravity attribution snapshot  并发读取一个 App 的归因配置快照
gravity attribution performance 读取一个 App 日期区间的四组归因表现
gravity attribution user-detail 读取一个 App 下已登记测试设备的单用户归因明细
gravity reports pulse         并发读取 App 经营概览与趋势
gravity reports usage         完整读取公司级按日资源用量趋势
gravity reports directory|subscriptions  完整读取报表目录/定义或订阅清单；空结果与权限裁剪空集不可区分
gravity reports create|delete|subscribe|unsubscribe  预览或显式执行 marker-governed 写
gravity materials performance 读取稳定的跨平台素材表现
gravity materials fetch       从已登记素材响应按精确引用下载文件
```

任意命令都可在顶层显式选择项目配置：

```powershell
gravity --workspace <gravity.toml-or-directory> <command> [options]
```

历史 Insight 命令可以省略 `insight`，但新文档和自动化应使用完整命名空间。

## Insight

Agent 优先从顶层机器协议开始：

```powershell
gravity agent
gravity agent "retention" --limit 3
gravity agent --input questions.json
gravity agent "run saved analysis" --resolve-inputs '{"app":"main"}' --output catalog.json
gravity agent-catalog host
gravity agent "<query>" --routing host_catalog --host-selection selection.json
```

完整能力面使用 `gravity agent-catalog categories` → `category <name>` →
`describe <selector>` 渐进浏览。目录项的 `identity_kind` 是机器边界：`product` 是 canonical Agent
产品卡；`raw_operation` 只是 manifest operation，固定 `product_equivalent=false`；
`capability_gap` 是登记但当前不可执行的缺口。`catalog_status=registered_unavailable` 的 gap 同时给出
精确 `gap_code`、`reason` 和 `next_action`。不得因为相邻 raw operation 的 `executable=true` 就把缺失
产品改判为可执行。目录和 describe 均完全离线，也不会执行能力。`agent-catalog describe` 投影产品卡
加压缩 operation 合同（含完整 `input_schema`），不投影 wire/examples/privacy/health；完整合同看
`gravity operations describe`。`operations describe` 投影完整 operation 合同，压缩 Agent 卡看
`gravity agent-catalog describe`。

`agent-catalog host` 是同一 owner/card/gap 的紧凑投影，只含 96 张产品卡和 7 个精确 gap，不含 raw
operation；每项固定给出目标、返回物、相邻边界、前置输入与 effect。宿主响应必须完整符合
`gravity.host-product-selection.v1`，只能引用当前 `catalog_ref`。0 个引用由仓库生成固定路由 gap；
多个引用固定为 `MULTIPLE_INTENTS`；未知字段、旧目录指纹、伪造产品或直接 operation/path 均整体拒绝。
调用方能产出选择时推荐显式 `--routing host_catalog --host-selection`；未指定 `--routing` 的默认仍是 recognizer，那是够不着宿主时的地板，不是劣等品。识别器若没选中产品、只排出至少 3 条互不相同的 raw operation（短英文目录查找除外；挂在后面的非权威 catalog 卡不算选定），会返回 `UNRANKED_OPERATIONS`（不是错误），`next.argv` 指向 `gravity agent-catalog host`，由宿主走已有 `host_catalog` 路径完成选择。

`category` 的顺序是合同而不是模糊相关性：每个 category 内固定按
`product → raw_operation → capability_gap` 排序，同类再按 selector 升序。于是第一页先展示 canonical
产品卡；调用方只有在产品不能表达任务时才继续浏览 raw operation。

无 query 时返回两步协议；有 query 时优先返回匹配的 workspace recipe，再用 stable operation
补足 capability cards；可由 Plan 执行的卡含必填输入、下一条 `argv` 和 `plan_node`，默认 3 个、
最多 5 个，不访问网络。`--input` 接受最多 32 个唯一 ID 问题的 `{"questions":[...]}`，为
多个问题复用一次离线目录快照并按输入顺序返回；不能与 positional query、continuation、
domain 或 platform 组合。需要完整 catalog 或 blocked 覆盖信息时再进入
`operations search/describe`。

`--resolve-inputs JSON|FILE|-` 是显式在线模式，只用于 App/平台等依赖上下文已知、引用或物理字段
未知的场景。它把能力发现和完整 live catalog 读取放在第一条顶层命令中；不选择值、不执行候选。
该模式要求 `--output <local-file>` 和 JSON 格式，保证目录不受 stdout 安全摘要上限影响。调用方从
文件按稳定 ID（模板按 scope + ID）或物理名精确选择，再执行原命令/Plan，合计两次。响应中的
`input_resolution.internal_http_calls_reduced=false` 明确表示目录 HTTP 没减少。冷 metadata/table
catalog 使用 `{"catalog_policy":"refresh"}`；任一来源失败时不发布 staging catalog。默认 Agent
和 `--input` batch 仍离线；App 或 Promotion 平台也未知时不能套用两次下界。

| 命令组 | 用途 |
| --- | --- |
| `operations list/search/describe/schema` | 发现 operation 和输入合同 |
| `validate` | 离线校验输入，可选渲染脱敏 wire |
| `read` | 执行一个 operation，支持受控分页和文件输出 |
| `run` | 执行 `@recipe` 或 operation 的 Resolver 管线，并产出脱敏 Receipt |
| `recipe validate/check/accept-contract` | 离线检查 recipe 格式或 operation 漂移；审阅合同 diff 后重钉指纹 |
| `discover-nonempty` | 在严格 HTTP 预算内发现非空组合；输出和缓存只保留输入字段名、脱敏语义错误码及字段提示，不保留值或响应消息 |
| `batch` | 批量执行独立的受控读取 |
| `parents resolve` | 解析 operation 需要的父资源 |
| `auth status/refresh` | 查看或刷新认证状态 |
| `export ...` | 一键创建/轮询/下载治理导出，或分阶段恢复 |
| `doctor` | 离线检查安装来源与本地合同；`--live` 通过后执行最小在线探针 |

领域命令如 `analysis`、`multidim`、`promotion`、`materials` 是受控 operation 的易用门面；不确定时从 `operations search` 开始。

`gravity doctor` 先在本地对齐当前源码 `pyproject.toml`、`gravity-sdk` distribution metadata、
editable 根目录、实际 `gravity_sdk` import 路径和版本。重复 metadata、版本或根目录不一致会在任何
客户端构造和 `--live` 探针前以 `INSTALL_*` reason code、local exit `4` 和有序
`reinstall_commands` 失败；检查本身不访问网络。

`operations search` 会把可调用 stable 结果排在前面，也会展示部分 draft/blocked catalog
条目来说明覆盖缺口。执行前检查 `executable`、`stability` 和 `block_reason`，再以 `describe`
返回的 input schema 和 example 为准。

例如，先发现并审阅巨量标题素材合同，再执行受控分页读取：

```powershell
gravity insight operations search "巨量 标题 素材" --domain material
gravity insight operations describe material.bytedance_asset_text_title.list
gravity run material.bytedance_asset_text_title.list --set page_size=100 `
  --all-pages --output tmp/material-titles.ndjson --format ndjson
```

常用读取参数：

```text
--input/-i <json|file>   内联 JSON 或 JSON 文件；'-' 表示 stdin
--set <path=value>       点路径覆盖，可重复
--all-pages              遵循 manifest 分页合同
--max-pages <n>          最大页数
--max-items <n>          最大返回条数
--concurrency <1..24>    已知总页数时的分页 worker（默认 6）
--output <path>          写入本地文件
--format json|ndjson     输出编码
--fields <a,b>           本地裁剪为合同允许字段；可重复
--start/--end/--date     ISO 日期，或封闭相对短语（昨天/today、最近 N 天/last N days、本周/this week 等）
```

时区顺序：`GRAVITY_TIMEZONE` → 已配置 workspace `defaults.timezone` → `Asia/Shanghai`。不用本机时区。

相对短语在进下游校验前解析成闭区间 `YYYY-MM-DD`。成功结果带
`resolved_date_window`，形如 `昨天 → 2026-08-17..2026-08-17 (Asia/Shanghai)`。
「最近一段时间」这类无唯一答案的短语按 `INPUT_INVALID` 拒绝，`field` 指向
`start/end` 或 `date`，`next_action` 要求给具体日期。ISO 日期行为不变。

`--fields` 也适用于 `run` 和 `batch run`；批量 item 与 Plan 节点也可单独使用
`output_fields`（item 值优先于批量默认值）。默认不指定时输出完全不变；未知字段会在联网前返回 caller/2。动态字段只能
选择请求已经声明且合同允许的字段。

结果型 `--output` 在同目录写临时文件并原子替换目标；写入成功后 stdout 只返回收据，不再混排结果：

```json
{
  "format": "json",
  "ok": true,
  "output": "tmp/result.json",
  "size_bytes": 1234,
  "status": "written"
}
```

`size_bytes` 是实际 UTF-8 文件字节数。已有 NDJSON 编码的行数继续由文件末尾
`_gravity_insight.rows_written` 表示，外层收据不另加字段。纯 `error`/`capability_gap` 不创建或替换
目标；支持 partial 的新产品写入完整 partial envelope，并原样返回非零退出码。

Insight 普通批量读取默认并发为 6，显式上限为 24；Metadata 同步允许 `1..24`。单次分页
读取在首页有明确总页数时按小窗口并发并保持页序，未知总页数时串行；batch 内的分页读取
强制单分页 worker，防止嵌套放大。这些是 worker 上限，实际请求仍受每 host 限流、重试和
共享冷却约束。

## Derived Metrics

`gravity derive --input <request.json>` 完全离线地给已有结果 envelope 增加
`gravity.derived-metrics.v1` 子合同。request 固定为 `source/spec`；source 是原 envelope，spec 使用
`gravity.derived-metrics-spec.v1`，声明 `rows_path`、`decimal_places` 和 1–32 个 calculations。
原 envelope 的顶层 schema、status、ok、result_source 和 data 不会改变。

```json
{
  "source": {
    "schema_version": "fictional.result.v1",
    "status": "success",
    "ok": true,
    "data": {"list": [{"orion_a": 3, "orion_b": 4}]}
  },
  "spec": {
    "schema_version": "gravity.derived-metrics-spec.v1",
    "rows_path": "/data/list",
    "decimal_places": 4,
    "calculations": [{
      "operator": "ratio",
      "result_name": "orion_ratio",
      "numerator": "orion_a",
      "denominator": "orion_b"
    }]
  }
}
```

执行 `gravity derive --input request.json` 后，数值为 decimal string；整数精确转换，除法使用
half-even。分母零、缺列、null/非法数、上游 partial 和舍入都有稳定 status/reason 或 warning code。
operator 只支持 `ratio/share/change/reconcile`，不会从列名推断公式。未在 workspace 声明公式的
自然语言比率问题由 Agent 返回 `DERIVED_METRIC_BINDING_REQUIRED`，不会自动填 numerator/denominator。

## Multidim

公开入口直接接受稳定的闭合物理输入，不增加一套字段改名后的 Spec DSL。App 单独绑定；
`--input-schema` 可离线取得机器合同，`--dry-run` 在构造 client 前完成本地预检：

```powershell
gravity multidim query --input-schema
gravity multidim query --app main --input <query.json> --include-total `
  --all-pages --max-pages 20 --max-items 5000 --concurrency 6
gravity multidim query --app main --input <query.json> `
  --filter click_company IN bytedance,tencent `
  --custom-metric roi_after_tax --relate-dim advertiser_name
```

产品 dry-run 必须显式写在子命令后并提供 App：`gravity multidim query --app main --input ... --dry-run`。
根级 `gravity --dry-run` 是全仓合同自检，不能与任何命令组合。除纯离线
`--input-schema` 外，缺少 `--app` 的专用 query 会在构造 client 前失败；不会使用 workspace 默认
App，也不会回退到 raw operation。

input 只含 `date_list/time_dims/metrics_list/custom_metrics_list/data_dims/relate_dims/filters/multi_keys`。
三个新增便利层直接复用物理字段：`--custom-metric NAME[,NAME...]` 覆盖
`custom_metrics_list`，`--relate-dim NAME[,NAME...]` 覆盖 `relate_dims`，
`--filter FIELD OPERATOR VALUE[,VALUE...]` 覆盖 `filters`。快捷参数优先于 `--set`，`--set`
优先于 `--input`；未出现的快捷参数不修改对应物理字段。filter value 按 JSON scalar 解析，
不能用快捷参数表达的字面值继续使用 `--input`/`--set`。

`--multi-days` 的当前队列观察窗由已编译 `report.multidim.query` 与
`report.multidim.calc_total` 的 `input_fields.multi_keys.item_enum` 共同决定；命令 help、
`--input-schema` 和 Agent 卡都投影同一枚举。结构畸形仍返回 `INPUT_INVALID`；结构合法但超出枚举
上界的请求返回 `MULTIDIM_COHORT_HORIZON_CONTRACT_MISSING`，且不会降级到通用 Analysis 留存。

真实 artifact 未提供多 filter 组合语义证据，因此当前 `--filter` 最多出现一次，且不能和
`--media` 同用；重复条件在联网前拒绝。该边界也由 `--input-schema` 的
`x-cli-shortcuts.filter` 机器字段声明。已有版本化物理 `filters[]` 合同不收缩：专家仍可通过
`--input`/`--set` 使用原合同形状，其语义与优先级不变。
`--app` 接受 workspace alias 或正整数；专用入口不再接受 `--app-id` 或 `--parent-id`。Agent 不会填
App、日期或 filter value；物理指标/维度未知时可在 App 和其余业务输入已知的前提下用在线输入解析
取得闭合 schema 与 live catalog，调用方仍精确选择。直接执行默认 6 workers、最大 24；Plan adapter 固定 1。`--include-total`
才会在 query 后串行计算 total，`--all-pages` 使用受控分页。HTTP 数为去重 metadata `M` + query
页数 `P` + 可选一次 total。已知输入一调用；能力/物理字段未知时是一次在线 Agent 解析加一次 Plan。多个查询
应放进一个 Plan，不新增 batch wrapper。

产品结果固定为 `gravity-insight.composite.multidim.v1`；业务行读取
`query.data.list`，并同时校验顶层 `status/exit_code` 和 `query.status`。`partial` 不是成功明细的
同义词，调用方必须按结构化状态处理。独立的 `multidim calc-total` 子命令已删除；合计只通过
`query --include-total` 请求。需要精确 raw operation 的专家流程继续使用
`gravity run report.multidim.query` 或 `gravity run report.multidim.calc_total`。

Multidim 不回放 template，不处理图表/透视、layout、收藏、拖拽、成员权限或业务指标语义；这些
边界也不会通过 `--input` 扩张。

## Business Semantic 与 Semantic Compose

复数 `semantics` 只离线编译显式 JSON/TOML Source，默认仅含 wheel 通用定义；singular `semantic compose` 才是 Multidim 之上的物理执行面。两者都不接受推断的字段或裸 SQL：

```powershell
gravity semantic compose --input-schema
gravity semantic compose --app main --input semantic-request.json --dry-run
gravity semantic compose --app main --input semantic-request.json
gravity semantics list|describe|resolve|validate [--source <semantic-source>]
```

input 必须逐项引用机器 schema 当前列出的 `{definition_id, version}`，并完整提供
`definition/window/metric/dimensions/filters/grain/joins`。`report.ap-cost-observation@1` 保持只登记
`ap_cost`、day/week/total、`click_company` 与其 many-to-one embedded join，且 `filters` 只能是 `[]`。
`@2` 在同一成员面增加 `click_company IN`，但必须同时选择 click dimension 和该 join；还登记
activate count、pay amount、total ROI 三个仅允许 day/week 的指标。`ap_cost` 在 v2 仍允许
day/week/total。`@3` 保留上述成员，并增加平台展示/点击/点击率/转化/激活、标准激活成本、标准付费人数、
广告收入与总收入 9 个 day/week 指标；注册数没有非空 day/week 证据而不登记。`@4` 保持 v3 成员面，
但把结果限定为 `result.query.fetched_at` 时点观察：同一结构化输入跨执行不保证数值相同，跨执行只能
降级为两个带时间戳的观察及算术差，不得称为确定性重放、稳定、已结算或因果变化。hour 或新指标 +
total 等不兼容组合在编译时零网络拒绝。

`--dry-run` 返回 `gravity.semantic-compose-compiled.v1`；同输入 canonical JSON 逐字节相同。执行返回 `gravity.semantic-compose-result.v1`，包含 `resolution_tier`、定义 ID/版本/指纹、实际成员、生成的
Multidim 查询、验证结果和按 App/窗口/成员收窄的 `allowed_claims`。未知成员、禁止 join 或粒度冲突
均不会构造客户端。该面复用既有 `report.multidim.query`，没有新增 operation，也不提供 Text-to-SQL。

## Material Performance

`materials list/tags/reviews` 保持原有兼容入口；新产品使用独立子命令：

```powershell
gravity materials performance --app main --app secondary `
  --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --platform tencent `
  --concurrency 6 --max-pages 20 --max-items 5000 `
  --output tmp/material-performance.json
```

`--app` 可重复或逗号分隔，接受 workspace alias 或正整数；平台省略时为
`bytedance/tencent/kuaishou/bilibili`。所有本地输入和输出路径先校验，之后才构造 client。
命令只写完整 JSON，不提供 NDJSON，以免破坏平台分组、分页收据和 partial 失败信息。

每个平台调用一次现有 stable `material.report.query` 并读取受控分页，多个 App 合并进该平台的
`app_list`；HTTP 数为 `Σ P_platform`。direct worker 范围 1..24、默认 6，实际池不超过平台数且
最多 4；每个平台分页 worker 固定 1。`max_items` 是共享声明预算，batch 实际给每个平台
`floor(max_items/platform_count)` 的不可借用份额。结果按平台声明序，物理指标保持原名；不生成
归一指标、总计、排名或业务结论。

## Material Asset Fetch

```powershell
gravity materials fetch --source local `
  --input '{"page":1,"page_size":20}' `
  --ref-field id --ref <exact-id> --role thumbnail `
  --output-root . --output tmp/thumbnail.jpg

gravity materials fetch --source bytedance_project `
  --input '{"advertiser_id":<id>,"project_id":<id>}' `
  --ref-field material_id --ref <exact-id> --role file `
  --output-root . --output tmp/video.mp4
```

`--input` 只接受所选 source 对应的已登记 operation 输入；命令先重新读取
`material.local.list` 或 `material.bytedance.project_material.list`，再从这次通过投影的唯一匹配行
取 `file_url` / `thumbnail_url`。没有 URL 参数，也不会从 `--input` 接受 URL。fresh URL 的精确 HTTPS
host/path 动态成为本次授权，不静态枚举未来 shard；重定向最多 3 次且只能留在同一精确 host，逃逸在
第二次请求前失败。结果只返回 host family、redirect count，绝不回显 URL。

`--output` 触发完整文件；`--output-root` 可显式绑定相对目标。省略 root 时相对路径绑定 cwd，旧绝对
目标绑定其 parent；root、祖先、reparse、overwrite 和扩展名在 source read 前检查，提交时再检查。
传输强制 Content-Length/stream cap、可用时的 source size/MD5、MIME+extension+magic、SHA-256、fsync
和原子 no-clobber；JPEG 为 16 MiB，MP4 为 1 GiB。维护 Range probe 不等于产品完整下载。

完整 GET 的 HTTP 200 才成功；terminal 401/403/404/410/429/5xx 及其他非 200 仍为 upstream/exit 3，
其中 408/425/429/5xx retryable。source/ref/role/input 与 output-root 错误为 caller/exit 2，本地 I/O 为
local/exit 4；redirect/type/size/digest 以稳定 `ARTIFACT_*` reason code 失败关闭且不留 partial。
结果为 `gravity.material-asset.v2` + `gravity.artifact-transfer.v1`，不会臆造素材失效状态。

## Promotion Performance

21 个合同同构的平台使用一个显式只读产品入口；App、日期、平台和物理指标都必须给出：

```powershell
gravity promotion performance --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --metric stat_cost --concurrency 6
```

`--platform`、`--metric` 可重复或逗号分隔。每个平台一个 batch item，分页 worker 固定 1；direct
平台池默认 6、最大 24。`max_pages` 按平台生效，`max_items` 按平台数等额 floor 分配且不可借用。
输出保留原生物理字段和平台声明序，不做跨平台归一、总计、排名或策略。
完整结果可用 `--output <path>` 写入 JSON；该产品不提供 NDJSON，以免拆散平台 component、分页
收据和 partial 失败信息。
operation 合同声明为 opaque JSON 的行字段只在产品深度、元素数和序列化大小边界内保留；普通
字段仍必须是有界 scalar。类型变化、超界结构和未登记字段继续返回 `contract_changed`，组件的
`drift_diagnostics` 只给固定检查类别与字段路径，不回显行值或业务标识。
同一个指标数组会发给每个所选平台；多个平台只有在各自实时元数据都证明该同名物理指标时才应
放进同一请求。平台原生指标名不同则使用同层 Plan 节点并发，SDK 不猜字段映射。
平台已知而指标未知时，可先用
`gravity agent "promotion performance" --resolve-inputs '{"platforms":["bytedance"]}' --output metrics.json`；
调用方精确选择后第二次执行上面的产品命令，执行端仍由 FieldPolicy live 复验。平台也未知时不适用。
旧 `promotion snapshot` 子命令仍保留并按输入分流。`primary` 加上述 21 个正式平台（包括
`--platform all`）必须用 `--app-id`、`--start/--end`、`--metrics` 提供统一绑定，返回同一个
`gravity-insight.promotion-performance.v1` envelope。非 primary 层级以及
`bing/xiaohongshu/taptap/wechat_video` 保留 stable inventory 兼容读取，只有匹配唯一 operation 才执行，
多候选时列出候选并失败；其 `gravity-insight.composite.promotion.v1` envelope 以
`compatibility.formal_binding_validation=not_performed` 明示未经正式绑定验证。`--platform all` 遇到
非 primary `--level`、`--media`、维度、父级或未知 input 字段仍显式失败，不按 operation schema 静默
忽略。Agent/Plan 只暴露正式产品；精确 raw 调试仍使用 `promotion query`。

批量 wrapper 可由机器自描述，不需要猜 JSON 字段：

```powershell
gravity insight batch schema
gravity insight batch read --input <batch.json> --concurrency 6
gravity insight batch schema --mode run
gravity insight batch run --input <resolver-batch.json> --concurrency 6
```

`batch read` 接受 operation；`batch run` 接受 recipe 或 operation selector，并为每项执行完整
Resolver 流水线。run item 可含 `selector`、`input`/`inputs`、`parameters`、`app`/`apps`、
`start/end`、`request_id` 和 `all_pages`。`apps` 数组保持声明顺序；`apps: "*"` 只展开当前
workspace 已绑定的 App alias，并按 alias 排序。外层并发保序且隔离错误，内层分页 worker
固定为 1；默认每项最多 5 页/200 项，可用 `--max-pages/--max-items` 显式调整。两种 batch
分别用自己的 schema 自描述，并按最高严重级别聚合退出码。

固定组合能力避免 Agent 手工执行一串独立命令：

```powershell
gravity analysis context --app main --concurrency 6
gravity analysis defaults --app main
gravity analysis realtime-events --app main --start "2026-08-18 00:00:00" --end "2026-08-18 23:59:59"
gravity analysis dashboard snapshot --app main --ref <id-or-exact-name> --concurrency 5
gravity analysis segment snapshot --app main --ref <id-or-exact-name> --date <YYYY-MM-DD> --concurrency 3
gravity apps snapshot --app main --concurrency 6
gravity apps permission-profile --concurrency 3
gravity attribution snapshot --app main --concurrency 6
gravity attribution performance --app main --start <YYYY-MM-DD> --end <YYYY-MM-DD> --concurrency 4
gravity attribution user-detail --app main --device-id <testing-device-row-id>
```

`--app` 接受 workspace alias 或正整数；归因命令继续接受 `--app-id` 兼容别名。Analysis
context 固定 13 个词汇/模板来源，App snapshot 固定 6 个治理来源；Attribution snapshot 固定
覆盖当前 8 个 stable attribution operation，其中两个 postback map 自动读取全部页。这三者
默认并发 6；Dashboard snapshot 默认 5，Segment snapshot 默认 3；所有组合上限均为 24，按固定来源顺序返回并隔离局部
失败。Attribution snapshot 不包含独立的归因表现产品，也不包含仍为 draft 的用户/设备级明细查询。

`analysis defaults` 一次读取调用方精确选择 App 的已登记 SDK 默认值字典，结果 schema 为
`gravity-insight.analysis-default-dictionary.v1`。当前完整键集合为 `api` 与 `cocoscreator`，
值均为 string array；两键全部暴露，新增键不会静默透传而是返回合同漂移。

`analysis realtime-events` 读取调用方精确选择 App 与显式 `start`/`end` 窗的实时事件目录第一页，默认 `filters.event_type=profile`。结果 schema 为 `gravity-insight.realtime-event-catalog.v1`。实测无 `page_info`，服务端一次可回 1000 条；产品暴露 6 个顶层 item 键，`raw_properties` 等省略。

### Governed export

已知 operation 和完整输入时，默认一次调用：

```powershell
gravity export run export.material.report.start --input material-export.json `
  --columns file_name,gravity_material_id,stat_cost `
  --idempotency-key material-20260812-001 `
  --output D:\exports\material.xlsx --timeout 300
```

`run` 接受 `<operation-id> --input <json|file|-> [--set PATH=VALUE] --columns <csv>
--idempotency-key <key> --output <file> [--timeout 300]`，复用现有状态机完成创建、轮询、下载、
隐私/schema 验证和原子提交。`--output` 只指定导出文件；JSON envelope 继续写 stdout，不覆盖
目标文件。未知导出先一次 `gravity agent "material report export"`，审阅卡片并补齐
`input/columns/idempotency_key/output` 后执行 `next.argv`，总共两次且不自动执行自然语言。

Agent 只为 `currently_callable=true` 的 `export_job_create` 返回 executable 卡；当前唯一操作是
`export.material.report.start`。status/cancel 路由和请求/文件合同未闭合的 Analysis exports 不作为创建候选。
卡片明确 `natural_language_auto_execute=false`、`plan_executable=false` 和 `plan_node=null`；导出
不进入 Plan v1。

`export evaluate <evaluate-operation-id>` 估算行数，不创建任务；`export task-types` 列出
已验证任务类型。这两条都不是 `gravity run` 可达的 Insight read。`start/status/wait/download/cancel/list`
是人工和恢复命令。run 或 wait 超时不会自动取消；已有 `job_id` 时用 status/wait 后在 READY
时 download 到同一显式路径。创建结果不确定且没有可靠 ID 时先
`gravity export list --page 1 --page-size 100`，不要直接重跑。详见
[导出指南](../guides/export.md)。

### First Analysis Bootstrap

调用方已经明确 App、日期窗和精确物理事件时，冷目录用两次顶层调用得到首条事件分析：

```powershell
gravity analysis bootstrap --app <id> --start <date> --end <date> `
  --target <physical-event> --plan-output first-plan.json
gravity plan run --input first-plan.json
```

bootstrap 先校验显式 App，必要时用现有 bounded worker pool 同步四类 Analysis metadata，离线精确
匹配事件，再输出 `gravity.plan.v1` 并完成 dry-run；不会执行分析或选择默认 App/事件。`--max-pages`
固定为 1，CLI transport 固定一次 attempt，所以空会话第一步最多 6 HTTP，Plan 执行只发一次业务
查询。缺输入、无可读 App、事件不存在或同步不完整时返回路径、观察值和唯一 `next_action`。

### Analysis Query Spec v1

`analysis query` 支持五种稳定分析：`event`、`funnel`、`retention`、`property`、`scatter`。
使用 `--spec` 时，调用方只声明事件、指标、日期、分组、窗口和条件等分析语义；编译器负责
生成 `query_id`、`query_item_list`、`group_by_list` 等上游 wire 结构。先查看机器合同：

```powershell
gravity analysis query --kind event --spec-schema
```

`--spec-schema` 完全离线，不创建客户端。`--spec` 接受内联 JSON、JSON 文件路径或 `-`
（stdin）；`--app <alias|id>` 选择 workspace App，`--workspace <file|directory>` 显式选择
workspace。`--start/--end` 必须成对使用，并覆盖 spec 中的日期。

下面的事件分析按天统计 `app_open` 的总次数。执行前应确认 `app_open` 是目标 App 的真实物理
事件名；如果不确定，先运行一次 `gravity metadata search "app_open" --app-id 1001`：

```powershell
gravity analysis query --kind event --app 1001 --spec '{
  "start": "2026-08-01",
  "end": "2026-08-07",
  "time_grain": "day",
  "steps": [
    {
      "event": "app_open",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    }
  ]
}'
```

漏斗响应只返回各步人数，不返回转化率。人数是该步及之前每步都完成的有序子集。调用方自算时必须先选定分母：相对上一步是本步/上一步，相对第一步是本步/第一步；三步及以上两种口径不同。SDK 不代算、不插入率字段。

下面的漏斗查询使用 workspace 的 `main` App，并通过 CLI 日期覆盖指定时间；窗口是一天：

```powershell
gravity analysis query --kind funnel --workspace . --app main `
  --start 2026-08-01 --end 2026-08-07 --spec '{
  "steps": [
    {
      "event": "app_open",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    },
    {
      "event": "purchase",
      "metric": {
        "field": "PresetAllCount",
        "aggregation": "PresetAllCount"
      }
    }
  ],
  "window": {"unit": "day", "value": 1}
}'
```

在上述命令末尾加 `--dry-run` 会离线编译并运行现有输入校验，保证
`network_called=false`，同时返回 `operation_id`、`compiled_input` 和可放入 Plan 的
`plan_node`。带条件值时预览会用占位符脱敏并把 `plan_node` 设为 `null`，避免同一敏感值在机器输出中重复；仍可直接执行原始 compact spec。正常执行已经包含相同编译与校验，不需要每次先跑 dry-run。

Spec 不接受自然语言，也不会猜测事件、属性、指标、窗口或筛选条件。物理字段未知时，先用
本地 metadata 目录确认，再执行一次 spec；自然语言能力发现仍只返回候选，不会自动联网执行。
原始 `--input` 入口继续兼容，但不能与 `--spec` 同时使用。

多个彼此独立的 compact spec 直接使用一次批量入口；它先编译全部 1–32 项，再交给同一个
Plan 全局 worker pool，并按输入顺序返回：

```powershell
gravity analysis query batch --input queries.json --concurrency 6 --dry-run
gravity analysis query batch --input queries.json --concurrency 6 `
  --output tmp/analysis-batch.json
```

`queries.json` 使用 `gravity.analysis-query-batch.v1`，每项必填唯一 `id/kind/app/spec`，可选
`start/end/output_fields/limits.max_items`。`--dry-run` 对整批完成零网络编译与 Plan 预检；任一
wrapper、预算或 literal spec 错误都会在执行前失败。正常执行保序、隔离 sibling 失败，且不回显
spec、compiled input 或筛选值。不要为批量查询再创建外层线程池。标量 query、batch 与下述多 App
入口都可用 `--output <path>` 原子写入完整 JSON；不提供 `--format`。

```json
{
  "schema_version": "gravity.analysis-query-batch.v1",
  "queries": [
    {
      "id": "daily_opens",
      "kind": "event",
      "app": "main",
      "spec": {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]
      },
      "limits": {"max_items": 200}
    }
  ]
}
```

同一 spec 跑多个 App 时只把合同版本和 App 参数改为 v2 的显式数组；当前支持
`event/funnel/retention/property`：

```powershell
gravity analysis query --kind retention --spec retention.json `
  --apps main,overseas,103 --concurrency 6 --output tmp/retention.json
```

`--apps` 可重复；它与 `--app`、跨期对比互斥。`--dry-run` 会编译每个 App 并完成 Plan 预检，
但不执行查询。Agent 或 SDK 需要直接生成机器输入时使用同一 v2 合同：

```json
{
  "schema_version": "gravity.analysis-query-batch.v2",
  "queries": [{
    "id": "weekly_retention",
    "kind": "retention",
    "apps": ["main", "overseas", 103],
    "spec": {"start": "2026-08-01", "end": "2026-08-07", "steps": ["<explicit-steps>"]},
    "limits": {"max_items": 200}
  }]
}
```

`apps` 必须是非空、唯一的 workspace alias/正整数数组；不支持 `"*"`，alias 与 ID 解析到同一
App 也视为重复。所有 query 展开后合计最多 32 个组件，超限在 Plan 前失败且零执行。每个组件
在 v2 result 中带原始 `query_id` 和提交的 `app`，保留自己的 `ok/status/result/error/exit_code`；
顶层沿用 Plan 的 success/empty/failure 计数与退出码优先级，并固定
`cross_app_aggregation=false`。SDK 不跨 App 合并行，不计算排序、TopN、汇总、差异或比率。

v1 的 `app`、节点 ID、`gravity.analysis-query-batch-result.v1` 和结果字段完全不变。v2 只做机械
展开：每个 App 仍是一个现有 `analysis_query` Plan 节点，adapter worker 固定 1，唯一并发预算是
`--concurrency` 对应的 Plan 全局预算。总请求集合等于各 App 单独执行的并集，不增加 metadata、
重试或探测请求；只可能把峰值在途数从 1 提高到该全局预算允许的值。

有依赖、binding 或需要混合 SQL/metadata/composite 时使用 `gravity plan run`。Plan composite
request 是 `name="analysis_query"` 加
`kind/app/spec`，可选成对的 `start/end`；`output_fields` 放在节点级：

```json
{
  "id": "daily_opens",
  "kind": "composite",
  "request": {
    "name": "analysis_query",
    "kind": "event",
    "app": "main",
    "spec": {
      "start": "2026-08-01",
      "end": "2026-08-07",
      "steps": [{"event": "app_open", "metric": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}}]
    }
  },
  "limits": {"max_pages": 1, "max_items": 200}
}
```

节点 `output_fields` 按底层 Analysis operation 的 data-relative FieldPolicy 选择，例如 event
可选 `list/target_list/date_list`；它不是 composite wrapper 字段。

五种 kind 与 `analysis query` 相同：`event/funnel/retention/property/scatter`。已知 kind、App
和 literal spec 时，一次 `gravity plan run --input plan.json`；未知时一次 `gravity agent`
发现候选、一次 `plan run` 执行。自然语言不会自动执行。`/app` 可以接受既有标量 binding；
`/spec/...` binding 和 spec 内部引用不受支持。完整事件示例及 event+funnel 同层并发示例见
[Plan v1 参考](plan.md#analysis-query-composite)。

### Single-user journey

已知 App、用户标识和时间窗时，一次并发读取受控 profile、event timeline 与 postback：

```powershell
gravity analysis user journey --app main --client-id <explicit-id> `
  --start 2026-08-01 --end 2026-08-07 --page 1 --page-size 20
```

也可用单个 `--date`；`--event/--field` 可重复，`--concurrency` 默认 3。结果固定按
`profile/events/postbacks` 排序并隔离局部失败，不回显 client ID、request 或凭据。上游
user-event 尚无已证明的 `page_info`，因此 v1 只读取显式页并返回
`continuation.automatic=false`；调用方根据下一页提示显式重试，不伪造自动分页。

### Order Directory v1

已知 App 和严格单日时，一次完整读取受控四字段的普通订单目录：

```powershell
gravity analysis order directory --app main --date 2026-08-08 `
  --concurrency 6 --max-pages 1000 --max-items 100000 --output <file.json>
```

命令固定调用 `analysis.order_detail.list`，使用 `page_size=100`、空 conditions/order 和四个静态
字段。成功的每行严格只含 `Amount/BackAmount/Status/CreateTime`；任何额外订单、用户、拆单或
归因标识，畸形 scalar、不完整分页收据、continuation 或预算越界都会使整个结果 fail closed，
不会裁剪前缀后冒充完整目录。它不接受任意 fields/filter/sort 或跨日窗口，也不解释退款、净收入
或订单成功。

有效请求实测为 `P` 个目录 POST、0 metadata、0 child；最小空日为 1 HTTP，7 个同层空日 Plan
节点为 7 HTTP。direct 分页 worker 默认 6、最大 24；
Plan adapter 固定 1。省略 `--output` 时输出安全 stdout 前缀；指定它时写入完整 JSON。
产品不提供 NDJSON 或 `--format`。未知入口时 Agent 返回唯一
`order_directory` Plan 节点及待填写的 `app/date`，不从自然语言取值或自动执行；否定、导出、
写入及相邻分析产品会安全报缺口且不扫描 operation inventory。精确 raw selector
`analysis.order_detail.list` 与 `analysis.order_split_detail.list` 仍保留专家兼容入口。

### Monetization Detail v1

`gravity analysis monetization detail --app main --date 2026-08-08` 固定使用完整已登记字段集和严格单日。
固定产品入口只接收 App、日期和分页预算；需要动态 fields/conditions/group/sort 时使用
`analysis.monetization_detail.list`，字段和条件继续由 live metadata 校验。有效请求实测为 `P` 个
明细 POST、0 metadata；最小空日为 1 HTTP。未登记字段仍返回
`contract_changed_additive`，详见
[历史投影裁决](../archive/decisions/2026-08/projection-and-privacy.md#投影边界总裁决全面放开2026-08-15)。

### Order Split Trace v1

已知 App、单日和显式 TraceID 时，使用一次受控 parent-child 读取：

```powershell
gravity analysis order trace --app main --date 2026-08-08 `
  --trace-id <explicit-sensitive-trace-id> --concurrency 6 `
  --max-pages 1000 --max-items 100000
```

命令固定以 `page_size=100` 和四个静态父字段完整读取受限单日目录，再在本地对 TraceID 做
大小写敏感的精确匹配。它不会把 TraceID 作为未经证明的上游 filter；零条、多条、截断、畸形
分页收据或预算不足都在 child 前 fail closed。唯一父行才触发一次严格后置的
`analysis.order_split_detail.list`，有效请求数为 `P + 1`。

direct 父分页 worker 默认 6、最大 24；`max_items` 由父扫描行和 child 行共享。产品只输出完整
JSON，不提供 NDJSON；成功行只保留 `Amount/BackAmount/Status/CreateTime`，结果和错误均不含
TraceID、ClientID、拆单 ID、PayEventTime、request 或原始异常。未知入口时 Agent 只给待填写的
`order_split_trace` Plan 节点，不提取、显示或执行自然语言中的 TraceID；精确 raw selector
`analysis.order_split_detail.list` 保持专家兼容。

### Dashboard control-plane snapshot

已知 App 和看板稳定 ID/精确名称时，一次调用读取看板控制面，不需要在 Web 中逐页检查：

```powershell
gravity analysis dashboard snapshot --app main --ref <id-or-exact-name> `
  --concurrency 5 --max-pages 5 --max-items 200
```

命令先用看板目录精确解析 `--ref`；名称歧义或不存在时 fail closed，不选择相似名称。解析后按
固定顺序读取 detail、dashboard members、space members、condition favourites 和 default
favourite 五个来源，保留 scope、operation identity 与局部失败。目录树仅用于精确解析引用，
不计入结果来源；detail 中未被合同证明的 opaque
config 会被裁剪；本产品不编译该 config，也不运行、重放或渲染看板图表。

CLI/SDK 外层并发默认 5、上限 24。Plan 使用 `{"name":"dashboard_snapshot","app":...,"ref":...}`；
adapter 内部固定 1 worker，由 Plan 全局 pool 管理并发。引用已知时直接执行是一次调用；App 已知、
引用未知时先用 `agent --resolve-inputs '{"app":"main"}' --output dashboards.json` 取得完整 live tree，
调用方精确选择稳定 ID 后执行 Plan，共两次。自然语言发现不会猜引用或自动执行。

结果较大时可把 `--output <path> --format json|ndjson` 放在 `snapshot` 子命令参数末尾；不指定
`--output` 时 JSON 输出仍受统一 stdout 裁剪保护，`--format ndjson` 可流式写到 stdout。

### Kanban 受治理写入

先离线查看完整 action/字段合同，再用同一个 action 和 JSON input 完成两步确认：

```powershell
gravity analysis dashboard kanban schema
gravity analysis dashboard kanban mutate --action dashboard.create --input kanban-input.json --dry-run
# 人工审查 request、target、impact/cascade 与 preview_fingerprint
gravity analysis dashboard kanban mutate --action dashboard.create --input kanban-input.json --execute
```

create/copy 名称自动添加 `GSDK-<12 hex>`；rename 保留 marker。delete 执行前重读 target marker，
含 report association 的 dashboard 不允许删除。folder/space delete 的 dry-run 会只读最新 tree，明确
报告 folder container、迁移 dashboard 和实际删除 dashboard 的数量；execute 再读一次 preimage，
只发一个 attempts=1 写请求，随后读回。share、未标记对象和多维报表内容不在本产品范围。

SDK 使用 `sdk.kanban_mutation(action, inputs, execute=False|True)`。Plan composite request 为
`{"name":"kanban_mutation","mode":"preview|execute","inputs":{"action":...,"inputs":...}}`；
只有调用方显式给出 execute mode 才能发送写请求，自然语言 Agent 卡永不自动写。

### Dashboard Analysis Replay v2

已知 App、看板引用和时间窗时，一次调用即可编译或执行声明的图表：

```powershell
gravity analysis dashboard prepare --app main --ref "Growth Overview" `
  --start 2026-08-01 --end 2026-08-08 --max-charts 32
gravity analysis dashboard run --app main --ref "Growth Overview" `
  --start 2026-08-01 --end 2026-08-08 --concurrency 6 `
  --max-charts 32 --max-items 100000
```

`prepare` 读取目录和详情、编译支持的 chart，但不执行最终查询；`run` 使用同一编译结果并发
执行，默认 6、上限 24，默认最多 32 个 chart，显式 `--max-charts` 硬上限 64。结果严格按看板
声明顺序返回，单图不支持或失败不会取消 sibling。start/end 都包含在 Gravity `date_list` 内，
允许同一天，最长 90 天；`--max-items` 同时约束目录、图表和结果规模。

编译器边界来自公开静态 Web artifact 中已证明的 event/funnel/retention/property/scatter
配置构造。它不是浏览器模拟器：不解释布局，不应用 favourite，也不模拟页面级 global filter；
无法证明的 subject/config 以结构化 unsupported chart 返回，不猜字段或改用任意 HTTP。

引用已知时 CLI/SDK 是一次顶层调用。App/窗口已知、引用或能力未知时先运行带
`--resolve-inputs` 的 Agent，精确选择 live tree 中的稳定 ID 后执行其 Plan node，总共两次；
自然语言卡永远不自动执行。

### Segment Snapshot v1

已知 App、分群稳定 ID/精确名称和单日日期时，一次调用替代 Web 中的目录、详情、历史和当日
结果页面切换：

```powershell
gravity analysis segment snapshot --app main --ref <id-or-exact-name> `
  --date 2026-08-01 --concurrency 3 --max-pages 5 --max-items 200
```

命令先精确解析 `--ref`，歧义或不存在时 fail closed；随后固定按 `detail/history/daily_result`
顺序读取并隔离局部失败。`--date` 是单个 `YYYY-MM-DD`，不表示趋势时间窗。结果不包含成员、
用户标识、规则定义、request 或原始异常；结果 schema 是 `gravity-insight.segment-snapshot.v1`，
固定 `source_count=3`，最小 `max-items` 为 4（目录命中与三个来源）。

已知输入时 CLI/SDK 是一次调用。App/日期已知、引用未知时，只有明确包含“分群快照/检查 + 详情 +
历史 + 单日计算结果”的强意图才会在线返回完整分群目录；调用方精确选择稳定 ID 后执行 Plan，共两次。
泛分群、规则评估、成员/用户列表、导出和写操作不会命中，且自然语言不会自动执行。

### Segment Members v1

已知 App 与精确分群引用时，一次调用返回该分群的成员及逐人属性：

```powershell
gravity analysis segment members --app main --ref <id-or-exact-name> `
  --fields 'Name,ClientID,user$level' --max-items 100000
```

不传 `--fields` 时返回登记的完整 profile；固定字段可直接填写，动态属性先用 `gravity metadata properties --app ...` 或 `gravity metadata search ...` 发现 live user-property 名称，再原样传给 `--fields`。字段选择在完整上游响应之后本地执行，不发送给上游。历史成员不用日期，而用可选 `--segment-version-id`。上游 route 没有可控分页；结果超过 `--max-items` 时 envelope 为 `partial` / exit 3，不伪造 continuation。schema 为 `gravity-insight.segment-members.v1`。

### Segment Mutation v1

分群写只通过领域命令开放；必须先 dry-run，再人工确认执行。dry-run 零网络并展示 exact request 或需要执行期 detail preimage 的 request template：

```powershell
gravity analysis segment create-from-analysis --spec funnel.json --app main `
  --name SDK测试漏斗 --step 1 --loss --idempotency-key funnel-loss-20260816 --dry-run
gravity analysis segment create-from-analysis --spec funnel.json --app main `
  --name SDK测试漏斗 --step 1 --loss --idempotency-key funnel-loss-20260816 --execute
gravity analysis segment create-from-rule --spec segment-rule.json --app main --dry-run
gravity analysis segment update --segment-id <id> --name SDK测试改名 --remark "待验证" --dry-run
gravity action segment-update preview --input segment-update-action.json
gravity action segment-update execute --plan-id <plan-id> --confirm-plan <same-plan-id> `
  --preview-fingerprint <reviewed-fingerprint> --input segment-update-action.json
gravity action dashboard-delivery preview --input analysis-dashboard-action.json
gravity action dashboard-delivery execute --plan-id <plan-id> --confirm-plan <same-plan-id> --preview-fingerprint <reviewed-fingerprint> --input analysis-dashboard-action.json
```
其他 direct 入口包括 `create-from-history/create-from-tmp/update-rule/refresh/delete`；它们同样要求显式 `--dry-run|--execute`，行为不因 Action Plan 改变。`segment-update-action.json` 固定为 `gravity.segment-metadata-update-request.v1` 的 exact `segment_id/name/remark`；`analysis-dashboard-action.json` 固定为 `gravity.analysis-dashboard-request.v1` 的完整 Artifact、`app_id/space_id/dashboard_id` 和唯一 `markdown_notes/artifact_scope/single_column` presentation，二者都不接受自然语言授权，后者也不接受 `ui_config` 或 `report_list`。

create 在 `segment_remark` 前缀写入可见 `GSDK-<12 hex>`，完整列表和 detail 读回后才返回 created；同 marker+同名复用已存在对象；direct update/delete 继续在执行时重读 exact detail 并要求 GSDK marker 或 `create_user_id == gravity_id`。Action preview 额外绑定同一 preimage/owner、managed fields、principal 与 expiry。
Action execute 必须同时重交相同 request、`plan_id`、同值 `--confirm-plan` 和 preview fingerprint；CLI invocation 才构造 current user authorization，tool/Context/Skill/history 不能授权。
确认先原子 plan+field claim，再由既有 Segment owner 在 write lock 内检查 preimage 并最多写一次；上游没有 revision/CAS，最后读取后的外部竞态只能靠 readback 判为 uncertain，确认不可重放。
成功为 `gravity.action-execution.v1 status=succeeded` 且 managed-field/ownership readback verified；写后不确定为 `uncertain`、`automatic_retry=false`，不伪装成功。
原 direct 结果仍是 `gravity-insight.segment-mutation.v1`；Action 不进入 Plan v1，也不改变其他 mutation family。
### Experiment Proposal / Outcome Handoff

`gravity experiment propose --input proposal-request.json` 只编译 `gravity.experiment-proposal.v1`：source Analysis Result、planning snapshot、Target Segment、Primary Metric、Guardrails、预计算 power evidence 与 Context assumptions 任一缺失或未对齐时固定为 `proposal_only`；全部满足也只到 `ready_for_review`，`experiment_creation_authorized=false`，不联网、不创建实验。
`gravity experiment outcome-handoff --input outcome-request.json` 要求 completed external observation 与 Proposal ID/digest 相等，并把后置、非重叠 evidence window 交给固定 `analysis.experiment-outcome-evaluation@1`。`handoff_ready` 只表示交接结构完整；当前 significance Operator 缺失使 Outcome Journey 继续 `blocked/OPERATOR_UNAVAILABLE`，且 `evaluation_performed=false`、同一运行与原建议自证永远禁止。
### Segment Rule Spec v1

人群规则人数/占比评估使用紧凑 spec，不需要拼接 FE_CONFIG 或上游 Web JSON：

```powershell
gravity analysis segment evaluate --spec-schema
gravity analysis segment evaluate --app main --spec segment.json --dry-run
gravity analysis segment evaluate --app main --spec segment.json --fields part,percent,total
```

`--spec` 接受内联 JSON、文件或 `-`；`--start/--end` 可覆盖 spec 日期。顶层字段是
`app/name/remark/update_type/start/end/logic/property_rules/event_rules`，完整条件、事件目标、日期
模式和枚举以 `--spec-schema` 为准。`--dry-run` 只编译并执行离线校验，返回脱敏预览和
`needs_live_metadata` 依赖，不发最终查询；物理事件、属性、分群与版本仍需执行阶段的实时元数据
证明。旧 `analysis segment --kind evaluate --input ...` 继续兼容现有调用方。

明确询问“人群/受众规则命中人数或占比评估”时，`gravity agent` 唯一返回
`analysis.segment.rule.spec` 强卡，包含完整紧凑 schema、缺失的 `app/spec` 和可复制的
`segment_evaluate` composite Plan 节点；自然语言不生成规则或自动执行。泛分群、成员、历史、
详情和导出不会误配此卡。

### Saved Analysis v4

保存分析入口把稳定的保存目录、详情读取和现有 Analysis Spec 编译器连成一条受控路径。已知
引用时不要手工执行 `operations search/describe`，直接运行：

```powershell
# 浏览目录；list 不需要 --ref
gravity analysis saved list --app main --concurrency 6

# 按稳定 ID 或精确名称查看受控定义摘要
gravity analysis saved get --app main --ref <id-or-exact-name>

# reference Web artifact：读取定义并编译，但不执行最终分析查询
gravity analysis saved prepare --app main --ref <id-or-exact-name> `
  --start 2026-08-01 --end 2026-08-07

# 本地 definition 直接严格编译，零网络且不需要 Gravity 凭据
gravity analysis saved prepare --app main --definition <json-object-or-file>

# reference Web artifact：一次解析、严格编译并执行
gravity analysis saved run --app main --ref <id-or-exact-name> `
  --start 2026-08-01 --end 2026-08-07

# create/update 都提交完整、可严格重放的五类定义；先预览，再原参数确认
gravity analysis saved create --app main --name "GSDK analysis" `
  --subject analysis_event --config event-config.json --dry-run
gravity analysis saved create --app main --name "GSDK analysis" `
  --subject analysis_event --config event-config.json --execute

gravity analysis saved update --app main --id <saved-analysis-id> --name "GSDK analysis v2" `
  --subject analysis_event --config event-config-v2.json --dry-run
gravity analysis saved update --app main --id <saved-analysis-id> --name "GSDK analysis v2" `
  --subject analysis_event --config event-config-v2.json --execute

gravity analysis saved delete --app main --id <saved-analysis-id> --dry-run
gravity analysis saved delete --app main --id <saved-analysis-id> --execute
```

`--app` 接受 workspace alias 或正整数。`--ref` 只接受稳定 ID 或精确名称；精确名称命中
多个项目会以 caller/2 失败，要求改用稳定 ID，不会静默选择第一项。分析 kind 由保存定义
中已登记的 subject 决定，调用方不能覆盖。若 reference 是 Web artifact，`prepare/run` 必须提供
成对 `--start/--end`；两端会包含在下发窗口中且 `end-start` 不超过 90 天，主路径建议
`YYYY-MM-DD`。旧 compact reference 可省略 window，并保留原定义的日期语义；只提供一端始终在
建客户端前失败。`list/get` 不要求日期窗，`get` 会明确报告该引用是否需要 window。

`list` 返回 `gravity-insight.saved-analysis-catalog.v2`。目录没有 `config`，所以每项固定为
`replay_supported=null`、`replay_status=unchecked`；`subject_supported=true` 只说明存在对应
compiler，不证明该条 Web config 已登记。按精确引用执行 `get` 或成功 `prepare/run` 后，才会返回
互相一致的 `replay_supported=true|false` 与 `replay_status=supported|unsupported|requires_window`。

Strict Replay 不是通用 Web 配置翻译器。reference 模式只接受静态证据已证明的 Web artifact，
并直接复用现有 `event/funnel/retention/property/scatter` 五类编译器；未知字段、无法证明的
opaque config 或其他 kind 均结构化失败，不降级为裸请求。显式 `--definition` 的 compact spec
保留旧兼容模式。两种模式都不解释 template、layout、favourite、权限或页面状态。
`list/get/prepare/run` 均支持 `--output <path>` 与 `--format json|ndjson`；目录较大时应显式落盘，
避免 stdout 的安全摘要上限遮住后续条目。
四个命令也都接受 `--concurrency 1..24`（默认 6），只在目录首页证明总页数后并发读取后续页，
结果仍按页码保序；未知总页数保持串行。Plan adapter 固定分页 worker 为 1，避免与 Plan 全局并发相乘。
`prepare --ref` 为解析引用会读取在线目录以及必要详情，所以它不是离线 dry-run；它与 `run`
的区别是不会发送最终分析查询。定义编译自身保持零网络，并在
`validation.live_metadata_dependencies` 完整声明执行期可能需要的 metadata；只有 `run` 在最终 query
前执行这些实时成员关系校验。`list/get` 也会访问已登记的 stable 只读 operation。

`create/update/delete` 共用 `analysis.report_config.update`，但卡和 CLI 按调用方动作分开。
create/update 的 `--config` 接受 inline JSON、文件或 `-`，并在写前复用五类 strict replay compiler；
只开放 event/funnel/retention/scatter/user-property，另外三类 config 尚未证明而 fail closed。create 写入
GSDK marker；update/delete 执行时要求 marker 或 `create_user_id == gravity_id`，删除 HTTP 200 后还会
完整列目录确认 ID 消失。三种动作均须二选一显式传 `--dry-run` 或 `--execute`；自然语言 Agent 卡只
给出两步命令，不自动写。分享不属于本入口。

Agent 查询 `run saved analysis <ref>`、`运行保存分析 <引用>`，包括 `--domain report`，唯一
权威候选是 `composite:saved_analysis`。卡片明确缺失 `app/ref/start/end`，Plan request 为四项
提供可机械填写的槽位，可选 `mode=prepare|run`；发现本身完全离线，也不会从自然语言提取引用
或自动执行。已有引用和窗口但不知道能力时是离线 Agent + Plan 两次；App/窗口已知而引用未知时，
在线输入解析把能力卡和完整 safe catalog 放进第一调用，调用方按稳定 ID 选择后第二次执行；
第一调用中的 `unchecked` 目录项只证明可选择，不是 replay 许可。

### Business pulse

一个命令并发读取 App 概览和经营趋势；`--app` 可重复或用逗号分隔，支持 workspace alias 或
正整数。平台默认包含 `bytedance/tencent/kuaishou`，可重复指定 `--platform`：

```powershell
gravity reports pulse --app main --start 2026-08-01 --end 2026-08-07 `
  --platform bytedance --include-hourly --output tmp/business-pulse.json
```

基础结果按 `overview`、`business` 顺序；`--include-hourly` 才追加
`hourly_comparison`。前两项是 `scope=app`，小时对比受上游合同限制并明确标记
`scope=workspace`，不能解释为单个 App 的小时结果。组合复用现有 stable operation、批量并发、
分页和局部失败合同；不推导业务结论或指标别名。

`--output` 原子写入完整 JSON，不提供 `--format`。`partial` 仍写文件并保留非零退出码，成功与失败
source 都留在 envelope 中；纯 `error` 或 `capability_gap` 不创建也不替换目标文件。

未知入口使用 `gravity agent "business pulse" --domain report`。明确 Pulse/脉搏或同时表达经营
概览与趋势的请求返回唯一 `composite:business_pulse`，且不扫描 operation inventory；卡片给出
完整的 `apps/start/end/platforms/include_hourly` Plan request。调用方显式替换占位值后执行，
自然语言不填值也不自动执行。泛 `business analysis/经营分析` 和多维、看板、保存分析、归因、
模板或导出意图不会被 Pulse 抢占。

同一 `reports` 命名空间还提供无 App 输入的公司资源用量趋势：

```powershell
gravity reports usage --max-pages 1000 --max-items 100000
```

命令完整分页读取已登记的广告、广告创建、点击、成本、事件、画像、存储、追踪和素材传输用量，
返回 `gravity-insight.company-usage.v1`；稳定投影固定排除 `user_count`，未知上游字段继续
fail closed。未知入口使用 `gravity agent "company resource usage" --domain report`，返回唯一
`composite:company_usage`，无需补 App、日期或引用，发现后执行共两次调用。

### 报表目录与订阅

报表目录与订阅都是无 App 输入的账号级产品：

```powershell
gravity reports directory --max-pages 1000 --max-items 100000 --concurrency 6
gravity reports subscriptions --max-pages 1000 --max-items 100000
```

目录完整分页后对每个精确 ID 读取 detail，返回 `gravity-insight.report-directory.v1`；订阅返回
`gravity-insight.report-subscriptions.v1`。两者均可直接进入 Plan。写操作必须显式二选一
`--dry-run` / `--execute`：`create/delete` 管理旧报表，`subscribe/unsubscribe` 管理 disabled、空收件人
订阅。create 写入 `GSDK-<12 hex>`，delete 只处理执行时读回仍带 marker 的对象。Agent 只返回预览与
确认后的两步 argv，`natural_language_auto_execute=false`，写操作不进入 Plan v1；永不调用
`subscribe/test`。

最小确认流程如下；第二条必须与第一条参数完全相同，只改变确认开关：

```powershell
gravity reports create --app-id <app-id> --name <name> --config <config.json> --dry-run
gravity reports create --app-id <app-id> --name <name> --config <config.json> --execute

gravity reports delete --report-id <marked-report-id> --dry-run
gravity reports subscribe --report-id <v3-report-id> --report-name <exact-name> `
  --start <date> --end <date> --column <exact-column> --dry-run
gravity reports unsubscribe --subscription-id <marked-subscription-id> --dry-run
```

后三条也只有在人审 preview 后，才用原参数将 `--dry-run` 改为 `--execute`。ID、名称、配置、日期和
列名必须来自调用方或已登记目录，不从自然语言复制或猜测。

### 自定义指标口径 CRUD

当前 turbo confmetric 目录提供完整的 list/create/update/delete 产品面。create 和 update 共用上游
`edit` upsert：省略字符串 ID 是创建，带列表返回的精确字符串 ID 是更新；调用方不直接构造 wire
`config`。所有 mutation 默认只做零网络 preview，执行时单次写入、无自动重放并在写前后完整读回。

```powershell
gravity reports custom-metrics schema
gravity reports custom-metrics list
gravity reports custom-metrics create --name <name> --formula <formula> `
  --description <text> --display-format 1 --idempotency-key <key> --dry-run
gravity reports custom-metrics update --metric-id <string-id> --name <name> `
  --formula <formula> --description <text> --display-format 2 --dry-run
gravity reports custom-metrics delete --metric-id <string-id> --dry-run
```

人工审查后只把同一命令的 `--dry-run` 改为 `--execute`。create 在 `tip` 写
`GSDK-<12 hex>`；update/delete 必须由该 marker 或列表暴露的 `create_user_id == current principal`
通过共享 owner gate。删除后再次完整读取当前目录并证明 ID 消失。Plan 使用
`custom_metric_mutation` composite 的显式 `preview|execute`，Agent 分别提供
`custom_metric.list/create/update/delete` 四张卡；自然语言不会自动写。指标权限和 share 不属于本产品。

### Custom audiences

自定义人群覆盖与状态是独立 Promotion 产品，不属于 promotion performance：

```powershell
gravity promotion custom-audiences --max-pages 1000 --max-items 100000
```

命令完整分页读取可投人群的覆盖数、上传数、来源和状态，返回
`gravity-insight.custom-audience.v1`。`cid/company/create_user_*/tag/update_user_*` 已登记返回，
未登记字段失败关闭。未知入口使用 `gravity agent "custom audience coverage status"
--domain promotion`，返回无缺失输入的唯一 `composite:custom_audience` 卡。

## Journey And Capability Trust

```powershell
gravity journey list
gravity journey verify
gravity journey describe analysis.merge2.ap-cost-anomaly-localization
gravity --workspace <project> journey can-run analysis.merge2.ap-cost-anomaly-localization --input <request.json>
gravity journey impact --input <capability-impact-request.json>
gravity --workspace <project> journey run analysis.merge2.ap-cost-anomaly-localization --input <request.json>

gravity capabilities trust operation app.list
gravity capabilities validate --input <capability-validation.json>
gravity capabilities impact --input <capability-impact-request.json>
```

`list/verify/describe/can-run/impact` 严格离线；`run` 也先执行同一 readiness，只有
`can_run_status=verified` 才委托既有 `metric-anomaly-localization@1` / Plan v1 路径。
当前 `report.multidim.query` 的合同完整性是 `unknown`，低于 Journey 要求的 `complete`，
因此真实项目 `can-run/run` 返回 exit 4、`blocked` 和
`COMPLETENESS_INSUFFICIENT`，不构造凭据、不发目标请求、不发布 findings。
Project Semantic 与 formal Context Requirement 来自调用项目；内置 Repo Provider 按实体、时间、authority、freshness、sensitivity 与预算组装 Pack。
离线使用 `gravity context project describe|index|search|get|pack|verify --project-id <id>`；search 只返回 role=data 候选，不能自动进入 Pack。
结果和 Receipt 只携带 URI、revision、hash、digest 与精确 citation，不保存正文；Skill/CLI 不新增 executor、binder、pagination 或 permission 逻辑。

Capability Trust 的 `stable` 必须同时有同层合同、匹配 provider fingerprint、未过期的当前
Validation、满足要求的 completeness 和 DQ；子 Operation 不能替 Product/Composite 生成
Trust。`validate` 只验证输入，不写 principal-scoped store。impact 输入固定为：

```json
{
  "schema_version": "gravity.capability-impact-request.v1",
  "changes": [
    {
      "identity_kind": "operation",
      "selector": "report.multidim.query",
      "change_kind": "provider_fingerprint_changed"
    }
  ]
}
```

合法 `change_kind` 为 `provider_fingerprint_changed|contract_changed|lifecycle_changed|validation_changed|data_quality_changed`。
输出只列受影响 Capability、Skill、Journey identity 与稳定 reason code，不执行或重跑生产查询。

## Skills and Team Hub

```powershell
gravity skills list
gravity skills show skill://gravity.game/ap-cost-anomaly-localization@1.0.0
gravity skills export-agent skill://gravity.game/ap-cost-anomaly-localization@1.0.0 --output <parent-directory>
gravity skills sync --source hub-source.json --repository <local-git-mirror> --state-root <state>
gravity skills lock --skill skill://org.example/team-analysis@1.0.0 --output gravity.skills.lock.json --state-root <state>
gravity trusted-packs install-plan --lock gravity.trusted-packs.lock.json --output install-plan.json --state-root <state> --cas-root <cas>
```

`list/show/export-agent` 继续只读 Built-in package；Team Hub 的 `sync/search/show/resolve/lock/fetch/install/update/verify/audit` 只接受显式本地 Git mirror 或 exact static HTTPS Source，search 不选择版本，lock 不含本机状态，install 只物化无代码 Render Model。Trusted Pack 使用独立 `resolve/lock/fetch/verify/install-plan`、lock 与 CAS；计划只交给外部 Installer，不执行 pip、加载 entry point 或绑定 Runtime，R09B 才负责项目 Team lock。

## Analysis playbook

```powershell
gravity analysis playbook schema
gravity analysis playbook run --input anomaly.json --dry-run
gravity analysis playbook run --input anomaly.json --output result.json
gravity analysis playbook run --input changed.json --checkpoint result.json --output resumed.json
```

当前只有 `metric-anomaly-localization@1`。它把四个现有 `semantic_compose` 查询编译为普通
`gravity.plan.v1`，并在结果 checkpoint 中保存可复用 Plan item；修改 hypothesis 时只执行两个
validate 后继。完整结论只针对两个窗口中返回的 `click_company/ap_cost` 行及其和，不代表未返回渠道
或完整 App total。任何 partial、capability gap、error、skipped、empty 或证据 identity 不一致都返回
`conclusion=null` 与空 `allowed_claims`。完整 DAG、事实路径和恢复规则见
[Plan 参考](plan.md#metric-anomaly-localization1)。

## Plan v1

```powershell
gravity plan schema
gravity plan run --input plan.json --dry-run
gravity plan run --input plan.json --concurrency 6
```

`schema` 输出 `gravity.plan-schema.v1`，包括节点类型、字段、预算、失败合同，以及
`composites.analysis_query` 的 `binding_targets` / `spec_binding` / `request_fields`。
`run` 的输入必须是 `gravity.plan.v1` 对象。最小可复制示例：

```json
{
  "schema_version": "gravity.plan.v1",
  "nodes": [
    {
      "id": "apps",
      "kind": "run",
      "request": {
        "selector": "app.list",
        "inputs": {"page": 1, "page_size": 20}
      },
      "limits": {"max_pages": 1, "max_items": 20},
      "output_fields": ["id", "name"]
    }
  ]
}
```

四种节点：

| `kind` | `request` 核心字段 | 执行边界 |
| --- | --- | --- |
| `run` | `selector`、`inputs`/`parameters`、可选 `app/start/end/all_pages` | operation 或 `@recipe` |
| `sql_product` | `product` 及该 Workspace 产品的 App/时间输入 | 已登记产品，禁止裸 SQL |
| `metadata_search` | `query`、可选 `kind/app_id/limit/offset/max_age_hours` | 已同步的本地 catalog；`kind=status` 严格离线 |
| `composite` | `name`、组合所需 App/查询输入 | 仅登记的 analysis/segment query、context/dashboard/app/attribution snapshot/performance、business pulse/company usage、multidim、material/promotion performance 与单 App `metadata_sync` |

每个节点还可声明 `depends_on`、标量 `bindings`、一个有限 `foreach`、`limits` 和
`output_fields`。binding/foreach 的 `from` 必须显式位于 `depends_on`，路径使用 RFC 6901 JSON
Pointer。预检覆盖 schema、ID、依赖、环、pointer、adapter 输入和最坏预算；任一节点预检
失败时零网络请求。

Business pulse 的 Plan 节点使用同一实现；`apps/start/end` 必填：

```json
{
  "id": "pulse",
  "kind": "composite",
  "request": {
    "name": "business_pulse",
    "apps": ["main"],
    "start": "2026-08-01",
    "end": "2026-08-07",
    "include_hourly": true
  },
  "limits": {"max_pages": 20, "max_items": 5000}
}
```

Plan 中小时结果仍为 `scope=workspace`；adapter 内部 worker 固定为 1，由 Plan 全局 worker pool
管理并发。binding 只接受 `/start`、`/end`、`/include_hourly`；`apps/platforms` 必须在提交前
作为显式数组给出，Plan v1 不把 scalar binding 当作数组。

`analysis_query` 同样由全局 pool 调度；同层独立查询并发，adapter worker 固定 1。一个查询
失败不取消 sibling，结果仍按节点声明顺序返回。节点 `max_items` 和 Plan 总预算共同限制结果
规模；失败结果不回显 request、spec、binding 值或原始异常，筛选值遵守既有脱敏合同。
bootstrap 生成的 event request 另带闭合 `metadata_snapshot`；执行前复验 App、freshness、同步时间和
catalog fingerprint，并从只读快照完成 FieldPolicy。快照缺失或漂移时 fail-closed，不回退到 live metadata。

外层并发默认 6、上限 24，adapter 内分页 worker 固定 1；SQL 的进程级并发仍为 2。声明节点
最多 64、展开执行最多 256、总 `max_items` 不超过 100,000。每个 foreach 默认最多 32、硬
上限 64，不支持嵌套或笛卡尔积。独立失败不取消 sibling，依赖失败的下游标记
`skipped/DEPENDENCY_FAILED`。结果按 Plan 声明顺序、foreach 源数组顺序返回；失败项
`result=null`，且不会回显 request、SQL、绑定值或原始异常。

## Metadata

```powershell
gravity metadata status [--app-id <id>] [--max-age-hours 24] [--database <path>]
gravity metadata sync --app-id <id> [--max-pages 1..8] [--database <path>] [--dry-run]
gravity metadata sync --all-apps [--database <path>] [--concurrency 1..24]
gravity metadata search [query] [--app-id <id>] [--database <path>]
gravity metadata events [query] [--app-id <id>] [--database <path>]
gravity metadata properties [query] [--app-id <id>] [--database <path>]
gravity metadata vocabulary [query] [--kind vocabulary|metric|custom_metric|metric_tag|metric_tag_category|media_enum|template]
gravity metadata tables [query] [--database <path>]
gravity find <query> [--backend operations] [--backend metadata]
```

默认位置是用户私有缓存下的 `GravityInsight/metadata/catalog.sqlite3`。`status` 与查询命令都以 SQLite
只读模式运行，不创建客户端、不读取凭据、不访问网络；status 回答目录是否存在/兼容、哪些 App 同步过、
同步时间、年龄/过期、四类对象数和失败数。它不能证明上游此刻是否变化、账号权限是否仍有效或业务词
如何绑定物理事件。

单 App sync 只替换目标 App，保留兼容 catalog 中其他 App、workspace 词汇与 lineage。它固定读取事件、
事件属性、用户属性和事件属性分组四类对象；其中三个分页 operation 各受 `--max-pages` 限制，另一个
非分页 operation 一次，所以同步前可机械得到逻辑请求上限 `3 * max_pages + 1`（默认 7，硬上限 25）。
`--dry-run` 零网络、零写入返回该界；执行摘要返回实际逻辑请求、receipt 可见的 HTTP/重试、各 operation
页数、对象数和失败。达到页界时保留安全前缀并显式标记 `partial/PAGE_BOUND_REACHED`，不冒充完整快照。
逻辑界不包含 transport 固定 retry 或一次鉴权刷新，两者只在执行后从 receipt 报告。

全 App 同步继续采用 staging 构建和原子替换；除 App 目录外，固定读取 9 个 workspace Analysis 词汇来源
各一次，请求数不随 App 增长，但 App 数与分页使总请求无法预先收敛到单 App 的 25 次界。部分失败保留
成功数据和失败来源；`status=partial` 不代表完整目录。
`find` 对三个目录做稳定相关性排序；backend 是显式注册表。

冷目录的两调用 Agent 路径使用
`gravity agent <query> --resolve-inputs '{"catalog_policy":"refresh"}' --output catalog.json`。与普通
`metadata sync` 可保留 partial 快照不同，这个集成 refresh 只有全部成功才发布；失败时旧 catalog
原样保留且解析命令失败。第二调用执行 metadata/table Plan 节点，结果继续携带同步时刻和 observed
语义。此模式合并顶层命令，不减少 sync 内部请求数。

`vocabulary` 搜索物理/自定义指标、指标标签与分类、媒体枚举和 mine/shared/preset 模板。它们都是 workspace scope，不接受 `--app-id`。`gravity agent <query>` 对强匹配返回同 kind 的 `metadata_search` Plan node；指标卡的 `request_fragment` 可复制进显式 Analysis spec，但不会自动执行。模板只提供安全目录身份，标记 `catalog_only`，不包含配置且不可回放。

`find` 当前注册 `operations`、`recipes`、`metadata` 三个 backend。`recipe validate` 只验证 workspace 声明；`recipe check` 还检查 operation 存在性/废弃状态、输入和输出字段及合同指纹，仍不访问网络。`recipe accept-contract` 先展示合同 diff：纯增量可直接重钉调用方 `gravity.toml` 的指纹；删除或类型变更默认拒绝，须同时给 `--allow-breaking --reason`，理由写入 envelope。不改 SDK 合同。

Resolver 常用形式：

```powershell
gravity run @retention-weekly --start 2026-08-01 --end 2026-08-07
gravity run <operation-id> --app <alias-or-id> --input <json> --set page_size=100
```

recipe 参数用 `--param name=value`，`start/end` 有同名快捷参数。`--app` 先查 workspace alias，未命中时只接受正整数 App id。Resolver 失败输出按输入合同、父资源、空结果和本地事件相似候选排序；相似候选只是字符串距离，不建立业务绑定。

workspace 的发现顺序、最小配置和 recipe 字段见 [Workspace 参考](workspace.md)。

`operations`、`validate`、`find`、`recipe validate/check/accept-contract`、`metadata status/search/events/properties/vocabulary/tables` 以及单 App sync 的 `--dry-run` 都不需要网络客户端，因此不会触发首次凭据向导。新增离线命令必须在自己的 parser 上声明相同属性。

## SQL

| 命令 | 用途 |
| --- | --- |
| `gravity sql --dry-run` | 离线校验 SQL 产品合同 |
| `gravity sql products` | 一次描述全部可调用产品与 query 输入合同，不返回原始 SQL |
| `gravity sql status [--json]` | 查看最近 Evidence 与可查询状态 |
| `gravity sql evidence-preflight` | Evidence 刷新前离线检查 |
| `gravity sql verify [--date ...] [--publish]` | 验证最近安全自然日；显式发布才更新 Evidence |
| `gravity sql query <product> ...` / `gravity sql explorer inspect|execute|promote --input ...` | 执行已登记聚合产品，或显式运行/晋升隔离 SQLite 探索 |

Registered SQL 只实现 `custom-sql` 受治理聚合产品；具体产品名称、SQL、App、数据源、输出字段和禁止结论全部由调用项目的 `gravity.toml` 维护。独立 Explorer 只接受显式 `gravity.sql-explorer-request.v1`：当前唯一方言为 SQLite，SQLGlot AST 单 SELECT、绝对本地 DB、`mode=ro` + `query_only` + authorizer、精确 relation/function/output allowlist、engine/progress/row/cell/byte budget 缺一即阻断；不会接管 registered SQL/Insight 失败。结果固定 `exploratory`、completeness `unknown`、allowed claims 空且零网络；SQL/path/parameters 不进入 session/error/promotion。`promote` 必须显式 review evidence 和 `--output`，只生成带 version/provenance/consumer contract 的普通 workspace product，不自动安装或授予 stable Trust。

未知产品时先运行一次 `gravity sql products`；已知产品直接 `gravity sql query`。query 支持
单个参数、`--input` 对象、数组或 `requests` wrapper，并以 `--concurrency 1..2` 保序并发。
可加 `--output <path>` 原子写入完整 JSON envelope；stdout 只返回与 Insight 产品一致的
`written` 收据。SQL 公开结果还包含状态、错误、Evidence 与查询收据，即使内部 `rows` 是二维，
也不提供会丢失这些合同信息的 CSV/表格输出。
Evidence 可用时附 reference；缺失或过期时附 warning，不阻断已登记产品查询。`status`、
`evidence-preflight` 和 `verify` 是诊断/授权维护命令，不是每次查询前要串行执行的门禁。
查询失败在 `error` 中返回 `stage=bind|compile|plan|execute|shape`、稳定 code、`retryable`、
`reached_sql_engine=yes|no|unknown`、`upstream_error` 和有界 `execution_evidence`。其中
`protocol_status` 只保留 `status/code/msg/extra.error` 的存在性与可分类标量：安全的数字/枚举
`code` 和固定协议状态词保留分类值，其他未审查字符串只返回类型、truthiness 和 SHA-256，不返回
原文，数组/对象不返回内部内容。引擎 non-success 属于
`plan/engine_rejected`，原样重试为 false；tabular rows 缺失属于 `shape`。下一步按 stage 指向
模板绑定、语法/类型与 join 合同、资源/超时收窄或响应形状复核，不再把引擎拒绝归因于认证。
批量 query 保留独立项隔离和有界并发：已经提交给 worker pool 的项不会因另一项确定性失败而取消；
`execution_evidence.request_count` 如实记录本批实际逻辑 SQL 请求数，不把该行为表述成早停。
Python 的底层 `GravityClient.execute_sql()` 只固定路由并限制并发，不执行 workspace/Evidence
产品治理；Agent 不应使用它绕过 CLI 产品。详见 [SDK 参考](sdk.md)。

SQL 进程级并发上限为 2。机制合同位于 `src/gravity_sdk/contracts/sql-products/catalog.json`；调用结果中的 `warnings` 和 `forbidden_claims` 必须保留。

## Census

| 命令 | 用途 |
| --- | --- |
| `fetch` | 下载公开前端 bundle |
| `parse` | 从 bundle 解析候选路由 |
| `params` | 提取请求参数候选 |
| `responses` / `apply-responses` | 提取并应用响应字段消费者 |
| `coverage` | 路由与 SDK manifest 对账 |
| `diff` / `impact` | 分析上游变化和 operation 影响 |
| `check-upstream` | 只读取 HTML 并比较入口 hash |

生产使用见 [路由盘点](../maintainers/census.md)。

## 认证配置

调用者只维护：

```dotenv
GRAVITY_USERNAME=...
GRAVITY_PASSWORD=...
```

token 由 SDK 私有缓存维护。不要把 token、Cookie 或密码作为命令行参数，也不要把本地凭据文件提交到 Git。

Resolver Receipt 写在 workspace 对应的 principal 私有缓存 `state_root/principals/<private-scope>/receipts/`。`<private-scope>` 只存在于磁盘布局，不进入 CLI、公开 envelope、错误或 receipt 内容。`gravity.receipt.v1` 的既有 base shape 不变；执行 owner 可按机器 schema 附加值无关的 run/Skill/Journey/Trust/Semantic/Operator/Context/Pagination/DQ/Policy/Action facets，但不得复制请求/结果值、Context 正文、用户行、账号/Scope/凭据或 Action target/preimage/owner/confirmation。`input_shape_fingerprint` 只哈希字段、容器结构和标量类型；相同结构换筛选值仍得到同一指纹。每个真实 HTTP response 另在同一私有 scope 的 `receipts/http/` 同步写入 `gravity.http-receipt.v1`；它只记录 method、合同 path、operation、status、完成时刻、页码、attempt/retry 和请求 shape fingerprint，不记录请求值、响应体或凭据。该逐请求账本先于本地投影、分页聚合与 composite/Plan envelope 组装完成。

逐 HTTP receipt 默认按数量与时间两者的更严格边界保留：最近 10,000 个且不老于 7 天，活动运行的全部 receipt 例外。可用正整数环境变量 `GRAVITY_HTTP_RECEIPT_MAX_FILES`、`GRAVITY_HTTP_RECEIPT_MAX_AGE_DAYS` 覆盖；非法值回退默认值。清理在当前 receipt 同步落盘后 best-effort 执行，失败只写 warning。使用 `gravity receipts list|get|export` 查询稳定只读合同，不要以目录 glob 当作 API。新增未登记响应字段会继续从 `data` 投影省略，但在结果 `result_audit.response_drift` 与对应 receipt 中记录 `gravity.response-drift.v1` 的 JSON Pointer 和观察类型；字段消失或类型变化仍 fail-closed。

## 输出与退出码

CLI 尽量输出带 `schema_version`、`status`、计数和结构化错误的 JSON envelope。业务数据是否为空与请求是否成功是两个维度。支持的 Windows shell 中，stdout/stderr 的文本 JSON 确定性地使用 UTF-8，不继承系统 ANSI code page；本地控制台或文件 I/O 失败属于 local/4。

| 退出码 | 类别 |
| --- | --- |
| `0` | 成功，包括合同允许的 empty |
| `2` | 输入、认证缺失等调用方问题 |
| `3` | 上游、权限或限流问题 |
| `4` | 本地合同、隐私或策略问题 |

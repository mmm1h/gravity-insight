# 维度表 wire 与分析价值探测

> 取证日期：2026-08-16。结论只适用于当次 hash-matched 前端和本租户现场。
> 本轮没有新增、晋升或修改 operation、manifest、产品卡或 Agent 动线。

## 结论

本单元按真正验收项判为**失败并停止建设**。

- 9 条预留路由的前端请求体均已静态还原；但除 `create`、`edit`、`delete` 和
  `conf_related_prop/override` 的空列表负向请求外，其余服务端响应仍未实测。
- 自建表成功：marker `GSDK-d9136038bab6`，表 ID
  `71ccfb34acd94f6aa3ef69d9ce1976fd`。创建请求原子完成两列（含中文名）、三行数据和版本 1，
  `detail` 回读为两列、三行、`using_version_id=1`；`edit` 也成功。
- 真正绑定前，先在这个尚未绑定的自建表上发送清理 wire
  `{"table_id":"…","prop_list":[]}`。HTTP 200，但上游明确返回
  `code=1004/msg=参数错误/extra.error="prop_list is empty"`。前端同时强制至少保留一条关联，
  没有产生空列表的 UI 路径。因此没有可证明的“解除最后一条关联”操作。
- 按任务停止条件，本轮没有绑定事件属性，没有尝试猜测 `null`、省略字段或依赖删表级联，
  也没有继续新版本、版本切换、中文名修改、下载任务或绑定后分析。
- 绑定前分析基线确实非空：App `26827043` 的 `order_status` 事件按 `order_id`
  在 2026-08-15 单日分组，修正后的请求返回 5,000 个分组、72,402 次事件。直播属性元数据中
  `order_id` 为 `STRING/id=2473840`，且没有 `dim_table` 绑定字段。由于没有安全解绑能力，
  无法取得“绑定后按业务属性分组”的结果，因而没有证明维度表能提升分析能力。
- 清理完成：删除返回语义成功；同一 marker 的表列表为 0；已删表的版本 ID 集合为 `[]`；
  从未创建属性绑定。没有残留对象或事件属性影响。

因此现在不应把剩余 8 条预留路由接入产品。应先由上游 owner 提供可验证的精确解绑合同，或新增
“删除最后一条关联”的正式路由；然后才能重新做绑定前/后同查询对照。只实现建表和版本管理，无法满足
“裸 ID → 业务属性 → 分析分组/筛选”的产品价值判据。

## 静态证据

仓库冻结 snapshot 指向三份 bundle。2026-08-16 重新 GET 后，大小和 SHA-256 与 snapshot 逐字一致：

| Bundle | Bytes | SHA-256 |
| --- | ---: | --- |
| `DataSheet-CgxGx0E4.js` | 48,102 | `d95d7acc08984d4c08e6b23a86132cf1ccf949204022319462156d06297815e2` |
| `dataSheet-data-D_dWJH0x.js` | 14,128 | `4c067e3c775ed18a3fed8a3a5dda45277b76798a2b44cfaf6ae756bc868cf964` |
| `DimEditDialog-DO5rc9go.js` | 25,392 | `b0fd4b190a74224d2fad82df8a410c6ae022099fa4a4f22aecc99461c91f4747` |

三份 bundle 都声明 sourcemap，但三个 `.js.map` URL 均返回 `NoSuchKey`。以下结论来自格式化后的
minified 控制流，不来自 sourcemap，也不把前端校验误写成服务端合同。

### 共同列结构和值域

`column_list[]` 的前端 wire 为：

```json
{
  "name": "<ASCII letters/digits/underscore; at most 64 chars>",
  "cname": "<non-empty Chinese/display name>",
  "data_type": "STRING|INT|FLOAT|BOOL|DATE|DATETIME|LIST",
  "is_pk": true
}
```

首列固定为主键；主键类型只允许 `STRING|INT|FLOAT|BOOL`。前端对行值的词法校验为：

- `INT`: `^\d+$`；
- `FLOAT`: `^\d+(\.\d+)?$`；
- `DATE`: `YYYY-MM-DD`；
- `DATETIME`: `YYYY-MM-DD HH:mm:ss`；
- `BOOL`: `true|false|TRUE|FALSE`；
- `LIST`: 可 JSON 解析且结果是 array；
- 主键不得为空，上传数据先按主键去重。

这些是 UI 可生成值域；没有逐项试错证明服务端完全相同。

## 9 条预留路由逐条 wire

“前端必填”指表单校验；“总是发送”指 bundle 的提交对象每次含该键。除已列实测外，不能把它外推为
服务端 required。

### 1. `metadata.dim.data.table.create` — 已还原，实测成功

```json
{
  "app_id_list": [26827043],
  "cname": "<2..40 chars; frontend required>",
  "name": "dim_<2..40 ASCII letters/digits/underscore>",
  "remark": "<string; UI max 100>",
  "column_list": [
    {"name": "order_id", "cname": "订单道具ID", "data_type": "STRING", "is_pk": true}
  ],
  "column_val_list": [
    {"order_id": "<value>"}
  ]
}
```

UI 输入的英文名提交前自动加 `dim_`。`app_id_list/name/cname` 是表单必填；`remark` 选填但总是发送。
`column_list/column_val_list` 来自 Excel，UI 没有合法空数据提交路径。本轮精确 payload 成功，创建了
版本 1；服务端成功响应为 `code=0/msg=成功/data={}/extra.error=""`。

### 2. `metadata.dim.data.table.update` — 已还原，实测成功

```json
{
  "table_id": "<table id>",
  "cname": "<2..40 chars; frontend required>",
  "app_id_list": [26827043],
  "remark": "<string; UI max 100>",
  "name": "<existing immutable English name>"
}
```

`cname/app_id_list` 是前端必填；`name` 从既有表对象原样回传。本轮五字段请求成功，响应同 create 的
空成功 envelope。

### 3. `metadata.dim.data.table.delete` — 已还原，实测成功

```json
{"table_id": "<table id>"}
```

本轮删除唯一 marker 表成功；随后列表和版本集合均为空。

### 4. `metadata.table.new.version.create` — 已还原，未实测

Route: `/event_dim/data_table/create_new_version/override/`。

```json
{
  "table_id": "<table id>",
  "version_id": "<current using_version_id>",
  "column_list": [
    {"name": "<name>", "cname": "<display name>", "data_type": "<enum>", "is_pk": false}
  ],
  "column_val_list": [
    {"<column name>": "<value>"}
  ]
}
```

覆盖模式允许增加或删除非主键列，但上传文件的主键字段名必须与当前表相同。停止条件触发后未发请求，
所以响应 shape、是否自动成为生效版本以及服务端 required 仍未知。

### 5. `metadata.new.version.data.create` — 已还原，未实测

Route: `/event_dim/data_table/create_new_version/append_data/`。body 与 override 完全相同。

前端在发送前要求列名集合、列数和每列类型与当前版本完全一致，并把与当前版本重复的主键行拒绝掉；
这说明 append 是“相同 schema 下追加新主键行”，不是给当前版本原地加行。停止后未取得服务端响应。

### 6. `metadata.table.using.version.state_change` — 已还原，未实测

```json
{"table_id": "<table id>", "version_id": "<selected version id>"}
```

前端确认框逐字说明：切换包含“数据表结构”和“数据表内数据”，**不包括数据表与属性的关联关系**。
停止后未实测切换响应。

### 7. `metadata.app.column.cname.update` — 已还原，未实测

```json
{
  "cname": "<2..40 chars; frontend required>",
  "app_id": "<bound app id>",
  "prop_type": "event|user",
  "prop_id": "<bound event/user property id>",
  "table_id": "<dimension table id>",
  "name": "<dimension column name after the last @>"
}
```

这不是给维度表原始列加中文名；它编辑的是已绑定 App 属性下派生维度列的显示名。因为本轮未绑定，
没有合法父对象，未发请求。

### 8. `metadata.conf.related.prop.update` — 已还原，空列表实测被拒绝

```json
{
  "table_id": "<table id>",
  "prop_list": [
    {
      "app_id": 26827043,
      "type": "event|user",
      "id": 2473840,
      "column_list": [
        {"name": "<non-PK dimension column>", "cname": "<derived display name>"}
      ]
    }
  ]
}
```

前端最多 20 条关联。表主键只能关联相同 `data_type` 的事件/用户属性；两侧都排除日期类和 `LIST`，
用户属性还排除 `prop_type=3`。前端的关联编辑器至少保留一条，提交前拒绝未选 App/属性。

本轮在绑定前发送 `prop_list=[]`，上游明确拒绝为 `prop_list is empty`。因此已证明的服务端约束是
`prop_list` 非空；没有证据支持通过该 route 解除最后一条关联。

### 9. `metadata.column.and.val.delete` — 已还原，未实测；现有命名语义错误

```json
{"table_id": "<table id>", "version_id": "<version id>"}
```

尽管 reservation ID 写成 `column.and.val.delete`，hash-matched 前端从表列表和历史版本页调用它后，
读取响应 `task_id` 并进入下载任务；按钮文案是“导出/下载”。静态控制流没有删除列或值的语义。
下一单若处理此 route，应先纠正能力分类，不能按 delete mutation 实现。停止后未发请求，`task_id`
响应 shape 尚未实证。

## 实际链路与停止点

### 绑定前分析基线

固定请求未换 App、未扩日期窗、未翻页：

```json
{
  "app_id": "26827043",
  "query_item_list": [{
    "event_name": "order_status",
    "target": {"field": "PresetAllCount", "name": "PresetAllCount"},
    "conditions": []
  }],
  "group_by_list": [
    {"type": "default_event", "field": "create_time", "group_by": "total"},
    {"type": "event", "field": "order_id", "group_by": "order_id"}
  ],
  "date_list": [{"start_date": "2026-08-15", "end_date": "2026-08-15"}]
}
```

首请求漏掉必需的 `create_time` 分组，HTTP 200、`code=1004`；第二次按离线 Analysis compiler 补为
`create_time=total` 后，HTTP 200、`code=0`。返回 5,000 个 `order_id` 分组，共 72,402 次事件。
三个拟映射的非空裸 ID 只记录 SHA-256 和计数，不把生产值写入 Git：

| Value SHA-256 | Event count |
| --- | ---: |
| `aa28faa009ff4328b66fce748244cee519ce755112d50f1942568c60e7f18085` | 304 |
| `c36b242f566ba6e3b7a34e40b0667ed862781116240687371c4617ae7041a6d7` | 277 |
| `4084768b50e6b21681a094a18ec92c98530ef9dada72786c50b0c3d0d203329c` | 254 |

这证明目标事件/属性确实有数据，也给自建表提供了合法、固定的主键样本。绑定前直播属性行没有
`dim_table` 字段，所以当时不存在可按业务列查询的维度引用。

### 建表和读回

create 的实际请求含：

- `app_id_list=[26827043]`；
- marker 同时出现在 `cname` 与 `remark`；
- 英文名 `dim_gsdk_d9136038bab6`；
- `order_id/订单道具ID` 主键列和 `seed_label/初始中文列` 普通列；
- 三行值，主键分别为上表三个 SHA-256 对应值。

创建、marker 列表读回、detail、edit 均为 HTTP 200 / `code=0`。detail 实际返回
`using_version_id=1`、两列、三行；这证明 create 同时完成“建表、加列、灌入第一版数据”。

### 停止

真正绑定前的 `prop_list=[]` 清理预检被服务端拒绝。紧随其后的 detail 仍为版本 1、两列、三行，
`related_prop=null`，证明失败请求没有建立绑定。此处按任务要求立即停止：

- 未发送非空 `prop_list`；
- 未发送 override/append/version switch；
- 未发送 `app_column_edit/cname` 或 `dl/column_and_val`；
- 未发送绑定后的分析请求。

所以完整链只走到“建表 + 列 + 第一版数据 + edit”；“新版本 → 切换 → 绑定 → 业务属性分析”均未开始，
不能拿静态控制流冒充实测完成。

## 版本机制：确定项与不确定项

确定项：

- create 实测产生版本 1，并立即成为 `using_version_id=1`；
- append/override 共用相同四字段 body，输入的 `version_id` 来自当前 `using_version_id`；
- append 的前端语义是相同 schema、无重复主键地追加；override 可替换数据并改变非主键列，主键字段名不变；
- switch 的前端语义是同时切换结构和数据，关联关系不随版本切换。

不确定项：

- append/override 成功响应 shape、是否自动切换生效版本、版本号分配方式；
- append 是否物化“旧行 + 新行”的完整版本，或采用服务端增量存储；
- switch 是否使对历史日期重新发起的分析按新维度版本重算。前端提示不足以回答最后一点；本轮没有绑定后
  的历史查询对照，不能猜测“影响”或“不影响”。

## 清理证据

唯一创建对象：

| Kind | ID / name | Marker | Final state |
| --- | --- | --- | --- |
| table | `71ccfb34acd94f6aa3ef69d9ce1976fd` / `dim_gsdk_d9136038bab6` | `GSDK-d9136038bab6` | deleted |
| version | table 上的 version `1` | inherited | `version_id_set=[]` after delete |
| property binding | none | n/a | never created |

删除响应 fingerprint 为
`f17124c260298828086477fcddc77df04c00aa4bd1db3bf6411d01d409d54122`；删除后 marker 列表响应
fingerprint 为 `3ab18a0331145cad8e79e434fc02aae892ee51dec997fa78f95848e6763600b6`，
`data.list=[]`；版本集合响应 fingerprint 为
`f3dcbaa224010e36da2574138a4b289b696e83c717147b7dac6801fad451954f`，`data=[]`。
残留清单为空。

## 生产 HTTP 账本

总计 **13 次实际生产 HTTP**：1 次凭据登录 + 12 次业务请求。全部 attempt 1、`retry=false`；
只有属性列表和表列表带 `page=1`，均未翻页。没有换 App、扩日期窗或自动重放。

| # | Operation / route | HTTP / semantic | Retry / page | Request fingerprint | Response fingerprint / result |
| ---: | --- | --- | --- | --- | --- |
| 1 | `authentication` — POST `/account_center/api/v1/user_login/v2/` | 200 | no / n/a | receipt shape `c676b564…adcf` | login success |
| 2 | raw analysis — POST `/report/api/v3/dataanalysis/query_sql/` | 200 / `code=1004` | no / n/a | `a3920681…ff5` | `c59d4d51…833`; missing `create_time` |
| 3 | raw analysis — same route | 200 / `code=0` | no / n/a | `54802e7c…88f` | `5fe2863e…b062`; 5,000 groups / 72,402 events |
| 4 | event property list — GET `/turbo_engine/api/v2/event/event_property_list/` | 200 / `code=0` | no / page 1 only | `e3eac563…b5b` | `6fe07588…a38`; 234 rows, `order_id` unbound |
| 5 | create — POST `/turbo_engine/api/v2/event_dim/data_table/create/` | 200 / `code=0` | no / n/a | `a7ceeaae…14d` | `f17124c2…122`; success |
| 6 | table list — POST `/turbo_engine/api/v2/event_dim/data_table/list/` | 200 / `code=0` | no / page 1 only | `3108933f…1ba` | `ddb7cb28…93e`; one marker row |
| 7 | table detail — POST `/turbo_engine/api/v2/event_dim/data_table/detail/` | 200 / `code=0` | no / n/a | `4bbe4494…5d1` | `9eff2dab…f28`; 2 columns / 3 rows / version 1 |
| 8 | edit — POST `/turbo_engine/api/v2/event_dim/data_table/edit/` | 200 / `code=0` | no / n/a | `a8e620fe…50d` | `f17124c2…122`; success |
| 9 | relation override empty preflight — POST `/turbo_engine/api/v2/event_dim/data_table/conf_related_prop/override/` | 200 / `code=1004` | no / n/a | `73daf0da…e3d` | `8228c8d0…c7ac`; `prop_list is empty` |
| 10 | table detail — same detail route | 200 / `code=0` | no / n/a | `4bbe4494…5d1` | `f46eba7a…640`; binding still null |
| 11 | delete — POST `/turbo_engine/api/v2/event_dim/data_table/delete/` | 200 / `code=0` | no / n/a | `4bbe4494…5d1` | `f17124c2…122`; success |
| 12 | table list — same list route | 200 / `code=0` | no / page 1 only | `3108933f…1ba` | `3ab18a03…0b6`; zero marker rows |
| 13 | version ID set — GET `/turbo_engine/api/v2/event_dim/data_table/version_id_set/` | 200 / `code=0` | no / n/a | `4bbe4494…5d1` | `f3dcbaa2…54f`; empty list |

另有公开静态资源请求，不计生产业务预算：三份 bundle 各 GET 两次（均 200；第二次用于在格式化工作副本后
恢复原始字节），三个 sourcemap 各 GET 一次并返回 `NoSuchKey`；全部无重试、无凭据、无业务对象。

## 下一单的进入条件

在以下信息齐全前，不值得实现剩余 8 条预留路由：

1. API owner 给出可删除最后一条 `conf_related_prop` 的精确 method/path/body，或给出可验证、可回读的
   事务性回滚方案；不能只说“删表会级联”。
2. 重新获批一次临时绑定后，先实测解绑与事件属性元数据恢复，再做同一请求的绑定前/后对照；后查询必须
   返回业务列的非空分组或筛选结果。
3. 补齐 override/append/switch/cname/download 五条未实测路由的成功响应 shape，以及新版本是否自动生效。
4. 用两个版本对同一历史日期查询，回答生效版本是否回溯改变历史分析结果。
5. 把 `dl/column_and_val` 按真实 export/download 语义重新分类；不能沿用当前 delete 命名。
6. 等 owner-gate 重构落定后再接写治理，避免当前 marker → owner 共享 spine 冲突。

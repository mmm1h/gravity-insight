> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# F41 数据表 schema：绑定投放中 App 后仍无活表

- 日期：2026-08-18
- 任务：F41
- 结论：hash-matched bundle 已坐实 list/detail 请求形状；绑定投放中 App `29034827` 及穷尽合理筛选后，`data_table.list` 仍明确 `total=0`，近期 `operation_log` 的 32 位 `table_id` 对 `detail` 为 `code=1004 / table_id not exist`。三条继续 draft，读产品未建。

## 确凿事实

### Bundle（0 次生产请求）

公开静态 GET 三次，SHA-256 与冻结 `bundle-snapshot.json` 逐字一致：

| Bundle | Bytes | SHA-256 |
| --- | ---: | --- |
| `DataSheet-CgxGx0E4.js` | 48,102 | `d95d7acc08984d4c08e6b23a86132cf1ccf949204022319462156d06297815e2` |
| `DataSheetDetail-CNEBq9Fe.js` | 2,406 | `f29cca6397a4730a995fbff9c20eb9618c46fd78c925ab211576c8c32043446c` |
| `dataSheet-data-D_dWJH0x.js` | 14,128 | `4c067e3c775ed18a3fed8a3a5dda45277b76798a2b44cfaf6ae756bc868cf964` |

另核 `index-D9HAN43D.js`（5,890,290 字节，`aa67659c360861d73309b2f9ca93ac15d95d6b39a092912a32cb72b9f1662d6b`）中的 `AppSelect`。

**list 前端自然请求**（`DataSheet` 装载函数 `Q`）：

```js
O({body:{page:oe.value,page_size:se.value,app_id_list:K.value.app_id,name_like:K.value.name}})
```

- 初始状态：`K={name:"",app_id:[]}`，`page=1`，`page_size=10`。
- 筛选器配置：`name` 为输入框，`app_id` 为 `AppSelect`（`radio:!1`，多选）。
- `AppSelect` 的 `modelValue` 类型是 `Number|Array|String|null`；多选时 `s.value.push(e)`，`e` 来自 `child.id`，与 `app.list` 的整数 `id` 同一字段。
- 分页只消费 `page_info.total`，`page-sizes=[10,20,50,100]`。bundle 内 **0 次** `total_page`。
- 列表列消费：`name`、`related_prop`、`app_id_list`、`create_type`、`update_user_name`、`modify_time`、`create_user_name`、`create_time`。点表名走 `ue(e.id)`，即 **list item 的 `id`**，不是 `table_id`。

**detail 前端自然请求**：

- `DataSheetDetail`：`P({body:{table_id:N.query.id}})`，路由 query `id` 就是上一行的 `e.id`。
- 同页更新/关联对话框也发 `{table_id:e.id}` 或 `{table_id:p.value.id}`。

**version.list / version_id_set**（`dataSheet-data` 的 History）：

- `version.list` body 是 `{filters:[...]}`，无筛选时仍会推入 `{field:table_id, operator:equals, values:[w.query.id]}`。
- 账号级 `metadata.version.list` 合同只发 `{page,page_size,filters:[]}`，**不是**数据表页的自然请求。
- `version_id_set` 是 GET，query `table_id=w.query.id`。

2026-08-16 create 实测 `app_id_list` 元素是整数（`[26827043]`），与 `AppSelect` emit 的 `id` 一致。

### 生产请求（11 次业务 HTTP + 1 次登录刷新）

全部 HTTP 200，无重试、无翻页、不建表。

#### `metadata.data_table.list`

路径 `POST /turbo_engine/api/v2/event_dim/data_table/list/`。七种形状全部：

`code=0` / `msg=成功` / `data.list=[]` / `data.page_info={page, page_size, total=0}`，**没有** `total_page`。

| # | 形状 | `total` |
| ---: | --- | ---: |
| 1 | `app_id_list=[29034827]` 整数，`name_like=""`，`page=1`，`page_size=10` | 0 |
| 2 | `app_id_list=["29034827"]` 字符串，其余同 1 | 0 |
| 3 | `app_id_list` = 当前账号 7 个 App 整数，其余同 1 | 0 |
| 4 | 省略 `name_like`，`app_id_list=[29034827]` | 0 |
| 5 | 省略 `app_id_list`，`name_like=""` | 0 |
| 6 | `app_id_list=[29034827]`，`name_like="dim_"` | 0 |
| 7 | 只发 `page=1` / `page_size=10`（两个筛选都省略） | 0 |

第 7 次收据证明实际 body 只有 `page`、`page_size`。

因此：**空 `app_id_list` ≠ 漏查投放中 App**。绑 `29034827`、绑全部 7 个、省略筛选、按 `dim_` 前缀搜，结果相同。

#### `metadata.version.list`（1 次，已是 stable）

`page=1` / `page_size=1`：HTTP 200 / `code=0`，`list_len=1`。首项键：`cid, create_time, create_user_id, create_user_name, id, info, name_en_cn_dict, ordered_field_name_list, table_id, version_id`。`table_id` 为 32 位字符串。`page_info` 含 `total_page` / `total_number`（与 list 不同）。

本轮 **没有** 把这个 `table_id` 再发给 detail（2026-08-17 已对同类 id 得过 `1004`）。

#### `metadata.operation_log.list`（2 次，已是 stable）

`page=1` / `page_size=20`：HTTP 200 / `code=0`，`list_len=20`，`page_info.total_number=1093`。本页 16 个不重复 `table_id`（均为 32 位字符串），动作只有 `edit` / `publish` / `download`，本页无 `delete`。

#### `metadata.data_table.detail`（1 次）

父项来源：上面 operation_log 本页第一条非 `delete` 行的内存 `table_id`（32 位字符串，动作 `edit`）。**不是** 2026-08-17 用过的 version.list 首行 id。

```
POST /turbo_engine/api/v2/event_dim/data_table/detail/
body: {table_id: <32-char string from operation_log>}
```

结果：HTTP 200 / `code=1004` / `msg=参数错误` / `extra.error="table_id not exist"` / `data={}`。

这坐实：`code=1004` 在本 route 上是**参数拒绝（id 不存在）**，不是权限码。日志/版本目录里的 `table_id` 不能当活表父绑定。

## 推测（不得当合同）

- 当前租户**很可能没有活着的数据表**。数据表是手建维度表，不会因 App 在投自动出现。`29034827` 有投放事件，不蕴含有 `data_table`。
- `operation_log` / `version.list` 保留已删或不可读表的历史 id；`detail` 的 `table_id not exist` 与 `list.total=0` 一致。
- 前端 list 列名暗示非空 item 至少有 `id`（detail 父键）、`name`、`cname`、`app_id_list`、`related_prop`、`using_version_id`、`create_type`、人员与时间字段。这些**尚未被当前租户的成功响应证明**。

## 未做 / 停止原因

- 不自建 marker 表。
- 不把同一个历史 `table_id` 再发一次 detail。
- 不晋升三条 draft，不建 Core/CLI/SDK/Plan/Agent 读产品。
- 不改评测题集。冻结 J44 仍期待 `CURRENT_TABLE_SCHEMA_PARENT_MISSING`，与本轮结果一致。

下一步最小证据不变：取得一份**当前** `data_table.list` 非空 item，再仅在内存中打 1 次成功 detail。本账号在已穷尽的请求形状上给不出这个 item。

归档入口见 [roadmap.d](README.md)。

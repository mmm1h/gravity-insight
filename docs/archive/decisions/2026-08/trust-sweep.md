> 归档材料：保留历史决策与取证，不代表当前接口或状态；当前入口见 docs/index.md。

# 上线前信任核查

- 日期：2026-08-18
- 任务：#203
- 结论：超限变现导出在生产上仍未报 `truncated`，根因是 pin 用了 26 列产品字段当分母；标题库 `last_3_day_*` 是新的死字段。

## 生产预算

- 读：25 次（上限 45）。优先投放中抖音 App `29034827`。
- 导出 create：2 次（1 变现全日 + 1 用户明细单日）。poll/download 不计入。
- 写：0。未碰实时事件路由。

## 确凿事实

### 1. 变现超限导出：文件触顶，信封仍是 `partial`

请求：`export.analysis.monetization_detail.start`，App `29034827`，`create_time` 单日 `2026-08-16`，`field_map={AdEventTime,ClientID}`。

| 项 | 值 |
| --- | --- |
| job_id | `2519119964c24199887daf590b4468c0` |
| `completion_status` | `partial`（不是 `truncated`，也不是 `complete`） |
| `file.rows` | 1,000,000 |
| `completeness.known_total_items` | 19,196 |
| `known_total_freshness` | `create_time_preflight` |
| `truncated` / `complete` | false / false |
| 文件大小 | 22,081,028 bytes |

同日、同 App 的 list 预检（另发，不计入 create）：

| list `fields` | `page_size` | `page.total_items` |
| --- | ---: | ---: |
| `CreateTime,AdEventTime,ClientID` | 1 | 13,497,904 |
| `AdEventTime,ClientID`（与导出相同） | 1 | 13,497,911 |
| 26 个 `SAFE_ROW_FIELDS`（当时 pin 用的形状） | 100 | 19,196 |

因此：create 时钉住的是 26 列产品读取的总量，不是导出两列的总量。文件触顶 100 万行，但 19,196 < 1,000,000，分类器不能报 `truncated`，只能报 `partial`。`create_time_preflight` 标注还在，丢钉修复本身成立；错的是分母的列集。

`report.get.query` `reporting_ad_cnt` 同日约 17,173，和 26 列 list 的 19,196 同一量级，和两列 list 的 1,350 万不是一回事。换日期不能做出“两列且小于百万”的变现切片：`2026-08-01` 两列 list 仍是 17,346,014，`2026-08-18` 仍是 7,639,664。

### 2. 小切片对照：用户明细 `complete`

请求：`export.analysis.user_detail.start`，同 App，单日 `2026-08-16`，`field_map={ClientID,CreateTime}`。

| 项 | 值 |
| --- | --- |
| job_id | `f9e0e42eab2b464bae01d11586a6d735` |
| `completion_status` | `complete` |
| `file.rows` | 4,556 |
| 同条件 list `page.total_items` | 4,556 |
| `completeness` | 空（该族不走 monetization pin） |

`file_rows == list.total_items`，未触顶。

### 3. 字段筛查

离线从 236 个 operation 合同挑出名字含
`count/total/num/cnt/rate/ratio/is_/has_/status/enabled/flag/valid/active/available/success/fail`
的字段，覆盖 130 条 route。生产取样优先投放中 App，只对常量且调用方会当判断依据的字段做交叉验证。

试过的形状与结论：

| 字段 | 取样 | 交叉验证 | 判定 |
| --- | --- | --- | --- |
| `analysis.event.list.yesterday_count` | 117/117 = 0 | 同 App 同日归因 `AppRealRegisterCnt` 有正行 | 已知死字段，维持原标注 |
| `analysis.event.list.is_favourite` | 117/117 = false | 无独立“是否收藏”route；请求默认 `need_favourite=true` | 信号，不当 bug。可能是本账号未收藏 |
| `analysis.event.list.visible` | 117/117 = true | 请求固定 `visible=true` 过滤 | 预期常量 |
| `app.list.is_enabled` | 7/7 = true | 目录事实，无反证 | 不当 bug |
| `app.list.status` | 7/7 缺字段 | 投影未给出 | 不当 bug |
| `analysis.segment.list.user_cnt` / `latest_user_cnt` | 9 行各不相同且两列两两相等 | 无需交叉 | 可信 |
| `promotion.bytedance.account.list.put_status` | 第 1 页 50 行 + 第 11 页 2 行全为 1 | 无独立投放状态 route 给出相反答案 | 信号，不当 bug。可能本租户账户都是投放中 |
| `promotion.bytedance.account.list.media_status` | 52 行全为空串 | 空串不是计数谎言 | 不当 bug |
| `promotion.bytedance.account.list.account_id` | 52 行同一值；`advertiser_id` 各不相同 | `account_id` 是代理账户，不是广告主 | 预期常量 |
| `material.local.list.status` / `audit_status` / `media_refuse_count` | 两页 40 行恒 1 / 1 / 0 | 信封 `contract_changed`（未登记嵌套容器），不能当交叉证据 | 不标注 |
| `material.bytedance_asset_text_title.list.last_3_day_click_rate` | 投放中 App 44/44 = 0；不绑 App 50/50 = 0 | 同页 `history_click_rate` 有 0.01/0.02；`material.report.query` 同 App 三日窗 `ctr` 有正值（如 1.70%） | **不可信** |
| `material.bytedance_asset_text_title.list.last_3_day_cost` | 同上，44/44 与 50/50 全 0 | 同页 `history_cost` 有正数；`material.report.query.stat_cost` 有正数 | **不可信** |
| 标准投放标题 list 的同名字段 | 44/44 全 0 | 与上一条同一交叉证据 | **不可信** |
| 标题包 list 的 `last_3_day_*` | 2/2 = 0，但 `history_*` 也是 0 | 没有“包级有量、近 3 日为 0”的反证 | 不标注 |

未标注的常量：`is_preset` 有 true/false；`plan_num` 有 0 也有上万；`convert_rate`/`ctr`/`stat_cost` 在素材报表上有变化。

## 推测（不是事实）

- 变现 list 的 `total_items` 随 `fields` 从 1,350 万掉到 1.9 万，可能是上游对含用户/设备/归因嵌套字段走了另一条计数路径。未穷尽每一个中间字段组合。
- 标题 `last_3_day_*` 可能是上游未算近 3 日窗口，或窗口与素材报表三日窗不对齐。本轮没有前端源码证明。
- `put_status` 全 1 更像租户现状，不是死字段。

## 处置

- 不删字段、不改写上游值。
- `export_scope_total` 预检改为使用导出 `field_map` 的键作 list `fields`，`page_size=1`。修后的单测：`test_pin_reads_one_static_page_and_keeps_create_time_total`、`test_pin_rejects_empty_field_map`。
- 两条标题 list 合同增加 `unreliable_item_keys.last_3_day_click_rate` / `last_3_day_cost`，`use_instead` 指向 `material.report.query` 的 `ctr`/`stat_cost` 或同 route 的 `history_*`。
- 读取 envelope 的 warning 文案从“是否有事件数据”改成通用的“不要当决策指标”，以便标题字段也能复用。
- 本轮超限变现文件仍是修前发出的，信封保持 `partial`。create 预算已用尽，修后的 `truncated` 路径只有单测，没有第二次生产 create。

## 没改什么

- 不改评测装置、题集、评分、阈值；不跑 holdout / final。
- 不动 `docs/roadmap.md` 汇总数字。
- 不动 describe 面、分页审计、目录可执行标注（并行 job `#advertised-vs-real`）。
- 导出动线状态仍是部分闭环；冻结宽问法 gap 不变。

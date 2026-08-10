# Merge 项目埋点字典

> 本文档由 `merge项目数据埋点.xlsx` 回读生成，面向 Codex/Claude 等 Agent 检索使用。字段名保留代码原始拼写，包括已有 typo。
>
> 最近验证状态以 `gravity sql status --json` 解析出的 immutable snapshot 及其 `event-coverage` 为准；输出必须保留 snapshot ID 与 hash。文中的 2026-06-01 至 2026-06-12 SQL 标注均为历史核验结果；“已接入”和“当前”描述也只对应生成时的代码快照。

## 可执行查询

```powershell
gravity sql status [--json]
gravity sql verify [--date YYYY-MM-DD] [--publish]
gravity sql query event-coverage --start YYYY-MM-DDTHH:MM:SS --end YYYY-MM-DDTHH:MM:SS [--app-id ID ...]
```

`event-coverage` 只检查字典声明事件在查询窗口是否出现，不验证事件属性，也不代表下文 170 个历史字段校验项已经复核。活动事件并非每天都应出现，因此单日缺失只作信息记录，不单独告警或阻断。返回 `partial` 时必须保留 `warnings` 和 `forbidden_claims`；`stale`、`pending_review` 或 `blocked` 时拒绝查询。只有显式 `verify --publish` 才更新最近验证证据。

## 元信息

| 项目 | 内容 |
| --- | --- |
| 来源 xlsx | `30_专题工作区/专题/线上活动总览/运营/工作簿/merge_event_tracking.xlsx` |
| 当前字典 | `docs/data-contracts/Merge埋点字典.md` |
| 客户端源码 | D:/git-pjt/client_2_to_1/client/assets/Script |
| 配置仓库 | D:/git-pjt/merge_public_cn/excel/csv |
| 工作表 | 数据埋点, 事件表, 用户属性, 预置属性, 接入须知 |
| 字典声明事件数 | 72（主表 71 + 平台预置 `$MPLaunch` 治理补录 1） |
| 主表行数 | 194 |

## 历史 SQL 核验标注

以下结果只描述 2026-06-01 至 2026-06-12 的历史窗口；最近完整窗口状态以滚动聚合证据为准。

- 核验表：`default.event`
- 核验应用：`app_id = 29034827`
- 主核验范围：`2026-06-10 00:00:00` 至 `2026-06-12 23:59:59`
- 结果：71 个整理事件中 61 个命中，10 个未命中；下表为未命中事件。

| 事件名 | 6/10-6/12 状态 | 扩展 6/1-6/12 状态 | 说明 |
| --- | --- | --- | --- |
| Login | 未查到 | 仍未查到 |  |
| $AppStart | 未查到 | 仍未查到 |  |
| AssetList | 未查到 | 仍未查到 |  |
| $AdClick | 未查到 | 仍未查到 | $AdShow 已命中，需核对广告点击/开始播放回调或后台事件名。 |
| $AdPlayStart | 未查到 | 仍未查到 | $AdShow 已命中，需核对广告点击/开始播放回调或后台事件名。 |
| vip_invitation | 未查到 | 仍未查到 |  |
| onegetone | 未查到 | 仍未查到 |  |
| questionnaire_submit | 未查到 | 仍未查到 |  |
| trainmerge_submit | 未查到 | 已查到 | 2026-06-01 至 2026-06-12 查到 49,790 次，集中在 2026-06-05 至 2026-06-08。 |
| trainmerge_reward | 未查到 | 已查到 | 2026-06-01 至 2026-06-12 查到 17,316 次，集中在 2026-06-05 至 2026-06-08。 |
## 字段 SQL 核验缺失

- 核验表：`default.event.properties`
- 核验应用：`app_id = 29034827`
- 核验范围：`2026-06-10 00:00:00` 至 `2026-06-12 23:59:59`
- 结果：170 个字段校验项中 9 个未发现。完整字段覆盖率见[历史字段核验报告](../30_专题工作区/专题/线上活动总览/报告/merge_property_sql_check.md)。

| 模块 | 事件 | 字段 | 事件数 | 说明 |
| --- | --- | --- | --- | --- |
| 广告 | $AdShow | ad_id | 130,517 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 ad_id；事件命中 130,517 次。 |
| Bingo 订单 | bingo_reward | type_id | 3,183 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 type_id；事件命中 3,183 次。 |
| 通行证 | pass_task | pass_task_id | 8,919,757 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 pass_task_id；事件命中 8,919,757 次。 |
| 付费 | pay_cancel | $pay_method | 10,422 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_method；事件命中 10,422 次。 |
| 付费 | pay_cancel | $pay_reason | 10,422 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_reason；事件命中 10,422 次。 |
| 付费 | pay_click | $pay_method | 19,971 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_method；事件命中 19,971 次。 |
| 付费 | pay_click | $pay_reason | 19,971 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_reason；事件命中 19,971 次。 |
| 场景导航 | routine_scence | build_id | 2,879,316 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 build_id；事件命中 2,879,316 次。 |
| 活动售卖 | tiered_gift | tiered_gift_tier | 4,767 | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 tiered_gift_tier；事件命中 4,767 次。 |
## 事件索引

| 模块 | 埋点名称 | 埋点含义 | 埋点方式 | 事件触发 |
| --- | --- | --- | --- | --- |
| 基础接入 | Login | 登录成功 | 游戏端-已接入 | GameLoadManager 登录流程完成后<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 基础接入 | $AppStart | 应用启动 | 游戏端-已接入 | 启动流程进入后上报<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 基础接入 | $MPLaunch | 小程序启动或回前台 | 平台侧预置 | 当前专题分析只将窗口内去重用户作为活跃代理；不等于活动曝光、活动进入或有效触达。 |
| 基础接入 | AssetList | 周期资产快照 | 游戏端-已接入 | StorageLogic.UpPlayerData 达到上传周期；动态字段 `asstes_2` 为当前体力，`asstes_9` 为累计体力消耗<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 玩家成长 | userlevel | 玩家等级变化 | 游戏端-已接入 | 玩家等级更新时 |
| 玩家成长 | power_multipe | 体力倍率切换 | 游戏端-已接入 | 玩家手动或自动切换体力倍数；不包含实际消耗数值 |
| 经济系统 | paid_assets | 付费资产变化 | 游戏端-已接入 | 付费资产获得或消耗时 |
| 经济系统 | piece_change | 合成棋子获得 | 游戏端-已接入 | 目标棋子通过奖励、活动或玩法进入棋盘/背包 |
| 合成棋盘 | generator_get | 发射器类物品合成产出 | 游戏端-已接入 | 棋盘合成后新物品类型为发射器类 |
| 订单系统 | order_status | 订单派发或完成 | 游戏端-已接入 | 订单生成、派发或完成时 |
| 仓库/收集 | island_store | 仓库/建筑道具操作 | 游戏端-已接入 | 建筑材料领取、仓库取出或订单提交 |
| 仓库/收集 | piece_achievement | 图鉴棋子收集 | 游戏端-已接入 | 图鉴棋子点亮或领取时 |
| 等级奖励 | lv_rewards | 等级宝箱领取 | 游戏端-已接入 | 玩家领取等级奖励宝箱 |
| 广告 | $AdClick | 激励视频广告点击/请求展示 | 平台侧-已接入 | PlayVideoAD 调用广告展示前<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 广告 | $AdPlayStart | 激励视频开始播放 | 平台侧-已接入 | AnyThink 播放开始回调<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 广告 | $AdShow | 激励视频有效展示/奖励 | 平台侧-已接入 | 播放结束或 onReward 回调 |
| 付费 | pay_click | 支付点击 | 游戏端-已接入 | 玩家点击商品支付入口 |
| 付费 | pay_cancel | 支付取消或失败 | 游戏端-已接入 | IAP/官方支付取消或验单失败 |
| 付费 | $PayEvent | 支付成功 | 游戏端-已接入 | 订单进入 `PAID` 成功分支后；取消或失败另报 `pay_cancel` |
| 场景导航 | routine_scence | 常规场景入口点击 | 游戏端-已接入 | 主页、棋盘、商店、仓库等入口点击 |
| 场景导航 | event_scence | 活动入口曝光/进入 | 游戏端-已接入 | 活动状态变更或入口进入时 |
| 剧情 | stage | 剧情对话推进 | 游戏端-已接入 | 剧情窗口展示/推进对话时 |
| 剧情 | skip_stoty | 跳过剧情 | 游戏端-已接入 | 玩家跳过单段或多段剧情 |
| 卡册 | card_collect | 卡牌收集 | 游戏端-已接入 | 卡牌进入卡册或被收集 |
| 卡册 | card_pack | 卡包开启 | 游戏端-已接入 | 玩家开启卡包 |
| 卡册 | card_box_get | 卡盒领取 | 游戏端-已接入 | 玩家领取卡盒奖励 |
| 七日任务 | seven_tasks | 七日任务行为 | 游戏端-已接入 | 七日任务完成或领取 |
| 七日任务 | seven_tasks_box | 七日任务宝箱领取 | 游戏端-已接入 | 领取七日任务进度宝箱 |
| 迷你棋盘 | mini_chenss_achievement | 迷你棋盘图鉴/阶段奖励 | 游戏端-已接入 | 领取单图鉴或阶段奖励 |
| 迷你棋盘 | mini_chessboard_box | 迷你棋盘宝箱领取 | 游戏端-已接入 | 领取迷你棋盘宝箱 |
| 街机活动 | arcade_game | 街机任务领取 | 游戏端-已接入 | 街机金币任务领取成功 |
| 街机活动 | arcade_game_piont | 街机积分变化 | 游戏端-已接入 | 街机活动币增加 |
| 街机活动 | arcade_game_reward | 街机奖励领取 | 游戏端-已接入 | 领取街机里程碑/等级奖励 |
| 水上挑战 | water_challenge | 水上挑战通关 | 游戏端-已接入 | 水上挑战完成一轮 |
| 水上挑战 | water_challenge_reward | 水上挑战奖励领取 | 游戏端-已接入 | 领取水上挑战结算奖励 |
| 皇冠活动 | royal_crown | 皇冠积分变化 | 游戏端-已接入 | 皇冠活动积分增加 |
| 皇冠活动 | royal_crown_reward | 皇冠奖励领取 | 游戏端-已接入 | 领取皇冠等级/排名奖励 |
| 竞速活动 | pkrace | PK 竞速积分变化 | 游戏端-已接入 | 竞速活动积分增加 |
| 竞速活动 | pkrace_reward | PK 竞速奖励领取 | 游戏端-已接入 | 领取竞速排名奖励 |
| 狗粮活动 | dogfood | 狗粮积分变化 | 游戏端-已接入 | 狗粮活动积分增加 |
| 狗粮活动 | dogfood_click | 狗粮界面点击 | 游戏端-已接入 | 狗粮开始/结束/关闭弹窗点击 |
| 狗粮活动 | dogfood_reward | 狗粮奖励领取 | 游戏端-已接入 | 领取狗粮轮次/宝箱奖励 |
| 神灯活动 | magiclamp | 神灯抽取/消耗 | 游戏端-已接入 | 神灯抽取或消耗活动币 |
| 神灯活动 | magiclamp_reward | 神灯奖励领取 | 游戏端-已接入 | 神灯奖励发放 |
| 活动入口 | vip_invitation | VIP 邀请入口点击 | 游戏端-已接入 | VIP 客服活动按钮点击<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 甜甜圈竞速 | donutrace | 甜甜圈竞速积分变化 | 游戏端-已接入 | 甜甜圈竞速积分增加 |
| 甜甜圈竞速 | donutrace_click | 甜甜圈竞速界面点击 | 游戏端-已接入 | 甜甜圈竞速界面关闭/开始点击 |
| 甜甜圈竞速 | donutrace_reward | 甜甜圈竞速奖励领取 | 游戏端-已接入 | 领取甜甜圈竞速奖励 |
| 岛屿活动 | island_scene | 岛屿活动币变化 | 游戏端-已接入 | 岛屿活动币获得或消耗 |
| 岛屿活动 | island_plot | 岛屿剧情购买 | 游戏端-已接入 | 玩家购买岛屿剧情节点 |
| 形象打造 | island_avatar | 头像/头像框保存 | 游戏端-已接入 | 玩家保存头像或头像框 |
| 勋章活动 | medal_campaign | 勋章任务/活动领取 | 游戏端-已接入 | 勋章活动内领取指定勋章 |
| 勋章活动 | medal_bigbag | 勋章大礼包领取 | 游戏端-已接入 | 领取勋章大礼包 |
| 惊喜扭蛋 | surprise_gachapon | 惊喜扭蛋奖励 | 游戏端-已接入 | 惊喜宝箱/扭蛋奖励发放 |
| 神秘惊喜 | smjx | 神秘惊喜礼包领取 | 游戏端-已接入 | 神秘惊喜礼包或小礼包领取 |
| 礼包活动 | energytrain | 能量列车积分变化 | 游戏端-已接入 | 能量列车活动币增加；不是体力消耗，不能按字面 energy 归到体力资源 |
| 礼包活动 | energytrain_reward | 能量列车奖励领取 | 游戏端-已接入 | 领取能量列车奖励 |
| 礼包活动 | onegetone | 买一赠一礼包行为 | 游戏端-已接入 | 买一赠一礼包触发<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 活动售卖 | spin_buy | 旋转购买 | 游戏端-已接入 | 旋转购买活动档位购买 |
| 活动售卖 | tiered_gift | 阶梯礼包领取/购买 | 游戏端-已接入 | 活动阶梯礼包发放 |
| 小飞机 | small_plane | 小飞机格子点击 | 游戏端-已接入 | 小飞机活动格子/奖励点击 |
| 通行证 | pass_task | 通行证任务完成 | 游戏端-已接入 | 通行证任务达成 |
| 通行证 | pass_reward | 通行证奖励领取 | 游戏端-已接入 | 领取普通或付费通行证奖励 |
| 评级冲刺 | soaring_ratings | 评级冲刺积分变化 | 游戏端-已接入 | 评级冲刺活动币增加 |
| 评级冲刺 | soaring_ratings_lv | 评级冲刺等级奖励 | 游戏端-已接入 | 开启或领取评级奖励 |
| 列车订单 | trainmerge_submit | 列车订单提交 | 游戏端-已接入 | 玩家提交列车订单所需棋子<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 查到 49,790 次，时间集中在 2026-06-05 至 2026-06-08。 |
| 列车订单 | trainmerge_reward | 列车订单奖励领取 | 游戏端-已接入 | 列车订单限时、完成、进度奖励发放<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 查到 17,316 次，时间集中在 2026-06-05 至 2026-06-08。 |
| Bingo 订单 | bingo_submit | Bingo 订单提交 | 游戏端-已接入 | 玩家提交 Bingo 订单所需棋子 |
| Bingo 订单 | bingo_reward | Bingo 奖励领取 | 游戏端-已接入 | Bingo 连线或完成奖励发放 |
| 问卷 | questionnaire_submit | 问卷提交 | 游戏端-已接入 | 玩家提交问卷答案<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 |
| 小太阳 | little_sun | 小太阳累计进度 | 游戏端-已接入 | 小太阳活动订单分数增加 |
| 小太阳 | little_sun_box | 小太阳宝箱领取 | 游戏端-已接入 | 小太阳宝箱奖励触发 |

## 工作表：数据埋点

| 项目名称 | 模块 | 埋点名称 | 埋点含义 | 列E | 事件属性 | 事件属性含义 | 属性类型 | 备注 | 事件触发 | 埋点方式 | 关联用户属性 | 埋点版本 | 上线日期 | 完成日期 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Merge | 基础接入 | Login | 登录成功 |  |  |  |  | 无显式事件属性<br>源: Work/GameLoadManager.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | GameLoadManager 登录流程完成后 | 游戏端-已接入 | total_login,last_login_time |  |  |  |
| Merge | 基础接入 | $AppStart | 应用启动 |  |  |  |  | 无显式事件属性<br>源: Work/GameLoadManager.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | 启动流程进入后上报 | 游戏端-已接入 |  |  |  |  |
| Merge | 基础接入 | AssetList | 周期资产快照 |  | level | 玩家等级 | int | 来自 PlayerDataManager.Level<br>源: Work/Common/Logic/StorageLogic.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | StorageLogic.UpPlayerData 达到上传周期 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | asstes_{assetId} | 资产数量 | int | 动态字段；代码当前拼写为 asstes_ + 资产 ID。`asstes_2`=当前体力，`asstes_9`=累计体力消耗。 |  |  |  |  |  |  |
| Merge | 玩家成长 | userlevel | 玩家等级变化 |  | lv_id | 当前等级 | string | 源: Work/Player/Data/PlayerDataManager.ts | 玩家等级更新时 | 游戏端-已接入 | current_level_line |  |  |  |
| Merge | 玩家成长 | power_multipe | 体力倍率切换 |  | power_multipe_type | 当前倍数 | string | 源: Work/Player/Data/PlayerDataManager.ts；只表示切倍行为，不含实际体力消耗量 | 玩家手动或自动切换体力倍数 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | power_multipe_act | 切换动作 | string | 1=手动，2=自动 |  |  |  |  |  |  |
| Merge | 经济系统 | paid_assets | 付费资产变化 |  | paid_assets_type | 资产类型 | string | 源: Work/Player/Data/PlayerDataManager.ts | 付费资产获得或消耗时 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | paid_assets_action | 变化动作 | string | paid_assets_get / paid_assets_use |  |  |  |  |  |  |
|  |  |  |  |  | paid_assets_route | 来源或去向 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | paid_assets_amount | 变化数量 | int |  |  |  |  |  |  |  |
|  |  |  |  |  | paid_assets_before_amount | 变化前数量 | int |  |  |  |  |  |  |  |
|  |  |  |  |  | paid_assets_current_amount | 变化后数量 | int |  |  |  |  |  |  |  |
| Merge | 经济系统 | piece_change | 合成棋子获得 |  | piece_route | 获得来源 | string | 源: Work/Player/Data/PlayerDataManager.ts | 目标棋子通过奖励、活动或玩法进入棋盘/背包 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | piece_action | 变化动作 | string | 当前代码为 piece_get |  |  |  |  |  |  |
|  |  |  |  |  | piece_id | 棋子 ID | array<string> |  |  |  |  |  |  |  |
|  |  |  |  |  | piece_amount | 数量 | int |  |  |  |  |  |  |  |
|  |  |  |  |  | piece_type | 棋子类型 | string |  |  |  |  |  |  |  |
| Merge | 合成棋盘 | generator_get | 发射器类物品合成产出 |  | generator_id | 发射器 ID | string | 源: Work/Game/ComGame/Data/RoomDataManager.ts | 棋盘合成后新物品类型为发射器类 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | generator_type | 发射器类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | generator_soure | 产出来源 | string | 代码字段当前拼写为 generator_soure |  |  |  |  |  |  |
| Merge | 订单系统 | order_status | 订单派发或完成 |  | order_status | 订单状态 | string | 1=完成，2=派发<br>源: Work/Game/ComGame/Data/RoomOrderManager.ts | 订单生成、派发或完成时 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | order_type | 订单类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | order_id | 订单目标列表 | string | 目标 ID 逗号拼接 |  |  |  |  |  |  |
|  |  |  |  |  | lv_id | 玩家等级 | string |  |  |  |  |  |  |  |
| Merge | 仓库/收集 | island_store | 仓库/建筑道具操作 |  | island_store_type | 操作类型 | string | 1=获得/取出，2=仓库操作，3=订单完成消耗<br>源: Work/Game/ComGame, Work/Player/Data | 建筑材料领取、仓库取出或订单提交 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | piece_id | 道具 ID | array<string> |  |  |  |  |  |  |  |
| Merge | 仓库/收集 | piece_achievement | 图鉴棋子收集 |  | piece_id | 棋子 ID | array<string> | 源: Work/Game/ComGame/Item/PictureType/PictureItemIcon.ts | 图鉴棋子点亮或领取时 | 游戏端-已接入 |  |  |  |  |
| Merge | 等级奖励 | lv_rewards | 等级宝箱领取 |  | lv_box | 宝箱 ID | string | 源: Work/Game/LevelReward/Data/LevelRewardManager.ts | 玩家领取等级奖励宝箱 | 游戏端-已接入 |  |  |  |  |
| Merge | 广告 | $AdClick | 激励视频广告点击/请求展示 |  | ad_id | 广告位 ID | string | 源: Work/Platform/AndroidPlatform.ts; IOSPlatform.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | PlayVideoAD 调用广告展示前 | 平台侧-已接入 |  |  |  |  |
|  |  |  |  |  | $ad_type | 广告类型 | string | Android=reward；iOS=reward_video |  |  |  |  |  |  |
| Merge | 广告 | $AdPlayStart | 激励视频开始播放 |  | ad_id | 广告位 ID | string | 源: Work/Platform/AndroidPlatform.ts; IOSPlatform.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | AnyThink 播放开始回调 | 平台侧-已接入 |  |  |  |  |
|  |  |  |  |  | $ad_type | 广告类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $adn_type | 广告渠道 | string | 来自 network_firm_id |  |  |  |  |  |  |
|  |  |  |  |  | $ecpm | 广告 eCPM | number | 来自 adsource_price |  |  |  |  |  |  |
| Merge | 广告 | $AdShow | 激励视频有效展示/奖励 |  | ad_id | 广告位 ID | string | 源: Work/Platform/AndroidPlatform.ts; IOSPlatform.ts<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 ad_id；事件命中 130,517 次。 | 播放结束或 onReward 回调 | 平台侧-已接入 |  |  |  |  |
|  |  |  |  |  | $ad_type | 广告类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $adn_type | 广告渠道 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $ecpm | 广告 eCPM | number |  |  |  |  |  |  |  |
| Merge | 付费 | pay_click | 支付点击 |  | $pay_method | 支付方式 | string | 源: Work/Platform/Pay/PayLogic.ts<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_method；事件命中 19,971 次。 | 玩家点击商品支付入口 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | $pay_reason | 商品/支付原因 | string | productId<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_reason；事件命中 19,971 次。 |  |  |  |  |  |  |
|  |  |  |  |  | prod_inlet | 商品入口 | string | PayLogic.GetPaySource(productId) |  |  |  |  |  |  |
|  |  |  |  |  | lv_id | 玩家等级 | string |  |  |  |  |  |  |  |
| Merge | 付费 | pay_cancel | 支付取消或失败 |  | $pay_method | 支付方式 | string | 源: Work/Platform/Pay/PayLogic.ts; IOSIAPTools.ts; OfficalPayTools.ts<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_method；事件命中 10,422 次。 | IAP/官方支付取消或验单失败 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | $pay_reason | 商品/支付原因 | string | 字段SQL核验：2026-06-10 至 2026-06-12，properties 字符串中未发现 $pay_reason；事件命中 10,422 次。 |  |  |  |  |  |  |
|  |  |  |  |  | pay_factors | 取消/失败原因 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | prod_inlet | 商品入口 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | lv_id | 玩家等级 | string |  |  |  |  |  |  |  |
| Merge | 付费 | $PayEvent | 支付成功 |  | prod_inlet | 商品入口 | string | 源: Work/Platform/Pay/PayLogic.ts | 订单进入 `PAID` 成功分支后；取消或失败另报 `pay_cancel` | 游戏端-已接入 | first_pay_time,first_pay_method,first_pay_reason,last_pay_time |  |  |  |
|  |  |  |  |  | lv_id | 玩家等级 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $order_id | 服务端订单 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $pay_amount | 支付金额 | number | 代码为 price * 100 |  |  |  |  |  |  |
|  |  |  |  |  | $pay_method | 支付方式 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $pay_reason | 商品/支付原因 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | $pay_type | 币种 | string | 当前为 CNY |  |  |  |  |  |  |
| Merge | 场景导航 | routine_scence | 常规场景入口点击 |  | scence_type | 场景类型 | string | 代码字段当前拼写为 scence_type<br>源: Work/Game/ComGame, Work/Store, Work/SunflowerModel | 主页、棋盘、商店、仓库等入口点击 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | scene_id | 场景/入口 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | build_id | 建筑 ID | string | 地图建筑入口时传入<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 build_id；事件命中 2,879,316 次。 |  |  |  |  |  |  |
| Merge | 场景导航 | event_scence | 活动入口曝光/进入 |  | scence_type | 场景类型 | string | 1/2 由 ActivityModelBase 传入<br>源: Work/Activity/ActivityModelBase.ts | 活动状态变更或入口进入时 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 剧情 | stage | 剧情对话推进 |  | buildi_id | 建筑 ID | string | 代码字段当前拼写为 buildi_id<br>源: Work/Plot; Work/EventSystem | 剧情窗口展示/推进对话时 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | stage_id | 剧情阶段 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | stage_dialogue | 对话段 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | stage_chat | 对话序号 | string |  |  |  |  |  |  |  |
| Merge | 剧情 | skip_stoty | 跳过剧情 |  | stage_dialogue | 对话段 ID | string | 代码事件名当前拼写为 skip_stoty<br>源: Work/Plot/Window | 玩家跳过单段或多段剧情 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | stage_chat | 对话序号 | string |  |  |  |  |  |  |  |
| Merge | 卡册 | card_collect | 卡牌收集 |  | card_collect_type | 收集类型 | string | 源: Work/Game/Album/Data/AlbumDataManager.ts | 卡牌进入卡册或被收集 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | card_bag_star | 卡包星级 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | card_collect_route | 收集来源 | string |  |  |  |  |  |  |  |
| Merge | 卡册 | card_pack | 卡包开启 |  | card_star | 卡牌星级 | string | 源: Work/Game/Album/Item/AlbumBookItem.ts | 玩家开启卡包 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | card_lv | 活动轮次/等级 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | card_get_flase | 是否新卡 | string | 代码字段当前拼写为 card_get_flase |  |  |  |  |  |  |
|  |  |  |  |  | card_type | 卡牌类型/ID | string |  |  |  |  |  |  |  |
| Merge | 卡册 | card_box_get | 卡盒领取 |  | card_lv | 卡盒等级/轮次 | string | 源: Work/Game/Album/Window/AlbumActivityWindow.ts | 玩家领取卡盒奖励 | 游戏端-已接入 |  |  |  |  |
| Merge | 七日任务 | seven_tasks | 七日任务行为 |  | seven_tasks_type | 任务行为类型 | string | 1/2 由代码传入<br>源: Work/Game/SevenDayTask/Data/SevenDayDataManager.ts | 七日任务完成或领取 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | seven_tasks_id | 任务 ID | string |  |  |  |  |  |  |  |
| Merge | 七日任务 | seven_tasks_box | 七日任务宝箱领取 |  | seven_tasks_box | 宝箱序号 | string | 源: Work/Game/SevenDayTask/Data/SevenDayDataManager.ts | 领取七日任务进度宝箱 | 游戏端-已接入 |  |  |  |  |
| Merge | 迷你棋盘 | mini_chenss_achievement | 迷你棋盘图鉴/阶段奖励 |  | piece_id | 图鉴/棋子 ID | array<string> | 源: Work/Activity/ActivityCommon/Item/RoomCollectBookItem.ts | 领取单图鉴或阶段奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | chenss_ahievement_type | 阶段奖励 ID | string | 代码字段当前拼写为 chenss_ahievement_type |  |  |  |  |  |  |
| Merge | 迷你棋盘 | mini_chessboard_box | 迷你棋盘宝箱领取 |  | chessbox_tpe | 宝箱等级 | string | 代码字段当前拼写为 chessbox_tpe<br>源: Work/Game/ComGame/Data/RoomActivity/RoomCollectOrderManager.ts | 领取迷你棋盘宝箱 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 街机活动 | arcade_game | 街机任务领取 |  | activiti_id | 活动 ID | string | 源: Work/ArcadeGame/Window/ArcadeGameGoldOKWindow.ts | 街机金币任务领取成功 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | arcade_game1_task | 任务序号 | string |  |  |  |  |  |  |  |
| Merge | 街机活动 | arcade_game_piont | 街机积分变化 |  | activiti_id | 活动 ID | string | 代码事件名当前拼写为 arcade_game_piont<br>源: Work/Activity/ArcadeGame/ArcadeGameModel.ts | 街机活动币增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | arcade_game1_point_get | 本次获得积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | arcade_game1_point | 当前积分 | number |  |  |  |  |  |  |  |
| Merge | 街机活动 | arcade_game_reward | 街机奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/ArcadeGame/Window/ArcadeGameWindow.ts | 领取街机里程碑/等级奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | arcade_game1_type | 奖励等级 | string |  |  |  |  |  |  |  |
| Merge | 水上挑战 | water_challenge | 水上挑战通关 |  | activiti_id | 活动 ID | string | 源: Work/Activity/WaterChallenge/WaterChallengeModel.ts | 水上挑战完成一轮 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | water_challenge_ok | 通关标识 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | water_challenge_lc | 当前关卡/轮次 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | water_round | 挑战次数 | string |  |  |  |  |  |  |  |
| Merge | 水上挑战 | water_challenge_reward | 水上挑战奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/WaterChallenge/Window/WaterChallengeEndWindow.ts | 领取水上挑战结算奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | water_challenge | 活动标识 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | water_round | 挑战次数 | string |  |  |  |  |  |  |  |
| Merge | 皇冠活动 | royal_crown | 皇冠积分变化 |  | activiti_id | 活动 ID | string | 源: Work/Activity/CrownActivity/CrownActivityModel.ts | 皇冠活动积分增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | royal_crown_point_get | 当前累计积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | royal_crown_point | 本次获得积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | royal_crown_jfpm | 当前排名 | string |  |  |  |  |  |  |  |
| Merge | 皇冠活动 | royal_crown_reward | 皇冠奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/CrownActivity; Work/CrownActivity/Window | 领取皇冠等级/排名奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | royal_crown_type | 奖励等级 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | royal_crown_lv | 当前排名 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | royal_crown_get | 领取标识 | string |  |  |  |  |  |  |  |
| Merge | 竞速活动 | pkrace | PK 竞速积分变化 |  | activiti_id | 活动 ID | string | 源: Work/Activity/PkRace/PkRaceActivityModel.ts | 竞速活动积分增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | pkrace_point_get | 本次获得积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | pkrace_point | 当前积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | pkrace_lc | 轮次/流程 | string |  |  |  |  |  |  |  |
| Merge | 竞速活动 | pkrace_reward | PK 竞速奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/BeachMotorcycle/Window/BeachMotorcycleRewardWindow.ts | 领取竞速排名奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | pkrace_type | 排名/奖励类型 | string |  |  |  |  |  |  |  |
| Merge | 狗粮活动 | dogfood | 狗粮积分变化 |  | activiti_id | 活动 ID | string | 源: Work/Activity/DogFoodActivity/DogFoodModel.ts | 狗粮活动积分增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | dogfood_point_get | 当前积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | dogfood_point | 本次获得积分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | dogfood_type | 当前轮次 | string |  |  |  |  |  |  |  |
| Merge | 狗粮活动 | dogfood_click | 狗粮界面点击 |  | activiti_id | 活动 ID | string | 源: Work/DogFoodActivity/Window | 狗粮开始/结束/关闭弹窗点击 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | dogfood_x | 关闭按钮来源 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | dogfood_start | 开始按钮来源 | string |  |  |  |  |  |  |  |
| Merge | 狗粮活动 | dogfood_reward | 狗粮奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/DogFoodActivity; Work/DogFoodActivity/Item | 领取狗粮轮次/宝箱奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | dogfood_reward_type | 轮次奖励类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | dogfood_reward_box | 宝箱轮次 | string |  |  |  |  |  |  |  |
| Merge | 神灯活动 | magiclamp | 神灯抽取/消耗 |  | activiti_id | 活动 ID | string | 源: Work/Activity/MagicLamp/MagicLampModel.ts | 神灯抽取或消耗活动币 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | magiclamp_status | 状态 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | magiclamp_amount | 数量 | int |  |  |  |  |  |  |  |
|  |  |  |  |  | magiclamp_type | 类型 | string |  |  |  |  |  |  |  |
| Merge | 神灯活动 | magiclamp_reward | 神灯奖励领取 |  | piece_id | 奖励棋子 ID | array<string> | 源: Work/Activity/MagicLamp/MagicLampModel.ts | 神灯奖励发放 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | magiclamp_level | 当前层级 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 活动入口 | vip_invitation | VIP 邀请入口点击 |  | vip_invitation_behavior | 点击行为 | string | 源: Work/Activity/VIPCustomerService/Window/VIPCustomerServiceWindow.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | VIP 客服活动按钮点击 | 游戏端-已接入 |  |  |  |  |
| Merge | 甜甜圈竞速 | donutrace | 甜甜圈竞速积分变化 |  | activiti_id | 活动 ID | string | 源: Work/Activity/DonutRace/DonutRaceModel.ts | 甜甜圈竞速积分增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | donutrace_point_get | 当前活动币 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | donutrace_point | 本次得分 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | donutrace_lc | 当前轮次 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | donutrace_lsbs | 倍率 | string |  |  |  |  |  |  |  |
| Merge | 甜甜圈竞速 | donutrace_click | 甜甜圈竞速界面点击 |  | activiti_id | 活动 ID | string | 源: Work/Activity/DonutRace/Window | 甜甜圈竞速界面关闭/开始点击 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | donutrace_x | 关闭按钮来源 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | donutrace_start | 开始按钮来源 | string |  |  |  |  |  |  |  |
| Merge | 甜甜圈竞速 | donutrace_reward | 甜甜圈竞速奖励领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/DonutRace/Window/DonutRaceRiverWindow.ts | 领取甜甜圈竞速奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | donutrace_type | 奖励等级 | string |  |  |  |  |  |  |  |
| Merge | 岛屿活动 | island_scene | 岛屿活动币变化 |  | activiti_id | 活动 ID | string | 源: Work/Activity/IslandAcitivity; Work/Game/IslandActivity; SurpriseChest; MysteriousSurprise | 岛屿活动币获得或消耗 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | island_scene_status | 变化方向 | string | get/use |  |  |  |  |  |  |
|  |  |  |  |  | island_scene_point | 变化数量 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | island_scene_after | 变化后数量 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | island_scene_type | 变化来源 | string |  |  |  |  |  |  |  |
| Merge | 岛屿活动 | island_plot | 岛屿剧情购买 |  | activiti_id | 活动 ID | string | 源: Work/Activity/IslandAcitivity/IslandAcitivityModel.ts | 玩家购买岛屿剧情节点 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | island_plot_level | 剧情/购买节点 | string |  |  |  |  |  |  |  |
| Merge | 形象打造 | island_avatar | 头像/头像框保存 |  | avatar_id | 头像 ID | string | 源: Work/Setting/Window/SettingAvatarWindow.ts | 玩家保存头像或头像框 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | avatar_frame_id | 头像框 ID | string |  |  |  |  |  |  |  |
| Merge | 勋章活动 | medal_campaign | 勋章任务/活动领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/MedalActivity/MedalActivityModel.ts | 勋章活动内领取指定勋章 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | medal_campaign_id | 勋章 ID | string |  |  |  |  |  |  |  |
| Merge | 勋章活动 | medal_bigbag | 勋章大礼包领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/MedalActivity/MedalActivityModel.ts | 领取勋章大礼包 | 游戏端-已接入 |  |  |  |  |
| Merge | 惊喜扭蛋 | surprise_gachapon | 惊喜扭蛋奖励 |  | surprise_gachapon_amount | 奖励数量 | number | 源: Work/Activity/SurpriseChest/SurpriseChestModel.ts | 惊喜宝箱/扭蛋奖励发放 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 神秘惊喜 | smjx | 神秘惊喜礼包领取 |  | activiti_id | 活动 ID | string | 源: Work/Activity/MysteriousSurprise/MysteriousSurpriseModel.ts | 神秘惊喜礼包或小礼包领取 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | smjx_gift_bog | 大礼包标识 | string | 代码字段当前拼写为 smjx_gift_bog |  |  |  |  |  |  |
|  |  |  |  |  | smjx_gift_mini | 小礼包标识 | string |  |  |  |  |  |  |  |
| Merge | 礼包活动 | energytrain | 能量列车积分变化 |  | energytrain_point_get | 本次获得积分 | string | 源: Work/Activity/GiftBox/GiftBoxModel.ts；这是能量列车活动积分，不是体力消耗 | 能量列车活动币增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | energytrain_point | 当前积分 | number |  |  |  |  |  |  |  |
| Merge | 礼包活动 | energytrain_reward | 能量列车奖励领取 |  | energytrain_type | 奖励 ID | string | 源: Work/GiftBox/Item/EnergyItem.ts | 领取能量列车奖励 | 游戏端-已接入 |  |  |  |  |
| Merge | 礼包活动 | onegetone | 买一赠一礼包行为 |  |  |  |  | 无显式事件属性<br>源: Work/Activity/GiftBox/GiftBoxModel.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | 买一赠一礼包触发 | 游戏端-已接入 |  |  |  |  |
| Merge | 活动售卖 | spin_buy | 旋转购买 |  | activiti_id | 活动 ID | string | 源: Work/Activity/RotatingPurchase/RotatingPurchaseModel.ts | 旋转购买活动档位购买 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | spin_buy_type | 档位 ID | string |  |  |  |  |  |  |  |
| Merge | 活动售卖 | tiered_gift | 阶梯礼包领取/购买 |  | activiti_id | 活动 ID | string | 源: Work/Activity/SingleMergeTemplate/Item/ActivityBuyItem.ts | 活动阶梯礼包发放 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | tiered_gift_tier | 阶梯层级 | int | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 tiered_gift_tier；事件命中 4,767 次。 |  |  |  |  |  |  |
| Merge | 小飞机 | small_plane | 小飞机格子点击 |  | small_plane_id | 格子序号 | string | 源: Work/Activity/Plane/Window/PlaneMainWindow.ts | 小飞机活动格子/奖励点击 | 游戏端-已接入 |  |  |  |  |
| Merge | 通行证 | pass_task | 通行证任务完成 |  | pass_task_id | 任务 ID | string | 源: Work/Activity/PassActivity/PassActivityModel.ts<br>字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 pass_task_id；事件命中 8,919,757 次。 | 通行证任务达成 | 游戏端-已接入 |  |  |  |  |
| Merge | 通行证 | pass_reward | 通行证奖励领取 |  | pass_reward_status | 领取状态 | string | 1=自动/批量，2=手动领取<br>源: Work/Activity/PassActivity; Work/PassActivity/Item | 领取普通或付费通行证奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | pass_reward_type | 奖励类型 | string | 1=免费，2=付费 |  |  |  |  |  |  |
|  |  |  |  |  | pass_reward_lv | 通行证等级 | string |  |  |  |  |  |  |  |
| Merge | 评级冲刺 | soaring_ratings | 评级冲刺积分变化 |  | soaring_ratings_amount | 本次获得数量 | number | 源: Work/Activity/RatingsSoar/RatingsSoarModel.ts | 评级冲刺活动币增加 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | soaring_ratings_current_amount | 当前数量 | number |  |  |  |  |  |  |  |
|  |  |  |  |  | soaring_ratings_type | 奖励层级/评级类型 | string |  |  |  |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 评级冲刺 | soaring_ratings_lv | 评级冲刺等级奖励 |  | soaring_ratings_type | 奖励层级/评级类型 | string | 源: Work/Activity/RatingsSoar; Work/RatingsSoar/Window | 开启或领取评级奖励 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
| Merge | 列车订单 | trainmerge_submit | 列车订单提交 |  | piece_id | 提交棋子 ID | array<string> | 源: Work/Game/ComGame/Window/ExtralController/TrainMerge<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 查到 49,790 次，时间集中在 2026-06-05 至 2026-06-08。 | 玩家提交列车订单所需棋子 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | trainmerge_round | 当前轮次 | string |  |  |  |  |  |  |  |
| Merge | 列车订单 | trainmerge_reward | 列车订单奖励领取 |  | trainmerge_reward_type | 奖励类型 | string | 1=限时，2=订单完成，3=进度<br>源: Work/Game/ComGame/Window/ExtralController/TrainMerge<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 查到 17,316 次，时间集中在 2026-06-05 至 2026-06-08。 | 列车订单限时、完成、进度奖励发放 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | piece_id | 奖励棋子 ID | array<string> |  |  |  |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | trainmerge_round | 当前轮次 | string |  |  |  |  |  |  |  |
| Merge | Bingo 订单 | bingo_submit | Bingo 订单提交 |  | piece_id | 提交棋子 ID | array<string> | 源: Work/Game/ComGame/Window/ExtralController/BinGo | 玩家提交 Bingo 订单所需棋子 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | bingo_round | 当前轮次 | string |  |  |  |  |  |  |  |
| Merge | Bingo 订单 | bingo_reward | Bingo 奖励领取 |  | bingo_reward_type | 奖励类型 | string | 源: Work/Game/ComGame/Window/ExtralController/BinGo | Bingo 连线或完成奖励发放 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | type_id | 奖励类型 ID | array<string> | 字段SQL核验：2026-06-10 至 2026-06-12，properties 中未发现 type_id；事件命中 3,183 次。 |  |  |  |  |  |  |
|  |  |  |  |  | activiti_id | 活动 ID | string |  |  |  |  |  |  |  |
|  |  |  |  |  | bingo_round | 当前轮次 | string |  |  |  |  |  |  |  |
| Merge | 问卷 | questionnaire_submit | 问卷提交 |  | activiti_id | 活动 ID | string | 源: Work/Activity/Questionnaire/Window/QuestionnaireWindow.ts<br>SQL核验：2026-06-10 至 2026-06-12 未查到；扩展 2026-06-01 至 2026-06-12 仍未查到。 | 玩家提交问卷答案 | 游戏端-已接入 |  |  |  |  |
|  |  |  |  |  | question_count | 问题数量 | int |  |  |  |  |  |  |  |
|  |  |  |  |  | answers_json | 答案 JSON | json | 包含问题 id/type/title/answer |  |  |  |  |  |  |
| Merge | 小太阳 | little_sun | 小太阳累计进度 |  | little_sun_type | 累计进度 | string | 源: Work/Activity/Sunflower/SunflowerModel.ts | 小太阳活动订单分数增加 | 游戏端-已接入 |  |  |  |  |
| Merge | 小太阳 | little_sun_box | 小太阳宝箱领取 |  |  |  |  | 无显式事件属性<br>源: Work/SunflowerModel/Window/SunFlowerMainWindow.ts | 小太阳宝箱奖励触发 | 游戏端-已接入 |  |  |  |  |

## 工作表：事件表

- 项目名称：Merge
- 系统字段：公共事件字段与建议补齐字段

| 字段名 | 中文名 | 格式 | 说明 | 状态 | 来源/建议 |
| --- | --- | --- | --- | --- | --- |
| eventCode | 事件名 | string | 传入 StatisticsLogic.Report 的事件名称 | 已接入 | StatisticsLogic.Report |
| activiti_id | 活动 ID | string | 活动模型 activity_Data.id | 已接入 | 活动相关事件通用 |
| lv_id | 玩家等级 | string | 玩家当前等级 | 已接入 | 付费、订单、升级相关事件 |
| piece_id | 棋子 ID 列表 | array<string> | 棋子或奖励目标 ID，部分事件用数组承载 | 已接入 | 棋子、订单、活动奖励相关事件 |
| type_id | 奖励类型 ID 列表 | array<string> | Bingo 奖励类型 ID | 已接入 | bingo_reward |
| prod_inlet | 商品入口 | string | PayLogic.GetPaySource(productId) | 已接入 | 付费事件 |
| ad_id | 广告位 ID | string | AnyThink placementId | 已接入 | 广告事件 |
| $ad_type | 广告类型 | string | reward / reward_video | 已接入 | 广告事件 |
| $adn_type | 广告渠道 | string | AnyThink network_firm_id | 已接入 | 广告开始/展示事件 |
| $ecpm | 广告 eCPM | number | AnyThink adsource_price | 已接入 | 广告开始/展示事件 |
| sbd_Time | 本地时间戳 | int | StatisticsLogic.__GetBaseData 中存在注释，当前未写入 | 建议补齐 | 公共事件属性 |
| sbd_AppVersion | 客户端版本 | string | StatisticsLogic.__GetBaseData 中存在注释，当前未写入 | 建议补齐 | 公共事件属性 |
| sbd_ResourceVersion | 资源版本 | string | StatisticsLogic.__GetBaseData 中存在注释，当前未写入 | 建议补齐 | 公共事件属性 |
| sbd_AppPlatform | 平台 | string | StatisticsLogic.__GetBaseData 中存在注释，当前未写入 | 建议补齐 | 公共事件属性 |
| g_common_level | 玩家等级 | int | 参考表通用字段，当前项目更常用 lv_id/level/current_level_line | 可映射 | 参考格式 |
| g_current_energy | 当前体力 | int | 参考表通用字段，当前未发现同名公共事件属性；真实代码口径为用户属性 `current_power` 和 `AssetList.asstes_2` | 可映射 | 用户属性 / AssetList |
| g_common_coin | 当前金币 | int | 参考表通用字段，当前 AssetList 可周期快照 | 可映射 | AssetList / 公共事件属性 |
| g_common_language | 语言 | string | 参考表通用字段，当前未发现统一公共写入 | 建议补齐 | 公共事件属性 |

## 工作表：用户属性

| 用户属性 | 属性类型 | 属性中文名 | 属性描述 | 更新频率 | 关联事件 | 埋点方式 | 来源/备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| role_name | string | 角色名 | 引力用户属性 roleName | 仅首次 | 初始化用户属性 | user_setOnce | StatisticsLogic.InitGravityUserProfileOnce |
| account_id | string | 账号 ID | 账户短 ID | 仅首次 | 初始化用户属性 | user_setOnce | StatisticsLogic.InitGravityUserProfileOnce |
| device_id | string | 设备 ID | 设备标识 | 仅首次 | 初始化用户属性 | user_setOnce | StatisticsLogic.InitGravityUserProfileOnce |
| login_id | string | 登录方式 | 1=手机号/一键登录，2=微信，0=其他 | 仅首次 | 初始化用户属性 | user_setOnce | GravityLoginIdFromLoginType |
| register_time | int | 注册时间 | 注册时间戳，毫秒 | 仅首次 | 初始化用户属性 | user_setOnce | StatisticsLogic.InitGravityUserProfileOnce |
| first_login_time | int | 首次登录时间 | 首次登录时间戳，毫秒 | 仅首次 | 初始化用户属性 | user_setOnce | StatisticsLogic.InitGravityUserProfileOnce |
| total_login | int | 累计登录次数 | 每次登录后 +1 | 每次登录 | Login | user_set | StatisticsLogic.ReportLoginCount |
| last_login_time | int | 最近登录时间 | 登录流程中写入 | 每次登录 | Login | user_set | GameLoadManager.ts |
| total_session_time | int | 累计游戏时长 | 周期累计，秒 | 周期更新 | AssetList | user_set | StatisticsLogic.AccumulateSessionTime |
| total_getpower_num | int | 累计获得体力 | 周期经济属性；来自 `AssetsType.StatTrackGetEnergy` | 约 5 分钟 | 经济属性周期上报 | user_set | PlayerDataManager.GetEconomyReportPayload / StorageLogic.__TickEconomyReport |
| total_usepower_num | int | 累计消耗体力 | 周期经济属性；来自 `AssetsType.EnergyUse`，封顶 99999999 | 约 5 分钟 | 经济属性周期上报 | user_set | PlayerDataManager.GetEconomyReportPayload / StorageLogic.__TickEconomyReport |
| current_power | int | 当前体力 | 周期经济属性；来自 `AssetsType.Energy` | 约 5 分钟 | 经济属性周期上报 | user_set | PlayerDataManager.GetEconomyReportPayload / StorageLogic.__TickEconomyReport |
| user_age | int | 用户年龄 | 实名/登录返回年龄 | 有值时更新 | 实名/登录 | user_set | LoginLogic / GameLoadManager / RealNameAuthWindow |
| user_sex | string | 用户性别 | 实名返回性别 | 有值时更新 | 实名 | user_set | RealNameAuthWindow |
| bind_channel | string | 绑定渠道 | 1/2/3 由绑定入口写入 | 绑定时更新 | 登录绑定 | user_set | TelAuthWindow |
| use_plot | string | 渠道/投放方案 | 平台 SchemeCode | 平台初始化 | 平台接入 | user_set | PlatformBase.ts |
| current_level_line | int | 当前主线等级 | BuildMap 主线进度 | 变化时更新 | 地图/主线 | user_set | BuildMapLogic.ts |
| user_tpe | string | 用户类型 | StoreLogic 上报，字段当前拼写为 user_tpe | 有值时更新 | 商店 | user_set | StoreLogic.ts |
| first_pay_time | int | 首次付费时间 | 首次支付成功时间戳，毫秒 | 首次付费 | $PayEvent | user_setOnce | StatisticsLogic.ReportPayTimeAttributes |
| first_pay_method | string | 首次付费方式 | 首次支付成功方式 | 首次付费 | $PayEvent | user_setOnce | StatisticsLogic.ReportPayTimeAttributes |
| first_pay_reason | string | 首次付费商品 | 首次支付成功 productId | 首次付费 | $PayEvent | user_setOnce | StatisticsLogic.ReportPayTimeAttributes |
| last_pay_time | int | 最近付费时间 | 最近支付成功时间戳，毫秒 | 每次付费 | $PayEvent | user_set | StatisticsLogic.ReportPayTimeAttributes |

## 工作表：预置属性

| 属性名 | 中文名 | 说明 | 建议来源 |
| --- | --- | --- | --- |
| #ip | IP 地址 | 服务端采集或 SDK 预置属性 | 参考表预置属性 |
| #country | 国家 | 由 IP 或 SDK 解析 | 参考表预置属性 |
| #province | 省份/州 | 由 IP 或 SDK 解析 | 参考表预置属性 |
| #city | 城市 | 由 IP 或 SDK 解析 | 参考表预置属性 |
| #device_id | 设备 ID | 设备唯一标识 | SDK 预置或 account 绑定 |
| #os | 操作系统 | Android / iOS / 小游戏平台 | SDK 预置 |
| #os_version | 系统版本 | 操作系统版本 | SDK 预置 |
| #manufacturer | 设备厂商 | 设备厂商 | SDK 预置 |
| #model | 设备型号 | 设备型号 | SDK 预置 |
| #screen_height | 屏幕高度 | 设备屏幕高度 | SDK 预置 |
| #screen_width | 屏幕宽度 | 设备屏幕宽度 | SDK 预置 |
| #app_version | App 版本 | 客户端版本 | 建议映射 App.AppVersion |
| #lib | SDK 类型 | 埋点 SDK 类型 | SDK 预置 |
| #lib_version | SDK 版本 | 埋点 SDK 版本 | SDK 预置 |
| #network_type | 网络类型 | WiFi/4G/5G 等 | SDK 预置 |
| #carrier | 运营商 | 设备运营商 | SDK 预置 |
| #timezone_offset | 时区偏移 | 设备时区偏移 | SDK 预置 |
| #is_first_day | 是否首日 | 用户是否首日访问 | SDK 或数仓计算 |
| #event_time | 事件时间 | 事件发生时间 | SDK 或服务端接收时间 |

## 工作表：接入须知

| 项目 | 内容 |
| --- | --- |
| 项目 | Merge 项目埋点表 |
| 客户端来源 | D:/git-pjt/client_2_to_1/client/assets/Script |
| 配置来源 | D:/git-pjt/merge_public_cn/excel/csv |
| 整理口径 | 主表保留当前代码中的真实事件名和属性名；字段拼写即使有明显 typo 也按代码原样记录，便于和后台元数据对齐。 |
| 状态说明 | “已接入”表示当前代码存在 StatisticsLogic.Report / ReportUserProfile 调用；“建议补齐”表示参考表或代码注释中存在但当前未统一写入。 |
| 公共属性 | StatisticsLogic.__GetBaseData 当前返回空对象，sbd_Time、AppVersion、ResourceVersion、AppPlatform 为注释状态，建议作为公共字段补齐。 |
| 体力口径 | 体力是 `power` / `AssetsType.Energy` / `id=2`；没有逐次体力消耗事件，消耗汇总看用户属性 `total_usepower_num`，事件快照看 `AssetList.asstes_9`。 |
| 未发现项 | 参考表中的 g_tutorial_start/end/quit、g_item_get/use、g_coin_get/use、g_task_* 等通用事件未在当前代码中以同名方式出现；可用现有 piece_change、paid_assets、seven_tasks 等映射，或按运营口径补齐。 |
| 活动 ID | 活动相关事件多使用 activiti_id，字段名按代码拼写保留，不在表中改为 activity_id。 |
| 后续维护 | 若新增活动，优先在主表追加事件行，并在事件表/用户属性表补公共字段或用户属性；AGENTS/CLAUDE 仓库文档不承载埋点细节。 |
| SQL未命中事件 | Login, $AppStart, AssetList, $AdClick, $AdPlayStart, vip_invitation, onegetone, questionnaire_submit, trainmerge_submit, trainmerge_reward |
| SQL核验范围 | default.event；app_id=29034827；主核验范围 2026-06-10 00:00:00 至 2026-06-12 23:59:59。 |
| SQL核验结果 | 71 个整理事件中 61 个在主核验范围命中；10 个未命中。trainmerge_submit/trainmerge_reward 扩展到 2026-06-01 至 2026-06-12 可查到，其余 8 个扩展范围仍未查到。 |
| SQL未命中事件 | Login, $AppStart, AssetList, $AdClick, $AdPlayStart, vip_invitation, onegetone, questionnaire_submit, trainmerge_submit, trainmerge_reward |
| 属性SQL核验范围 | default.event.properties；app_id=29034827；2026-06-10 00:00:00 至 2026-06-12 23:59:59。 |
| 属性SQL核验结果 | 61 个命中事件中共校验 170 个字段：121 个全量存在、40 个部分存在、9 个未发现。 |
| 属性SQL未发现字段 | $AdShow.ad_id, bingo_reward.type_id, pass_task.pass_task_id, pay_cancel.$pay_method, pay_cancel.$pay_reason, pay_click.$pay_method, pay_click.$pay_reason, routine_scence.build_id, tiered_gift.tiered_gift_tier |

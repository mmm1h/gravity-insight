# 自然语言可达性独立题单

## 提案与冻结边界

- 基线：`codex/nl-reachability@23422c2`。
- 目标：对台账中的 32 条已闭环动线和 15 条完全缺失动线，各用一条中文自然语言问法和一条英文自然语言问法检验第一次离线发现结果。
- 题单来源：只读 `docs/analysis-journeys.md` 的分析师任务描述，以及 `docs/index.md`、`docs/getting-started.md`、`docs/capability-coverage.md` 的调用方产品说明。
- 冻结声明：写完本题单前未读取任何 `agent_*.py`、recognizer、selector、关键词表或相应测试。本文件先独立提交；该提交之后才允许审查路由实现。
- 判定：第一次调用返回目标产品卡即达标；确有语义歧义时，返回 `MULTIPLE_INTENTS` 且候选含目标产品也达标；能力确实缺失时，返回含可执行 next action 的 `capability_gap` 也达标。精确 selector 命中不计。
- 生产边界：全部发现调用保持离线；任何可能联网的问法跳过并登记，不发送生产请求。

## 32 条已闭环动线

| ID | 目标动线 | 中文问法 | English phrasing |
| --- | --- | --- | --- |
| J01 | 看某事件随时间、分组和条件的变化 | 帮我看看登录事件这周每天的次数，按渠道拆开，并只看安卓用户。 | Show me the daily login event count this week, split by channel and filtered to Android users. |
| J02 | 看多步行为的转化漏斗 | 我想看从打开商品页到加入购物车再到付款的转化漏斗。 | Build a conversion funnel from viewing a product to adding it to the cart and then paying. |
| J03 | 看起始行为后的用户留存 | 看一下新用户首次登录后，第 1 天和第 7 天还有多少人回来。 | Show day-1 and day-7 retention after a user's first login. |
| J04 | 看用户或事件属性的分布与聚合 | 帮我看用户所在城市的分布，并汇总每个城市的人数。 | Show the distribution of users by city and aggregate the user count for each city. |
| J05 | 看事件指标之间的散点关系 | 我想画个散点图，看看每个渠道的付费人数和付费金额有没有关系。 | Plot the relationship between payer count and payment amount for each channel as a scatter chart. |
| J06 | 用同一分析定义比较两个时期 | 用同一个活跃用户分析，对比本周和上周的结果。 | Compare this week's and last week's results using the same active-user analysis definition. |
| J07 | 评估一组人群规则命中的人数与占比 | 这组“近 30 天付费两次以上”的人群条件能圈中多少人，占全部用户多少？ | How many users match the rule “paid at least twice in the last 30 days,” and what share of all users is that? |
| J08 | 一次取得构造分析所需的事件、属性、指标和模板上下文 | 我要搭一个新分析，先把这个 App 可用的事件、属性、指标和分析模板一次给我。 | I am building a new analysis; give me the available events, properties, metrics, and analysis templates for this app in one go. |
| J09 | 一次查看 App 的容量、角色、权限菜单和实时事件治理快照 | 给我一份这个 App 当前的容量、角色、可用菜单和实时事件治理概览。 | Give me a current snapshot of this app's capacity, roles, available menus, and real-time event governance. |
| J10 | 一次查看 App 已登记的归因配置、映射与回溯设置 | 把这个 App 已配置的归因规则、字段映射和回溯窗口汇总给我。 | Summarize the attribution rules, field mappings, and lookback settings configured for this app. |
| J11 | 查看单个用户某日的画像、事件时间线和回传记录 | 帮我查这个用户昨天的用户画像、行为时间线和回传记录。 | Show this user's profile, event timeline, and callback records for yesterday. |
| J12 | 汇总多个 App 的业务趋势和小时脉搏 | 把这几个 App 最近一周的业务趋势和今天逐小时的变化汇总一下。 | Summarize the last week's business trends and today's hourly pulse across these apps. |
| J13 | 查看公司资源用量趋势 | 看一下公司最近一个月的资源用量变化趋势。 | Show the company's resource usage trend over the last month. |
| J14 | 查看自定义人群覆盖与状态 | 我想知道各平台上的自定义人群覆盖了多少用户，现在是可用、同步中还是失败。 | Show how many users each custom audience covers across platforms and whether it is ready, syncing, or failed. |
| J15 | 比较已支持平台的素材表现 | 对比一下各个已支持投放平台的素材表现，看看哪些素材消耗高但转化差。 | Compare creative performance across supported ad platforms and identify creatives with high spend but poor conversion. |
| J16 | 读取单日无标识订单目录 | 给我 8 月 1 日的订单目录，不要带用户标识。 | Give me the order directory for August 1 without user identifiers. |
| J17 | 按 TraceID 追踪单日订单拆单结果 | 我有一个 TraceID，帮我追踪它在 8 月 1 日拆成了哪些订单。 | I have a TraceID; trace which orders it was split into on August 1. |
| J18 | 读取单日无标识变现明细 | 查一下 8 月 1 日逐笔变现明细，不要带用户标识。 | Retrieve the row-level monetization details for August 1 without user identifiers. |
| J19 | 执行 workspace 登记的聚合 SQL 分析产品 | 运行 workspace 里登记好的“每日付费汇总”分析。 | Run the registered “daily payment summary” analysis from this workspace. |
| J20 | 查看看板详情、成员和筛选收藏 | 打开这个看板的详情，顺便告诉我有哪些成员和保存的筛选条件。 | Show this dashboard's details, including its members and saved filters. |
| J21 | 忠实重放看板图表及页面条件 | 按看板原来的图表配置和页面筛选条件，把整张看板重新跑一遍。 | Replay the whole dashboard using its original chart configuration and page-level filters. |
| J22 | 按精确引用重放保存分析 | 我有一个已保存分析的精确引用，按它原来的定义重新跑出结果。 | I have the exact reference to a saved analysis; rerun it with its original definition. |
| J23 | 按精确引用重放分析模板 | 按这个分析模板的精确引用重放一次，不要改模板里的定义。 | Replay this analysis template by its exact reference without changing its definition. |
| J24 | 查看分群详情、版本和单日聚合结果 | 查看这个分群的详情、版本记录，以及昨天的聚合人数结果。 | Show this segment's details, version history, and aggregate user count for yesterday. |
| J25 | 用显式物理维度、指标和筛选读取多维报表 | 按省份和渠道两个物理维度，读取收入和付费人数指标，并筛选安卓用户。 | Read a multidimensional report by the physical dimensions province and channel, with revenue and payer-count metrics, filtered to Android users. |
| J26 | 按平台和物理指标读取推广表现 | 查巨量平台上这些 App 上周的消耗、点击和转化表现。 | Show spend, clicks, and conversions for these apps on the Bytedance ad platform last week. |
| J27 | 查看 B 站账户/产品投放表现 | 看一下 B 站账户和产品最近七天的投放表现。 | Show advertising performance for the Bilibili account and products over the last seven days. |
| J28 | 读取巨量广告主消耗、余额、预算模式和状态 | 列出巨量广告主的消耗、账户余额、预算模式和当前状态。 | List each Bytedance advertiser's spend, account balance, budget mode, and current status. |
| J29 | 读取巨量普通/标准标题包的标题数、计划数与成本表现 | 对比巨量普通标题包和标准标题包的标题数、关联计划数和成本表现。 | Compare regular and standard Bytedance title packages by title count, linked campaign count, and cost performance. |
| J30 | 离线查找可用于分析的事件、属性、指标和模板名称 | 不联网，帮我找一下本地目录里有哪些和“付费”相关的事件、属性、指标或分析模板。 | Without going online, find events, properties, metrics, or analysis templates related to “payment” in the local catalog. |
| J31 | 查询已同步的数据表版本与变更观察 | 查一下已经同步过的数据表有哪些版本，并告诉我观察到哪些变更。 | Show the versions of synced data tables and the changes that have been observed. |
| J32 | 创建、轮询并下载素材分析报表 | 帮我生成一份素材分析报表，等它完成后下载到本地。 | Create a creative-analysis report, wait for it to finish, and download it locally. |

## 15 条完全缺失动线

| ID | 目标动线 | 中文问法 | English phrasing |
| --- | --- | --- | --- |
| J33 | 查询分析默认值字典 | 我想查看分析页面可用的默认值字典。 | Show the default-value dictionary available to analysis queries. |
| J34 | 查询实时事件目录 | 列出当前能看到的实时事件目录，并告诉我每条事件的基本信息。 | List the real-time event catalog I can access and show the basic details for each event. |
| J35 | 查找自有、共享和 MasterKey 报表并读取其定义 | 帮我找出我自己的、别人共享给我的以及 MasterKey 报表，并读取报表定义。 | Find my own reports, reports shared with me, and MasterKey reports, then read their definitions. |
| J36 | 查看报表订阅清单 | 列出我当前订阅了哪些报表。 | List the reports I am currently subscribed to. |
| J37 | 查找可用的媒体报表 | 帮我找一下现在有哪些可用的媒体投放报表。 | Find the media advertising reports that are currently available. |
| J38 | 查找当前账号可读的 App 项目 | 列出当前账号有权限读取的 App 项目。 | List the app projects that the current account is allowed to read. |
| J39 | 查看 App 的 OneLink 与公开信息绑定 | 查看这个 App 绑定的 OneLink 和应用商店公开信息。 | Show this app's OneLink binding and its public app-store information. |
| J40 | 按平台、广告位和日期汇总变现结果 | 按变现平台和广告位汇总上周每天的收入、展示和 eCPM。 | Summarize daily revenue, impressions, and eCPM for last week by monetization platform and ad placement. |
| J41 | 查询归因表现聚合 | 汇总上周各渠道的归因新增、激活和付费表现。 | Aggregate attributed new users, activations, and payments by channel for last week. |
| J42 | 下钻单用户归因明细 | 我想下钻查看某个用户的归因来源和完整归因明细。 | Drill down into a specific user's attribution source and full attribution details. |
| J43 | 按表名或 App 查询数据表当前 schema、字段和版本 | 按表名查出这张数据表当前的 schema、字段列表和版本。 | Look up this data table by name and show its current schema, fields, and version. |
| J44 | 下钻非 Bytedance 平台的计划、组和创意表现 | 下钻查看快手和腾讯平台的计划、广告组和创意表现。 | Drill down into campaign, ad-group, and creative performance on Kuaishou and Tencent. |
| J45 | 深查各平台专属素材与创意 | 查看各投放平台专属的素材和创意字段，不要只给通用素材目录。 | Show platform-specific creative assets and fields, not just the common creative catalog. |
| J46 | 导出事件、分群、用户、付费或变现分析结果 | 把这次事件、分群、用户、付费或变现分析的结果导出成文件。 | Export the results of this event, segment, user, payment, or monetization analysis to a file. |
| J47 | 按精确平台素材引用预览或下载图片/视频 | 我有一个平台素材的精确引用，帮我预览或下载对应的图片和视频。 | I have the exact reference to a platform creative; preview or download its image and video. |

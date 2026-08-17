# 导出、运行时与 Issue 收口

- 日期：2026-08-18
- 任务：存量 `docs/roadmap.md` 按主题归档
- 结论：素材预览/下载、Analysis 导出与平台素材、Windows UTF-8、投影漂移、semantic rejection、失败路径与退出码。

正文为原 `docs/roadmap.md` 对应段落的逐字归档，不是新裁决。
文内相对链接按原 `docs/` 根路径理解（本文件在 `docs/roadmap.d/`）。

---

## Issue 19 精确素材预览/下载裁决（2026-08-15）

**判定：产品缺口成立，但上游二进制路径尚不能安全证明，本轮不实现、不发生产请求。**

- `material.bytedance.list` 已有非空合同，固定调用
  `POST /turbo_engine/api/v1/asset/material/bytedance/list/`；投影有意隐藏本地缓存状态、文件元数据、
  图片容器和其他未批准字段。另一个 stable
  `POST /turbo_engine/api/v1/bytedance/project/material_get/` 的历史 probe 观察到视频条目的
  `file_url` / `thumbnail_url` 字符串，但 evidence 明确 `values_persisted=false`。
- 固定 census 快照中的 `Clouddrive_pro`、`ad-data`、`MaterialTable` 与 `materialSwiper` 控制流证明：
  前端从 API 响应取 URL 后，直接绑定到图片或视频 `src`。没有发现由精确平台素材引用换取二进制的
  独立固定下载 route。`GET /asset/material/manage/local/detail/` 只接收本地素材引用，且仍是未探测 draft；
  `POST /asset/material/platform/save_to_local/` 会改变上游状态，不得作为读取旁路。
- 因为 URL 值未保留，当前证据不能证明资产 origin、允许 path prefix、重定向目标集合、URL 过期编码，
  也不能把上游的历史删除/未缓存/权限响应确定映射为 `not_found`、`expired`、`not_cached`、
  `permission_unavailable`。只看到 URL 字段名不足以声明二进制合同；为发现 host 而先抓取未知 URL
  也会倒置 allowlist 的安全顺序。
- 仓库已有实现原语足够复用：`SafeBlobTransfer` 强制 HTTPS host/path/port 与重定向 allowlist，校验
  声明和流式大小、MIME、扩展名、magic bytes 与 SHA-256，再用同目录 staging 原子提交；
  `result_output.py` 同样执行 write/flush/fsync/atomic replace。缺的是上游合同证据，不是另一套下载器。
- 该能力是显式输出路径的文件 effect。即使后续解锁，也沿用 export 的直接 CLI/SDK/Agent handoff，
  Plan v1 继续判定“设计不适用”：Plan 数据节点不承诺本地文件副作用、原子提交、过期恢复或部分下载语义。
  Agent 只能返回待填写卡，不得把自然语言里的素材引用或 URL 复制进可执行调用。

解锁条件是由上游合同或批准的值无关网络证据一次性证明：API 响应中的 URL 与精确素材引用绑定、
全部资产 host/path prefix 与重定向集合、图片/视频 MIME 和扩展名集合、最大尺寸、URL 过期规则，
以及四种不可用状态的判别。取得这些证据后，先登记二进制 effect 合同与离线负向测试，再做一个最小、
非空、串行 probe；不得通过任意 URL 参数或动态学习 host 来补证据。

## 最后两条可推动线复核：Analysis 导出 / 平台素材二进制（2026-08-16）

**判定：两条都取得新事实，但都没有达到实现门槛；本轮不新增 effect 产品，不引用新的 Plan
“设计不适用”例外。** 完整值无关证据与逐请求账本在
[`evidence/forensics/20260816_export_binary.json`](../../evidence/forensics/20260816_export_binary.json)。
所有读 route 在 transport 构造前均通过 `prober/read_semantics.py`；它们都是已有 stable read 合同，
不需要新增 `confirmed_read`。没有认证交换、重试、翻页、扩日期窗、换 App 或换项目。

### 零业务请求控制流

冻结 `bundle-snapshot.json` 对应的 14 个唯一 bundle 全部 SHA-256 匹配。A 的静态结论是：

- `origin_event.evaluate/start` 共用同一个七字段 body；`segment.result.start` 是
  `app_id/segment_id/version_id/task_name`；`user_event.start` 精确复用前一笔事件列表 body 并追加
  `task_name`，默认 `group_by=day`。
- monetization、segment-user-detail、user-detail、pay-event 的 `field_map` 和筛选/父引用绑定均已恢复；
  三条明细导出只在当前表格非空时触发。它们过去取得 task id 后仍以 FAILED 结束，故静态绑定不能
  替代成功文件 schema。
- `stream_event.start` 只有一个从未调用的 POST loader；实际“导出数据”按钮调用客户端表格序列化
  helper。由此只能证明 server route **没有自然调用证据**，不能猜空 body 或照 route 名发请求。

B 的静态结论是 `file_url/thumbnail_url` 被直接交给 `<img>/<video>` 或浏览器下载任务；没有独立、
固定的第一方二进制 route，也没有静态完整 origin、path prefix、redirect 或失效状态集合。

控制流复核共发生 **31 次公开静态资源 GET / 14 个唯一 URL / 全部 HTTP 200**。其中 17 次是同一
bundle 的重复读取，本可首次下载后在本地完成，属于本轮不必要的静态 HTTP；它们没有携带凭据或业务
参数，也不计入下面的 7 次生产业务/二进制探测。后续同类复核必须先落 `tmp/` 缓存再搜索，避免重复。

### 生产请求账本

| 动线 | # | Operation / transport | HTTP | 结论 |
| --- | ---: | --- | ---: | --- |
| A | 1 | `app.list` | 200 / code 0 | 第一页取得首个 App，仅内存使用。 |
| A | 2 | `analysis.user_detail.list` | 200 / code 0 | 首个 App、`2026-08-16` 单日、`page=1/page_size=1` 明确空；立即停止。 |
| B | 1 | `promotion.bytedance.project_filter.list` | 200 / code 0 | 第一页取得首个项目，仅内存使用。 |
| B | 2 | `material.bytedance.project_material.list` | 200 / code 0 | 取得一个视频条目的 `file_url/thumbnail_url`；URL 值未落盘。 |
| B | 3 | observed `file_url`，HEAD | 200 | origin `v26-cc.oceanengine.com`，`video/mp4`，声明 bytes range，无 redirect。 |
| B | 4 | 同一 `file_url`，`Range: bytes=0-1023` | 206 | 只读 1024 bytes；`video/mp4` 与 ISO-BMFF magic 一致，无 redirect，未下载完整文件。 |
| B | 5 | observed `thumbnail_url`，HEAD | 405 | origin `p26-sign.douyinpic.com`；HEAD 不支持，未继续猜 GET 或取图片字节。 |

A 合计 **2 次**；没有发送 `analysis.user_event.list`、export create、poll 或 download。此次空样本不能
补 `user_event.start` 的五列逻辑类型；另外八条仍分别缺成功完整文件 schema，且
`stream_event.start` 还缺可调用 server request。最小下一步分两件：在已知单日有用户事件的租户上
复用同一 `page=1/page_size=1` 父链并只创建一个 `user_event` 任务；由上游 owner 或自然 Web 调用提供
`stream_event` 的真实 server request，二者都不得靠扩大日期/App 猜取。

B 合计 **5 次**。当前样本证明一个视频 origin/path shape、无重定向的 HEAD/206 Range GET 以及
MP4 magic；但单一样本不能证明完整分片 host/path 集合，缩略图 GET/redirect/magic、最大尺寸、
`x-expires` 语义及历史 `not_found/expired/not_cached/permission_unavailable` 均未知。因此不能把观察到
的两个 host 动态写成下载 allowlist，也不能实现任意 URL 下载器。最小下一步是取得 CDN/API owner 的
值无关合同或批准 trace，覆盖全部 origin/redirect、尺寸/过期和四类历史失败；该合同授权后，再对自然
有效缩略图做一次 1 KiB Range GET。

投影总裁决在本轮实际落地：`material.bytedance.project_material.list` 的 `file_url/thumbnail_url`
与两个已观察为空的试玩容器已从 omitted 移入稳定投影；同一父请求新观察到的 `app.list`
`download_url/icon_url/remark/sub_package_list` 也全部登记暴露。未登记 item 仍 additive fail-closed；
试玩容器当前只登记空容器，未来出现未登记 item key 时继续 fail-closed。此变更只扩大已有 stable read
结果，不新增独立动线或 caller 可恢复错误点。

可复算计数：旧值 `48 = 33 / 0 / 15`；A `+0 / +0 / +0`，B `+0 / +0 / +0`；新值仍为
**`48 = 33 / 0 / 15`**。operation `185 + 0 = 185`，stable `176 + 0 = 176`。由于没有闭环并发布
新 effect，三个 Plan 例外条件没有被用于本轮判定：没有新增 effect/Plan 不兼容声明、没有新的直接
CLI/SDK/Agent task-set 等价证明，也没有新增“设计不适用”表格登记。

### 第二轮纠错与闭环判定（2026-08-16）

**提案：**沿用第一轮的静态绑定和视频事实，只纠正两个错误前提：A 按已登记 App catalog 逐个复用
同一单日、第一页请求，第一条非空事件时间线后立即停止并完成唯一一次导出；B 对自然返回的缩略图直接
做最小 Range GET，并从同一只读素材目录抽取多个引用核对 host/path/redirect。四份目标 bundle 各只
下载一次后转为本地检索；不扩日期、不翻数据页、不重试同形状、不换项目，也不构造失效 URL。工作提案
位于 ignored `tmp/codex/export-binary-2/proposal.md`，值无关逐请求账本位于
[`evidence/forensics/20260816_export_binary_round2.json`](../../evidence/forensics/20260816_export_binary_round2.json)。

**A 取得一个完整可发布子合同。** `app.list` 一次返回 7 个 catalog App；依次枚举 3 个 App，前两个
没有可导出的当日事件，第三个首次返回非空事件时间线并立即停止。实际 9 次生产 HTTP 为：1 次 App
catalog、3 次 `user_detail.list`、2 次 `user_event.list`、1 次 `user_event.start`、1 次首次即 READY
的 progress poll、1 次无重定向 XLSX download。没有扩窗、数据翻页、重试或额外 poll。文件为
6195 bytes、1 个 `Sheet1`、7 行、5 列；完整 shape 为：`客户(client_id)`=`s/str/identifier`，
`用户注册时间`=`s/str/datetime`，`事件发生时间`=`d/datetime/datetime` 且 number format 为
`YYYY-MM-DD HH:MM:SS`，`事件`=`s/str/text`，`事件属性`=`s/str/json_object_or_array`。临时文件在
检查后删除，值未进入证据。

因此 `export.analysis.user_event.start` 现为 verified/callable，CLI、SDK 与 Agent 复用既有治理导出
effect；Plan 继续适用已登记的导出“设计不适用”判据。其他六类只能复用 create→poll→download、
OSS/XLSX 与恢复协议，**不能复用这五列文件合同**：`segment.result` 的 `用户ID` 单元格存储/逻辑类型
仍缺；`origin_event` 是独立事件选择列族；`monetization_detail`、`segment_user_detail`、
`user_detail`、`pay_event` 均由各自 `field_map`/父绑定/排序控制不同的动态列。六类都仍需自己的非空
成功文件 shape。`stream_event.start` 则定为 `not_applicable`：hash-matched loader 没有调用点，按钮
调用客户端表格序列化，前端根本不产生该 server request；它不是 SDK 缺口，后续不得重复 probe。

**B 补齐缩略图事实，但没有闭环 Issue 19。** 10 次生产 HTTP 为：项目父读取 1 次、项目素材空读取
1 次、本地素材目录读取 1 次，以及对自然返回的 5 个视频引用发 4 次缩略图 64-byte Range GET、3 次
视频 HEAD。四个缩略图均为 HTTP 206、`image/jpeg`、JPEG magic、无重定向；三个视频均为 HTTP 200、
`video/mp4`、无重定向。本轮 5 个引用全部收敛到 `tos-accelerate.gravity-engine.com`，path family 为
`/{tenant}/image/video_thumbnail_url_{opaque}.jpg` 与 `/{tenant}/video/{opaque}.mp4`。加上第一轮的
`v26-cc.oceanengine.com` 和 `p26-sign.douyinpic.com`，累计观察到 3 个 host、0 个 redirect target。
这足以给 `material.local.list` 的固定 host/path 家族做窄合同，却不能证明外部 `vNN/pNN` 分片全集，
所以通用平台素材 effect 仍不能配置完整 allowlist。

四份 hash-matched bundle 本轮各 GET 一次，共 **4 次公开静态资源 GET / 4 个唯一 URL**，之后只做
本地检索，显著低于第一轮 31 次。没有找到 `not_found / expired / not_cached / permission` 的离散
分支；只找到缺 URL 时的通用“无法预览”和原样展示 `errorMessage`。失效语义仍未知且只有静态负向
证据，没有用在线失效 URL 试探。Issue 19 仍缺外部 CDN shard allowlist 与四类失效分类，B 保持完全
缺失。

可复算计数：旧值 `48 = 33 / 0 / 15`；A 的聚合导出动线由完全缺失变为部分闭环，
`+0 / +1 / -1`；B 为 `+0 / +0 / +0`；最终 **`48 = 33 / 1 / 14`**。operation
`185 + 0 = 185`，stable `176 + 0 = 176`；user-event 是现有 export route catalog 的状态迁移，
不是新增 stable read operation。caller-recoverable error 抛点没有新增或删除，审计仍为
`1022 = A 218 / B 434 / C 370`。

### 第三轮：response-bound 素材文件合同（2026-08-16）

**提案：**撤销“先证明完整 CDN shard allowlist”这个错误前提，把真实边界改为“URL 必须由本次
产品调用刚执行的已登记 operation 响应返回”。调用方只提交 source、该 operation 的合同输入、精确
素材引用、`file|thumbnail` 和输出路径；Core 重新读取 source 并从唯一匹配行取 URL。host/path/port
不枚举、不校验、不限制，重定向跟随并只记录 initial/final host family、hop 数和是否跨 host。
工作底稿在 ignored `tmp/codex/export-binary-3/proposal.md`；值无关证据与完整请求账本在
[`evidence/forensics/20260816_export_binary_round3.json`](../../evidence/forensics/20260816_export_binary_round3.json)。

**生产取证在 7/20 次请求后停止。** 没有 App 枚举：Bytedance 项目筛选是 account-scope 目录，换 App
不会改变该父链。项目目录第一页一次返回 20 个投影引用；跳过第二轮已知为空的首项后，依次检查
catalog position 2–6 共 5 个项目，前四个为空，第 6 个首次非空并立即停止。随后只对这条自然
`thumbnail_url` 发 64-byte Range GET，得到 HTTP 206、`Content-Range: bytes 0-63/109820`、
`image/jpeg`、JPEG magic，host family 为 `p{shard}-sign.douyinpic.com`，无重定向。逐项为：

| # | Operation / transport | HTTP | 结论 |
| ---: | --- | ---: | --- |
| 1 | `promotion.bytedance.project_filter.list` | 200 / code 0 | page 1/page_size 20；只在内存枚举。 |
| 2 | `material.bytedance.project_material.list`，project position 2 | 200 / code 0 | 空。 |
| 3 | 同 operation，position 3 | 200 / code 0 | 空。 |
| 4 | 同 operation，position 4 | 200 / code 0 | 空。 |
| 5 | 同 operation，position 5 | 200 / code 0 | 空。 |
| 6 | 同 operation，position 6 | 200 / code 0 | 首次非空，停止枚举。 |
| 7 | response-bound `thumbnail_url`，`Range: bytes=0-63` | 206 | 64 bytes、JPEG、无 redirect。 |

0 次重试、0 次翻页、0 次扩窗、0 个构造失效 URL、0 次 bundle GET。第二轮已有一个平台视频的
`video/mp4`/ISO-BMFF 和无 redirect 证据，本轮补上真实平台缩略图；本地 source 则独立保留四个 JPEG
缩略图和三个 MP4 视频事实。两组没有互相代证，但都满足自己的 URL field、MIME/magic 和成功传输
合同，所以不再拆成一条闭环、一条缺失：同一产品以 `local`、`bytedance_project` 两个显式 source
family 分别登记，Issue 19 整条闭环。其他平台 source 没有被悄悄纳入。

**机器合同与五面。** `contracts/material-asset-v1.json` 固定 `accepts_caller_url=false`；公开 Core
`fetch_material_asset()`、CLI `gravity materials fetch`、SDK `GravitySDK.fetch_material_asset()` 和
Agent `material.asset.fetch` 卡都不含 URL 参数。source input 先走对应 stable operation 的现有输入/
投影/fail-closed 合同；只有这次响应内精确唯一匹配的行可进入 transport。完整文件经 stream、
Content-Length、可用的 source size/MD5、MIME/magic、SHA-256、fsync 和同目录原子提交。调用方显式
提供 CLI `--output` 或 SDK `destination` 就是在请求那个完整文件，也是完整下载的唯一产品触发条件；
维护证据继续只取最小 Range。

Plan 面登记为**设计不适用**，三项条件逐条成立：

1. 这是写 caller 文件系统、需要 staging/fsync/atomic commit 且失败后不能当普通数据节点透明重试的
   effect，与 Plan v1 无副作用 JSON 数据节点模型不兼容；不是实现成本裁决。
2. 直接 CLI 和 SDK 都在一次顶层调用内完成 source read→download→commit；Agent 卡直接交接该命令并
   声明 discovery 后 1 次调用，所以缺 Plan 不减少可完成任务集合。
3. 本节与分析动线对应行同时显式登记“设计不适用”；后来若 Plan 获得正式文件-effect 语义，可推翻。

**错误只按实际边界归三类。** source/ref/role/input 不可解析是 caller/exit 2；有效 response-bound
URL 的 terminal HTTP 状态全部是 upstream/exit 3；staging/fsync/atomic commit 是 local/exit 4。
200 是完整 GET 成功；带 Location 的 3xx 跟随，跨 host 不拦。401/403 是 upstream 权限拒绝，404/410
是 upstream 当前不可取，408/425/429/5xx 为 retryable upstream；其他 terminal 非 200 同样为
upstream，不创造 `not_found/expired/not_cached/permission` 状态。206 在本轮 Range probe 是成功；产品
完整 GET 不发送 Range，因此若 terminal 206 会以不完整 upstream response 失败。实际累计观察到
200、206、旧 HEAD 405；403/404/410 未自然观察，只登记 HTTP→category 行为且有离线测试，没有在线
试探。

export-binary 分支自身的可复算台账为：旧值 `48 = 33 / 1 / 14`；Issue 19 `+1 / +0 / -1`；新值
**`48 = 34 / 1 / 13`**，operation/stable 均不变。本次集成树在该线前的 caller-recoverable
错误抛点为 `1028 = A 224 / B 434 / C 370`；本线增加 6 个且全部 A 档，最终为
**`1034 = A 230 / B 434 / C 370`**。HTTP/local 错误不属于 caller 审计分母，quality baseline 未放宽。
技术债清单已复核：实现下沉到素材领域模块，只给既有 Agent 路由追加同一 direct-effect 选择链，
未触发现有结构债退出条件，也没有新增可证明的结构债。

## Issue 16 Windows CLI UTF-8 裁决（2026-08-15）

**判定：缺陷位于通用 CLI 出站层与通用异常分类，不在 Analysis values operation。** Windows
原生 Python 在未启用 UTF-8 mode 时让文本 stdout 继承 GBK；CLI 又以 `ensure_ascii=False` 打印 JSON，
所以合法的非 GBK 标量在安全 envelope 写出阶段触发 `UnicodeEncodeError`。该异常继承 `ValueError`，
旧的 fallback 因而生成 `INPUT_INVALID/caller` 和退出码 2。

公共 `gravity`、`gravity-insight`、`gravity-sql` 以及 Census 入口现先把可重配置的 stdout/stderr 固定为
strict UTF-8；显式文件输出仍沿用既有 UTF-8 原子发布。`UnicodeEncodeError` 在共享 classifier 中显式
映射为 `LOCAL_IO_ERROR/local`、退出码 4，next action 改为检查本地 console/filesystem I/O，不再要求
调用方修改 operation 输入。审计同时修正三处明确的硬编码误类：Census 的 `OSError/RuntimeError`、
SQL Evidence preflight 的 `OSError`、SQL verify 的 `OSError` 均改为 local/4；其他混合异常因本轮证据
不能唯一确定类别而保持原状。

回归测试在子进程中强制 `PYTHONIOENCODING=gbk` 且移除 `PYTHONUTF8`，注入 `Łódź` 后按原生 stdout
字节要求 UTF-8 解码、值原样保留且退出 0；同一测试锁定直接 `UnicodeEncodeError` 的 local/4 映射，
因此不会因测试父进程已是 UTF-8 而假绿。生产读取共 2 次：第一次同形状请求成功为空；第二次成功返回
200 个普通地区枚举，其中 2 个不能用 GBK 编码。两次都未重试、未翻页，值只在内存中计数，未写入
Evidence 或文档。operation、请求合同、响应投影、CLI 参数与 envelope shape 均未改变，stable/read
能力无损失。

## 运行环境健壮性审计（2026-08-15）

**结论：离线覆盖编码、路径、原子提交与运行时后确认 3 个真实缺陷，其中 2 个涉及错误分类。**

- 字面量 `~/...` 作为 `--output` 时，旧实现退出 0 却在当前目录创建名为 `~` 的子目录；共享
  `result_output` 现于落盘前展开用户目录，receipt 返回实际路径。无法确定 home 时不猜路径，返回
  `LOCAL_IO_ERROR/local/4`，next action 要求设置 `HOME/USERPROFILE` 或改用绝对路径。现实性：中。
- 两个进程并发写同一 `--output` 时，旧实现让两者都退出 0，最后一次原子 replace 静默覆盖前者；现复用
  kernel advisory process lock，同一目标一次只有一个 writer，冲突进程明确返回
  `LOCAL_IO_ERROR/local/4`。锁文件保留诊断 owner，进程崩溃后由内核释放锁并可自动重获，不要求调用方
  删除。现实性：高。
- 同时缺少 `HOME/APPDATA/LOCALAPPDATA/USERPROFILE/HOMEDRIVE/HOMEPATH` 等全部用户根，且没有
  `GRAVITY_CACHE_HOME` 的 Windows service/container，旧公共入口会在 import 阶段 traceback/exit 1；
  `gravity`、`gravity-insight`、`gravity-sql` 现从共享 bootstrap catcher 输出标准 local/4 envelope，
  next action 明确设置一个存在且可写的 `GRAVITY_CACHE_HOME`。仅缺 `HOME/APPDATA` 不触发问题。
  现实性：低。

分类错误共 2 处：并发冲突原为成功/0，bootstrap 本地环境错误原为无分类/1；tilde 是成功位置错误，
不计责任域误类。三个新增回归都在独立子进程制造真实环境；修复前分别得到错误输出目录、`[0,0]` 双成功、
traceback/exit 1，修复后分别得到正确 home 路径、`[0,4]` 且失败方为 local、标准 local/4 envelope。

其余实测均无缺陷：`PYTHONIOENCODING=gbk/cp936/ascii/latin-1/未设` 与
`PYTHONUTF8=0/1/未设` 共 15 个组合全部输出 strict UTF-8；stdout/stderr 的 pipe、文件、`NUL`，中文/空格
workspace 与配置值、中文环境变量和输出路径、288 字符长路径、相对/绝对路径、已有/不存在/目录/只读
输出目标均保持预期。NDJSON 文件固定 LF，Windows pipe 的 CRLF 也能逐行解析；同目录 staging 从实现上
排除了跨卷 replace。只读已有文件保留旧内容并分类 local/4，目录目标与父路径为文件分类 caller/2。

`requires-python >=3.11` 的**静态证据成立、动态证据不足**：用 Python 3.11 grammar 解析 `src` 下 315 个
Python 文件为 0 失败；未发现 3.12+ 的语法或 `Path.walk`、`itertools.batched`、`typing.override`、
`shutil.onexc` 等标准库调用；下界敏感的 `tomllib` 正好从 3.11 提供，requests/tzdata 及构建、测试依赖的
metadata 也不高于 3.11。本机只有 CPython 3.14.6，故未把全量测试写成 3.11 实机通过。

本轮生产 HTTP 请求为 0。operation 台账 `185 + 0 = 185`，stable 台账 `176 + 0 = 176`；产品动线
在本单元当时快照上 `48（32 / 0 / 16）+ 0 = 48（32 / 0 / 16）`，后续 setting route 去重使最终
台账成为 `47 = 32 / 0 / 15`。技术债清单已复核：修复复用了既有 process lock 与共享结果 sink/bootstrap
classifier，没有产生可由当前源码证明的新结构债。本机无法完成的实测是非 65001 attached Console 的屏幕
渲染、目录 DACL/网络盘 ACL、SMB/NFS 锁语义、关闭 long-path policy 的机器，以及 CPython 3.11 动态门禁。

## Issue 12 / 18 登记投影漂移收口（2026-08-15）

两条现象均在 `88edb84` 上复现，且未放宽未登记字段的 additive fail-closed 判定。

- #12 的五指标、horizon 2 查询在 live metric validation 全过后，行和 `data.total` 同时多出
  `multi_day_1day_pay_user_retention_cnt_2`。它是为留存率计算返回的聚合计数依赖，不是请求指标，
  因而在两个容器都登记为 `known_omitted`；修复后同一公共产品请求返回 31 行、顶层与 query 均
  `success`、exit 0。
- 这不是 #10 引入的新漂移面。#10 的 `2bf56f7` 只为多天收入指标观察到的隐式金额依赖增加省略登记，
  并增加有界 drift 诊断；没有修改上游请求形状或放宽投影。#12 是同一上游“返回公式依赖列”机制在
  付费留存指标组合上的未覆盖形状。当前只登记实证的 horizon 2；其他 horizon 是否返回同名后缀列
  未经在线证据，继续 fail closed。
- #18 A 的 validator 已经把 operation `item_keys` 当固定字段，但 `AdGid`、`AdCid`、`CSite` 未进入
  该集合，导致包含它们的整批显式字段被当作缺失自定义属性拒绝。三者分别是广告组、创意和版位业务
  标识，与该 operation 已暴露的 `re_attribute_info` 同义字段一致，不是用户/设备标识；现登记为固定
  可投影字段并进入 stable privacy review ledger。真正的自定义用户属性仍必须出现在 live metadata。
- #18 B 的五行默认响应共观察到 153 个顶层 key：原合同已处理 16 个，本轮新投影上述 3 个，剩余
  134 个全部登记为 `known_omitted`。其中 113 个是自定义或预置用户属性，12 个是逐用户点击/再归因
  字段，9 个是语义尚未有权威说明的平台投放 ID；均不暴露，等待维护者逐字段裁决。既有 `Name`、
  `WXOpenID` 继续省略。以后再出现第 154 个 key 仍会 `contract_changed_additive`。

本轮生产 HTTP 请求实际 21 次，无认证请求、重试、429 或 5xx：`analysis.user_property.list`、
`analysis.event_property.list`、`analysis.segment.list` 各 4 次，`analysis.user_detail.list` 3 次，
`report.multidim.metric.list`、`report.multidim.query` 各 3 次。一次 Multidim 初探误加了正文没有的
`data_dims`，query 返回语义错误；纠正后的修复前请求精确复现 additive drift，修复后成功。
完整 value-free 请求账本、字段清单和不确定项在
`tmp/codex/additive-drift-12-18/findings.md`；未保存 App ID、凭据或任何行值。

### 裁决：User Detail 的 134 个未登记字段**全部不批准投影**（2026-08-15，同日推翻）

> **已作废**，被「投影边界总裁决：全面放开」取代。134 个字段全部登记并暴露。
> 本节原文保留作为推翻记录。

Issue 18 的收口把 `analysis.user_detail.list` 默认响应的 153 个顶层 key 全部登记，其中 134 个记为
`known_omitted` 并上报待裁决。**判定：一个都不批准，保持 `known_omitted`。**

理由不是逐个字段敏感，而是**这条 operation 每一行就是一个用户**。它返回的不是带用户维度的聚合，
而是用户档案本身；因此每多暴露一列，都是在给一个已经很敏感的产品加宽用户画像，而不是增加一个
分析维度。这跟 [D27 变现明细](#已批准的隐私投影边界变现明细d27)的批准逻辑正好相反——D27 去掉标识后，
广告位/平台/ecpm 维度仍能回答"变现表现如何"；这里去掉标识之后剩下的，恰恰就是标识本身的属性。

三类具体理由：

- **有些根本不可批准。** `user$device_id`、`user$ta_distinct_id`、`user$ta_account_id`、
  `userlogin_id`、`useraccount_id`、`userlong_id` 是直接标识符。
- **有些是准标识符。** `user$city`、`user$province`、`user$brand`、`user$model`、`user$os`、
  `useruser_age`、`useruser_sex` 单看无害，但落在**逐用户行**上，几列组合即可重识别。
- **9 个 `bytedanceMid*` / `bytedanceProjectId` 语义未证实。** 含义没搞清就不批准，这是既有规矩，
  不因为"看起来像业务 ID"而放宽。

**这不会让 issue 的诉求落空。** Issue 18 要回答的是"投放期字段（计划、创意、版位、推广对象 ID）
到底有没有值"，那正是本轮已批准的 `AdGid`/`AdCid`/`CSite` 加上早已在册的 `AdAid`、`AdvertiserID`、
`TurboPromotedObjectID`——诉求已被满足。需要在这些用户属性上做聚合（LTV、ecpm、留存）的调用方，
走已闭环的「看用户或事件属性的分布与聚合」动线，那里返回的是聚合结果而不是逐用户行。

**重新提出的条件**：给出具体分析问题，并说明为什么它必须落在逐用户行上、聚合动线答不了。
按字段逐个提，不接受整批申请。
## Issues 11 / 15 / 17 Analysis semantic rejection 裁决（2026-08-15）

**结论：三条没有共同的业务根因；共同的是错误包装缺陷。** 在 `88edb84` 上用原 compact spec
离线复现时，三条仍都能编译并声明 `needs_live_metadata`。串行在线区分后：Retention 原请求已经被
当前上游接受；两个 Segment preset 仍被 endpoint 拒绝；Property 的 acquisition-ID 分组仍被拒绝。
因此没有证据支持一个统一 wire-shape 修复。

- **#11**：原 `semantic_error` 已不能在当前上游复现，故不能反推 `ae0d449` 时的服务端拒绝原因。
  未改 spec 的当前响应是非空 aggregate，但旧安全投影缺少月桶、累计/周期字段和百分比标量合同，
  于是本地给出 `contract_changed`。Retention 合同升到 v2，只增加固定 aggregate 字段和数值路径，
  不开放 identifier；同一 spec 的最终线上确认是 `success`。
- **#15**：静态 bundle 与现有 request codec 的 `from_user_prop/from_event_prop/FE_CONFIG` 形状一致；
  两个指定 preset 在 live metadata 放行后分别被 Segment endpoint 确定性拒绝。事件“已注册”不等于
  “可用于 Segment 规则”。schema 现在公开 operation-specific `event_support`，把 `$MPShow`、
  `$PayEvent` 标为 unsupported；compact compiler 和 raw field policy 都在网络前给出字段路径与替代动作。
  其他 preset 未由这两次观察推断为支持或不支持，自定义事件继续走 live metadata 和既有执行路径。
  同一轮对 metadata-backed custom event 的正向控制执行成功，证明该预检没有收窄普通事件能力。
- **#17**：原请求失败；只去掉用户过滤仍失败，只去掉 `$ea_gid` group 后成功；把该 group 的物理
  type 改成 `user_re_attribute` 也失败。证据只证明 Property endpoint 不接受当前 acquisition-ID
  grouped cohort，不证明另一种 accepted wire。SDK 因此不猜转换，而是在 compact/raw 两个入口于
  网络前拒绝该 group，字段指向 `group_by[0].field` / `group_by_list[0].field`，下一步是移除它或选用
  metadata-backed 的非 acquisition user property。

横切错误也已修正：manifest semantic rule 命中仍保留 `status=semantic_error`，但改为
`INPUT_INVALID / caller / retryable=false`，CLI/Plan 分类从 exit 3 变为 exit 2。影响所有依赖
`UPSTREAM_UNAVAILABLE`、`category=upstream` 或自动 retry 的既有调用方；它们应停止重试并按 caller
错误处理。真正的 transport/upstream unavailable 仍为 exit 3 且可重试。

本轮实际生产 HTTP read **33 次**：7 次 event metadata、7 次 event-property metadata、8 次
user-property metadata、4 次 retention query、3 次 Segment evaluation、4 次 Property query；
均单次尝试，无 retry、翻页、credential exchange 或旁路请求。输入/响应值和 App ID 均未持久化。
输入能力未减少：Retention 仅扩大安全 aggregate 投影；#15/#17 新拒绝的精确形状已有重复线上失败
证据，从“发出必失败请求”提升为可机械修复的 caller error；其他 Segment event 与 Property group
路径不变。operation 总数仍为 185。

## 失败与降级路径一致性审计（2026-08-15）

本轮以 fake session、stub client 和离线 manifest 覆盖 HTTP 429/5xx/连接故障、认证与权限、坏响应、
明确空、semantic rejection、分页中断/safe-max，以及多组件 partial；生产 HTTP 请求 **0 次**。
矩阵按共享边界选代表格，而不是制造 11 × 24 个重复组合：HTTP/runtime 覆盖所有 Insight、SQL、
composite 和 Plan 列，所有拥有 semantic sanitizer 的产品则逐个检查。修复前新增回归集实际得到
`11 failed, 1 passed`，证明两类缺陷；修复后同一断言全部通过。

- 8 个产品边界仍把 native `INPUT_INVALID` semantic receipt 当作旧
  `UPSTREAM_UNAVAILABLE`：advertiser profile、company usage、custom audience、material
  performance、promotion performance、title package、order directory、order split trace。结果会被
  重写为 contract drift/upstream/exit 3。现统一为 `INPUT_INVALID/caller/retryable=false/exit 2`，
  order 两产品同时给出修正 App/date/domain input 的 caller action。
- credential login/refresh 把最终 HTTP 503、HTTP 429、畸形/截断 JSON 全包装为
  `AuthenticationError/caller/retryable=false/exit 2`。现保留 transport 类型：503 和坏响应为
  `UPSTREAM_UNAVAILABLE`，429 为带 bounded `retry_after_ms` 的 `RATE_LIMITED`，均
  upstream/retryable/exit 3；真正的 credential 缺失、4xx 拒绝和 semantic auth rejection 仍为
  caller/non-retryable/exit 2。业务 429 也把同一 cooldown delay 交给错误 receipt。

按调用方可观察路径，分类错 **11 处 = 8 个 caller→upstream + 3 个 upstream→caller**；按策略族
是 2 类。`retryable` 布尔值错 **3 处**，即登录最终 503、坏响应、429 的 false→true。8 个 semantic
子路径的旧 contract-drift receipt 本来也是 false，所以它们是分类/status/exit 错，不重复计入
retryable 数。跨产品共审出 4 类差异：上述 2 类无合理领域原因，已统一；另 2 类保留——direct read
的 `semantic_error`、产品项的 `error` 与 Plan 聚合的 `partial` 描述不同 envelope 层级，错误身份仍
一致；单组件 page 2 失败不发布不完整 page 1，而 composite 保留已完整成功的独立兄弟，避免用不完整
前缀做分析。

这是两组显式破坏性分类变更。依赖上述 8 个产品 exit 3/upstream 自动重试或可用性告警的 direct
SDK/CLI、Plan、Agent 消费者，应改为按 caller/exit 2 修正字段并停止重试；partial 中已成功兄弟仍可
消费。Insight/SQL 刷新链路的消费者则应停止把 503/429/坏登录响应提示成“换凭据”，改为遵守总重试
预算和 `retry_after_ms`；真正的密码/令牌拒绝仍要求调用方处理。仓库外 `work-dashboard` 的迁移由其
consumer release 执行，本仓库不添加兼容别名或双重 envelope。

没有新增 operation、请求形状、投影、CLI 参数、SDK 方法或分析动线：operation
**185 + 0 - 0 = 185**；本单元在当时台账上的净变化是 `48 + 0 = 48`、`32 / 0 / 16 + 0 / 0 / 0`，
后续 setting route 去重使最终台账成为 **47 = 32 / 0 / 15**。质量 baseline
只删除已改善的 `Transport.request` complexity 16 项，没有放宽任何阈值。既有 composite
result/error/pagination 模型差异继续按技术债裁决保留，不借本轮建立通用错误 DSL。

## 退出码共享分类与门禁（2026-08-15）

**提案：**对 `src/gravity_sdk` 做 AST 全集审计，把 `exit_code` 槽位、本地 category→数字映射与
公共 CLI 直接返回分层计数；错误身份已经存在时一律走共享分类，确属非 `ErrorDetail` 协议状态时只允许
带相邻理由的窄豁免。门禁直接接入现有 quality check，不建立 lint/规则框架。工作底稿位于 ignored
`tmp/codex/exit-code-guard/proposal.md` 与 `audit-ledger.md`。

审计快照上一共 **63 处 = 47 个具名 exit-code AST 上下文 + 16 个公共 CLI 直接返回表达式**。
其中与已注册分类可证明不一致 **1 处**：Analysis Template 目录的聚合结果把所有组件失败固定为
exit 3，但组件可以是 `PAGINATION_LIMIT/caller`。现按组件异常的共享分类聚合；目录因分页/
item 上限中断时从 **exit 3 → exit 2**，调用方应提高文档内的分页或 item 上限后再请求，不应把原请求
当作 upstream 故障退避重试。其余注册错误的数值均与分类一致；SQL/Census 与 onboarding 的若干旧
命令返回没有内嵌 built-in `ErrorCode`，本轮只把数字改由明确共享 category 产生，不猜造错误身份，
对外值不变。

未合并的 Segment Members 不在上述 63 处内，也未修改其分支。合并时 `truncated` 应复用
`PAGINATION_LIMIT`，构造并发布 `ErrorDetail`，由 `exit_code_for_error` 得到 **caller / false /
exit 2**；当前 **exit 3 → exit 2**。原因是调用方给定的 `max_items`/分页预算不足，原样重试必然再次
截断；无需新增 code。测试应同时把 partial 的期望 exit 改为 2，并断言 error code/category。

质量门禁现以 Python AST 检查非零 2/3/4 是否出现在 `exit_code` dict/call/assignment/default、
exit-code helper/constant 或 caller/upstream/local 数字映射中。成功 0、共享函数与普通业务数字不报；
唯一保留的是 replay `capability_gap` 的 caller-selection exit 2，代码旁用
`exit-code-guard: allow - <reason>` 明示理由，空理由本身会失败。因而新分支再写
`3 if truncated else 0` 会在 `python -m gravity_sdk.quality check` 失败，且不进入 ratchet baseline。

`failure-paths` 的 8 个 semantic sanitizer 复核结果为 **8 / 8 均是
`INPUT_INVALID/caller/retryable=false/exit 2`**。advertiser profile、company usage、custom
audience、title package 经 shared composite/batch 分类；Order Directory、Order Split Trace 直接
调用 `exit_code_for_error`。复核发现 shared composite/batch 路径本身仍留一份本地 2/3/4 映射，
Material/Promotion 也各留一份；三处数值虽正确，仍是会与注册表漂移的接缝，合计影响前 6 个产品。
本轮均已改为 `exit_code_for_category`，最终 8 处全部走共享分类，没有同类数字硬编码。

本轮没有新增 operation、请求形状、投影、CLI 参数、SDK 方法或分析动线；operation
**185 + 0 - 0 = 185**，分析动线仍为 **47 + 0 = 47 = 32 / 0 / 15**。生产 HTTP 请求 **0 次**。


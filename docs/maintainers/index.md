# 维护者入口

普通查询不需要阅读本目录。只有修改 SDK、合同、探针、Evidence 或 Census 时进入这里。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 查看、领取、推进或关闭 GitHub Issue | [Issue 状态管理](issues.md) |
| 查看或清理结构性技术债 | [技术债清单](technical-debt.md) |
| 对齐 Agent 错误分类与退出码 | [错误分类对齐](error-classification-alignment.md) |
| 完善 Multidim 的 Agent 产品面 | [Multidim Agent Surface v1](multidim-agent-surface.md) |
| 完善 Business Pulse 的 Agent 交接 | [Business Pulse Agent Surface v1](business-pulse-agent-surface.md) |
| 完善四平台素材表现的 Agent 产品面 | [Material Performance v1](material-performance.md) |
| 完善跨平台推广表现的 Agent 产品面 | [Promotion Performance v1](promotion-performance.md) |
| 一次调用追踪订单拆单明细 | [Order Split Trace v1](order-split-trace.md) |
| 读取单日无标识普通订单目录 | [Order Directory v1](order-directory.md) |
| 阻止自然语言误落原始变现明细 | [Monetization Discovery Guard](monetization-discovery-guard.md) |
| 选择 operation、codec、CLI、recipe、SQL 或 export 扩展面 | [扩展地图](extending.md) |
| 新增、升级或废弃 operation | [新增受控能力](operations.md) |
| 在线探测、浏览器确认页面行为 | [探测安全](probing.md) |
| 发现上游路由或评估漂移 | [路由盘点](census.md) |
| 刷新和发布 Evidence | [Evidence 运行手册](evidence.md) |

先理解 [架构与概念](../architecture.md)，然后只阅读当前任务对应的一页。

## 源码真相

- operation 源合同：`src/gravity_sdk/contracts/operations/`
- 编译后 manifest：`src/gravity_sdk/manifests/`
- 生成 provenance：`src/gravity_sdk/contracts/generated/`
- SQL 产品机器合同：`src/gravity_sdk/contracts/sql-products/`
- Census 数据：`src/gravity_sdk/census/data/`
- operation 探针证据：`evidence/probe/`
- SQL Evidence：当前 workspace 对应的用户私有 `state_root/evidence/`

文档解释流程和边界；schema、默认值、operation 数量与字段列表以当前合同和 CLI 输出为准。

## 调用项目同步门禁

SDK 新增或破坏性调整调用方能力时，发布完成条件包含同一轮更新 `work-dashboard`：

- canonical route 指向唯一当前 CLI/Plan/SDK 入口；
- 可执行 consumer 使用当前 envelope，并对版本、顶层状态和组件状态 fail closed；
- consumer tests 同时覆盖新形状成功、旧形状拒绝和 partial/error/contract drift；
- 冻结历史报告可保留旧命令作为历史事实，现行文档不得把旧 surface 写成兼容方案。

这里取消的是调用方旧 surface，不是上游 operation 治理。精确 operation 可继续由专家通过
`gravity run <operation-id>` 使用；其输入/响应语义仍必须按
[新增受控能力](operations.md)提升合同版本、编译 manifest、审核投影与隐私，并在漂移时 fail closed。
SDK 不为尚未迁移的调用项目保留 CLI alias、隐式 mode 或旧 envelope；调用项目的业务词、App alias
和业务口径仍由调用项目维护。

## 验证节奏

开发内循环先跑受影响的目标测试和确定性检查；不要让纯文档、CLI 文案或局部合同改动每一步
都等待 live probe、Census 或 Evidence。提交前仍运行完整门禁：

```powershell
python -m unittest discover -s tests
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```

如果改动包含在线探针或 Evidence 发布，还必须遵循对应运行手册；普通测试不得访问生产 Gravity。

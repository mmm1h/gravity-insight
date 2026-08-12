# 维护者入口

普通查询不需要阅读本目录。只有修改 SDK、合同、探针、Evidence 或 Census 时进入这里。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 查看、领取、推进或关闭 GitHub Issue | [Issue 状态管理](issues.md) |
| 查看或清理结构性技术债 | [技术债清单](technical-debt.md) |
| 完善 Multidim 的 Agent 产品面 | [Multidim Agent Surface v1](multidim-agent-surface.md) |
| 完善 Business Pulse 的 Agent 交接 | [Business Pulse Agent Surface v1](business-pulse-agent-surface.md) |
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

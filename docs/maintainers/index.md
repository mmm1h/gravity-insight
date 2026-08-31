# 维护者入口

普通查询不需要阅读本目录。只有修改 SDK、合同、探针、Evidence 或 Census 时进入这里；先理解
[架构与概念](../architecture.md)，然后只读当前任务对应的一页。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 领取、推进或关闭 GitHub Issue | [Issue 状态管理](issues.md) |
| 完成发布治理中的人工决策或占位符 | [负责人操作清单](owner-actions.md) |
| 执行或核对发布门禁与供应链证据 | [Release Gate](releasing.md) |
| 查看或清理结构性技术债 | [技术债清单](technical-debt.md) |
| 修改 Gravity Agent Runtime 架构 | [Canonical Architecture](../architecture.md) → [Runtime Component Index](../../specs/agent-runtime/index.md) → 对应机器 Schema/Registry 与 owner reference |
| 定位已交付 composite / CLI / SDK / Plan owner | [产品面总览](product-surfaces.md) |
| 维护变现明细产品与 discovery guard | [Monetization Detail Guard](monetization-discovery-guard.md) |
| 选择 operation、codec、CLI、recipe、SQL 或 export 扩展面 | [扩展地图](extending.md) |
| 新增、升级或废弃 operation | [新增受控能力](operations.md) |
| 在线探测或确认页面行为 | [探测安全](probing.md) |
| 发现上游路由或评估漂移 | [路由盘点](census.md) |
| 规划分页 production/wire 证据 | [分页证据采集计划](pagination-evidence-plan.md) |
| 刷新和发布 Evidence | [Evidence 运行手册](evidence.md) |

## 结论生命周期

1. 提案和请求账本放 `tmp/`，不创建逐趟长期 Markdown。
2. 当前结论原位写入唯一 owner：排期进 roadmap，能力证据进候选矩阵，动线进分析台账，结构债进技术债。
3. 公共行为变化同步更新对应 reference；动态字段、默认值和目录规模不抄进入口页。
4. 历史证据和已替代设计只由 Git 保存，不在 `docs/` 复制归档树。
5. `specs/agent-runtime/` 只保存四字段架构绑定与当前组件索引；草案留在 `tmp/`，施工史由 Git 保存。

## 源码真相

- operation 源合同：`src/gravity_insight/contracts/operations/`
- 编译后 manifest：`src/gravity_insight/manifests/`
- 生成 provenance：`src/gravity_insight/contracts/generated/`
- SQL 产品机器合同：`src/gravity_insight/contracts/sql-products/`
- Census 数据：`src/gravity_insight/census/data/`
- operation 探针证据：`evidence/probe/`
- SQL Evidence：当前 workspace 对应的用户私有 `state_root/evidence/`

文档解释流程和边界；schema、默认值、字段列表和可执行目录以机器合同与 CLI 输出为准。

## 调用项目同步门禁

SDK 新增或破坏性调整调用方能力时，同一发布必须更新 `work-dashboard` canonical consumer：使用唯一
当前入口，校验 envelope 版本及顶层/组件状态，并覆盖新形状成功、旧形状拒绝和
partial/error/contract drift。冻结报告可保留旧命令作为历史事实，现行文档不得把旧 surface 写成兼容方案。

精确 operation 仍可由专家用 `gravity run <operation-id>` 调用，但输入和响应继续服从合同版本、
manifest 编译、投影/隐私审核与 fail-closed 漂移。业务词、App alias 和业务口径由调用项目维护。

## 验证节奏

开发内循环跑受影响的目标测试和确定性检查；提交前运行完整门禁：

```powershell
python -m unittest discover -s tests
python -m pytest -q
python -m gravity_insight.compiler check
python -m gravity_insight.quality check
$env:PYTHONPATH='src'; python scripts/agent_usability_eval.py run --split development --output-dir tmp/agent-usability-gate > tmp/agent-usability-gate.log 2>&1; if ($LASTEXITCODE) { exit $LASTEXITCODE }
python -m gravity_insight --help
git diff --check
```

在线探针或 Evidence 发布还必须遵循对应运行手册；普通测试不得访问生产 Gravity。

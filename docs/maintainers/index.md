# 维护者入口

普通查询不需要阅读本目录。只有修改 SDK、合同、探针、Evidence 或 Census 时进入这里；先理解
[架构与概念](../architecture.md)，然后只读当前任务对应的一页。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
| 领取、推进或关闭 GitHub Issue | [Issue 状态管理](issues.md) |
| 查看或清理结构性技术债 | [技术债清单](technical-debt.md) |
| 定位已交付 composite / CLI / SDK / Plan owner | [产品面总览](product-surfaces.md) |
| 维护变现明细产品与 discovery guard | [Monetization Detail Guard](monetization-discovery-guard.md) |
| 选择 operation、codec、CLI、recipe、SQL 或 export 扩展面 | [扩展地图](extending.md) |
| 新增、升级或废弃 operation | [新增受控能力](operations.md) |
| 在线探测或确认页面行为 | [探测安全](probing.md) |
| 发现上游路由或评估漂移 | [路由盘点](census.md) |
| 刷新和发布 Evidence | [Evidence 运行手册](evidence.md) |
| 复核已交付设计或外部证据 | [历史归档](../archive/index.md) |

## 结论生命周期

1. 提案和请求账本放 `tmp/`，不创建逐趟长期 Markdown。
2. 当前结论原位写入唯一 owner：排期进 roadmap，能力证据进候选矩阵，动线进分析台账，结构债进技术债。
3. 公共行为变化同步更新对应 reference；动态字段、默认值和目录规模不抄进入口页。
4. `docs/archive` 只保存已被替代的历史证据，不作为日常追加日志，也不参与当前接口裁决。

## 源码真相

- operation 源合同：`src/gravity_sdk/contracts/operations/`
- 编译后 manifest：`src/gravity_sdk/manifests/`
- 生成 provenance：`src/gravity_sdk/contracts/generated/`
- SQL 产品机器合同：`src/gravity_sdk/contracts/sql-products/`
- Census 数据：`src/gravity_sdk/census/data/`
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
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
$env:PYTHONPATH='src'; python scripts/agent_usability_eval.py run --split development --output-dir tmp/agent-usability-gate > tmp/agent-usability-gate.log 2>&1; if ($LASTEXITCODE) { exit $LASTEXITCODE }
python -m gravity_sdk --help
git diff --check
```

在线探针或 Evidence 发布还必须遵循对应运行手册；普通测试不得访问生产 Gravity。

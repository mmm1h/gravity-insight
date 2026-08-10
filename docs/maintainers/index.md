# 维护者入口

普通查询不需要阅读本目录。只有修改 SDK、合同、探针、Evidence 或 Census 时进入这里。

## 按任务阅读

| 任务 | 文档 |
| --- | --- |
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
- 探针与发布证据：`evidence/`

文档解释流程和边界；schema、默认值、operation 数量与字段列表以当前合同和 CLI 输出为准。

## 必跑门禁

```powershell
python -m unittest discover -s tests
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
python -m gravity_sdk --help
git diff --check
```

如果改动包含在线探针或 Evidence 发布，还必须遵循对应运行手册；普通测试不得访问生产 Gravity。

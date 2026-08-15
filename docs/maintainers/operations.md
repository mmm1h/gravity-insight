# 新增受控能力

如果还没确定应该新增 operation、codec、CLI 门面、workspace recipe 或 SQL product，先读
[扩展地图](extending.md)。能由合同表达时保持数据化；不要为一个平台或一次业务查询复制
运行时。

## 准入条件

一个候选接口成为 stable operation 前，必须回答：

1. 它是否只读，或是否属于显式治理的 export effect；
2. host、path、method 和请求形状是否已取得可复核证据；
3. 输入字段、分页和错误语义是否明确；
4. 响应字段是否完成 shape 登记、投影和访问边界复核；
5. 是否存在最小、低成本、可重复的 live probe；
6. 是否有脱敏 fixture、合同测试和漂移预期。

缺少任何一项时保留为 draft、blocked 或 permission-unavailable，不得开放裸 HTTP 旁路。

## 修改顺序

```text
路由证据
  → operation 源合同
  → codec / projection（仅在共享模型无法表达时）
  → deterministic compile
  → fixture 与测试
  → offline gates
  → minimum live probe
  → stable
```

### 1. 定义合同

在 `src/gravity_sdk/contracts/operations/` 中登记稳定 operation ID、固定路由、输入、响应、分页、稳定性、隐私和 probe。不要手工编辑编译产物。

### 2. 编译并检查

```powershell
python -m gravity_sdk.compiler check
```

需要生成时使用 compiler 提供的正式命令，然后再次运行 `check`，确保结果确定且 provenance 完整。

### 3. 添加测试

至少覆盖：

- 合法输入和边界值；
- 未声明字段、错误枚举和错误父资源；
- 固定 host/path/method；
- 分页终止和规模上限；
- 响应投影与未登记字段 fail-closed；
- 已登记用户级、设备级和标识符字段原样保留，凭据字段递归剔除；
- 401 单次刷新、限流或上游错误的结构化映射；
- 最小探针使用脱敏 fixture 时的合同一致性。

开发内循环先运行新增 operation 及共享模型的目标测试；不要求每次修改合同都运行整个测试
目录。提升 stable 或准备提交时再运行完整门禁。

### 4. 在线验证

在线 probe 只能在离线门禁通过后执行，并遵循 [探测安全](probing.md)。一次失败不能通过放宽 host、字段或隐私策略解决。

## 兼容性规则

- 上游 v1/v2/v3 路径变化优先保持 operation ID 不变。
- 输入或响应语义发生不兼容变化时提升合同版本，而不是静默修改含义。
- 删除能力时保留 `deprecated` 身份和迁移说明。
- 只新增 operation 合同的改动应尽量保持数据化，避免顺带扩张运行时引擎。

## 完成定义

stable 不是“页面上看到了接口”，而是请求/响应合同、测试和最小线上证据同时成立。最终运行完整门禁，并检查 `git diff` 中没有凭据、生产响应值或临时探针输出。

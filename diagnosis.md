# 用户提问规范（大模型解析前置约束）

为保证 Ability 匹配和外来参数提取稳定，用户提问建议包含以下信息：

1. 问题现象（必须）
   - 例如：锁等待、阻塞链、接口超时、慢请求。
2. 目标对象（建议必须）
   - 例如：数据库 IP、数据库名称、登录用户、服务名称、接口路径。
3. 上下文范围（可选）
   - 例如：最近 10 分钟、生产环境、指定实例。
4. 操作授权（强烈建议）
   - 例如：只诊断不处置 / 允许自动处置。

推荐提问模板：

```text
【现象】...
【对象】...
【范围】...
【授权】只诊断 / 允许处置
【补充】...
```

针对当前 Ability 的最小建议：

1. database_lock_wait
   - 至少包含：锁等待相关关键词 + db_ip + db_name + db_user
   - allow_recovery 未提供时默认 false（仅诊断，不执行处置）
   - 示例：生产库 10.10.20.15 出现锁等待，数据库名称 order_prod，登录用户 diagnosis_user，只诊断不要处置。

2. api_timeout
   - 至少包含：接口超时相关关键词 + service_name
   - 建议补充：api_path + time_range
   - 示例：order-service 出现接口超时，路径 /api/v1/createOrder，最近 10 分钟。

不推荐提问方式：

- 仅描述“系统有问题，帮我看下”（缺少目标对象）
- 在一个问题中混入多个无关故障
- 不声明是否允许处置

---

# 自动化故障诊断能力

大模型先从用户问题中识别问题类型并提取外来参数，再将参数传给 Markdown 解析器。解析器按 Ability 中 Step 的顺序输出本地自动化平台请求。

执行请求采用扁平结构：

```json
{
  "toolType": "orchestration 或 operation",
  "TargetName": "自动化平台中的编排或操作名称",
  "业务参数名": "赋值后的参数"
}
```

规则：

1. `toolType` 只允许 `orchestration`（编排）或 `operation`（操作）。
2. `TargetName` 是本地自动化平台中的真实对象名称，名称应包含问题关键词。
3. `ExternalParameters` 声明解析器可接收的外来参数、别名、默认值和必填约束。
4. 大模型应将用户描述中的参数转换为 `ExternalParameters` 声明的规范参数名；解析器也支持通过 `aliases` 接收原始名称。
5. `Parameters` 是传给自动化平台的业务参数模板。
6. 外来参数使用 `{{external.<参数名>}}` 引用。
7. 用户原始问题使用 `{{user_input}}` 引用。
8. 前序步骤结果传递（本文件实现方式）：
   - 上游 Step 通过 `Output: steps.<Step编号>.result` 声明结果保存位置。
   - 上游 Step 通过 `PassTo` 声明哪些字段会传给后续 Step。
   - 下游 Step 通过 `InputFrom` 声明参数来源。
   - 下游 Step 在 `Parameters` 中用 `{{steps.<Step编号>.result.<字段>}}` 完成赋值。
9. Step 按文档中的编号顺序执行。执行后必须以 Step 编号保存结果，供后续 Step 赋值。
10. 密码、令牌等 `secret: true` 参数可以传递，但不得写入日志。

步骤结果传递示例（Step1 -> Step2）：

```text
Step1.Output = steps.Step1.result
Step1.PassTo = blocking_session_id -> Step2.Parameters.blocking_session_id
Step2.InputFrom = blocking_session_id <- {{steps.Step1.result.blocking_session_id}}
```

外来参数赋值示例：当用户输入“生产库 10.10.20.15 出现锁等待，数据库名称 order_prod，登录用户 diagnosis_user”时，大模型应提取：

```json
{
  "db_ip": "10.10.20.15",
  "db_name": "order_prod",
  "db_user": "diagnosis_user",
  "allow_recovery": false
}
```

解析器生成的第一步请求应为：

```json
{
  "toolType": "orchestration",
  "TargetName": "db_lock_keyword_orchestration",
  "db_ip": "10.10.20.15",
  "db_port": 5432,
  "db_name": "order_prod",
  "db_user": "diagnosis_user",
  "db_password": null,
  "problem_description": "生产库 10.10.20.15 出现锁等待，数据库名称 order_prod，登录用户 diagnosis_user"
}
```

---

# Ability: database_lock_wait
Name: 数据库锁等待诊断与处置
Description: 根据数据库连接信息诊断锁等待；必要时执行阻塞会话处置。
Keywords:
- 数据库锁等待
- 数据库阻塞
- 锁等待
- 阻塞链
- deadlock
Version: 3.0
ExternalParameters:
```json
[
  {
    "name": "db_ip",
    "type": "string",
    "required": true,
    "aliases": ["数据库IP", "数据库ip", "ip", "host"],
    "description": "发生锁等待的数据库IP地址"
  },
  {
    "name": "db_port",
    "type": "integer",
    "required": false,
    "default": 5432,
    "aliases": ["数据库端口", "port"],
    "description": "数据库服务端口"
  },
  {
    "name": "db_name",
    "type": "string",
    "required": true,
    "aliases": ["数据库名称", "数据库名", "database"],
    "description": "发生锁等待的数据库名称"
  },
  {
    "name": "db_user",
    "type": "string",
    "required": true,
    "aliases": ["登录用户", "数据库用户", "username"],
    "description": "登录数据库的用户"
  },
  {
    "name": "db_password",
    "type": "string",
    "required": false,
    "aliases": ["登录密码", "数据库密码", "password"],
    "description": "登录数据库的密码",
    "secret": true
  },
  {
    "name": "allow_recovery",
    "type": "boolean",
    "required": false,
    "default": false,
    "aliases": ["允许处置", "是否处置"],
    "description": "是否允许执行阻塞会话处置；必须获得用户明确授权"
  }
]
```

## Step1
Name: 诊断数据库锁等待
Description: 将外来数据库参数赋值后，调用数据库锁等待诊断编排。
ToolType: orchestration
TargetName: db_lock_keyword_orchestration
Condition: always
Parameters:
```json
{
  "db_ip": "{{external.db_ip}}",
  "db_port": "{{external.db_port}}",
  "db_name": "{{external.db_name}}",
  "db_user": "{{external.db_user}}",
  "db_password": "{{external.db_password}}",
  "problem_description": "{{user_input}}"
}
```
Output: steps.Step1.result
OutputFields:
- blocking_session_id: 阻塞源会话ID
- summary: 诊断摘要
PassTo:
- blocking_session_id -> Step2.Parameters.blocking_session_id
- result -> Step3.Parameters.diagnosis_result
Retry: 2
Timeout: 60
OnError: stop

## Step2
Name: 处置数据库阻塞会话
Description: 用户授权后，使用诊断编排返回的阻塞会话ID执行处置操作。
ToolType: operation
TargetName: db_lock_release_operation
Condition: external.allow_recovery == true and steps.Step1.result.blocking_session_id exists
InputFrom:
- blocking_session_id <- steps.Step1.result.blocking_session_id
Parameters:
```json
{
  "db_ip": "{{external.db_ip}}",
  "db_port": "{{external.db_port}}",
  "db_name": "{{external.db_name}}",
  "db_user": "{{external.db_user}}",
  "db_password": "{{external.db_password}}",
  "blocking_session_id": "{{steps.Step1.result.blocking_session_id}}",
  "operation_reason": "处理数据库锁等待问题：{{user_input}}"
}
```
Output: steps.Step2.result
PassTo:
- result -> Step3.Parameters.recovery_result
Retry: 1
Timeout: 30
OnError: continue

## Step3
Name: 生成数据库锁等待报告
Description: 汇总诊断编排和处置操作的结果，生成最终诊断报告。
ToolType: orchestration
TargetName: db_lock_report_orchestration
Condition: steps.Step1.result exists
InputFrom:
- diagnosis_result <- steps.Step1.result
- recovery_result <- steps.Step2.result
Parameters:
```json
{
  "db_ip": "{{external.db_ip}}",
  "db_name": "{{external.db_name}}",
  "diagnosis_result": "{{steps.Step1.result}}",
  "recovery_result": "{{steps.Step2.result}}",
  "problem_description": "{{user_input}}"
}
```
Output: steps.Step3.result
Retry: 2
Timeout: 60
OnError: stop

---

# Ability: api_timeout
Name: 接口超时诊断
Description: 根据服务和接口信息查询超时样本，再执行原因分析编排。
Keywords:
- 接口超时
- 请求超时
- 网关慢请求
- timeout
Version: 3.0
ExternalParameters:
```json
[
  {
    "name": "service_name",
    "type": "string",
    "required": true,
    "aliases": ["服务名称", "应用名称", "service"],
    "description": "发生接口超时的服务名称"
  },
  {
    "name": "api_path",
    "type": "string",
    "required": false,
    "aliases": ["接口路径", "url", "path"],
    "description": "发生超时的接口路径"
  },
  {
    "name": "time_range",
    "type": "string",
    "required": false,
    "default": "10m",
    "aliases": ["时间范围", "查询时间"],
    "description": "超时样本查询范围"
  }
]
```

## Step1
Name: 查询接口超时样本
Description: 调用自动化平台中的接口超时查询操作。
ToolType: operation
TargetName: api_timeout_query_operation
Condition: always
Parameters:
```json
{
  "service_name": "{{external.service_name}}",
  "api_path": "{{external.api_path}}",
  "time_range": "{{external.time_range}}"
}
```
Output: steps.Step1.result
OutputFields:
- samples: 超时请求样本
- statistics: 超时统计信息
PassTo:
- samples -> Step2.Parameters.timeout_samples
- statistics -> Step2.Parameters.timeout_statistics
Retry: 2
Timeout: 30
OnError: stop

## Step2
Name: 分析接口超时原因
Description: 将超时样本传给自动化平台中的原因分析编排。
ToolType: orchestration
TargetName: api_timeout_analysis_orchestration
Condition: steps.Step1.result exists
InputFrom:
- timeout_samples <- steps.Step1.result.samples
- timeout_statistics <- steps.Step1.result.statistics
Parameters:
```json
{
  "service_name": "{{external.service_name}}",
  "api_path": "{{external.api_path}}",
  "timeout_samples": "{{steps.Step1.result.samples}}",
  "timeout_statistics": "{{steps.Step1.result.statistics}}",
  "problem_description": "{{user_input}}"
}
```
Output: steps.Step2.result
Retry: 2
Timeout: 60
OnError: stop

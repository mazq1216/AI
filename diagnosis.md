# 故障诊断能力定义

本文档由大模型解析。大模型根据用户问题匹配 Ability，并严格按照 Ability 中 Step 的编号顺序生成自动化平台执行请求。

## 解析与执行约定

1. 每个 `Ability` 表示一种完整的故障诊断能力。
2. 大模型使用 Ability 的“问题关键词”匹配用户问题。
3. 每个 Step 只允许调用本地自动化平台的以下一种机制：
   - `编排`：执行自动化平台中已定义的编排。
   - `操作`：执行自动化平台中已定义的操作。
4. “平台对象名称”是自动化平台中的真实名称，名称中必须包含对应的问题关键词。
5. Step 按编号从小到大串行执行。后续 Step 可以引用用户输入、Ability 入参、运行上下文或前序 Step 输出。
6. 所有调用均由执行程序发送给本地自动化平台；本文档不固定接口地址、鉴权信息和公共请求字段。
7. `请求参数模板` 只描述传递给编排或操作的业务参数。执行程序将其放入自动化平台接口约定的参数字段。
8. 变量引用格式：
   - 用户原始问题：`{{user_input}}`
   - Ability 入参：`{{ability.inputs.<参数名>}}`
   - 运行上下文：`{{context.<变量名>}}`
   - Step 输出：`{{steps.<Step编号>.output.<字段路径>}}`
   - 固定值：直接填写，不使用变量表达式。
9. 参数值必须按“传递方式”处理：
   - `直接传递`：保持原值和原数据类型。
   - `字段提取`：从来源对象中按字段路径提取。
   - `模板拼接`：将多个变量按模板组成字符串。
   - `固定值`：使用文档中给出的常量。

---

# Ability: database_lock_wait

## 能力信息

- 能力名称：数据库锁等待诊断与处置
- 功能说明：查询数据库锁等待和阻塞链；当用户允许处置时，终止阻塞源会话；最后生成诊断报告。
- 问题关键词：
  - 数据库锁等待
  - 数据库阻塞
  - 阻塞链
  - deadlock
- 版本：1.0

## Ability 入参

| 参数名 | 类型 | 必填 | 获取方式 | 说明 |
| --- | --- | --- | --- | --- |
| database_name | string | 是 | 从用户问题提取；无法提取时向用户询问 | 数据库名称 |
| instance_id | string | 是 | 从用户问题或运行上下文提取；无法提取时向用户询问 | 数据库实例标识 |
| time_range | string | 否 | 从用户问题提取，默认 `15m` | 查询时间范围 |
| allow_recovery | boolean | 否 | 必须由用户明确授权，默认 `false` | 是否允许执行恢复操作 |

## 执行顺序

`Step1 数据采集编排` → `Step2 阻塞会话处置操作（条件执行）` → `Step3 报告生成编排`

## Step1: 数据库锁等待数据采集

### 自动化平台对象

- 机制：编排
- 平台对象名称：数据库锁等待-阻塞链数据采集编排
- 执行条件：始终执行
- 功能：采集锁等待、阻塞链和相关会话信息。

### 入参与参数传递

| 目标参数 | 类型 | 必填 | 参数来源 | 传递方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| databaseName | string | 是 | `{{ability.inputs.database_name}}` | 直接传递 | 数据库名称 |
| instanceId | string | 是 | `{{ability.inputs.instance_id}}` | 直接传递 | 数据库实例标识 |
| timeRange | string | 否 | `{{ability.inputs.time_range}}` | 直接传递 | 查询时间范围 |
| diagnosisKeyword | string | 是 | `数据库锁等待` | 固定值 | 用于匹配平台内的编排能力 |

### 请求参数模板

```json
{
  "databaseName": "{{ability.inputs.database_name}}",
  "instanceId": "{{ability.inputs.instance_id}}",
  "timeRange": "{{ability.inputs.time_range}}",
  "diagnosisKeyword": "数据库锁等待"
}
```

### 输出约定

- 保存位置：`{{steps.Step1.output}}`
- 必须返回：
  - `blockChain`：阻塞链数组。
  - `rootBlockingSession`：阻塞源会话；不存在时为 `null`。
  - `summary`：数据采集摘要。

### 异常处理

- 超时：60 秒
- 重试：2 次
- 最终失败：终止当前 Ability，并返回 Step1 错误。

## Step2: 数据库阻塞源会话处置

### 自动化平台对象

- 机制：操作
- 平台对象名称：数据库阻塞-终止阻塞源会话操作
- 执行条件：`{{ability.inputs.allow_recovery}}` 为 `true`，且 `{{steps.Step1.output.rootBlockingSession}}` 不为 `null`。
- 条件不满足时：跳过 Step2，并将 `{{steps.Step2.output.status}}` 记录为 `skipped`。
- 功能：终止 Step1 识别出的阻塞源会话。

### 入参与参数传递

| 目标参数 | 类型 | 必填 | 参数来源 | 传递方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| instanceId | string | 是 | `{{ability.inputs.instance_id}}` | 直接传递 | 数据库实例标识 |
| sessionId | string | 是 | `{{steps.Step1.output.rootBlockingSession.sessionId}}` | 字段提取 | 阻塞源会话 ID |
| operatorReason | string | 是 | `处理用户报告的数据库锁等待问题：{{user_input}}` | 模板拼接 | 操作审计原因 |

### 请求参数模板

```json
{
  "instanceId": "{{ability.inputs.instance_id}}",
  "sessionId": "{{steps.Step1.output.rootBlockingSession.sessionId}}",
  "operatorReason": "处理用户报告的数据库锁等待问题：{{user_input}}"
}
```

### 输出约定

- 保存位置：`{{steps.Step2.output}}`
- 必须返回：
  - `status`：`success`、`failed` 或 `skipped`。
  - `operationId`：自动化平台操作记录 ID。
  - `message`：处置结果说明。

### 异常处理

- 超时：30 秒
- 重试：1 次
- 最终失败：记录失败并继续执行 Step3。

## Step3: 数据库锁等待诊断报告生成

### 自动化平台对象

- 机制：编排
- 平台对象名称：数据库锁等待-诊断报告生成编排
- 执行条件：Step1 执行成功。
- 功能：综合采集结果和处置结果生成最终报告。

### 入参与参数传递

| 目标参数 | 类型 | 必填 | 参数来源 | 传递方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| userQuestion | string | 是 | `{{user_input}}` | 直接传递 | 用户原始问题 |
| blockChain | array | 是 | `{{steps.Step1.output.blockChain}}` | 字段提取 | 阻塞链 |
| collectionSummary | string | 是 | `{{steps.Step1.output.summary}}` | 字段提取 | 数据采集摘要 |
| recoveryResult | object | 否 | `{{steps.Step2.output}}` | 直接传递 | Step2 处置结果；Step2 跳过时传入跳过状态 |

### 请求参数模板

```json
{
  "userQuestion": "{{user_input}}",
  "blockChain": "{{steps.Step1.output.blockChain}}",
  "collectionSummary": "{{steps.Step1.output.summary}}",
  "recoveryResult": "{{steps.Step2.output}}"
}
```

### 输出约定

- 保存位置：`{{steps.Step3.output}}`
- 必须返回：
  - `report`：最终诊断报告。
  - `conclusion`：诊断结论。
  - `suggestions`：后续建议数组。

### 异常处理

- 超时：60 秒
- 重试：2 次
- 最终失败：返回 Step1 与 Step2 的原始结果，并说明报告生成失败。

---

# Ability: api_timeout

## 能力信息

- 能力名称：接口超时诊断
- 功能说明：查询接口超时样本，并根据查询结果生成治理建议。
- 问题关键词：
  - 接口超时
  - 请求超时
  - 网关慢请求
  - timeout
- 版本：1.0

## Ability 入参

| 参数名 | 类型 | 必填 | 获取方式 | 说明 |
| --- | --- | --- | --- | --- |
| service_name | string | 是 | 从用户问题提取；无法提取时向用户询问 | 服务名称 |
| api_path | string | 否 | 从用户问题提取 | 接口路径 |
| time_range | string | 否 | 从用户问题提取，默认 `10m` | 查询时间范围 |

## 执行顺序

`Step1 超时查询操作` → `Step2 超时分析编排`

## Step1: 接口超时样本查询

### 自动化平台对象

- 机制：操作
- 平台对象名称：接口超时-请求样本查询操作
- 执行条件：始终执行
- 功能：查询指定服务的接口超时样本。

### 入参与参数传递

| 目标参数 | 类型 | 必填 | 参数来源 | 传递方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| serviceName | string | 是 | `{{ability.inputs.service_name}}` | 直接传递 | 服务名称 |
| apiPath | string | 否 | `{{ability.inputs.api_path}}` | 直接传递 | 接口路径 |
| timeRange | string | 否 | `{{ability.inputs.time_range}}` | 直接传递 | 查询时间范围 |

### 请求参数模板

```json
{
  "serviceName": "{{ability.inputs.service_name}}",
  "apiPath": "{{ability.inputs.api_path}}",
  "timeRange": "{{ability.inputs.time_range}}"
}
```

### 输出约定

- 保存位置：`{{steps.Step1.output}}`
- 必须返回：
  - `samples`：超时请求样本数组。
  - `statistics`：超时统计信息。

### 异常处理

- 超时：30 秒
- 重试：2 次
- 最终失败：终止当前 Ability。

## Step2: 接口超时原因分析

### 自动化平台对象

- 机制：编排
- 平台对象名称：接口超时-原因分析与治理建议编排
- 执行条件：Step1 执行成功。
- 功能：分析超时样本并生成治理建议。

### 入参与参数传递

| 目标参数 | 类型 | 必填 | 参数来源 | 传递方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| userQuestion | string | 是 | `{{user_input}}` | 直接传递 | 用户原始问题 |
| timeoutSamples | array | 是 | `{{steps.Step1.output.samples}}` | 字段提取 | 超时样本 |
| timeoutStatistics | object | 是 | `{{steps.Step1.output.statistics}}` | 字段提取 | 超时统计 |
| targetService | string | 是 | `{{ability.inputs.service_name}}` | 直接传递 | 目标服务 |

### 请求参数模板

```json
{
  "userQuestion": "{{user_input}}",
  "timeoutSamples": "{{steps.Step1.output.samples}}",
  "timeoutStatistics": "{{steps.Step1.output.statistics}}",
  "targetService": "{{ability.inputs.service_name}}"
}
```

### 输出约定

- 保存位置：`{{steps.Step2.output}}`
- 必须返回：
  - `rootCause`：超时根因。
  - `suggestions`：治理建议数组。
  - `report`：完整诊断报告。

### 异常处理

- 超时：60 秒
- 重试：2 次
- 最终失败：返回 Step1 原始数据，并说明分析编排失败。

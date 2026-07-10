# Diagnosis Markdown v2
Description: 面向大模型解析的能力编排配置，统一通过本地自动化平台接口执行。
ExecutionEntry:
- ToolType: orchestration
- ToolType: operation
CommonExecutor:
Type: local_automation_platform_api
Method: POST
Url: http://127.0.0.1:8080/api/automation/execute

LLMParseRule:
- 每个 Ability 由一级标题定义，名称中包含问题关键词。
- 每个 Step 按顺序执行，二级标题顺序即执行顺序。
- Step 仅允许两种 ToolType: orchestration / operation。
- 每个 Step 必须声明 Inputs 与 ParamMapping，说明入参来源和传递方式。
- 变量统一为 {{context_key}} 或 {{stepX.result.xxx}}。

FieldSpec:
- AbilityRequired: Ability, Name, Description, Keywords
- StepRequired: Name, ToolType, TargetName, Inputs, ParamMapping, Output
- ParamSource: user_input | context | step_result | literal
- PassMode: body | query | path | header

# Ability: db_lock_analysis
Name: 数据库锁等待诊断
Description: 先执行锁诊断编排，再调用阻塞会话处置操作，最后输出诊断结果。
Keywords:
- 数据库阻塞
- 锁等待
- deadlock
Version: 2.0
Author: platform-team
Tags:
- database
- lock
- orchestration
- operation

## Step1
Name: 执行数据库锁诊断编排
ToolType: orchestration
TargetName: db_lock_keyword_orchestration
Description:
调用本地自动化平台编排能力，拉取锁等待链路和会话画像。
Inputs:
- param: keyword
  source: user_input
  required: true
- param: database
  source: context
  from: {{database}}
  required: true
- param: time_range
  source: literal
  value: 15m
  required: true
ParamMapping:
- param: keyword
  pass_mode: body
  target_field: request.keyword
- param: database
  pass_mode: body
  target_field: request.database
- param: time_range
  pass_mode: query
  target_field: timeRange
Output:
save_as: step1.result
extract:
- from: data.block_chain
  to: context.block_chain
- from: data.blocked_sessions
  to: context.blocked_sessions
Retry: 3
Timeout: 60
OnError: stop

## Step2
Name: 执行阻塞会话处置操作
ToolType: operation
TargetName: db_kill_block_session_operation
Description:
根据编排结果对阻塞源会话执行自动化处置。
Inputs:
- param: block_chain
  source: step_result
  from: {{step1.result.data.block_chain}}
  required: true
- param: dry_run
  source: context
  from: {{dry_run}}
  required: false
ParamMapping:
- param: block_chain
  pass_mode: body
  target_field: request.blockChain
- param: dry_run
  pass_mode: body
  target_field: request.dryRun
Output:
save_as: step2.result
extract:
- from: data.operation_id
  to: context.operation_id
- from: data.action_result
  to: context.action_result
Retry: 2
Timeout: 45
OnError: continue

## Step3
Name: 执行诊断报告编排
ToolType: orchestration
TargetName: db_lock_report_orchestration
Description:
汇总步骤结果并输出最终诊断报告。
Inputs:
- param: block_chain
  source: context
  from: {{context.block_chain}}
  required: true
- param: action_result
  source: context
  from: {{context.action_result}}
  required: true
- param: current_time
  source: context
  from: {{current_time}}
  required: true
ParamMapping:
- param: block_chain
  pass_mode: body
  target_field: request.blockChain
- param: action_result
  pass_mode: body
  target_field: request.actionResult
- param: current_time
  pass_mode: header
  target_field: X-Current-Time
Output:
save_as: step3.result
extract:
- from: data.report_markdown
  to: context.final_report
Retry: 2
Timeout: 60
OnError: stop

# Ability: api_timeout_diagnosis
Name: 接口超时诊断
Description: 仅使用操作能力完成超时查询和限流动作建议。
Keywords:
- 接口超时
- timeout
- 网关慢请求
Version: 2.0
Author: platform-team
Tags:
- api
- timeout
- operation

## Step1
Name: 执行接口超时检索操作
ToolType: operation
TargetName: api_timeout_query_operation
Description:
按服务名和时间窗获取超时请求样本。
Inputs:
- param: service_name
  source: context
  from: {{service_name}}
  required: true
- param: window
  source: literal
  value: 10m
  required: true
ParamMapping:
- param: service_name
  pass_mode: query
  target_field: serviceName
- param: window
  pass_mode: query
  target_field: timeWindow
Output:
save_as: step1.result
extract:
- from: data.timeout_samples
  to: context.timeout_samples
Retry: 2
Timeout: 30
OnError: retry

## Step2
Name: 执行限流建议操作
ToolType: operation
TargetName: api_rate_limit_suggestion_operation
Description:
根据超时样本生成限流与降级建议。
Inputs:
- param: timeout_samples
  source: context
  from: {{context.timeout_samples}}
  required: true
- param: user_input
  source: user_input
  required: false
ParamMapping:
- param: timeout_samples
  pass_mode: body
  target_field: request.timeoutSamples
- param: user_input
  pass_mode: body
  target_field: request.userQuestion
Output:
save_as: step2.result
extract:
- from: data.suggestion
  to: context.final_report
Retry: 2
Timeout: 40
OnError: continue

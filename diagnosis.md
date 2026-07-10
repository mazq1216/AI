# Ability: gauss_lock
Name: GaussDB锁等待诊断
Description: 用于分析GaussDB锁等待、阻塞链和会话状态。
Version: 1.0
Trigger:
- block
- lock
- deadlock
Author: platform-team
Tags:
- database
- gaussdb
- lock

## Step1
Name: 查询阻塞链
Tool: sql
Description:
查询当前数据库中的阻塞链信息。
SQL:
SELECT pid, usename, wait_event_type, wait_event, query
FROM pg_stat_activity
WHERE datname = '{{database}}';
Output:
step1.result
Retry: 2
Timeout: 30
OnError: retry

## Step2
Name: 生成阻塞分析结论
Tool: llm
System:
你是一名数据库故障诊断专家。
User:
请基于阻塞链结果输出：问题摘要、根因判断、处置建议。
Input:
用户问题: {{user_input}}
阻塞信息: {{step1.result}}
当前时间: {{current_time}}
Output:
step2.result
Retry: 3
Timeout: 60
OnError: retry

## Step3
Name: 输出系统资源快照
Tool: shell
Description:
采集主机CPU和磁盘使用情况。
Command:
top -bn1 && df -h
Output:
step3.result
OnError: continue

# Ability: service_api_diagnosis
Name: 服务接口异常诊断
Description: 用于排查接口高错误率、慢请求与下游依赖异常。
Version: 1.0
Trigger:
- timeout
- error
- api
Author: platform-team
Tags:
- service
- http
- api

## Step1
Name: 调用监控接口获取错误明细
Tool: http
Method: POST
Url:
http://monitor.local/api/v1/errors/query
Body:
{
  "service": "{{service_name}}",
  "timeRange": "15m"
}
Output:
step1.result
Retry: 2
Timeout: 20
OnError: retry

## Step2
Name: 执行本地脚本聚合错误码
Tool: python
Script:
diagnosis.py
Input:
{{step1.result}}
Output:
step2.result
OnError: continue

## Step3
Name: 生成最终诊断报告
Tool: llm
System:
你是一名SRE故障分析专家。
User:
请根据监控数据和聚合结果输出诊断报告，包含：现象、根因、影响面、修复建议。
Input:
监控结果: {{step1.result}}
聚合结果: {{step2.result}}
用户输入: {{user_input}}
Output:
step3.result
Retry: 3
Timeout: 60
OnError: retry

# Markdown 故障诊断执行器

系统分为三层，通过结果对象传递衔接（不要求把平台执行做成命令行工具）：

1. `llm_analyzer.py`：理解用户问题、匹配 Ability、提取外来参数。
2. `markdown_parser.py`：读取 LLM 结果 + `diagnosis.md`，校验参数并生成执行计划。
3. `platform_executor.py`：只负责平台调用；外来参数直接赋值进请求，并在代码中注释参数来源。

大模型不能决定 `ToolType`、`TargetName` 或修改执行步骤；这些可信字段只能来自 `diagnosis.md`。

## 结果传递方式

```python
from pathlib import Path
from llm_analyzer import LLMAnalyzer, OpenAICompatibleChatClient, load_markdown
from markdown_parser import MarkdownParser
from platform_executor import PlatformExecutor
from automation_executor import HttpAutomationExecutor

markdown = load_markdown("diagnosis.md")
question = "10.10.20.15 的 order_prod 数据库出现锁等待，登录用户 diagnosis_user"

# 1) LLM 结果
llm_result = LLMAnalyzer(
    OpenAICompatibleChatClient(endpoint="...", model="...")
).analyze(markdown, question)
# llm_result 含 ability / external_parameters / reasoning

# 2) Parser 计划
plan = MarkdownParser().build_transfer_plan(markdown, {
    **llm_result.__dict__,
    "user_input": question,
})

# 3) 平台调用（无 CLI）：按 plan 直接赋值参数并调用编排/操作
result = PlatformExecutor(
    HttpAutomationExecutor(endpoint="http://127.0.0.1:8080/api/automation/execute")
).execute_plan(plan)
```

## 平台参数赋值说明

`platform_executor.py` 中请求参数直接赋值，来源注释约定：

- `toolType` / `TargetName`：来自 `diagnosis.md`（经 `markdown_parser.py`）
- `db_ip` / `db_name` / `db_user` 等：来自 `llm_analyzer.py` 外来参数提取，经 `markdown_parser.py` 绑定
- `steps.*.result.*`：来自前序平台调用返回值
- 字面量：来自 `diagnosis.md` 固定值

## 测试

```bash
python3 -m unittest -v
```

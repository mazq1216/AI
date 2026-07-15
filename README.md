# Markdown 故障诊断执行器

系统分为三个**可独立运行**的脚本，通过 JSON 结果传递衔接：

1. `llm_analyzer.py`：理解用户问题、匹配 Ability、提取外来参数。
2. `markdown_parser.py`：读取 LLM 结果 + `diagnosis.md`，校验参数并生成执行计划。
3. `platform_executor.py`：按计划顺序调用本地自动化平台的编排/操作。

大模型不能决定 `ToolType`、`TargetName` 或修改执行步骤；这些可信字段只能来自 `diagnosis.md`。

## 独立脚本流水线

```bash
export LLM_ENDPOINT="http://llm.local/v1/chat/completions"
export LLM_MODEL="your-model"
export LLM_API_KEY="optional-key"
export AUTOMATION_ENDPOINT="http://127.0.0.1:8080/api/automation/execute"
export AUTOMATION_TOKEN="optional-token"

# 1) LLM 分析结果写入文件
python3 llm_analyzer.py \
  --markdown diagnosis.md \
  --question "10.10.20.15 的 order_prod 数据库出现锁等待，登录用户 diagnosis_user" \
  --output llm_result.json

# 2) MarkdownParser 消费 LLM 结果，生成平台执行计划
python3 markdown_parser.py \
  --markdown diagnosis.md \
  --llm-result llm_result.json \
  --output plan.json

# 3) 平台执行器消费计划，调用编排/操作
python3 platform_executor.py \
  --plan plan.json \
  --output execution_result.json
```

也可以用管道传递：

```bash
python3 llm_analyzer.py --markdown diagnosis.md --question "..." --output - \
  | python3 markdown_parser.py --markdown diagnosis.md --llm-result - --output - \
  | python3 platform_executor.py --plan - --output execution_result.json
```

## 结果约定

- `llm_result.json`：`ability`、`external_parameters`、`reasoning`、`user_input`
- `plan.json`：绑定后的外来参数 + 有序 `steps`（含 `toolType`/`TargetName`/`parameters`/`condition`）
- `execution_result.json`：每个 Step 的执行状态与平台返回结果

## 测试

```bash
python3 -m unittest -v
```

# Markdown 故障诊断执行器

系统分为三层：

1. `LLMAnalyzer`：理解用户问题、匹配 Ability、提取外来参数。
2. `MarkdownParser`：校验 Ability 和参数、应用默认值、排序 Step、绑定前序结果。
3. `DiagnosisService`：按顺序调用本地自动化平台，并保存每一步结果。

大模型不能决定 `ToolType`、`TargetName` 或修改执行步骤；这些可信字段只能来自 `diagnosis.md`。

## 运行

代码仅使用 Python 标准库，支持 OpenAI 兼容的 Chat Completions 接口。

```bash
export LLM_ENDPOINT="http://llm.local/v1/chat/completions"
export LLM_MODEL="your-model"
export LLM_API_KEY="optional-key"
export AUTOMATION_ENDPOINT="http://127.0.0.1:8080/api/automation/execute"
export AUTOMATION_TOKEN="optional-token"

python3 run_diagnosis.py \
  --question "10.10.20.15 的 order_prod 数据库出现锁等待，登录用户 diagnosis_user"
```

也可以通过同名命令行参数传入接口地址和模型名称。

## 测试

```bash
python3 -m unittest -v
```

## Groovy Markdown 解析脚本（无正则）

新增 `complex_md_parser.groovy`，用于解析复杂 Markdown（标题层级、键值块、多行字段、列表、JSON 代码块），并输出结构化 JSON。

```bash
groovy complex_md_parser.groovy diagnosis.md
```

脚本实现约束：不使用正则表达式 API（如 `Pattern`、`matches`、`replaceAll`）。

## Markdown 转 HTML5（Groovy 2.5.6，分词+AST，无正则）

新增 `markdown_html5_converter.groovy`：

- 使用“分词（lexer）+ AST + 渲染器”实现 Markdown 到 HTML5 的转换。
- 不使用正则表达式。
- 支持源文本里包含字面量 `\n`（会先解码再解析）。
- 支持常见 Markdown 结构：标题、段落、无序/有序列表、引用、围栏代码块、分隔线、表格、行内强调/代码/链接/图片/删除线。

运行：

```bash
groovy markdown_html5_converter.groovy
```

或指定文件：

```bash
groovy markdown_html5_converter.groovy your.md
```

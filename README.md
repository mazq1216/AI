# Markdown diagnosis parser

`markdown_parser.py` 是文档《基于 Markdown 的故障诊断能力编排规范》的
Python 实现，负责将 `diagnosis.md` 解析为类型化的 `Workflow`、`Step` 和
`Prompt` 对象。实现仅使用 Python 标准库。

## 使用方式

```python
from markdown_parser import MarkdownParser

workflows = MarkdownParser("diagnosis.md").parse()
workflow = workflows[0]

print(workflow.ability)
print(workflow.steps[0].tool)
```

也可以直接解析 Markdown 文本：

```python
from markdown_parser import parse

workflows = parse("""
# Ability: disk_full
Name: 磁盘空间诊断
Description: 检查文件系统使用率。

## Step1
Name: 获取磁盘使用率
Tool: shell
Command:
df -h
""")
```

解析器支持：

- Ability 和 Step 的必填字段校验；
- `llm`、`sql`、`shell`、`python`、`http`、`function` 工具；
- Prompt、SQL、Command、HTTP、Script 等多行字段；
- Trigger、Tags 列表；
- Retry、Timeout、OnError 类型及取值校验；
- `{{variable}}` 变量提取；
- 围栏代码块，以及未知扩展字段的保留；
- 重复 Ability、Step 和字段检测。

默认启用严格模式，首个 Ability 前出现非空内容会报错。对于带说明前言的文档，
可使用 `parse(text, strict=False)`。

## 测试

```bash
python -m unittest -v
```

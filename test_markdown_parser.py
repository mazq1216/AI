import tempfile
import unittest
from pathlib import Path

from markdown_parser import (
    MarkdownParser,
    MarkdownSyntaxError,
    MarkdownValidationError,
    parse,
)


DOCUMENT = """\
# Ability: gauss_lock
Name: GaussDB锁等待诊断
Description: 用于分析GaussDB锁等待及阻塞链。
Version: 1.0
Trigger:
- block
- lock
- deadlock
Author: DBA
Tags:
- database
- gaussdb

## Step1
Name: 查询阻塞信息
Tool: sql
Description:
查询数据库当前阻塞链。
SQL:
SELECT *
FROM pg_stat_activity;
Output:
block_info
Retry: 3
Timeout: 30
OnError: retry

## Step2
Name: 分析阻塞信息
Tool: llm
System:
你是一名数据库专家。
User:
分析下面 SQL。
Input:
{{step1.result}}

# Ability: disk_full
Name: 磁盘空间诊断
Description: 检查文件系统使用率。

## CheckDisk
Name: 检查磁盘
Tool: shell
Command:
df -h
"""


class MarkdownParserTests(unittest.TestCase):
    def test_parses_complete_document_and_preserves_order(self):
        workflows = parse(DOCUMENT)

        self.assertEqual(["gauss_lock", "disk_full"], [item.ability for item in workflows])
        workflow = workflows[0]
        self.assertEqual("GaussDB锁等待诊断", workflow.name)
        self.assertEqual(["block", "lock", "deadlock"], workflow.trigger)
        self.assertEqual(["database", "gaussdb"], workflow.tags)
        self.assertEqual(["Step1", "Step2"], [step.id for step in workflow.steps])

        sql_step = workflow.steps[0]
        self.assertEqual("sql", sql_step.tool)
        self.assertEqual("SELECT *\nFROM pg_stat_activity;", sql_step.sql)
        self.assertEqual(3, sql_step.retry)
        self.assertEqual(30.0, sql_step.timeout)
        self.assertEqual("retry", sql_step.on_error)

        llm_step = workflow.steps[1]
        self.assertEqual("你是一名数据库专家。", llm_step.prompt.system)
        self.assertEqual("{{step1.result}}", llm_step.prompt.input)
        self.assertEqual(["step1.result"], [item.name for item in llm_step.variables])
        self.assertEqual(["step1.result"], [item.name for item in llm_step.prompt.variables])

    def test_accepts_path_and_utf8_bom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "diagnosis.md")
            path.write_text("\ufeff" + DOCUMENT, encoding="utf-8")
            workflows = MarkdownParser(path).parse()
        self.assertEqual(2, len(workflows))

    def test_fenced_content_is_not_mistaken_for_structure_or_fields(self):
        document = """\
# Ability: python_check
Name: Python检查
Description: 执行检查
## Step1
Name: 执行脚本
Tool: python
Code:
```python
# Ability: not_an_ability
if value:
    print(value)
```
Script: diagnosis.py
"""
        step = parse(document)[0].steps[0]
        self.assertIn("# Ability: not_an_ability", step.extras["Code"])
        self.assertEqual("diagnosis.py", step.script)

    def test_unknown_fields_are_retained_as_extras(self):
        document = """\
# Ability: custom
Name: 自定义
Description: 自定义字段
OwnerTeam: platform
## Step1
Name: 调用函数
Tool: function
Function: diagnose
"""
        workflow = parse(document)[0]
        self.assertEqual({"OwnerTeam": "platform"}, workflow.extras)
        self.assertEqual({"Function": "diagnose"}, workflow.steps[0].extras)

    def test_rejects_missing_required_fields(self):
        document = """\
# Ability: invalid
Description: no name
## Step1
Name: run
Tool: shell
"""
        with self.assertRaisesRegex(MarkdownValidationError, "Name"):
            parse(document)

    def test_rejects_ability_without_steps(self):
        document = """\
# Ability: invalid
Name: 无步骤
Description: invalid
"""
        with self.assertRaisesRegex(MarkdownValidationError, "at least one Step"):
            parse(document)

    def test_rejects_invalid_tool_and_error_policy(self):
        invalid_tool = """\
# Ability: invalid
Name: 错误
Description: invalid
## Step1
Name: run
Tool: unknown
"""
        with self.assertRaisesRegex(MarkdownValidationError, "unsupported Tool"):
            parse(invalid_tool)

        invalid_policy = invalid_tool.replace("Tool: unknown", "Tool: shell\nOnError: skip")
        with self.assertRaisesRegex(MarkdownValidationError, "invalid OnError"):
            parse(invalid_policy)

    def test_rejects_duplicate_abilities_steps_and_fields(self):
        duplicate_ability = DOCUMENT + """\
# Ability: gauss_lock
Name: 重复
Description: duplicate
## Step1
Name: run
Tool: shell
"""
        with self.assertRaisesRegex(MarkdownValidationError, "duplicate Ability"):
            parse(duplicate_ability)

        duplicate_step = """\
# Ability: duplicate_step
Name: 重复步骤
Description: duplicate
## Step1
Name: first
Tool: shell
## Step1
Name: second
Tool: shell
"""
        with self.assertRaisesRegex(MarkdownValidationError, "duplicate Step"):
            parse(duplicate_step)

        duplicate_field = duplicate_step.replace(
            "Name: first", "Name: first\nName: duplicate"
        )
        with self.assertRaises(MarkdownSyntaxError):
            parse(duplicate_field)

    def test_strict_mode_can_be_disabled_for_preamble(self):
        document = "说明文本\n" + DOCUMENT
        with self.assertRaises(MarkdownSyntaxError):
            parse(document)
        self.assertEqual(2, len(parse(document, strict=False)))

    def test_camel_case_api_aliases(self):
        parser = MarkdownParser()
        variables = parser.parseVariable("{{ user_input }} / {{step1.result}}")
        self.assertEqual(["user_input", "step1.result"], [item.name for item in variables])


if __name__ == "__main__":
    unittest.main()

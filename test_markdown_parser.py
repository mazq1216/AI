import unittest

from markdown_parser import MarkdownParser


SAMPLE = """# Ability: gauss_lock
Name: GaussDB锁等待诊断
Description: 用于分析GaussDB锁等待及阻塞链。
Version: 1.0
Trigger:
- block
- lock
- deadlock
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
FROM pg_stat_activity
WHERE datname = '{{database}}';
Output:
step1.result

## Step2
Name: 生成总结
Tool: llm
System:
你是一名数据库专家。
User:
请总结以下结果：{{step1.result}}
Input:
{{step1.result}}
Retry: 3
Timeout: 30
OnError: retry
"""


class MarkdownParserTests(unittest.TestCase):
    def test_parse_workflow(self) -> None:
        parser = MarkdownParser()
        workflows = parser.parse(SAMPLE)
        self.assertEqual(len(workflows), 1)

        workflow = workflows[0]
        self.assertEqual(workflow.ability, "gauss_lock")
        self.assertEqual(workflow.version, "1.0")
        self.assertEqual(workflow.trigger, ["block", "lock", "deadlock"])
        self.assertEqual(workflow.tags, ["database", "gaussdb"])
        self.assertEqual(len(workflow.steps), 2)

        first = workflow.steps[0]
        self.assertEqual(first.tool, "sql")
        self.assertIn("pg_stat_activity", first.sql or "")
        self.assertIn("database", first.variables())

        second = workflow.steps[1]
        self.assertEqual(second.tool, "llm")
        self.assertIsNotNone(second.prompt)
        self.assertEqual(second.retry, 3)
        self.assertEqual(second.timeout, 30)
        self.assertEqual(second.on_error, "retry")

    def test_parse_variable(self) -> None:
        text = "A={{user_input}} B={{ step1.result }} C={{current_time}}"
        self.assertEqual(
            MarkdownParser.parse_variable(text),
            ["user_input", "step1.result", "current_time"],
        )


if __name__ == "__main__":
    unittest.main()

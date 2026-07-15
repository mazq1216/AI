import unittest
from pathlib import Path

from markdown_parser import MarkdownParser


DIAGNOSIS_PATH = Path(__file__).with_name("diagnosis.md")


class MarkdownParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = MarkdownParser()
        self.markdown = DIAGNOSIS_PATH.read_text(encoding="utf-8")

    def test_parse_v3_ability_and_steps(self) -> None:
        workflows = self.parser.parse(self.markdown)

        self.assertEqual(len(workflows), 2)
        workflow = workflows[0]
        self.assertEqual(workflow.ability, "database_lock_wait")
        self.assertIn("数据库锁等待", workflow.keywords)
        self.assertEqual(len(workflow.external_parameters), 6)
        self.assertEqual(len(workflow.steps), 3)
        self.assertEqual(workflow.steps[0].tool_type, "orchestration")
        self.assertEqual(
            workflow.steps[0].target_name, "db_lock_keyword_orchestration"
        )
        self.assertEqual(workflow.steps[1].tool_type, "operation")

    def test_build_plan_assigns_external_parameters_and_defaults(self) -> None:
        user_input = (
            "生产库10.10.20.15出现锁等待，数据库名称order_prod，"
            "登录用户diagnosis_user，请先诊断。"
        )
        plan = self.parser.build_execution_plan(
            self.markdown,
            user_input,
            {
                "db_ip": "10.10.20.15",
                "db_name": "order_prod",
                "db_user": "diagnosis_user",
            },
        )

        self.assertEqual(
            plan[0],
            {
                "toolType": "orchestration",
                "TargetName": "db_lock_keyword_orchestration",
                "db_ip": "10.10.20.15",
                "db_port": 5432,
                "db_name": "order_prod",
                "db_user": "diagnosis_user",
                "db_password": None,
                "problem_description": user_input,
            },
        )
        self.assertEqual(plan[1]["toolType"], "operation")
        self.assertEqual(
            plan[1]["blocking_session_id"],
            "{{steps.Step1.result.blocking_session_id}}",
        )

    def test_aliases_are_accepted_for_llm_extracted_values(self) -> None:
        plan = self.parser.build_execution_plan(
            self.markdown,
            "数据库出现锁等待",
            {
                "数据库IP": "192.168.1.20",
                "数据库名称": "billing",
                "登录用户": "ops_user",
            },
        )

        self.assertEqual(plan[0]["db_ip"], "192.168.1.20")
        self.assertEqual(plan[0]["db_name"], "billing")
        self.assertEqual(plan[0]["db_user"], "ops_user")

    def test_previous_step_result_can_be_assigned(self) -> None:
        plan = self.parser.build_execution_plan(
            self.markdown,
            "数据库锁等待",
            {
                "db_ip": "10.0.0.8",
                "db_name": "orders",
                "db_user": "diagnosis",
            },
            step_results={
                "Step1": {
                    "result": {
                        "blocking_session_id": "9876",
                        "summary": "found blocker",
                    }
                }
            },
        )

        self.assertEqual(plan[1]["blocking_session_id"], "9876")
        self.assertEqual(plan[2]["diagnosis_result"]["summary"], "found blocker")

    def test_missing_required_external_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError, "Missing required external parameters: db_user"
        ):
            self.parser.build_execution_plan(
                self.markdown,
                "数据库锁等待",
                {"db_ip": "10.0.0.8", "db_name": "orders"},
            )

    def test_parse_key_values_keeps_target_name_and_condition_separate(self) -> None:
        # Reproduces the bug: indented Condition was appended into TargetName
        # as "value\\nCondition: ..." because key matching ignored leading spaces.
        fields = self.parser._parse_key_values(
            [
                "Name: 诊断数据库锁等待",
                "ToolType: orchestration",
                "TargetName: db_lock_keyword_orchestration",
                "  Condition: always",
                "Parameters:",
                "```json",
                "{",
                '  "db_ip": "{{external.db_ip}}",',
                '  "note": "ToolType: must stay inside fence"',
                "}",
                "```",
                "Output: steps.Step1.result",
            ]
        )

        self.assertEqual(fields["TargetName"], "db_lock_keyword_orchestration")
        self.assertEqual(fields["Condition"], "always")
        self.assertNotIn("\n", fields["TargetName"])
        self.assertIn("ToolType: must stay inside fence", fields["Parameters"])
        self.assertEqual(fields["Output"], "steps.Step1.result")


if __name__ == "__main__":
    unittest.main()

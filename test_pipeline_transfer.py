import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Optional

from markdown_parser import MarkdownParser
from platform_executor import PlatformExecutor


MARKDOWN = Path(__file__).with_name("diagnosis.md").read_text(encoding="utf-8")


class FakeAutomationExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], Optional[int]]] = []

    def execute(
        self,
        request_payload: Mapping[str, Any],
        timeout: Optional[int] = None,
    ) -> Any:
        request = dict(request_payload)
        self.calls.append((request, timeout))
        target = request["TargetName"]
        if target == "db_lock_keyword_orchestration":
            return {
                "blocking_session_id": "session-123",
                "summary": "发现阻塞源会话",
            }
        if target == "db_lock_release_operation":
            return {"status": "success", "operation_id": "op-456"}
        if target == "db_lock_report_orchestration":
            return {"report": "诊断完成"}
        raise AssertionError(f"Unexpected target: {target}")


class TransferPipelineTests(unittest.TestCase):
    def test_markdown_parser_builds_plan_from_llm_result_file(self) -> None:
        llm_result = {
            "ability": "database_lock_wait",
            "external_parameters": {
                "db_ip": "10.10.20.15",
                "db_name": "order_prod",
                "db_user": "diagnosis_user",
                "allow_recovery": False,
            },
            "reasoning": "命中数据库锁等待",
            "user_input": "10.10.20.15 order_prod 出现锁等待",
        }

        with tempfile.TemporaryDirectory() as tmp:
            llm_path = Path(tmp) / "llm_result.json"
            plan_path = Path(tmp) / "plan.json"
            llm_path.write_text(
                json.dumps(llm_result, ensure_ascii=False), encoding="utf-8"
            )

            from markdown_parser import main as parser_main

            parser_main(
                [
                    "--markdown",
                    str(Path(__file__).with_name("diagnosis.md")),
                    "--llm-result",
                    str(llm_path),
                    "--output",
                    str(plan_path),
                ]
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))

        self.assertEqual(plan["ability"], "database_lock_wait")
        self.assertEqual(plan["external_parameters"]["db_port"], 5432)
        self.assertEqual(plan["steps"][0]["toolType"], "orchestration")
        self.assertEqual(
            plan["steps"][0]["TargetName"], "db_lock_keyword_orchestration"
        )
        self.assertEqual(plan["steps"][0]["request"]["db_ip"], "10.10.20.15")

    def test_platform_executor_consumes_parser_plan(self) -> None:
        llm_result = {
            "ability": "database_lock_wait",
            "external_parameters": {
                "db_ip": "10.10.20.15",
                "db_name": "order_prod",
                "db_user": "diagnosis_user",
                "allow_recovery": True,
            },
            "user_input": "数据库锁等待，允许处置",
        }
        plan = MarkdownParser().build_transfer_plan(MARKDOWN, llm_result)
        fake = FakeAutomationExecutor()
        result = PlatformExecutor(fake).execute_plan(plan)

        self.assertEqual(
            [step["status"] for step in result["steps"]],
            ["success", "success", "success"],
        )
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(
            fake.calls[1][0]["blocking_session_id"], "session-123"
        )


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from pathlib import Path
from typing import Any, Mapping, Optional

from diagnosis_service import DiagnosisService
from llm_analyzer import LLMAnalyzer
from markdown_parser import MarkdownParser


MARKDOWN = Path(__file__).with_name("diagnosis.md").read_text(encoding="utf-8")


class FakeChatClient:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.system_prompt = ""
        self.user_prompt = ""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.response, ensure_ascii=False)


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


class DiagnosisServiceTests(unittest.TestCase):
    def build_service(
        self, allow_recovery: bool
    ) -> tuple[DiagnosisService, FakeChatClient, FakeAutomationExecutor]:
        chat = FakeChatClient(
            {
                "ability": "database_lock_wait",
                "externalParameters": {
                    "db_ip": "10.10.20.15",
                    "db_name": "order_prod",
                    "db_user": "diagnosis_user",
                    "allow_recovery": allow_recovery,
                },
                "reasoning": "用户问题包含数据库锁等待关键词",
            }
        )
        executor = FakeAutomationExecutor()
        service = DiagnosisService(
            LLMAnalyzer(chat),
            MarkdownParser(),
            executor,
        )
        return service, chat, executor

    def test_llm_matches_and_extracts_but_markdown_controls_execution(self) -> None:
        service, chat, executor = self.build_service(allow_recovery=False)
        question = "10.10.20.15 的 order_prod 数据库出现锁等待"

        result = service.diagnose(MARKDOWN, question)

        self.assertEqual(result.ability, "database_lock_wait")
        self.assertEqual([step.status for step in result.steps], [
            "success",
            "skipped",
            "success",
        ])
        self.assertEqual(len(executor.calls), 2)
        first_request, first_timeout = executor.calls[0]
        self.assertEqual(
            first_request["TargetName"], "db_lock_keyword_orchestration"
        )
        self.assertEqual(first_request["db_ip"], "10.10.20.15")
        self.assertEqual(first_request["db_port"], 5432)
        self.assertEqual(first_request["db_name"], "order_prod")
        self.assertEqual(first_timeout, 60)
        self.assertIn("<diagnosis_markdown>", chat.user_prompt)
        self.assertIn(question, chat.user_prompt)

        report_request, _ = executor.calls[1]
        self.assertEqual(
            report_request["diagnosis_result"]["blocking_session_id"],
            "session-123",
        )
        self.assertEqual(report_request["recovery_result"]["status"], "skipped")

    def test_authorized_operation_receives_previous_step_result(self) -> None:
        service, _, executor = self.build_service(allow_recovery=True)

        result = service.diagnose(MARKDOWN, "数据库锁等待，需要执行处置")

        self.assertEqual([step.status for step in result.steps], [
            "success",
            "success",
            "success",
        ])
        self.assertEqual(len(executor.calls), 3)
        operation_request, operation_timeout = executor.calls[1]
        self.assertEqual(operation_request["toolType"], "operation")
        self.assertEqual(
            operation_request["TargetName"], "db_lock_release_operation"
        )
        self.assertEqual(operation_request["blocking_session_id"], "session-123")
        self.assertEqual(operation_timeout, 30)

        report_request, _ = executor.calls[2]
        self.assertEqual(
            report_request["recovery_result"]["operation_id"], "op-456"
        )

    def test_llm_cannot_select_an_undefined_ability(self) -> None:
        chat = FakeChatClient(
            {
                "ability": "invented_ability",
                "externalParameters": {},
            }
        )
        service = DiagnosisService(
            LLMAnalyzer(chat),
            MarkdownParser(),
            FakeAutomationExecutor(),
        )

        with self.assertRaisesRegex(ValueError, "Ability not found"):
            service.diagnose(MARKDOWN, "数据库锁等待")


if __name__ == "__main__":
    unittest.main()

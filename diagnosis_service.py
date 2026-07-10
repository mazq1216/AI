"""Coordinate LLM analysis, trusted Markdown parsing, and platform execution."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Mapping, Tuple

from automation_executor import AutomationExecutor
from llm_analyzer import LLMAnalyzer
from markdown_parser import MarkdownParser, Step


@dataclass
class StepExecution:
    step_id: str
    tool_type: str
    target_name: str
    status: str
    result: Any = None
    error: str | None = None


@dataclass
class DiagnosisResult:
    ability: str
    reasoning: str | None
    steps: List[StepExecution]


class ConditionEvaluator:
    """Evaluate the deliberately small condition language used by diagnosis.md."""

    def evaluate(self, condition: str, context: Mapping[str, Any]) -> bool:
        expression = condition.strip()
        if not expression or expression.lower() == "always":
            return True
        return all(
            self._evaluate_clause(clause.strip(), context)
            for clause in re.split(r"\s+and\s+", expression, flags=re.IGNORECASE)
        )

    def _evaluate_clause(
        self, clause: str, context: Mapping[str, Any]
    ) -> bool:
        exists_match = re.fullmatch(r"([\w.]+)\s+exists", clause, re.IGNORECASE)
        if exists_match:
            found, value = self._lookup(exists_match.group(1), context)
            return found and value is not None

        bool_match = re.fullmatch(
            r"([\w.]+)\s*==\s*(true|false)", clause, re.IGNORECASE
        )
        if bool_match:
            found, value = self._lookup(bool_match.group(1), context)
            expected = bool_match.group(2).lower() == "true"
            return found and value is expected

        raise ValueError(f"Unsupported Step condition: {clause}")

    def _lookup(
        self, path: str, context: Mapping[str, Any]
    ) -> Tuple[bool, Any]:
        current: Any = context
        for part in path.split("."):
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return False, None
        return True, current


class DiagnosisService:
    """Run the three-stage diagnosis pipeline."""

    def __init__(
        self,
        analyzer: LLMAnalyzer,
        parser: MarkdownParser,
        executor: AutomationExecutor,
    ) -> None:
        self.analyzer = analyzer
        self.parser = parser
        self.executor = executor
        self.condition_evaluator = ConditionEvaluator()

    def diagnose(self, markdown: str, user_input: str) -> DiagnosisResult:
        analysis = self.analyzer.analyze(markdown, user_input)
        workflows = self.parser.parse(markdown)
        workflow = self.parser.select_ability(
            workflows, user_input, ability_name=analysis.ability
        )
        external = self.parser.bind_external_parameters(
            workflow, analysis.external_parameters
        )

        context: Dict[str, Any] = {
            "external": external,
            "user_input": user_input,
            "steps": {},
        }
        executions: List[StepExecution] = []

        for step in workflow.steps:
            if not self.condition_evaluator.evaluate(step.condition, context):
                skipped = {"status": "skipped"}
                context["steps"][step.id] = {"result": skipped}
                executions.append(
                    StepExecution(
                        step_id=step.id,
                        tool_type=step.tool_type,
                        target_name=step.target_name,
                        status="skipped",
                        result=skipped,
                    )
                )
                continue

            execution = self._execute_step(step, context)
            executions.append(execution)
            context["steps"][step.id] = {"result": execution.result}

            if execution.status == "failed" and step.on_error != "continue":
                raise RuntimeError(
                    f"{step.id} ({step.target_name}) failed: {execution.error}"
                )

        return DiagnosisResult(
            ability=workflow.ability,
            reasoning=analysis.reasoning,
            steps=executions,
        )

    def _execute_step(
        self, step: Step, context: Mapping[str, Any]
    ) -> StepExecution:
        attempts = 1 + (step.retry or 0)
        last_error: Exception | None = None
        for _ in range(attempts):
            request = self.parser.build_step_request(step, context)
            unresolved = self.parser.parse_variable(str(request))
            if unresolved:
                raise ValueError(
                    f"{step.id} has unresolved parameters: {', '.join(unresolved)}"
                )
            try:
                result = self.executor.execute(request, timeout=step.timeout)
                return StepExecution(
                    step_id=step.id,
                    tool_type=step.tool_type,
                    target_name=step.target_name,
                    status="success",
                    result=result,
                )
            except Exception as exc:  # executor implementations define error types
                last_error = exc

        return StepExecution(
            step_id=step.id,
            tool_type=step.tool_type,
            target_name=step.target_name,
            status="failed",
            error=str(last_error),
        )

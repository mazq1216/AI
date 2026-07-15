"""Independently execute automation-platform orchestration/operation plans."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

from automation_executor import AutomationExecutor, HttpAutomationExecutor
from markdown_parser import MarkdownParser


@dataclass
class StepExecution:
    step_id: str
    tool_type: str
    target_name: str
    status: str
    request: Optional[Dict[str, Any]] = None
    result: Any = None
    error: Optional[str] = None


class ConditionEvaluator:
    """Evaluate the small Condition language used in transfer plans."""

    def evaluate(self, condition: str, context: Mapping[str, Any]) -> bool:
        expression = (condition or "").strip()
        if not expression or expression.lower() == "always":
            return True
        return all(
            self._evaluate_clause(clause.strip(), context)
            for clause in re.split(r"\s+and\s+", expression, flags=re.IGNORECASE)
        )

    def _evaluate_clause(self, clause: str, context: Mapping[str, Any]) -> bool:
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


class PlatformExecutor:
    """Execute a MarkdownParser transfer plan against the local automation platform."""

    def __init__(self, executor: AutomationExecutor) -> None:
        self.executor = executor
        self.parser = MarkdownParser()
        self.condition_evaluator = ConditionEvaluator()

    def execute_plan(self, plan: Mapping[str, Any]) -> Dict[str, Any]:
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Plan must contain a non-empty steps array")

        context: Dict[str, Any] = {
            "external": dict(plan.get("external_parameters") or {}),
            "user_input": plan.get("user_input") or "",
            "steps": {},
        }
        executions: List[StepExecution] = []

        for raw_step in steps:
            if not isinstance(raw_step, Mapping):
                raise ValueError("Each plan step must be an object")
            execution = self._execute_one_step(raw_step, context)
            executions.append(execution)
            context["steps"][execution.step_id] = {"result": execution.result}

            if execution.status == "failed" and raw_step.get("on_error") != "continue":
                raise RuntimeError(
                    f"{execution.step_id} ({execution.target_name}) failed: "
                    f"{execution.error}"
                )

        return {
            "ability": plan.get("ability"),
            "reasoning": plan.get("reasoning"),
            "user_input": plan.get("user_input"),
            "steps": [asdict(item) for item in executions],
        }

    def _execute_one_step(
        self, step: Mapping[str, Any], context: Mapping[str, Any]
    ) -> StepExecution:
        step_id = str(step.get("id") or "Step")
        tool_type = str(step.get("toolType") or "")
        target_name = str(step.get("TargetName") or "")
        condition = str(step.get("condition") or "always")

        if not self.condition_evaluator.evaluate(condition, context):
            skipped = {"status": "skipped"}
            return StepExecution(
                step_id=step_id,
                tool_type=tool_type,
                target_name=target_name,
                status="skipped",
                result=skipped,
            )

        parameters = step.get("parameters")
        if not isinstance(parameters, Mapping):
            parameters = {}
        request = {
            "toolType": tool_type,
            "TargetName": target_name,
        }
        request.update(self.parser._resolve_value(parameters, context))

        unresolved = self.parser.parse_variable(json.dumps(request, ensure_ascii=False))
        if unresolved:
            raise ValueError(
                f"{step_id} has unresolved parameters: {', '.join(unresolved)}"
            )

        attempts = 1 + int(step.get("retry") or 0)
        timeout = step.get("timeout")
        timeout_value = int(timeout) if timeout is not None else None
        last_error: Optional[Exception] = None

        for _ in range(attempts):
            try:
                result = self.executor.execute(request, timeout=timeout_value)
                return StepExecution(
                    step_id=step_id,
                    tool_type=tool_type,
                    target_name=target_name,
                    status="success",
                    request=request,
                    result=result,
                )
            except Exception as exc:  # platform adapters define their own errors
                last_error = exc

        return StepExecution(
            step_id=step_id,
            tool_type=tool_type,
            target_name=target_name,
            status="failed",
            request=request,
            error=str(last_error),
        )


def load_json_payload(source: str) -> Dict[str, Any]:
    if source == "-":
        text = sys.stdin.read()
    else:
        text = Path(source).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("JSON payload must be an object")
    return data


def write_json(payload: Mapping[str, Any], output: str) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output == "-":
        print(text)
        return
    Path(output).write_text(text + "\n", encoding="utf-8")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently execute a MarkdownParser transfer plan on the "
            "local automation platform"
        )
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="JSON file produced by markdown_parser.py, or '-' for stdin",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Where to write execution result JSON: file path or '-' for stdout",
    )
    parser.add_argument(
        "--automation-endpoint",
        default=os.getenv("AUTOMATION_ENDPOINT"),
        help="Local automation platform execution endpoint",
    )
    parser.add_argument(
        "--automation-token",
        default=os.getenv("AUTOMATION_TOKEN"),
        help="Optional automation platform token",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    args = build_argument_parser().parse_args(argv)
    if not args.automation_endpoint:
        raise SystemExit(
            "Missing configuration: --automation-endpoint/AUTOMATION_ENDPOINT"
        )

    plan = load_json_payload(args.plan)
    executor = PlatformExecutor(
        HttpAutomationExecutor(
            endpoint=args.automation_endpoint,
            token=args.automation_token,
        )
    )
    result = executor.execute_plan(plan)
    write_json(result, args.output)


if __name__ == "__main__":
    main()

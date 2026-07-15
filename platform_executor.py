"""Call local automation-platform orchestration/operation APIs.

This script does not provide CLI/command-line entrypoints.
It receives a plan produced by ``markdown_parser.py`` and directly assigns
business parameters into each platform request.

Parameter sources:
- ``toolType`` / ``TargetName``: from ``diagnosis.md`` via ``markdown_parser.py``
- business fields such as ``db_ip`` / ``db_name``: from ``llm_analyzer.py``
  external-parameter extraction, then bound/validated by ``markdown_parser.py``
- previous-step fields such as ``blocking_session_id``: from earlier platform
  call results stored in the running context
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from automation_executor import AutomationExecutor
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
    """Execute a MarkdownParser transfer plan via platform API calls only."""

    def __init__(self, executor: AutomationExecutor) -> None:
        self.executor = executor
        self.parser = MarkdownParser()
        self.condition_evaluator = ConditionEvaluator()

    def execute_plan(self, plan: Mapping[str, Any]) -> Dict[str, Any]:
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Plan must contain a non-empty steps array")

        # 来源：markdown_parser.py 输出的 plan["external_parameters"]
        # （原始值来自 llm_analyzer.py 的 external_parameters，经 Parser 校验/默认值绑定）
        external_parameters = dict(plan.get("external_parameters") or {})

        # 来源：markdown_parser.py 输出的 plan["user_input"]
        # （通常透传自 llm_analyzer.py 的 user_input）
        user_input = plan.get("user_input") or ""

        context: Dict[str, Any] = {
            "external": external_parameters,
            "user_input": user_input,
            "steps": {},
        }
        executions: List[StepExecution] = []

        for raw_step in steps:
            if not isinstance(raw_step, Mapping):
                raise ValueError("Each plan step must be an object")
            execution = self._execute_one_step(
                raw_step,
                context,
                external_parameters=external_parameters,
                user_input=user_input,
            )
            executions.append(execution)
            # [步骤结果传递-写回]
            # 对应 diagnosis.md:
            #   Output: steps.Step1.result
            # 执行完 Step1 后，把平台返回值写入 context，供 Step2/Step3 读取。
            # 例如：
            #   context["steps"]["Step1"]["result"]["blocking_session_id"]
            # 会被 Step2.Parameters 中的
            #   {{steps.Step1.result.blocking_session_id}}
            # 解析并赋值。
            context["steps"][execution.step_id] = {"result": execution.result}

            if execution.status == "failed" and raw_step.get("on_error") != "continue":
                raise RuntimeError(
                    f"{execution.step_id} ({execution.target_name}) failed: "
                    f"{execution.error}"
                )

        return {
            "ability": plan.get("ability"),
            "reasoning": plan.get("reasoning"),
            "user_input": user_input,
            "steps": [asdict(item) for item in executions],
        }

    def _execute_one_step(
        self,
        step: Mapping[str, Any],
        context: Mapping[str, Any],
        external_parameters: Mapping[str, Any],
        user_input: str,
    ) -> StepExecution:
        # 来源：diagnosis.md -> markdown_parser.py 生成的 plan.steps[*]
        step_id = str(step.get("id") or "Step")
        tool_type = str(step.get("toolType") or "")
        target_name = str(step.get("TargetName") or "")
        condition = str(step.get("condition") or "always")

        if not self.condition_evaluator.evaluate(condition, context):
            # [步骤结果传递-条件判断]
            # 对应 diagnosis.md Step2:
            #   Condition: ... and steps.Step1.result.blocking_session_id exists
            # 若 Step1 尚未产出该字段，则跳过 Step2。
            skipped = {"status": "skipped"}
            return StepExecution(
                step_id=step_id,
                tool_type=tool_type,
                target_name=target_name,
                status="skipped",
                result=skipped,
            )

        # 平台支持直接参数赋值输入：先解析模板，再显式赋值到请求体
        template_parameters = step.get("parameters")
        if not isinstance(template_parameters, Mapping):
            template_parameters = {}
        # [步骤结果传递-参数赋值]
        # 对应 diagnosis.md Step2:
        #   InputFrom:
        #   - blocking_session_id <- steps.Step1.result.blocking_session_id
        #   Parameters:
        #     "blocking_session_id": "{{steps.Step1.result.blocking_session_id}}"
        # _resolve_value 会把上述模板替换为 Step1 平台返回的真实值。
        assigned_parameters = self.parser._resolve_value(template_parameters, context)

        # 直接构造平台调用入参（平台侧接收已赋值参数）
        request: Dict[str, Any] = {
            # 来源：diagnosis.md / markdown_parser.py
            "toolType": tool_type,
            # 来源：diagnosis.md / markdown_parser.py
            "TargetName": target_name,
        }

        # 将业务参数直接赋值进平台请求；值来源见各字段注释
        for key, value in assigned_parameters.items():
            # 来源说明：
            # - external.*     : llm_analyzer.py 提取，经 markdown_parser.py 绑定
            # - user_input     : llm_analyzer.py / markdown_parser.py 透传
            # - steps.*.result : 前序平台调用返回结果（diagnosis.md 的 InputFrom/PassTo）
            # - 字面量         : diagnosis.md 中写死的固定值
            #
            # Step1 -> Step2 示例：
            #   key="blocking_session_id"
            #   value=context["steps"]["Step1"]["result"]["blocking_session_id"]
            request[key] = value

        # 兼容显式外来参数直传：若模板未覆盖，但 external 中存在同名键，则直接赋值
        for key, value in external_parameters.items():
            if key not in request:
                # 来源：llm_analyzer.py -> markdown_parser.py(external_parameters)
                request[key] = value

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
                # 仅做平台调用：把已赋值参数提交给自动化平台
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


def build_platform_request_example() -> Dict[str, Any]:
    """Example of direct parameter assignment for one platform call.

    Values below are placeholders. In real flow they come from:
    - llm_analyzer.py result
    - markdown_parser.py transfer plan
    """
    # 来源：llm_analyzer.py -> markdown_parser.py(external_parameters)
    db_ip = "10.10.20.15"
    # 来源：llm_analyzer.py -> markdown_parser.py(external_parameters)，默认值可能来自 diagnosis.md
    db_port = 5432
    # 来源：llm_analyzer.py -> markdown_parser.py(external_parameters)
    db_name = "order_prod"
    # 来源：llm_analyzer.py -> markdown_parser.py(external_parameters)
    db_user = "diagnosis_user"
    # 来源：llm_analyzer.py 透传的 user_input
    problem_description = "生产库出现锁等待"

    # 来源：diagnosis.md / markdown_parser.py
    tool_type = "orchestration"
    # 来源：diagnosis.md / markdown_parser.py
    target_name = "db_lock_keyword_orchestration"

    # 平台入参：直接赋值，不再走命令行封装
    return {
        "toolType": tool_type,
        "TargetName": target_name,
        "db_ip": db_ip,
        "db_port": db_port,
        "db_name": db_name,
        "db_user": db_user,
        "problem_description": problem_description,
    }

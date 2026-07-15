"""Parse diagnosis abilities and build local automation platform requests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple


VARIABLE_PATTERN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
ABILITY_HEADER_PATTERN = re.compile(r"^#\s+Ability:\s*(?P<name>[\w.-]+)\s*$")
STEP_HEADER_PATTERN = re.compile(r"^##\s+(?P<name>Step[\w.-]*)\s*$", re.IGNORECASE)


@dataclass
class ExternalParameter:
    """A value extracted by the LLM and supplied to the parser."""

    name: str
    type: str = "string"
    required: bool = False
    default: Any = None
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    secret: bool = False


@dataclass
class Step:
    """One ordered automation-platform invocation."""

    id: str
    name: str
    tool_type: str
    target_name: str
    parameters: Dict[str, Any]
    description: Optional[str] = None
    condition: str = "always"
    output: Optional[str] = None
    retry: Optional[int] = None
    timeout: Optional[int] = None
    on_error: Optional[str] = None

    def variables(self) -> List[str]:
        encoded = json.dumps(self.parameters, ensure_ascii=False)
        return MarkdownParser.parse_variable(encoded)


@dataclass
class Workflow:
    """A diagnosis Ability."""

    ability: str
    name: str
    description: str
    keywords: List[str]
    external_parameters: List[ExternalParameter]
    steps: List[Step]
    version: Optional[str] = None

    def validate(self) -> None:
        if not self.name:
            raise ValueError(f"Ability '{self.ability}' missing required field: Name")
        if not self.description:
            raise ValueError(
                f"Ability '{self.ability}' missing required field: Description"
            )
        if not self.keywords:
            raise ValueError(f"Ability '{self.ability}' must define Keywords")
        if not self.steps:
            raise ValueError(f"Ability '{self.ability}' must contain at least one Step")


class MarkdownParser:
    """Parse Markdown and produce directly executable, ordered request payloads."""

    SUPPORTED_TOOL_TYPES = {"orchestration", "operation"}
    SUPPORTED_ON_ERROR = {"stop", "continue", "retry"}
    RESERVED_REQUEST_FIELDS = {"toolType", "TargetName"}
    BOOLEAN_TRUE_VALUES = {"true", "yes", "1", "是", "允许"}
    BOOLEAN_FALSE_VALUES = {"false", "no", "0", "否", "不允许"}

    def parse(self, markdown: str) -> List[Workflow]:
        workflows = [
            self.parse_ability(block)
            for block in self._split_ability_blocks(markdown.splitlines())
        ]
        for workflow in workflows:
            workflow.validate()
        return workflows

    def parse_ability(self, lines: List[str]) -> Workflow:
        match = ABILITY_HEADER_PATTERN.match(lines[0].strip())
        if not match:
            raise ValueError(f"Invalid Ability header: {lines[0]}")

        metadata_lines, step_blocks = self._split_metadata_and_steps(lines[1:])
        fields = self._parse_key_values(metadata_lines)
        steps = [self.parse_step(block) for block in step_blocks]
        steps.sort(key=self._step_sort_key)
        step_ids = [step.id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError(f"Ability '{match.group('name')}' has duplicate Step IDs")
        workflow = Workflow(
            ability=match.group("name"),
            name=self._required(fields, "Name", "Ability"),
            description=self._required(fields, "Description", "Ability"),
            keywords=self._parse_list(fields.get("Keywords", "")),
            external_parameters=self.parse_external_parameters(
                fields.get("ExternalParameters", "[]")
            ),
            version=self._optional(fields, "Version"),
            steps=steps,
        )
        return workflow

    def parse_step(self, lines: List[str]) -> Step:
        match = STEP_HEADER_PATTERN.match(lines[0].strip())
        if not match:
            raise ValueError(f"Invalid Step header: {lines[0]}")

        step_id = match.group("name")
        fields = self._parse_key_values(lines[1:])
        tool_type = self._parse_tool_type(fields, step_id)
        parameters = self.parse_parameters(fields.get("Parameters", "{}"), step_id)
        self._validate_reserved_parameters(step_id, parameters)
        on_error = self._parse_on_error(fields, step_id)

        return Step(
            id=step_id,
            name=self._required(fields, "Name", step_id),
            tool_type=tool_type,
            target_name=self._required(fields, "TargetName", step_id),
            parameters=parameters,
            description=self._optional(fields, "Description"),
            condition=self._optional(fields, "Condition") or "always",
            output=self._optional(fields, "Output"),
            retry=self._optional_int(fields.get("Retry"), "Retry", step_id),
            timeout=self._optional_int(fields.get("Timeout"), "Timeout", step_id),
            on_error=on_error,
        )

    def parse_external_parameters(self, value: str) -> List[ExternalParameter]:
        data = self._parse_json_block(value, "ExternalParameters")
        if not isinstance(data, list):
            raise ValueError("ExternalParameters must be a JSON array")

        parameters: List[ExternalParameter] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("name"):
                raise ValueError(
                    "Each ExternalParameters item must be an object with a name"
                )
            parameters.append(
                ExternalParameter(
                    name=item["name"],
                    type=item.get("type", "string"),
                    required=bool(item.get("required", False)),
                    default=item.get("default"),
                    aliases=list(item.get("aliases", [])),
                    description=item.get("description", ""),
                    secret=bool(item.get("secret", False)),
                )
            )
        return parameters

    def parse_parameters(self, value: str, step_id: str = "Step") -> Dict[str, Any]:
        data = self._parse_json_block(value, f"{step_id} Parameters")
        if not isinstance(data, dict):
            raise ValueError(f"{step_id} Parameters must be a JSON object")
        return data

    def build_execution_plan(
        self,
        markdown: str,
        user_input: str,
        external_parameters: Mapping[str, Any],
        ability_name: Optional[str] = None,
        step_results: Optional[Mapping[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Build ordered, flat requests for the local automation platform.

        External values are assigned immediately. References to previous Step results
        are assigned when ``step_results`` contains them; otherwise their template is
        retained so a sequential executor can resolve it after that Step finishes.
        """
        workflows = self.parse(markdown)
        workflow = self.select_ability(workflows, user_input, ability_name)
        external = self.bind_external_parameters(workflow, external_parameters)
        context = {
            "external": external,
            "user_input": user_input,
            "steps": dict(step_results or {}),
        }

        return [
            self.build_step_request(step, context)
            for step in workflow.steps
        ]

    def build_step_request(
        self, step: Step, context: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Assign current context values to one trusted Step definition."""
        request: Dict[str, Any] = {
            "toolType": step.tool_type,
            "TargetName": step.target_name,
        }
        request.update(self._resolve_value(step.parameters, context))
        return request

    def build_transfer_plan(
        self,
        markdown: str,
        llm_result: Mapping[str, Any],
        user_input: Optional[str] = None,
        step_results: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Combine LLM result with Markdown into a transferable execution plan.

        This is the hand-off payload for a separate platform executor script.
        External parameters are bound immediately. References to later Step
        results remain as ``{{steps...}}`` templates until those results exist.
        """
        ability_name = llm_result.get("ability")
        if not isinstance(ability_name, str) or not ability_name.strip():
            raise ValueError("LLM result must contain a non-empty ability")

        external_raw = (
            llm_result.get("external_parameters")
            if "external_parameters" in llm_result
            else llm_result.get("externalParameters")
        )
        if external_raw is None:
            external_raw = {}
        if not isinstance(external_raw, Mapping):
            raise ValueError("LLM result external parameters must be an object")

        question = user_input or llm_result.get("user_input")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(
                "user_input is required either via --question or LLM result JSON"
            )

        workflows = self.parse(markdown)
        workflow = self.select_ability(
            workflows, question, ability_name=ability_name.strip()
        )
        external = self.bind_external_parameters(workflow, external_raw)
        context = {
            "external": external,
            "user_input": question,
            "steps": dict(step_results or {}),
        }

        steps: List[Dict[str, Any]] = []
        for step in workflow.steps:
            resolved_parameters = self._resolve_value(step.parameters, context)
            steps.append(
                {
                    "id": step.id,
                    "name": step.name,
                    "condition": step.condition,
                    "retry": step.retry,
                    "timeout": step.timeout,
                    "on_error": step.on_error,
                    "toolType": step.tool_type,
                    "TargetName": step.target_name,
                    "parameters": resolved_parameters,
                    "request": self.build_step_request(step, context),
                }
            )

        return {
            "ability": workflow.ability,
            "user_input": question,
            "reasoning": llm_result.get("reasoning"),
            "external_parameters": external,
            "steps": steps,
        }

    def select_ability(
        self,
        workflows: List[Workflow],
        user_input: str,
        ability_name: Optional[str] = None,
    ) -> Workflow:
        if ability_name:
            for workflow in workflows:
                if workflow.ability == ability_name:
                    return workflow
            raise ValueError(f"Ability not found: {ability_name}")

        normalized = user_input.casefold()
        matches = [
            workflow
            for workflow in workflows
            if any(keyword.casefold() in normalized for keyword in workflow.keywords)
        ]
        if not matches:
            raise ValueError("No Ability matched the user input")
        if len(matches) > 1:
            names = ", ".join(workflow.ability for workflow in matches)
            raise ValueError(f"Multiple Abilities matched; specify ability_name: {names}")
        return matches[0]

    def bind_external_parameters(
        self, workflow: Workflow, supplied: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """Normalize canonical names/aliases and validate required external values."""
        accepted_names = {
            name
            for definition in workflow.external_parameters
            for name in [definition.name, *definition.aliases]
        }
        unknown = sorted(set(supplied) - accepted_names)
        if unknown:
            raise ValueError("Unknown external parameters: " + ", ".join(unknown))

        bound: Dict[str, Any] = {}
        missing: List[str] = []
        for definition in workflow.external_parameters:
            value, is_missing = self._bind_one_external_parameter(definition, supplied)
            if is_missing:
                missing.append(definition.name)
            else:
                bound[definition.name] = value

        if missing:
            raise ValueError(
                "Missing required external parameters: " + ", ".join(missing)
            )
        return bound

    def _bind_one_external_parameter(
        self,
        definition: ExternalParameter,
        supplied: Mapping[str, Any],
    ) -> Tuple[Any, bool]:
        for key in [definition.name, *definition.aliases]:
            if key in supplied:
                return self._coerce_parameter(supplied[key], definition), False

        if definition.default is not None:
            return self._coerce_parameter(definition.default, definition), False
        if definition.required:
            return None, True
        return None, False

    def _coerce_parameter(
        self, value: Any, definition: ExternalParameter
    ) -> Any:
        if value is None:
            if definition.required:
                raise ValueError(
                    f"External parameter '{definition.name}' cannot be null"
                )
            return None

        expected = definition.type.lower()
        coercer = self._coercer_for(expected, definition)
        try:
            return coercer(value)
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("Unsupported type"):
                raise
            raise ValueError(
                f"External parameter '{definition.name}' must be "
                f"{definition.type}, got {value!r}"
            ) from exc

    def _coercer_for(self, expected: str, definition: ExternalParameter):
        coercers = {
            "string": self._coerce_string,
            "integer": self._coerce_integer,
            "number": self._coerce_number,
            "boolean": self._coerce_boolean,
            "object": self._coerce_object,
            "array": self._coerce_array,
        }
        if expected not in coercers:
            raise ValueError(
                f"Unsupported type '{definition.type}' for "
                f"external parameter '{definition.name}'"
            )
        return coercers[expected]

    def _coerce_string(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            raise TypeError
        return str(value)

    def _coerce_integer(self, value: Any) -> int:
        if isinstance(value, bool):
            raise TypeError
        return int(value)

    def _coerce_number(self, value: Any) -> float:
        if isinstance(value, bool):
            raise TypeError
        return float(value)

    def _coerce_boolean(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in self.BOOLEAN_TRUE_VALUES:
                return True
            if normalized in self.BOOLEAN_FALSE_VALUES:
                return False
        if value in (0, 1):
            return bool(value)
        raise TypeError

    def _coerce_object(self, value: Any) -> Dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError
        return dict(value)

    def _coerce_array(self, value: Any) -> List[Any]:
        if not isinstance(value, list):
            raise TypeError
        return value

    @staticmethod
    def parse_variable(text: str) -> List[str]:
        return [match.group(1).strip() for match in VARIABLE_PATTERN.finditer(text)]

    def _resolve_value(self, value: Any, context: Mapping[str, Any]) -> Any:
        """把参数模板中的 {{变量}} 替换成 context 里的真实值。

        支持递归解析：
        - dict：对每个 value 再调用本函数
        - list：对每个元素再调用本函数
        - 普通值/字符串：在本层直接处理

        例如输入：
            {
              "db_ip": "{{external.db_ip}}",
              "tags": ["{{external.db_name}}", "lock"]
            }
        会先进入 dict 分支，再对每个字段递归；遇到 list 再继续递归，
        最终把所有可解析变量替换成真实值。
        """
        # ---------- 递归分支 1：字典 ----------
        # 如果当前值是 dict，说明这是一个参数对象（例如 Step.Parameters）。
        # 字典本身不直接替换，而是对每个 value 再调用 _resolve_value。
        # key 保持不变，只解析 value。
        #
        # 递归示意：
        #   {"a": "{{x}}", "b": {"c": "{{y}}"}}
        #     -> 解析 a: "{{x}}"
        #     -> 解析 b: 又是 dict，继续递归解析 c: "{{y}}"
        if isinstance(value, dict):
            return {
                # key：参数名，原样保留
                # item：参数模板值，可能还是 dict/list/str，因此递归调用
                key: self._resolve_value(item, context)
                for key, item in value.items()
            }

        # ---------- 递归分支 2：列表 ----------
        # 如果当前值是 list，说明这是数组型参数。
        # 对每个元素递归解析，保证嵌套模板也能被替换。
        #
        # 递归示意：
        #   ["{{external.db_ip}}", {"name": "{{external.db_name}}"}]
        #     -> 第 1 个元素是字符串，走字符串替换
        #     -> 第 2 个元素是 dict，再进入上面的 dict 递归分支
        if isinstance(value, list):
            return [self._resolve_value(item, context) for item in value]

        # ---------- 终止条件：非字符串叶子节点 ----------
        # 走到这里说明既不是 dict，也不是 list。
        # 若也不是字符串（如 int/bool/None），说明已经是最终值，无需替换，直接返回。
        # 这是递归的重要出口之一，避免无意义继续下钻。
        if not isinstance(value, str):
            return value

        # ---------- 字符串叶子节点：做变量替换 ----------
        # 从这里开始处理字符串模板，不再递归结构，而是解析 {{...}}。

        # 情况 A：整个字符串恰好是一个变量，例如 "{{external.db_port}}"
        # 使用 fullmatch，要求从头到尾完全匹配，不能有额外文字。
        full_match = VARIABLE_PATTERN.fullmatch(value)
        if full_match:
            # group(1) 取出花括号内表达式，如 "external.db_port"
            # strip() 去掉表达式两侧空格，兼容 "{{ external.db_port }}"
            # _lookup 在 context 中按路径查找对应值
            found, resolved = self._lookup(full_match.group(1).strip(), context)
            # 找到则返回原类型值（可能是 int/dict/list），实现“类型保留”
            # 找不到则返回原模板字符串，留给后续步骤结果就绪后再解析
            return resolved if found else value

        # 情况 B：字符串中嵌入一个或多个变量，例如
        # "处理问题：{{user_input}}，库名={{external.db_name}}"
        # 这时不能整段替换为对象，只能把每个变量转成字符串后拼回去。
        def replacement(match: re.Match[str]) -> str:
            # match.group(1) 是当前匹配到的变量表达式
            found, resolved = self._lookup(match.group(1).strip(), context)
            # 找到：转成字符串后参与拼接
            # 找不到：保留原始 "{{...}}" 文本，避免静默丢信息
            return str(resolved) if found else match.group(0)

        # sub 会扫描字符串中所有 {{...}}，并对每个匹配调用 replacement。
        # 最终返回完成变量替换后的字符串。
        return VARIABLE_PATTERN.sub(replacement, value)

    def _parse_tool_type(self, fields: Dict[str, str], step_id: str) -> str:
        tool_type = self._required(fields, "ToolType", step_id).lower()
        if tool_type not in self.SUPPORTED_TOOL_TYPES:
            raise ValueError(
                f"{step_id} ToolType must be orchestration or operation, got: "
                f"{tool_type}"
            )
        return tool_type

    def _validate_reserved_parameters(
        self, step_id: str, parameters: Mapping[str, Any]
    ) -> None:
        reserved = self.RESERVED_REQUEST_FIELDS.intersection(parameters)
        if reserved:
            raise ValueError(
                f"{step_id} Parameters contains reserved fields: {sorted(reserved)}"
            )

    def _parse_on_error(self, fields: Dict[str, str], step_id: str) -> Optional[str]:
        on_error = self._optional(fields, "OnError")
        if on_error and on_error not in self.SUPPORTED_ON_ERROR:
            raise ValueError(f"{step_id} has invalid OnError value: {on_error}")
        return on_error

    def _lookup(
        self, expression: str, context: Mapping[str, Any]
    ) -> Tuple[bool, Any]:
        if expression == "user_input":
            return True, context["user_input"]

        parts = expression.split(".")
        current: Any = context
        for part in parts:
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return False, None
        return True, current

    def _split_ability_blocks(self, lines: List[str]) -> List[List[str]]:
        blocks: List[List[str]] = []
        current: List[str] = []
        for line in lines:
            if ABILITY_HEADER_PATTERN.match(line.strip()):
                if current:
                    blocks.append(current)
                current = [line]
            elif current:
                current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _split_metadata_and_steps(
        self, lines: List[str]
    ) -> Tuple[List[str], List[List[str]]]:
        metadata: List[str] = []
        steps: List[List[str]] = []
        current: List[str] = []
        for line in lines:
            if STEP_HEADER_PATTERN.match(line.strip()):
                if current:
                    steps.append(current)
                current = [line]
            elif current:
                current.append(line)
            else:
                metadata.append(line)
        if current:
            steps.append(current)
        return metadata, steps

    def _step_sort_key(self, step: Step) -> Tuple[int, str]:
        match = re.search(r"\d+", step.id)
        return (int(match.group()) if match else 2**31, step.id)

    def _parse_key_values(self, lines: List[str]) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        key: Optional[str] = None
        buffer: List[str] = []

        def flush() -> None:
            nonlocal key, buffer
            if key is not None:
                fields[key] = "\n".join(buffer).strip()
            key, buffer = None, []

        for raw in lines:
            line = raw.rstrip()
            if line.strip() == "---":
                continue

            # 最小修复：字段可能有缩进，匹配前去掉行首尾空白。
            match = re.match(
                r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$",
                line.strip(),
            )
            if match:
                flush()
                key = match.group(1)
                buffer = [match.group(2)] if match.group(2) else []
            elif key is not None:
                buffer.append(line)

        flush()
        return fields

    def _parse_json_block(self, value: str, field_name: str) -> Any:
        text = value.strip()
        fence = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} contains invalid JSON: {exc.msg}") from exc

    def _parse_list(self, value: str) -> List[str]:
        return [
            line.strip()[1:].strip()
            for line in value.splitlines()
            if line.strip().startswith("-") and line.strip()[1:].strip()
        ]

    def _required(self, fields: Dict[str, str], key: str, scope: str) -> str:
        value = self._optional(fields, key)
        if not value:
            raise ValueError(f"{scope} missing required field: {key}")
        return value

    def _optional(self, fields: Dict[str, str], key: str) -> Optional[str]:
        value = fields.get(key, "").strip()
        return value or None

    def _optional_int(
        self, value: Optional[str], field_name: str, scope: str
    ) -> Optional[int]:
        if not value:
            return None
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{scope} has invalid {field_name}: {value}") from exc


def load_json_payload(source: str) -> Dict[str, Any]:
    """Load JSON from a file path or stdin (``-``)."""
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
            "Independently parse diagnosis Markdown using an LLM analyzer result"
        )
    )
    parser.add_argument(
        "--markdown",
        default="diagnosis.md",
        help="Path to diagnosis Markdown file",
    )
    parser.add_argument(
        "--llm-result",
        required=True,
        help="JSON file produced by llm_analyzer.py, or '-' for stdin",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Optional override for user_input; defaults to LLM result user_input",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Where to write execution plan JSON: file path or '-' for stdout",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry: consume LLM JSON + Markdown -> emit transferable plan JSON."""
    args = build_argument_parser().parse_args(argv)
    markdown = Path(args.markdown).read_text(encoding="utf-8")
    llm_result = load_json_payload(args.llm_result)
    plan = MarkdownParser().build_transfer_plan(
        markdown,
        llm_result,
        user_input=args.question,
    )
    write_json(plan, args.output)


if __name__ == "__main__":
    main()

"""Markdown parser for diagnosis workflow definitions.

The parser follows the conventions described in the uploaded specification:
- Ability sections start with '# Ability: <ability_name>'
- Steps start with '## <step_id>'
- Metadata uses 'Key: Value' form
- List values are declared as bullet items right after 'Trigger:' / 'Tags:'
- Variables are referenced as '{{variable_name}}'
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Tuple


VARIABLE_PATTERN = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")
ABILITY_HEADER_PATTERN = re.compile(r"^#\s+Ability:\s*(?P<ability>[A-Za-z0-9_\-\.]+)\s*$")
STEP_HEADER_PATTERN = re.compile(r"^##\s+(?P<step_id>[A-Za-z0-9_\-\.]+)\s*$")


@dataclass
class Prompt:
    """Prompt definition for llm steps."""

    system: Optional[str] = None
    user: Optional[str] = None
    input: Optional[str] = None

    def variables(self) -> List[str]:
        collected = []
        for value in (self.system, self.user, self.input):
            if value:
                collected.extend(MarkdownParser.parse_variable(value))
        return sorted(set(collected))


@dataclass
class Step:
    """Workflow step definition."""

    id: str
    name: str
    tool: str
    description: Optional[str] = None
    input: Optional[str] = None
    output: Optional[str] = None
    retry: Optional[int] = None
    timeout: Optional[int] = None
    on_error: Optional[str] = None

    # Tool-specific fields
    sql: Optional[str] = None
    command: Optional[str] = None
    script: Optional[str] = None
    method: Optional[str] = None
    url: Optional[str] = None
    body: Optional[str] = None
    prompt: Optional[Prompt] = None

    def variables(self) -> List[str]:
        collected = []
        for value in (
            self.description,
            self.input,
            self.output,
            self.sql,
            self.command,
            self.script,
            self.url,
            self.body,
        ):
            if value:
                collected.extend(MarkdownParser.parse_variable(value))
        if self.prompt:
            collected.extend(self.prompt.variables())
        return sorted(set(collected))


@dataclass
class Workflow:
    """Ability-level workflow object."""

    ability: str
    name: str
    description: str
    version: Optional[str] = None
    trigger: List[str] = field(default_factory=list)
    author: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)

    def validate(self) -> None:
        if not self.ability:
            raise ValueError("Ability is required")
        if not self.name:
            raise ValueError(f"Ability '{self.ability}' missing required field: Name")
        if not self.description:
            raise ValueError(f"Ability '{self.ability}' missing required field: Description")
        if not self.steps:
            raise ValueError(f"Ability '{self.ability}' must contain at least one Step")


class MarkdownParser:
    """Parser that converts diagnosis markdown text to workflow objects."""

    SUPPORTED_TOOLS = {"llm", "sql", "shell", "python", "http", "function"}
    SUPPORTED_ON_ERROR = {"stop", "continue", "retry", "fallback"}

    def parse(self, markdown: str) -> List[Workflow]:
        """Parse markdown text into a list of workflows."""
        lines = markdown.splitlines()
        workflows: List[Workflow] = []
        ability_blocks = self._split_ability_blocks(lines)
        for block in ability_blocks:
            workflow = self.parse_ability(block)
            workflow.validate()
            workflows.append(workflow)
        return workflows

    def parse_ability(self, ability_lines: List[str]) -> Workflow:
        """Parse one ability block."""
        if not ability_lines:
            raise ValueError("Ability block is empty")

        header_match = ABILITY_HEADER_PATTERN.match(ability_lines[0].strip())
        if not header_match:
            raise ValueError(f"Invalid ability header: {ability_lines[0]}")
        ability = header_match.group("ability")

        metadata, step_blocks = self._split_ability_metadata_and_steps(ability_lines[1:])
        meta = self._parse_key_values(metadata)

        name = meta.get("Name", "").strip()
        description = meta.get("Description", "").strip()
        version = self._optional_value(meta, "Version")
        trigger = self._parse_list_field(meta, "Trigger")
        author = self._optional_value(meta, "Author")
        tags = self._parse_list_field(meta, "Tags")

        steps = [self.parse_step(block) for block in step_blocks]
        return Workflow(
            ability=ability,
            name=name,
            description=description,
            version=version,
            trigger=trigger,
            author=author,
            tags=tags,
            steps=steps,
        )

    def parse_step(self, step_lines: List[str]) -> Step:
        """Parse one step block."""
        if not step_lines:
            raise ValueError("Step block is empty")

        header_match = STEP_HEADER_PATTERN.match(step_lines[0].strip())
        if not header_match:
            raise ValueError(f"Invalid step header: {step_lines[0]}")
        step_id = header_match.group("step_id")

        body_fields = self._parse_key_values(step_lines[1:])
        name = self._required_field(body_fields, "Name", f"Step '{step_id}'")
        tool = self._required_field(body_fields, "Tool", f"Step '{step_id}'").lower()
        if tool not in self.SUPPORTED_TOOLS:
            raise ValueError(f"Step '{step_id}' uses unsupported tool: {tool}")

        retry = self._parse_optional_int(body_fields.get("Retry"), "Retry", step_id)
        timeout = self._parse_optional_int(body_fields.get("Timeout"), "Timeout", step_id)
        on_error = self._optional_value(body_fields, "OnError")
        if on_error and on_error not in self.SUPPORTED_ON_ERROR:
            raise ValueError(f"Step '{step_id}' has invalid OnError value: {on_error}")

        step = Step(
            id=step_id,
            name=name,
            tool=tool,
            description=self._optional_value(body_fields, "Description"),
            input=self._optional_value(body_fields, "Input"),
            output=self._optional_value(body_fields, "Output"),
            retry=retry,
            timeout=timeout,
            on_error=on_error,
            sql=self._optional_value(body_fields, "SQL"),
            command=self._optional_value(body_fields, "Command"),
            script=self._optional_value(body_fields, "Script"),
            method=self._optional_value(body_fields, "Method"),
            url=self._optional_value(body_fields, "Url"),
            body=self._optional_value(body_fields, "Body"),
        )

        if tool == "llm":
            step.prompt = self.parse_prompt(body_fields)
        return step

    def parse_prompt(self, fields: Dict[str, str]) -> Prompt:
        """Parse llm prompt fields from a step."""
        return Prompt(
            system=self._optional_value(fields, "System"),
            user=self._optional_value(fields, "User"),
            input=self._optional_value(fields, "Input"),
        )

    @staticmethod
    def parse_variable(text: str) -> List[str]:
        """Extract '{{variable}}' references from text."""
        return [m.group(1).strip() for m in VARIABLE_PATTERN.finditer(text or "")]

    def _split_ability_blocks(self, lines: List[str]) -> List[List[str]]:
        blocks: List[List[str]] = []
        current: List[str] = []
        for line in lines:
            if ABILITY_HEADER_PATTERN.match(line.strip()):
                if current:
                    blocks.append(current)
                current = [line]
                continue
            if current:
                current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _split_ability_metadata_and_steps(
        self, lines: List[str]
    ) -> Tuple[List[str], List[List[str]]]:
        metadata: List[str] = []
        step_blocks: List[List[str]] = []
        current_step: List[str] = []

        for line in lines:
            if STEP_HEADER_PATTERN.match(line.strip()):
                if current_step:
                    step_blocks.append(current_step)
                current_step = [line]
                continue

            if current_step:
                current_step.append(line)
            else:
                metadata.append(line)

        if current_step:
            step_blocks.append(current_step)
        return metadata, step_blocks

    def _parse_key_values(self, lines: List[str]) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        current_key: Optional[str] = None
        buffer: List[str] = []

        def flush() -> None:
            nonlocal current_key, buffer
            if current_key is not None:
                fields[current_key] = "\n".join(buffer).strip()
            current_key = None
            buffer = []

        for raw in lines:
            line = raw.rstrip()
            if not line.strip():
                if current_key is not None:
                    buffer.append("")
                continue

            if re.match(r"^[A-Za-z][A-Za-z0-9_]*\s*:", line):
                flush()
                key, value = line.split(":", 1)
                current_key = key.strip()
                value_text = value.lstrip()
                if value_text:
                    buffer = [value_text]
                else:
                    buffer = []
                continue

            if current_key is not None:
                buffer.append(line)

        flush()
        return fields

    def _optional_value(self, fields: Dict[str, str], key: str) -> Optional[str]:
        value = fields.get(key)
        if value is None:
            return None
        stripped = value.strip()
        return stripped if stripped else None

    def _required_field(self, fields: Dict[str, str], key: str, scope: str) -> str:
        value = self._optional_value(fields, key)
        if not value:
            raise ValueError(f"{scope} missing required field: {key}")
        return value

    def _parse_optional_int(
        self, value: Optional[str], key_name: str, step_id: str
    ) -> Optional[int]:
        if value is None or not value.strip():
            return None
        try:
            return int(value.strip())
        except ValueError as exc:
            raise ValueError(
                f"Step '{step_id}' has invalid integer for {key_name}: {value}"
            ) from exc

    def _parse_list_field(self, fields: Dict[str, str], key: str) -> List[str]:
        raw = fields.get(key, "")
        if not raw.strip():
            return []
        values: List[str] = []
        for line in raw.splitlines():
            striped = line.strip()
            if striped.startswith("-"):
                item = striped[1:].strip()
                if item:
                    values.append(item)
            elif striped:
                # Also allow single-line values without bullets.
                values.append(striped)
        return values

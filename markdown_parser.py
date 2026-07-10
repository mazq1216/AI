"""Parser for the Markdown-based diagnosis workflow format.

The module intentionally has no third-party dependencies.  A parser can be
constructed with a path (or Markdown text), or a source can be passed directly
to :meth:`MarkdownParser.parse`.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


SUPPORTED_TOOLS = frozenset({"llm", "sql", "shell", "python", "http", "function"})
ON_ERROR_POLICIES = frozenset({"stop", "continue", "retry", "fallback"})


class MarkdownParserError(ValueError):
    """Base error raised for an invalid diagnosis Markdown document."""


class MarkdownSyntaxError(MarkdownParserError):
    """Raised when the Markdown structure cannot be parsed."""


class MarkdownValidationError(MarkdownParserError):
    """Raised when a parsed ability or step violates the specification."""


@dataclass(frozen=True)
class Variable:
    """A ``{{variable}}`` reference found in a workflow field."""

    name: str
    expression: str


@dataclass
class Prompt:
    """Prompt configuration for an LLM step."""

    system: str | None = None
    user: str | None = None
    input: str | None = None
    variables: list[Variable] = field(default_factory=list)


@dataclass
class Step:
    """One executable workflow step."""

    id: str
    name: str
    tool: str
    description: str | None = None
    input: str | None = None
    output: str | None = None
    retry: int | None = None
    timeout: float | None = None
    on_error: str | None = None
    prompt: Prompt | None = None
    sql: str | None = None
    command: str | None = None
    method: str | None = None
    url: str | None = None
    body: str | None = None
    script: str | None = None
    extras: dict[str, str] = field(default_factory=dict)
    variables: list[Variable] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


@dataclass
class Workflow:
    """An Ability and its ordered steps."""

    ability: str
    name: str
    description: str
    steps: list[Step]
    version: str | None = None
    trigger: list[str] = field(default_factory=list)
    author: str | None = None
    tags: list[str] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Alias for the unique English ability name."""

        return self.ability

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


# The specification uses both terms for the same object.
Ability = Workflow


@dataclass(frozen=True)
class _Line:
    number: int
    text: str


class MarkdownParser:
    """Parse ``diagnosis.md`` into ordered :class:`Workflow` objects."""

    _ABILITY_HEADING = re.compile(r"^\s*#\s+Ability\s*:\s*(.*?)\s*$", re.IGNORECASE)
    _STEP_HEADING = re.compile(r"^\s*##\s+(.+?)\s*$")
    _FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")
    _VARIABLE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")

    _ABILITY_FIELDS = {
        "name",
        "description",
        "version",
        "trigger",
        "author",
        "tags",
    }
    _STEP_FIELDS = {
        "name",
        "tool",
        "description",
        "input",
        "output",
        "retry",
        "timeout",
        "onerror",
        "system",
        "user",
        "sql",
        "command",
        "method",
        "url",
        "body",
        "script",
    }

    def __init__(self, source: str | os.PathLike[str] | None = None, *, strict: bool = True):
        self.source = source
        self.strict = strict

    def parse(
        self, source: str | os.PathLike[str] | None = None
    ) -> list[Workflow]:
        """Parse a path or Markdown string.

        A string beginning with a Markdown heading or containing a newline is
        treated as document text.  Other strings are treated as file paths.
        """

        selected_source = self.source if source is None else source
        if selected_source is None:
            raise TypeError("parse() requires Markdown text or a file path")

        text = self._read_source(selected_source)
        lines = [_Line(index, line) for index, line in enumerate(text.splitlines(), 1)]
        ability_sections = self._split_abilities(lines)
        if not ability_sections:
            raise MarkdownSyntaxError("no '# Ability: <name>' heading found")

        workflows = [
            self.parse_ability(ability_name, section, heading_line)
            for ability_name, section, heading_line in ability_sections
        ]
        duplicates = self._duplicates(workflow.ability for workflow in workflows)
        if duplicates:
            names = ", ".join(sorted(duplicates))
            raise MarkdownValidationError(f"duplicate Ability name(s): {names}")
        return workflows

    def parse_file(self, path: str | os.PathLike[str]) -> list[Workflow]:
        """Explicitly parse a UTF-8 Markdown file."""

        return self.parse(Path(path))

    def parse_ability(
        self, ability_name: str, lines: list[_Line], heading_line: int = 1
    ) -> Workflow:
        """Parse one Ability section (primarily useful for parser extensions)."""

        if not ability_name.strip():
            raise MarkdownSyntaxError(f"line {heading_line}: Ability name is empty")

        ability_lines: list[_Line] = []
        step_sections: list[tuple[str, list[_Line], int]] = []
        current_step: tuple[str, list[_Line], int] | None = None
        in_fence = False

        for line in lines:
            if self._is_fence(line.text):
                in_fence = not in_fence
            step_match = None if in_fence else self._STEP_HEADING.match(line.text)
            if step_match:
                current_step = (step_match.group(1).strip(), [], line.number)
                step_sections.append(current_step)
            elif current_step is None:
                ability_lines.append(line)
            else:
                current_step[1].append(line)

        ability_fields = self._parse_fields(ability_lines, f"Ability '{ability_name}'")
        required = self._require_fields(
            ability_fields, ("name", "description"), f"Ability '{ability_name}'"
        )
        if not step_sections:
            raise MarkdownValidationError(
                f"line {heading_line}: Ability '{ability_name}' must contain at least one Step"
            )

        steps = [
            self.parse_step(step_id, step_lines, step_line, ability_name)
            for step_id, step_lines, step_line in step_sections
        ]
        duplicate_steps = self._duplicates(step.id for step in steps)
        if duplicate_steps:
            names = ", ".join(sorted(duplicate_steps))
            raise MarkdownValidationError(
                f"Ability '{ability_name}' contains duplicate Step heading(s): {names}"
            )

        return Workflow(
            ability=ability_name.strip(),
            name=required["name"],
            description=required["description"],
            version=self._optional(ability_fields, "version"),
            trigger=self._as_list(ability_fields.get("trigger")),
            author=self._optional(ability_fields, "author"),
            tags=self._as_list(ability_fields.get("tags")),
            steps=steps,
            extras=self._extras(ability_fields, self._ABILITY_FIELDS),
        )

    def parse_step(
        self,
        step_id: str,
        lines: list[_Line],
        heading_line: int = 1,
        ability_name: str = "",
    ) -> Step:
        """Parse one Step section."""

        context = f"Step '{step_id}'"
        if ability_name:
            context += f" in Ability '{ability_name}'"
        fields = self._parse_fields(lines, context)
        required = self._require_fields(fields, ("name", "tool"), context)
        tool = required["tool"].strip().lower()
        if tool not in SUPPORTED_TOOLS:
            supported = ", ".join(sorted(SUPPORTED_TOOLS))
            raise MarkdownValidationError(
                f"line {heading_line}: {context} uses unsupported Tool "
                f"'{required['tool']}' (expected one of: {supported})"
            )

        retry = self._parse_int(fields, "retry", context, minimum=0)
        timeout = self._parse_float(fields, "timeout", context, minimum_exclusive=0)
        on_error = self._optional(fields, "onerror")
        if on_error:
            on_error = on_error.lower()
            if on_error not in ON_ERROR_POLICIES:
                policies = ", ".join(sorted(ON_ERROR_POLICIES))
                raise MarkdownValidationError(
                    f"{context} has invalid OnError '{on_error}' "
                    f"(expected one of: {policies})"
                )

        prompt = self.parse_prompt(fields) if tool == "llm" else None
        variables = self.parse_variable("\n".join(value for _, value, _ in fields.values()))
        return Step(
            id=step_id.strip(),
            name=required["name"],
            tool=tool,
            description=self._optional(fields, "description"),
            input=self._optional(fields, "input"),
            output=self._optional(fields, "output"),
            retry=retry,
            timeout=timeout,
            on_error=on_error,
            prompt=prompt,
            sql=self._optional(fields, "sql"),
            command=self._optional(fields, "command"),
            method=self._optional(fields, "method"),
            url=self._optional(fields, "url"),
            body=self._optional(fields, "body"),
            script=self._optional(fields, "script"),
            extras=self._extras(fields, self._STEP_FIELDS),
            variables=variables,
        )

    def parse_prompt(self, fields: Mapping[str, Any]) -> Prompt:
        """Build an LLM prompt from a normalized or display-name field map."""

        normalized: dict[str, str] = {}
        for key, raw_value in fields.items():
            value = raw_value[1] if isinstance(raw_value, tuple) else raw_value
            normalized[self._normalize_key(key)] = str(value)
        system = self._clean_optional(normalized.get("system"))
        user = self._clean_optional(normalized.get("user"))
        input_value = self._clean_optional(normalized.get("input"))
        variables = self.parse_variable(
            "\n".join(value for value in (system, user, input_value) if value)
        )
        return Prompt(system=system, user=user, input=input_value, variables=variables)

    def parse_variable(self, text: str | None) -> list[Variable]:
        """Extract unique ``{{variable}}`` references in encounter order."""

        if not text:
            return []
        result: list[Variable] = []
        seen: set[str] = set()
        for match in self._VARIABLE.finditer(text):
            name = match.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                result.append(Variable(name=name, expression=match.group(0)))
        return result

    # Camel-case aliases mirror the method names in the source specification.
    parseAbility = parse_ability
    parseStep = parse_step
    parsePrompt = parse_prompt
    parseVariable = parse_variable

    def _read_source(self, source: str | os.PathLike[str]) -> str:
        if isinstance(source, os.PathLike):
            return Path(source).read_text(encoding="utf-8-sig")
        if not isinstance(source, str):
            raise TypeError("source must be Markdown text or a file path")
        stripped = source.lstrip("\ufeff \t")
        if "\n" in source or "\r" in source or stripped.startswith("#"):
            return source.lstrip("\ufeff")
        return Path(source).read_text(encoding="utf-8-sig")

    def _split_abilities(
        self, lines: list[_Line]
    ) -> list[tuple[str, list[_Line], int]]:
        sections: list[tuple[str, list[_Line], int]] = []
        current: tuple[str, list[_Line], int] | None = None
        in_fence = False
        for line in lines:
            if self._is_fence(line.text):
                in_fence = not in_fence
            match = None if in_fence else self._ABILITY_HEADING.match(line.text)
            if match:
                current = (match.group(1).strip(), [], line.number)
                sections.append(current)
            elif current is not None:
                current[1].append(line)
            elif line.text.strip() and self.strict:
                raise MarkdownSyntaxError(
                    f"line {line.number}: content appears before the first Ability"
                )
        if in_fence:
            raise MarkdownSyntaxError("unclosed fenced code block")
        return sections

    def _parse_fields(
        self, lines: list[_Line], context: str
    ) -> dict[str, tuple[str, str, int]]:
        fields: dict[str, tuple[str, str, int]] = {}
        current_key: str | None = None
        current_display = ""
        current_line = 0
        value_lines: list[str] = []
        in_fence = False

        def save() -> None:
            nonlocal value_lines
            if current_key is None:
                return
            value = self._clean_multiline(value_lines)
            fields[current_key] = (current_display, value, current_line)
            value_lines = []

        for line in lines:
            if self._is_fence(line.text):
                in_fence = not in_fence
                if current_key is not None:
                    value_lines.append(line.text)
                continue
            match = None if in_fence else self._FIELD.match(line.text)
            if match:
                save()
                display = match.group(1)
                key = self._normalize_key(display)
                if key in fields:
                    previous_line = fields[key][2]
                    raise MarkdownSyntaxError(
                        f"line {line.number}: duplicate field '{display}' in {context} "
                        f"(first defined on line {previous_line})"
                    )
                current_key = key
                current_display = display
                current_line = line.number
                value_lines = [match.group(2)] if match.group(2) else []
            elif current_key is not None:
                value_lines.append(line.text)
            elif line.text.strip() and self.strict:
                raise MarkdownSyntaxError(
                    f"line {line.number}: expected a 'Field: value' in {context}"
                )
        save()
        if in_fence:
            raise MarkdownSyntaxError(f"unclosed fenced code block in {context}")
        return fields

    @staticmethod
    def _clean_multiline(lines: list[str]) -> str:
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(line.rstrip() for line in lines)

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.replace("_", "").replace("-", "").lower()

    @staticmethod
    def _is_fence(text: str) -> bool:
        return bool(re.match(r"^\s*(`{3,}|~{3,})", text))

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    def _optional(
        self, fields: Mapping[str, tuple[str, str, int]], key: str
    ) -> str | None:
        item = fields.get(key)
        return self._clean_optional(item[1]) if item else None

    def _require_fields(
        self,
        fields: Mapping[str, tuple[str, str, int]],
        keys: Iterable[str],
        context: str,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        missing: list[str] = []
        for key in keys:
            value = self._optional(fields, key)
            if value is None:
                missing.append(key.title())
            else:
                result[key] = value
        if missing:
            raise MarkdownValidationError(
                f"{context} is missing required field(s): {', '.join(missing)}"
            )
        return result

    def _parse_int(
        self,
        fields: Mapping[str, tuple[str, str, int]],
        key: str,
        context: str,
        *,
        minimum: int,
    ) -> int | None:
        value = self._optional(fields, key)
        if value is None:
            return None
        try:
            parsed = int(value)
        except ValueError as exc:
            raise MarkdownValidationError(
                f"{context} field {key.title()} must be an integer, got '{value}'"
            ) from exc
        if parsed < minimum:
            raise MarkdownValidationError(
                f"{context} field {key.title()} must be at least {minimum}"
            )
        return parsed

    def _parse_float(
        self,
        fields: Mapping[str, tuple[str, str, int]],
        key: str,
        context: str,
        *,
        minimum_exclusive: float,
    ) -> float | None:
        value = self._optional(fields, key)
        if value is None:
            return None
        try:
            parsed = float(value)
        except ValueError as exc:
            raise MarkdownValidationError(
                f"{context} field {key.title()} must be numeric, got '{value}'"
            ) from exc
        if parsed <= minimum_exclusive:
            raise MarkdownValidationError(
                f"{context} field {key.title()} must be greater than {minimum_exclusive:g}"
            )
        return parsed

    @staticmethod
    def _as_list(item: tuple[str, str, int] | None) -> list[str]:
        if item is None:
            return []
        value = item[1]
        result: list[str] = []
        for line in value.splitlines():
            cleaned = re.sub(r"^\s*[-*+]\s+", "", line).strip()
            if cleaned:
                result.extend(part.strip() for part in cleaned.split(",") if part.strip())
        return result

    @staticmethod
    def _extras(
        fields: Mapping[str, tuple[str, str, int]], known: set[str]
    ) -> dict[str, str]:
        return {
            display: value
            for key, (display, value, _) in fields.items()
            if key not in known
        }

    @staticmethod
    def _duplicates(values: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        return duplicates


def parse(source: str | os.PathLike[str], *, strict: bool = True) -> list[Workflow]:
    """Convenience function equivalent to ``MarkdownParser(...).parse()``."""

    return MarkdownParser(source, strict=strict).parse()


__all__ = [
    "Ability",
    "MarkdownParser",
    "MarkdownParserError",
    "MarkdownSyntaxError",
    "MarkdownValidationError",
    "ON_ERROR_POLICIES",
    "Prompt",
    "SUPPORTED_TOOLS",
    "Step",
    "Variable",
    "Workflow",
    "parse",
]

"""Command-line entry point for the diagnosis pipeline."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from automation_executor import HttpAutomationExecutor
from diagnosis_service import DiagnosisService
from llm_analyzer import LLMAnalyzer, OpenAICompatibleChatClient
from markdown_parser import MarkdownParser


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Markdown diagnosis Ability")
    parser.add_argument("--question", required=True, help="User problem description")
    parser.add_argument("--markdown", default="diagnosis.md")
    parser.add_argument(
        "--llm-endpoint",
        default=os.getenv("LLM_ENDPOINT"),
        help="OpenAI-compatible chat completions endpoint",
    )
    parser.add_argument("--llm-model", default=os.getenv("LLM_MODEL"))
    parser.add_argument(
        "--automation-endpoint",
        default=os.getenv("AUTOMATION_ENDPOINT"),
        help="Local automation platform execution endpoint",
    )
    return parser


def main() -> None:
    args = build_argument_parser().parse_args()
    missing = [
        name
        for name, value in (
            ("--llm-endpoint/LLM_ENDPOINT", args.llm_endpoint),
            ("--llm-model/LLM_MODEL", args.llm_model),
            ("--automation-endpoint/AUTOMATION_ENDPOINT", args.automation_endpoint),
        )
        if not value
    ]
    if missing:
        raise SystemExit("Missing configuration: " + ", ".join(missing))

    markdown = Path(args.markdown).read_text(encoding="utf-8")
    analyzer = LLMAnalyzer(
        OpenAICompatibleChatClient(
            endpoint=args.llm_endpoint,
            model=args.llm_model,
            api_key=os.getenv("LLM_API_KEY"),
        )
    )
    executor = HttpAutomationExecutor(
        endpoint=args.automation_endpoint,
        token=os.getenv("AUTOMATION_TOKEN"),
    )
    service = DiagnosisService(analyzer, MarkdownParser(), executor)
    result = service.diagnose(markdown, args.question)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

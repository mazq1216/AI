# AGENTS.md

## Cursor Cloud specific instructions

### What this repo is
A pure-Python (stdlib only, Python 3.12) Markdown-driven fault-diagnosis pipeline. There are no third-party dependencies, no package manager, and no build step. Layers: `llm_analyzer.py` (LLM ability matching + external-parameter extraction), `markdown_parser.py` (trusted parsing/validation of `diagnosis.md` into an execution plan), and `platform_executor.py` / `diagnosis_service.py` (execute steps via an automation platform HTTP API). See `README.md` for the design and `diagnosis.md` for the ability definitions.

### Lint / test
- No linter is installed or configured. Use `python3 -m compileall *.py` as the syntax/lint check.
- Tests: `python3 -m unittest -v` (also documented in `README.md`). Tests are fully self-contained and use fakes — no network needed.

### Run the application (end-to-end)
`run_diagnosis.py` is the CLI entrypoint. It requires two external HTTP endpoints that are NOT part of this repo:
- an OpenAI-compatible chat completions endpoint (`--llm-endpoint` / `LLM_ENDPOINT`, plus `--llm-model` / `LLM_MODEL`, optional `LLM_API_KEY`)
- an automation platform execute endpoint (`--automation-endpoint` / `AUTOMATION_ENDPOINT`, optional `AUTOMATION_TOKEN`)

To run/demo the full pipeline without real backends, stand up local mock HTTP servers (stdlib `http.server`): the chat endpoint returns `{"choices":[{"message":{"content": <ability JSON string>}}]}` where the content is a JSON string with keys `ability`, `externalParameters`, `reasoning`; the automation endpoint returns a JSON object keyed by the request's `TargetName`. Then point `--llm-endpoint`/`--automation-endpoint` at them. The `TargetName`s for the `database_lock_wait` ability are `db_lock_keyword_orchestration`, `db_lock_release_operation`, and `db_lock_report_orchestration`.

Note: `Step2` (the release operation) only runs when the extracted `allow_recovery` is `true`; otherwise it is correctly skipped (diagnose-only).

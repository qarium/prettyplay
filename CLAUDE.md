# CLAUDE.md

## Project

prettyplay — a library for UI tests written as plain sentences. Step code is
LLM-generated once against the live page and cached in the repository; later
runs replay the cache with no LLM. Python 3.10+, pydantic v2, playwright,
openai + anthropic SDKs.

## Commands

The project venv lives in `.venv` (not installed globally):

```bash
.venv/bin/pytest tests/ -x                    # full test suite
.venv/bin/pytest tests/<cell>/test_<module>.py -v
.venv/bin/ruff check prettyplay/ tests/       # lint (line-length 120, complexity 10)
.venv/bin/ruff format --check prettyplay/ tests/   # format gate (what CI runs)
```

Both ruff gates must pass. `prettyplay/engine/generator.py` carries a
per-file `E501` ignore because its prompt constants are verbatim contract
texts and must not be rewrapped.

## Structure

Eight cells, each with a facade `__init__.py` (`__all__`) and a read-only
`CODEMANIFEST`:

- `prettyplay/config` — `Config`, `load_config` (pyproject.toml + `PRETTYPLAY_*` env overrides)
- `prettyplay/reporting` — `StepHooks` (no-op hook base), `StepReporter`
- `prettyplay/failures` — `PrettyplayError` + `ProductDefectError` / `IncurableStepError` / `LlmUnavailableError`
- `prettyplay/driver` — `DriverSession`, `PageFacade`, `LocatorFacade` (playwright boundary)
- `prettyplay/cache` — `normalize_step_text`, `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets`
- `prettyplay/llm` — `LlmProvider` port, `OpenAiProvider`, `AnthropicProvider`, `create_provider`, `FailureClassification`
- `prettyplay/engine` — `StepGenerator`, `StepHealer`, `run_step_code`
- `prettyplay` (root) — `PrettyTest`, `PrettyplayRuntime`, `get_runtime`, `StepExecutor`

Tests mirror the layout (`tests/<cell>/test_<module>.py`).

## Rules

- `CODEMANIFEST` files are read-only contracts. When implementation does not
  match the contract, fix the implementation — never the contract.
- Prompt constants (`GENERATION_PROMPT`, `CLASSIFICATION_PROMPT`) are frozen
  verbatim texts; do not reword them.
- `PAGE_API_SURFACE` in `prettyplay/engine/generator.py` mirrors
  `prettyplay/driver/.usages/facade.md` verbatim. Changing the facade surface
  is a conscious extension and requires synchronizing the constant.
- Imports inside the package are relative; no new package boundaries.
- `.usages/*.md` files inside each cell document the domain behavior; keep
  them accurate when behavior changes.

## Conventions

- Docstrings on every module, class and function (Google style with
  Args/Returns/Raises); Cyrillic inline comments are intentional in this
  codebase (test fixtures and domain remarks).
- Tests: contract tests (facade import, exact signatures) and logic tests
  (behavior with stub boundaries); file tests use only `tmp_path`; env is
  manipulated only through `monkeypatch`.
- The runtime is a process-wide singleton (`prettyplay.runtime._runtime`);
  tests reset it via an autouse fixture.

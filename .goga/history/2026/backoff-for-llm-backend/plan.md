# Plan: `backoff-for-llm-backend` — Bounded Transport Backoff for the LLM Port

## Purpose

Implement the bounded transport retry mechanism for every LLM backend request of the
`prettyplay` port: five new entities at `prettyplay/llm/_request.py`
(`TransportFailureClassification`, `classify_openai_failure`, `classify_anthropic_failure`,
`compute_transport_pause`, `send_with_retries`), the `llm_request_attempts` setting in
`prettyplay/config`, provider rewiring (SDK `max_retries=0`, every SDK call wrapped in
`send_with_retries`, per-operation `except OpenAIError`/`except AnthropicError` blocks deleted),
facade exports of the five names, and wording-only docstring alignment in
`prettyplay/failures` and the engine cells.

After implementation: one logical LLM attempt (per engine attempt) resends the identical SDK
request up to the configured budget (default 3 sends, initial included); permanent provider
rejections fail immediately with the cause chained; a Retry-After above 10 seconds terminates
with an actionable `LLMUnavailableError`; every retry emits exactly one WARNING on the
`prettyplay` logger; engine attempt budgets are never consumed by transport retries.

Strategy: leaf cells first (`prettyplay/config`, then `prettyplay/llm` — the core), then the
docstring alignment in `prettyplay/failures` and the engine cells, then the cross-cell
integration test. Every coding task follows the TDD workflow (contract tests → code →
verification → logic tests → debugging → re-verification → lint) and runs its implementation
phase as a REPL cycle (see Mandatory Rules M4).

## Context

### Contract Surface

**Entity: `TransportFailureClassification(category: str, retry_after: float | None)`**
- Type: `class` (Entity, pydantic v2 model)
- Declared `location`: `prettyplay/llm/_request.py`
- Facade obligation: importable from `prettyplay.llm` (new `__all__` entry, D17)
- Properties:
  - `category -> str` — one of the closed nine-label set; retryable family: `connection`,
    `timeout`, `rate_limit`, `server_error`; permanent family: `authentication`,
    `permission_denied`, `invalid_request`, `not_found`, `quota_exhausted`
  - `retry_after -> float | None` — parsed Retry-After seconds; `None` — absent or malformed
  - `retryable -> bool` — whether the category belongs to the retryable family; the
    retry-or-raise decision of the retry loop (a computed `@property`, not a field)
- Semantic requirements: pydantic v2, kw_only, empty defaults (per `conventions`); `category`
  is always one of the nine labels — an unrecognized failure classifies permanent **before**
  reaching this type (the classifiers are the only producers; no pydantic validation of the
  label set)
- Imported dependencies: none (stdlib/pydantic only)

**Routine: `classify_openai_failure(error: Exception) -> failure: TransportFailureClassification`**
- Type: `function` (Routine)
- Declared `location`: `prettyplay/llm/_request.py`
- Facade obligation: importable from `prettyplay.llm`
- Behavior (the CODEMANIFEST algorithm, verbatim):
  1. Match the permanent signals first: an explicitly exhausted quota — even when the status
     looks retryable, e.g. 429 — authentication failure, permission denial, invalid request,
     not found; an explicit permanent cause always wins over a retryable status
  2. Otherwise match the retryable signals: connection failure, timeout, HTTP 408 and 429, any
     HTTP status 500 through 599
  3. Extract Retry-After from the failure response when present and parse it to seconds; a
     missing or malformed value yields None
  4. An exception matching no known signal classifies permanent — a never-recognized failure
     is never blindly retried
- Requirements: pure classification — no I/O, no logging, no state; the label set and the
  permanent-precedence rule mirror `classify_anthropic_failure` exactly (provider parity)
- Constraints: never raise — every input classifies to a verdict

**Routine: `classify_anthropic_failure(error: Exception) -> failure: TransportFailureClassification`**
- Type: `function` (Routine)
- Declared `location`: `prettyplay/llm/_request.py`
- Facade obligation: importable from `prettyplay.llm`
- Behavior: identical algorithm mirrored onto the anthropic exception hierarchy — the same
  nine-label set, the same permanent-precedence rule, the same Retry-After handling; full
  parity with the openai classification
- Requirements/constraints: identical to `classify_openai_failure` (pure, never raises)

**Routine: `compute_transport_pause(failed_attempt: int, retry_after: float | None) -> pause: float`**
- Type: `function` (Routine)
- Declared `location`: `prettyplay/llm/_request.py`
- Facade obligation: importable from `prettyplay.llm`
- Behavior (the CODEMANIFEST algorithm, verbatim):
  1. Base: one second doubled per prior failure, capped at ten — the sequence 1, 2, 4, 8, 10,
     10… seconds
  2. Add a random jitter of 0–25 percent of the base
  3. Cap the result at 10 seconds
  4. A valid retry_after — positive and at most 10 — raises the pause to the indicated wait
     when it exceeds the computed delay
- Requirements: pure function — no I/O, no sleeps; deterministic on the inputs aside from the
  random jitter
- Constraints: a retry_after above 10 seconds never reaches this routine as a wait — the retry
  loop terminates before computing a pause

**Routine: `send_with_retries(provider: str, operation: str, attempts: int, classify: Callable[[Exception], TransportFailureClassification], send: Callable[[], T]) -> response: T`**
- Type: `function` (Routine, generic — `T = TypeVar("T")`, D9)
- Declared `location`: `prettyplay/llm/_request.py`
- Facade obligation: importable from `prettyplay.llm`
- Signature parameters: `provider` — the provider label for logs and errors (`openai`,
  `anthropic`); `operation` — the operation label for logs (`generation`, `classification`,
  `group diagnosis`, `compliance verdict`); `attempts` — the total send budget, initial send
  included (`llm_request_attempts` of `Config`; 1 disables retries); `classify` — the
  provider-specific classifier; `send` — the closure performing exactly one SDK request;
  `response` — the successful response of `send`
- Behavior (the CODEMANIFEST algorithm, verbatim):
  1. Run send; a success returns its response as is
  2. On an exception: classify through `classify` into a `TransportFailureClassification`
  3. A permanent category raises `LLMUnavailableError` naming `provider` with the original
     cause chained — immediately, no retry
  4. A retry_after above 10 seconds raises `LLMUnavailableError` with an actionable message
     naming the provider and the indicated wait — before any pause is computed
  5. The attempt was the last of `attempts`: raise `LLMUnavailableError` naming `provider`
     with the original cause chained
  6. Otherwise compute the pause through `compute_transport_pause`, emit one WARNING record to
     the logger prettyplay — provider, operation, attempt number, error category, delay; never
     secrets, never request or response contents — then wait the pause and run the next attempt
- Requirements: at most `attempts` sends of the identical request — the loop is the only
  retry authority of the port; KeyboardInterrupt during a wait propagates without another
  retry; one WARNING record per retry — no other log records, no hook events
- Constraints: never retry a permanent category; never consult engine attempt budgets — those
  belong to the calling engine
- Imported dependencies: `LLMUnavailableError` from `prettyplay/failures` (already imported in
  `_request.py`); stdlib `logging`/`time`/`random`

**Entity: `Config(... llm_request_attempts: int ...)` (changed)**
- Type: `class` (Entity, pydantic model)
- Declared `location`: `prettyplay/config/models.py`
- Facade obligation: already exported from `prettyplay.config`
- Changed surface: new field `llm_request_attempts: PositiveInt = 3` placed **between**
  `healing_attempts` and `send_screenshots` (contract signature order)
- CODEMANIFEST parameter text (mirrors into the class docstring):
  "`llm_request_attempts`: the total attempt budget of one LLM request — the maximum number of
  physical request sends of one logical LLM attempt of the port (generation, failure
  classification, group diagnosis, compliance verdict alike), the initial request included;
  default 3; 1 — request retries disabled, fully the single-send behavior; the retry delays
  themselves are fixed policy, never configurable; participates in the layered merge like
  every other scalar setting."
- Requirements: a positive integer — a value below 1 fails loudly with the received value
  named; participates in the layered merge of `load_config` like every other scalar setting;
  env name `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` (step-6 env enumeration, decimal integer; an
  unparseable value raises the loud actionable `ConfigurationError` naming the setting, the
  received value and the accepted form)

**Entities: `LLMProvider::OpenAIProvider`, `LLMProvider::AnthropicProvider` (changed)**
- Declared `location`: `prettyplay/llm/openai_provider.py`, `prettyplay/llm/anthropic_provider.py`
- Facade obligation: already exported from `prettyplay.llm`
- Changed behavior (all four operations of both providers):
  - construction of the SDK client with `max_retries=0` (the SDK never resends on its own)
  - the single SDK call of every operation wrapped in `send_with_retries` — provider label
    `openai`/`anthropic`, operation label `generation`/`classification`/`group diagnosis`/
    `compliance verdict`, attempts from `config.llm_request_attempts`, the provider classifier
    as `classify`, exactly one SDK call inside the closure
  - error mapping through the provider classifier (the per-operation
    `except OpenAIError`/`except AnthropicError` → `LLMUnavailableError` blocks are **deleted**)
  - the client is resolved via `self._get_client()` **before** entering the retry loop (D3) —
    the missing-key `LLMUnavailableError` never enters classification
- Unchanged: request builders, `require_completion_text`, the parsers — response-content
  recovery stays in the operations and never enters the retry loop

**Entity: `PrettyplayError::LLMUnavailableError(message: str)` (annotation widened only)**
- Declared `location`: `prettyplay/failures/errors.py`
- No signature, property or method change; the class docstring aligns with the widened
  CODEMANIFEST annotation (see Task 9 for the exact text)

### Re-exports

None — the contract adds no `->Name: {}` embedding blocks. The five new `_request.py` names
become new facade entries of `prettyplay/llm` (D17); the root facade `prettyplay/__init__.py`
stays unchanged (negative assertion: the names are absent from `prettyplay.__all__`).

### Entity Interaction and Data Flow (verbatim from the design)

```
                       engine attempt (generation / healing / diagnosis / verdict)
                                     │ one logical LLM attempt
                                     ▼
        OpenAIProvider / AnthropicProvider  (prettyplay/llm)
        │ construction: SDK client with max_retries=0
        │ 1. build request fields (existing _request.py builders, unchanged)
        │ 2. send_with_retries(provider, operation,
        │        attempts=config.llm_request_attempts,
        │        classify=classify_openai_failure | classify_anthropic_failure,
        │        send=<one SDK call closure>)
        ▼
   ┌───────────────────── send_with_retries (_request.py) ─────────────────────┐
   │  send() ─ ok ───────────────────────────────────────────────► response    │
   │  send() ─ Exception ─► classify(error) ─► TransportFailureClassification  │
   │     ├─ permanent category ─────────────► LLMUnavailableError (chained)    │
   │     ├─ retry_after > 10 s ─────────────► LLMUnavailableError (actionable) │
   │     ├─ attempt == attempts ────────────► LLMUnavailableError (chained)    │
   │     └─ else: compute_transport_pause(attempt, retry_after)               │
   │              WARNING → logger "prettyplay"; time.sleep(pause); next send  │
   └───────────────────────────────────────────────────────────────────────────┘
        │ success                                  │ LLMUnavailableError
        ▼                                          ▼
  parse/validate answer                      engine propagation (unchanged):
  (extract_code_block, parse_*                generate/heal/diagnose → terminal;
  — outside the retry loop)                  classification → quiet WARNING skip
```

- **Attempt budget flow**: `pyproject [tool.prettyplay].llm_request_attempts` →
  `load_config` (file layer) ← `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` (env layer) ← programmatic
  `PrettyConfig(llm_request_attempts=…)` (override layer) → validated `Config` → provider reads
  `config.llm_request_attempts` once per request → `send_with_retries(attempts=…)`. Engine
  budgets (`generation_attempts`, `healing_attempts`, group budgets) never interact with it.
- **Failure flow**: SDK exception → `classify_*_failure` → `TransportFailureClassification`
  → (permanent | over-cap | exhausted → `LLMUnavailableError` chained) or (retryable →
  `compute_transport_pause` → WARNING + sleep → identical resend).
- **Success flow**: SDK response object passes through `send_with_retries` untouched → the
  operation extracts and validates the text answer exactly as today (`require_completion_text`,
  `extract_code_block`, `parse_*`) — response-content recovery never enters the retry loop.

Initialization order for implementation: `TransportFailureClassification` + label constants →
`classify_*_failure` → `compute_transport_pause` → `send_with_retries` → provider rewiring →
`Config` field + loader entries (any order between config and llm; both precede engine
docstring alignment). This plan implements `Config` first (leaf cell, provider wiring reads
`config.llm_request_attempts`), then the llm chain in the design's order.

### Usages Context

- **`conventions`** (`.goga/usages/conventions.md`) — mandatory Python rules: relative imports,
  pydantic v2 kw_only models with empty defaults, `logging` with structured `extra`,
  Google-style docstrings, test structure and mocking boundaries, Python 3.10+
  compatibility. Where used: all five new entities and the whole implementation/test suite —
  and this plan's Mandatory Rules section (extracted below). How: relative imports inside
  `prettyplay.llm`; `ConfigDict(kw_only=True)` + empty defaults for the new model;
  `logging.getLogger("prettyplay")` + `extra` metadata (the contract fixes the logger name
  `prettyplay`, which overrides the conventions' `__name__` example — contract first);
  Google docstrings on every new public symbol; tests mirrored under `tests/llm/`,
  `tests/config/`; mocks only at the SDK/sleep/random boundaries.
- **`pydantic`** (`.goga/usages/cooks/pydantic.md`) — configuration model and loader
  practice for Task 2: keyword-only pydantic construction, one validation path for
  file and programmatic settings, and actionable `ConfigurationError` wrapping for
  invalid loaded values. The new scalar participates in the existing layered merge.
- **`openai`** (`.goga/usages/cooks/openai.md`, corrected by the design) — the openai SDK
  call patterns, client initialization with `max_retries=0`, the exception mapping table, the
  bounded-backoff policy bullet naming `llm_request_attempts` /
  `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`. Where used: `OpenAIProvider`, `classify_openai_failure`
  (Tasks 4, 8).
- **`anthropic`** (`.goga/usages/cooks/anthropic.md`, corrected by the design) — the anthropic
  mirror: init with `max_retries=0`, the exception hierarchy, `max_tokens=4096`, the same
  bounded-backoff policy bullet. Where used: `AnthropicProvider`, `classify_anthropic_failure`
  (Tasks 4, 8). `billing_error` is the explicit quota signal; 529/503/504 sit inside the
  5xx retryable family.
- **`json_repair`** (`.goga/usages/cooks/json_repair.md`) — syntax salvage of malformed JSON
  verdict answers. Where used: `parse_compliance_verdict`,
  `parse_group_failure_classification` — untouched by this change (Task 8 leaves the parsers
  and their `json_repair` usage exactly as is; response parsing never enters the retry loop).

### Imported Usages

- **`taxonomy`** from `prettyplay/failures/.usages/taxonomy.md` is imported by
  `prettyplay/config`. Task 2 preserves its `ConfigurationError` guidance: invalid
  loaded settings fail with an actionable message naming the setting, received value,
  and accepted form; pydantic validation errors remain chained by the existing loader.
- `prettyplay/llm` imports types only (`Config` from `prettyplay/config`;
  `LLMUnavailableError`, `ComplianceVerdictError` from `prettyplay/failures`), with no
  imported Usages. The engine imports `classification`, but the engine's classification
  behavior is unchanged by this plan.

### Local Usages

None planned. The design verified every `.usages/` file of the touched cells as current
(`prettyplay/config/.usages/configuration.md`, `prettyplay/llm/.usages/providers.md`,
`prettyplay/llm/.usages/classification.md`, `prettyplay/failures/.usages/taxonomy.md` —
"Additions/Updates needed: none"); `prettyplay/engine` and `prettyplay/engine/groups` have no
`.usages/` directories. No usage-file creation tasks.

### External Dependencies

- `openai` SDK (≥ 1.30 per `pyproject.toml`; design verified against 3.14.1) — exception
  classes `APIStatusError`, `APIError`, `AuthenticationError`, `PermissionDeniedError`,
  `BadRequestError`, `NotFoundError`, `APITimeoutError`, `APIConnectionError`,
  `RateLimitError`, `InternalServerError`; client constructor parameter `max_retries`
- `anthropic` SDK (≥ 0.28; design verified against 1.6.0) — the mirrored exception classes;
  error type literal `billing_error`; `max_retries`; `max_tokens=4096` (unchanged)
- `pydantic` ≥ 2.7 — `BaseModel`, `ConfigDict`, `PositiveInt` (all already dependencies)
- Test tools: `pytest` ≥ 8.0, `pytest-cov` ≥ 5.0, `pytest-mock` ≥ 3.10, `ruff` ≥ 0.15.0 (the
  `[test]` extras of `pyproject.toml`)
- No new third-party dependencies are added by this plan

---

## Mandatory Rules

Rules extracted from the project convention (`.goga/usages/conventions.md`) — **binding for
every task of this plan**. Priority when they conflict: the CODEMANIFEST contract first, the
facade obligations second, these project conventions next, target-language idioms last.

### M1. Coding Style (conventions: Development)

- **Principles**: readable, explicit code; predictable, straightforward control flow; stable
  abstractions; operational stability and maintainability.
- **Compatibility**: Python 3.10 and above only (test code included).
- **Configuration**: `pyproject.toml` is the single configuration source.
- **Environment**: all code executes within a virtualenv — create it if missing (Task 1).
- **Imports**: relative imports for all intra-package references; absolute imports only for
  stdlib and third-party packages. Example for this plan: `from ..failures import
  LLMUnavailableError` (intra-package, relative); `from openai import APIStatusError`
  (third-party, absolute); `import logging`, `import time`, `import random` (stdlib).
- **Data models**: pydantic for all data models; every model class uses `kw_only=True`; empty
  defaults for all fields — `None` only for fields that represent the explicit absence of a
  value (`retry_after: float | None = None` is exactly that case).
- **Logging**: the `logging` library; operational logs carry contextual metadata, are
  machine-readable, support filtering — structured `extra` on every record; lowercase,
  concise messages with stable event names; levels reflect operational importance (WARNING =
  abnormal but recoverable — retryable failures and retries); **no secrets, credentials,
  tokens, personal data, request or response payloads in any log output**.
- **Code formatting (house style)**: inside function and method bodies, logical blocks are
  separated by one blank line — initialization apart from conditionals/loops, data
  preparation apart from processing, processing apart from the return.
- **Docstrings**: Google style, mandatory on all public functions, methods and classes; the
  first line starts with a capital letter and ends with a period; `Args` when the callable
  accepts parameters, `Returns` when it returns a value, `Raises` when it raises beyond
  built-in types.
- **Dependencies**: every third-party library lives in `pyproject.toml` with a minimum
  version (this plan adds none).

### M2. Test Writing (conventions: Testing)

- **Tools**: pytest (running), ruff (linting and formatting test code), pytest-cov
  (coverage); all tests run inside the virtualenv.
- **Structure mirrors the sources directly**: `prettyplay/llm/_request.py` →
  `tests/llm/test_request.py`; `prettyplay/config/models.py` → `tests/config/test_models.py`;
  integration tests covering multiple packages go directly in `tests/` (no subpackage).
- Every test directory contains `__init__.py`; local fixtures in
  `tests/<package>/conftest.py`, shared fixtures in `tests/conftest.py`.
- **Naming**: files `test_<module>.py`; functions `test_<what>_<scenario>`; grouping
  `class Test<Component>:`.
- **Coverage**: unit tests for every public function/method/class — the main scenario and
  typical data; edge cases cover empty inputs, boundary values (0, negative, very large),
  invalid types, and expected exceptions via `pytest.raises`; integration tests only for
  interaction between modules/packages.
- **Boundary tests**: for thresholds, ranges and state transitions use
  `@pytest.mark.parametrize` with a table of values including each boundary (the pause
  sequence and the retryable/permanent truth tables are exactly this shape).
- **Mocks — only at external boundaries**: pure logic is tested without mocks; file I/O uses
  the `tmp_path` fixture exclusively; external dependencies are `mock.patch`-ed at the import
  point. For this plan the external boundaries are: the SDK client constructors and `create`
  calls, `time.sleep`, `random.uniform`, and environment variables. The classifiers, the
  pause policy and the loop branching logic itself stay mock-free.
- Self-documenting test names; comments minimal. `pytest.mark.skipif` for unavailable
  external dependencies.
- **Classification (project conventions)**: contract tests (facade accessibility, API shape,
  signatures — written FIRST, expected to fail), logic tests (behavior — written after
  implementation), integration tests (cross-entity — a separate task). Integration tests
  never replace contract or logic tests.

### M3. Lint and Format Enforcement (all development stages and local commits)

- The project linter and formatter is **ruff**, configured by `pyproject.toml`
  (`[tool.ruff]`: target `py310`, line length 120, rule families E, W, F, I, N, UP, B, SIM,
  PL, PLR, C4, DTZ, PT, ARG, RUF, PTH, C90; mccabe `max-complexity = 10`;
  `[tool.ruff.format]`: double quotes, space indent, LF line endings, magic trailing comma
  kept; per-file ignores for `tests/**` and the verbatim prompt-constant modules).
- **Every task** ends with its Lint step: `ruff check` over `prettyplay/` and `tests/`
  reports zero errors, and `ruff format` is applied to every file the task touched. Fix the
  code — never the configuration — to pass; decompose when complexity rules demand it. Do
  not widen per-file ignores.
- **Every local commit** (after each approved task) passes the commit gate before
  `git commit` runs:
  1. `.venv/bin/python -m ruff check <changed paths>` — zero errors;
  2. `.venv/bin/python -m ruff format --check <changed paths>` — clean;
  3. `.venv/bin/python -m pytest <affected test modules> -q` — all pass.
  A commit with lint, format or test failures never happens, at any stage of this plan.

### M4. REPL Cycle (development workflow structure)

The implementation phase of every coding task runs as a REPL cycle — continuous interactive
evaluation, hot reloading, code migration to source files:

- **Evaluate live**: keep one long-lived interpreter of the project venv
  (`.venv/bin/python -i`; an equivalent scratch driver script kept **outside the repository**,
  e.g. under `/tmp`, is acceptable when a detached session fits the harness better). Exercise
  the unit under construction with fakes: `SimpleNamespace`-shaped SDK exceptions, patched
  `random.uniform` / `time.sleep`, fake SDK clients.
- **Hot reload**: after every source edit, re-evaluate in the *same* session via
  `importlib.reload(<module>)` — never restart the environment from scratch.
- **Migrate to source files**: code proven in the REPL migrates verbatim into the declared
  `location` file; after migration, reload and re-evaluate importability in the same session;
  then the task's logic tests lock the verified behavior.
- **Boundaries**: REPL experiments make no real network calls and use no real API keys (fakes
  only); the interpreter session and any scratch driver are never committed and never land in
  `tests/`; REPL evidence never substitutes for a test — tests remain the durable
  verification.

Each coding task below names its REPL-cycle specifics.

## Facts

- `prettyplay/llm/_request.py` exists (366 lines): the `CATEGORY_*` / `CATEGORIES` constants
  precedent, the builders, `require_completion_text`, `extract_code_block`,
  `parse_classification_line`; it already imports `LLMUnavailableError`
  (`from ..failures import LLMUnavailableError`). None of the five new entities exist.
- `prettyplay/llm/openai_provider.py` / `anthropic_provider.py`: `_get_client` constructs
  `OpenAI(api_key=…, base_url=… or None)` / `Anthropic(api_key=…, base_url=… or None)`
  without `max_retries`; each of the four operations has one
  `except OpenAIError`/`except AnthropicError` → `LLMUnavailableError` block
  (openai_provider.py:186, 237, 313, 368; anthropic_provider.py:217, 266, 340, 393).
- `prettyplay/config/models.py`: `healing_attempts: PositiveInt = 2` at line 221,
  `send_screenshots: bool = False` at line 222 — the new field slots between them;
  `PositiveInt` is already imported (models.py:8).
- `prettyplay/config/loader.py`: `_ENV_NAMES` (line 22), `_INT_ENV_SETTINGS` (line 63),
  `_ALLOWED_TEXT` (line 76) — none mentions `llm_request_attempts`; the env-name derivation
  (`setting.upper().replace('.', '_')`, loader.py:23) produces exactly
  `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`; the layered merge is generic and needs no change.
- `prettyplay/llm/__init__.py` exports 11 names alphabetically; the five new names are
  absent. `prettyplay/__init__.py` (root) is unchanged by this plan.
- `prettyplay/failures/errors.py:331` — the `LLMUnavailableError` docstring predates the
  widened annotation.
- Engine docstrings still say "no retry" at `engine/generator.py` (≈ 251, 301, 346, 453,
  733), `engine/healer.py` (≈ 98), `engine/groups/recovery.py` (≈ 128, 228),
  `engine/groups/diagnosis.py` (≈ 83), `engine/compliance.py` (≈ 98).
- Test modules exist for every touched source: `tests/llm/test_request.py` (32 tests),
  `tests/llm/test_openai_provider.py` (35), `tests/llm/test_anthropic_provider.py`,
  `tests/config/test_models.py` (39), `tests/config/test_loader.py` (52); helper
  `make_client_create` / `completion_answer` at tests/llm/test_openai_provider.py:64/:78.
- The design verified the SDK evidence rules against the installed sources: `openai` 3.14.1
  and `anthropic` 1.6.0 (`APIStatusError` carries `response: httpx.Response`; 408 has no SDK
  subclass in either SDK; anthropic `ErrorType` includes `billing_error`). Re-verify in the
  REPL against the actually installed versions before coding the classifiers (Task 4).
- The `.venv` of the working tree was created on macOS (interpreter symlinks point at
  `/opt/homebrew/...`) and is unusable on Linux hosts — Task 1 checks and repairs it
  (conventions: create the virtualenv if missing).
- The cooks practices were already corrected by the design stage
  (`llm_request_attempts` / `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` in both
  `.goga/usages/cooks/*.md`); `grep -r transport_attempts` over `.goga/usages/` and
  `prettyplay/` matches only the supersession annotation of `prettyplay/llm/CODEMANIFEST`,
  which stays verbatim — do not edit it.

## Gap Analysis

- **Missing contract entities**: `TransportFailureClassification`, `classify_openai_failure`,
  `classify_anthropic_failure`, `compute_transport_pause`, `send_with_retries` — none exist
  in `prettyplay/llm/_request.py`.
- **Missing facade exposure**: none of the five names in `prettyplay/llm/__all__`.
- **Missing config surface**: no `llm_request_attempts` field, docstring line, loader
  registry entries, env parsing, allowed-text entry.
- **API/behavioral mismatches**: providers construct SDK clients with SDK-default retries
  (2) instead of `max_retries=0`; the per-operation `except *Error` blocks implement the old
  single-send mapping instead of the bounded retry loop; engine/failures docstrings describe
  the old no-retry behavior.
- **Existing code reused as is**: all request builders, `require_completion_text`, the
  parsers, `_get_client` key handling (message byte-for-byte preserved, D3), the loader's
  generic merge/validation machinery, the test helpers (`make_client_create`,
  `completion_answer`, `mock.patch.object(provider, "_get_client", …)`).
- **Test coverage gaps**: all 30 design test scenarios are new (15 positive, 9 negative,
  6 edge); two existing config enumeration tests need field-list updates.
- **Workspace visibility**: all target files exist and are git-tracked; the venv needs
  verification/repair (Task 1).

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the
> next. Order: `prettyplay/config` (Task 2) → `prettyplay/llm` (Tasks 3–8) → docstring
> alignment across `prettyplay/failures` + engine cells (Task 9) → cross-cell integration
> test (Task 10). Within each coding task, contract tests are written first (TDD workflow).
> The five `_request.py` entities share one `location` but are split into staged tasks
> (model → classifiers → pause → loop) following the design's initialization order — each
> stage builds on the previous, and each task stays executable in a single session.

### Task 1: Toolchain bootstrap — virtualenv, pytest, ruff (infrastructure)

**Context**: conventions M1/M3 require all code to execute in a virtualenv and ruff to gate
every stage. The repository venv (`.venv/`) was created on macOS and may be unusable on the
execution host (interpreter symlinks pointing at `/opt/homebrew/...`). This task verifies —
and if needed repairs — the toolchain before any coding task runs. No product code changes.

**Usages relevant to this task:**
- `conventions`: "Execute all code within a virtualenv environment — create it if missing";
  validation commands table (`pytest tests/ -x`, `ruff check <src>/`).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Declaration (STEP 0)**: task 1, infrastructure — toolchain bootstrap, no contract entities
- [x] Verify the toolchain: `.venv/bin/python --version`, then
      `.venv/bin/python -c "import pytest, ruff, openai, anthropic, pydantic; print('toolchain ok')"`
      and `.venv/bin/python -m pytest tests/config -q` (smoke run)
- [x] If the venv is broken or missing: recreate it
      (`python3 -m venv .venv --clear`), install the project with the test extras
      (`.venv/bin/pip install -e '.[test]'`), and re-run the verification above
      (venv was broken — macOS interpreter symlinks; recreated on Python 3.12.15)
- [x] Record the installed SDK versions:
      `.venv/bin/python -c "import openai, anthropic; print(openai.__version__, anthropic.__version__)"`
      — the design verified the classifier evidence against openai 3.14.1 / anthropic 1.6.0;
      if the installed versions differ materially, note it for Task 4 (the evidence ladder is
      re-verified there against the installed sources in the REPL)
      (recorded: openai 3.26.0 / anthropic 1.11.0 — newer than the design's versions, but the
      full evidence surface was re-verified live and is unchanged: all ten exception classes
      present in both SDKs, `APITimeoutError` still subclasses `APIConnectionError`,
      `APIStatusError` still carries `response`/`status_code`/`type` parsed from the body,
      `billing_error` still in `anthropic.types.ErrorType`, `max_retries` constructor
      parameter present in both clients — immaterial for Task 4)
- [x] Verify the linter gate runs: `.venv/bin/python -m ruff check prettyplay/ tests/` —
      zero errors on the untouched tree (report if not)
- [x] Lint (STEP 7): no files were touched — confirm `git status` shows no product changes

### Task 2: `Config.llm_request_attempts` — field, docstring, loader registries (TDD coding)

**Context**: the `prettyplay/config` cell. The `Config` entity gains the
`llm_request_attempts` field between `healing_attempts` and `send_screenshots`, exactly per
the contract text quoted in Contract Surface. Files: `prettyplay/config/models.py` (field +
docstring attribute line), `prettyplay/config/loader.py` (three registry additions only —
`_ENV_NAMES`, `_INT_ENV_SETTINGS`, `_ALLOWED_TEXT`; the merge code is generic and needs no
change). Tests extend `tests/config/test_models.py` and `tests/config/test_loader.py`.
The layered merge is verified by the design: scalars merge generically
(`merged = {**section, **env}` at loader.py:310; `_apply_overrides` at loader.py:233).

**Usages relevant to this task:**
- `conventions`: pydantic kw_only with empty defaults (the field takes default `3`, the
  positive-integer analogue of an empty default); loud actionable validation; tests at
  `tests/config/`, `@pytest.mark.parametrize` for the boundary values; ruff on test code.
- `pydantic` (`.goga/usages/cooks/pydantic.md`): keep the existing
  `ConfigDict(kw_only=True)` model, validate `llm_request_attempts` through
  `PositiveInt` for file and programmatic settings alike, and preserve the loader's
  `ConfigurationError` wrapper for invalid loaded values. Its message identifies the
  setting, received value, and accepted form; the new scalar follows the existing
  pyproject → environment → explicit override merge.
- Imported `taxonomy` (`prettyplay/failures/.usages/taxonomy.md`): a bad
  `llm_request_attempts` value loaded from pyproject or the environment remains an
  actionable `ConfigurationError` naming the setting, received value, and accepted
  format. Preserve the existing cause behavior: chain pydantic validation errors,
  while malformed decimal environment input raises from `None`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Declaration (STEP 0)**: task 2 — `Config.llm_request_attempts` (field + docstring + loader registries)
- [x] **Contract tests** (in `tests/config/test_models.py`, `tests/config/test_loader.py`;
      expected to fail at this stage):
  - `test_config_llm_request_attempts_field_defaults_and_order` — `Config().llm_request_attempts == 3`;
    `list(Config.model_fields)[13:16] == ["generation_attempts", "healing_attempts", "llm_request_attempts"]`
  - `test_loader_env_override_parses_decimal_integer` — `tmp_path` pyproject.toml with
    `[tool.prettyplay] model = "m"` and `llm_request_attempts = 2`;
    `monkeypatch.setenv("PRETTYPLAY_LLM_REQUEST_ATTEMPTS", "5")`; `PRETTYPLAY_*` browser/legacy
    env cleaned; `load_config(str(tmp_path / "pyproject.toml"))` →
    `config.llm_request_attempts == 5`
- [x] **REPL cycle** (M4): in the venv interpreter — construct `Config()` and read
  `.llm_request_attempts`; inspect `list(Config.model_fields)` around the insertion point;
  set `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` in `os.environ`, call `load_config` on a scratch
  `tmp_path` TOML, observe the override and the loud error on `"three"`; after each edit,
  `importlib.reload(prettyplay.config.models)` / `...loader`; migrate the verified field and
  registry lines into the source files
- [x] **Code**: add to `prettyplay/config/models.py` the field
  `llm_request_attempts: PositiveInt = 3` between `healing_attempts` (line 221) and
  `send_screenshots` (line 222), and the class-docstring attribute line mirroring the
  CODEMANIFEST parameter text quoted in Contract Surface (one line, same style as the
  neighboring `healing_attempts` line)
- [x] **Code**: add to `prettyplay/config/loader.py` exactly three registry entries:
  `"llm_request_attempts"` in `_ENV_NAMES` (derives `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`),
  `"llm_request_attempts"` in `_INT_ENV_SETTINGS`, and
  `_ALLOWED_TEXT["llm_request_attempts"] = "a positive integer"`
- [x] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/config/test_models.py tests/config/test_loader.py -q`
- [x] **Logic tests (STEP 4)** (design scenarios, negative and edge):
  - `test_config_rejects_llm_request_attempts_below_one` — `pytest.raises(ValidationError)`
    on `Config(llm_request_attempts=0)` and `-1` (`pytest.param` both); the rendered text
    contains `llm_request_attempts` and the received value (mirrors the existing
    `test_zero_generation_attempts_fails_with_field_name`)
  - `test_loader_unparseable_env_llm_request_attempts_fails_loudly` — `tmp_path` pyproject
    with `[tool.prettyplay]`; `monkeypatch.setenv("PRETTYPLAY_LLM_REQUEST_ATTEMPTS", "three")`;
    `pytest.raises(ConfigurationError)` with the message naming the setting, the received
    value (`'three'`) and the accepted form (`a decimal integer`)
- [x] **Existing test updates** (field enumerations only, not behavior):
  `tests/config/test_models.py::test_all_nineteen_properties_accessible` → twenty entries
  (insert `llm_request_attempts` after `healing_attempts`; adjust the count word in the test
  name to match); `test_signature_declares_seventeen_fields_in_contract_order` → rename/extend
  to eighteen fields with `llm_request_attempts` between `healing_attempts` and
  `send_screenshots`
- [x] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/config -q` — fix
  implementation code until all tests pass (do NOT fix test code)
- [x] **Contract re-verification (STEP 6)**: field order/default match the CODEMANIFEST
  signature; env name is exactly `PRETTYPLAY_LLM_REQUEST_ATTEMPTS`; facade
  `prettyplay.config` still imports `Config`/`PrettyConfig`
- [x] **Lint (STEP 7)**: `.venv/bin/python -m ruff check prettyplay/ tests/` — zero errors;
  `.venv/bin/python -m ruff format` on `prettyplay/config/models.py`,
  `prettyplay/config/loader.py`, `tests/config/test_models.py`, `tests/config/test_loader.py`
- [x] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate
  (M3) before the local commit.

### Task 3: `TransportFailureClassification` and the transport label constants (TDD coding)

**Context**: the `prettyplay/llm` cell, `location` `_request.py`. The immutable verdict of
one transport failure classification. Module constants (house style follows the existing
`CATEGORY_*` / `CATEGORIES` block at the top of `_request.py`):

```
TRANSPORT_CONNECTION = "connection"; TRANSPORT_TIMEOUT = "timeout"
TRANSPORT_RATE_LIMIT = "rate_limit"; TRANSPORT_SERVER_ERROR = "server_error"
TRANSPORT_AUTHENTICATION = "authentication"; TRANSPORT_PERMISSION_DENIED = "permission_denied"
TRANSPORT_INVALID_REQUEST = "invalid_request"; TRANSPORT_NOT_FOUND = "not_found"
TRANSPORT_QUOTA_EXHAUSTED = "quota_exhausted"
RETRYABLE_TRANSPORT_CATEGORIES = frozenset({connection, timeout, rate_limit, server_error})
PERMANENT_TRANSPORT_CATEGORIES = frozenset({authentication, permission_denied,
                                            invalid_request, not_found, quota_exhausted})
```

The model mirrors the `FailureClassification` / `ComplianceFinding` precedent in
`prettyplay/llm/models.py` (pydantic v2, `ConfigDict(kw_only=True)`, empty defaults).
`retryable` is a plain `@property` — the CODEMANIFEST lists it under `properties`, not in the
signature. The closed nine-label set is enforced by the classifiers (the only constructors),
never by pydantic validation.

**Usages relevant to this task:**
- `conventions`: pydantic v2 kw_only with empty defaults; `None` only for explicit absence;
  Google docstrings; ruff; tests mirrored at `tests/llm/test_request.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Declaration (STEP 0)**: task 3 — `TransportFailureClassification` + label constants
- [x] **Contract tests** (new class in `tests/llm/test_request.py`; expected to fail):
  constructible with keyword args `category`/`retry_after`; `retryable` is a callable
  attribute (not a constructor field — `inspect` shows no such `__init__` parameter); the
  module exposes the constants
- [x] **REPL cycle** (M4): in the venv interpreter — construct
  `TransportFailureClassification(category="connection")`, check `.retryable` for all nine
  labels, attempt positional construction (expect `TypeError` before field validation);
  `importlib.reload(prettyplay.llm._request)` after each edit; migrate the verified class
  into `_request.py`
- [x] **Code**: add the constants block to `prettyplay/llm/_request.py` (above the model,
  beside the existing `CATEGORY_*` block, with `#:` comments in the house style)
- [x] **Code**: add `TransportFailureClassification` — pydantic v2 `BaseModel`,
  `model_config = ConfigDict(kw_only=True)`; fields `category: str = ""` and
  `retry_after: float | None = None`; `@property def retryable(self) -> bool` returning
  `self.category in RETRYABLE_TRANSPORT_CATEGORIES`; Google docstring
  (`from pydantic import BaseModel, ConfigDict` — the third-party absolute import)
- [x] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/llm/test_request.py -q`
- [x] **Logic tests (STEP 4)** — the design scenario
  `test_transport_failure_classification_model_shape_and_retryable_truth_table`:
  `TransportFailureClassification(category=X).retryable is True` for connection, timeout,
  rate_limit, server_error; `is False` for authentication, permission_denied,
  invalid_request, not_found, quota_exhausted; `TransportFailureClassification().retryable
  is False` (empty default category); `pytest.raises(TypeError)` on positional construction
  `TransportFailureClassification("connection")` — parametrize the truth table
- [x] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/llm/ -q` — fix
  implementation until green (do NOT fix test code)
- [x] **Contract re-verification (STEP 6)**: model shape matches the signature
  `(category: str, retry_after: float | None)`; kw_only; empty defaults; `retryable`
  under properties — no other public members added
- [x] **Lint (STEP 7)**: ruff check + ruff format on `prettyplay/llm/_request.py`,
  `tests/llm/test_request.py`
- [x] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 4: `classify_openai_failure` / `classify_anthropic_failure` (TDD coding)

**Context**: the two pure classifiers at `prettyplay/llm/_request.py`. Shared algorithm
(evidence classes per SDK — verified by the design against `openai` 3.14.1 and
`anthropic` 1.6.0 `_exceptions.py` / `_client.py`):

```
GIVEN error
1. permanent evidence (first match wins):
   a. openai:  APIStatusError with code|type == "insufficient_quota"      → quota_exhausted
      anthropic: APIStatusError with type == "billing_error"             → quota_exhausted
   b. AuthenticationError   → authentication
   c. PermissionDeniedError → permission_denied
   d. BadRequestError       → invalid_request
   e. NotFoundError         → not_found
2. retryable evidence:
   a. APITimeoutError                                  → timeout
   b. APIConnectionError                               → connection
   c. RateLimitError                                   → rate_limit
   d. APIStatusError with status_code == 408           → timeout
   e. APIStatusError with 500 ≤ status_code ≤ 599      → server_error
3. retry_after := float(response.headers["retry-after"]) when parseable and finite, else None
   (extraction is category-independent; HTTP-dates and the anthropic retry-after-ms
    are not parsed — D4)
4. no rule matched → invalid_request                    (D2/2A — permanent fallback)
RETURN TransportFailureClassification(category, retry_after)
```

Design decisions to honor: **D2/2A** the permanent fallback label is `invalid_request`;
**D4** decimal-seconds-only Retry-After parsing (HTTP-date and `retry-after-ms` → `None`);
**D5** neither SDK has a 408 subclass — match `APIStatusError.status_code == 408` and label
it `timeout`; **D6** quota evidence — openai `code` or `type` == `"insufficient_quota"`
(`APIError` parses them from the body's `error` object), anthropic `type` ==
`"billing_error"` (SDK `ErrorType` literal); **D7** anthropic 529/503/504 fall under the
500–599 `server_error` rule. `APITimeoutError` is a subclass of `APIConnectionError` — check
it first. Both SDKs carry `response: httpx.Response` on `APIStatusError`; the classifiers
only read attributes, so tests pass a `SimpleNamespace(status_code=…, headers={…},
request=SimpleNamespace())` as the response kwarg. Constraints: pure (no I/O, no logging,
no state); never raise — every attribute access goes through `getattr(..., None)` guards so
even a non-SDK exception classifies.

**Usages relevant to this task:**
- `openai` / `anthropic` (cooks): the per-SDK exception mapping tables and evidence rules;
  import the exception classes from the public `openai` / `anthropic` packages.
- `conventions`: pure functions without mocks in tests; `@pytest.mark.parametrize` tables;
  Google docstrings; relative/absolute import split (SDK imports are third-party absolute).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Declaration (STEP 0)**: task 4 — both classifiers, provider parity
- [x] **Contract tests** (in `tests/llm/test_request.py`; expected to fail): both names
  importable from `prettyplay.llm._request`; signatures
  `(error: Exception) -> TransportFailureClassification`; a `ValueError` input returns a
  `TransportFailureClassification` (never raises)
- [x] **REPL cycle** (M4): in the venv interpreter — build fake status errors
  (`SimpleNamespace`-response `RateLimitError`, `InternalServerError`, generic
  `APIStatusError` with 408/599, `APIConnectionError(request=…)`, `APITimeoutError`,
  attribute-patched quota/billing errors) and drive both classifiers through the whole
  ladder live; confirm against the **installed** SDK sources
  (`import openai._exceptions, inspect; inspect.getsource(...)`) that the evidence classes
  and attributes match the table above (the design verified 3.14.1 / 1.6.0); reload after
  every edit; migrate the verified ladders into `_request.py`
  (verified against openai 3.26.0 / anthropic 1.11.0: the full ladder driven live; note —
  openai `_client._make_status_error` unwraps `body.get("error", body)` before
  `APIError` parses `code`/`type`, so real quota responses do surface
  `insufficient_quota` on the attributes)
- [x] **Code**: implement `classify_openai_failure(error: Exception) ->
  TransportFailureClassification` in `prettyplay/llm/_request.py` — permanent ladder first
  (quota body evidence via `getattr(error, "code", None)` / `getattr(error, "type", None)`
  on `APIStatusError`; then `AuthenticationError`, `PermissionDeniedError`,
  `BadRequestError`, `NotFoundError`), retryable ladder (`APITimeoutError` before
  `APIConnectionError`; `RateLimitError`; `APIStatusError` with `status_code == 408`;
  `APIStatusError` with `500 <= status_code <= 599`), category-independent Retry-After
  extraction (`response = getattr(error, "response", None)`; `raw =
  response.headers.get("retry-after")` when both present; `float(raw)`; missing header,
  non-numeric value (HTTP-date included) or non-finite result → `None`), fallback
  `invalid_request`; return `TransportFailureClassification(category=…, retry_after=…)`
- [x] **Code**: implement `classify_anthropic_failure` with rule-by-rule parity — quota
  evidence `getattr(error, "type", None) == "billing_error"`; the same five permanent
  classes; the same retryable ladder; identical Retry-After extraction (the non-standard
  `retry-after-ms` header stays unread); fallback `invalid_request`
- [x] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/llm/test_request.py -q`
- [x] **Logic tests (STEP 4)** — the five design scenarios:
  - `test_classify_openai_failure_maps_the_retryable_family` — Setup: helper
    `status_error(cls_or_status, headers=None)` building an `APIStatusError` (or subclass)
    with `SimpleNamespace(status_code=…, headers=headers or {}, request=SimpleNamespace())`
    and `body=None`; Input (parametrized): `APIConnectionError(request=…)`,
    `APITimeoutError(request=…)` (both take only `request`), `RateLimitError(..., response=…429…)`,
    `APIStatusError(..., 408 ...)`, `InternalServerError(..., 500 ...)`,
    `APIStatusError(..., 599 ...)`; Assertions:
    `failure.category == param.expected` (`connection | timeout | rate_limit |
    server_error`), `failure.retryable is True`, `failure.retry_after is None`
  - `test_classify_openai_failure_quota_beats_retryable_status` — a real `RateLimitError`
    (429, response faked) whose `code` is `"insufficient_quota"` (set after construction or
    via `body={"error": {"code": "insufficient_quota", "type": "insufficient_quota"}}`);
    Assertions: `failure.category == "quota_exhausted"`, `failure.retryable is False`
  - `test_classify_anthropic_failure_billing_error_is_permanent_quota` — an anthropic
    `APIStatusError`-shaped error with `type = "billing_error"` (status 429); Assertions:
    `failure.category == "quota_exhausted"`, `failure.retryable is False`
  - `test_classify_failures_parse_retry_after_seconds` — parametrized over both
    classifiers; a `RateLimitError` with `headers={"retry-after": "7"}`; variants `"2.5"`,
    `"0"`, `"-3"`, an HTTP-date string, missing header; Assertions: `failure.retry_after ==
    7.0 | 2.5 | -3.0 | None | None` per case, `failure.category == "rate_limit"`
  - `test_classify_failures_unrecognized_exception_is_permanent_invalid_request` —
    `ValueError("boom")` and an openai `ConflictError`-shaped status error (409), through
    both classifiers (parametrized 2×2); Assertions: `failure.category ==
    "invalid_request"`, `failure.retryable is False`
  (all five scenarios implemented; plus a supplementary permanent-family parity table
  parametrized over both classifiers — authentication, permission_denied,
  invalid_request, not_found)
- [x] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/llm/ -q` — fix
  implementation until green
- [x] **Contract re-verification (STEP 6)**: both classifiers total and pure — no raise on
  any input; the nine-label closed set; parity of ladders between the two SDKs
  (never-raise verified live on attr-less objects, non-mapping headers, non-finite
  values; the closed set flows from the `TRANSPORT_*` constants through one shared
  ladder core used by both classifiers — parity is structural)
- [x] **Lint (STEP 7)**: ruff check + ruff format on `prettyplay/llm/_request.py`,
  `tests/llm/test_request.py`
- [x] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 5: `compute_transport_pause` (TDD coding)

**Context**: the fixed delay policy at `prettyplay/llm/_request.py`. Algorithm:

```
GIVEN failed_attempt (≥ 1), retry_after
1. base := min(2 ** (failed_attempt - 1), 10.0)
2. pause := base + random.uniform(0.0, base * 0.25)
3. pause := min(pause, 10.0)
4. IF retry_after is not None AND 0 < retry_after ≤ 10.0:
     pause := max(pause, retry_after)
RETURN pause
```

Pure aside from `random.uniform` (the only random source — tests monkeypatch it). No I/O, no
sleeps. Output: `float` in `(0, 10]`. Edge cases: `failed_attempt = 1` → base 1.0, pause ∈
[1.0, 1.25]; `failed_attempt ≥ 5` → exactly 10.0 (cap dominates); `retry_after` of 0 /
negative / `None` → ignored (the lift guard excludes non-positive values).

**Usages relevant to this task:**
- `conventions`: boundary values via `@pytest.mark.parametrize`; pure logic tested without
  mocks (the single permitted patch is `random.uniform` — an external randomness boundary).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Declaration (STEP 0)**: task 5 — the delay policy
- [x] **Contract tests** (in `tests/llm/test_request.py`; expected to fail): name
  importable; signature `(failed_attempt: int, retry_after: float | None) -> float`; returns
  a `float` for `(1, None)`
- [x] **REPL cycle** (M4): in the venv interpreter — evaluate
  `[compute_transport_pause(n, None) for n in range(1, 8)]` with
  `random.uniform = lambda a, b: 0.0` patched in the session (restore afterwards); verify
  the sequence 1, 2, 4, 8, 10, 10, 10 and the lift/cap arithmetic live; reload after each
  edit; migrate the verified function into `_request.py`
  (scratch driver under /tmp — phase 1 proved the inline arithmetic: the sequence, the lift
  cases incl. negative/10.0-boundary Retry-After, the jitter band; phase 2 re-verified the
  migrated function via importlib.reload in the same session)
- [x] **Code**: implement `compute_transport_pause(failed_attempt: int, retry_after:
  float | None) -> float` exactly per the algorithm (`import random` — stdlib absolute);
  Google docstring with `Args`/`Returns`
  (house-style `_TRANSPORT_PAUSE_CAP = 10.0` / `_TRANSPORT_JITTER_FRACTION = 0.25`
  constants beside the function, mirroring the `_STATUS_*` precedent)
- [x] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/llm/test_request.py -q`
- [x] **Logic tests (STEP 4)** — the three design scenarios:
  - `test_compute_transport_pause_base_sequence_jitter_and_cap` —
    `monkeypatch.setattr("random.uniform", lambda a, b: 0.0)`; Input
    `compute_transport_pause(n, None)` for n in 1..7; Assertion:
    `[compute_transport_pause(n, None) for n in range(1, 8)] == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0, 10.0]`
  - `test_compute_transport_pause_jitter_bounds_and_final_cap` —
    `monkeypatch.setattr("random.uniform", lambda a, b: b)` (max jitter); Assertions:
    `compute_transport_pause(1, None) == 1.25` and `compute_transport_pause(5, None) == 10.0`
  - `test_compute_transport_pause_retry_after_lifts_within_cap` — jitter off; Inputs
    `(1, 5.0)`, `(3, 2.0)`, `(1, 0.0)`, `(1, None)`; Assertion: results `== [5.0, 4.0, 1.0, 1.0]`
- [x] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/llm/ -q` — fix
  implementation until green
  (272 passed in tests/llm/; full suite 1117 passed)
- [x] **Contract re-verification (STEP 6)**: pure function — no sleep, no logging; the cap
  and the lift guard match the CODEMANIFEST algorithm
  (verified via inspect.getsource: no sleep/logging/logger references; the only external
  touch is random.uniform — the permitted randomness boundary)
- [x] **Lint (STEP 7)**: ruff check + ruff format on `prettyplay/llm/_request.py`,
  `tests/llm/test_request.py`
  (one fix round: ARG005 unused lambda args → underscore-prefixed `_a`/`_b` per the
  existing tests/test_integration.py style — code fixed, configuration untouched)
- [x] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 6: `send_with_retries` — the bounded retry loop (TDD coding)

**Context**: the only retry authority of the port, at `prettyplay/llm/_request.py`.
Algorithm (D16 — terminal branch order is contractual):

```
GIVEN provider, operation, attempts (≥ 1), classify, send
logger := logging.getLogger("prettyplay")
FOR attempt IN 1..attempts:
  TRY RETURN send()
  EXCEPT Exception AS error:
    failure := classify(error)
    IF NOT failure.retryable:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} request failed permanently: {failure.category}") FROM error
    IF failure.retry_after IS NOT None AND failure.retry_after > 10.0:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} asked to wait {failure.retry_after:g} seconds"
          " — above the 10 second retry cap, not retrying") FROM error
    IF attempt == attempts:
      RAISE LLMUnavailableError(
          f"llm unavailable: {provider} request failed after {attempts} attempts") FROM error
    pause := compute_transport_pause(attempt, failure.retry_after)
    logger.warning("llm request retry", extra={"provider": provider, "operation": operation,
                  "attempt": attempt, "category": failure.category, "delay": pause})
    time.sleep(pause)          # KeyboardInterrupt propagates — no further send
```

Message shapes (keep stable — tests assert substrings): permanent — `llm unavailable:
{provider} request failed permanently: {category}`; over-cap — `llm unavailable: {provider}
asked to wait {n} seconds — above the 10 second retry cap, not retrying`; exhaustion —
`llm unavailable: {provider} request failed after {attempts} attempts`. Always
`raise … from` the original SDK error. `except Exception` only — never `BaseException`
(`KeyboardInterrupt` during the SDK call propagates untouched; inside `time.sleep` it
propagates — no further send). Generic typing: module-level `T = TypeVar("T")`;
`Callable` from `typing`/`collections.abc` — Python 3.10+ (D9). The module gains
`logger = logging.getLogger("prettyplay")` (the contract fixes the logger name, matching
`engine/generator.py:25`) and `import logging`, `import time`. `LLMUnavailableError` is
already imported in `_request.py`. Exactly one WARNING per retry with the five metadata
fields (`provider`, `operation`, `attempt`, `category`, `delay`) — labels and numbers only,
never secrets, never request/response contents. No records on success; no records on
terminal failures beyond the exceptions themselves.

**Usages relevant to this task:**
- `conventions`: structured `extra` logging, lowercase stable event names, WARNING for
  retryable failures; mock boundaries — `time.sleep` and `random.uniform` are patched at the
  external boundary, the loop logic itself stays mock-free; `caplog` for log-field tests.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration (STEP 0)**: task 6 — the retry loop
- [ ] **Contract tests** (in `tests/llm/test_request.py`; expected to fail): name
  importable; signature `(provider: str, operation: str, attempts: int, classify, send)`;
  generic pass-through — `send_with_retries("openai", "generation", 3, classify, lambda: "ok")`
  returns `"ok"` with a never-classifying classifier
- [ ] **REPL cycle** (M4): in the venv interpreter — drive the loop live with scripted
  closures: a `send` that raises `anthropic.APIConnectionError(request=…)` twice then
  returns an object; `time.sleep` replaced in-session by a recorder
  (`time.sleep = lambda p: sleeps.append(p)`, restored afterwards) and
  `random.uniform = lambda a, b: 0.0`; watch the WARNINGs arrive on
  `logging.getLogger("prettyplay")` (attach a handler in the session); repeat for the
  permanent / over-cap / exhaustion scripts; reload after each edit; migrate the verified
  loop into `_request.py`
- [ ] **Code**: add to `prettyplay/llm/_request.py` — `T = TypeVar("T")` (module level),
  `logger = logging.getLogger("prettyplay")` (module level), and
  `send_with_retries(provider: str, operation: str, attempts: int, classify:
  Callable[[Exception], TransportFailureClassification], send: Callable[[], T]) -> T`
  implementing the algorithm above verbatim (branch order: permanent → over-cap →
  exhaustion → pause/log/wait)
- [ ] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/llm/test_request.py -q`
- [ ] **Logic tests (STEP 4)** — eleven design scenarios (positive):
  - `test_send_with_retries_success_returns_response_without_side_effects` — Setup:
    `sent = []; send = lambda: sent.append(1) or "ok"`; classifier =
    `lambda e: pytest.fail("must not classify")`; sleep recorded; Input:
    `send_with_retries("openai", "generation", 3, classifier, send)`; Assertions:
    `result == "ok"`, `sent == [1]`, `sleep_calls == []`, `caplog.records == []`
  - `test_send_with_retries_retries_then_succeeds_with_two_warnings` — Setup: scripted
    `[anthropic.APIConnectionError(request=…), anthropic.APIConnectionError(request=…),
    "ok"]`; classifier = `classify_anthropic_failure`; sleep recorded;
    `caplog.set_level(logging.WARNING, logger="prettyplay")`; `random.uniform → 0`; Input:
    `send_with_retries("anthropic", "group diagnosis", 3, classify, send)`; Assertions:
    `result is response`, `send_call_count == 3`, `[sleep args] == [1.0, 2.0]`,
    `len(caplog.records) == 2`, `records[0].levelname == "WARNING"`,
    `records[0].name == "prettyplay"`, `records[0].provider == "anthropic"`,
    `records[0].operation == "group diagnosis"`, `records[0].attempt == 1`,
    `records[0].category == "connection"`, `records[0].delay == 1.0`
- [ ] **Logic tests (negative)**:
  - `test_send_with_retries_permanent_failure_terminates_immediately` — `send` raises an
    `AuthenticationError`-shaped exception every call; classifier =
    `classify_openai_failure`; Assertions: `pytest.raises(LLMUnavailableError)` with
    "openai" and "authentication" in `str(excinfo.value)`;
    `excinfo.value.__cause__ is the SDK error`; `send_call_count == 1`;
    `sleep_calls == []`; `caplog.records == []`
  - `test_send_with_retries_over_cap_retry_after_terminates_before_any_pause` — `send`
    raises a `RateLimitError`-shaped error with `headers={"retry-after": "30"}`; Assertions:
    `pytest.raises(LLMUnavailableError)` with "10 second retry cap" in the message;
    `excinfo.value.__cause__ is the SDK error`; `send_call_count == 1`;
    `sleep_calls == []`; `caplog.records == []`
  - `test_send_with_retries_exhaustion_raises_with_cause_and_attempt_count` — `send`
    always raises a connection-shaped failure; classifier =
    `classify_anthropic_failure`; `random.uniform → 0`; Assertions:
    `pytest.raises(LLMUnavailableError)` with "after 3 attempts" in the message;
    `excinfo.value.__cause__ is the last SDK error`; `send_call_count == 3`;
    `[sleep args] == [1.0, 2.0]`; `len(caplog.records) == 2` (the terminal attempt logs
    nothing)
  - `test_send_with_retries_single_attempt_disables_retries` — connection-shaped failure,
    `attempts=1`; Assertions: `pytest.raises(LLMUnavailableError)`; `send_call_count == 1`;
    `sleep_calls == []`; `caplog.records == []`
  - `test_send_with_retries_keyboard_interrupt_during_wait_propagates` — sleep raises
    `KeyboardInterrupt`; Assertions: `pytest.raises(KeyboardInterrupt)`;
    `send_call_count == 1`
- [ ] **Logic tests (edge)**:
  - `test_send_with_retries_never_sends_more_than_the_budget` — always retryable failure,
    `attempts = 5`, `random.uniform → 0`; Assertions: `send_call_count == 5`;
    `[sleep args] == [1.0, 2.0, 4.0, 8.0]`; `len(caplog.records) == 4`
  - `test_send_with_retries_over_cap_retry_after_wins_over_exhaustion` — rate-limit-shaped
    error with `retry-after: 15`, `attempts = 1`; Assertion: `pytest.raises(
    LLMUnavailableError)` with "retry cap" in the message and **not** "after 1 attempts"
  - `test_send_with_retries_zero_retry_after_is_ignored_not_fatal` — rate-limit-shaped
    error with `headers={"retry-after": "0"}`, `attempts = 2`, second send succeeds;
    Assertions: `result is the response`; `sleep args == [1.0]`
  - `test_logging_carries_no_request_payloads` — retry-then-succeed scenario where the send
    closure captured a payload containing `"secret-token"` in its kwargs; Assertions:
    `all("secret-token" not in rec.getMessage() for rec in caplog.records)` and
    `all(set(("provider","operation","attempt","category","delay")) <= set(rec.__dict__)
    for rec in caplog.records)`
- [ ] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/llm/ -q` — fix
  implementation until green
- [ ] **Contract re-verification (STEP 6)**: at most `attempts` sends; branch order
  permanent → over-cap → exhaustion; one WARNING per retry with exactly the five fields;
  `raise … from` on all three terminal branches
- [ ] **Lint (STEP 7)**: ruff check + ruff format on `prettyplay/llm/_request.py`,
  `tests/llm/test_request.py`
- [ ] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 7: Facade exports of the transport machinery (infrastructure + contract test)

**Context**: D17 — export the five new names from `prettyplay/llm/__init__.py` (`__all__`
updated, alphabetical order per the existing facade style); the root facade
`prettyplay/__init__.py` stays unchanged. The facade test follows the existing pattern
(`tests/llm/test_models.py` asserts `prettyplay.llm.__all__` entries).

**Usages relevant to this task:**
- `conventions`: facade check via `python -c "from package import Entity"`; tests mirror
  sources at `tests/llm/test_request.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration (STEP 0)**: task 7 — facade exposure of the five names
- [ ] **Contract test** (in `tests/llm/test_request.py`; expected to fail): the design
  scenario `test_facade_exports_the_transport_machinery` — `import prettyplay.llm as llm`;
  Assertion: `all(name in llm.__all__ and getattr(llm, name) is not None for name in
  ["TransportFailureClassification", "classify_openai_failure",
  "classify_anthropic_failure", "compute_transport_pause", "send_with_retries"])`; negative
  assertion: the names are absent from `prettyplay.__all__` (root facade unchanged)
- [ ] **REPL cycle** (M4): in the venv interpreter — after editing the facade,
  `importlib.reload(prettyplay.llm)` and import the five names directly from the package;
  confirm `__all__` is complete and alphabetically ordered
- [ ] **Code**: extend the `from ._request import (...)` import in
  `prettyplay/llm/__init__.py` with the five names and insert them into `__all__`
  (alphabetical: after `"ScenarioStep"` comes `"TransportFailureClassification"`, then
  `"classify_anthropic_failure"`, `"classify_openai_failure"`, `"compute_transport_pause"`,
  then the existing `"create_provider"`, and `"send_with_retries"` after
  `"parse_group_failure_classification"`)
- [ ] Verify facade accessibility: `.venv/bin/python -c "from prettyplay.llm import
  TransportFailureClassification, classify_openai_failure, classify_anthropic_failure,
  compute_transport_pause, send_with_retries; print('facade ok')"`
- [ ] Negative facade check: `.venv/bin/python -c "import prettyplay; names =
  {'TransportFailureClassification','classify_openai_failure','classify_anthropic_failure',
  'compute_transport_pause','send_with_retries'}; assert not (names &
  set(prettyplay.__all__)); print('root facade unchanged')"`
- [ ] Run the contract test: `.venv/bin/python -m pytest tests/llm/test_request.py -q`
- [ ] Lint (STEP 7): ruff check + ruff format on `prettyplay/llm/__init__.py`,
  `tests/llm/test_request.py`
- [ ] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 8: Provider rewiring — `max_retries=0`, `send_with_retries` wrapping (TDD coding)

**Context**: `prettyplay/llm/openai_provider.py` and `prettyplay/llm/anthropic_provider.py`.
Per operation (all four of both providers — generation, classification, group diagnosis,
compliance verdict):

```
1. build request (existing builders; anthropic adds max_tokens=4096)   — unchanged
2. client := self._get_client()          # max_retries=0 inside; key check outside the loop (D3)
3. response := send_with_retries(provider label, operation label,
                                 config.llm_request_attempts,
                                 classify_openai_failure | classify_anthropic_failure,
                                 <one SDK call closure>)
4. parse/validate the answer (existing require_completion_text + parse path) — unchanged
```

The client is resolved **before** entering the retry loop — the missing-key
`LLMUnavailableError` ("llm unavailable: openai: OPENAI_API_KEY is not set") is preserved
byte-for-byte and never enters classification. The request kwargs are built once and reused
verbatim on every resend; the closure contains exactly one SDK call. The old per-operation
`try/except OpenAIError` / `except AnthropicError` → `LLMUnavailableError` blocks
(openai_provider.py:186/237/313/368, anthropic_provider.py:217/266/340/393) are **deleted**
— the loop owns the mapping now. Operation labels passed to `send_with_retries`:
`"generation"`, `"classification"`, `"group diagnosis"`, `"compliance verdict"`. Keep
`require_completion_text` exactly as is — an empty completion raises `LLMUnavailableError`
inside the operation without a resend, exactly as today (response-content recovery never
enters the loop). `ComplianceVerdictError` semantics untouched. The parsers and their
`json_repair` usage are unchanged.

**Usages relevant to this task:**
- `openai` / `anthropic` (cooks): client initialization `OpenAI(api_key=…, base_url=… or
  None, max_retries=0)` / `Anthropic(api_key=…, base_url=… or None, max_retries=0)` — both
  SDKs expose the `max_retries` constructor parameter.
- `conventions`: mocks only at the SDK boundary (`mock.patch.object(provider,
  "_get_client", …)`, patched constructors); existing helpers reused (`make_client_create`,
  `completion_answer`).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration (STEP 0)**: task 8 — provider rewiring, both providers, all four operations
- [ ] **Contract tests** (extend `tests/llm/test_openai_provider.py` /
  `tests/llm/test_anthropic_provider.py`; expected to fail): the four operations of both
  providers route their single SDK call through `send_with_retries` (assert via a patched
  `prettyplay.llm._request.send_with_retries` recorder or by retry behavior);
  `_get_client` constructs the SDK client with `max_retries=0`
- [ ] **REPL cycle** (M4): in the venv interpreter — patch the provider module's `OpenAI` /
  `Anthropic` constructor with a fake returning a client whose `create` raises
  `APIConnectionError` once then answers; call `provider.generate_step_code(...)` live with
  sleep patched; observe the WARNING, the resend, the parsed code; verify the missing-key
  path by deleting the env var (`os.environ.pop`) and calling an operation — the exact old
  message surfaces before any classification; reload the provider modules after each edit;
  migrate the verified wiring into both provider files
- [ ] **Code**: `_get_client` of both providers gains `max_retries=0` in the SDK
  constructor call
- [ ] **Code**: rewire all four operations of `OpenAIProvider` — resolve
  `client = self._get_client()` before the loop, build kwargs once, replace the direct
  `client.chat.completions.create(...)` + `except OpenAIError` block with
  `send_with_retries("openai", <operation label>, self._config.llm_request_attempts,
  classify_openai_failure, <one-call closure>)`; delete the four except blocks
- [ ] **Code**: rewire all four operations of `AnthropicProvider` identically
  (`"anthropic"` label, `classify_anthropic_failure`, `client.messages.create` closure,
  `max_tokens=4096` kept); delete its four except blocks
- [ ] **Interface verification (STEP 3)**: `.venv/bin/python -m pytest tests/llm/ -q`
- [ ] **Logic tests (STEP 4)** — the four design scenarios:
  - `test_providers_construct_clients_with_max_retries_zero` — Setup:
    `monkeypatch.setenv("OPENAI_API_KEY", "test")` / `monkeypatch.setenv("ANTHROPIC_API_KEY",
    "test")`; separately patch `prettyplay.llm.openai_provider.OpenAI` /
    `prettyplay.llm.anthropic_provider.Anthropic` to return fakes whose
    `chat.completions.create` / `messages.create` answer; retain the patched constructors;
    Input: `OpenAIProvider(Config(model="gpt-5"))` → `generate_step_code(...)` and
    `AnthropicProvider(Config(provider="anthropic", model="claude…"))` →
    `generate_step_code(...)` (minimal args as in the existing tests); Assertions:
    `openai_ctor.call_args.kwargs["max_retries"] == 0` and
    `anthropic_ctor.call_args.kwargs["max_retries"] == 0`
  - `test_provider_transient_failure_recovers_inside_one_logical_attempt` — Setup: fake
    client whose `create` raises a connection-shaped `APIConnectionError` on the first call
    and answers on the second; `Config(model="gpt-5", llm_request_attempts=2)`;
    `mock.patch.object(provider, "_get_client", return_value=client)`; sleep monkeypatched;
    Input: `provider.generate_step_code(prompt="p", …)` (full minimal arg set as in the
    existing tests); Assertions: `result == "def step(page)…\n"`,
    `client.create.call_count == 2`
  - `test_provider_permanent_failure_maps_to_llm_unavailable_immediately` — Setup: fake
    client whose `create` raises an `AuthenticationError`-shaped error;
    `Config(model="gpt-5")`; `mock.patch.object(provider, "_get_client", …)`; sleep
    recorder; Input: `provider.classify_step_failure(...)` (minimal args); Assertions:
    `pytest.raises(LLMUnavailableError)` with "openai" in `str(excinfo.value)`;
    `client.create.call_count == 1`
  - `test_missing_api_key_still_surfaces_before_the_retry_loop` — Setup:
    `monkeypatch.delenv("OPENAI_API_KEY", raising=False)`;
    `provider = OpenAIProvider(Config())`; `caplog`; sleep recorder (must stay empty);
    Input: `provider.classify_step_failure(...)`; Assertions: `pytest.raises(
    LLMUnavailableError)` with "OPENAI_API_KEY" in `str(excinfo.value)`;
    `sleep_calls == []`; `caplog.records == []`
  - Update any existing provider tests that assert the old single-send error mapping or the
    constructor kwargs — behavior-only assertions, no contract relaxation
- [ ] **Debugging (STEP 5)**: `.venv/bin/python -m pytest tests/ -x` — the whole suite;
  fix implementation until green (engine tests exercise the propagation paths unchanged)
- [ ] **Contract re-verification (STEP 6)**: all four operations of both providers wrapped;
  exactly one SDK call per closure; kwargs built once; no `except OpenAIError` /
  `except AnthropicError` blocks remain in the provider files; missing-key message
  byte-for-byte
- [ ] **Lint (STEP 7)**: ruff check + ruff format on `prettyplay/llm/openai_provider.py`,
  `prettyplay/llm/anthropic_provider.py`, `tests/llm/test_openai_provider.py`,
  `tests/llm/test_anthropic_provider.py`
- [ ] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 9: Docstring alignment — `failures` and engine cells (wording only)

**Context**: wording-only alignment, no behavioral change. The engine propagation topology
is unchanged (verified by the design: every engine site catches or propagates
`LLMUnavailableError` by type; the retries happen inside the provider before the error ever
surfaces). Docstrings still say "no retry" on the provider-unavailability paths. Also align
the `LLMUnavailableError` class docstring with the widened CODEMANIFEST annotation:

> LLM infrastructure failure: the provider service is unreachable, times out, rate-limits or
> rejects authentication — raised when the bounded transport retries of one logical LLM
> attempt are exhausted, skipped by a permanent provider rejection or cut short by an
> over-cap Retry-After. Blocks every LLM operation — code generation, step failure
> classification, group diagnosis and the compliance verdict; cached steps keep running.

**Usages relevant to this task:**
- `conventions`: Google-style docstrings; comments brief and professional.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration (STEP 0)**: task 9 — docstring alignment, zero behavior change
- [ ] **Code**: replace the "no retry" phrasing with the after-the-bounded-transport-retries
  wording on the provider-unavailability paths of `prettyplay/engine/generator.py` (≈ lines
  251, 301, 346, 453, 733), `prettyplay/engine/healer.py` (≈ 98),
  `prettyplay/engine/groups/recovery.py` (≈ 128, 228),
  `prettyplay/engine/groups/diagnosis.py` (≈ 83), `prettyplay/engine/compliance.py` (≈ 98)
- [ ] **Code**: align the `LLMUnavailableError` class docstring in
  `prettyplay/failures/errors.py` (line 331) with the widened annotation quoted above
  (keep the `Args:` section)
- [ ] **REPL cycle** (M4): in the venv interpreter — reload
  `prettyplay.failures.errors` and the touched engine modules; confirm `import
  prettyplay.engine.generator` (and the other modules) still succeeds and
  `LLMUnavailableError.__doc__` renders the new wording
- [ ] **Verification**: `.venv/bin/python -m pytest tests/failures tests/engine -q` — all
  existing behavior green (the quiet WARNING skip, the terminal propagation, the verdict
  paths are unchanged); `git diff --stat` shows only docstring lines in the touched files
- [ ] **Contract re-verification (STEP 6)**: no signature, control flow or message changes —
  diff contains docstrings only
- [ ] **Lint (STEP 7)**: ruff check + ruff format on the touched files
- [ ] **Completion (STEP 8)**: mark checkboxes; → review → approval → next task. Commit gate.

### Task 10: Integration test — transport retries stay inside one logical engine attempt (integration tests)

**Context**: the cross-cell scenario of the design — a real `OpenAIProvider` inside a real
`StepGenerator` engine cycle; the central invariant: transport retries consume no engine
budget. Per conventions, integration tests covering multiple packages go directly in
`tests/` (no subpackage) — create `tests/test_transport_retries_integration.py`.

**Usages relevant to this task:**
- `conventions`: integration tests directly in `tests/`; mocks only at the SDK and sleep
  boundaries — the engine and the provider run for real.
- `openai`: the SDK client surface faked at the constructor boundary.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Declaration (STEP 0)**: task 10 — the budget-neutrality integration scenario
- [ ] **REPL cycle** (M4): in the venv interpreter — assemble the fixtures live once (the
  fake client raising `openai.APIConnectionError` on the first `create` and answering with
  valid `def step(page) -> None:` code on the second; `Config(model="gpt-5",
  llm_request_attempts=2, generation_attempts=1)`; a `StepGenerator` with page, cache,
  reporter and settle-window fixtures) to confirm the wiring produces a `CachedStep`;
  reload the modules after any fixture adjustment; migrate the verified fixtures into the
  test file
- [ ] Create test file `tests/test_transport_retries_integration.py` (with the scenario
  below)
- [ ] Test `test_engine_budgets_untouched_by_transport_retries` — **Setup**: real
  `OpenAIProvider` with `_get_client()` patched to return a fake SDK client whose
  `chat.completions.create` raises `openai.APIConnectionError` on the first call and
  returns a completion containing valid `def step(page) -> None:` code on the second; use
  `Config(model="gpt-5", llm_request_attempts=2, generation_attempts=1)`; monkeypatch
  sleep; pass the provider to a real `StepGenerator` with page, cache, reporter and settle
  window fixtures that allow the generated code to execute and be cached; pass one known
  `StepIdentity` and `RunBudgets(generation_limit=1, healing_limit=2)` to the same
  generator. **Input**: `StepGenerator.generate(identity, step_text, step_type,
  previous_steps, group_prompt, page, attempt_history, window)` for one generation cycle.
  **Trace**: engine `try_generation(identity)` grants attempt 1 (of
  `generation_attempts=1`) → the real provider enters `send_with_retries(attempts=2)` →
  SDK send 1 fails retryably → WARNING → sleep → SDK send 2 returns a completion → the
  provider extracts code → the engine executes and caches it → `CachedStep` returned; no
  second engine attempt occurs. **Assertions**:
  `cached_step.code == expected generated code`;
  `sdk_client.chat.completions.create.call_count == 2`;
  `budgets._generation_used[identity.filename] == 1` (transport retries consumed nothing);
  `budgets.try_generation(identity) is False` (the single logical slot is exhausted)
- [ ] Run validation: `.venv/bin/python -m pytest tests/test_transport_retries_integration.py -q`
- [ ] **Full-suite confirmation**: `.venv/bin/python -m pytest tests/ -x`
- [ ] Lint (STEP 7): ruff check + ruff format on `tests/test_transport_retries_integration.py`
- [ ] **Completion (STEP 8)**: mark checkboxes; → review → approval → done. Commit gate.

---

## Validation Commands

All commands run in the project virtualenv (Task 1); Python 3.10+ compatibility required.

- `.venv/bin/python -m pytest tests/ -x`: Run all tests (the conventions' canonical command)
- `.venv/bin/python -m ruff check prettyplay/ tests/`: Lint check — zero errors
- `.venv/bin/python -m ruff format --check prettyplay/llm/ prettyplay/config/ prettyplay/failures/errors.py prettyplay/engine/generator.py prettyplay/engine/healer.py prettyplay/engine/compliance.py prettyplay/engine/groups/ tests/llm/ tests/config/ tests/test_transport_retries_integration.py`: Format check on every file touched by this plan
- `.venv/bin/python -c "from prettyplay.llm import TransportFailureClassification, classify_openai_failure, classify_anthropic_failure, compute_transport_pause, send_with_retries; print('facade ok')"`: Facade accessibility of the five new names
- `.venv/bin/python -c "import prettyplay; names = {'TransportFailureClassification','classify_openai_failure','classify_anthropic_failure','compute_transport_pause','send_with_retries'}; assert not (names & set(prettyplay.__all__)); print('root facade unchanged')"`: Negative facade check — the root facade is unchanged
- `.venv/bin/python -c "from prettyplay.config import Config; assert Config().llm_request_attempts == 3; print('config ok')"`: The new setting default
- `goga lint`: Cell/manifest consistency (11 cells, 0 errors expected)
- `goga schema`: Dependency map unchanged; the five new types visible at `_request.py`
- `goga contract`: Contract conformance once the implementation exists

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
- [ ] Every contract entity is accessible from the facade (the five new names from
      `prettyplay.llm`; the root facade unchanged)
- [ ] Properties and methods match the declared API (kw_only model, computed `retryable`,
      generic `send_with_retries`)
- [ ] Descriptions are reflected in behavior (the classification ladders, the delay policy,
      the terminal branch order, the message shapes, the one-WARNING-per-retry logging)
- [ ] Contract dependencies are met (`LLMUnavailableError` chaining; `Config` feeds
      `attempts`)
- [ ] All 30 design test scenarios exist and pass (15 positive, 9 negative, 6 edge)
- [ ] Every coding task followed the TDD workflow (contract tests → code → verification →
      logic tests → debugging → re-verification → lint)
- [ ] Every coding task ran its implementation phase as a REPL cycle (M4: evaluate live →
      hot reload → migrate to source); nothing scratch was committed
- [ ] The Mandatory Rules (M1–M4) were honored in every task: coding style, test rules,
      ruff lint/format at every stage, and the commit gate before every local commit
- [ ] Integration tests exist where cross-entity scenarios require them (Task 10)
- [ ] No package boundary was expanded; no new cells
- [ ] `CODEMANIFEST` files were not modified (contract is read-only); the supersession
      annotation of `prettyplay/llm/CODEMANIFEST` stays verbatim
- [ ] All validation commands pass (`pytest tests/ -x`, `ruff check`, `ruff format
      --check`, facade checks, `goga lint`, `goga schema`, `goga contract`)
- [ ] Every Usages entry is exercised in at least one task (`conventions` everywhere via
      M1–M4; `openai`/`anthropic` in Tasks 4 and 8; `json_repair` untouched in Task 8)

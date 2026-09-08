# Prettyplay MVP — Human-Language UI Tests with Step Cache and Self-Healing

> Task for branch `master`. Sources: PRD `.goga/history/2026/the-first-version/prd.md` (product definition) and
> ADR `.goga/history/2026/the-first-version/adr.md` (14 approved technical decisions). Where this document and
> the ADR disagree, the ADR wins.

## Current State

- `prettyplay/` is an empty Python package (only `__init__.py`); `dependencies = []` in `pyproject.toml`.
- No cells or CODEMANIFEST files exist (`goga schema` returns `[]`) — the architecture is designed from scratch in the next stage.
- Product definition is validated and approved (PRD); all technical decisions are approved and recorded (ADR).
- Project conventions (`.goga/usages/conventions.md`) are mandatory: pydantic `kw_only=True` models, relative intra-package imports, Google-style docstrings, structured `logging`, pytest tests mirroring source layout, every dependency pinned with a minimum version in `pyproject.toml`.

## Description

Implement the prettyplay MVP library: UI tests written as natural-language sentences inside ordinary Python tests, with an LLM-generated step cache stored in the repository and automatic self-healing — running entirely on the user's infrastructure inside their existing runner and CI.

Functional parts:

1. **Step API (framework-agnostic).** A main integrator object owns the browser context of the test and the cache addressing (mandatory explicit `cache_key`; optional `cache_path` — part of the cache address). Methods for action steps and assertion steps take free-form natural-language text (RU/EN/other). Step texts are visible in test output via standard `logging` (logger `prettyplay`), so the suite reads as a plain-language scenario; for integrators, step and healing events are also exposed through a thin callback hooks interface — no own event bus (R1, R4, R5, R7, ADR-12).
2. **Driver facade (Playwright, sync-only).** A narrow facade over Playwright sync API: browser matrix {Chromium, Firefox, WebKit} selected from configuration, one isolated browser context per test, locators with auto-wait, `aria_snapshot()` as the primary structured page representation for the LLM (ADR-1, ADR-2, ADR-7, R6).
3. **Step cache (repository artifact).** One `.py` file per step with metadata (step text, `cache_key`, date); filename is a deterministic function of the key. Key = `cache_key` + step type (action/assertion) + hash of the normalized step text (Unicode NFC, trim, whitespace collapse, casefold — RU/EN translation of the same intent is a different step). Root defaults to `<repo>/.prettyplay/cache/`, configurable via `cache_root`. Writes are atomic (unique tmp file + `os.replace`; short retry on Windows, then skip that step's write with a loud message). Read-only environments (CI) are best-effort: cache is always read, unsaved results are loudly marked "not saved: read-only cache". Cached runs never call the LLM (ADR-3, ADR-4, ADR-5, ADR-10, ADR-11, R8–R13).
4. **Generation engine (LLM).** On first execution of an unknown step: generate executable Python code through the facade via LLM, execute it against the real application; on failure — re-generate with the fresh error and snapshot. Inputs: a11y snapshot, step text, previous step texts of the test; optional screenshot behind the project flag `send_screenshots`. Budget: ≤ 3 attempts, shared per step per run. Providers: official `openai` and `anthropic` SDKs — both hard dependencies; provider selection and models (`model`, optional `generation_model` / `classification_model`) come from configuration (ADR-6, ADR-7, ADR-8).
5. **Healing and failure taxonomy.** On a cached step failure: classify the error — healable rot (UI changed) → regenerate from the current page and retry, on success update the cache and loudly report the healing; real product defect → loud test failure; incurable (budget exhausted, text no longer matches reality, ambiguity) → explicit exception with step, reason, recommended action. Healing budget ≤ 2 attempts, shared with the step's run budget. LLM unavailability blocks only generation/healing (explicit infrastructure error) — cached steps keep running. Anti-masking: healing never turns a real product defect into a green test (R14–R20, ADR-8).
6. **Project configuration.** `[tool.prettyplay]` section in `pyproject.toml`: browser, `model` + optional `generation_model`/`classification_model`, `base_url`, `cache_root`, attempt budgets, `send_screenshots`; every setting has an env override for CI. Secrets only from environment variables (the config may name the variable) (ADR-13).
7. **Documented limitation.** Secrets and test data inside step text are unsupported in MVP — step text lands in the cache, reports and LLM requests (ADR-14).

## Scope

**In scope:**

- Framework-agnostic step API (`action` / `assertion`) sufficient for an integrator to wire the library into any popular Python test framework.
- Natural-language step → automatically generated executable code for web UI.
- Persistent per-step code cache in the repository, fully managed by the product.
- Cache reuse without LLM in any environment (local, CI), including read-only best-effort mode.
- Agent self-healing: error classification, bounded regeneration, healed code written back to the cache, loud healing visibility.
- Distinct failure taxonomy (product defect / incurable step / infrastructure) with actionable messages.
- Project-level configuration (`[tool.prettyplay]` + env overrides); user's LLM keys.
- Playwright sync-only driver facade with per-test isolated browser contexts.
- Observability: logger `prettyplay` + a thin callback hooks interface (no own event bus).
- User-facing documentation stating the ADR-14 limitation (no secrets in step text).

**Out of scope:**

- Framework integrations/plugins (pytest plugin, unittest base classes) — wiring is the integrator's job.
- Gherkin/markdown/no-code authoring formats — steps live inside Python tests.
- Async execution (future extension, ADR-2).
- Driver abstraction beyond Playwright (e.g. Selenium) (ADR-1).
- Cache invalidation by library version; version field in cache files (ADR-9).
- Secrets/test-data substitution into step text (ADR-14).
- Mobile, native, desktop testing; visual (screenshot-diff) and performance testing.
- Test recording, IDE plugins, authoring UI, reporting portal/analytics.
- Parallel execution as a library feature (runner's responsibility, R21).

## Acceptance Criteria

End-to-end (PRD success criteria):

1. A realistic web scenario (e.g. login + main action + assertion) authored entirely in sentences through the API runs green on the first run after generation; not a single line of driver code written by the engineer.
2. With LLM keys removed, the cached suite passes in a fresh environment (another machine / CI) using only the repository — no LLM calls on the cached path.
3. After an intentional UI change (element renamed/moved/restructured), the affected step heals during the run: the test passes, the healing is loudly reported (which step, why rot, what changed), the cache in the repository is updated.
4. A real functional regression fails the suite as a product defect with a clear message — and is never healed into green.
5. A non-healable step (text no longer matches reality / attempt budget exhausted) raises a distinct exception: step, reason, recommended action.
6. With the LLM unavailable, cached steps execute; generation/healing attempts end with an explicit infrastructure error.
7. The suite runs by the standard runner command after the integrator wires the API in a few lines; step texts read as a plain-language scenario in the output.
8. Tests yield identical outcomes regardless of execution order (no cross-test state leaks through the library).

ADR-specific verifiable conditions:

- Step identity: same normalized text + same `cache_key` + same step type resolves to one cached step reused across tests; different `cache_key`, different step type, or different language (RU vs EN) resolves to a different step (cache miss → regeneration, not an error).
- Normalization: "Нажать Войти" and "нажать  войти " resolve to the same step.
- Budgets: generation ≤ 3 attempts, healing ≤ 2 attempts, shared per step within a run (not reset between tests); exhaustion yields the explicit incurable failure.
- Cache writes are atomic (`os.replace`); concurrent writers on one step do not corrupt the file; on Windows a busy target retries briefly, then skips the write with a loud message without failing the run.
- In a read-only cache directory the run completes correctly and unsaved steps are loudly marked.
- Configuration is read from `[tool.prettyplay]` with env overrides; no LLM key is ever read from a repository file.
- Facade check passes: `python -c "from prettyplay import PrettyTest"` (or the final type name fixed by the contract).
- User-facing documentation states the no-secrets-in-step-text limitation (ADR-14).

## Stack

- **Frameworks:** none — a framework-agnostic library; no test-framework plugins.
- **Libraries:** `playwright>=1.49` (hard; first version with `aria_snapshot()`), `openai>=1.0` (hard; v2 client with `chat.completions`), `anthropic>=0.30` (hard; messages API), `pydantic>=2.0` (models and configuration; v2 `ConfigDict`/`kw_only`), `tomli>=2.0; python_version < "3.11"` (TOML reading on 3.10; 3.11+ uses stdlib `tomllib`). Minimum versions are floors: they may be raised at implementation, never lowered.
- **Infrastructure:** none required by the product — stdlib `logging` (logger `prettyplay`), atomic writes via `os.replace`, hashing/normalization via `hashlib`/`unicodedata`. LLM service and Playwright browser binaries live on user infrastructure.
- **Test tooling (already declared):** pytest, pytest-cov, pytest-mock, ruff (Python ≥ 3.10, `pyproject.toml`-based configuration).

## External Dependencies

| Component  | Usage file                          | Status  |
|------------|-------------------------------------|---------|
| playwright | `.goga/usages/cooks/playwright.md`  | created |
| openai     | `.goga/usages/cooks/openai.md`      | created |
| anthropic  | `.goga/usages/cooks/anthropic.md`   | created |
| pydantic   | `.goga/usages/cooks/pydantic.md`    | created |
| tomli      | `.goga/usages/cooks/pydantic.md` (TOML loading section) | covered |

pytest, ruff and logging are covered by the existing `.goga/usages/conventions.md`.

## Risks and Constraints

- **Backward-compatible facade (ADR-9).** The cache is not invalidated by library version, so the driver facade the step code is generated against must stay backward compatible across library releases; breaking facade changes require a migration strategy (open question, out of MVP).
- **Sync-only execution (ADR-2).** Async runners are unsupported in MVP.
- **LLM quality bounds generation/healing quality** (PRD constraint); attempt budgets (3/2) and the shared per-run budget guard against infinite loops.
- **Parallel cache writes (ADR-10).** Atomic `os.replace`, last writer wins; Windows gets a short retry then skips the write loudly. No file locking.
- **Read-only environments (ADR-11).** Best-effort writes; unsaved steps loudly marked. Team workflow: generate locally → commit cache → CI runs fully from cache without LLM keys.
- **Trust boundary (ADR-3).** The repository is the trust boundary; generated code is constrained to the narrow facade by generation prompt rules — no code validator in MVP.
- **Secrets in step text unsupported (ADR-14)** — must be stated in user-facing documentation.
- **Python 3.10 compatibility:** no stdlib `tomllib` — the conditional `tomli` dependency covers it.
- **Conventions apply throughout:** pydantic `kw_only=True`, relative imports, Google docstrings, structured logging, ruff (line length 120, max complexity 10), pytest layout mirroring source.

## Scope Estimate

Single task (approved by the user, no decomposition at task level). Scale: ~7 responsibility zones — configuration; step API / main object; Playwright driver facade; step cache store; LLM generation engine (2 providers); healing/classification with failure taxonomy; observability (logging + hooks). The zones do not deliver independent user value separately (cache without generation cannot fill; generation without cache breaks the determinism criterion), so the MVP is delivered as one task. Decomposition into cells is the next stage (brainstorm), which receives the zone list above as input material — not as a fixed partition.

## Existing Architecture

Greenfield: no cells exist (`goga schema` → `[]`), no code beyond the empty `prettyplay/__init__.py`. The next stage designs cells bottom-up from leaves to root. Base annotations for all future CODEMANIFEST files: use `conventions` (`.goga/usages/conventions.md`) for code writing rules and testing; the created cooks (`playwright`, `openai`, `anthropic`, `pydantic`) connect per-cell as needed via the `Usages` directive.

## Notes

- Source documents: PRD `.goga/history/2026/the-first-version/prd.md` (requirements R1–R21, success criteria), ADR `.goga/history/2026/the-first-version/adr.md` (ADR-1…ADR-14 — authoritative on every conflict).
- Illustrative target API — **form illustration, not a contract**; final signatures are fixed by the CODEMANIFEST design stage:

```python
from prettyplay import PrettyTest

t = PrettyTest("login-flow")            # cache_key: mandatory explicit context
t.action("открыть страницу логина")
t.action("ввести логин и пароль")
t.action('нажать "Войти"')
t.assertion('появилась надпись "Добро пожаловать"')
```

- Cache addressing: root `<repo>/.prettyplay/cache/` (configurable `cache_root`); `cache_path` is part of the address (steps live in the given subdirectory; reuse happens within one subdirectory; default — shared root, so equal `cache_key` steps are reused across tests).
- Healing inputs: existing step code + error + fresh a11y snapshot (+ optional screenshot when `send_screenshots` is on).
- Generated step code works only through the driver facade; it must not depend on the LLM provider.
- The user-facing documentation must state the ADR-14 limitation (no secrets in step text).
- Acceptance verification runs against a small local fixture web application owned by the library's test suite (login + main action + assertion scenario; UI elements can be intentionally changed and behavior broken to verify healing and anti-masking). The fixture is test infrastructure, not a product deliverable.
- Decisions made at task formulation (2026-08-26): stack approved with conditional `tomli` for Python 3.10; 4 cooks created; single-task scope.

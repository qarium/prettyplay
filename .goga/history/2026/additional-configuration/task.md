# Prettyplay Configuration Extension: Per-Test Runtime, PrettyConfig with Layered Merging, Generation Instructions, Universal Locators, Remote Browser

## Current State

The current state of the library (facts collected at technical discovery from the CODEMANIFESTs of config / driver / engine / cache / the root prettyplay):

1. **The config is not passed into the test.** `PrettyTest(cache_key, cache_path)` accepts no settings; everything is resolved by the process-wide singleton `get_runtime()` → `PrettyplayRuntime` — one browser process, one LLM provider, one budget registry for the whole process.
2. **Budgets are "per whole run".** `RunBudgets` lives for the whole process; a step reused by N tests shares one attempt budget — a documented invariant of the cache cell.
3. **No user generation instructions.** The generation system prompt is fixed (the engine cell's `generation_prompt` usage); passing a per-project style for generated code ("prefer data-test-id") into the request is impossible.
4. **The facade is limited to three locators.** `find_by_role` / `find_by_label` / `find_by_text` — no locating by data attributes, CSS selectors or XPath; generated code cannot search by test-id.
5. **Local browser only.** `DriverSession` always does launch(); there is no `browser_endpoint` setting (the remote-connection section was already added to the playwright usage at the formulation stage — the code does not follow the usage yet).
6. **No programmatic settings override.** `load_config` reads pyproject+env; no merging with explicitly passed values exists.

## Description

Implement the five approved ADR decisions of the `additional-configuration` topic
(`.goga/history/2026/additional-configuration/adr.md`) in the existing prettyplay cells — a single configuration-extension release:

- **ADR-1. Per-test runtime.** Every `PrettyTest` builds its own runtime: its own configuration instance, its own browser process, its own provider, its own attempt budgets. The process-wide singleton is gone; `get_runtime()` leaves the public contract (an internal facade detail). Attempt budgets are per-test — the invariant "budgets are not reset between tests" is reversed. Every runtime registers its own shutdown in atexit — all browsers stop by process exit; laziness is preserved — constructing `PrettyTest` is cheap, the browser starts on the first step.
- **ADR-2. PrettyConfig — a single settings model and layered merging.** `PrettyConfig` is the public name of the full settings model (an alias of the config cell's `Config`), not a separate subset object. A config passed into `PrettyTest` sets only explicitly given values; unset/empty fields are resolved by layered merging against pyproject+env. One model — one place of validation; every new setting is automatically available along the whole pyproject → env → `PrettyConfig` chain.
- **ADR-3. The `generation_prompt` setting — user instructions into generation requests.** A string setting (env `PRETTYPLAY_GENERATION_PROMPT`, default empty). A non-empty value lands as a separate **USER INSTRUCTIONS** block in generation and regeneration (healing) requests; the fixed system prompt does not change; failure classification is untouched. The instructions are not part of the cache address: changing the instructions does not invalidate the cache, a cached step is not regenerated. The engine's internal usage `generation_prompt` is renamed to `system_prompt`, freeing the term for the public setting.
- **ADR-4. Facade: universal locators.** The page facade is extended with the ability to locate by any data attributes, CSS selectors and XPath. The system prompt's default priority (role → text → label) does not change — accessibility remains the global default, the priority is tuned per-project by user instructions. The API surface listing and the facade usage change synchronously — the model will see the new locators automatically.
- **ADR-5. Remote execution via the Playwright ws endpoint.** A string setting `browser_endpoint` (env `PRETTYPLAY_BROWSER_ENDPOINT`, default empty = local launch, as today). An endpoint is set → the driver connects (Playwright connect) instead of launching; `headless` is ignored (window visibility is controlled by the server); `browser` still selects the engine type to connect to. An endpoint URL in the config is acceptable (an address, not a key); rotation in CI — via the env override. Combined with ADR-1, every test can connect to its own endpoint.

### Target usage form (examples are a form, not a contract; names are fixed by brainstorm)

```python
from prettyplay import PrettyTest, PrettyConfig

# per-test config: explicitly set wins, the rest resolves from pyproject+env
test = PrettyTest(
    cache_key="login-flow",
    config=PrettyConfig(
        browser="firefox",
        generation_prompt="Отдавай приоритет data-test-id атрибутам",
        browser_endpoint="ws://ci-grid:3000/playwright/chromium",
    ),
)

with test as t:
    t.action("Открыть страницу логина")
    t.assertion("Форма логина видна")
```

```python
# new facade locators — available to generated step code
page.find_by_attribute("data-test-id", "submit-button")
page.find_by_css("form > button.primary")
page.find_by_xpath("//button[@type='submit']")
```

```toml
# pyproject.toml — the same settings via file
[tool.prettyplay]
generation_prompt = "Отдавай приоритет data-test-id атрибутам"
browser_endpoint = "ws://ci-grid:3000/playwright/chromium"
```

## Scope

**In scope:**

- `PrettyTest` accepts a config; every test builds its own runtime (configuration, browser process, provider, budgets); `get_runtime()` is abolished as a public contract (ADR-1)
- Per-test attempt budgets: reset for every test; protection from infinite retries within a test (ADR-1)
- Atexit shutdown of every runtime: all browsers stop by process exit; idempotent close (ADR-1)
- `PrettyConfig` — the public name of the `Config` model; layered merging: explicitly set wins, unset/empty falls back to pyproject+env; uniform validation of file-based and programmatic values (ADR-2)
- The `generation_prompt` setting (TOML + env `PRETTYPLAY_GENERATION_PROMPT`, default empty); the USER INSTRUCTIONS block in generation and regeneration requests (ADR-3)
- Renaming the engine usage `generation_prompt` → `system_prompt` (ADR-3)
- Facade locators by data attributes, CSS, XPath + synchronous update of the API surface listing in the generation usage (ADR-4)
- The `browser_endpoint` setting (TOML + env `PRETTYPLAY_BROWSER_ENDPOINT`, default empty); connect instead of launch when an endpoint is set; `headless` ignored on connect (ADR-5)
- Updating cell-level usages: `driver/.usages/facade.md`, `prettyplay/.usages/lifecycle.md`, `config/.usages/configuration.md`
- Updating the project playwright usage (remote connection) — applied at the formulation stage
- Tests per the project conventions (`pytest`, `ruff`)

**Out of scope:**

- CDP connection (`connect_over_cdp` to a running Chrome with a debugging port) — deferred as a future extension via a separate field (ADR-5)
- Keying runtimes by effective config (tests with an identical config share one browser) — rejected (ADR-1)
- A private runtime only when a config is explicitly passed — rejected: one behavior semantics (ADR-1)
- Including an instructions hash in the step address / invalidating the cache on instruction change — rejected (ADR-3)
- Instructions into failure classification and into the cache address — rejected (ADR-3)
- Changing the system prompt's default locator priority to test-id-first — rejected: the global default is conservative (ADR-4)
- Pasting the instructions into the system prompt — rejected (ADR-3)
- Contract design (signatures, CODEMANIFEST changes) — the brainstorm stage

## Acceptance Criteria

- Two `PrettyTest`s in one process: each with its own browser process and its own budgets; results do not depend on test execution order
- A step reused by N tests gets N× attempts per launch: budgets reset for every test; exhausting the budget within one test still raises `IncurableStepError`
- All launched browsers stop by process exit without explicit closes (atexit per runtime); a repeated close is safe
- Constructing `PrettyTest` does not launch the browser and does not require LLM credentials; the browser process starts lazily on the test's first step
- `PrettyTest` without a config works as today (pyproject+env); with a config: an explicitly set value wins, unset/empty resolves from pyproject+env (verify on `base_url`/`model` set only in the file)
- `get_runtime()` is absent from the package's public export; `PrettyConfig` is available in the package's public export (an alias of the full `Config` model)
- `[tool.prettyplay] generation_prompt` / env `PRETTYPLAY_GENERATION_PROMPT`: a non-empty value → the USER INSTRUCTIONS block in generation and regeneration requests; empty → requests without the block; classification without the block under any setting
- Changing the instructions does not invalidate the cache: a cached step executes without regeneration; the instructions are visible only on fresh generation
- The engine usage is named `system_prompt`; the public setting is `generation_prompt`; there is no name collision in the manifest
- Generated code can locate by data attributes, CSS and XPath through the facade; the API surface listing in requests contains the new locators mirroring `facade.md`; the prompt's default priority role → text → label is unchanged
- `browser_endpoint` set → connection over ws instead of local launch; empty → local launch as today; `headless` is ignored on connection; `browser` selects the engine type
- Facade backward compatibility: extension only, no renames or removals; cached steps keep working
- `ruff check` and `pytest tests/ -x` green; Python 3.10+

## Stack

- **Frameworks:** — (a pure Python library, does not touch runners)
- **Libraries:** pydantic v2 (the settings model: the new `generation_prompt`, `browser_endpoint` fields; the layered-merging mechanics on top of a model with empty defaults), Playwright sync API (data-attr/CSS/XPath locators, connect over a ws endpoint), openai SDK and anthropic SDK — the SDKs themselves unchanged (USER INSTRUCTIONS is request content; the `LlmProvider` port contract is extended with the new instructions input, see Existing Architecture)
- **Infrastructure:** an external browser ws endpoint (optional; provided by the user — e.g. a Playwright Server, a hosted grid); no new dependencies in `pyproject.toml`

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| playwright | `.goga/usages/cooks/playwright.md` | updated (per-test browser process in Lifecycle; the remote connect section — applied at the formulation stage) |
| pydantic | `.goga/usages/cooks/pydantic.md` | updated (the `generation_prompt`/`browser_endpoint` fields in the schema; the layered-merging section — applied at the formulation stage) |
| openai | `.goga/usages/cooks/openai.md` | existing |
| anthropic | `.goga/usages/cooks/anthropic.md` | existing |

## Risks and Constraints

- **Abolishing the public `get_runtime()` is a deliberate breaking change.** There are no external consumers (a discovery fact); interactive sessions using `get_runtime().close()` from `lifecycle.md` switch to closing test objects — update the usage in the task
- **The price of a per-test browser:** ~a second to launch a browser per test — the accepted price of the isolation decision (ADR-1)
- **Atexit accumulation:** every runtime registers its own shutdown — N tests = N atexit hooks; every shutdown is idempotent and safe in a not-launched state
- **Driver threads:** per-test runtime → per-test driver thread; strictly sequential driving is preserved within each test; interactive hosts (IPython/Jupyter) keep working
- **Distinguishing "explicitly set" from "unset":** a model with empty defaults — an empty field means "take from pyproject+env"; the project's pydantic-model convention (empty defaults, `None` only for explicit absence) makes the distinction mechanical
- **Synchrony of the two surface copies:** the page API listing mirrors `driver/.usages/facade.md` — they are edited only together, otherwise the model will not see the new locators
- **The `generation_prompt` name collision** is resolved by renaming the engine usage to `system_prompt` — before the rename one name would be doing two jobs in one manifest
- **Remote tests:** a real ws endpoint is unavailable in the test environment — mocks of external boundaries and `pytest.mark.skipif` per the project conventions
- Python 3.10+; project conventions (`conventions`) are mandatory

## Scope Estimate

One task (user's decision). Scale: 5 ADRs, 6 cells, ~13 affected types — one architectural composition refactor (per-test runtime) + point extensions. Splitting rejected: the change clusters intersect densely across cells (the runtime consumes merging; ADR-3/ADR-5 add settings to one model and one constructor; ADR-3/ADR-4 change one generation usage) — subtasks would edit the same cells in parallel and carry no standalone value. The whole release ships together on the `additional-configuration` branch. The next stage (brainstorm) will distribute the contract edits across cells.

## Existing Architecture

The affected cells and the nature of changes:

- `prettyplay` (root facade) — `PrettyTest`: the configuration parameter, the test's own runtime; `PrettyplayRuntime`: from process-wide singleton to per-test composition; `get_runtime`: abolished as a public contract; `StepExecutor`: per-test budgets; updating `.usages/lifecycle.md`
- `prettyplay/config` — `Config`: the `generation_prompt`, `browser_endpoint` fields, the public alias `PrettyConfig`; `load_config`: layered merging with explicitly passed values; updating `.usages/configuration.md`
- `prettyplay/driver` — `DriverSession`: the lifecycle changes from run-scoped to per-test (the session is owned by the test's runtime); the cell's global annotation "one browser for the whole run" and the facade-usage rule "the browser is shared per run" are reversed; connect over the ws endpoint when the setting is set, local launch otherwise; `open_context` remains the source of the isolated page context; `PageFacade`/`LocatorFacade`: locators by data attributes, CSS, XPath; updating `.usages/facade.md`
- `prettyplay/engine` — the usage `generation_prompt` is renamed to `system_prompt`; the USER INSTRUCTIONS block in generation/regeneration requests; synchronous extension of the API surface listing
- `prettyplay/cache` — `RunBudgets`: per-test semantics, the invariant "budgets are not reset between tests" is reversed; cache addressing is unchanged
- `prettyplay/llm` — `LlmProvider.generate_step_code` and both provider implementations (`OpenAiProvider`, `AnthropicProvider`): the new generation-instructions input in full parity — the USER INSTRUCTIONS block is assembled into the user content of the request by the providers; there is no separate slot in the port's fixed input list today; `classify_failure` does not change; `FailureClassification`, `create_provider` — unchanged
- `prettyplay/failures`, `prettyplay/reporting` — untouched

## Notes

- User's decisions at formulation: the formulation confirmed in full (q1-A); target API usage examples are included in the task — a form, not a contract (q2-A); the stack and the usage-file plan confirmed (q3-A); the `playwright.md` and `pydantic.md` edits applied at this stage (q4-A); one task without decomposition (q5-A)
- Open details for the next stage (brainstorm), not fixed in the ADRs: the signature of `PrettyTest` with a config (parameter position/name); the merging mechanics at the contract level (how `load_config` participates in resolving unset fields); the signatures of the new facade locators (method names, arity); the exact format of the USER INSTRUCTIONS block in the request; the fate of `PrettyplayRuntime` in the manifest (mutation vs renaming); the behavior of interactive sessions without the public `get_runtime()`
- Env names confirmed by the ADR: `PRETTYPLAY_GENERATION_PROMPT`, `PRETTYPLAY_BROWSER_ENDPOINT`
- Task input: ADR `.goga/history/2026/additional-configuration/adr.md` (approved 09.09.2026, five decisions + terms)

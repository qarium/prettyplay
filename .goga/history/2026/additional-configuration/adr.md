# Prettyplay Configuration Extension Decisions (branch `additional-configuration`)

> Recorded from the technical discovery interview of 09.09.2026. Status: **approved**.
> The topic was initiated by three user wishes formulated in the file-based dialog (no PRD/TODO was created for the topic). Facts about the current architecture were collected from `goga schema` and the CODEMANIFESTs of the config, driver, engine, cache cells. Each entry records the fact of the decision and its "why".

## Terms

- **Per-test runtime** — a runtime (a configuration instance, a browser process, an LLM provider, attempt budgets) owned by one `PrettyTest`, not by the whole process.
- **PrettyConfig** — the public name of prettyplay's single full settings model (an alias of the config cell's `Config`); passed into `PrettyTest` for per-test overrides.
- **Layered merging** — the rule for resolving a test's settings: a value explicitly set in `PrettyConfig` wins; an unset/empty one falls back to pyproject+env.
- **Generation user instructions** — a `generation_prompt` settings string that lands in generation and regeneration requests as a separate USER INSTRUCTIONS block; it governs the style of the generated code (user's example: "prefer data-test-id attributes"), not failure diagnostics.
- **`browser_endpoint`** — the ws endpoint address of a remote browser; an empty value means local launch, as today.

---

## ADR-1. Per-test runtime: every test gets its own browser and its own configuration

Every `PrettyTest` builds its own runtime: its own configuration instance, its own browser process, its own provider, its own attempt budgets. The process-wide singleton is gone; `get_runtime()` leaves the public contract (an internal facade detail). Attempt budgets become per-test — the documented invariant "budgets are not reset between tests" is reversed. The user's choice: test isolation matters more than the economy of one browser per launch — "every test gets its own runtime, its own configuration instance and its own browser instance".

**Alternatives considered:** keying runtimes by effective config (tests with an identical config share one browser) — rejected by the user: the runtime belongs to the test, not the config; a private runtime only when a config is explicitly passed — rejected: two behavior semantics in one library.

**Consequences:** launching a browser per test (~a second) is the accepted price; a step reused by N tests gets N× attempts per launch — protection from infinite retries is preserved within each test; every runtime registers its own shutdown in atexit — all browsers stop by process exit; laziness is preserved — constructing `PrettyTest` is cheap, the browser starts on the first step.

## ADR-2. PrettyConfig — a single settings model and layered merging

`PrettyConfig` is the public name of the same full settings model (an alias of `Config`), not a separate lightweight override object. A config passed into `PrettyTest` sets only explicitly given values; unset/empty fields are resolved by layered merging against pyproject+env. One model — one place of validation and one resolution chain; "to pass a config" intuitively means "to override the specific", whereas with full replacement the `base_url`/`model` set in pyproject would be silently lost.

**Alternatives considered:** a separate subset object for per-test overrides — rejected: divergence of two settings models; full replacement without merging — rejected: silent loss of file settings.

**Consequences:** every new setting is automatically available along the whole pyproject → env → `PrettyConfig` chain; value validation is uniform for file-based and programmatic settings.

## ADR-3. The `generation_prompt` setting — user instructions into generation requests

A string setting `generation_prompt` appears (env `PRETTYPLAY_GENERATION_PROMPT`, default empty). A non-empty value lands as a separate **USER INSTRUCTIONS** block in generation and regeneration (healing) requests; the fixed system prompt does not change; failure classification is untouched (the instructions are about code style, classification is about diagnostics). The instructions are **not part of** the cache address: the cache is a repository of verified code — a working cached step is not regenerated because the style changed — the user's choice.

**Alternatives considered:** pasting the instructions into the system prompt — rejected: the system prompt is a stable product, the instructions are variable request data; including an instructions hash in the step address — rejected by the user: changing the instructions must not invalidate the cache; extending to classification — rejected.

**Consequences:** a change of instructions is visible only on fresh generation — cached steps stay as they are until a manual cache cleanup or regeneration by healing; the engine's internal usage named `generation_prompt` (the fixed system prompt) is renamed to `system_prompt`, freeing the term for the public setting — otherwise one name would be doing two jobs within one manifest.

## ADR-4. Facade: universal locators — data attributes, CSS, XPath

The page facade is extended with the ability to locate by any data attributes, CSS selectors and XPath. The system prompt's default priority (role → text → label) does not change — accessibility remains the global default, the priority is tuned per-project by user instructions. The topic's flagship scenario ("prefer data-test-id") requires the generated code to *be able* to search by test-id: the code works only through the facade, instructions alone without extending the surface are insufficient.

**Alternatives considered:** changing the prompt's default priority to test-id-first — rejected: the global default is conservative, the priority is a project decision; limiting to instructions without extending the facade — rejected: the example is unfulfillable.

**Consequences:** the backward-compatibility contract is honored — extend only, no renames or removals; the API surface is sent into requests from the facade usage, the model will see the new locators automatically (the listing and the usage change together).

## ADR-5. Remote execution via the Playwright ws endpoint

A string setting `browser_endpoint` appears (env `PRETTYPLAY_BROWSER_ENDPOINT`, default empty = local launch, as today). The mechanism is the Playwright ws endpoint (connect). An endpoint is set → the driver **connects** instead of launching locally; `headless` is ignored (window visibility is controlled by the server); `browser` still selects the engine type to connect to. An endpoint URL in the config is acceptable — it is an address, not a key; rotation in CI — via the env override (the user's remark "don't forget env" is covered by the general rule "every setting has an env override").

**Alternatives considered:** CDP connection (`connect_over_cdp` to a running Chrome with a debugging port) — deferred as a future extension via a separate field; both mechanisms at once — rejected: extra surface before a real need.

**Consequences:** the playwright usage (`.goga/usages/cooks/playwright.md`) gains a section on remote connection — remote is not described there today; combined with ADR-1, every test can connect to its own endpoint.

---

## Interview summary

Three user wishes → solutions: a config in `PrettyTest` → ADR-1 + ADR-2; user input into the generation prompt → ADR-3 + ADR-4 (the data-test-id example pulled the facade extension along); playwright to remote execution → ADR-5. All decisions were approved by the user in the file-based dialog (questions q1–q5 in the pipeline stage directory): q1 — task formulation, q2 — a round of 10 frontier questions, q3 — a round of 6 (consequences of the per-test runtime), q4–q5 — the `generation_prompt` term collision and final confirmation. Contract design (signatures, CODEMANIFEST changes) — outside discovery scope.

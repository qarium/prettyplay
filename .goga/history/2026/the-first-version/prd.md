# Prettyplay: Human-Language UI Tests with Self-Healing (MVP)

> PRD for the `master` branch. The product definition is validated and contains no conflicts.

## Problem

Web product teams need regular automated regression testing of web interfaces, embedded in their existing Python testing stack (pytest/unittest). Today this outcome is unattainable for most teams for two reasons:

1. **Accessibility.** Writing a UI automated test requires programming and knowledge of the browser driver API. Non-programmers (manual QA, analysts, product managers) are entirely excluded from automation; only an engineer can write tests.
2. **Cost of maintenance.** Hand-written automated tests are slow to create and brittle: every change to the UI structure or texts (selectors, labels, layout) breaks them, and each breakage demands engineering time to diagnose and fix cryptic selector errors.

Current approaches are mixed and depend on a company's willingness to invest in staff and infrastructure: some teams maintain a hand-written suite on Selenium/Playwright, others test manually. Existing AI testing tools are commercial, closed, laden with vendor lock-in, and offer no integration into the team's own stack.

The net result: automation coverage stays low, regression is checked slowly and manually, test maintenance eats engineering capacity. The product is built as an **open source** solution without vendor lock-in.

## Users

**The primary user is an engineer (QA automation / developer) who writes web UI tests.**

- Works inside the team's existing Python stack (pytest/unittest); writes and maintains a suite of web UI tests, runs it locally during development and in CI on every change.
- In the MVP, this engineer **writes steps** in human language — inside ordinary tests — and also wires the library into their framework as the integrator.
- Goal: write test steps as sentences rather than driver code; get a stable suite that does not fall apart when the UI changes; on failure — a comprehensible signal, not a cryptic selector error.
- Expectations: the step text is the test; repeat runs are fast and deterministic; breakages heal themselves or fail loudly and explainably; the team's runner, CI and reports stay unchanged.
- Within the MVP the engineer is **not obliged** to read or edit the generated code ("full magic"): trust is built on behavior — determinism, speed, loud outcomes.

**Secondary participants:**

- **Team members who do not write tests** (manual QA, analysts, product) — read the scenarios: a human-language suite doubles as living documentation of coverage.
- **CI** — runs the suite without a human: no interactive input, with distinguishable failure kinds (product bug / incurable step / LLM unavailability).
- **The open-source community** — future users and contributors; the product must run entirely on the user's infrastructure.

## Goals

1. **Writing in human language.** The engineer phrases a web UI test step as an ordinary sentence inside an ordinary test; for typical actions, no driver code is written at all.
2. **Stability without maintenance.** The suite stays green when the UI changes: broken steps heal automatically, the engineer does not maintain step code. Incurable breakages and real defects fail loudly and unambiguously.
3. **Seamless integration without lock-in.** The capability works inside the team's existing stack (their runner, CI, reports), entirely on the user's infrastructure with their own LLM keys; open source, with no mandatory product cloud services.
4. **Living documentation.** The suite reads as a plain-language scenario — the whole team sees what is covered without reading code.

Priority: goals 1 and 2 are co-primary (both are user pains); goal 3 is structural; goal 4 is derivative.

Trust model: "full magic" — the engineer neither looks at nor edits the generated code; trust is ensured by cache determinism, visible healing outcomes and loud failures.

## User Experience

### Entering the scenario

The engineer installs the library into an existing project (an ordinary Python package), configures the project once (browser driver, LLM access with their own keys) and writes tests as usual — phrasing steps as natural-language sentences (Russian, English, another) through the library API: action steps and assertion steps.

### Main scenario

1. The engineer writes a test: steps are ordinary sentences ("открыть страницу логина", "ввести логин и пароль", "нажать \"Войти\"", "убедиться, что появилась надпись \"Добро пожаловать\"").
2. **First run:** for every unknown step the product itself generates executable code (using the LLM and the live page state) and executes it against the real application. The first run is noticeably slower; the engineer sees which steps are being generated. The generated code lands in a cache stored **in the repository next to the tests**.
3. **Repeat runs** (locally and in CI): steps execute straight from the cache — fast, deterministic, with no calls to the LLM.
4. The step text is visible in the test output — the scenario reads as documentation.

### Self-healing scenario (the key alternative path)

A cached step has failed. The product starts an agentic error-classification loop:

- **healable rot** (the UI changed: selector, labels, structure) → the step is regenerated from the current page state and retried; on success the repository cache is updated and the healing is **loudly marked** in the output (which step, why it is rot, what changed);
- **real product defect** (the expected behavior is genuinely broken) → a loud test failure with an explanation — this is the very signal tests exist for;
- **incurable** (regeneration failed within the attempt budget, the step text no longer matches reality, ambiguity) → an explicit exception: step, reason, recommended action.

### States meaningful to the user

`generation (first run)` → `in cache (fast deterministic path)` → `healing (classification + regeneration)` → `healed (loudly marked, cache updated)` | `failure: product defect` | `failure: incurable step`.

### Failures and recovery

- The LLM is unavailable → cached steps keep working; only generation and healing are blocked — with a comprehensible infrastructure error.
- The same step text is reused across tests; the cache never silently applies code generated for a substantially different context.
- An interrupted run does not lose results: successfully generated/healed steps remain in the cache; a repeat run regenerates nothing again.
- Cache updates (new and healed steps) land in the repository and spread to all environments through ordinary version control.

## Requirements

### Integration and API

- **R1.** The library provides a framework-agnostic step API: separate methods for action steps (`action`) and assertion steps (`assertion`), sufficient for an integrator to wire it into any popular Python test framework (pytest, unittest, etc.). Built-in framework integrations/plugins are not part of the product.
- **R2.** Tests with steps run by the team's standard runner command alongside ordinary tests; no CI configuration or reporting changes are required.
- **R3.** Project settings (browser driver, LLM access with the user's keys) are configured once per project.

### Authoring

- **R4.** A step is phrased as a free-form natural-language sentence (Russian, English, another).
- **R5.** Action steps and assertion steps are supported; assertion steps yield an ordinary pass/fail outcome.
- **R6.** Steps of one test execute in a shared browser context in order; **each test runs in its own isolated context** independent of other tests.
- **R7.** Step texts are visible in the test output/report.

### Generation and cache

- **R8.** On first execution of an unknown step the product automatically generates executable code for it and executes it against the real application; no manual coding is required.
- **R9.** The cache of generated steps is stored in the project repository next to the tests and is fully managed by the product; the engineer is not required to read or edit it.
- **R10.** Repeat executions of a step use the cache directly, without calling the LLM — fast and deterministic.
- **R11.** The cache is environment-independent: it works wherever the repository exists (locally, CI); missing steps are generated in the environment where the run happens.
- **R12.** The same step text in the same context resolves to one cached step (reuse across tests). Business rule: the cache never silently applies code generated for a substantially different context.
- **R13.** Cache updates (new and healed steps) land in the repository as the run proceeds and spread to all environments through version control.

### Self-healing

- **R14.** When a cached step (action or assertion) fails, the product performs agentic error classification: healable rot → regenerate from the current page and retry; real product defect → loud test failure; incurable → explicit exception naming the step, the reason and the recommended action.
- **R15.** Healing is bounded: a finite number of regeneration attempts; budget exhaustion is treated as incurability; infinite loops are excluded.
- **R16.** A healed step is updated in the repository cache.
- **R17.** Every healing is loudly reflected in the output: which step, why the error was classified as rot, what changed; for assertion steps — what changed in the expectation.
- **R18.** Anti-masking: healing never turns a real product defect into a passed test.

### Failures and communication

- **R19.** Failure kinds are distinguishable by the user: product defect / incurable step / infrastructure (LLM unavailable); each with an actionable message.
- **R20.** When the LLM is unavailable, cached steps keep executing; only generation and healing are blocked — with an explicit message.

### Isolation and execution model

- **R21.** The execution model (order, parallelism) is the runner's responsibility, not the library's; the library gives no parallelism guarantees of its own but must honor per-test isolation (R6) so that any runner execution model remains correct.

## Constraints

- Python library inside the existing `prettyplay` project (Python ≥ 3.10, BSD-3-Clause license).
- The solution requires no changes to the team's runner, CI or reporting.
- Generation and healing depend on an external LLM service on the user's side (their keys and infrastructure); the quality and availability of these operations are bounded by the chosen LLM.
- Fully open source: no proprietary cloud components, no mandatory product service, no vendor lock-in.
- The cache is a repository artifact next to the tests, managed by the product.
- Normal product operation never requires the engineer to read or edit generated code.
- Cached runs never call the LLM (determinism and speed).
- Healing is bounded by an attempt budget.
- The MVP covers only browser web-interface testing; the set of supported browsers is not fixed by the product (an engineering decision determined by the chosen driver).

## Scope

### In Scope

- Framework-agnostic step API (`action` / `assertion`), sufficient for an integrator to wire into any popular Python test framework.
- A human-language step → automatically generated executable code for the web UI.
- A persistent step cache in the repository, fully managed by the product.
- Cache reuse without the LLM in any environment (locally and CI).
- Agentic self-healing: error classification, bounded regeneration, healed code written back to the cache, loud healing visibility.
- A distinguishable failure taxonomy with actionable messages.
- Project-level configuration (browser driver, the user's LLM keys).
- Running entirely on the user's infrastructure; open source.

### Out of Scope

- Built-in framework integrations/plugins (pytest plugin, unittest base classes) — the integrator does the wiring.
- Authoring formats for non-programmers (markdown/Gherkin scenarios, no-code studios) — steps live inside Python tests.
- Testing of mobile, native and desktop applications.
- Fixing the browser matrix — an engineering decision.
- Test recording, IDE plugins, authoring UI.
- A proprietary reporting portal, analytics, dashboards — output goes through the framework's native reporting.
- A managed cloud service / LLM hosting provided by the product.
- Visual testing (screenshot diffing) and performance testing.
- Parallel execution as a library feature — the runner's responsibility.

## Success Criteria

1. **Authoring without driver code.** A realistic web scenario (e.g. login + main action + assertion), authored entirely in sentences through the API, runs green on the first run after generation; the engineer wrote not a single line of driver code.
2. **Cache and determinism.** With LLM keys removed, the cached suite passes in a fresh environment (another machine / CI) using only the repository — confirming cache reuse and determinism.
3. **Self-healing.** After an intentional UI change (an element renamed/moved/restructured) the affected step heals during the run: the test passes, the healing is loudly marked in the output, the repository cache is updated.
4. **Anti-masking.** A real functional regression fails the suite as a product defect with a comprehensible message — and is never "healed" into green.
5. **Incurability.** A step that cannot be regenerated (text no longer matches reality / attempt budget exhausted) yields a distinct exception: step, reason, recommended action.
6. **Resilience to LLM unavailability.** With the LLM unavailable, cached steps execute; generation/healing attempts end with an explicit infrastructure error.
7. **Integration.** The suite runs by the standard runner command after the integrator wires the API in a few lines; step texts read as a plain-language scenario in the output.
8. **Isolation.** Tests yield identical outcomes regardless of execution order (no cross-test state leaks through the library).

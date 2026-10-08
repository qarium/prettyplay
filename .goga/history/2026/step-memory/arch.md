# Architecture Plan — step-memory

Runtime step memory with Jinja result declarations for PrettyPlay.
Source task: `.goga/history/2026/step-memory/task.md` (ADR: `adr.md`, PRD: `prd.md`).

## Topic

**step-memory** — plan file: `.goga/history/2026/step-memory/arch.md` (path printed by `goga history path -f arch.md`).

## Implementation Order

Cells ordered leaves → root; each cell is implemented only after its Imports exist in the implemented state.

When implementing the renderer (step 2), add `jinja2>=3.1` to `[project].dependencies` in `pyproject.toml` before importing Jinja. This is package metadata required by the task, alongside the contract and usage artifacts below.

| # | Cell | Status | Rationale |
|---|---|---|---|
| 1 | `prettyplay/cache` | MODIFY | Depends only on config/reporting (existing, untouched); the addressing change is self-contained |
| 2 | `prettyplay/engine/renderer` | CREATE | Depends only on `prettyplay/failures` (existing); every feature cell below imports it |
| 3 | `prettyplay/llm` | MODIFY | Depends on config/failures (existing); receives primitives only — no renderer dependency |
| 4 | `prettyplay/engine/polling` | MODIFY | Depends on driver (existing, untouched); result carriage is self-contained |
| 5 | `prettyplay/engine` | MODIFY | Depends on cache/llm/polling states from steps 1, 3, 4 + renderer from step 2 |
| 6 | `prettyplay/engine/groups` | MODIFY | Depends on engine (step 5) + renderer (step 2) |
| 7 | `prettyplay/engine/steering` | MODIFY | Depends on engine (step 5) + renderer (step 2) |
| 8 | `prettyplay` | MODIFY | The facade — depends on every cell above |

Untouched cells (no plan artifacts): `prettyplay/driver`, `prettyplay/failures` (`PrettyplayError` reused), `prettyplay/config`, `prettyplay/reporting`.

## Artifacts

Convention for MODIFY entries: the resulting **current state** is specified — changed sections are given in full, preserved sections are marked `= PRESERVED =` (kept verbatim from the existing file). No changelog narrative.

---

### 1. `prettyplay/cache` (MODIFY)

#### CODEMANIFEST `prettyplay/cache/CODEMANIFEST`

- Header
  - `Imports`: = PRESERVED = (Config from `prettyplay/config`; StepReporter + `hooks` from `prettyplay/reporting`)
  - `Usages`: = PRESERVED = (`conventions: .goga/usages/conventions.md`)
  - `Annotations`: = PRESERVED = with one line added after the "Step identity is intentional" line:

    ```
    Step identity stays on the original template sentence: a sentence containing Jinja markers addresses verbatim (NFC + trim — case-sensitive names, significant expression whitespace); an ordinary sentence keeps the casefold normalization; runtime values never enter the address.
    ```

- Body
  - `normalize_step_text(text: str) -> normalized: str` — `location: text.py`; replaced annotation:

    ```yaml
    annotations: |
      Normalize a step sentence for identity and addressing — template-aware.

      `text`: the raw step sentence as written by the engineer.
      `normalized`: the normalized sentence.

      Algorithm:
      1. Detect Jinja template markers — an occurrence of `{{` or `{%` anywhere in the sentence
      2. A template sentence: apply Unicode NFC normalization and trim leading/trailing whitespace only — the source stays verbatim otherwise; Jinja names are case-sensitive and whitespace inside expressions is significant
      3. An ordinary sentence: the existing pipeline — NFC, trim, collapse internal whitespace runs to single spaces, casefold

      Requirements:
      - Pure function: no I/O, no locale dependence, deterministic on `text` alone
      - `{{ name }}` and `{{ Name }}` address different steps; semantically different Jinja source never shares an address
      - «Нажать Войти» and «нажать  войти » still normalize to the same string; a Russian sentence and its English translation stay different
      - Runtime values never enter the address — the normalization sees the template source only
    ```

  - `StepIdentity`, `CachedStep`, `StepCache`, `RunBudgets`: = PRESERVED =
- Footer
  - `Author: Goga`; `CreatedAt: 07/09/26` (original); `Description` replaced:

    ```
    The step cache of prettyplay: template-aware normalization (template sentences address verbatim, ordinary sentences casefold), deterministic addressing, atomic repository storage and the per-test attempt budgets, the group recovery cycle accounting.
    ```

#### `.usages/` files

- `prettyplay/cache/.usages/addressing.md` — UPDATE. Identity-triple table row for the normalized sentence becomes: *templates: NFC + trim (verbatim); ordinary: NFC, trim, whitespace collapse, casefold — a template addresses by its source; an ordinary sentence casefolds as before*. New section inserted after the identity table:

  ```markdown
  ## Template sentences

  A sentence containing Jinja markers (`{{` or `{%`) is a template step:

  ```python
  normalize_step_text("Read the first item name into {% var name %}")
  # NFC + trim only — case-sensitive names and expression whitespace stay significant
  ```

  - `{{ name }}` and `{{ Name }}` are different steps — Jinja names are case-sensitive
  - Two templates differing only by prose case or spacing do not share an entry — a fresh generation, never a wrong hit
  - Runtime values never enter the address: the same template with different observed values reuses the same cached code, which re-reads captures on every execution
  ```

  Sections "Normalize and address" and "Layout": = PRESERVED =.
- `budgets.md`, `storage.md`: = PRESERVED =

---

### 2. `prettyplay/engine/renderer` (CREATE)

#### CODEMANIFEST `prettyplay/engine/renderer/CODEMANIFEST` — full file

```yaml
Imports:
  - Types:
      - PrettyplayError
    Usages:
      - taxonomy
    From: prettyplay/failures

Usages:
  conventions: .goga/usages/conventions.md
  jinja: .goga/usages/cooks/jinja.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `jinja` for the Jinja environment, the `{% var %}` capture extension, the namespaces and the missing-value policy.
  Use `taxonomy` from Imports for the base failure kind the authoring errors raise.

  The step-sentence preparation of prettyplay: rendering a step sentence from a snapshot of the test memory and the call inputs into a plain-text instruction with capture declarations, the per-test memory of captured observations, and the deterministic validation of returned step results.
  Rendering is pure preparation — no browser, no LLM, no page access: everything happens before execution; authoring errors surface here, before any code runs.
  The memory belongs to one test execution: it survives navigation, never crosses tests, and publishes only validated captures after full acceptance.
  Substituted values are data, never templates: a captured string containing `{{ x }}` stays literal; automatic HTML escaping is off; the instruction is plain text.
  The prepared instruction is the single text every LLM request and every raised failure carries for a step; the raw template sentence stays the addressing artifact of the caller.

---

"PreparedStep(instruction: str, inputs: dict[str, str], declarations: list[str])":
  location: render.py
  annotations: |
    The render product of one step sentence — what the whole agent cycle works with after preparation.

    `instruction`: the prepared plain-text instruction — the rendered sentence with actual values embedded; what generation requests receive and failures carry.
    `inputs`: the call-local input bindings of this step (`vars`), empty when none — separate from memory, never establishing memory.
    `declarations`: the names of the capture tags reached during rendering, in execution order; empty — the step has no memory writes.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - Immutable data carrier: rendering produces it once per preparation
  properties:
    "instruction -> str": |
      The prepared plain-text instruction with actual values embedded.
    "inputs -> dict[str, str]": |
      The call-local input bindings of this step; empty — none.
    "declarations -> list[str]": |
      The reached capture-tag names, in execution order; empty — no memory writes.
    "has_declarations -> bool": |
      Whether the step declared any result captures.

"render_step(text: str, step_type: str, memory: StepMemory, vars: dict[str, str] | None) -> prepared: PreparedStep":
  location: render.py
  annotations: |
    Render one step sentence from a snapshot of memory and call inputs into a `PreparedStep` — the render point of every step execution and every recovery re-invocation.

    `text`: the raw step sentence as written by the engineer — the template source, verbatim.
    `step_type`: action or assertion — an assertion with reached capture declarations is an authoring error.
    `memory`: the test memory — the render reads its snapshot; the step's own new captures stay invisible to its template.
    `vars`: the call-local string inputs; None — none. `vars` is a reserved namespace beside memory: neither overwrites the other.
    `prepared`: the render product.

    Algorithm:
    1. Take the snapshot: the `StepMemory` snapshot plus `vars` (None — empty); standard Jinja scope applies, ordinary `set` stays local to the template
    2. Compile through the Jinja environment of `jinja`: `StrictUndefined`, `autoescape=False`, the `{% var %}` extension
    3. Render: a reached capture tag records its name and renders to empty text; a duplicate name within one render fails as an authoring error; the reserved name `vars` and non-Jinja-identifier capture names fail as authoring errors
    4. An unavailable name fails ordinary interpolation with the unavailable name in the message; author-written `default` and `is defined` keep standard behavior
    5. `step_type` assertion with non-empty declarations — the authoring error: capture declarations are invalid in `expect`; an inactive branch declares nothing
    6. Build and return `PreparedStep` — instruction (the rendered text), inputs (`vars`), declarations

    Requirements:
    - All authoring errors raise the loud actionable `PrettyplayError` naming the problem and the offending name — before any browser execution
    - Substituted data is never rendered again; the instruction is plain text
    - A same-step read observes the previous value or fails — new captures publish only after acceptance

    Constraints:
    - No browser, LLM or page access; no mutation of `memory` — the snapshot is read-only

"StepMemory()":
  location: memory.py
  annotations: |
    The per-test-execution memory of captured observations — the names namespace of rendering.

    Constructs empty. Owned by the step executor of one test; rendering reads snapshots; publication happens only at acceptance points.

    Requirements:
    - Survives navigation; never crosses test boundaries — concurrent tests stay isolated
  methods:
    "snapshot() -> values: dict[str, str]": |
      Return a copy of the current values — the render source.

      `values`: the stable copy; later publications never mutate a taken snapshot.
    "publish(captures: dict[str, str])": |
      Publish validated captures atomically.

      `captures`: the validated dictionary of one accepted step execution.

      Algorithm:
      1. Replace the value of every name present in `captures` — a successful recapture replaces the previous value
      2. Names absent from `captures` keep their values

      Requirements:
      - All captures of one step publish together — one call per accepted execution
      - A failed or rejected attempt never calls publish — its captures stay unpublished

"validate_step_result(prepared: PreparedStep, result: dict[str, str] | None) -> captures: dict[str, str]":
  location: validation.py
  annotations: |
    Deterministically validate the returned result of one step execution against the prepared declarations.

    `prepared`: the render product of the executed step — the declaration set.
    `result`: the step function's return — the dictionary of declared names to observed strings, or None for a declaration-free step.
    `captures`: the validated captures, ready for publication; empty for a declaration-free step.

    Algorithm:
    1. No declarations: `result` None — return the empty captures (success without result); a non-None result is a violation
    2. Declarations present: `result` None — the violation (missing result)
    3. The keys of `result` equal the declarations exactly — a missing or an unexpected name is a violation naming it
    4. Every value is a str; every value is non-blank (not empty, not whitespace-only) — a violation names the offending capture
    5. Return the validated captures

    Requirements:
    - Pure validation: no I/O, no LLM, deterministic on the inputs
    - A violation raises AssertionError with the deterministic violation text — the failed-check channel of the calling cycle: corrective generation on permitted non-strict paths, strict failure without generation
    - Values are accepted as observed strings — no normalization, no trimming

    Constraints:
    - Never fabricates or repairs values: a violation is a failure, never a silent pass

---

Author: Goga
CreatedAt: 08/10/26
Description: |
  The step-sentence preparation of prettyplay: rendering Jinja step templates with the `{% var %}` capture extension from a snapshot of memory and call inputs into prepared instructions with input bindings and result declarations, the per-test memory of captured observations with atomic publication, and the deterministic validation of returned step results.
```

Module grouping: `render.py` (render_step + PreparedStep), `memory.py` (StepMemory), `validation.py` (validate_step_result); `__init__.py` exposes all four names through `__all__`.

#### `.usages/` files — full content

**`prettyplay/engine/renderer/.usages/rendering.md`**

```markdown
# Rendering step sentences

Domain: preparing a step sentence into a plain-text instruction with capture declarations. Audience: library internals — the step executor and the recovery engine calling the render point.

## Render a step

```python
from prettyplay.engine.renderer import render_step

prepared = render_step(
    text="For the item named {{ name }}, read its tags into {% var tags %}",
    step_type="action",
    memory=memory,
    vars=None,
)
prepared.instruction   # "For the item named Book, read its tags into " — plain text, actual values
prepared.inputs        # {} — the call's vars
prepared.declarations  # ["tags"] — reached capture tags only
```

- The render starts from a snapshot: later publications never change a taken render
- `{{ name }}` reads memory; `{{ vars.expected }}` reads the call input — separate namespaces, neither overwrites the other
- A reached `{% var name %}` renders to empty text and declares a result slot; an inactive branch declares nothing
- Capture declarations are invalid for assertion steps (`expect`)

## Authoring errors

Raised as the loud actionable `PrettyplayError` before any browser execution:

- a duplicate capture name within one render
- the reserved capture name `vars` or a non-Jinja-identifier name
- an unavailable ordinary reference — the message names it; author-written `| default(...)` and `is defined` behave as authored
- a capture declaration in an assertion step

## Literal Jinja in a sentence

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

Use standard `raw` blocks to output literal Jinja syntax.
```

**`prettyplay/engine/renderer/.usages/memory.md`**

```markdown
# Test memory

Domain: the per-test memory of captured observations. Audience: library internals — the executor owning the memory and the engines publishing at acceptance.

## Lifecycle

```python
from prettyplay.engine.renderer import StepMemory

memory = StepMemory()              # empty at construction, one per test execution
values = memory.snapshot()         # the render source — a stable copy
memory.publish({"name": "Book"})   # atomic, after full acceptance only
```

- Rendering reads a snapshot: a step's own new captures stay invisible to its template; a same-step read observes the previous value or fails
- All captures of one step publish together after full acceptance (including the compliance gate); a failed or rejected step publishes nothing
- A successful recapture replaces the previous value; absent names keep theirs
- Memory survives navigation and never crosses test boundaries — concurrent tests stay isolated

## Who publishes

- The executor — after a validated successful replay of cached code
- The engines — at the candidate acceptance point (after the compliance gate)
- The group recovery — per accepted row step; a later group failure never rolls back accepted publications
```

**`prettyplay/engine/renderer/.usages/validation.md`**

```markdown
# Validating step results

Domain: deterministic acceptance of returned step results. Audience: library internals — the executor and the engines validating executions.

## Validate an execution result

```python
from prettyplay.engine.renderer import validate_step_result

captures = validate_step_result(prepared, result)  # result — the step function's return
memory.publish(captures)
```

- Exact declared keys: missing or unexpected names violate; string values only; blank (empty or whitespace-only) values violate
- A declaration-free step accepts None and validates to empty captures — the success-without-result behavior
- A violation raises AssertionError with a deterministic text — it enters the existing failed-check paths: classification and bounded corrective generation where non-strict execution permits, strict failure without generation
- Publish only validated captures — never fabricated or repaired values
```

---

### 3. `prettyplay/llm` (MODIFY)

#### CODEMANIFEST `prettyplay/llm/CODEMANIFEST`

- Header
  - `Imports`, `Usages`: = PRESERVED =
  - `Annotations`: = PRESERVED = except replace the existing scenario-context and group-diagnosis lines with the text below, and add the following four lines:

    ```
    The scenario-context input participates in both provider implementations with identical semantics: generation and group diagnosis render PREVIOUS STEPS from the typed scenario records' prepared instruction fields, marking group membership; raw template sentences stay local to addressing and re-rendering.
    The group diagnosis operation is the fourth operation of the port with absolute provider parity: one logical request carries the group prompt, previous scenario instructions, group trace instructions, the failed prepared instruction, attempt history, snapshot and optional screenshot; the strict parser and conservative degraded verdict remain as before.
    ```

    ```
    The prepared-instruction input participates in both provider implementations with identical semantics: every generation request renders the prepared instruction of the step — the plain-text sentence produced by rendering, actual values embedded — as the STEP block; the raw template sentence never appears in any request; the scenario records render their instruction field — the model never sees raw Jinja; a parity requirement, not a capability difference.
    The input-bindings input participates in both provider implementations with identical semantics: a non-empty inputs mapping of a generation request renders as its own INPUTS block — one name = value line per binding — placed immediately after the STEP line of the user content; empty — no block; a parity requirement, not a capability difference.
    The result-declarations input participates in both provider implementations with identical semantics: a non-empty declarations list of a generation request renders as its own RESULTS block — the declared names plus the result contract (the step code returns a dictionary of exactly these names to non-blank observed strings) — placed immediately after the INPUTS block; empty — no block, the code form stays success-without-result; a parity requirement, not a capability difference.
    The compliance verdict request also receives the prepared instruction, inputs and declarations as primitives in both providers. It renders the STEP line from the instruction and optional INPUTS and RESULTS blocks before ATTEMPT HISTORY; the gate reviews the executed code against the same result contract as generation.
    ```

- Body
  - `LLMProvider` → method `generate_step_code` — replaced signature and annotation:

    ```yaml
    "generate_step_code(prompt: str, user_instructions: str, instruction: str, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, inputs: dict[str, str], declarations: list[str], snapshot: str, page_url: str | None, screenshot: bytes | None, cheat_sheet: str, attempt_history: list[str], recommendation: str | None, guidance: str | None) -> code: str": |
      Generate step code of the fixed form.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's code style instructions supplied by the calling engine from the generation_prompt setting; empty — the request carries no instructions block; non-empty — rendered by the provider implementations verbatim as a separate USER INSTRUCTIONS block of the user content, identically in both.
      `instruction`: the prepared instruction of the step — the rendered plain-text sentence with actual values embedded; rendered as the STEP block, identically in both; the raw template sentence never reaches the request.
      `step_type`: action or assertion — rendered as the STEP TYPE line immediately before the STEP line, identically in both.
      `previous_steps`: the typed scenario records of the previous steps of the test, in execution order — each entry renders its `instruction` (the prepared instruction recorded at execution) with the group entries marked, identically in both.
      `group_prompt`: the group prompt of the current step's group; None — an ordinary step, no GROUP PROMPT block; non-empty — rendered verbatim as a separate GROUP PROMPT block immediately before the PREVIOUS STEPS block, identically in both; takes no part in step addressing.
      `inputs`: the call-local input bindings of the step; non-empty — rendered as the INPUTS block immediately after the STEP line, one name = value line per binding, identically in both; empty — no block.
      `declarations`: the declared result names of the step; non-empty — rendered as the RESULTS block immediately after the INPUTS block stating the result contract — the code returns a dictionary of exactly the declared names to non-blank strings observed on the page; empty — no block, the success-without-result code form.
      `snapshot`: the accessibility snapshot of the current page.
      `page_url`: the current URL of the page; non-empty — rendered as its own PAGE URL line immediately after the PAGE SNAPSHOT block, identically in both; None — no line.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `cheat_sheet`: the compact standard Playwright sync API reference supplied by the calling engine — rendered as the leading CHEAT SHEET block of the user content, identically in both; guidance, not an allowlist.
      `attempt_history`: the attempt history of the step — every record a complete multi-line verbatim record composed by the calling engine; non-empty — rendered as the HISTORY block after the USER INSTRUCTIONS block; empty — no block; no collapsing, no size limits.
      `recommendation`: the diagnosis of the classification that preceded the regeneration; non-empty — rendered as a separate RECOMMENDATION block after the HISTORY block; None — no block.
      `guidance`: the engineer guidance message of the interactive steering; non-empty — rendered as a separate USER GUIDANCE block; None — no block.
      `code`: the generated step code of the fixed form — `def step(page) -> None` without result declarations, `def step(page) -> dict[str, str] | None` with them, working through the standard Playwright sync API — imports from playwright.sync_api and the Python standard library only, global at the top level of the code block; the first markdown-fenced block of the answer is unwrapped — an answer with no closed fence returns verbatim.

      Requirements:
      - A provider transport failure is retried inside this operation up to the configured request-attempt budget; exhaustion, a permanent rejection or an over-cap Retry-After raises `LLMUnavailableError` naming the provider with the original cause chained
      - The generated code contains no provider-specific constructs
      - The block order of the scenario part is fixed: STEP TYPE line, STEP line, INPUTS block (when non-empty), RESULTS block (when non-empty), PAGE URL line, then the remaining scenario blocks — the fixed order of the regeneration tail (HISTORY, RECOMMENDATION, USER GUIDANCE) is unchanged; a non-empty input renders its named block, identically in both implementations
      - The new inputs take no part in step addressing: a cached step never regenerates because they changed
    ```

  - `LLMProvider` → `check_instruction_compliance` — replaced signature and annotation:

    ```yaml
    "check_instruction_compliance(prompt: str, user_instructions: str, instruction: str, step_type: str, inputs: dict[str, str], declarations: list[str], code: str, attempt_history: list[str]) -> verdict: list[ComplianceFinding]": |
      Check an executed candidate against the binding user instructions and the prepared step, including its result contract.

      `prompt`: the compliance system prompt, applied verbatim.
      `user_instructions`: the binding generation instructions; the caller invokes the gate only when these are non-empty.
      `instruction`: the prepared plain-text step instruction, rendered as STEP; never the raw template.
      `step_type`: action or assertion, rendered immediately before STEP.
      `inputs`: current call bindings; non-empty — render INPUTS after STEP, one name = value line per binding; empty — omit the block.
      `declarations`: reached capture names; non-empty — render RESULTS after INPUTS with the exact-key, observed non-blank string return contract; empty — omit the block and retain the success-without-result form.
      `code`: the successfully executed candidate under review.
      `attempt_history`: verbatim attempt records, rendered as ATTEMPT HISTORY after the scenario blocks when non-empty.
      `verdict`: the parsed findings of instruction compliance and step adequacy; empty — both dimensions pass.

      Requirements:
      - Both provider implementations render the same block order: INSTRUCTIONS, STEP TYPE and STEP, optional INPUTS, optional RESULTS, ATTEMPT HISTORY, CODE
      - Preserve the existing bounded transport retries and strict verdict parsing; malformed verdicts raise ComplianceVerdictError
      - These inputs do not enter cache addressing, and the gate never runs on replayed cached code
    ```

  - `LLMProvider` → `classify_step_failure` — signature unchanged (`step_text: str`), its `step_text` annotation replaced:

    ```
    `step_text`: the prepared instruction of the failed step, rendered as STEP in the classification request; never the raw template sentence. Both providers use it identically.
    ```

  - `LLMProvider` → `classify_group_failure` — replaced signature and annotation:

    ```yaml
    "classify_group_failure(prompt: str, user_instructions: str, group_prompt: str, group_steps: list[str], previous_steps: list[ScenarioStep], step_text: str, attempt_history: list[str], snapshot: str, screenshot: bytes | None) -> diagnosis: GroupFailureClassification": |
      Send the group diagnosis with the whole prior scenario visible.

      `previous_steps`: previous scenario records in execution order; render a PREVIOUS STEPS block from their prepared instruction fields, marking group membership, before GROUP STEPS. Empty — omit the block.
      `group_steps`: the rendered group traces; each trace's visible sentence line is its recorded prepared instruction.
      `step_text`: the failed step's prepared instruction, rendered as STEP; never its raw template sentence.
      `diagnosis`: earliest_step quotes a visible prepared instruction verbatim, so the recovery matcher can resolve it against group traces or prior scenario records.

      Requirements:
      - Both providers render GROUP PROMPT, optional PREVIOUS STEPS, GROUP STEPS, STEP, HISTORY, PAGE SNAPSHOT, optional SCREENSHOT, USER INSTRUCTIONS in the same order
      - Preserve the existing strict verdict parser and bounded transport retries
    ```

  - `ScenarioStep` — replaced declaration:

    ```yaml
    "ScenarioStep(sentence: str, instruction: str, group_prompt: str)":
      location: models.py
      annotations: |
        One record of the scenario context of a test — the unit every PREVIOUS STEPS block renders.

        `sentence`: the raw step sentence (the template source) as written by the engineer, verbatim — the addressing and diagnostics artifact; never rendered into requests.
        `instruction`: the prepared instruction recorded at the step's execution — the rendered plain-text sentence; equals `sentence` for a non-template step; the only field requests render.
        `group_prompt`: the group prompt of the step's group; empty — an ordinary step; non-empty — the verbatim group prompt; the membership is permanent for the lifetime of the test context.

        Requirements:
        - pydantic v2, kw_only, empty defaults (see `conventions`)
        - A record appended to the scenario context is never rewritten
      properties:
        "sentence -> str": |
          The raw step sentence (the template source), verbatim.
        "instruction -> str": |
          The prepared instruction recorded at execution; equals the sentence for a non-template step.
        "group_prompt -> str": |
          The group prompt of the step's group; empty means an ordinary step.
    ```

  - `LLMProvider::OpenAIProvider(config)` and `LLMProvider::AnthropicProvider(config)`: = PRESERVED = with three identical lines added to both block-composition algorithms: *generation and compliance scenario parts render the STEP TYPE line, the prepared-instruction STEP line, the INPUTS block (when non-empty) and the RESULTS block (when non-empty) immediately after it — identically in both implementations; ordinary classification renders its prepared `step_text` as STEP; group diagnosis renders previous scenario instructions in PREVIOUS STEPS before GROUP STEPS, with identical behavior in both providers*
  - All other types and operations: = PRESERVED =
- Footer
  - `Author: Goga`; `CreatedAt: 10/09/26` (original); `Description` replaced:

    ```
    The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity — generation (carrying the prepared instruction with input bindings and result declarations), classification and the two-dimension compliance verdict with identical user-instructions, cheat-sheet, step-type and attempt-history semantics — the failure classification verdict and the instruction-compliance and step-adequacy findings, the typed scenario records (raw sentence + prepared instruction), the group diagnosis operation and its verdict, and the shared bounded transport retry mechanism.
    ```

#### `.usages/` files

- `providers.md` — UPDATE: two paragraphs appended to the Parity section:

  ```markdown
  Prepared-instruction parity: every generation request renders the prepared instruction — the plain-text sentence with actual values produced by rendering — as the STEP block; the raw template sentence never appears. Scenario records render their instruction field; the model never sees raw Jinja. A parity requirement, not a capability difference.

  Input-bindings and result-declarations parity: a non-empty inputs mapping renders as the INPUTS block immediately after the STEP line (one name = value line per binding); a non-empty declarations list renders as the RESULTS block immediately after INPUTS stating the result contract — the code returns a dictionary of exactly the declared names to non-blank observed page strings; empty inputs — no INPUTS block, empty declarations — no RESULTS block and the success-without-result form. Both providers render the blocks identically at the same positions. A parity requirement, not a capability difference.

  Compliance parity: the gate request uses the same prepared instruction, INPUTS and RESULTS representation in both providers. The reviewer sees the exact result contract next to the STEP line before ATTEMPT HISTORY and CODE; it never sees the raw template sentence.

  Classification parity: ordinary classification renders its `step_text` input as the prepared instruction in the STEP block, identically in both providers. Group diagnosis renders prior scenario and group trace instruction fields, plus the prepared failed STEP. Raw template sentences stay local to cache addressing and re-rendering.
  ```

- `classification.md`, `transport.md`: = PRESERVED =

---

### 4. `prettyplay/engine/polling` (MODIFY)

#### CODEMANIFEST `prettyplay/engine/polling/CODEMANIFEST`

- Header: `Imports`, `Usages`: = PRESERVED =; `Annotations`: = PRESERVED = with one line added:

  ```
  An execution result rides the loop: settle returns the result of the successful execution — the step's dictionary for steps with result declarations, None otherwise; the window gates repetitions exactly as before, never touching the result beyond passing the successful one through.
  ```

- Body
  - `SettleWindow`: = PRESERVED =
  - `settle` — replaced signature and annotation:

    ```yaml
    "settle(execute: Callable[[str, PageFacade], dict[str, str] | None], code: str, page: PageFacade, window: SettleWindow) -> result: dict[str, str] | None":
      location: settle.py
      annotations: |
        Execute step code under the settle window: absorb transient page-state failures by re-executing the same code, propagate everything else as-is — and carry the result of the successful execution back to the caller.

        `execute`: the step-code execution routine passed by the caller — returns the step's result (a dictionary of declared names to observed strings, or None for a declaration-free step).
        `code`: the step code text.
        `page`: the page facade of the current test.
        `window`: the settle window of the current step execution.
        `result`: the result returned by the successful execution — the last successful re-execution's result when repetitions occurred; None for a declaration-free step.

        Algorithm:
        In the count-bounded mode (`window` count_bounded): execute the code up to `window` tries times in total — each repetition requires the failure to be pollable and pauses the `window` delay; settle_retry records are uniform with the time mode; exhaustion propagates the failure to the caller as-is. In the time-bounded mode — as today.
        1. `window` start — mark the first execution
        2. Call `execute` with `code` and `page`; success — return the execution's result as-is: the step code worked
        3. On failure: `window` enabled, `is_pollable_failure` of the exception True, `window` has time remaining — pause the `window` delay, repeat from step 2
        4. Otherwise propagate the failure to the caller as-is

        Requirements:
        - Each repetition writes a settle_retry record to the logger prettyplay at INFO: the attempt counter and the failure text; no hook events are emitted
        - No LLM budget is consumed: re-execution is execution, not generation
        - Each settle call counts from zero in the count mode — the counter belongs to the code unit being executed: the cached code and every generated candidate each get their own full count; the LLM attempt budget is never multiplied
        - The result passes through untouched: the loop never inspects, validates or alters it — validation belongs to the calling cycle

        Constraints:
        - Never swallow, translate or retry a non-pollable failure — the classification path decides it
    ```

- Footer: `Author: Goga`; `CreatedAt: 12/09/26` (original); `Description` replaced:

  ```
  The settle policy of prettyplay: the per-execution settle window and the re-execution loop absorbing transient page-state failures before any costly move — carrying the successful execution's result back to the caller — beside the time window the count-bounded re-execution mode (tries).
  ```

#### `.usages/` files

- `settle.md` — UPDATE: new section appended:

  ```markdown
  ## Result carriage

  `settle` returns the result of the successful execution — `run_step_code` returns the step's dictionary for steps with capture declarations and None otherwise. The loop passes the successful result through untouched; validation and publication belong to the calling cycle. A repeated execution's success returns that re-execution's result.
  ```

  All other sections: = PRESERVED =.

---

### 5. `prettyplay/engine` (MODIFY)

#### CODEMANIFEST `prettyplay/engine/CODEMANIFEST`

- Header
  - `Imports`: = PRESERVED = with one block added:

    ```yaml
      - Types:
          - PreparedStep
          - StepMemory
          - validate_step_result
        Usages:
          - memory
          - validation
        From: prettyplay/engine/renderer
    ```

  - `Usages`: = PRESERVED = (conventions, system_prompt, cheat_sheet, group_framing, classification_prompt) except `compliance_prompt`: keep its verdict format and severity rules, replace the STEP input description with the prepared instruction and add INPUTS and RESULTS input descriptions. Require the reviewer to treat RESULTS as the exact-key, observed non-blank string return contract and flag code that cannot produce it as an adequacy finding; keep the existing block order around the optional new blocks.
  - `Annotations`: = PRESERVED = except replace the existing "Honest inputs in every step request" line with the text below. Add the following three lines:

    ```
    Honest inputs in every step request: the step type and prepared instruction, with current input bindings and result declarations when present, reach generation, regeneration and compliance; scenario records render their instruction fields. The raw template sentence remains the cache and re-render source, never a request input.
    ```

    ```
    The honest inputs of a step request carry the prepared instruction: the engines receive the render product of the step — instruction, input bindings, result declarations — and every provider request renders the prepared instruction with its INPUTS and RESULTS blocks; the raw template sentence never reaches a request; raised failures carry the prepared instruction as the step text; the casefolded normalization stays an addressing key only.
    Step results flow through the cycle: run_step_code returns the step's dictionary, settle carries it, validate_step_result gates it deterministically, and the accepted execution's captures publish through the `StepMemory` at the acceptance point — after validation and the compliance gate; a failed or gate-blocked attempt publishes nothing; an accepted step is never executed again merely to recover its result (see `memory` and `validation` from Imports).
    A result-contract violation is a failed check: the deterministic AssertionError of `validate_step_result` from Imports enters the existing failed-check paths — classification, bounded healing, strict by step type; generation and healing never invent fallbacks and never substitute a new observation for an unavailable earlier one.
    ```

- Body
  - `StepAttempt`: = PRESERVED =
  - `StepGenerator` → `generate` — replaced signature and annotation:

    ```yaml
    "generate(identity: StepIdentity, prepared: PreparedStep, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt], window: SettleWindow, memory: StepMemory) -> step: CachedStep": |
      Generate and store a new step.

      `prepared`: the render product of the step — instruction, input bindings, result declarations; every request renders the instruction with its INPUTS and RESULTS blocks; declarations present — the candidate code must return the result dictionary of exactly the declared names.
      `step_type`: action or assertion — carried into every request.
      `group_prompt`: the group prompt of the current step's group; None — an ordinary step: the behavior is byte-identical to today — the same requests, the same classification points, the same bounded healing; non-empty — a group step: every request carries the group framing per `group_framing` and the internal classification points are suppressed.
      `attempt_history`: the per-step attempt history created by the executor — this loop appends a record after every attempt that does not produce a cached step.
      `memory`: the test memory — the accepted candidate's validated captures publish here after validation and the gate (see `memory` from Imports); a failed or gate-blocked attempt publishes nothing.

      Algorithm:
      1. Ask the budgets registry try_generation for the step identity; a refused attempt is the incurable failure
      2. Collect the request inputs: the page accessibility snapshot, `prepared` — the instruction with its INPUTS and RESULTS blocks — `step_type`, `previous_steps` (typed records rendering their instructions), the cheat-sheet from `cheat_sheet`; add the page screenshot when the project settings enable screenshots
      3. Request step code from the provider port generate_step_code passing `system_prompt` as the system prompt, the cheat-sheet taken from `cheat_sheet`, the user instructions — the effective config generation_prompt — when non-empty, the rendered `attempt_history` and the guarded page URL read from `page`; a group step request carries the group framing per `group_framing`
      4. Read the page URL, execute the candidate under the settle window: `settle` with run_step_code, the candidate code, `page` and `window`; read the page URL again — the pair brackets the whole attempt
      5. On success: validate the returned result through `validate_step_result` from Imports — a violation appends the attempt record (outcome failed check, the deterministic violation text in the error field) and enters the failed-check paths of step 6 unchanged; a valid result waits for the gate. Gate the candidate through `check_step_compliance`. An empty findings list — publish the validated captures through `memory` publish, build `CachedStep`, save it to the cache, return it. A high finding of either dimension — the attempt is failed: append the attempt record (outcome compliance blocked, the finding instruction and explanation in the error field); nothing publishes; the retry carries the grown history. Medium and low findings pass with a WARNING naming the instructions, then the captures publish, the step is stored and returned. The gate hard failures — provider unavailability and a malformed verdict — propagate immediately: nothing is cached, nothing publishes
      6. On a failed check — an AssertionError that survived the settle window or the violation of step 5: append the attempt record (outcome failed check, the full failure description); a group step (`group_prompt` non-empty) — no classification request and no healing-funded regeneration: raise `IncurableStepError` carrying the failed code in the code field and the full failure description in the error field; the calling executor routes it to the group recovery. Otherwise — as today: classify via `classify_step_failure` passing the prepared instruction; a product_defect verdict raises `ProductDefectError` carrying the verdict and the full failure description of the candidate in the error field; an incurable verdict raises `IncurableStepError` carrying them; a rot or fixable verdict grants exactly one regeneration: try_healing funds it — a refused funding leaves the failure terminal `IncurableStepError` carrying the verdict, the reason naming the exhausted healing pool; the request carries the classification recommendation and the grown history — a success stores and returns the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect raises `ProductDefectError`, anything else raises `IncurableStepError` — no further regeneration; provider unavailability at these classifications is skipped quietly with a WARNING — the failure raises without a verdict as IncurableStepError, the conservative default uniform with the unrecognized-label fallback, the reason naming the failed candidate check
      7. On any other candidate failure: append the attempt record (outcome execution failed, the full failure description), repeat from step 1 with the fresh snapshot and the grown history, while attempts remain
      8. On budget exhaustion: the existing semantics preserved verbatim — a group step raises `IncurableStepError` carrying the failed code and the last candidate failure; otherwise the last candidate is classified (rot/fixable — one extra healing-funded regeneration carrying the recommendation; a repeat failure is terminal IncurableStepError without reclassification; product_defect → `ProductDefectError`; incurable → `IncurableStepError` naming the exhausted pool); budget exhaustion with a standing high finding raises `IncurableStepError` carrying the verdict built from the finding; provider unavailability at this classification is skipped quietly with a WARNING
      9. Report on_generation_started for every LLM attempt

      Requirements:
      - Every generation request carries the cheat-sheet taken from `cheat_sheet` from Usages: the model always sees the standard-API reference — guidance, never an allowlist
      - `group_prompt` None — the behavior is byte-identical to the ordinary path: the same requests, the same classification points, the same bounded healing (C13)
      - Every generation request carries the prepared instruction, the step type and the rendered attempt history — the record list grows by one after every attempt that does not produce a cached step
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` after the bounded transport retries inside the logical LLM attempt; the engine itself adds no retries above them
      - Provider unavailability of a classification is skipped quietly with a WARNING: the failure raises without a verdict — the failed check itself is the primary signal
      - Exactly one failed check drives the bounded healing rule; the attempt budget is never spent on a legitimately failing assertion beyond it
      - A verdict requested on this path fully reaches the raised error
      - Every verdict-preceded regeneration request carries the classification recommendation — regeneration starts from the diagnosis, not the raw error
      - The raised IncurableStepError carries the failed step code in the code field
      - The retry request after a blocking finding carries the grown history — the violation text rides the record's error field, the model fixes the finding targeted
      - Medium and low compliance findings pass with a visible WARNING through the library logger — structured, naming the step and the findings
      - The compliance gate itself consumes no attempt budget; only a blocking finding consumes the attempt it fails
      - The accepted execution's captures publish exactly once — after validation and the gate; retries, violations and gate-blocked candidates publish nothing
      - The raw template sentence never reaches a request; raised failures carry the prepared instruction as the step text
    ```

  - `StepGenerator` → `regenerate` — replaced signature and annotation:

    ```yaml
    "regenerate(identity: StepIdentity, prepared: PreparedStep, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt], recommendation: str, window: SettleWindow, memory: StepMemory) -> step: CachedStep": |
      Regenerate a failed step for healing.

      `prepared`: the render product of the row or healed step — carried into every request with its INPUTS and RESULTS blocks; passed by the calling path: the healer threads the executor's product, the recovery re-renders the row step against the current context.
      `step_type`: action or assertion — carried into every request.
      `group_prompt`: the group prompt of the row step's group — the recovery row passes it; non-empty: the request carries the framing per `group_framing`; None — an ordinary regeneration.
      `attempt_history`: the anchored per-step attempt history — record 0 carries the original cached code composed by the caller; this loop appends after every attempt that does not produce a cached step; the original is never lost to a re-binding.
      `recommendation`: the diagnosis of the classification that launched the healing; non-empty — rendered into every request as the RECOMMENDATION block.
      `window`: the settle window of the current step execution.
      `memory`: the test memory — publication at the acceptance point, as in generate.

      Algorithm:
      1. The same loop as the generate method with the same differences as today plus: every provider request carries `prepared` (instruction, inputs, declarations), `step_type` and the rendered `attempt_history`; attempts consume the healing budget via try_healing; candidate executions run under `settle` with `window`, the URL pair bracketing each attempt; a returned-result violation of `validate_step_result` — a failed attempt of any kind, appended and retried with the fresh failure description while attempts remain; every successfully executed and validated candidate is gated through `check_step_compliance` before storing — the same two-dimension semantics as generate; on gate pass the captures publish through `memory` before the store and return
      2. A budget exhaustion raises `IncurableStepError` without an extra classification — the verdict of the entry classification is carried, the reason names the exhausted pool

      Requirements:
      - The retry request after a blocking finding carries the grown history — the violation text rides the record's error field, the model fixes the finding targeted
      - Medium and low compliance findings pass with a visible WARNING through the library logger — structured, naming the step and the findings
      - The compliance gate itself consumes no attempt budget; only a blocking finding consumes the attempt it fails
      - The publication requirements of generate apply: exactly once, after validation and the gate; nothing publishes on a failed or gate-blocked attempt
    ```

  - `format_step_error`: = PRESERVED =
  - `run_step_code` — replaced signature and annotation:

    ```yaml
    "run_step_code(code: str, page: PageFacade) -> result: dict[str, str] | None":
      location: execution.py
      annotations: |
        Execute step code of the fixed form: compile and resolve on the calling thread, run the whole step inside the driver worker thread against the genuine sync Page — and return the step function's result.

        `code`: the step code text.
        `page`: the page handle of the current test — the carrier of the worker boundary.
        `result`: the step function's return as-is — the dictionary of declared names to observed strings for a step with declarations, None for a declaration-free step; plain data only.

        Algorithm:
        1. Compile and load `code` as a module in an isolated namespace — on the calling thread, Playwright untouched
        2. Resolve the step function of the fixed form — the single callable receiving the page
        3. Execute the whole step-function call inside the driver worker thread as one unit through the run primitive of `page` — the step function receives the genuine sync Page and works through the standard Playwright sync API
        4. An exception raised by the step code propagates to the caller as-is; a return value passes back as-is — plain data

        Requirements:
        - A failure inside the step code reaches the caller untouched: the engine classifies it, this routine never swallows, translates or retries
        - Executing step code loads no LLM provider and touches no network beyond the page itself
        - The calling thread never touches Playwright: the worker boundary is crossed only by the run primitive

        Constraints:
        - Execute only step code produced by generation or loaded from the cache — never arbitrary file content
    ```

  - `classify_step_failure` — signature unchanged; the `step_text` paragraph of the annotation replaced:

    ```
    `step_text`: the prepared instruction of the failed step as passed by the calling engine — the code was generated for it; never the raw template sentence.
    ```

  - `check_step_compliance` — replaced signature and annotation:

    ```yaml
    "check_step_compliance(config: Config, provider: LLMProvider, prepared: PreparedStep, step_type: str, code: str, attempt_history: list[StepAttempt]) -> findings: list[ComplianceFinding]":
      location: compliance.py
      annotations: |
        Gate a successfully executed candidate on two dimensions — instruction compliance and step adequacy — the single gate of every caching path; the verdict request renders the prepared instruction with its INPUTS and RESULTS blocks so the reviewer judges the result-returning code against the declared contract.

        `config`: project settings — the gate switch and the generation instructions.
        `provider`: the LLM port.
        `prepared`: the render product of the generated step — instruction, input bindings, result declarations.
        `step_type`: action or assertion — the adequacy dimension judges by it.
        `code`: the successfully executed candidate code — with the result return when declarations are present.
        `attempt_history`: the step's attempt history — rendered through the record render and passed to the verdict request as the ATTEMPT HISTORY block.
        `findings`: the verdict findings of both dimensions; empty — compliant and adequate, or the gate is off.

        Algorithm:
        1. The generation_approve setting is off or the generation_prompt setting is empty — return an empty list with zero provider calls: fully the old behavior
        2. Ask the provider port check_instruction_compliance passing `compliance_prompt` as the system prompt, the effective config generation_prompt as the user instructions, `prepared` (instruction, inputs, declarations), `step_type`, `code` and the rendered `attempt_history`
        3. Return the findings

        Requirements:
        - Never called for replayed cached code — the gate checks candidates before caching
        - A high finding of either dimension blocks: the calling loop turns it into the failed attempt — the finding text rides the attempt record's error field
        - Provider unavailability and a malformed verdict propagate to the caller as the hard failures they are: this routine never swallows, the calling path never caches

        Constraints:
        - No attempt budget is consumed here — budgets belong to the calling loops
    ```

  - `StepHealer` → `heal` — replaced signature and annotation:

    ```yaml
    "heal(step: CachedStep, error: str, prepared: PreparedStep, step_type: str, previous_steps: list[ScenarioStep], page: PageFacade, attempt_history: list[StepAttempt], window: SettleWindow, memory: StepMemory) -> step: CachedStep": |
      Classify and heal a failed cached step.

      `error`: the full failure description of the cached replay — carried by record 0.
      `prepared`: the render product of the failed step — the classification and every regeneration request carry the prepared instruction with its INPUTS and RESULTS blocks.
      `step_type`: action or assertion — forwarded into every regeneration request.
      `previous_steps`: the typed scenario records of the previous steps of the test, in execution order — each carries the raw sentence for addressing, the prepared instruction rendered in requests, and permanent group membership; never the normalized addressing forms.
      `attempt_history`: the anchored per-step attempt history — record 0 carries the original cached code seeded by the executor; threaded into the regeneration loop which appends every further attempt.
      `window`: the settle window of the current step execution.
      `memory`: the test memory — the accepted regeneration's captures publish inside the regeneration loop at the acceptance point (see `memory` from Imports).

      Algorithm:
      1. Classify the failure via `classify_step_failure` passing the prepared instruction — the verdict is a `FailureClassification`
      2. Report on_healing_started with the category
      3. product_defect: raise `ProductDefectError` carrying the verdict built from the classification and the full underlying error in the error field — the message states what was expected against what was observed; the recommendation reaches the error through the verdict
      4. incurable: raise `IncurableStepError` carrying the verdict and the full underlying error in the error field; the reason names the classification explanation of incurability
      5. rot and fixable: regenerate via the generator regenerate — the request carries `prepared`, `step_type`, the classification recommendation, the anchored `attempt_history` and `memory`; the loop executes the candidate under the settle window, validates the returned result, gates it, publishes the captures at the acceptance point and stores the healed step on success; report on_healed with the explanation of what failed and what changed, return the healed step
      6. A regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the step 1 classification — the reason names the exhausted pool; no extra LLM request is made
      7. Provider unavailability of the classification surfaces as `LLMUnavailableError` — an explicit infrastructure failure

      Requirements:
      - Anti-masking: healing may only turn a rot- or fixable-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution
      - Every verdict produced on the paths of this method fully reaches the raised error; the raised IncurableStepError carries the failed step code in the code field
      - Nothing publishes on a failed or gate-blocked regeneration
    ```

- Footer: `Author: Goga`; `CreatedAt: 10/09/26` (original); `Description` replaced:

  ```
  The agent engine of prettyplay: step code generation against the standard Playwright API with execution in the loop, prepared instructions with input bindings and result declarations in every request, deterministic result validation and capture publication at the acceptance point, one continuous verbatim per-step attempt history, honest request inputs, the fixed-form execution routine returning the step's result inside the driver worker thread, the two-dimension instruction compliance and step adequacy gate before caching, the shared classification call, the error-text policy shared with the executor, and healing with anti-masking and verdicts on terminal failures, the typed scenario context and the group-framing input of generation.
  ```

#### Project practice `.goga/usages/prompts/step_generation.md` — UPDATE

- Input list changes: `STEP: the prepared instruction of the step — the plain-text sentence with actual values embedded`; two inputs added after STEP:

  ```
  - INPUTS: the call input bindings, one name = value line each — present when the step carries inputs
  - RESULTS: the declared result names — present when the step declares captures; the code must return a dictionary of exactly these names to non-blank strings observed on the page
  ```

- Output-form paragraph replaced:

  ```
  Output exactly one Python code block with one function of the fixed form:

  - without RESULTS: def step(page) -> None: ...
  - with RESULTS: def step(page) -> dict[str, str] | None: ... — return the dictionary of exactly the declared names to values actually read from the current page
  ```

- Rules — added:

  ```
  - When the request carries a RESULTS block: read every declared value from the current page — never fabricate, never reuse values from HISTORY; return all declared names in one dictionary; every value is a non-blank string; a missing observation fails the step rather than fabricating a value
  ```

#### `.usages/` files

- `generation.md` — UPDATE: the generate example passes `prepared=PreparedStep(...)`, `memory=memory`; the loop description becomes "request code → execute against the live page → validate the returned result → append the full attempt record → on failure re-request with the fresh snapshot and the grown history"; new section:

  ```markdown
  ## Result contract

  A candidate of a step with result declarations must return the dictionary of exactly the declared names to
  non-blank observed strings. After a successful execution the loop validates it deterministically
  (`validate_step_result` from the renderer): a violation is a failed check — the record lands in the history with
  the violation text, the existing classification and healing budgets apply. A valid result publishes to the test
  memory together with the gate pass: an accepted candidate publishes its captures exactly once, after validation
  and the compliance gate; failed and gate-blocked attempts publish nothing.
  ```

- `healing.md` — UPDATE: the heal example passes `prepared=`, `memory=`; the paragraph "The raw `step_text` and the step type ride every classification and regeneration request" becomes "The prepared instruction and the step type ride every classification and regeneration request — the casefolded normalization is an addressing key only"; a rule added: "The accepted regeneration publishes its validated captures after the gate — nothing publishes on a failed or gate-blocked attempt".

---

### 6. `prettyplay/engine/groups` (MODIFY)

#### CODEMANIFEST `prettyplay/engine/groups/CODEMANIFEST`

- Header
  - `Imports`: = PRESERVED = with one block added:

    ```yaml
      - Types:
          - PreparedStep
          - StepMemory
          - render_step
        Usages:
          - rendering
          - memory
          - validation
        From: prettyplay/engine/renderer
    ```

  - `Usages`: = PRESERVED =
  - `Annotations`: = PRESERVED = except replace the existing "Honest inputs" line with the text below. Add the following six lines:

    ```
    Honest inputs: group diagnosis renders the prepared instructions from its local scenario and trace views and the failed prepared instruction; regeneration uses each freshly rendered row instruction. Raw template sentences remain available for row re-rendering and cache addressing. The group prompt still joins requests verbatim and remains subject to the never-put-secrets rule.
    ```

    ```
    Use `rendering` from Imports for the row re-render patterns of the recovery.
    Use `memory` and `validation` from Imports for the per-step capture publication and the result acceptance of the row.
    Recovery re-renders against the current context: every row step is prepared anew through `render_step` from Imports before its regeneration — from the trace's template sentence, the step's recorded inputs and the current memory; the failed step's own render product threads in from the executor.
    Recovery keeps local copies of previous scenario records and group traces. After each accepted row step, replace that occurrence's instruction in these local views with its newly prepared instruction before building later requests or a new diagnosis; the test's stored records and appended traces remain immutable. Locate occurrences by group order, not sentence equality, because step sentences may repeat.
    Recovery also keeps the active failure facts locally: the failing row step's prepared instruction, step type, identity, attempt history and underlying error. A failed regeneration updates those facts before another diagnosis; STEP and HISTORY always describe the failure that triggered that diagnosis, while a fully successful row returns the healed code of the originally failed step.
    Accepted row steps publish their captures immediately through the `StepMemory` from Imports at each step's acceptance point — after validation and the compliance gate; a later row failure never rolls back the published values; steps left behind retain their last accepted values; the failed step's accepted captures publish with its acceptance and it is never executed again merely to recover them.
    The diagnosis request and the row matcher work on prepared instructions: the traces render their instruction field and the earliest-step quote matches against instructions — what the model saw; the raw template sentences never reach a request.
    ```

- Body
  - `GroupStepOutcome` — replaced declaration (fields + render):

    ```yaml
    "GroupStepOutcome(sentence: str, instruction: str, step_type: str, tries: int | None, delay: float | None, vars: dict[str, str], outcome: str, url_before: str, url_after: str, identity: StepIdentity)":
      location: outcome.py
      annotations: |
        One verbatim trace record of a group step's execution — the unit the GROUP STEPS block of the diagnosis request renders.

        `sentence`: the raw sentence of the step (the template source), verbatim — the re-render source of the row mechanics, never rendered into requests.
        `instruction`: the prepared instruction recorded at the step's execution — what the GROUP STEPS block renders and the matcher matches against; equals `sentence` for a non-template step.
        `step_type`: action or assertion.
        `tries`: the declared retry count of the step; None — the step is governed by the global polling settings.
        `delay`: the declared start pause of the step in seconds; None — no pause.
        `vars`: the call-local input bindings of the step's original call — the re-render input of the row mechanics.
        `outcome`: passed or failed.
        `url_before`: the page URL read immediately before the step's execution.
        `url_after`: the page URL read immediately after the step's execution.
        `identity`: the cache address of the step — recorded by the executor when the trace is appended; the addressing metadata of the row mechanics (regeneration and the healing-counter refresh resolve row steps by it), never rendered into the GROUP STEPS block.

        Requirements:
        - pydantic v2, kw_only, empty defaults (see `conventions`)
        - A record is immutable once appended: no rewriting, no truncation
      properties:
        "sentence -> str": |
          The raw sentence (the template source) of the group step, verbatim.
        "instruction -> str": |
          The prepared instruction recorded at execution; equals the sentence for a non-template step.
        "step_type -> str": |
          The step kind: action or assertion.
        "tries -> int | None": |
          The declared retry count; None — the global polling settings govern the step.
        "delay -> float | None": |
          The declared start pause in seconds; None — no pause.
        "vars -> dict[str, str]": |
          The call-local input bindings of the step's original call.
        "outcome -> str": |
          The execution outcome: passed or failed.
        "url_before -> str": |
          The page URL read immediately before the step's execution.
        "url_after -> str": |
          The page URL read immediately after the step's execution.
        "identity -> StepIdentity": |
          The cache address of the step; recorded at trace time, never rendered.
      methods:
        "render() -> record: str": |
          Render the complete verbatim trace — the unit the GROUP STEPS block renders.

          `record`: the multi-line trace text.

          Algorithm:
          1. The instruction line — the prepared instruction verbatim
          2. The outcome line — the outcome label
          3. The URL line — url_before, an arrow, url_after

          Requirements:
          - No collapsing, no size limits, no truncation of any field
    ```

  - `classify_group_failure` — replaced signature and annotation:

    ```yaml
    "classify_group_failure(config: Config, provider: LLMProvider, group_prompt: str, traces: list[GroupStepOutcome], previous_steps: list[ScenarioStep], step_text: str, step_type: str, attempt_history: list[StepAttempt], page: PageFacade) -> diagnosis: GroupFailureClassification":
      location: diagnosis.py
      annotations: |
        Compose one group diagnosis request from the prior scenario and the group traces.

        `previous_steps`: the previous steps of this test, in execution order; provide their prepared instructions to the provider for outside-group root diagnosis.
        `traces`: group records whose render method emits prepared instructions in GROUP STEPS.
        `step_text`: the failed step's prepared instruction, passed from recovery as STEP; never the raw template sentence.
        `diagnosis`: the parsed group verdict.

        Algorithm:
        1. Read the current page snapshot and optional screenshot as before.
        2. Render the traces and attempt history verbatim.
        3. Call the provider with `previous_steps` and the prepared `step_text`, preserving the existing group prompt and classification instructions.
        4. Preserve the existing conservative handling of degraded verdicts and unavailable providers.

        Requirements:
        - The returned earliest_step is matched verbatim against trace and previous-scenario instruction fields; raw sentences remain only for row re-rendering and addressing.
    ```
  - `GroupRecovery` → `recover` — replaced signature and annotation:

    ```yaml
    "recover(group_prompt: str, traces: list[GroupStepOutcome], prepared: PreparedStep, step_type: str, previous_steps: list[ScenarioStep], identity: StepIdentity, attempt_history: list[StepAttempt], page: PageFacade, window: SettleWindow, memory: StepMemory) -> step: CachedStep": |
      Diagnose a failed group step and recover the affected row.

      `group_prompt`: the group prompt, verbatim — reaches the diagnosis and every row request.
      `traces`: the group's step traces with instructions, outcomes and URL transitions.
      `prepared`: the render product of the failed step — threaded from the executor; its requests and failures carry the prepared instruction with its INPUTS and RESULTS blocks.
      `step_type`: action or assertion.
      `previous_steps`: the typed scenario records of the test, in execution order — recovery copies them into a local view and updates accepted row instructions for later requests, preserving the caller's records.
      `identity`: the address of the failed step.
      `attempt_history`: the per-step attempt history grown to the failure.
      `page`: the live page facade — the row re-executes forward on the current page.
      `window`: the settle window of the failed step's execution.
      `memory`: the test memory — the publication point of every accepted row step and the failed step (see `memory` from Imports).
      `step`: the healed cached step of the failed step.

      Verdict mapping: every raised terminal failure carries a `FailureVerdict` — a diagnosis verdict maps onto it (category as is — product_defect and incurable are taxonomy labels, recoverable never raises; explanation ← root_cause plus the earliest_step quote when it names a step; recommendation ← recommendation); a refused cycle authors its own — category incurable, the explanation naming the exhausted per-group cycle cap (colon-free); an outside-group root — category incurable, the explanation naming that step verbatim (colon-free).

      Algorithm:
      1. Open a recovery cycle via budgets open_group_cycle keyed by the group prompt; a refused cycle raises `IncurableStepError` carrying the verdict naming the exhausted cycle cap — the reason colon-free, one render
      2. Copy the prior scenario records and group traces into recovery-local views on entry. Initialize the active failure from the executor's `prepared`, `step_type`, `identity` and `attempt_history`; derive its underlying error from that history. Diagnose via `classify_group_failure`, passing the local views and the active failure's instruction as STEP and its history as HISTORY. On later cycles, diagnose with the updated local views and active failure. A product_defect verdict raises `ProductDefectError` carrying the active failure verdict and underlying error; an incurable verdict raises `IncurableStepError` carrying them
      3. Match the earliest affected step: an exact verbatim match of earliest_step against the local traces' current instructions names the row start; an exact match against a step of the test outside the group raises the honest terminal `IncurableStepError` whose verdict names that step — recovery is out of mandate; no match degrades to the active failure's occurrence in the group
      4. Grant every row step a fresh healing counter via budgets refresh_healing
      5. The row — from the earliest affected step through the failed step, the group's own steps only — sequentially: the step's declared delay passes quietly; re-render the step through `render_step` from Imports — the trace's sentence, step type, recorded `vars` and the current `memory` produce a fresh `PreparedStep` against the current context; the step regenerates via the generator regenerate carrying the fresh prepared step, the diagnosis recommendation, the group framing per `group_framing`, the recovery-local scenario view, the grown attempt history, the step's own window built from its declared tries and the trace identity, and `memory`; the candidate executes immediately on the current page inside the regeneration loop; the returned result validates; the two-dimension compliance gate guards the write-back; the captures publish through `memory` at the step's acceptance; the cache stores the step; update that step occurrence's instruction in the local scenario and trace views before the next row request; report on_healing_started and on_healed for the recovered step; a structured log record names the diagnosis and the row composition
      6. A repeat failure of a row step — an `IncurableStepError` from regeneration — updates the active failure to that row occurrence's fresh `PreparedStep`, step type, identity, grown row attempt history and underlying error; mark that occurrence failed in the local trace view, preserving its freshly prepared instruction. Then re-enter a fresh diagnosis and cycle from step 1 with those facts, while cycles remain. The caller's stored traces and scenario records are not rewritten
      7. On success return the healed cached step of the failed step — the group continues normally

      Requirements:
      - Strict mode never invokes this engine — the executor guards the gate
      - The row never leaves the group's steps
      - Anti-masking: a product_defect diagnosis always fails the test loudly
      - One render per terminal failure — the existing taxonomy, exactly once
      - The recovery is loudly reported through the healing events and the log records
      - Every accepted row step publishes its validated captures at its own acceptance point — a later row failure never rolls them back; the failed step's captures publish with its acceptance, never through a re-execution
      - A new diagnosis after a row failure uses the actual failing row step's STEP and HISTORY, not the executor's original failure; after full row success the return value remains the healed cached step of the originally failed step
      - A re-render authoring error of a row step surfaces as that step's failure — loud, never silently skipped

      Constraints:
      - No page-state rollback — forward re-execution only
      - No new failure kinds — the existing taxonomy carries every terminal outcome
      - The ordinary per-step healing pools of non-group steps are never consumed
    ```

- Footer: `Author: Goga`; `CreatedAt: 16/09/26` (original); `Description` replaced:

  ```
  The group recovery of prettyplay: the group-level diagnosis request over the whole interaction, the group-scoped affected row with per-step re-rendering against the current context, sequential regeneration and immediate forward re-execution, the compliance-gated per-step cache write-back with capture publication at each acceptance, and the bounded recovery cycles with fresh healing counters per cycle.
  ```

#### Project practice `.goga/usages/prompts/group_diagnosis.md` — UPDATE

- Describe PREVIOUS STEPS as the prior scenario's prepared instructions in execution order (with group membership), GROUP STEPS as the recorded prepared instructions with outcomes and URL transitions, and STEP as the failed prepared instruction. The `earliest_step` answer must quote a visible instruction verbatim, including one from PREVIOUS STEPS when the root is outside the group; raw template sentences are not request content.

#### `.usages/` files

- `recovery.md` — UPDATE: the recover example passes `prepared=PreparedStep(...)`, `memory=memory` (replacing `step_text=`); cycle step 3 replaced:

  ```markdown
  3. `recoverable`: the row runs from the earliest affected group step through the failed step — each step is
     re-rendered against the current context (its template sentence, its recorded inputs, the current memory),
     regenerates as its own unit (the diagnosis recommendation + the group framing ride the request), re-executes
     immediately on the current page, validates its returned result, passes the two-dimension compliance gate,
     publishes its captures to the test memory and writes back to the cache per step.
  ```

  New section appended:

  ```markdown
  ## Memory and re-render

  - Row steps re-render through `render_step` — recovery never reuses a stale instruction: the current memory and
    the step's recorded inputs produce the fresh one
  - Recovery keeps local copies of previous scenario records and group traces. After each accepted row step, its
    newly prepared instruction replaces that occurrence in the local views used by later row requests and diagnoses;
    the test's stored records and appended traces remain immutable
  - A failed row regeneration becomes the active failure for the next diagnosis: STEP and HISTORY describe that row
    step and its latest attempt; a complete row still returns the healed code of the originally failed step
  - Every accepted row step publishes its captures immediately; a later failure in the row never rolls back accepted
    values — steps left behind keep their last accepted observations
  - Traces carry the instruction (what the model saw and what the row matcher quotes) and the original `vars` of
    each step's call
  ```

---

### 7. `prettyplay/engine/steering` (MODIFY)

#### CODEMANIFEST `prettyplay/engine/steering/CODEMANIFEST`

- Header
  - `Imports`: = PRESERVED = with one block added:

    ```yaml
      - Types:
          - PreparedStep
          - StepMemory
          - validate_step_result
        Usages:
          - memory
          - validation
        From: prettyplay/engine/renderer
    ```

  - `Usages`: = PRESERVED =
  - `Annotations`: = PRESERVED = except replace the existing "Every guidance turn" line with the text below. Add the following three lines:

    ```
    Every guidance turn is a regeneration request carrying the step type and prepared instruction with current input bindings and result declarations, plus the scenario records' instruction fields and grown attempt history. The raw template sentence stays outside the request; record 0 still anchors the original failure.
    ```

    ```
    Use `memory` and `validation` from Imports for the publication point and the result validation of an accepted turn.
    The dialog works on the prepared instruction: every guided regeneration request carries the stuck step's render product — instruction, input bindings, result declarations (INPUTS/RESULTS blocks); the raw template sentence never reaches a request; the banner shows the prepared instruction.
    A green turn publishes its captures: the executed candidate's returned result validates through `validate_step_result` from Imports and the captures publish through the `StepMemory` from Imports after the compliance gate — a rejected, failed or gate-blocked turn publishes nothing.
    ```

- Body
  - `StepSteering` → `steer` — replaced signature and annotation:

    ```yaml
    "steer(failure: IncurableStepError, identity: StepIdentity, prepared: PreparedStep, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt], memory: StepMemory) -> healed: CachedStep | None": |
      Run the steering dialog over a terminal failure.

      `failure`: the terminal failure about to propagate — the source of the failed code, the underlying error and the verdict.
      `identity`: the address of the stuck step — the healed step is written back under it.
      `prepared`: the render product of the stuck step — threaded from the executor; the banner and every guided request carry the prepared instruction with its INPUTS and RESULTS blocks.
      `step_type`: action or assertion — carried into every guided request and the gate verdict.
      `previous_steps`: the typed scenario records of the previous steps of the test — requests render each prepared instruction with its permanent group membership; raw sentences remain local metadata.
      `group_prompt`: the group prompt of the stuck step's group; None — an ordinary step; non-empty — every guidance request of this dialog carries the group framing per `group_framing`.
      `page`: the live page facade of the test.
      `attempt_history`: the shared per-step attempt history grown by the engine loops and anchored by record 0 — the dialog appends every completed turn to it.
      `memory`: the test memory — the publication point of the accepted turn (see `memory` from Imports).
      `healed`: the healed cached step on a successful guided execution; None — the dialog declined or died: the caller propagates the original failure.

      Algorithm:
      1. Render the context banner once: the prepared instruction, the failed code, the terminal error render of `failure`, the current URL read from `page`, a screenshot path, the commands — no snapshot fragment
      2. Read the guidance line; quit, EOF, SIGINT or an unreadable stdin — return None
      3. A local command runs without the LLM: snapshot — the full accessibility snapshot; screenshot — a full PNG written to a temporary file with the path printed; error and code — the stored texts; back to step 2
      4. A guidance message builds one regeneration request via the provider: `system_prompt` as the system prompt, the cheat-sheet from `cheat_sheet`, `prepared` (instruction, inputs, declarations) with `step_type` and `previous_steps` as the scenario context — the request carries the group framing per `group_framing` when the step belongs to a group — the fresh accessibility snapshot plus the screenshot when the project settings enable screenshots, the current URL read from `page` as the page URL input, the user instructions — the effective config generation_prompt — when non-empty, the message as the guidance and the rendered `attempt_history` as the HISTORY block — every record verbatim, the anchored original first
      5. Show the complete generated code to the engineer, then the confirmation prompt run? [y/N]: y — proceed to step 6; n, Enter or quit — the turn is aborted without execution, the rejected candidate enters `attempt_history` as a completed record with the outcome rejected by the engineer, not executed, and the same URL on both sides, back to step 2
      6. Read the page URL, execute the candidate via `run_step_code` against `page` — the whole step runs inside the driver worker thread and returns its result; the settle window never re-arms inside the dialog; read the page URL again — the pair brackets the turn
      7. Success: validate the returned result through `validate_step_result` from Imports — a violation shows in the dialog, appends the completed record (outcome failed check, complete code, the violation text), returns to step 2. A valid result: gate the executed candidate through `check_step_compliance` with `prepared`, `step_type` and `attempt_history` — the gate switch off or empty generation instructions yield an empty findings list with zero provider calls. An empty findings list: publish the captures through `memory`, build `CachedStep` with `identity`, save it to the cache, report on_healed with an explanation naming the interactive healing, return the healed step. A high finding of either dimension: no write-back — show the violation in the dialog (the finding instruction and explanation), append the completed record — outcome compliance blocked, complete code, complete violation text — to `attempt_history`, return to step 2. Medium and low findings pass with a WARNING naming the instructions, then the publication and write-back. The gate hard failures — provider unavailability and a malformed verdict — end the dialog after showing the gate failure line in the dialog and logging a WARNING through the library logger naming the step and the gate failure: return None, the original terminal failure propagates; nothing is cached, nothing publishes
      8. A failed execution: show the complete error, append the completed record to `attempt_history` — outcome failed check for an AssertionError, execution failed otherwise, complete code, complete outcome — return to step 2 — no re-execution of the same code, the settle window never re-arms
      9. Provider unavailability of the request: the dialog ends, return None

      Requirements:
      - The write-back happens only after a successful execution, a valid result and a passed two-dimension gate; the captures publish with the write-back
      - No code executes without the engineer approval of this turn
      - A rejected, failed or gate-blocked turn always enters the shared history before the guidance prompt reopens — and never publishes
      - No generation or healing budget is consumed; no polling applies
      - The dialog never outlives the failure: every exit path either heals or returns None

      Constraints:
      - Never persist the guidance into the cache file
      - Never introduce history size limits or line collapsing; never truncate a record
    ```

- Footer: `Author: Goga`; `CreatedAt: 12/09/26` (original); `Description` replaced:

  ```
  The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration carrying the prepared instruction with input/result bindings against the standard Playwright API, the shared per-step attempt history and honest inputs, live execution with result validation inside the driver worker thread, the two-dimension compliance-gated healed write-back with capture publication, or honest decline.
  ```

#### `.usages/` files

- `steering.md` — UPDATE: the steer example passes `prepared=PreparedStep(...)`, `memory=memory` (replacing `step_text=`); added notes:

  ```markdown
  - The banner and every guided request carry the prepared instruction — with INPUTS and RESULTS blocks when the
    step carries inputs or declarations; the model never sees raw Jinja
  - A green turn: execute → validate the returned result (a violation is a red turn with the deterministic text) →
    the compliance gate → the captures publish to the test memory together with the write-back; a rejected, failed
    or gate-blocked turn publishes nothing
  ```

---

### 8. `prettyplay` (MODIFY)

#### CODEMANIFEST `prettyplay/CODEMANIFEST`

- Header
  - `Imports`: = PRESERVED = with one block added:

    ```yaml
      - Types:
          - PreparedStep
          - StepMemory
          - render_step
          - validate_step_result
        Usages:
          - rendering
          - memory
          - validation
        From: prettyplay/engine/renderer
    ```

  - `Usages`: = PRESERVED =
  - `Annotations`: = PRESERVED = except replace the existing "Honest inputs thread end to end" line with the text below. Add the following five lines:

    ```
    Honest inputs thread end to end through the executor: the raw step sentence establishes cache identity and supports re-rendering; the prepared instruction, input bindings, declarations and scenario instruction fields reach engine and LLM requests. The per-step attempt history remains anchored by the original cached code on failed replay.
    ```

    ```
    Use `rendering`, `memory` and `validation` from Imports for the render point, the test memory and the result acceptance of the executor.
    The render point lives in the executor: every step — facade or group — is prepared through `render_step` from Imports before its cycle; authoring errors (a duplicate capture declaration, the reserved name `vars`, an invalid capture name, a capture tag in an expect, an unavailable name) raise the loud actionable `PrettyplayError` before any browser execution; memory and `vars` stay separate namespaces.
    The memory of the test lives in the executor: one `StepMemory` from Imports per test execution; rendering reads its snapshot; validated captures publish after full acceptance — the executor publishes the validated result of a cached replay, the engines publish at their acceptance points; navigation never discards memory; memory never crosses tests.
    The authoring surface: step and expect accept the keyword-only retry count, start pause and the string input mapping `vars`; non-string values of `vars` raise the loud actionable `PrettyplayError` naming the parameter, the received value and the allowed form; template sentences address the cache by their source and render to prepared instructions every request carries.
    The scenario records carry both texts: the raw sentence (the addressing artifact) and the prepared instruction (what requests render); failures carry the prepared instruction.
    ```

- Body
  - Embeddings and `PrettyPlay` constructor/other methods: = PRESERVED =; methods `step`/`expect` replaced:

    ```yaml
    "step(text: str, tries: int | None, delay: float | None, vars: dict[str, str] | None)": |
      Execute the action step `text` — a plain sentence or a Jinja template with capture declarations.

      `text`: the step sentence — an ordinary sentence or a template; rendered by the executor before the cycle.
      `tries`: keyword-only — the total number of executions of the step's code, a positive integer, the first execution included; invalid values — zero, negative, non-integer — raise the loud actionable `PrettyplayError` naming the parameter, the received value and the allowed form.
      `delay`: keyword-only — the quiet pre-step pause in seconds, non-negative, fractional allowed; a negative or malformed value raises the same loud error.
      `vars`: keyword-only — the call-local string inputs; every value must be a str, otherwise the loud actionable `PrettyplayError` naming the parameter, the received value and the allowed form; a separate namespace from memory — `{{ name }}` reads memory, `{{ vars.name }}` reads the input; call inputs never establish memory.

      Delegates to the executor execute with the step type action, the sentence, `vars` and the test page; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`); authoring errors of the template surface as the loud actionable `PrettyplayError` before any browser execution.
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary — the existing guarantee preserved verbatim.
    "expect(text: str, tries: int | None, delay: float | None, vars: dict[str, str] | None)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      (the same keyword-only `tries`, `delay` and `vars` parameters and the same validation as step)
      Delegates to the executor execute with the step type assertion; capture declarations in the sentence are authoring errors raised by the render before any browser execution; failures propagate by kind (see `taxonomy`); the traceback folding guarantee is preserved verbatim.
    ```

  - `StepGroup` — constructor and properties: = PRESERVED =; `traces` semantics note: the records carry the sentence, the prepared instruction, the step type, the declared tries/delay/vars, the outcome and the URL pair. Methods `step`/`expect` replaced:

    ```yaml
    "step(text: str, tries: int | None, delay: float | None, vars: dict[str, str] | None)": |
      Execute the action step `text` inside the group — the ordinary step surface with the group context: validates
      like the facade methods (including the string-only `vars`), delegates to the executor execute with this group,
      records the step trace — the sentence, the prepared instruction, the step type, the declared tries/delay/vars,
      the outcome and the URL pair bracketing the step.
    "expect(text: str, tries: int | None, delay: float | None, vars: dict[str, str] | None)": |
      Execute the assertion step `text` inside the group — the same delegation and trace as step, assertion kind;
      capture declarations are authoring errors of the render.
    ```

  - `StepExecutor` — replaced declaration:

    ```yaml
    "StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, steering: StepSteering, recovery: GroupRecovery, budgets: RunBudgets, reporter: StepReporter, config: PrettyConfig, provider: LLMProvider)":
      location: executor.py
      annotations: |
        The owner of the step cycle, the per-step attempt history and the test memory: render — cache hit — execute; cache miss — generate and store; cached failure — heal; in strict mode the cycle is replay-only: nothing is ever (re)generated. Every execution of step code — cached code and candidates alike — goes through settle with run_step_code: the worker-thread boundary is encapsulated inside run_step_code, the executor never sees it. Constructs the test's own `StepMemory` (see `memory` from Imports) — one per test execution.

        `cache_key`: the context key of the owning test object.
        `cache`: the step cache of the test.
        `generator` and `healer`: the engines (see `generation` and `healing` from Imports) — never invoked in strict mode.
        `steering`: the interactive steering of terminally stuck steps — invoked only on a non-strict interactive run; never in strict mode.
        `recovery`: the group recovery engine — invoked only on a non-strict run for a group step; never in strict mode.
        `budgets`: the per-test attempt registry — never consumed in strict mode.
        `reporter`: the visibility point.
        `config`: the effective settings of the test — the source of the strict switch.
        `provider`: the LLM port of the test — the source of the strict-path classification.
        A classification reached on the strict path is carried by the raised terminal failure as a `FailureVerdict`.
      methods:
        "execute(step_text: str, step_type: str, page: PageFacade, group: StepGroup | None, tries: int | None, delay: float | None, vars: dict[str, str] | None)": |
          Run one step through the full cycle.

          `vars`: the validated call-local string inputs — passed by the facade/group methods; rendered into the step's `PreparedStep`, never published to memory.

          Algorithm:
          1. Report on_step_started with the sentence and the step type; a declared `delay` passes quietly — the step's started event fires, the declared seconds pass, then the step's code runs; a step never reached after a terminal failure never pauses
          2. Render through `render_step` from Imports — a snapshot of the test memory plus `vars` produces the `PreparedStep`; authoring errors raise the loud actionable `PrettyplayError` — identity untouched, browser untouched. Build the step identity from the ORIGINAL `step_text`: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type; create a `SettleWindow` of this step execution from the polling settings of the effective config and the declared `tries` — a declared count switches the window to the count-bounded mode; create the per-step attempt history — an empty `StepAttempt` record list
          3. Load the cached step. Strict mode and a miss: raise `IncurableStepError` — the reason states that strict mode forbids generation and names the cache miss, the error field empty, the verdict absent; no generation request is made, no budget consumed. A hit: read the page URL, execute its code under the settle window — `settle` with `run_step_code` returning the step's result, `page` and the window; read the page URL again — the pair brackets the replay. Validate the result through `validate_step_result` from Imports: valid captures — publish through the test `StepMemory` (the gate never runs on replay — acceptance is the validated successful execution); a violation enters the failed-check paths of step 4
          4. On a hit execution failure. Strict mode — classification only: classify via `classify_step_failure` passing the prepared instruction and the full underlying error; a product_defect classification raises `ProductDefectError` carrying the verdict and the full underlying error; a rot, fixable or incurable classification raises `IncurableStepError` carrying them — the reason names the classification explanation; both authored colon-free; never regenerated: the healer is not invoked, the healing budget stays untouched, on_healing_started never fires; an unavailable LLM at this classification is skipped quietly with a WARNING and the failure raises immediately by step type without a verdict — colon-free. Otherwise, a group step (a non-null `group`): delegate to the recovery engine recover with the group prompt, the traces of `group`, `prepared`, the step type, the scenario context, the identity, the anchored history, the window and the memory — instead of the healer; a recovered step continues as success. Otherwise: seed the attempt history with record 0 — a `StepAttempt` of outcome original cached code carrying the cached code, the full replay error formatted by `format_step_error` and the URL pair of the replay — then delegate to the healer heal with `prepared`, the step type, the scenario context, the anchored history, the window and the memory — a healed step is already re-executed, stored and published by the engine
          5. Otherwise on a miss: the generator generate with the window, `prepared`, the step type, the group prompt as the framing input for a group step, the empty attempt history and the memory — the engine stores the step and publishes the accepted captures on success; the group-step generation failures arrive unclassified (the engine suppresses its classification points) and route to the recovery
          6. Steering intercept — wrap the engine paths of steps 4 and 5: a group step's `IncurableStepError` reaches the recovery first on a non-strict run; steering remains the terminal gate for the still-terminal failure — the dialog receives the group context; a raised `IncurableStepError` on a non-strict interactive run goes to the steering steer with the failure, the identity, `prepared`, the step type, the group prompt, the scenario context, the anchored attempt history, the memory and `page` before it propagates; a healed return continues as success — the cache write-back and the capture publication already happened inside the dialog; None — the original failure propagates unchanged. The intercept never triggers on `ProductDefectError`, on `LLMUnavailableError`, in strict mode or when interactive is off
          7. Append the `ScenarioStep` record — the raw sentence, the prepared instruction, plus the group prompt of `group` when inside one, permanent for the test — the previous steps feed the next generation and the row regeneration of the group recovery
          8. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the full render — the rendered message of the raised error, never re-composed; then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields taken from the verdict object; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`)
          9. Report on_step_finished with the sentence, the step type and the outcome — passed or failed — exactly once at the very end of every step, after every other event, regardless of outcome

          Requirements:
          - The scenario context lives per test: steps of different tests never mix
          - The pre-step pause is quiet — elapsed time, no output noise; uniform for the first step of a test, every following step and every re-execution inside a recovery row — the recovery applies the row step's declared delay
          - The scenario context lives per test as typed records; group membership is permanent once recorded
          - A cached step executes with no LLM involvement whatsoever
          - An assertion step surfaces a legitimately failed expectation as the product defect failure
          - Strict mode: the only LLM calls are classifications; the generation and healing budgets are never consumed; the engines are never invoked; the settle window still applies to the cached code
          - The raw step sentence builds the step address; the prepared instruction reaches every engine call; the casefolded normalization is an addressing key only
          - The per-step attempt history lives exactly one step execution: created in step 2, grown by the engine loops and the steering dialog, never carried across steps
          - Record 0 is composed before the heal delegation — a regeneration never loses the original cached code
          - The error text carried by the raised failures: for failed checks — without the AssertionError prefix, the exception type already carries the assertion semantics; for action steps — the full underlying error text with its type; formatted by `format_step_error`
          - One render per terminal failure: the exception message, the on_step_failed error payload and the log record carry the same rendered text
          - One settle window per step execution: created in step 2, threaded into every engine call; the first execution marks its start
          - on_step_finished fires exactly once per step — the closing event of the cycle
          - One render per step execution; recovery re-invocations re-render inside the recovery against the current context
          - An accepted step is never executed again merely to recover its return value
          - The memory lives exactly one test execution; concurrent tests never mix
    ```

  - `PrettyplayRuntime`: = PRESERVED =
- Footer: `Author: Goga`; `CreatedAt: 10/09/26` (original); `Description` replaced:

  ```
  The facade of prettyplay: the per-test scenario object with screenshot abilities and the author escape hatch onto the genuine page, the step cycle executor as the render point of step templates with the per-test memory and atomic capture publication, the strict replay-only path, the per-step attempt history and the honest-inputs threading, verdict reporting, the per-test composition root, the re-exported settings models — PrettyConfig and BrowserConfig, the step parameters (tries, delay, vars), the group authoring block and the group recovery routing.
  ```

#### `.usages/` files

- `steps.md` — UPDATE: new sections inserted (after "Step parameters", which also gains the `vars` bullet: *step(text, vars={"expected": "Details"}) — the call-local string inputs; separate namespace from memory*):

  ```markdown
  ## Templates and step memory

  Capture an observation, navigate, verify — ordinary step and expect calls plus explicit template syntax:

  ```python
  with PrettyPlay("item-name") as t:
      t.step("Open https://shop.example/products")
      t.step("Read the first item name into {% var name %}")
      t.step("Open the item named {{ name }}")
      t.expect("The page contains {{ name }}")
  ```

  - `{% var name %}` declares where the step saves text read from the page; once the step is accepted, `name` is
    available in later templates
  - Several captures in one step publish together — `t.step("Read the first item name into {% var first_name %} and
    the second item name into {% var second_name %}")`; a successful recapture replaces the previous value; a failed
    step publishes nothing
  - Memory survives navigation and belongs to one test execution — never shared across tests, concurrent runs included
  - A same-step read observes the previous value or fails with the unavailable name; use two steps to capture then use
  - Templates are ordinary Python strings — f-strings evaluate before PrettyPlay receives them

  Call-local inputs through the reserved `vars` namespace:

  ```python
  t.expect("The page contains {{ name }} and {{ vars.expected }}", vars={"expected": "Details"})
  ```

  - `{{ name }}` reads memory, `{{ vars.name }}` reads the call input — separate namespaces, neither overwrites the
    other; call inputs never establish memory; values are strings only
  - Standard Jinja stays available (filters, conditions, `set` — template-local); missing values fail loudly naming
    the name; author-written `| default(...)` and `is defined` behave as authored

  ## Literal Jinja in existing sentences

  ```python
  t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
  ```

  ## Cache and replay limitation

  - Template sentences address the cache by their source: `{{ name }}` and `{{ Name }}` are different steps; runtime
    values never enter the address
  - Cached code re-reads captures from the current page on every execution — a changed item name for the same
    operation replays without regeneration
  - Accepted limitation: a template that changes the operation itself may let old cached code succeed at the previous
    operation without triggering healing
  ```

  All other sections: = PRESERVED =.
- `lifecycle.md` — UPDATE: paragraph appended to the "Strict mode" section:

  ```markdown
  Template steps replay like any cached step: captures re-read from the current page, results validate and publish
  on the strict path exactly as on the ordinary replay; strict adds no generation, healing or new checks.
  ```

## Dependency Map

```
prettyplay (facade, M)
 ├── config, reporting, failures, driver          (untouched leaves)
 ├── cache (M) ── config, reporting
 ├── llm (M) ── config, failures                  (primitives only; no renderer import)
 ├── engine (M) ── config, reporting, failures, driver, cache, llm, polling, renderer
 │    ├── polling (M) ── driver
 │    └── renderer (NEW) ── failures
 ├── groups (M) ── config, reporting, failures, driver, cache, llm, engine, polling, renderer
 └── steering (M) ── failures, config, llm, cache, reporting, driver, engine, renderer
```

New inter-cell edges: failures→renderer (PrettyplayError, taxonomy); renderer→engine (PreparedStep, StepMemory, validate_step_result; usages memory, validation); renderer→groups (PreparedStep, StepMemory, render_step; usages rendering, memory, validation); renderer→steering (PreparedStep, StepMemory, validate_step_result; usages memory, validation); renderer→prettyplay (PreparedStep, StepMemory, render_step, validate_step_result; usages rendering, memory, validation). No pairwise cycles.

## Verification Checklist

After implementing each artifact, verify:

| Artifact | Checks |
|---|---|
| `prettyplay/cache/CODEMANIFEST` + `addressing.md` | `goga lint` clean; `{{ name }}` vs `{{ Name }}` produce different filenames; ordinary sentences produce byte-identical filenames to the previous behavior; template sentences differing only in leading/trailing whitespace share an address, while differences in internal prose whitespace or expression whitespace address differently |
| `prettyplay/engine/renderer/CODEMANIFEST` + 3 usage files | `goga lint` clean; facade imports all four names (`python -c "from prettyplay.engine.renderer import PreparedStep, StepMemory, render_step, validate_step_result"`); authoring errors (duplicate declaration, reserved `vars`, invalid name, capture in assertion, missing name) raise `PrettyplayError` before any browser/LLM touch; substituted data never re-rendered; declaration-free render returns empty declarations |
| `pyproject.toml` package metadata | `[project].dependencies` includes `jinja2>=3.1`; a clean install can import Jinja and the renderer; supported Python versions remain unchanged |
| `prettyplay/llm/CODEMANIFEST` + `providers.md` | `goga lint` clean; generation and compliance port signatures carry instruction/inputs/declarations; both providers render INPUTS/RESULTS identically at the fixed positions; empty inputs/declarations render no blocks; ordinary classification and group diagnosis also render prepared instructions only (no raw template anywhere) |
| `prettyplay/engine/polling/CODEMANIFEST` + `settle.md` | `goga lint` clean; settle returns the successful execution's result; window semantics unchanged; result passes through untouched |
| `prettyplay/engine/CODEMANIFEST` + practice + `generation.md`/`healing.md` | `goga lint` clean; generate/regenerate/heal accept prepared+memory; violations enter failed-check paths; captures publish exactly once after validation+gate; gate-blocked attempts publish nothing; `system_prompt` carries the dual code form and the RESULTS rules |
| `prettyplay/engine/groups/CODEMANIFEST` + `recovery.md` + group diagnosis practice | `goga lint` clean; row steps re-render against current context (sentence+step_type+vars); per-row publication survives later row failures; subsequent row requests and new diagnosis cycles use updated recovery-local scenario and trace instructions; diagnosis STEP and HISTORY switch to the actually failed row step on repeat failure; restart matching against instructions |
| `prettyplay/engine/steering/CODEMANIFEST` + `steering.md` | `goga lint` clean; banner/requests carry the prepared instruction; green turn validates → gates → publishes with the write-back; rejected/failed/blocked turns publish nothing |
| `prettyplay/CODEMANIFEST` + `steps.md`/`lifecycle.md` | `goga lint` clean; step/expect accept keyword-only `vars` (string values only, loud error otherwise); executor renders before identity, publishes after acceptance on the replay path; ScenarioStep carries sentence+instruction; non-template steps behave byte-identically |
| Whole feature | `pytest tests/ -x` green; `ruff check` clean; the four task usage examples work as documented; test isolation incl. concurrent runs; strict replay of template steps re-reads captures |

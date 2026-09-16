# Architecture Plan — Pace control, step parameters and step groups

## Topic

**Pace control, step parameters and step groups** for the prettyplay runtime (the approved ADR
`adr.md` and the actualized PRD `prd.md` of this topic directory are the input contracts).

Plan path: `.goga/history/2026/step-group-and-step-params/arch.md`.

User decisions of the brainstorm session (binding for this plan):

1. **Cell placement** — the group authoring object lives on the facade; the diagnosis + recovery
   machinery lives in a NEW child cell `prettyplay/engine/groups` (mirror of the steering pattern).
2. **Provider surface** — a fourth port operation `classify_group_failure` returning
   `GroupFailureClassification`; the existing port method `classify_failure` is renamed
   `classify_step_failure` (nominal, behavior identical); types parallel:
   `FailureClassification` / `GroupFailureClassification`.
3. **Prompt artifacts** — the combined approach continues: file-based prompt practices gain a
   prefix unification (`generation.md` → `step_generation.md`, `cheatsheet.md` →
   `step_cheatsheet.md`, content byte-identical — C13); the new group artifacts are files
   `.goga/usages/prompts/group_framing.md` and `.goga/usages/prompts/group_diagnosis.md`; the
   engine's inline `classification_prompt` / `compliance_prompt` stay inline.
4. **Scenario context** — a typed record (raw sentence + permanent group membership) replaces the
   plain string list in every consumer signature and in the port input; the steering cell joins
   the affected list (input type only).

Fixed constraints (ADR/PRD): C1 cache addressing untouched; C2 LLM-free replays; C3
one-function-per-step; C4 anti-masking; C5 bounded autonomy; C6 one render per failure; C7 the
compliance gate on every caching path; C8 honest inputs; C9 the secrets rule extends to group
prompts; C10 pacing outside generated code; C11 layered config; C12 framework-agnostic surface;
C13 frozen prompts.

## Implementation Order

Leaves → root; each cell names the reason for its position.

1. `prettyplay/config` (modify) — no new imports (existing failures import); everything above
   reads the `speed` setting through it.
2. `prettyplay/driver` (modify) — depends on config only; the slow_mo wiring reads the browser
   group.
3. `prettyplay/engine/polling` (modify) — depends on driver only; the count-bounded mode is
   self-contained beside the time window.
4. `prettyplay/llm` (modify) — depends on config + failures; introduces `ScenarioStep`,
   `GroupFailureClassification`, the fourth operation and the rename — the types every
   group-aware consumer above imports.
5. `prettyplay/cache` (modify) — depends on config + reporting; the recovery budget semantics
   (`refresh_healing`, `open_group_cycle`) land before their consumer.
6. `prettyplay/engine` (modify) — depends on config, reporting, failures, driver, cache, llm,
   polling; the typed context and the suppressed group classification points land before the
   groups cell that consumes `StepGenerator`/`StepAttempt`.
7. `prettyplay/engine/groups` (CREATE) — depends on engine, polling, llm, cache, config, driver,
   reporting, failures (the steering pattern: a consumer of the engine is its child).
8. `prettyplay/engine/steering` (modify) — depends on engine et al.; the typed context input and
   the group framing practice of guided regeneration.
9. `prettyplay` (facade, modify) — depends on all; the authoring surface (`tries`/`delay`,
   `group()`), `StepGroup`, the executor wiring (pre-step pause, count mode, typed context, group
   failure routing) and the composition of `GroupRecovery`.
10. Project-level practices (rename + create) — land together with the cells that reference them
    (engine, steering, groups): `step_generation.md`, `step_cheatsheet.md` (renames),
    `group_framing.md`, `group_diagnosis.md` (new).

Non-cell follow-ups recorded by the task (outside this plan's artifacts): the public MkDocs
surface (`docs/`) — configuration, writing-steps, a groups page, self-healing; the two cook
updates (`.goga/usages/cooks/playwright.md`, `json_repair.md`) are already present in the working
tree.

## Artifacts

### 1. Cell `prettyplay/config` (MODIFY)

#### CODEMANIFEST diff

**Header — Annotations:**

- CHANGE the env-names sentence to:
  «Env overrides stay flat: PRETTYPLAY_BROWSER_NAME, PRETTYPLAY_BROWSER_SCREEN,
  PRETTYPLAY_BROWSER_HEADLESS, PRETTYPLAY_BROWSER_ENDPOINT, PRETTYPLAY_BROWSER_ACCEPT_DIALOGS,
  PRETTYPLAY_BROWSER_SPEED.»
- ADD after it:
  «The pace setting is an ordinary browser-group value: the group stores the percentage only — the
  percent→slow_mo mapping belongs to the driver cell.»

**Body — `BrowserConfig`:**

- CHANGE signature to:
  `"BrowserConfig(name: str, screen: str, headless: bool, endpoint: str, accept_dialogs: bool, speed: int)"`
- ADD the parameter line (after `accept_dialogs`):
  «`speed`: the pace of the run as a percentage; 100 — full speed, the behavior identical to today
  (default); lower values slow the run linearly; 0 — the slowest supported pace; valid 0–100
  inclusive.»
- ADD to Requirements:
  «- `speed` is an integer 0–100 inclusive; an out-of-range or non-integer value fails loudly with
  the received value named — never a silent ignore»
- ADD property:
  `"speed -> int": |` → «The pace setting of the run: a percentage 0–100; 100 — full speed, 0 —
  the slowest supported pace.»

**Body — `load_config`:**

- CHANGE Algorithm step 6 browser-group env list to include `PRETTYPLAY_BROWSER_SPEED`.
- CHANGE the Requirement «An env override exists for every setting of `Config`…» — «…and the six
  PRETTYPLAY_BROWSER_* variables».
- ADD Requirement:
  «- PRETTYPLAY_BROWSER_SPEED parses as a decimal integer; an unparseable value or a value outside
  0–100 raises the loud actionable `ConfigurationError` naming the setting, the received value and
  the accepted form — never a silent ignore»

**Footer — Description:** append «, the browser pace setting (speed)».

#### .usages diff — `prettyplay/config/.usages/configuration.md`

- ADD to the TOML example inside `[tool.prettyplay.browser]`:
  `speed = 100            # pace of the run: 0–100 %, 100 — full speed (default)`
- ADD env table row: `| browser.speed | PRETTYPLAY_BROWSER_SPEED |`
- ADD section (after «## Settle polling»):

```md
## Pace

`speed` of the browser group (a percentage, 0–100 inclusive, default 100) controls how fast the
browser executes the run: 100 — full speed, exactly the default behavior; lower values slow the
run down linearly — 0 is the slowest supported pace. It is an ordinary layered setting — file,
env (PRETTYPLAY_BROWSER_SPEED), per-test override:

```python
from prettyplay import BrowserConfig, PrettyConfig, PrettyPlay

test = PrettyPlay(
    cache_key="demo",
    config=PrettyConfig(browser=BrowserConfig(speed=40)),
)
```

- One value per test, fixed for the whole run — it applies at browser start in every launch mode
  (local headed, local headless, remote connect); replays and strict runs take it identically
- An out-of-range or malformed value fails at configuration load — the error names the setting,
  the received value and the allowed range; never a silent ignore
```

### 2. Cell `prettyplay/driver` (MODIFY)

#### CODEMANIFEST diff

**Header — Annotations:** ADD after the start-mode branching sentence:

«The pace rides the browser start: the speed setting of the browser group maps linearly to
Playwright's native slow_mo — int((100 − speed) × 30) ms, 100 → 0 — passed on both the local
launch and the remote connect, every launch mode; one value per browser process, fixed for the
whole run, replays and strict runs identically (see `playwright`). slow_mo is a browser-process
start parameter, not a code wait — the fixed-delays rule for generated step code is untouched.»

**Body — `DriverSession.open_context()`:**

- CHANGE Algorithm step 1 — the local launch sentence gains «…and slow_mo computed from the speed
  setting of the browser group (see `playwright`)»; the remote connect sentence gains «…with the
  same slow_mo».
- ADD Requirement:
  «- The pace applies in every launch mode: the same speed setting slows local headed, local
  headless and remote connect runs identically»

**Footer — Description:** append «, the pace (slow_mo) at launch and connect».

#### .usages — no changes (the consumer surface is untouched; pace is documented in
`prettyplay/config/.usages/configuration.md` and `.goga/usages/cooks/playwright.md`).

### 3. Cell `prettyplay/engine/polling` (MODIFY)

#### CODEMANIFEST diff

**Header — Annotations:**

- CHANGE the first sentence to: «The settle policy of step-code execution: one window per step
  execution, created by the step executor from the polling settings and the step's declared retry
  count, threaded into every execution of the step's code — cached code and candidates alike,
  replay-strict included.»
- ADD after it: «Two bound modes live side by side: the time window (no declared count — the
  behavior identical to today) and the count bound (a declared count — the total number of
  executions of one code unit replaces the time bound for that loop); the pollable filter and the
  inter-execution pause apply in both.»

**Body — `SettleWindow`:**

- CHANGE signature to: `"SettleWindow(timeout: float | None, delay: float, tries: int | None)"`
- ADD parameter line:
  «`tries`: the total number of executions of one code unit within its re-execution loop, the
  first execution included (1 — no re-execution); None — the time-bounded mode of today.»
- ADD properties:
  `"tries -> int | None": |` → «The declared retry count: None — the time-bounded mode, a positive
  integer — the count-bounded mode.»
  `"count_bounded -> bool": |` → «Whether the window bounds this loop by execution count.»
- `start()` / `has_remaining()` unchanged (they serve the time mode; in the count mode `settle`
  gates on its own per-call execution counter).
- CHANGE the `enabled` property annotation to: «Whether polling is active: a positive timeout is
  set or the window is count-bounded (a declared tries count).»

**Body — `settle`:**

- ADD at the head of the Algorithm:
  «In the count-bounded mode (`window` count_bounded): execute the code up to `window` tries times
  in total — each repetition requires the failure to be pollable and pauses the `window` delay;
  settle_retry records are uniform with the time mode; exhaustion propagates the failure to the
  caller as-is. In the time-bounded mode — as today.»
- ADD Requirements:
  «- Each settle call counts from zero in the count mode — the counter belongs to the code unit
  being executed: the cached code and every generated candidate each get their own full count; the
  LLM attempt budget is never multiplied»
  «- Re-executions of both modes write settle_retry records at INFO — no hook events»

**Footer — Description:** append «, beside the time window the count-bounded re-execution mode
(tries)».

#### .usages diff — `prettyplay/engine/polling/.usages/settle.md`

ADD section:

```md
## Count-bounded re-execution (tries)

A step declared with a retry count replaces the time bound for that step's loop with a count
bound: `SettleWindow(timeout=..., delay=..., tries=3)` — the code unit executes at most 3 times in
total (the first execution included; 1 — no re-execution). The pollable filter and the `delay`
pause keep applying between executions; retries appear as `settle_retry` records; exhaustion
propagates the failure to the ordinary path. Each `settle` call counts from zero — the cached code
and every generated candidate each get their own full count. No LLM budget is consumed.
```

### 4. Cell `prettyplay/llm` (MODIFY)

#### CODEMANIFEST diff

**Header — Imports:** no changes — `ScenarioStep` is defined in this cell, never imported.

**Header — Annotations:** ADD after the attempt-history parity sentence:

1. «The scenario-context input participates in both provider implementations with identical
   semantics: every generation request renders the PREVIOUS STEPS block from the typed scenario
   records — the raw sentence of each entry verbatim, the entries carrying group membership marked
   as group steps; a parity requirement, not a capability difference.»
2. «The group-framing input participates in both provider implementations with identical
   semantics: a non-empty group_prompt of a generation request renders as its own GROUP PROMPT
   block immediately before the PREVIOUS STEPS block; None — no block; a parity requirement, not a
   capability difference.»
3. «The group diagnosis operation is the fourth operation of the port with the same absolute
   parity: one request per diagnosis carrying the group prompt, the group step traces, the failed
   step's sentence and attempt history, the page snapshot and the optional screenshot — sent
   through the effective classification model; the answer parses strictly through
   `parse_group_failure_classification`; a degraded answer is the conservative incurable, never a
   granted regeneration.»
4. «The classification operation `classify_step_failure` is the former `classify_failure` — the
   rename is nominal, the behavior identical. The one-request-per-attempt rule covers the
   diagnosis request too.»

**Body — `LLMProvider`:**

- CHANGE `generate_step_code` signature to:
  `"generate_step_code(prompt: str, user_instructions: str, step_text: str, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, snapshot: str, page_url: str | None, screenshot: bytes | None, cheat_sheet: str, attempt_history: list[str], recommendation: str | None, guidance: str | None) -> code: str"`
- CHANGE the `previous_steps` parameter text to:
  «the typed scenario records of the previous steps of the test, in execution order — each the raw
  sentence plus its permanent group membership; rendered by the provider implementations as the
  PREVIOUS STEPS block with the group entries marked, identically in both.»
- ADD the `group_prompt` parameter:
  «the group prompt of the current step's group; None — an ordinary step, no GROUP PROMPT block;
  non-empty — rendered by the provider implementations verbatim as a separate GROUP PROMPT block
  immediately before the PREVIOUS STEPS block, identically in both; takes no part in step
  addressing.»
- ADD to Requirements: «- the GROUP PROMPT block renders immediately before the PREVIOUS STEPS
  block of the scenario part, identically in both implementations»
- RENAME the method `classify_failure` to `classify_step_failure` (signature and behavior text
  unchanged) with the added line: «the former classify_failure — the rename is nominal, the
  behavior identical.»
- ADD method:

```yaml
    "classify_group_failure(prompt: str, user_instructions: str, group_prompt: str, group_steps: list[str], step_text: str, attempt_history: list[str], snapshot: str, screenshot: bytes | None) -> diagnosis: GroupFailureClassification": |
      Send one group diagnosis request — the diagnosis of a failed step with the whole interaction
      in view.

      `prompt`: the group diagnosis system prompt supplied by the calling engine — applied
      verbatim as the system message.
      `user_instructions`: the project's classification instructions supplied by the calling
      engine from the classification_prompt setting — the diagnosis request carries them exactly
      as a classification request does; empty — no instructions block.
      `group_prompt`: the group prompt, verbatim.
      `group_steps`: the composed verbatim traces of the group's steps in execution order — each
      the sentence, the outcome and the URL before -> after transition, supplied by the calling
      engine.
      `step_text`: the raw sentence of the failed step.
      `attempt_history`: the rendered verbatim records of the failed step's attempt history.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables
      screenshots.
      `diagnosis`: the `GroupFailureClassification` verdict.

      Algorithm:
      1. Build the user content in the fixed order GROUP PROMPT, GROUP STEPS, STEP, HISTORY,
         PAGE SNAPSHOT, SCREENSHOT (when attached), USER INSTRUCTIONS last — identically in both
         implementations
      2. Send one request through the effective classification model
      3. Parse the text answer strictly through `parse_group_failure_classification` and return
         the verdict

      Requirements:
      - A provider service failure raises `LLMUnavailableError` naming the provider
      - One request per diagnosis — attempt budgets belong to the calling engine
      - The input takes no part in step addressing
```

**Body — ADD types (models.py):**

```yaml
"ScenarioStep(sentence: str, group_prompt: str)":
  location: models.py
  annotations: |
    One record of the scenario context of a test — the unit every PREVIOUS STEPS block renders.

    `sentence`: the raw step sentence as written by the engineer, verbatim — never the normalized
    addressing form.
    `group_prompt`: the group prompt of the step's group; empty — an ordinary step; non-empty —
    the verbatim group prompt; the membership is permanent for the lifetime of the test context.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - A record appended to the scenario context is never rewritten
  properties:
    "sentence -> str": |
      The raw step sentence, verbatim.
    "group_prompt -> str": |
      The group prompt of the step's group; empty means an ordinary step.

"GroupFailureClassification(category: str, root_cause: str, earliest_step: str, recommendation: str)":
  location: models.py
  annotations: |
    The verdict of a group diagnosis: what kind of failure it is, why, where it stems from and what
    to do.

    `category`: one of recoverable (the affected steps of the group can be regenerated and the run
    fixed), product_defect (the application is genuinely broken — never healed green), incurable
    (the root cannot be reached from inside the group, or regeneration cannot help).
    `root_cause`: why the failure got this category.
    `earliest_step`: the verbatim sentence quote of the earliest affected step as answered.
    `recommendation`: the recommended regeneration or engineer action.

    Requirements:
    - `category` is always one of the three labels; a degraded answer carries the conservative
      incurable with the raw answer in root_cause
  properties:
    "category -> str": |
      The diagnosis label: recoverable, product_defect or incurable.
    "root_cause -> str": |
      Why the failure got this category; a degraded verdict carries the raw answer here.
    "earliest_step -> str": |
      The verbatim sentence quote of the earliest affected step.
    "recommendation -> str": |
      The recommended engineer or regeneration action.

"parse_group_failure_classification(verdict_text: str) -> diagnosis: GroupFailureClassification":
  location: models.py
  annotations: |
    Parse the raw answer of the group diagnosis request into the verdict — the strict single
    parsing point of the diagnosis with the conservative degradation.

    `verdict_text`: the raw text answer of the diagnosis model.
    `diagnosis`: the parsed verdict; a garbage answer degrades to the conservative incurable.

    Algorithm:
    1. Parse the trimmed text as a JSON object of the four fields; a JSON syntax failure is
       salvaged once through the `json_repair` library (see `json_repair`)
    2. Validate the semantics: category of the {recoverable, product_defect, incurable} set and
       the four fields present; the validation applies to a salvaged answer identically
    3. An unparseable, unrecognized or incomplete answer degrades conservatively: category
       incurable, the raw answer carried in root_cause
    4. Return the verdict

    Requirements:
    - Pure function: no state, no I/O, deterministic on the input text
    - The salvage repairs syntax only — semantics stay strict
    - Never synthesizes recoverable: a garbage answer never grants regeneration
    - A failure of the salvage library itself degrades too — a third-party exception never crosses
      the parse (see `json_repair`)
    - The WARNING naming the degraded raw answer is logged by the calling engine, not here
```

**Footer — Description:** append «, the typed scenario records, the group diagnosis operation and
its verdict».

#### .usages diffs — `prettyplay/llm/.usages/`

`providers.md`:

- UPDATE the Parity sentence — «Both providers expose the same four operations —
  generate_step_code, classify_step_failure, classify_group_failure and
  check_instruction_compliance — …» (the rest of the sentence unchanged).
- ADD the rename note: the classification operation is named `classify_step_failure` (the former
  `classify_failure` — nominal rename).
- ADD note under the generation inputs: the scenario context arrives as typed records (the raw
  sentence + permanent group membership) and the group prompt renders as the GROUP PROMPT block
  before PREVIOUS STEPS.
- ADD section:

```md
## The group diagnosis operation

The fourth port operation `classify_group_failure` — one request per diagnosis through the
effective classification model, both providers in full parity:

- inputs: the group prompt (verbatim), the group step traces (sentence, outcome, URL transition —
  one per step), the failed step's sentence, its rendered attempt history, the page snapshot and
  the optional screenshot; the classification instructions of the project reach it exactly as a
  classification request
- the answer parses strictly through `parse_group_failure_classification`: JSON with the four
  fields, one json-repair salvage of a syntax glitch, the closed label set
  recoverable | product_defect | incurable
- a garbage or incomplete answer degrades conservatively to incurable with the raw answer logged —
  never a granted regeneration
- provider unavailability raises LLMUnavailableError; one request per diagnosis, budgets belong to
  the calling engine
```

`classification.md`:

- FIX the example call — `provider.classify_step_failure(...)` (the nominal rename; the rest of
  the example unchanged).

### 5. Cell `prettyplay/cache` (MODIFY)

#### CODEMANIFEST diff

**Header — Annotations:** CHANGE the RunBudgets ownership sentence — append: «; the
recovery-cycle accounting joins the registry — per-group cycle counters keyed by the group key,
beside the per-step pools».

**Body — `RunBudgets`:**

- CHANGE the type annotation description to: «The per-test attempt registry: how many generation
  and healing attempts each step has left within the test — and how many recovery cycles each
  group has left.»
- ADD Requirements:
  «- Ordinary per-step healing keeps its per-test pools exactly as today — the recovery semantics
  ride beside them»
  «- The recovery cycle cap of a group is the healing_limit value — the loop is never infinite»
- ADD methods:

```yaml
    "refresh_healing(identity: StepIdentity)": |
      Grant the step a fresh full healing counter — the recovery engine calls it at every new
      recovery cycle for every row step, so a second attempt is never starved by the first cycle.

      `identity`: the address of the row step.

      Requirements:
      - The next try_healing calls of the step draw from a renewed pool of the full healing_limit
    "open_group_cycle(group_key: str) -> allowed: bool": |
      Consume one recovery cycle for the group identified by `group_key` within this test.

      `group_key`: the key of the group — its group prompt.
      `allowed`: True — a new cycle is open; False — the per-group cycle cap, the healing_limit
      value, is exhausted — the caller turns it into the terminal incurable failure.

      Requirements:
      - The cap counts recovery cycles per group per test, never per step
```

**Footer — Description:** append «, the group recovery cycle accounting».

#### .usages diff — `prettyplay/cache/.usages/budgets.md`

ADD section:

```md
## Recovery budgets (groups)

The group recovery engine draws on the same registry with two group-scoped operations:

```python
if budgets.open_group_cycle(group_key=group_prompt):
    for step_identity in row:
        budgets.refresh_healing(step_identity)  # a fresh full healing counter per cycle
```

- `open_group_cycle(group_key)` — consume one recovery cycle of the group; False — the per-group
  cycle cap (the `healing_attempts` value) is exhausted → the terminal incurable failure
- `refresh_healing(identity)` — at every new cycle each row step gets a fresh full healing
  counter, so a second attempt is never starved by the first

Ordinary per-step healing keeps its per-test pools unchanged. Row regenerations pay from the
healing budget via the ordinary `try_healing`. Group cycle counters live only in the memory of the
running process, like every budget.
```

### 6. Cell `prettyplay/engine` (MODIFY)

#### CODEMANIFEST diff

**Header — Usages:**

- CHANGE `system_prompt: .goga/usages/prompts/generation.md` →
  `system_prompt: .goga/usages/prompts/step_generation.md`
- CHANGE `cheat_sheet: .goga/usages/prompts/cheatsheet.md` →
  `cheat_sheet: .goga/usages/prompts/step_cheatsheet.md`
- ADD `group_framing: .goga/usages/prompts/group_framing.md`

**Header — Imports:** ADD `ScenarioStep` to the Types from `prettyplay/llm`.

**Header — Annotations:**

- CHANGE the honest-inputs sentence — insert after «the raw step sentence as written by the
  engineer»: «— carried by the typed scenario records: the sentence of each entry verbatim, the
  group membership a property of the record, never a mutation of the sentence —».
- ADD: «Inside a group there is no isolated per-step classification: a group step (a non-empty
  group framing input) suppresses the generator's internal classification points — a failed check
  of a candidate and the generation-budget exhaustion surface as the unclassified incurable
  failure carrying the underlying error, and the calling executor routes it to the group recovery;
  with no group framing input the ordinary-step paths stay byte-identical (C13).»
- ADD: «Use `group_framing` from Usages as the single source of the additive group framing of
  generation and regeneration requests of group steps — the block structure and the marking change
  together with the practice.»

**Body — `StepGenerator.generate`:**

- CHANGE signature to:
  `"generate(identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt], window: SettleWindow) -> step: CachedStep"`
- CHANGE the `previous_steps` implicit contract (add to the request-inputs notes): typed records —
  each the raw sentence plus its permanent group membership; the group entries render marked per
  `group_framing`.
- ADD parameter `group_prompt`: «the group prompt of the current step's group; None — an ordinary
  step: the behavior is byte-identical to today — the same requests, the same classification
  points, the same bounded healing; non-empty — a group step: every request carries the group
  framing per `group_framing` (the GROUP PROMPT block and the group-marked previous steps on top
  of the full test scenario context; nothing existing is removed) and the internal classification
  points are suppressed.»
- CHANGE Algorithm step 3 — a group step request carries the group framing per `group_framing`.
- CHANGE Algorithm step 6 (failed check) — prepend the group branch: «A group step
  (`group_prompt` non-empty) — no classification request and no healing-funded regeneration:
  append the attempt record and raise `IncurableStepError` carrying the failed code in the code
  field and the full failure description in the error field; the calling executor routes it to the
  group recovery. Otherwise — as today.»
- CHANGE Algorithm step 8 (budget exhaustion) — the same group branch before any classification.
- ADD Requirement: «- `group_prompt` None — the behavior is byte-identical to the ordinary path:
  the same requests, the same classification points, the same bounded healing (C13)»

**Body — `StepGenerator.regenerate`:**

- CHANGE signature to:
  `"regenerate(identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt], recommendation: str, window: SettleWindow) -> step: CachedStep"`
- ADD parameter `group_prompt`: «the group prompt of the row step's group — the recovery row passes
  it; non-empty: the request carries the framing per `group_framing`; None — an ordinary
  regeneration.»

**Body — `StepHealer.heal`:** CHANGE `previous_steps` to `previous_steps: list[ScenarioStep]`
(type only; behavior unchanged — group steps never reach the healer).

**Body — `classify_step_failure`:**

- CHANGE Algorithm step 2 — the port reference follows the rename: «Ask the provider port
  `classify_step_failure` passing…» (the rename is nominal, the behavior identical).

**Footer — Description:** append «, the typed scenario context and the group-framing input of
generation (the group classification points delegated outward)».

#### .usages diffs

`prettyplay/engine/.usages/generation.md` — UPDATE the «Generate a step» example: the scenario
context arrives as typed records (each the raw sentence plus its permanent group membership) —
`previous_steps=[ScenarioStep(sentence="open the login page", group_prompt=""), ScenarioStep(sentence="enter the login and password", group_prompt="")],`; ADD section:

```md
## Group steps (framing, no per-step classification)

Inside a group the generator behaves differently in exactly two ways:

- every request of a group step carries the additive group framing — the GROUP PROMPT block and
  the group-marked earlier steps of the group on top of the full test scenario context; nothing
  existing is removed
- the two internal classification points — a failed check of a candidate and the
  generation-budget exhaustion — are suppressed: no classification request, no healing-funded
  regeneration; the loop appends the attempt record and raises IncurableStepError carrying the
  failed code and the full failure text; the executor routes it to the group recovery

With no group framing input (`group_prompt=None`) the ordinary paths are byte-identical. The
previous-steps context is typed: each entry carries the raw sentence verbatim plus its permanent
group membership.
```

`prettyplay/engine/.usages/healing.md` — UPDATE the «Heal» example the same way —
`previous_steps=[ScenarioStep(sentence="open the login page", group_prompt="")],`; ADD to Rules:
«The scenario context is typed (the raw sentence + permanent group membership); group steps never
reach the healer — their failures route to the group recovery».

### 7. Cell `prettyplay/engine/groups` (CREATE)

#### CODEMANIFEST (full)

```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - StepReporter
    From: prettyplay/reporting
  - Types:
      - ProductDefectError
      - IncurableStepError
      - LLMUnavailableError
      - FailureVerdict
    From: prettyplay/failures
  - Types:
      - PageFacade
    From: prettyplay/driver
  - Types:
      - StepCache
      - StepIdentity
      - CachedStep
      - RunBudgets
    From: prettyplay/cache
  - Types:
      - LLMProvider
      - ScenarioStep
      - GroupFailureClassification
    From: prettyplay/llm
  - Types:
      - StepGenerator
      - StepAttempt
    From: prettyplay/engine
  - Types:
      - SettleWindow
    From: prettyplay/engine/polling

Usages:
  conventions: .goga/usages/conventions.md
  group_diagnosis: .goga/usages/prompts/group_diagnosis.md
  group_framing: .goga/usages/prompts/group_framing.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `group_diagnosis` from Usages as the system prompt of every group diagnosis request.
  Use `group_framing` from Usages as the single source of the additive group framing of the row regeneration requests.

  The diagnosis-driven recovery of step groups: every classification point of a group step routes here — one group-level diagnosis replaces the per-step classification-and-heal; inside a group there is no isolated per-step healing.
  The diagnosis rides the classification model and the classification instructions of the project settings — the screenshot attaches when enabled.
  Anti-masking: a product_defect diagnosis fails the test loudly through the existing product-defect failure; a garbage answer never grants regeneration — the conservative incurable with the raw answer logged.
  Recovery is group-scoped: the row is built from the group's own steps only; a diagnosis naming a root outside the group ends the run in the honest terminal incurable failure whose verdict names that step — no doomed cycles are spent.
  Bounded autonomy: every new recovery cycle grants each row step a fresh healing counter — the full healing pool per cycle — while the number of cycles per group is capped by the healing pool value; the loop is never infinite.
  Recovery re-executes forward on the current page — no rollback machinery; a re-planned action step repeats its action, never riding leftover state.
  Every successfully re-executed row step passes the two-dimension compliance gate — the same gate as every caching path — and is written back to the cache per step.
  Reporting reuses the healing events per recovered step plus structured log records for the diagnosis itself and the row composition — no new hook events.
  Strict mode never runs the recovery — the executor keeps the classification-only path.
  Honest inputs: the group prompt and the step sentences reach the diagnosis and the regeneration requests verbatim; the group prompt joins the repository cache, the logs and the LLM requests — the never-put-secrets rule extends to it.

---

"GroupStepOutcome(sentence: str, step_type: str, tries: int | None, delay: float | None, outcome: str, url_before: str, url_after: str, identity: StepIdentity)":
  location: outcome.py
  annotations: |
    One verbatim trace record of a group step's execution — the unit the GROUP STEPS block of the diagnosis request renders.

    `sentence`: the raw sentence of the step, verbatim.
    `step_type`: action or assertion.
    `tries`: the declared retry count of the step; None — the step is governed by the global polling settings.
    `delay`: the declared start pause of the step in seconds; None — no pause.
    `outcome`: passed or failed.
    `url_before`: the page URL read immediately before the step's execution.
    `url_after`: the page URL read immediately after the step's execution.
    `identity`: the cache address of the step — recorded by the executor when the trace is
    appended; the addressing metadata of the row mechanics (regeneration and the healing-counter
    refresh resolve row steps by it), never rendered into the GROUP STEPS block.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - A record is immutable once appended: no rewriting, no truncation
  properties:
    "sentence -> str": |
      The raw sentence of the group step, verbatim.
    "step_type -> str": |
      The step kind: action or assertion.
    "tries -> int | None": |
      The declared retry count; None — the global polling settings govern the step.
    "delay -> float | None": |
      The declared start pause in seconds; None — no pause.
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
      1. The sentence line — the raw sentence verbatim
      2. The outcome line — the outcome label
      3. The URL line — url_before, an arrow, url_after

      Requirements:
      - No collapsing, no size limits, no truncation of any field

"classify_group_failure(config: Config, provider: LLMProvider, group_prompt: str, traces: list[GroupStepOutcome], step_text: str, step_type: str, attempt_history: list[StepAttempt], page: PageFacade) -> diagnosis: GroupFailureClassification":
  location: diagnosis.py
  annotations: |
    Compose and send one group diagnosis request — the single diagnosis call of the recovery.

    `config`: project settings — the screenshot flag and the classification instructions.
    `provider`: the LLM port.
    `group_prompt`: the group prompt, verbatim.
    `traces`: the group's step traces in execution order.
    `step_text`: the raw sentence of the failed step, verbatim.
    `step_type`: action or assertion.
    `attempt_history`: the per-step attempt history of the failed step — rendered records.
    `page`: the page facade of the current test.
    `diagnosis`: the `GroupFailureClassification` verdict.

    Algorithm:
    1. Collect the fresh page accessibility snapshot — plus the screenshot when the project settings enable it
    2. Compose the GROUP STEPS traces — the render of every trace record — and the HISTORY records of the failed step
    3. One request via the provider port classify_group_failure passing `group_diagnosis` as the system prompt and the user instructions — the effective classification_prompt — when non-empty
    4. A degraded verdict — the conservative incurable carrying the raw answer in root_cause — logs a WARNING through the logger prettyplay naming the group and carrying the raw answer
    5. Return the verdict

    Constraints:
    - Provider unavailability propagates as `LLMUnavailableError` — an explicit infrastructure failure; no retry

"GroupRecovery(config: Config, provider: LLMProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: recovery.py
  annotations: |
    The group recovery engine: one diagnosis over the whole interaction, a group-scoped affected row, bounded cycles.

    `config`: project settings.
    `provider`: the LLM port for the diagnosis request.
    `generator`: the regeneration engine — every row step regenerates as its own per-step unit.
    `cache`: the step cache for the per-step write-back.
    `budgets`: the per-test attempt registry — the cycle cap and the per-cycle refresh.
    `reporter`: the visibility point.
  methods:
    "recover(group_prompt: str, traces: list[GroupStepOutcome], step_text: str, step_type: str, previous_steps: list[ScenarioStep], identity: StepIdentity, attempt_history: list[StepAttempt], page: PageFacade, window: SettleWindow) -> step: CachedStep": |
      Diagnose a failed group step and recover the affected row.

      `group_prompt`: the group prompt, verbatim — reaches the diagnosis and every row request.
      `traces`: the group's step traces with outcomes and URL transitions.
      `step_text`: the raw sentence of the failed step, verbatim.
      `step_type`: action or assertion.
      `previous_steps`: the typed scenario records of the test, in execution order — every row
      regeneration request carries them per `group_framing`.
      `identity`: the address of the failed step.
      `attempt_history`: the per-step attempt history grown to the failure.
      `page`: the live page facade — the row re-executes forward on the current page.
      `window`: the settle window of the failed step's execution.
      `step`: the healed cached step of the failed step.

      Verdict mapping: every raised terminal failure carries a `FailureVerdict` — a diagnosis
      verdict maps onto it (category as is — product_defect and incurable are taxonomy labels,
      recoverable never raises; explanation ← root_cause plus the earliest_step quote when it
      names a step; recommendation ← recommendation); a refused cycle authors its own — category
      incurable, the explanation naming the exhausted per-group cycle cap (colon-free); an
      outside-group root — category incurable, the explanation naming that step verbatim
      (colon-free).

      Algorithm:
      1. Open a recovery cycle via budgets open_group_cycle keyed by the group prompt; a refused cycle raises `IncurableStepError` carrying the verdict naming the exhausted cycle cap — the reason colon-free, one render
      2. Diagnose via `classify_group_failure`; a product_defect verdict raises `ProductDefectError` carrying the verdict and the full underlying error; an incurable verdict raises `IncurableStepError` carrying them
      3. Match the earliest affected step: an exact verbatim match of earliest_step against the group's steps names the row start; an exact match against a step of the test outside the group raises the honest terminal `IncurableStepError` whose verdict names that step — recovery is out of mandate; no match degrades to the failed step itself
      4. Grant every row step a fresh healing counter via budgets refresh_healing
      5. The row — from the earliest affected step through the failed step, the group's own steps only — sequentially: the step's declared delay passes quietly; the step regenerates via the generator regenerate carrying the diagnosis recommendation, the group framing per `group_framing`, `previous_steps`, the grown attempt history and the step's own window built from its declared tries and the trace identity; the candidate executes immediately on the current page inside the regeneration loop; the two-dimension compliance gate guards the write-back; the cache stores the step; report on_healing_started and on_healed for the recovered step; a structured log record names the diagnosis and the row composition
      6. A repeat failure of a row step — an `IncurableStepError` from the regeneration — re-enters a fresh diagnosis and a new cycle from step 1 with the fresh failure state, while cycles remain
      7. On success return the healed cached step of the failed step — the group continues normally

      Requirements:
      - Strict mode never invokes this engine — the executor guards the gate
      - The row never leaves the group's steps
      - Anti-masking: a product_defect diagnosis always fails the test loudly
      - One render per terminal failure — the existing taxonomy, exactly once
      - The recovery is loudly reported through the healing events and the log records

      Constraints:
      - No page-state rollback — forward re-execution only
      - No new failure kinds — the existing taxonomy carries every terminal outcome
      - The ordinary per-step healing pools of non-group steps are never consumed

---

Author: Goga
CreatedAt: 16/09/26
Description: |
  The group recovery of prettyplay: the group-level diagnosis request over the whole interaction (recoverable | product_defect | incurable), the group-scoped affected row with sequential per-step regeneration and immediate forward re-execution, the compliance-gated per-step cache write-back, and the bounded recovery cycles with fresh healing counters per cycle.
```

#### .usages file (full) — `prettyplay/engine/groups/.usages/recovery.md`

```md
# Group recovery

Domain: the diagnosis-driven recovery of step groups. Audience: library internals and engineers
reasoning about recovered group runs.

## When recovery runs

Every classification point of a group step on a non-strict run routes here instead of the per-step
classification-and-heal: a failed check of a generation candidate, a failed cached replay and the
generation-budget exhaustion. Inside a group there is no isolated per-step healing. Strict mode
never runs recovery — the classification-only path stays.

## The cycle

```python
healed = recovery.recover(
    group_prompt="accept cookies, fill and submit the order form",
    traces=group_traces,          # GroupStepOutcome per group step, execution order
    step_text="the status shows order confirmed",
    step_type="assertion",
    previous_steps=scenario,      # the typed scenario records of the test, execution order
    identity=identity,
    attempt_history=history,
    page=page,
    window=window,
)
```

1. One group-level diagnosis request — the classification model and instructions, the group
   prompt, the step traces with outcomes and URL transitions, the current page state, the failed
   step's attempt history. Labels: `recoverable | product_defect | incurable`; a garbage answer
   degrades to incurable with the raw answer logged.
2. `product_defect` fails loudly; `incurable` fails terminally; a root named outside the group
   ends in the honest terminal failure naming that step.
3. `recoverable`: the row runs from the earliest affected group step through the failed step —
   each step regenerates as its own unit (the diagnosis recommendation + the group framing ride
   the request), re-executes immediately on the current page, passes the two-dimension compliance
   gate and writes back to the cache per step.
4. A repeat failure re-enters a fresh diagnosis and a new cycle while cycles remain; every new
   cycle grants each row step a fresh full healing counter; the number of cycles per group is
   capped by `healing_attempts` — never infinite.

## Reporting

`on_healing_started` / `on_healed` per recovered step plus structured log records for the
diagnosis itself and the row composition. No new hook events.
```

### 8. Cell `prettyplay/engine/steering` (MODIFY)

#### CODEMANIFEST diff

**Header — Usages:**

- CHANGE `system_prompt` path → `.goga/usages/prompts/step_generation.md`
- CHANGE `cheat_sheet` path → `.goga/usages/prompts/step_cheatsheet.md`
- ADD `group_framing: .goga/usages/prompts/group_framing.md`

**Header — Imports:** ADD `ScenarioStep` to the Types from `prettyplay/llm`.

**Header — Annotations:** ADD after the shared-history sentence: «A terminally failed group step
reaches the dialog with the group context available: the guided regeneration requests of a group
step carry the group framing — the GROUP PROMPT block and the group-marked scenario context (see
`group_framing`); the dialog itself is unchanged.»

**Body — `StepSteering.steer`:**

- CHANGE signature to:
  `"steer(failure: IncurableStepError, identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[ScenarioStep], group_prompt: str | None, page: PageFacade, attempt_history: list[StepAttempt]) -> healed: CachedStep | None"`
- CHANGE the `previous_steps` text: «the typed scenario records of the previous steps of the test
  — each the raw sentence plus its permanent group membership.»
- ADD parameter `group_prompt`: «the group prompt of the stuck step's group; None — an ordinary
  step; non-empty — every guidance request of this dialog carries the group framing per
  `group_framing`.»
- CHANGE Algorithm step 4 — the request «carries the group framing — `group_prompt` and the marked
  scenario context — per `group_framing` when the step belongs to a group».

#### .usages diff — `prettyplay/engine/steering/.usages/steering.md`

ADD note in the dialog section: «A group step's guidance requests carry the group context — the
group prompt and the group-marked previous steps; the banner is unchanged».

### 9. Cell `prettyplay` (facade, MODIFY)

#### CODEMANIFEST diff

**Header — Imports:**

- ADD block:
  `Types: GroupRecovery, GroupStepOutcome` / `Usages: recovery` / `From: prettyplay/engine/groups`
- ADD `ScenarioStep` to the Types from `prettyplay/llm`.

**Header — Annotations:**

- ADD Use-line: «Use `recovery` from Imports for the group cycle the executor delegates to.»
- ADD after the strict-mode sentence: «Group steps route their failures differently on a
  non-strict run: every classification point of a group step goes to one group-level diagnosis and
  the group-scoped recovery instead of the per-step heal (see `recovery` from Imports); strict
  mode keeps the classification-only path; the honest inputs extend to the group prompt — it joins
  requests verbatim and the never-put-secrets rule covers it.»
- ADD: «The authoring surface: step and expect accept the keyword-only retry count and start
  pause; the group block yields a group object with the ordinary step surface — no ambient
  rerouting of the test object.»
- ADD: «The group pace and pauses are library-level behavior around steps: the pauses between the
  group's steps follow the same percent→ms mapping as the browser speed setting — never slow_mo,
  which cannot change mid-run.»

**Body — `PrettyPlay`:**

- CHANGE method signatures:
  `"step(text: str, tries: int | None, delay: float | None)"`
  `"expect(text: str, tries: int | None, delay: float | None)"`
- ADD to both annotations: «`tries`: keyword-only — the total number of executions of the step's
  code, a positive integer, the first execution included; invalid values — zero, negative,
  non-integer — raise the loud actionable `PrettyplayError` naming the parameter, the received
  value and the allowed form. `delay`: keyword-only — the quiet pre-step pause in seconds,
  non-negative, fractional allowed; a negative or malformed value raises the same loud error. A
  declared `tries` switches the step to the count-bounded re-execution; a declared `delay` is the
  quiet pre-step pause.»
- ADD method:

```yaml
    "group(prompt: str, speed: int | None, delay: float | None) -> g: StepGroup": |
      Open the group authoring block — one coherent mini-scenario with a shared goal.

      `prompt`: the group prompt — empty raises the loud actionable `PrettyplayError` at entry.
      `speed`: keyword-only — the group pace, an integer 0–100; outside the range — the loud
      actionable `PrettyplayError`.
      `delay`: keyword-only — the quiet pause before the group's first step in seconds,
      non-negative; negative — the loud actionable `PrettyplayError`.
      `g`: the group object — the ordinary step surface (`step`, `expect`, `tries`/`delay`
      included); no ambient rerouting of the test object; group membership changes no step's cache
      address; cached group steps replay as ordinary steps.
```

- CHANGE the construction Algorithm step 5 — append: «Construct `GroupRecovery` from the runtime
  config, provider, budgets, the step cache, the generator and the reporter»; step 6 — the
  executor receives the recovery engine.

**Body — ADD type:**

```yaml
"StepGroup(prompt: str, speed: int | None, delay: float | None, executor: StepExecutor)":
  location: groups.py
  annotations: |
    The authoring group object — one coherent mini-scenario with a shared goal, yielded by the
    group method of the test object.

    `prompt`: the group prompt, verbatim — reaches generation and diagnosis requests and the
    framing log records.
    `speed`: the group pace, 0–100; None — no between-step pauses.
    `delay`: the quiet pause before the group's first step, seconds; None — no pause.
    `executor`: the step cycle executor of the owning test — every step delegates to it with this
    group as the context.

    Supports the context manager protocol: entry — one INFO framing log record with the group
    prompt verbatim; exit — one INFO framing log record; zero steps — a quiet no-op.

    Requirements:
    - The declared delay passes quietly before the first step — the entry framing visible, the
      wait quiet
    - Between consecutive group steps the quiet pause int((100 − speed) × 30) milliseconds when
      speed is declared — library-level pauses, never slow_mo
    - Group membership changes no step's cache address
  properties:
    "prompt -> str": |
      The group prompt, verbatim.
    "traces -> list[GroupStepOutcome]": |
      The verbatim trace records of the group's steps, in execution order — the input the
      executor passes to the group recovery; a record is appended once per executed group step.
  methods:
    "step(text: str, tries: int | None, delay: float | None)": |
      Execute the action step `text` inside the group — the ordinary step surface with the group
      context: validates like the facade methods, delegates to the executor execute with this
      group, records the step trace — the sentence, the step type, the declared tries/delay, the
      outcome and the URL pair bracketing the step.
    "expect(text: str, tries: int | None, delay: float | None)": |
      Execute the assertion step `text` inside the group — the same delegation and trace as step,
      assertion kind.
```

**Body — `StepExecutor`:**

- CHANGE signature to:
  `"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, steering: StepSteering, recovery: GroupRecovery, budgets: RunBudgets, reporter: StepReporter, config: PrettyConfig, provider: LLMProvider)"`
- ADD parameter: «`recovery`: the group recovery engine — invoked only on a non-strict run for a
  group step; never in strict mode.»
- CHANGE method signature to:
  `"execute(step_text: str, step_type: str, page: PageFacade, group: StepGroup | None, tries: int | None, delay: float | None)"`
- CHANGE Algorithm:
  - step 1 — append after on_step_started: «a declared `delay` passes quietly — the step's started
    event fires, the declared seconds pass, then the step's code runs; a step never reached after
    a terminal failure never pauses»;
  - step 2 — the `SettleWindow` is built «from the polling settings and the declared `tries` — a
    declared count switches the window to the count-bounded mode»;
  - step 4 (a hit execution failure) — non-strict and a group step: «delegate to the recovery
    engine recover with the group prompt, the group's traces (`traces` of `group`), the raw
    sentence, the step type, the scenario context, the identity, the anchored history and the
    window — instead of the healer; a recovered step continues as success»; ordinary steps heal
    exactly as today; strict — classification only, unchanged;
  - step 5 (a miss) — «generate with the group prompt as the framing input for a group step — the
    group-step generation failures arrive unclassified (the engine suppresses its classification
    points) and route to the recovery»;
  - step 6 (steering intercept) — «a group step's `IncurableStepError` reaches the recovery first
    on a non-strict run; steering remains the terminal gate for the still-terminal failure — the
    dialog receives the group context»;
  - step 7 — «Append the `ScenarioStep` record — the raw sentence plus the group prompt of
    `group` when inside one, permanent for the test — the previous steps feed the next generation
    and the row regeneration of the group recovery».
- ADD Requirements:
  «- The pre-step pause is quiet — elapsed time, no output noise; uniform for the first step of a
  test, every following step and every re-execution inside a recovery row — the recovery applies
  the row step's declared delay»
  «- The scenario context lives per test as typed records; group membership is permanent once
  recorded»

**Footer — Description:** append «, the step parameters (tries, delay), the group authoring block
and the group recovery routing».

#### .usages diffs

`prettyplay/.usages/steps.md` — ADD sections:

```md
## Step parameters

- step(text, tries=3) — the total number of executions of the step's code (the first included);
  replaces the time-bounded settle window for that step; the global polling settings stay
  untouched; absorbed retries appear as settle_retry records only, the step stays green
- step(text, delay=1.5) — a quiet pause in seconds before the step's code runs: the started event
  fires, the declared seconds pass, then the code; a step never reached never pauses
- Both parameters are keyword-only and accepted by both step kinds; invalid values (zero/negative
  tries, negative delay) fail loudly at the call

## Groups

```python
with t.group("accept cookies, fill and submit the order form") as g:
    g.step("accept the cookie banner")
    g.step("fill the email field", delay=0.5)
    g.step("submit the form")
    g.expect("the status shows order confirmed", tries=2)
```

- The group block is one coherent mini-scenario with a shared goal; inside, steps use the ordinary
  authoring surface — retry count and start pause included
- An empty group prompt fails loudly at entry; a group with zero steps is a quiet no-op
- Group membership changes no step's cache address: cached group steps replay as ordinary steps —
  no LLM calls, strict replay-only included
- On a non-strict run a failing group step is diagnosed with the whole group in view and the
  affected row is regenerated and re-executed automatically — a product defect fails loudly,
  recovery never loops forever
- Group pace and pause: `with t.group("…", speed=30, delay=2) as g:` slows the pauses between the
  group's steps (the same percent→pause mapping as the browser speed setting) and waits the
  declared seconds before the group's first step — quiet, library-level pauses
```

`prettyplay/.usages/lifecycle.md` — ADD section:

```md
## Group recovery

Steps inside a group fail differently: on a non-strict run every failure that would be classified
and healed per-step triggers one group-level diagnosis instead — the classification model sees the
group prompt, every step's outcome and URL transition, and the current page. recoverable → the
affected row regenerates and re-executes automatically (per-step cache write-back, loud
reporting); product_defect → the test fails loudly. The recovery budget: every new cycle grants
each row step a fresh healing counter, the number of cycles per group is capped by
healing_attempts. Strict mode never recovers groups; a terminally failed group step still reaches
the steering dialog with the group context available.
```

### 10. Project-level practices

- RENAME `.goga/usages/prompts/generation.md` → `step_generation.md` (content byte-identical —
  C13; update the Usages paths of `prettyplay/engine` and `prettyplay/engine/steering`).
- RENAME `.goga/usages/prompts/cheatsheet.md` → `step_cheatsheet.md` (content byte-identical).
- CREATE `.goga/usages/prompts/group_framing.md` (full content):

```md
# Group generation framing

The additive framing every generation and regeneration request of a group step carries —
referenced by the engine and engine/groups cells as the `group_framing` practice. It changes
nothing in the ordinary step requests: the framing rides on top of the full test scenario context,
nothing existing is removed.

---

Blocks a group step request renders additionally:

- GROUP PROMPT — the group's shared goal, verbatim, rendered as its own block immediately before
  the PREVIOUS STEPS block
- PREVIOUS STEPS marking — the entries belonging to the group render marked: the group prompt of
  the entry renders with the marked sentence, so the model sees which earlier steps belong to the
  same interaction

Semantics:

- The group prompt is framing on top of the scenario context — it never replaces the step
  sentence, the step type, the attempt history or any existing block
- The marking is permanent: a scenario-context entry keeps its group membership forever, so later
  ordinary steps and the group diagnosis see the group-marked steps in the full test context
- The model generates one step at a time exactly as for ordinary steps: the one-function-per-step
  form and per-step caching are unchanged — the group is never generated as one multi-step unit
```

- CREATE `.goga/usages/prompts/group_diagnosis.md` (full content):

```md
# Group diagnosis system prompt

The system prompt of every group diagnosis request of prettyplay — referenced by the engine/groups
cell as the `group_diagnosis` practice. Content is the single source; the cell renders it verbatim
as the system message.

---

You diagnose a failure of one step inside a group of steps that form one coherent interaction with
a shared goal.

Input you receive:
- GROUP PROMPT: the shared goal of the group, verbatim
- GROUP STEPS: every step of the group in execution order — each with its sentence, its outcome
  (passed or failed) and its URL before -> after transition
- STEP: the failed step sentence
- HISTORY: the verbatim record of every attempt of the failed step so far
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- SCREENSHOT: an image of the page, when attached
- USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it;
  it never overrides the fixed answer format below

Answer with exactly one JSON object of the form:
{"category": "recoverable | product_defect | incurable",
 "root_cause": "<one short sentence>",
 "earliest_step": "<the verbatim sentence of the earliest affected step>",
 "recommendation": "<one short sentence what should be regenerated or done>"}

Category calibration:
- recoverable — the failure stems from one or more earlier steps of the group (a step that did not
  land what its sentence says) and regenerating the affected steps of the group can fix the run
- product_defect — the application is genuinely broken; regenerating steps cannot and must not
  turn this green
- incurable — the root cannot be reached from inside the group (it lives in an earlier step of the
  test outside the group), or regeneration cannot help

Rules:
- earliest_step must quote a group step sentence verbatim when the category is recoverable; when
  the root lives outside the group, quote that outside step sentence verbatim and answer incurable
- Output only the JSON object, no other text
```

- ALREADY UPDATED (working tree, no plan action): `.goga/usages/cooks/playwright.md` (the slow_mo
  section), `.goga/usages/cooks/json_repair.md` (the group diagnosis answer as the second salvage
  consumer).

## Dependency Map

```
failures ──► config ──► {llm, driver}
reporting ──► {cache, engine, groups, steering, facade}
driver ──► polling
llm (ScenarioStep, GroupFailureClassification) ──► {engine, groups, steering, facade}
cache (RunBudgets refresh/cycle) ──► {engine, groups, steering, facade}
polling (SettleWindow tries) ──► {engine, groups, facade}
engine (StepGenerator framing, StepHealer) ──► {groups, steering, facade}
engine/groups (GroupRecovery, GroupStepOutcome) ──► facade
steering ──► facade
facade (PrettyPlay, StepGroup, StepExecutor) — the root
```

No cycles: `engine` imports neither `groups` nor `steering`; `groups` and `steering` do not import
each other or the facade.

## Verification Checklist

Per artifact, after implementation:

- `prettyplay/config`: `goga lint` clean; `load_config` layers `speed` from file/env/override;
  out-of-range and malformed values raise `ConfigurationError` naming setting, value, range; the
  merge reaches inside the browser group (SC2).
- `prettyplay/driver`: `open_context` passes `slow_mo=int((100−speed)×30)` on local launch and
  remote connect; speed 100 ≡ no slow_mo argument passed today's behavior (SC1).
- `prettyplay/engine/polling`: `SettleWindow(tries=None)` — behavior identical to today; declared
  `tries` bounds the loop by count; settle_retry records uniform; counter resets per settle call
  (SC3, SC4).
- `prettyplay/llm`: both providers implement `classify_step_failure` (renamed) and
  `classify_group_failure` with identical block order; `ScenarioStep`/`GroupFailureClassification`
  models kw_only; `parse_group_failure_classification` degrades garbage to incurable, never
  synthesizes recoverable, salvage failures degrade too; `generate_step_code` renders GROUP PROMPT
  before PREVIOUS STEPS in both providers (parity).
- `prettyplay/cache`: `refresh_healing` renews the full pool; `open_group_cycle` caps per group by
  `healing_limit`; ordinary pools untouched.
- `prettyplay/engine`: `generate`/`regenerate`/`heal` accept `list[ScenarioStep]`;
  `group_prompt=None` paths byte-identical (regression pins); group branch raises unclassified
  `IncurableStepError` carrying code + error; the frozen prompts byte-identical (mirror pins); the
  renamed practice paths resolve.
- `prettyplay/engine/groups` (new): full CODEMANIFEST validates (`goga lint`); the earliest-step
  matching covers group-step / outside-step / no-match; the cycle cap and per-cycle refresh are
  wired to RunBudgets; on_healing_started/on_healed + log records fire per recovered step; strict
  never reaches recover (SC6, SC8).
- `prettyplay/engine/steering`: steer accepts typed records and group_prompt; dialog behavior
  unchanged; the guided requests of a group step carry the framing.
- `prettyplay` (facade): `step`/`expect` validate tries/delay loudly at the call; `group()`
  validates prompt/speed/delay loudly; zero steps — quiet no-op; pre-step pause quiet and
  measurable (SC5); group between-step pauses use the percent→ms formula, never slow_mo (SC10);
  the executor routes group failures to recovery before steering; cache addressing untouched
  (SC9); strict replay of a fully cached group makes zero LLM calls (SC7).
- Practices: `step_generation.md`/`step_cheatsheet.md` byte-identical to the former files (diff
  must be empty after rename); `group_framing.md`/`group_diagnosis.md` exist and are referenced by
  exactly the cells above.
- Project gates: `pytest tests/ -x` green, `ruff check` clean, prompt-mirror pins extended to the
  two new artifacts without touching the frozen mirrors (C13); the public docs (MkDocs) render the
  new settings, step parameters and the group block.

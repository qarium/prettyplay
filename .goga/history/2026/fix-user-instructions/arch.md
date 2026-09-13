# Architecture Plan — fix-user-instructions

Topic: **fix-user-instructions** — make user instructions binding, checkable, and expressible.
Plan path: `.goga/history/2026/fix-user-instructions/arch.md` (this file).
Policy line (ADR, binding): **an unfollowed or unfulfillable instruction must surface as a generation error, never as silent ignoring.**

Base usages for every CODEMANIFEST (from `.goga/config.yml`): `conventions: .goga/usages/conventions.md`; base annotation: `Use \`conventions\` for code writing rules and testing.`

Status markers: **[MODIFIED]** — existing cell changed via diff; **[NEW TYPE]** — new type inside a modified cell. No new cells are created.

---

## Implementation Order

| # | Cell | Status | Reason for position |
|---|---|---|---|
| 1 | `prettyplay/failures` | [MODIFIED] | Leaf — no Imports; provides `ComplianceVerdictError` consumed by llm |
| 2 | `prettyplay/config` | [MODIFIED] | Depends only on failures (existing); provides `generation_approve` consumed by engine/steering |
| 3 | `prettyplay/driver` | [MODIFIED] | Depends only on config (existing); provides the assertion capability consumed by the PAGE API listing |
| 4 | `prettyplay/llm` | [MODIFIED] | Depends on config + failures; provides `ComplianceFinding`, `parse_compliance_verdict`, the third port operation |
| 5 | `prettyplay/engine` | [MODIFIED] | Depends on config, failures, driver, cache, llm, reporting, polling; integrates the gate |
| 6 | `prettyplay/engine/steering` | [MODIFIED] | Depends on engine + llm (top of the modified chain); gates the guided write-back |
| 7 | `prettyplay` (root) | [MODIFIED] | Top of the chain — the by-kind failure enumerations gain `ComplianceVerdictError`; text-only additive change, no signature changes |

Design rule: the mirror practice `.goga/usages/prompts/generation.md`, the facade.md surface rows and example section, and both frozen mirrors (`SYSTEM_PROMPT`, `PAGE_API_SURFACE` in `prettyplay/engine/generator.py` and `prettyplay/engine/steering/steering.py`) change **together** in one coordinated change during implementation steps 5–6; the driver CODEMANIFEST and implementation land earlier at step 3 without touching facade.md — the signature change does not break the old listing.

Explicitly out of scope (owner decision 2026-09-13): `example/.prettyplay/cache/**` stays untouched; cells `prettyplay/cache`, `prettyplay/reporting`, `prettyplay/engine/polling` are untouched.

---

## Artifacts

### 1. Cell `prettyplay/failures` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/failures/CODEMANIFEST`)

**CHANGE — global Annotations**, first taxonomy line:

```text
- FROM: The failure taxonomy of the library: three distinct, user-distinguishable step failure kinds plus the shared verdict type; every failure carries an actionable message.
- TO:   The failure taxonomy of the library: four distinct, user-distinguishable step failure kinds plus the shared verdict type; every failure carries an actionable message.
```

**ADD — global Annotations**, after that line:

```text
The compliance verdict hard failure joins the LLM contour of the taxonomy — it blocks only the generation contour and never touches cached step execution; it is raised when the compliance gate cannot obtain a usable verdict, so unchecked candidate code is never cached.
```

**ADD — Body**, after the `"PrettyplayError::LLMUnavailableError(message: str)"` block:

```yaml
"PrettyplayError::ComplianceVerdictError(message: str)":
  location: errors.py
  annotations: |
    The compliance gate could not obtain a usable verdict: the provider answer did not
    parse into findings. The successfully executed candidate stays unchecked and is never
    cached — a loud hard failure, never a silent pass.

    `message`: the rendered actionable text — names the compliance gate, the parse failure
    and a fragment of the raw verdict answer.

    Requirements:
    - Derives from `PrettyplayError`: catchable with the single library except clause
    - Raised only on the compliance gate paths — generation, healing and steering
      candidates; never on a cached step execution path
    - Carries no verdict: a verdict parse failure is not a step failure classification —
      uniform with the LLM infrastructure failure
    - The raiser guarantees nothing was written to the step cache
  properties:
    "message -> str": |
      The rendered actionable text naming the gate and the raw answer fragment.
```

**CHANGE — Footer Description:**

```text
- FROM: The failure taxonomy of prettyplay: product defect, incurable step, LLM infrastructure — mutations of one library base — the shared verdict of a terminal failure, and the single structured render of its message.
- TO:   The failure taxonomy of prettyplay: product defect, incurable step, LLM infrastructure, compliance verdict — mutations of one library base — the shared verdict of a terminal failure, and the single structured render of its message.
```

#### `.usages` file (`prettyplay/failures/.usages/taxonomy.md`) — CHANGE/ADD

**CHANGE — intro line:**

```text
- FROM: Every step failure is one of three distinct kinds; all derive from `PrettyplayError`, so one except clause catches any prettyplay failure. A fourth kind — the configuration error — joins the base from the config cell.
- TO:   Every step failure is one of four distinct kinds; all derive from `PrettyplayError`, so one except clause catches any prettyplay failure. A fifth kind — the configuration error — joins the base from the config cell.
```

**ADD — exceptions table row** (after the LLMUnavailableError row, before ConfigurationError):

```markdown
| ComplianceVerdictError | the compliance gate could not obtain a usable verdict | a successfully executed candidate was checked, but the verdict model answer did not parse | rerun the step to retry generation; a repeatedly malformed verdict points at the verdict model — the candidate was never cached |
```

**ADD — section after the LLM-unavailable section:**

```markdown
## Compliance verdict failure — ComplianceVerdictError

Raised when the instruction compliance gate cannot parse the verdict model's answer into
findings: the JSON shape is invalid, a priority label is outside {high, medium, low}, or a
finding misses its fields. The gate is strict by design — a flaky verdict model surfaces
loudly instead of waving candidates through.

Catch it together with every other library failure:

```python
from prettyplay.failures import ComplianceVerdictError, PrettyplayError

try:
    scenario.step("open the dashboard")
except ComplianceVerdictError as error:
    ...  # the candidate was NOT cached; rerun the step to retry generation
except PrettyplayError:
    ...
```

What it means for the engineer:
- the step candidate executed successfully but was never verified against the project
  instructions, so it was not cached
- remediation is on the verdict side, not the page: rerun the test, check the provider
  state and the model behind the effective generation model; a repeatedly malformed
  verdict points at a model unable to follow the verdict format
- switching `generation_approve` off removes the gate entirely (the old behavior)
```

---

### 2. Cell `prettyplay/config` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/config/CODEMANIFEST`)

**ADD — global Annotations** (append to the existing block):

```text
The generation_approve switch defaults to True — the opt-out carries the product line loud errors instead of silent ignoring: the instruction compliance gate runs unless explicitly disabled.
```

**CHANGE — Body, `Config` entity signature:**

```text
- FROM: "Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, polling_timeout: float | None, polling_delay: float, interactive: bool, generation_attempts: int, healing_attempts: int, send_screenshots: bool)"
- TO:   "Config(provider: str, browser: BrowserConfig, model: str, generation_model: str, classification_model: str, base_url: str, cache_root: str, generation_prompt: str, classification_prompt: str, strict: bool, polling_timeout: float | None, polling_delay: float, interactive: bool, generation_attempts: int, healing_attempts: int, send_screenshots: bool, generation_approve: bool)"
```

**ADD — Body, `Config` annotations**, after the `send_screenshots` param description:

```yaml
    generation_approve: the instruction compliance gate switch; True — every successfully
    executed generation and regeneration candidate is verified against the user
    instructions (the non-empty generation_prompt) before it is cached — one extra LLM
    call per successful generation; False — the gate never runs, fully the old behavior;
    default True (the opt-out default).
```

**ADD — Body, `Config` Requirements:**

```yaml
    - generation_approve participates in the layered merge of `load_config` like every
      other setting — an explicitly passed False overrides the file layer too (the
      `strict`/`interactive` pattern)
```

**ADD — Body, `Config` properties** (after `"send_screenshots -> bool"`):

```yaml
    "generation_approve -> bool": |
      Whether the instruction compliance gate runs before caching a generated step.
```

**CHANGE — Body, `load_config` Algorithm step 6**, append to the env-override sentence:

```text
; generation_approve reads PRETTYPLAY_GENERATION_APPROVE — booleans parse true/false/1/0 case-insensitively; an unparseable value raises the loud actionable `ConfigurationError` naming the setting, the received value and the accepted form
```

**ADD — Body, `load_config` Requirements:**

```yaml
    - PRETTYPLAY_GENERATION_APPROVE exists as the env override of generation_approve, parsing booleans true/false/1/0 case-insensitively; an unparseable value raises the loud actionable `ConfigurationError` — never a silent ignore
```

**CHANGE — Footer Description:**

```text
- FROM: Project settings of prettyplay: the validated [tool.prettyplay] schema with the nested browser group (engine, screen mode, headless, endpoint, dialog auto-accept), the strict replay-only switch, the generation and classification instructions, and the loader ...
- TO:   Project settings of prettyplay: the validated [tool.prettyplay] schema with the nested browser group (engine, screen mode, headless, endpoint, dialog auto-accept), the strict replay-only switch, the generation and classification instructions, the generation compliance switch, and the loader ...
```

#### `.usages` file (`prettyplay/config/.usages/configuration.md`) — ADD

TOML example block line (after `generation_prompt`):

```toml
generation_approve = true  # the instruction compliance gate before caching; false -> never runs (the old behavior)
```

Env table row:

```markdown
| generation_approve | `PRETTYPLAY_GENERATION_APPROVE` |
```

New section:

```markdown
## The instruction compliance gate

The user instructions of `generation_prompt` are binding for generated step code: every
successfully executed candidate passes an independent compliance check before it is
cached. The gate is the default; switch it off consciously when the extra LLM call per
successful generation matters more than the enforcement.

[tool.prettyplay]
generation_prompt = "Prefer id attributes for locating elements"
generation_approve = true   # default; false -> the gate never runs (the old behavior)

Env override (booleans: true/false/1/0, case-insensitive; anything else fails loudly):

```bash
export PRETTYPLAY_GENERATION_APPROVE=false
```

Per-test override — an explicit False wins over the file layer:

```python
config = PrettyConfig(generation_approve=False)
scenario = PrettyPlay(cache_key="smoke", config=config)
```

Notes for the engineer:
- while the gate is on, every successful generation costs one extra LLM call (the verdict
  request) through the effective generation model
- a `high` finding fails the attempt and the retry carries the violation text — loud
  errors instead of silent ignoring
- changing `generation_prompt` does not invalidate cached steps: the step address stays
  instruction-free, so purge the cache manually after changing instructions — replayed
  cached code is never re-gated
- the gate never runs when `generation_prompt` is empty, regardless of the switch
```

---

### 3. Cell `prettyplay/driver` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/driver/CODEMANIFEST`)

**ADD — global Annotations**, appended to the parity-principle paragraph:

```text
The case semantics of the text assertion family mirror Playwright's own ignore_case flag — the capability rides the existing mirror method names, not a new non-mirror family.
```

**CHANGE — Body, `PageFacade.methods`:**

```yaml
    - FROM:
    "expect_title(title: str)":
      Assert the page title contains `title` — auto-waiting.
    - TO:
    "expect_title(title: str, ignore_case: bool = False)":
      Assert the page title contains `title` — auto-waiting.

      `title`: the expected substring.
      `ignore_case`: False (the default) — the check stays case-sensitive, the behavior
      unchanged; True — the title pattern compiles with the case-insensitive regex flag
      (see `playwright`).
```

**CHANGE — Body, `LocatorFacade.methods`:**

```yaml
    - FROM:
    "expect_text(text: str)":
      Assert the element text contains `text` (substring, whitespace-normalized).
    - TO:
    "expect_text(text: str, ignore_case: bool = False)":
      Assert the element text contains `text` (substring, whitespace-normalized).

      `text`: the expected substring.
      `ignore_case`: False (the default) — the check stays case-sensitive, the behavior
      unchanged; True — the substring check matches case-insensitively through the
      Playwright ignore_case flag (see `playwright`).
```

Footer: unchanged.

#### `.usages` file (`prettyplay/driver/.usages/facade.md`) — CHANGE/ADD

**CHANGE — Surface — page row:**

```text
- FROM: | page.expect_title(title) | assert the title contains |
- TO:   | page.expect_title(title, ignore_case) | assert the title contains; ignore_case=true — case-insensitive |
```

**CHANGE — Surface — element row:**

```text
- FROM: | element.expect_text(text) | assert text contains (substring, whitespace-normalized) |
- TO:   | element.expect_text(text, ignore_case) | assert text contains (substring, whitespace-normalized); ignore_case=true — case-insensitive |
```

**ADD — section after Interactions:**

```markdown
Case-insensitive text assertions:

```python
page.get_by_text("status").expect_text("success", ignore_case=True)
page.expect_title("dashboard", ignore_case=True)

# default (False) — the check stays case-sensitive, the behavior unchanged
page.get_by_text("status").expect_text("success")
```

The flag belongs to the assertion family only: text locating (get_by_text,
filter(has_text=...)) already matches case-insensitively through Playwright defaults.
```

---

### 4. Cell `prettyplay/llm` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/llm/CODEMANIFEST`)

**CHANGE — Header Imports** (failures entry):

```yaml
  - FROM:
  - Types:
      - LLMUnavailableError
    From: prettyplay/failures
  - TO:
  - Types:
      - LLMUnavailableError
      - ComplianceVerdictError
    From: prettyplay/failures
```

**ADD — global Annotations:**

```text
The compliance verdict operation is the third operation of the port with the same absolute parity: one verdict request per successfully executed candidate, the answer parsed strictly — a malformed verdict raises the hard compliance failure, never a silent pass.
The one-request-per-attempt rule covers the verdict request too: attempt budgets are owned by the calling engine, never by a provider.
```

**ADD — Body, `LLMProvider.methods`** (after `classify_failure`):

```yaml
    "check_instruction_compliance(prompt: str, user_instructions: str, step_text: str, code: str) -> verdict: list[ComplianceFinding]": |
      Check the successfully executed candidate code against the project user instructions —
      the compliance verdict request of the gate.

      `prompt`: the gate system prompt text supplied by the calling engine — applied
        verbatim as the system message.
      `user_instructions`: the project's generation instructions supplied by the calling
        engine from the generation_prompt setting; the calling engine guarantees non-empty —
        the gate never runs on empty instructions.
      `step_text`: the sentence of the generated step.
      `code`: the successfully executed candidate code.
      `verdict`: the parsed findings; an empty list means compliant.

      Requirements:
      - A provider service failure raises `LLMUnavailableError` naming the provider
      - The answer parses strictly through `parse_compliance_verdict`; a malformed verdict
        raises `ComplianceVerdictError` — unchecked code is never waved through
      - The user content carries three blocks in the fixed order INSTRUCTIONS, STEP, CODE —
        identically in both implementations
      - The gate model is the effective generation model of the provider settings
      - The input takes no part in step addressing: a cached step never regenerates because
        it changed
```

**CHANGE — Body, `LLMProvider::OpenAIProvider` and `LLMProvider::AnthropicProvider` annotations:** rename `Algorithm (both operations):` → `Algorithm (all three operations):` and **ADD** the compliance branch after the existing steps:

```yaml
    The compliance operation: the prompt as the system message, the user content carrying
    the INSTRUCTIONS, STEP and CODE blocks in this fixed order; sent as one request
    through the effective generation model; the text answer parses strictly through
    `parse_compliance_verdict` — no fence unwrapping, a malformed verdict raises
    `ComplianceVerdictError`; an SDK error maps to `LLMUnavailableError` (see `openai` /
    `anthropic`)
```

(The anthropic implementation keeps the fixed 4096-token completion cap on the verdict request, as on every operation.)

**ADD — Body, new types** (after `"FailureClassification(...)"`):

```yaml
"ComplianceFinding(instruction: str, priority: str, explanation: str)":
  location: models.py
  annotations: |
    One finding of the instruction compliance verdict: which instruction the candidate
    code violated, how severely, and why.

    `instruction`: the violated instruction — the verbatim quote of the project's user
    instructions the finding names.
    `priority`: high, medium or low; only high blocks the candidate.
    `explanation`: one short sentence why the code violates the instruction.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - `priority` accepts exactly the three labels; anything else never reaches this type
      — the parse fails loudly before
  properties:
    "instruction -> str": |
      The violated instruction quote.
    "priority -> str": |
      The finding priority: high, medium or low.
    "explanation -> str": |
      One short sentence why the code violates the instruction.

"parse_compliance_verdict(verdict_text: str) -> findings: list[ComplianceFinding]":
  location: models.py
  annotations: |
    Parse the raw answer of the compliance verdict request into findings — the strict
    single parsing point of the gate.

    `verdict_text`: the raw text answer of the verdict model.
    `findings`: the parsed findings; empty — compliant.

    Algorithm:
    1. Parse the trimmed text as a JSON list of objects; anything else — not valid
       JSON, not a list, a non-object item — is a malformed verdict
    2. Validate every item: instruction, priority of the {high, medium, low} set,
       explanation — a missing field or an unknown priority label is a malformed verdict
    3. A malformed verdict raises `ComplianceVerdictError` carrying a fragment of the
       raw answer — a flaky verdict model surfaces loudly, never a silent pass
    4. Return the findings; an empty list means compliant

    Requirements:
    - Pure function: no state, no I/O, deterministic on the input text
    - No fence unwrapping and no protective fallback: the verdict answer parses as
      received (see `openai` and `anthropic`)
```

**CHANGE — Footer Description:**

```text
- FROM: The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity — generation and classification user instructions with identical semantics — and the failure classification verdict.
- TO:   The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity — generation, classification and compliance verdict operations with identical user-instructions semantics — the failure classification verdict and the instruction compliance findings.
```

#### `.usages` file (`prettyplay/llm/.usages/providers.md`) — CHANGE/ADD

**CHANGE — Parity section:**

```text
- FROM: Both providers expose the same two operations — generate_step_code and classify_failure — ...
- TO:   Both providers expose the same three operations — generate_step_code, classify_failure and check_instruction_compliance — ...
```

**ADD — Models table note:**

```markdown
The instruction compliance gate runs on the effective generation model (generation_model
or model).
```

**ADD — section:**

```markdown
## The compliance operation

check_instruction_compliance is the verdict request of the instruction compliance gate:
the engine calls it once per successfully executed candidate before caching — never for
replayed cached code, never when generation_approve is off or generation_prompt is empty
(zero calls).

The request carries the gate system prompt and three blocks — INSTRUCTIONS, STEP, CODE;
the answer is a JSON list of findings:

[{"instruction": "...", "priority": "high", "explanation": "..."}]

- the priority is high, medium or low; only high blocks the candidate — the calling
  engine owns that decision
- the model behind the call is the effective generation model (generation_model or
  model)
- a malformed answer raises ComplianceVerdictError and a provider failure raises
  LLMUnavailableError — both hard: the candidate is not cached unchecked
```

---

### 5. Cell `prettyplay/engine` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/engine/CODEMANIFEST`)

**CHANGE — Header Imports** (llm entry adds `ComplianceFinding`):

```yaml
  - FROM:
  - Types:
      - LLMProvider
      - FailureClassification
    Usages:
      - classification
    From: prettyplay/llm
  - TO:
  - Types:
      - LLMProvider
      - FailureClassification
      - ComplianceFinding
    Usages:
      - classification
    From: prettyplay/llm
```

**ADD — Header Usages** (new inline practice):

```yaml
  compliance_prompt: |
    You verify that generated step code follows the project's user instructions.

    Input you receive:
    - INSTRUCTIONS: the project's user instructions, verbatim
    - STEP: the step sentence the code was generated for
    - CODE: the successfully executed candidate code

    Check the code against every instruction and answer with exactly one JSON list of
    findings:
    [{"instruction": "<the violated instruction quote>", "priority": "high|medium|low",
    "explanation": "<one short sentence>"}]

    Priority calibration:
    - high — a confident, material violation evident from the code itself: the instruction
      was expressible through the page API the code already uses, and the code plainly
      skipped or contradicted it without any fallback attempt; only high blocks the
      candidate
    - medium and low — minor observations, partial compliance or doubt: visible, never
      blocking; when in doubt, never high
    - an empty list [] means the code complies

    Rules:
    - Conditional prefer-type instructions are checked conditionally: when the code shows
      a graceful fallback attempt, that is compliance; judge followability from the code
      and the step sentence alone — you see no page state, never speculate about it
    - An instruction the code could not follow because the step sentence itself prevents
      it is not a violation; when the inputs leave the followability in doubt, the finding
      is never high
    - Judge only what the code does against the instructions — not the step sentence,
      not the page state beyond the instructions
    - Output only the JSON list, no other text
```

**CHANGE — Header Usages, inline `classification_prompt`:** the input line

```text
- FROM: - USER INSTRUCTIONS: the project's classification guidance, when configured
- TO:   - USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it; it never overrides the fixed answer format above
```

**ADD — global Annotations:**

```text
Use `compliance_prompt` as the system prompt of every compliance verdict request.
The instruction compliance gate runs inside the engines: every successfully executed candidate — generation, healing and steering alike — passes `check_step_compliance` before it is cached; the gate never runs on replayed cached code.
An unfollowed instruction surfaces as a generation error, never as silent ignoring: a high finding fails the attempt and the retry carries the violation text.
```

**ADD — Body, new type** (after `"classify_step_failure(...)"`):

```yaml
"check_step_compliance(config: Config, provider: LLMProvider, step_text: str, code: str) -> findings: list[ComplianceFinding]":
  location: compliance.py
  annotations: |
    Gate a successfully executed candidate against the project user instructions — the
    single compliance check of every caching path.

    `config`: project settings — the gate switch and the generation instructions.
    `provider`: the LLM port.
    `step_text`: the sentence of the generated step.
    `code`: the successfully executed candidate code.
    `findings`: the verdict findings; empty — compliant or the gate is off.

    Algorithm:
    1. The generation_approve setting is off or the generation_prompt setting is empty —
       return an empty list with zero provider calls: fully the old behavior
    2. Ask the provider port check_instruction_compliance passing `compliance_prompt` as
       the system prompt, the effective config generation_prompt as the user
       instructions, `step_text` and `code`
    3. Return the findings

    Requirements:
    - Never called for replayed cached code — the gate checks candidates before caching
    - Provider unavailability and a malformed verdict propagate to the caller as the
      hard failures they are: this routine never swallows, the calling path never caches

    Constraints:
    - No attempt budget is consumed here — budgets belong to the calling loops
```

**CHANGE — Body, `StepGenerator` annotations**, constructor line:

```text
- FROM: `config`: project settings — the screenshot flag and the generation instructions.
- TO:   `config`: project settings — the screenshot flag, the generation instructions and the compliance gate switch.
```

**CHANGE — Body, `StepGenerator.generate` Algorithm step 5:**

```yaml
    - FROM:
    5. On success: build `CachedStep`, save it to the cache, return it
    - TO:
    5. On success: gate the candidate through `check_step_compliance`. An empty findings
       list — build `CachedStep`, save it to the cache, return it. A high finding — the
       attempt is failed: the violation text (the finding instruction and explanation)
       becomes the ERROR of the attempt; retry with it and the fresh snapshot while
       attempts remain. Medium and low findings pass with a WARNING naming the
       instructions, then the step is stored and returned. The gate hard failures —
       provider unavailability and a malformed verdict — propagate immediately: nothing
       is cached
```

**CHANGE — Body, `StepGenerator.generate` Algorithm step 8**, append after the existing exhaustion text:

```yaml
       budget exhaustion with a standing high compliance finding raises
       `IncurableStepError` carrying the verdict that names the violated instruction —
       the reason names the exhausted pool and the instruction (colon-free), the
       violation text rides the error field; the verdict is built from the standing
       high finding: category incurable, explanation — the finding instruction and its
       explanation, recommendation — restating to follow the violated instruction in
       the step code
```

**CHANGE — Body, `StepGenerator.regenerate` Algorithm step 1**, append:

```yaml
       every successfully executed candidate is gated through `check_step_compliance`
       before storing — the same semantics as generate
```

**ADD — Body, `generate`/`regenerate` Requirements:**

```yaml
      - The retry request after a high compliance finding carries the violation text as
        its ERROR — the model fixes the violation targeted
      - Medium and low compliance findings pass with a visible WARNING through the
        library logger — structured, naming the step and the findings
      - The compliance gate itself consumes no attempt budget; only a high finding
        consumes the attempt it fails
```

**CHANGE — Footer Description:**

```text
- FROM: The agent engine of prettyplay: step code generation with execution in the loop and failed-check classification, the fixed-form execution routine, ...
- TO:   The agent engine of prettyplay: step code generation with execution in the loop and failed-check classification, the instruction compliance gate before caching, the fixed-form execution routine, ...
```

#### `.usages` files

**`prettyplay/engine/.usages/generation.md` — ADD section after «Failed candidate check (bounded healing)»:**

```markdown
## The instruction compliance gate

Every successfully executed candidate is verified against the generation_prompt
instructions before it is cached — the default behavior; switch it off with
generation_approve = false:

- one verdict request per candidate through the provider (the effective generation
  model); zero requests when the switch is off or the instructions are empty
- a high finding fails the attempt: the retry request carries the violation text as its
  ERROR, so the model fixes it targeted; budget exhaustion with a standing high finding
  is the terminal incurable failure naming the violated instruction
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) and provider unavailability
  (LLMUnavailableError) are hard failures — a candidate is never cached unchecked
- replayed cached code is never re-gated: changing the instructions does not invalidate
  the cache — purge it manually when the instructions change
```

**`prettyplay/engine/.usages/healing.md` — ADD line to the `## Rules` section (first rule of the list):**

```markdown
A healed candidate passes the instruction compliance gate before the write-back: a high
violation fails the healing attempt with the violation text as its ERROR; medium and low
findings pass with a WARNING; a malformed verdict or provider unavailability is a hard
failure — nothing is cached unchecked.
```

---

### 6. Cell `prettyplay/engine/steering` [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/engine/steering/CODEMANIFEST`)

**CHANGE — Header Imports (engine entry only):**

```yaml
  - FROM:
  - Types:
      - run_step_code
    From: prettyplay/engine
  - TO:
  - Types:
      - run_step_code
      - check_step_compliance
    From: prettyplay/engine
```

(The `prettyplay/llm` import entry is unchanged: no steering signature or annotation names `ComplianceFinding` — the findings are consumed inside the `check_step_compliance` semantics, so the type stays out of this contract.)

**ADD — global Annotations:**

```text
The instruction compliance gate guards the write-back: every successfully executed guided candidate passes `check_step_compliance` before it is saved — the same gate as the generation paths; the gate never runs on replayed cached code.
```

**CHANGE — Body, `StepSteering.steer` Algorithm step 6:**

```yaml
    - FROM:
    6. Success: build `CachedStep` with `identity`, save it to the cache, report on_healed with an explanation naming the interactive healing, return the healed step
    - TO:
    6. Success: gate the executed candidate through `check_step_compliance` — the gate
       switch off or empty generation instructions yield an empty findings list with zero
       provider calls. An empty findings list: build `CachedStep` with `identity`, save it
       to the cache, report on_healed with an explanation naming the interactive healing,
       return the healed step. A high finding: no write-back — show the violation in the
       dialog (the finding instruction and explanation), append the turn to the history,
       return to step 2. Medium and low findings pass with a WARNING naming the
       instructions, then the write-back. The gate hard failures — provider unavailability
       and a malformed verdict — end the dialog after showing the gate failure line in the
       dialog (the failure kind and its message) and logging a WARNING through the library
       logger naming the step and the gate failure: return None, the original terminal
       failure propagates; nothing is cached
```

**CHANGE — Body, `StepSteering.steer` Requirements:**

```text
- FROM: - The write-back happens only after a successful execution
- TO:   - The write-back happens only after a successful execution and a passed compliance gate
```

**ADD — Body, `StepSteering.steer` Requirements:**

```yaml
      - A high finding never reaches the cache: the dialog is the recovery path — the
        engineer steers the fix; interactive attempts stay budget-free
```

**CHANGE — Footer Description:**

```text
- FROM: The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration, live execution, healed write-back or honest decline.
- TO:   The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration, live execution, the compliance-gated healed write-back or honest decline.
```

#### `.usages` file (`prettyplay/engine/steering/.usages/steering.md`) — ADD section

```markdown
## The compliance gate of a guided heal

A guided candidate that executes successfully is verified against the generation_prompt
instructions before the write-back — the same compliance check as unattended generation:

- a high violation never reaches the cache: the dialog shows it, the turn lands in the
  history and the guidance prompt reopens — steer the model to fix the violation
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) or provider unavailability
  (LLMUnavailableError) ends the dialog — the gate failure is shown in the dialog and
  logged as a WARNING naming the step before the dialog ends, so the engineer sees why the
  green candidate was not written back; the original terminal failure propagates and
  nothing is cached
- the gate adds no budget consumption: interactive attempts stay free, the human in the
  loop is the bound
```

---

### 6a. Cell `prettyplay` (root) [MODIFIED]

#### CODEMANIFEST diff (`prettyplay/CODEMANIFEST`)

**CHANGE — Header Imports** (failures entry adds `ComplianceVerdictError`):

```yaml
  - FROM:
  - Types:
      - ProductDefectError
      - IncurableStepError
      - LLMUnavailableError
      - PrettyplayError
      - FailureVerdict
    Usages:
      - taxonomy
    From: prettyplay/failures
  - TO:
  - Types:
      - ProductDefectError
      - IncurableStepError
      - LLMUnavailableError
      - ComplianceVerdictError
      - PrettyplayError
      - FailureVerdict
    Usages:
      - taxonomy
    From: prettyplay/failures
```

**CHANGE — Body, `PrettyPlay.step` annotations:**

```text
- FROM: ... failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`).
- TO:   ... failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`).
```

**CHANGE — Body, `PrettyPlay.expect` annotations:** the identical enumeration change as `step`.

**CHANGE — Body, `StepExecutor.execute` Algorithm step 8:**

```text
- FROM: ... finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError` (see `taxonomy`)
- TO:   ... finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`)
```

The steering intercept of execute step 6 needs no change: it triggers only on `IncurableStepError`, and the gate hard failure is not an incurable step — it propagates directly, uniform with `LLMUnavailableError`.

Footer: unchanged.

---

### 7. Project-level practice [MODIFIED] — `.goga/usages/prompts/generation.md`

Content change (lands in the same implementation step as both frozen mirrors):

**CHANGE — input list line:**

```text
- FROM: - USER INSTRUCTIONS: the project's code style guidance, when configured
- TO:   - USER INSTRUCTIONS: the project's binding code style guidance, when configured
```

**ADD — Rules** (after the RECOMMENDATION/USER GUIDANCE rule):

```text
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules:
  follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function
  form, no imports, facade-only calls, expectations-only assertions, no fixed delays.
  An instruction conflicting with a Rule or naming a call outside the page API surface
  is unfollowable: never implement it silently — raise in the step code with the message
  "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the
  page offers the option — best-effort with a graceful fallback is compliance
```

---

### 8. Accompanying (non-cell) work items

Not CODEMANIFEST/`.usages` artifacts; listed for completeness of the approved scope:

| Item | Detail |
|---|---|
| Frozen mirrors | `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` and `prettyplay/engine/steering/steering.py` = practice text of `.goga/usages/prompts/generation.md`; `PAGE_API_SURFACE` in both = surface tables of `prettyplay/driver/.usages/facade.md` — change together with items 3 and 7 |
| Docs | `docs/configuration.md` (the new setting, the instruction policy, the manual cache-purge note, the cost note), `docs/reference/llm-providers.md` (the third operation), `docs/reference/step-cache.md` (the manual purge note) |
| Tests | Per the task acceptance list: gate retry/error paths with fake providers, zero gate calls when off/empty, medium/low WARNING pass, facade case-insensitive behavior + unchanged default, config field/env/merge/override, prompt-mirror sync tests |
| Explicitly NOT done | `example/.prettyplay/cache/**` untouched (owner decision 2026-09-13); no changes to cells cache/reporting/polling |

---

## Dependency Map

```
prettyplay/failures  [MODIFIED: +ComplianceVerdictError]
  ▲                ▲
  │                │ (LLMUnavailableError, +ComplianceVerdictError)
  │                │
  │     prettyplay/llm  [MODIFIED: +ComplianceFinding, +parse_compliance_verdict,
  │                      +check_instruction_compliance on LLMProvider]
  │        ▲                    ▲
  │        │                    │ (+ComplianceFinding)
  │        │                    │
  │        │            prettyplay/engine  [MODIFIED: +check_step_compliance,
  │        │                    │           StepGenerator gate, +compliance_prompt]
  │        │                    │                    │ (run_step_code, +check_step_compliance)
  │        │                    │                    ▼
  │        │            prettyplay/engine/steering  [MODIFIED: gate before write-back;
  │        │                                          llm edge unchanged (LLMProvider only)]
  │        │
  └── prettyplay/config  [MODIFIED: +generation_approve] ──► llm, engine, steering (Config)

prettyplay/driver  [MODIFIED: expect_title/expect_text + ignore_case]
  └── facade.md surface ──► PAGE_API_SURFACE mirrors in engine + steering
```

Dependency order (leaves → root): failures → reporting → config → driver → cache → llm → engine/polling → engine → engine/steering → prettyplay (root) [MODIFIED: the by-kind enumerations gain `ComplianceVerdictError`]. No cycles; all new imports ride existing edge directions.

---

## Verification Checklist

After implementing each artifact:

1. `prettyplay/failures` — `goga lint` clean; `ComplianceVerdictError` derives from `PrettyplayError`; taxonomy text says four kinds; `taxonomy.md` section present and self-contained, the intro says four kinds plus the config fifth, and the exceptions table carries the `ComplianceVerdictError` row.
2. `prettyplay/config` — `goga lint` clean; default `generation_approve=True`; env `PRETTYPLAY_GENERATION_APPROVE` accepts true/false/1/0 case-insensitively and fails loudly otherwise; explicit-False overrides the file layer; `configuration.md` TOML line, env row and section present.
3. `prettyplay/driver` — `goga lint` clean; `expect_text`/`expect_title` carry `ignore_case: bool = False`; default path behavior unchanged (case-sensitive); `facade.md` surface rows and example section updated in the same change as the `PAGE_API_SURFACE` mirrors.
4. `prettyplay/llm` — `goga lint` clean; three operations on both providers with parity; `parse_compliance_verdict` strict (JSON list, three priority labels, no fallback); verdict request uses the effective generation model; `providers.md` says three operations.
5. `prettyplay/engine` — `goga lint` clean; `check_step_compliance` returns `[]` with zero provider calls when the switch is off or instructions empty; gate runs before every cache save in `generate`/`regenerate`; high finding → attempt ERROR + targeted retry; exhaustion with standing high → `IncurableStepError` naming the instruction (colon-free reason); medium/low → structured WARNING via the library logger; `compliance_prompt` referenced by annotations; `classification_prompt` carries the binding wording; practice `generation.md` and both mirrors updated together.
6. `prettyplay/engine/steering` — `goga lint` clean; write-back only after execution + passed gate; high finding → dialog + history → guidance prompt; gate hard failures end the dialog returning None, with the gate failure line shown in the dialog and a WARNING logged; `steering.md` section present.
7. `prettyplay` (root) — `goga lint` clean; the failures import entry carries `ComplianceVerdictError`; the three by-kind enumerations (`PrettyPlay.step`, `PrettyPlay.expect`, `StepExecutor.execute` step 8) name it.
8. Practice `.goga/usages/prompts/generation.md` — the three binding rules present; mirrors byte-equal (sync tests).
9. Whole project — `goga lint` (10 cells, 0 errors); `pytest tests/ -x` green including the new acceptance tests; `ruff check` clean; docs pages updated; `example/.prettyplay/cache/**` untouched.

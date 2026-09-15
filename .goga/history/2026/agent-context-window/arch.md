# [ARCHITECTURE_PLAN]

## Topic

**Honest step context window — attempt history and the two-dimension cache gate.**

Plan path: `.goga/history/2026/agent-context-window/arch.md` (topic `agent-context-window`, branch `agent-context-window`).
Source task: `.goga/history/2026/agent-context-window/task.md`; accepted ADR: `.goga/history/2026/agent-context-window/adr.md`.

All cells in this plan are **modified** existing cells — no cell is created anew. New artifacts inside existing cells: the type `StepAttempt` (`prettyplay/engine/attempts.py`) and the CI regression test suite under `tests/`. All content below is the **current state** of each artifact after the change; the per-cell "Modification summary" orients the apply stage (add/change/delete against today's files).

## Implementation Order

Leaves to root — each cell depends only on cells earlier in the list (its imports exist or are updated before it is touched):

1. **`prettyplay/llm`** (modified) — no dependency on the other touched cells; the port contract and the verdict models define what the engine renders into requests. Designed first.
2. **`prettyplay/engine`** (modified) — imports `ComplianceFinding`/`LLMProvider` from `prettyplay/llm`; owns the new `StepAttempt`, the loops, the healer and the two-dimension gate.
3. **`prettyplay/engine/steering`** (modified) — imports `run_step_code`, `check_step_compliance` and (newly) `StepAttempt` from `prettyplay/engine`; joins the shared history.
4. **`prettyplay`** (root, modified) — imports from `prettyplay/engine` (+`StepAttempt`) and `prettyplay/engine/steering`; the executor threads the honest inputs and seeds record #0.
5. **Project prompt mirror + tests** — `.goga/usages/prompts/generation.md` changes together with the frozen constants of engine and steering (step 2/3); the CI regression and parity-test extensions land with the cells they cover (steps 1–2), the live acceptance run belongs to the build stage.

## Artifacts

### 1. Cell: `prettyplay/llm` (modified)

**Modification summary:** header Annotations — add the step-type, attempt-history and two-dimension-verdict parity rules; the steering-history rule is replaced by the attempt-history rule. `generate_step_code` — add `step_type` and `attempt_history`, remove `existing_code`, `error`, `guidance_history`; the tail block order becomes HISTORY, RECOMMENDATION, USER GUIDANCE. `check_instruction_compliance` — add `step_type` and `attempt_history`; four-block user content. `ComplianceFinding` — add `dimension`. `parse_compliance_verdict` — validate `dimension`; an old-shaped answer is malformed. Both provider algorithms — render the new inputs in parity. `classify_failure` — the `step_text` input description now notes the raw sentence as passed by the calling engine; the rest unchanged. `create_provider`, `FailureClassification` — unchanged. Description updated.

#### CODEMANIFEST — `prettyplay/llm/CODEMANIFEST`

```yaml
Imports:
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - LLMUnavailableError
      - ComplianceVerdictError
    From: prettyplay/failures

Usages:
  conventions: .goga/usages/conventions.md
  openai: .goga/usages/cooks/openai.md
  anthropic: .goga/usages/cooks/anthropic.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `openai` and `anthropic` for the SDK call patterns and the error mapping of the two providers.

  Provider parity is absolute: both providers expose the same operations, accept the same inputs, return the same output shapes and map failures to the same taxonomy; the provider choice is a configuration decision, never a capability difference.
  The one SDK-forced asymmetry: the anthropic Messages API requires max_tokens on every request, so the anthropic implementation carries a fixed completion cap (4096 tokens — sized so a full multi-step step-code response never truncates) the openai side has no analogue of; the openai SDK sends no cap and defaults to the model maximum. A transport requirement of the SDK, not a capability difference of the port.
  The user instructions input participates in both provider implementations with identical semantics: generation requests render the generation instructions, classification requests render the classification instructions — each verbatim as a separate USER INSTRUCTIONS block; classification requests never carry the generation instructions and generation requests never carry the classification instructions; a parity requirement, not a capability difference.
  The cheat-sheet input participates in both provider implementations with identical semantics: every generation request renders the CHEAT SHEET block after the scenario inputs and immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by the calling engine; guidance, not an allowlist; a parity requirement, not a capability difference.
  The page-URL input participates in both provider implementations with identical semantics: a non-empty page_url of a generation request renders as its own PAGE URL line immediately after the PAGE SNAPSHOT block of the user content; None or empty — no line; a parity requirement, not a capability difference.
  The step-type input participates in both provider implementations with identical semantics: every generation request and every compliance verdict request renders the STEP TYPE line — action or assertion — immediately before the STEP line of the user content; a parity requirement, not a capability difference.
  The attempt-history input participates in both provider implementations with identical semantics: the HISTORY block renders every attempt-history record verbatim — each record a complete multi-line record (the attempt outcome, the URL before -> after line, the complete candidate code, the complete error) composed by the calling engine; the record list carries the whole attempt history of the step, the anchored original cached code first when it exists; no collapsing, no size limits; the block takes the place of the former CODE and ERROR request inputs and the former steering-only history block; a parity requirement, not a capability difference.
  API keys come only from environment variables; never log keys or payloads containing secrets.
  One completion request per attempt: attempt budgets are owned by the calling engine, never by a provider.
  Cached step code never depends on the provider: the provider serves generation, classification and the compliance verdict only.
  The compliance verdict operation is the third operation of the port with the same absolute parity: one verdict request per successfully executed candidate judging two dimensions in one request — instruction compliance and step adequacy — the answer parsed strictly through `parse_compliance_verdict`; a malformed verdict raises the hard compliance failure, never a silent pass.
  The one-request-per-attempt rule covers the verdict request too: attempt budgets are owned by the calling engine, never by a provider.

---

"LLMProvider()":
  location: provider.py
  annotations: |
    The unified LLM port of the library: code generation for a step, failure classification for healing and the two-dimension compliance verdict of the gate. One contract, two interchangeable implementations selected by configuration.
  methods:
    "generate_step_code(prompt: str, user_instructions: str, step_text: str, step_type: str, previous_steps: list[str], snapshot: str, page_url: str | None, screenshot: bytes | None, cheat_sheet: str, attempt_history: list[str], recommendation: str | None, guidance: str | None) -> code: str": |
      Generate step code of the fixed form.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's code style instructions supplied by the calling engine from the generation_prompt setting; empty — the request carries no instructions block; non-empty — rendered by the provider implementations verbatim as a separate USER INSTRUCTIONS block of the user content, identically in both.
      `step_text`: the raw sentence of the step to generate — as written by the engineer, verbatim; never the normalized addressing form.
      `step_type`: action or assertion — rendered by the provider implementations as the STEP TYPE line immediately before the STEP line, identically in both.
      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context.
      `snapshot`: the accessibility snapshot of the current page.
      `page_url`: the current URL of the page; non-empty — rendered by the provider implementations as its own PAGE URL line immediately after the PAGE SNAPSHOT block, identically in both; None — no line; supplied by the interactive steering only.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `cheat_sheet`: the compact standard Playwright sync API reference supplied by the calling engine — rendered by the provider implementations as the leading CHEAT SHEET block of the user content, identically in both; guidance, not an allowlist — everything standard stays allowed.
      `attempt_history`: the attempt history of the step — every record a complete multi-line verbatim record (the attempt outcome, the URL before -> after line, the complete candidate code, the complete error) composed by the calling engine; the original cached code anchors the list as record 0 when it exists; non-empty — rendered as the HISTORY block after the USER INSTRUCTIONS block; empty — no block; no collapsing, no size limits; the list takes the place of the former existing_code, error and guidance_history inputs — the last record is the code being fixed.
      `recommendation`: the diagnosis of the classification that preceded the regeneration; non-empty — rendered as a separate RECOMMENDATION block after the HISTORY block; None — no block.
      `guidance`: the engineer guidance message of the interactive steering; non-empty — rendered as a separate USER GUIDANCE block; None — no block.
      `code`: the generated step code of the fixed form, working through the standard Playwright sync API — imports from playwright.sync_api and the Python standard library only, global at the top level of the code block; the first markdown-fenced block of the answer is unwrapped — an answer with no closed fence returns verbatim.

      Requirements:
      - A provider service failure (connectivity, timeout, rate limit, authentication) raises `LLMUnavailableError` naming the provider
      - The generated code contains no provider-specific constructs
      - The block order of a generation request is fixed: CHEAT SHEET, user instructions, HISTORY, RECOMMENDATION, USER GUIDANCE — a non-empty input renders its named block, identically in both implementations
      - The PAGE URL line renders in the scenario part — immediately after the PAGE SNAPSHOT block; the STEP TYPE line renders immediately before the STEP line; the fixed order of the regeneration tail (HISTORY, RECOMMENDATION, USER GUIDANCE) is unchanged within it
      - The new inputs take no part in step addressing: a cached step never regenerates because they changed
    "classify_failure(prompt: str, user_instructions: str, step_text: str, code: str, error: str, snapshot: str, screenshot: bytes | None) -> classification: FailureClassification": |
      Classify a failed cached step.

      `prompt`: the system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's classification instructions supplied by the calling engine from the classification_prompt setting; empty — the request carries no instructions block; non-empty — rendered by the provider implementations verbatim as a separate USER INSTRUCTIONS block of the user content, identically in both.
      `step_text`: the raw sentence of the failed step as passed by the calling engine.
      `code`: the existing step code that failed.
      `error`: the human-readable description of the failure.
      `snapshot`: the accessibility snapshot of the current page.
      `screenshot`: an optional PNG image of the page; passed only when the project enables screenshots.
      `classification`: the `FailureClassification` verdict.

      Requirements:
      - A provider service failure raises `LLMUnavailableError` naming the provider
    "check_instruction_compliance(prompt: str, user_instructions: str, step_text: str, step_type: str, code: str, attempt_history: list[str]) -> verdict: list[ComplianceFinding]": |
      Check the successfully executed candidate code on two dimensions — instruction compliance and step adequacy — the compliance verdict request of the gate.

      `prompt`: the gate system prompt text supplied by the calling engine — applied verbatim as the system message.
      `user_instructions`: the project's generation instructions supplied by the calling engine from the generation_prompt setting; the calling engine guarantees non-empty — the gate never runs on empty instructions.
      `step_text`: the raw sentence of the generated step.
      `step_type`: action or assertion — the adequacy dimension judges by it; rendered as the STEP TYPE line immediately before the STEP line.
      `code`: the successfully executed candidate code.
      `attempt_history`: the attempt history of the step — verbatim records composed by the calling engine; non-empty — rendered as the ATTEMPT HISTORY block after the STEP block; the gate prompt instructs the reviewer to use it.
      `verdict`: the parsed findings of both dimensions; an empty list means compliant and adequate.

      Requirements:
      - A provider service failure raises `LLMUnavailableError` naming the provider
      - The answer parses strictly through `parse_compliance_verdict`; a malformed verdict raises `ComplianceVerdictError` — unchecked code is never waved through
      - The user content carries four blocks in the fixed order INSTRUCTIONS, STEP, ATTEMPT HISTORY, CODE — with the STEP TYPE line immediately before the STEP line — identically in both implementations
      - The gate model is the effective generation model of the provider settings
      - The input takes no part in step addressing: a cached step never regenerates because it changed

"LLMProvider::OpenAIProvider(config: Config)":
  location: openai_provider.py
  annotations: |
    The openai SDK implementation of `LLMProvider` (see `openai`).

    `config`: project settings; the generation model is the effective_generation_model of `config`, the classification model is the effective_classification_model of `config`; the base_url setting of `config` overrides the endpoint when set.

    Algorithm (all three operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — the STEP TYPE line renders immediately before the STEP line; the CHEAT SHEET block renders after the scenario inputs; a non-empty page_url renders as its own PAGE URL line immediately after the PAGE SNAPSHOT block; a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed immediately after the CHEAT SHEET block; the attempt-history records render as the HISTORY block placed after the USER INSTRUCTIONS block — every record verbatim, complete multi-line records, no collapsing; the remaining regeneration-only blocks render in the fixed order RECOMMENDATION, USER GUIDANCE; a non-empty input renders its named block, identically in both implementations; a non-empty user_instructions of a classification request renders as the separate USER INSTRUCTIONS block placed last in the user content, after all classification inputs (STEP, CODE, ERROR, PAGE SNAPSHOT)
    2. Send one completion request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
    4. An SDK error maps to `LLMUnavailableError` (see `openai`)

    The compliance operation: the prompt as the system message, the user content carrying the INSTRUCTIONS, STEP (with its STEP TYPE line), ATTEMPT HISTORY and CODE blocks in this fixed order; sent as one request through the effective generation model; the text answer parses strictly through `parse_compliance_verdict` — no fence unwrapping, a malformed verdict (an answer of the old shape included) raises `ComplianceVerdictError`; an SDK error maps to `LLMUnavailableError` (see `openai`)

"LLMProvider::AnthropicProvider(config: Config)":
  location: anthropic_provider.py
  annotations: |
    The anthropic SDK implementation of `LLMProvider` (see `anthropic`); full parity with the openai implementation — the SDK-forced max_tokens cap aside (see the document annotations).

    `config`: the same settings semantics as the openai implementation.

    Algorithm (all three operations):
    1. Build the request: the prompt text as the system message, the user content carrying the inputs — the STEP TYPE line renders immediately before the STEP line; the CHEAT SHEET block renders after the scenario inputs; a non-empty page_url renders as its own PAGE URL line immediately after the PAGE SNAPSHOT block; a non-empty user_instructions of a generation request renders as a separate USER INSTRUCTIONS block placed immediately after the CHEAT SHEET block; the attempt-history records render as the HISTORY block placed after the USER INSTRUCTIONS block — every record verbatim, complete multi-line records, no collapsing; the remaining regeneration-only blocks render in the fixed order RECOMMENDATION, USER GUIDANCE; a non-empty input renders its named block, identically in both implementations; a non-empty user_instructions of a classification request renders as the separate USER INSTRUCTIONS block placed last in the user content, after all classification inputs (STEP, CODE, ERROR, PAGE SNAPSHOT)
    2. Send one message request via the SDK
    3. Extract the text answer; a generation answer unwraps its first markdown-fenced block — an unfenced answer passes through verbatim
    4. An SDK error maps to `LLMUnavailableError` (see `anthropic`)

    The compliance operation: the prompt as the system message, the user content carrying the INSTRUCTIONS, STEP (with its STEP TYPE line), ATTEMPT HISTORY and CODE blocks in this fixed order; sent as one request through the effective generation model; the text answer parses strictly through `parse_compliance_verdict` — no fence unwrapping, a malformed verdict (an answer of the old shape included) raises `ComplianceVerdictError`; an SDK error maps to `LLMUnavailableError` (see `anthropic`)

"create_provider(config: Config) -> provider: LLMProvider":
  location: provider.py
  annotations: |
    Select and construct the LLM provider from configuration.

    `config`: project settings.
    `provider`: the selected provider implementation.

    Algorithm:
    1. Read the provider choice from `config`
    2. Construct the matching provider implementation with `config`
    3. Return it

    Requirements:
    - An unknown provider value fails loudly with an actionable message listing the supported providers

"FailureClassification(category: str, explanation: str, recommendation: str)":
  location: models.py
  annotations: |
    The verdict of a failure classification: what kind of failure it is and what to do about it.

    `category`: one of rot (the UI changed — regeneration is meaningful), product_defect (the expectation legitimately failed), fixable (the step code is at fault — an ambiguous or wrong locator or strategy — while the intent stays satisfiable; regeneration for the same intent can help), incurable (regeneration cannot help).
    `explanation`: why the failure got this category.
    `recommendation`: the recommended engineer action.

    Requirements:
    - `category` is always one of the four labels
    - An unrecognized label of the model answer parses to incurable — the protective fallback in both provider implementations: an unknown verdict never grants a regeneration
  properties:
    "category -> str": |
      The classification label: rot, product_defect, fixable or incurable.
    "explanation -> str": |
      Why the failure got this category.
    "recommendation -> str": |
      The recommended engineer action.

"ComplianceFinding(instruction: str, priority: str, explanation: str, dimension: str)":
  location: models.py
  annotations: |
    One finding of the two-dimension compliance verdict: which dimension it belongs to, what it names, how severely, and why.

    `instruction`: the verbatim quote the finding names — the violated instruction of the project's user instructions (instruction dimension) or the fragment of the step sentence the code fails to accomplish (adequacy dimension).
    `priority`: high, medium or low; only high blocks the candidate — in both dimensions.
    `explanation`: one short sentence why.
    `dimension`: instruction or adequacy — which side of the gate produced the finding.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - `priority` accepts exactly the three labels and `dimension` exactly the two; anything else never reaches this type — the parse fails loudly before
  properties:
    "instruction -> str": |
      The verbatim quote the finding names.
    "priority -> str": |
      The finding priority: high, medium or low.
    "explanation -> str": |
      One short sentence why.
    "dimension -> str": |
      The finding dimension: instruction or adequacy.

"parse_compliance_verdict(verdict_text: str) -> findings: list[ComplianceFinding]":
  location: models.py
  annotations: |
    Parse the raw answer of the compliance verdict request into findings — the strict single parsing point of the gate.

    `verdict_text`: the raw text answer of the verdict model.
    `findings`: the parsed findings; empty — compliant and adequate.

    Algorithm:
    1. Parse the trimmed text as a JSON list of objects; anything else — not valid JSON, not a list, a non-object item — is a malformed verdict
    2. Validate every item: instruction, priority of the {high, medium, low} set, explanation, dimension of the {instruction, adequacy} set — a missing field, an unknown priority label or an unknown dimension is a malformed verdict; an answer of the old shape — a finding without a dimension — is malformed, never a silent pass
    3. A malformed verdict raises `ComplianceVerdictError` carrying a fragment of the raw answer — a flaky verdict model surfaces loudly, never a silent pass
    4. Return the findings; an empty list means compliant and adequate

    Requirements:
    - Pure function: no state, no I/O, deterministic on the input text
    - No fence unwrapping and no protective fallback: the verdict answer parses as received (see `openai` and `anthropic`)

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The LLM port of prettyplay: one contract, the openai and anthropic SDK implementations in full parity — generation, classification and the two-dimension compliance verdict with identical user-instructions, cheat-sheet, step-type and attempt-history semantics — the failure classification verdict and the instruction-compliance and step-adequacy findings.
```

#### `.usages/` files

**File:** `prettyplay/llm/.usages/providers.md` (updated; `classification.md` unchanged)

````markdown
# Providers

Domain: LLM provider selection and parity. Audience: integrators choosing a provider and setting models.

## Select a provider

```python
from prettyplay.config import Config
from prettyplay.llm import create_provider

config = Config(provider="anthropic", model="claude-sonnet-4-5")
provider = create_provider(config)
````

The provider is a project setting: openai or anthropic; env override PRETTYPLAY_PROVIDER. API keys come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic.

## Models

| Setting | Purpose | Fallback |
|---|---|---|
| model | the main model for both operations | — |
| generation_model | code generation only | model |
| classification_model | failure classification only | model |

The instruction compliance gate runs on the effective generation model (generation_model
or model).

base_url overrides the provider endpoint when set.

## Parity

Both providers expose the same three operations — generate_step_code, classify_failure and check_instruction_compliance — with identical inputs, identical output shapes and the identical failure taxonomy: a provider service failure raises LLMUnavailableError; cached step code never depends on the provider. One request per attempt; attempt budgets belong to the calling engine.

User instructions parity: each operation carries its own instructions — generation requests render the generation_prompt setting, classification requests render the classification_prompt setting — as a verbatim USER INSTRUCTIONS block with identical placement semantics in both providers. A parity requirement, not a capability difference.

Step-type parity: every generation request and every compliance verdict request renders the STEP TYPE line — action or assertion — immediately before the STEP line, identically in both providers. A parity requirement, not a capability difference.

Attempt-history parity: a generation request may carry the attempt history of the step — attempt_history, a list of complete multi-line records composed by the calling engine (the attempt outcome, the URL before -> after line, the complete candidate code, the complete error; the original cached code anchors the list as record 0 when it exists). Non-empty — rendered as the HISTORY block after the USER INSTRUCTIONS block, every record verbatim, never collapsed, never size-limited; the block replaces the former CODE/ERROR request pair and the former steering-only history. The request tail order is fixed: HISTORY, RECOMMENDATION (the classification diagnosis), USER GUIDANCE (the engineer message of the interactive steering). Both providers render every non-empty block identically at the same position. A parity requirement, not a capability difference.

Page-URL parity: a generation request with a non-empty page URL renders it as its own PAGE URL line immediately after the PAGE SNAPSHOT block — identically in both providers. The URL reaches guided regeneration requests of the interactive steering only. A parity requirement, not a capability difference.

Cheat-sheet parity: every generation request renders the CHEAT SHEET block after the scenario inputs and
immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by the
calling engine; guidance, not an allowlist. Both providers render it identically at the same position.

## The compliance operation

check_instruction_compliance is the verdict request of the two-dimension gate — instruction
compliance and step adequacy judged in one request: the engine calls it once per successfully
executed candidate before caching — never for replayed cached code, never when generation_approve
is off or generation_prompt is empty (zero calls).

The request carries the gate system prompt and four blocks — INSTRUCTIONS, STEP (with its
STEP TYPE line), ATTEMPT HISTORY, CODE; the answer is a JSON list of findings:

[{"instruction": "...", "priority": "high", "explanation": "...", "dimension": "instruction"}]

- the dimension is instruction or adequacy: instruction findings quote the violated project
  instruction; adequacy findings quote the fragment of the step sentence the code fails to
  accomplish — judged from the step type and the attempt history
- the priority is high, medium or low; only high blocks the candidate, in either dimension —
  the calling engine owns that decision
- the model behind the call is the effective generation model (generation_model or model)
- a malformed answer — including an old-shaped finding without a dimension — raises
  ComplianceVerdictError and a provider failure raises LLMUnavailableError — both hard: the
  candidate is not cached unchecked

## Answer shape

generate_step_code returns step code of the fixed form. Models often answer with a fenced python block (```python … ```); the provider unwraps the first fenced block before returning, so the engine receives clean code either way — an answer with no closed fence is returned verbatim and, if unparsable, keeps failing downstream in execution.
```

---

### 2. Cell: `prettyplay/engine` (modified)

**Modification summary:** header Usages — `compliance_prompt` inline practice fully rewritten (two dimensions, STEP TYPE and ATTEMPT HISTORY inputs, dimension in the answer); global Annotations — add the verbatim-history, honest-inputs, URL-bracket, record-append and replayability rules; extend the gate rules to two dimensions. Body — add `StepAttempt` (`attempts.py`); `StepGenerator.generate`/`regenerate` gain `step_type` + `attempt_history` and the record/URL mechanics; `StepHealer.heal` gains `step_text`, `step_type`, `attempt_history`; `check_step_compliance` gains `step_type` + `attempt_history` and the two-dimension semantics. `format_step_error`, `run_step_code`, `classify_step_failure` — unchanged (the classification input description notes the raw sentence). Description updated.

#### CODEMANIFEST — `prettyplay/engine/CODEMANIFEST`

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
      - FailureClassification
      - ComplianceFinding
    Usages:
      - classification
    From: prettyplay/llm
  - Types:
      - SettleWindow
      - settle
    From: prettyplay/engine/polling

Usages:
  conventions: .goga/usages/conventions.md
  system_prompt: .goga/usages/prompts/generation.md
  cheat_sheet: .goga/usages/prompts/cheatsheet.md
  classification_prompt: |
    You classify a failure of a web UI test step.

    Input you receive:
    - STEP: the step sentence
    - CODE: the step code that failed
    - ERROR: the failure description
    - PAGE SNAPSHOT: the accessibility snapshot of the current page
    - SCREENSHOT: an image of the page, when attached
    - USER INSTRUCTIONS: the project's binding classification guidance, when configured — follow it; it never overrides the fixed answer format above

    Answer with exactly one line of the form:
    category | explanation | recommendation

    where category is one of:
    - rot — the UI changed (selectors, texts, structure) and the step can be regenerated for the same intent
    - product_defect — the step works as written but the expected behavior of the application is genuinely broken
    - fixable — the step code is at fault (an ambiguous or wrong locator or strategy) while the intent stays satisfiable; regeneration for the same intent can help
    - incurable — the step sentence no longer matches reality, the intent is ambiguous, or regeneration cannot help

    explanation: one short sentence why. recommendation: one short sentence what the engineer should do.
    Output only that single line — no code, no extra text.
  compliance_prompt: |
    You verify generated step code on two dimensions: the project's user instructions and what the step says.

    Input you receive:
    - INSTRUCTIONS: the project's user instructions, verbatim
    - STEP TYPE: action or assertion
    - STEP: the step sentence the code was generated for
    - ATTEMPT HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
    - CODE: the successfully executed candidate code

    Check the code on both dimensions and answer with exactly one JSON list of
    findings:
    [{"instruction": "<quote>", "priority": "high|medium|low",
    "explanation": "<one short sentence>", "dimension": "instruction|adequacy"}]

    Dimension calibration:
    - instruction — the code violates a project instruction: the quote is the
      violated instruction
    - adequacy — the code does not accomplish what the step says, given the step
      type and the attempt history: the quote is the fragment of the step sentence
      the code fails to accomplish

    Priority calibration:
    - high — a confident, material finding evident from the code, the step type
      and the attempt history; for adequacy: an action step whose code contains no
      action of the step — the page state the code relies on was produced by a
      prior attempt or manual intervention, not by the code itself; use the URL
      lines and the records of the history to see it; only high blocks the
      candidate
    - medium and low — minor observations, partial compliance or doubt: visible,
      never blocking; when in doubt, never high
    - an empty list [] means the code complies and accomplishes the step

    Rules:
    - The attempt history is your ground truth for what already happened on the
      page: the candidate ran on a page that may already contain effects of prior
      attempts or manual intervention — code that only checks an already-achieved
      state without producing it is an adequacy violation for an action step
    - Conditional prefer-type instructions are checked conditionally: when the code shows
      a graceful fallback attempt, that is compliance; judge followability from the code
      and the step sentence alone — never speculate about page state beyond the attempt
      history and the inputs
    - An instruction the code could not follow because the step sentence itself prevents
      it is not a violation; when the inputs leave the followability in doubt, the finding
      is never high
    - Judge both dimensions: the code against the instructions, and the code against the
      step sentence with its type
    - Output only the JSON list, no other text

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `cheat_sheet` from Usages as the single source of the standard Playwright API reference for generation requests — the listing and the practice change together; guidance, never an allowlist — everything standard stays allowed.
  Use `classification` from Imports for the healing decision categories.
  Use `system_prompt` as the system prompt of every code generation request.
  Use `classification_prompt` as the system prompt of every failure classification request.
  Use `compliance_prompt` as the system prompt of every compliance verdict request.

  The fixed form of step code: one function receiving exactly one argument — the genuine sync Page of the test; the function body works through the standard Playwright sync API; imports allowed from playwright.sync_api and the Python standard library only — third-party libraries are forbidden; imports are global only: at the top level of the code block, before def step, never inside the function body — a prompt rule carried by `system_prompt`, no runtime enforcement; the whole step executes inside the driver worker thread through the run primitive of `PageFacade` — the calling thread never touches Playwright.
  Every attempt — generation or healing — consumes the shared per-step budget of the test; exhaustion is the incurable failure, never an infinite loop.
  One continuous per-step attempt history threads through generation, healing and steering: every step-code request of the engines carries it verbatim — every record complete (the outcome, the URL before -> after line, the complete candidate code, the complete error); the original cached code anchors it as record 0 when it exists; the history is bounded by the attempt budgets alone — no collapsing, no truncation, no size limits.
  Honest inputs in every step request: the step type — action or assertion — and the raw step sentence as written by the engineer reach every generation, regeneration and gate request of the engines; the casefolded normalization stays an addressing key, never a request input; the heal path forwards the raw sentence passed by the executor.
  Every attempt record carries the mechanical URL pair read from the page immediately before and after the attempt's execution — settle re-executions inside one attempt are covered by the single pair; an engineer-rejected turn carries the same URL on both sides.
  A record is appended after every attempt that does not produce a cached step — a failed execution, a failed check, a gate-blocked candidate (the violation text in the error field) — with the closed outcome label set of `StepAttempt`.
  The replayability requirement lands in `system_prompt` and its frozen mirror: the current page state may include effects of prior attempts or manual intervention — the generated code must produce the step outcome itself, never rely on the current state.
  Healing never masks a product defect: a classified product_defect fails the test loudly; a healed step is reported loudly and written back to the cache.
  Every terminal failure carries a verdict — a `FailureVerdict` of category, explanation, recommendation — fully present in the exception message, the verdict hook event and the log; an unavailable LLM skips the verdict quietly with a WARNING, the failure itself is never delayed or distorted — the quiet skip applies to verdicts enriching an already-decided failure; the classification driving the healing decision surfaces as the infrastructure failure.
  A failed check of a candidate stops the generation-budget retries: a check that executed and did not hold is classified first; a rot or fixable verdict grants exactly one healing-funded regeneration, a repeat failure gets the final terminal-kind classification — the attempt budget is never spent on a legitimately failing assertion beyond it.
  The cheat-sheet sent to the provider mirrors `cheat_sheet` from Usages exactly — the listing and the practice change together.
  The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.
  The user instructions of the project settings reach their own requests only: the generation_prompt field of `Config` reaches generation and regeneration requests and the compliance verdict request — there as the checked INSTRUCTIONS block, never as guidance; the classification_prompt field reaches classification requests; neither crosses to the other kind; the instructions take no part in the step address: a cached step never regenerates because the instructions changed.
  The instruction compliance gate runs inside the engines and judges two dimensions in one request — instruction compliance and step adequacy, the latter from the step type and the attempt history: every successfully executed candidate — generation, healing and steering alike — passes `check_step_compliance` before it is cached; the gate never runs on replayed cached code.
  An unfollowed instruction and an inadequate candidate surface as a generation error, never as silent ignoring: a high finding of either dimension fails the attempt and the retry carries the finding in the attempt record's error field.
  The terminal failures raised by the engines carry the full underlying error of the failed code in the error field; reason and message texts are authored without colons — the first line of the rendered message carries the terminal failure's class name and the authored reason.
  The uniform decision table on every classification point: product_defect raises ProductDefectError — never healed; rot and fixable regenerate carrying the classification recommendation; incurable raises IncurableStepError carrying the verdict. The category decides, the path only delivers.
  Polling runs before every costly move: every execution of step code — cached code and candidates alike — runs under the settle window threaded through the calling paths; per-attempt classification inside the loops is rejected (LLM cost): an attempt failure retries with the fresh error and snapshot plus the grown attempt history while budget remains.
  on_generation_started fires once per LLM attempt regardless of the settle re-executions inside it; the raised IncurableStepError carries the failed step code in the code field.

---

"StepAttempt(code: str, error: str, outcome: str, url_before: str, url_after: str)":
  location: attempts.py
  annotations: |
    One verbatim record of the per-step attempt history — the unit the provider HISTORY block and the gate ATTEMPT HISTORY block render.

    `code`: the complete candidate code of the attempt, verbatim.
    `error`: the complete failure text of the attempt — the execution error, the failed check text, or the gate violation text; empty on no error.
    `outcome`: the closed label set of five labels:
    - original cached code — record 0, the anchored cached code and the error of its failed replay
    - failed check
    - execution failed
    - compliance blocked — executed green, blocked by the gate
    - rejected by the engineer, not executed — interactive steering
    `url_before`: the page URL read immediately before the attempt's execution.
    `url_after`: the page URL read immediately after the attempt's execution.

    Requirements:
    - pydantic v2, kw_only, empty defaults (see `conventions`)
    - A record is immutable once appended: no rewriting, no truncation
  properties:
    "code -> str": |
      The complete candidate code of the attempt.
    "error -> str": |
      The complete failure text of the attempt; empty means no error.
    "outcome -> str": |
      The outcome label of the closed set.
    "url_before -> str": |
      The page URL read immediately before the attempt's execution.
    "url_after -> str": |
      The page URL read immediately after the attempt's execution.
  methods:
    "render() -> record: str": |
      Render the complete verbatim record text — the unit the provider HISTORY block renders.

      `record`: the multi-line record text.

      Algorithm:
      1. The outcome line — the label of `outcome`
      2. The URL line — `url_before`, an arrow, `url_after`
      3. The complete `code`
      4. A non-empty `error` renders the complete error text; empty — no error part

      Requirements:
      - No collapsing, no size limits, no truncation of any field

"StepGenerator(config: Config, provider: LLMProvider, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: generator.py
  annotations: |
    The generation engine: produce working step code for an unknown step, executing candidates against the live page and growing the per-step attempt history.

    `config`: project settings — the screenshot flag, the generation instructions and the compliance gate switch.
    `provider`: the LLM port.
    `cache`: the step cache — a generated step is stored on success.
    `budgets`: the per-test attempt registry.
    `reporter`: the visibility point.
  methods:
    "generate(identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[str], page: PageFacade, attempt_history: list[StepAttempt], window: SettleWindow) -> step: CachedStep": |
      Generate and store a new step.

      `step_text`: the raw sentence of the step — carried into every request verbatim.
      `step_type`: action or assertion — carried into every request.
      `attempt_history`: the per-step attempt history created by the executor — this loop appends a record after every attempt that does not produce a cached step.

      Algorithm:
      1. Ask the budgets registry try_generation for the step identity; a refused attempt is the incurable failure
      2. Collect the request inputs: the page accessibility snapshot, the raw step sentence, `step_type`, `previous_steps`, and the cheat-sheet from `cheat_sheet`; add the page screenshot when the project settings enable screenshots
      3. Request step code from the provider port generate_step_code passing `system_prompt` as the system prompt, the cheat-sheet taken from `cheat_sheet`, the user instructions — the effective config generation_prompt — when non-empty, the rendered `attempt_history` and page_url None — the URL input is steering-only, uniform with guidance None
      4. Read the page URL, execute the candidate under the settle window: `settle` with run_step_code, the candidate code, `page` and `window` — transient failures re-execute inside the window, no LLM budget consumed; read the page URL again — the pair brackets the whole attempt
      5. On success: gate the candidate through `check_step_compliance` with the step type and the grown history. An empty findings list — build `CachedStep`, save it to the cache, return it. A high finding of either dimension — the attempt is failed: append the attempt record (outcome compliance blocked, the finding instruction and explanation in the error field); the retry carries the grown history — the model fixes the violation targeted. Medium and low findings pass with a WARNING naming the instructions, then the step is stored and returned. The gate hard failures — provider unavailability and a malformed verdict — propagate immediately: nothing is cached
      6. On a failed check — an AssertionError that survived the settle window: append the attempt record (outcome failed check, the full failure description); classify via `classify_step_failure`; a product_defect verdict raises `ProductDefectError` carrying the verdict and the full failure description of the candidate in the error field; an incurable verdict raises `IncurableStepError` carrying them; a rot or fixable verdict grants exactly one regeneration: try_healing funds it — a refused funding leaves the failure terminal `IncurableStepError` carrying the verdict, the reason naming the exhausted healing pool; the request carries the classification recommendation and the grown history — a success stores and returns the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect raises `ProductDefectError`, anything else raises `IncurableStepError` — no further regeneration; provider unavailability at these classifications is skipped quietly with a WARNING — the failure raises without a verdict as IncurableStepError, the conservative default uniform with the unrecognized-label fallback, the reason naming the failed candidate check
      7. On any other candidate failure: append the attempt record (outcome execution failed, the full failure description), repeat from step 1 with the fresh snapshot and the grown history, while attempts remain
      8. On budget exhaustion: classify the last candidate via `classify_step_failure`; a rot or fixable verdict grants exactly one extra regeneration funded by try_healing and carrying the recommendation and the grown history — a refused funding leaves the failure terminal `IncurableStepError` carrying the verdict, the reason naming the exhausted healing pool; a repeat failure is terminal `IncurableStepError` carrying the verdict, no reclassification; a product_defect verdict raises `ProductDefectError` carrying the verdict and the last candidate failure in the error field; an incurable verdict raises `IncurableStepError` carrying them — the reason names the exhausted pool; provider unavailability at this classification is skipped quietly with a WARNING, the failure raises without a verdict; budget exhaustion with a standing high finding raises
      `IncurableStepError` carrying the verdict that names the violated instruction or the unaccomplished step —
      the reason names the exhausted pool and the finding (colon-free), the finding text rides the error field; the verdict is built from the standing
      high finding: category incurable, explanation — the finding instruction and its
      explanation, recommendation — restating to satisfy the finding in the step code
      9. Report on_generation_started for every LLM attempt

      Requirements:
      - Every generation request carries the cheat-sheet taken from `cheat_sheet` from Usages: the model always sees the standard-API reference — guidance, never an allowlist
      - Every generation request carries the raw step sentence, the step type and the rendered attempt history — the record list grows by one after every attempt that does not produce a cached step
      - Provider unavailability of a generation request surfaces as `LLMUnavailableError` immediately — no retry on it
      - Provider unavailability of a classification is skipped quietly with a WARNING: the failure raises without a verdict — the failed check itself is the primary signal
      - Exactly one failed check drives the bounded healing rule; the attempt budget is never spent on a legitimately failing assertion beyond it
      - A verdict requested on this path fully reaches the raised error
      - Every verdict-preceded regeneration request carries the classification recommendation — regeneration starts from the diagnosis, not the raw error
      - The raised IncurableStepError carries the failed step code in the code field
      - The retry request after a blocking finding carries the grown history — the violation text rides the record's error field, the model fixes the finding targeted
      - Medium and low compliance findings pass with a visible WARNING through the
        library logger — structured, naming the step and the findings
      - The compliance gate itself consumes no attempt budget; only a blocking
        finding consumes the attempt it fails
    "regenerate(identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[str], page: PageFacade, attempt_history: list[StepAttempt], recommendation: str, window: SettleWindow) -> step: CachedStep": |
      Regenerate a failed step for healing.

      `step_text`: the raw sentence of the step — carried into every request verbatim, never the casefolded normalization.
      `step_type`: action or assertion — carried into every request.
      `attempt_history`: the anchored per-step attempt history — record 0 carries the original cached code composed by the caller; this loop appends after every attempt that does not produce a cached step; the original is never lost to a re-binding.
      `recommendation`: the diagnosis of the classification that launched the healing; non-empty — rendered into every request as the RECOMMENDATION block.
      `window`: the settle window of the current step execution.

      Algorithm:
      1. The same loop as the generate method with four differences: every provider request carries `step_type`, the raw `step_text` and the rendered `attempt_history` plus the user instructions — the effective config generation_prompt — when non-empty; attempts consume the healing budget via try_healing; candidate executions run under `settle` with `window`, the URL pair bracketing each attempt; a failed attempt of any kind — a failed check included — appends its record and retries with the fresh failure description, the fresh snapshot and the grown history while attempts remain: no per-attempt classification inside the loop (rejected: LLM cost), the entry classification already guards the anti-masking; every successfully executed candidate is gated through `check_step_compliance`
      before storing — the same two-dimension semantics as generate
      2. A budget exhaustion raises `IncurableStepError` without an extra classification — the verdict of the entry classification is carried, the reason names the exhausted pool

      Requirements:
      - The retry request after a blocking finding carries the grown history — the violation text rides the record's error field, the model fixes the finding targeted
      - Medium and low compliance findings pass with a visible WARNING through the
        library logger — structured, naming the step and the findings
      - The compliance gate itself consumes no attempt budget; only a blocking
        finding consumes the attempt it fails

"format_step_error(exc: Exception) -> text: str":
  location: text.py
  annotations: |
    Format the full failure text of a step-code exception — the single error-text policy shared by the engines and the executor.

    `exc`: the exception raised by the failed step or candidate branch.
    `text`: the formatted failure text carried by reports, renders and requests.

    Requirements:
    - A failed check — an AssertionError — yields its message verbatim with no prefix: the exception type already carries the assertion semantics; a message-less check yields an empty text, so the structured render omits the error line
    - Any other failure carries its type name: the action failures of step code are timeouts and driver errors whose bare messages lose the kind of failure
    - A message-less error yields the bare type name, never a dangling separator

"run_step_code(code: str, page: PageFacade)":
  location: execution.py
  annotations: |
    Execute step code of the fixed form: compile and resolve on the calling thread, run the
    whole step inside the driver worker thread against the genuine sync Page.

    `code`: the step code text.
    `page`: the page handle of the current test — the carrier of the worker boundary.

    Algorithm:
    1. Compile and load `code` as a module in an isolated namespace — on the calling thread, Playwright untouched
    2. Resolve the step function of the fixed form — the single callable receiving the page
    3. Execute the whole step-function call inside the driver worker thread as one unit through the run primitive of `page` — the step function receives the genuine sync Page and works through the standard Playwright sync API
    4. An exception raised by the step code propagates to the caller as-is

    Requirements:
    - A failure inside the step code reaches the caller untouched: the engine classifies it, this routine never swallows, translates or retries
    - Executing step code loads no LLM provider and touches no network beyond the page itself
    - The calling thread never touches Playwright: the worker boundary is crossed only by the run primitive

    Constraints:
    - Execute only step code produced by generation or loaded from the cache — never arbitrary file content

"classify_step_failure(config: Config, provider: LLMProvider, step_text: str, code: str, error: str, page: PageFacade) -> classification: FailureClassification":
  location: classification.py
  annotations: |
    Classify a step failure: collect the page state and ask the provider — the single classification call for both engines.

    `config`: project settings — the screenshot flag and the classification instructions.
    `provider`: the LLM port.
    `step_text`: the raw sentence of the failed step as passed by the calling engine.
    `code`: the step code that failed.
    `error`: the human-readable failure description.
    `page`: the page facade of the current test.
    `classification`: the `FailureClassification` verdict.

    Algorithm:
    1. Collect the classification inputs: the step sentence, the failed code, the `error` text, the fresh page snapshot — plus the screenshot when enabled
    2. Ask the provider port classify_failure passing `classification_prompt` as the system prompt and the user instructions — the effective config classification_prompt — when non-empty
    3. Return the verdict

    Constraints:
    - Provider unavailability propagates to the caller: this routine never swallows it — the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip

"check_step_compliance(config: Config, provider: LLMProvider, step_text: str, step_type: str, code: str, attempt_history: list[StepAttempt]) -> findings: list[ComplianceFinding]":
  location: compliance.py
  annotations: |
    Gate a successfully executed candidate on two dimensions — instruction compliance and step adequacy — the
    single gate of every caching path.

    `config`: project settings — the gate switch and the generation instructions.
    `provider`: the LLM port.
    `step_text`: the raw sentence of the generated step.
    `step_type`: action or assertion — the adequacy dimension judges by it.
    `code`: the successfully executed candidate code.
    `attempt_history`: the step's attempt history — rendered through the record render and passed to the verdict request as the ATTEMPT HISTORY block.
    `findings`: the verdict findings of both dimensions; empty — compliant and adequate, or the gate is off.

    Algorithm:
    1. The generation_approve setting is off or the generation_prompt setting is empty —
       return an empty list with zero provider calls: fully the old behavior
    2. Ask the provider port check_instruction_compliance passing `compliance_prompt` as
       the system prompt, the effective config generation_prompt as the user
       instructions, `step_text`, `step_type`, `code` and the rendered `attempt_history`
    3. Return the findings

    Requirements:
    - Never called for replayed cached code — the gate checks candidates before caching
    - A high finding of either dimension blocks: the calling loop turns it into the failed
      attempt — the finding text rides the attempt record's error field
    - Provider unavailability and a malformed verdict propagate to the caller as the
      hard failures they are: this routine never swallows, the calling path never caches

    Constraints:
    - No attempt budget is consumed here — budgets belong to the calling loops

"StepHealer(config: Config, provider: LLMProvider, generator: StepGenerator, cache: StepCache, budgets: RunBudgets, reporter: StepReporter)":
  location: healer.py
  annotations: |
    The healing engine: classify a failed cached step, regenerate rot, never mask a defect.

    `config`: project settings — the screenshot flag.
    `provider`: the LLM port for classification.
    `generator`: the regeneration engine.
    `cache`: the step cache for the healed write-back.
    `budgets`: the per-test attempt registry.
    `reporter`: the visibility point.
  methods:
    "heal(step: CachedStep, error: str, step_text: str, step_type: str, previous_steps: list[str], page: PageFacade, attempt_history: list[StepAttempt], window: SettleWindow) -> step: CachedStep": |
      Classify and heal a failed cached step.

      `error`: the full failure description of the cached replay — carried by record 0.
      `step_text`: the raw sentence of the step as passed by the executor — forwarded into the classification and every regeneration request verbatim, never the casefolded normalization.
      `step_type`: action or assertion — forwarded into every regeneration request.
      `previous_steps`: the sentences of the previous steps of the test, in execution order — scenario context for regeneration.
      `attempt_history`: the anchored per-step attempt history — record 0 carries the original cached code seeded by the executor; threaded into the regeneration loop which appends every further attempt.
      `window`: the settle window of the current step execution.

      Algorithm:
      1. Classify the failure via `classify_step_failure` passing the raw `step_text` — the verdict is a `FailureClassification`
      2. Report on_healing_started with the category
      3. product_defect: raise `ProductDefectError` carrying the verdict built from the classification and the full underlying error in the error field — the message states what was expected against what was observed; the recommendation reaches the error through the verdict
      4. incurable: raise `IncurableStepError` carrying the verdict and the full underlying error in the error field; the reason names the classification explanation of incurability
      5. rot and fixable: regenerate via the generator regenerate — the request carries the raw `step_text`, `step_type`, the classification recommendation and the anchored `attempt_history`, the loop executes the candidate under the settle window and stores the healed step on success; report on_healed with the explanation of what failed and what changed, return the healed step
      6. A regeneration budget exhaustion inside step 5 surfaces as `IncurableStepError` carrying the verdict of the step 1 classification — the reason names the exhausted pool; no extra LLM request is made
      7. Provider unavailability of the classification surfaces as `LLMUnavailableError` — an explicit infrastructure failure

      Requirements:
      - Anti-masking: healing may only turn a rot- or fixable-failed step green; a classified product defect always fails the test
      - The healed code replaces the cached code only after a successful execution
      - Every verdict produced on the paths of this method fully reaches the raised error; the raised IncurableStepError carries the failed step code in the code field

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The agent engine of prettyplay: step code generation against the standard Playwright API with execution in the loop, one continuous verbatim per-step attempt history, honest request inputs (the step type and the raw step sentence) and failed-check classification, the fixed-form execution routine running the whole step inside the driver worker thread, the two-dimension instruction compliance and step adequacy gate before caching, the shared classification call carrying the classification user instructions, the error-text policy shared with the executor, and healing with anti-masking and verdicts on terminal failures.
```

#### `.usages/` files

**File:** `prettyplay/engine/.usages/generation.md` (updated)

````markdown
# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="click the «Sign in» button",
    step_type="action",
    previous_steps=["open the login page", "enter the login and password"],
    page=page,
    attempt_history=history,
    window=window,
)
````

- The loop: request code → execute against the live page → append the full attempt record → on failure re-request with the fresh snapshot and the grown history
- The attempt history is one continuous verbatim list: every record carries the outcome, the `URL before -> after` line, the complete candidate code and the complete error; no collapsing, no size limits — the attempt budgets are the only bound
- Every request carries the honest inputs: the step type (action or assertion) and the raw step sentence as written by the engineer — never the casefolded normalization
- The page may carry side effects of failed candidates and manual intervention — the replayability requirement of the system prompt tells the model the code must produce the step outcome itself
- Every candidate execution runs under the settle window: transient failures re-execute the same code inside the window (settle_retry log records), no LLM budget consumed; deterministic failures go to the next request or classification; the URL pair brackets the whole attempt, settle re-executions included
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request; classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only; generation requests never carry it
- Every generation and regeneration request carries the CHEAT SHEET block right before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference carried by every request; guidance, not an allowlist: everything standard stays allowed, the error-driven regeneration loop is the second line of defense

## The execution boundary

The whole step executes inside the driver worker thread as one unit: compile and resolve stay on the calling thread,
the step call itself runs in the worker and receives the genuine sync Page — the calling thread never touches
Playwright, so interactive hosts keep working. An AssertionError of a step — a failed expect chain or a plain assert
on an immediate read — reaches failure classification untouched.

## The decision table

Every classification verdict drives the same table — the category decides, the path only delivers:

| Verdict | Action |
|---|---|
| product_defect | ProductDefectError carrying the verdict — loud, never healed |
| rot, fixable | regeneration carrying the classification recommendation |
| incurable | IncurableStepError carrying the verdict |

## Failed candidate check (bounded healing)

A failed check — an assertion that executed and did not hold, survived the settle window — appends its attempt
record, then is classified:

- product_defect → ProductDefectError with the verdict; one failed check is spent, never the whole budget
- rot or fixable → exactly one regeneration funded from the healing budget, the request carrying the recommendation as a RECOMMENDATION block and the grown history; success stores the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect → ProductDefectError, anything else → IncurableStepError; no further regeneration
- incurable → IncurableStepError with the verdict
- LLM unavailable at the classification → the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it

## The instruction compliance gate

Every successfully executed candidate is verified on two dimensions before it is cached —
instruction compliance and step adequacy — the default behavior; switch it off with
generation_approve = false:

- one verdict request per candidate through the provider (the effective generation
  model); zero requests when the switch is off or the instructions are empty
- the request carries INSTRUCTIONS, STEP with its STEP TYPE line, the ATTEMPT HISTORY
  records and the CODE block; the reviewer is instructed to use the attempt history as
  the ground truth of what already happened on the page
- a high finding of either dimension fails the attempt: the record lands in the history
  with the violation text in its error field, the retry carries the grown history — the
  model fixes the finding targeted; budget exhaustion with a standing high finding is the
  terminal incurable failure naming the violated instruction or the unaccomplished step
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) and provider unavailability
  (LLMUnavailableError) are hard failures — a candidate is never cached unchecked
- replayed cached code is never re-gated: changing the instructions does not invalidate
  the cache — purge it manually when the instructions change

## Budget exhaustion

Exhaustion of the generation attempts classifies the last candidate: rot or fixable grants exactly one extra
recommendation-carrying regeneration funded from the healing budget — a repeat failure is terminal
IncurableStepError without reclassification; any other verdict is terminal as before. LLM unavailability at this
classification skips the verdict quietly.

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config,
    provider=provider,
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. The step sentence is the raw sentence passed by the caller — the casefolded normalization is an addressing key only. The category set is four: rot, product_defect, fixable, incurable. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the genuine sync Playwright Page — importing from
playwright.sync_api and the Python standard library only (third-party libraries forbidden; imports global only, at
the top level of the code block, before `def step`, never inside the function body) and working through the standard API: `page.get_by_role("button", name="Sign in").click()`,
`page.locator("form > button.primary")`, `videos = page.get_by_role("listitem")` with
`expect(videos.first).to_be_visible()` and `assert videos.count() > 1`,
`with page.expect_event("dialog") as info: ... info.value.accept()`,
`with page.expect_popup() as popup_info: ... popup_info.value`,
`page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`,
`locator.scroll_into_view_if_needed()`, `page.mouse.wheel(0, 600)`. No provider constructs, no fixed delays, no
page.close()/context.close(), no stateful actions (route, clock, add_init_script, tracing, HAR, CDP) — the prompt
rules; the runtime never enforces them.
```

**File:** `prettyplay/engine/.usages/healing.md` (updated)

````markdown
# Step healing

Domain: healing a failed cached step. Audience: library internals and engineers reasoning about healed runs.

## Heal

```python
healed = healer.heal(
    step=failed_step,
    error="element not found: button «Sign in»",
    step_text="click the «Sign in» button",
    step_type="action",
    previous_steps=["open the login page"],
    page=page,
    attempt_history=history,
    window=window,
)
````

The executor seeds record 0 of `attempt_history` before the delegation — the original cached code, the full replay
error and the URL pair of the replay — so regeneration never loses the original: the history carries every record,
the anchored cached code first. The raw `step_text` and the step type ride every classification and regeneration
request — the casefolded normalization is an addressing key only.

The classification verdict decides the path — the uniform decision table:

| Category | Path |
|---|---|
| rot, fixable | regenerate from the current page within the healing budget (default 2), the request carrying the classification recommendation as a RECOMMENDATION block and the grown attempt history; execute under the settle window, save back to the cache on success, report loudly |
| product_defect | raise ProductDefectError carrying the verdict — explanation and recommendation reach the exception message and the log, all three fields reach the on_step_verdict hook (the category never renders) |
| incurable | raise IncurableStepError carrying the verdict; the reason names the incurability cause |

## Rules

- A healed candidate passes the two-dimension compliance gate before the write-back: a high
  finding of either dimension fails the healing attempt — the record lands in the history
  with the violation text in its error field; medium and low findings pass with a WARNING;
  a malformed verdict or provider unavailability is a hard failure — nothing is cached
  unchecked
- Anti-masking: healing never turns a product defect into a green test
- The healed code replaces the cached code only after a successful execution
- Generation and healing attempts live in one per-test registry — owned by the runtime of the test — with separate per-step limits (default 3 and 2)
- Inside the regeneration loop no per-attempt classification happens (rejected: LLM cost): a failed attempt of any kind — a failed check included — appends its record and retries with the fresh error, the fresh snapshot and the grown history while budget remains; the entry classification guards the anti-masking
- A regeneration budget exhaustion raises IncurableStepError carrying the verdict of the original classification — no extra LLM request
- Provider unavailability during the classification raises LLMUnavailableError — an explicit infrastructure failure
- Healing never runs in strict mode: a failed cached step is at most classified, never regenerated
- Interactive steering attempts are separate from healing: they consume no budgets, join the same per-step history and report their own healings

## Verdicts

Every terminal failure carries its verdict in full and the full underlying error in the error field: the exception
message is the structured render — the first line carries the class name of the terminal failure and the authored
reason, then the `---` separated step/error section, the conditional received/cause/Call log details section and the
unpadded verdict block; the same text reaches on_step_verdict (structured fields) and the log record. IncurableStepError
also carries the failed step code in the code field — a programmatic field, never rendered.
```

---

### 3. Cell: `prettyplay/engine/steering` (modified)

**Modification summary:** Imports — add `StepAttempt` from `prettyplay/engine`. Global Annotations — replace the dialog-local history rules with the shared-history rule; add the honest-inputs rule; extend the write-back gate rule to two dimensions. `StepSteering.steer` — add `step_text`, `step_type`, `attempt_history`; the request renders the HISTORY block (replacing existing_code/error/guidance_history); per-turn records with URL pairs; the gate consumes the honest inputs. Description updated.

#### CODEMANIFEST — `prettyplay/engine/steering/CODEMANIFEST`

```yaml
Imports:
  - Types:
      - IncurableStepError
    From: prettyplay/failures
  - Types:
      - Config
    From: prettyplay/config
  - Types:
      - LLMProvider
    From: prettyplay/llm
  - Types:
      - StepCache
      - CachedStep
      - StepIdentity
    From: prettyplay/cache
  - Types:
      - StepReporter
    From: prettyplay/reporting
  - Types:
      - PageFacade
    From: prettyplay/driver
  - Types:
      - run_step_code
      - check_step_compliance
      - StepAttempt
    From: prettyplay/engine

Usages:
  conventions: .goga/usages/conventions.md
  system_prompt: .goga/usages/prompts/generation.md
  cheat_sheet: .goga/usages/prompts/cheatsheet.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `system_prompt` as the system prompt of every guided regeneration request.
  Use `cheat_sheet` from Usages as the single source of the standard Playwright API reference for regeneration requests — the listing and the practice change together; guidance, never an allowlist.
  The system prompt sent to the provider is the frozen local mirror of `system_prompt` — the mirror and the practice change together.
  The cheat-sheet sent to the provider mirrors `cheat_sheet` from Usages exactly — the listing and the practice change together.

  The opt-in human-in-the-loop escape hatch of a terminally stuck step: opened by the step executor exactly at the moment an IncurableStepError would propagate — never on product_defect, never in replay-strict, never when the LLM is unavailable.
  The dialog joins the one shared per-step attempt history passed by the executor — the same record list the engine loops grew; the history no longer dies with the dialog. Every completed turn lands as a full record: the outcome label, the URL before -> after pair of the turn (identical on both sides when the engineer rejected the candidate without execution), the complete generated code, the complete outcome text — the full error or the compliance-violation text; no line-collapsing, no size limits, no truncation.
  Every guidance turn is a regeneration request carrying the honest inputs — the step type and the raw step sentence passed by the executor — plus the grown attempt history in place of the former dialog-local turn history; record 0 anchors the original failure the engineer guidance refers to; the complete generated code is shown to the engineer before any execution and confirmed with the run? [y/N] prompt — nothing runs unseen; y executes against the live page, n, Enter or quit aborts the turn without execution; every executed turn has a measurable green or red outcome; no free-form conversation.
  An engineer-rejected candidate enters the shared history as a completed turn with the outcome rejected by the engineer, not executed — the model never re-proposes it blind.
  The current page URL joins every guided regeneration request (its own line beside the page snapshot) and the dialog banner — the banner only, never per turn; the banner carries the step, the failed code, the terminal error render, the URL, the screenshot path and the commands — never a snapshot fragment; the full snapshot stays behind the snapshot command and in the request.
  Interactive attempts consume no generation or healing budgets — the human in the loop is the bound; the settle window never re-arms inside the dialog: a failed execution returns to the guidance prompt immediately.
  The guidance is one-shot: logged, never persisted. Nothing hangs: quit, EOF, SIGINT and an unreadable stdin end the dialog and the original terminal failure propagates.
  The instruction compliance gate guards the write-back on both dimensions — instruction compliance and step adequacy: every successfully executed guided candidate passes `check_step_compliance` with the step type and the shared attempt history before it is saved — the same gate as the generation paths; the gate never runs on replayed cached code; a high finding of either dimension never reaches the cache.

---

"StepSteering(config: Config, provider: LLMProvider, cache: StepCache, reporter: StepReporter | None)":
  location: steering.py
  annotations: |
    The interactive steering dialog of a terminally stuck step: show the full failure context, take engineer guidance, regenerate with it, execute against the live page, heal or decline.

    `config`: the effective settings of the test — the generation instructions of the config join every request.
    `provider`: the LLM port for guided regeneration requests.
    `cache`: the step cache for the healed write-back.
    `reporter`: the visibility point — the healed step is reported loudly; omitted — the hook-less default reporter.
  methods:
    "steer(failure: IncurableStepError, identity: StepIdentity, step_text: str, step_type: str, previous_steps: list[str], page: PageFacade, attempt_history: list[StepAttempt]) -> healed: CachedStep | None": |
      Run the steering dialog over a terminal failure.

      `failure`: the terminal failure about to propagate — the source of the failed code, the underlying error and the verdict.
      `identity`: the address of the stuck step — the healed step is written back under it.
      `step_text`: the raw sentence of the stuck step as written by the engineer — carried into every guided request verbatim.
      `step_type`: action or assertion — carried into every guided request and the gate verdict.
      `previous_steps`: the sentences of the previous steps of the test — scenario context for regeneration.
      `page`: the live page facade of the test.
      `attempt_history`: the shared per-step attempt history grown by the engine loops and anchored by record 0 — the dialog appends every completed turn to it.
      `healed`: the healed cached step on a successful guided execution; None — the dialog declined or died: the caller propagates the original failure.

      Algorithm:
      1. Render the context banner once: the step sentence, the failed code, the terminal error render of `failure`, the current URL read from `page`, a screenshot path, the commands — no snapshot fragment
      2. Read the guidance line; quit, EOF, SIGINT or an unreadable stdin — return None
      3. A local command runs without the LLM: snapshot — the full accessibility snapshot; screenshot — a full PNG written to a temporary file with the path printed; error and code — the stored texts; back to step 2
      4. A guidance message builds one regeneration request via the provider: `system_prompt` as the system prompt, the cheat-sheet from `cheat_sheet`, the raw `step_text` with `step_type` and `previous_steps` as the scenario context, the fresh accessibility snapshot plus the screenshot when the project settings enable screenshots, the current URL read from `page` as the page URL input, the user instructions — the effective config generation_prompt — when non-empty, the message as the guidance and the rendered `attempt_history` as the HISTORY block — every record verbatim, the anchored original first
      5. Show the complete generated code to the engineer, then the confirmation prompt run? [y/N]: y — proceed to step 6; n, Enter or quit — the turn is aborted without execution, the rejected candidate enters `attempt_history` as a completed record with the outcome rejected by the engineer, not executed, and the same URL on both sides, back to step 2
      6. Read the page URL, execute the candidate via `run_step_code` against `page` — the whole step runs inside the driver worker thread; the settle window never re-arms inside the dialog; read the page URL again — the pair brackets the turn
      7. Success: gate the executed candidate through `check_step_compliance` with `step_text`, `step_type` and `attempt_history` — the gate switch off or empty generation instructions yield an empty findings list with zero provider calls. An empty findings list: build `CachedStep` with `identity`, save it to the cache, report on_healed with an explanation naming the interactive healing, return the healed step. A high finding of either dimension: no write-back — show the violation in the dialog (the finding instruction and explanation), append the completed record — outcome compliance blocked, complete code, complete violation text — to `attempt_history`, return to step 2. Medium and low findings pass with a WARNING naming the instructions, then the write-back. The gate hard failures — provider unavailability and a malformed verdict — end the dialog after showing the gate failure line in the dialog and logging a WARNING through the library logger naming the step and the gate failure: return None, the original terminal failure propagates; nothing is cached
      8. A failed execution: show the complete error, append the completed record to `attempt_history` — outcome failed check for an AssertionError, execution failed otherwise, complete code, complete outcome — return to step 2 — no re-execution of the same code, the settle window never re-arms
      9. Provider unavailability of the request: the dialog ends, return None

      Requirements:
      - The write-back happens only after a successful execution and a passed two-dimension gate
      - No code executes without the engineer approval of this turn
      - A rejected, failed or gate-blocked turn always enters the shared history before the guidance prompt reopens
      - No generation or healing budget is consumed; no polling applies
      - The dialog never outlives the failure: every exit path either heals or returns None

      Constraints:
      - Never persist the guidance into the cache file
      - Never introduce history size limits or line collapsing; never truncate a record

---

Author: Goga
CreatedAt: 12/09/26
Description: |
  The interactive steering of prettyplay: the opt-in terminal REPL taking engineer guidance over a terminally stuck step — guided regeneration against the standard Playwright API with the shared per-step attempt history and honest inputs, live execution inside the driver worker thread, the two-dimension compliance-gated healed write-back or honest decline.
```

#### `.usages/` files

**File:** `prettyplay/engine/steering/.usages/steering.md` (updated)

````markdown
# Interactive steering

Domain: the opt-in REPL that rescues a terminally stuck step with engineer guidance. Audience: engineers running generation sessions locally.

## When the dialog opens

The step executor opens the dialog at the exact moment an `IncurableStepError` would propagate — budget exhausted,
incurable verdict, failed-check final classification — when `interactive` is on and the run is not strict. It never
opens on `product_defect` (a dialog must never repaint a red test green), never in replay-strict, and never when the
LLM is unavailable. The dialog receives the per-step attempt history the engine loops grew — anchored by record 0,
the original cached code — and continues growing it; the history survives the dialog.

## The dialog

```text
── step "click Checkout" — about to raise IncurableStepError ──────────
code:     videos = page.get_by_role("listitem")
          expect(videos.first).to_be_visible()
          assert videos.count() > 1
error:    IncurableStepError: the generation budget is exhausted
          ---
          step: click Checkout
          error: TimeoutError: Timeout 10000ms exceeded
          ---
          received: … / cause: … / Call log: …
          ---
          explanation: the button is behind the "Terms" modal
          recommendation: dismiss the modal first, then click
url:      https://shop.example.com/cart
shot:     /tmp/prettyplay-steering-abc123.png

commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE — the complete candidate code is printed
run? [y/N] y
✓ step green — healed step written to the cache
````

- The banner shows the step, the failed code, the terminal error render, the current page
  URL, the screenshot path and the commands — no snapshot fragment; the full snapshot
  stays behind the `snapshot` command and in every request
- Local commands answer without the LLM: `snapshot` prints the full accessibility snapshot,
  `screenshot` writes a full PNG to a temporary file and prints the path, `error` and `code`
  reprint the stored texts
- Every other line is guidance: one regeneration request carrying the step type, the raw
  step sentence, a USER GUIDANCE block, the current page URL and the grown attempt history
  as the HISTORY block — record 0 anchors the original failure
- Every turn shows the complete generated code and asks `run? [y/N]`: `y` executes against
  the live page; `n`, Enter or `quit` aborts the turn without execution and the guidance
  prompt reopens — the rejected candidate lands in the history as a completed record with
  the outcome `rejected by the engineer, not executed` and the same URL on both sides
- Every completed turn — executed or rejected — enters the shared per-step history in full:
  the outcome label, the `URL before -> after` pair of the turn, the complete code, the
  complete outcome; nothing is collapsed or truncated
- A red turn shows the complete error and returns to the guidance prompt immediately — no
  re-execution loop, the settle window does not re-arm inside the dialog
- `quit`, EOF (Ctrl+D), SIGINT (Ctrl+C) and an unreadable stdin (a captured CI stream) end
  the dialog and the original terminal failure propagates — nothing hangs

## Effects

- A green turn writes the healed step back to the cache — only after the successful execution — and reports
  on_healed; the test continues
- Guidance is one-shot: it lands in the log, never in the cache file
- Interactive attempts consume no generation or healing budgets — the human in the loop is the bound

## The compliance gate of a guided heal

A guided candidate that executes successfully is verified on two dimensions before the
write-back — instruction compliance and step adequacy, judged from the step type and the
shared attempt history — the same gate as unattended generation:

- a high finding of either dimension never reaches the cache: the dialog shows it, the turn
  lands in the history with the violation text and the guidance prompt reopens — steer the
  model to fix the finding
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) or provider unavailability
  (LLMUnavailableError) ends the dialog — the gate failure is shown in the dialog and
  logged as a WARNING naming the step before the dialog ends, so the engineer sees why the
  green candidate was not written back; the original terminal failure propagates and
  nothing is cached
- the gate adds no budget consumption: interactive attempts stay free, the human in the
  loop is the bound

## Rules

- Opt-in by design: `interactive` defaults to false; PRETTYPLAY_INTERACTIVE must never leak into CI environments
- The dialog is a v1 terminal surface: no chat mode, no manual code paste — every turn must have a measurable outcome
```

---

### 4. Cell: `prettyplay` (root, modified)

**Modification summary:** Imports — add `StepAttempt` to the `prettyplay/engine` import group. Global Annotations — add the honest-inputs end-to-end rule; note the steering intercept passing the anchored history. Body — `->PrettyConfig`/`->BrowserConfig`/`->StepHooks`, `PrettyPlay`, `PrettyplayRuntime` unchanged; `StepExecutor.execute` — history creation in step 2, replay URL brackets in step 3, record #0 seeding in step 4, honest inputs threaded in steps 4–6, three new requirements. Description updated.

#### CODEMANIFEST — `prettyplay/CODEMANIFEST`

```yaml
Imports:
  - Types:
      - Config AS PrettyConfig
      - BrowserConfig
      - load_config
    From: prettyplay/config
  - Types:
      - StepHooks
      - StepReporter
    Usages:
      - hooks
    From: prettyplay/reporting
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
  - Types:
      - DriverSession
      - PageFacade
    From: prettyplay/driver
  - Types:
      - StepCache
      - StepIdentity
      - normalize_step_text
      - RunBudgets
    From: prettyplay/cache
  - Types:
      - LLMProvider
      - create_provider
    From: prettyplay/llm
  - Types:
      - StepGenerator
      - StepHealer
      - StepAttempt
      - run_step_code
      - classify_step_failure
      - format_step_error
    Usages:
      - generation
      - healing
    From: prettyplay/engine
  - Types:
      - SettleWindow
      - settle
    From: prettyplay/engine/polling
  - Types:
      - StepSteering
    From: prettyplay/engine/steering

Usages:
  conventions: .goga/usages/conventions.md

Annotations: |
  Use `conventions` for code writing rules and testing.
  Use `taxonomy` from Imports for the failure kinds the step methods propagate.
  Use `hooks` from Imports for the callback contract accepted by the constructor hooks parameter and add_hooks.
  Use `generation` and `healing` from Imports for the engine cycles the executor delegates to.

  The facade of the library: one main object per test; the engineer writes steps as plain sentences and reads the suite as a scenario.
  Framework-agnostic: no plugin machinery, no runner integration — the integrator wires the library in a few lines.
  Step sentences are visible in the test output through the standard logger prettyplay; step texts land in the cache and in LLM requests — never put secrets or personal data into a step sentence.
  `PrettyConfig` — the public name of the settings model — is re-exported by this facade (see the embedding).
  `BrowserConfig` — the public name of the browser settings group — is re-exported by this facade (see the embedding), uniform with `PrettyConfig`.
  `StepHooks` — the callback contract the facade accepts — is re-exported by this facade (see the embedding), uniform with `PrettyConfig` and `BrowserConfig`.
  Strict mode — the strict field of the effective config — makes the step cycle replay-only: cached code executes honestly, nothing is ever (re)generated. A cache miss is the incurable failure stating that strict forbids generation; a failed cached step is at most classified — never regenerated; without LLM access the failure raises immediately by step type. Classifications are the only LLM calls of a strict run; the generation and healing budgets are never consumed.
  Honest inputs thread end to end through the executor: the executor owns the per-step attempt history — created empty on a cache miss, anchored on a failed cached hit by record 0 (the original cached code, the full replay error and the URL pair of the replay, a `StepAttempt` of outcome original cached code) — and passes the step type and the raw step sentence into every engine call; the casefolded normalization stays an addressing key only.
  The interactive gate lives in the executor: the steering dialog opens exactly at a caught IncurableStepError on a non-strict interactive run — never on product_defect, never in replay-strict, never when the LLM is unavailable; the dialog receives the same anchored history, the raw sentence and the step type, and continues growing it.
  The author escape hatch: run_on_page executes an author callable wholly inside the driver worker thread with the genuine sync Page — the stateful actions excluded from generated code (page.route, page.clock, add_init_script, tracing, HAR, CDP) are performed by the author explicitly; Playwright objects never cross back to the calling thread — the callable returns plain data.

---

->PrettyConfig: {}

->BrowserConfig: {}

->StepHooks: {}

"PrettyPlay(cache_key: str, cache_path: str | None, hooks: list[StepHooks] | None, config: PrettyConfig | None)":
  location: scenario.py
  annotations: |
    The main integrator object — one instance per test. Owns the cache addressing and the isolated browser context of the test; the step cycle is delegated to `StepExecutor`.

    `cache_key`: the mandatory explicit context key — part of the step address; equal keys in the shared root reuse steps across tests.
    `cache_path`: the optional cache subdirectory — part of the address; steps never leak across subdirectories.
    `hooks`: the optional integrator callbacks of this test, keyword-only together with `config` — the reporter is seeded with them at construction, so every event of every step reaches them; None — an empty hooks list, add_hooks appends later.
    `config`: per-test overrides, keyword-only — the same full model, the nested `BrowserConfig` group and the strict switch included; explicitly set values win, unset/empty fields resolve from pyproject+env; None — everything resolves from pyproject+env, as before.

    Supports the context manager protocol: exit closes the test.

    Algorithm:
    1. Resolve the effective config: `load_config` with overrides = config
    2. Build the own `PrettyplayRuntime` with the effective config — no process-wide singleton exists
    3. Construct the per-test reporter: `StepReporter` seeded with hooks — the given list or an empty one; add_hooks appends to it
    4. Construct the per-test `StepCache` from the runtime config, `cache_path` and the reporter
    5. Construct `StepGenerator`, `StepHealer` and `StepSteering` from the runtime config, provider, budgets, the step cache and the reporter
    6. Construct `StepExecutor` with `cache_key`, the cache, the engines, the steering, the runtime budgets, the reporter, the runtime config and the runtime provider
    7. The test page opens lazily on the first step via the runtime open_page

    Requirements:
    - Construction is cheap: the browser starts lazily on the first step; no LLM credentials are required to construct
    - The instance holds no cross-test state: identical outcomes regardless of execution order
  properties:
    "cache_key -> str": |
      The explicit context key, exposed for diagnostics.
  methods:
    "step(text: str)": |
      Execute the action step `text`.

      Delegates to the executor execute with the step type action, the sentence and the test page; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`).
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "expect(text: str)": |
      Execute the assertion step `text` — a legitimately failed expectation surfaces as the product defect failure.

      Delegates to the executor execute with the step type assertion; failures propagate by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`).
      A `PrettyplayError` leaving this method carries its traceback folded to the library boundary: internal library frames — engine, healing, provider — do not appear in what the runner shows.
    "run_on_page(action: Callable[[Page], T]) -> result: T": |
      Execute the author action wholly inside the driver worker thread against the genuine sync Page of the test — the author escape hatch.

      `action`: the callable to execute; receives the genuine sync Page — the stateful actions excluded from generated code (page.route, page.clock, add_init_script, tracing, HAR, CDP) are the author's explicit tools here.
      `result`: the outcome of `action` as-is — plain data only.

      Algorithm:
      1. Resolve the opened test page of this test — a missing page raises a loud actionable `PrettyplayError` telling to run a step first
      2. Delegate to the run primitive of the page handle: `action` executes wholly inside the driver worker thread, sequentially with every step
      3. Return the outcome as-is; an exception raised inside `action` propagates to the caller as-is

      Requirements:
      - Requires an opened test page: calling before the first step raises the loud actionable error
      - The callable runs sequentially with the steps of the test — the shared worker takes one unit at a time

      Constraints:
      - Playwright objects (locators, handles, pages, contexts) never cross back to the calling thread through `result` — the callable returns plain data
      - The prompt rules of generated code do not bind the author
    "get_screenshot() -> image: bytes": |
      Return a full-page PNG image of the current state of the test page — uniform with the facade screenshot.

      `image`: the full-page PNG bytes.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable `PrettyplayError` telling to run a step first
      - No screenshot is taken automatically on step failures: the decision to capture belongs to the test author
    "save_screenshot(filepath: str)": |
      Write a full-page PNG image of the current state of the test page to `filepath`.

      `filepath`: the explicit destination path chosen by the user — any directory, any filename; no default directory is imposed.

      Requirements:
      - Requires an opened test page: calling before the first step raises a loud actionable `PrettyplayError` telling to run a step first
      - A write failure — e.g. a missing parent directory — surfaces as a loud actionable `PrettyplayError`; nothing is created silently
    "add_hooks(hooks: StepHooks)": |
      Register a callback implementation (see `hooks`); applies to the steps of this test.
    "close()": |
      Close the test page context and stop the whole runtime of this test — the browser process, the Playwright driver and the driver thread; idempotent; the context manager exit does the same.

"StepExecutor(cache_key: str, cache: StepCache, generator: StepGenerator, healer: StepHealer, steering: StepSteering, budgets: RunBudgets, reporter: StepReporter, config: PrettyConfig, provider: LLMProvider)":
  location: executor.py
  annotations: |
    The owner of the step cycle and the per-step attempt history: cache hit — execute; cache miss — generate and store; cached failure — heal. In strict mode the cycle is replay-only: nothing is ever (re)generated.
    Every execution of step code — cached code and candidates alike — goes through settle with run_step_code: the worker-thread boundary is encapsulated inside run_step_code, the executor never sees it.

    `cache_key`: the context key of the owning test object.
    `cache`: the step cache of the test.
    `generator` and `healer`: the engines (see `generation` and `healing` from Imports) — never invoked in strict mode.
    `steering`: the interactive steering of terminally stuck steps — invoked only on a non-strict interactive run; never in strict mode.
    `budgets`: the per-test attempt registry — never consumed in strict mode.
    `reporter`: the visibility point.
    `config`: the effective settings of the test — the source of the strict switch.
    `provider`: the LLM port of the test — the source of the strict-path classification.
    A classification reached on the strict path is carried by the raised terminal failure as a `FailureVerdict`.
  methods:
    "execute(step_text: str, step_type: str, page: PageFacade)": |
      Run one step through the full cycle.

      Algorithm:
      1. Report on_step_started with the sentence and the step type
      2. Build the step identity: `normalize_step_text`, then `StepIdentity` with the test cache key and the step type; create a `SettleWindow` of this step execution from the polling settings of the effective config; create the per-step attempt history — an empty `StepAttempt` record list
      3. Load the cached step. Strict mode and a miss: raise `IncurableStepError` — the reason states that strict mode forbids generation and names the cache miss, the error field empty, the verdict absent; no generation request is made, no budget consumed. A hit: read the page URL, execute its code under the settle window — `settle` with `run_step_code`, the cached code, `page` and the window; read the page URL again — the pair brackets the replay; replay-strict included: re-executing cached code is execution, not generation
      4. On a hit execution failure. Strict mode — classification only: classify via `classify_step_failure` passing the raw sentence and the full underlying error; a product_defect classification raises `ProductDefectError` carrying the verdict and the full underlying error; a rot, fixable or incurable classification raises `IncurableStepError` carrying them — the reason names the classification explanation; both authored colon-free; never regenerated: the healer is not invoked, the healing budget stays untouched, on_healing_started never fires; an unavailable LLM at this classification is skipped quietly with a WARNING and the failure raises immediately by step type without a verdict — colon-free. Otherwise: seed the attempt history with record 0 — a `StepAttempt` of outcome original cached code carrying the cached code, the full replay error formatted by `format_step_error` and the URL pair of the replay — then delegate to the healer heal with the raw sentence, the step type, the scenario context, the anchored history and the window — a healed step is already re-executed and stored by the engine
      5. Otherwise on a miss: the generator generate with the window, the raw sentence, the step type and the empty attempt history — the engine stores the step on success
      6. Steering intercept — wrap the engine paths of steps 4 and 5: a raised `IncurableStepError` on a non-strict interactive run goes to the steering steer with the failure, the identity, the raw sentence, the step type, the scenario context, the anchored attempt history and `page` before it propagates; a healed return continues as success — the cache write-back already happened inside the dialog; None — the original failure propagates unchanged. The intercept never triggers on `ProductDefectError`, on `LLMUnavailableError`, in strict mode or when interactive is off
      7. Append the sentence to the scenario context of the test — the previous step texts feed the next generation
      8. Report on_step_passed; on a failed step report on_step_failed with the sentence, the step type and the full render — the rendered message of the raised error, never re-composed; then, when the terminal failure carries a verdict, report on_step_verdict with the sentence and the three verdict fields taken from the verdict object; finally raise by kind — `ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError` (see `taxonomy`)
      9. Report on_step_finished with the sentence, the step type and the outcome — passed or failed — exactly once at the very end of every step, after every other event, regardless of outcome

      Requirements:
      - The scenario context lives per test: steps of different tests never mix
      - A cached step executes with no LLM involvement whatsoever
      - An assertion step surfaces a legitimately failed expectation as the product defect failure
      - Strict mode: the only LLM calls are classifications; the generation and healing budgets are never consumed; the engines are never invoked; the settle window still applies to the cached code
      - The raw step sentence reaches every engine call verbatim — generate, heal and steer alike; the casefolded normalization is an addressing key only
      - The per-step attempt history lives exactly one step execution: created in step 2, grown by the engine loops and the steering dialog, never carried across steps
      - Record 0 is composed before the heal delegation — a regeneration never loses the original cached code
      - The error text carried by the raised failures: for failed checks — without the AssertionError prefix, the exception type already carries the assertion semantics; for action steps — the full underlying error text with its type; formatted by `format_step_error`
      - One render per terminal failure: the exception message, the on_step_failed error payload and the log record carry the same rendered text
      - One settle window per step execution: created in step 2, threaded into every engine call; the first execution marks its start
      - on_step_finished fires exactly once per step — the closing event of the cycle

"PrettyplayRuntime(config: PrettyConfig)":
  location: runtime.py
  annotations: |
    The per-test composition root: one instance per test, owning everything the steps of that test share.

    `config`: the effective settings of the test.

    Requirements:
    - One instance serves exactly one test: construction starts nothing expensive — the browser, the provider and the budgets belong to this test alone
  properties:
    "config -> PrettyConfig": |
      The effective settings of the test.
    "driver -> DriverSession": |
      The browser process of this test, created lazily.
    "budgets -> RunBudgets": |
      The attempt registry of the test — one budget per step within the test.
    "provider -> LLMProvider": |
      The LLM provider instance, created lazily on first access via `create_provider`.

      Requirements:
      - Constructing the runtime never requires LLM credentials: a missing key surfaces as the infrastructure failure on the first generation or classification request
  methods:
    "open_page() -> page: PageFacade": |
      Open a fresh isolated browser context and return its page handle — the internal runtime plumbing handle of the test page; one per test. The run_on_page escape hatch of the facade delegates to its run primitive.
    "close()": |
      Stop the browser, the Playwright driver and the driver thread of this test; safe when nothing was started.

      Requirements:
      - Every instance registers its own close with atexit, so the driver stops synchronously before the process exits even when no test closes the runtime explicitly; manual calls stay valid and idempotent

---

Author: Goga
CreatedAt: 10/09/26
Description: |
  The facade of prettyplay: the per-test scenario object with screenshot abilities and the author escape hatch onto the genuine page, the step cycle executor with the strict replay-only path, the per-step attempt history and the honest-inputs threading, verdict reporting, the per-test composition root, and the re-exported settings models — PrettyConfig and BrowserConfig.
```

#### `.usages/` files

**File:** `prettyplay/.usages/steps.md` (updated; `lifecycle.md` unchanged)

````markdown
# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the «Sign in» button")
    t.expect("the «Welcome back» message appears")
    t.close()
````

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

## Step kinds

- step(text) — performs what the sentence says
- expect(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## The honest step context

The step cycle carries an honest context window end to end: every generation, healing and
steering request receives the step type (action or assertion), the raw step sentence as
written by the engineer, and the verbatim per-step attempt history — every prior candidate
with its outcome, its URL before -> after line, its complete code and complete error, the
original cached code anchored first. The cache write is guarded by a two-dimension gate —
instruction compliance and step adequacy — so a cached step contains the action the
sentence asks for, not a check of an already-achieved state. All of this is internal: the
authoring surface — step(), expect(), the cache addressing — is unchanged.

## Author page access

The excluded-from-generation stateful actions are performed explicitly by the author — the callable runs wholly
inside the driver worker thread and receives the genuine sync Page:

    with PrettyPlay("videos-flow") as t:
        t.step("open the videos page")
        t.run_on_page(lambda page: page.route("**/api/videos", lambda route: route.fulfill(json={"items": []})))
        t.expect("the page shows a list of videos")

- Requires an opened page: call it after the first step — a loud error otherwise
- The callable returns plain data; Playwright objects (locators, handles, pages, contexts) never cross back to the calling thread
- Prompt rules do not bind the author: page.route, page.clock, tracing, HAR, CDP are the author's explicit tools
- The callable must use the page API only — calling back into the test object (a step, a screenshot, a nested
  run_on_page) re-enters the worker thread the action itself runs on and is rejected with a loud error instead of a
  deadlock
- The callable runs sequentially with the steps — the shared worker takes one unit at a time

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed. Replayed cached code is never re-checked against the current instructions: purge the cache manually after changing them. The attempt history and the honest request inputs take no part in the address either.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the first line with the class name of the terminal failure and the authored reason, the `---` separated step/error section, the conditional received/cause/Call log details section and the unpadded verdict block — identical in the runner output, the log and the on_step_failed hook. Every step ends with one closing on_step_finished event (passed or failed). Healing, cache writes and skipped writes are reported loudly through the same logger. Transient failures absorbed by the settle window appear as settle_retry records — the step itself stays green.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.
```

---

### 5. Project practice — the generation prompt mirror (updated in place)

**File:** `.goga/usages/prompts/generation.md` — changes **together with** the frozen `SYSTEM_PROMPT` constant of `prettyplay/engine` and `prettyplay/engine/steering` (the mirror discipline of both manifests). The frozen `CHEAT_SHEET` constants and `.goga/usages/prompts/cheatsheet.md` stay untouched.

````markdown
# Generation system prompt

The system prompt of every step-code generation and regeneration request of prettyplay — referenced by the engine
and steering cells as the `system_prompt` practice. Content is the single source; both referencing cells render it
verbatim as the system message.

---

You generate executable Python code for one step of a web UI test.

Input you receive:
- STEP TYPE: action or assertion — the kind of the step
- STEP: the step sentence in a natural language
- PREVIOUS STEPS: the sentences of the previous steps of the test, in order
- PAGE SNAPSHOT: the accessibility snapshot of the current page
- PAGE URL: the current URL of the page, when present
- SCREENSHOT: an image of the page, when attached
- CHEAT SHEET: a compact reference of useful Playwright sync API idioms — guidance, not an allowlist; everything standard stays allowed
- USER INSTRUCTIONS: the project's binding code style guidance, when configured
- HISTORY: the verbatim record of every attempt of this step so far, when present — the original cached code first when it exists; each record carries the attempt outcome, the URL before -> after line, the complete candidate code and the complete error
- RECOMMENDATION: the diagnosis of the classification that preceded this regeneration, when present
- USER GUIDANCE: the engineer guidance message of the interactive steering, when present

Output exactly one Python code block with one function of the fixed form:

def step(page) -> None:
    ...

Rules:
- The function receives exactly one argument: the page — the genuine Playwright sync Page; the whole step runs inside the driver worker thread
- Import from playwright.sync_api and the Python standard library only — no third-party
  libraries; imports are global only: at the top level of the code block, before `def
  step`, never inside the function body
- Work through the standard Playwright sync API: locator factories, actions, waits, expect chains, plain asserts on immediate reads — everything standard is allowed; the CHEAT SHEET is guidance, never a boundary
- Assertions: for an assertion sentence end with a check — a waiting expect(...) chain for dynamic content, or an immediate read with a plain Python assert (assert locator.count() > 1)
- No fixed delays, no sleeps, no wait_for_timeout — locators and expect chains auto-wait
- The runtime owns the page lifecycle: never call page.close() or context.close()
- No stateful actions that outlive the step on the page shared by the whole test: page.route, page.clock, add_init_script, tracing, HAR, CDP — excluded from generated code; a cached step would poison every later step far from the cause
- Dialogs: capture with the stock means — with page.expect_event("dialog") as info: — perform the triggering action inside the block, read info.value.type, info.value.message, info.value.default_value, then info.value.accept() or info.value.dismiss()
- Popups and new tabs: capture with with page.expect_popup() as popup_info: — trigger the opening action inside the block, work through popup_info.value; page.bring_to_front() raises a page above the others
- Content inside an iframe goes through page.frame_locator(selector) — locate elements within the returned scope; nested frames chain
- Scrolling: locator.scroll_into_view_if_needed() and page.mouse.wheel(dx, dy) are the standard means
- The page state may already include the effects of prior attempts or manual intervention — the HISTORY records and their URL before -> after lines show what already happened. Your code must produce the step outcome itself: never rely on the current page state already satisfying the step; complete the action or the check even if the page looks done
- RECOMMENDATION and USER GUIDANCE carry the diagnosis and the engineer's intent — follow them when they conflict with your first instinct
- USER INSTRUCTIONS are binding for everything below the safety core of these Rules: follow them when configured; silently ignoring an instruction is a violation
- The safety core of these Rules always outranks the instructions: the fixed function form, the import rule, the lifecycle rule, the stateful-action exclusions, no fixed delays. An instruction conflicting with a Rule or demanding a stateful action is unfollowable: never implement it silently — raise in the step code with the message "instruction conflicts with rule Y" naming the conflict, so the failure surfaces loudly
- Prefer-type instructions are conditional by their own wording: follow them when the page offers the option — best-effort with a graceful fallback is compliance
- The step must complete exactly what STEP says — nothing more, nothing less
- Output only the code block, no explanations
````

### 6. Test artifacts (plan-level requirements, not cell contracts)

- **CI regression (new, mandatory):** a fake-provider test under `tests/engine/` reproducing the contaminated-page scenario — candidate #1 mutates the page and fails a check; assert every step request carries the full attempt history with URL effects, the step type and the raw step sentence (the heal path included); assert the gate blocks action-step code with no action (an adequacy high); assert the final cached code keeps the action. Structure per `conventions` (`tests/engine/test_generator.py` and companions mirroring the source modules).
- **Provider parity (extended):** the existing parity tests under `tests/llm/` extended to the new request parts — the STEP TYPE line, the HISTORY block, the ATTEMPT HISTORY block of the gate request, the dimension field of the verdict.
- **Verdict parsing (extended):** `parse_compliance_verdict` tests — the closed dimension set, the old shape rejected.
- **Live acceptance (build stage):** the duckduckgo example run — plain flow and interactive captcha scenario — from an empty cache; the next run green with no LLM.

## Dependency Map

```
prettyplay/config ─┐
prettyplay/failures ─┼─> prettyplay/llm ──(ComplianceFinding, LLMProvider, FailureClassification
prettyplay/reporting ┘                     + classification usage)──> prettyplay/engine
prettyplay/cache, prettyplay/driver, prettyplay/engine/polling ──────> prettyplay/engine
prettyplay/engine ──(run_step_code, check_step_compliance, StepAttempt)──> prettyplay/engine/steering
prettyplay/engine ──(StepGenerator, StepHealer, StepAttempt + generation/healing usages)──> prettyplay
prettyplay/engine/steering ──(StepSteering)──> prettyplay
```

Zero new edges; no cycles; `StepAttempt` travels only along pre-existing import directions; `prettyplay/llm` imports nothing from the engine contour (the port carries `list[str]` rendered records).

## Verification Checklist

After applying each artifact:

1. **`prettyplay/llm`** — `goga lint` clean; the facade check `python -c "from prettyplay.llm import LLMProvider, ComplianceFinding, parse_compliance_verdict, create_provider"` passes; parity tests extended and green (STEP TYPE line, HISTORY block, ATTEMPT HISTORY block, dimension in the verdict); the old-shaped verdict (no dimension) raises `ComplianceVerdictError` in the parse tests.
2. **`prettyplay/engine`** — `goga lint` clean; `python -c "from prettyplay.engine import StepAttempt, check_step_compliance, run_step_code"` passes; the fake-provider CI regression green (history + URL effects + step type + raw sentence on every request, heal path included; adequacy-high blocks an actionless action step; the final cached code keeps the action); unit tests for `StepAttempt.render` (verbatim, no truncation, closed outcome labels) green.
3. **`prettyplay/engine/steering`** — `goga lint` clean; the dialog test green: the shared history grows across a rejected turn, a red turn and a gate-blocked turn, each with its URL pair; the write-back happens only after a two-dimension pass.
4. **`prettyplay` (root)** — `goga lint` clean; executor tests: the history is created per step execution, record 0 seeds from the failed cached replay (code + full error + URL pair), the raw sentence reaches heal/steer; strict-mode behavior unchanged.
5. **Prompt mirror** — `.goga/usages/prompts/generation.md` and the frozen `SYSTEM_PROMPT` constants of engine and steering are byte-identical mirrors; `CHEAT_SHEET` constants untouched; `goga lint` passes on the whole project.
6. **Acceptance** — the CI regression is deterministic on the fake provider (no live site); the live duckduckgo acceptance run belongs to the build stage: empty cache → fill+check code cached in both scenarios; second run green with no LLM.

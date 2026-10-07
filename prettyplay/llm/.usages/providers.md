# Providers

Domain: LLM provider selection and parity. Audience: integrators choosing a provider and setting models.

## Select a provider

```python
from prettyplay.config import Config
from prettyplay.llm import create_provider

config = Config(provider="anthropic", model="claude-sonnet-4-5")
provider = create_provider(config)
```

The provider is a project setting: openai or anthropic; env override PRETTYPLAY_PROVIDER. API keys come only from environment variables: OPENAI_API_KEY for openai, ANTHROPIC_API_KEY for anthropic.

## Models

| Setting | Purpose | Fallback |
|---|---|---|
| model | the main model for both operations | — |
| generation_model | code generation only | model |
| classification_model | failure classification and the compliance gate | model |

The instruction compliance gate runs on the effective classification model (classification_model
or model) — never on the generation model, so the verdict never comes from the model that
wrote the candidate.

base_url overrides the provider endpoint when set.

## Parity

Both providers expose the same four operations — generate_step_code, classify_step_failure, classify_group_failure and check_instruction_compliance — with identical inputs, identical output shapes and the identical failure taxonomy: a provider transport failure resends the identical request inside one logical attempt (bounded transport retries) and raises LLMUnavailableError only on exhaustion, a permanent rejection or an over-cap Retry-After; cached step code never depends on the provider. One logical attempt per engine attempt; attempt budgets belong to the calling engine and are never consumed by transport retries.

The classification operation is named `classify_step_failure` — the former `classify_failure`, a nominal rename.

User instructions parity: each operation carries its own instructions — generation requests render the generation_prompt setting, classification requests render the classification_prompt setting — as a verbatim USER INSTRUCTIONS block with identical placement semantics in both providers. A parity requirement, not a capability difference.

Scenario-context parity: the previous steps of a generation request arrive as typed records — each the raw sentence plus its permanent group membership — and render as the PREVIOUS STEPS block with the group entries marked; the group prompt of the current step renders as the GROUP PROMPT block before PREVIOUS STEPS. A parity requirement, not a capability difference.

Step-type parity: every generation request and every compliance verdict request renders the STEP TYPE line — action or assertion — immediately before the STEP line, identically in both providers. A parity requirement, not a capability difference.

Attempt-history parity: a generation request may carry the attempt history of the step — attempt_history, a list of complete multi-line records composed by the calling engine (the attempt outcome, the URL before -> after line, the complete candidate code, the complete error; the original cached code anchors the list as record 0 when it exists). Non-empty — rendered as the HISTORY block after the USER INSTRUCTIONS block, every record verbatim, never collapsed, never size-limited; the block replaces the former CODE/ERROR request pair and the former steering-only history. The request tail order is fixed: HISTORY, RECOMMENDATION (the classification diagnosis), USER GUIDANCE (the engineer message of the interactive steering). Both providers render every non-empty block identically at the same position. A parity requirement, not a capability difference.

Page-URL parity: a generation request with a non-empty page URL renders it as its own PAGE URL line immediately after the PAGE SNAPSHOT block — identically in both providers. The URL reaches every generation and regeneration request of the engine and the guided requests of the steering. A parity requirement, not a capability difference.

Cheat-sheet parity: every generation request renders the CHEAT SHEET block after the scenario inputs and
immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by the
calling engine; guidance, not an allowlist. Both providers render it identically at the same position.

## Transport retries

Transient provider outages no longer kill a logical attempt: every SDK call of all four
operations passes through the shared bounded retry mechanism inside the port.

- Retryable: connection failures, timeouts, HTTP 408/429 and any 5xx — the identical request is
  resent after a computed pause (base 1, 2, 4, 8, 10, 10… s + 0–25% jitter, cap 10 s; a valid
  Retry-After ≤ 10 s lifts the pause to the asked wait)
- Permanent — authentication, authorization, invalid request, an explicitly exhausted quota —
  fails immediately; an explicit permanent cause wins over a retryable status
- Retry-After above 10 s terminates with an actionable LLMUnavailableError — never an early
  resend, never a cap-breaking wait
- The send budget per logical attempt: llm_request_attempts (default 3, initial send included,
  1 disables retries); SDK built-in retries are off (max_retries=0) — the budget is also the
  maximum number of physical sends
- Each retry logs one WARNING (provider, operation, attempt, category, delay) to the logger
  prettyplay — no secrets, no payloads; KeyboardInterrupt during a wait stops the retrying
- Generation, healing and group budgets are untouched: one logical LLM attempt per budget
  attempt, with or without transport retries

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
  accomplish, or — for behavior exceeding the step — the code line performing it — judged
  from the step type and the attempt history
- the priority is high, medium or low; only high blocks the candidate, in either dimension —
  the calling engine owns that decision
- the model behind the call is the effective classification model (classification_model or model)
- a JSON syntax glitch of the answer is salvaged once (the json-repair library) before the
  strict validation — a model dropping a quote, a comma or a bracket does not fail the run; an
  answer that still is not the required shape — including an old-shaped finding without a
  dimension, or an emptiness reached only through the salvage — raises
  ComplianceVerdictError and a provider failure raises LLMUnavailableError — both hard: the
  candidate is not cached unchecked

## The group diagnosis operation

The fourth port operation `classify_group_failure` — one logical request per diagnosis, with
bounded resends of the identical SDK request inside it, through the
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
- provider unavailability raises LLMUnavailableError; one logical request per diagnosis, with
  bounded resends of the identical SDK request inside it, budgets belong to
  the calling engine

## Answer shape

generate_step_code returns step code of the fixed form. Models often answer with a fenced python block (```python … ```); the provider unwraps the first fenced block before returning, so the engine receives clean code either way — an answer with no closed fence is returned verbatim and, if unparsable, keeps failing downstream in execution.

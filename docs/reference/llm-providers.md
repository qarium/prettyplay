# LLM providers

LLM provider selection and parity. For integrators choosing a provider and
setting models.

## Select a provider

```python
from prettyplay.config import Config
from prettyplay.llm import create_provider

config = Config(provider="anthropic", model="claude-sonnet-4-5")
provider = create_provider(config)
```

The provider is a project setting: `openai` or `anthropic`; env override
`PRETTYPLAY_PROVIDER`. API keys come only from environment variables:
`OPENAI_API_KEY` for openai, `ANTHROPIC_API_KEY` for anthropic — read lazily
on the first request.

## Models

| Setting | Purpose | Fallback |
|---|---|---|
| `model` | the main model for both operations | — |
| `generation_model` | code generation only | `model` |
| `classification_model` | failure classification only | `model` |

The instruction compliance gate runs on the effective generation model
(`generation_model` or `model`).

`base_url` overrides the provider endpoint when set.

## Parity

Both providers expose the same three operations — `generate_step_code`,
`classify_failure` and `check_instruction_compliance` — with identical inputs,
identical output shapes and the identical failure taxonomy: a provider service
failure raises `LLMUnavailableError`; cached step code never depends on the
provider. One request per attempt; attempt budgets belong to the calling
engine.

User instructions parity: each operation carries its own instructions —
generation requests render the `generation_prompt` setting, classification
requests render the `classification_prompt` setting — as a verbatim
`USER INSTRUCTIONS` block with identical placement semantics in both
providers. A parity requirement, not a capability difference: classification
requests never carry the generation instructions and generation requests never
carry the classification instructions.

Regeneration block parity: a regeneration request may carry three extra
inputs after the failed code and its error — `RECOMMENDATION` (the diagnosis
of the classification that preceded the regeneration, when present),
`USER GUIDANCE` (the engineer guidance message of the interactive steering,
when present) and `HISTORY` (the accumulated steering turns, when present) —
rendered in this fixed order, identically in both providers. An unset input
renders no block. Unrecognized classification labels fall back to `incurable`
in both providers alike.

Cheat-sheet parity: every generation request renders the `CHEAT SHEET` block
after the scenario inputs and immediately before the `USER INSTRUCTIONS`
block — the compact standard Playwright sync API reference supplied by the
calling engine; guidance, not an allowlist. Both providers render it
identically at the same position. A parity requirement, not a capability
difference.

The one transport-level asymmetry: the anthropic Messages API requires
`max_tokens`, so anthropic requests carry a fixed completion cap (4096
tokens, sized so a full step-code response never truncates); the openai side
sends no cap and the model maximum applies.

## Answer shape

`generate_step_code` returns step code of the fixed form (see
[Driver facade](driver-facade.md)). Models often answer with a fenced python
block (```` ```python … ``` ````); the provider unwraps the first fenced block
before returning, so the engine receives clean code either way — an answer
with no closed fence is returned verbatim and, if unparsable, keeps failing
downstream in execution.

## Classification

```python
classification = provider.classify_failure(
    prompt=system_prompt,  # the system prompt text comes from the calling engine
    user_instructions="",  # the classification instructions from the classification_prompt setting; empty — no block
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    snapshot=snapshot_text,
    screenshot=None,
)
print(classification.category, classification.explanation, classification.recommendation)
```

The classification categories — `rot`, `product_defect`, `fixable`,
`incurable` — and their consequences are covered in
[Self-healing](self-healing.md).

A non-empty `user_instructions` renders as a separate `USER INSTRUCTIONS`
block in the request — the final block of the user content, after all
classification inputs.

## The compliance operation

`check_instruction_compliance` is the verdict request of the instruction
compliance gate (see [Configuration](../configuration.md#the-instruction-compliance-gate)):
the engine calls it once per successfully executed candidate before caching —
never for replayed cached code, never when `generation_approve` is off or
`generation_prompt` is empty (zero calls).

```python
findings = provider.check_instruction_compliance(
    prompt=system_prompt,           # the gate system prompt text comes from the calling engine
    user_instructions=instructions, # the project's user instructions (the generation_prompt setting)
    step_text="click the «Sign in» button",
    code=step_code,
)
```

- full parity between the providers: the user content carries three blocks in
  the fixed order — `INSTRUCTIONS`, `STEP`, `CODE` — built identically by both
  through one shared builder; no screenshot input on this operation
- the gate model is the effective generation model (`generation_model` or
  `model`)
- the answer parses strictly: a JSON list of findings, each with `instruction`,
  `priority` (`high|medium|low`) and `explanation`; an empty list `[]` means
  compliant; a malformed verdict raises `ComplianceVerdictError` — never a
  silent pass. Only a `high` finding blocks the candidate, and that decision
  belongs to the calling engine, not the provider
- SDK errors map to `LLMUnavailableError` exactly like the other operations —
  `llm unavailable: {provider} request failed`
- one request per call, no retry inside the provider

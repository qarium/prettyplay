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
| classification_model | failure classification only | model |

The instruction compliance gate runs on the effective generation model (generation_model
or model).

base_url overrides the provider endpoint when set.

## Parity

Both providers expose the same three operations — generate_step_code, classify_failure and check_instruction_compliance — with identical inputs, identical output shapes and the identical failure taxonomy: a provider service failure raises LLMUnavailableError; cached step code never depends on the provider. One request per attempt; attempt budgets belong to the calling engine.

User instructions parity: each operation carries its own instructions — generation requests render the generation_prompt setting, classification requests render the classification_prompt setting — as a verbatim USER INSTRUCTIONS block with identical placement semantics in both providers. A parity requirement, not a capability difference.

Regeneration block parity: a regeneration request may carry extra blocks after CODE and ERROR — RECOMMENDATION (the classification diagnosis), USER GUIDANCE (the engineer message of the interactive steering) and HISTORY (the accumulated steering turns), in this fixed order. Both providers render every non-empty block identically at the same position. A parity requirement, not a capability difference.

Cheat-sheet parity: every generation request renders the CHEAT SHEET block after the scenario inputs and
immediately before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference supplied by
the calling engine; guidance, not an allowlist. Both providers render it identically at the same position.
A parity requirement, not a capability difference.

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

## Answer shape

generate_step_code returns step code of the fixed form. Models often answer with a fenced python block (```python … ```); the provider unwraps the first fenced block before returning, so the engine receives clean code either way — an answer with no closed fence is returned verbatim and, if unparsable, keeps failing downstream in execution.

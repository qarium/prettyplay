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

`base_url` overrides the provider endpoint when set.

## Parity

Both providers expose the same two operations — `generate_step_code` and
`classify_failure` — with identical inputs, identical output shapes and the
identical failure taxonomy: a provider service failure raises
`LLMUnavailableError`; cached step code never depends on the provider. One
request per attempt; attempt budgets belong to the calling engine.

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

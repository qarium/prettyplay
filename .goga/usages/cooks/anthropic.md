# Anthropic SDK — LLM Generation and Classification Usage

Practices for the official `anthropic` SDK within prettyplay. Target audience: implementing agents working on the generation and healing engines.

`anthropic` is a hard dependency (ADR-6). It provides the same two operations as the OpenAI provider — step code generation and error classification — selected by project configuration.

## Client initialization — secrets from env only

API keys are read from environment variables, never from repository files (ADR-13):

```python
import os

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```

## Message call for step generation

Send the system prompt and the step request (a11y snapshot, step text, previous step texts) as messages; request the generated step code:

```python
message = client.messages.create(
    model=config.model,
    max_tokens=1024,
    system=GENERATION_SYSTEM_PROMPT,
    messages=[
        {"role": "user", "content": build_step_request(snapshot, step_text, previous_steps)},
    ],
)
code = message.content[0].text
```

Healing calls additionally include the existing step code and the error message (ADR-7).

## Error handling — infrastructure failure

```python
try:
    message = client.messages.create(...)
except anthropic.AnthropicError as error:
    raise LlmUnavailableError("llm unavailable: anthropic request failed") from error
```

SDK errors map to the "LLM unavailable" infrastructure failure (R19, R20) — a taxonomy identical to the OpenAI provider.

## Rules

- Provider parity with `openai`: same inputs, same outputs, same failure taxonomy; cached step code never depends on the provider
- One message call per attempt; attempt budgets are managed by the calling engine (ADR-8), never by the SDK client
- Never log API keys or payloads containing secrets

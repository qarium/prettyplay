# OpenAI SDK — LLM Generation and Classification Usage

Practices for the official `openai` SDK within prettyplay. Target audience: implementing agents working on the generation and healing engines.

`openai` is a hard dependency (ADR-6). The SDK serves two operations: code generation for a step and error classification during healing. Cached runs never call the SDK.

## Client initialization — secrets from env only

API keys are read from environment variables, never from repository files (ADR-13):

```python
import os

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
```

## Completion call for step generation

Send the system prompt, the a11y snapshot, the step text and the previous step texts as messages; request the generated step code:

```python
response = client.chat.completions.create(
    model=config.model,
    messages=[
        {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": build_step_request(snapshot, step_text, previous_steps)},
    ],
)
code = response.choices[0].message.content
```

Healing calls additionally include the existing step code and the error message (ADR-7).

## Error handling — infrastructure failure

SDK errors (connectivity, timeout, rate limit, authentication) map to the distinct "LLM unavailable" infrastructure failure (R19, R20): cached steps keep working, only generation and healing are blocked, with an actionable message:

```python
from openai import OpenAIError

try:
    response = client.chat.completions.create(...)
except OpenAIError as error:
    raise LlmUnavailableError("llm unavailable: openai request failed") from error
```

## Rules

- Provider parity: every capability exposed for `openai` must exist for `anthropic` and vice versa; provider selection is a configuration decision
- One completion per attempt; attempt budgets are managed by the calling engine (ADR-8), never by the SDK client
- Never log API keys or payloads containing secrets

# OpenAI SDK — LLM Generation, Classification and Compliance Usage

Practices for the official `openai` SDK within prettyplay. Target audience: implementing agents working on the generation and healing engines.

`openai` is a hard dependency (ADR-6). The SDK serves three operations: code generation for a step, error classification during healing, and the compliance verdict of the gate. Cached runs never call the SDK.

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

## Compliance check call

The compliance gate sends one verdict request per successfully executed candidate — the gate system prompt, the user instructions and the candidate code as messages; the answer is the findings verdict text, not code — no fence unwrapping:

```python
response = client.chat.completions.create(
    model=config.model,  # the effective gate model of the settings
    messages=[
        {"role": "system", "content": COMPLIANCE_SYSTEM_PROMPT},
        {"role": "user", "content": build_compliance_request(instructions, step_text, code)},
    ],
)
verdict_text = response.choices[0].message.content
```

Rules:
- SDK errors map to `LLMUnavailableError` identically — a gate failure is hard, unchecked code is never cached
- The gate is called only when its toggle is on and the instructions are non-empty — zero calls otherwise
- One verdict request per candidate — attempt budgets stay with the calling engine

## Error handling — infrastructure failure

SDK errors (connectivity, timeout, rate limit, authentication) map to the distinct "LLM unavailable" infrastructure failure (R19, R20): cached steps keep working, only generation and healing are blocked, with an actionable message:

```python
from openai import OpenAIError

try:
    response = client.chat.completions.create(...)
except OpenAIError as error:
    raise LLMUnavailableError("llm unavailable: openai request failed") from error
```

## Rules

- Provider parity: every capability exposed for `openai` must exist for `anthropic` and vice versa; provider selection is a configuration decision
- One completion per attempt; attempt budgets are managed by the calling engine (ADR-8), never by the SDK client
- Never log API keys or payloads containing secrets

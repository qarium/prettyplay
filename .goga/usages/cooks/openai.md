# OpenAI SDK — LLM Generation, Classification and Compliance Usage

Practices for the official `openai` SDK within prettyplay. Target audience: implementing agents working on the generation and healing engines.

`openai` is a hard dependency (ADR-6). The SDK serves three operations: code generation for a step, error classification during healing, and the compliance verdict of the gate. Cached runs never call the SDK.

## Client initialization — secrets from env only

API keys are read from environment variables, never from repository files (ADR-13):

```python
import os

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)
```

`max_retries=0` is mandatory: all transport retry control is centralized in the retry mechanism of the llm cell — the SDK never resends a request on its own, so the configured attempt limit is also the actual limit of request sends.

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
- One logical verdict request per provider operation call — the engine gate may re-ask once after a malformed verdict; attempt budgets stay with the calling engine

## Error handling — infrastructure failure

SDK errors (connectivity, timeout, rate limit, authentication) map to the distinct "LLM unavailable" infrastructure failure (R19, R20): cached steps keep working, only generation and healing are blocked, with an actionable message:

```python
from openai import OpenAIError

try:
    response = client.chat.completions.create(...)
except OpenAIError as error:
    raise LLMUnavailableError("llm unavailable: openai request failed") from error
```

## Transport retries — bounded backoff

All four operations (step generation, failure classification, group diagnosis, the compliance verdict) pass through the shared transport retry mechanism inside one logical LLM attempt; transport retries never consume generation, healing or group recovery budgets — those belong to the calling engine.

Retryable failures: connection failures (`APIConnectionError`), timeouts (`APITimeoutError`), HTTP 408/429 (`RateLimitError` carries `Retry-After`) and transient 5xx (`InternalServerError` and any `APIStatusError` with a 5xx status). Permanent failures fail immediately: `AuthenticationError`, `PermissionDeniedError`, `BadRequestError`, `NotFoundError` and an explicitly exhausted quota; an explicit permanent cause takes precedence over a retryable HTTP status.

Policy — fixed by the transport backoff decision (2026-10-07):

- Default **3 total attempts** including the initial request; only the attempt count is configurable (`llm_request_attempts`: explicit test parameters > env `PRETTYPLAY_LLM_REQUEST_ATTEMPTS` > pyproject); a value below 1 is a configuration error
- Delays: base grows 1, 2, 4, 8, 10, 10… seconds, jitter adds 0–25% of the base, the final pause never exceeds 10 seconds
- The retry loop uses only the fixed delay sequence: `Retry-After` at most 10 seconds never lengthens its pause; above 10 seconds the request terminates with an actionable error instead of retrying; malformed values are ignored. Direct callers of `compute_transport_pause` can supply an in-cap hint to raise their pause — the loop itself passes None
- Cancellation (`KeyboardInterrupt`) interrupts the backoff wait and prevents another retry; SDK request timeouts stay unchanged
- Empty completion bodies use a separate response-validation channel: one bounded re-send within the same total send budget, then the closure's own `LLMUnavailableError` is re-raised unchanged if still empty; SDK classification is not used on this channel
- Other malformed answer content is parsed after a successful send, outside transport retries
- After exhaustion an SDK failure raises `LLMUnavailableError` with the original cause chained
- Every retry logs one WARNING to the `prettyplay` logger: provider, operation, attempt number, error category, delay — never secrets or request/response contents

## Rules

- Provider parity: every capability exposed for `openai` must exist for `anthropic` and vice versa; provider selection is a configuration decision
- One logical LLM attempt per engine attempt: bounded transport retries happen inside it and are owned by the llm cell; generation and healing attempt budgets are managed by the calling engine (ADR-8), never by the SDK client; SDK built-in retries are disabled (`max_retries=0`)
- Never log API keys or payloads containing secrets

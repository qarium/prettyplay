# Transport helpers

Domain: using the LLM cell's transport facade. Audience: provider adapter authors and
engineers diagnosing SDK failures. Built-in providers already apply this policy; configure
them with `Config(llm_request_attempts=3)` rather than wrapping a provider operation again.

## Inspect a failure without sending a request

```python
from prettyplay.llm import (
    TransportFailureClassification,
    classify_anthropic_failure,
    classify_openai_failure,
    compute_transport_pause,
)

failure: TransportFailureClassification = classify_openai_failure(ValueError("unknown failure"))
assert failure.category == "invalid_request"
assert failure.retryable is False
assert classify_anthropic_failure(ValueError("unknown failure")).retryable is False

# When planning a retry after the first transient failure:
pause = compute_transport_pause(failed_attempt=1, retry_after=5.0)
assert pause == 5.0
```

Pass the original SDK exception to the corresponding classifier. The returned verdict exposes
`category`, `retry_after` and the computed `retryable` property. Quota evidence can reside in
the SDK exception attributes or its dictionary response body, including the nested error
object; older SDKs need not provide parsed attributes. Unknown failures are permanent.

`compute_transport_pause` draws random jitter but does not sleep. Pass a positive, one-based
failed attempt number. A Retry-After above 10 seconds is a terminal condition for the retry
loop; do not call the pause helper to turn that value into a shorter wait.

## Wrap one SDK send

```python
import os

from openai import OpenAI

from prettyplay.config import Config
from prettyplay.failures import LLMUnavailableError
from prettyplay.llm import classify_openai_failure, send_with_retries

config = Config(model="gpt-5", llm_request_attempts=3)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)
request = {
    "model": config.effective_generation_model,
    "messages": [{"role": "user", "content": "Return a short greeting."}],
}

try:
    response = send_with_retries(
        provider="openai",
        operation="generation",
        attempts=config.llm_request_attempts,
        classify=classify_openai_failure,
        send=lambda: client.chat.completions.create(**request),
    )
except LLMUnavailableError as error:
    # The original SDK failure is available through error.__cause__.
    raise
else:
    # Validate successful response content after the transport loop.
    text = response.choices[0].message.content
finally:
    client.close()
```

The closure performs exactly one send and reuses the same request. Supply a positive total
send budget; `1` disables retries. For Anthropic, use an `Anthropic(max_retries=0, ...)`
client, `classify_anthropic_failure`, and a closure calling `client.messages.create`.
The adapter supplies the provider's usual request parameters, including Anthropic's
required `max_tokens`.

The helper sleeps synchronously between transient failures and logs one WARNING per retry.
Permanent rejection, excessive Retry-After and exhaustion raise `LLMUnavailableError` with
the original cause. `KeyboardInterrupt` propagates. Keep engine budget accounting and
successful-response validation outside the closure.

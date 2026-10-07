# Bounded transport backoff for LLM backend requests

## Current State

The `prettyplay/llm` cell implements the four LLM operations — step code generation, failure classification, group diagnosis and the compliance verdict — through `OpenAIProvider` and `AnthropicProvider` in full parity. Every SDK error, including transient connectivity failures, timeouts, HTTP 408/429 and 5xx, maps immediately to `LLMUnavailableError` with no retry. The contracts state this explicitly:

- `prettyplay/llm` document annotations: "One completion request per attempt"
- `prettyplay/engine` (generate, classify_step_failure): provider unavailability surfaces immediately — "no retry on it"
- `prettyplay/engine/groups` (classify_group_failure): "no retry"

The usages `.goga/usages/cooks/openai.md` and `.goga/usages/cooks/anthropic.md` carried the matching rule ("One completion per attempt"). The SDK built-in retries were left at their defaults, so an SDK-level resend could silently multiply request sends.

The result: a single transient backend outage terminates a whole logical LLM attempt — and with it the running test — although resending the identical request seconds later would succeed.

## Description

Implement bounded transport-level backoff for all four LLM operations of the port, centrally inside the `prettyplay/llm` cell as one shared retry mechanism used by both provider implementations, per the approved ADR (`.goga/history/2026/backoff-for-llm-backend/adr.md`, decision of 2026-10-07):

- Retryable failures: connection failures, timeouts, HTTP 408/429 and any HTTP status from 500 through 599. Permanent failures fail immediately: authentication, authorization, invalid requests and explicitly exhausted quota; an explicit permanent cause takes precedence over a retryable HTTP status, including 5xx. Invalid content in a successful response stays with the existing response validation and recovery — never transport backoff.
- Default **3 total attempts** including the initial request. Only the attempt count is configurable through a new `transport_attempts` setting of `prettyplay/config` with the existing precedence: explicit test parameters > environment (`PRETTYPLAY_TRANSPORT_ATTEMPTS`) > pyproject. One attempt disables retries; values below one are configuration errors.
- Delays are fixed: the base grows 1, 2, 4, 8, 10, 10… seconds; a random 0–25% of the base is added; the final pause is capped at 10 seconds. With the default attempt count the two pauses are 1–1.25 and 2–2.5 seconds.
- A valid `Retry-After` of at most 10 seconds takes the greater of the indicated wait and the computed delay; above 10 seconds the request terminates with an actionable error instead of retrying earlier than requested or exceeding the cap; malformed values are ignored.
- Preserve current SDK request timeouts; no timeout configuration and no overall deadline is added. Cancellation (`KeyboardInterrupt`) interrupts the backoff wait and prevents another retry.
- Disable SDK built-in retries (`max_retries=0` on both clients) so the configured attempt limit also limits request sends.
- After exhaustion, raise the existing `LLMUnavailableError` with the original cause chained; downstream handling is unchanged — required operations fail the current test through normal error handling and cleanup, optional terminal-failure classification logs a warning preserving the original failure, steering preserves its original terminal failure. Only the compliance request is retried after browser actions have run; a candidate is never cached without a successful compliance verdict. Modes making no LLM requests stay untouched.
- Transport retries remain within one logical LLM attempt: they consume no generation, healing or group recovery attempts, and stay distinct from browser polling, which repeats browser code.
- Log every retry to the `prettyplay` logger at WARNING: provider, operation, attempt number, error category, delay. No secrets, no request/response contents, no new public monitoring events.

## Scope

**In scope:**

- Shared transport retry mechanism (error classification, pause computation with jitter and `Retry-After`, bounded retry loop, cancellation, retry logging) inside `prettyplay/llm`, applied to all four operations of both provider implementations
- New `transport_attempts` setting in `prettyplay/config`: field with default 3, positive-integer validation (below one — loud `ConfigurationError`), env override `PRETTYPLAY_TRANSPORT_ATTEMPTS`, participation in the layered merge
- `max_retries=0` at client construction in both provider implementations
- Contract reconciliation: `prettyplay/llm` document and method annotations ("one completion request per attempt" → one logical attempt with bounded transport retries; SDK error mapping semantics), `prettyplay/engine` and `prettyplay/engine/groups` "no retry" statements (transport retries now happen inside the attempt; the engine adds none above them)
- `prettyplay/failures` contract reconciliation: update the `LLMUnavailableError` annotation to cover all four LLM operations without changing the public error type or downstream handling
- Unit tests: retry classification per provider exception type, pause computation (base sequence, jitter bounds, 10-second cap, `Retry-After` max/ignore/terminate paths), attempt-count boundaries (1 attempt — no retry; below 1 — configuration error), exhaustion raising `LLMUnavailableError` with the cause chained, cancellation interrupting the wait, `max_retries=0` at construction, log record fields, no retry consumption of engine budgets

**Out of scope:**

- Timeout configuration and any overall wall-clock deadline
- Any extension of SDK retry policies beyond disabling them
- Changes to browser polling (`prettyplay/engine/polling`)
- New public monitoring or hook events (`prettyplay/reporting` stays untouched)
- Provider work duplication guarantees: exactly-once provider execution is explicitly not guaranteed (see ADR consequences)

## Acceptance Criteria

- A retryable failure (connection, timeout, HTTP 408/429 or any HTTP status from 500 through 599, unless the response identifies an explicitly permanent cause) of any of the four operations is retried up to the configured attempt count with the computed pauses; a success on a later attempt returns normally
- A permanent failure (authentication, authorization, invalid request, explicitly exhausted quota) raises `LLMUnavailableError` immediately with no retry, even when the status would otherwise look retryable; an explicit permanent cause wins over a retryable status
- `transport_attempts` resolves through the existing precedence (explicit test parameters > `PRETTYPLAY_TRANSPORT_ATTEMPTS` > pyproject), defaults to 3, and a value below 1 fails loudly with an actionable `ConfigurationError`
- Computed pauses follow base 1, 2, 4, 8, 10, 10… with jitter 0–25% of the base and a hard cap of 10 seconds
- `Retry-After` ≤ 10 s raises the pause to the indicated wait when it exceeds the computed delay; `Retry-After` > 10 s terminates with an actionable error; a malformed value is ignored
- `KeyboardInterrupt` during a backoff wait propagates without another retry
- Both SDK clients are constructed with `max_retries=0`; the configured attempt count equals the maximum number of request sends for one logical attempt
- After exhaustion the operation raises `LLMUnavailableError` naming the provider with the original cause chained (`raise … from`)
- Each retry produces one WARNING log record carrying provider, operation, attempt number, error category and delay; no secrets or payload contents appear in logs
- Generation, healing and group recovery attempt budgets are consumed identically with and without transport retries (one logical LLM attempt per budget attempt)
- `pytest tests/ -x` passes; `ruff check prettyplay/` passes

## Stack

- **Frameworks:** none beyond the existing project baseline (Python 3.10+, pydantic v2)
- **Libraries:** `openai` >= 1.30 and `anthropic` >= 0.28 (existing; used with `max_retries=0`), stdlib `logging`, stdlib `random`/`time` for jitter and waits — no new dependencies (stdlib decision confirmed 2026-10-07)
- **Infrastructure:** none

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| openai SDK | `.goga/usages/cooks/openai.md` | updated (this session) |
| anthropic SDK | `.goga/usages/cooks/anthropic.md` | updated (this session) |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing |
| general conventions | `.goga/usages/conventions.md` | existing |

Synced usage files are managed by `goga usages sync` — reference them read-only, never create or update them in the task. No synced dependencies exist in this project.

## Risks and Constraints

- The ADR is based on architecture contracts and usage documentation, not an implementation audit: implementation must reconcile every existing no-retry statement it meets in code and verify actual SDK retry defaults of the pinned SDK versions
- Retrying a request whose response was lost after server-side processing may duplicate provider work and increase usage costs; exactly-once provider execution is not guaranteed
- Bounded attempts and capped pauses trade outage tolerance for predictability; there is no total wall-clock bound because request timeouts are unchanged
- The retry loop must stay injectable-sleep testable per the project conventions (mock only external boundaries); tests must not wait real seconds
- Parity is absolute: any classification rule added for one provider's exception hierarchy must have the semantic counterpart in the other

## Scope Estimate

Single task, no decomposition. One bounded mechanism (transport backoff of the LLM port) flowing from one ADR; the config setting, the retry mechanism and the contract reconciliation must land atomically — partial states would be incoherent. No additional topics created.

## Existing Architecture

- `prettyplay/llm` — the core change: shared retry mechanism (a natural home is the existing internal `_request.py` module), `LLMProvider` method annotations for all four operations, `OpenAIProvider`/`AnthropicProvider` algorithms (`max_retries=0`, retry loop around the single SDK call, error category mapping), document annotations ("One completion request per attempt" and the one-request rules of the diagnosis and verdict operations)
- `prettyplay/config` — `Config` gains `transport_attempts` (default 3, positive-integer validation); `load_config` gains the `PRETTYPLAY_TRANSPORT_ATTEMPTS` env override and the layered-merge participation, following the exact pattern of `generation_attempts`/`healing_attempts`
- `prettyplay/engine` — reconcile the generate and classify statements "no retry on it": provider unavailability still surfaces as `LLMUnavailableError` after the transport retries of the logical attempt; the engine itself adds no retries above them
- `prettyplay/engine/groups` — the same reconciliation for the group diagnosis statement
- `prettyplay/failures` — reconcile the `LLMUnavailableError` annotation so it no longer restricts this error to generation and healing; the type and downstream handling stay unchanged
- `prettyplay/reporting`, `prettyplay/engine/polling`, `prettyplay/engine/steering`, the facade cell — no contract changes; log-only visibility and budget semantics carry over unchanged

## Notes

- Input ADR: `.goga/history/2026/backoff-for-llm-backend/adr.md` — the behavioral authority; where wording differs, the ADR wins
- Approved reference example for the pause computation (the exact numeric policy, one compact function):

```python
import random


def compute_pause(failed_attempt: int, retry_after: float | None) -> float:
    """Compute the backoff pause after the failed attempt.

    Args:
        failed_attempt: the 1-based number of the failed attempt.
        retry_after: the parsed Retry-After seconds, None when absent or malformed.

    Returns:
        The pause in seconds: base 1, 2, 4, 8, 10, 10... with 0-25% jitter,
        capped at 10 seconds; a valid Retry-After of at most 10 seconds
        raises the pause to the indicated wait.
    """
    base = min(1.0 * (2 ** (failed_attempt - 1)), 10.0)
    pause = base + base * random.uniform(0.0, 0.25)

    pause = min(pause, 10.0)

    if retry_after is not None and 0 < retry_after <= 10.0:
        pause = max(pause, retry_after)

    return pause
```

  A `Retry-After` above 10 seconds never reaches this function as a wait: the caller terminates with an actionable error before computing a pause.
- Configuration naming decided in this session: `transport_attempts` / `PRETTYPLAY_TRANSPORT_ATTEMPTS`, consistent with `generation_attempts`/`healing_attempts`
- Usage files `openai.md` and `anthropic.md` were updated during task formulation; implementation verifies their consistency with the final code

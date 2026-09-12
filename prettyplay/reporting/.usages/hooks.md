# Step and healing hooks

Domain: event callbacks of prettyplay. Audience: integrators building custom reporting, metrics or CI reactions on top of step execution.

StepHooks is a thin callback contract. The library calls the matching method synchronously while a step executes. The base implementation of every method is a no-op — override only the events you need. Hook implementations are registered on the main library object at the start of a test.

## Events

| Method | When | Payload |
|---|---|---|
| on_step_started | a step started executing | step_text, step_type (action or assertion) |
| on_step_passed | the step finished successfully | step_text, step_type |
| on_step_failed | the step failed | step_text, step_type, error — the **full rendered failure message** (see below) |
| on_step_verdict | the terminal failure carried a verdict (fires after on_step_failed) | step_text, category (rot, product_defect, fixable, incurable), explanation, recommendation |
| on_step_finished | the step ended — always the last step event, regardless of outcome | step_text, step_type, outcome (passed or failed) |
| on_generation_started | a generation attempt started | step_text, attempt (1-based, one per LLM request) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, fixable, incurable) |
| on_healed | the step healed, cache updated | step_text, explanation (why it failed, what changed — interactive healings report here too) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## The error payload of on_step_failed

`error` carries the full structured render of the terminal failure — the same multi-line text the raised exception carries and the log record writes: the primary reason line, the `---` separated step/error block and the column-aligned verdict block. Display it verbatim in reports; do not parse it — structured data arrives through on_step_verdict fields. In strict mode on_generation_started and on_healing_started never fire: classification is the only LLM call.

## Attempt semantics

Hook events fire per step or per LLM attempt — never per execution retry. Settle re-executions of the same step code (transient failure absorption) emit no hook events: they are visible only as settle_retry log records. on_step_finished closes every step exactly once, passed or failed.

## Example

```python
from prettyplay.reporting import StepHooks


class FailureMonitor(StepHooks):
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        print(f"failed [{step_type}]: {step_text}\n{error}")  # the full render, verbatim

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        print(f"verdict [{category}]: {step_text} — {explanation} → {recommendation}")

    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None:
        print(f"finished [{outcome}]: {step_text}")

    def on_healed(self, step_text: str, explanation: str) -> None:
        print(f"healed: {step_text} — {explanation}")
```

## Rules

- Handlers run synchronously inside step execution: keep them fast
- A raising handler is logged as a warning and skipped — the test run never fails because of a hook
- on_step_verdict fires only when the verdict exists: LLM unavailability skips the verdict quietly (WARNING in the log)
- The verdict payload is built from the verdict object of the failure — never parsed from the rendered `error` text
- Payload values are plain strings; the attempt counter of on_generation_started is an int
- Step texts land in logs and hooks: never put secrets or personal data into a step sentence

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
| on_group_started | a group block started (once per entered group, zero-step groups included) | group_prompt |
| on_group_passed | the group block completed without an exception — a recovered group reports passed; a zero-step group reports passed | group_prompt |
| on_group_failed | the group block exited through an exception — a failed step, a refused recovery or an author exception alike; the exception still propagates | group_prompt |
| on_group_finished | the group block ended — always the last group event, regardless of outcome, after on_group_passed/on_group_failed | group_prompt |
| on_generation_started | a generation attempt started | step_text, attempt (1-based, one per LLM request) |
| on_healing_started | healing of a failed cached step started | step_text, category (rot, product_defect, fixable, incurable — a group recovery row reports the diagnosis label recoverable) |
| on_healed | the step healed, cache updated | step_text, explanation (why it failed, what changed — interactive healings report here too) |
| on_cache_saved | step code written to the cache | step_text, filename |
| on_cache_skipped | cache write skipped | step_text, reason (e.g. read-only cache) |

## The step_text of every event

Every `step_text` payload field carries the ready layer of the step — the addressing text of the render: actual values embedded, capture tags kept. Hooks never see the authored template sentence unless the render itself failed — a render-failed step reports the authored template, the only layer that exists. The log-only records below name the step by the same ready layer.

## The error payload of on_step_failed

`error` carries the full structured render of the terminal failure — the same multi-line text the raised exception carries and the log record writes: the first line with the class name of the terminal failure and the authored reason, the `---` separated step/error section, the conditional received/cause/Call log details section and the unpadded verdict block. Display it verbatim in reports; do not parse it — structured data arrives through on_step_verdict fields. In strict mode on_generation_started and on_healing_started never fire: classification is the only LLM call.

## Attempt semantics

Hook events fire per step or per LLM attempt — never per execution retry. Settle re-executions of the same step code (transient failure absorption) emit no hook events: they are visible only as settle_retry log records. on_step_finished closes every step exactly once, passed or failed; on_group_finished closes every entered group exactly once the same way — the group verdict is the block outcome, never the traces: a step healed by the group recovery leaves its verbatim failed trace record behind while the group reports passed.

## Log-only records

Observability data that never belongs to the callback contract goes to the `prettyplay` logger without hook fan-out:

| Record | When | Fields |
|---|---|---|
| generation_request | every step-code provider request completed | step_text, request_ms — the provider call alone, snapshot collection excluded |
| step_execution | every settle window closed, success and failure alike | step_text, attempt (1-based, the LLM request whose candidate executed), execution_ms — the whole settle window, internal re-executions included |

The two records do not sum to wall time: snapshot collection sits between them. Integrators needing them programmatically should watch the logger, not the hooks.


## Structured execution-context logs

Execution-context records keep their existing human-readable messages; programmatic consumers read
`LogRecord.event` and its contextual fields instead of parsing those messages. They never dispatch to hooks.

| event | Context |
|---|---|
| step_results_declared | step_text, declarations — tuple of declared capture names |
| step_inputs | step_text, inputs — copied binding dictionary |
| step_candidate_code | step_text, attempt, code — complete candidate code |
| step_cached_code | step_text, code — complete code restored from the cache |
| step_captured | step_text, captures — copied dictionary of accepted observations |
| verdict_skipped | instruction — the prepared instruction; reason = llm_unavailable |
| cache_sweep_failed | cleanup — the close-time switch; the original traceback stays in exc_info |

The step_text fields carry the addressing text with values embedded and active capture tags kept.
Declaration/input records occur only when those bindings exist; capture records occur only after
acceptance. The candidate/replay messages, their order and levels are unchanged. No new page reads,
provider calls or budget draws happen for logging. Never put secrets into step text or inputs.

For a readable console handler, do not append all contextual fields to messages that already
render their payload. The `EventFormatter` in `example/conftest.py` prints only the existing
message for `step_results_declared`, `step_inputs`, `step_candidate_code`, `step_cached_code`
and `step_captured`. Other records retain their contextual suffix, including lifecycle events,
timings and warnings. Formatting never removes the structured fields from the `LogRecord`;
other handlers can still use the event identifier and complete context.

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

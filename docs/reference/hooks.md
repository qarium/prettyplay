# Hooks and logging

Event callbacks of prettyplay. For integrators building custom reporting,
metrics or CI reactions on top of step execution.

`StepHooks` is a thin callback contract. The library calls the matching method
synchronously while a step executes. The base implementation of every method
is a no-op — override only the events you need. Hook implementations are
registered on the main library object at the start of a test.

```python
from prettyplay import PrettyPlay, StepHooks


class Reporter(StepHooks):
    def on_step_started(self, step_text: str, step_type: str) -> None: ...
    def on_step_passed(self, step_text: str, step_type: str) -> None: ...
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None: ...
    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None: ...
    def on_step_finished(self, step_text: str, step_type: str, outcome: str) -> None: ...
    def on_group_started(self, group_prompt: str) -> None: ...
    def on_group_passed(self, group_prompt: str) -> None: ...
    def on_group_failed(self, group_prompt: str) -> None: ...
    def on_group_finished(self, group_prompt: str) -> None: ...
    def on_generation_started(self, step_text: str, attempt: int) -> None: ...
    def on_healing_started(self, step_text: str, category: str) -> None: ...
    def on_healed(self, step_text: str, explanation: str) -> None: ...
    def on_cache_saved(self, step_text: str, filename: str) -> None: ...
    def on_cache_skipped(self, step_text: str, reason: str) -> None: ...


t = PrettyPlay("login-flow")
t.add_hooks(Reporter())
```

Hooks can also be wired at construction — pass the list to the keyword-only
`hooks` parameter (`PrettyPlay("login-flow", hooks=[Reporter()])`) and every
event of every step reaches them. `StepHooks` is re-exported from the package
root, so `from prettyplay import StepHooks` works too.

## Events

Every lifecycle, generation and healing event (`on_step_started`,
`on_step_passed`, `on_step_failed`, `on_step_verdict`, `on_step_finished`,
`on_generation_started`, `on_healing_started`, `on_healed`) carries the
ready layer in `step_text` — the rendered sentence with current values
embedded and the capture tags kept verbatim
(`Save the title into {% var title %}`): the same text the cache identity
addresses by, destination markers included. The LLM request STEP block
alone carries the instruction with the capture tags stripped — its RESULTS
block declares the destinations. A step whose template never rendered (an
authoring error) carries the authored template — the only layer that
exists. The `on_step_failed` error can also contain the rendered
instruction.

| Method | When | Payload |
|---|---|---|
| `on_step_started` | a step started executing | step_text, step_type (action or assertion) |
| `on_step_passed` | the step finished successfully | step_text, step_type |
| `on_step_failed` | the step failed | step_text, step_type, error — the **full rendered failure message** (see below) |
| `on_step_verdict` | the terminal failure carried a verdict (fires after on_step_failed) | step_text, category (rot, product_defect, fixable, incurable), explanation, recommendation |
| `on_step_finished` | the step ended — the closing event of every step, fired exactly once regardless of outcome, after every other event | step_text, step_type, outcome (passed or failed) |
| `on_group_started` | a group block started — once per entered group, zero-step groups included | group_prompt |
| `on_group_passed` | the group block completed without an exception — a recovered group reports passed (its traces keep the verbatim failed record), a zero-step group reports passed | group_prompt |
| `on_group_failed` | the group block exited through an exception — a terminally failed step, a refused recovery or an author exception inside the block alike; the exception still propagates | group_prompt |
| `on_group_finished` | the group block ended — the closing event of every group, fired exactly once regardless of outcome, after `on_group_passed`/`on_group_failed` | group_prompt |
| `on_generation_started` | a generation attempt started | step_text, attempt (1-based) |
| `on_healing_started` | healing of a failed cached step started | step_text, category (rot, product_defect, fixable, incurable, recoverable — a group recovery row, see [Groups](groups.md)) |
| `on_healed` | the step healed, cache updated | step_text, explanation (why the heal happened — the rot/fixable verdict, the interactive engineer guidance, or the group diagnosis root cause) |
| `on_cache_saved` | step code written to the cache | step_text, filename |
| `on_cache_skipped` | cache write skipped | step_text, reason (e.g. read-only cache) |

## The error payload of on_step_failed

`error` carries the full structured render of the terminal failure — the same
multi-line text the raised exception carries and the log record writes: the
first line with the terminal class name and the authored reason, the `---`
separated step/error block, the conditional received/cause/Call log details
section and the column-zero verdict block. Display it verbatim in reports; do not parse it
— structured data arrives through `on_step_verdict` fields. In strict mode
`on_generation_started` and `on_healing_started` never fire: classification is
the only LLM call.

## Example

```python
from prettyplay.reporting import StepHooks


class FailureMonitor(StepHooks):
    def on_step_failed(self, step_text: str, step_type: str, error: str) -> None:
        print(f"failed [{step_type}]: {step_text}\n{error}")  # the full render, verbatim

    def on_step_verdict(self, step_text: str, category: str, explanation: str, recommendation: str) -> None:
        print(f"verdict [{category}]: {step_text} — {explanation} → {recommendation}")

    def on_healed(self, step_text: str, explanation: str) -> None:
        print(f"healed: {step_text} — {explanation}")
```

## Logging

Visibility goes through the standard logging library: the logger is named
`prettyplay`; the library configures no handlers. Step lifecycle events —
including the verdict event — and group lifecycle events are logged at INFO;
a skipped cache write, a
failed hook call and the non-blocking compliance outcomes — WARNING. The
steering dialog logs its openings, guidance lines and declines at INFO as
`steering_opened`, `steering_guidance` and `steering_declined`; settle
re-executions log at INFO as `settle_retry`. Candidate executions log
their context at INFO — the `saves into:`, `inputs:` and candidate-code
lines (the replay counterpart: `saves into:` and `cached code (replay):`),
and a capturing step's acceptance logs `captured:` with every published
name = value pair. These messages are unchanged; the records additionally
carry stable `event` identifiers and structured context for filtering:
`step_results_declared` (`step_text`, `declarations`), `step_inputs`
(`step_text`, `inputs`), `step_candidate_code` (`step_text`, `attempt`,
`code`), `step_cached_code` (`step_text`, `code`), and `step_captured`
(`step_text`, `captures`). The step text is the addressing text; declarations
are a tuple of names and dictionaries are copied snapshots. The quiet
`verdict_skipped` WARNING carries `instruction` and `reason=llm_unavailable`;
`cache_sweep_failed` carries `cleanup` and keeps its original traceback.
The example's console formatter displays the existing message alone for the
five execution-context events above: code, inputs, declarations and captures
are not repeated in an escaped `| key=value` suffix. Structured fields remain
on the `LogRecord` for other handlers. Lifecycle events, timings and warnings
keep their contextual suffix; custom formatters control their own display.
These records remain log-only. The engine writes log-only
timing records at INFO: `generation_request` (step_text, request_ms — the
provider call alone) and `step_execution` (step_text, attempt,
execution_ms — the whole settle window) on every request and every settle
window; their `step_text` is the ready layer — the capture tag names the
destination inline; they never dispatch to hooks, and the two do not sum
to wall time.
A group block frames itself
with the lifecycle events `on_group_started`/`on_group_passed`/`on_group_failed`/`on_group_finished`
at INFO (the group prompt verbatim; the outcome events are mutually exclusive,
`on_group_finished` always closes),
its recovery logs the landed diagnosis as `group_diagnosed` at INFO and each
recovered row step as `group_row_recovered` at INFO; a degraded diagnosis
answer logs `group_diagnosis_degraded` at WARNING (see
[Groups](groups.md)). The compliance gate
logs its outcomes at WARNING: `compliance findings passed` — the medium and
low findings a green candidate passed with, on the generation path and in the
steering dialog alike — and `compliance gate failed` — a gate hard failure
that ends a steering dialog before the original failure propagates. The
deferred dialog resolver logs a failed resolution of an unclaimed dialog at
WARNING as `dialog resolution failed` — logged and dropped, never masking
the outcome of the action — and a drain that hits the pass bound as
`dialog drain limit reached; the rest resolves at the next unit tail`, so
a page firing a dialog per resolution cannot wedge the unit. The
error field of the `on_step_failed` event and
its log record carry the full structured render of the terminal failure;
integrators display it verbatim.

!!! warning
    Never log secrets, credentials, tokens or sensitive personal data. Step
    sentences, call-local `vars` and captured page values can appear in LLM
    prompts, logs, errors and hooks.

## Rules

- Handlers run synchronously inside step execution: keep them fast
- A raising handler is logged as a warning and skipped — the test run never
  fails because of a hook
- `on_step_verdict` fires only when the verdict exists: LLM unavailability
  skips the verdict quietly (`WARNING` in the log)
- The verdict payload is built from the verdict object of the failure — never
  parsed from the rendered `error` text
- Payload values are plain strings; the attempt counter of
  `on_generation_started` is an int

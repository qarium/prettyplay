# Interactive steering

The opt-in human-in-the-loop escape hatch of a terminally stuck step. For
engineers running local generation sessions.

## When the dialog opens

The step executor opens the dialog at the exact moment an
`IncurableStepError` would propagate — budget exhausted, incurable verdict,
failed-check final classification — when `interactive` is on (default
`false`; env `PRETTYPLAY_INTERACTIVE`, per-test override) and the run is not
strict. It never opens on `product_defect` (a dialog must never repaint a red
test green), never in replay-strict, and never when the LLM is unavailable.

## The dialog

```text
── step "click Checkout" — about to raise IncurableStepError ──────────
code:     items = page.get_by_role("listitem")
          assert items.count() > 1
error:    IncurableStepError: the generation budget is exhausted
          ---
          step: click Checkout
          error: TimeoutError: Timeout 10000ms exceeded
          ---
          received: … / cause: … / Call log: …
          ---
          explanation: the button is behind the "Terms" modal
          recommendation: dismiss the modal first, then click
url:      https://shop.example.com/cart
shot:     /tmp/prettyplay-steering-abc123.png
commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE
generated code:
def step(page) -> None:
    page.get_by_label("Close").click()

run? [y/N] y
✓ step green — healed step written to the cache
```

The banner shows the step, the failed code, the full terminal error render
(see [Failure taxonomy](failure-taxonomy.md)), the current page URL, the
screenshot path and the commands — no snapshot fragment: the full snapshot
stays behind the `snapshot` command and rides every request.

Local commands answer without the LLM:

| Command | Effect |
|---|---|
| `snapshot` | print the full accessibility snapshot |
| `screenshot` | write a full PNG to a temporary file, print the path |
| `error` | reprint the stored underlying error text |
| `code` | reprint the stored step code text |
| `quit` | end the dialog — the original terminal failure propagates |

Every other line is guidance: one regeneration request carrying the step
type, the raw step sentence, a `USER GUIDANCE` block, the fresh page URL
and the grown shared attempt history (see
[LLM providers](llm-providers.md#parity)) — the original failure stays
anchored as record 0 of the history.

Every turn shows the complete generated code and asks `run? [y/N]` —
nothing executes unseen:

- `y` executes the candidate against the live page
- any other answer (`n`, Enter, `quit`) aborts the turn without execution
  and the guidance prompt reopens — the rejected candidate enters the
  history with the outcome `rejected by the engineer, not executed`
- a completed turn — executed or rejected — enters the shared per-step
  attempt history in full: the outcome label, the URL before -> after pair
  (identical on both sides for a rejected turn), the complete code, the
  complete outcome; nothing is collapsed or truncated, and every later
  request carries every record
- a red turn shows the complete outcome and returns to the guidance prompt
  immediately — no re-execution loop, the settle window never re-arms
  inside the dialog (see [Settle polling](settle-polling.md))
- `quit`, EOF (Ctrl+D), SIGINT (Ctrl+C) and an unreadable stdin (a captured
  CI stream) end the dialog and the original terminal failure propagates —
  nothing hangs
- Provider unavailability of a request ends the dialog the same way

## Effects

- A green turn writes the healed step back to the cache — only after the
  successful execution and the compliance gate (which judges both the user
  instructions and the step adequacy from the shared attempt history):
  `medium` and `low` findings pass with a `WARNING`, a `high` finding in
  either dimension never reaches the cache
  (the violation joins the history and the prompt reopens), and a gate hard
  failure — the provider unavailable or a malformed verdict — ends the dialog
  declined, the original terminal failure propagating. A passed turn reports
  `on_healed` with an explanation naming
  the interactive healing (see [Hooks and logging](hooks.md)); the test
  continues
- Guidance is one-shot: it lands in the log, never in the cache file
- Interactive attempts consume no generation or healing budgets — the human
  in the loop is the bound

```python
from prettyplay import PrettyConfig, PrettyPlay

# a local generation session with the steering dialog armed
test = PrettyPlay("login-flow", config=PrettyConfig(interactive=True))
```

## Rules

- Opt-in by design: `interactive` defaults to false; `PRETTYPLAY_INTERACTIVE`
  must never leak into CI environments
- The dialog never opens on `product_defect`, in strict mode, or without LLM
  access
- A v1 terminal surface: no chat mode, no manual code paste — every turn must
  have a measurable outcome

!!! warning
    Keep `interactive` off in CI — an accidentally opened dialog would hang
    the run waiting on a guidance line that never arrives.

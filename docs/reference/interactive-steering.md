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
intent:   click the checkout button
code:     page.get_by_text("Checkout").click()
error:    TimeoutError: Timeout 10000ms exceeded ... element is not visible
verdict:  fixable — the button is behind the "Terms" modal;
          recommendation: dismiss the modal first, then click.

commands: snapshot | screenshot | error | code | quit
guidance> the modal has id=terms — close it via
          page.get_by_label("Close").click() first
⟳ regenerating with USER GUIDANCE … executing against the live page …
✓ step green — healed step written to the cache
```

Local commands answer without the LLM:

| Command | Effect |
|---|---|
| `snapshot` | print the full accessibility snapshot |
| `screenshot` | write a full PNG to a temporary file, print the path |
| `error` | reprint the stored underlying error text |
| `code` | reprint the stored step code text |
| `quit` | end the dialog — the original terminal failure propagates |

Every other line is guidance: one regeneration request carrying a
`USER GUIDANCE` block plus the conversation history (see
[LLM providers](llm-providers.md#parity)) — the result executes against the
live page, every turn ends green or red.

- A red turn shows the outcome and returns to the guidance prompt immediately
  — no re-execution loop, the settle window never re-arms inside the dialog
  (see [Settle polling](settle-polling.md))
- `quit`, EOF (Ctrl+D), SIGINT (Ctrl+C) and an unreadable stdin (a captured
  CI stream) end the dialog and the original terminal failure propagates —
  nothing hangs
- Provider unavailability of a request ends the dialog the same way

## Effects

- A green turn writes the healed step back to the cache — only after the
  successful execution — and reports `on_healed` with an explanation naming
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

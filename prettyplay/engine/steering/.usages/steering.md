# Interactive steering

Domain: the opt-in REPL that rescues a terminally stuck step with engineer guidance. Audience: engineers running generation sessions locally.

## When the dialog opens

The step executor opens the dialog at the exact moment an `IncurableStepError` would propagate — budget exhausted,
incurable verdict, failed-check final classification — when `interactive` is on and the run is not strict. It never
opens on `product_defect` (a dialog must never repaint a red test green), never in replay-strict, and never when the
LLM is unavailable.

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

- Local commands answer without the LLM: `snapshot` prints the full accessibility snapshot, `screenshot` writes a
  full PNG to a temporary file and prints the path, `error` and `code` reprint the stored texts
- Every other line is guidance: one regeneration request carrying a USER GUIDANCE block plus the conversation
  history — the result executes against the live page, every turn ends green or red
- A red turn shows the outcome and returns to the guidance prompt immediately — no re-execution loop, the settle
  window does not re-arm inside the dialog
- `quit`, EOF (Ctrl+D) and SIGINT (Ctrl+C) end the dialog and the original terminal failure propagates — nothing hangs

## Effects

- A green turn writes the healed step back to the cache — only after the successful execution — and reports
  on_healed; the test continues
- Guidance is one-shot: it lands in the log, never in the cache file
- Interactive attempts consume no generation or healing budgets — the human in the loop is the bound

## Rules

- Opt-in by design: `interactive` defaults to false; PRETTYPLAY_INTERACTIVE must never leak into CI environments
- The dialog is a v1 terminal surface: no chat mode, no manual code paste — every turn must have a measurable outcome

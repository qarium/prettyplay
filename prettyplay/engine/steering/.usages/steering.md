# Interactive steering

Domain: the opt-in REPL that rescues a terminally stuck step with engineer guidance. Audience: engineers running generation sessions locally.

## When the dialog opens

The step executor opens the dialog at the exact moment an `IncurableStepError` would propagate — budget exhausted,
incurable verdict, failed-check final classification — when `interactive` is on and the run is not strict. It never
opens on `product_defect` (a dialog must never repaint a red test green), never in replay-strict, and never when the
LLM is unavailable. The dialog receives the per-step attempt history the engine loops grew — anchored by record 0,
the original cached code — and continues growing it; the history survives the dialog.

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
⟳ regenerating with USER GUIDANCE — the complete candidate code is printed
run? [y/N] y
✓ step green — healed step written to the cache
```

- The banner shows the step, the failed code, the terminal error render, the current page
  URL, the screenshot path and the commands — no snapshot fragment; the full snapshot
  stays behind the `snapshot` command and in every request
- Local commands answer without the LLM: `snapshot` prints the full accessibility snapshot,
  `screenshot` writes a full PNG to a temporary file and prints the path, `error` and `code`
  reprint the stored texts
- Every other line is guidance: one regeneration request carrying the step type, the raw
  step sentence, a USER GUIDANCE block, the current page URL and the grown attempt history
  as the HISTORY block — record 0 anchors the original failure
- Every turn shows the complete generated code and asks `run? [y/N]`: `y` executes against
  the live page; `n`, Enter or `quit` aborts the turn without execution and the guidance
  prompt reopens — the rejected candidate lands in the history as a completed record with
  the outcome `rejected by the engineer, not executed` and the same URL on both sides
- Every completed turn — executed or rejected — enters the shared per-step history in full:
  the outcome label, the `URL before -> after` pair of the turn, the complete code, the
  complete outcome; nothing is collapsed or truncated
- A red turn shows the complete error and returns to the guidance prompt immediately — no
  re-execution loop, the settle window does not re-arm inside the dialog
- `quit`, EOF (Ctrl+D), SIGINT (Ctrl+C) and an unreadable stdin (a captured CI stream) end
  the dialog and the original terminal failure propagates — nothing hangs

A group step's guidance requests carry the group context — the group prompt and the
group-marked previous steps; the banner is unchanged.

## Effects

- A green turn writes the healed step back to the cache — only after the successful execution — and reports
  on_healed; the test continues
- Guidance is one-shot: it lands in the log, never in the cache file
- Interactive attempts consume no generation or healing budgets — the human in the loop is the bound

## The compliance gate of a guided heal

A guided candidate that executes successfully is verified on two dimensions before the
write-back — instruction compliance and step adequacy, judged from the step type and the
shared attempt history — the same gate as unattended generation:

- a high finding of either dimension never reaches the cache: the dialog shows it, the turn
  lands in the history with the violation text and the guidance prompt reopens — steer the
  model to fix the finding
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) or provider unavailability
  (LLMUnavailableError) ends the dialog — the gate failure is shown in the dialog and
  logged as a WARNING naming the step before the dialog ends, so the engineer sees why the
  green candidate was not written back; the original terminal failure propagates and
  nothing is cached
- the gate adds no budget consumption: interactive attempts stay free, the human in the
  loop is the bound

## Rules

- Opt-in by design: `interactive` defaults to false; PRETTYPLAY_INTERACTIVE must never leak into CI environments
- The dialog is a v1 terminal surface: no chat mode, no manual code paste — every turn must have a measurable outcome

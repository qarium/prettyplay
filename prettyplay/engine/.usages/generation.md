# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
step = generator.generate(
    identity=identity,
    step_text="click the «Sign in» button",
    step_type="action",
    previous_steps=[
        ScenarioStep(sentence="open the login page", group_prompt=""),
        ScenarioStep(sentence="enter the login and password", group_prompt=""),
    ],
    group_prompt=None,  # None — an ordinary step; the group prompt of the step's group inside one
    page=page,
    attempt_history=history,
    window=window,
)
```

- The loop: request code → execute against the live page → append the full attempt record → on failure re-request with the fresh snapshot and the grown history
- The attempt history is one continuous verbatim list: every record carries the outcome, the `URL before -> after` line, the complete candidate code and the complete error; no collapsing, no size limits — the attempt budgets are the only bound
- Every request carries the honest inputs: the step type (action or assertion) and the raw step sentence as written by the engineer — never the casefolded normalization
- The page may carry side effects of failed candidates and manual intervention — the replayability requirement of the system prompt tells the model a regeneration never rides that leftover state: an action step repeats its action; a first attempt works on the page the previous steps produced. The structural separation rides the same prompt: an action step ends at its action, an assertion step observes without changing the page
- Every candidate execution runs under the settle window: transient failures re-execute the same code inside the window (settle_retry log records), no LLM budget consumed; deterministic failures go to the next request or classification; the URL pair brackets the whole attempt, settle re-executions included
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request; classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only; generation requests never carry it
- Every generation and regeneration request carries the CHEAT SHEET block right before the USER INSTRUCTIONS block — the compact standard Playwright sync API reference carried by every request; guidance, not an allowlist: everything standard stays allowed, the error-driven regeneration loop is the second line of defense

## The execution boundary

The whole step executes inside the driver worker thread as one unit: compile and resolve stay on the calling thread,
the step call itself runs in the worker and receives the genuine sync Page — the calling thread never touches
Playwright, so interactive hosts keep working. An AssertionError of a step — a failed expect chain or a plain assert
on an immediate read — reaches failure classification untouched.

## The decision table

Every classification verdict drives the same table — the category decides, the path only delivers:

| Verdict | Action |
|---|---|
| product_defect | ProductDefectError carrying the verdict — loud, never healed |
| rot, fixable | regeneration carrying the classification recommendation |
| incurable | IncurableStepError carrying the verdict |

## Failed candidate check (bounded healing)

A failed check — an assertion that executed and did not hold, survived the settle window — appends its attempt
record, then is classified:

- product_defect → ProductDefectError with the verdict; one failed check is spent, never the whole budget
- rot or fixable → exactly one regeneration funded from the healing budget, the request carrying the recommendation as a RECOMMENDATION block and the grown history; success stores the healed step; a repeat failure gets one final classification deciding only the terminal kind — product_defect → ProductDefectError, anything else → IncurableStepError; no further regeneration
- incurable → IncurableStepError with the verdict
- LLM unavailable at the classification → the verdict is skipped quietly (WARNING in the log) and IncurableStepError raises without it

## Group steps (framing, no per-step classification)

Inside a group the generator behaves differently in exactly two ways:

- every request of a group step carries the additive group framing — the GROUP PROMPT block and
  the group-marked earlier steps of the group on top of the full test scenario context; nothing
  existing is removed
- the two internal classification points — a failed check of a candidate and the
  generation-budget exhaustion — are suppressed: no classification request, no healing-funded
  regeneration; the loop appends the attempt record and raises IncurableStepError carrying the
  failed code and the full failure text; the executor routes it to the group recovery

With no group framing input (`group_prompt=None`) the ordinary paths are byte-identical. The
previous-steps context is typed: each entry carries the raw sentence verbatim plus its permanent
group membership.

## The instruction compliance gate

Every successfully executed candidate is verified on two dimensions before it is cached —
instruction compliance and step adequacy — the default behavior; switch it off with
generation_approve = false:

- one verdict request per candidate through the provider (the effective classification
  model); zero requests when the switch is off or the instructions are empty
- the request carries INSTRUCTIONS, STEP with its STEP TYPE line, the ATTEMPT HISTORY
  records and the CODE block; the reviewer is instructed to use the attempt history as
  the ground truth of what already happened on the page
- a high finding of either dimension fails the attempt: the record lands in the history
  with the violation text in its error field, the retry carries the grown history — the
  model fixes the finding targeted; budget exhaustion with a standing high finding is the
  terminal incurable failure naming the violated instruction or the unaccomplished step
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) and provider unavailability
  (LLMUnavailableError) are hard failures — a candidate is never cached unchecked
- replayed cached code is never re-gated: changing the instructions does not invalidate
  the cache — purge it manually when the instructions change

## Budget exhaustion

Exhaustion of the generation attempts classifies the last candidate: rot or fixable grants exactly one extra
recommendation-carrying regeneration funded from the healing budget — a repeat failure is terminal
IncurableStepError without reclassification; any other verdict is terminal as before. LLM unavailability at this
classification skips the verdict quietly.

## Classification call

Both engines classify through one routine:

```python
from prettyplay.engine import classify_step_failure

classification = classify_step_failure(
    config=config,
    provider=provider,
    step_text="click the «Sign in» button",
    code=step_code,
    error="element not found: button «Sign in»",
    page=page,
)
```

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. The step sentence is the raw sentence passed by the caller — the casefolded normalization is an addressing key only. The category set is four: rot, product_defect, fixable, incurable. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the genuine sync Playwright Page — importing from
playwright.sync_api and the Python standard library only (third-party libraries forbidden; imports global only, at
the top level of the code block, before `def step`, never inside the function body) and working through the standard API: `page.get_by_role("button", name="Sign in").click()`,
`page.locator("form > button.primary")`, `items = page.get_by_role("listitem")` with
`assert items.count() > 1`,
`with page.expect_event("dialog") as info: ... info.value.accept()`,
`with page.expect_popup() as popup_info: ... popup_info.value`,
`page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`,
`locator.scroll_into_view_if_needed()`, `page.mouse.wheel(0, 600)`. No provider constructs, no fixed delays, no
page.close()/context.close(), no stateful actions (route, clock, add_init_script, tracing, HAR, CDP) — the prompt
rules; the runtime never enforces them.

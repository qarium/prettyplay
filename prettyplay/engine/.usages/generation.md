# Step generation

Domain: generating executable code for an unknown step. Audience: library internals and engineers debugging a first run.

## Generate a step

```python
from prettyplay.cache import StepIdentity, normalize_step_text
from prettyplay.engine.renderer import render_step
from prettyplay.llm import ScenarioStep

prepared = render_step("click the Sign in button", "action", memory, None)
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalize_step_text(prepared.addressing_text),
)

step = generator.generate(
    identity=identity,
    prepared=prepared,  # instruction, addressing text, inputs and declarations from one render
    step_type="action",
    previous_steps=[
        ScenarioStep(sentence="open the login page", instruction="open the login page", group_prompt=""),
        ScenarioStep(
            sentence="enter the login and password", instruction="enter the login and password", group_prompt=""
        ),
    ],
    group_prompt=None,  # None — an ordinary step; the group prompt of the step's group inside one
    page=page,
    attempt_history=history,
    window=window,
    memory=memory,
)
```

- The loop: request code → check the candidate deterministically (pre-flight) → execute against the live page → validate the returned result → on failure append the full attempt record and re-request with the fresh snapshot and the grown history
- The attempt history is one continuous verbatim list: every record carries the outcome, the `URL before -> after` line, the complete candidate code and the complete error; no collapsing, no size limits — the attempt budgets are the only bound. The error text follows the engine error-text policy: the bulky aria-snapshot section Playwright appends to a failed check message is excluded — the fresh page state reaches the loop through the separately captured snapshot
- Every request carries the honest inputs: the step type (action or assertion) and the prepared instruction of the step (with its INPUTS/RESULTS blocks when present) — the raw template sentence never reaches a request; NFC + trim normalization is an addressing key only
- The page may carry side effects of failed candidates and manual intervention — the replayability requirement of the system prompt tells the model a regeneration never rides that leftover state: an action step repeats its action; a first attempt works on the page the previous steps produced. The structural separation rides the same prompt: an action step ends at its action, an assertion step observes without changing the page
- Every candidate execution runs under the settle window: transient failures re-execute the same code inside the window (settle_retry log records), no LLM budget consumed; deterministic failures go to the next request or classification; the URL pair brackets the whole attempt, settle re-executions included
- A positive probe_timeout setting (seconds) shortens the default action timeout of every candidate execution (generation, healing and funded regeneration alike): a wrong locator fails in the probe bound instead of the page default; after every candidate the page default restores to the baseline — the browser timeout setting, explicitly applied at page creation (default 30 s); replayed cached code and steering keep the baseline; probe 0 — off (the default)
- Every provider request and every settle window is timed through log-only records in the prettyplay logger: generation_request carries request_ms (the provider call alone), step_execution carries attempt and execution_ms (the whole settle window) — never hook events; the two do not sum to wall time; both name the step by its ready layer — the addressing text, capture tags kept
- A non-empty generation_prompt setting adds a USER INSTRUCTIONS block to every generation and regeneration request; classification requests never carry it; changing the instructions never invalidates the cache — cached steps run as stored
- A non-empty classification_prompt setting adds a USER INSTRUCTIONS block to classification requests only; generation requests never carry it
- Every generation and regeneration request carries the PLAYWRIGHT SKILL block right before the USER INSTRUCTIONS block — the packaged Playwright skill (prettyplay/skills/playwright/SKILL.md, read once per runtime) with failure-avoidance idioms; guidance, not an allowlist: everything standard stays allowed; the error-driven regeneration loop is the second line of defense

## The pre-flight gate

Every candidate passes a deterministic check before any browser execution — syntax validity, a module-level
`def step` function, no runtime `__import__` call, no leaked `page.route` without its `page.unroute`, no
`expect(...)` assertion trailing the step's own `page.goto`, no unused import and name resolution
(`check_step_code`, stdlib `ast`; the one-argument form of the step function resolves at execution, never here). A
candidate that does not compile, has no step function, imports at runtime, leaks a route, self-confirms its own
navigation or loads a name bound nowhere (a
missing `import`, a typo) never reaches the page: the
attempt record lands in the history with the violation text (outcome `preflight blocked`, the URL pair equal on
both sides) and the loop re-requests immediately. The violation consumes the attempt like any candidate failure.
Name analysis collects store/delete targets, imports, definitions, parameters, exception handler names and
global/nonlocal declarations across all scopes. Pattern-matching captures are not collected: valid match/case
code can be rejected as undefined, so the analyzer does not promise zero false positives for full Python.
Scope-sensitive binding errors remain execution failures. Whitelisted dunders are analyzer exemptions,
not runtime guarantees: __file__ is absent unless the candidate binds it; exec supplies __builtins__. A star
import suspends name analysis, and an unexpected analysis error passes the candidate. Replayed cached code
is never checked.
Navigation-confirmation detection compares independently collected source positions by line and column:
nested goto calls followed by expect are blocked regardless of AST traversal order, including calls on
the same line. Expectations that precede every goto remain allowed; this is a structural source-order
check, not control-flow or alias analysis.

## Result contract

A candidate of a step with result declarations must return the dictionary of exactly the declared names to
non-blank observed strings. After a successful execution the loop validates it deterministically
(`validate_step_result` from the renderer): a violation is a failed check — the record lands in the history with
the violation text, the existing classification and healing budgets apply. A valid result publishes to the test
memory together with the gate pass: an accepted candidate publishes its captures exactly once, after validation
and the compliance gate; failed and gate-blocked attempts publish nothing.

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
previous-steps context is typed: each entry carries the raw sentence plus its prepared instruction —
requests render the instruction field with the permanent group membership marked.

## The instruction compliance gate

Every successfully executed candidate is verified on two dimensions before it is cached —
instruction compliance and step adequacy — the default behavior; switch it off with
generation_approve = false:

- one verdict request per candidate through the provider (the effective classification
  model); zero requests when the switch is off or the instructions are empty
- the request carries INSTRUCTIONS, STEP with its STEP TYPE line, optional INPUTS and RESULTS,
  the ATTEMPT HISTORY records and the CODE block; the reviewer is instructed to use the attempt history as
  the ground truth of what already happened on the page
- a high finding of either dimension fails the attempt: the record lands in the history
  with the violation text in its error field, the retry carries the grown history — the
  model fixes the finding targeted — and the next request's RECOMMENDATION block carries
  the standing finding as an imperative prohibition (`Do not repeat the violation that
  blocked the previous attempt — …`); on a healing path the prohibition composes with the
  entry diagnosis, a fresh candidate failure supersedes it; budget exhaustion with a
  standing high finding is the
  terminal incurable failure naming the violated instruction or the unaccomplished step
- medium and low findings pass with a WARNING naming the instructions
- a malformed verdict (ComplianceVerdictError) is re-asked once; a verdict that stays unparsable
  degrades to a loud unchecked pass (WARNING) — a green step never dies on verdict quality;
  provider unavailability (LLMUnavailableError) stays the hard failure it always was — a candidate
  is never cached on an outage
- replayed cached code is never re-gated: changing the instructions does not invalidate
  the cache — purge it manually when the instructions change

## Budget exhaustion

Each provider request may resend the identical SDK request up to `llm_request_attempts`
(default 3, initial send included). These transport sends consume no additional generation
or healing budget and emit no additional generation-started hooks. If the provider raises
`LLMUnavailableError` after its retry policy terminates, generation propagates it without
another engine attempt; an optional terminal classification still uses the quiet verdict skip.

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

The routine collects the fresh page snapshot (plus the screenshot when enabled) and calls the provider with the engine classification prompt; a non-empty classification_prompt setting of the config reaches the request as a USER INSTRUCTIONS block. A deterministic code defect — the error text starting with `SyntaxError: `, `NameError: `, `ImportError: ` or `ModuleNotFoundError: ` — returns a synthesized `fixable` verdict with no page read and no provider request. The step sentence is the prepared instruction passed by the caller — never the raw template sentence; NFC + trim normalization is an addressing key only. The category set is four: rot, product_defect, fixable, incurable. Provider unavailability propagates: the calling path decides whether it is a terminal infrastructure failure or a quiet verdict skip.

## The fixed form

Generated code is one function receiving exactly one argument — the genuine sync Playwright Page — importing from
playwright.sync_api and the Python standard library only (third-party libraries forbidden; imports global only, at
the top level of the code block, before `def step`, never inside the function body) and working through the standard API: `page.get_by_role("button", name="Sign in").click()`,
`page.locator("form > button.primary")`, `items = page.get_by_role("listitem")` with
`assert items.count() > 1`,
`with page.expect_event("dialog") as info: ... info.value.accept()`,
`with page.expect_popup() as popup_info: ... popup_info.value`,
`page.frame_locator("#checkout").get_by_role("button", name="Pay").click()`,
`locator.scroll_into_view_if_needed()`, `page.mouse.wheel(0, 600)`. Every name the code binds, the code uses — no
dead weight. No provider constructs, no fixed delays, no page.close()/context.close(), no stateful actions (route,
clock, add_init_script, tracing, HAR, CDP) — the prompt rules; the runtime never enforces them.

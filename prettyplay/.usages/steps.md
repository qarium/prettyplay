# Writing steps

Domain: authoring UI tests as plain sentences. Audience: engineers writing tests and integrators wiring the library into a test framework.

## A test as a scenario

```python
from prettyplay import PrettyPlay


def test_login():
    t = PrettyPlay("login-flow")
    t.step("open the login page")
    t.step("enter the login and password")
    t.step("click the «Sign in» button")
    t.expect("the «Welcome back» message appears")
    t.close()
```

Or with the context manager:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
```

## Step kinds

- step(text) — performs what the sentence says
- expect(text) — verifies what the sentence says; a legitimately failed expectation fails the test as a product defect

## Step parameters

- step(text, tries=3) — the total number of executions of the step's code (the first included);
  replaces the time-bounded settle window for that step; the global polling settings stay
  untouched; absorbed retries appear as settle_retry records only, the step stays green
- step(text, delay=1.5) — a quiet pause in seconds before the step's code runs: the started event
  fires, the declared seconds pass, then the code; a step never reached never pauses
- step(text, vars={"expected": "Details"}) — the call-local string inputs; separate namespace from memory
- The optional tries, delay and vars parameters are keyword-only and accepted by both step kinds; invalid values (zero/negative
  tries, negative delay) and non-string vars values fail loudly at the call

## Templates and step memory

Capture an observation, navigate, verify — ordinary step and expect calls plus explicit template syntax:

```python
with PrettyPlay("item-name") as t:
    t.step("Open https://shop.example/products")
    t.step("Read the first item name into {% var name %}")
    t.step("Open the item named {{ name }}")
    t.expect("The page contains {{ name }}")
```

- `{% var name %}` declares where the step saves text read from the page; once the step is accepted, `name` is
  available in later templates
- Several captures in one step publish together — `t.step("Read the first item name into {% var first_name %} and
  the second item name into {% var second_name %}")`; a successful recapture replaces the previous value; a failed
  step publishes nothing
- Memory survives navigation and belongs to one test execution — never shared across tests, concurrent runs included
- A same-step read observes the previous value or fails with the unavailable name; use two steps to capture then use
- Templates are ordinary Python strings — f-strings evaluate before PrettyPlay receives them

Call-local inputs through the reserved `vars` namespace:

```python
t.expect("The page contains {{ name }} and {{ vars.expected }}", vars={"expected": "Details"})
```

- `{{ name }}` reads memory, `{{ vars.name }}` reads the call input — separate namespaces, neither overwrites the
  other; call inputs never establish memory; values are strings only
- Standard Jinja stays available (filters, conditions, `set` — template-local); missing values fail loudly naming
  the name; author-written `| default(...)` and `is defined` behave as authored

## Literal Jinja in existing sentences

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

## Cache and replay limitation

- Template sentences address the cache by their source: `{{ name }}` and `{{ Name }}` are different steps; runtime
  values never enter the address
- Cached code re-reads captures from the current page on every execution — a changed item name for the same
  operation replays without regeneration
- Accepted limitation: a template that changes the operation itself may let old cached code succeed at the previous
  operation without triggering healing

## Groups

```python
with t.group("accept cookies, fill and submit the order form") as g:
    g.step("accept the cookie banner")
    g.step("fill the email field", delay=0.5)
    g.step("submit the form")
    g.expect("the status shows order confirmed", tries=2)
```

- The group block is one coherent mini-scenario with a shared goal; inside, steps use the ordinary
  authoring surface — retry count and start pause included
- The block frames itself with the four group lifecycle events — on_group_started on entry, then
  on_group_passed/on_group_failed and the closing on_group_finished on exit; a recovered group
  reports passed
- An empty group prompt fails loudly at entry; a group with zero steps emits only the group lifecycle events
- Group membership changes no step's cache address: cached group steps replay as ordinary steps —
  no LLM calls, strict replay-only included
- On a non-strict run a failing group step is diagnosed with the whole group in view and the
  affected row is regenerated and re-executed automatically — a product defect fails loudly,
  recovery never loops forever
- Group pace and pause: `with t.group("…", speed=30, delay=2) as g:` slows the pauses between the
  group's steps (the same percent→pause mapping as the browser speed setting) and waits the
  declared seconds before the group's first step — quiet, library-level pauses

## The honest step context

The step cycle carries an honest context window end to end: every generation, healing and
steering request receives the step type (action or assertion), the prepared instruction with its input bindings and
result declarations, and the verbatim per-step attempt history — every prior candidate
with its outcome, its URL before -> after line, its complete code and complete error, the
original cached code anchored first. The cache write is guarded by a two-dimension gate —
instruction compliance and step adequacy — so a cached step contains the action the
sentence asks for, not a check of an already-achieved state. All of this is internal: the
authoring surface uses step() and expect() with optional vars; cache addressing uses the original
template source.

## Author page access

The excluded-from-generation stateful actions are performed explicitly by the author — the callable runs wholly
inside the driver worker thread and receives the genuine sync Page:

    with PrettyPlay("videos-flow") as t:
        t.step("open the videos page")
        t.run_on_page(lambda page: page.route("**/api/videos", lambda route: route.fulfill(json={"items": []})))
        t.expect("the page shows a list of videos")

- Requires an opened page: call it after the first step — a loud error otherwise
- The callable returns plain data; Playwright objects (locators, handles, pages, contexts) never cross back to the calling thread
- Prompt rules do not bind the author: page.route, page.clock, tracing, HAR, CDP are the author's explicit tools
- The callable must use the page API only — calling back into the test object (a step, a screenshot, a nested
  run_on_page) re-enters the worker thread the action itself runs on and is rejected with a loud error instead of a
  deadlock
- The callable runs sequentially with the steps — the shared worker takes one unit at a time

## Screenshots

Two author-facing abilities on the test object:

```python
with PrettyPlay("login-flow") as t:
    t.step("open the login page")
    png = t.get_screenshot()  # full-page PNG bytes of the current state
    t.save_screenshot("artifacts/home.png")  # write full-page PNG to an explicit path
```

- Both require an opened page: call them after the first step of the test
- Nothing is captured automatically on failures — attaching screenshots to reports is the author's decision

## Addressing

The constructor arguments form the cache address: cache_key (mandatory) and cache_path (optional subdirectory). Equal cache keys in the shared root reuse one cached step across tests; a different language, step type or key is a different step. User instructions (generation_prompt, classification_prompt) take no part in the address — a cached step never regenerates because the instructions changed. Replayed cached code is never re-checked against the current instructions: purge the cache manually after changing them. The attempt history and the honest request inputs take no part in the address either.

## What you see

Step sentences go to the logger prettyplay at info level — the suite output reads as a plain-language scenario. A failed step renders one structured message — the first line with the class name of the terminal failure and the authored reason, the `---` separated step/error section, the conditional received/cause/Call log details section and the unpadded verdict block — identical in the runner output, the log and the on_step_failed hook. Every step ends with one closing on_step_finished event (passed or failed). Healing, cache writes and skipped writes are reported loudly through the same logger. Transient failures absorbed by the settle window appear as settle_retry records — the step itself stays green.

## Limitations

Step sentences land in the repository cache, the logs and the LLM requests: never put secrets or personal data into a step.

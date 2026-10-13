# The packaged Playwright skill

Domain: consuming the packaged Playwright pattern library through the cached facade of the
skills cell. Audience: consumer cells threading the skill into LLM requests — the engine
generation loops and the interactive steering — and engineers wiring their own consumers.

## What the skill is

The packaged Playwright skill — `playwright/SKILL.md` inside this cell — is the pattern library
of the standard Playwright sync API: locator factories, narrowing, actions, waiting assertions,
count forms, immediate reads, dialogs, popups, frames, scrolling. Battle-tested idioms and
failure-avoidance patterns distilled from live generation runs; guidance for the generation
model, never an allowlist — everything standard stays allowed.

Every fenced python example of the skill executes green against a live fixture page — the
dedicated test `tests/test_playwright_skill.py` keeps every pattern runnable. The skill changes
only together with that test.

## Loading

```python
from prettyplay.skills import load_skill

skill = load_skill("playwright")  # the verbatim SKILL.md content
```

- Call `load_skill` wherever the request is built — the process-level cache guarantees one
  filesystem read per runtime per skill; after the first call the load is a dictionary lookup,
  so a call inside the request path costs nothing
- The name argument is the skill directory name under the cell package — `playwright` today
- The return is the verbatim content of the skill's `SKILL.md`; no validation happens here —
  the consumer owns the interpretation
- A named skill directory without a `SKILL.md` raises `FileNotFoundError`

## Carrying the skill in requests

The provider port renders the skill as the leading `PLAYWRIGHT SKILL` block of the user content
of every generation and regeneration request — after the scenario inputs, before the USER
INSTRUCTIONS block:

```python
code = provider.generate_step_code(
    prompt=system_prompt,
    instruction=prepared.instruction,
    step_type=step_type,
    skill=load_skill("playwright"),
    ...,
)
```

The skill teaches; the error-driven regeneration loop corrects — it is the second line of
defense against hallucinated calls.

## Rules for consumers

- Rely on the process-level cache — never add a local cache beside it, never copy the skill's
  bytes into a module constant
- Never copy the skill's content into a manifest or a prompt constant — the file is the single
  source of its bytes; a connection note (this practice included) describes how to reach it,
  never restates it

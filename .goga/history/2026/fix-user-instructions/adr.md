# Make user instructions binding, checkable, and expressible

---
Status: accepted
Date: 2026-09-13
---

The example's `generation_prompt` instructions ("Prefer to use id attributes in HTML documents to
find elements", "Make text matching checks case-insensitive") were silently ignored by generated
step code. Tracing surfaced three independent root causes: the system prompt gives the
`USER INSTRUCTIONS` block no enforcement weight (its Rules carry explicit "follow them" directives
only for `RECOMMENDATION` and `USER GUIDANCE`), case-insensitive text assertions are inexpressible
through the driver facade (`expect_text` maps to Playwright `to_contain_text` — a case-sensitive
substring check; `expect_title` compiles its regex without IGNORECASE; the surface exposes no text
getters and `evaluate` is an excluded capability), and cached steps replay without any instruction
awareness. We decided to fix all three layers — prompt, facade, example cache — under one policy:
**an unfollowed or unfulfillable instruction must surface as a generation error, never as silent
ignoring.**

## Decisions

1. **Scope — full fix across three layers.** Prompt layer (instructions become mandatory),
   facade capability (case-insensitive text matching becomes expressible), and regeneration of the
   stale example cache (created 2026-09-13 under the old behavior; deleted in this change, the
   owner regenerates it on the next run).
2. **Compliance gate — an independent LLM check, once per successfully executed candidate, before
   caching** (the same gate on the healing/regeneration path). A non-compliant candidate is a
   failed attempt: the retry carries the violation text as its ERROR, so the model fixes it
   targeted; budget exhaustion raises the terminal error with a verdict naming the instruction.
   The gate is config-toggleable, **default ON (opt-out)** — the default carries the product line
   "loud errors instead of silent ignoring"; a user who minds the cost of one extra LLM call per
   successful generation switches it off consciously. With the gate off (or with an empty
   `generation_prompt`, in which case the gate is not called at all) behavior is fully the old one.
3. **Findings model of the gate verdict.** The verdict is a list of findings, each naming the
   instruction, a priority of `high | medium | low`, and a short explanation. **Only `high`
   blocks** (non-compliance → retry); `medium`/`low` pass with a visible WARNING. `high` is
   assigned only for a confident, material violation that was followable in the concrete situation
   (the page offers the possibility, the API surface allows it); doubt resolves to `medium`/`low`.
   This calibration is what prevents a hyper-strict checker from rejecting working candidates over
   minor issues and burning the attempt budget — minor observations stay visible without blocking.
   An empty findings list means compliant. A malformed or unparsable verdict is a hard failure —
   unchecked code is never cached.
4. **Gate failure is hard.** Provider unavailability of the gate raises `LLMUnavailableError`; the
   successfully executed but unchecked candidate is not cached. Rationale: the gate is a
   configurable procedure, so the strict strategy is acceptable — no silent pass on infrastructure
   flake.
5. **Compliance standard.** The safety core of the system prompt (fixed function form, no
   imports, facade-only calls, expectations-only assertions, no fixed delays) always outranks user
   instructions: an instruction conflicting with a Rule is unfollowable and must error loudly as
   `instruction conflicts with rule Y` — text from the config can never weaken the framework.
   `generation_prompt` is the single full-fledged binding instruction channel for everything below
   the safety core, "system-style" directives included; an instruction naming a call outside the
   facade surface is a conflict error of the same kind. "Prefer"-type instructions are conditional
   by their own wording: followed when the page offers the option (best-effort with graceful
   fallback), and the gate checks conditional compliance, never the impossible always.
6. **Facade capability — text assertion family only.** Only the text assertion family
   (`expect_text`, `expect_title` semantics) gains the case-insensitive capability, as a declared
   non-mirror extension (precedents: the `expect_*` naming family, the scroll extras). Text
   *locating* is deliberately untouched: `get_by_text` and `filter(has_text=...)` already match
   case-insensitively through Playwright's own string-matching defaults, so the gap the example
   instruction exposed is exactly the assertion family.
7. **Request shape unchanged.** The `USER INSTRUCTIONS` block stays after the PAGE API block —
   the block order fixed by the llm cell contract does not change; enforcement weight comes from
   the system prompt rule and the gate, not from repositioning.
8. **Step address stays independent of instructions.** Changing `generation_prompt` does not
   invalidate cached steps — a deliberate retention of the existing addressing contract. The
   consequence is a documented manual step: engineers purge the cache when they change
   instructions, because replayed cached code is never re-gated. The stale example cache files are
   deleted as part of this change.
9. **Classification side — wording only.** The classification system prompt gets the same binding
   wording for its `USER INSTRUCTIONS` input, but no gate: the verdict is a single line with an
   existing protective fallback, and gating it would double the cost of healing paths while
   protecting nothing essential.

## Consequences

- Every successful generation costs one extra LLM call while the gate is on (the default).
- The system prompt change must land in sync in three places: `.goga/usages/prompts/generation.md`
  and its frozen mirrors in `prettyplay/engine/generator.py` and
  `prettyplay/engine/steering/steering.py` ("the mirror and the practice change together").
- Acceptance follows the full checklist: per-layer tests with fake providers (gate retry/error
  paths, zero gate calls when toggled off, facade case-insensitive behavior, new config field with
  env override and layered merge), prompt-mirror sync tests, deletion of the stale example cache,
  documentation of the new setting and the manual cache-purge note, and a final visual run of the
  example by the owner.

## Considered Options (rejected)

- **Prompt-layer-only fix** — rejected: instruction "case-insensitive" stays architecturally
  unfulfillable without the facade capability.
- **Self-declared compliance in the generation answer** — rejected: the declaration comes from the
  same model that just ignored the instructions; the failure is correlated.
- **No mechanical check (hard prompt only)** — rejected: silently reintroduces the observed bug.
- **User instructions above the safety core** — rejected: one config line could break the honest
  page-state model behind classification and caching.
- **Severity escalation / violation budgets** (N rejections then accept with a warning) — rejected:
  turns binding instructions into advisories after a retry; the findings priority scale addresses
  the over-strict-checker concern without that loophole.
- **Instructions in the step address** — rejected: cache churn on instruction edits outweighs the
  benefit; documented manual purge instead.
- **Uniform explicit case semantics across the whole text surface** — deferred (see open
  questions).

## Open Questions

- Exact signature and shape of the case-insensitive text assertion capability (parameter vs.
  separate call) — design stage.
- Config field name for the gate toggle, its env variable, and docs placement — design stage.
- Placement of the gate call within the cell structure (port operation vs engine-owned call) and
  the content of the gate's own system prompt — design stage.
- Facade extension mechanism for users who need custom API surface additions (configurable facade
  extension + auto-extended surface listing + gate awareness; or a second system-level instruction
  channel) — deliberately out of scope, a separate future task.
- Facade-wide case consistency (explicit case semantics for text locating as well) — possible
  future consistency work.

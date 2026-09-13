# Make user instructions binding, checkable, and expressible

Task topic: `fix-user-instructions`. Input: the accepted ADR at
`.goga/history/2026/fix-user-instructions/adr.md` (all ADR decisions are binding for this task).

## Current State

The example's `generation_prompt` instructions ("Prefer to use id attributes in HTML documents to
find elements", "Make text matching checks case-insensitive") were silently ignored by generated
step code. Three independent root causes, confirmed in code:

1. **No enforcement weight.** The generation system prompt
   (`.goga/usages/prompts/generation.md`, frozen mirrors `SYSTEM_PROMPT` in
   `prettyplay/engine/generator.py:22` and `prettyplay/engine/steering/steering.py:24`) directs
   the model to follow only `RECOMMENDATION` and `USER GUIDANCE`; `USER INSTRUCTIONS` is listed
   as a mere input.
2. **Case-insensitive assertions are inexpressible.** `LocatorFacade.expect_text`
   (`prettyplay/driver/page.py:680`) maps to Playwright `to_contain_text` — a case-sensitive
   substring check; `PageFacade.expect_title` (`prettyplay/driver/page.py:158`) compiles its regex
   without `re.IGNORECASE`. Illustration: `page.get_by_text("results").expect_text("test")` fails
   on the text `"Test"` today, and the facade offers no way to express the check the instruction
   demands.
3. **Cache is instruction-blind.** The step address deliberately excludes the instructions, so
   cached steps replay un-gated; the committed example cache
   (`example/.prettyplay/cache/**`, 6 files across `test_google` and `test_yandex`) was generated
   under the old behavior and violates both example instructions.

## Description

Fix all three layers under one policy — **an unfollowed or unfulfillable instruction must surface
as a generation error, never as silent ignoring**:

1. **Prompt layer — instructions become mandatory.** The generation system prompt gains rules:
   `USER INSTRUCTIONS` are binding for everything below the safety core; the safety core (fixed
   function form, no imports, facade-only calls, expectations-only assertions, no fixed delays)
   always outranks them; an instruction conflicting with a Rule or naming a call outside the
   facade surface is unfollowable and errors loudly (`instruction conflicts with rule Y`);
   "prefer"-type instructions are conditional — followed when the page offers the option,
   best-effort with graceful fallback. The change lands in sync in three places: the practice
   `.goga/usages/prompts/generation.md` and both frozen mirrors (the mirror and the practice
   change together). The classification prompt (`classification_prompt` in the engine CODEMANIFEST)
   gets the same binding wording for its `USER INSTRUCTIONS` input — wording only, no gate.
2. **Facade layer — text assertion family gains case-insensitive capability.** Only
   `expect_text` / `expect_title` semantics, as a declared non-mirror extension (precedents: the
   `expect_*` naming family, the scroll extras). The PAGE API surface listing (from the `facade`
   practice) and `prettyplay/driver/.usages/facade.md` change together with the capability. Text
   locating stays untouched — `get_by_text` and `filter(has_text=...)` already match
   case-insensitively through Playwright defaults.
3. **Compliance gate — independent LLM check before caching.** Runs once per successfully
   executed candidate, before it is stored (generation path and healing/regeneration path alike).
   Findings verdict: a list of findings, each naming the instruction, a priority
   `high | medium | low`, and a short explanation. Illustration of the verdict shape the gate
   parses: `[{"instruction": "Make text matching checks case-insensitive", "priority": "high",
   "explanation": "expect_text called without the case-insensitive option"}]`. Only `high`
   blocks: the finding text becomes the ERROR of a failed attempt, so the retry fixes it
   targeted; budget exhaustion raises the terminal error with a verdict naming the instruction.
   `medium`/`low` findings pass with a visible WARNING; an empty findings list means compliant.
   A malformed/unparsable verdict is a hard failure, as is provider unavailability
   (`LLMUnavailableError`) — unchecked code is never cached. The gate never runs when
   `generation_approve` is off or `generation_prompt` is empty — zero calls, fully the old
   behavior.
4. **Config layer — the toggle.** New field `generation_approve: bool`, default `True`
   (opt-out; the default carries the product line "loud errors instead of silent ignoring").
   Env override `PRETTYPLAY_GENERATION_APPROVE` parsing booleans (true/false/1/0
   case-insensitively); participates in the layered merge and per-test overrides like every
   other setting. Documented in the project docs with the cost note (one extra LLM call per
   successful generation while on) and the manual cache-purge note (changing instructions does
   not invalidate cached steps — engineers purge the cache; replayed cached code is never
   re-gated).
5. **Example cache.** Delete the stale `example/.prettyplay/cache/**` files; the owner
   regenerates them on the next run under the new behavior.

## Scope

**In scope:**
- Generation system prompt rules (practice + both frozen mirrors, in sync) and classification
  prompt binding wording
- Case-insensitive capability in the text assertion family of the facade + PAGE API listing +
  `facade.md` practice update
- Compliance gate: findings verdict model and parsing, gate system prompt, the gate call on the
  generation and healing paths before caching, retry-with-violation-text and
  hard-failure semantics
- `generation_approve` config field: validation, env override, layered merge, per-test override
- Deletion of the stale example cache files
- Documentation: the new setting, the instruction policy, the manual cache-purge note
- Tests per the ADR acceptance checklist (see Acceptance Criteria)

**Out of scope:**
- Facade extension mechanism for user-defined surface additions (separate future task)
- Facade-wide case consistency (explicit case semantics for text *locating*) — possible future
  work
- Repositioning the `USER INSTRUCTIONS` block in the request shape (block order fixed by the llm
  cell contract stays)
- Instructions in the step address (addressing contract unchanged)
- A gate on the classification path (classification gets wording only)

## Acceptance Criteria

- Per-layer tests with fake providers:
  - gate retry path: a `high` finding fails the attempt, the retry request carries the violation
    text as its ERROR, success after fixing stores and the healed/next candidate is gated too
  - gate error path: budget exhaustion with a standing `high` finding raises the terminal error
    with a verdict naming the instruction; a malformed verdict and provider unavailability are
    hard failures and nothing is cached
  - zero gate calls when `generation_approve` is off or `generation_prompt` is empty
  - `medium`/`low` findings pass with a visible WARNING
  - facade case-insensitive behavior: the text assertion family matches case-insensitively when
    the capability is used; the default (case-sensitive) behavior is unchanged
  - config: `generation_approve` default True, env override `PRETTYPLAY_GENERATION_APPROVE`
    (true/false/1/0), layered merge and per-test override participation, loud actionable error
    on an unparseable value
- Prompt-mirror sync tests: `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` and
  `prettyplay/engine/steering/steering.py` equal the practice text of
  `.goga/usages/prompts/generation.md`; the `PAGE_API_SURFACE` listings in both files stay in
  sync with the surface table of `prettyplay/driver/.usages/facade.md`
- The stale example cache files under `example/.prettyplay/cache/` are deleted
- Docs cover the new setting, the instruction compliance policy and the manual cache-purge note
- `goga lint` passes; `pytest tests/ -x` passes; `ruff check` clean
- Final visual run of the example by the owner (both instructions now followed in generated
  code) — owner-owned verification step

## Stack

- **Language/runtime:** Python 3.10+ (virtualenv, `pyproject.toml`)
- **Frameworks:** none (library project)
- **Libraries:** `playwright>=1.49` (sync API — case-insensitive expectations), `openai>=1.30`
  and `anthropic>=0.28` (the gate call through the existing provider port), `pydantic` v2 (the
  new config field), `tomli` fallback on Python 3.10
- **Testing/tooling:** pytest, ruff, pytest-cov (per `conventions`)
- **Docs:** MkDocs (`docs/`, `mkdocs.yml`)
- **Infrastructure:** none new — LLM API endpoints and Playwright browsers are existing external
  services

## External Dependencies

| Component | Usage file | Status |
|-----------|--------------------------------|---------|
| playwright | `.goga/usages/cooks/playwright.md` | updated (case-insensitive text expectations section) |
| openai | `.goga/usages/cooks/openai.md` | updated (compliance check call section, three operations) |
| anthropic | `.goga/usages/cooks/anthropic.md` | updated (compliance message call section, three operations, parity) |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing — no change needed |

## Risks and Constraints

- **Prompt mirror sync** — the system prompt exists in three places; a partial update silently
  splits behavior between generation and steering. Mitigated by sync tests named in acceptance.
- **Hyper-strict checker** — a gate that assigns `high` to minor issues burns the attempt budget
  on working candidates. Mitigated by the ADR calibration: `high` only for a confident, material,
  followable violation; doubt resolves to `medium`/`low` (visible, non-blocking).
- **Cost** — one extra LLM call per successful generation while the gate is on (the default);
  opt-out documented, off-switch restores the old behavior exactly.
- **Correlated failure** — the gate verdict comes from an LLM; a malformed verdict is a hard
  failure by design (never a silent pass), so a flaky verdict model surfaces loudly.
- **Cache semantics retained** — instructions stay outside the step address (manual purge
  documented); replayed cached code is never re-gated.
- **Python 3.10 compatibility** — tomli fallback, no 3.11+ stdlib-only constructs.
- **Full-suite validation** in a virtualenv; no new third-party dependencies.

## Scope Estimate

Single task — no decomposition. The layers are interdependent (the prompt mandates what the
facade must make expressible and the gate verifies; the ADR explicitly rejected partial fixes —
a prompt-only or prompt+facade state silently reintroduces the bug class). Internal
implementation order (facade → gate → prompt wording → config/docs/cache) is sequencing within
one task, not subtasks.

## Existing Architecture

Affected cells (dependency order, bottom-up):

- `prettyplay/failures` — only if the malformed-verdict hard failure lands as a new taxonomy
  member (a design-stage decision; reusing an existing failure kind keeps this cell untouched)
- `prettyplay/config` — `Config` gains `generation_approve`; `load_config` gains the env
  override and merge participation
- `prettyplay/driver` — `PageFacade.expect_title`, `LocatorFacade.expect_text` gain the
  case-insensitive capability; `facade.md` practice and the PAGE API listing change together
- `prettyplay/llm` — the gate's provider-side request (third operation; parity in both
  implementations); exact port shape is a design-stage decision
- `prettyplay/engine` — `StepGenerator.generate`/`regenerate` integrate the gate before caching;
  `SYSTEM_PROMPT` mirror sync; `PAGE_API_SURFACE` mirror sync; `classification_prompt` wording
- `prettyplay/engine/steering` — `SYSTEM_PROMPT` mirror sync; `PAGE_API_SURFACE` mirror sync;
  the regeneration path through steering carries the same gate
- `prettyplay` (root) — only if the gate wiring requires composition changes
- `example/` — stale cache deletion
- Practices: `.goga/usages/prompts/generation.md`, `.goga/usages/cooks/playwright.md`,
  `.goga/usages/cooks/openai.md`, `.goga/usages/cooks/anthropic.md` (the latter three already
  updated as part of task formulation), `prettyplay/driver/.usages/facade.md`

## Notes

- Decisions fixed during formulation (beyond the ADR):
  - the gate toggle is named `generation_approve`, env `PRETTYPLAY_GENERATION_APPROVE`,
    default `True` — chosen for the `generation_*` family consistency (`generation_prompt`
    already covers regeneration in this codebase's naming)
  - the task document carries illustrative examples only (current case-sensitive behavior, the
    findings verdict shape) — no target API signatures are fixed here
- Open questions handed to the design stage: the exact signature/shape of the case-insensitive
  text assertion capability (parameter vs separate call); the gate call placement within the
  cell structure (port operation vs engine-owned call) and the content of the gate's own system
  prompt; docs placement of the new setting description.
- The ADR open questions about facade extension mechanism and facade-wide case consistency are
  explicitly out of scope (future tasks).
- Usage-file updates (playwright/openai/anthropic cooks) were applied and approved during
  formulation; `goga lint` passes (10 cells, 0 errors).

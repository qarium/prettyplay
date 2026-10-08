# Runtime step memory with Jinja result declarations

## Current State

- `step`/`expect` accept only `text: str` plus the keyword-only `tries`/`delay`; steps are plain sentences with no templating, and there is no `vars` parameter.
- Generated step code has the fixed form `def step(page) -> None` — results are not returned. `run_step_code` returns nothing, although the driver contract `PageFacade.run` already passes plain data back (`result: T`).
- There is no memory between steps: an observation made on one page cannot be reused in a later step without author-written Python transfer code.
- Generation receives the raw step sentence (`.goga/usages/prompts/step_generation.md`); the LLM receives neither input values nor result declarations.
- Cache addressing is `normalize_step_text` (casefolded) + `cache_key` + step type; the engine cycle (`StepGenerator`, `StepHealer`, `GroupRecovery`, `StepSteering`, `SettleWindow`) carries no execution results.
- Jinja is not a project dependency.

Decision documents: `adr.md` and `prd.md` in this topic directory.

## Description

Implement runtime step memory for PrettyPlay per the ADR: standard Jinja templates in ordinary steps plus a `{% var name %}` extension for capture declarations; separate call-local string inputs through the reserved `vars` namespace; a generated step with captures returns a dictionary of declared names to observed strings; deterministic validation and atomic acceptance publish the values to the memory of the current test execution; cached and strict replay use current-run values — cached code re-reads captures from the current page with current input bindings.

Rendering starts from a snapshot of memory and call inputs and produces a plain-text instruction, the current input bindings, and the declarations of the result tags actually executed. The LLM receives the prepared instruction and the input/result binding information needed for execution; it is not tasked with translating raw Jinja control flow into Python. Substituted data is never rendered again; automatic HTML escaping is disabled.

New captures become visible after step acceptance; a same-step read observes the previous value or fails if unavailable. Ordinary missing-value interpolation fails with the unavailable name; author-written `default` and `is defined` retain standard behavior; generation and healing must not invent fallbacks. Failed or rejected attempts publish nothing. Successful execution results are carried through polling, generation, healing, group recovery, and steering — an accepted step is never executed again merely to recover its return value.

## Usage Examples

Capture, navigate, and verify:

```python
with PrettyPlay("item-name") as t:
    t.step("Open https://shop.example/products")
    t.step("Read the first item name into {% var name %}")
    t.step("Open the item named {{ name }}")
    t.expect("The page contains {{ name }}")
```

Several results and dependent captures:

```python
t.step("Read the first item name into {% var first_name %} and the second item name into {% var second_name %}")
t.step("For the item named {{ first_name }}, read its tags into {% var tags %}")
t.expect("The page contains {{ tags }}")
```

Separate inputs for one call:

```python
t.expect("The page contains {{ name }} and {{ vars.expected }}", vars={"expected": "Details"})
```

Escaping literal Jinja in existing sentences:

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

## Scope

**In scope:**

- Jinja rendering of ordinary step sentences: an environment with `StrictUndefined` and the `{% var %}` capture extension; a render from the memory and input snapshot produces the plain-text instruction, the current input bindings, and the declarations of the tags actually executed.
- Authoring surface: `step`/`expect` gain the keyword-only `vars: dict[str, str] | None`; memory and `vars` are separate namespaces; `vars` is reserved; capture tags are invalid in `expect`; duplicate declarations within one render and non-Jinja-compatible or reserved capture names are authoring errors before browser execution.
- Per-test-execution memory: all captured values of a step publish together after full acceptance (including any required candidate-compliance check); a successful recapture replaces the previous value; a failed or rejected step publishes nothing; navigation does not discard memory; memory does not cross test boundaries.
- Result flow through the agent cycle: `run_step_code` returns the step's dictionary; deterministic result validation (exact declared keys, string values, nonblank text); result-contract violations lead to corrective generation where non-strict execution permits it within existing budgets, strict fails without generation; results of the accepted execution are carried through polling, generation, healing, group recovery, and steering without an extra execution; ordinary retries retain the prepared instruction, recovery that re-invokes a step prepares it against the current context.
- Generation practice update (`.goga/usages/prompts/step_generation.md`): the request carries the prepared instruction and the input/result binding information; the fixed code form gains the result return for steps with declarations; steps without declarations keep success-without-result behavior.
- Cache identity stays on the original step template with the existing scenario and step-kind distinctions; runtime values never enter the identity. Template addressing must distinguish semantically different Jinja source, including case-sensitive names and significant whitespace inside expressions, while ordinary non-template sentences retain their existing normalization. Cached code consumes current input bindings and performs capture reads again. The key encoding is an architectural decision.
- Authoring documentation: examples, literal-template escaping, Python string-formatting expectations, and the accepted changed-operation replay limitation.
- Tests per the project conventions.

**Out of scope:**

- Inferring memory references from unnamed phrases; sharing or restoring memory across test executions; memory listing, deletion, import, or export APIs.
- Structured captured data, non-string captured values, or a general facility for persisting computed values (standard template calculations stay available for preparing instructions).
- Translating raw Jinja control flow into generated Python, branch-specific cache identities, or a new semantic correctness check on every replay.
- Automatic detection of a changed operation inside a cached template when the old code still succeeds — an explicitly accepted limitation.
- Additional template-loading or customization infrastructure; redesign of unrelated cache, reporting, and recovery behavior.

## Acceptance Criteria

- An author completes capture, navigation, and verification through ordinary `step`/`expect` calls and explicit template syntax without Python transfer code.
- The destination check passes only when its condition using the earlier observation holds and fails through the existing expectation-failure experience when it does not — never by substituting a newly read value.
- New observations for the same operation work on later cached and strict executions without regenerating otherwise valid code; strict remains replay-only with no new LLM checks.
- Templates that differ in the meaning or case of Jinja names (for example, `{{ name }}` and `{{ Name }}`) do not share cached code; ordinary non-template sentence normalization remains compatible.
- Multiple captures publish together; independent names stay independent; successful recaptures replace values; failed captures preserve previous successful values and publish nothing.
- Invalid returned result shape, names, or values cause deterministic failure and applicable corrective generation rather than fabricated success; values are actually read from the page.
- Memory and `vars` remain distinct; missing ordinary references fail with the unavailable name; explicit author-written Jinja absence handling behaves as authored.
- Capture declarations are invalid in `expect`; duplicate declarations in one render fail before browser execution; an inactive branch declares nothing.
- Recovery uses results from the accepted execution without executing it again merely to obtain them; group restart selection remains unchanged and accepted repeated captures update memory.
- Separate tests remain isolated, concurrent runs included; existing non-template scenarios retain behavior; literal-Jinja escaping and the changed-operation limitation are documented.
- The full test suite passes (`pytest tests/ -x`) and lint stays clean (`ruff check`).

## Stack

- **Frameworks:** none new — a Python 3.10+ library (`pyproject.toml`, setuptools).
- **Libraries:** Jinja (`jinja2>=3.1`, new — environment, `from_string` templates, the extension mechanism for `{% var %}`); pydantic v2 (existing, typed models); playwright, openai, anthropic, json-repair, tomli (existing, unchanged).
- **Infrastructure:** none.

## External Dependencies

| Component | Usage file | Status |
|-----------|------------|--------|
| jinja2 | `.goga/usages/cooks/jinja.md` | created |
| playwright | `.goga/usages/cooks/playwright.md` | existing |
| pydantic | `.goga/usages/cooks/pydantic.md` | existing |

Synced usage files are managed by `goga usages sync` — reference them read-only, never create or update them in the task.

## Risks and Constraints

- Coordinated change across the whole agent cycle (executor, generator, healer, groups, steering, polling) is the main integration risk; the ordinary non-template path must stay behaviorally identical.
- Strict mode introduces no generation, healing, or replay checks; cache misses and execution failures keep their established strict-mode consequences.
- The cache address stays keyed on the original template, preserving semantic distinctions in Jinja source; a changed item name for the same operation must work through cached and strict replay.
- Existing scenarios containing literal Jinja syntax now require standard `raw` escaping — the only intentional behavioral change to existing scenarios.
- Accepted limitation: a template that changes the operation itself may let old cached code succeed at the previous operation without triggering healing; automatic correctness across such changes is outside this task.
- Generated step code keeps importing from `playwright.sync_api` and the standard library only — Jinja stays a library-side dependency of rendering, never an import of generated step code.
- Function signatures, context transport, binding/cache serialization, and contract layout are deliberately left to architectural design; this task records behavior and constraints.
- Test isolation and the unchanged group-recovery restart behavior must be verified by tests.

## Scope Estimate

Single task — no decomposition. The rendering subsystem and the agent-cycle result flow are one coherent feature: neither half delivers independent value alone. The architectural stage decides cell boundaries (including whether the template/memory subsystem becomes a separate cell).

## Existing Architecture

Affected cells (per `goga schema`):

- `prettyplay` — the facade: `PrettyPlay.step`/`expect` (the `vars` parameter), `StepGroup.step`/`expect`, `StepExecutor` (the render point, the memory of the test, result acceptance and publication).
- `prettyplay/engine` — `StepGenerator`, `StepHealer`, `run_step_code` (result return), `check_step_compliance` (results publish after the gate); the generation practice `system_prompt`.
- `prettyplay/llm` — the provider generation contract and both provider implementations must convey the prepared instruction and input/result bindings to the LLM; exact signatures remain for architectural design.
- `prettyplay/engine/polling` — `settle`/`SettleWindow` must carry the result of the successful re-execution.
- `prettyplay/engine/groups` — `GroupRecovery` carries results through row regeneration and repeated steps.
- `prettyplay/engine/steering` — `StepSteering` carries results of the accepted execution.
- `prettyplay/cache` — `StepIdentity`/`normalize_step_text` keep the identity on the original template sentence while distinguishing semantically different Jinja source; ordinary non-template normalization stays compatible.
- `prettyplay/driver` — no change required: `PageFacade.run` already returns plain data.

Practices: `.goga/usages/prompts/step_generation.md` (generation practice), `.goga/usages/cooks/jinja.md` (Jinja patterns, created by this task).

## Notes

- The four usage examples above were approved verbatim from the ADR/PRD.
- Stack approved: `jinja2>=3.1` added to `[project] dependencies`; all other dependencies unchanged.
- Open for architectural design: function signatures, context transport, binding/cache serialization, contract layout.
- Decisions recorded in `adr.md`; product behavior in `prd.md` (same topic directory).

# Design Document: `step-memory`

<!-- Topic directory: `.goga/history/2026/step-memory/`. Base branch: `origin/0.0.x` (all changes in the working tree). -->

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/engine/renderer/CODEMANIFEST` — **NEW cell**: the step-sentence preparation (rendering, memory, result validation). Imports `PrettyplayError` + `taxonomy` from `prettyplay/failures`; practices `conventions`, `jinja`.
- `prettyplay/cache/CODEMANIFEST` — template-aware `normalize_step_text` (template sentences address verbatim: NFC + trim; ordinary sentences keep the casefold pipeline); global annotation extended.
- `prettyplay/llm/CODEMANIFEST` — `generate_step_code` takes `instruction`, `inputs`, `declarations` (renamed from `step_text`); `check_instruction_compliance` the same three; `classify_step_failure.step_text` now the prepared instruction; `classify_group_failure` gains `previous_steps`; `ScenarioStep` gains `instruction`; provider algorithm annotations extended.
- `prettyplay/engine/polling/CODEMANIFEST` — `settle` and its `execute` callable carry the successful execution's result through untouched.
- `prettyplay/engine/CODEMANIFEST` — `generate`/`regenerate`/`heal`/`check_step_compliance` take `PreparedStep` (+ `memory` for the loops); `run_step_code` returns the step's result; `classify_step_failure.step_text` is the prepared instruction; prompt practices extended (INPUTS/RESULTS blocks, result contract).
- `prettyplay/engine/groups/CODEMANIFEST` — `GroupStepOutcome` gains `instruction` and `vars`; `classify_group_failure` gains `previous_steps`; `recover` takes `prepared` + `memory`, keeps recovery-local scenario/trace views, re-renders row steps, publishes at each row acceptance.
- `prettyplay/engine/steering/CODEMANIFEST` — `steer` takes `prepared` + `memory`; the dialog validates each green turn's result and publishes with the write-back.
- `prettyplay/CODEMANIFEST` (root) — facade `step`/`expect` and group `step`/`expect` gain the keyword-only `vars`; `StepExecutor` is the render point, owns the per-test `StepMemory`, validates replayed results and publishes them; `ScenarioStep`/trace records carry both texts; `execute` threads `vars`.

### New Entities

- `PreparedStep(instruction, inputs, declarations)` — the immutable render product; `prettyplay/engine/renderer/render.py`.
- `render_step(text, step_type, memory, vars)` — the render point of every step execution and recovery re-invocation; `render.py`.
- `StepMemory()` with `snapshot()` / `publish(captures)` — the per-test memory of captured observations; `memory.py`.
- `validate_step_result(prepared, result)` — deterministic acceptance of a returned step result; `validation.py`.

### Changed Entities

- `normalize_step_text` — template/ordinary split (markers `{{`, `{%`, `{#`).
- `generate_step_code` / `check_instruction_compliance` / `classify_group_failure` (LLM port) — prepared instruction, INPUTS/RESULTS blocks, PREVIOUS STEPS in group diagnosis.
- `ScenarioStep` — new `instruction` field (sentence stays the addressing artifact).
- `GroupStepOutcome` — new `instruction` + `vars` fields; `render()` renders the instruction line.
- `settle` / `run_step_code` — result carriage (`dict[str, str] | None`).
- `StepGenerator.generate` / `regenerate`, `StepHealer.heal`, `check_step_compliance`, `classify_group_failure` (engine cell wrapper), `GroupRecovery.recover`, `StepSteering.steer` — `PreparedStep` + `StepMemory` threading, validation and publication at acceptance.
- `PrettyPlay.step` / `expect`, `StepGroup.step` / `expect` — keyword-only `vars`; string-only validation at the call.
- `StepExecutor.execute` — render → identity → cycle; replay validation + publication; engines receive the render product.

### Deleted Entities

- None.

### Usages and Annotations Changes

- New practice `.goga/usages/cooks/jinja.md` — the Jinja environment, the `{% var %}` capture extension, namespaces, missing-value policy (connected as `jinja` in the renderer).
- `.goga/usages/prompts/step_generation.md` — STEP is the prepared instruction; new INPUTS/RESULTS inputs; the two code forms (`-> None` / `-> dict[str, str] | None`); the RESULTS rule (read from the page, never fabricate).
- `.goga/usages/prompts/group_diagnosis.md` — PREVIOUS STEPS block of prepared instructions; earliest_step quotes a visible instruction.
- Engine inline `compliance_prompt` — INPUTS/RESULTS inputs; the RESULTS exact-key return contract rule.
- Renderer `.usages/`: `rendering.md`, `memory.md`, `validation.md` (new, consumer documentation).
- Updated cell `.usages/`: `addressing.md` (template addressing), `steps.md` (vars + templates + memory), `lifecycle.md` (strict replay of template steps), `generation.md` / `healing.md` (prepared instruction threading), `recovery.md` (re-render, local views, publication), `settle.md` (result carriage), `steering.md` (validation + publication), `providers.md` (prepared-instruction/input-bindings/result-declarations/compliance parity).
- `pyproject.toml` — `jinja2>=3.1` added to `[project].dependencies`.

## Applied Fixes

### Fixed CODEMANIFEST Defects

- `prettyplay/llm/CODEMANIFEST` (`generate_step_code` Requirements): the block-order bullet said "…RESULTS block, PAGE URL line, then the remaining scenario blocks", contradicting the thrice-stated page-URL parity rule ("immediately after the PAGE SNAPSHOT block"). Reworded to: INPUTS/RESULTS render immediately after the STEP line; the remaining scenario blocks keep their current order and positions — GROUP PROMPT immediately before PREVIOUS STEPS, the PAGE URL line immediately after the PAGE SNAPSHOT block (reason: interface↔interface consistency; approved by user).
- `prettyplay/llm/CODEMANIFEST` (`OpenAIProvider` / `AnthropicProvider`, "The compliance operation"): the block enumeration omitted the new optional INPUTS/RESULTS blocks; extended to "INSTRUCTIONS, STEP (with its STEP TYPE line), the optional INPUTS and RESULTS blocks, ATTEMPT HISTORY and CODE" (reason: annotations↔entity consistency; approved by user).
- `prettyplay/cache/CODEMANIFEST` + `prettyplay/cache/.usages/addressing.md`: template detection markers extended from `{{` / `{%` to `{{` / `{%` / `{#` — a comment-only sentence no longer breaks the "instruction equals sentence for a non-template step" invariant (reason: type↔mutation consistency; user chose option A).

### Resolved Ambiguities (user decisions, no contract edit needed)

- Hook payloads (`on_step_started` / `on_step_failed` / `on_step_finished`) carry the **raw sentence** — the reporting surface is unchanged; the prepared instruction is visible inside the rendered failure text (`error` payload). Option A.
- Cell `.usages/` refresh: `generation.md` (honest-inputs bullet, group-steps bullet, classification-call bullet, `ScenarioStep` examples with `instruction=`) and `healing.md` (scenario-context bullet, example) updated.

## Entity Interaction and Data Flow

### Interaction Diagram

```
author                facade (scenario.py / groups.py)
  │ t.step(text, vars={"expected": "D"})        # keyword-only vars, str-only validated at the call
  ▼
StepExecutor.execute(step_text, step_type, page, group, tries, delay, vars)
  │ 1. on_step_started(raw sentence) → quiet delay
  │ 2. render_step(text, step_type, memory, vars) ──► renderer.render_step
  │       │ StepMemory.snapshot() + vars → Jinja (StrictUndefined, autoescape=False,
  │       │ {% var %} extension) → PreparedStep(instruction, inputs, declarations)
  │       └ authoring errors → PrettyplayError (before any browser execution)
  │    StepIdentity ← normalize_step_text(ORIGINAL step_text)   [cache cell]
  │ 3. cache.load(identity)
  │    ├─ HIT:  url pair → settle(run_step_code, …) → result
  │    │        validate_step_result(prepared, result)
  │    │          ├─ valid → memory.publish(captures)      [acceptance = validated replay]
  │    │          └─ violation (AssertionError) → step 4 failed-check paths
  │    ├─ strict + MISS → IncurableStepError
  │    └─ MISS: generator.generate(identity, prepared, step_type, previous_steps,
  │              group_prompt, page, attempt_history, window, memory)
  │ 4. HIT failure → strict classify(prepared.instruction) | group recover | healer.heal(prepared, …, memory)
  │ 6. IncurableStepError (non-strict, interactive) → steering.steer(failure, identity,
  │              prepared, step_type, previous_steps, group_prompt, page, history, memory)
  │ 7. ScenarioStep(sentence, instruction, group_prompt) append; group trace
  │    GroupStepOutcome(sentence, instruction, step_type, tries, delay, vars, outcome, urls, identity)
  ▼
engines (generator / healer / recovery / steering)
  │ every request: provider.*(instruction=prepared.instruction, inputs=prepared.inputs,
  │                          declarations=prepared.declarations, …)
  │ acceptance: validate_step_result → check_step_compliance → memory.publish → cache.save
  ▼
LLM port (openai / anthropic — full parity)
  STEP TYPE line, STEP line, [INPUTS], [RESULTS], [GROUP PROMPT], PREVIOUS STEPS
  (instruction fields, group-marked), PAGE SNAPSHOT, PAGE URL, CHEAT SHEET,
  USER INSTRUCTIONS, HISTORY, RECOMMENDATION, USER GUIDANCE
```

### Data Flows

1. **Ordinary template step, cache miss (non-strict)** — `render_step` → `PreparedStep` → `generate` loop: request (instruction + INPUTS/RESULTS) → `settle(run_step_code)` → result → `validate_step_result` → `check_step_compliance` → `memory.publish` → cache store → `ScenarioStep` append.
2. **Cached replay of a template step** — render → identity → HIT → `settle` → result → validate → publish (the gate never runs on replay). Violation → failed-check paths (strict: classify by step type; group: recovery; ordinary: heal).
3. **Group row recovery** — executor traces the failed step (with instruction + vars) and delegates `recover(group_prompt, traces, prepared, …, memory)`; recovery copies scenario/trace views, initializes the active failure, diagnoses (`classify_group_failure` with `previous_steps`), re-renders each row step (`render_step` from the trace sentence + recorded vars + current memory), regenerates, validates, gates, publishes per step, updates the local views, returns the failed step's healed code.
4. **Steering turn** — banner shows the prepared instruction; each guidance turn requests with `prepared`; `y` runs via `run_step_code` → result → `validate_step_result` (violation = red turn, record `failed check`) → gate → `memory.publish` + cache write-back.
5. **Capture flow across steps** — step A: `{% var name %}` declares; accepted execution returns `{"name": "Book"}`; validation passes; publication; step B: `{{ name }}` reads the snapshot value "Book"; the model and the failure texts see the prepared instruction with "Book" embedded.

### Entity Dependencies

Initialization/composition order (leaves → root), unchanged wiring plus the renderer:

```
failures → config → driver → reporting → cache → polling → renderer → llm → engine → groups → steering → executor → scenario(PrettyPlay)
```

- The renderer depends only on `prettyplay/failures` (`PrettyplayError`, `taxonomy`) and `jinja2`.
- `engine` imports `PreparedStep`, `StepMemory`, `validate_step_result` from the renderer (not `render_step` — the engine never re-renders).
- `groups` additionally imports `render_step` (row re-render).
- `steering` imports `PreparedStep`, `StepMemory`, `validate_step_result`.
- The root imports all four renderer types; the executor constructs the per-test `StepMemory` and is the only render point outside recovery.
- No import cycles (verified by `goga schema`: renderer sits under engine, all four consumers point to it, nothing points back).

## Code Stack Trace

### Trace: `render_step`

#### Chain
1. **Input**: executor step 2 (or recovery row step 5) calls `render_step(text=step_text, step_type, memory=self._memory, vars=vars)`; `text` is the raw template source; `vars` is the validated call-local dict or `None`.
2. **Snapshot**: `memory.snapshot()` → a `dict[str, str]` copy; `vars` None → `{}`. The step's own new captures are invisible — rendering reads the pre-step snapshot → checkpoint: read-only, no memory mutation — **passed**.
3. **Compile**: build a per-call `jinja2.Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])`; `environment.from_string(text)`. Parse-time tag validation: the token after `var` must be a single Jinja identifier → otherwise `PrettyplayError` naming the tag → checkpoint: matches `jinja` practice — **passed**.
4. **Render**: `template.render(snapshot, vars=vars_dict)`. A reached `{% var name %}` records its name into the per-render declaration list and renders to empty text; the reserved name `vars` and a repeated reached name raise `PrettyplayError`; an ordinary unavailable interpolation raises `UndefinedError` → caught → `PrettyplayError` naming the missing name; author-written `| default(...)` / `is defined` behave as authored; `set` stays template-local; `raw` blocks emit literal text → checkpoint: separate namespaces (`{{ name }}` = memory, `{{ vars.x }}` = input), substituted values never re-rendered — **passed**.
5. **Assertion gate**: `step_type == "assertion"` and declarations non-empty → `PrettyplayError` (captures invalid in `expect`); inactive branches declared nothing → no error → checkpoint: matches the facade contract — **passed**.
6. **Output**: `PreparedStep(instruction=rendered_text, inputs=vars or {}, declarations=[… in reach order])` — immutable; identity untouched, browser untouched.

#### Checkpoint Summary
- Snapshot isolation: passed (a same-step read observes the previous value or fails).
- StrictUndefined + authored defaults: passed (loud missing names; authored absence honored).
- Assertion/capture exclusivity: passed.
- Data-never-template: passed (`autoescape=False`, no second render pass).

### Trace: `StepMemory.snapshot` / `StepMemory.publish`

#### Chain
1. **Input**: `snapshot()` at render time; `publish(captures)` at an acceptance point (executor replay, engine gate pass, recovery row acceptance, steering green turn).
2. `snapshot()` returns `dict(self._values)` — a stable copy → checkpoint: later publishes never mutate a taken snapshot — **passed**.
3. `publish(captures)`: every name present in `captures` replaces its value; absent names keep theirs; all captures of one step land together in one call → checkpoint: atomic replace-or-keep semantics — **passed**.
4. **Output**: the internal values dict grows monotonically (names are never removed); survives navigation; dies with the test (one executor → one memory).

#### Checkpoint Summary
- One publication per accepted execution: passed (callers publish exactly at acceptance).
- Cross-test isolation: passed (memory is executor-owned state, never module-global).

### Trace: `validate_step_result`

#### Chain
1. **Input**: `prepared` (the declaration set) and `result` — the step function's return passed back through `page.run` by `run_step_code` (`PageFacade.run(action) -> _T` already returns the callable's outcome → checkpoint: the driver primitive carries plain data back — **passed**).
2. No declarations: `result is None` → `{}` (success without result); non-None → violation → checkpoint: old cached code (`-> None`) replays clean — **passed**.
3. Declarations present: `result is None` → violation (missing result).
4. Reject a non-dict result with a deterministic `AssertionError` before inspecting keys (the generated function can return any Python object at runtime); otherwise check key set equality with `declarations` (order-free); a missing or unexpected name → violation naming it.
5. Every value `isinstance(str)` and `value.strip() != ""` (non-blank); offenders named → checkpoint: deterministic on the inputs alone — **passed**.
6. **Output**: the validated dict, ready for `publish`. A violation raises `AssertionError` with the deterministic text → the calling cycle formats it via `format_step_error` (AssertionError → message with no prefix, aria tail stripped) → the existing failed-check channel.

#### Checkpoint Summary
- AssertionError channel compatibility: passed (enters classification / bounded healing / strict-by-type unchanged).
- No fabrication/repair: passed.

### Trace: `normalize_step_text` (changed)

#### Chain
1. **Input**: the raw sentence from the executor.
2. Contains any of `{{`, `{%`, `{#` → NFC + trim only; case-sensitive names and significant expression whitespace survive verbatim → checkpoint: `{{ name }}` ≠ `{{ Name }}` addresses — **passed**.
3. Otherwise → NFC, trim, collapse internal whitespace, casefold (unchanged pipeline) → checkpoint: ordinary sentences byte-identical to today — **passed**.
4. **Output**: the addressing key of `StepIdentity`; runtime values never enter (rendering happens after identity).

### Trace: `StepExecutor.execute` (changed)

#### Chain
1. **Input**: facade/group delegation with `step_text`, `step_type`, `page`, optional `group`, `tries`, `delay`, `vars` (already string-validated at the facade).
2. `on_step_started(raw sentence)`; quiet `delay` sleep → checkpoint: unchanged event surface (raw sentence) — **passed**.
3. `prepared = render_step(...)` — authoring errors raise `PrettyplayError` here (browser untouched, identity untouched) → checkpoint: before any execution, per contract — **passed**.
4. `identity = StepIdentity(cache_key, step_type, normalize_step_text(step_text))` — **from the ORIGINAL sentence**, never the instruction; `window`, empty `attempt_history`, group URL bracket.
5. Cache HIT: URL pair → `result = settle(run_step_code, cached.code, page, window)` (result carriage) → `validate_step_result(prepared, result)` → valid: `self._memory.publish(captures)` (the gate never runs on replay); violation: route to step 6 with `format_step_error(violation)` and the replay URL pair → checkpoint: type flow `dict | None` through `settle` — **passed**.
6. HIT failure (execution error or validation violation): strict → `classify_step_failure(step_text=prepared.instruction, …)` by step type; group → failed trace append (`instruction`, `vars` included) + record 0 + `recover(group_prompt, traces, prepared, …, memory)`; ordinary → record 0 + `heal(step, error, prepared, …, memory)`.
7. MISS non-strict: `generate(identity, prepared, step_type, self._scenario, group_prompt, page, attempt_history, window, memory)`; strict MISS → `IncurableStepError`.
8. Steering intercept on `IncurableStepError` (non-strict, interactive): `steer(failure, identity, prepared, step_type, scenario, group_prompt, page, history, memory)` — healed continues as success.
9. `self._scenario.append(ScenarioStep(sentence=step_text, instruction=prepared.instruction, group_prompt=…))`; group trace `GroupStepOutcome(sentence, instruction, step_type, tries, delay, vars, outcome, url_before, url_after, identity)` → checkpoint: both texts recorded exactly once — **passed**.
10. `on_step_passed` / `on_step_failed` (raw sentence + `str(error)` — the render carries the prepared instruction) / `on_step_verdict` / `on_step_finished`.

#### Checkpoint Summary
- Render-before-identity ordering: passed (authoring errors precede cache access).
- Memory lifecycle: passed (constructed in `__init__`, one per test, never crosses tests).
- Event surface: passed (raw sentence; decided with user, option A).

### Trace: `StepGenerator.generate` / `regenerate` (changed)

#### Chain
1. **Input**: `prepared`, `memory`, plus the unchanged threading.
2. Budget `try_generation`; collect snapshot/screenshot; `provider.generate_step_code(prompt=SYSTEM_PROMPT, user_instructions, instruction=prepared.instruction, step_type, previous_steps, group_prompt, inputs=prepared.inputs, declarations=prepared.declarations, snapshot, page_url, screenshot, cheat_sheet, attempt_history=[r.render() …], recommendation, guidance)` → checkpoint: port signature match (`instruction`, `inputs`, `declarations`) — **passed**.
3. `settle(run_step_code, code, page, window)` → `result`; URL pair brackets the attempt.
4. Success → `validate_step_result(prepared, result)`: violation → append record (`failed check`, violation text) → the step-6 failed-check decision table unchanged; valid → `check_step_compliance(config, provider, prepared, step_type, code, history)` → empty findings (or medium/low + WARNING) → `memory.publish(captures)` → `_store` → return; high finding → record (`compliance blocked`), nothing publishes, retry with grown history → checkpoint: publish exactly once, after validation and gate — **passed**.
5. The funded regeneration (bounded healing) runs the same acceptance inline: execute → validate → gate → publish → store → checkpoint: consistent with "captures publish exactly once" — **passed**.
6. `regenerate` (healing loop): identical acceptance; budget exhaustion raises `IncurableStepError` carrying the entry verdict — nothing publishes.

#### Checkpoint Summary
- Violation ≡ failed check (group suppression, classification, one funded retry): passed.
- Publication atomicity: passed.

### Trace: `StepHealer.heal` (changed)

#### Chain
1. **Input**: `step`, `error`, `prepared`, `step_type`, `previous_steps`, `page`, `attempt_history` (record 0 seeded by the executor), `window`, `memory`.
2. `classify_step_failure(config, provider, step_text=prepared.instruction, code=step.code, error, page)` → verdict → checkpoint: classification sees the prepared instruction — **passed**.
3. product_defect → `ProductDefectError`; incurable → `IncurableStepError`; rot/fixable → `generator.regenerate(identity, prepared, step_type, previous_steps, None, page, attempt_history, recommendation, window, memory)` — the loop validates, gates, publishes and stores → `on_healed` → return.

### Trace: `GroupRecovery.recover` (changed)

#### Chain
1. **Input**: `group_prompt`, `traces`, `prepared` (executor's render product of the failed step), `step_type`, `previous_steps`, `identity`, `attempt_history`, `page`, `window`, `memory`.
2. Cycle cap `open_group_cycle` → refused → `IncurableStepError` (authored verdict).
3. **Local views**: `local_scenario = [r.model_copy(update={…}) for r in previous_steps]`-style copies; `local_traces` likewise; the caller's lists are never mutated → checkpoint: immutable caller records preserved — **passed**.
4. **Active failure** initialized from `prepared`, `step_type`, `identity`, `attempt_history`; underlying error ← last record's error.
5. `classify_group_failure(config, provider, group_prompt, local_traces, local_scenario, active.instruction, step_type, active.history, page)` → the port renders GROUP PROMPT, optional PREVIOUS STEPS (instruction fields, group-marked), GROUP STEPS (trace instructions), STEP, HISTORY, PAGE SNAPSHOT → checkpoint: the model never sees raw Jinja — **passed**.
6. Verdict mapping unchanged (product_defect / outside-group / incurable raise; recoverable → row). `earliest_step` matches verbatim against the local traces' current instructions; outside match against the local scenario's instructions (group order, not sentence equality, locates occurrences — repeated sentences are handled by index).
7. Row (`earliest … failed step`, group steps only): per step — quiet declared delay → `fresh = render_step(trace.sentence, trace.step_type, memory, trace.vars)` → `refresh_healing(trace.identity)` → `regenerate(identity=trace.identity, prepared=fresh, …, group_prompt, local_scenario_view, row_history, recommendation, row_window, memory)` → inside the loop: execute → validate → gate → publish at acceptance → store → update the occurrence's instruction in `local_scenario`/`local_traces` (new records; located by index) → `on_healing_started` / `on_healed` + `group_row_recovered` log → checkpoint: fresh render against current memory; publication per step, never rolled back — **passed**.
8. Repeat failure: update the active failure (fresh `PreparedStep`, that trace's identity, grown row history, underlying error), mark the occurrence failed in the local view preserving its fresh instruction, re-enter the cycle; full row success returns the healed step of the **originally** failed step.
9. Re-render authoring error (defensive; unreachable in practice since memory never loses names): propagates loudly as that row step's failure — never swallowed, never retried silently.

#### Checkpoint Summary
- Local-view isolation: passed.
- STEP/HISTORY freshness per cycle: passed.
- The failed step's captures publish with its acceptance; never re-executed to recover them: passed.

### Trace: `StepSteering.steer` (changed)

#### Chain
1. **Input**: `failure`, `identity`, `prepared`, `step_type`, `previous_steps`, `group_prompt`, `page`, `attempt_history`, `memory`.
2. Banner: the prepared instruction, failed code, terminal error render, URL, screenshot path, commands.
3. Guidance turn request: `generate_step_code(…, instruction=prepared.instruction, inputs=prepared.inputs, declarations=prepared.declarations, guidance=message, …)` with group framing when applicable.
4. Approval → `result = run_step_code(code, page)` (no settle) → `validate_step_result(prepared, result)`: violation shown in the dialog + record (`failed check`, violation text) → back to the prompt; valid → `check_step_compliance(prepared, step_type, code, history)` → empty/medium-low → `memory.publish` + `CachedStep` + `on_healed` + return healed; high → shown + record (`compliance blocked`); gate hard failure → dialog ends, return `None` → checkpoint: publication only with the write-back — **passed**.

### Trace: LLM port providers (changed)

#### Chain
1. **Input**: `instruction: str`, `inputs: dict[str, str]`, `declarations: list[str]` as primitives; `previous_steps: list[ScenarioStep]` for group diagnosis.
2. `build_fields_text`: sections `[STEP TYPE + STEP, [INPUTS: name = value …], [RESULTS: names + contract], [GROUP PROMPT], PREVIOUS STEPS (record.instruction, group-marked), PAGE SNAPSHOT, [PAGE URL], CHEAT SHEET, [USER INSTRUCTIONS], [HISTORY], [RECOMMENDATION], [USER GUIDANCE]]` → checkpoint: matches the reworded block-order requirement and the page-URL parity rule — **passed**.
3. `build_group_diagnosis_fields`: `[GROUP PROMPT, [PREVIOUS STEPS], GROUP STEPS (trace render lines — instructions), STEP, [HISTORY], PAGE SNAPSHOT, [USER INSTRUCTIONS last]]`.
4. `build_compliance_fields`: `[INSTRUCTIONS, STEP TYPE + STEP, [INPUTS], [RESULTS], [ATTEMPT HISTORY], CODE]`.
5. **Output**: one SDK call through `send_with_retries` per operation; strict parsers unchanged; frozen prompt mirrors updated from the practices.

#### Checkpoint Summary
- Provider parity (identical composition in both implementations): passed.
- Addressing independence (inputs/declarations never enter the address): passed.

## Algorithm Design

### `render_step` (renderer/render.py)

**Responsibility**: turn one step sentence + memory snapshot + call inputs into the single `PreparedStep` every request and failure carries; surface authoring errors before any execution.

**Algorithm:**
```
1. snapshot ← memory.snapshot(); inputs ← vars if vars is not None else {}
2. recorder ← []; environment ← Environment(autoescape=False, undefined=StrictUndefined,
   extensions=[VarExtension(recorder)])          # per call — concurrent tests stay isolated
3. TRY template ← environment.from_string(text)
   CATCH TemplateSyntaxError → PrettyplayError naming the template syntax problem and line;
   this includes malformed {% var %} tags, incomplete standard Jinja blocks/expressions,
   and TemplateAssertionError (a TemplateSyntaxError subclass)
4. TRY instruction ← template.render(snapshot, vars=inputs)
   CATCH UndefinedError → PrettyplayError naming the unavailable name
   (a reached {% var name %} appends name to recorder; the reserved name `vars` and a repeat
   of an already-recorded name raise PrettyplayError inside the render)
5. IF step_type == "assertion" AND recorder non-empty → PrettyplayError (captures invalid in expect)
6. RETURN PreparedStep(instruction=instruction, inputs=inputs, declarations=recorder)
```

**Errors:**
- `PrettyplayError` → malformed Jinja syntax, duplicate capture name / reserved `vars` / non-identifier name / unavailable name / capture in an assertion — loud and actionable, raised before any browser execution; the facade folds the traceback. Compile-time `TemplateSyntaxError` is translated with its message and `lineno` (per the [Jinja API](https://jinja.palletsprojects.com/en/stable/api/)).

**Edge Cases:**
- A capture tag inside a loop body reached twice → duplicate-name authoring error (a loop-carried single capture is invalid; the author declares per-iteration names or captures outside the loop).
- A capture inside an inactive branch → declares nothing.
- `{% raw %}{{ x }}{% endraw %}` → literal `{{ x }}` in the instruction.
- A captured value containing `{{ … }}` → embedded verbatim, never re-rendered.
- `vars=None` and `{{ vars.x }}` in the template → unavailable-name error naming `vars.x`.
- Memory name equal to an input name → both accessible (`{{ name }}` vs `{{ vars.name }}`).

### `StepMemory` (renderer/memory.py)

**Responsibility**: the per-test names namespace; read via snapshot, written only at acceptance points.

**Algorithm:**
```
construct: values ← {}
snapshot(): RETURN dict(values)                     # stable copy
publish(captures): FOR name, value IN captures: values[name] ← value
                   # absent names keep theirs; names never removed; one call = one accepted step
```

**Errors:** none (validated data only reaches publish).

**Edge Cases:**
- Recapture on a later replay/regeneration replaces the value (fresh observation wins).
- Navigation never touches memory; a second test's memory is a different object.

### `validate_step_result` (renderer/validation.py)

**Responsibility**: deterministic gate between an execution's return and publication.

**Algorithm:**
```
1. IF prepared.declarations empty:
     IF result is None → RETURN {}
     ELSE → violation "unexpected result without declarations"
2. IF result is None → violation "missing result"
3. IF not isinstance(result, dict) → violation "result must be a dictionary"
4. IF set(result) != set(prepared.declarations) → violation naming the missing/unexpected names
5. FOR name, value IN result.items():
     IF not isinstance(value, str) → violation naming name
     IF value.strip() == "" → violation naming name (blank observation)
6. RETURN dict(result)
```

**Errors:**
- Violation → `AssertionError` with the deterministic text (no colons requirement does not apply — it is a check text, formatted by `format_step_error` into the failed-check channel).

**Edge Cases:**
- Declaration-free legacy cached code returning `None` → accepted, empty captures.
- Values keep surrounding whitespace (`"  X  "` is non-blank, accepted untrimmed); `""` and `"   "` violate.
- A list, string, number or other non-dict return violates through `AssertionError` before key inspection; generated code's return annotation does not enforce the type at runtime.

### `StepExecutor.execute` (root/executor.py)

**Responsibility**: the render point and memory owner of the step cycle.

**Algorithm:**
```
1. emit on_step_started(step_text, step_type); IF delay is not None: sleep(delay)
2. prepared ← render_step(step_text, step_type, self._memory, vars)
3. identity ← StepIdentity(cache_key, step_type, normalize_step_text(step_text))
   window ← SettleWindow(polling_timeout, polling_delay, tries); attempt_history ← []
   group_url_before ← read_url(page) IF group
4. cached ← cache.load(identity)
5. IF cached is not None:
     url_before ← group bracket or read_url(page)
     TRY result ← settle(run_step_code, cached.code, page, window)
         captures ← validate_step_result(prepared, result); self._memory.publish(captures)
       CATCH error:
         route failure (formatted by format_step_error, replay URL pair):
           strict → classify(prepared.instruction) → raise by kind (quiet skip on LLM down)
           group  → failed trace + record 0 + recover(…, prepared, …, memory) → steering gate
           else   → record 0 + heal(step, error, prepared, …, memory) → steering gate
   ELIF strict → raise IncurableStepError(strict miss)
   ELSE → generate(identity, prepared, step_type, scenario, group_prompt, page, history, window,
                   memory) → group routing of its IncurableStepError → steering gate
6. scenario.append(ScenarioStep(sentence=step_text, instruction=prepared.instruction, group_prompt))
   group trace append (sentence, instruction, step_type, tries, delay, vars, outcome, urls, identity)
7. emit on_step_passed; failure path: on_step_failed(step_text, str(error)) → on_step_verdict →
   raise; finally on_step_finished(step_text, step_type, outcome)
```

**Errors:** authoring (`PrettyplayError`, before execution), taxonomy kinds (`ProductDefectError`, `IncurableStepError`, `LLMUnavailableError`, `ComplianceVerdictError`); strict-miss incurable.

**Edge Cases:**
- Strict + template step: rendering still happens first (memory must hold the names); a strict replay validates and publishes exactly like the ordinary replay.
- A declared `delay` sleeps before rendering — an authoring error surfaces after the pause (matches the numbered contract order).
- A step that dies before a trace record never re-arms group pauses (unchanged `_delegated` mechanics).

### `StepGenerator` loops (engine/generator.py)

**Responsibility:** candidate production with in-loop validation, gate and publication at acceptance.

**Algorithm (generate; regenerate = same loop, healing budget, no classification):**
```
per attempt:
  budget.try_generation(identity) or exhaustion table
  code ← provider.generate_step_code(…, instruction=prepared.instruction, inputs=prepared.inputs,
          declarations=prepared.declarations, previous_steps, attempt_history=[r.render() …])
  url pair; TRY result ← settle(run_step_code, code, page, window)
    CATCH AssertionError → record(failed check) → decision table (group suppress | classify |
      one funded retry with recommendation | final classification)
    CATCH Exception → record(execution failed) → next attempt
    ELSE captures ← validate_step_result(prepared, result)
      (violation → record(failed check) → decision table — identical channel)
      findings ← check_step_compliance(prepared, step_type, code, history)
      high → record(compliance blocked), standing ← finding, next attempt   # nothing publishes
      ELSE medium/low → WARNING; memory.publish(captures); store; RETURN step
the funded regeneration repeats the same acceptance inline (execute → validate → gate → publish → store)
```

**Errors:** unchanged taxonomy; violations are failed checks.

**Edge Cases:**
- Gate hard failures (`LLMUnavailableError`, `ComplianceVerdictError`) propagate immediately — nothing cached, nothing published.
- The funded regeneration publishes like any acceptance (exactly once).

### `GroupRecovery.recover` (engine/groups/recovery.py)

**Responsibility:** diagnosis over prepared instructions; the row as per-step re-render + regeneration + publication cycles.

**Algorithm:**
```
1. open_group_cycle(group_prompt) or raise (cycle cap)
2. local_scenario ← copies of previous_steps; local_traces ← copies of traces
   active ← (prepared, step_type, identity, attempt_history, error ← last record's error)
3. verdict ← classify_group_failure(…, local_traces, local_scenario, active.instruction,
              step_type, active.history, page)
4. product_defect / outside-root (matched against local_scenario instructions) / incurable →
   raise carrying the mapped verdict and active.error
5. row ← local_traces[index_of(earliest_step match):]   # no match → the active failure's occurrence
   refresh_healing per row identity
6. FOR each row trace (sequential):
     sleep(trace.delay) if declared
     fresh ← render_step(trace.sentence, trace.step_type, memory, trace.vars)
     row_history ← active history for the failed step / anchored record-0 list for earlier steps
     regenerate(trace.identity, fresh, trace.step_type, local_scenario_view, group_prompt,
                row_history, verdict.recommendation, SettleWindow(…, trace.tries), memory)
       # inside: execute → validate → gate → publish → store
     update the occurrence's instruction in local_scenario + local_traces (by index)
     on_healing_started / on_healed; group_row_recovered log
   RETURN the failed step's healed CachedStep
7. row failure → active ← (fresh prepared of that occurrence, its identity/type, grown history,
   fresh error); mark the occurrence failed in local_traces (keep the fresh instruction);
   GOTO 1 while cycles remain
```

**Errors:** unchanged; re-render authoring errors propagate loudly as the row step's failure.

**Edge Cases:**
- Repeated identical sentences: occurrences located by group order (index), never by equality.
- A later row failure never rolls back published captures of earlier accepted row steps.
- The caller's `previous_steps` / `traces` are never mutated.

### `StepSteering.steer` (engine/steering/steering.py)

**Responsibility:** guided regeneration on the prepared instruction; validated, gated, published green turns.

**Algorithm:** banner (prepared instruction) → prompt loop: local commands | guidance → request (instruction/inputs/declarations + guidance + history) → show code → `run? [y/N]` → `y`: `run_step_code` → `validate_step_result` (violation → red turn, record failed check) → gate (high → red turn, record compliance blocked; hard → end dialog, return None) → `memory.publish` + write-back + `on_healed` → return healed; `n`/Enter/quit → record rejected, back to prompt; quit/EOF/SIGINT/unreadable stdin → return None.

### `normalize_step_text` (cache/text.py)

```
markers ← any of "{{", "{%", "{#" in text
IF markers: RETURN NFC(text).strip()           # verbatim otherwise
ELSE: NFC → trim → collapse whitespace → casefold   # unchanged
```

### LLM providers (llm/_request.py builders + provider.py signatures)

- `build_fields_text(user_instructions, instruction, step_type, previous_steps, group_prompt, inputs, declarations, snapshot, page_url, cheat_sheet, attempt_history, recommendation, guidance)` — section order as traced; INPUTS lines `name = value`; RESULTS block lists the names + the return-contract sentence.
- `_previous_step_line(record)` renders `record.instruction` (+ group marking from `record.group_prompt`).
- `build_group_diagnosis_fields(…, previous_steps)` inserts the optional PREVIOUS STEPS block before GROUP STEPS.
- `build_compliance_fields(…, inputs, declarations)` inserts optional INPUTS/RESULTS after the STEP block.
- Port signatures renamed/extended exactly per the CODEMANIFEST (`instruction`, `inputs`, `declarations`; `classify_group_failure(…, previous_steps, …)`).
- Frozen mirrors updated in lockstep from the practices: `SYSTEM_PROMPT` (generator.py), `SYSTEM_PROMPT` (steering.py — cell-owned copy), `COMPLIANCE_PROMPT` (compliance.py), `GROUP_DIAGNOSIS_PROMPT` (groups/diagnosis.py), `CHEAT_SHEET` (unchanged content).

## Cross-cutting Concerns

- **Error handling**: two loud channels with a strict boundary — authoring errors (`PrettyplayError`, before any browser execution: duplicate/reserved/invalid capture names, unavailable names, capture-in-expect, invalid `tries`/`delay`/`vars` values) and result-contract violations (`AssertionError` from `validate_step_result`, formatted by `format_step_error` into the existing failed-check paths — classification, bounded healing, strict by step type). Terminal taxonomy failures carry the prepared instruction as the step text; the raw template sentence never reaches a request. Anti-masking unchanged: publication happens only after validation + gate; a published capture is never fabricated.
- **Validation**: facade-level parameter validation (positive `tries`, non-negative `delay`, string-only `vars` — a shared `_validate_vars` beside `_validate_tries`/`_validate_delay` in groups.py, used by facade and group methods); render-time name/tag validation; deterministic post-execution result validation. Validation never repairs: a violation is a failure.
- **Logging**: no new log records on the happy path; publication is silent; violations ride the existing attempt-record texts; `settle_retry` INFO records unchanged; retries/gate warnings unchanged. Step sentences (raw or rendered) may reach logs — the never-put-secrets rule covers both texts.
- **Caching**: the address stays the raw template sentence (NFC + trim for templates; the casefold pipeline for ordinary sentences); `vars` values, rendered values, INPUTS and RESULTS never enter the address — a changed observed value replays the same cached code, which re-reads captures on every execution. Documented accepted limitation: a template that changes the operation itself may let old cached code succeed at the previous operation.
- **Concurrency**: one `StepMemory` per executor (per test); a fresh Jinja `Environment` per `render_step` call — no shared mutable render state; everything within a test is sequential (the driver worker thread executes one unit at a time), so memory needs no locks.
- **Memory lifecycle**: created empty at executor construction; grows monotonically (publish replaces/adds, never removes); survives navigation; dies with the test object; never module-global.

## Usages Analysis

### `jinja` (`.goga/usages/cooks/jinja.md`, file form)
- **What it provides**: the Jinja environment contract (`autoescape=False`, `StrictUndefined`, `from_string`), the `{% var %}` extension mechanics, the memory/vars namespaces, the missing-value policy, `raw` blocks.
- **Where used**: renderer annotations (`render_step` algorithm references it); global renderer annotations.
- **Why chosen**: file form — an extensive practice reused by the renderer cell, evolving independently.
- **How exactly**: `Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])`, `from_string`, `template.render(snapshot, vars=inputs)`; extension subclasses `Extension`, parses the tag, emits an output node that renders to nothing and records the reached name.

### `taxonomy` (imported from `prettyplay/failures`)
- **What it provides**: the failure kinds and the structured render; the base kind (`PrettyplayError`) of authoring errors.
- **Where used**: renderer global annotations ("Use `taxonomy` from Imports for the base failure kind the authoring errors raise").
- **Why chosen**: authoring errors must be the loud actionable kind the facade already folds.
- Path: `prettyplay/failures/.usages/taxonomy.md` — read; consistent with the renderer's use (message-first constructor, single library base).

### `conventions` (`.goga/usages/conventions.md`)
- **What it provides**: Python rules — pydantic v2 `kw_only` + empty defaults, relative imports, Google docstrings, logging levels, test structure (`tests/engine/renderer/test_*.py`), validation commands.
- **Where used**: every changed cell's global annotations.
- **How exactly**: `PreparedStep` — pydantic `kw_only=True, frozen=True`, empty defaults; `StepMemory` — plain stateful class (not a data record); tests mirror `prettyplay/engine/renderer/`.

### `system_prompt` (`.goga/usages/prompts/step_generation.md`)
- **What it provides**: the generation system prompt — now STEP = prepared instruction, INPUTS/RESULTS inputs, the two function forms, the read-from-page RESULTS rule.
- **Where used**: engine `generate`/`regenerate`, steering guided requests; frozen mirrors in `generator.py` and `steering.py` change together with the file.

### `compliance_prompt` (engine inline)
- **What it provides**: the gate prompt with INPUTS/RESULTS inputs and the RESULTS exact-key contract rule.
- **Where used**: `check_step_compliance`; frozen mirror in `compliance.py`.

### `group_framing`, `classification_prompt`, `cheat_sheet`
- Unchanged content; consumed exactly as before; group framing now rides instruction fields.

### Imported Usages (renderer consumers)
- `rendering` from `prettyplay/engine/renderer` — root (executor render point), groups (row re-render patterns). Path: `prettyplay/engine/renderer/.usages/rendering.md`.
- `memory` from `prettyplay/engine/renderer` — root, engine, groups, steering (publication points, snapshot semantics). Path: `prettyplay/engine/renderer/.usages/memory.md`.
- `validation` from `prettyplay/engine/renderer` — root, engine, groups, steering (result acceptance, violation channel). Path: `prettyplay/engine/renderer/.usages/validation.md`.
- All imported practices exist and match the contracts (verified by reading each file; `goga lint` validates the references).

## `.usages/` Update

### Cell: `prettyplay/engine/renderer`
- New files `rendering.md`, `memory.md`, `validation.md` — created at apply-architecture; verified current against the CODEMANIFEST (render example, authoring-error list, lifecycle, publisher list, validation contract). No changes needed.

### Cell: `prettyplay/engine`
- **`generation.md`** → status: was outdated → **updated now**: honest-inputs bullet (prepared instruction), group-steps scenario-context bullet (instruction fields), classification-call bullet (prepared instruction), `ScenarioStep` examples with `instruction=`.
- **`healing.md`** → status: was outdated → **updated now**: scenario-context bullet (sentence + instruction + membership), example with `instruction=`.

### Cell: `prettyplay/cache`
- **`addressing.md`** — updated: identity-triple row (template/ordinary split), template-sentences section, marker set now `{{`, `{%`, `{#` (this session's fix).

### Cells: `prettyplay`, `prettyplay/engine/groups`, `prettyplay/engine/polling`, `prettyplay/engine/steering`, `prettyplay/llm`
- `steps.md`, `lifecycle.md`, `recovery.md`, `settle.md`, `steering.md`, `providers.md` — verified current against the changed CODEMANIFESTs (templates and memory authoring docs, strict replay semantics, row re-render and local views, result carriage, parity paragraphs). No further changes needed.

## Test Stack Trace

### General Setup

- New test package `tests/engine/renderer/` with `__init__.py`; pure unit tests need no mocks (pure functions + a real `StepMemory`).
- Facade/executor tests reuse the existing fakes pattern: a fake `PageFacade` (url reads, `aria_snapshot()`, `run(fn)` returning `fn(fake_page)`), a fake `LLMProvider` returning canned code, `tmp_path` cache roots.
- Frozen prompt mirrors are asserted verbatim against the practice files where such tests exist today (extend to the updated prompts).

### Source File Registry

- New: `prettyplay/engine/renderer/{__init__,render,memory,validation}.py`; tests under `tests/engine/renderer/`.
- Changed: `prettyplay/cache/text.py`; `prettyplay/engine/{generator,healer,compliance,classification,execution}.py`; `prettyplay/engine/polling/settle.py`; `prettyplay/engine/groups/{outcome,diagnosis,recovery}.py`; `prettyplay/engine/steering/steering.py`; `prettyplay/llm/{provider,models,openai_provider,anthropic_provider,_request}.py`; `prettyplay/{executor,scenario,groups}.py`.
- Corresponding test files updated; new cases below.

---

### Positive Tests

#### `test_render_substitutes_memory_value_into_instruction`

**Setup**: `memory = StepMemory()`; `memory.publish({"name": "Book"})`.

**Input**: `render_step("Open the item named {{ name }}", "action", memory, None)`.

**Trace**:
```
render_step(text="Open the item named {{ name }}", step_type="action", memory, vars=None)
  → memory.snapshot()            # {"name": "Book"}
  → environment.from_string(text); template.render({"name": "Book"}, vars={})
    returns: "Open the item named Book"
  → step_type "action", declarations [] — no assertion gate
  → PreparedStep(instruction="Open the item named Book", inputs={}, declarations=[])
```

**Assertions**:
```
prepared.instruction == "Open the item named Book"
prepared.inputs == {}
prepared.declarations == []
prepared.has_declarations is False
```

**Sufficiency**: the core rendering contract — actual values embedded, plain text; prevents regressions where requests would carry raw Jinja.

---

#### `test_render_reads_vars_namespace_separately_from_memory`

**Setup**: `memory.publish({"name": "Book"})`.

**Input**: `render_step("The page contains {{ name }} and {{ vars.expected }}", "assertion", memory, {"expected": "Details"})`.

**Trace**:
```
render_step(…, vars={"expected": "Details"})
  → snapshot {"name": "Book"}; inputs {"expected": "Details"}
  → template.render({"name": "Book"}, vars={"expected": "Details"})
    returns: "The page contains Book and Details"
  → assertion + declarations [] — no capture gate
  → PreparedStep(instruction="The page contains Book and Details",
                 inputs={"expected": "Details"}, declarations=[])
```

**Assertions**:
```
prepared.instruction == "The page contains Book and Details"
prepared.inputs == {"expected": "Details"}
```

**Sufficiency**: the two-namespace contract (`{{ name }}` memory vs `{{ vars.x }}` inputs); prevents one namespace overwriting the other.

---

#### `test_render_capture_tag_declares_result_and_renders_empty`

**Setup**: empty memory.

**Input**: `render_step("Read the first item name into {% var name %}", "action", memory, None)`.

**Trace**:
```
render_step(…)
  → render: {% var name %} reached → recorder ["name"], renders ""
    returns: "Read the first item name into "
  → PreparedStep(instruction="Read the first item name into ", inputs={}, declarations=["name"])
```

**Assertions**:
```
prepared.declarations == ["name"]
prepared.has_declarations is True
prepared.instruction == "Read the first item name into "
```

**Sufficiency**: the capture mechanism — a declaration is a slot, not a value; prevents instructions carrying tag syntax.

---

#### `test_render_inactive_branch_declares_nothing`

**Setup**: empty memory.

**Input**: `render_step("{% if false %}{% var x %}{% endif %}click Save", "action", memory, None)`.

**Trace**: render skips the branch → recorder empty → `PreparedStep(instruction="click Save", declarations=[])`.

**Assertions**: `prepared.declarations == []`; `prepared.instruction == "click Save"`.

**Sufficiency**: only reached tags declare — an unreachable declaration must not create a result obligation.

---

#### `test_validate_accepts_exact_declared_dictionary`

**Setup**: `prepared = PreparedStep(instruction="…", inputs={}, declarations=["name", "kind"])`.

**Input**: `validate_step_result(prepared, {"kind": "book", "name": "Dune"})`.

**Trace**:
```
validate_step_result(prepared, result)
  → declarations non-empty; result not None
  → set(result) == {"name", "kind"} == set(declarations)
  → both values str, non-blank
  returns: {"kind": "book", "name": "Dune"}
```

**Assertions**: `captures == {"name": "Dune", "kind": "book"}` (order irrelevant, values verbatim).

**Sufficiency**: the exact-key contract — order-free key equality, values untrimmed.

---

#### `test_validate_declaration_free_step_accepts_none`

**Setup**: `prepared = PreparedStep(instruction="click Sign in", inputs={}, declarations=[])`.

**Input**: `validate_step_result(prepared, None)` → returns `{}`.

**Assertions**: `captures == {}` — legacy cached code replays clean.

**Sufficiency**: backward compatibility of the replay path for all pre-template cached steps.

---

#### `test_memory_publish_replaces_present_and_keeps_absent`

**Setup**: `memory.publish({"name": "Book"})`.

**Input**: `memory.publish({"name": "Tale", "kind": "novel"})`; then `memory.snapshot()`.

**Trace**: publish replaces `name`, adds `kind` → snapshot `{"name": "Tale", "kind": "novel"}`.

**Assertions**: earlier snapshot objects unchanged (`first == {"name": "Book"}`); new snapshot reflects the replace-and-keep semantics.

**Sufficiency**: recapture-replaces + absent-keeps + snapshot stability — the memory contract in one test.

---

#### `test_normalize_template_sentence_addresses_verbatim`

**Input**: `normalize_step_text("  Read {{ name }} into {% var out %}  ")`.

**Trace**: markers detected (`{{`, `{%`) → NFC + trim only.

**Assertions**: result == `"Read {{ name }} into {% var out %}"` (case and internal whitespace preserved); `normalize_step_text("read {{ Name }} …") != normalize_step_text("read {{ name }} …")`.

**Sufficiency**: case-sensitive template addressing; prevents the casefold pipeline from collapsing distinct templates into one address.

---

#### `test_settle_carries_successful_result_through`

**Setup**: `window = SettleWindow(None, 0.0)` (polling off); `execute = lambda code, page: {"name": "Dune"}`.

**Input**: `settle(execute, "code", page, window)`.

**Trace**: window.start → single execution succeeds → return its result.

**Assertions**: `result == {"name": "Dune"}` — the loop passes the result untouched.

**Sufficiency**: result carriage without polling; the executor's replay publication depends on it.

---

#### `test_settle_carries_result_of_successful_count_retry`

**Setup**: `window = SettleWindow(None, 0.0, 2)`; fake `page = object()`; `caplog` captures INFO from logger `prettyplay`; a fake `execute` increments `calls`, raises `AssertionError("page not ready")` on call 1, and returns `{"name": "Dune"}` on call 2. `AssertionError` is pollable under the existing `is_pollable_failure` map.

**Input**: `result = settle(execute, "code", page, window)`.

**Trace**: `window.start()` → count branch calls `execute("code", page)` → `AssertionError` is pollable and `executed=1 < tries=2` → one `settle_retry` log and zero-delay pause → second call returns `{"name": "Dune"}` → `_settle_by_count` and `settle` pass that same dictionary to the caller.

**Assertions**: `assert result == {"name": "Dune"}`; `assert calls == 2`; `assert [r.getMessage() for r in caplog.records if r.getMessage() == "settle_retry"] == ["settle_retry"]`.

**Sufficiency**: the count-mode helper has a separate return path. This catches an implementation that preserves the first-execution result but discards the successful retry's result.

---

#### `test_executor_publishes_validated_captures_on_cached_replay`

**Setup**: fake page; cache primed with `code = 'def step(page):\n    return {"name": "Dune"}\n'` for the identity of `"Read {{ kind }} into {% var name %}"` (memory holds `kind` → "novel"); non-strict.

**Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`.

**Trace**:
```
execute(…)
  → render_step → PreparedStep(instruction="Read novel into ", declarations=["name"])
  → identity ← normalize(original sentence); cache.load → HIT
  → settle(run_step_code, cached.code, page, window) → {"name": "Dune"}
  → validate_step_result → captures {"name": "Dune"} → memory.publish
  → ScenarioStep(sentence=<raw>, instruction="Read novel into ", group_prompt="")
  → on_step_started/on_step_passed carry the raw sentence
```

**Assertions**: `memory.snapshot() == {"kind": "novel", "name": "Dune"}`; the prior `kind` value survives publication of `name`; scenario record holds both texts; no LLM calls; no gate call.

**Sufficiency**: the replay acceptance rule — the gate never runs on replay; publication is the validated successful execution.

---

#### `test_generator_publishes_captures_after_gate_pass_and_stores`

**Setup**: fake provider returns `def step(page) -> dict: return {"name": "Dune"}`; gate returns `[]`; budgets fresh.

**Input**: `generator.generate(identity, prepared(declarations=["name"]), "action", [], None, page, [], window, memory)`.

**Trace**: request carries `instruction/inputs/declarations` → settle returns result → validate OK → gate `[]` → `memory.publish({"name": "Dune"})` → cache.save → return step.

**Assertions**: memory snapshot; cache file exists; provider call kwargs include `instruction=prepared.instruction`, `inputs={}`, `declarations=["name"]`.

**Sufficiency**: the acceptance ordering — validation → gate → publication → store.

---

#### `test_recovery_rerenders_row_step_against_current_memory`

**Setup**: group traces: step1 `sentence="Read {{ kind }} into {% var name %}"`, `vars={}`, `instruction="Read novel into "` (recorded at execution); memory now holds `name="Dune"` after the failed step's history; diagnosis verdict `recoverable`, `earliest_step="Read novel into "`; fake provider regenerates `def step(page): return {"name": "Dune"}`.

**Input**: `recovery.recover(group_prompt, traces, prepared_failed, "action", scenario, identity, history, page, window, memory)`.

**Trace**:
```
recover(…) → local views copied → diagnosis → row = [step1, failed]
  → step1: fresh = render_step("Read {{ kind }} into {% var name %}", "action", memory, {})
      → instruction "Read novel into " (same values); regenerate carries fresh
  → failed step: fresh render with memory containing name → its own regeneration
  → per step: validate → gate → publish → store; local views updated by index
  → returns the failed step's healed CachedStep
```

**Assertions**: provider received `instruction="Read novel into "` for step1 (fresh, not stale); `memory` holds recaptured values; caller's `traces`/`previous_steps` unchanged objects; row histories anchored per step.

**Sufficiency**: row re-render against current context + local-view isolation — the two most intricate recovery mechanics.

---

#### `test_steer_validates_green_turn_and_publishes_with_writeback`

**Setup**: stdin scripted `b"guidance\ny\n"`; provider returns `def step(page) -> dict: return {"name": "Dune"}`; gate `[]`; prepared has `declarations=["name"]`.

**Input**: `steering.steer(failure, identity, prepared, "action", [], None, page, history, memory)`.

**Trace**: banner carries the prepared instruction → guidance request carries instruction/inputs/declarations + USER GUIDANCE → approval → `run_step_code` → result → validate OK → gate `[]` → publish → write-back → `on_healed` → returns healed step.

**Assertions**: memory snapshot `{"name": "Dune"}`; cache saved; healed returned; banner line contains the prepared instruction, never `{{`.

**Sufficiency**: the steering acceptance chain — result validation and publication ride the same acceptance rule as the engines.

---

#### `test_provider_renders_inputs_and_results_blocks_in_fixed_order`

**Setup**: recorded provider request capture (openai implementation with a stubbed SDK call).

**Input**: `generate_step_code(prompt=…, user_instructions="", instruction="Read novel into ", step_type="action", previous_steps=[], group_prompt=None, inputs={"expected": "Details"}, declarations=["name"], snapshot="snap", page_url="https://x", screenshot=None, cheat_sheet="cs", attempt_history=[], recommendation=None, guidance=None)`.

**Trace**: `build_fields_text` composes sections; the user content string is captured.

**Assertions**:
```
text.index("STEP TYPE: action") < text.index("STEP:\nRead novel into ")
  < text.index("INPUTS:\nexpected = Details") < text.index("RESULTS:")
  < text.index("PAGE SNAPSHOT:") < text.index("PAGE URL: https://x") < text.index("CHEAT SHEET:")
```
Identical composition asserted for the anthropic builder (parity).

**Sufficiency**: the fixed scenario-part order — INPUTS/RESULTS immediately after STEP, PAGE URL immediately after PAGE SNAPSHOT (the defect D1 regression lock).

---

### Negative Tests

#### `test_render_duplicate_capture_name_raises_authoring_error`

**Input**: `render_step("{% var x %}{% var x %} go", "action", memory, None)`.

**Trace**: second reached tag finds `x` recorded → raise.

**Assertions**: `pytest.raises(PrettyplayError)` with a message naming `x` and the duplicate problem; raised before any browser interaction (no page object involved at all).

**Sufficiency**: one slot per name per render — prevents ambiguous result dictionaries.

---

#### `test_render_malformed_standard_jinja_is_an_authoring_error`

**Setup**: empty `StepMemory()`; no page, provider or cache object exists.

**Input**: `render_step("{% if x %}", "action", memory, None)`.

**Trace**: `snapshot()` returns `{}`; fresh Jinja environment is constructed; `from_string` parses the incomplete `if` and raises `TemplateSyntaxError` with line 1; `render_step` catches it and raises `PrettyplayError` retaining the syntax message and line; no render or browser execution occurs.

**Assertions**: `with pytest.raises(PrettyplayError) as exc:`; `assert "if" in str(exc.value)`; `assert "line 1" in str(exc.value)`.

**Sufficiency**: standard Jinja syntax errors need the same loud authoring-error boundary as malformed `{% var %}` tags; a raw library exception must not escape through the public step call.

---

#### `test_render_reserved_and_invalid_capture_names_raise`

**Input**: `render_step("{% var vars %}", "action", …)` and `render_step("{% var 1x %}", "action", …)`.

**Assertions**: both raise `PrettyplayError` naming the offending tag; the reserved `vars` namespace stays unreachable as a capture.

**Sufficiency**: namespace reservation and identifier-form enforcement.

---

#### `test_render_unavailable_name_raises_naming_the_name`

**Setup**: empty memory.

**Input**: `render_step("Open {{ missing }}", "action", memory, None)`.

**Trace**: `StrictUndefined` raises `UndefinedError('missing' …)` → caught → `PrettyplayError` naming `missing`.

**Assertions**: `pytest.raises(PrettyplayError)`, `"missing" in str(exc)`.

**Sufficiency**: the loud missing-value policy — no silent empty strings (Jinja default `Undefined` would).

---

#### `test_render_capture_in_expectation_raises`

**Input**: `render_step("The page shows {% var x %}", "assertion", memory, None)`.

**Assertions**: `PrettyplayError`; declarations gate applies only to assertions — the same sentence as `action` succeeds.

**Sufficiency**: captures are actions-only; expectations observe.

---

#### `test_facade_rejects_non_string_vars_value`

**Setup**: `t = PrettyPlay("k")` with fakes.

**Input**: `t.step("open the page", vars={"expected": 42})`.

**Trace**: `_validate_vars` before the executor → raise.

**Assertions**: `pytest.raises(PrettyplayError)` naming `vars`, the received value `42` and the allowed form; executor/render never invoked; no page opened.

**Sufficiency**: the loud call-surface validation, uniform with tries/delay.

---

#### `test_validate_missing_and_unexpected_names_violate`

**Input**: `prepared(declarations=["a", "b"])` with `{"a": "x"}` (missing `b`) and with `{"a": "x", "b": "y", "c": "z"}` (unexpected `c`); also `None` (missing result) and a non-None dict for a declaration-free prepared.

**Assertions**: each raises `AssertionError`; the message names the offending name(s).

**Sufficiency**: the exact-key contract's both sides plus the None matrix.

---

#### `test_validate_blank_value_violates`

**Input**: `prepared(declarations=["a"])` with `{"a": ""}` and `{"a": "   "}`.

**Assertions**: `AssertionError` naming `a`; `{"a": "  x  "}` passes with the value verbatim.

**Sufficiency**: blank = unobserved; whitespace-only is blank; non-blank values keep their form.

---

#### `test_validate_wrong_result_type_is_a_failed_check`

**Setup**: `prepared = PreparedStep(instruction="Read the name", inputs={}, declarations=["name"])`; no page, provider or cache is needed for this pure validator test.

**Input**: call `validate_step_result(prepared, ["name"])` and `validate_step_result(prepared, 42)` separately.

**Trace**: each result is non-None, then fails `isinstance(result, dict)` before key inspection; each call raises `AssertionError("result must be a dictionary")`. The list is especially important: `set(["name"])` would match the declarations even though it has no `.items()`.

**Assertions**: for both inputs, `pytest.raises(AssertionError, match="result must be a dictionary")`; no captures are returned.

**Sufficiency**: generated Python code can return a value of any type despite its annotated return form. This test keeps wrong types in the deterministic failed-check channel instead of leaking `TypeError` or `AttributeError`.

---

#### `test_generator_violation_is_a_failed_check_and_publishes_nothing`

**Setup**: provider returns code yielding `{"name": ""}` (blank); classification returns `incurable`.

**Input**: `generate(identity, prepared(declarations=["name"]), "action", [], None, page, [], window, memory)`.

**Trace**: settle succeeds → validate raises → record(`failed check`, violation text) → classify → `IncurableStepError` carrying the verdict, code and violation text.

**Assertions**: memory snapshot empty; history record outcome `failed check` with the deterministic text; raised `IncurableStepError.verdict.category == "incurable"`.

**Sufficiency**: the result-contract violation joins the existing failed-check channel with publication withheld.

---

#### `test_steering_violation_is_a_red_turn_without_publication`

**Setup**: stdin `b"guidance\ny\nquit\n"`; provider returns blank-valued code.

**Input**: `steer(...)` → executed turn validates to a violation.

**Assertions**: record appended with outcome `failed check`; memory empty; nothing cached; dialog returns to the prompt and finally `None` → the original failure propagates.

**Sufficiency**: interactive turns obey the same acceptance rule; nothing green is written back unvalidated.

---

### Edge Case Tests

#### `test_render_same_step_cannot_read_its_own_capture`

**Input**: `render_step("Read {{ name }} and {% var name %}", "action", StepMemory(), None)` with empty memory.

**Assertions**: `PrettyplayError` naming `name` (the snapshot lacks it) — a same-step read observes the previous value or fails; two steps are needed.

**Sufficiency**: snapshot isolation — new captures publish only after acceptance.

---

#### `test_render_captured_value_containing_jinja_stays_literal`

**Setup**: `memory.publish({"payload": "{{ boom }}"})`.

**Input**: `render_step("Type {{ payload }}", "action", memory, None)`.

**Assertions**: `prepared.instruction == "Type {{ boom }}"` — data is never re-rendered; no injection through captured content.

**Sufficiency**: the substituted-data-is-never-a-template rule.

---

#### `test_render_author_written_default_and_is_defined_keep_behavior`

**Input**: `render_step("{{ missing | default('n/a') }}", …)` and `render_step("{% if missing is defined %}x{% else %}y{% endif %}", …)`.

**Assertions**: instruction `"n/a"`; instruction `"y"` — authored absence handling is honored, engines never add fallbacks.

**Sufficiency**: StrictUndefined does not break authored Jinja idiom.

---

#### `test_normalize_comment_marker_sentence_is_template`

**Input**: `normalize_step_text("{# note #} Click Sign in")`.

**Assertions**: verbatim NFC+trim form (case preserved, no casefold) — the `{#` marker keeps the instruction-equals-sentence invariant.

**Sufficiency**: locks this session's marker-set fix (defect 3).

---

#### `test_executor_strict_template_step_validates_and_publishes_on_replay`

**Setup**: `strict=True`; cache primed under `StepIdentity(cache_key="k", step_type="action", normalized_text=normalize_step_text("Read {{ kind }} into {% var name %}"))` with `def step(page): return {"name": "Dune"}`; executor memory initially `{"kind": "novel"}`; fake page returns the step function's plain result; fake provider and generator record calls; patch the gate with a call recorder.

**Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`.

**Trace**: render reads `kind="novel"` and declares `name`; identity uses the raw template; cache hit; `settle` passes through `{"name": "Dune"}`; validation returns that dictionary; executor publishes `name` and retains `kind`; scenario receives raw sentence and prepared instruction; strict replay does not request a gate or LLM call.

**Assertions**: `assert memory.snapshot() == {"kind": "novel", "name": "Dune"}`; `assert provider.call_count == 0`; `assert generator.call_count == 0`; `assert gate.call_count == 0`; `assert scenario[-1].instruction == "Read novel into "`.

**Sufficiency**: strict replay accepts and publishes valid captures without regeneration or compliance gating.

---

#### `test_executor_strict_template_result_violation_stays_unpublished`

**Setup**: same strict cache and initial memory as the successful test, except cached code returns `{"name": ""}`; fake provider's classification response is `FailureClassification(category="incurable", explanation="capture is blank", recommendation="inspect the page")`; fake page supplies snapshot `"snap"`; generator and gate are call-recording fakes.

**Input**: `executor.execute("Read {{ kind }} into {% var name %}", "action", page, vars=None)`.

**Trace**: render and cache hit follow the successful test; `settle` returns the blank dictionary; `validate_step_result` raises `AssertionError` naming `name`; replay failure formats the assertion text without an `AssertionError` prefix; strict classification receives `step_text="Read novel into "`, failed code and the validation text; the `incurable` verdict raises `IncurableStepError`; no publication, generation or gate call occurs.

**Assertions**: `pytest.raises(IncurableStepError)` with `"name" in str(exc.value)` and `exc.value.verdict.category == "incurable"`; `assert memory.snapshot() == {"kind": "novel"}`; `assert provider.classify_step_failure.call_count == 1`; `assert generator.call_count == 0`; `assert gate.call_count == 0`.

**Sufficiency**: a result-contract violation on cached strict replay must remain a failed check, keep memory unchanged and terminate through classification without generation.

---

#### `test_recovery_row_failure_updates_active_failure_for_next_diagnosis`

**Setup**: two-row recovery; the first row step's regeneration raises `IncurableStepError` once; second diagnosis verdict `product_defect`.

**Input**: `recover(...)`.

**Trace**: row step 1 fails → active failure updated (fresh prepared, identity, grown history, error) → occurrence marked failed with the fresh instruction preserved → new diagnosis receives that STEP/HISTORY → product_defect raises `ProductDefectError`.

**Assertions**: the second `classify_group_failure` call received the row step's instruction (not the executor's original) as `step_text`; local trace view marks failure; caller views untouched.

**Sufficiency**: "STEP and HISTORY always describe the failure that triggered that diagnosis".

---

#### `test_scenario_records_carry_both_texts_and_events_carry_raw_sentence`

**Setup**: template step end-to-end with fakes (miss → generate → accept).

**Input**: `t.step("Open the item named {{ name }}")` after a capture step.

**Assertions**: `ScenarioStep(sentence="Open the item named {{ name }}", instruction="Open the item named Book", …)`; hook events' `step_text == "Open the item named {{ name }}"`; the provider request's STEP line is the prepared instruction.

**Sufficiency**: the dual-text invariant and the hook-surface decision (option A).

---

#### `test_group_trace_records_instruction_and_vars`

**Input**: group step `g.step("Check {{ vars.code }}", vars={"code": "A1"})` with fakes.

**Assertions**: `GroupStepOutcome(sentence="Check {{ vars.code }}", instruction="Check A1", vars={"code": "A1"}, …)`; `record.render()` starts with the instruction line.

**Sufficiency**: the trace feeds row re-render (sentence + vars) and the matcher (instruction) — both fields must be recorded.

---

## Additional Instructions for the Implementation Agent

- Create `prettyplay/engine/renderer/__init__.py` exporting `PreparedStep`, `render_step`, `StepMemory`, `validate_step_result` (relative imports only; `jinja2` import lives in `render.py`).
- Build a fresh Jinja `Environment` per `render_step` call (statelessness across concurrent tests); the `{% var %}` extension carries the per-render recorder list; validate the tag token at parse time (single identifier), the reserved name and duplicates at record time. Translate all compile-time `TemplateSyntaxError` (including its `TemplateAssertionError` subclass) into `PrettyplayError` with the original diagnostic and line number.
- `PreparedStep`: pydantic v2, `kw_only=True`, `frozen=True`, empty defaults; `has_declarations` is a plain property, not a field. `StepMemory` is a plain mutable class — not pydantic.
- `validate_step_result` violation messages are deterministic check texts (they ride record error fields and dialogs); the calling cycles format them via `format_step_error` — never re-compose.
- Thread `PreparedStep` + `StepMemory` through every engine signature exactly as the CODEMANIFESTs order the parameters; keep the frozen-mirror prompt constants (`generator.SYSTEM_PROMPT`, `steering.SYSTEM_PROMPT`, `compliance.COMPLIANCE_PROMPT`, `groups.diagnosis.GROUP_DIAGNOSIS_PROMPT`) in lockstep with the updated practice files — copy the post-`---` sections verbatim.
- In the executor: render **before** identity; identity from the **original** sentence; construct `StepMemory` once in `__init__`; the cached-hit path validates and publishes; the violation routes into the existing failure paths with the replay URL pair.
- In the recovery: copy scenario/trace records into local views (`model_copy(update=…)`) — never mutate the caller's lists; locate occurrences by index; re-render every row step (including the failed one) through `render_step` before its regeneration; publish per accepted row step; a re-render authoring error propagates loudly.
- In the LLM builders: INPUTS/RESULTS sections insert immediately after the STEP section; PAGE URL stays immediately after PAGE SNAPSHOT; `_previous_step_line` renders `record.instruction`; group diagnosis gains the optional PREVIOUS STEPS block; both providers compose identically.
- Facade: add `_validate_vars` beside `_validate_tries`/`_validate_delay` (bools never coerce; every value must be `str`); `vars` is keyword-only on `step`/`expect` of both the test object and the group object; hook events keep the raw sentence.
- Update the touched unit tests to the new signatures first, then add the cases above; run `pytest tests/ -x` and `ruff check prettyplay/` in the project virtualenv (the repo `.venv` is macOS-built — recreate it on Linux).

# Design Document: `fix-user-instructions`

Topic: make user instructions binding, checkable, and expressible — the instruction
compliance gate before caching, the case-insensitive text assertion capability, the
`generation_approve` switch, and the binding prompt wording. Source contracts: the
CODEMANIFEST state materialized by apply-architecture from
`.goga/history/2026/fix-user-instructions/arch.md` (binding ADR:
`.goga/history/2026/fix-user-instructions/adr.md`). Policy line: **an unfollowed or
unfulfillable instruction must surface as a generation error, never as silent
ignoring.**

Language rules: `goga-cell-python` conventions via `.goga/usages/conventions.md`
(Python 3.10+, relative intra-package imports, pydantic v2 `kw_only`, Google docstrings,
`logging` with structured `extra`, tests mirror source structure).

---

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/failures/CODEMANIFEST`: taxonomy header now four kinds; new
  `PrettyplayError::ComplianceVerdictError(message: str)` after `LLMUnavailableError`;
  footer description updated.
- `prettyplay/config/CODEMANIFEST`: `Config` signature gains `generation_approve: bool`
  (last position); param annotation, layered-merge requirement, property;
  `load_config` env override (`PRETTYPLAY_GENERATION_APPROVE`) in Algorithm step 6 and
  Requirements; global annotation line; footer.
- `prettyplay/driver/CODEMANIFEST`: `PageFacade.expect_title` and
  `LocatorFacade.expect_text` gain `ignore_case: bool = False`; parity annotation
  extended (the capability rides existing mirror names).
- `prettyplay/llm/CODEMANIFEST`: Imports failures +`ComplianceVerdictError`;
  `LLMProvider` gains the third operation `check_instruction_compliance`; both provider
  mutations renamed "Algorithm (all three operations)" + compliance branch; new types
  `ComplianceFinding` and `parse_compliance_verdict` (both `models.py`); two global
  annotation lines; footer.
- `prettyplay/engine/CODEMANIFEST`: Imports llm +`ComplianceFinding`; Usages gains the
  inline practice `compliance_prompt`; `classification_prompt` USER INSTRUCTIONS line
  gains the binding wording; three global annotation lines; new routine
  `check_step_compliance` (`compliance.py`); `StepGenerator` gate in `generate` step 5,
  exhaustion-with-standing-high in step 8, `regenerate` step 1 + Requirements; footer.
- `prettyplay/engine/steering/CODEMANIFEST`: Imports engine +`check_step_compliance`;
  global annotation (the gate guards the write-back); `steer` step 6 rewritten; two
  Requirements changes; footer.
- `prettyplay/CODEMANIFEST` (root): Imports failures +`ComplianceVerdictError`; the
  three by-kind enumerations (`PrettyPlay.step`, `PrettyPlay.expect`,
  `StepExecutor.execute` step 8) name it. Text-only; no signature changes.

### New Entities

- `PrettyplayError::ComplianceVerdictError(message: str)` — `prettyplay/failures/errors.py`.
  The compliance gate could not obtain a usable verdict; message-only, carries no verdict.
- `ComplianceFinding(instruction: str, priority: str, explanation: str)` —
  `prettyplay/llm/models.py`. One finding of the verdict; pydantic v2 entity with
  properties only.
- `parse_compliance_verdict(verdict_text: str) -> findings: list[ComplianceFinding]` —
  `prettyplay/llm/models.py`. Strict single parsing point of the gate; pure routine.
- `LLMProvider.check_instruction_compliance(prompt, user_instructions, step_text, code)
  -> verdict: list[ComplianceFinding]` — port method, implemented in
  `prettyplay/llm/openai_provider.py` and `prettyplay/llm/anthropic_provider.py`.
- `check_step_compliance(config, provider, step_text, code) -> findings:
  list[ComplianceFinding]` — new module `prettyplay/engine/compliance.py`. The single
  compliance check of every caching path.

### Changed Entities

- `Config` — gains `generation_approve: bool` (default True, opt-out); env override
  `PRETTYPLAY_GENERATION_APPROVE`; layered-merge participation identical to
  `strict`/`interactive`.
- `PageFacade.expect_title(title, ignore_case=False)` — True compiles the title regex
  with `re.IGNORECASE`.
- `LocatorFacade.expect_text(text, ignore_case=False)` — True forwards Playwright's
  `ignore_case` flag to `to_contain_text`.
- `StepGenerator.generate` — step 5 gates every successfully executed candidate through
  `check_step_compliance` before `_store`; step 8 builds the exhaustion verdict from a
  standing high finding.
- `StepGenerator.regenerate` (via `_healing_loop` and `_funded_regeneration`) — the same
  gate before every store; a high finding is a failed attempt retried with the violation
  text as ERROR.
- `StepSteering.steer` — step 6 gates the green guided candidate before `_write_back`.
- `LLMProvider::OpenAIProvider` / `LLMProvider::AnthropicProvider` — the third operation
  in full parity.
- Frozen mirrors (implementation artifacts under the mirror rule):
  `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` and
  `prettyplay/engine/steering/steering.py` (binding rules of the practice
  `.goga/usages/prompts/generation.md`); `PAGE_API_SURFACE` in both (two rows gain
  `ignore_case`); `CLASSIFICATION_PROMPT` in `prettyplay/engine/classification.py`
  (binding wording).

### Deleted Entities

None. No cells are created or deleted; `example/.prettyplay/cache/**` stays untouched
(owner decision 2026-09-13, superseding the ADR's deletion clause); cells
`prettyplay/cache`, `prettyplay/reporting`, `prettyplay/engine/polling` untouched.

### Usages and Annotations Changes

- Engine header Usages: new inline practice `compliance_prompt` (the gate system prompt,
  with priority calibration); `classification_prompt` input line now "binding
  classification guidance — follow it; it never overrides the fixed answer format above".
- Engine global Annotations: `compliance_prompt` binding line; the gate-runs-inside-the-
  engines line; the loud-errors line; generation_prompt reach extended to the compliance
  request (defect fix 3, below).
- llm global Annotations: third-operation parity line; one-request-per-attempt covers the
  verdict request; provider-serves line extended (defect fix 1).
- Project practice `.goga/usages/prompts/generation.md`: "binding code style guidance"
  wording + three binding rules (binding below the safety core; conflicts raise
  `instruction conflicts with rule Y`; prefer-type instructions conditional).
- Cooks (already applied at formulation): `playwright.md` (case-insensitive expectations
  section), `openai.md`/`anthropic.md` (compliance call sections, three operations).
- Cell `.usages/`: `failures/taxonomy.md`, `config/configuration.md`,
  `driver/facade.md`, `llm/providers.md`, `engine/generation.md`, `engine/healing.md`,
  `engine/steering/steering.md` — all updated by apply-architecture; verified current
  (see `.usages/ Update`).

---

## Applied Fixes

### Fixed CODEMANIFEST Defects

Found by the Phase 3 four-dimension consistency audit; all three approved by the owner
(dialog q1, 2026-09-13) and applied; `goga lint` clean after each.

1. `prettyplay/llm/CODEMANIFEST` global Annotations:
   "…the provider serves generation and classification only." →
   "…the provider serves generation, classification and the compliance verdict only."
   (reason: internal contradiction — the same block declares the compliance verdict the
   third port operation).
2. `prettyplay/llm/CODEMANIFEST` `LLMProvider` type annotations:
   "code generation for a step and failure classification for healing" →
   "code generation for a step, failure classification for healing and the compliance
   verdict of the gate" (reason: stale enumeration — the port contract now carries three
   operations).
3. `prettyplay/engine/CODEMANIFEST` global Annotations, the user-instructions reach line:
   appended "…and the compliance verdict request — there as the checked INSTRUCTIONS
   block, never as guidance" (reason: incomplete enumeration — `check_step_compliance`
   step 2 passes the effective `generation_prompt` into the compliance request, which the
   old line did not account for).

---

## Entity Interaction and Data Flow

### Interaction Diagram

```
                       PrettyPlay.step / expect (root, traceback folding)
                              │ execute(step_text, step_type, page)
                              ▼
                       StepExecutor.execute ── on_step_failed / on_step_verdict (verdict=None here)
                        │ cache load → miss → generate          │ IncurableStepError only → steering intercept
                        ▼                                       ▼
                  StepGenerator.generate/regenerate        StepSteering.steer (interactive)
                        │ _generation_loop / _healing_loop        │ guided request (provider.generate_step_code)
                        │  candidate green under settle           │ run_step_code → green
                        ▼                                         ▼
              ┌─ check_step_compliance (engine/compliance.py) ──────────────┐
              │  off switch or empty generation_prompt → [] (zero calls)     │
              │  else provider.check_instruction_compliance                  │
              ▼                                                            │
     LLMProvider port (llm)                                                 │
      ├─ OpenAIProvider.check_instruction_compliance                        │
      └─ AnthropicProvider.check_instruction_compliance ────────────────────┤
                        │ build_compliance_fields: INSTRUCTIONS/STEP/CODE   │
                        │ one request · effective_generation_model          │
                        ▼                                                   │
              parse_compliance_verdict (llm/models.py)                       │
                malformed → ComplianceVerdictError (failures) ── hard ──→ propagates;
                SDK error   → LLMUnavailableError ──────────── hard ──→ propagates
                        │
                        ▼ list[ComplianceFinding]
   generator loops: high → attempt failed (violation = ERROR) → retry → exhaustion: verdict from finding
                    medium/low → WARNING → cache save        steering: high → dialog + history → re-prompt;
                                                               medium/low → WARNING → write-back
```

### Data Flows

1. **Gate pass (generation)** — `executor.execute` (cache miss) → `StepGenerator.generate`
   → `_generation_loop`: `try_generation` → `_request` (provider code) →
   `settle(run_step_code, …)` green → `check_step_compliance(config, provider, step_text,
   code)` → `provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT,
   user_instructions=config.generation_prompt, step_text, code)` →
   `build_compliance_fields` → one SDK request on `effective_generation_model` → answer
   text → `parse_compliance_verdict` → `list[ComplianceFinding]` → empty → `_store`
   (CachedStep saved) → return.
2. **Gate block (generation)** — same prefix; findings contain a `high` → violation text
   = `f"violated instruction: {instruction} — {explanation}"` becomes the loop `error`,
   the candidate becomes `existing_code`, next iteration regenerates targeting it; on
   budget exhaustion with the high finding still standing, `IncurableStepError` carries a
   verdict built from the finding (no LLM call).
3. **Gate hard failure** — provider SDK error → `LLMUnavailableError`; unparsable answer
   → `ComplianceVerdictError`; both propagate through `check_step_compliance` (never
   swallowed) → out of the loops (the gate call sits in the success branch, outside every
   `try` that catches candidate failures) → `executor.execute` outer `except Exception`
   fires `on_step_failed` with the message → re-raised → `PrettyPlay.step` folds the
   traceback (it is a `PrettyplayError`) → runner.
4. **Steering write-back gate** — `steer` green turn → `check_step_compliance` (same
   routine, engine import) → empty/medium/low → `_write_back` (cache save + `on_healed`);
   high → dialog line + history turn + re-prompt (no write-back); hard failure → gate
   failure line + WARNING + `return None` (original terminal failure propagates from the
   executor).
5. **Config flow** — `pyproject.toml [tool.prettyplay].generation_approve` → env
   `PRETTYPLAY_GENERATION_APPROVE` (true/false/1/0, case-insensitive; unparseable → loud
   `ConfigurationError`) → `Config(**merged)` → programmatic `PrettyConfig(generation_approve=False)`
   overlay wins last; `config.generation_approve` + `config.generation_prompt` read by
   `check_step_compliance` only.
6. **Facade capability flow** — generated step code calls
   `page.get_by_text("status").expect_text("SUCCESS", ignore_case=True)` →
   `LocatorFacade.expect_text` → thread-marshaled `self._call` → Playwright
   `expect(locator).to_contain_text(text, ignore_case=True)`; `page.expect_title(t,
   ignore_case=True)` → regex compiled with `re.DOTALL | re.IGNORECASE` →
   `expect(page).to_have_title(pattern)`.

### Entity Dependencies

Implementation order (leaves → root, matching the contract dependency map; no cycles):

1. `prettyplay/failures` — `ComplianceVerdictError` in `errors.py` + `__init__` export;
   module docstring three→four kinds.
2. `prettyplay/config` — `generation_approve` field; loader `_ENV_NAMES` /
   `_BOOL_ENV_SETTINGS` / `_ALLOWED_TEXT` entries + module docstring.
3. `prettyplay/driver` — `ignore_case` on the two assertion methods.
4. `prettyplay/llm` — `ComplianceFinding` + `parse_compliance_verdict` in `models.py`;
   `build_compliance_fields` in `_request.py`; port method + both implementations;
   `__init__` exports.
5. `prettyplay/engine` — new `compliance.py` (`COMPLIANCE_PROMPT` +
   `check_step_compliance`); `__init__` export; `generator.py` gate integration;
   `classification.py` `CLASSIFICATION_PROMPT` wording.
6. `prettyplay/engine/steering` — `steering.py` gate before `_write_back` +
   `SYSTEM_PROMPT`/`PAGE_API_SURFACE` mirror updates.
7. `prettyplay` (root) — docstring enumerations only (`executor.py`, `scenario.py`).

**Mirror coordination rule (binding, from the plan)**: the practice
`.goga/usages/prompts/generation.md` (already changed), both `SYSTEM_PROMPT` mirrors, the
`facade.md` rows (already changed), both `PAGE_API_SURFACE` mirrors, and the
`CLASSIFICATION_PROMPT` wording land **together** with steps 3–6 in one coordinated
change; the two byte-equality sync tests
(`test_system_prompt_mirrors_the_generation_practice`,
`test_steering_mirrors_the_practices`) are red until then — this is the designed
intermediate state left by apply-architecture.

Initialization order is unchanged: `PrettyplayRuntime` → provider/generator/healer/
steering/executor wiring in `PrettyPlay.__init__` needs no new collaborators (the gate
reads `config` + `provider` already held by every consumer).

---

## Code Stack Trace

Verified against the actual sources; checkpoints passed unless stated.

### Trace: `StepGenerator._generation_loop` (the gate integration point)

#### Chain
1. **Input**: `execute` (executor) on a cache miss calls `generate(identity, step_text,
   previous_steps, page, window)` → `_generation_loop`. Existing loop state: `attempt`,
   `existing_code`, `error`, `code`.
2. `try_generation(identity)` refused → `_exhaustion_outcome(...)` — now also receives
   the standing high finding (see trace 2). → checkpoint: budget consumed at loop top
   only, the gate never calls `try_*` — "the gate consumes no attempt budget" holds.
3. `_request(...)` → provider `generate_step_code` (unchanged) → candidate `code`.
4. `settle(run_step_code, code, page, window)`:
   - `AssertionError` → `_failed_check_outcome` (unchanged decision table) → checkpoint:
     the failed-check path needs no gate — the candidate never succeeded.
   - other `Exception` → retry branch: `existing_code = code`; `error =
     format_step_error(...)`; any previously standing high finding is cleared (the
     standing failure is now the execution error).
   - green → **the gate** (new): `findings = check_step_compliance(self._config,
     self._provider, step_text, code)` placed in the `else` branch, **outside** any
     `try` — `LLMUnavailableError`/`ComplianceVerdictError` propagate immediately;
     nothing cached. → checkpoint: `except Exception as candidate_error` would swallow
     the gate failures if the call sat inside the `settle` try — placement verified.
   - `high = _high_finding(findings)` (first finding with `priority == "high"`):
     high → `existing_code = code`; `error = _violation_text(high)`; `standing = high`;
     `continue` (retry with it and the fresh snapshot). → checkpoint: the retry request
     passes `error` → rendered as the ERROR block of the regeneration request — "the
     retry carries the violation text" holds.
     no high, findings non-empty → `logger.warning("compliance findings passed",
     extra={"step_text", "findings"})` → `_store`.
     findings empty → `_store` silently (fully the old behavior).
5. **Output**: `_store` → `CachedStep` saved → returned; or a terminal error raised by
   the decision tables; or a gate hard failure propagating.

#### Checkpoint Summary
- Gate placement outside all exception-swallowing `try` blocks: passed (the only
  candidate-failure handlers wrap `settle`, not the `else` branch).
- Budget semantics: passed (gate consumes nothing; a high finding fails the attempt the
  budget already consumed).
- Type flow `list[ComplianceFinding]` from llm into engine loops: passed
  (`ComplianceFinding` imported on the engine→llm edge).

### Trace: budget exhaustion with a standing high finding (`_exhaustion_outcome`)

#### Chain
1. **Input**: loop-top `try_generation` refusal with `standing` (the high finding whose
   violation text is the current `error`) and the last candidate `code`.
2. `standing is not None` → build the verdict **without an LLM call**:
   `FailureVerdict(category="incurable", explanation=f"{standing.instruction} —
   {standing.explanation}", recommendation=f"follow the violated instruction in the step
   code: {standing.instruction}")`. → checkpoint: matches "the verdict is built
   from the standing high finding: category incurable, explanation — the finding
   instruction and its explanation, recommendation — restating to follow the violated
   instruction".
3. Reason: `f"generation attempt budget exhausted — violated instruction
   {_reason_safe(standing.instruction)}"` where `_reason_safe` takes the first line and
   removes colons (`text.partition("\n")[0].replace(":", " ")`) — instruction text comes
   from user config and may contain colons/newlines; the first-line contract forbids
   both. → checkpoint: reason colon-free by construction.
4. `raise IncurableStepError(step_text, reason, error=violation_text, code=code,
   verdict=verdict)`. → checkpoint: "the violation text rides the error field" holds;
   `IncurableStepError` renders through `render_terminal_message` with multi-line
   continuation support.
5. **Output**: terminal incurable failure naming the instruction; the steering intercept
   (`IncurableStepError`) may still open the dialog — intended: the engineer steers the
   fix.

#### Checkpoint Summary
- No classification LLM call on this path: passed (the contract grants the verdict from
  the finding).
- `standing` cleared on any non-compliance failure: passed (only the finding whose
  violation text is the standing `error` drives the verdict).

### Trace: `check_step_compliance` (engine) → `LLMProvider.check_instruction_compliance` → `parse_compliance_verdict`

#### Chain
1. **Input**: `(config: Config, provider: LLMProvider, step_text: str, code: str)` —
   called only on green candidates by the two loops, `_funded_regeneration`, and the
   steering dialog.
2. `not config.generation_approve or not config.generation_prompt` → `return []` — zero
   provider calls. → checkpoint: port requirement "the calling engine guarantees
   non-empty user_instructions" is upheld by the second disjunct.
3. `provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT,
   user_instructions=config.generation_prompt, step_text=step_text, code=code)`.
4. OpenAI implementation: `build_compliance_fields(user_instructions, step_text, code)`
   → `"INSTRUCTIONS:\n…\n\nSTEP:\n…\n\nCODE:\n…"` (fixed order, shared builder);
   messages `[system: prompt, user: text]` (plain string — the gate request carries no
   screenshot); one `chat.completions.create(model=config.effective_generation_model,
   messages=…)`. → checkpoint: model = effective generation model (contract +
   `providers.md` + cooks agree); `OpenAIError` → `LLMUnavailableError("llm
   unavailable: openai request failed")` — identical mapping to the other operations.
5. Anthropic implementation: same builder; `messages.create(model=…, system=prompt,
   max_tokens=REQUEST_MAX_TOKENS, messages=[…])`. → checkpoint: the fixed 4096 cap rides
   the verdict request too (SDK-forced, plan-mandated parity note); `AnthropicError` →
   `LLMUnavailableError`.
6. Answer text → `require_completion_text(_first_choice_text(response) /
   _first_text_block(response), provider)` — an empty completion stays an infrastructure
   failure. → checkpoint: no fence unwrapping anywhere on this path (contract:
   "no fence unwrapping").
7. `parse_compliance_verdict(answer)` (trace 4 below) → `list[ComplianceFinding]`.
8. **Output**: findings to the caller; `LLMUnavailableError`/`ComplianceVerdictError`
   propagate untouched.

#### Checkpoint Summary
- Both providers share one builder → block order identical by construction: passed.
- One request per call, no retry loop inside the provider: passed.

### Trace: `parse_compliance_verdict`

#### Chain
1. **Input**: raw verdict text (already `require_completion_text`-guarded non-empty).
2. `json.loads(verdict_text.strip())` inside `try/except ValueError` → malformed on
   parse failure. → checkpoint: "parse the trimmed text" holds.
3. `isinstance(data, list)` else malformed; per item `isinstance(item, dict)` else
   malformed.
4. Per item: `instruction`/`priority`/`explanation` each present **and** a `str`
   (`item.get(...)` + isinstance check — a missing key yields `None`, non-str values
   fail the same check); `priority in {"high", "medium", "low"}` (`COMPLIANCE_PRIORITIES`
   frozenset) else malformed. → checkpoint: covers the contract's "missing field or
   unknown priority label" plus non-string values, which could not construct the str
   fields faithfully.
5. Malformed → `raise ComplianceVerdictError(f"compliance verdict unparsable — expected
   a JSON list of findings with instruction, priority high|medium|low and explanation;
   received fragment: {_answer_fragment(verdict_text)}")` where `_answer_fragment`
   collapses whitespace and caps at 200 characters. → checkpoint: message names the
   gate, the parse failure and a bounded fragment of the raw answer.
6. Construct `ComplianceFinding(instruction=…, priority=…, explanation=…)` per item;
   unknown extra keys in an item are tolerated (the three contract fields fully
   validated; strictness targets compliance ambiguity, not model chattiness).
7. **Output**: the findings list; `[]` means compliant. Pure function — no state, no
   I/O, deterministic.

#### Checkpoint Summary
- No protective fallback (uniform with the ADR's "malformed verdict is a hard
  failure"): passed — contrast with `parse_classification_line` → `unparsable_classification`
  fallback, which stays classification-only.
- `ComplianceFinding` model itself carries no priority validation (plain `str` fields,
  empty defaults, `kw_only`): consistent with "anything else never reaches this type —
  the parse fails loudly before".

### Trace: `Config.generation_approve` (models + loader)

#### Chain
1. **Input**: TOML `[tool.prettyplay] generation_approve = false` / env
   `PRETTYPLAY_GENERATION_APPROVE` / programmatic `PrettyConfig(generation_approve=False)`.
2. `models.py`: field `generation_approve: bool = True` after `send_screenshots`
   (`kw_only`, `extra="forbid"`) — the deliberate opt-out default; docstring Attributes
   entry. → checkpoint: default True per ADR decision 2; the "empty defaults" convention
   bends here by explicit contract (as `strict`/`interactive` bend with False).
3. `loader.py`: `"generation_approve"` added to `_ENV_NAMES` (→
   `PRETTYPLAY_GENERATION_APPROVE`), `_BOOL_ENV_SETTINGS`, `_ALLOWED_TEXT`
   (`"a boolean"`); module docstring line.
4. `_collect_env_overrides` → `_parse_env_scalar("generation_approve", raw)` — the
   existing boolean branch parses true/false/1/0 case-insensitively and raises
   `ConfigurationError(f"generation_approve: received {raw!r} — allowed: a boolean
   (true/false/1/0)")` otherwise. → checkpoint: names setting, received value, accepted
   form — the loud-actionable contract; no new parsing code needed.
5. File+env merge → `Config(**merged)`; `_apply_overrides`: an explicitly passed False
   is in `model_fields_set`, is not None, is not a str → participates and overwrites the
   file layer. → checkpoint: the `strict`/`interactive` pattern verified in the existing
   merge code — False survives the string-emptiness guard.
6. **Output**: `config.generation_approve` read solely by `check_step_compliance`.

#### Checkpoint Summary
- Merge participation identical to existing booleans: passed (no branch of
  `_apply_overrides` treats bools specially).

### Trace: `LocatorFacade.expect_text` / `PageFacade.expect_title`

#### Chain
1. **Input**: step code `page.get_by_text("status").expect_text("SUCCESS", ignore_case=True)`
   / `page.expect_title("dashboard", ignore_case=True)`; default `False` keeps the old
   call shape working.
2. `expect_text`: `self._call(lambda: expect(self._locator).to_contain_text(text,
   ignore_case=ignore_case))` — Playwright python `to_contain_text(expected,
   ignore_case=…)` exists since 1.44; `pyproject.toml` pins `playwright>=1.49`. →
   checkpoint: marshaled through the existing `_call` boundary — no raw object crosses.
3. `expect_title`: `flags = re.DOTALL | re.IGNORECASE if ignore_case else re.DOTALL`;
   `pattern = re.compile(f".*{re.escape(title)}.*", flags)`; `to_have_title(pattern)`.
   → checkpoint: Playwright python `to_have_title` accepts a compiled regex;
   case-insensitivity via the pattern flag (playwright.md documents exactly this).
4. **Output**: auto-waiting assertion; failure raises `AssertionError` inside the settle
   window semantics — unchanged failure classification surface.

#### Checkpoint Summary
- Default path byte-identical behavior (case-sensitive): passed — the default flag value
  reproduces the current lambda/regex exactly.
- Text *locating* untouched: passed (`get_by_text`, `filter(has_text=…)`) — matches
   facade.md note and ADR decision 6.

### Trace: `StepSteering.steer` step 6 (the write-back gate)

#### Chain
1. **Input**: green guided execution (`run_step_code(code, page)` succeeded) — the gate
   runs **after** the execution try/except, before `_write_back`.
2. `findings = check_step_compliance(self._config, self._provider, failure.step_text,
   code)` inside `try/except (LLMUnavailableError, ComplianceVerdictError) as
   gate_failure`: → `print(f"compliance gate failed: {gate_failure}")` (the kind travels
   in the message text: "llm unavailable: …" / "compliance verdict unparsable — …");
   `logger.warning("compliance gate failed", extra={"step_text": …, "gate_failure":
   str(gate_failure)})`; `return None` — the original terminal failure propagates from
   the executor. → checkpoint: gate hard failures end the dialog — matches the contract;
   `return None` keeps "every exit path either heals or returns None".
3. `high` finding → `print` the violation (instruction + explanation); history turn
   `f"{message} => instruction violated: {_first_line(high.instruction)}"`; `continue`
   → step 2 (re-prompt). → checkpoint: no write-back, no `on_healed`, budget-free.
4. medium/low → WARNING (`"compliance findings passed"`, extra step + findings) →
   `_write_back` (save + `on_healed` + green line).
5. **Output**: healed `CachedStep` or `None`; nothing cached on block/hard-failure.

#### Checkpoint Summary
- The gate sits outside the generic `except Exception as outcome` of the execution
  block: passed (otherwise the hard failures would degrade into red turns).
- Steering imports `check_step_compliance` from the engine cell (declared import edge);
  `ComplianceVerdictError` is imported at implementation level for the except clause —
  uniform with the existing undeclared `LLMUnavailableError` implementation import; the
  contract edges stay exactly as planned.

### Trace: root propagation (`StepExecutor.execute` → `PrettyPlay.step`)

#### Chain
1. A gate hard failure raised inside `generate`/`regenerate`/`heal`/`steer`-None-return
   paths: not an `IncurableStepError` → the steering intercept never triggers (contract
   note in the plan: uniform with `LLMUnavailableError`).
2. `executor.execute` outer `except Exception as error`: `on_step_failed` payload
   `{"step_text", "step_type", "error": str(error)}` — the message verbatim;
   `error.verdict` attribute absent → no `on_step_verdict`. → checkpoint:
   `ComplianceVerdictError` has no `verdict` attribute — the `isinstance(…,
   (ProductDefectError, IncurableStepError))` guard already excludes it.
3. `on_step_finished` in `finally` (outcome "failed").
4. `PrettyPlay.step`/`expect`: `except PrettyplayError` → `_raise_folded(error)` —
   `ComplianceVerdictError` derives from `PrettyplayError` → folded traceback, runner
   sees the boundary frame only. → checkpoint: derivation requirement of the failures
   contract is load-bearing exactly here.
5. **Output**: runner sees `ComplianceVerdictError` with the actionable message.

#### Checkpoint Summary
- Zero structural changes needed at executor/scenario beyond docstring enumerations:
  passed — the root CODEMANIFEST changes are text-only by design and the trace confirms
  it.

---

## Algorithm Design

### `ComplianceVerdictError` (failures)

**Responsibility**: the hard failure of an unusable compliance verdict — the candidate
executed but was never verified, so it was never cached.

**Algorithm** (mirrors `LLMUnavailableError` exactly):
```
1. __init__(message): self.message = message; super().__init__(message)
```

**Errors**: raised only by `parse_compliance_verdict`; catchable as `PrettyplayError`.

**Edge Cases**: carries no verdict, no step fields — uniform with the infrastructure
failure; `errors.py` module docstring "three distinct kinds" → "four distinct kinds";
`failures/__init__.py` gains the export.

### `ComplianceFinding` (llm)

**Responsibility**: one parsed finding — instruction quote, priority label, explanation.

**Algorithm**: pydantic v2 model, `model_config = ConfigDict(kw_only=True)`, fields
`instruction: str = ""`, `priority: str = ""`, `explanation: str = ""` (empty defaults per
`conventions`; unreachable through the parse path, which validates before constructing);
properties are the fields. No priority validation in the model — the parse fails loudly
before anything invalid reaches the type.

### `parse_compliance_verdict` (llm)

**Responsibility**: the strict single parsing point of the gate.

**Algorithm**:
```
1. data = json.loads(verdict_text.strip())            → ValueError: malformed
2. IF not isinstance(data, list)                      → malformed
3. FOR item IN data:
     IF not isinstance(item, dict)                    → malformed
     instruction, priority, explanation = item.get(...) each
     IF any value is missing or not a str             → malformed
     IF priority not in {"high","medium","low"}       → malformed
     append ComplianceFinding(instruction=…, priority=…, explanation=…)
4. RETURN findings                                    → [] means compliant

malformed: raise ComplianceVerdictError(
    "compliance verdict unparsable — expected a JSON list of findings with "
    "instruction, priority high|medium|low and explanation; received fragment: "
    + _answer_fragment(verdict_text))
_answer_fragment: whitespace-collapsed first 200 characters of the raw text
```

**Errors**: `ComplianceVerdictError` on every malformed shape; nothing else raises.

**Edge Cases**: `[]` → compliant; whitespace-padded JSON tolerated (trim); extra keys in
an item tolerated; empty-string field values tolerated (not named malformed by the
contract — the calibration, not the parser, judges usefulness).

### `build_compliance_fields` (llm `_request.py`)

**Responsibility**: the shared request body of both providers — parity by construction.

**Algorithm**: join `f"INSTRUCTIONS:\n{user_instructions}"`, `f"STEP:\n{step_text}"`,
`f"CODE:\n{code}"` with blank lines — the fixed block order; no optional blocks (the
engine guarantees non-empty instructions; step and code are always present).

### `LLMProvider.check_instruction_compliance` + implementations

**Responsibility**: the verdict request of the port.

**Algorithm** (port: `raise NotImplementedError`, as its siblings):
```
1. text = build_compliance_fields(user_instructions, step_text, code)
2. openai:  client.chat.completions.create(model=config.effective_generation_model,
            messages=[{system: prompt}, {user: text}])
   anthropic: client.messages.create(model=config.effective_generation_model,
            system=prompt, max_tokens=REQUEST_MAX_TOKENS, messages=[{user: text}])
   SDK error → LLMUnavailableError("llm unavailable: {provider} request failed")
3. answer = require_completion_text(extract(response), provider)
4. RETURN parse_compliance_verdict(answer)              # no fence unwrapping
```

**Errors**: `LLMUnavailableError` (service), `ComplianceVerdictError` (unparsable) —
both hard.

**Edge Cases**: no screenshot input on this operation (the prompt's input list has none);
lazy client construction and env-only keys identical to the other operations;
provider docstrings/class docstrings updated "two operations" → three.

### `check_step_compliance` (engine `compliance.py`)

**Responsibility**: the single compliance check of every caching path.

**Algorithm**:
```
1. IF not config.generation_approve OR not config.generation_prompt:
       RETURN []                                       # zero provider calls, old behavior
2. RETURN provider.check_instruction_compliance(
       prompt=COMPLIANCE_PROMPT,
       user_instructions=config.generation_prompt,
       step_text=step_text, code=code)
```

`COMPLIANCE_PROMPT` is the frozen local mirror of the `compliance_prompt` practice
(inline in the engine CODEMANIFEST) — the `CLASSIFICATION_PROMPT` pattern: constant +
module docstring note that it changes only together with the CODEMANIFEST practice.

**Errors**: both hard failures propagate — the routine never swallows, never logs, never
caches.

**Edge Cases**: never called for replayed cached code (all three call sites are
candidate-green branches); consumes no budget.

### `StepGenerator` gate helpers

**Responsibility**: the loop-level decision layer over the findings.

**Algorithm**:
```
_high_finding(findings)  → the first finding with priority "high", else None
   (first by list order — the verdict's own ordering; the gate re-runs on the next
   candidate and catches any remaining violation)
_violation_text(finding) → f"violated instruction: {finding.instruction} — {finding.explanation}"
   (the ERROR block text of the failed attempt and the steering dialog line)
_medium_warning(step_text, findings) → logger.warning(
   "compliance findings passed",
   extra={"step_text": step_text,
          "findings": [f"{f.priority}: {f.instruction} — {f.explanation}" for f in findings]})
_reason_safe(instruction) → first line, colons replaced by spaces (the first-line contract)
```

**Edge Cases**: `on_generation_started` and the attempt ordinal count **generation**
attempts only — the gate request fires no hook event (the event name and payload track
generation; hook semantics stay identical across the gate switch).

### `StepGenerator._generation_loop` (changed)

**Algorithm** (delta to the existing loop):
```
state += standing: ComplianceFinding | None = None
on green (else branch):
    findings = check_step_compliance(config, provider, step_text, code)
    high = _high_finding(findings)
    IF high: existing_code = code; error = _violation_text(high); standing = high; continue
    IF findings: _medium_warning(step_text, findings)
    RETURN _store(identity, code)
on other candidate failure (except branch): standing = None; …existing retry logic…
on budget refusal (loop top): _exhaustion_outcome(..., standing)
```

**Errors**: unchanged decision tables for checks/exhaustion; the new standing-high
exhaustion branch below.

### `StepGenerator._exhaustion_outcome` (changed)

**Algorithm** (new first branch, before the existing classification):
```
IF standing is not None:
    verdict = FailureVerdict(
        category="incurable",
        explanation=f"{standing.instruction} — {standing.explanation}",
        recommendation=f"follow the violated instruction in the step code: {standing.instruction}")
    raise IncurableStepError(
        step_text,
        f"generation attempt budget exhausted — violated instruction {_reason_safe(standing.instruction)}",
        error=violation_text, code=code, verdict=verdict)
… existing error-is-None / classify / decision-table logic unchanged …
```

**Edge Cases**: no LLM classification on this branch (the verdict comes from the
finding); `healing_attempts`-funded regeneration is **not** granted here — the standing
high finding already consumed the failed attempt, the pool is exhausted.

### `StepGenerator._healing_loop` (changed)

**Algorithm** (delta): the same else-branch gate as `_generation_loop` minus `standing`
(the contract's regenerate step 2: exhaustion raises with the entry verdict — the healer
reattaches it; the violation text rides `error`). High → `existing_code = code; error =
_violation_text(high); continue`.

### `StepGenerator._funded_regeneration` (changed)

**Algorithm** (delta): after the `settle` try/except (in the implicit else, outside every
`try`):
```
findings = check_step_compliance(...)          # hard failures propagate
high = _high_finding(findings)
IF high: RETURN None, code, _violation_text(high), False   # a repeat failure of the funded attempt
IF findings: _medium_warning(step_text, findings)
RETURN _store(identity, code), code, "", False
```

**Edge Cases**: `repeat_was_check=False` — a compliance block is a candidate failure, not
a check: `_failed_check_outcome` runs its one final classification with reason
"candidate failed — …"; `_exhaustion_outcome` stays terminal without reclassification.
The single funded attempt is not repeated — "exactly one regeneration" holds.

### `StepSteering.steer` (changed)

**Algorithm** (delta at the green branch): per the trace above — gate outside the
execution `try`; hard failure → gate line + WARNING + `return None`; high → dialog line +
history turn + `continue`; medium/low → WARNING + `_write_back`. Dialog print lines:
`f"compliance gate failed: {gate_failure}"` and
`f"compliance violation — not written back: {violation}"`.

Steering picks the first high finding inline — `next((f for f in findings if
f.priority == "high"), None)` — and renders the dialog line from `finding.instruction`
and `finding.explanation` directly; no engine-private helper import — the declared
engine→steering edge stays `check_step_compliance` plus `run_step_code` only.

### `PageFacade.expect_title` / `LocatorFacade.expect_text` (changed)

**Algorithm**: per the traces — flag OR-ed into `re.DOTALL` for the title regex;
`ignore_case=` forwarded to `to_contain_text`; Google-style docstrings with the
`ignore_case` arg described exactly as the CODEMANIFEST annotations do.

### `Config` / `load_config` (changed)

**Algorithm**: per the traces — one field, three loader tables, docstrings.

---

## Cross-cutting Concerns

- **Error handling**: the taxonomy owns the kinds — `ComplianceVerdictError` joins the
  LLM contour (blocks generation only, never cached execution); the gate's two hard
  failures are never swallowed anywhere on the path (the single deliberate softening is
  the steering dialog, which *ends* and declines — still nothing cached); retry loops
  treat a high finding as an attempt failure with a targeted ERROR, never as an
  exception. A failed classification stays quietly skipped with a WARNING — unchanged;
  the gate is deliberately stricter (ADR decision 4).
- **Logging**: one library logger (`logging.getLogger("prettyplay")`). New events —
  `"compliance findings passed"` (WARNING; extra: `step_text`, rendered findings list)
  on every engine path; `"compliance findings passed"` (WARNING) and
  `"compliance gate failed"` (WARNING; extra: `step_text`, `gate_failure`) in steering.
  No payloads carry API keys; findings carry user instruction text only (non-secret).
- **Validation**: config validates at the pydantic boundary (bool field) and the env
  boundary (`_parse_env_scalar`, loud `ConfigurationError`); the verdict validates at
  the single parse point (strict, no fallback); the facade validates nothing new
  (Playwright owns assertion semantics).
- **Caching**: the gate is a precondition of `StepCache.save` on every candidate path
  (two loops, funded regeneration, steering write-back) — an unchecked candidate is
  never stored; replayed cached code never re-gates; instructions stay outside the step
  address (manual purge documented in `configuration.md`).
- **Concurrency**: no new threads; gate calls run on the calling thread exactly like
  every provider request; the facade additions stay behind the driver-thread marshal
  (`_call`). The steering dialog remains single-threaded and budget-free.

---

## Usages Analysis

### `conventions` (all changed cells)
- **What it provides**: Python writing/testing rules — relative imports, pydantic v2
  `kw_only`, docstrings, structured logging, test structure.
- **Where used**: every entity designed above; tests mirror source paths.
- **Why chosen**: project base practice (`.goga/config.yml`).
- **How exactly**: `ComplianceFinding` follows the pydantic rules; `compliance.py`
  follows module style; tests land in mirrored `tests/<pkg>/test_<module>.py` files.

### `compliance_prompt` (engine, inline)
- **What it provides**: the gate system prompt — inputs INSTRUCTIONS/STEP/CODE, the JSON
  findings answer shape, priority calibration (high only for confident, material,
  followable violations; doubt never high), conditional-compliance rules.
- **Where used**: `check_step_compliance` step 2; global annotation binding line.
- **Why chosen**: the calibration is the ADR's mitigation of the hyper-strict-checker
  risk — it lives in the prompt because only the verdict model can judge followability
  from code + step sentence.
- **How exactly**: frozen as `COMPLIANCE_PROMPT` in `compliance.py`, passed verbatim as
  the system message of every verdict request.

### `system_prompt` (engine + steering, `.goga/usages/prompts/generation.md`)
- **What it provides**: the generation prompt — now with binding USER INSTRUCTIONS
  (below the safety core), the loud-conflict rule (`instruction conflicts with rule Y`),
  and the conditional prefer-type rule.
- **Where used**: `StepGenerator._request`, `StepSteering._guided_request`; the mirror
  annotations of both cells.
- **Why chosen**: prompt-layer enforcement is one of the three root-cause fixes.
- **How exactly**: frozen mirrors `SYSTEM_PROMPT` in `generator.py` and `steering.py`
  updated in the same change; sync tests enforce byte equality with the practice section
  after the `---` separator.

### `classification_prompt` (engine, inline)
- **What it provides**: classification prompt with the binding wording — wording only,
  no gate (ADR decision 9).
- **Where used**: `classify_step_failure` step 2.
- **How exactly**: `CLASSIFICATION_PROMPT` mirror line updated to the exact CODEMANIFEST
  text.

### `facade` (driver → engine/steering, `prettyplay/driver/.usages/facade.md`)
- **What it provides**: the consumer surface of the facade — the single source of
  `PAGE_API_SURFACE`.
- **Where used**: engine/steering annotations ("the listing and the practice change
  together").
- **How exactly**: both mirror constants' `expect_title`/`expect_text` rows updated in
  the same change as the driver methods and the practice rows.

### `classification` (llm → engine, `prettyplay/llm/.usages/classification.md`)
- **What it provides**: classification categories and call pattern — read for the
  healing-path context; unchanged by this task.

### `openai` / `anthropic` (llm, cooks)
- **What they provide**: SDK call patterns incl. the new compliance call sections;
  error mapping to `LLMUnavailableError`.
- **How exactly**: the designed implementations follow the cook snippets — system+user
  messages, `build_compliance_request` equivalent (`build_compliance_fields`), verdict
  text extracted, anthropic `max_tokens=4096`.

### `playwright` (driver, cook)
- **What it provides**: the case-insensitive expectation API —
  `to_contain_text(expected, ignore_case=…)` (≥1.44), `to_have_title` compiled-regex
  matching with `re.IGNORECASE`, and the note that text *locating* is already
  case-insensitive by default.
- **How exactly**: the two facade methods map exactly onto these calls; the project pins
  `playwright>=1.49`.

### `pydantic` (config, cook) / `taxonomy` (failures → config/root), `configuration` (config → driver), `providers`/`taxonomy` (llm/failures `.usages`)
- Read for context; unchanged by this task beyond what apply-architecture already
  materialized.

---

## `.usages/` Update

All six affected `.usages` files were materialized by apply-architecture; the Phase 4
Step 6 verification against the final CODEMANIFEST (including the three applied defect
fixes) finds them **current** — no further additions.

### Cell: `prettyplay/failures`
- **`taxonomy.md`** → current (intro four+fifth kinds; `ComplianceVerdictError` table
  row; self-contained section with catch example and engineer notes; matches the final
  contract, including "never cached" and the off-switch note).

### Cell: `prettyplay/config`
- **`configuration.md`** → current (TOML line after `generation_prompt`; env row without
  backticks matching the table style; "The instruction compliance gate" section with
  cost/high-finding/cache-purge/empty-instructions notes).

### Cell: `prettyplay/driver`
- **`facade.md`** → current (two surface rows with `ignore_case`; the case-insensitive
  assertions example section after Interactions; the locating-is-already-insensitive
  note).

### Cell: `prettyplay/llm`
- **`providers.md`** → current (three operations in Parity; effective-generation-model
  note; "The compliance operation" section).

### Cell: `prettyplay/engine`
- **`generation.md`** → current ("The instruction compliance gate" section: verdict cost,
  high/medium-low/malformed semantics, never-re-gated note).
- **`healing.md`** → current (the first rule of `## Rules`: the healed candidate passes
  the gate before the write-back).

### Cell: `prettyplay/engine/steering`
- **`steering.md`** → current ("The compliance gate of a guided heal" section).

No new `.usages` files: every change falls inside an existing functional domain
(decision rule — supplement, don't split). No CODEMANIFEST `Usages` key points at own
`.usages` files.

---

## Test Stack Trace

### General Setup

- Fake provider (extend the existing `StubProvider` idiom in
  `tests/engine/test_generator.py`): records `check_instruction_compliance` kwargs into
  `compliance_calls`; returns a scripted verdict — a list built from
  `ComplianceFinding(...)` literals, or a raise (`LLMUnavailableError` /
  `ComplianceVerdictError`); default return `[]`.
- Fake page/locator (existing `FakePage`/`FakeLocator` in `tests/engine/test_generator.py`
  and the driver fakes in `tests/driver/test_page.py`): locators record
  `("expect_text", text, {"ignore_case": …})`; the fake page records
  `("expect_title", pattern)`.
- Existing fixtures: `write_pyproject` (tests/conftest.py), `RunBudgets`, `StepCache`
  on `tmp_path`.
- Mirror-sync helpers: read the practice file, split on the first `---`, compare to the
  constant (existing pattern in `test_generator.py:1144` and
  `test_steering.py:230`).
- Run: `pytest tests/ -x` in the project virtualenv; `ruff check` clean.

### Source File Registry

`prettyplay/failures/errors.py`, `prettyplay/failures/__init__.py`,
`prettyplay/config/models.py`, `prettyplay/config/loader.py`,
`prettyplay/driver/page.py`, `prettyplay/llm/models.py`, `prettyplay/llm/_request.py`,
`prettyplay/llm/provider.py`, `prettyplay/llm/openai_provider.py`,
`prettyplay/llm/anthropic_provider.py`, `prettyplay/llm/__init__.py`,
`prettyplay/engine/compliance.py` (new), `prettyplay/engine/generator.py`,
`prettyplay/engine/classification.py`, `prettyplay/engine/__init__.py`,
`prettyplay/engine/steering/steering.py`, `prettyplay/executor.py`,
`prettyplay/scenario.py`, and the two mirrors + practice files under sync tests.

---

### Positive Tests

#### `test_compliance_verdict_error_is_a_library_failure` (tests/failures/test_errors.py)

**Setup**: none.
**Input**: `ComplianceVerdictError("compliance verdict unparsable — … fragment: []")`.
**Trace**:
```
ComplianceVerdictError(message)
  → PrettyplayError.__init__(message)      # base chain
    self.message = message
  → assert isinstance(err, PrettyplayError) and not isinstance(err, AssertionError)
  → assert err.message == message and str(err) == message
  → assert not hasattr(err, "verdict")
```
**Assertions**: derivation, message attribute, no verdict field (it is not a terminal
step classification).
**Sufficiency**: the single-`except`-clause contract of the taxonomy; prevents the error
accidentally deriving from `AssertionError` (a gate failure is an error, not a check).

#### `test_generation_approve_defaults_true` (tests/config/test_models.py)

**Setup**: `config = Config()`.
**Input**: —.
**Trace**: `Config()` → pydantic defaults → `config.generation_approve`.
**Assertions**: `is (config.generation_approve, True)`; `generation_approve in
Config.model_fields`.
**Sufficiency**: the opt-out default is the product line (loud errors by default); a
regression to False would silently disable the gate everywhere.

#### `test_generation_approve_env_override_parses_booleans` (tests/config/test_loader.py)

**Setup**: `write_pyproject()` (empty section); `monkeypatch.setenv(
"PRETTYPLAY_GENERATION_APPROVE", raw)`; parametrize `raw ∈ {"true","FALSE","1","0","True"}`,
expected `∈ {True,False,True,False,True}`.
**Input**: `load_config(pyproject_path)`.
**Trace**:
```
load_config → _collect_env_overrides
  → _parse_env_scalar("generation_approve", raw)   # _BOOL_ENV_SETTINGS membership
    returns True/False
  → merged into Config(**merged)
```
**Assertions**: `config.generation_approve is expected`.
**Sufficiency**: the CI override channel; case-insensitive boolean parsing is the
documented contract of the configuration practice.

#### `test_generation_approve_explicit_false_overrides_the_file_layer` (tests/config/test_loader.py)

**Setup**: `write_pyproject(generation_approve=True)`.
**Input**: `load_config(path, overrides=PrettyConfig(generation_approve=False))`.
**Trace**: file layer True → `_apply_overrides`: field in `model_fields_set`, False is
not None and not a str → participates.
**Assertions**: `config.generation_approve is False`.
**Sufficiency**: the `strict`/`interactive` merge pattern for booleans — without this, a
per-test opt-out would be impossible (False would be filtered as "unset").

#### `test_check_step_compliance_returns_empty_with_zero_calls_when_off` (tests/engine/test_compliance.py)

**Setup**: `Config(generation_approve=False, generation_prompt="Prefer id attributes")`;
`StubProvider()` (records calls).
**Input**: `check_step_compliance(config, provider, "click Sign in", CODE)`.
**Trace**: step 1 disjunct 1 → `return []` before any provider touch.
**Assertions**: result `== []`; `provider.compliance_calls == []` (zero calls).
**Sufficiency**: the off-switch must restore the old behavior exactly — including zero
LLM cost; guards the "never runs" contract.

#### `test_check_step_compliance_returns_empty_when_instructions_empty`

**Setup**: `Config(generation_approve=True, generation_prompt="")`.
**Input/Trace/Assertions**: as above via the second disjunct — `[]`, zero calls.
**Sufficiency**: the port requirement "the calling engine guarantees non-empty" is
enforced here; an empty-instructions gate call would send a vacuous INSTRUCTIONS block.

#### `test_check_step_compliance_passes_practice_prompt_and_instructions`

**Setup**: `Config(generation_approve=True, generation_prompt="Prefer id attributes")`;
fake returns `[]`.
**Input**: `check_step_compliance(config, provider, "click Sign in", CODE)`.
**Trace**: step 2 → recorded kwargs.
**Assertions**: `call["prompt"] == COMPLIANCE_PROMPT` (byte-equal to the
`compliance_prompt` practice text of the engine CODEMANIFEST); `call[
"user_instructions"] == "Prefer id attributes"`; `call["step_text"]`,
`call["code"]` passed through.
**Sufficiency**: the practice binding — the gate system prompt is the calibrated
contract; drifting it breaks the priority semantics.

#### `test_openai_check_instruction_compliance_request_and_parse` (tests/llm/test_openai_provider.py)

**Setup**: `OpenAIProvider(Config(model="gpt-x"))` with the client mocked
(`mock.patch.object(provider, "_get_client")`); SDK response object whose first choice
message content is `'[{"instruction": "Prefer id attributes", "priority": "high",
"explanation": "locates by text"}]'`.
**Input**: `provider.check_instruction_compliance(prompt="P", user_instructions="Prefer
id attributes", step_text="click Sign in", code=CODE)`.
**Trace**:
```
build_compliance_fields → "INSTRUCTIONS:\nPrefer id attributes\n\nSTEP:\nclick Sign in\n\nCODE:\n…"
chat.completions.create(model="gpt-x", messages=[system P, user text])   # recorded
→ _first_choice_text → require_completion_text
→ parse_compliance_verdict → [ComplianceFinding(instruction=…, priority="high", …)]
```
**Assertions**: exactly one create call; `model == "gpt-x"` (effective generation
model); system message is `P`; user content is the three blocks in the fixed order; one
finding returned with the parsed fields; no `ignore`/screenshot keys anywhere.
**Sufficiency**: parity half 1 of the third operation — request shape, model choice and
strict parse in one.

#### `test_anthropic_check_instruction_compliance_parity` (tests/llm/test_anthropic_provider.py)

**Setup**: `AnthropicProvider(Config(model="claude-x"))`, client mocked; response with
one text block carrying the same verdict JSON.
**Input**: identical.
**Trace**: `messages.create(model="claude-x", system="P", max_tokens=4096,
messages=[user text])` → `_first_text_block` → parse.
**Assertions**: same user content string as the openai test (shared builder — assert
equal to `build_compliance_fields(...)` output); `max_tokens == 4096`; same findings.
**Sufficiency**: parity half 2 + the SDK-forced cap — the parity requirement is a
contract line, not a courtesy.

#### `test_parse_compliance_verdict_parses_findings` (tests/llm/test_models.py)

**Setup**: none.
**Input**: `'  [{"instruction": "Make text matching checks case-insensitive",
"priority": "high", "explanation": "expect_text without the flag"},
{"instruction": "Prefer ids", "priority": "low", "explanation": "minor"}]  '` (padded).
**Trace**: trim → `json.loads` → two dict items validated → two models.
**Assertions**: `len(findings) == 2`; `findings[0].priority == "high"`;
`findings[1].priority == "low"`; instruction/explanation verbatim.
**Sufficiency**: the single parse point feeding every gate decision; padding tolerance
mirrors real model answers.

#### `test_expect_text_passes_ignore_case_to_playwright` (tests/driver/test_page.py)

**Setup**: fake locator recording calls, wrapped in `LocatorFacade`.
**Input**: `facade.expect_text("SUCCESS", ignore_case=True)`.
**Trace**: `_call(...)` → recorded `("expect_text", "SUCCESS", {"ignore_case": True})`.
**Assertions**: the recorded kwargs; default call `expect_text("SUCCESS")` records
`{"ignore_case": False}`.
**Sufficiency**: the expressibility fix — the instruction "case-insensitive checks" is
now expressible; the default keeps the old semantics bit-for-bit.

#### `test_expect_title_compiles_case_insensitive_pattern` (tests/driver/test_page.py)

**Setup**: fake page recording `("expect_title", pattern)`.
**Input**: `facade.expect_title("dashboard", ignore_case=True)`.
**Trace**: flags `re.DOTALL | re.IGNORECASE` → compiled pattern → `to_have_title(pattern)`.
**Assertions**: `pattern.flags & re.IGNORECASE`; `pattern.match("My Dashboard")` is not
None; the default-path pattern has no IGNORECASE flag and `pattern.match("DASHBOARD")`
is None.
**Sufficiency**: the second half of the capability; locks the regex-flag mechanism the
playwright cook documents.

#### `test_generate_gates_candidate_and_stores_on_compliant` (tests/engine/test_generator.py)

**Setup**: `Config(generation_approve=True, generation_prompt="Prefer id attributes")`;
fake provider: `generate_step_code` returns WORKING_CODE; compliance returns `[]`;
`StepCache` on `tmp_path`; `RunBudgets()`; window off.
**Input**: `generator.generate(identity, "open example.com", [], page, window)`.
**Trace**: attempt 1 → candidate green → gate called once with the candidate code →
`[]` → `_store` → cache save.
**Assertions**: returned `CachedStep.code == WORKING_CODE`; cache file exists;
`provider.compliance_calls[0]["code"] == WORKING_CODE`; one generation call, one
compliance call.
**Sufficiency**: the happy gate-on path — the gate runs exactly once per green
candidate and stores on compliance.

#### `test_generate_high_finding_fails_attempt_and_retry_carries_violation`

**Setup**: as above; provider script: candidate 1 = `WORKING_CODE` (non-compliant),
compliance 1 → `[ComplianceFinding("Prefer id attributes", "high", "locates by text")]`;
candidate 2 = COMPLIANT_CODE, compliance 2 → `[]`.
**Input**: `generate(...)`.
**Trace**: attempt 1 green → high → `error = "violated instruction: Prefer id
attributes — locates by text"` → attempt 2 request recorded with
`error=violation_text`, `existing_code=WORKING_CODE` → green → gate → `[]` → store.
**Assertions**: the second `generate_step_code` call's `error` kwarg equals the
violation text and `existing_code == WORKING_CODE`; exactly 2 generation calls, 2
compliance calls; cache stores COMPLIANT_CODE only (assert cache content); no WARNING
records.
**Sufficiency**: the core retry mechanic of the policy — the model receives the targeted
violation, not a generic failure; prevents regressions to blind retries or to caching
the violating candidate.

#### `test_generate_medium_low_findings_pass_with_warning` (uses `caplog`)

**Setup**: compliance returns `[ComplianceFinding("Prefer ids", "medium", "minor"),
ComplianceFinding("Add waits", "low", "cosmetic")]`.
**Input**: `generate(...)` with WORKING_CODE twice.
**Trace**: green → no high → WARNING → store.
**Assertions**: `any(r.name == "compliance findings passed" and r.levelno ==
logging.WARNING for r in caplog.records)`; the record's `step_text` extra matches; the
rendered findings contain both priorities; returned step code == WORKING_CODE; cache
saved (visible, non-blocking).
**Sufficiency**: the calibration contract — minor findings never block; silent storage
without visibility would hide them.

#### `test_generate_budget_exhaustion_with_standing_high_names_instruction`

**Setup**: `Config(generation_attempts=2, …)`; compliance always high on the same
instruction; candidates always WORKING_CODE (green but non-compliant).
**Input**: `generate(...)`.
**Trace**: attempt 1 green → high → retry; attempt 2 green → high → loop top
`try_generation` refused → standing branch → verdict built from the finding.
**Assertions**: raises `IncurableStepError`; `exc.verdict.category == "incurable"`;
`exc.verdict.explanation == "Prefer id attributes — locates by text"`;
`exc.verdict.recommendation` contains the instruction; `exc.reason == "generation
attempt budget exhausted — violated instruction Prefer id attributes"` (colon-free —
assert `":" not in exc.reason.split("\n")[0]`); `exc.error == violation_text`;
`exc.code == WORKING_CODE`; **no** `classify_failure` call (the fake records it) — the
verdict came from the finding; nothing in the cache.
**Sufficiency**: the terminal loud-error path of the policy; guards both the
verdict-from-finding construction and the no-extra-LLM-call guarantee.

#### `test_regenerate_gates_healed_candidate_before_write_back` (tests/engine/test_generator.py)

**Setup**: healing-budget config; entry classification not needed (call `regenerate`
directly); provider: candidate 1 green but high finding, candidate 2 green and `[]`.
**Input**: `generator.regenerate(identity, step_text, [], page, existing_code=BROKEN_CODE,
error="…", recommendation="…", window)`.
**Trace**: `_healing_loop` attempt 1 → gate high → retry with violation as `error`;
attempt 2 → gate `[]` → store.
**Assertions**: second request `error == violation_text`; healed step stored;
2 compliance calls.
**Sufficiency**: the healing path is gated identically — the ADR demands the same gate
on regeneration; prevents caching a healed-but-violating candidate.

#### `test_regenerate_high_finding_exhaustion_carries_violation_and_entry_verdict`

**Setup**: `Config(healing_attempts=1, generation_approve=True, generation_prompt=
"Prefer id attributes", …)`; StubProvider: candidate = WORKING_CODE (green),
compliance always `[ComplianceFinding("Prefer id attributes", "high", "locates by
text")]`; `StepCache` on `tmp_path`; window off.
**Input**: `generator.regenerate(identity, step_text, [], page, existing_code=
BROKEN_CODE, error="TimeoutError …", recommendation="use ids", window)` under
`pytest.raises(IncurableStepError)`.
**Trace**: `_healing_loop`: `try_healing` grants attempt 1 → candidate green → gate →
high → `existing_code = code; error = violation_text` → `continue` → loop-top
`try_healing` refused → `raise IncurableStepError(step_text, "healing attempt budget
exhausted", error, code=code)` with verdict None (the healer reattaches the entry
verdict).
**Assertions**: `exc.error == "violated instruction: Prefer id attributes — locates by
text"`; `exc.reason == "healing attempt budget exhausted"`; `exc.verdict is None` (the
verdict is reattached by the healer, not built inside the loop); `exc.code ==
WORKING_CODE`; exactly 1 generation call and 1 compliance call; zero `classify_failure`
calls; nothing in the cache.
**Sufficiency**: pins the error-field contract of the healing exhaustion under the gate
and the no-extra-classification guarantee — a regression to a generic error text or an
extra LLM call would otherwise pass unnoticed.

#### `test_steer_high_finding_never_reaches_cache` (tests/engine/steering/test_steering.py)

**Setup**: existing steering fixtures (stdin scripted via `mock.patch("builtins.input")`:
guidance 1, then guidance 2); fake provider: guided candidate 1 green with a high
finding, candidate 2 green with `[]`; cache on `tmp_path`.
**Input**: `steering.steer(failure, identity, [], page)`.
**Trace**: turn 1 → green → gate → high → dialog prints the violation → history turn
appended → re-prompt; turn 2 → green → `[]` → `_write_back` → `on_healed`.
**Assertions**: returns a `CachedStep` whose code is candidate 2; the cache holds
candidate 2 only; the second guided request's `guidance_history` carries a turn
containing the instruction; stdout captured the violation line; no budget consumption
(`RunBudgets` untouched).
**Sufficiency**: the write-back guard of the dialog — a high violation must never land
in the cache, and the engineer must see why.

#### `test_steer_medium_findings_pass_with_warning_and_write_back`

**Setup**: existing steering fixtures; `_script_input(monkeypatch, ["use the id
locator"])`; StubProvider: guided candidate green, compliance →
`[ComplianceFinding("Prefer ids", "medium", "minor")]`; cache on `tmp_path`; `caplog`
at the "prettyplay" logger.
**Input**: `steering.steer(failure, identity, [], page)`.
**Trace**: turn 1 → green → gate → no high → WARNING ("compliance findings passed",
extra: step + findings) → `_write_back` → cache save + `on_healed` + the green line.
**Assertions**: a `CachedStep` with the candidate code is returned; the cache file
exists; hooks saw `on_healed`; `caplog` holds a `"compliance findings passed"` record
at WARNING level with the `step_text` extra; stdout carries no violation line
("compliance violation").
**Sufficiency**: pins the calibration contract of the dialog — only high blocks the
write-back; medium and low are visible but never blocking.

#### `test_steer_gate_hard_failure_ends_dialog_returning_none`

**Setup**: input scripted with one guidance; compliance raises
`ComplianceVerdictError("compliance verdict unparsable — … fragment: 'nope'")` after a
green execution.
**Input**: `steer(...)`.
**Trace**: green → gate raises → gate line printed → WARNING logged → `return None`.
**Assertions**: result `is None`; cache file absent; `caplog` has
`"compliance gate failed"` with the step extra; stdout contains "compliance gate failed"
and the fragment; the original failure propagates from the executor path in the
integration variant.
**Sufficiency**: the hard-failure semantics of the dialog — unchecked green code is
never written back, and the engineer sees the gate failure, not a silent decline.

#### `test_step_surfaces_compliance_verdict_error` (tests/test_scenario.py)

**Setup**: scenario with fake provider whose compliance raises `ComplianceVerdictError`;
page faked so generation reaches the gate (or unit-level: executor with a generator
whose provider raises).
**Input**: `scenario.step("open example.com")`.
**Trace**: executor → generate → gate raise → `on_step_failed` payload → re-raise →
`_raise_folded`.
**Assertions**: `pytest.raises(ComplianceVerdictError)`; hooks saw `on_step_failed`
with the message and **no** `on_step_verdict`; `on_step_finished` outcome "failed"; the
raised traceback contains no engine frames (folding).
**Sufficiency**: the end-to-end loud surface — the runner-visible behavior of the whole
feature.

#### Mirror-sync tests (updated existing: `test_system_prompt_mirrors_the_generation_practice`, `test_steering_mirrors_the_practices`; plus the `PAGE_API_SURFACE` row checks)

**Setup**: practice files read from the repo.
**Input**: compare `SYSTEM_PROMPT` (both files) to the practice section after `---`;
compare both `PAGE_API_SURFACE` constants to the facade.md surface (name-level rows plus
the two updated rows).
**Assertions**: byte equality of the prompt mirrors; both surface mirrors equal each
other; `page.expect_title(title, ignore_case)` and `element.expect_text(text,
ignore_case)` present in both; `CLASSIFICATION_PROMPT` contains "binding classification
guidance" line verbatim.
**Sufficiency**: the three-place prompt split is the ADR's named regression risk —
these tests are the mitigation named in the acceptance list.

#### `test_compliance_prompt_mirror_matches_the_code_manifest_practice` (tests/engine/test_compliance.py)

**Setup**: `codemanifest_text = Path("prettyplay/engine/CODEMANIFEST").read_text(
encoding="utf-8")`; `from prettyplay.engine.compliance import COMPLIANCE_PROMPT`.
**Input**: the raw CODEMANIFEST text and the frozen constant.
**Trace**: for each distinctive line of the `compliance_prompt` practice — the line is
present both in the CODEMANIFEST text (the source) and in `COMPLIANCE_PROMPT` (the
mirror).
**Assertions**:
```python
for line in (
    "only high blocks the",
    "when in doubt, never high",
    "an empty list [] means the code complies",
    "Output only the JSON list, no other text",
):
    assert line in codemanifest_text
    assert line in COMPLIANCE_PROMPT
```
**Sufficiency**: pins the frozen-mirror rule of the new gate prompt the same way the
binding classification line is pinned — without it, a calibration edit landing only in
the CODEMANIFEST (or only in the code) silently changes the gate's blocking semantics
with no failing test.

---

### Negative Tests

#### `test_parse_compliance_verdict_malformed_variants` (parametrized)

**Setup**: none.
**Input**: `["not json at all", '{"instruction": "x"}' (not a list), '[1]' (non-object),
'[{"priority": "high", "explanation": "e"}]' (missing instruction),
'[{"instruction": "i", "priority": "critical", "explanation": "e"}]' (unknown label),
'[{"instruction": 7, "priority": "high", "explanation": "e"}]' (non-str)]`.
**Trace**: each hits a malformed branch → `ComplianceVerdictError`.
**Assertions**: raises with type `ComplianceVerdictError` (and `isinstance` of
`PrettyplayError`); the message contains "compliance verdict unparsable" and the
fragment (for the non-JSON case: "not json at all").
**Sufficiency**: the strict-parse contract — every malformed shape surfaces loudly;
this is the anti-silent-pass guarantee of the whole feature.

#### `test_generation_approve_env_unparseable_fails_loudly` (tests/config/test_loader.py)

**Setup**: `write_pyproject()`; `monkeypatch.setenv("PRETTYPLAY_GENERATION_APPROVE",
"yes")`.
**Input**: `load_config(path)`.
**Trace**: `_parse_env_scalar` boolean branch → no match → raise.
**Assertions**: `pytest.raises(ConfigurationError)`; message ==
`generation_approve: received 'yes' — allowed: a boolean (true/false/1/0)`.
**Sufficiency**: never a silent ignore on the switch itself — mirrors the loader's
loud-override contract.

#### `test_openai_compliance_sdk_error_maps_to_unavailable` / `test_anthropic_compliance_sdk_error_maps_to_unavailable`

**Setup**: client mock raising `OpenAIError` / `AnthropicError` on create.
**Input**: `check_instruction_compliance(...)`.
**Assertions**: `pytest.raises(LLMUnavailableError)` with "llm unavailable:
{provider} request failed"; no findings returned; no ComplianceVerdictError (the two
kinds never alias).
**Sufficiency**: the gate's infrastructure failure kind — distinct handling from a
malformed verdict, uniform with the other two operations.

#### `test_generate_gate_hard_failure_propagates_and_caches_nothing`

**Setup**: compliance raises `ComplianceVerdictError` on the first green candidate.
**Input**: `generate(...)`.
**Trace**: green → gate raise → propagates out of the loop (no retry, no budget table).
**Assertions**: `pytest.raises(ComplianceVerdictError)`; cache directory holds no step
for the identity; exactly one generation call (no retry on the hard failure).
**Sufficiency**: the "never cached unchecked" invariant on the generation path and the
no-retry rule for hard failures.

---

### Edge Case Tests

#### `test_parse_compliance_verdict_empty_list_means_compliant`

**Input**: `"[]"` → `findings == []`. **Sufficiency**: the compliant verdict is a valid
verdict — must not be mistaken for a parse failure.

#### `test_parse_compliance_verdict_tolerates_extra_keys_and_padding`

**Input**: `'  [{"instruction": "i", "priority": "low", "explanation": "e", "note":
"x"}]  '` → one finding with the three fields. **Sufficiency**: documents the tolerance
boundary — strictness targets compliance ambiguity, not model chattiness.

#### `test_check_step_compliance_off_switch_beats_nonempty_instructions` — covered by
`..._when_off` (switch off + instructions present) and `..._instructions_empty` (switch
on + empty): the two zero-call disjuncts are independently guarded.

#### `test_funded_regeneration_gates_before_store`

**Setup**: drive `_failed_check_outcome` via a first candidate failing a check with a
rot classification; funded candidate green but high finding.
**Input**: `generate(...)` full loop.
**Trace**: funded request → green → gate → high → returns failure facts → final
classification → terminal.
**Assertions**: raises `IncurableStepError`; the final classification request's `error`
carries the violation text; cache untouched; exactly one funded request.
**Sufficiency**: the bounded-healing table under the gate — the funded attempt is gated
too, and a block is a repeat failure, not a regeneration loop.

#### `test_expect_text_default_stays_case_sensitive` — folded into
`test_expect_text_passes_ignore_case_to_playwright` (default records `ignore_case
False`); the title twin asserts the no-flag pattern.

---

## Additional Instructions for the Implementation Agent

- Follow the implementation order of *Entity Dependencies*; land the mirror coordination
  change (practice files already changed + both `SYSTEM_PROMPT` mirrors + both
  `PAGE_API_SURFACE` mirrors + `CLASSIFICATION_PROMPT` + the two driver methods) as one
  commit-scale unit — the sync tests are red until all of it lands (designed intermediate
  state, checklist items 3, 5, 8 of the plan).
- Keep `PAGE_API_SURFACE`'s aligned-column style when updating the two rows; the sync
  tests check names and mirror equality, not padding.
- Do not add `on_generation_started` events or attempt ordinals for gate requests.
- Do not touch: `example/.prettyplay/cache/**` (owner decision 2026-09-13), cells
  `prettyplay/cache`, `prettyplay/reporting`, `prettyplay/engine/polling`, the request
  shape of generation/classification (block order frozen by the llm contract), text
  locating semantics.
- Accompanying non-cell work items owned by the plan (docs pages
  `docs/configuration.md`, `docs/reference/llm-providers.md`,
  `docs/reference/step-cache.md`; acceptance-test list) follow the same semantics as
  designed here.
- Validation gates: `goga lint` (10 cells, 0 errors); `pytest tests/ -x`; `ruff check`;
  the plan's verification checklist remains the acceptance authority.

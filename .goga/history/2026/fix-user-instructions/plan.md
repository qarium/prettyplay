# Plan: `fix-user-instructions`

## Purpose

Make user instructions binding, checkable, and expressible in prettyplay. After
implementation the library provides:

1. the **instruction compliance gate** — every successfully executed generation,
   healing and steering candidate is verified against the project's user
   instructions (`generation_prompt`) through one extra LLM call before it is
   cached; a high finding fails the attempt and the retry carries the violation
   text; a malformed verdict or provider failure is a loud hard failure
   (`ComplianceVerdictError`), never a silent pass;
2. the **case-insensitive text assertion capability** — `page.expect_title(title,
   ignore_case=True)` and `element.expect_text(text, ignore_case=True)` on the
   driver facade, so "make text checks case-insensitive" instructions become
   expressible;
3. the **`generation_approve` switch** — `Config(generation_approve: bool = True)`
   with TOML, env (`PRETTYPLAY_GENERATION_APPROVE`) and programmatic layers; the
   deliberate opt-out default keeps loud errors by default;
4. the **binding prompt wording** — the generation practice gains binding USER
   INSTRUCTIONS rules; the frozen `SYSTEM_PROMPT`/`PAGE_API_SURFACE`/
   `CLASSIFICATION_PROMPT` mirrors land together with the practices.

Policy line: **an unfollowed or unfulfillable instruction must surface as a
generation error, never as silent ignoring.**

The contract state (all 7 changed CODEMANIFESTs, all cooks, all `.usages/` files,
the generation practice) is already materialized by apply-architecture and
verified by design review. The most important gap between contract and code: the
entire implementation is missing — the working tree holds only the contract and
practice layer; the two byte-equality mirror-sync tests
(`test_system_prompt_mirrors_the_generation_practice`,
`test_steering_mirrors_the_practices`) are red by design until the coordinated
mirror change lands (Task 3). Strategy: implement leaf-cells first (failures →
config → driver+mirrors → llm → engine → steering → root), each task TDD, one
ralphex iteration per task.

---

## Context

### Contract Surface

**Entity: `PrettyplayError::ComplianceVerdictError(message: str)`** (NEW)
- Type: class (failure kind mutation of the library base)
- Declared `location`: `prettyplay/failures/errors.py`
- Facade obligation: importable from `prettyplay.failures` (`__init__` export)
- Properties: `message -> str` — the rendered actionable text naming the gate and
  the raw answer fragment.
- Semantic requirements: mirrors `LLMUnavailableError` exactly —
  `self.message = message; super().__init__(message)`; derives from
  `PrettyplayError` only (never `AssertionError`); carries no verdict, no step
  fields; raised only by `parse_compliance_verdict`; the raiser guarantees
  nothing was written to the step cache. `errors.py` module docstring changes
  "three distinct kinds" → "four distinct kinds".
- Imported dependencies: none (base is local).
- Annotation cascade: taxonomy header — "four distinct, user-distinguishable step
  failure kinds"; the compliance verdict hard failure "joins the LLM contour of
  the taxonomy — it blocks only the generation contour and never touches cached
  step execution".

**Entity: `Config` (changed)** and **`load_config` (changed)**
- Type: class / function
- Declared `location`: `prettyplay/config/models.py` / `prettyplay/config/loader.py`
- Facade obligation: importable from `prettyplay.config` (already exported; the
  root re-exports `PrettyConfig`)
- Change: `Config` signature gains `generation_approve: bool` in the **last
  position** (after `send_screenshots`); pydantic v2 `kw_only`, `extra="forbid"`;
  `generation_approve: bool = True` — the deliberate opt-out default (the
  "empty defaults" convention bends by explicit contract, as `strict`/
  `interactive` bend with False); docstring Attributes entry; property
  `generation_approve -> bool` — "Whether the instruction compliance gate runs
  before caching a generated step".
- Loader: `"generation_approve"` added to `_ENV_NAMES` (→
  `PRETTYPLAY_GENERATION_APPROVE`), `_BOOL_ENV_SETTINGS`, `_ALLOWED_TEXT`
  (`"a boolean"`); module docstring line. `load_config` Algorithm step 6 gains:
  "generation_approve reads PRETTYPLAY_GENERATION_APPROVE — booleans parse
  true/false/1/0 case-insensitively; an unparseable value raises the loud
  actionable `ConfigurationError` naming the setting, the received value and the
  accepted form". Layered merge: an explicitly passed False participates and
  overrides the file layer — the `strict`/`interactive` pattern (False is not
  None and not a str, so it survives the string-emptiness guard of
  `_apply_overrides`).
- Read solely by `check_step_compliance` (engine).
- Imported dependencies: `PrettyplayError` + `taxonomy` (failures), `pydantic` cook.

**Entity: `PageFacade.expect_title(title: str, ignore_case: bool = False)`** (changed)
- Type: method of `PageFacade` — declared `location`: `prettyplay/driver/page.py`
- Facade obligation: `PageFacade` importable from `prettyplay.driver`
- Semantics: False (default) — case-sensitive, behavior unchanged; True — the
  title regex compiles with the case-insensitive flag:
  `flags = re.DOTALL | re.IGNORECASE if ignore_case else re.DOTALL`;
  `pattern = re.compile(f".*{re.escape(title)}.*", flags)`; `to_have_title(pattern)`
  accepts a compiled regex. Google-style docstring documents `ignore_case` exactly
  as the CODEMANIFEST annotation does.
- Constraint: text *locating* untouched (`get_by_text`, `filter(has_text=…)`
  stay as-is).

**Entity: `LocatorFacade.expect_text(text: str, ignore_case: bool = False)`** (changed)
- Type: method of `LocatorFacade` — declared `location`: `prettyplay/driver/page.py`
- Semantics: True forwards Playwright's own flag —
  `self._call(lambda: expect(self._locator).to_contain_text(text,
  ignore_case=ignore_case))`; Playwright python `to_contain_text(expected,
  ignore_case=…)` exists since 1.44, the project pins `playwright>=1.49`. Default
  False reproduces the current lambda exactly. Marshaled through the existing
  `_call` boundary — no raw object crosses.

**Entity: `LLMProvider.check_instruction_compliance(prompt: str, user_instructions: str, step_text: str, code: str) -> verdict: list[ComplianceFinding]`** (NEW port method)
- Type: method of the `LLMProvider` port — declared `location`:
  `prettyplay/llm/provider.py`
- Facade obligation: the port stays importable from `prettyplay.llm`
- Semantics: the third port operation in absolute parity. Port body raises
  `NotImplementedError` (as its siblings). Requirements: provider service failure
  raises `LLMUnavailableError`; the answer parses strictly through
  `parse_compliance_verdict` — a malformed verdict raises
  `ComplianceVerdictError`, no fence unwrapping; the user content carries three
  blocks in the fixed order INSTRUCTIONS, STEP, CODE — identically in both
  implementations; the gate model is the **effective generation model**; the
  input takes no part in step addressing. No screenshot input on this operation
  (the prompt's input list has none); lazy client construction and env-only keys
  identical to the other operations.

**Entity: `LLMProvider::OpenAIProvider(config: Config)` / `LLMProvider::AnthropicProvider(config: Config)`** (changed)
- Type: class mutations of the port — declared `location`:
  `prettyplay/llm/openai_provider.py` / `prettyplay/llm/anthropic_provider.py`
- Semantics (both, from the "Algorithm (all three operations)" annotations):
  1. `text = build_compliance_fields(user_instructions, step_text, code)`
  2. openai: one `client.chat.completions.create(model=config.
     effective_generation_model, messages=[{system: prompt}, {user: text}])` —
     plain string user content (no screenshot);
     anthropic: one `client.messages.create(model=…, system=prompt,
     max_tokens=REQUEST_MAX_TOKENS, messages=[{user: text}])` — the fixed 4096
     SDK-forced cap rides the verdict request too;
     SDK error (`OpenAIError`/`AnthropicError`) → `LLMUnavailableError("llm
     unavailable: {provider} request failed")` — identical mapping to the other
     operations;
  3. `answer = require_completion_text(_first_choice_text(response) /
     _first_text_block(response), provider)`;
  4. `return parse_compliance_verdict(answer)` — no fence unwrapping.
  Provider docstrings/class docstrings updated "two operations" → three.

**Entity: `ComplianceFinding(instruction: str, priority: str, explanation: str)`** (NEW)
- Type: pydantic v2 entity, properties only — declared `location`:
  `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Semantics: `model_config = ConfigDict(kw_only=True)`; fields `instruction:
  str = ""`, `priority: str = ""`, `explanation: str = ""` (empty defaults per
  conventions; unreachable through the parse path, which validates before
  constructing); **no priority validation in the model** — the parse fails loudly
  before anything invalid reaches the type. Google docstring with Attributes.

**Entity: `parse_compliance_verdict(verdict_text: str) -> findings: list[ComplianceFinding]`** (NEW)
- Type: module-level routine (pure function) — declared `location`:
  `prettyplay/llm/models.py`
- Facade obligation: importable from `prettyplay.llm`
- Semantics — the strict single parsing point of the gate:
  ```
  1. data = json.loads(verdict_text.strip())            → ValueError: malformed
  2. IF not isinstance(data, list)                      → malformed
  3. FOR item IN data:
       IF not isinstance(item, dict)                    → malformed
       instruction, priority, explanation = item.get(...) each
       IF any value is missing or not a str             → malformed
       IF priority not in {"high","medium","low"}       → malformed  (COMPLIANCE_PRIORITIES frozenset)
       append ComplianceFinding(instruction=…, priority=…, explanation=…)
  4. RETURN findings                                    → [] means compliant

  malformed: raise ComplianceVerdictError(
      "compliance verdict unparsable — expected a JSON list of findings with "
      "instruction, priority high|medium|low and explanation; received fragment: "
      + _answer_fragment(verdict_text))
  _answer_fragment: whitespace-collapsed first 200 characters of the raw text
  ```
  Edge cases: `[]` → compliant (never a parse failure); whitespace-padded JSON
  tolerated (trim); unknown extra keys in an item tolerated (strictness targets
  compliance ambiguity, not model chattiness); empty-string field values
  tolerated. No fence unwrapping, no protective fallback (contrast
  `parse_classification_line` → `unparsable_classification`, which stays
  classification-only). Pure: no state, no I/O, deterministic.

**Entity: `build_compliance_fields(user_instructions: str, step_text: str, code: str) -> str`** (NEW internal routine)
- Type: module-level function — lives in `prettyplay/llm/_request.py` (internal
  helper; not a facade entity — shared request body of both providers, parity by
  construction)
- Semantics: join `f"INSTRUCTIONS:\n{user_instructions}"`, `f"STEP:\n{step_text}"`,
  `f"CODE:\n{code}"` with blank lines — the fixed block order; no optional blocks
  (the engine guarantees non-empty instructions; step and code are always
  present). Same section style as `build_classification_fields`.

**Entity: `check_step_compliance(config: Config, provider: LLMProvider, step_text: str, code: str) -> findings: list[ComplianceFinding]`** (NEW)
- Type: module-level routine — declared `location`: `prettyplay/engine/compliance.py` (new module)
- Facade obligation: importable from `prettyplay.engine` (`__init__` export)
- Semantics — the single compliance check of every caching path:
  ```
  1. IF not config.generation_approve OR not config.generation_prompt:
         RETURN []                                       # zero provider calls, old behavior
  2. RETURN provider.check_instruction_compliance(
         prompt=COMPLIANCE_PROMPT,
         user_instructions=config.generation_prompt,
         step_text=step_text, code=code)
  ```
  Both hard failures propagate — the routine never swallows, never logs, never
  caches. Never called for replayed cached code (all three call sites are
  candidate-green branches); consumes no budget.
- `COMPLIANCE_PROMPT` is the frozen local mirror of the `compliance_prompt`
  practice (inline in the engine CODEMANIFEST) — the `CLASSIFICATION_PROMPT`
  pattern: constant + module docstring note that it changes only together with
  the CODEMANIFEST practice. Full text in Task 5.

**Entity: `StepGenerator.generate` (changed)** — gate in step 5, standing-high exhaustion in step 8
- Type: method — declared `location`: `prettyplay/engine/generator.py`
- Semantics (delta to `_generation_loop`):
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
  Gate placement: the `check_step_compliance` call sits in the `else` branch of
  the `settle` try/except, **outside every exception-swallowing `try`** —
  `except Exception as candidate_error` would swallow the gate failures if the
  call sat inside the `settle` try. The failed-check path (`AssertionError`)
  needs no gate — the candidate never succeeded.
- New engine-private helpers (module level in `generator.py`):
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
- Budget semantics: the gate consumes no attempt budget; only a high finding
  consumes the attempt it fails. `on_generation_started` and the attempt ordinal
  count **generation** attempts only — the gate request fires no hook event.

**Entity: `StepGenerator._exhaustion_outcome` (changed)** — new first branch:
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
  `_reason_safe` takes the first line and removes colons
  (`text.partition("\n")[0].replace(":", " ")`) — instruction text comes from
  user config and may contain colons/newlines; the first-line contract forbids
  both. No LLM classification on this branch; `healing_attempts`-funded
  regeneration is **not** granted here — the standing high finding already
  consumed the failed attempt, the pool is exhausted.

**Entity: `StepGenerator._healing_loop` (changed)** — the same else-branch gate minus `standing`:
  ```
  findings = check_step_compliance(...); high = _high_finding(findings)
  IF high: existing_code = code; error = _violation_text(high); continue
  ```
  Exhaustion keeps raising `IncurableStepError(step_text, "healing attempt budget
  exhausted", error, code=code)` with verdict None — the healer reattaches the
  entry verdict (healer.py, unchanged).

**Entity: `StepGenerator._funded_regeneration` (changed)** — after the `settle` try/except (in the implicit else, outside every `try`):
  ```
  findings = check_step_compliance(...)          # hard failures propagate
  high = _high_finding(findings)
  IF high: RETURN None, code, _violation_text(high), False   # a repeat failure of the funded attempt
  IF findings: _medium_warning(step_text, findings)
  RETURN _store(identity, code), code, "", False
  ```
  `repeat_was_check=False` — a compliance block is a candidate failure, not a
  check: `_failed_check_outcome` runs its one final classification with reason
  "candidate failed — …". The single funded attempt is not repeated.

**Entity: `StepSteering.steer` step 6 (changed)** — the write-back gate
- Type: method — declared `location`: `prettyplay/engine/steering/steering.py`
- Semantics (delta at the green branch): the gate runs **after** the execution
  try/except, before `_write_back`:
  ```
  findings = check_step_compliance(self._config, self._provider, failure.step_text, code)
      inside try/except (LLMUnavailableError, ComplianceVerdictError) as gate_failure:
          print(f"compliance gate failed: {gate_failure}")
          logger.warning("compliance gate failed", extra={"step_text": …, "gate_failure": str(gate_failure)})
          return None   — the original terminal failure propagates from the executor
  high → print(f"compliance violation — not written back: {violation}")
         history turn f"{message} => instruction violated: {_first_line(high.instruction)}"
         continue → re-prompt (step 2)
  medium/low → logger.warning("compliance findings passed", extra step + findings)
         → _write_back (save + on_healed + green line)
  ```
  Steering picks the first high finding inline — `next((f for f in findings if
  f.priority == "high"), None)` — and renders the dialog line from
  `finding.instruction` and `finding.explanation` directly; **no engine-private
  helper import** — the declared engine→steering edge stays
  `check_step_compliance` plus `run_step_code` only. `ComplianceVerdictError` is
  imported at implementation level for the except clause — uniform with the
  existing undeclared `LLMUnavailableError` implementation import. No write-back,
  no `on_healed`, budget-free on the block path.

**Entity: root enumerations (text-only)** — `prettyplay/executor.py`, `prettyplay/scenario.py`
- `PrettyPlay.step` / `PrettyPlay.expect` docstrings and
  `StepExecutor.execute` step 8 docstring enumerate the failure kinds — add
  `ComplianceVerdictError` to each by-kind enumeration. Zero structural changes:
  `ComplianceVerdictError` has no `verdict` attribute, so the
  `isinstance(…, (ProductDefectError, IncurableStepError))` guard already
  excludes it from `on_step_verdict`; the outer `except Exception` fires
  `on_step_failed` with the message; `PrettyPlay.step` folds the traceback (it is
  a `PrettyplayError`).

**Entity: frozen mirrors (implementation artifacts under the mirror rule)**
- `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` AND
  `prettyplay/engine/steering/steering.py` — byte-equal to the section after the
  first `---` of `.goga/usages/prompts/generation.md` (already changed in the
  working tree): the USER INSTRUCTIONS input line now reads "the project's
  binding code style guidance", and three binding rules are inserted after the
  RECOMMENDATION/USER GUIDANCE rule: (1) USER INSTRUCTIONS are binding for
  everything below the safety core — silently ignoring an instruction is a
  violation; (2) the safety core always outranks the instructions; an
  unfollowable instruction is never implemented silently — raise in the step code
  with the message "instruction conflicts with rule Y"; (3) prefer-type
  instructions are conditional by their own wording — best-effort with a graceful
  fallback is compliance.
- `PAGE_API_SURFACE` in both files — two rows gain `ignore_case`:
  `page.expect_title(title, ignore_case)` and `element.expect_text(text,
  ignore_case)`; keep the aligned-column style (sync tests check names and mirror
  equality, not padding); both mirrors stay byte-equal to each other.
- `CLASSIFICATION_PROMPT` in `prettyplay/engine/classification.py` — the USER
  INSTRUCTIONS input line becomes: "- USER INSTRUCTIONS: the project's binding
  classification guidance, when configured — follow it; it never overrides the
  fixed answer format above".

### Re-exports

Pre-existing, unchanged by this feature (root `prettyplay/CODEMANIFEST`):
- `->PrettyConfig: {}` — from `prettyplay/config` (`Config`); importable from the
  root facade.
- `->BrowserConfig: {}` — from `prettyplay/config`; importable from the root facade.
- `->StepHooks: {}` — from `prettyplay/reporting`; importable from the root facade.

New facade exports (local entities, not `->` blocks): `ComplianceVerdictError`
(`prettyplay.failures`), `ComplianceFinding` + `parse_compliance_verdict`
(`prettyplay.llm`), `check_step_compliance` (`prettyplay.engine`).

### Usages Context

- `conventions` (`.goga/usages/conventions.md`, all changed cells): Python 3.10+,
  relative intra-package imports, pydantic v2 `kw_only`, Google docstrings,
  `logging` with structured `extra`, tests mirror source structure
  (`tests/<pkg>/test_<module>.py`). Applied to every entity and test below.
- `compliance_prompt` (engine, inline in the engine CODEMANIFEST): the gate
  system prompt — inputs INSTRUCTIONS/STEP/CODE, the JSON findings answer shape,
  priority calibration (high only for confident, material, followable violations;
  doubt never high), conditional-compliance rules. Frozen as `COMPLIANCE_PROMPT`
  in `compliance.py`, passed verbatim as the system message of every verdict
  request. Full text in Task 5.
- `system_prompt` (`.goga/usages/prompts/generation.md`, engine + steering): the
  generation prompt with binding USER INSTRUCTIONS. Frozen mirrors
  `SYSTEM_PROMPT` in `generator.py` and `steering.py`; sync tests enforce byte
  equality with the practice section after the `---` separator.
- `classification_prompt` (engine, inline): classification prompt with the
  binding wording — wording only, no gate (ADR decision 9).
- `pydantic` (`.goga/usages/cooks/pydantic.md`, config): data models and TOML loading.
- `openai` / `anthropic` (`.goga/usages/cooks/openai.md`, `anthropic.md`, llm):
  SDK call patterns incl. the new compliance call sections; error mapping to
  `LLMUnavailableError`; anthropic `max_tokens=4096`.
- `playwright` (`.goga/usages/cooks/playwright.md`, driver):
  `to_contain_text(expected, ignore_case=…)` (≥1.44; project pins `playwright>=1.49`),
  `to_have_title` compiled-regex matching with `re.IGNORECASE`, and the note that
  text *locating* is already case-insensitive by default.

### Imported Usages

- `taxonomy` — from cell `prettyplay/failures`
  (`prettyplay/failures/.usages/taxonomy.md`); consumed by `config` and root.
  Four kinds, single-render policy. Already updated by apply-architecture.
- `configuration` — from cell `prettyplay/config`
  (`prettyplay/config/.usages/configuration.md`); consumed by `driver`. TOML/env/
  programmatic layers incl. the `generation_approve` row and "The instruction
  compliance gate" section. Already updated.
- `facade` — from cell `prettyplay/driver` (`prettyplay/driver/.usages/facade.md`);
  consumed by `engine` and `steering`. The single source of `PAGE_API_SURFACE` —
  the two `ignore_case` rows are already in; both mirror constants update in the
  same change as the driver methods ("the listing and the practice change
  together").
- `classification` — from cell `prettyplay/llm`
  (`prettyplay/llm/.usages/classification.md`); consumed by `engine`. Unchanged.
- Cell practices for consumers (`providers.md`, `generation.md`, `healing.md`,
  `steering.md`, `taxonomy.md`, `configuration.md`, `facade.md`) — all verified
  current by the design review; no further additions.

### Local Usages

None created or extended. The design's Phase 4 Step 6 verification found every
affected cell `.usages/` file current against the final CODEMANIFEST (including
the three applied defect fixes): `failures/taxonomy.md`, `config/configuration.md`,
`driver/facade.md`, `llm/providers.md`, `engine/generation.md`, `engine/healing.md`,
`engine/steering/steering.md`. Decision rule: every change falls inside an
existing functional domain — supplement, don't split. No CODEMANIFEST `Usages`
key points at own `.usages` files.

### External Dependencies

- `openai` SDK (`OpenAI`, `OpenAIError`) — `check_instruction_compliance` rides
  `chat.completions.create` exactly like the other operations.
- `anthropic` SDK (`Anthropic`, `AnthropicError`) — `messages.create` with the
  SDK-forced `max_tokens=REQUEST_MAX_TOKENS` (4096).
- `playwright` (sync API, `expect` assertions) — `to_contain_text(…,
  ignore_case=…)` and `to_have_title(compiled regex)`.
- `pydantic` v2 — `ComplianceFinding` model, `Config` field.
- Tools: `pytest` (run `tests/`), `ruff` (lint), `goga lint` (contract check —
  10 cells, 0 errors; read-only gate over the already-materialized manifests).

### Interaction Diagram

Verbatim from the design document (the verified entity flow of the feature):

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
              ▼                                                            ▼
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

Verbatim from the design document (the six end-to-end flows; each carries a
covering test — see tasks):

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

---

## Facts

- The working tree already holds the full contract layer: 7 changed CODEMANIFESTs,
  the changed practice `.goga/usages/prompts/generation.md`, the updated cooks
  (`playwright.md`, `openai.md`, `anthropic.md`) and all 7 cell `.usages/` files
  (git diff: 18 files, +466/−36). `goga lint`: 10 cells, 0 errors.
- The current test suite state is the **designed intermediate state**: 723 passed,
  2 failed — exactly the two byte-equality mirror-sync tests
  (`tests/engine/test_generator.py::test_system_prompt_mirrors_the_generation_practice`,
  `tests/engine/steering/test_steering.py::test_steering_mirrors_the_practices`),
  red until the coordinated mirror change lands (Task 3).
- The provider port currently exposes exactly two operations; both provider
  docstrings say "two operations"; `REQUEST_MAX_TOKENS = 4096` lives at
  `prettyplay/llm/anthropic_provider.py:25`.
- `errors.py` module docstring says "three distinct kinds"; `failures/__init__.py`
  exports six names (no `ComplianceVerdictError`).
- `Config` currently ends at `send_screenshots: bool = False`
  (`prettyplay/config/models.py:193`); the loader's `_ENV_NAMES`,
  `_BOOL_ENV_SETTINGS`, `_ALLOWED_TEXT` lack `generation_approve`.
- `driver/page.py`: `expect_title(self, title: str)` at line 158 compiles
  `re.DOTALL` only; `expect_text(self, text: str)` at line 680 calls
  `to_contain_text(text)` without the flag.
- `engine/compliance.py` does not exist; `prettyplay/engine/__init__.py` exports
  five names; `tests/engine/test_healer.py:650`
  (`test_engine_facade_reexports_all_entities`) pins that exact `__all__` and
  must gain `check_step_compliance`.
- The generator's `_generation_loop`/`_healing_loop` green branch is a bare
  `else: return self._store(identity, code)`; `_funded_regeneration` ends
  `return self._store(identity, code), code, "", False` — all three gate
  insertion points verified in the design's code stack trace.
- The executor's steering intercept triggers on `IncurableStepError` only — a
  standing-high exhaustion verdict may still open the steering dialog (intended:
  the engineer steers the fix); gate hard failures never trigger it.
- `tests/engine/test_classification.py:166` asserts the OLD classification
  wording ("- USER INSTRUCTIONS: the project's classification guidance") — it
  must be updated together with the `CLASSIFICATION_PROMPT` mirror.
- Owner decisions binding the implementation: `example/.prettyplay/cache/**`
  stays untouched (2026-09-13, superseding the ADR's deletion clause); no cells
  created or deleted; `prettyplay/cache`, `prettyplay/reporting`,
  `prettyplay/engine/polling` untouched; no deleted entities.

---

## Gap Analysis

- Missing contract entities: `ComplianceVerdictError`;
  `ComplianceFinding` + `parse_compliance_verdict`; `build_compliance_fields`;
  `LLMProvider.check_instruction_compliance` (port + both implementations);
  `check_step_compliance` + `COMPLIANCE_PROMPT` (new module
  `prettyplay/engine/compliance.py`).
- Missing facade exposure: `ComplianceVerdictError` (`prettyplay.failures`),
  `ComplianceFinding`, `parse_compliance_verdict` (`prettyplay.llm`),
  `check_step_compliance` (`prettyplay.engine`).
- Behavioral gaps in changed entities: `Config.generation_approve` field + loader
  wiring absent; `expect_title`/`expect_text` `ignore_case` absent;
  `StepGenerator` gate integration (green-branch gate, standing-high exhaustion,
  healing-loop gate, funded-regeneration gate, four helpers) absent;
  `StepSteering.steer` write-back gate absent; root docstring enumerations stale.
- Mirror drift (the designed red state): both `SYSTEM_PROMPT` mirrors, both
  `PAGE_API_SURFACE` mirrors and the `CLASSIFICATION_PROMPT` line trail the
  already-changed practices — 2 failing sync tests.
- API mismatches: none beyond the above (design review verified all signatures,
  annotations and locations against the current code).
- Existing code to reuse verbatim: `require_completion_text`,
  `_first_choice_text`/`_first_text_block`, `LLMUnavailableError` mapping,
  `REQUEST_MAX_TOKENS`, `_parse_env_scalar` boolean branch, `_apply_overrides`,
  the `StubProvider`/`FakePage`/`FakeLocator`/`write_pyproject` test idioms, the
  `test_healer.py` facade test (extend the `__all__` assertion),
  `facade_surface_rows` helpers.
- Test coverage gaps: every scenario in the design's Test Stack Trace (31 named
  tests — see tasks) plus the mirror-sync assertion updates
  (`test_page_api_surface_lists_every_facade_call` rows gain `ignore_case`;
  `test_classification.py:166` line update).
- Missing visibility: none — all target files are tracked; no new cells.

---

## Tasks

> **Package ordering rule**: coding tasks for each package are completed before starting the next. Within each coding task, contract tests are written first (TDD workflow). Order follows the design's Entity Dependencies (leaves → root): failures → config → driver(+coordinated mirrors) → llm → engine → steering → root. The non-cell documentation task (Task 8) closes the plan after the root.

> **CODEMANIFEST files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.** The same applies to the already-materialized `.goga/usages/**` practices and cooks: they are the frozen sources the mirrors copy.

> **Project note**: the checked-in `.venv` may be a broken cross-platform artifact (macOS shebangs). Run tests with `python3 -m pytest` and lint with `python3 -m ruff check .` (dependencies: `pytest pytest-mock pydantic ruff openai anthropic playwright`).

### Task 1: `ComplianceVerdictError` — the fourth failure kind (failures cell, TDD)

Add the compliance gate's hard failure to the taxonomy: the class
`PrettyplayError::ComplianceVerdictError(message: str)` in
`prettyplay/failures/errors.py` (declared `location: errors.py`), the
`prettyplay/failures/__init__.py` export, and the module docstring update
"three distinct kinds" → "four distinct kinds". The class mirrors
`LLMUnavailableError` exactly (algorithm: `__init__(message):
self.message = message; super().__init__(message)`); it carries no verdict and
no step fields — a verdict parse failure is not a step failure classification.
It is raised only by `parse_compliance_verdict` (Task 4) and derives from
`PrettyplayError` only — never from `AssertionError` (a gate failure is an
error, not a check).

**Usages relevant to this task:**
- `conventions`: Google docstrings, `tests/failures/test_errors.py` mirrors the
  source path; follow the existing `LLMUnavailableError` code style in the same
  file.
- `taxonomy` (`.usages/taxonomy.md`, already updated): the table row and
  catch-example for `ComplianceVerdictError` already document the consumer
  surface — the implementation must match it (message-only, "never cached").

**CRITICAL: `prettyplay/failures/CODEMANIFEST` — read-only. Do NOT modify it.**

- [x] **Contract tests** (in `tests/failures/test_errors.py`, next to the
      existing `LLMUnavailableError` tests; expected to fail now):
      facade accessibility — `from prettyplay.failures import ComplianceVerdictError`
      succeeds and `ComplianceVerdictError` is in
      `prettyplay.failures.__all__`; API shape — `ComplianceVerdictError("m")`
      exposes the `message` property.
- [x] **Code**: create the class in `prettyplay/failures/errors.py` after
      `LLMUnavailableError`: docstring ("The compliance gate could not obtain a
      usable verdict: the provider answer did not parse into findings. The
      successfully executed candidate stays unchecked and is never cached — a
      loud hard failure, never a silent pass." + Args), `__init__` per the
      mirror algorithm.
- [x] **Code**: add `ComplianceVerdictError` to the imports and `__all__` of
      `prettyplay/failures/__init__.py`.
- [x] **Code**: update the `errors.py` module docstring "three distinct kinds" →
      "four distinct kinds".
- [x] **Interface verification**: `python3 -m pytest tests/failures/ -q` — the
      contract tests pass.
- [x] **Logic tests** (write now, after implementation):
      `test_compliance_verdict_error_is_a_library_failure` —
      `ComplianceVerdictError("compliance verdict unparsable — … fragment: []")`
      is `isinstance` of `PrettyplayError` and **not** of `AssertionError`;
      `err.message == message` and `str(err) == message`;
      `not hasattr(err, "verdict")` (it is not a terminal step classification).
- [x] **Debugging**: `python3 -m pytest tests/ -x -q` — fix implementation code
      until all tests pass (the two known-red mirror-sync tests are expected to
      fail; they stay red until Task 3 — run `python3 -m pytest tests/ -q
      --deselect tests/engine/test_generator.py::TestPromptConstants::test_system_prompt_mirrors_the_generation_practice
      --deselect tests/engine/steering/test_steering.py::TestStepSteeringContract::test_steering_mirrors_the_practices`
      for the green gate; do NOT fix test code).
- [x] **Contract re-verification**: facade importable, `__all__` complete,
      message-only surface, no verdict attribute.
- [x] **Lint**: `python3 -m ruff check prettyplay/failures tests/failures` — fix
      formatting if necessary.

### Task 2: `Config.generation_approve` — the gate switch (config cell, TDD)

Add the instruction compliance gate switch to the config cell: the field
`generation_approve: bool = True` in the `Config` signature
(`prettyplay/config/models.py`, **last position**, after `send_screenshots`) and
the loader wiring in `prettyplay/config/loader.py`
(`_ENV_NAMES` → `PRETTYPLAY_GENERATION_APPROVE`, `_BOOL_ENV_SETTINGS`,
`_ALLOWED_TEXT` → `"a boolean"`, module docstring line). The default True is the
deliberate opt-out carrying the product line (loud errors instead of silent
ignoring); a regression to False would silently disable the gate everywhere. The
layered merge needs no new code: the existing `_parse_env_scalar` boolean branch
parses true/false/1/0 case-insensitively, and `_apply_overrides` already lets an
explicitly passed False participate (not None, not a str) — the
`strict`/`interactive` pattern, verified in the design's trace.

**Usages relevant to this task:**
- `conventions`: pydantic v2 `kw_only`, empty-or-neutral defaults (this field
  bends the empty-default rule by explicit contract, as `strict`/`interactive`
  bend with False); tests in `tests/config/test_models.py` /
  `tests/config/test_loader.py`.
- `pydantic` (`.goga/usages/cooks/pydantic.md`): model field style, Attributes
  docstring entry.
- `configuration` (`prettyplay/config/.usages/configuration.md`, already
  updated): the TOML line after `generation_prompt`, the env row, "The
  instruction compliance gate" section — the loader behavior must match it.

**CRITICAL: `prettyplay/config/CODEMANIFEST` — read-only. Do NOT modify it.**

- [x] **Contract tests** (expected to fail now): in `tests/config/test_models.py`
      — `generation_approve in Config.model_fields`; in
      `tests/config/test_loader.py` — the env override reads
      `PRETTYPLAY_GENERATION_APPROVE` (set it, `load_config`, assert no crash).
- [x] **Code**: add `generation_approve: bool = True` to `Config` in
      `prettyplay/config/models.py` (last position) + Attributes docstring
      entry: "whether the instruction compliance gate runs before caching a
      generated step; default True (the opt-out default)".
- [x] **Code**: add `"generation_approve"` to `_ENV_NAMES`,
      `_BOOL_ENV_SETTINGS` and `_ALLOWED_TEXT` (`"a boolean"`) in
      `prettyplay/config/loader.py`; add the module docstring line naming
      `PRETTYPLAY_GENERATION_APPROVE`.
- [x] **Interface verification**: `python3 -m pytest tests/config/ -q` — the
      contract tests pass.
- [x] **Logic tests**:
      `test_generation_approve_defaults_true` (tests/config/test_models.py) —
      `Config().generation_approve is True`.
      `test_generation_approve_env_override_parses_booleans`
      (tests/config/test_loader.py) — `write_pyproject()` empty section +
      `monkeypatch.setenv("PRETTYPLAY_GENERATION_APPROVE", raw)`, parametrize
      `raw ∈ {"true","FALSE","1","0","True"}` → expected
      `∈ {True,False,True,False,True}`; assert `config.generation_approve is
      expected`.
      `test_generation_approve_explicit_false_overrides_the_file_layer`
      (tests/config/test_loader.py) — `write_pyproject(generation_approve=True)`;
      `load_config(path, overrides=PrettyConfig(generation_approve=False))` →
      `config.generation_approve is False` (without this, a per-test opt-out
      would be impossible).
      `test_generation_approve_env_unparseable_fails_loudly` (negative,
      tests/config/test_loader.py) — env `"yes"` → `pytest.raises(
      ConfigurationError)` with message
      `generation_approve: received 'yes' — allowed: a boolean (true/false/1/0)`.
- [x] **Debugging**: `python3 -m pytest tests/ -x -q` (same two known-red
      mirror-sync tests excluded as in Task 1) — fix implementation code until
      all tests pass (do NOT fix test code).
- [x] **Contract re-verification**: field in the last signature position, default
      True, merge participation identical to `strict`/`interactive`, env
      override present.
- [x] **Lint**: `python3 -m ruff check prettyplay/config tests/config` — fix
      formatting if necessary.

### Task 3: the coordinated mirror change + the `ignore_case` capability (driver cell + the frozen mirrors, TDD)

Land the design's **mirror coordination unit as one commit-scale task**: the two
driver facade methods gain `ignore_case`, and ALL frozen mirrors update in the
same change — `SYSTEM_PROMPT` in `prettyplay/engine/generator.py` AND
`prettyplay/engine/steering/steering.py` (byte-equal to the already-changed
practice `.goga/usages/prompts/generation.md`), the two `PAGE_API_SURFACE`
mirrors (two rows gain `ignore_case`), and the `CLASSIFICATION_PROMPT` input line
in `prettyplay/engine/classification.py`. The two byte-equality sync tests are
red until this whole task lands — after it, the suite is fully green for the
rest of the plan. The practices and cooks are already changed in the working
tree; this task only brings the code mirrors and the driver methods up to them.

Driver semantics: `PageFacade.expect_title(title, ignore_case=False)` — True
compiles the title regex with `re.DOTALL | re.IGNORECASE` (default keeps
`re.DOTALL` only, reproducing the current lambda exactly); Playwright's
`to_have_title` accepts the compiled pattern. `LocatorFacade.expect_text(text,
ignore_case=False)` — True forwards Playwright's own flag:
`to_contain_text(text, ignore_case=ignore_case)` (available since 1.44; project
pins `playwright>=1.49`). Both stay marshaled through the existing `_call`
boundary. Text *locating* is untouched (`get_by_text`, `filter(has_text=…)`).

**Usages relevant to this task:**
- `playwright` (`.goga/usages/cooks/playwright.md`, already updated): the
  case-insensitive expectation section — `to_contain_text(expected,
  ignore_case=…)`, `to_have_title` compiled-regex matching, the
  locating-is-already-case-insensitive note. The methods map exactly onto these
  calls.
- `facade` (`prettyplay/driver/.usages/facade.md`, already updated): the single
  source of `PAGE_API_SURFACE` — rows `page.expect_title(title, ignore_case)` and
  `element.expect_text(text, ignore_case)` are already in; the mirrors copy them.
- `system_prompt` (`.goga/usages/prompts/generation.md`, already updated): the
  section after the first `---` is the byte-exact target of both `SYSTEM_PROMPT`
  mirrors — read the file, do not retype from memory.
- `conventions`: docstrings describe `ignore_case` exactly as the CODEMANIFEST
  annotations do.

**CRITICAL: `prettyplay/driver/CODEMANIFEST`, `prettyplay/engine/CODEMANIFEST`, `prettyplay/engine/steering/CODEMANIFEST` — read-only. Do NOT modify them, and do NOT modify `.goga/usages/**` (already at the target state).**

- [x] **Contract tests** (in `tests/driver/test_page.py`, extend the existing
      fake-locator/fake-page idiom; expected to fail now): signature shape —
      `PageFacade.expect_title` and `LocatorFacade.expect_text` accept the
      `ignore_case` keyword.
- [x] **Code** (driver): `expect_title(self, title: str, ignore_case: bool =
      False)` in `prettyplay/driver/page.py` — `flags = re.DOTALL |
      re.IGNORECASE if ignore_case else re.DOTALL`;
      `pattern = re.compile(f".*{re.escape(title)}.*", flags)`; keep
      `to_have_title(pattern)` behind `self._call`; update the docstring with
      the `ignore_case` arg.
- [x] **Code** (driver): `expect_text(self, text: str, ignore_case: bool =
      False)` — `self._call(lambda: expect(self._locator).to_contain_text(text,
      ignore_case=ignore_case))`; update the docstring.
- [x] **Interface verification**: `python3 -m pytest tests/driver/ -q` — the
      contract tests pass.
- [x] **Logic tests** (driver): `test_expect_text_passes_ignore_case_to_playwright`
      — fake locator wrapped in `LocatorFacade` records
      `("expect_text", "SUCCESS", {"ignore_case": True})`; the default call
      `expect_text("SUCCESS")` records `{"ignore_case": False}` (folds in the
      default-stays-case-sensitive edge case).
      `test_expect_title_compiles_case_insensitive_pattern` — fake page records
      `("expect_title", pattern)`; assert `pattern.flags & re.IGNORECASE` and
      `pattern.match("My Dashboard") is not None`; the default-path pattern has
      no IGNORECASE flag and `pattern.match("DASHBOARD")` is None.
- [x] **Code** (mirrors — engine): set `SYSTEM_PROMPT` in
      `prettyplay/engine/generator.py` to the byte-exact section after the first
      `---` of `.goga/usages/prompts/generation.md` (the USER INSTRUCTIONS input
      line now says "binding code style guidance"; three binding rules are
      inserted after the RECOMMENDATION/USER GUIDANCE rule: instructions are
      binding below the safety core / the safety core outranks them with the
      "instruction conflicts with rule Y" loud raise for unfollowable ones /
      prefer-type instructions are conditional with graceful-fallback
      compliance).
- [x] **Code** (mirrors — engine): update the two `PAGE_API_SURFACE` rows in
      `prettyplay/engine/generator.py` — `page.expect_title(title, ignore_case)`
      and `element.expect_text(text, ignore_case)` — keeping the
      aligned-column style.
- [x] **Code** (mirrors — engine): update the `CLASSIFICATION_PROMPT` input line
      in `prettyplay/engine/classification.py` to "- USER INSTRUCTIONS: the
      project's binding classification guidance, when configured — follow it; it
      never overrides the fixed answer format above".
- [x] **Code** (mirrors — steering): apply the same two updates to
      `SYSTEM_PROMPT` and `PAGE_API_SURFACE` in
      `prettyplay/engine/steering/steering.py` — the local copies stay
      byte-equal to the engine's (frozen mirrors stay cell-owned; no runtime
      read of `.goga/`, no import between the cells).
- [x] **Code** (tests updated to the new mirrors): in
      `tests/engine/test_generator.py::test_page_api_surface_lists_every_facade_call`
      — the two rows become `page.expect_title(title, ignore_case)` and
      `element.expect_text(text, ignore_case)`; in
      `tests/engine/test_classification.py` line ~166 — the asserted prompt line
      becomes "- USER INSTRUCTIONS: the project's binding classification
      guidance, when configured — follow it; it never overrides the fixed answer
      format above"; add the mirror-row assertions of the design:
      `page.expect_title(title, ignore_case)` and
      `element.expect_text(text, ignore_case)` present in BOTH
      `PAGE_API_SURFACE` constants.
- [x] **Interface verification**: `python3 -m pytest
      tests/engine/test_generator.py::TestPromptConstants
      tests/engine/steering/test_steering.py::TestStepSteeringContract
      tests/engine/test_classification.py -q` — the previously-red
      `test_system_prompt_mirrors_the_generation_practice` and
      `test_steering_mirrors_the_practices` now pass (byte equality restored).
- [x] **Debugging**: `python3 -m pytest tests/ -x -q` — the WHOLE suite is green
      from this task onward (723 + the new tests); fix implementation code until
      all tests pass (do NOT fix test code — the sync tests are the authority).
- [x] **Contract re-verification**: driver signatures match the CODEMANIFEST
      (`expect_title(title: str, ignore_case: bool = False)`,
      `expect_text(text: str, ignore_case: bool = False)`); both mirror pairs
      byte-equal; the capability rides the existing mirror names — no new
      non-mirror family.
- [x] **Lint**: `python3 -m ruff check prettyplay tests` — fix formatting if
      necessary.

### Task 4: the compliance verdict operation of the LLM port (llm cell, TDD)

Implement the third port operation end-to-end in `prettyplay/llm`: the
`ComplianceFinding` model and the strict `parse_compliance_verdict` routine in
`models.py`, the shared `build_compliance_fields` builder in `_request.py`
(parity by construction), the port method `check_instruction_compliance` in
`provider.py`, and the full implementations in `openai_provider.py` and
`anthropic_provider.py`. Errors: `ComplianceVerdictError` (from
`prettyplay/failures`, Task 1) on a malformed verdict; `LLMUnavailableError` on
an SDK error ("llm unavailable: {provider} request failed" — identical mapping
to the other operations). One request per call, no retry loop inside the
provider, no screenshot input, model = `effective_generation_model`.

**Usages relevant to this task:**
- `openai` / `anthropic` (`.goga/usages/cooks/openai.md`, `anthropic.md`,
  already updated): the compliance call sections — system+user messages, the
  `build_compliance_fields` request body, verdict text extracted, anthropic
  `max_tokens=4096` (`REQUEST_MAX_TOKENS`, `anthropic_provider.py:25`).
- `conventions`: `parse_compliance_verdict` is a pure function (no state, no
  I/O, deterministic); tests mirror sources in `tests/llm/test_models.py`,
  `tests/llm/test_openai_provider.py`, `tests/llm/test_anthropic_provider.py`,
  `tests/llm/test_request.py`.
- `providers` (`prettyplay/llm/.usages/providers.md`, already updated): three
  operations in Parity; effective-generation-model note; "The compliance
  operation" section.

**CRITICAL: `prettyplay/llm/CODEMANIFEST` — read-only. Do NOT modify it.**

- [x] **Contract tests** (expected to fail now): `from prettyplay.llm import
      ComplianceFinding, parse_compliance_verdict` succeeds and both are in
      `prettyplay.llm.__all__`; `LLMProvider.check_instruction_compliance`
      exists on the port; `build_compliance_fields` in `tests/llm/test_request.py`
      returns the fixed block order.
- [x] **Code**: `ComplianceFinding` in `prettyplay/llm/models.py` — pydantic v2,
      `model_config = ConfigDict(kw_only=True)`, fields `instruction: str = ""`,
      `priority: str = ""`, `explanation: str = ""`; Google docstring with
      Attributes; **no priority validation in the model**.
- [x] **Code**: `parse_compliance_verdict(verdict_text: str) ->
      list[ComplianceFinding]` in `prettyplay/llm/models.py` — implement the
      algorithm verbatim (trim → `json.loads` in `try/except ValueError` → list
      check → per-item dict/str/priority validation against the
      `COMPLIANCE_PRIORITIES = frozenset({"high", "medium", "low"})` → construct
      findings; every malformed shape raises `ComplianceVerdictError` with the
      fixed message and `_answer_fragment(verdict_text)` — whitespace-collapsed
      first 200 characters); module docstring gains the findings; import
      `ComplianceVerdictError` from `..failures`.
- [x] **Code**: `build_compliance_fields(user_instructions: str, step_text: str,
      code: str) -> str` in `prettyplay/llm/_request.py` — join
      `f"INSTRUCTIONS:\n{user_instructions}"`, `f"STEP:\n{step_text}"`,
      `f"CODE:\n{code}"` with blank lines; same section style as
      `build_classification_fields`.
- [x] **Code**: the port method in `prettyplay/llm/provider.py` after
      `classify_failure` — full Google docstring (Args: prompt, user_instructions,
      step_text, code; Returns: the parsed findings; Raises: NotImplementedError),
      body `raise NotImplementedError(...)` as its siblings.
- [x] **Code**: `OpenAIProvider.check_instruction_compliance` in
      `prettyplay/llm/openai_provider.py` — `text =
      build_compliance_fields(...)`; messages `[{"role": "system", "content":
      prompt}, {"role": "user", "content": text}]` (plain string — no screenshot);
      one `chat.completions.create(model=self._config.effective_generation_model,
      messages=messages)` in `try/except OpenAIError` → `LLMUnavailableError`;
      `return parse_compliance_verdict(require_completion_text(
      _first_choice_text(response), "openai"))`; docstring; class docstring
      "two operations" → three.
- [x] **Code**: `AnthropicProvider.check_instruction_compliance` in
      `prettyplay/llm/anthropic_provider.py` — same builder; one
      `messages.create(model=self._config.effective_generation_model,
      system=prompt, max_tokens=REQUEST_MAX_TOKENS, messages=[{"role": "user",
      "content": text}])` in `try/except AnthropicError` →
      `LLMUnavailableError`; `parse_compliance_verdict(require_completion_text(
      _first_text_block(response), "anthropic"))`; docstring; class docstring
      "two operations" → three.
- [x] **Code**: add `ComplianceFinding` and `parse_compliance_verdict` to the
      imports and `__all__` of `prettyplay/llm/__init__.py`.
- [x] **Interface verification**: `python3 -m pytest tests/llm/ -q` — the
      contract tests pass.
- [x] **Logic tests**:
      `test_parse_compliance_verdict_parses_findings` (tests/llm/test_models.py)
      — padded input with two findings (high + low); trim → 2 models;
      `findings[0].priority == "high"`, `findings[1].priority == "low"`;
      instruction/explanation verbatim.
      `test_parse_compliance_verdict_malformed_variants` (negative,
      parametrized) — inputs `["not json at all", '{"instruction": "x"}'` (not a
      list), `'[1]'` (non-object), `'[{"priority": "high", "explanation": "e"}]'`
      (missing instruction), `'[{"instruction": "i", "priority": "critical",
      "explanation": "e"}]'` (unknown label), `'[{"instruction": 7, "priority":
      "high", "explanation": "e"}]'` (non-str)]; each raises
      `ComplianceVerdictError` (also `isinstance` of `PrettyplayError`); the
      message contains "compliance verdict unparsable" and the fragment ("not
      json at all" for the non-JSON case).
      `test_parse_compliance_verdict_empty_list_means_compliant` (edge) —
      `"[]"` → `findings == []`.
      `test_parse_compliance_verdict_tolerates_extra_keys_and_padding` (edge) —
      padded item with a `"note"` key → one finding with the three fields.
      `test_openai_check_instruction_compliance_request_and_parse`
      (tests/llm/test_openai_provider.py) — mock the client
      (`mock.patch.object(provider, "_get_client")`); scripted first-choice
      content `'[{"instruction": "Prefer id attributes", "priority": "high",
      "explanation": "locates by text"}]'`; assert exactly one create call,
      `model == "gpt-x"` (effective generation model), system message is the
      prompt, user content is the three blocks in the fixed order, one finding
      returned with the parsed fields, no `ignore`/screenshot keys anywhere.
      `test_anthropic_check_instruction_compliance_parity`
      (tests/llm/test_anthropic_provider.py) — same verdict JSON; assert
      `max_tokens == 4096`; the user content equals the openai test's (shared
      builder — assert equality with `build_compliance_fields(...)` output);
      same findings.
      `test_openai_compliance_sdk_error_maps_to_unavailable` /
      `test_anthropic_compliance_sdk_error_maps_to_unavailable` (negative) —
      client mock raising `OpenAIError`/`AnthropicError` →
      `pytest.raises(LLMUnavailableError)` with "llm unavailable: {provider}
      request failed"; no findings returned, no `ComplianceVerdictError`.
- [x] **Debugging**: `python3 -m pytest tests/ -x -q` — fix implementation code
      until all tests pass (do NOT fix test code).
- [x] **Contract re-verification**: facade exports complete; port method present
      with the exact signature `(prompt: str, user_instructions: str,
      step_text: str, code: str) -> list[ComplianceFinding]`; parity — same
      builder, same block order, same error mapping; anthropic cap present.
- [x] **Lint**: `python3 -m ruff check prettyplay/llm tests/llm` — fix
      formatting, apply decomposition if necessary.

### Task 5: `check_step_compliance` + the generator gate (engine cell, TDD)

Create the gate module and integrate it into the generator. New module
`prettyplay/engine/compliance.py` holds `COMPLIANCE_PROMPT` (frozen mirror of
the `compliance_prompt` inline practice of `prettyplay/engine/CODEMANIFEST`) and
`check_step_compliance(config, provider, step_text, code) -> list[ComplianceFinding]`
— off switch or empty `generation_prompt` → `[]` with zero provider calls;
otherwise one `provider.check_instruction_compliance(prompt=COMPLIANCE_PROMPT,
user_instructions=config.generation_prompt, step_text=step_text, code=code)`;
hard failures propagate untouched. Export it from `prettyplay/engine/__init__.py`.
Then integrate the gate into `StepGenerator` at the four points verified by the
design's code stack trace: the `_generation_loop` green branch (with the
`standing` state), the `_exhaustion_outcome` standing-high branch, the
`_healing_loop` green branch, and `_funded_regeneration`. The gate call sits in
the `else` branch, **outside every exception-swallowing `try`** — inside the
`settle` try the `except Exception` handlers would swallow
`LLMUnavailableError`/`ComplianceVerdictError`. The gate consumes no attempt
budget; the gate request fires no `on_generation_started` event and no attempt
ordinal.

`COMPLIANCE_PROMPT` — the frozen mirror text (verbatim from the engine
CODEMANIFEST `compliance_prompt` practice):

```
You verify that generated step code follows the project's user instructions.

Input you receive:
- INSTRUCTIONS: the project's user instructions, verbatim
- STEP: the step sentence the code was generated for
- CODE: the successfully executed candidate code

Check the code against every instruction and answer with exactly one JSON list of
findings:
[{"instruction": "<the violated instruction quote>", "priority": "high|medium|low",
"explanation": "<one short sentence>"}]

Priority calibration:
- high — a confident, material violation evident from the code itself: the instruction
  was expressible through the page API the code already uses, and the code plainly
  skipped or contradicted it without any fallback attempt; only high blocks the
  candidate
- medium and low — minor observations, partial compliance or doubt: visible, never
  blocking; when in doubt, never high
- an empty list [] means the code complies

Rules:
- Conditional prefer-type instructions are checked conditionally: when the code shows
  a graceful fallback attempt, that is compliance; judge followability from the code
  and the step sentence alone — you see no page state, never speculate about it
- An instruction the code could not follow because the step sentence itself prevents
  it is not a violation; when the inputs leave the followability in doubt, the finding
  is never high
- Judge only what the code does against the instructions — not the step sentence,
  not the page state beyond the instructions
- Output only the JSON list, no other text
```

Module docstring notes the mirror rule: the constant changes only together with
the CODEMANIFEST practice (the `CLASSIFICATION_PROMPT` pattern).

**Usages relevant to this task:**
- `compliance_prompt` (engine, inline in the CODEMANIFEST — read the manifest,
  copy verbatim): the calibration is the ADR's mitigation of the
  hyper-strict-checker risk; the mirror test pins the distinctive lines.
- `classification` (from Imports, `prettyplay/llm/.usages/classification.md`):
  the healing decision categories of the loops this task touches — read for the
  healing-path context; the classification paths themselves are unchanged by the
  gate (a high finding is a candidate failure, never a classification).
- `healing` (`prettyplay/engine/.usages/healing.md`, already updated): the
  first rule of `## Rules` — the healed candidate passes the compliance gate
  before the write-back — documents the consumer-visible semantics of the
  healing-path gate this task implements (`_healing_loop`,
  `_funded_regeneration`).
- `conventions`: module style of `classification.py` as the template; tests in
  the new `tests/engine/test_compliance.py` (mirrors the new module) and
  `tests/engine/test_generator.py`.
- `system_prompt` (`.goga/usages/prompts/generation.md`): unchanged in this
  task (Task 3 landed it); `generation_prompt` now reaches the compliance
  request as the checked INSTRUCTIONS block, never as guidance.

**CRITICAL: `prettyplay/engine/CODEMANIFEST` — read-only. Do NOT modify it.**

- [ ] **Contract tests** (expected to fail now): `from prettyplay.engine import
      check_step_compliance` succeeds; the `__all__` assertion in
      `tests/engine/test_healer.py::test_engine_facade_reexports_all_entities`
      is updated to include `"check_step_compliance"`; `COMPLIANCE_PROMPT`
      importable from `prettyplay.engine.compliance`.
- [ ] **Code**: create `prettyplay/engine/compliance.py` — module docstring
      (the mirror rule), `COMPLIANCE_PROMPT` (text above, verbatim),
      `check_step_compliance` with the two-step algorithm and a full Google
      docstring (Args: config — the gate switch and the generation instructions,
      provider, step_text, code; Returns: the findings; empty — compliant or the
      gate is off; Raises: both hard failures propagate).
- [ ] **Code**: add `check_step_compliance` to the import and `__all__` of
      `prettyplay/engine/__init__.py`.
- [ ] **Interface verification**: `python3 -m pytest tests/engine/test_compliance.py
      tests/engine/test_healer.py -q` — the contract tests pass.
- [ ] **Logic tests — the gate routine** (new `tests/engine/test_compliance.py`;
      extend the existing `StubProvider` idiom of `tests/engine/test_generator.py`
      with a compliance-recording stub: `check_instruction_compliance(**kwargs)`
      appends to `compliance_calls`, returns a scripted verdict — a list of
      `ComplianceFinding(...)` literals or a raise; default `[]`):
      `test_check_step_compliance_returns_empty_with_zero_calls_when_off` —
      `Config(generation_approve=False, generation_prompt="Prefer id attributes")`
      → `[]`, `provider.compliance_calls == []`.
      `test_check_step_compliance_returns_empty_when_instructions_empty` — switch
      True, `generation_prompt=""` → `[]`, zero calls (the port requirement "the
      calling engine guarantees non-empty" is enforced here).
      `test_check_step_compliance_passes_practice_prompt_and_instructions` —
      fake returns `[]`; recorded kwargs: `call["prompt"] == COMPLIANCE_PROMPT`
      (byte-equal to the practice), `call["user_instructions"] == "Prefer id
      attributes"`, `step_text`/`code` passed through.
      `test_compliance_prompt_mirror_matches_the_code_manifest_practice` — read
      `prettyplay/engine/CODEMANIFEST` and assert each distinctive line
      (`"only high blocks the"`, `"when in doubt, never high"`, `"an empty list
      [] means the code complies"`, `"Output only the JSON list, no other
      text"`) is present both in the CODEMANIFEST text and in
      `COMPLIANCE_PROMPT`.
- [ ] **Code — generator integration**: in `prettyplay/engine/generator.py`
      import `ComplianceFinding` (from `..llm`) and
      `check_step_compliance` (from `.compliance`); add the four module-level
      helpers `_high_finding`, `_violation_text`, `_medium_warning`,
      `_reason_safe` (exact texts in the Contract Surface above).
- [ ] **Code — `_generation_loop`**: add `standing: ComplianceFinding | None =
      None` to the loop state; replace the bare `else: return
      self._store(identity, code)` with the gate sequence (findings → high →
      retry with violation as `error`, `standing = high`, `continue`; findings →
      `_medium_warning` → `_store`; empty → `_store`); on the `except Exception`
      retry branch set `standing = None`; pass `standing` into
      `_exhaustion_outcome` at the loop top.
- [ ] **Code — `_exhaustion_outcome`**: new first branch (before the
      `error is None` check) — `standing is not None` → build the
      `FailureVerdict(category="incurable", explanation=…, recommendation=…)`
      from the finding and `raise IncurableStepError(step_text, f"generation
      attempt budget exhausted — violated instruction
      {_reason_safe(standing.instruction)}", error=violation_text, code=code,
      verdict=verdict)`; no classification call.
- [ ] **Code — `_healing_loop`**: same green-branch gate minus `standing`
      (high → `existing_code = code; error = _violation_text(high); continue`);
      exhaustion raise unchanged (verdict stays None — the healer reattaches).
- [ ] **Code — `_funded_regeneration`**: after the settle try/except, in the
      implicit `else` — gate; high → `return None, code, _violation_text(high),
      False`; findings → `_medium_warning`; else `_store`. The existing
      docstring gains the gate note (a compliance block is a repeat failure of
      the funded attempt, not a check).
- [ ] **Logic tests — the generator gate** (in `tests/engine/test_generator.py`,
      extend `StubProvider` with the compliance recording/scripting):
      `test_generate_gates_candidate_and_stores_on_compliant` — compliance `[]`;
      returned `CachedStep.code == WORKING_CODE`; cache file exists;
      `provider.compliance_calls[0]["code"] == WORKING_CODE`; one generation
      call, one compliance call.
      `test_generate_high_finding_fails_attempt_and_retry_carries_violation` —
      candidate 1 green but high (`ComplianceFinding("Prefer id attributes",
      "high", "locates by text")`), candidate 2 compliant; the second
      `generate_step_code` call's `error` kwarg equals `"violated instruction:
      Prefer id attributes — locates by text"` and `existing_code ==
      WORKING_CODE`; exactly 2 generation + 2 compliance calls; the cache stores
      the compliant code only; no WARNING records.
      `test_generate_medium_low_findings_pass_with_warning` (`caplog`) —
      medium + low findings; WARNING `"compliance findings passed"` at the
      "prettyplay" logger with the `step_text` extra; the rendered findings
      contain both priorities; the step is stored and returned.
      `test_generate_budget_exhaustion_with_standing_high_names_instruction` —
      `Config(generation_attempts=2, …)`, compliance always high on the same
      instruction, candidates always green; `pytest.raises(IncurableStepError)`:
      `exc.verdict.category == "incurable"`, `exc.verdict.explanation ==
      "Prefer id attributes — locates by text"`, `exc.verdict.recommendation`
      contains the instruction, `exc.reason == "generation attempt budget
      exhausted — violated instruction Prefer id attributes"` (assert `":" not
      in exc.reason.split("\n")[0]`), `exc.error == violation_text`,
      `exc.code == WORKING_CODE`; **zero** `classify_failure` calls; nothing in
      the cache.
      `test_generate_gate_hard_failure_propagates_and_caches_nothing` (negative)
      — compliance raises `ComplianceVerdictError` on the first green candidate;
      propagates (no retry, no budget table); cache holds no step for the
      identity; exactly one generation call.
      `test_regenerate_gates_healed_candidate_before_write_back` — call
      `regenerate` directly; candidate 1 green but high, candidate 2 compliant;
      second request `error == violation_text`; healed step stored; 2 compliance
      calls.
      `test_regenerate_high_finding_exhaustion_carries_violation_and_entry_verdict`
      — `Config(healing_attempts=1, …)`, compliance always high;
      `pytest.raises(IncurableStepError)`: `exc.error == "violated instruction:
      Prefer id attributes — locates by text"`, `exc.reason == "healing attempt
      budget exhausted"`, `exc.verdict is None` (the healer reattaches the entry
      verdict — not built inside the loop), `exc.code == WORKING_CODE`; exactly
      1 generation + 1 compliance call, zero `classify_failure` calls, nothing
      in the cache.
      `test_funded_regeneration_gates_before_store` (edge) — drive a first
      candidate failing a check with a rot classification; funded candidate
      green but high; full `generate(...)` loop; raises
      `IncurableStepError`; the final classification request's `error` carries
      the violation text; cache untouched; exactly one funded request.
- [ ] **Debugging**: `python3 -m pytest tests/ -x -q` — fix implementation code
      until all tests pass (do NOT fix test code).
- [ ] **Contract re-verification**: gate outside every exception-swallowing try
      (the only candidate-failure handlers wrap `settle`, not the `else`
      branch); gate consumes no budget; no new hook events; facade export
      complete; standing-high invariant (standing non-None ⟺ `error` is its
      violation text) across all loop branches.
- [ ] **Lint**: `python3 -m ruff check prettyplay/engine tests/engine` — fix
      formatting, apply decomposition if necessary.

### Task 6: the steering write-back gate (engine/steering cell, TDD)

Integrate the same gate into `StepSteering.steer`
(`prettyplay/engine/steering/steering.py`) — step 6 of the contract: a green
guided candidate passes `check_step_compliance` before `_write_back`. Gate hard
failures end the dialog (gate line + WARNING + `return None` — the original
terminal failure propagates from the executor); a high finding never reaches the
cache (dialog line + history turn + re-prompt); medium/low pass with a WARNING
and write back. Steering picks the first high finding inline (`next((f for f in
findings if f.priority == "high"), None)`) and renders the dialog line from the
finding fields directly — **no engine-private helper import**; the declared
engine→steering edge stays `check_step_compliance` plus `run_step_code` only.
Import `check_step_compliance` from the engine cell (`from ..compliance import
check_step_compliance`, uniform with the existing `from ..execution import
run_step_code`); import `ComplianceVerdictError` at implementation level for the
except clause (uniform with the existing undeclared `LLMUnavailableError`
implementation import). Interactive attempts stay budget-free.

**Usages relevant to this task:**
- `conventions`: tests in `tests/engine/steering/test_steering.py`; the existing
  `SteeringFixture`/`FakeProvider`/`_script_input` idioms.
- `steering` (`prettyplay/engine/steering/.usages/steering.md`, already
  updated): "The compliance gate of a guided heal" section documents the
  consumer-visible semantics this task implements.
- `system_prompt` / `facade` mirrors: already landed in Task 3 — this task
  touches only behavior, not the constants.

**CRITICAL: `prettyplay/engine/steering/CODEMANIFEST` — read-only. Do NOT modify it.**

- [ ] **Contract tests** (expected to fail now): the `FakeProvider` test double
      of `tests/engine/steering/test_steering.py` gains
      `check_instruction_compliance` (records kwargs into `compliance_calls`,
      returns a scripted verdict, default `[]`) — a green turn with the default
      `[]` still heals (the off-switch behavior is unchanged for the gate-off
      config).
- [ ] **Code**: in `prettyplay/engine/steering/steering.py` — add the imports
      (`from ..compliance import check_step_compliance`;
      `from ...failures import ComplianceVerdictError` alongside
      `LLMUnavailableError`); in `steer`, after the green execution (the current
      `return self._write_back(failure, identity, code)` site): run the gate
      inside `try/except (LLMUnavailableError, ComplianceVerdictError) as
      gate_failure` → `print(f"compliance gate failed: {gate_failure}")`,
      `logger.warning("compliance gate failed", extra={"step_text":
      failure.step_text, "gate_failure": str(gate_failure)})`, `return None`;
      then `high = next((f for f in findings if f.priority == "high"), None)` →
      print `f"compliance violation — not written back: {violation}"` (the
      violation rendered from `high.instruction` and `high.explanation`),
      `history.append(f"{message} => instruction violated:
      {_first_line(high.instruction)}")`, `continue`; medium/low →
      `logger.warning("compliance findings passed", extra={"step_text":
      failure.step_text, "findings": [...]})` → `_write_back`; empty →
      `_write_back`. Update the `steer` docstring (step 6 of the contract
      Algorithm).
- [ ] **Interface verification**: `python3 -m pytest
      tests/engine/steering/ -q` — the contract tests pass (the gate-off and
      `[]`-default paths heal exactly as before).
- [ ] **Logic tests**:
      `test_steer_high_finding_never_reaches_cache` — stdin scripted with two
      guidances; guided candidate 1 green with a high finding, candidate 2 green
      with `[]`; returns a `CachedStep` with candidate 2; the cache holds
      candidate 2 only; the second guided request's `guidance_history` carries a
      turn containing the instruction; stdout captured the violation line;
      `RunBudgets` untouched.
      `test_steer_medium_findings_pass_with_warning_and_write_back` — one
      guidance; compliance → `[ComplianceFinding("Prefer ids", "medium",
      "minor")]`; a `CachedStep` returned; the cache file exists; hooks saw
      `on_healed`; `caplog` holds `"compliance findings passed"` at WARNING with
      the `step_text` extra; stdout carries no "compliance violation" line.
      `test_steer_gate_hard_failure_ends_dialog_returning_none` (negative) — one
      guidance; compliance raises `ComplianceVerdictError("compliance verdict
      unparsable — … fragment: 'nope'")` after a green execution; result `is
      None`; cache file absent; `caplog` has `"compliance gate failed"` with the
      step extra; stdout contains "compliance gate failed" and the fragment.
- [ ] **Debugging**: `python3 -m pytest tests/ -x -q` — fix implementation code
      until all tests pass (do NOT fix test code).
- [ ] **Contract re-verification**: the gate sits outside the generic
      `except Exception as outcome` of the execution block (otherwise hard
      failures would degrade into red turns); every exit path either heals or
      returns None; nothing cached on block/hard-failure; no budget consumed.
- [ ] **Lint**: `python3 -m ruff check prettyplay/engine/steering
      tests/engine/steering` — fix formatting if necessary.

### Task 7: root by-kind enumerations + the end-to-end loud surface (root cell + integration test)

Close the feature at the root: the text-only docstring enumerations in
`prettyplay/executor.py` and `prettyplay/scenario.py` name
`ComplianceVerdictError` among the propagated kinds (root CODEMANIFEST:
`PrettyPlay.step`, `PrettyPlay.expect`, `StepExecutor.execute` step 8), and the
end-to-end scenario test proves the runner-visible behavior: a gate hard failure
inside `generate` propagates through `executor.execute` (outer `except Exception`
→ `on_step_failed` with the message, **no** `on_step_verdict` —
`ComplianceVerdictError` has no `verdict` attribute and the
`isinstance(…, (ProductDefectError, IncurableStepError))` guard already excludes
it), `on_step_finished` fires "failed", and `PrettyPlay.step` folds the
traceback (the runner sees the boundary frame only). Zero structural changes at
the executor/scenario — the trace confirmed it.

**Usages relevant to this task:**
- `taxonomy` (`prettyplay/failures/.usages/taxonomy.md`, already updated): the
  four-kind enumeration and the folded-traceback guarantee the docstrings cite.
- `conventions`: the scenario-level test lands in `tests/test_scenario.py` next
  to the existing end-to-end idioms (fake provider + fake page driving
  generation to the gate).

**CRITICAL: `prettyplay/CODEMANIFEST` (root) — read-only. Do NOT modify it.**

- [ ] **Code**: update the `StepExecutor.execute` docstring (step 8) and the
      `PrettyPlay.step` / `PrettyPlay.expect` docstrings in
      `prettyplay/executor.py` and `prettyplay/scenario.py`: every by-kind
      enumeration (`ProductDefectError`, `IncurableStepError`,
      `LLMUnavailableError`) gains `ComplianceVerdictError`.
- [ ] **Integration test**: `test_step_surfaces_compliance_verdict_error` in
      `tests/test_scenario.py` — scenario with a fake provider whose
      `check_instruction_compliance` raises `ComplianceVerdictError` (config:
      `generation_approve=True`, non-empty `generation_prompt`; page faked so
      generation reaches a green candidate, or unit-level: executor with a
      generator whose provider raises); `scenario.step("open example.com")` →
      `pytest.raises(ComplianceVerdictError)`; hooks saw `on_step_failed` with
      the message and **no** `on_step_verdict`; `on_step_finished` outcome
      "failed"; the raised traceback contains no engine frames (folding).
- [ ] **Verify**: `python3 -m pytest tests/test_scenario.py tests/test_executor.py -q`.
- [ ] **Run validation**: full gates — `python3 -m pytest tests/ -q` (all green,
      including the two mirror-sync tests landed green in Task 3),
      `python3 -m ruff check .`, `goga lint` (10 cells, 0 errors).
- [ ] **Cross-entity check against the interaction diagram**: gate pass (1),
      gate block (2), gate hard failure (3), steering write-back gate (4),
      config flow (5), facade capability flow (6) — each demonstrated by at
      least one test from Tasks 3–7.

### Task 8: the documentation pages (non-cell work owned by this plan)

The design's Additional Instructions name the accompanying non-cell work items
owned by the plan: the three docs pages follow the same semantics as designed.
No code, no tests — the pages are hand-written docs under `docs/`, and the
already-materialized cell practices are the content source of truth: copy the
semantics (not the file text verbatim — the pages have their own structure and
audience) from the practices named below. Zero contract impact.

**Usages relevant to this task:**
- `configuration` (`prettyplay/config/.usages/configuration.md`, already
  materialized): the source for the `generation_approve` setting documentation —
  the TOML line, the env row, "The instruction compliance gate" section.
- `providers` (`prettyplay/llm/.usages/providers.md`, already materialized): the
  source for the third-operation documentation — parity, effective generation
  model, "The compliance operation" section.
- `generation` (`prettyplay/engine/.usages/generation.md`, already materialized):
  the source for the cache-page documentation — "The instruction compliance
  gate" section (verdict cost, high/medium-low/malformed semantics,
  never-re-gated note).

**CRITICAL: no CODEMANIFEST and no `.goga/usages/**` file is modified by this
task — the practices are read as sources; the docs pages under `docs/` are the
only files changed.**

- [ ] **Code** (docs): `docs/configuration.md` — add the `generation_approve`
      row to the TOML settings table after `generation_prompt` (default true —
      the opt-out default; false — the gate never runs, fully the old
      behavior); the env override row `PRETTYPLAY_GENERATION_APPROVE`
      (true/false/1/0 case-insensitive; an unparseable value fails loudly with
      `ConfigurationError`); the programmatic `PrettyConfig(generation_approve=False)`
      per-test override winning over the file layer (the `strict`/`interactive`
      pattern); and "The instruction compliance gate" section — one extra LLM
      call per successful generation while on, a high finding fails the attempt
      and the retry carries the violation, medium/low pass with a WARNING, a
      malformed verdict is a loud hard failure (`ComplianceVerdictError`), the
      gate never runs on replayed cached code, instructions take no part in the
      step address (changing them requires a manual cache purge).
- [ ] **Code** (docs): `docs/reference/llm-providers.md` — document the third
      port operation `check_instruction_compliance(prompt, user_instructions,
      step_text, code)`: full parity between the providers, the gate model is
      the effective generation model, the fixed INSTRUCTIONS/STEP/CODE user
      blocks, the strict parse (`[]` means compliant; a malformed verdict
      raises `ComplianceVerdictError` — never a silent pass), SDK errors map to
      `LLMUnavailableError`, one request per call with no retry inside the
      provider, no screenshot input on this operation.
- [ ] **Code** (docs): `docs/reference/step-cache.md` — document the
      gate-before-caching invariant: every successfully executed candidate
      (generation, healing, funded regeneration, steering write-back) passes
      `check_step_compliance` before the cache save; an unchecked candidate is
      never stored; replayed cached code is never re-gated; the off switch or
      an empty `generation_prompt` restores the old behavior with zero extra
      LLM calls.
- [ ] **Verify**: the three pages mention `generation_approve` /
      `check_instruction_compliance` / the gate invariant respectively; the
      docs changes touch no code — `python3 -m pytest tests/ -q` stays green
      and `goga lint` stays at 10 cells, 0 errors.

---

## Validation Commands

- `python3 -m pytest tests/ -q`: Run all tests — the whole suite green,
  including the two mirror-sync tests after Task 3.
- `python3 -m pytest tests/ -x -q`: The per-task debugging gate (stop at first
  failure).
- `python3 -m ruff check .`: Lint check (project ruff config: pyproject.toml
  `[tool.ruff]`).
- `python3 -c "from prettyplay.failures import ComplianceVerdictError; from prettyplay.llm import ComplianceFinding, parse_compliance_verdict; from prettyplay.engine import check_step_compliance; from prettyplay.engine.compliance import COMPLIANCE_PROMPT; print('facades ok')"`:
  Facade accessibility of every new export across the four cells.
- `goga lint`: Contract check — 10 cells, 0 errors (read-only gate over the
  materialized manifests).

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location`
      (`errors.py`, `models.py`×2, `loader.py`, `page.py`, `provider.py`,
      `openai_provider.py`, `anthropic_provider.py`, `_request.py`,
      `compliance.py`, `generator.py`, `steering.py`, `executor.py`,
      `scenario.py`)
- [ ] Every contract entity is accessible from the facade
      (`prettyplay.failures`, `prettyplay.llm`, `prettyplay.engine`)
- [ ] Properties and methods match the declared API (`ignore_case: bool =
      False` defaults; the port signature; `check_step_compliance` signature)
- [ ] Descriptions are reflected in behavior (the gate-before-cache invariant on
      all four paths; the standing-high exhaustion verdict; the steering
      decline semantics; the strict parse; the loud env override)
- [ ] Contract dependencies are met (engine→llm `ComplianceFinding` import;
      steering→engine `check_step_compliance` import; llm→failures
      `ComplianceVerdictError` import)
- [ ] Re-exports are accessible from the facade (`PrettyConfig`,
      `BrowserConfig`, `StepHooks` — unchanged, verified by the existing tests)
- [ ] Every coding task followed the TDD workflow (contract tests → code →
      verification → logic tests → debugging → re-verification → lint)
- [ ] Contract tests and logic tests cover facade, API, and behavior within each
      coding task (31 named scenarios: 1 + 4 + 2 + 8 + 12 + 3 + 1)
- [ ] Integration tests exist where cross-entity scenarios require them
      (`test_step_surfaces_compliance_verdict_error`; the six data flows each
      covered by at least one test)
- [ ] No package boundary was expanded (no new cells; `prettyplay/cache`,
      `prettyplay/reporting`, `prettyplay/engine/polling` untouched;
      `example/.prettyplay/cache/**` untouched)
- [ ] `CODEMANIFEST` files were not modified (contract is read-only); the
      `.goga/usages/**` practices and cooks stay at their already-materialized
      target state
- [ ] All validation commands pass (`pytest`, `ruff`, the facade import check,
      `goga lint` — 10 cells, 0 errors)
- [ ] The three docs pages named by the design are updated (Task 8:
      `docs/configuration.md`, `docs/reference/llm-providers.md`,
      `docs/reference/step-cache.md`) — content synchronized with the
      materialized cell practices
- [ ] Every Usages entry is mentioned in at least one task (`conventions`,
      `compliance_prompt`, `system_prompt`, `classification_prompt`, `facade`,
      `classification`, `openai`, `anthropic`, `playwright`, `pydantic`,
      `taxonomy`, `configuration`, `providers`/`generation`/`healing`/`steering`
      cell practices — all referenced in their owning tasks)
- [ ] The frozen mirrors are byte-equal to their practices (both sync tests
      green; `COMPLIANCE_PROMPT` mirror test green)
- [ ] No `on_generation_started` events or attempt ordinals were added for gate
      requests; the request shape of generation/classification and the text
      locating semantics are unchanged

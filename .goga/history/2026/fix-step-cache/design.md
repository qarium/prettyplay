# Design Document: `step-cache-addressing`

<!-- Topic directory: `.goga/history/2026/fix-step-cache/` — ADR `adr.md`, plan `arch.md`, task `task.md`. -->

The step cache addresses steps by the rendered sentence (the addressing text) and cleans its
working scope on close. This document is the complete architectural specification of that change
against the current CODEMANIFESTs (already materialized by the apply stage) and the current
implementation (pre-change). It specifies **what** to implement and **how** — the implementation
order stays with the planning stage.

Source of truth: the six applied CODEMANIFEST files (lint-clean, 0 errors, 12 cells). The ADR
cleanup-amendment applies: `cleanup` is a keyword-only constructor parameter of `PrettyPlay`, not
a layered config field — `prettyplay/config` stays untouched.

## Contract Changes

### Changed CODEMANIFEST Files

- `prettyplay/cache/CODEMANIFEST`: addressing-text identity paragraphs in the header;
  `normalize_step_text` annotation replaced (NFC + trim only, no casefold, no collapse, no marker
  detection); `StepIdentity.normalized_text` reworded to the addressing-text source;
  `CachedStep` gains the `addressing_text` parameter/property and its metadata requirements;
  `StepCache` gains the touched-set Requirements, the STEP_TEXT validation in `load`, the
  STEP_TEXT serialization from `addressing_text` in `save`, and the new `sweep_untouched` method;
  `RunBudgets` identity-key bullet replaced; footer description replaced.
- `prettyplay/engine/renderer/CODEMANIFEST`: header annotations extended with the addressing
  render of `jinja`; `PreparedStep` gains `addressing_text` (param, property, one-render
  Requirement); `render_step` Algorithm steps 3 and 6 replaced plus a one-render Requirement;
  footer description replaced.
- `prettyplay/engine/CODEMANIFEST`: `generate`/`regenerate` carry `prepared.addressing_text` into
  every newly constructed `CachedStep`; `heal` retains the passed render's addressing text; two
  stale header phrases reworded (the apply stage's documented consistency rider).
- `prettyplay/engine/steering/CODEMANIFEST`: the `steer` `identity` param redefined (built by the
  executor from the addressing text); the guided write-back constructs `CachedStep` with
  `prepared.addressing_text`; Requirements extended.
- `prettyplay/engine/groups/CODEMANIFEST`: `normalize_step_text` added to the cache Imports;
  honest-inputs and recovery-re-render header paragraphs updated; `GroupStepOutcome.identity`
  redefined as the execution fact; `recover` Algorithm steps 4–6 replaced (fresh identity from
  the re-rendered addressing text keys healing refresh, regeneration and write-back); new
  Requirement; footer description replaced.
- `prettyplay/CODEMANIFEST`: header annotations (honest inputs, authoring surface, scenario
  records, new cache-lifecycle paragraph); `PrettyPlay` gains `cleanup: bool` (keyword-only,
  default True) and the replaced `close()` algorithm; `StepExecutor.execute` step 2 builds the
  identity from the render product's addressing text; footer description replaced.

### New Entities

- `StepCache.sweep_untouched(cache_key: str) -> removed: list[str]` — `prettyplay/cache`,
  `store.py`. The per-test working-set cleanup: deletes the untouched step files of one cache key
  in this store's scope.
- `PreparedStep.addressing_text` (property/field) — `prettyplay/engine/renderer`, `render.py`.
- `CachedStep.addressing_text` (property/field) — `prettyplay/cache`, `models.py`.
- `PrettyPlay.cleanup` (constructor parameter) — `prettyplay`, `scenario.py`.

### Changed Entities

- `normalize_step_text` — one verbatim rule for every addressing text: Unicode NFC + trim,
  nothing else. The `_WHITESPACE_RUN` collapse, the casefold and the `_TEMPLATE_MARKERS` branch
  are deleted.
- `render_step` — produces both texts of one render (instruction and addressing text) from one
  snapshot and one set of branch decisions.
- `StepCache.load` — validates `STEP_TEXT` by normalizing it and comparing with
  `identity.normalized_text`; restores the metadata value as `CachedStep.addressing_text`;
  records successful reconstructs in the touched set.
- `StepCache.save` — serializes `STEP_TEXT` from `step.addressing_text`; records stored writes
  in the touched set.
- `StepExecutor.execute` — builds the step identity from `prepared.addressing_text` instead of
  the raw `step_text`.
- `StepGenerator._store` (private, `generate`/`regenerate`/`_funded_regeneration` paths) —
  constructs `CachedStep` carrying `prepared.addressing_text`.
- `StepSteering._write_back` (private) — constructs `CachedStep` carrying
  `prepared.addressing_text`.
- `GroupRecovery._run_row` (private) — builds the fresh row identity from the re-rendered
  addressing text; refreshes healing counters inside the row loop under the fresh identity;
  failure updates carry the fresh identity.
- `PrettyPlay.__init__`/`close` — the `cleanup` switch and the guarded close-time sweep.

### Deleted Entities

- None. No cell, no contract type, no import edge is removed. The dropped internals
  (`_WHITESPACE_RUN`, `_TEMPLATE_MARKERS` constants of `prettyplay/cache/text.py`) are
  implementation details, not contract entities.

### Usages and Annotations Changes

- `.goga/usages/cooks/jinja.md` — the "Addressing render — the second text of one render"
  section (already in the worktree): `{{ ... }}` substituted from the same snapshot, active
  `{% var name %}` kept verbatim, inactive branches contribute nothing, one snapshot invariant,
  `{% raw %}` literal in both texts.
- Cell `.usages/` files rewritten/updated by the apply stage: `prettyplay/cache/.usages/`
  `addressing.md` (full rewrite), `storage.md` (file-format sentence, per-test working set
  section, team workflow), `budgets.md` (fresh-budget bullet);
  `prettyplay/engine/renderer/.usages/rendering.md` (the addressing text section);
  `prettyplay/engine/groups/.usages/recovery.md` (re-addressing bullet);
  `prettyplay/.usages/lifecycle.md` (cache lifecycle on close), `steps.md` (cache addressing and
  replay section, addressing preamble, honest-context tail).
- See `.usages/` Update below for the one post-apply consistency fix (`storage.md` example).

## Applied Fixes

### Design Review Fixes

- Replaced the proposed two-pass Jinja render with one evaluation and two derived text views.
  Jinja's built-in `random` filter proved that a common context snapshot does not guarantee
  equal values or branch decisions across two evaluations. Added a controlled-filter test.
- Replaced canonicalized capture tags with their exact source spans. The renderer contract and
  `jinja` practice require reached tags to remain verbatim in the addressing text. Added a
  formatting-variant and inactive-branch test.
- Corrected test traces for NFC output, keyword-only identities, the heal path's same-normalized
  address precondition, a missing result assignment and a missing strict-replay trace. Tightened
  the sweep fixtures so metadata ownership is actually provable.

### Fixed CODEMANIFEST Defects

- None. Phase 3 validation found no CODEMANIFEST defects: `goga lint` reports 12 cells, 0
  errors; all backtick references resolve; `location` directives point at existing same-level
  files; the four consistency dimensions (Interface ↔ Type, Type ↔ Mutation, Interface ↔
  Interface, Annotations ↔ Entity) hold — verified across the executor → engine → cache chain,
  the recovery fresh-identity chain and the facade sweep edge.

### Fixed `.usages/` Defect (post-apply consistency)

- `prettyplay/cache/.usages/storage.md`: the "Read and write" example constructed
  `CachedStep(identity=..., code=..., created_at=...)` without the new required
  `addressing_text` — it violated the applied contract requirement
  `normalize_step_text(addressing_text) == identity.normalized_text`. Fixed by passing
  `addressing_text="open the login page"` (reason: consumer documentation must match the
  contract it documents).

## Entity Interaction and Data Flow

### Interaction Diagram

```
                         ┌─────────────────────────────── prettyplay (facade) ──────────────────────────────┐
                         │  PrettyPlay(cache_key, cache_path, *, cleanup=True, hooks, config)                │
                         │  close(): runtime teardown ──then── cleanup? ──> StepCache.sweep_untouched(key)   │
                         └───────┬───────────────────────────────────────────────────────────┬───────────────┘
                                 │ composes                                                  │ identity built from
                                 ▼                                                           │ prepared.addressing_text
        ┌──────────── StepExecutor.execute ─────────────┐                                    │
        │ 1. render_step(step_text, ..., memory, vars)  │                                    │
        │        │                                      │                                    │
        │        ▼                                      │                                    │
        │  PreparedStep(instruction, ADDRESSING_TEXT,   │                                    │
        │               inputs, declarations)           │                                    │
        │        │                                      │                                    │
        │        ▼  normalize_step_text(addressing_text)│ + cache_key + step_type             │
        │  StepIdentity ────────────────────────────────┼────────────────────────────────────>│
        └───┬──────────────┬───────────────┬────────────┴────────────────────────────────────┘
            │ miss          │ cached failure │ group failure
            ▼              ▼               ▼
   StepGenerator      StepHealer      GroupRecovery ── re-render row step ──> render_step ──> fresh identity
   generate/          heal ──>                 │                                  (normalize_step_text)
   regenerate         regenerate               ▼
        │                 │             StepGenerator.regenerate(fresh_identity, fresh prepared)
        ▼                 ▼                │
     _store(identity, addressing_text, code) ──> CachedStep ──> StepCache.save ──> touched set
            (every path stores prepared.addressing_text verbatim)

   StepSteering.steer (terminal IncurableStepError, non-strict interactive)
        └─> _write_back(instruction, addressing_text, identity, code) ──> StepCache.save ──> touched set

  prettyplay/cache:
    StepCache.load ──hit──> normalize(STEP_TEXT)==normalized_text? ──> CachedStep(addressing_text=STEP_TEXT) + touched
    StepCache.save ──stored──> STEP_TEXT := step.addressing_text + touched
    StepCache.sweep_untouched(cache_key) ──> delete untouched digest files of the key in scope
```

### Data Flows

**Flow 1 — addressing (every step execution).**
`step_text` (raw sentence) → `render_step` (one snapshot of `StepMemory` + `vars`) →
`PreparedStep(instruction, addressing_text, inputs, declarations)` →
`normalize_step_text(addressing_text)` → `StepIdentity(cache_key, step_type, normalized_text)` →
`identity.filename` (sha256 of the triple). The raw sentence never addresses anything after this
change; it stays the render and re-render source only.

**Flow 2 — generation write-back.** Executor miss → `generate(identity, prepared, ...)` →
candidate proven → `_store(identity, prepared.addressing_text, code)` → `CachedStep` →
`save` → file with `STEP_TEXT = addressing_text`, name = `identity.filename` → touched set gains
the name. The same flow runs inside `regenerate` (healer, recovery row) and the funded
regeneration of the bounded healing.

**Flow 3 — replay.** Executor hit path → `load(identity)` → metadata check
(`normalize_step_text(STEP_TEXT) == identity.normalized_text`) → `CachedStep` with
`addressing_text = STEP_TEXT` (the saved metadata is preserved) → touched set gains the name →
code executes under the settle window.

**Flow 4 — steering write-back.** Terminal `IncurableStepError` (non-strict interactive) →
`steer(failure, identity, prepared, ...)` → a green, validated, gate-passed turn →
`_write_back(instruction, prepared.addressing_text, identity, code)` → `save` → touched set.

**Flow 5 — recovery row re-addressing.** Group failure → `recover(..., identity, ...)` →
diagnosis → the row, per step: `render_step(trace.sentence, trace.step_type, memory, trace.vars)`
→ `fresh.addressing_text` → `normalize_step_text` → fresh `StepIdentity` (cache_key taken from
`trace.identity`, the execution fact) → `refresh_healing(fresh_identity)` →
`regenerate(fresh_identity, fresh, ...)` → write-back under the fresh identity. A repeat failure
updates the active failure to the fresh identity.

**Flow 6 — close-time sweep.** `close()` → page close → `runtime.close()` (idempotent) →
`cleanup` on → `sweep_untouched(cache_key)`: enumerate digest-named `*.py` files in
`_target_dir()`; parse metadata; skip foreign keys silently; skip unreadable metadata with a
WARNING; delete untouched files of the key, one INFO log per deletion; per-file failures logged
WARNING and swallowed; return the removed names.

### Entity Dependencies

Implementation order (leaves first — matches the plan; within each cell, files are independent):

1. `prettyplay/cache` — `text.py` (normalization), `models.py` (`CachedStep.addressing_text` +
   the invariant validator), `store.py` (touched set, STEP_TEXT validation/serialization,
   `sweep_untouched`). Depends only on untouched `prettyplay/config` and `prettyplay/reporting`.
2. `prettyplay/engine/renderer` — `render.py` (`PreparedStep.addressing_text`, the addressing
   render). Depends only on untouched `prettyplay/failures`.
3. `prettyplay/engine` — `generator.py` (`_store` threading). No signature changes.
4. `prettyplay/engine/steering` — `steering.py` (`_write_back` threading). No signature changes.
5. `prettyplay/engine/groups` — `recovery.py` (fresh identity inside the row loop; the import
   gains `normalize_step_text`).
6. `prettyplay` — `executor.py` (identity switch), `scenario.py` (`cleanup` parameter, guarded
   sweep). The facade lands last: everything it composes must already carry the new contract.

No import edges are added or removed. The groups → cache edge only gains `normalize_step_text`
in its Types payload; the facade → cache `sweep_untouched` call rides the existing edge.

## Code Stack Trace

### Trace: `render_step`

#### Chain
1. **Input**: `execute` (or the recovery row loop) calls
   `render_step(text, step_type, memory, vars)` with the raw sentence, the step kind, the
   per-test memory and the validated call-local inputs.
2. **Snapshot**: `memory.snapshot()` → a stable `dict[str, str]` copy; `inputs = {} if vars is
   None else dict(vars)` → the one Jinja evaluation receives this context.
3. **Source tags and single evaluation**: lex the source once to collect exact `{% var ... %}`
   spans in parse order (Jinja's lexer preserves whitespace in token values and does not expose
   raw-block contents as tag tokens). Compile with the capture extension; each parsed tag receives
   its matching source span. Evaluate once: each reached capture emits an opaque, unique marker
   and records its name and source span. All interpolations, filters, branches and loops execute
   only once. Preserve the existing compile/render error mapping.
4. **Derive both texts** from that one output: remove only emitted capture markers for
   `instruction`; replace only those markers with their exact source spans for `addressing_text`.
   Guard marker collisions with ordinary rendered data and fail before browser execution rather
   than silently altering either string. Substituted values are never parsed as templates.
5. **Declarations and assertion check**: use the names recorded by the same evaluation;
   `step_type == "assertion" and declarations` raises the existing authoring error.
6. **Output**: `PreparedStep(instruction=instruction, addressing_text=addressing_text,
   inputs=inputs, declarations=declarations)` — frozen, kw_only, empty defaults.

#### Checkpoint Summary
- One evaluation for both texts: **passed** (the rendered output is split only after evaluation;
  a nondeterministic filter cannot yield different values between the two texts).
- Instruction byte-identical to the old render: **passed** for ordinary templates when marker
  removal restores the capture tag's original empty output.
- Authoring errors before browser execution: **passed** (the original mapping and assertion
  check run before returning the render product).
- `{% raw %}` literal in both texts: **passed** (raw blocks are template-source constructs —
  evaluated once).
- Review fix: a second evaluation was removed because standard Jinja includes nondeterministic
  filters such as `random`; a common snapshot does not make two evaluations equivalent.

### Trace: `normalize_step_text`

#### Chain
1. **Input**: an addressing text — the rendered sentence from `PreparedStep.addressing_text`
   (executor, recovery), the `STEP_TEXT` metadata value (load validation), or a plain sentence
   addressing as itself.
2. `unicodedata.normalize("NFC", text)` → checkpoint: composes combining marks; NFC of NFC is
   NFC (idempotent).
3. `.strip()` — leading and trailing whitespace only → checkpoint: case preserved, internal
   whitespace preserved, no template-marker detection.
4. **Output**: the normalized addressing text — the `normalized_text` of `StepIdentity`, the
   comparison basis of `load`, and (via the triple) the sha256 file name.

#### Checkpoint Summary
- «Click Sign in» ≠ «click  sign in »: **passed** — both differences survive normalization.
- Plain sentence == identical template render: **passed** — exact-text equality is the only
  unifier.
- Pure/deterministic: **passed** — stdlib-only, no I/O, no locale.

### Trace: `StepCache.load`

#### Chain
1. **Input**: `identity` from the executor (or the recovery row's fresh identity).
2. Resolve `self._target_dir() / identity.filename`; a missing file → `None` → checkpoint: a
   miss touches nothing.
3. Read the text; `_parse_header` extracts `STEP_TEXT`, `CACHE_KEY`, `STEP_TYPE`, `CREATED_AT`;
   the code tail starts at the sentinel (legacy: at `def step(`) → checkpoint: unchanged
   mechanics.
4. Validate: `CACHE_KEY`/`STEP_TYPE` equal the identity's (else `None`);
   `normalize_step_text(fields["STEP_TEXT"]) == identity.normalized_text` (else `None` — a
   mismatched sentence is a miss) → checkpoint: new files pass by construction
   (`STEP_TEXT = addressing_text`); legacy files whose old normalization coincides with the new
   one also pass — their `STEP_TEXT` already contains the normalized sentence.
5. Build `CachedStep(identity=identity, addressing_text=fields["STEP_TEXT"], code=code,
   created_at=fields["CREATED_AT"])` — the saved metadata value is restored as the addressing
   text → checkpoint: the model invariant holds — step 4 checked exactly
   `normalize(addressing_text) == normalized_text`.
6. `self._touched.add(identity.filename)`; return the step → checkpoint: a damaged entry (any
   parse/validation exception path) returns `None` and touches nothing.

#### Checkpoint Summary
- Touched-set success-only marking: **passed** (single add site on the success path).
- STEP_TEXT validation by normalization: **passed** (type flow: `str` → `str` comparison).
- Legacy restore: **passed** (documented in the contract; consistent with the invariant).

### Trace: `StepCache.save`

#### Chain
1. **Input**: a `CachedStep` built by `_store`/`_write_back` (carrying `addressing_text`) or a
   test.
2. Writability probe; read-only → `on_cache_skipped`, return `False` → checkpoint: a skipped
   write touches nothing.
3. `_serialize(step)`: header literals — `STEP_TEXT` from `step.addressing_text` (was
   `identity.normalized_text`), then `CACHE_KEY`, `STEP_TYPE`, `CREATED_AT`, the sentinel, the
   code → checkpoint: the file name still derives from `step.identity` — the address space is
   unchanged; the metadata sentence becomes the verbatim rendered sentence.
4. Temp file in the target directory (unique name, fsync), `os.replace` with the Windows retry;
   any skip/failure path reports `on_cache_skipped` and returns `False` → checkpoint: untouched
   on failure.
5. Success: `on_cache_saved` with the file name; `self._touched.add(step.identity.filename)`;
   return `True` → checkpoint: only a stored write touches.

#### Checkpoint Summary
- STEP_TEXT serialization source: **passed**.
- Touched-set success-only marking: **passed**.
- Atomicity/concurrency guarantees unchanged: **passed** (steps 3–4 mechanics untouched).

### Trace: `StepCache.sweep_untouched`

#### Chain
1. **Input**: `cache_key` — the owning test object's context key (from `PrettyPlay.close`).
2. Scope: `self._target_dir()`; a nonexistent directory → return `[]` → checkpoint: no error on
   a fresh test that never wrote.
3. Enumerate digest-named files only — names matching `^[0-9a-f]{64}\.py$` (sorted, for
   deterministic order) → checkpoint: the file name is the address — the sha256 of the triple;
   foreign files (`notes.py`, stale `.tmp-*.py` temps) are not step files and are left alone,
   so garbage never produces WARNING noise.
4. Per file: read + `_parse_header`; unreadable metadata (any of `OSError`, `ValueError`,
   `SyntaxError`, `KeyError`, `IndexError`) → `logger.warning(...)` naming the file, continue →
   checkpoint: ownership is unprovable in a possibly shared root.
5. `fields["CACHE_KEY"] != cache_key` → skip silently → checkpoint: other tests' entries in a
   shared root survive.
6. `file.name in self._touched` → survive → checkpoint: touched = successfully loaded or saved.
7. Delete (`unlink`); an `OSError` → `logger.warning(...)`, continue; success →
   `removed.append(file.name)` + one `logger.info` record naming the file → checkpoint:
   deletions are log records only — no hook event (deferred contract decision).
8. **Output**: `removed` — the deleted file names. The enumeration itself is wrapped: an
   unexpected `OSError` from listing logs a WARNING and returns the partial `removed` →
   checkpoint: never raises.

#### Checkpoint Summary
- Never raises: **passed** (per-file guards + the enumeration guard).
- Idempotent: **passed** — survivors are touched files, foreign keys and unreadable ones; a
  repeated call re-enumerates and finds nothing new to delete.
- Untouched legacy files of the key swept on the first call: **passed** — they are digest-named,
  key-matching, untouched.
- No address recomputation: **passed** — membership tests use names only.

### Trace: `StepExecutor.execute`

#### Chain
1. **Input**: `step_text`, `step_type`, `page`, optional `group`/`tries`/`delay`/`vars`.
2. `on_step_started`; the declared `delay` passes quietly → unchanged.
3. `prepared = render_step(step_text, step_type, self._memory, vars)` → authoring errors raise
   `PrettyplayError` before identity, cache or browser — unchanged → checkpoint: identity
   untouched on authoring errors.
4. **The switch**: `identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
   normalized_text=normalize_step_text(prepared.addressing_text))` — was
   `normalize_step_text(step_text)` → checkpoint: type flow `str → str`; a plain sentence
   addresses as itself (its addressing text equals the sentence); a template addresses by its
   rendered values — cross-value replay becomes impossible because different values produce
   different `normalized_text`, hence different file names.
5. `SettleWindow` from polling settings + `tries`; the per-step attempt history; the group URL
   bracket; `cached = self._cache.load(identity)` → checkpoint: load now validates STEP_TEXT by
   normalization — a file of the same triple is found; the executor is unaware of the change.
6. Hit → replay under settle, validate, publish; miss + strict → the strict stop; miss →
   `generate`; cached failure → strict classify / group recover / heal — all unchanged paths
   receive `identity` and `prepared` → checkpoint: every downstream write-back (Flow 2/4/5)
   stores `prepared.addressing_text` under this identity — the invariant
   `normalize(addressing_text) == normalized_text` holds by construction.
7. Scenario record (`sentence=step_text, instruction=prepared.instruction`), group trace
   (`identity` recorded — the execution fact), the event bracket — unchanged.

#### Checkpoint Summary
- Identity from the render product's addressing text: **passed**.
- Every engine call receives the prepared instruction: **passed** (unchanged threading).
- Contract interaction checkpoint (executor ↔ generator/healer/steering/recovery): **passed** —
  `StepIdentity` + `PreparedStep` types align on all six edges.

### Trace: `StepGenerator.generate` / `regenerate` (via `_store`)

#### Chain
1. **Input**: `identity`, `prepared`, `step_type`, ... (unchanged signatures).
2. The loops are unchanged: budget ask, request inputs from `prepared` (instruction + INPUTS +
   RESULTS), settle execution, result validation, the compliance gate, publication at
   acceptance.
3. On acceptance: `_store(identity, prepared.addressing_text, code)` — the private helper gains
   the addressing text parameter; it builds `CachedStep(identity=identity,
   addressing_text=prepared.addressing_text, code=code, created_at=date.today().isoformat())`
   and saves → checkpoint: `prepared.addressing_text` is carried **unchanged** — no
   normalization applied at storage (the file keeps the verbatim rendered sentence); the
   identity's `normalized_text` is the NFC+trim of that same text (the executor/recovery built
   it so) — the model invariant holds.
4. **Output**: the stored `CachedStep` — the caller (healer: the healed step; executor: the
   generated step; recovery: the row write-back) returns it unchanged.

#### Checkpoint Summary
- Every newly constructed `CachedStep` carries the render's verbatim addressing text:
  **passed** — single choke point (`_store`), three call sites (`_generation_loop`,
  `_healing_loop`, `_funded_regeneration`) all hold `prepared`.
- Healing never substitutes an old cached entry's metadata text: **passed** — the healer passes
  the executor's `prepared` into `regenerate`; nothing reads the loaded step's metadata for
  storage.

### Trace: `StepHealer.heal`

#### Chain
1. **Input**: the failed `step` (loaded `CachedStep`), the replay `error`, the executor's
   `prepared`, ... (unchanged signature).
2. Classification → verdict mapping → the rot/fixable branch calls
   `regenerate(identity=step.identity, prepared=prepared, ...)` → checkpoint:
   `step.identity` is the same object the executor built from `prepared.addressing_text` (the
   load returned it unchanged), so the regenerated `CachedStep` carries the **current render's**
   addressing text — never the old entry's metadata text.
3. **Output**: the healed step from `regenerate`. No healer code changes; the retention is
   structural.

#### Checkpoint Summary
- Addressing-text retention through healing: **passed** (structural, via `regenerate`).

### Trace: `StepSteering.steer` (write-back)

#### Chain
1. **Input**: `failure`, `identity` (executor-built from the addressing text), `prepared`, ... —
   `identity` doc: the healed step is written back under it; a successful write joins the
   touched set.
2. Banner, guidance turns, candidate generation/execution, validation, gate — unchanged.
3. On an accepted turn: `_write_back(prepared.instruction, prepared.addressing_text, identity,
   code)` — the helper gains the addressing text; it builds `CachedStep(identity=identity,
   addressing_text=addressing_text, code=code, created_at=...)` and saves → checkpoint: the
   STEP_TEXT metadata preserves the stuck render's addressing text verbatim;
   `normalize(addressing_text) == identity.normalized_text` holds (one executor-built identity,
   one prepared product); the successful save marks the touched set inside `StepCache.save` —
   the steering cell holds no touched-set logic of its own.
4. **Output**: the healed `CachedStep` (or `None` on decline — nothing written, nothing
   touched).

#### Checkpoint Summary
- Write-back carries the stuck render's verbatim addressing text: **passed**.
- Touched-set marking through `save` only: **passed**.

### Trace: `GroupRecovery.recover` (the row loop)

#### Chain
1. **Input**: `group_prompt`, `traces`, `prepared`, `step_type`, `previous_steps`, `identity`,
   `attempt_history`, `page`, `window`, `memory`.
2. Cycle cap, local views, the active failure from the executor's facts, diagnosis, verdict
   mapping, the row resolution (quote match / active occurrence) — unchanged.
3. **Removed**: the pre-row healing-counter refresh loop (`for _occurrence, trace in row:
   refresh_healing(trace.identity)`) — it refreshed under stale trace identities → checkpoint:
   defect in the old design under the new addressing (a re-rendered step draws its fresh budget
   under the fresh identity, not the trace one).
4. Per row step (inside `_run_row`): declared delay; `fresh = render_step(trace.sentence,
   trace.step_type, memory, trace.vars)`; **fresh identity**:
   `StepIdentity(cache_key=trace.identity.cache_key, step_type=trace.step_type,
   normalized_text=normalize_step_text(fresh.addressing_text))`; `refresh_healing(fresh_identity)`
   — once per cycle per row step; `regenerate(identity=fresh_identity, prepared=fresh, ...,
   group_prompt=group_prompt, ...)` → checkpoint: regeneration and write-back key on the fresh
   identity — a row step re-rendered against changed memory is a new address with a fresh
   budget; `trace.identity` keeps only the `cache_key` (the execution fact, never rewritten in
   the trace views).
5. Acceptance: local view updates by occurrence index (instruction only — identity stays the
   execution fact); reporting — unchanged.
6. A repeat failure (`IncurableStepError` from regeneration): the active failure updates to
   `fresh`, `trace.step_type`, **`fresh_identity`**, the grown row history; the local trace
   marks the occurrence failed preserving the freshly prepared instruction; re-enter the cycle
   → checkpoint: the next diagnosis STEP/HISTORY describe the failing row occurrence under its
   fresh identity; the caller's stored traces and scenario records are not rewritten.
7. `_anchored_history(trace)` (earlier row steps) loads the cached code under `trace.identity`
   — unchanged → checkpoint: record 0 anchors the code the test actually executed; the trace
   identity is where that code was loaded/saved (execution fact).

#### Checkpoint Summary
- Fresh identity after the re-render: **passed** (built from `fresh.addressing_text`).
- `refresh_healing` keyed by the fresh identity, once per cycle per row step: **passed** (the
  single in-loop call).
- No stale-trace-identity writes: **passed** (the only write path is `regenerate` under
  `fresh_identity`).
- Fresh budget for a changed-memory re-render: **passed** (identity-keyed registry).

### Trace: `PrettyPlay.__init__` / `close`

#### Chain
1. **Input**: `PrettyPlay(cache_key, cache_path=None, *, cleanup=True, hooks=None,
   config=None)` — `cleanup` keyword-only, default True; no config/env/pyproject surface.
2. The composition is unchanged (runtime, reporter, cache, engines, executor);
   `self._cleanup = cleanup` → checkpoint: construction stays cheap; nothing sweeps at
   construction.
3. `close()`: page close (if any) → `runtime.close()` (idempotent, `finally`) → then, when
   `self._cleanup`: `self._cache.sweep_untouched(self.cache_key)` wrapped in
   `try/except Exception: logger.warning("cache sweep failed on close", exc_info=True)` →
   checkpoint: the sweep runs **after** the teardown — a teardown error propagates and skips
   the sweep (never masked); a sweep error is swallowed and logged (the close never fails on
   hygiene); `sweep_untouched` itself never raises by contract — the facade guard is
   belt-and-braces.
4. `__exit__` calls `close()` — the context manager inherits the behavior; a repeated `close()`
   re-runs the idempotent sweep and deletes nothing new → checkpoint: idempotent.

#### Checkpoint Summary
- Teardown-then-guarded-sweep order: **passed**.
- Idempotency and repeated-close safety: **passed**.
- No config surface: **passed** (`prettyplay/config` untouched).

## Algorithm Design

### `normalize_step_text` (`prettyplay/cache/text.py`)

**Responsibility**: the single verbatim normalization of every addressing text — identity and
addressing.

**Algorithm:**
```
1. normalized ← Unicode NFC of `text`
   → composed forms; idempotent
2. return normalized.strip()
   → leading and trailing whitespace only
```

**Errors:** none — pure function.

**Edge Cases:**
- «Click Sign in» stays «Click Sign in»; «click  sign in » → «click  sign in» — case and
  internal whitespace significant (rendered values are data).
- Text containing `{{`, `{%`, `{#` — treated as plain data; the marker-detection branch is gone.
- Idempotent: `normalize(normalize(x)) == normalize(x)`.

**Implementation notes**: delete `_WHITESPACE_RUN` and `_TEMPLATE_MARKERS`; keep the `re` import
only if still used (it is not — drop it); docstring per the contract annotation.

### `CachedStep` (`prettyplay/cache/models.py`)

**Responsibility**: one cached step in memory — the metadata (identity, addressing text,
creation date) and the generated code.

**Algorithm:**
```
1. Fields: identity (StepIdentity), addressing_text (str, default ""),
   code (str, default ""), created_at (str, default "") — kw_only
2. model_validator(mode="after"):
   - normalize_step_text(addressing_text) == identity.normalized_text
     else raise ValueError — the invariant of every built cached step
```

**Errors:** a pydantic `ValidationError` (wrapping the `ValueError`) on an invariant violation —
a construction-time programming error, never a runtime path (all sites comply; `load` validates
exactly this equality before constructing).

**Edge Cases:**
- The legacy restore (`addressing_text` = the old normalized sentence) passes: `load` checked
  `normalize(STEP_TEXT) == normalized_text`, which is the validator's own condition.
- Docstrings: the `addressing_text` attribute documents "the verbatim rendered sentence before
  NFC and trim; the metadata sentence field carries it".

**Decision — mechanical invariant enforcement.** The contract states the requirement for "every
newly built cached step". Enforcing it as a pydantic model validator (rather than site
discipline) makes a violation impossible to construct: every documented path (store load,
generator `_store`, steering `_write_back`) satisfies it, as traced above. Import
`normalize_step_text` from `.text` (no cycle: `text.py` imports stdlib only).

### `PreparedStep` + `render_step` (`prettyplay/engine/renderer/render.py`)

**Responsibility**: the render product of one step sentence — both texts of one render.

**Algorithm (render_step):**
```
1. snapshot ← memory.snapshot(); inputs ← vars or {}
2. environment ← Environment(autoescape=False, undefined=StrictUndefined,
   extensions=[capture extension]); template ← environment.from_string(text)
3. Lex source tag spans in parse order; pass each parsed `{% var ... %}` its exact span. Render
   exactly once against snapshot and inputs. Each reached capture records its name and source
   span, then emits a unique opaque marker representing only that occurrence.
4. Derive instruction by removing the emitted capture markers; derive addressing_text by
   replacing them with their original source spans. Use unique unpredictable markers and verify
   that each emitted marker appears exactly once in the completed output; an extra occurrence
   means ordinary data collided with a marker, so fail loudly before returning.
5. declarations ← list(extension.declarations)
6. IF step_type == "assertion" AND declarations: raise the existing authoring error
7. return PreparedStep(instruction, addressing_text, inputs, declarations)
```

`_MarkedVarExtension(VarExtension)`:
```
_record(name):
1. super()._record(name)        # the same reserved/duplicate checks, the same declaration recording
2. create a unique opaque marker for this reached occurrence; record its exact source span
3. return the marker; postprocessing removes it for instruction and restores the tag for addressing
```

**Errors:** keep the existing `PrettyplayError` mapping for compilation, undefined names and
capture authoring errors. A marker collision must fail loudly before browser execution; it must
never silently produce a mismatched instruction and address.

**Edge Cases:**
- A plain sentence: `addressing_text == instruction == text` (no tags) — addresses as itself.
- A capture tag inside an inactive branch: absent from both texts and declarations.
- A memory value containing `{% var x %}` or `{{ x }}`: literal data in both texts.
- `{% raw %}` blocks: literal in both texts.
- Tag formatting variations (`{%var x%}`, `{% var  x %}`): the addressing text preserves each
  reached tag exactly as written; these variants therefore have different addresses.

**Decisions.**
1. **One evaluation implements the contract's one-render requirement.** A common snapshot is
   insufficient: Jinja's standard `random` filter can change values and branch decisions between
   evaluations. Emit identifiable capture markers during the sole evaluation, then derive the two
   strings without rerunning Jinja. A collision guard prevents marker text in user data from
   being silently treated as a capture. The instruction after marker removal must equal the old
   single-render output for ordinary templates.
2. **Exact tag source.** Lex the template source before compilation and associate each parsed
   capture with its raw span. Jinja's lexer retains token whitespace; raw-block contents are data,
   not capture tags. The addressing text uses the reached tag's original span, as the contract's
   `verbatim` and the `jinja` usage's `as written` require.
3. **Error mapping.** Keep the existing compile/render mapping around the sole evaluation.

### `StepCache` (`prettyplay/cache/store.py`)

**Responsibility**: the repository store — addressing, atomic writes, the read-only mode, and
the per-test working-set lifecycle (touched-address accumulation, close-time sweep).

**Algorithm (changes only):**
```
__init__: ... existing ... ; _touched: set[str] ← ∅        # per instance, memory only

load(identity):
1..3. unchanged resolution/parse/tail
4. IF CACHE_KEY ≠ identity.cache_key OR STEP_TYPE ≠ identity.step_type: return None
5. IF normalize_step_text(STEP_TEXT) ≠ identity.normalized_text: return None
6. step ← CachedStep(identity, addressing_text=STEP_TEXT, code, created_at)
7. _touched.add(identity.filename); return step
   # every None path (missing, damaged, mismatch) touches nothing

save(step):
1..5. unchanged, except _serialize writes STEP_TEXT from step.addressing_text
6. on success (after the atomic replace): emit on_cache_saved; _touched.add(filename); return True
   # every skipped/failed path touches nothing

sweep_untouched(cache_key) -> removed:
1. scope ← _target_dir(); IF not scope.is_dir(): return []
2. candidates ← sorted(name for name in scope.iterdir()
                       if _STEP_FILE_NAME.fullmatch(name.name))     # ^[0-9a-f]{64}\.py$
   — an OSError of the listing: log WARNING, return the partial removed
3. FOR each candidate:
   a. TRY text ← read; fields ← _parse_header(text)
      CATCH (OSError, ValueError, SyntaxError, KeyError, IndexError):
         logger.warning("cache sweep skipped a file with unreadable metadata",
                        extra={"filename": name}); continue
   b. IF fields["CACHE_KEY"] ≠ cache_key: continue                  # silent
   c. IF name ∈ _touched: continue                                  # survives
   d. TRY name.unlink()
      CATCH OSError: logger.warning("cache sweep failed on a file",
                                    extra={"filename": name}); continue
   e. removed.append(name); logger.info("cache file swept",
                                        extra={"filename": name, "cache_key": cache_key})
4. return removed
```

**Errors:** `load`/`save` unchanged; `sweep_untouched` never raises — per-file guards plus the
enumeration guard; deletions and skips are log records only (no hook event — deferred decision).

**Edge Cases:**
- Idempotency: survivors are touched, foreign-key and unreadable files; a repeat call is a no-op.
- A fresh test that never wrote: the scope directory may not exist → `[]`.
- Foreign non-digest files (`notes.py`, stale `.tmp-*.py`): never enumerated, never logged.
- The touched set is per `StepCache` instance — the facade's per-test composition gives one
  store (and one set) per test; engines and steering share it, so every write-back path touches.
- The sweep knows nothing of the `cleanup` switch — the facade decides.

**Implementation notes**: module logger `logging.getLogger("prettyplay")`; the digest-name
pattern as a module constant; `_serialize` header tuple `("STEP_TEXT", step.addressing_text)`.

### `StepExecutor.execute` (`prettyplay/executor.py`)

**Responsibility**: the step cycle — render, address, hit/miss, heal/recover/steer.

**Algorithm (step 2 of the contract only):**
```
2. prepared ← render_step(step_text, step_type, memory, vars)     # unchanged
   identity ← StepIdentity(cache_key=self.cache_key, step_type=step_type,
                           normalized_text=normalize_step_text(prepared.addressing_text))
   # was normalize_step_text(step_text); everything downstream unchanged
```

**Errors:** unchanged.

**Edge Cases:** the docstring of `step_text` loses "the addressing artifact" — it is now "the
template source; never rendered into a request". The Requirement wording lands verbatim:
"The addressing text of the render product builds the step address; the prepared instruction
reaches every engine call; the verbatim NFC+trim normalization is an addressing key only".

### `StepGenerator` (`prettyplay/engine/generator.py`)

**Responsibility**: candidate generation/regeneration; the single caching choke point.

**Algorithm (the `_store` helper only):**
```
_store(identity, addressing_text, code):
1. step ← CachedStep(identity=identity, addressing_text=addressing_text, code=code,
                     created_at=date.today().isoformat())
2. self._cache.save(step); return step
```
Call sites — `_generation_loop`, `_healing_loop`, `_funded_regeneration` — pass
`prepared.addressing_text` (each holds `prepared`).

**Errors/Edge Cases:** none new. The param docstrings of `generate`/`regenerate` gain the
contract sentence: the `addressing_text` of `prepared` is carried unchanged into every newly
constructed `CachedStep`; the `normalized_text` of its `identity` is the NFC+trim normalization
of that text.

### `StepSteering._write_back` (`prettyplay/engine/steering/steering.py`)

**Algorithm:**
```
_write_back(instruction, addressing_text, identity, code):
1. step ← CachedStep(identity=identity, addressing_text=addressing_text, code=code,
                     created_at=date.today().isoformat())
2. stored ← self._cache.save(step)          # a stored write joins the touched set
3. emit on_healed (instruction); the console line reflects `stored`
4. return step
```
The call site (step 7 of `steer`) passes `prepared.instruction, prepared.addressing_text,
identity, code`.

**Errors/Edge Cases:** none new — the save is best-effort as today.

### `GroupRecovery` (`prettyplay/engine/groups/recovery.py`)

**Algorithm (the row mechanics only):**
```
resolve row (unchanged) — then DELETE the pre-row refresh loop

_run_row, per (occurrence, trace):
1. IF trace.delay is not None: sleep(trace.delay)
2. fresh ← render_step(trace.sentence, trace.step_type, memory, trace.vars)
3. fresh_identity ← StepIdentity(cache_key=trace.identity.cache_key,
                                 step_type=trace.step_type,
                                 normalized_text=normalize_step_text(fresh.addressing_text))
4. self._budgets.refresh_healing(fresh_identity)      # once per cycle per row step
5. row_history ← active.history if occurrence == active.occurrence else _anchored_history(trace)
6. healed ← regenerate(identity=fresh_identity, prepared=fresh, step_type=trace.step_type,
                       previous_steps=local_scenario, group_prompt=group_prompt, page=page,
                       attempt_history=row_history, recommendation=verdict.recommendation,
                       window=row_window, memory=memory)
7. CATCH IncurableStepError:
   active.prepared ← fresh; active.step_type ← trace.step_type; active.identity ← fresh_identity
   active.history ← row_history; active.occurrence ← occurrence
   local_traces[occurrence] ← trace.model_copy(update={"instruction": fresh.instruction,
                                                       "outcome": "failed"})
   raise                                            # the cycle re-enters
8. acceptance: local views update the occurrence instruction only (identity = execution fact);
   on_healing_started/on_healed; the structured log record — unchanged
```

**Errors:** unchanged — a re-render authoring error of a row step stays that step's loud failure
(it raises out of `render_step` before any identity work).

**Edge Cases:**
- The import line gains `normalize_step_text`: `from ...cache import CachedStep, RunBudgets,
  StepCache, StepIdentity, normalize_step_text`.
- `_anchored_history` is unchanged: record 0 anchors the code the test executed, loaded under
  the execution-time (trace) identity.
- The group traces and scenario records the caller stores are never rewritten.

### `PrettyPlay` (`prettyplay/scenario.py`)

**Algorithm:**
```
__init__(cache_key, cache_path=None, *, cleanup=True, hooks=None, config=None):
  ... unchanged composition ... ; self._cleanup ← cleanup

close():
1. page ← self._page; self._page ← None
2. TRY: IF page is not None: page.close()
   FINALLY: self._runtime.close()                    # idempotent teardown, never masked
3. IF self._cleanup:
   TRY: self._cache.sweep_untouched(self.cache_key)
   CATCH Exception: logger.warning("cache sweep failed on close", exc_info=True)
```

**Errors:** teardown errors propagate (the sweep is skipped — never masks); sweep errors are
swallowed and logged.

**Edge Cases:** `__exit__` delegates to `close()`; repeated close sweeps again and deletes
nothing new; `import logging` + the module logger `logging.getLogger("prettyplay")` are added.

## Cross-cutting Concerns

- **Error handling**: unchanged failure taxonomy. The sweep is the only new failure surface and
  it never raises: per-file guards (read/parse/delete) + the enumeration guard; the facade adds
  a belt-and-braces catch so no unexpected sweep error can fail a closing test. The `CachedStep`
  invariant surfaces as a construction-time `ValidationError` — a programming-error guard, not a
  runtime path.
- **Logging**: the library logger `prettyplay`. New records: one INFO per swept file
  (`cache file swept`, extras: filename, cache_key); WARNING for unreadable metadata
  (`cache sweep skipped a file with unreadable metadata`, extra: filename); WARNING for a
  per-file failure (`cache sweep failed on a file`, extra: filename); WARNING on the facade
  guard (`cache sweep failed on close`, with the traceback). Log content carries no secrets
  beyond file names and keys already on disk in metadata (the deferred ADR security question
  covers the value-bearing metadata itself).
- **Validation**: `render_step` validates authoring (unchanged, before any browser execution);
  `normalize_step_text` is the addressing key (NFC + trim); `StepCache.load` validates metadata
  by normalization comparison; the `CachedStep` model validator enforces the address/text
  invariant at construction.
- **Caching**: the repository cache itself is the subject — per-test working set by default;
  touched set in process memory per `StepCache` instance; `cleanup=False` is the persistence
  mode; no migration, first-sweep-cleans-legacy on compatible addresses, docs tell to purge.
- **Concurrency**: no new shared state across threads. The touched set lives on the per-test
  `StepCache`, touched only from the calling thread of the step cycle (the driver worker thread
  never touches the store). Concurrent tests keep separate stores — exactly today's isolation.

## Usages Analysis

### `conventions` (`.goga/usages/conventions.md`)
- **What it provides**: mandatory Python rules — relative imports, pydantic `kw_only` + empty
  defaults, Google docstrings, the `prettyplay` structured logging style, blank-line blocking,
  test structure (`tests/<pkg>/test_<module>.py`, `tmp_path` for file I/O, no mocks for pure
  logic), validation commands.
- **Where used**: every touched file and every new test.
- **Why chosen**: the project-wide contract for all cells.
- **How exactly**: `CachedStep.addressing_text: str = ""` kw_only; `import logging` +
  `getLogger("prettyplay")`; store tests use `tmp_path`; sweep tests monkeypatch only the
  filesystem edge (`Path.unlink`) where a failure must be forced.

### `jinja` (`.goga/usages/cooks/jinja.md`)
- **What it provides**: the Jinja environment contract (StrictUndefined, autoescape=False,
  from_string), the `{% var %}` extension mechanics, the namespaces, the missing-value policy —
  and the **addressing render** section: the second text of one render, tag-verbatim, one
  snapshot, raw-literal.
- **Where used**: `render_step`, `PreparedStep`, `_MarkedVarExtension`.
- **Why chosen**: the single source for everything Jinja in the renderer.
- **How exactly**: the one environment uses the capture extension with marked output;
  `_record` reuse keeps the documented authoring-error set and postprocessing builds both texts.

### `taxonomy` (Imports, `prettyplay/failures`)
- **What it provides**: the failure kinds and the structured render.
- **Where used**: the renderer's authoring errors (`PrettyplayError`); unchanged elsewhere.
- **Why chosen**: authoring errors stay in the existing base kind — no new failure kinds.

### `rendering`, `memory`, `validation` (Imports, `prettyplay/engine/renderer/.usages/`)
- **What they provide**: the render point contract, the publication semantics, the deterministic
  result acceptance.
- **Where used**: `engine`, `groups`, `steering`, facade annotations referencing them.
- **Why chosen / how**: `rendering` now documents the addressing text — the consumers
  (`executor` identity, recovery fresh identity) follow its example patterns verbatim.

### `generation`, `healing` (Imports, `prettyplay/engine/.usages/`)
- **What they provide**: the engine cycle contracts the executor delegates to.
- **Where used**: facade annotations; unchanged content — the addressing carry is internal to
  the engines.

### `recovery` (Imports, `prettyplay/engine/groups/.usages/`)
- **What it provides**: the group recovery cycle, memory and re-render semantics — including the
  new re-addressing bullet.
- **Where used**: facade annotations, `GroupRecovery`.

### `hooks` (Imports, `prettyplay/reporting`)
- **What it provides**: the `StepReporter`/`StepHooks` payload contract.
- **Where used**: `StepCache` events; **not** the sweep — deletions are log records only (the
  `on_cache_deleted` question is deferred by the ADR).

### Prompt practices (`system_prompt`, `cheat_sheet`, `group_framing`, `classification_prompt`, `compliance_prompt`, `group_diagnosis`)
- Unchanged by this topic; no prompt text references the addressing form (verified: the prompts
  carry the prepared instruction, which keeps its tag-stripped render — byte-identical).

## `.usages/` Update

### Cell: `prettyplay/cache`

#### Existing Files — Consistency
- **`addressing`** → `prettyplay/cache/.usages/addressing.md` — Status: current (rewritten by
  the apply stage per the plan). No additions needed.
- **`storage`** → `prettyplay/cache/.usages/storage.md` — Status: current after one post-apply
  fix. The "Read and write" example now passes
  `addressing_text="open the login page"` — the applied example without it violated the
  `CachedStep` invariant. Nothing else to change: the file-format sentence, the per-test working
  set section and the team workflow (purge-after-upgrade note) are in place.
- **`budgets`** → `prettyplay/cache/.usages/budgets.md` — Status: current (the fresh-budget
  bullet is in place). No additions.

#### New Files
- None — the working set belongs to the existing `storage` domain; the sweep example already
  lives there.

### Cell: `prettyplay/engine/renderer`

- **`rendering`** → `.usages/rendering.md` — Status: current (the addressing text section with
  the both-texts example). No additions.
- **`memory`**, **`validation`** — untouched, still consistent.

### Cell: `prettyplay/engine/groups`

- **`recovery`** → `.usages/recovery.md` — Status: current (the re-render re-addressing bullet).
  No additions.

### Cell: `prettyplay`

- **`lifecycle`** → `.usages/lifecycle.md` — Status: current (the "Cache lifecycle on close"
  section). No additions.
- **`steps`** → `.usages/steps.md` — Status: current (the "Cache addressing and replay" section,
  the Addressing preamble, the honest-context tail). No additions.

## Test Stack Trace

### General Setup

- Filesystem-touching tests use `tmp_path` exclusively (conventions); a `Config` with
  `cache_root=str(tmp_path)` builds a `StepCache` rooted in the test's own directory.
- A step file is composed by `StepCache.save` (or hand-written with the same header format:
  `STEP_TEXT`/`CACHE_KEY`/`STEP_TYPE`/`CREATED_AT` literals, the
  `\n# --- step code ---\n` sentinel, then the code).
- Log assertions use `caplog` with `caplog.at_level(logging.WARNING, logger="prettyplay")`.
- Pure-logic tests (normalization, render) run without mocks; engine/steering/recovery tests
  mock only the external boundaries (provider port, page facade) as the existing suites do.
- `StepMemory` seeded via `memory.publish({...})` before the render under test.

### Source File Registry

- `prettyplay/cache/text.py`, `models.py`, `store.py`, `budgets.py`
- `prettyplay/engine/renderer/render.py`
- `prettyplay/engine/generator.py`, `healer.py`
- `prettyplay/engine/steering/steering.py`
- `prettyplay/engine/groups/recovery.py`
- `prettyplay/executor.py`, `scenario.py`

---

### Positive Tests

#### `test_normalize_applies_nfc_and_trim_only`

**Setup**: none (pure function).

**Input**: `result = normalize_step_text("  Cafe\u0301 ")` — decomposed `e` plus combining
acute, leading and trailing spaces.

**Trace**:
```
normalize_step_text("  Cafe\u0301 ")
  → unicodedata.normalize("NFC", ...)   # "  Café "
  → .strip()                            # "Café"
```

**Assertions**:
```
assert result == "Café"
normalize_step_text(result) == result            # idempotent
normalize_step_text("Click Sign in") == "Click Sign in"   # case preserved
normalize_step_text("click  sign in") == "click  sign in" # internal whitespace preserved
```

**Sufficiency**: pins the verbatim rule — the dropped casefold/collapse and the NFC composition
are the addressing foundation every other test builds on.

#### `test_render_produces_both_texts_of_one_render`

**Setup**: `memory = StepMemory(); memory.publish({"name": "Book"})`.

**Input**: `render_step("For the item named {{ name }}, read its tags into {% var tags %}",
"action", memory, None)`.

**Trace**:
```
render_step(...)
  → snapshot {"name": "Book"}
  → one evaluation, then remove the capture marker for instruction:
      "For the item named Book, read its tags into "
  → declarations ["tags"]; action — no assertion error
  → replace the same capture marker with its tag for addressing:
      "For the item named Book, read its tags into {% var tags %}"
  → PreparedStep(instruction, addressing_text, inputs={}, declarations=["tags"])
```

**Assertions**:
```
prepared.instruction == "For the item named Book, read its tags into "
prepared.addressing_text == "For the item named Book, read its tags into {% var tags %}"
prepared.declarations == ["tags"]
```

**Sufficiency**: the core regression of the topic — the instruction stays byte-identical while
the addressing text carries the values and the tag; prevents any drift of either text.

#### `test_render_both_texts_observe_one_snapshot_and_branches`

**Setup**: `memory.publish({"name": "Book", "kind": "short"})`.

**Input**: `render_step("{% if kind == 'short' %}The {{ name }} briefly{% else %}The {{ name }}
at length{% endif %} — note {% var n %}", "action", memory, None)`.

**Trace**: the sole evaluation tests `kind == "short"` once, takes the then-branch and resolves
`{{ name }}` once to "Book"; marker postprocessing changes only the reached capture tag.

**Assertions**:
```
prepared.instruction == "The Book briefly — note "
prepared.addressing_text == "The Book briefly — note {% var n %}"
# and the inactive branch contributes nothing to either text:
"at length" not in prepared.addressing_text
```

**Sufficiency**: enforces the one-render invariant at the value and branch level.

#### `test_render_nondeterministic_filter_is_evaluated_once`

**Setup**: `memory = StepMemory()`; monkeypatch `jinja2.filters.random.choice` with a function
that increments `calls`, returns `"A"` on the first call and `"B"` on the second.

**Input**: `prepared = render_step("Open {{ ['A', 'B']|random }} {% var found %}",
"action", memory, None)`.

**Trace**: Jinja's built-in `random` filter calls the patched choice once (`calls == 1`) and emits the capture marker once;
postprocessing removes that marker from `instruction` and restores the capture tag in
`addressing_text` without reevaluating the filter.

**Assertions**:
```
assert calls == 1
assert prepared.instruction == "Open A "
assert prepared.addressing_text == "Open A {% var found %}"
assert prepared.declarations == ["found"]
```

**Sufficiency**: catches a second Jinja evaluation even when both passes share one snapshot;
prevents an instruction from being cached under a different rendered value.

#### `test_render_preserves_reached_capture_tag_source`

**Setup**: empty `StepMemory`; no call inputs; use the normal Jinja environment.

**Input**: `render_step("A{%var x%}{% if false %}{% var hidden %}{% endif %}B{% var  y %}",
"action", memory, None)`.

**Trace**: source lexing associates `x` with `{%var x%}` and `y` with `{% var  y %}`;
the false branch emits no marker for `hidden`; the one evaluation produces markers only for
`x` and `y`. Removing them gives `"AB"`; replacing them with their recorded source spans
gives `"A{%var x%}B{% var  y %}"`.

**Assertions**:
```
assert prepared.instruction == "AB"
assert prepared.addressing_text == "A{%var x%}B{% var  y %}"
assert prepared.declarations == ["x", "y"]
```

**Sufficiency**: prevents canonicalization of capture tags and inclusion of inactive tags in
cache addresses while preserving the existing instruction output.

#### `test_save_serializes_step_text_from_addressing_text`

**Setup**: `cache = StepCache(Config(cache_root=str(tmp_path)), None, StepReporter(hooks=[]))`;
`identity = StepIdentity(cache_key="k", step_type="action",
normalized_text=normalize_step_text("Open the item named Book"))`.

**Input**: `stored = cache.save(CachedStep(identity=identity,
addressing_text="Open the item named Book", code="def step(page):\n    ...",
created_at="2026-10-11"))`.

**Trace**:
```
save → _serialize: STEP_TEXT = "Open the item named Book" (from addressing_text)
     → temp write + os.replace → <sha256>.py in tmp_path
```

**Assertions**:
```
stored is True
text = (tmp_path / identity.filename).read_text()
text.startswith('STEP_TEXT = \'Open the item named Book\'')
round = cache.load(identity)
round.addressing_text == "Open the item named Book"
```

**Sufficiency**: the metadata sentence is the addressing text (verbatim, pre-normalization) and
the round trip restores it — the on-disk contract of the change.

#### `test_execute_builds_identity_from_addressing_text`

**Setup**: executor suite fixtures (mocked cache/engine collaborators, page stub);
`memory.publish({"name": "Book"})` on the executor's memory.

**Input**: `executor.execute("Open the item named {{ name }}", "action", page)`.

**Trace**:
```
execute → render_step → addressing_text "Open the item named Book"
        → normalize_step_text(...) → "Open the item named Book"
        → StepIdentity(cache_key, "action", "Open the item named Book")
        → cache.load(identity)  # mock records the identity
```

**Assertions**:
```
recorded_identity.normalized_text == "Open the item named Book"
recorded_identity.filename == StepIdentity(cache_key=..., step_type="action",
    normalized_text="Open the item named Book").filename
```

**Sufficiency**: the executor switch — a template addresses by its rendered value; prevents
regression to raw-sentence addressing (the cross-value replay bug).

#### `test_generate_stores_addressing_text_of_prepared`

**Setup**: generator suite fixtures (fake provider returning a fixed code, page stub, real
`StepCache` on `tmp_path`); `identity` built from
`normalize_step_text("Read the count into {% var n %}")`.

**Input**: `generator.generate(identity, prepared, "action", [], None, page, [], window,
memory)` with `prepared.addressing_text == "Read the count into {% var n %}"`.

**Trace**:
```
generate → candidate executes green → validates → gate empty
         → _store(identity, prepared.addressing_text, code)
         → CachedStep(addressing_text="Read the count into {% var n %}") → save
```

**Assertions**:
```
returned.addressing_text == "Read the count into {% var n %}"
returned.identity.normalized_text == normalize_step_text(returned.addressing_text)
file STEP_TEXT == "Read the count into {% var n %}"      # the tag stays in the metadata
```

**Sufficiency**: every caching path of the engines stores the render's verbatim addressing text
(the same helper serves `regenerate` and the funded path).

#### `test_row_identity_comes_from_fresh_render_addressing`

**Setup**: recovery suite fixtures (mocked generator, real budgets/cache); `group_traces` with a
template step `"Open the item named {{ name }}"` recorded with `identity` built when
`name == "Book"`; before recovery, `memory.publish({"name": "Film"})`.

**Input**: `recovery.recover(prompt, traces, prepared, "action", [], stale_identity, history,
page, window, memory)` with a recoverable diagnosis verdict naming that step.

**Trace**:
```
row loop → render_step("Open the item named {{ name }}", ..., memory, {})
         → fresh.addressing_text "Open the item named Film"
         → fresh_identity = StepIdentity(cache_key=stale.cache_key, step_type="action",
                                         normalized_text=normalize_step_text("Open the item named Film"))
         → refresh_healing(fresh_identity)
         → generator.regenerate(identity=fresh_identity, prepared=fresh, ...)
```

**Assertions**:
```
regenerate_identity.normalized_text == "Open the item named Film"
regenerate_identity.filename != stale_identity.filename
refresh_healing called exactly once, with regenerate_identity
```

**Sufficiency**: the fresh-identity contract of the row — regeneration, healing refresh and
write-back key on the re-rendered addressing text, never the stale trace identity.

#### `test_close_sweeps_untouched_entries_by_default`

**Setup**: `cfg = PrettyConfig(cache_root=str(tmp_path))`; hand-write an
untouched step file of `cache_key="login-flow"` into `tmp_path` (valid metadata, digest name),
plus a valid digest-named file of `cache_key="other-flow"`; save both filenames.

**Input**: `test = PrettyPlay("login-flow", cache_path=None, config=cfg); test.close()` — no
step ever executed (no page, no browser).

**Trace**:
```
close → page None → runtime.close() (nothing started)
      → cleanup True → sweep_untouched("login-flow")
      → file: digest name, CACHE_KEY matches, not touched → unlink + INFO log
```

**Assertions**:
```
assert not (tmp_path / filename).exists()
assert (tmp_path / foreign_filename).exists()  # the foreign-key neighbor survives
```

**Sufficiency**: the facade lifecycle — default close deletes the untouched working set filtered
by the key, without ever opening a browser.

#### `test_cleanup_false_keeps_every_file`

**Setup**: identical to the previous test.

**Input**: `PrettyPlay("login-flow", cleanup=False, config=cfg)`; `close()`.

**Trace**: `close → cleanup False → no sweep call` (assert via a counting `StepCache` stub or
by the file surviving).

**Assertions**: `(tmp_path / filename).exists()` after close; no `cache file swept` record in
`caplog`.

**Sufficiency**: the persistence mode of the committed-cache workflow — the switch must gate the
sweep and nothing else.

---

### Negative Tests

#### `test_normalize_keeps_case_and_whitespace_distinct`

**Setup**: none.

**Input**: `normalize_step_text("Click Sign in")`, `normalize_step_text("click  sign in ")`.

**Trace**: both texts pass through NFC+trim unchanged (except the trim).

**Assertions**:
```
normalize_step_text("Click Sign in") != normalize_step_text("click  sign in ")
StepIdentity(cache_key="k", step_type="action",
             normalized_text=normalize_step_text("Click Sign in")).filename
    != StepIdentity(cache_key="k", step_type="action",
                    normalized_text=normalize_step_text("click  sign in ")).filename
```

**Sufficiency**: the old documented merge is gone by decision — prevents reintroduction of the
casefold/collapse equivalence.

#### `test_load_rejects_mismatched_step_text`

**Setup**: a step file whose `STEP_TEXT` normalizes to something other than the identity's
`normalized_text` (same `CACHE_KEY`/`STEP_TYPE`, digest name of the identity).

**Input**: `cache.load(identity)`.

**Trace**: metadata parse OK → `normalize_step_text(STEP_TEXT) != identity.normalized_text` →
miss.

**Assertions**: `load(...) is None`; a later `sweep_untouched(key)` deletes the file (nothing
touched it).

**Sufficiency**: the address is the triple — a same-key file with a different sentence never
replays; also proves the miss touched nothing.

#### `test_cached_step_rejects_addressing_invariant_violation`

**Setup**: `identity = StepIdentity(cache_key="k", step_type="action",
normalized_text="open the login page")`.

**Input**: `CachedStep(identity=identity, addressing_text="Open the LOGIN page", code="...",
created_at="...")`.

**Trace**: the model validator compares
`normalize_step_text("Open the LOGIN page") != "open the login page"` → `ValueError` inside
pydantic validation.

**Assertions**: `pytest.raises(ValidationError)`.

**Sufficiency**: the invariant is mechanically enforced — no construction site can silently
store a mismatched pair.

#### `test_sweep_skips_unreadable_metadata_with_warning`

**Setup**: a digest-named file in scope whose content is not a parseable module
(`"not python !!!"`); `caplog` at WARNING on the `prettyplay` logger.

**Input**: `cache.sweep_untouched("k")`.

**Trace**: read OK → `ast.parse` raises `SyntaxError` → WARNING, skip.

**Assertions**: file still exists; exactly one WARNING record naming the filename; return value
does not include it.

**Sufficiency**: ownership of an unparseable file is unprovable in a shared root — the sweep
must skip loudly-but-safely, never delete and never raise.

#### `test_sweep_swallows_per_file_delete_failure`

**Setup**: an untouched key-matching file; `monkeypatch.setattr(pathlib.Path, "unlink",
raise_OSError)`.

**Input**: `cache.sweep_untouched("k")`.

**Trace**: metadata OK → key matches → not touched → `unlink` raises → WARNING → continue →
return `[]`.

**Assertions**: no exception; a WARNING record; `removed == []`.

**Sufficiency**: never-raises is a hard contract of the close path — a poisoned file must not
fail the closing test.

#### `test_close_sweep_never_masks_teardown_and_never_raises`

**Setup**: `monkeypatch` a `PrettyPlay` instance's `_cache.sweep_untouched` to raise
`RuntimeError`; and a second case where `runtime.close` raises.

**Input**: `test.close()` in both cases.

**Trace**: case A — teardown OK, sweep raises inside the guard → WARNING logged, close returns
normally. Case B — teardown raises → propagates; the sweep is never reached.

**Assertions**: case A — no exception, one WARNING with the traceback; case B — the teardown
error is the raised one.

**Sufficiency**: the guarded order — hygiene can neither fail nor mask the teardown.

---

### Edge Case Tests

#### `test_sweep_is_idempotent_and_repeat_close_safe`

**Setup**: one untouched file of the key, one touched (load it first).

**Input**: `removed1 = cache.sweep_untouched("k")`; `removed2 = cache.sweep_untouched("k")`.

**Trace**: first call deletes the untouched file; second call re-enumerates — the touched file
survives (in the set), the deleted one is gone.

**Assertions**: `removed1 == [untouched_name]`; `removed2 == []`; the touched file exists.

**Sufficiency**: idempotency backs the "repeated close sweeps again and deletes nothing new"
guarantee.

#### `test_sweep_ignores_non_digest_and_foreign_files`

**Setup**: in scope — `notes.py` (valid module, matching key, untouched), `.tmp-abc.py`
(garbage), a digest file of another key.

**Input**: `cache.sweep_untouched("k")`.

**Trace**: enumeration filters by `^[0-9a-f]{64}\.py$` → `notes.py` and the temp never parsed;
the foreign-key digest file parses, key differs → silent skip.

**Assertions**: all three files still exist; no WARNING records; `removed == []`.

**Sufficiency**: the sweep touches exactly the address space — foreign artifacts and other
tests' entries are invisible to it.

#### `test_touch_marks_only_successful_load_and_save`

**Setup**: real store on `tmp_path`: (a) a missing address; (b) a digest-named file with valid
parseable metadata and the target cache key, but `STEP_TEXT` mismatching its identity (a load
miss whose ownership the sweep can still prove); (c) a save skipped by temporarily forcing
`cache._writable = False`, then reset the probe; (d) a good load; (e) a good save.

**Input**: loads/saves per case, then one `sweep_untouched(key)`.

**Trace**: (a) misses; (b) parses but fails the address check; (c) skips without writing; only
(d) and (e) enter the touched set. The sweep parses (b), proves the key matches, deletes it,
and keeps (d)/(e).

**Assertions**: (b) gone; (d)/(e) present; `removed == [b_name]`.

**Sufficiency**: the success-only marking rule — miss, damage, skip and failure never touch;
also covers the legacy-sweep rider (untouched files of the key vanish on the first call).

#### `test_render_data_never_reparsed_in_addressing_text`

**Setup**: `memory.publish({"captured": "read {% var x %} then {{ y }}"})`.

**Input**: `render_step("Echo {{ captured }}", "action", memory, None)`.

**Trace**: the value substitutes as literal data in the one evaluation; no re-parsing, no declaration
recorded.

**Assertions**:
```
prepared.instruction == 'Echo read {% var x %} then {{ y }}'
prepared.addressing_text == prepared.instruction
prepared.declarations == []
```

**Sufficiency**: the data-is-not-a-template rule on the new text — an authoring injection via a
captured value must not change addressing or declarations.

#### `test_plain_sentence_and_identical_render_share_one_address`

**Setup**: `memory.publish({"name": "Book"})`.

**Input**: `render_step("Open the item named Book", "action", memory, None)` vs
`render_step("Open the item named {{ name }}", "action", memory, None)`.

**Trace**: both produce `addressing_text == "Open the item named Book"` → equal
`normalized_text` → equal filenames.

**Assertions**: the two `StepIdentity` filenames are equal.

**Sufficiency**: exact-text equality unifies plain and template sentences — the intentional
unification of the new addressing.

#### `test_strict_replay_self_preserving_committed_cache`

**Setup**: store-level: a pre-existing key-matching file; `load(identity)` returns it (a strict
replay's only cache interaction).

**Input**: `cache.sweep_untouched(key)` after the load.

**Trace**: `load(identity)` validates the matching metadata and adds `identity.filename` to this
store's touched set; the sweep sees the same key and filename, then keeps the file.

**Assertions**: the file exists; `removed == []`.

**Sufficiency**: the committed strict workflow's self-preservation — replayed entries are
loaded, hence touched; the docs' promise is backed by the store contract.

#### `test_heal_retains_render_addressing_text_not_old_metadata`

**Setup**: source `"Open {{ name }}"`; the saved step has `STEP_TEXT == "Open Book "` from
`name == "Book "`, identity `normalized_text == "Open Book"`, and failing code. Before replay,
memory changes to `name == "Book"`, producing `prepared.addressing_text == "Open Book"`.
`StepCache.load(identity)` succeeds because both metadata texts normalize to `"Open Book"`.
The provider classifies rot; use a real store on `tmp_path` and a generator whose next
candidate passes execution and validation.

**Input**: `healer.heal(step, error, prepared, "action", [], page, history, window, memory)`.

**Trace**: the executor builds the same normalized identity from the current render, so load
hits despite the differing verbatim metadata; failing replay enters `heal` →
`regenerate(identity=step.identity, prepared=prepared, ...)` →
`_store(identity, "Open Book", code)` → `save` replaces `STEP_TEXT` with `"Open Book"`.

**Assertions**: `healed.addressing_text == "Open Book"` and differs from the loaded step's
`"Open Book "`; the file's `STEP_TEXT == "Open Book"` and its digest filename is unchanged.

**Sufficiency**: healing must not resurrect an old cached entry's metadata text — the write-back
always carries the current render.

#### `test_write_back_carries_stuck_render_addressing_text`

**Setup**: steering fixtures — scripted stdin guidance + `y` approval, fake provider code that
executes green, real store on `tmp_path`.

**Input**: `steering.steer(failure, identity, prepared, "action", [], None, page, history,
memory)` with `identity` built from `prepared.addressing_text`.

**Trace**: green turn → validate → gate empty → publish →
`_write_back(prepared.instruction, prepared.addressing_text, identity, code)` → save (touches).

**Assertions**: the cached file's `STEP_TEXT == prepared.addressing_text`; a following
`sweep_untouched(key)` keeps it.

**Sufficiency**: the steering write-back joins the touched set through `save` and preserves the
stuck render's text verbatim in the metadata.

---

## Additional Instructions for the Implementation Agent

- **Implement in the dependency order** (cache → renderer → engine → steering → groups →
  facade); run `pytest tests/ -x` and `ruff check prettyplay/` after each cell.
- **Do not change**: `prettyplay/config` (no `cleanup` field anywhere — the switch is the
  constructor parameter only), the reporting hooks payload contract (no `on_cache_deleted`),
  `StepMemory`/`validate_step_result`, the prompt files, the failure taxonomy, `RunBudgets`
  signatures, `ScenarioStep`, the engine/steering/groups public signatures.
- **Keep the instruction render byte-identical**: removing only the capture markers from the
  one evaluated output must reproduce the prior instruction. The regression suite pins this.
- **The three recorded design decisions** (documented above, follow exactly): (1) both texts
  come from one Jinja evaluation with marked capture occurrences; (2) the addressing text keeps
  each reached capture tag's exact source span;
  (3) the sweep enumerates only digest-named files (`^[0-9a-f]{64}\.py$`).
- **Enforce the `CachedStep` invariant** with the pydantic model validator
  (`normalize_step_text(addressing_text) == identity.normalized_text`).
- **The touched set is per `StepCache` instance**, mutated only by `load`/`save` success paths;
  every other cell reaches it through those two methods — no direct set access anywhere outside
  `store.py`.
- **Docs riders (ride with the implementation)**: update `docs/reference/step-cache.md` —
  restate the addressing table (rendered sentence; NFC+trim; case and internal whitespace
  significant; capture tags verbatim; plain==identical render), replace the limitation passage
  with the addressing semantics, document `cleanup` and the per-test working set, add the
  purge-after-upgrade note. Update `docs/guides/writing-steps.md` accordingly. Then
  `grep -rn "casefold\|accepted limitation\|raw template sentence addresses\|template source"
  docs/` and fix any remaining page stating the old addressing (source wording: the updated
  `addressing.md`, `storage.md`, `lifecycle.md`, `steps.md`).
- **Existing test debt**: `tests/cache/test_text.py` asserts the old casefold/collapse behavior —
  rewrite it to the verbatim rule; `tests/cache/test_models.py`/`test_store.py` constructions
  need `addressing_text`; renderer/generator/healer/steering/recovery/executor/scenario suites
  gain the new assertions above. Keep every still-valid old assertion (the instruction values,
  atomicity, strict paths) — they are the regression backbone.
- **Log record names stay stable and lowercase** (`cache file swept`, `cache sweep skipped a
  file with unreadable metadata`, `cache sweep failed on a file`, `cache sweep failed on close`)
  with structured extras — machine-readable filtering per the conventions.
- **No new dependencies**; `pyproject.toml` is untouched.

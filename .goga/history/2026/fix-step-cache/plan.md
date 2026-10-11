# Plan: `fix-step-cache`

Result of compiling the verified design document (`.goga/history/2026/fix-step-cache/design.md`;
design review complete — 3/3 fixes applied; `goga lint` 12 cells / 0 errors) into a
ralphex-compatible execution plan. The scope is the **step-cache addressing** change: the cache
addresses steps by the rendered sentence (the addressing text) and cleans its working scope on
close.

---

## Purpose

After implementation, the package provides:

- **One verbatim normalization** — `normalize_step_text` applies Unicode NFC + trim to every
  addressing text and nothing else: case and internal whitespace are significant («Click Sign in»
  and «click  sign in » are different steps), template markers in a text are plain data.
- **Both texts of one render** — `render_step` produces, from ONE Jinja evaluation and one set of
  branch decisions, the tag-stripped instruction (byte-identical to today's render) and the
  addressing text (values substituted from the same snapshot, reached `{% var %}` tags kept
  verbatim as written).
- **Addressing by the rendered value** — the executor (and the recovery row) builds `StepIdentity`
  from `normalize_step_text(prepared.addressing_text)`; a plain sentence and a template producing
  the exact same text share one address; cross-value replay becomes impossible.
- **Verbatim metadata** — every newly constructed `CachedStep` carries the render's addressing
  text (`_store`, `_write_back`); the file's `STEP_TEXT` preserves it; `load` validates it by
  normalization comparison and restores it; a pydantic model validator makes a mismatched
  (identity, addressing_text) pair impossible to construct.
- **The per-test working set** — `StepCache` accumulates the touched set (successful loads and
  saves only) and gains `sweep_untouched(cache_key)`; `PrettyPlay` gains the keyword-only
  `cleanup=True` switch and the guarded close-time sweep — untouched files of the test's key are
  deleted on close by default; `cleanup=False` keeps every file (the committed-cache persistence
  mode).

The most important gaps between contract and code: every new entity above is absent; the current
normalization casefolds and collapses plain sentences; the render produces one text; `load`
compares `STEP_TEXT` by exact equality; `_store`/`_write_back` construct `CachedStep` without the
addressing text; the executor addresses by the raw sentence; the recovery refreshes healing and
writes back under stale trace identities; `close()` never sweeps.

**Strategy**: strict TDD per contract entity, one declared `location` per task, ordered by the
invariant-dependency graph (see `## Tasks` — cache → renderer → executor → groups → engine →
steering → facade, NOT the design's cell listing; the executor identity switch must precede the
engine threading because the `CachedStep` invariant is only satisfiable once identities are built
from the addressing text). Three one-line mechanical bridges (Task 2) keep the whole suite green
at every task boundary. Every coding task runs through the REPL cycle (Mandatory Rules). The six
changed `CODEMANIFEST` files are applied to the tree and lint-clean — they are **read-only** for
the implementation.

---

## Context

### Contract Surface

**Entity: `normalize_step_text(text: str) -> normalized: str`** (changed)
- Type: `function` (Routine)
- Declared `location`: `prettyplay/cache/text.py`
- Facade obligation: importable from `prettyplay.cache` (existing `__all__` entry)
- Algorithm (verbatim): 1. Apply Unicode NFC normalization; 2. Trim leading and trailing
  whitespace — nothing else
- Requirements: pure function (no I/O, no locale, deterministic on `text` alone); case and
  internal whitespace are significant — «Click Sign in» and «click  sign in » are different steps;
  exact-text equality unifies a plain sentence and a template producing the same text
- Constraints: no casefold, no internal whitespace collapse, no template-marker detection
- Deleted internals: `_WHITESPACE_RUN`, `_TEMPLATE_MARKERS` constants and the `re` import —
  implementation details, not contract entities

**Entity: `StepIdentity(cache_key: str, step_type: str, normalized_text: str)`** (context, code unchanged)
- Declared `location`: `prettyplay/cache/models.py`; facade: `prettyplay.cache`
- `normalized_text` is reworded to the addressing-text source: the rendered sentence after
  NFC + trim. The `filename` property (sha256 of the triple joined with `\x1f`) is unchanged —
  the address space derives from the triple exactly as today

**Entity: `CachedStep(identity: StepIdentity, addressing_text: str, code: str, created_at: str)`** (changed)
- Type: `class` (Entity, pydantic model)
- Declared `location`: `prettyplay/cache/models.py`; facade: `prettyplay.cache`
- New field/property `addressing_text -> str`: the verbatim rendered sentence before NFC and
  trim; the metadata sentence field carries it
- Requirement (the invariant): `normalize_step_text(addressing_text) == identity.normalized_text`
  for every newly built cached step; the load path may restore legacy files whose `STEP_TEXT`
  already contains the normalized sentence
- Decision — mechanical invariant enforcement: a pydantic `model_validator(mode="after")` raises
  `ValueError` (surfacing as `ValidationError`) on violation — a construction-time programming
  error, never a runtime path; import `normalize_step_text` from `.text` (no cycle: `text.py`
  imports stdlib only)

**Entity: `StepCache(config: Config, path: str | None, reporter: StepReporter | None)`** (changed)
- Type: `class` (Entity)
- Declared `location`: `prettyplay/cache/store.py`; facade: `prettyplay.cache`
- New internal state: `_touched: set[str]` — per instance, memory only; a successful load or save
  records the step's file name; a miss, a damaged entry, a skipped or failed write touch nothing
- `load(identity) -> step: CachedStep | None` (changed): validates the metadata by normalizing
  the `STEP_TEXT` value through `normalize_step_text` and comparing with
  `identity.normalized_text` (a mismatched sentence is a miss); restores the metadata value as
  `CachedStep.addressing_text`; a successful reconstruct records the file name in the touched set
- `save(step: CachedStep) -> stored: bool` (changed): `_serialize` writes `STEP_TEXT` from
  `step.addressing_text` (was `identity.normalized_text`); a stored write records the file name
  in the touched set; skipped/failed paths touch nothing; atomicity and the Windows retry are
  unchanged
- New method `sweep_untouched(cache_key: str) -> removed: list[str]`: deletes the untouched step
  files of one cache key in this store's scope — enumerate digest-named files
  (`^[0-9a-f]{64}\.py$`, sorted) only; unreadable metadata → WARNING + skip; a foreign
  `CACHE_KEY` → silent skip; touched files survive; per-file failure → WARNING + continue;
  one INFO record per deletion; never raises (per-file guards + the enumeration guard returning
  the partial `removed`)
- Constraints: deletions are log records only — no hook event (deferred contract decision); no
  address recomputation — membership tests use file names only; the method knows nothing of the
  `cleanup` switch
- Imported dependencies: `Config` from `prettyplay/config`, `StepReporter` from
  `prettyplay/reporting` (both untouched)

**Entity: `RunBudgets(generation_limit: int, healing_limit: int)`** (annotation rewording only)
- Declared `location`: `prettyplay/cache/budgets.py`; facade: `prettyplay.cache`
- The identity-key bullet is reworded in the manifest (budgets follow the addressing: a
  re-rendered identity draws a fresh budget) — already true in code by keying on `StepIdentity`;
  **no code change**

**Entity: `PreparedStep(instruction: str, addressing_text: str, inputs: dict[str, str], declarations: list[str])`** (changed)
- Type: `class` (Entity, pydantic model, frozen, kw_only, empty defaults)
- Declared `location`: `prettyplay/engine/renderer/render.py`; facade: `prettyplay.engine.renderer`
- New field/property `addressing_text -> str`: the same rendered sentence with actual values
  embedded and the reached capture tags kept verbatim; what the caller builds the cache identity
  from
- Requirement: both texts observe one snapshot and one set of branch decisions — they never
  disagree about a value or a branch

**Entity: `render_step(text: str, step_type: str, memory: StepMemory, vars: dict[str, str] | None) -> prepared: PreparedStep`** (changed)
- Type: `function` (Routine)
- Declared `location`: `prettyplay/engine/renderer/render.py`; facade: `prettyplay.engine.renderer`
- Algorithm (verbatim from the design): 1. snapshot ← `memory.snapshot()`; inputs ← vars or {};
  2. environment ← `Environment(autoescape=False, undefined=StrictUndefined, extensions=[capture
  extension])`; template ← `environment.from_string(text)`; 3. lex source tag spans in parse
  order; pass each parsed `{% var ... %}` its exact span; render exactly once against snapshot
  and inputs — each reached capture records its name and source span, then emits a unique opaque
  marker representing only that occurrence; 4. derive instruction by removing the emitted capture
  markers; derive addressing_text by replacing them with their original source spans — use unique
  unpredictable markers and verify each emitted marker appears exactly once in the completed
  output; an extra occurrence means ordinary data collided with a marker, so fail loudly before
  returning; 5. declarations ← list(extension.declarations); 6. IF step_type == "assertion" AND
  declarations: raise the existing authoring error; 7. return
  `PreparedStep(instruction, addressing_text, inputs, declarations)`
- `_MarkedVarExtension(VarExtension)`: `_record(name)` calls `super()._record(name)` (the same
  reserved/duplicate checks, the same declaration recording), creates a unique opaque marker for
  this reached occurrence, records its exact source span, returns the marker
- Errors: keep the existing `PrettyplayError` mapping for compilation, undefined names and
  capture authoring errors; a marker collision fails loudly before browser execution
- Edge cases: a plain sentence — `addressing_text == instruction == text`; a capture tag inside
  an inactive branch — absent from both texts and declarations; a memory value containing
  `{% var x %}` or `{{ x }}` — literal data in both texts; `{% raw %}` blocks — literal in both
  texts; tag formatting variations (`{%var x%}`, `{% var  x %}`) — the addressing text preserves
  each reached tag exactly as written, so the variants have different addresses
- The three recorded design decisions (follow exactly): (1) both texts come from one Jinja
  evaluation with marked capture occurrences — a common snapshot is insufficient because Jinja's
  standard `random` filter can change values and branch decisions between evaluations; (2) the
  addressing text keeps each reached capture tag's exact source span (lex the template source
  before compilation; raw-block contents are data, not capture tags); (3) the instruction after
  marker removal must equal the old single-render output for ordinary templates

**Entity: `StepGenerator.generate` / `regenerate`** (changed via the private `_store`)
- Declared `location`: `prettyplay/engine/generator.py`; facade: `prettyplay.engine`
- Public signatures unchanged (the engine contract fixes them); the param docstrings gain the
  contract sentence: the `addressing_text` of `prepared` is carried unchanged into every newly
  constructed `CachedStep`; the `normalized_text` of its `identity` is the NFC+trim normalization
  of that text
- `_store(identity, addressing_text, code)` — the single caching choke point; three call sites
  (`_generation_loop`, `_healing_loop`, `_funded_regeneration`) pass `prepared.addressing_text`
  unchanged — no normalization applied at storage (the file keeps the verbatim rendered sentence)

**Entity: `StepHealer.heal`** (no code change)
- The retention is structural: the healer passes the executor's `prepared` into `regenerate`, so
  the regenerated `CachedStep` carries the current render's addressing text — never the old
  entry's metadata text. Tested in Task 7

**Entity: `StepSteering.steer`** (changed via the private `_write_back`)
- Declared `location`: `prettyplay/engine/steering/steering.py`; facade:
  `prettyplay.engine.steering`
- The `identity` param is redefined: the address of the stuck step, built by the executor from
  the addressing text of the render product — the healed step is written back under it, and the
  successful write joins the test's touched set
- `_write_back(instruction, addressing_text, identity, code)` builds
  `CachedStep(identity=identity, addressing_text=addressing_text, code=code, created_at=...)`
  and saves; the call site (step 7 of `steer`) passes `prepared.instruction`,
  `prepared.addressing_text`, `identity`, `code`; the successful save marks the touched set
  inside `StepCache.save` — the steering cell holds no touched-set logic of its own

**Entity: `GroupRecovery.recover`** (changed row mechanics) and `GroupStepOutcome.identity` (reworded)
- Declared `location`: `prettyplay/engine/groups/recovery.py` (and the `identity` attribute
  docstring in `outcome.py`); facade: `prettyplay.engine.groups`
- Removed: the pre-row healing-counter refresh loop (`for _occurrence, trace in row:
  refresh_healing(trace.identity)`) — it refreshed under stale trace identities
- `_run_row`, per (occurrence, trace): declared delay; `fresh = render_step(trace.sentence,
  trace.step_type, memory, trace.vars)`; fresh identity
  `StepIdentity(cache_key=trace.identity.cache_key, step_type=trace.step_type,
  normalized_text=normalize_step_text(fresh.addressing_text))`; `refresh_healing(fresh_identity)`
  — once per cycle per row step; `regenerate(identity=fresh_identity, prepared=fresh, ...)`; a
  repeat failure updates the active failure to `fresh`, `trace.step_type`, `fresh_identity`, the
  grown row history; the local trace marks the occurrence failed preserving the freshly prepared
  instruction
- `trace.identity` keeps only the `cache_key` (the execution fact, never rewritten in the trace
  views); `_anchored_history` is unchanged; the import line gains `normalize_step_text`:
  `from ...cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text`

**Entity: `PrettyPlay(cache_key: str, cache_path: str | None, cleanup: bool, hooks: list[StepHooks] | None, config: PrettyConfig | None)`** (changed)
- Type: `class` (Entity — the facade's main object)
- Declared `location`: `prettyplay/scenario.py`; facade: `prettyplay`
- New constructor parameter `cleanup: bool` — keyword-only, default `True`, together with `hooks`
  and `config`; no config, env or pyproject surface for the switch (`prettyplay/config` stays
  untouched)
- `close()` algorithm (verbatim): 1. Stop the runtime teardown as today — idempotent;
  2. When cleanup is on, run the cache sweep with this test's cache_key — best-effort, guarded:
  any unexpected sweep error is caught and logged, never raised, never masking the teardown; a
  repeated close sweeps again and deletes nothing new; deletions are log records
- Implementation form (from the design): page close (if any) → `runtime.close()` (idempotent,
  `finally`) → when `self._cleanup`: `self._cache.sweep_untouched(self.cache_key)` wrapped in
  `try/except Exception: logger.warning("cache sweep failed on close", exc_info=True)`;
  `__exit__` delegates to `close()`

**Entity: `StepExecutor.execute`** (changed step 2 only)
- Declared `location`: `prettyplay/executor.py`; facade: `prettyplay`
- The switch: `identity = StepIdentity(cache_key=self.cache_key, step_type=step_type,
  normalized_text=normalize_step_text(prepared.addressing_text))` — was
  `normalize_step_text(step_text)`; everything downstream unchanged
- Docstrings: `step_text` loses "the addressing artifact" — it is "the template source; never
  rendered into a request"; the Requirement wording lands verbatim: "The addressing text of the
  render product builds the step address; the prepared instruction reaches every engine call;
  the verbatim NFC+trim normalization is an addressing key only"

### Interaction Diagram (verbatim from the design)

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

### Data Flows (verbatim from the design)

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

### Entity Dependencies (implementation order)

Within the change, the true dependency graph (leaves first; within each cell, files are
independent):

1. `prettyplay/cache` — `text.py` (normalization), `models.py` (`CachedStep.addressing_text` +
   the invariant validator), `store.py` (touched set, STEP_TEXT validation/serialization,
   `sweep_untouched`). Depends only on untouched `prettyplay/config` and `prettyplay/reporting`.
2. `prettyplay/engine/renderer` — `render.py` (`PreparedStep.addressing_text`, the addressing
   render). Depends only on untouched `prettyplay/failures`.
3. `prettyplay` `executor.py` — the identity switch. Depends on the renderer (the addressing-text
   source) and the cache.
4. `prettyplay/engine/groups` — `recovery.py` (fresh identity inside the row loop; the import
   gains `normalize_step_text`). Depends on the executor switch (consistent identities) and the
   renderer.
5. `prettyplay/engine` — `generator.py` (`_store` threading). Depends on the executor switch
   (the `CachedStep` invariant requires identity == normalize(addressing_text)). No signature
   changes.
6. `prettyplay/engine/steering` — `steering.py` (`_write_back` threading). No signature changes.
7. `prettyplay` `scenario.py` — the `cleanup` parameter and the guarded sweep. The true facade
   lands last: everything it composes already carries the new contract.

No import edges are added or removed. The groups → cache edge only gains `normalize_step_text`
in its Types payload; the facade → cache `sweep_untouched` call rides the existing edge.

**Ordering note (departs from the design's cell listing, with reason)**: the design lists
cache → renderer → engine → steering → groups → facade, and explicitly delegates implementation
order to the planning stage. The `CachedStep` invariant (Task 2) makes (identity,
addressing_text) consistency a hard construction-time constraint, so the engine/steering storage
threading is only possible after the executor builds identities from the addressing text; the
recovery row must pass fresh (identity, prepared) pairs before the threading replaces the
bridges. The order above keeps the entire test suite green at every task boundary; three
one-line mechanical bridges (Task 2) cover the window before the real threading lands.

### Re-exports

- `->PrettyConfig: {}` — source: `Config AS PrettyConfig` from `prettyplay/config`. Facade
  obligation: importable from `prettyplay`. Status: already in place — no work.
- `->BrowserConfig: {}` — source: `prettyplay/config`. Facade obligation: importable from
  `prettyplay`. Status: already in place — no work.
- `->StepHooks: {}` — source: `prettyplay/reporting`. Facade obligation: importable from
  `prettyplay`. Status: already in place — no work.

No new re-exports in this topic: every new name rides an existing facade export
(`StepCache.sweep_untouched` is a method of the exported class; `PreparedStep.addressing_text`
and `CachedStep.addressing_text` are fields of exported models; `normalize_step_text` is already
exported).

### Usages Context

- **`conventions`** (`.goga/usages/conventions.md`): mandatory Python rules — relative imports,
  pydantic `kw_only` + empty defaults, Google docstrings, the `prettyplay` structured logging
  style, blank-line blocking, the test structure (`tests/<pkg>/test_<module>.py`, `tmp_path` for
  file I/O, no mocks for pure logic), validation commands. Relevant to every task; extracted in
  full into `## Mandatory Rules`.
- **`jinja`** (`.goga/usages/cooks/jinja.md`): the Jinja environment contract (StrictUndefined,
  autoescape=False, from_string), the `{% var %}` extension mechanics, the namespaces, the
  missing-value policy — and the **Addressing render** section: `{{ ... }}` substituted from the
  same snapshot, active `{% var name %}` kept verbatim as written, inactive branches contribute
  nothing, substituted values are data (never reparsed), one snapshot invariant, `{% raw %}`
  literal in both texts. Relevant to Task 4 (renderer) — the single source for everything Jinja.

### Imported Usages

- **`taxonomy`** (from `prettyplay/failures`, `.usages/taxonomy.md`): the failure kinds and the
  structured render. Relevant to Task 4 — the renderer's authoring errors stay in the existing
  `PrettyplayError` base kind; no new failure kinds anywhere in this topic.
- **`hooks`** (from `prettyplay/reporting`, `.usages/hooks.md`): the `StepReporter`/`StepHooks`
  payload contract. Relevant to Task 3 — `StepCache` events (`on_cache_saved`, `on_cache_skipped`
  with their payloads) ride it; **not** the sweep — deletions are log records only (the
  `on_cache_deleted` question is deferred by the ADR).
- **`rendering`** (from `prettyplay/engine/renderer`, `.usages/rendering.md`): the render point
  contract including the addressing-text section; the consumers (executor identity, recovery
  fresh identity) follow its example patterns verbatim. Relevant to Tasks 4, 5.
- **`memory`**, **`validation`** (from `prettyplay/engine/renderer`): the publication semantics
  and the deterministic result acceptance. Relevant as unchanged context to Tasks 5, 11.
- **`generation`**, **`healing`** (from `prettyplay/engine`): the engine cycle contracts the
  executor delegates to. Relevant to Task 7 (the `_store` choke point serves all three paths);
  their content is unchanged — the addressing carry is internal to the engines.
- **`recovery`** (from `prettyplay/engine/groups`, `.usages/recovery.md`): the group recovery
  cycle, memory and re-render semantics — including the new re-addressing bullet. Relevant to
  Task 6.

### Local Usages

All cell `.usages/` files of this topic were rewritten/updated by the apply stage and confirmed
current by the design review — **no creation or update tasks are planned**:

- `prettyplay/cache/.usages/addressing.md` — full rewrite (the addressing-text identity).
  Status: current.
- `prettyplay/cache/.usages/storage.md` — the file-format sentence, the per-test working-set
  section, the team workflow; the post-apply consistency fix (the "Read and write" example
  passes `addressing_text="open the login page"`) is already in the tree. Status: current.
- `prettyplay/cache/.usages/budgets.md` — the fresh-budget bullet. Status: current.
- `prettyplay/engine/renderer/.usages/rendering.md` — the addressing-text section with the
  both-texts example. Status: current.
- `prettyplay/engine/groups/.usages/recovery.md` — the re-render re-addressing bullet.
  Status: current.
- `prettyplay/.usages/lifecycle.md` — the "Cache lifecycle on close" section. Status: current.
- `prettyplay/.usages/steps.md` — the "Cache addressing and replay" section, the addressing
  preamble, the honest-context tail. Status: current.

### External Dependencies

- **pydantic >= 2.7** — data models, the `model_validator` of Task 2 (external library type from
  `Usages`/`conventions`).
- **jinja2 >= 3.1** — the renderer: `Environment`, `StrictUndefined`, `Extension`, `Parser`,
  the lexer (token spans), `jinja2.filters` (the nondeterministic-filter test monkeypatches
  `random.choice`).
- **pytest / pytest-mock / pytest-cov** — the test stack (`[project.optional-dependencies]
  test`).
- **ruff >= 0.15.0** — the linter and the formatter (the project-convention gate).
- **No new dependencies** — `pyproject.toml` is untouched by this topic.

## Facts

- The six changed CODEMANIFEST files (`prettyplay/cache`, `prettyplay/engine/renderer`,
  `prettyplay/engine`, `prettyplay/engine/steering`, `prettyplay/engine/groups`, `prettyplay`)
  are applied to the worktree and lint-clean (`goga lint`: 12 cells, 0 errors). They are the
  source of truth and read-only.
- Python 3.10+; the project venv is `.venv/` — all commands run through it (`plain python` has
  no playwright).
- The library logger is the fixed `logging.getLogger("prettyplay")` — the established pattern in
  `executor.py`, `generator.py`, `recovery.py`, `reporter.py`, `page.py`, `settle.py`.
- Current `normalize_step_text` (`prettyplay/cache/text.py`): NFC → strip → template-marker
  split (`{{`, `{%`, `{#` → verbatim) → whitespace-run collapse → casefold. For template texts
  the new rule behaves identically; only plain sentences change.
- Current `CachedStep` (`prettyplay/cache/models.py`): `identity`, `code`, `created_at` — no
  `addressing_text`, no validator.
- Current `StepCache` (`prettyplay/cache/store.py`): `load` checks
  `fields["STEP_TEXT"] != identity.normalized_text` by exact equality and constructs
  `CachedStep(identity, code, created_at)`; `_serialize` writes
  `("STEP_TEXT", step.identity.normalized_text)`; no touched set; no sweep.
- Current `render_step` (`prettyplay/engine/renderer/render.py`): one text (the instruction),
  `VarExtension._record` returns `""`; `PreparedStep` has `instruction`, `inputs`,
  `declarations`.
- Current `_store` (`prettyplay/engine/generator.py:932`) signature is
  `_store(self, identity, code)`; three call sites at lines 474, 570, 868.
- Current `_write_back` (`prettyplay/engine/steering/steering.py:569`) signature is
  `_write_back(self, instruction, identity, code)`; the call site at line 371.
- Current `recovery.py` lines 268–270 hold the pre-row refresh loop under stale trace
  identities.
- Current `executor.py:175-178` builds the identity from `normalize_step_text(step_text)`.
- Current `scenario.py`: `__init__(cache_key, cache_path=None, *, hooks=None, config=None)` —
  no `cleanup`; `close()` = page close + `runtime.close()`, no sweep, no logger import.
- Existing test debt: `tests/cache/test_text.py` asserts the old casefold/collapse behavior;
  `CachedStep` constructions across the suites lack `addressing_text`;
  `tests/test_executor.py:763` (`test_hit_path_runs_cached_code_without_engines`) relies on the
  old case/space merge.
- Tests mirror the source tree (`tests/cache/`, `tests/engine/renderer/`, ...); every test
  directory has `__init__.py`; shared fixtures in `tests/conftest.py` build identities through
  `normalize_step_text` (self-consistent under the new rule).
- The `jinja` cook's "Addressing render" section and all cell `.usages/` rewrites are already in
  the tree (worktree modifications of the apply stage).
- Docs stating the old addressing: `docs/reference/step-cache.md`, `docs/guides/writing-steps.md`
  (plus any page the grep sweep finds).
- `pyproject.toml` ruff config: rule set E/W/F/I/N/UP/B/SIM/PL/PLR/C4/DTZ/PT/ARG/RUF/PTH/C90,
  mccabe `max-complexity = 10`, `line-length = 120`, `target-version = py310`; per-file ignores
  include `store.py` PTH105 (the atomic write is fixed to `os.replace`) and the prompt-file E501
  exemptions; `[tool.ruff.format]`: double quotes, spaces, LF, magic trailing comma.
- pytest config: `testpaths = ["tests"]`, `addopts = "-v --tb=short"`.

## Gap Analysis

- **Missing contract entities**: `StepCache.sweep_untouched` (absent);
  `PreparedStep.addressing_text` (absent); `CachedStep.addressing_text` + the invariant
  validator (absent); `PrettyPlay.cleanup` (absent).
- **Missing facade exposure**: none — every new name rides an existing export.
- **Incorrect `location` placement**: none — all entities live at their declared locations.
- **API mismatches**: `_store(identity, code)` and `_write_back(instruction, identity, code)`
  lack the addressing-text parameter; `PrettyPlay.__init__` lacks `cleanup`.
- **Behavioral mismatches**: the normalization pipeline (collapse + casefold + marker split vs
  NFC + trim); the single-text render vs both texts of one evaluation; `load`'s exact
  `STEP_TEXT` equality vs the normalization comparison; `save`'s `STEP_TEXT` source
  (`identity.normalized_text` vs `step.addressing_text`); the executor's identity source (raw
  sentence vs addressing text); the recovery's stale-identity refresh/write-back vs the fresh
  re-rendered identity; `close()` without the sweep.
- **Existing code that can be reused**: `VarExtension._record` (subclassed by
  `_MarkedVarExtension` — the reserved/duplicate checks and declaration recording are kept);
  `_parse_header` / `_serialize` / the atomic-write machinery (temp file, fsync, `os.replace`
  with the Windows retry); `SettleWindow`/`settle`; the existing suite fixtures
  (`ExecutorFixture`, `EventRecorder`, scripted-stdin steering fixtures, fake provider/page).
- **Test coverage gaps**: all 25 design scenarios are absent; the old tests assert removed
  behavior (casefold/collapse, the executor address merge).
- **Usages**: no gaps — all `.usages/` files are current (apply stage + the post-apply
  `storage.md` fix).
- **Docs**: `step-cache.md` and `writing-steps.md` state the old addressing and the old
  limitation passage.

---

## Mandatory Rules

Extracted from the project convention `.goga/usages/conventions.md` (referenced as
`conventions` by every CODEMANIFEST of this topic) and binding for **every task** — they govern
all development stages and every local commit. When rules conflict, the stack is: the applied
contract first, the package boundary and facade obligations second, these project conventions
next, target-language idioms last.

### Coding Style

1. Engineering principles: readable, explicit code; predictable, straightforward control flow;
   stable abstractions; operational stability and maintainability.
2. Python 3.10+ only. `pyproject.toml` is the configuration source. Execute all code within the
   virtualenv. Before Task 1, verify that `.venv/bin/python` is executable; an existing broken
   virtualenv (including a Python symlink whose target is absent) must be recreated with an
   available Python 3.10+ interpreter, just as a missing virtualenv must be created. Install
   the project and its existing test dependencies with `.venv/bin/python -m pip install -e
   '.[test]'`, then verify `.venv/bin/python -m pytest --version` succeeds. **This topic adds no
   dependencies; `pyproject.toml` stays untouched.**
3. Imports: relative for ALL intra-package references (`from .models import ...`,
   `from ..cache import ...`); absolute imports only for stdlib and third-party.
4. Data models: pydantic for all data models; `kw_only=True`; empty defaults for all fields
   (empty string, zero); `None` only for fields that represent the explicit absence of a value.
   Applied here: `CachedStep.addressing_text: str = ""`, `PreparedStep.addressing_text: str =
   ""`.
5. Logging: stdlib `logging`; this library's logger is the fixed
   `logging.getLogger("prettyplay")` (the established project pattern — a stable name for
   machine-readable filtering); structured contextual metadata via `extra={...}`; lowercase,
   concise, stable log event names; levels per the convention (INFO — lifecycle events and
   significant state transitions; WARNING — abnormal but recoverable situations). Log content
   carries no secrets beyond file names and keys already on disk in metadata. The four new
   records use the exact stable names from the design: `cache file swept` (INFO, extras:
   filename, cache_key), `cache sweep skipped a file with unreadable metadata` (WARNING, extra:
   filename), `cache sweep failed on a file` (WARNING, extra: filename), `cache sweep failed on
   close` (WARNING, with the traceback).
6. Code formatting: inside function and method bodies, logical blocks are separated by one
   blank line — variable initialization vs conditionals/loops, data preparation vs processing,
   processing vs the return.
7. Docstrings: ALL public functions, methods and classes, Google style; the first line is
   capitalized and ends with a period; `Args` when parameters exist, `Returns` when a value is
   returned, `Raises` for exceptions beyond built-ins; brief, professional, one point per
   comment.
8. Type hints are mandatory; signatures follow the applied contracts exactly — no `*args` /
   `**kwargs` (the DSL's arbitrary-arguments form excepted, unused here), no untyped `dict` /
   `list`.

### Test Writing

1. Tools: pytest (runner), ruff (lint and format of test code — the per-file test ignores are
   configured), pytest-cov (coverage). Test libraries live in
   `[project.optional-dependencies] test`.
2. Structure mirrors the source directly: `prettyplay/<pkg>/<module>.py` →
   `tests/<pkg>/test_<module>.py`; every test directory contains `__init__.py`; local fixtures
   in `tests/<pkg>/conftest.py`, shared fixtures in `tests/conftest.py`; integration tests
   covering multiple packages sit directly in `tests/`.
3. Naming: files `test_<module>.py`; functions `test_<what>_<scenario>`; grouping
   `class Test<Component>`; self-documenting names, minimal comments.
4. Test types: unit — every public function/method/class with the main scenario and typical
   data; edge cases — empty inputs (`None`, `""`, `[]`, `{}`), boundary values, invalid types,
   expected exceptions via `pytest.raises`; integration — only for interaction between
   modules/packages.
5. Boundary tests: `@pytest.mark.parametrize` with a table of values including each boundary.
6. Mocks — only at external boundaries: pure logic is tested without mocks; file I/O uses the
   `tmp_path` fixture exclusively; external dependencies are `mock.patch`ed at the import point;
   business-logic tests stay mock-free. Applied here: the sweep tests monkeypatch only the
   filesystem edge (`Path.unlink`) where a failure must be forced; the engine/steering/recovery
   suites mock only the provider port and the page facade, as the existing suites do.
7. Log assertions: `caplog.at_level(logging.WARNING, logger="prettyplay")`.
8. Contract-oriented classification enforced by the task workflow: **contract tests** — facade
   accessibility, API shape, signatures — written FIRST in each coding task, expected to fail;
   **logic tests** — positive, negative and edge behavior from the contract descriptions —
   written after implementation; **integration tests** — cross-entity scenarios, separate tasks.
   Integration tests never replace contract or logic tests.
9. Traceability: every test names the contract entity under test, the scenario and the expected
   behavior; keep every still-valid old assertion — the instruction values, atomicity, strict
   paths are the regression backbone.
10. Skip integration tests with unavailable external dependencies via `pytest.mark.skipif`.

### Lint and Format Enforcement

1. Linter: **ruff** with the project configuration in `pyproject.toml` — the configured rule
   set and per-file ignores stand as committed (including `store.py` PTH105 and the prompt-file
   E501 exemptions).
2. Formatter: **ruff format** (`[tool.ruff.format]`: double quotes, space indent, LF line
   endings, magic trailing comma kept).
3. Commands (all through the project virtualenv):
   - `.venv/bin/ruff check <paths>` — must exit with zero findings;
   - `.venv/bin/ruff format --check <paths>` — must report no needed reformatting; fix drift
     with `.venv/bin/ruff format <paths>`, never by hand.
4. **At every development stage**: the lint + format gate runs inside every task at every
   protocol-step boundary — the files touched so far must be clean before declaring any step
   (contract tests, code, logic tests, debugging) complete. The final LINT step of each task
   runs both commands on every file the task touched, source and tests alike.
5. **At every local commit**: immediately before creating any local commit (a per-task commit,
   the build agent's commit, any manual commit), run both commands on the tree
   (`prettyplay/ tests/`); a commit carrying lint findings or format drift is forbidden — fix
   the code first, then commit.
6. Never fix a finding by weakening configuration: `pyproject.toml` (ruff settings included) is
   untouched by this topic. A targeted `# noqa` with a reason comment is allowed only where the
   applied contract fixes the signature or structure (the existing
   `# noqa: PLR0913, PLR0917 — ...` pattern); a new global ignore is not.
7. If `ruff format --check` flags files this topic never touched, leave them unchanged and note
   them in the task report — this topic does not reformat the world.

### REPL Cycle

The development workflow of every task runs through REPL cycles inside the project virtualenv
(`.venv/bin/python`) — continuous interactive evaluation, hot reloading, and code migration to
source files:

1. **Baseline evaluation — REPL in, before editing**: start a fresh `.venv/bin/python` process
   from the repository root, import the touched module, run the design's scenario input against
   the current code and record the observed output. The pre-change behavior is the regression
   baseline.
2. **Continuous evaluation after every increment**: after each implementation step, re-evaluate
   the touched functions in a REPL against the design's trace inputs and check the intermediate
   values — the addressing text of a render, the serialized `STEP_TEXT` literal, a swept
   directory listing — not just the final pytest result.
3. **Hot reload discipline**: Python does not hot-reload edited modules — every re-evaluation
   happens in a fresh interpreter process (or an explicit `importlib.reload` inside one
   exploratory session); never verify against a stale interpreter after a file change. Keep the
   working directory at the repository root so imports resolve.
4. **Code migration to source files**: any snippet proven in the REPL migrates into the source
   file within the same task, adapted to the conventions (Google docstring, type hints,
   blank-line blocking, relative imports). No behavior may live only in a REPL transcript — the
   REPL is the scratchpad; the source tree is the single home of the logic.
5. **The REPL never replaces tests**: every REPL-verified expectation lands as a named pytest
   test in the task's logic-tests step; the suite stays the only acceptance gate.

Every coding task below carries explicit **REPL baseline** and **REPL check** checkboxes
implementing this cycle.

---

## Tasks

> **Package ordering rule**: coding tasks are completed in the listed order — the order follows
> the invariant-dependency graph (see `### Entity Dependencies`), and each task leaves the
> entire test suite green. Within each coding task, contract tests are written first (TDD
> workflow) and the REPL cycle runs through every step.

> **`CODEMANIFEST` files are read-only contract definitions.** The six applied manifests are
> the source of truth. If implementation does not match the contract, fix the implementation —
> never fix the contract.

> **Do not change (verbatim constraints from the design's Additional Instructions — they bind
> every task)**: `prettyplay/config` (no `cleanup` field anywhere — the switch is the
> constructor parameter only); the reporting hooks payload contract (no `on_cache_deleted` —
> deletions are log records only); `StepMemory`/`validate_step_result`; the prompt files
> (`system_prompt`, `cheat_sheet`, `group_framing`, `classification_prompt`,
> `group_diagnosis` — unchanged by this topic; no prompt text references the addressing form);
> the failure taxonomy; `RunBudgets` signatures; `ScenarioStep`; the
> engine/steering/groups public signatures. Keep the instruction render byte-identical —
> removing only the capture markers from the one evaluated output must reproduce the prior
> instruction; the regression suite pins this. The touched set is mutated only by the
> `load`/`save` success paths of `prettyplay/cache/store.py` — no direct set access anywhere
> outside that file. Log record names stay stable and lowercase with structured extras. No new
> dependencies; `pyproject.toml` is untouched.

### Task 1: The verbatim normalization of addressing texts (cache)

Rewrite `normalize_step_text` in `prettyplay/cache/text.py` to the one verbatim rule of the
applied contract. This routine is the foundation of the whole topic: the identity triple, the
`load` validation basis and (via the triple) the sha256 file name all derive from it. Today it
runs NFC → strip → template-marker split (`{{`, `{%`, `{#` → verbatim) → whitespace-run collapse
→ casefold; the contract replaces all of that with **Unicode NFC + trim, nothing else**. Case
and internal whitespace become significant — the old documented merge of «Click Sign in» /
«click  sign in » is gone **by decision**; a text containing `{{`, `{%`, `{#` is plain data (the
marker-detection branch is deleted). The `_WHITESPACE_RUN` and `_TEMPLATE_MARKERS` constants and
the `re` import are removed.

Design trace (verbatim): input — an addressing text: the rendered sentence from
`PreparedStep.addressing_text` (executor, recovery), the `STEP_TEXT` metadata value (load
validation), or a plain sentence addressing as itself → `unicodedata.normalize("NFC", text)`
(composes combining marks; idempotent) → `.strip()` (leading and trailing whitespace only; case
preserved, internal whitespace preserved, no template-marker detection) → output — the normalized
addressing text: the `normalized_text` of `StepIdentity`, the comparison basis of `load`, and
(via the triple) the sha256 file name. Edge cases: «Click Sign in» stays «Click Sign in»;
«click  sign in » → «click  sign in»; idempotent — `normalize(normalize(x)) == normalize(x)`.

**Usages relevant to this task:**
- `conventions`: pure stdlib function, no mocks in its tests; Google docstring; tests at
  `tests/cache/test_text.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/cache/test_text.py`; expected to fail at this stage): keep
  the still-valid ones — `normalize_step_text` importable from the `prettyplay.cache` facade;
  `inspect.signature` parameters are exactly `["text"]`; the result of a call is `str`; add —
  the module defines neither `_WHITESPACE_RUN` nor `_TEMPLATE_MARKERS` (the removed-policy
  assertion pattern)
- [x] **REPL baseline** (fresh `.venv/bin/python` from the repository root — record today's
  outputs before editing):
  `normalize_step_text("  Café ")` → `"café"`; `normalize_step_text("  Click   Sign In ")`
  → `"click sign in"`; `normalize_step_text("Read {{ name }} into {% var out %}")` → verbatim
  unchanged
- [x] **Code**: replace the body with `unicodedata.normalize("NFC", text).strip()`; delete
  `_WHITESPACE_RUN`, `_TEMPLATE_MARKERS` and the `re` import; rewrite the docstring per the
  contract annotation ("Normalize an addressing text for identity and addressing — one verbatim
  rule for every text"; `text` — the addressing text of the step, the rendered sentence, a plain
  sentence addresses as itself; Returns — the normalized addressing text)
- [x] **REPL check** (fresh process — never a stale interpreter): re-evaluate the baseline
  inputs — `"  Café "` → `"Café"`, `"  Click   Sign In "` → `"Click   Sign In"` (case and
  the internal run preserved), the template text unchanged, and
  `normalize_step_text(normalize_step_text(x)) == normalize_step_text(x)`; migrate the verified
  body into the source file
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/cache/test_text.py -q` — the
  contract tests pass
- [x] **Logic tests** (rewrite the suite to the verbatim rule; keep every still-valid
  assertion — empty and whitespace-only inputs return `""`, distinct sentences stay distinct):
  - `test_normalize_applies_nfc_and_trim_only` (design scenario, verbatim):
    `normalize_step_text("  Café ") == "Café"`; idempotency;
    `normalize_step_text("Click Sign in") == "Click Sign in"` (case preserved);
    `normalize_step_text("click  sign in") == "click  sign in"` (internal whitespace preserved)
  - `test_normalize_keeps_case_and_whitespace_distinct` (design scenario, verbatim):
    `normalize_step_text("Click Sign in") != normalize_step_text("click  sign in ")`; the two
    `StepIdentity(cache_key="k", step_type="action", normalized_text=...)` filenames differ
  - delete the template-split class and the collapse/casefold pipeline tests — the old
    documented merge is gone by decision
- [x] **Registered mechanical breakage** (test debt, not implementation): in
  `tests/test_executor.py`, `test_hit_path_runs_cached_code_without_engines` saves under
  `normalized_text="открыть страницу"` and executes `"  Открыть   страницу "` relying on the old
  merge — align the saved identity with the executed sentence's new normalization (keep the
  hit-path intent: cached code runs, no engine calls); sweep the suite for any other
  old-merge reliance (a saved sentence executed in different case/spacing) and align the same
  way
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation code until all
  tests pass (test-code changes happen only in the registered rewrite steps above, never to
  make a failing assertion pass)
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.cache import
  normalize_step_text; assert normalize_step_text('  Café ') == 'Café'; assert
  normalize_step_text('Click Sign in') != normalize_step_text('click  sign in ')"` — facade,
  API shape and the verbatim behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/text.py tests/cache/test_text.py
  tests/test_executor.py` and `.venv/bin/ruff format --check` on the same files — zero
  findings; both gates must also pass immediately before any local commit of this task

### Task 2: `CachedStep.addressing_text` and the construction-time invariant (cache)

Extend `CachedStep` in `prettyplay/cache/models.py` with the `addressing_text` field and the
mechanical invariant validator. The field is the step's addressing text — the verbatim rendered
sentence before NFC and trim; the metadata sentence field of the cache file carries it
(`code: str = ""`, `created_at: str = ""` keep their empty defaults per `conventions`;
`addressing_text: str = ""`). The invariant —
`normalize_step_text(addressing_text) == identity.normalized_text` for every newly built cached
step — is enforced by a pydantic `model_validator(mode="after")` raising `ValueError` (surfacing
as `ValidationError`): a construction-time programming error, never a runtime path; every
documented path (store load, generator `_store`, steering `_write_back`) satisfies it, as
traced in the design. Import `normalize_step_text` from `.text` — no cycle (`text.py` imports
stdlib only).

**Cascade contract (mandatory reading)**: once the validator lands, EVERY `CachedStep(...)`
construction without a matching `addressing_text` fails. Three one-line mechanical bridges keep
the whole suite green until the real threading lands (each marked with a brief comment naming
the replacing task):

- `prettyplay/cache/store.py` `load` — temporarily pass
  `addressing_text=fields["STEP_TEXT"]` (the existing exact check already guarantees
  `STEP_TEXT == normalized_text`, so the invariant holds); replaced by Task 3.
- `prettyplay/engine/generator.py` `_store` — temporarily pass
  `addressing_text=identity.normalized_text` (preserves today's `STEP_TEXT` content); replaced
  by Task 7.
- `prettyplay/engine/steering/steering.py` `_write_back` — temporarily pass
  `addressing_text=identity.normalized_text`; replaced by Task 8.

**Usages relevant to this task:**
- `conventions`: pydantic `kw_only=True` + empty defaults; Google docstrings (the
  `addressing_text` attribute documents "the verbatim rendered sentence before NFC and trim;
  the metadata sentence field carries it"); relative import `from .text import
  normalize_step_text`; tests at `tests/cache/test_models.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/cache/test_models.py`; expected to fail at this stage):
  `CachedStep.__init__` parameters are exactly `identity`, `addressing_text`, `code`,
  `created_at`; positional construction is rejected (kw_only — the existing type-ignore test
  stays valid); the constructed model exposes the four attributes
- [x] **REPL baseline**: in a fresh `.venv/bin/python` REPL, construct
  `CachedStep(identity=StepIdentity(cache_key="k", step_type="action",
  normalized_text="open the login page"), code="...", created_at="...")` — it succeeds today
  (no addressing_text); this is the pre-change baseline that must start failing
- [x] **Code**: add `addressing_text: str = ""` to `CachedStep`; add the
  `model_validator(mode="after")` enforcing
  `normalize_step_text(self.addressing_text) == self.identity.normalized_text` (raise
  `ValueError` with a concise lowercase message naming the violation); extend the class and
  attribute docstrings per the contract
- [x] **Code (bridges)**: add the three one-line mechanical bridges listed in the cascade
  contract, each with a brief comment naming the replacing task
- [x] **Code (mechanical sweep)**: every `CachedStep(` construction in the test tree gains a
  consistent `addressing_text=` (each fixture's value normalizes to its identity's
  `normalized_text`). The files constructing `CachedStep` directly (verified by
  `grep -rln "CachedStep(" tests/`): `tests/cache/test_models.py`,
  `tests/cache/test_store.py`, `tests/engine/groups/test_recovery.py`,
  `tests/engine/test_healer.py`, `tests/test_executor.py`, `tests/test_scenario.py`,
  `tests/test_integration.py`, `tests/test_groups_integration.py` — re-run the grep at
  implementation time and cover whatever it lists
- [x] **REPL check** (fresh process): construct a valid pair — `addressing_text=" Open the
  login page "` with `identity.normalized_text="Open the login page"` (the NFC+trim
  relationship: the verbatim sentence with surrounding whitespace against its normalization);
  construct the mismatched pair `"Open the LOGIN page"` against
  `normalized_text="open the login page"` and observe the `ValidationError`;
  confirm the exception type is a `ValueError` subclass
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/cache/test_models.py -q` —
  the contract tests pass
- [x] **Logic tests**:
  - `test_cached_step_rejects_addressing_invariant_violation` (design scenario, verbatim):
    `identity = StepIdentity(cache_key="k", step_type="action",
    normalized_text="open the login page")`;
    `CachedStep(identity=identity, addressing_text="Open the LOGIN page", code="...",
    created_at="...")` raises `ValidationError` (the model validator compares
    `normalize_step_text("Open the LOGIN page") != "open the login page"`)
  - the legacy restore passes: `addressing_text` equal to the old normalized sentence
    (`normalize(addressing_text) == normalized_text`) constructs successfully — the load path
    restores legacy files whose `STEP_TEXT` already contains the normalized sentence
  - keep the still-valid `StepIdentity` tests (filename determinism, the separator) and the
    CachedStep defaults tests (adjusted to the matching pair)
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — the bridges and the mechanical
  sweep keep it green; fix implementation code until all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.cache import
  CachedStep, StepIdentity; s = CachedStep(identity=StepIdentity(cache_key='k',
  step_type='action', normalized_text='open the login page'), addressing_text='open the login
  page', code='x', created_at='2026-10-11'); assert s.addressing_text == 'open the login
  page'"` — facade, API shape and the invariant intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/models.py prettyplay/cache/store.py
  prettyplay/engine/generator.py prettyplay/engine/steering/steering.py tests/` and
  `.venv/bin/ruff format --check` on the same paths — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 3: The store lifecycle — touched set, STEP_TEXT contract, `sweep_untouched` (cache)

Implement the `StepCache` changes in `prettyplay/cache/store.py`: the per-test working-set
lifecycle. `_touched: set[str]` is per instance, memory only, mutated exclusively by the
`load`/`save` success paths (no direct set access anywhere outside `store.py`). `load`
validates the metadata by normalization comparison and restores the saved value as the
addressing text. `save` serializes `STEP_TEXT` from `step.addressing_text`. The new
`sweep_untouched(cache_key)` deletes the untouched digest-named files of the key in scope.

Algorithm (verbatim from the design; changes only):

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

Implementation notes (from the design): module logger `logging.getLogger("prettyplay")`; the
digest-name pattern `^[0-9a-f]{64}\.py$` as a module constant; the `_serialize` header tuple
becomes `("STEP_TEXT", step.addressing_text)`. The Task 2 bridge in `load` is replaced by the
real change. Edge cases: idempotency (survivors are touched, foreign-key and unreadable files; a
repeat call is a no-op); a fresh test that never wrote — the scope directory may not exist →
`[]`; foreign non-digest files (`notes.py`, stale `.tmp-*.py`) never enumerated, never logged;
the touched set is per `StepCache` instance — the facade's per-test composition gives one store
(and one set) per test; the sweep knows nothing of the `cleanup` switch.

**Usages relevant to this task:**
- `conventions`: `tmp_path` for every filesystem-touching test; the structured logging style
  (lowercase stable event names, `extra=` metadata, the `prettyplay` logger); monkeypatch only
  the filesystem edge (`Path.unlink`) where a failure must be forced.
- `hooks` (from Imports, `prettyplay/reporting`): the `on_cache_saved` / `on_cache_skipped`
  payload contract — unchanged; **not** the sweep — deletions are log records only (the
  `on_cache_deleted` question is deferred by the ADR).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/cache/test_store.py`; expected to fail at this stage):
  `StepCache` declares the callable `sweep_untouched`;
  `inspect.signature(StepCache.sweep_untouched)` parameters are exactly `["cache_key"]`;
  `load`/`save` signatures are unchanged; the constructor signature is unchanged
- [x] **REPL baseline** (fresh `.venv/bin/python`): build a real store on a temp directory
  (`Config(cache_root=...)`), save a step, read the file — observe the `STEP_TEXT` literal
  (today the bridge's normalized form) and a `load` roundtrip
- [x] **Code**: add `self._touched: set[str] = set()` to `__init__` (extend the Attributes
  docstring); in `load`, replace the exact `STEP_TEXT` equality with
  `normalize_step_text(fields["STEP_TEXT"]) != identity.normalized_text` (a mismatched sentence
  is a miss), construct `CachedStep(identity=identity, addressing_text=fields["STEP_TEXT"],
  code=code, created_at=fields["CREATED_AT"])` (replacing the Task 2 bridge) and add
  `self._touched.add(identity.filename)` on the success path only; import `normalize_step_text`
  from `.text`
- [x] **Code**: in `save`, `_serialize` writes `("STEP_TEXT", step.addressing_text)` and the
  success path adds `self._touched.add(step.identity.filename)` after the atomic replace
- [x] **Code**: add the module logger and the digest-name constant; implement
  `sweep_untouched` exactly per the algorithm above (sorted enumeration; the per-file guards;
  the enumeration guard returning the partial `removed`; the stable log record names)
- [x] **REPL check** (fresh process, temp directory): save two steps of one key and one of
  another key; `load` one of them; call `sweep_untouched(key)` and list the directory — the
  untouched file of the key is gone, the loaded one and the foreign-key file survive; the
  return value names the deleted file; a second call returns `[]`; migrate the verified
  behavior into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/cache/test_store.py -q` —
  the contract tests pass
- [x] **Logic tests** (design scenarios, verbatim; every filesystem fixture on `tmp_path`):
  - `test_save_serializes_step_text_from_addressing_text`: `stored is True`; the file text
    starts with `STEP_TEXT = 'Open the item named Book'`; a `load` roundtrip restores
    `round.addressing_text == "Open the item named Book"` — the metadata sentence is the
    addressing text, verbatim, pre-normalization
  - `test_load_rejects_mismatched_step_text`: a file whose `STEP_TEXT` normalizes to something
    other than the identity's `normalized_text` (same `CACHE_KEY`/`STEP_TYPE`, digest name of
    the identity) — `load` returns `None`; a later `sweep_untouched(key)` deletes the file
    (nothing touched it)
  - `test_touch_marks_only_successful_load_and_save`: (a) a missing address; (b) a digest-named
    file with valid parseable metadata and the target key but a `STEP_TEXT` mismatching its
    identity; (c) a save skipped by temporarily forcing `cache._writable = False` (then reset
    the probe); (d) a good load; (e) a good save — the sweep deletes (b) and keeps (d)/(e);
    `removed == [b_name]`
  - `test_strict_replay_self_preserving_committed_cache`: a pre-existing key-matching file;
    `load(identity)` returns it; a following `sweep_untouched(key)` keeps the file — replayed
    entries are loaded, hence touched
  - `test_sweep_skips_unreadable_metadata_with_warning`: a digest-named file whose content is
    not a parseable module (`"not python !!!"`); `caplog` at WARNING on the `prettyplay`
    logger — the file still exists, exactly one WARNING record naming the filename, the return
    value does not include it
  - `test_sweep_swallows_per_file_delete_failure`: an untouched key-matching file;
    `monkeypatch.setattr(pathlib.Path, "unlink", raise_OSError)` — no exception, a WARNING
    record, `removed == []`
  - `test_sweep_is_idempotent_and_repeat_close_safe`: one untouched file of the key, one
    touched (load it first) — `removed1 == [untouched_name]`, `removed2 == []`, the touched
    file exists
  - `test_sweep_ignores_non_digest_and_foreign_files`: in scope — `notes.py` (valid module,
    matching key, untouched), `.tmp-abc.py` (garbage), a digest file of another key — all three
    still exist, no WARNING records, `removed == []`
  - keep every still-valid old assertion: the roundtrip, top-level imports, the legacy
    sentinel load, read-only skip, busy-target retry, no temp files left behind, path
    validation, the event payloads
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation code until all
  tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.cache import
  StepCache; assert callable(StepCache.sweep_untouched)"` plus the facade importability of the
  whole cache surface — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/cache/store.py tests/cache/test_store.py` and
  `.venv/bin/ruff format --check` on the same files — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 4: Both texts of one render (renderer)

Implement the addressing render in `prettyplay/engine/renderer/render.py`: `PreparedStep` gains
`addressing_text`, and `render_step` produces both texts of ONE evaluation. Lex the source once
to collect the exact `{% var ... %}` spans in parse order (Jinja's lexer preserves whitespace in
token values and does not expose raw-block contents as tag tokens); compile with the capture
extension, each parsed tag receiving its matching source span; evaluate exactly once — each
reached capture emits a unique opaque marker and records its name and source span; derive the
instruction by removing the markers and the addressing text by replacing them with their exact
source spans; guard marker collisions with ordinary rendered data and fail before browser
execution rather than silently altering either string. Substituted values are never parsed as
templates. The instruction must stay **byte-identical** to the old render for ordinary
templates — the regression suite pins this.

`_MarkedVarExtension(VarExtension)`:

```
_record(name):
1. super()._record(name)   # the same reserved/duplicate checks, the same declaration recording
2. create a unique opaque marker for this reached occurrence; record its exact source span
3. return the marker; postprocessing removes it for instruction and restores the tag for addressing
```

Errors: keep the existing `PrettyplayError` mapping for compilation, undefined names and
capture authoring errors; a marker collision fails loudly before browser execution — it must
never silently produce a mismatched instruction and address.

**Usages relevant to this task:**
- `jinja`: the environment contract (StrictUndefined, autoescape=False, from_string), the
  `{% var %}` extension mechanics, the namespaces, the missing-value policy — and the
  "Addressing render" section: `{{ ... }}` substituted from the same snapshot, active
  `{% var name %}` kept verbatim as written, inactive branches contribute nothing, substituted
  values are data, one snapshot invariant, `{% raw %}` literal in both texts.
- `taxonomy` (from Imports, `prettyplay/failures`): the authoring errors stay in the existing
  `PrettyplayError` base kind.
- `conventions`: pydantic frozen kw_only model with empty defaults; pure-logic tests without
  mocks; tests at `tests/engine/renderer/test_render.py`.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/engine/renderer/test_render.py`; expected to fail at this
  stage): `PreparedStep.__init__` parameters are `instruction`, `addressing_text`, `inputs`,
  `declarations` (kw_only, frozen, empty defaults); the constructed model exposes
  `addressing_text`; the `render_step` signature is unchanged; `has_declarations` is unchanged
- [x] **REPL baseline** (fresh `.venv/bin/python`): with
  `memory.publish({"name": "Book"})`, render
  `"For the item named {{ name }}, read its tags into {% var tags %}"` — record today's single
  instruction `"For the item named Book, read its tags into "` and `declarations == ["tags"]`;
  this instruction value is the byte-identity baseline
- [x] **Code**: add `addressing_text: str = ""` to `PreparedStep` with the contract docstring
  ("the addressing text: the rendered sentence with actual values embedded and the reached
  capture tags kept verbatim; what the caller builds the cache identity from")
- [x] **Code**: implement `_MarkedVarExtension(VarExtension)` per the algorithm above; lex the
  source tag spans in parse order before compilation and associate each parsed capture with its
  raw span; render exactly once against the snapshot and inputs; derive both texts; use unique
  unpredictable markers and verify each emitted marker appears exactly once in the completed
  output — an extra occurrence means ordinary data collided with a marker: raise the loud
  `PrettyplayError` before returning
- [x] **Code**: keep the existing compile/render error mapping around the sole evaluation and
  the assertion-with-declarations authoring error; return
  `PreparedStep(instruction=instruction, addressing_text=addressing_text, inputs=inputs,
  declarations=declarations)`
- [x] **REPL check** (fresh process): re-evaluate the baseline template — the instruction is
  byte-identical and `addressing_text == "For the item named Book, read its tags into
  {% var tags %}"`; evaluate the formatting variants
  `"A{%var x%}{% if false %}{% var hidden %}{% endif %}B{% var  y %}"` — instruction `"AB"`,
  addressing `"A{%var x%}B{% var  y %}"`; migrate the verified derivation into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/engine/renderer/ -q` — the
  contract tests pass
- [x] **Logic tests** (design scenarios, verbatim):
  - `test_render_produces_both_texts_of_one_render`: with `memory.publish({"name": "Book"})` —
    `prepared.instruction == "For the item named Book, read its tags into "`;
    `prepared.addressing_text == "For the item named Book, read its tags into {% var tags %}"`;
    `prepared.declarations == ["tags"]`
  - `test_render_both_texts_observe_one_snapshot_and_branches`: with
    `memory.publish({"name": "Book", "kind": "short"})` on
    `"{% if kind == 'short' %}The {{ name }} briefly{% else %}The {{ name }} at length{% endif %} — note {% var n %}"`
    — `prepared.instruction == "The Book briefly — note "`;
    `prepared.addressing_text == "The Book briefly — note {% var n %}"`; the inactive branch
    contributes nothing (`"at length" not in prepared.addressing_text`)
  - `test_render_nondeterministic_filter_is_evaluated_once`: monkeypatch
    `jinja2.filters.random.choice` with a counter returning `"A"` then `"B"` on
    `"Open {{ ['A', 'B']|random }} {% var found %}"` — `calls == 1`;
    `prepared.instruction == "Open A "`; `prepared.addressing_text == "Open A {% var found %}"`;
    `prepared.declarations == ["found"]`
  - `test_render_preserves_reached_capture_tag_source`: empty memory, no inputs, on
    `"A{%var x%}{% if false %}{% var hidden %}{% endif %}B{% var  y %}"` —
    `prepared.instruction == "AB"`;
    `prepared.addressing_text == "A{%var x%}B{% var  y %}"`;
    `prepared.declarations == ["x", "y"]`
  - `test_render_data_never_reparsed_in_addressing_text`: with
    `memory.publish({"captured": "read {% var x %} then {{ y }}"})` on
    `"Echo {{ captured }}"` —
    `prepared.instruction == 'Echo read {% var x %} then {{ y }}'`;
    `prepared.addressing_text == prepared.instruction`; `prepared.declarations == []`
  - `test_plain_sentence_and_identical_render_share_one_address`: with
    `memory.publish({"name": "Book"})`, render `"Open the item named Book"` and
    `"Open the item named {{ name }}"` — both `addressing_text ==
    "Open the item named Book"`; the two `StepIdentity` filenames built from them are equal
  - keep every existing render assertion — the instruction values, the authoring errors
    (malformed template, duplicate capture, the reserved `vars` name, an unavailable name, an
    assertion declaring captures): the regression backbone
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — the additive field with an empty
  default keeps the other suites green; fix implementation code until all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.engine.renderer
  import PreparedStep, render_step"` — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/renderer/render.py
  tests/engine/renderer/test_render.py` and `.venv/bin/ruff format --check` on the same files —
  zero findings; both gates must also pass immediately before any local commit of this task

### Task 5: The executor builds the identity from the addressing text (root)

Switch the identity construction in `prettyplay/executor.py` (`StepExecutor.execute`, step 2 of
the contract). The change is one construction:

```
2. prepared ← render_step(step_text, step_type, memory, vars)     # unchanged
   identity ← StepIdentity(cache_key=self.cache_key, step_type=step_type,
                           normalized_text=normalize_step_text(prepared.addressing_text))
   # was normalize_step_text(step_text); everything downstream unchanged
```

A plain sentence addresses as itself (its addressing text equals the sentence); a template
addresses by its rendered values — cross-value replay becomes impossible because different
values produce different `normalized_text`, hence different file names. Everything downstream
(hit/miss, heal, recover, steer, the scenario record, the group trace) is unchanged and already
receives `identity` and `prepared`. The `load` validation runs inside the store — the executor
is unaware. Docstring updates: the `step_text` parameter loses "the addressing artifact" — it is
"the template source; never rendered into a request"; the Requirement wording lands verbatim:
"The addressing text of the render product builds the step address; the prepared instruction
reaches every engine call; the verbatim NFC+trim normalization is an addressing key only".

**Usages relevant to this task:**
- `rendering` (from Imports, `prettyplay/engine/renderer`): the render point contract — the
  executor identity follows its example patterns verbatim (the addressing text of the render
  product establishes the cache identity).
- `conventions`: the docstring updates keep Google style; executor tests mock only the external
  boundaries (cache/engine collaborators, page stub) as the existing suite does.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/test_executor.py`; expected to hold, not fail — the
  signatures are unchanged): `execute` parameters and the `StepExecutor` constructor signature
  are unchanged (the regression backbone — the switch is behavioral, not structural)
- [x] **REPL baseline** (fresh `.venv/bin/python`): with
  `memory.publish({"name": "Book"})`, render
  `"Open the item named {{ name }}"` and build both identities by hand — today's
  `normalize_step_text(step_text)` gives the raw-template address; the product's
  `addressing_text` gives `"Open the item named Book"`; record both
- [x] **Code**: apply the switch (the single identity construction); update the `step_text`
  param docstring and add the Requirement wording verbatim
- [x] **REPL check** (fresh process): re-evaluate — for the template, the identity built from
  `prepared.addressing_text` has `normalized_text == "Open the item named Book"`; for a plain
  sentence the identity equals the sentence's own normalization; migrate into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/test_executor.py -q`
- [x] **Logic tests**:
  - `test_execute_builds_identity_from_addressing_text` (design scenario, verbatim): executor
    suite fixtures (mocked cache/engine collaborators, page stub);
    `memory.publish({"name": "Book"})` on the executor's memory; execute
    `"Open the item named {{ name }}"` — the mocked cache records
    `recorded_identity.normalized_text == "Open the item named Book"` and
    `recorded_identity.filename == StepIdentity(cache_key=..., step_type="action",
    normalized_text="Open the item named Book").filename`
  - update the identity expectations of the template-step executor tests (the rendered value,
    not the raw sentence); keep every still-valid old assertion — the hit/miss paths, the heal
    delegation, the strict paths, the event payloads, the scenario records
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — the generator/steering bridges
  (Task 2) keep the engine paths green; fix implementation code until all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay import
  StepExecutor"` and the execute signature check — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/executor.py tests/test_executor.py` and
  `.venv/bin/ruff format --check` on the same files — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 6: The fresh row identity of the group recovery (groups)

Rework the row mechanics in `prettyplay/engine/groups/recovery.py`. **Delete the pre-row
healing-counter refresh loop** (`for _occurrence, trace in row:
self._budgets.refresh_healing(trace.identity)` — today at lines 268–270): it refreshed under
stale trace identities — a defect under the new addressing, because a re-rendered step draws its
fresh budget under the fresh identity, not the trace one. Inside `_run_row`, per
`(occurrence, trace)`:

```
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

The import line gains `normalize_step_text`: `from ...cache import CachedStep, RunBudgets,
StepCache, StepIdentity, normalize_step_text`. `trace.identity` keeps only the `cache_key` (the
execution fact, never rewritten in the trace views); `_anchored_history` is unchanged (record 0
anchors the code the test actually executed, loaded under the execution-time identity); the
group traces and scenario records the caller stores are never rewritten. Errors: unchanged — a
re-render authoring error of a row step stays that step's loud failure (it raises out of
`render_step` before any identity work). The `GroupStepOutcome.identity` attribute docstring in
`prettyplay/engine/groups/outcome.py` is aligned with the applied contract: the execution fact.

**Usages relevant to this task:**
- `recovery` (from Imports, `prettyplay/engine/groups`): the group recovery cycle, memory and
  re-render semantics — including the re-addressing bullet.
- `conventions`: recovery tests mock only the generator and keep real budgets/cache; Google
  docstrings.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/engine/groups/test_recovery.py`; expected to hold): the
  `recover` signature is unchanged; `GroupStepOutcome` shape is unchanged — the change is
  behavioral (the identity the row regenerates under)
- [x] **REPL baseline** (fresh `.venv/bin/python`): with `memory.publish({"name": "Book"})`
  render a template, then with `memory.publish({"name": "Film"})` re-render it — build both
  identities by hand and confirm the filenames differ; this is the stale-vs-fresh relationship
  the row must respect
- [x] **Code**: add `normalize_step_text` to the cache import; delete the pre-row refresh loop;
  implement the row steps per the algorithm above (the fresh render, the fresh identity keyed
  by `trace.identity.cache_key`, the in-loop `refresh_healing`, the regeneration under the
  fresh identity, the failure update to the fresh facts)
- [x] **Code**: align the `GroupStepOutcome.identity` attribute docstring in `outcome.py` with
  the applied contract (the execution fact)
- [x] **REPL check** (fresh process): re-evaluate the stale-vs-fresh construction — the fresh
  identity derives from the re-rendered addressing text and differs from the trace identity;
  migrate into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/engine/groups/ -q`
- [x] **Logic tests**:
  - `test_row_identity_comes_from_fresh_render_addressing` (design scenario, verbatim):
    recovery suite fixtures (mocked generator, real budgets/cache); `group_traces` with a
    template step `"Open the item named {{ name }}"` recorded with the identity built when
    `name == "Book"`; before recovery, `memory.publish({"name": "Film"})`; call `recover` with
    a recoverable diagnosis verdict naming that step —
    `regenerate_identity.normalized_text == "Open the item named Film"`;
    `regenerate_identity.filename != stale_identity.filename`;
    `refresh_healing` called exactly once, with `regenerate_identity`
  - keep the existing recovery assertions — the verdict mapping, the row composition, the
    anti-masking, the cycle cap, the local-view updates
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — the generator bridge keeps the
  real-regeneration paths green; fix implementation code until all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.engine.groups import
  GroupRecovery, GroupStepOutcome"` — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/groups/recovery.py
  prettyplay/engine/groups/outcome.py tests/engine/groups/test_recovery.py` and
  `.venv/bin/ruff format --check` on the same files — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 7: The caching choke point carries the render's addressing text (engine)

Thread the addressing text through `_store` in `prettyplay/engine/generator.py` — the single
caching choke point (three call sites: `_generation_loop`, `_healing_loop`,
`_funded_regeneration` — each holds `prepared`):

```
_store(identity, addressing_text, code):
1. step ← CachedStep(identity=identity, addressing_text=addressing_text, code=code,
                     created_at=date.today().isoformat())
2. self._cache.save(step); return step
```

The call sites pass `prepared.addressing_text` **unchanged** — no normalization applied at
storage (the file keeps the verbatim rendered sentence); the identity's `normalized_text` is
the NFC+trim of that same text (the executor/recovery built it so) — the model invariant holds
by construction. The param docstrings of `generate`/`regenerate` gain the contract sentence:
"The `addressing_text` of `prepared` is carried unchanged into every newly constructed
`CachedStep`; the `normalized_text` of its `identity` is the NFC+trim normalization of that
text." The Task 2 bridge in `_store` is removed. **The healer needs no code change** — the
retention is structural: `heal` passes the executor's `prepared` into `regenerate`; nothing
reads the loaded step's metadata for storage.

**Usages relevant to this task:**
- `generation`, `healing` (from Imports, `prettyplay/engine`): the engine cycles — the choke
  point serves the generation loop, the healing loop and the funded regeneration alike.
- `conventions`: generator tests use a fake provider and a real `StepCache` on `tmp_path`;
  Google docstrings; the `# noqa: PLR0913, PLR0917` signature exemptions stand (the engine
  contract fixes the signatures).

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/engine/test_generator.py`; expected to hold): the
  `generate`/`regenerate` signatures are unchanged — the engine contract fixes them
- [x] **REPL baseline** (fresh `.venv/bin/python`): with a fake provider returning a fixed
  green code and a real store on a temp directory, run one `generate` — observe today's saved
  `STEP_TEXT` literal (the bridge's normalized form) and the returned step
- [x] **Code**: change `_store` to the `(identity, addressing_text, code)` signature and the
  construction above; update the three call sites to pass `prepared.addressing_text`; remove
  the Task 2 bridge; add the contract sentence to the `generate`/`regenerate` `prepared` param
  docstrings
- [x] **REPL check** (fresh process): re-run the baseline generation — the returned
  `CachedStep.addressing_text` equals the prepared product's text; the file's `STEP_TEXT`
  keeps the capture tag verbatim; a `load` roundtrip restores it; migrate into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/engine/test_generator.py
  -q`
- [x] **Logic tests**:
  - `test_generate_stores_addressing_text_of_prepared` (design scenario, verbatim): generator
    suite fixtures (fake provider returning a fixed code, page stub, real `StepCache` on
    `tmp_path`); `identity` built from
    `normalize_step_text("Read the count into {% var n %}")`;
    `generator.generate(identity, prepared, "action", [], None, page, [], window, memory)` with
    `prepared.addressing_text == "Read the count into {% var n %}"` —
    `returned.addressing_text == "Read the count into {% var n %}"`;
    `returned.identity.normalized_text ==
    normalize_step_text(returned.addressing_text)`;
    the file's `STEP_TEXT == "Read the count into {% var n %}"` (the tag stays in the metadata)
  - `test_heal_retains_render_addressing_text_not_old_metadata` (design scenario, verbatim; in
    `tests/engine/test_healer.py`): source `"Open {{ name }}"`; the saved step has
    `STEP_TEXT == "Open Book "` from `name == "Book "`, identity
    `normalized_text == "Open Book"`, and failing code; before replay, memory changes to
    `name == "Book"`, producing `prepared.addressing_text == "Open Book"`;
    `StepCache.load(identity)` succeeds because both metadata texts normalize to
    `"Open Book"`; the provider classifies rot; a real store on `tmp_path` and a generator
    whose next candidate passes execution and validation; call
    `healer.heal(step, error, prepared, "action", [], page, history, window, memory)` —
    `healed.addressing_text == "Open Book"` and differs from the loaded step's
    `"Open Book "`; the file's `STEP_TEXT == "Open Book"` and its digest filename is unchanged
  - update the generator/healer fixtures: every `PreparedStep` reaching `_store` now carries an
    `addressing_text` consistent with its identity (the empty default would violate the
    invariant once the threading lands)
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — the executor (Task 5) and the
  recovery (Task 6) already pass consistent (identity, prepared) pairs, so the threading holds
  everywhere; fix implementation code until all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.engine import
  StepGenerator, StepHealer"` — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/generator.py
  prettyplay/engine/healer.py tests/engine/test_generator.py tests/engine/test_healer.py` and
  `.venv/bin/ruff format --check` on the same files — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 8: The steering write-back carries the stuck render's addressing text (steering)

Thread the addressing text through `_write_back` in
`prettyplay/engine/steering/steering.py`:

```
_write_back(instruction, addressing_text, identity, code):
1. step ← CachedStep(identity=identity, addressing_text=addressing_text, code=code,
                     created_at=date.today().isoformat())
2. stored ← self._cache.save(step)          # a stored write joins the touched set
3. emit on_healed (instruction); the console line reflects `stored`
4. return step
```

The call site (step 7 of `steer`, today at line 371) passes `prepared.instruction`,
`prepared.addressing_text`, `identity`, `code`. The `STEP_TEXT` metadata preserves the stuck
render's addressing text verbatim; `normalize(addressing_text) == identity.normalized_text`
holds (one executor-built identity, one prepared product); the successful save marks the
touched set inside `StepCache.save` — the steering cell holds no touched-set logic of its own.
The `identity` param docstring of `steer` is redefined per the applied contract: the address of
the stuck step, built by the executor from the addressing text of the render product. The Task
2 bridge is removed. Errors/edge cases: none new — the save is best-effort as today; on decline
nothing is written, nothing touched.

**Usages relevant to this task:**
- `conventions`: steering tests use scripted stdin guidance + `y` approval, a fake provider and
  a real store on `tmp_path`; Google docstrings; the prompt-constant E501 exemptions stand.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [x] **Contract tests** (in `tests/engine/steering/test_steering.py`; expected to hold): the
  `steer` signature is unchanged — the change is the private helper and the docstring
- [x] **REPL baseline** (fresh `.venv/bin/python`): run one scripted write-back today (guidance
  line + `y` approval, fake provider, real store on a temp directory) — observe the saved
  `STEP_TEXT` (the bridge's normalized form)
- [x] **Code**: change `_write_back` to the `(instruction, addressing_text, identity, code)`
  signature and the algorithm above; update the call site; remove the Task 2 bridge; redefine
  the `identity` param docstring of `steer`
- [x] **REPL check** (fresh process): re-run the scripted write-back — the cached file's
  `STEP_TEXT` equals the prepared product's addressing text verbatim; a following sweep of the
  key keeps the file; migrate into the source
- [x] **Interface verification**: `.venv/bin/python -m pytest tests/engine/steering/ -q`
- [x] **Logic tests**:
  - `test_write_back_carries_stuck_render_addressing_text` (design scenario, verbatim):
    steering fixtures — scripted stdin guidance + `y` approval, fake provider code that
    executes green, real store on `tmp_path`; call
    `steering.steer(failure, identity, prepared, "action", [], None, page, history, memory)`
    with `identity` built from `prepared.addressing_text` — the cached file's
    `STEP_TEXT == prepared.addressing_text`; a following `sweep_untouched(key)` keeps it
  - keep the existing steering assertions — the banner, the rejected-turn history, the
    gate-blocked paths, the decline path
- [x] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation code until
  all tests pass
- [x] **Contract re-verification**: `.venv/bin/python -c "from prettyplay.engine.steering
  import StepSteering"` — facade, API shape and behavior intact
- [x] **Lint**: `.venv/bin/ruff check prettyplay/engine/steering/steering.py
  tests/engine/steering/test_steering.py` and `.venv/bin/ruff format --check` on the same
  files — zero findings; both gates must also pass immediately before any local commit of this
  task

### Task 9: The cleanup switch and the guarded close-time sweep (root)

Implement the cache lifecycle on the facade in `prettyplay/scenario.py`. The constructor gains
`cleanup: bool` — keyword-only, default `True`, grouped with `hooks` and `config`; no config,
env or pyproject surface for the switch (`prettyplay/config` stays untouched). Algorithm
(verbatim from the design):

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

Errors: teardown errors propagate (the sweep is skipped — never masks); sweep errors are
swallowed and logged. Edge cases: `__exit__` delegates to `close()`; a repeated close re-runs
the idempotent sweep and deletes nothing new; `import logging` + the module logger
`logging.getLogger("prettyplay")` are added; construction stays cheap — nothing sweeps at
construction.

**Usages relevant to this task:**
- `conventions`: the structured logging style (the facade guard WARNING with the traceback);
  `tmp_path` for the filesystem fixtures; Google docstrings; keyword-only parameter grouping.
- `lifecycle` (local usage, `prettyplay/.usages/lifecycle.md`): the "Cache lifecycle on close"
  section documents the exact behavior being implemented — the task's docstrings follow it.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Contract tests** (in `tests/test_scenario.py`; expected to fail at this stage):
  `inspect.signature(PrettyPlay.__init__)` parameters are `cache_key`, `cache_path`, `cleanup`
  (keyword-only), `hooks` (keyword-only), `config` (keyword-only); `cleanup` defaults to
  `True`; `close` is declared; the constructor accepts `cleanup=False`
- [ ] **REPL baseline** (fresh `.venv/bin/python`): hand-write an untouched digest-named step
  file of `cache_key="login-flow"` into a temp cache root; construct
  `PrettyPlay("login-flow", config=...)` and `close()` — the file survives today (no sweep);
  this is the pre-change baseline
- [ ] **Code**: add the `cleanup` parameter and `self._cleanup`; implement the `close`
  algorithm above (the teardown-then-guarded-sweep order); add `import logging` and the module
  logger; extend the `__init__`/`close` docstrings per the contract (the `cleanup` param: the
  cache lifecycle switch — `True`: close deletes the untouched step files of this test's cache
  key in its cache scope; `False`: keeps every file, the persistence mode of the committed-cache
  workflow)
- [ ] **REPL check** (fresh process, temp cache root): re-run the baseline — the default close
  sweeps the untouched file; `cleanup=False` keeps it; a sweep forced to raise (monkeypatched
  stub) is swallowed with a WARNING and `close()` returns normally; migrate into the source
- [ ] **Interface verification**: `.venv/bin/python -m pytest tests/test_scenario.py -q`
- [ ] **Logic tests** (design scenarios, verbatim):
  - `test_close_sweeps_untouched_entries_by_default`: `cfg = PrettyConfig(cache_root=str(
    tmp_path))`; hand-write an untouched step file of `cache_key="login-flow"` into `tmp_path`
    (valid metadata, digest name), plus a valid digest-named file of `cache_key="other-flow"`;
    save both filenames; `test = PrettyPlay("login-flow", cache_path=None, config=cfg);
    test.close()` — no step ever executed (no page, no browser);
    `not (tmp_path / filename).exists()` and `(tmp_path / foreign_filename).exists()` (the
    foreign-key neighbor survives)
  - `test_cleanup_false_keeps_every_file`: identical setup;
    `PrettyPlay("login-flow", cleanup=False, config=cfg)`; `close()` —
    `(tmp_path / filename).exists()` after close; no `cache file swept` record in `caplog`
  - `test_close_sweep_never_masks_teardown_and_never_raises`: case A — monkeypatch a
    `PrettyPlay` instance's `_cache.sweep_untouched` to raise `RuntimeError`: `close()`
    returns normally, one WARNING with the traceback; case B — `runtime.close` raises: the
    teardown error is the raised one, the sweep is never reached
  - keep the existing scenario assertions — the composition, the lazy page, the context
    manager, the traceback folding, the hooks seeding
- [ ] **Registered breakage sweep** (test debt, not implementation): grep the scenario and
  integration suites for tests that call `close()` and then assert cache files exist — align
  them with the default sweep (the test's own loaded/saved files survive; hand-written
  untouched fixtures are swept — use `cleanup=False` or pre-touched fixtures where persistence
  is the point of the test)
- [ ] **Debugging**: `.venv/bin/python -m pytest tests/ -x` — fix implementation code until
  all tests pass (test-code changes happen only in the registered sweep above)
- [ ] **Contract re-verification**: `.venv/bin/python -c "from prettyplay import PrettyPlay;
  import inspect; assert 'cleanup' in inspect.signature(PrettyPlay.__init__).parameters"` —
  facade, API shape and behavior intact
- [ ] **Lint**: `.venv/bin/ruff check prettyplay/scenario.py tests/test_scenario.py` and
  `.venv/bin/ruff format --check` on the same files — zero findings; both gates must also pass
  immediately before any local commit of this task

### Task 10: Documentation riders (docs)

Update the user-facing documentation to the new addressing semantics. Source wording: the
updated `addressing.md`, `storage.md`, `lifecycle.md`, `steps.md` (all current in the tree).
This is a documentation task — no TDD cycle; the REPL verifies that every documented example
reproduces exactly.

**Usages relevant to this task:**
- `conventions`: professional concise technical language; examples must be accurate.
- The applied `.usages/` files (listed above) — the authoritative wording of the addressing
  semantics, the file format and the close lifecycle.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **Code**: update `docs/reference/step-cache.md` — restate the addressing table (the
  rendered sentence; NFC + trim; case and internal whitespace significant; capture tags
  verbatim; a plain sentence and an identical render share one address), replace the old
  limitation passage with the addressing semantics, document `cleanup` and the per-test working
  set (the default sweep on close; `cleanup=False` as the committed-cache persistence mode),
  add the purge-after-upgrade note (no library version field invalidates the cache; purge
  manually after an upgrade)
- [ ] **Code**: update `docs/guides/writing-steps.md` accordingly (the addressing preamble —
  templates address by their rendered values; the honest-context tail)
- [ ] **REPL check** (fresh `.venv/bin/python`): run every code example and expected output
  shown in the updated pages through the REPL — the documented behavior must reproduce exactly
  (the normalization examples, the render examples, the `cleanup` constructor call)
- [ ] **Validation**: `grep -rn "casefold\|accepted limitation\|raw template sentence
  addresses\|template source" docs/` — fix every remaining page stating the old addressing;
  only intentional matches remain (e.g. the new "template source" phrasing of the render
  input)
- [ ] **Lint**: none for prose; keep the markdown structure of the existing docs (headings,
  code fences, tables)

### Task 11: Integration tests for the wired addressing lifecycle

Wire-level verification of the addressing flows across cells in `tests/test_integration.py` —
the cross-entity scenarios of the design's Flows 1–6 through the wired objects (fake provider,
fake page, real `StepCache` on `tmp_path`, real executor/engines/facade). These tests
complement, never replace, the per-entity contract and logic tests of Tasks 1–9.

**Usages relevant to this task:**
- `conventions`: integration tests exercising real wiring with fakes only at the external
  boundaries (fake provider, fake page); `tmp_path` for the cache root; shared fixtures in
  `tests/conftest.py`.
- `rendering`, `generation`, `healing`, `recovery` (imported usages): the cycles the wired flow
  delegates to — their documented semantics hold end-to-end.

**CRITICAL: `CODEMANIFEST` files — read-only contract definitions. Do NOT modify them. If implementation does not match the contract, fix the implementation — never fix the contract.**

- [ ] **REPL check** (fresh `.venv/bin/python`): drive one wired scenario by hand before
  writing the test — a fake provider, a real store on a temp directory, one template step
  through the executor — and observe the generated file's name (the rendered-value identity)
  and its `STEP_TEXT` (the verbatim addressing text)
- [ ] **Code**: add the wired template-addressing scenario — a template step with a memory
  value generates; the file is named by the rendered-value identity and carries
  `STEP_TEXT` = the verbatim addressing text (the capture tag included); the identical second
  execution replays without a second provider call; a changed memory value produces a
  different address and a new generation (cross-value replay is impossible)
- [ ] **Code**: add the unification scenario — a plain sentence and a template producing the
  exact same text share one address end-to-end (the second form replays the first form's cache
  entry)
- [ ] **Code**: add the close-lifecycle scenario — after executed steps, the default `close()`
  keeps the test's working set (the loaded/saved files survive) and sweeps an untouched
  hand-written entry of the same key; `cleanup=False` keeps every file
- [ ] **Run validation**: `.venv/bin/python -m pytest tests/test_integration.py
  tests/test_groups_integration.py -q` — all pass
- [ ] **Run the full suite**: `.venv/bin/python -m pytest tests/ -x` — all pass
- [ ] **Lint**: `.venv/bin/ruff check tests/test_integration.py
  tests/test_groups_integration.py` and `.venv/bin/ruff format --check` on the same files —
  zero findings; both gates must also pass immediately before any local commit of this task

---

## Validation Commands

- `.venv/bin/python -m pytest tests/ -x`: Run all tests (the design's verify command — all
  commands run in the project virtualenv)
- `.venv/bin/ruff check prettyplay/ tests/`: Lint check — zero findings (the pyproject rule set)
- `.venv/bin/ruff format --check prettyplay/ tests/`: Format check — ruff format is the project
  formatter; fix drift with `.venv/bin/ruff format`, never by hand (pre-existing drift in files
  this topic never touched is reported, not fixed)
- `.venv/bin/python -c "from prettyplay import PrettyPlay; from prettyplay.cache import CachedStep, RunBudgets, StepCache, StepIdentity, normalize_step_text; from prettyplay.engine.renderer import PreparedStep, StepMemory, render_step, validate_step_result; from prettyplay.engine import StepGenerator, StepHealer; from prettyplay.engine.steering import StepSteering; from prettyplay.engine.groups import GroupRecovery, GroupStepOutcome"`:
  Facade accessibility — every contract name importable from its facade
- `.venv/bin/python -m pytest tests/cache/ tests/engine/renderer/ tests/engine/ tests/engine/steering/ tests/engine/groups/ tests/test_executor.py tests/test_scenario.py tests/test_integration.py -q`:
  Per-package suites (used inside the tasks)
- `goga lint`: CODEMANIFEST integrity — 12 cells, 0 errors (the six applied manifests are
  read-only and must stay lint-clean)

---

## Completion Criteria

- [ ] Every contract entity is implemented in the correct `location` (`normalize_step_text` in
      `prettyplay/cache/text.py`; `CachedStep.addressing_text` + the validator in
      `prettyplay/cache/models.py`; the touched set, the `STEP_TEXT` validation/serialization
      and `sweep_untouched` in `prettyplay/cache/store.py`; `PreparedStep.addressing_text` and
      the both-texts render in `prettyplay/engine/renderer/render.py`; the identity switch in
      `prettyplay/executor.py`; the fresh row identity in
      `prettyplay/engine/groups/recovery.py`; the `_store` threading in
      `prettyplay/engine/generator.py`; the `_write_back` threading in
      `prettyplay/engine/steering/steering.py`; the `cleanup` switch and the guarded sweep in
      `prettyplay/scenario.py`)
- [ ] Every contract entity is accessible from the facade (all names ride the existing exports;
      the facade check command passes)
- [ ] Properties and methods match the declared API (`sweep_untouched(cache_key) ->
      removed: list[str]`; the `CachedStep`/`PreparedStep` field sets; the `PrettyPlay`
      constructor with the keyword-only `cleanup=True`; no public signature changed anywhere)
- [ ] Descriptions are reflected in behavior (the verbatim NFC+trim rule; both texts of one
      evaluation with tag-source preservation and the collision guard; the identity from the
      addressing text; the verbatim `STEP_TEXT` metadata and its normalization validation; the
      success-only touched set; the never-raising idempotent sweep; the teardown-then-guarded
      close)
- [ ] Contract dependencies are met (groups → cache gains `normalize_step_text` in its Types
      payload; the facade → cache `sweep_untouched` call rides the existing edge; no import
      edge added or removed)
- [ ] The three re-exports (`->PrettyConfig`, `->BrowserConfig`, `->StepHooks`) remain
      accessible from the facade
- [ ] Every coding task followed the TDD workflow (contract tests → code → interface
      verification → logic tests → debugging → contract re-verification → lint) **and** the
      REPL cycle (baseline evaluation, continuous evaluation, hot-reload discipline, code
      migration to source files)
- [ ] Contract tests and logic tests cover facade, API and behavior within each coding task
- [ ] All 25 design test scenarios are implemented (Tasks 1–9) and the integration scenarios
      exist (Task 11)
- [ ] The three mechanical bridges of Task 2 are all replaced — no bridge remains in the tree
- [ ] The documentation riders are complete (Task 10: the addressing table, the limitation
      passage, `cleanup` and the per-test working set, the purge note, the grep sweep clean)
- [ ] No package boundary was expanded (no new cells, no new facade names, no new dependencies;
      `pyproject.toml` untouched)
- [ ] `CODEMANIFEST` files were not modified (the contract is read-only)
- [ ] All validation commands pass (the full suite, lint, format, the facade check, `goga lint`)
- [ ] Every local commit was created only after the lint and format gates passed on the tree
- [ ] Every Usages entry is mentioned in at least one task (`conventions` — all tasks;
      `jinja` — Task 4; `taxonomy` — Task 4; `hooks` — Task 3; `rendering` — Tasks 4, 5, 11;
      `memory`/`validation` — Tasks 5, 11; `generation`/`healing` — Tasks 7, 11; `recovery` —
      Tasks 6, 11; the local `lifecycle` — Task 9)

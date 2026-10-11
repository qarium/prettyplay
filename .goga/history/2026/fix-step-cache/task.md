# Step cache: address by the rendered sentence, clean the working scope on close

## Current State

- Steps address the cache by their template source: `normalize_step_text` (`prettyplay/cache`, `text.py`) keeps a template sentence verbatim (NFC + trim) and casefolds an ordinary sentence with whitespace collapse; runtime values never enter the address. One template rendered with different values therefore reuses one address and replays code generated for another value — sometimes succeeding silently; documented as the accepted limitation in `prettyplay/.usages/steps.md`. Side effect of casefold: «Click Sign in» and «click  sign in » merge into one step.
- No cache lifecycle exists: step files persist forever; `PrettyPlay.close()` only stops the browser and driver runtime; nothing ever deletes entries.
- No cleanup switch exists anywhere in the library.

## Description

Implements the accepted ADR (`.goga/history/2026/fix-step-cache/adr.md`) with one interview amendment: the cleanup switch is a keyword-only constructor parameter of `PrettyPlay`, not a layered config field (see Notes).

1. **Addressing text.** `render_step` (`prettyplay/engine/renderer`) produces, beside the instruction, the addressing text — the rendered sentence with `{{ }}` interpolations substituted from the same vars + memory snapshot and active `{% var x %}` capture tags kept verbatim; an inactive branch contributes nothing. The LLM instruction keeps today's tag-stripped render — unchanged.
2. **Addressing.** `normalize_step_text` becomes one verbatim normalization for all addressing texts — Unicode NFC + trim; casefold and whitespace collapse are dropped from addressing. `StepIdentity` is built from the addressing text; a plain sentence addresses as itself (exact-text equality already unifies plain and identically rendered template sentences). The identity triple `(cache_key, step_type, normalized_text)` and the sha256 file name stay as they are.
3. **Cleanup switch.** `PrettyPlay` gains the keyword-only parameter `cleanup: bool`, default `True` — the cache is a per-test working set by default; persistence is opt-in:

   ```python
   test = PrettyPlay("login-flow", cleanup=False)  # keep the cache directory after close
   ```

4. **Cleanup algorithm on `close()`.** The test's cache accumulates touched addresses only after a successful load (`CachedStep`) or save (`True`) — cache hits, strict replays, generation, healing, steering and recovery write-backs. A load miss or skipped/failed save does not touch an address. On `close()` it reads every step file in its working scope — the `cache_root` + `cache_path` directory, filtered by file metadata to files carrying this object's `cache_key` — and deletes the files whose address is outside the touched set. Best-effort: a per-file failure is logged and never fails `close()`; `close()` stays idempotent; deletions are visible as log records.
5. **Budgets follow.** Attempt budgets keyed by `StepIdentity` follow the new addresses automatically: the same template re-rendered against changed memory is a different step with a fresh budget.
6. **No migration.** Some existing cache addresses change, while already normalized plain sentences can retain the same address and file name. Docs say to purge the cache directory after upgrading to remove incompatible entries. The first `cleanup=True` close sweeps untouched legacy files in this test's scope; touched compatible files survive.

## Scope

**In scope:**
- `prettyplay/engine/renderer`: the addressing text in the render product (`PreparedStep` field or an equivalent contract shape — the design belongs to the plan); one snapshot, one set of branch decisions for both texts.
- `prettyplay/cache`: single verbatim normalization in `normalize_step_text`; identity from the addressing text; `StepCache` — touched-address accumulation on load/save and the close-time sweep operation in the object's scope filtered by `cache_key`.
- `prettyplay` (facade): the keyword-only `cleanup` constructor parameter (default `True`); `close()` runs the sweep; `StepExecutor` builds the step identity from the addressing text of the render product instead of the raw sentence.
- `prettyplay/engine/groups`, `prettyplay/engine/steering`: recovery re-renders and steering write-backs address by their re-rendered addressing text and mark touched addresses (covered centrally when tracking lives in the per-test `StepCache`).
- Documentation: cell usages (`addressing.md`, `storage.md`, `steps.md`, `lifecycle.md`, `rendering.md` — as needed) and user docs (`docs/reference/step-cache.md`, `docs/guides/writing-steps.md`, other pages that state the old limitation or the team workflow), including the purge-after-upgrade note.

**Out of scope:**
- Security posture for value-bearing cache files (deferred ADR open question).
- A `on_cache_deleted` hook event (a contract decision for a later stage; deletions are log records only).
- Migration or conversion of existing cache files.
- Config, env or pyproject surface for `cleanup` — rejected in the interview: constructor parameter only; the `prettyplay/config` cell stays untouched.
- `ScenarioStep` records (raw sentence + prepared instruction), the LLM instruction render, attempt budget semantics.
- New multi-process coordination for the cache beyond today's last-writer-wins writes.

## Acceptance Criteria

- The same template rendered with different values yields different identities — no cross-value replay; the documented "accepted limitation" is gone from the docs.
- `normalize_step_text` applies NFC + trim only: «Click Sign in» and «click  sign in » are different steps; a plain sentence and a template producing the exact same text still share one step.
- The addressing text keeps active capture tags verbatim: `Read {% var a %}` and `Read {% var x %}` address differently; a tag inside an inactive branch contributes nothing.
- The instruction text is unchanged (tag-stripped) in generation requests and failure carries.
- `PrettyPlay("key")` defaults to `cleanup=True`; `close()` deletes only files inside `cache_root` + `cache_path` whose metadata carries this `cache_key` and whose address was not touched; touched files survive; a per-file deletion failure is logged and does not fail `close()`; repeated `close()` calls stay safe.
- Only a successful `load()` or `save()` marks an address touched; a missing or damaged cache entry and a skipped or failed write do not. An existing damaged or stale file is eligible for cleanup if no successful operation touched its address.
- `cleanup=False` deletes nothing.
- A committed strict replay run keeps the entries it replays — they are loaded, hence touched.
- The same template re-rendered against changed memory draws a fresh attempt budget (a new identity).
- No changes to the config schema, env overrides or `PrettyConfig` fields.
- Unit and edge tests cover the normalization, the addressing render, the touched set, the sweep and the flag (filesystem via `tmp_path` per conventions); existing tests updated; `pytest tests/ -x` green; `ruff check prettyplay/` clean.

## Stack

- **Frameworks:** none — framework-agnostic library
- **Libraries:** pydantic v2 (existing), jinja2>=3.1 (existing)
- **Infrastructure:** none — the step cache stays a filesystem store (sha256 file names, atomic writes)
- Python 3.10+; conventions of `.goga/usages/conventions.md`

## External Dependencies

| Component | Usage file                             | Status                       |
|-----------|----------------------------------------|------------------------------|
| jinja2    | `.goga/usages/cooks/jinja.md`          | updated (addressing render pattern added at the specify stage) |
| pydantic  | `.goga/usages/cooks/pydantic.md`       | existing |
| pytest / ruff | `.goga/usages/conventions.md`      | existing |

Synced usage files are managed by `goga usages sync` — reference them read-only, never create or update them in the task.

## Risks and Constraints

- Some existing cache files become unreachable after the upgrade; already normalized plain sentences can retain their address and file name. Docs carry the purge-after-upgrade note to remove incompatible entries. The first `cleanup=True` close sweeps untouched legacy files in this test's scope; touched compatible files survive.
- Rendered values (vars, memory captures) now land in cache file metadata on disk — accepted knowingly in the ADR; the security posture is a deferred open question.
- The committed-cache team workflow (generate locally, commit the directory, strict replay in CI) now needs an explicit `cleanup=False`; strict replays keep the entries they use, so a committed strict run is self-preserving.
- Strict replay across processes requires the replay to render the exact same sentences as the generation run (deterministic vars and application state).
- `close()` reliability: the sweep is best-effort and must never mask or break the browser/driver teardown; `close()` stays idempotent.

## Scope Estimate

Single task. One ADR, one semantic feature — the addressing change and the cleanup are coupled (the sweep operates on the new addresses through the same load/save points); no decomposition, no additional topics.

## Existing Architecture

- `prettyplay/engine/renderer` — `render_step`, `PreparedStep` (`render.py`): the render point of every step execution and every recovery re-invocation; `StepMemory` snapshot plus `vars` feed it.
- `prettyplay/cache` — `normalize_step_text` (`text.py`), `StepIdentity`/`CachedStep` (`models.py`), `StepCache` (`store.py`), `RunBudgets` (`budgets.py`); cache files carry metadata (sentence, cache key, step type, creation date) — the sweep filters by the metadata `cache_key` and compares addresses.
- `prettyplay` (facade) — `PrettyPlay` (`scenario.py`): the constructor builds the per-test `StepCache` (algorithm step 4); `StepExecutor.execute` step 2 builds the identity from the original sentence via `normalize_step_text` — the point that switches to the addressing text; `close()` delegates to `PrettyplayRuntime.close()`.
- `prettyplay/engine/groups` — `GroupRecovery` re-renders row steps against the current context and writes back to the cache; `prettyplay/engine/steering` — `StepSteering` healed write-back.
- The per-test `StepCache` instance is shared by the executor and every engine — central load/save tracking in the cache covers all touched-address sources.

## Notes

- **ADR deviation (interview, 2026-10-11).** The ADR specifies `cleanup` as a layered config field (`[tool.prettyplay] cleanup`, env `PRETTYPLAY_CLEANUP`, per-test override). The owner overrode this at the specify stage: `cleanup` is a keyword-only `PrettyPlay` constructor parameter only, default `True`; no pyproject, env or `PrettyConfig` surface. This task follows the override; the ADR text stands as the discover-stage record.
- The only code example fixed by the interview: `PrettyPlay("login-flow", cleanup=False)`.
- The addressing render pattern was added to `.goga/usages/cooks/jinja.md` at the specify stage.
- Deferred with the ADR: the `on_cache_deleted` hook event; the security posture for value-bearing cache files.

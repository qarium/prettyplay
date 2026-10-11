# Step cache addresses by the rendered sentence and cleans its scope on close

---
status: accepted
date: 2026-10-11
---

The step cache addressed steps by their template source — "runtime values never enter the address" — so the same
template rendered with different values replayed code generated for the wrong value, sometimes succeeding silently
(the documented "accepted limitation" of the old addressing). We decided: the step address is now built from the
**addressing text** — the rendered sentence with `{{ }}` substitutions applied (vars + memory), capture tags
`{% var x %}` kept verbatim — and every `PrettyPlay` object, on `close()`, deletes the step files in its working
scope whose addresses it did not load or save during its lifetime, governed by a new `cleanup` setting
(`[tool.prettyplay] cleanup`, env `PRETTYPLAY_CLEANUP`, per-test override; default `True`).

## Decision

1. **Address structure unchanged, text changed**: the identity stays the triple
   `(cache_key, step_type, normalize(addressing_text))` hashed with sha256 into the file name.
2. **Addressing text**: a plain sentence addresses as itself; a template addresses by its render — `{{ }}`
   substituted with actual values from vars and memory, `{% var x %}` capture tags remaining verbatim in the
   addressing text. The LLM instruction keeps today's tag-stripped render — unchanged.
   Keeping the capture tags makes templates differing only in capture names (`Read {% var a %}` vs
   `Read {% var x %}`) address differently by construction.
3. **One normalization for all addressing texts**: Unicode NFC + trim, verbatim — case and internal whitespace
   are significant because rendered values are data ("Sign in" and "sign In" are different buttons). Casefold
   and whitespace collapse are dropped from addressing; the old documented merge
   («Click Sign in» == «click  sign in ») is gone by decision.
4. **Cleanup flag**: a config field, layered like `strict`/`interactive` — pyproject, env, per-test override.
   Default `True`: the cache is a per-test working set by default; persistence is opt-in (`cleanup = false`).
5. **Cleanup algorithm on `close()`**: during execution the object accumulates the set of addresses it loaded
   (cache hits, strict replays) or saved (generation, healing, steering/recovery write-backs, recovery
   re-renders). On close it reads every step file in its working scope — the `cache_root` + `cache_path`
   directory, filtered to files whose metadata carries this object's `cache_key` — and deletes the files whose
   address is outside the touched set. Best-effort: a per-file failure never fails `close()` and is logged;
   `close()` stays idempotent. Deletions are visible as log records; a hook event is a contract question for a
   later stage.

## Considered options

- **Unified casefold normalization** (merge case/whitespace of the whole rendered text): rejected — it
  reintroduces silent wrong hits for values differing only in case or spacing, the exact bug class this change
  fixes; it did buy template/plain unification when texts coincide exactly, judged not worth it.
- **Hybrid normalization** (plain sentences casefold, template renders verbatim): rejected — two addressing
  regimes to document and explain; exact-text equality already unifies plain and rendered sentences without it.
- **Capture declarations excluded from the address**: superseded by keeping `{% var %}` tags in the addressing
  text — cheaper than a separate declarations component and collision-free.
- **Cleanup scope = the whole `cache_path` directory regardless of `cache_key`**: rejected — with the default
  shared root (`cache_path` unset) every test close would purge other tests' entries; the `cache_key` filter
  (readable from file metadata) keeps the scope honest to "this object's working area".
- **Cleanup default `False`**: rejected — the owner wants value-bearing cache entries treated as a per-test
  working set unless persistence is explicitly requested.

## Consequences

- The committed-cache team workflow (generate locally, commit the directory, strict replay in CI) now requires
  an explicit `cleanup = false`; with the default, generated entries vanish at test close. Strict replays keep
  the entries they use (they load them), so a committed strict run is self-preserving.
- Strict replay across processes requires the replay to render the exact same sentences as the generation run
  (deterministic vars and application state).
- Every existing cache file becomes unreachable (addresses change for plain and template steps alike): no
  migration; docs say to purge the cache directory after upgrading — and the first `cleanup = True` close
  sweeps the legacy files out of each test's scope as a side effect.
- Attempt budgets keyed by `StepIdentity` follow the new addresses: the same template re-rendered against
  changed memory is a different step with a fresh budget.
- `ScenarioStep` records (raw sentence + prepared instruction) are unchanged.
- Rendered values (vars, memory captures) now land in cache file metadata on disk — accepted knowingly;
  see open questions.

## Open questions

- Security posture for value-bearing cache files (secrets in vars/captures reaching disk, logs and LLM
  requests): deliberately deferred — no docs rule extended now, to be designed later.
- Whether cache cleanup deserves a hook event (e.g. on_cache_deleted) alongside the log record — a contract
  decision for the contract-designing stage, intentionally not fixed here.

# Investigation Report

## Task Summary

The user reports: when an already-assembled `PrettyConfig` is passed to prettyplay, the library still loads the configuration (pyproject.toml + `PRETTYPLAY_*` env) instead of taking the ready instance verbatim. The task is to find the root cause and fix it so a pre-assembled config is honored without re-loading the file layer.

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| `prettyplay/config` | Owns `load_config` — the unconditional file+env load under defect | 1 |
| `prettyplay` (root) | `PrettyPlay.__init__` (scenario.py:181) — the entry point routing every passed config through `load_config` | 2 |

## Tracing Summary

- `PrettyPlay.__init__` calls `load_config(None, config)` unconditionally (scenario.py:181) — the only production call site.
- `load_config` (loader.py:279) unconditionally: finds pyproject.toml upward from cwd → parses TOML → rejects legacy names → collects `PRETTYPLAY_*` env overrides → builds the file-layer `PrettyConfig` → only then overlays explicitly set fields of the passed config (`_apply_overrides`, loader.py:239).
- `_apply_overrides` drops fields that are: not in `model_fields_set`, `None`, or empty strings — so unset/empty parts of a pre-assembled config silently fall back to the file/env layer.
- Without a pyproject.toml anywhere upward from cwd, `load_config` raises `FileNotFoundError` — a fully programmatic setup cannot construct `PrettyPlay` at all.

## Data Flow Analysis

`PrettyConfig(ready)` → `overrides` parameter → overlaid onto file+env layer → effective config → `PrettyplayRuntime` → engines. Data loss points: unset fields, `None` (polling_timeout), empty strings (e.g. intentionally empty `generation_model`), and per-field browser-group merge — each lets the file/env value leak into a config the integrator considered assembled.

## Manifest Algorithm Analysis

- `prettyplay/config` CODEMANIFEST, `load_config` Algorithm steps 1–7 prescribe the unconditional file+env load; steps 9–11 prescribe the overlay. The implementation matches the manifest exactly — the manifest itself mandates the reported behavior.
- `prettyplay` root CODEMANIFEST, `PrettyPlay` Algorithm step 1: "Resolve the effective config: `load_config` with overrides = config"; `config` is documented as "per-test overrides … unset/empty fields resolve from pyproject+env".
- Conclusion: this is not an implementation bug — it is a **contract design gap**: no path exists for a pre-assembled config taken verbatim.

## Affected Usages

| Usage | Cell | Classification | Reason |
|---|---|---|---|
| `.usages/configuration.md` ("Per-test overrides — layered merge", "Loading") | prettyplay/config | DIRECTLY AFFECTED | Must document the pre-assembled path once designed |
| `.usages/lifecycle.md` | prettyplay | INDIRECTLY AFFECTED | Construction flow references config resolution |
| `.usages/steps.md` | prettyplay | INDIRECTLY AFFECTED | Verify no layered-merge references |
| `.goga/usages/conventions.md` | project | INDIRECTLY AFFECTED | Code/test conventions for the fix |

## Rejected Hypotheses

| Hypothesis | Rejection evidence |
|---|---|
| H1: `_apply_overrides` loses values due to a bug in `model_fields_set` handling | The drop rules (unset/None/empty) are intentional and manifest-documented (loader.py:244-272; manifest step 10) — the overlay works as specified |
| H2: env overrides defeat programmatic values | False: the overlay runs after env merging and explicit non-empty values win (test_scenario.py:569) |
| H3: a stray second `load_config` call ignores the passed config | Only one production call site exists (scenario.py:181); tests patch exactly it |
| H4: the runtime re-loads config later | `PrettyplayRuntime.__init__` only stores the passed config (runtime.py:23-29); no re-load |

## Confirmed Root Cause

**The library has no "pre-assembled config" code path.** `PrettyPlay.__init__` routes every passed config through `load_config(None, config)`, which by contract and by code always loads the pyproject+env file layer first and back-fills every unset/empty field of the passed config from it (loader.py:303-340; CODEMANIFEST `load_config` Algorithm steps 1–11; root CODEMANIFEST `PrettyPlay` Algorithm step 1). Observable failures:
1. A run without any pyproject.toml upward from cwd dies with `FileNotFoundError` even though the config is complete.
2. `PRETTYPLAY_*` env vars and a foreign `[tool.prettyplay]` section mutate fields the integrator left at defaults in an assembled config.
3. Intentionally empty/`None` fields of the passed config never take effect — file values leak through.

Evidence chain: user report ↔ scenario.py:181 ↔ loader.py:303-340 ↔ both CODEMANIFESTs ↔ tests pinning the behavior (test_scenario.py:545 "untouched fields come from the file", :540 `call(None, None)`).

## Confidence Level

**HIGH** — deterministic causality with a full evidence chain: the unconditional load is visible in code, prescribed by both manifests, and pinned by tests. The remaining open question is not factual but a design choice (which fix shape), resolved at the planning stage.

## Breaking Change Assessment

Fix shape is a planning decision; assessment per candidate:

1. Existing call with same arguments produces different behavior? — **Reinterpreting `config` as verbatim: YES** (partial configs lose the file fallback; test_scenario.py:545 breaks). New separate channel (explicit opt-in): NO.
2. Existing file paths change? — NO for both.
3. Output format change? — NO for both.
4. Return value semantics change? — Effective-config semantics change only under the verbatim reinterpretation: YES.
5. Manifest-defined guarantees altered? — Verbatim reinterpretation alters the documented `config` overlay guarantee: YES; new channel: NO (extends the contract additively).
6. Existing tests break? — Verbatim reinterpretation: YES (test_scenario.py:545, :540). New channel: NO.

**BREAKING CHANGE DETECTED** for the "reinterpret `config`" shape — pipeline STOP applies unless the user explicitly overrides and approves that shape at the planning checkpoint (Step 3 WAIT).

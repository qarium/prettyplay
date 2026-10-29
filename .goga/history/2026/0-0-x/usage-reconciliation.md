# Usage Reconciliation Report

## Classification

| Usage File | Classification |
|---|---|
| `prettyplay/config/.usages/configuration.md` | DIRECTLY AFFECTED |
| `prettyplay/.usages/lifecycle.md` | DIRECTLY AFFECTED |
| `prettyplay/.usages/steps.md` | UNAFFECTED (verified — no config-resolution references) |
| other cell `.usages/` files (cache, engine, llm, driver, reporting, failures, skills) | UNAFFECTED (no config-resolution references) |
| `README.md`, `docs/` (public documentation) | INDIRECTLY AFFECTED — verified and updated (breaking-change communication) |

## Updated Usages

| Usage File | Changes Made | Reason |
|---|---|---|
| `prettyplay/config/.usages/configuration.md` | Intro sentence; "Per-test overrides — layered merge" → "The programmatic configuration" (verbatim semantics, rebuilt example with an explicit `model`, new bullet set); `per-test override` wording in llm retries / pace / interactive / strict sections → "programmatically assembled config"; compliance-gate override example now shows a passed config as the effective one; "Loading" section gained the `adopt_config` recipe | The documented overlay semantics no longer match the implemented verbatim adoption |
| `prettyplay/.usages/lifecycle.md` | Composition paragraph (verbatim statement, `config=None` path); `per-test override` wording in strict/interactive sections | Same |
| `README.md` | The `config` argument paragraph — verbatim semantics, `config=None` file path | Public quickstart described the removed overlay |
| `docs/configuration.md` | "Per-test overrides — layered merge" → "The programmatic configuration"; `load_config` API section keeps its (still valid) layered description with a fixed anchor and the verbatim note; strict section wording | Public reference described the removed overlay |
| `docs/getting-started.md` | Composition paragraph; strict / polling / interactive wording | Same |
| `docs/guides/browser-setup.md` | "Per-test overrides" → "Browser settings of a passed config" with verbatim semantics; fixed anchor | Same |
| `docs/reference/interactive-steering.md` | `per-test override` → "programmatically assembled config" | Same |

## Verified Usages

| Usage File | Verified? | Notes |
|---|---|---|
| `prettyplay/.usages/steps.md` | yes | No config-resolution references; cache/step recipes unaffected |
| `prettyplay/config/.usages/configuration.md` examples | yes | All code examples re-checked against the new behavior; the `PrettyPlay(..., config=...)` call shapes remain valid |
| remaining cell usages | yes | No references to config resolution or layered merge of the passed config |
| `prettyplay/config/CODEMANIFEST` usage references (`conventions`, `pydantic`, `taxonomy`) | yes | `goga lint` passes (13 cells, 0 errors) |

## Canonical Patterns Status

**Changed by design, safely.** The canonical "pass a PrettyConfig" call shape is preserved verbatim (`PrettyPlay(cache_key=..., config=PrettyConfig(...))`); only its meaning changed from overlay to complete configuration — the user-approved breaking change. The `load_config` file-layer recipe stays canonical for `config=None` consumers. The `PrettyConfig`/`BrowserConfig` construction patterns, env override table, and screen/pace/timeout recipes are unchanged.

## Consistency Summary

**Consistent.** All DIRECTLY/INDIRECTLY affected usages updated to the verbatim semantics; no unrelated usages rewritten; `goga lint` passes; full test suite green (1524 passed, 1 pre-existing skip).

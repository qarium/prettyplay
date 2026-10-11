# Compatibility Report

## Checklist Results

### API Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Function signature unchanged for existing callers? | YES | No signature touched: `generate`, `regenerate`, `check_step_compliance`, `run_step_code`, `steer` keep their parameter lists; only prompt text constants and manifest practice/annotation text change |
| Return type unchanged? | YES | `check_step_compliance` still returns `list[ComplianceFinding]`; loops still return `CachedStep`; the finding shape (instruction/priority/explanation/dimension) is unchanged |
| Default parameter values preserved? | YES | No defaults touched anywhere (`cleanup`, `generation_approve`, gate switch semantics intact) |

### Semantic Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Same arguments produce same behavior? | **NO** | A green candidate carrying unused bindings — cached silently today — becomes a high adequacy finding: the gate returns a non-empty findings list, the attempt is blocked (outcome compliance blocked), retried with the grown history, and only clean code caches; repeated dead-code candidates can end in `IncurableStepError` naming the finding. Same inputs to `generate`/`regenerate`/`steer`/`check_step_compliance`, different outcome for dirty candidates — the intended repair |
| Output format unchanged? | YES | The verdict answer format (JSON findings list), attempt-record shape, cache file format and log event names are unchanged; new finding texts ride the existing fields |
| File paths unchanged? | YES | No module, practice, doc or cache path moves; the only deletion is a gitignored local cache artifact (`c8135598….py`) |
| Error messages and codes unchanged? | YES | No error type, message template or authored reason changes; violation texts are verdict content, not message formats |

### Algorithmic Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Manifest-defined algorithm steps preserved? | YES | The generate/regenerate/steer algorithms keep every step and branch; the gate remains the acceptance authority (step 5/step 7). The `compliance_prompt` practice and the fixed-form annotation — normative texts the manifest itself defines — gain the cleanliness dimension; the blocking path used is the existing high-finding path |
| Execution order unchanged? | YES | request → execute → validate → gate → publish → store, unchanged on every path |
| Side effects unchanged? | YES | Cache writes, memory publication, hook events, logging keep their points; a blocked attempt publishes nothing (existing semantics) |

### Consumer Compatibility
| Question | Answer | Evidence |
|----------|--------|----------|
| Existing tests pass without modification? | YES | Full suite green on the current tree (1380 passed, verified this run); prompt pins assert substrings and orders among markers the edit preserves; mirror-equality tests carry the lockstep |
| Usage recipes remain valid? | YES | Cell usages (engine `generation.md`, `healing.md`, steering) describe API consumption, untouched; the generation practice keeps its structure — one rule extended |
| Downstream consumers unaffected? | YES | For well-formed clean code every consumer (example suite, committed-cache strict replays) behaves identically; cached replays never pass the gate; only newly generated dirty candidates change outcome |

## Verdict

**BREAKING** — Semantic Compatibility / «Same arguments produce same behavior» fails: the compliance gate changes its verdict for candidates carrying unused bindings (pass+cache → high finding+block+retry). Every other checkbox is YES.

## Owner Approval

The breaking dimension is **approved by the owner** (dialog q2, this run, option A): the blocking high design proceeds as planned — dead code never caches; dirty candidates consume their attempt and retry within existing budgets; repeated violations fail loudly with the finding named. The warn-only alternative was presented and declined. The stop is lifted; the pipeline continues.

## Breaking Change Details

One breaking dimension, identical in kind to the owner-approved `hotfix-step-context` change: the acceptance boundary of the generation system tightens. Candidates with dead code — accepted and cached before — are now rejected by the gate and retried; the retry carries the violation text in the attempt record so the model targets it; budget exhaustion after repeated violations raises the existing incurable failure naming the finding. No public API, format, path or error-contract change; well-formed code and existing caches are untouched. The alternative design — a medium (warn-only) finding — keeps today's behavior for dirty candidates (they cache, with a WARNING) and is not breaking; it also leaves the reported defect reachable in the cache. Per the project rule «Breaking-Change Authorization Gate» the pipeline is stopped here; only explicit owner approval of the blocking design lifts the stop.

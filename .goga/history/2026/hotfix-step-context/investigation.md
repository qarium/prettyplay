# Investigation Report

## Task Summary

Owner-reported defect: cached step code reads the execution context — `step_inputs["vars"]["url"]` in `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/b6341eae….py` and `step_inputs["vars"].get("request", "vibe coding")` in `c8135598….py` — while the owner's requirement is that steps use the values rendered into the step and know nothing about the context. The task: find the root cause of why the shipped generator produces context-dependent step code and resolve it.

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| prettyplay/engine | All three defect carriers: runtime context exposure (`execution.py`), generation teaching (SYSTEM_PROMPT), gate rule forcing context reads (COMPLIANCE_PROMPT) | 1 |
| prettyplay/engine/steering | Frozen SYSTEM_PROMPT copy with the same teaching; context binding around guided execution | 2 |
| prettyplay | Executor binds the context on the replay path | 3 |

## Tracing Summary

See `trace.md` in this directory. Every execution path — generation (`generator.py:418`), healing (`generator.py:545`), funded regeneration (`generator.py:847`), steering (`steering.py:323`), replay (`executor.py:191`) — wraps `run_step_code` in `bind_step_inputs(memory.snapshot(), prepared.inputs)`, which sets a ContextVar that `run_step_code` copies into the step-code namespace as the `step_inputs` global (`execution.py:42`).

## Data Flow Analysis

The rendered values reach generated code through two channels: (1) statically — embedded in the prepared instruction rendered into every LLM request and pinned into the cache address via `addressing_text`; (2) dynamically — the context global bound fresh at each execution. Channel (2) is the residue of the pre-`fix-step-cache` regime, when one template address served all values and cached code had to read runtime values to stay correct. Under rendered-sentence addressing the dynamic channel is not merely unnecessary — it is harmful: the address already fixes the values, so context reads can only agree with the address (redundant) or diverge from it (wrong: hallucinated names, cross-shape replays).

## Manifest Algorithm Analysis

The cache contract (`prettyplay/cache`): deterministic addressing by the addressing text — the same template rendered with different values yields different identities. The engine contract (`engine` CODEMANIFEST): the fixed form of step code "may read the current execution's step_inputs global (captured values by name, call-local inputs under vars)" (:147), and the `compliance_prompt` practice (:134-135) mandates `step_inputs["vars"]` reads for input-influenced steps, blocking hardcoded rendered values as a high adequacy finding. The two contracts contradict: the cache pins values into the address; the engine contract makes cached code value-dynamic. The compliance rule's justification — "cannot replay with new inputs" — states a premise the addressing change removed (new inputs produce a new addressing text and a fresh generation; a cached step never replays against different values of its own template).

## Affected Usages

| Usage | Cell | Classification | Reason |
|---|---|---|---|
| `.goga/usages/prompts/step_generation.md` (`system_prompt`) | engine, steering | DIRECTLY AFFECTED | The teaching rule (line 33 after the separator) is the defect carrier; three synchronized copies must change together |
| `compliance_prompt` practice (engine CODEMANIFEST) | engine | DIRECTLY AFFECTED | The inverted hardcoded-values rule must flip to the self-containment rule; constant mirror in `compliance.py` follows |
| engine CODEMANIFEST global annotations | engine | DIRECTLY AFFECTED | The `step_inputs` grant (:147) is replaced by the self-containment statement |
| `docs/reference/step-cache.md` | docs | DIRECTLY AFFECTED | Lines 42-45 teach the context global with a rationale the addressing change inverted |
| `engine/.usages/generation.md`, `healing.md`, `steering/.usages/steering.md` | engine, steering | INDIRECTLY AFFECTED | Verified: no `step_inputs` mentions today; snippets already show self-contained code — re-verified after the change |

## Rejected Hypotheses

- "The LLM hallucinated the construct against its instructions" — rejected: all three prompt copies explicitly teach reading `step_inputs` "instead of hardcoding"; the compliance gate additionally blocks hardcoded values for steps with inputs. The behavior is prescribed, not hallucinated.
- "The addressing change missed a code path and old-address files leak through" — rejected: both defect entries carry fresh rendered addressing texts (`Open https://youtube.com`, `Find videos for "vibe coding"` — created 2026-10-11 after the feature merged); the addresses are new-regime, the code shape is old-regime teaching.
- "Prompt-only regression introduced by the acceptance-stage edits" — rejected: git blame shows the teaching line predates the addressing change and was carried unchanged through it (commits c9e6f16..2df1bd5 touch addressing, not the step_inputs rules).

## Confirmed Root Cause

The `fix-step-cache` addressing change replaced template-text addressing with rendered-sentence addressing but did not migrate the step-code value contract: the generation/steering system prompts still teach reading the `step_inputs` context global, the compliance gate still enforces context reads (blocking hardcoded rendered values for steps with inputs), the runtime still binds and exposes the context, and the engine manifest still grants it. For steps whose values arrive through call `vars`, the system deterministically produces context-reading cached code — exactly the owner's symptom; the gate rejects the correct self-contained form. Secondary consequence: context-reading cached steps break (loudly or silently) on legitimate replays of the same addressing text with a different vars shape (plain sentence vs template), e.g. `step_inputs["vars"].get("request", …)` silently fabricating a value.

## Confidence Level

HIGH — deterministic causality with a full evidence chain: owner's artifact shows the construct; the three synchronized prompt copies prescribe it; the gate rule enforces it exactly for the affected steps (both defect entries carry INPUTS; the five non-inputs example entries embed literals and passed); the runtime implements it; the contradiction with the shipped addressing contract is stated in the artifacts themselves.

## Breaking Change Assessment

1. Existing function call with same arguments produces different behavior? **YES** — `run_step_code(code, page)` for code reading `step_inputs` works today and raises `NameError` after the fix; replays of legacy cache entries with context reads fail loudly (and self-heal outside strict mode).
2. Existing file paths change? **NO** — cache layout, file names, metadata unchanged.
3. Output format change? **NO** — log records, step files, hook events keep their shapes.
4. Return value semantics change? **NO** — for well-formed self-contained code, behavior is identical.
5. Manifest-defined guarantees altered? **YES** — engine CODEMANIFEST :147 guarantees the `step_inputs` global; the fix removes that guarantee and replaces it with the self-containment requirement (the guarantee itself is the defect carrier).
6. Existing tests break? **YES** — `tests/engine/test_execution.py:77-84` (bind/fresh-reads contract), `tests/engine/test_generator.py:2674-2675` (healing through context reads), `tests/test_executor.py:1279-1291` (replay through context reads) pin the removed behavior.

**BREAKING CHANGE DETECTED** — per the pipeline policy the change halts at the compatibility guard; escalation to the owner follows there.

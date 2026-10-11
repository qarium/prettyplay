# Scope Resolution Report

## Task Summary

Owner-reported defect: generated step code persisted in the cache reads the execution context — `step_inputs["vars"]["url"]` — instead of using the values rendered into the step. Concrete evidence: `example/.prettyplay/cache/tests/test_youtube/test_youtube_search/b6341eae….py` (`page.goto(step_inputs["vars"]["url"])`, addressing text `Open https://youtube.com`) and `c8135598….py` (`step_inputs["vars"].get("request", "vibe coding")`, addressing text `Find videos for "vibe coding"`). Owner requirement: steps must use the values rendered into the step and know nothing about the context. This is a residue of the pre-addressing-change regime: the generation and steering system prompts still teach reading `step_inputs`, and the compliance gate still blocks hardcoded rendered values demanding context reads — both invert the rendered-sentence addressing semantics shipped in `fix-step-cache`.

## Candidate Cells

| Cell | Reason | Priority |
|---|---|---|
| prettyplay/engine | Root cause lives here: `execution.py` binds the `step_inputs` ContextVar into the step-code namespace; `generator.py` SYSTEM_PROMPT teaches context reads (line 55); `compliance.py` COMPLIANCE_PROMPT demands `step_inputs["vars"]` reads and blocks hardcoded rendered values (lines 73–74); CODEMANIFEST fixes both texts as practices/annotations | 1 |
| prettyplay/engine/steering | Frozen local copy of SYSTEM_PROMPT carries the same teaching line (line 59); binds `step_inputs` around guided execution (line 323); CODEMANIFEST pins the mirror discipline | 2 |
| prettyplay | Facade `executor.py` imports and binds `step_inputs` on the strict-replay path (lines 14, 191) | 3 |

## Included Dependencies

| Cell | Behavioral Relevance |
|---|---|
| prettyplay/llm | No signature or request-shape change — `check_instruction_compliance` keeps its inputs; only the prompt text passed by the engine changes. Verified no `step_inputs` references. Not modified; participates as the unchanged port |
| prettyplay/engine/renderer | `PreparedStep` already carries the rendered instruction, input bindings and declarations — the values steps must embed. No change; the fix consumes the existing render product |

## Excluded Dependencies

| Cell | Exclusion Reason |
|---|---|
| prettyplay/cache | Addressing, storage, sweep and budgets are correct under rendered-sentence addressing; no `step_inputs` surface. The defect is upstream of the cache |
| prettyplay/engine/groups | Recovery executions go through the engine executor paths; no own `step_inputs` binding or prompt text (grep-verified). Covered transitively by the engine change |
| prettyplay/config | No settings surface involved; the gate switch `generation_approve` semantics stay |
| prettyplay/driver, prettyplay/failures, prettyplay/reporting | Infrastructural only — no behavioral participation in the defect |
| prettyplay/engine/polling | Settle semantics unrelated to context binding |

## Usage Relationships

| Usage | Relevance |
|---|---|
| `.goga/usages/prompts/step_generation.md` (`system_prompt` practice of engine and steering) | Single source of the generation system prompt; the teaching line is the defect carrier — must change in lockstep with both frozen constants (test-enforced: `tests/test_groups_integration.py:564`, `tests/engine/steering/test_steering.py:353`) |
| engine CODEMANIFEST `compliance_prompt` practice | Single source of the compliance prompt; carries the inverted hardcoded-values rule — must change in lockstep with the `COMPLIANCE_PROMPT` constant |
| `docs/reference/step-cache.md` | User documentation teaches reading `step_inputs` (lines 43–44) — must state the self-contained contract instead |
| `.goga/usages/conventions.md` | Testing conventions for the new/updated tests; no edit |

## Semantic Participation Summary

`prettyplay/engine` owns all three defect carriers: the runtime context exposure (`execution.py`), the generation teaching (SYSTEM_PROMPT), and the gate rule that forces context reads for steps with inputs (COMPLIANCE_PROMPT). `prettyplay/engine/steering` duplicates the teaching and the binding for guided regeneration. The facade `prettyplay` binds the context on the cache-replay path. Every other cell either already provides what self-contained steps need (renderer, llm) or is untouched by the context question.

## Final Investigation Scope

- prettyplay/engine (execution, generator, compliance, CODEMANIFEST)
- prettyplay/engine/steering (steering.py, CODEMANIFEST)
- prettyplay (executor.py)
- Docs: `docs/reference/step-cache.md`; practice source: `.goga/usages/prompts/step_generation.md`
- Tests pinning the current behavior or the new one

## Scope Risks

- Over-scoping: touching the LLM port or renderer would widen the change beyond the defect — excluded.
- Under-scoping: fixing only the prompts would leave the runtime context reachable and the manifest contract permitting context reads — the owner's requirement ("know nothing about the context") demands the runtime removal too.
- Mirror lockstep: the generation prompt exists in three synchronized copies (practice file + engine constant + steering constant) and the compliance prompt in two (manifest practice + constant) — a one-sided edit fails mirror tests.
- Legacy caches: entries generated by the previous prompt that read `step_inputs` fail loudly on replay once the runtime global is gone — handled at the compatibility guard.

## Notes

- The two example cache files are gitignored local artifacts (`example/.prettyplay/`); the library fix is the deliverable, the local entries are purged as remediation of the reported symptom.
- Most steps in the example cache already embed rendered values (`page.get_by_role("link", name="Что такое вайб-кодинг?")`); only the two steps whose values arrive through call `vars` fell into the taught context-read pattern — confirming the prompt lines as the cause.

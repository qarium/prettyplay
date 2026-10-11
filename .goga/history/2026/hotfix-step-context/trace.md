# Trace Report

## Call Flow

Generation path:
```
PrettyPlay.step/expect (facade scenario.py)
  → StepExecutor.execute (executor.py)
    → render_step (renderer) → PreparedStep{addressing_text, instruction, inputs, declarations}
    → StepIdentity(cache_key, step_type, normalize_step_text(addressing_text))
    → StepCache.load(identity) → miss
    → StepGenerator.generate → _generation_loop
        → provider.generate_step(SYSTEM_PROMPT, …)  ← teaches step_inputs reads (generator.py:55)
        → with bind_step_inputs(memory.snapshot(), prepared.inputs):   (generator.py:418)
            → settle(run_step_code, code, page, window)
                → run_step_code: namespace = {"step_inputs": …}; exec; page.run(step_fn)  (execution.py:42-48)
        → validate_step_result → check_step_compliance(COMPLIANCE_PROMPT, …)  ← blocks hardcoded values (compliance.py:73-74)
        → StepCache.save
```

Healing path: `StepHealer.heal → StepGenerator.regenerate → _healing_loop` — same bind at generator.py:545, funded regeneration bind at generator.py:847, same gate.
Steering path: `StepSteering.run → _guided_request(local SYSTEM_PROMPT copy, steering.py:59) → bind_step_inputs (steering.py:323) → run_step_code → gate → write-back`.
Replay path: `StepExecutor.execute → StepCache.load → hit → bind_step_inputs (executor.py:191) → settle(run_step_code, cached.code)`.

## Data Flow

`render_step` produces `PreparedStep` — the instruction embeds the rendered values (vars + memory), the addressing text pins them into the cache identity. In parallel, `bind_step_inputs` pushes the SAME values as a mutable runtime context (`{**memory, "vars": inputs}`) through a ContextVar into the step-code namespace. Every execution path (generation, healing, steering, replay) binds the context and executes code that may read it — so a cached step's behavior depends on two value sources: the address (static) and the context (dynamic), by design of the old template-addressing regime.

## Manifest Algorithm Mapping

- engine CODEMANIFEST `run_step_code` entry: "Compile and load `code` in an isolated namespace … the step function receives the genuine sync Page" — code matches; the namespace additionally carries the context global (declared in the global annotation :147, not in the routine entry).
- engine CODEMANIFEST global annotation :147: "…may read the current execution's step_inputs global (captured values by name, call-local inputs under vars)" — implemented by execution.py:9-19,42.
- engine CODEMANIFEST `compliance_prompt` practice :134-135 — mirrored verbatim in compliance.py:73-74; the gate rule fires "when INPUTS values influence the step".
- cache cell schema: "deterministic addressing by the addressing text … the same template rendered with different values yields different identities" — the value-pinning contract the step_inputs rules contradict.

## Cross-Cell Traversals

| Source Cell | Target Cell | Type | Path |
|---|---|---|---|
| prettyplay (facade) | prettyplay/engine | call | executor.py imports `run_step_code`, `bind_step_inputs`; executes replays and generation candidates |
| prettyplay/engine | prettyplay/llm | data | SYSTEM_PROMPT / COMPLIANCE_PROMPT texts passed to `provider.generate_step` / `check_instruction_compliance` |
| prettyplay/engine | prettyplay/engine/renderer | data | `PreparedStep.inputs` → context binding; `PreparedStep.instruction` → request STEP block |
| prettyplay/engine/steering | prettyplay/engine (mirror) | data | frozen local SYSTEM_PROMPT copy mirrors `.goga/usages/prompts/step_generation.md`; test-enforced equality with the engine constant |
| prettyplay/engine | prettyplay/cache | call | `StepCache.load/save` keyed by the identity built from the rendered addressing text |
| prettyplay/engine/groups | prettyplay/engine | call | recovery rows regenerate through the engine loop — same bind and gate, no own context binding |

## Inconsistencies

| Type | Location | Expected | Actual |
|---|---|---|---|
| Prompt rule contradicts addressing contract | generator.py:55, steering.py:59, `.goga/usages/prompts/step_generation.md:33` | Steps self-contained: values rendered into the step are embedded as literals (each value combination owns its cache address) | Prompt teaches reading `step_inputs` "instead of hardcoding the current STEP or INPUTS values into cached code" |
| Gate rule built on a dead premise | engine CODEMANIFEST :134-135, compliance.py:73-74 | Hardcoded rendered values are correct (new inputs → new address → fresh generation, never a stale replay) | Rule blocks hardcoded values as a HIGH adequacy finding and demands `step_inputs["vars"]` reads — "cannot replay with new inputs" is false under rendered-sentence addressing |
| Manifest annotation contradicts cache contract | engine CODEMANIFEST :147 | Fixed-form step code receives exactly the page | Annotation additionally grants the `step_inputs` context global to step code |
| Self-contradictory user doc | docs/reference/step-cache.md:26-27 vs :42-45 | One semantics of the cached step | "different values, different steps, no cross-value replay" followed by "cached code tracks the live page instead of the values baked into its address" |
| Latent replay defect | execution.py:15,42 | Same address ⇒ same behavior | A plain sentence and a template rendering the identical text share one address; the context-reading cached code KeyErrors on the plain replay (empty `vars`) — e.g. `Open https://youtube.com` vs `Open {{ vars.url }}` |

## Trace Graph

```
render ──► PreparedStep ──► instruction (rendered values) ──► LLM request (STEP/INPUTS)
                 │
                 └────────► addressing_text ──► identity ──► cache file (value pinned)
                                              (static value source)

bind_step_inputs ──► ContextVar ──► namespace["step_inputs"] ──► generated code reads
   (dynamic value source) ──────────────── conflicts with ──── (address already pins values)
```

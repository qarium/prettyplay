# [ARCHITECTURE_PLAN]

## Topic

**step-cache-addressing** — the step cache addresses steps by the rendered sentence (addressing text) and cleans its
working scope on close.

Plan path: `.goga/history/2026/fix-step-cache/arch.md` (topic `.goga/history/2026/fix-step-cache/`).

All six cells are **modifications of existing cells** — no cell is created anew (per Artifact Resolution of
`[PRIMARY_ANALYSIS_REPORT]`). The sections below specify each modification as a precise diff against the current CODEMANIFESTs. They include
the complete replacement text for each changed algorithm and description.

## Implementation Order

1. **`prettyplay/cache`** — leaf among the modified cells (its Imports — `prettyplay/config`, `prettyplay/reporting` —
   are untouched). Defines the addressing primitives every upper cell consumes: the single NFC + trim normalization,
   the identity source, the touched set and `sweep_untouched`.
2. **`prettyplay/engine/renderer`** — depends only on untouched `prettyplay/failures`. Produces the addressing text
   inside `PreparedStep` that the executor, recovery and steering consume.
3. **`prettyplay/engine`** — depends on cache and renderer. The generation and regeneration paths carry the
   verbatim addressing text into each newly constructed `CachedStep`.
4. **`prettyplay/engine/steering`** — depends on cache, renderer and engine. Its guided write-back carries the
   verbatim addressing text into `CachedStep`.
5. **`prettyplay/engine/groups`** — depends on cache, renderer and engine (+ untouched polling, llm, driver,
   reporting, config, failures). Fresh row identities from the re-rendered addressing text.
6. **`prettyplay` (facade)** — the root; depends on all of the above. The `cleanup` parameter, the close-time sweep
   orchestration and the executor identity switch land last.

Documentation riders (not cell artifacts, ride with implementation): `docs/reference/step-cache.md`,
`docs/guides/writing-steps.md`, and any other user-doc page still stating the old addressing or the accepted
limitation — restate the addressing table, remove the limitation passage, document `cleanup` and the
purge-after-upgrade note (source wording: the updated cell usages `addressing.md`, `storage.md`, `lifecycle.md`,
`steps.md`).

## Artifacts

### 1. `prettyplay/cache` (modify)

**CODEMANIFEST `prettyplay/cache/CODEMANIFEST`:**

- Header → `Annotations`: **delete** the paragraph
  «Step identity stays on the original template sentence: … runtime values never enter the address.»; **add** after
  the «Step identity is intentional…» paragraph:

  ```
  Step identity is built from the addressing text — the rendered sentence with interpolations substituted and active capture tags verbatim; a plain sentence addresses as itself; exact-text equality unifies a plain sentence and a template producing the same text. One verbatim normalization serves every addressing text: case and internal whitespace are significant, because rendered values are data.
  The cache is a per-test working set by default: the store accumulates the addresses it successfully loaded or saved, and the close-time sweep deletes the untouched files of its cache key in its scope — best-effort, logged, never raising.
  ```

  **append** to the RunBudgets paragraph: « Budgets follow the addressing: a re-rendered identity draws a fresh
  budget.»
- Body → `normalize_step_text`: **replace** the whole annotation:

  ```yaml
  annotations: |
    Normalize an addressing text for identity and addressing — one verbatim rule for every text.

    `text`: the addressing text of the step — the rendered sentence; a plain sentence addresses as itself.
    `normalized`: the normalized addressing text.

    Algorithm:
    1. Apply Unicode NFC normalization
    2. Trim leading and trailing whitespace — nothing else

    Requirements:
    - Pure function: no I/O, no locale dependence, deterministic on `text` alone
    - Case and internal whitespace are significant: «Click Sign in» and «click  sign in » are different steps — rendered values are data
    - Exact-text equality unifies: a plain sentence and a template producing the exact same text share one address

    Constraints:
    - No casefold, no internal whitespace collapse, no template-marker detection
  ```

- Body → `StepIdentity`: **replace** the `normalized_text` param line with
  «`normalized_text`: the step's addressing text after `normalize_step_text` — the rendered sentence,
  verbatim-normalized.» and the property text with «The normalized addressing text of the step — the rendered
  sentence after NFC + trim.» (triple and `filename` algorithm unchanged).
- Body → `CachedStep` → Requirements: **add** the bullet
  «- The metadata sentence field carries the step's addressing text — the rendered sentence with actual values;
  rendered values on disk are accepted by the design, the security posture is a deferred question». Its signature
  **becomes** `"CachedStep(identity: StepIdentity, addressing_text: str, code: str, created_at: str)"`; add the
  `addressing_text` parameter and property (`"addressing_text -> str"`) as the verbatim rendered sentence before
  NFC and trim. Require `normalize_step_text(addressing_text) == identity.normalized_text` for every newly built
  cached step. The load path may restore legacy files whose `STEP_TEXT` already contains the normalized sentence.
- Body → `StepCache`: **replace** the first annotation line with
  «The repository store of cache steps: addressing, atomic writes, the read-only mode — and the per-test
  working-set lifecycle: the touched-address accumulation and the close-time sweep.» and **add** Requirements:

  ```
  - A successful load or save records the step's file name in the touched set — the object's working set; a miss, a damaged entry, a skipped or a failed write touch nothing
  - The touched set lives in the memory of the running process, one per StepCache instance — it never persists
  ```

  - `load` Algorithm: **add** step 4 «A successful reconstruct records the identity file name in the touched set; a
    miss or a damaged entry records nothing». Validate `STEP_TEXT` by normalizing its value and comparing it with
    `identity.normalized_text`; restore that value as `CachedStep.addressing_text` so the saved metadata is preserved.
  - `save` Algorithm step 6: **extend** to «Report on_cache_saved with the file name on success; a stored write
    records the file name in the touched set, a skipped or failed one records nothing». Serialize `STEP_TEXT` from
    `step.addressing_text`, while deriving the file name from `step.identity` as before.
  - **add** the new method block (after `save`):

  ```yaml
    "sweep_untouched(cache_key: str) -> removed: list[str]": |
      Delete the untouched step files of one cache key in this store's scope — the per-test working-set cleanup.

      `cache_key`: the context key of the owning test object — the sweep considers only files whose metadata carries it.
      `removed`: the file names deleted by this call.

      Algorithm:
      1. The scope is the effective root plus the object's subdirectory
      2. Enumerate every step file in the scope
      3. Read the metadata fields: unreadable metadata — log a WARNING and skip the file, its ownership is unprovable in a possibly shared root; a cache_key other than `cache_key` — skip silently
      4. A file name present in the touched set survives; every other file of this key is deleted, one log record per deletion naming the file
      5. A per-file failure — reading or deleting — logs a WARNING and continues with the next file

      Requirements:
      - Never raises: the sweep is best-effort hygiene and must never fail the closing test
      - Idempotent: a repeated call deletes nothing new — the survivors are touched files, other keys' files and unreadable ones
      - Untouched legacy files of this key are swept by the first call after the upgrade
      - The method knows nothing of the cleanup switch — the caller decides whether to sweep

      Constraints:
      - Deletions are log records only — no hook event, a deferred contract decision
      - No address recomputation: the file name is the address — the sha256 of the triple; the touched set and the directory names share one key space
  ```

- Body → `RunBudgets` → Requirements: **add** the bullet
  «- The identity key is `StepIdentity`; budgets follow the addressing — a step re-rendered against changed memory is
  a different identity and draws a fresh budget» (replacing the plain identity-key bullet).
- Footer → `Description`: **replace** with
  «The step cache of prettyplay: one verbatim normalization of addressing texts (the rendered sentence; NFC + trim),
  deterministic addressing by the addressing text, atomic repository storage, the per-test working-set lifecycle —
  touched-address accumulation and the close-time sweep — and the per-test attempt budgets, the group recovery cycle
  accounting.»

**`.usages/` files:**

- `prettyplay/cache/.usages/addressing.md` — **rewrite** (full content):

```md
# Step addressing

Domain: step identity and addressing of the cache. Audience: engineers reasoning about step reuse and inspecting the repository cache.

## Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | the addressing text — the rendered sentence — after NFC + trim | «Click Sign in» and «click  sign in » are different steps; a plain sentence and a template producing the exact same text are one step |

A missing cache entry for the computed address is a cache miss — the step is generated, not an error.

## The addressing text

Steps address the cache by their rendered sentence — the addressing text:

- `{{ ... }}` interpolations substitute the actual values from vars and memory — different values, different steps, no cross-value replay
- an active `{% var name %}` capture tag stays in the addressing text verbatim — `Read {% var a %}` and `Read {% var x %}` are different steps
- a capture tag inside an inactive branch contributes nothing — it disappears with the branch
- a plain sentence addresses as itself

```python
# one template — two renderings against different memory — two steps:
t.step("Open the item named {{ name }}")   # name = "Book" → addresses as "Open the item named Book"
t.step("Open the item named {{ name }}")   # name = "Film" → addresses as "Open the item named Film"
```

Case and internal whitespace are significant: rendered values are data («Sign in» and «sign In» are different buttons).

## Normalize and address

```python
from prettyplay.cache import StepIdentity, normalize_step_text

normalized = normalize_step_text("  Click Sign In ")
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalized,
)
# identity.filename — the deterministic digest of the triple
```

## Layout

The cache root defaults to <cwd>/.prettyplay/cache/ — the working directory of the run — and is set by cache_root. The optional subdirectory argument is part of the address: steps never leak across subdirectories; without a subdirectory, equal cache keys are reused across tests. One .py file per step.
```

- `prettyplay/cache/.usages/storage.md` — **update**: replace the File-format sentence's metadata list with «(the
  step's addressing text — the rendered sentence with actual values — the cache key, the step type, the creation
  date)»; **insert** the new section before «Team workflow»:

```md
## The per-test working set

The cache is a per-test working set by default. The store accumulates the touched set — the file names of every step it successfully loaded or saved; misses, damaged entries and skipped or failed writes touch nothing. On close the owning test object sweeps:

```python
removed = cache.sweep_untouched(cache_key="login-flow")
# deletes the untouched files of this cache key in this store's scope; returns their names
```

- the scope is this store's directory (cache root + subdirectory); only files whose metadata carries `cache_key` are considered — other tests' entries in a shared root survive
- a file with unreadable metadata is skipped with a WARNING — its ownership is unprovable
- deletions are log records, one per file; a per-file failure is logged and never raises; the call is idempotent
- `PrettyPlay(..., cleanup=False)` skips the sweep entirely — the persistence mode of the committed-cache workflow
```

  **replace** the Team-workflow section with:

```md
## Team workflow

Generate locally where the LLM is reachable → commit the cache directory → CI runs the whole suite from the cache with no LLM keys at all. Committed caches need `cleanup=False` on every generating and replaying run — a strict replay keeps the entries it replays (they are loaded, hence touched), so a committed strict run is self-preserving.

Upgrading across the addressing change: some existing addresses change. Purge the cache directory once after the upgrade — or let the first `cleanup=True` close sweep the untouched legacy files of each test's key out of its scope.
```

- `prettyplay/cache/.usages/budgets.md` — **add** one bullet under «Semantics»:
  «- The identity key follows the addressing: the same template re-rendered against changed memory is a different
  identity and draws a fresh budget»

### 2. `prettyplay/engine/renderer` (modify)

**CODEMANIFEST `prettyplay/engine/renderer/CODEMANIFEST`:**

- Header → `Annotations`: the `jinja` line **extends** with «, the addressing render»; the first paragraph **extends**
  with «…instruction with capture declarations **and the addressing text of the step**…»; «the instruction is plain
  text» → «both texts are plain text»; the last paragraph **replaced** by
  «The prepared instruction is the single text every LLM request and every raised failure carries for a step; the
  addressing text — the second text of the same render — is the addressing artifact the caller builds the cache
  identity from.»
- Body → `PreparedStep`: signature **becomes**
  `"PreparedStep(instruction: str, addressing_text: str, inputs: dict[str, str], declarations: list[str])"`;
  annotation **adds** the param
  «`addressing_text`: the addressing text — the same rendered sentence with actual values embedded and the reached
  capture tags kept verbatim; what the caller builds the cache identity from.» and the Requirement
  «- Both texts observe one snapshot and one set of branch decisions — they never disagree about a value or a branch»;
  the `instruction` param/property wording **gains** «, capture tags stripped»; **add** the property:

  ```yaml
    "addressing_text -> str": |
      The addressing text: the rendered sentence with actual values embedded and the reached capture tags kept verbatim; the addressing artifact the caller derives the step identity from.
  ```

- Body → `render_step`: `prepared` param line → «the render product — the instruction and the addressing text of one
  render»; Algorithm step 3 **replaced** by
  «Render: a reached capture tag records its name and renders to empty text in the instruction while its tag source
  stays in the addressing text; a duplicate name within one render fails as an authoring error; the reserved name
  `vars` and non-Jinja-identifier capture names fail as authoring errors»; Algorithm step 6 **replaced** by
  «Build and return `PreparedStep` — instruction (the tag-stripped rendered text), addressing_text (the rendered
  sentence keeping the reached capture tags verbatim), inputs (`vars`), declarations — one render produces both texts
  per the addressing render of `jinja`»; Requirements **add**
  «- The instruction and the addressing text come from one render: the same values, the same branch decisions — an
  inactive branch contributes neither declarations nor addressing-text tags».
- Footer → `Description`: **replace** with:
  «The step-sentence preparation of prettyplay: rendering Jinja step templates with the `{% var %}` capture extension from a snapshot of memory and call inputs into prepared instructions with input bindings and result declarations — carrying both texts of one render, the instruction and the addressing text — the per-test memory of captured observations with atomic publication, and the deterministic validation of returned step results.»

**`.usages/` files:**

- `prettyplay/engine/renderer/.usages/rendering.md` — **insert** after «Render a step»:

```md
## The addressing text

The same render produces a second text — the addressing text the cache identity is built from:

```python
prepared = render_step(
    text="For the item named {{ name }}, read its tags into {% var tags %}",
    step_type="action",
    memory=memory,
    vars=None,
)
prepared.instruction      # "For the item named Book, read its tags into " — tag-stripped
prepared.addressing_text  # "For the item named Book, read its tags into {% var tags %}" — tags verbatim
```

- `{{ ... }}` interpolations substitute the actual values in both texts — the addressing text carries real values, so different values address different steps
- a reached `{% var name %}` tag renders to empty text in the instruction and stays verbatim in the addressing text
- a tag inside an inactive branch contributes nothing to either text
- both texts observe one snapshot and one set of branch decisions — they never disagree
- substituted values are data and never re-rendered; `{% raw %}` blocks stay literal in both texts
```

- `memory.md`, `validation.md` — no changes.

### 3. `prettyplay/engine` (modify)

**CODEMANIFEST `prettyplay/engine/CODEMANIFEST`:**

- Body → `StepGenerator.generate` and `StepGenerator.regenerate`: extend the `prepared` parameter annotation with
  «The `addressing_text` of `prepared` is carried unchanged into every newly constructed `CachedStep`; its
  `identity.normalized_text` is the NFC+trim normalization of that text». At the accepted-candidate step of each
  Algorithm, require construction of `CachedStep` with `addressing_text=prepared.addressing_text` before save.
  The same rule applies to a generated candidate accepted during bounded healing.
- Body → `StepHealer.heal`: the generated replacement retains the `addressing_text` of the passed `prepared` render
  product through `StepGenerator.regenerate`; healing must not replace it with an old cached entry's metadata text.

**`.usages/` files:** none changed; the existing generation and healing examples still use the same facade API.

### 4. `prettyplay/engine/steering` (modify)

**CODEMANIFEST `prettyplay/engine/steering/CODEMANIFEST`:** the `steer` `identity` param line **replaced** by
«`identity`: the address of the stuck step, built by the executor from the addressing text of the render product —
the healed step is written back under it, and the successful write joins the test's touched set.» The accepted
guided write-back constructs `CachedStep` with `addressing_text=prepared.addressing_text` from the stuck step's
render product, so its `STEP_TEXT` metadata preserves that text verbatim. Specify this in the `steer` Algorithm
and the write-back Requirement; no signature changes.

**`.usages/` files:** none changed (`steering.md` verified clean of addressing statements).

### 5. `prettyplay/engine/groups` (modify)

**CODEMANIFEST `prettyplay/engine/groups/CODEMANIFEST`:**

- Header → `Imports`: in the `prettyplay/cache` entry the Types list **becomes** `StepCache, StepIdentity,
  normalize_step_text, CachedStep, RunBudgets` — the recover algorithm now references `normalize_step_text` when
  building the fresh row identity (verification fix; the edge itself is unchanged).
- Header → `Annotations`: in the honest-inputs paragraph the sentence «Raw template sentences remain available for
  row re-rendering and cache addressing.» **replaced** by «Raw template sentences remain the re-render source of the
  row mechanics; the re-rendered addressing text builds each row step's fresh cache identity.»; the recovery
  re-render paragraph **appended** with «The fresh render's addressing text builds the row step's fresh identity,
  which keys the healing refresh, the regeneration and the cache write-back.»
- Body → `GroupStepOutcome`: `identity` param **replaced** by
  «`identity`: the cache address of the step at its execution — recorded by the executor when the trace is appended;
  the row mechanics take only the cache_key from it and re-derive the address from the re-rendered addressing text;
  never rendered into the GROUP STEPS block.»; the `identity` property **replaced** by
  «The cache address recorded at the step's execution; the row re-render derives a fresh address — this record keeps
  the execution fact. Never rendered.»
- Body → `GroupRecovery.recover`: Algorithm step 4 **replaced** by «The row healing counters refresh inside the row
  loop — a fresh identity exists only after the re-render of step 5; every cycle still grants each row step a fresh
  full counter»; step 5 **replaced** by:

  ```
  5. The row — from the earliest affected step through the failed step, the group's own steps only — sequentially: the step's declared delay passes quietly; re-render the step through `render_step` from Imports — the trace's sentence, step type, recorded vars and the current `memory` produce a fresh `PreparedStep` against the current context; build the fresh identity from the fresh render's addressing text — `normalize_step_text`, then `StepIdentity` with the trace identity's `cache_key` and the step type; refresh the step's healing counter via budgets refresh_healing for this cycle; the step regenerates via the generator regenerate carrying the fresh prepared step, the diagnosis recommendation, the group framing per `group_framing`, the recovery-local scenario view, the grown attempt history, the step's own window built from its declared tries and the fresh identity, and `memory`; the candidate executes immediately on the current page inside the regeneration loop; the returned result validates; the two-dimension compliance gate guards the write-back; the captures publish through `memory` at the step's acceptance; the cache stores the step under the fresh identity; update that step occurrence's instruction in the local scenario and trace views before the next row request; report on_healing_started and on_healed for the recovered step; a structured log record names the diagnosis and the row composition
  ```

  Step 6 **replaced** by:

  ```
  6. A repeat failure of a row step — an `IncurableStepError` from regeneration — updates the active failure to that row occurrence's fresh `PreparedStep`, step type, fresh identity, grown row attempt history and underlying error; mark that occurrence failed in the local trace view, preserving its freshly prepared instruction. Then re-enter a fresh diagnosis and cycle from step 1 with those facts, while cycles remain. The caller's stored traces and scenario records are not rewritten
  ```

  Requirements **add** «- A row step's re-rendered identity is the address of its regeneration and write-back —
  the recovery never writes a row step under a stale trace identity».
- Footer → `Description`: **replace** with:
  «The group recovery of prettyplay: the group-level diagnosis request over the whole interaction, the group-scoped affected row with per-step re-rendering against the current context — addressed by the re-rendered addressing text — sequential regeneration and immediate forward re-execution, the compliance-gated per-step cache write-back with capture publication at each acceptance, and the bounded recovery cycles with fresh healing counters per cycle.»

**`.usages/` files:**

- `prettyplay/engine/groups/.usages/recovery.md` — **add** one bullet at the end of «Memory and re-render»:

```md
- The re-rendered addressing text re-addresses every row step: the regeneration, the healing-counter
  refresh and the cache write-back key on the fresh identity — a row step re-rendered against changed
  memory is a new address with a fresh budget
```

### 6. `prettyplay` (facade) (modify)

**CODEMANIFEST `prettyplay/CODEMANIFEST`:**

- Header → `Annotations`:
  - «Honest inputs thread end to end…» paragraph: «the raw step sentence establishes cache identity and supports
    re-rendering» **replaced** by «the addressing text of the render product establishes the cache identity; the raw
    sentence is the render and re-render source».
  - The authoring-surface paragraph tail «template sentences address the cache by their source and render to prepared
    instructions every request carries» **replaced** by «sentences render to prepared instructions every request
    carries, and their rendered form — the addressing text — addresses the cache».
  - The scenario-records paragraph **replaced** by «The scenario records carry both texts: the raw sentence and the
    prepared instruction (what requests render); failures carry the prepared instruction; the addressing text — the
    second render product — addresses the cache and takes no part in requests.»
  - **add** the new paragraph after it:
    «The cache lifecycle lives on the facade: the keyword-only `cleanup` constructor parameter — default True — makes
    close() delete the untouched step files of this test's cache key in its cache scope; cleanup=False keeps every
    file, the persistence mode of the committed-cache workflow. There is no config, env or pyproject surface for the
    switch.»
- Body → `PrettyPlay`: signature **becomes**
  `"PrettyPlay(cache_key: str, cache_path: str | None, cleanup: bool, hooks: list[StepHooks] | None, config: PrettyConfig | None)"`;
  annotation **adds** the param
  «`cleanup`: keyword-only — the cache lifecycle switch, default True: close() deletes the untouched step files of
  this test's cache key in its cache scope (the per-test working set); False keeps every file — the persistence mode
  of the committed-cache workflow.»; `close()` annotation **replaced** by:

  ```
      Close the test page context and stop the whole runtime of this test — the browser process, the Playwright driver and the driver thread; then, when `cleanup` is on, sweep the cache. Idempotent; the context manager exit does the same.

      Algorithm:
      1. Stop the runtime teardown as today — idempotent
      2. When `cleanup` is on, run the cache sweep with this test's `cache_key` — best-effort, guarded: any unexpected sweep error is caught and logged, never raised, never masking the teardown; a repeated close sweeps again and deletes nothing new; deletions are log records
  ```
- Body → `StepExecutor.execute`: Algorithm step 2 — the sentence «Build the step identity from the ORIGINAL
  `step_text`: `normalize_step_text`, then `StepIdentity`…» **replaced** by «Build the step identity from the render
  product's addressing text: `normalize_step_text` on the addressing text, then `StepIdentity` with the test cache
  key and the step type» (and the render clause gains «with the instruction and the addressing text»); the
  Requirement «The raw step sentence builds the step address; … the casefolded normalization is an addressing key
  only» **replaced** by «The addressing text of the render product builds the step address; the prepared instruction
  reaches every engine call; the verbatim NFC+trim normalization is an addressing key only».
- Footer → `Description`: **replace** with:
  «The facade of prettyplay: the per-test scenario object with screenshot abilities and the author escape hatch onto the genuine page, the step cycle executor as the render point of step templates — building the step identity from the addressing text — with the per-test memory and atomic capture publication, the strict replay-only path, the per-step attempt history and the honest-inputs threading, verdict reporting, the per-test composition root, the keyword-only cleanup switch and the close-time cache sweep, the re-exported settings models — PrettyConfig and BrowserConfig, the step parameters (tries, delay, vars), the group authoring block and the group recovery routing.»

**`.usages/` files:**

- `prettyplay/.usages/lifecycle.md` — **insert** after «Composition»:

```md
## Cache lifecycle on close

The step cache is a per-test working set by default: `close()` deletes every step file of this
test's `cache_key` in its cache scope that the test did not successfully load or save — best-effort,
logged, never failing the close. Replayed and freshly generated steps survive (they were touched);
strict replays keep what they replay.

```python
test = PrettyPlay("login-flow", cleanup=False)  # keep the cache directory after close
```

- `cleanup` is a keyword-only constructor parameter, default `True`; there is no config or env switch
- the sweep scope is this test's cache directory filtered by its `cache_key` — other tests' entries
  in a shared root survive; a file with unreadable metadata is skipped with a WARNING
- committed-cache workflow (generate locally, commit, replay in CI): pass `cleanup=False` on every
  run — a committed strict run is self-preserving (replayed entries are loaded, hence touched)
- upgrading across the addressing change: purge the cache directory once, or let the first default
  close sweep the untouched legacy files of each test's key
```

- `prettyplay/.usages/steps.md` — **replace** the section «Cache and replay limitation» with:

```md
## Cache addressing and replay

- Steps address the cache by their rendered sentence: `{{ name }}` interpolations substitute the
  actual values from memory and vars, so the same template with different values is a different
  step — no cross-value replay
- Active `{% var name %}` capture tags stay in the address verbatim — `Read {% var a %}` and
  `Read {% var x %}` are different steps; a tag inside an inactive branch contributes nothing
- Case and internal whitespace are significant in the address: «Click Sign in» and
  «click  sign in » are different steps; a plain sentence and a template producing the exact same
  text share one step
- The instruction sent to the LLM keeps the tag-stripped render — unchanged
- By default the cache is a per-test working set: close() deletes the untouched entries of this
  test; pass `cleanup=False` to keep the directory
```

  «Addressing» section: **prepend** «The step's address is built from its rendered sentence (the addressing text); a
  template rendered with different values is a different step.»; «The honest step context» tail: «cache addressing
  uses the original template source» **replaced** by «cache addressing uses the rendered sentence (the addressing
  text)».

## Dependency Map

```
config ──(Config)──> cache <──(StepReporter, hooks)── reporting
failures ──(PrettyplayError, taxonomy)──> renderer
cache ──(StepCache, StepIdentity, normalize_step_text, RunBudgets)──> facade
cache ──(StepCache, StepIdentity, normalize_step_text, CachedStep, RunBudgets)──> groups
cache ──(StepCache, StepIdentity, CachedStep)──> steering
renderer ──(PreparedStep[+addressing_text], StepMemory, render_step, validate_step_result; usages rendering/memory/validation)──> facade, groups, steering, engine
engine ──(StepGenerator, StepHealer, StepAttempt, run_step_code, …; usages generation/healing)──> facade, groups, steering
polling ──(SettleWindow, settle)──> facade, groups
groups ──(GroupRecovery, GroupStepOutcome; usage recovery)──> facade
steering ──(StepSteering)──> facade
llm/driver/config/reporting/failures ──> facade (unchanged edges)
```

New edges: **none**. Payload changes travel inside existing types (`PreparedStep.addressing_text`) and one new
method call (`PrettyPlay.close() → StepCache.sweep_untouched(cache_key)`) over the existing facade → cache edge.

## Verification Checklist

After implementing each artifact:

1. **`prettyplay/cache`** — `goga lint` clean; `normalize_step_text` is NFC + trim only (no casefold, no collapse, no
   marker detection — property tests: «Click Sign in» ≠ «click  sign in », plain == identical render, `{{ name }}` vs
   `{{ Name }}` in the *addressing text* domain differ only when their rendered values differ); `sweep_untouched`:
   touched files survive, foreign `cache_key` files survive, unreadable metadata skipped with WARNING, per-file
   failure logged and swallowed, repeat call is a no-op, never raises (tests via `tmp_path` per `conventions`);
   metadata sentence = the addressing text; unit + edge tests for the touched set (success-only marking: miss,
   damaged, skipped, failed write).
2. **`prettyplay/engine/renderer`** — one render produces both texts from one snapshot: same values, same branch
   decisions; active `{% var x %}` verbatim in the addressing text, inactive branch contributes nothing to either
   text; `{% raw %}` literal in both; instruction byte-identical to the old render (regression); authoring errors
   unchanged and raised before any browser execution; pydantic kw_only with empty defaults.
3. **`prettyplay/engine`** — every successful generation and regeneration saves a `CachedStep` carrying the
   prepared render's verbatim addressing text; healing preserves the current render's text.
4. **`prettyplay/engine/steering`** — the guided write-back saves the stuck render's verbatim addressing text and
   marks the touched set through `StepCache.save`.
5. **`prettyplay/engine/groups`** — the row loop builds the fresh identity after the re-render; `refresh_healing`
   keyed by the fresh identity once per cycle per row step; write-back under the fresh identity; re-render authoring
   errors still loud; no stale-trace-identity writes; fresh budget for a changed-memory re-render.
6. **`prettyplay` (facade)** — `PrettyPlay("key")` defaults `cleanup=True`; `PrettyPlay("login-flow", cleanup=False)`
   deletes nothing; `close()` = idempotent teardown then guarded sweep; the sweep never masks/breaks teardown;
   repeated `close()` safe; the executor builds the identity from `prepared.addressing_text`; committed strict replay
   keeps its entries; no `PrettyConfig`/env/pyproject change (`prettyplay/config` untouched).
7. **Docs riders** — `docs/reference/step-cache.md` and `docs/guides/writing-steps.md` (+ any page stating the old
   limitation) match the updated cell usages; the «accepted limitation» passage is gone; the purge-after-upgrade note
   present.
8. **Whole project** — `pytest tests/ -x` green (new tests: normalization, addressing render, touched set, sweep,
   the flag — filesystem via `tmp_path`); `ruff check prettyplay/` clean; `goga lint` clean on all six cells.

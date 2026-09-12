# Step cache

Step identity, cache storage and attempt budgets. For engineers reasoning
about step reuse, inspecting the repository cache and tuning budgets.

The cache is a repository artifact: one `.py` file per step, addressed
deterministically; the cache is always read, writes are best-effort.

## Addressing

### Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | NFC, trim, whitespace collapse, casefold | «Click Sign in» equals «click  sign in »; a Russian sentence and its English translation are different steps |

A missing cache entry for the computed address is a cache miss — the step is
generated, not an error.

### Normalize and address

```python
from prettyplay.cache import StepIdentity, normalize_step_text

normalized = normalize_step_text("  Click   Sign In ")
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalized,
)
# identity.filename — the deterministic digest of the triple
```

### Layout

The cache root defaults to `<repo root>/.prettyplay/cache/` and is set by
`cache_root`. The optional `cache_path` subdirectory argument is part of the
address: steps never leak across subdirectories; without a subdirectory, equal
cache keys are reused across tests. One `.py` file per step.

## Storage

### Read and write

```python
from prettyplay.cache import CachedStep, StepCache
from prettyplay.config import Config
from prettyplay.reporting import StepReporter

cache = StepCache(config=Config(), path="checkout", reporter=StepReporter(hooks=[]))

step = cache.load(identity)  # None on a cache miss
if step is None:
    # a miss means: generate the step, then store it
    cache.save(CachedStep(identity=identity, code=step_code, created_at="2026-09-07"))
```

### File format

Each file carries the metadata fields (step sentence, cache key, step type,
creation date) followed by the generated step code of the fixed form (see
[Driver facade](driver-facade.md)). Files carry no library version and are
never invalidated by a library upgrade.

### Write behavior

- `save` never fails the run: a read-only cache or a busy Windows target
  skips the write loudly
- writes are atomic: a unique temporary file in the target directory, then an
  atomic replace; the last writer wins, a partial file never becomes visible
- `load` always works, in every environment

## Attempt budgets

Generation and healing attempts are budgeted per step per test.

### Consume attempts

```python
from prettyplay.cache import RunBudgets

budgets = RunBudgets(generation_limit=3, healing_limit=2)

if budgets.try_generation(identity):
    ...  # attempt allowed; False — budget exhausted, the caller reports incurability
```

### Semantics

- Budgets are per step per test: every test owns its registry and starts with
  full limits — a step reused across tests gets a fresh budget in each test
  (N tests running one step in a process spend N × attempts in total)
- Defaults: 3 generation attempts, 2 healing attempts — configurable via
  `generation_attempts` / `healing_attempts` in the project settings
- An exhausted budget is the incurable failure, never an infinite loop
- Budgets exist only in the memory of the running process — nothing is
  persisted

## Team workflow and CI

Generate locally where the LLM is reachable → commit the cache directory → CI
runs the whole suite from the cache with no LLM keys at all — `strict = true`
turns that posture into a guarantee: a cache miss fails the run instead of
silently generating. See [Configuration](../configuration.md).

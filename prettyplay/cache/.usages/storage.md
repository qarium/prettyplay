# Cache storage

Domain: reading and writing the step cache. Audience: engineers inspecting cache files and building tooling around the store.

## Read and write

```python
from prettyplay.cache import CachedStep, StepCache
from prettyplay.config import Config
from prettyplay.reporting import StepReporter

cache = StepCache(config=Config(), path="checkout", reporter=StepReporter(hooks=[]))

step = cache.load(identity)  # None on a cache miss
if step is None:
    # a miss means: generate the step, then store it
    cache.save(
        CachedStep(
            identity=identity,
            addressing_text="open the login page",  # the rendered sentence, verbatim
            code=step_code,
            created_at="2026-09-07",
        )
    )
```

## File format

Each file carries the metadata fields (the step's addressing text — the rendered sentence with actual values — the cache key, the step type, the creation date), then the `# --- step code ---` sentinel line, then the generated step code — top-level imports when present, then the fixed-form `def step` function, restored verbatim on load. Files carry no library version and are never invalidated by a library upgrade.

## Write behavior

- save never fails the run: a read-only cache or a busy Windows target skips the write loudly — save returns whether the step was stored (False on a skip; the on_cache_skipped hook carries the reason)
- writes are atomic: a unique temporary file in the target directory, then an atomic replace; the last writer wins, a partial file never becomes visible
- load always works, in every environment

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

## Team workflow

Generate locally where the LLM is reachable → commit the cache directory → CI runs the whole suite from the cache with no LLM keys at all. Committed caches need `cleanup=False` on every generating and replaying run — a strict replay keeps the entries it replays (they are loaded, hence touched), so a committed strict run is self-preserving.

Upgrading across the addressing change: some existing addresses change. Purge the cache directory once after the upgrade — or let the first `cleanup=True` close sweep the untouched legacy files of each test's key out of its scope.

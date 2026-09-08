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
    cache.save(CachedStep(identity=identity, code=step_code, created_at="2026-09-07"))
```

## File format

Each file carries the metadata fields (step sentence, cache key, step type, creation date) followed by the generated step code of the fixed form. Files carry no library version and are never invalidated by a library upgrade.

## Write behavior

- save never fails the run: a read-only cache or a busy Windows target skips the write loudly
- writes are atomic: a unique temporary file in the target directory, then an atomic replace; the last writer wins, a partial file never becomes visible
- load always works, in every environment

## Team workflow

Generate locally where the LLM is reachable → commit the cache directory → CI runs the whole suite from the cache with no LLM keys at all.

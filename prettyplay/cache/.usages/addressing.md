# Step addressing

Domain: step identity and addressing of the cache. Audience: engineers reasoning about step reuse and inspecting the repository cache.

## Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | NFC, trim, whitespace collapse, casefold | «Click Sign in» equals «click  sign in »; a Russian sentence and its English translation are different steps |

A missing cache entry for the computed address is a cache miss — the step is generated, not an error.

## Normalize and address

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

## Layout

The cache root defaults to <repo root>/.prettyplay/cache/ and is set by cache_root. The optional subdirectory argument is part of the address: steps never leak across subdirectories; without a subdirectory, equal cache keys are reused across tests. One .py file per step.

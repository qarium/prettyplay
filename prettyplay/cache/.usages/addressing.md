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

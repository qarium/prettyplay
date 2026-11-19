# Step addressing

Domain: step identity and addressing of the cache. Audience: engineers reasoning about step reuse and inspecting the repository cache.

## Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step; replaced by the scope for a scoped step (see below) |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | the addressing text — the rendered sentence — after NFC + trim | «Click Sign in» and «click  sign in » are different steps; a plain sentence and a template producing the exact same text are one step |
| scope | the `_scope` of the step call or the group block | non-empty — the shared cache namespace of one page object: the scope becomes the key part of the address and routes the file to root/<scope>/; empty — unscoped, exactly the old triple |

A missing cache entry for the computed address is a cache miss — the step is generated, not an error.

## The addressing text

Steps address the cache by their rendered sentence — the addressing text:

- `{{ ... }}` interpolations substitute the actual values from vars and memory — different values, different steps, no cross-value replay
- an active `{% var name %}` capture tag stays in the addressing text verbatim — `Read {% var a %}` and `Read {% var x %}` are different steps
- a capture tag inside an inactive branch contributes nothing — it disappears with the branch
- a plain sentence addresses as itself

```python
# one template — two renderings against different memory — two steps:
t.step("Open the item named {{ name }}")  # name = "Book" → addresses as "Open the item named Book"
t.step("Open the item named {{ name }}")  # name = "Film" → addresses as "Open the item named Film"
```

Case and internal whitespace are significant: rendered values are data («Sign in» and «sign In» are different buttons).

## The step scope

A scope is the shared cache namespace of one page object — the integrator layer sets it once per block:

```python
t.step("open the dashboard", _scope="pages/dashboard")          # per step on the facade
g = t.group("the user signs in", _scope="pages/login_page")     # once per block — inherited by every step
```

- For a scoped step the scope replaces exactly two things: the key part of the address (key = the scope) and
  the file routing (`root/<scope>/`); the full address stays (key, step type, normalized sentence)
- One step phrase under one scope is one cache entry for all tests: the first test generates through the LLM,
  the rest reuse the file without a model call; unscoped steps address exactly as before — no collisions
- The same phrase as an action and as an assertion remains two entries even under one scope
- The scope never enters the rendered sentence or the LLM requests — it addresses and routes only
- The routing path never enters the digest file name: the scope already addresses the step, the path only routes
- Form: 1..N segments of `[A-Za-z0-9._-]+` joined by exactly one `/` (e.g. `pages/login_page`); an invalid
  value fails loudly at the call naming `_scope`, the received value and the allowed form — the store
  re-enforces the same rule at addressing

## Normalize and address

```python
from prettyplay.cache import StepIdentity, normalize_step_text

normalized = normalize_step_text("  Click Sign In ")
identity = StepIdentity(
    cache_key="login-flow",
    step_type="action",
    normalized_text=normalized,
    scope="pages/login",  # empty — unscoped (the default); non-empty — the scope IS the address key
)
# identity.address_key — "pages/login" here, the cache key otherwise: the digest and the file metadata key on it
# identity.filename — the deterministic digest of (address_key, step_type, normalized_text)
```

## Layout

The cache root defaults to <cwd>/.prettyplay/cache/ — the working directory of the run — and is set by cache_root. The optional subdirectory argument is part of the address: steps never leak across subdirectories; without a subdirectory, equal cache keys are reused across tests. One .py file per step.

A scoped step routes to `root/<scope>/` — a subdirectory of the cache root; the optional subdirectory argument
of the store never applies to scoped steps. Unscoped steps keep the old layout: the root plus the store
subdirectory.

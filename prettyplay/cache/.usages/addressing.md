# Step addressing

Domain: step identity and addressing of the cache. Audience: engineers reasoning about step reuse and inspecting the repository cache.

## Identity triple

| Component | Source | Effect on identity |
|---|---|---|
| cache_key | the main object constructor argument | a different key — a different step |
| step type | action vs assertion | the same sentence as action and as assertion — two steps |
| normalized sentence | templates: NFC + trim (verbatim); ordinary: NFC, trim, whitespace collapse, casefold — a template addresses by its source; an ordinary sentence casefolds as before | «Click Sign in» equals «click  sign in »; a Russian sentence and its English translation are different steps |

A missing cache entry for the computed address is a cache miss — the step is generated, not an error.

## Template sentences

A sentence containing Jinja markers (`{{`, `{%` or `{#`) is a template step:

```python
normalize_step_text("Read the first item name into {% var name %}")
# NFC + trim only — case-sensitive names and expression whitespace stay significant
```

- `{{ name }}` and `{{ Name }}` are different steps — Jinja names are case-sensitive
- Two templates differing only by prose case or spacing do not share an entry — a fresh generation, never a wrong hit
- Runtime values never enter the address: the same template with different observed values reuses the same cached code, which re-reads captures on every execution

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

The cache root defaults to <cwd>/.prettyplay/cache/ — the working directory of the run — and is set by cache_root. The optional subdirectory argument is part of the address: steps never leak across subdirectories; without a subdirectory, equal cache keys are reused across tests. One .py file per step.

# Insecure TLS switch, site base URL, and the shared step scope

Three decisions of the new-reworks line. Together they remove three recurring
hardcodings of an integration suite: self-signed-certificate staging grids, the
address of the environment under test, and step code regenerated per test where a
page object should share it.

## D1 — `browser.ignore_https_errors`: a context parameter in every start mode

The browser group gains the boolean `ignore_https_errors` (default `false`), so
pages behind self-signed or invalid certificates (staging, CI grids) open. It is
applied as a context parameter — never a launch argument — which makes every start
mode identical: local launch, ws/wss remote connect (Playwright protocol), http/https
remote connect (CDP). Full configuration surface — TOML
`[tool.prettyplay.browser]`, env `PRETTYPLAY_BROWSER_IGNORE_HTTPS_ERRORS`,
programmatic config — participating in the layered merge like every browser-group
field. Enabling it is silent: an explicit configuration is not a suspicious state,
no WARNING is logged.

## D2 — `site.base_url`: one property for the author, no implicit Playwright wiring

A new nested `site` group holds the single `base_url` field — the root URL of the
environment under test, set once instead of being hardcoded in tests: TOML
`[tool.prettyplay.site]`, env `PRETTYPLAY_SITE_BASE_URL`, programmatic config. The
layered merge is symmetric to the browser group: an explicitly passed value wins,
an empty field never overwrites the file layer. Validation: a non-empty value must
be an http/https URL (scheme + netloc) or the loud `ConfigurationError` fires; empty
means unset. The value is kept verbatim — no trailing-slash normalization; the
author composes URL strings. Tests read it through the facade property
`site_base_url`.

The name does not collide with the top-level `base_url` (the LLM API endpoint): the
group scopes the field, exactly as the browser group scopes `name`.

### Considered options

Property only vs. wiring the value into `new_context(base_url=...)` so generated
code could navigate relatively and share cache entries across environments. The
wiring is rejected: it changes generated-code semantics and is a separate large
task — recorded as out of scope. Consequence of the accepted option: the absolute
URL the author renders into a sentence becomes part of the cache address, so
staging and production keep separate cache entries — accepted under the "rendered
values are data" principle.

## D3 — `_scope`: one shared cache entry per step phrase per page object

Steps gain the service keyword-only parameter `_scope` — the shared cache namespace
of one page object (for the integrator layer). It is accepted per step on the
facade `step`/`expect`, and once per block on `PrettyPlay.group(..., _scope=...)`,
inherited by every step of the group; it is not accepted per step inside a group —
the page-object layer sets it once at group creation.

A scope is a relative subdirectory of the cache root (`pages/login_page`); for the
scoped step it replaces exactly two things: the test cache key inside the address
and the file routing (`root/<scope>/`). The full address stays (key = the scope,
step_type, normalized_text after NFC+trim) — the same phrase as an action and as an
assertion remains two entries even under one scope. The routing path never enters
the digest file name: the scope already addresses the step, the path only routes.
One step phrase under one scope is one cache entry for all tests: the first test
generates through the LLM, the rest reuse it without a model call. Unscoped steps
address exactly as before — no collisions; `cache_path` remains the namespace of
the test's unscoped steps. Group membership changes neither a step's scope nor its
address — the group only passes its scope down.

The metadata key of a scoped file is the scope itself, so the close-time sweep of
any test (filtering by its own cache key) never touches scoped files: shared
entries survive every sweep, cleanup concerns only the test's unscoped steps.

### Validation: two rings

Ring 1 — at the call site, before any render or execution: the loud authoring
`PrettyplayError` naming the parameter, the received value and the allowed form.
The rule: 1..N segments of `[A-Za-z0-9._-]+` joined by exactly one `/`; forbidden —
the empty string, leading/trailing `/`, empty segments, any `..` segment, absolute
forms (leading `/`, `\`, `C:`), and every other character (spaces, non-ASCII).

Ring 2 — the same forbidden set re-enforced in cache addressing, so the address
cannot escape the cache root even by bypassing the facade. Ring 2 must reject
exactly the same set of values as ring 1 and may not be softer than the structural
bans already present in addressing (`_validated_subdir`: absolute paths and `..`
segments). The existing `cache_path` is not tightened retroactively — the strict
charset applies to the scope from birth only; symmetry holds at the level of "the
address never escapes the cache root", the asymmetry is the charset.

### Consequences

- Budgets follow the runtime, addressing follows the scope: budgets stay per test;
  the generating test pays from its own budget, a test hitting the shared file pays
  nothing; there is no shared "scope budget".
- Strict mode: a scoped-address miss is the same loud incurable "generation
  forbidden" failure; nothing scope-specific.
- Group recovery: a recovery row is re-addressed by the re-rendered text under the
  group's scope — the row identity carries both address parts (the scope); worth
  pinning with a test.
- Parallel generation: two tests missing the same scope both generate on their own
  budgets; the write stays atomic (mkstemp + os.replace), last writer wins, and the
  file stays valid for both — the read checks CACHE_KEY/STEP_TYPE and the digest
  name.

## Glossary

- **step scope (`_scope`)** — the shared cache namespace of one page object's
  steps: replaces the cache key in the address and routes the file to
  `root/<scope>/`.
- **cache scope** (pre-existing term) — the cache root plus the StepCache
  subdirectory, the boundary of the close-time sweep. Not to be confused with step
  scope.
- **site base URL** — the root http(s) URL of the environment under test, from
  config.
- **integrator** — the author of the page-object layer above the facade, the user
  of `_scope`.

## Open points

- The exact contract place of validation ring 2 inside the cache cell is left to
  the design stages; the constraint above (the same forbidden set as ring 1, never
  softer than the existing structural bans) already binds it.

# Project rules

## Bounded upstream mirroring

The real third-party API at the mirrored interaction level is the sole source of truth for which facade members exist and what they are called: invented facade-only names, and renames of the legacy surface made without checking what the upstream library actually provides, are rejected. Mirroring is scoped to the user-level interaction surface — upstream capabilities that mutate or observe state invisibly to the observable page-state model (script evaluation, network or protocol-level interception, tracing-style instrumentation) are permanently excluded, so the state model feeding failure classification and healing remains a truthful account of what step code did.

## Parity-first clean-break atomic landing

When a standing stability contract collides with parity, parity wins: a mirror member is renamed or removed only together with an upstream-level re-mapping, the old name simply stops acting, and breakage of previously cached consumers is accepted cost. The break stays pure — no backward-compatibility alias, no deprecation hint, no runtime warning directing users to the new name, no migration layer cushioning it. The change lands as one atomic change together with every artifact that describes or is generated from the surface — declarations, the contract manifest, cross-cell annotations and usage files, the machine-facing API listing and prompt, the configuration surface, and the published documentation — because a partial landing desynchronizes the real surface from what the code generator is told about it. Partial renames and artifacts that still carry a known-stale name are rejected, and the corrected change is re-issued for approval with the corrected form carried into all later work.

## Contour-fitting construct redesign

Upstream interaction models that cannot fit the step-code shape (one function of a single page argument, no imports), such as event subscriptions, are re-expressed as scoped capture constructs in the facade's own idiom that yield a wrapped object with explicit actions and readable properties. When such an explicit in-step construct and a global configuration setting can both govern the same situation, the explicit construct wins for the duration of its scope; the global setting applies only to cases no active explicit construct covers.

## Facade boundary purity

No raw object from the underlying library ever crosses the facade boundary: every object kind reachable from step code is wrapped in its own facade, and the driver's marshaling boundary covers every facade kind uniformly.

## Stateless multi-target interaction

Working with several concurrently live targets (windows, tabs, frames) never introduces hidden session state such as an "active target" that silently redirects subsequent actions; moving between targets is an explicit operation invoked on the target's own facade.

## Neutral defaults for new behavior settings

A newly introduced behavior-changing configuration setting defaults to the behavior that existed before the setting: the new behavior is strictly opt-in, and the outcomes of scenarios that no explicit setting touches are unchanged.

## Minimal generation-friendly surface growth

When the API is exercised by model-generated step text, the surface favors explicit, direction-named methods taking constrained positive-integer amounts over signed or encoded arguments, because a sign embedded in an argument is a source of generation errors and reads worse in generated propositions. The surface grows only when existing constructs cannot express the need: where exposed properties plus plain language-level assertions already express a check, no facade-specific expectation or convenience member is added. Growth is additive — existing call sites stay untouched.

## Contained exception boundary

Raw third-party or validation-framework exceptions never escape the library boundary: they are wrapped in a library-defined error type that derives from the library's single root error, so one except clause catches every library failure. The wrapper carries a human-readable diagnostic rendered per offending item and chains the original exception as its cause. Errors extending the project's base error are declared in the DSL as mutations via the `::` syntax from the base type, not as independent types; the error base is declared in the manifest of the taxonomy-owning cell.

## Loud failure over silent degradation

Invoking a capability before its precondition holds raises a loud, actionable failure telling the caller what to do first, rather than silently returning useless output; decisions that belong to the caller (such as when to capture artifacts) are never taken implicitly by the library, and explicit write operations surface their failures loudly.

## Single-source failure rendering

Structured failure or diagnostic text that must reach multiple surfaces (exception message, log record, event payload, hook payload) is composed exactly once, at the moment the failure object is constructed, and all downstream consumers reuse that one render instead of each composing its own variant. The components orchestrating the failing flow construct it; the outcome types never request or build it themselves; it is carried as one optional field on terminal outcomes, and when the enrichment source is unavailable the value is simply absent — a quiet skip that never delays or blocks the failure. The render itself stays minimal: it opens with a bare reason line free of internal labels, continues with delimited labeled blocks for the failing step and its error, omits blocks that have no content, aligns multi-line continuations to the value column, and excludes bulky context such as source code, which stays in the stores designed to hold it.

## Format-versus-registry validation split

Configuration-time validation covers only syntactic formats; semantics that depend on an external registry's vocabulary resolve in the driver at runtime against the live registry, so configuration never hardcodes a copy of a vocabulary it does not own.

## Replay-only strict execution

Strict mode never generates, heals, or consumes run budgets: a cache miss fails immediately, a failed cached step is only classified into its fixed error taxonomy, LLM availability is discovered by attempting the classification call itself (unavailability logs a warning and raises a step-type-determined error without a verdict), and no proactive provider probes are made.

## Provider-parity instruction injection

User-supplied classification instructions render as a clearly delimited block placed last in the user content, formatted identically for every provider, and appear only in classification requests — generation requests and caches stay unaffected.

## Self-contained current-state cell specifications

Contract and usage specifications describe only the present state of the system — what exists and how it behaves now — never narrating change history: no mentions of legacy names, renames, deprecated behavior, or what no longer works; a specification that references change history is reworked to describe the current state. They are fully self-contained: CODEMANIFEST and usage files reference no external project documents (ADRs, PRDs, task files), and every requirement is stated inside manifest annotations so the cell contract is readable and verifiable without consulting source documents. The observable-behavior contract (what the outside world must see) is specified on the type that carries it, while the mechanics that enforce that behavior are specified on the boundary methods that execute it — neither stated in both places nor left unspecified. Usage files are named after the functional domain they describe (not technical or abstract names); every cell carries, alongside conceptual descriptions, a usage file with ready code examples of calling its API, written in English only — sample data in any other natural language is not permitted — and the snippets demonstrate every facet of the public surface they document, including both commanding and verifying calls. Any modification to an already-approved fragment is re-approved as its own decision before work continues.

## Shared types go to a leaf cell to keep the DAG

Types needed by multiple cells (including the failure taxonomy for interrelated functions such as generation and healing) are extracted into a separate leaf cell imported by all consumers; mutual imports and cycles in the cell graph are not allowed.

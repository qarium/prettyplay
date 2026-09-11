# Project rules

## Initialism capitalization

Class and type names capitalize initialisms in full rather than folding them into CamelCase as ordinary words (for
example LLMUnavailableError), matching the initialism style already established across the project's contracts.

## Clean-break atomic renaming

When a public surface is renamed, the rename is pure: the old name simply stops acting, with no backward-compatibility
alias, no deprecation hint, and no runtime warning directing users to the new name. Any rename or user correction is
also propagated atomically, in a single change, to every artifact that references the name — declarations, cross-cell
annotations, and usage files — and the corrected artifact is re-issued for approval with the corrected form carried
into all later work. Partial renames, and publishing artifacts that still carry a known-stale name, are rejected.

## Single-source failure rendering

Structured failure or diagnostic text that must reach multiple surfaces (exception message, log record, event payload,
hook payload) is composed exactly once, at the moment the failure object is constructed, and all downstream consumers
reuse that one render instead of each composing its own variant. The components orchestrating the failing flow
construct it; the outcome types never request or build it themselves; it is carried as one optional field on terminal
outcomes, and when the enrichment source is unavailable the value is simply absent — a quiet skip that never delays or
blocks the failure. The render itself stays minimal: it opens with a bare reason line free of internal labels,
continues with delimited labeled blocks for the failing step and its error, omits blocks that have no content, aligns
multi-line continuations to the value column, and excludes bulky context such as source code, which stays in the
stores designed to hold it.

## Replay-only strict execution

Strict mode never generates, heals, or consumes run budgets: a cache miss fails immediately, a failed cached step is
only classified into its fixed error taxonomy, LLM availability is discovered by attempting the classification call
itself (unavailability logs a warning and raises a step-type-determined error without a verdict), and no proactive
provider probes are made.

## Format-versus-registry validation split

Configuration-time validation covers only syntactic formats; semantics that depend on an external registry's
vocabulary resolve in the driver at runtime against the live registry, so configuration never hardcodes a copy of a
vocabulary it does not own.

## Provider-parity instruction injection

User-supplied classification instructions render as a clearly delimited block placed last in the user content,
formatted identically for every provider, and appear only in classification requests — generation requests and caches
stay unaffected.

## Contained exception boundary

Raw third-party or validation-framework exceptions never escape the library boundary: they are wrapped in a
library-defined error type that derives from the library's single root error, so one except clause catches every library
failure. The wrapper carries a human-readable diagnostic rendered per offending item and chains the original exception
as its cause. Errors extending the project's base error are declared in the DSL as mutations via the `::` syntax from
the base type, not as independent types; the error base is declared in the manifest of the taxonomy-owning cell.

## Loud failure over silent degradation

Invoking a capability before its precondition holds raises a loud, actionable failure telling the caller what to do
first, rather than silently returning useless output; decisions that belong to the caller (such as when to capture
artifacts) are never taken implicitly by the library, and explicit write operations surface their failures loudly.

## Current-state-only specification

Contract and usage specifications describe only the present state of the system: they state what exists and how it
behaves now, and never narrate change history — no mentions of legacy names, renames, deprecated behavior, or what no
longer works. Any specification that references change history is reworked to describe the current state instead.

## Self-contained cell contracts

CODEMANIFEST and usage files must not reference external project documents (ADRs, PRDs, task files). Every requirement
is stated fully inside manifest annotations so the cell contract is readable and verifiable without consulting source
documents.

## Shared types go to a leaf cell to keep the DAG

Types needed by multiple cells (including the failure taxonomy for interrelated functions such as generation and
healing) are extracted into a separate leaf cell imported by all consumers; mutual imports and cycles in the cell graph
are not allowed.

## Domain-named usage files with exhaustive English code examples

Usage files are named after the functional domain they describe (not technical names like "api" or abstract ones), and
every cell has, alongside conceptual descriptions, a usage file with ready code examples of calling its API. Every code
example in consumer-facing usage documentation is written in English only; sample data in any other natural language is
not permitted, and affected examples are reworked across the project before approval. Usage-practice snippets
demonstrate every facet of the public surface they document — including both commanding and verifying calls — rather
than only the most common ones, and any modification to an already-approved fragment is re-approved as its own decision
before work continues.

## Contract–mechanics separation

The observable-behavior contract (what the outside world must see) is specified on the type that carries it, while the
mechanics that enforce that behavior are specified on the boundary methods that execute it; the split is explicit so
neither the contract nor the mechanics are stated in both places or left unspecified.

## Generation-friendly API surface

When the API is exercised by model-generated step text, the surface favors explicit, direction-named methods taking
constrained positive-integer amounts over signed or encoded arguments, because a sign embedded in an argument is a
source of generation errors and reads worse in generated propositions. Changes are additive: existing call sites stay
untouched, and the API listing and consumer documentation are extended in the same change.

## Derived accessor over composed fields

A type never accepts, as an independent constructor input, a field already carried by a composed value the type holds;
the public property is preserved but becomes derived from the composed value, with a fallback for when that value is
absent. One source of truth, public surface unchanged.

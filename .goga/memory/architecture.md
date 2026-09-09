# Project rules

## Current-state-only specification

Contract and usage specifications describe only the present state of the system: they state what exists and how it behaves now, and never narrate change history — no mentions of legacy names, renames, deprecated behavior, or what no longer works. Any specification that references change history is reworked to describe the current state instead.

## Domain-named usage files with English code examples

Usage files are named after the functional domain they describe (not technical names like "api" or abstract ones), and every cell has, alongside conceptual descriptions, a usage file with ready code examples of calling its API. Every code example in consumer-facing usage documentation is written in English only; sample data in any other natural language is not permitted, and affected examples are reworked across the project before approval.

## Clean-break renaming

When a public surface is renamed, the rename is pure: the old name simply stops acting, with no backward-compatibility alias, no deprecation hint, and no runtime warning directing users to the new name.

## Recorded deviation

A decision that deliberately overrides the upstream task or decision-record text is captured explicitly as the single deliberate deviation in the architecture plan, so divergence from the source requirement is always visible and never silent.

## Derived accessor over composed fields

A type never accepts, as an independent constructor input, a field already carried by a composed value the type holds; the public property is preserved but becomes derived from the composed value, with a fallback for when that value is absent. One source of truth, public surface unchanged.

## Contained exception boundary

Raw third-party or validation-framework exceptions never escape the library boundary: they are wrapped in a library-defined error type that derives from the library's single root error, so one except clause catches every library failure. The wrapper carries a human-readable diagnostic rendered per offending item and chains the original exception as its cause. Errors extending the project's base error are declared in the DSL as mutations via the `::` syntax from the base type, not as independent types; the error base is declared in the manifest of the taxonomy-owning cell.

## Unified optional diagnostic value

A diagnostic value that must reach multiple surfaces (exception text, event payload, log) is defined once with a single render shared by all surfaces, and carried as one optional field on terminal outcomes. The components orchestrating the failing flow construct it; the outcome types never request or build it themselves. When the enrichment source is unavailable, the value is simply absent — a quiet skip that never delays or blocks the failure.

## Shared routine for duplicated preparation

When several components in a module need identical input-collection or preparation logic, that logic is extracted into one shared routine owned by the module and invoked by each component, instead of being inlined and duplicated inside every component's own algorithm.

## Contract–mechanics separation

The observable-behavior contract (what the outside world must see) is specified on the type that carries it, while the mechanics that enforce that behavior are specified on the boundary methods that execute it; the split is explicit so neither the contract nor the mechanics are stated in both places or left unspecified.

## Generation-friendly API surface

When the API is exercised by model-generated step text, the surface favors explicit, direction-named methods taking constrained positive-integer amounts over signed or encoded arguments, because a sign embedded in an argument is a source of generation errors and reads worse in generated propositions. Changes are additive: existing call sites stay untouched, and the API listing and consumer documentation are extended in the same change.

## Loud failure over silent degradation

Invoking a capability before its precondition holds raises a loud, actionable failure telling the caller what to do first, rather than silently returning useless output; decisions that belong to the caller (such as when to capture artifacts) are never taken implicitly by the library, and explicit write operations surface their failures loudly.

## Self-contained cell contracts

CODEMANIFEST and usage files must not reference external project documents (ADRs, PRDs, task files). Every requirement is stated fully inside manifest annotations so the cell contract is readable and verifiable without consulting source documents.

## Shared types go to a leaf cell to keep the DAG

Types needed by multiple cells (including the failure taxonomy for interrelated functions such as generation and healing) are extracted into a separate leaf cell imported by all consumers; mutual imports and cycles in the cell graph are not allowed.

## Imports and references bound to the cell body

Every imported type is used by the cell body (an explicit backtick reference in annotations or a real parameter/return), and every backtick reference in annotations resolves within the cell's DSL tree; import_is_used and annotation_links_exists errors are never left unfixed.

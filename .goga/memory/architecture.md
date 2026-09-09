# Project rules

## Self-contained cell contracts

CODEMANIFEST and usage files must not reference external project documents (ADRs, PRDs, task files). Every requirement
is stated fully inside manifest annotations so the cell contract is readable and verifiable without consulting source
documents.

## Domain-named usage files with code examples

Usage files are named after the functional domain they describe (not technical names like "api" or abstract ones), and
every cell has, alongside conceptual descriptions, a usage file with ready code examples of calling its API.

## Shared types go to a leaf cell to keep the DAG

Types needed by multiple cells (including the failure taxonomy for interrelated functions such as generation and
healing) are extracted into a separate leaf cell imported by all consumers; mutual imports and cycles in the cell graph
are not allowed.

## Imports and references bound to the cell body

Every imported type is used by the cell body (an explicit backtick reference in annotations or a real parameter/return),
and every backtick reference in annotations resolves within the cell's DSL tree; import_is_used and
annotation_links_exists errors are never left unfixed.

## `::` mutations for derived errors

Errors extending the project's base error are declared in the DSL as mutations via the `::` syntax from the base type,
not as independent types; the error base is declared in the manifest of the taxonomy-owning cell.

# Jinja — Step Templates and Capture Declarations

Practices for `jinja2` within prettyplay. Target audience: implementing agents building the step-template rendering — the Jinja environment, the `{% var %}` capture extension, and the render contract of step sentences.

`jinja2>=3.1` is declared in `pyproject.toml`; project conventions (`.goga/usages/conventions.md`) apply.

## Environment — plain text, no autoescape

```python
from jinja2 import Environment, StrictUndefined

environment = Environment(autoescape=False, undefined=StrictUndefined, extensions=[VarExtension])
template = environment.from_string(step_text)
instruction = template.render(memory, vars=inputs)
```

Rules:

- Templates come from ordinary Python strings via `from_string`; no loader infrastructure
- `autoescape=False` always — the instruction is plain text, not HTML
- Substituted values are data and are never re-rendered: a captured string containing `{{ x }}` stays literal
- Standard Jinja features stay available — filters, conditions, loops, `set`; no restricted subset; ordinary `set` stays local to the template and publishes nothing

## Capture declarations — the `{% var %}` extension

Capture tags come through the standard extension mechanism (subclass `Extension`, declare the tag, parse the name token, emit an output node that renders to nothing and records the name when reached):

- `{% var name %}` renders to an empty string — it declares a result slot, it supplies no value
- Names are case-sensitive Jinja identifiers; the reserved name `vars` is rejected
- A repeated declaration of one name within one render is an authoring error raised before browser execution
- Only tags reached during rendering create expected results — a declaration inside an inactive branch declares nothing
- Capture tags are invalid in `expect` — rejected before execution rendering

## Separate namespaces — memory and call inputs

```python
template.render(memory, vars={"expected": "Details"})
```

- `{{ name }}` reads memory; `{{ vars.expected }}` reads the call input
- Neither namespace overwrites the other; call inputs never establish memory
- Rendering starts from a snapshot of memory and inputs — a step's own new captures are invisible to its template

## Missing values — loud failure, authored absence handling

```python
from jinja2 import UndefinedError

try:
    instruction = template.render(memory, vars=inputs)
except UndefinedError as error:
    ...  # the message names the unavailable name
```

- `StrictUndefined` raises on ordinary interpolation and names the unavailable variable; Jinja's default `Undefined` would silently render it as an empty string
- Author-written `| default(...)` and `is defined` keep standard behavior; generation and healing never add fallbacks
- No silent guessing and no re-reading the page to fill a missing name

## Literal Jinja in existing sentences

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

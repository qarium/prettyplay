# Rendering step sentences

Domain: preparing a step sentence into a plain-text instruction with capture declarations. Audience: library internals — the step executor and the recovery engine calling the render point.

## Render a step

```python
from prettyplay.engine.renderer import StepMemory, render_step

memory = StepMemory()
memory.publish({"name": "Book"})  # a previously accepted observation

prepared = render_step(
    text="For the item named {{ name }}, read its tags into {% var tags %}",
    step_type="action",
    memory=memory,
    vars=None,
)
prepared.instruction  # "For the item named Book, read its tags into " — plain text, actual values
prepared.inputs  # {} — the call's vars
prepared.declarations  # ["tags"] — reached capture tags only
```

- The render starts from a snapshot: later publications never change a taken render
- `{{ name }}` reads memory; `{{ vars.expected }}` reads the call input — separate namespaces, neither overwrites the other
- A reached `{% var name %}` renders to empty text and declares a result slot; an inactive branch declares nothing
- Capture declarations are invalid for assertion steps (`expect`)

## Authoring errors

Raised as the loud actionable `PrettyplayError` before any browser execution:

- a duplicate capture name within one render
- the reserved capture name `vars` or a non-Jinja-identifier name
- an unavailable ordinary reference — the message names it; author-written `| default(...)` and `is defined` behave as authored
- a capture declaration in an assertion step

## Literal Jinja in a sentence

```python
t.expect("The page contains {% raw %}{{ name }}{% endraw %}")
```

Use standard `raw` blocks to output literal Jinja syntax.

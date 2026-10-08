# Test memory

Domain: the per-test memory of captured observations. Audience: library internals — the executor owning the memory and the engines publishing at acceptance.

## Lifecycle

```python
from prettyplay.engine.renderer import StepMemory

memory = StepMemory()              # empty at construction, one per test execution
values = memory.snapshot()         # the render source — a stable copy
memory.publish({"name": "Book"})   # atomic, after full acceptance only
```

- Rendering reads a snapshot: a step's own new captures stay invisible to its template; a same-step read observes the previous value or fails
- All captures of one step publish together after full acceptance (including the compliance gate); a failed or rejected step publishes nothing
- A successful recapture replaces the previous value; absent names keep theirs
- Memory survives navigation and never crosses test boundaries — concurrent tests stay isolated

## Who publishes

- The executor — after a validated successful replay of cached code
- The engines — at the candidate acceptance point (after the compliance gate)
- The group recovery — per accepted row step; a later group failure never rolls back accepted publications

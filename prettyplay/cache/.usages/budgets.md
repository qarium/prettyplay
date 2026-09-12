# Attempt budgets

Domain: generation and healing attempt budgets. Audience: engineers tuning budgets and reasoning about budget exhaustion.

## Consume attempts

```python
from prettyplay.cache import RunBudgets

budgets = RunBudgets(generation_limit=3, healing_limit=2)

if budgets.try_generation(identity):
    ...  # attempt allowed; False — budget exhausted, the caller reports incurability
```

## Semantics

- Budgets are per step per test: every test owns its registry and starts with full limits — a step reused across tests gets a fresh budget in each test (N tests running one step in a process spend N × attempts in total)
- Defaults: 3 generation attempts, 2 healing attempts — configurable in the project settings
- An exhausted budget is the incurable failure, never an infinite loop
- Budgets exist only in the memory of the running process — nothing is persisted

## Healing-funded regenerations

Two verdict-driven regenerations are paid from the healing budget via `try_healing`, exactly one each:

- generation-budget exhaustion with a rot or fixable verdict grants one extra recommendation-carrying regeneration; a repeat failure is terminal — no reclassification
- a failed candidate check (generation loop) classified rot or fixable gets one recommendation-carrying regeneration before the final terminal-kind classification

A refused `try_healing` — the healing budget already exhausted — leaves the failure terminal: no unfunded regeneration ever runs.

Settle re-executions of the same code never consume budgets — re-execution is execution, not generation. Interactive steering attempts never consume budgets either: the human in the loop is the bound.

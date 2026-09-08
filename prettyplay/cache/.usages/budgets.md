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

- Budgets are per step per run (process) and shared across tests: a step reused in several tests has one budget
- Defaults: 3 generation attempts, 2 healing attempts — configurable in the project settings
- An exhausted budget is the incurable failure, never an infinite loop
- Budgets exist only in the memory of the running process — nothing is persisted

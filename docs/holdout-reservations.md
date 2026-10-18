# Holdout reservations: single-use evaluation splits

`open_dream_rsi/holdout.py` reserves task ids so an evaluation split is
consumed exactly once. The design guard: once a holdout has been looked at,
results measured on it are selection-contaminated; a reservation makes that
state explicit and machine-checkable.

- `claim` is first-claim-wins. Re-claiming the same ids **for the same
  purpose** is idempotent (a crashed phase can resume without corrupting the
  protocol); claiming the same ids **for a different purpose** is refused.
- `release` exists for operator corrections (wrong ids claimed) and is never
  part of a protocol — a released split is no longer a holdout.
- The loop never reads the registry; reservations gate *your* harness, not the
  runtime.

## CLI

```
odr holdout claim --ids 102 103 104 --purpose holdout-v1   # first-claim-wins
odr holdout show                                           # what is reserved, by whom
odr holdout release --ids 102 --purpose holdout-v1         # operator correction only
odr holdout split tasks.json --purpose holdout-v1          # partition a task list
```

`--memory` is a global flag: pass it **before** the subcommand
(`odr --memory /path/to/memory holdout show`).

## When to use

Preregistered protocols (train → freeze → one holdout pass), arm-selection
archives that must be excluded from the final report, shared evaluation sets
where two operators must not tune against the same ids. The TravelPlanner
study in the paper follows this shape; its selection-era contamination is
stated explicitly in the paper's protocol section.

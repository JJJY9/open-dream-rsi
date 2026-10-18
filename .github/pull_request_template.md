## What

<!-- one or two sentences: what changed -->

## Why

## Tests

- [ ] `python -m unittest discover -s tests` passes
- [ ] `python scripts/fast_tests.py` passes
- [ ] `ruff check --select E9,F63,F7,F82,F401,F841 open_dream_rsi plugins examples scripts tests` is clean
- [ ] `python -m unittest tests.test_vendored_drift` is clean (changed files mirrored into `plugins/deepseek_harness/open_dream_rsi/`)
- [ ] No new runtime dependency (the library is stdlib-only by design)
- [ ] If a published number moved: README/paper tables re-measured and updated in this commit

# Contributing

Thanks for your interest in Open Dream-RSI.

## Ground rules

- **Stdlib only.** The library has zero runtime dependencies. Do not add one
  — not for HTTP, not for parsing. This is a design constraint, not an
  oversight.
- **Everything in English** — docs, docstrings, comments, CLI output.
- **Python 3.10+.** The suite must parse and pass on 3.10 through 3.13;
  syntax newer than 3.10 (e.g. multi-line f-string expressions, PEP 701)
  breaks CI.
- **Tests are stdlib `unittest`**, discovered by
  `python -m unittest discover -s tests`. A pytest-importing test file dies
  as a whole-module ImportError under discovery — write unittest.

## Making a change

1. Fork and branch from `main`.
2. Add or update tests for behaviour you change. Behavioural contracts
   (`bench`, `bench-policy`) are regression contracts, not benchmarks — if
   your change moves their published numbers, re-measure and update the
   README/paper tables **in the same commit**.
3. Run locally:
   ```bash
   python -m unittest discover -s tests          # full suite, ~2 min
   python scripts/fast_tests.py                  # fast subset (slow bench/sandbox modules excluded), ~15 s
   python examples/live_loop_demo.py             # key-free end-to-end demo
   python -m open_dream_rsi bench --cycles 10 --markdown
   ```
   CI also runs a pinned ruff pass (`E9,F63,F7,F82,F401,F841`) and a
   byte-equality check between `open_dream_rsi/` and the vendored npm
   bundle copy — run both before pushing:
   ```bash
   ruff check --select E9,F63,F7,F82,F401,F841 open_dream_rsi plugins examples scripts tests
   python -m unittest tests.test_vendored_drift
   ```
4. Keep diffs focused. One idea per PR.

## Claims

This project makes performance claims on exactly one benchmark (goose ×
TravelPlanner). Changes to evaluation wording must keep the distinction
between *that* benchmark and the scripted self-checks intact.

## Good first issues

Look for the [`good first issue`](/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
label. Docs fixes, integration examples, and reproduction tests are always
welcome.

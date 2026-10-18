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

## Releasing (maintainers)

1. Bump the version in **all** carrier files — `pyproject.toml`,
   `open_dream_rsi/__init__.py`, `.cursor-plugin/plugin.json`,
   `.cursor-plugin/marketplace.json` (both `metadata.version` and the plugin
   entry), `plugins/deepseek_harness/package.json` — and mirror any changed
   files into `plugins/deepseek_harness/open_dream_rsi/`. `python
   scripts/check_versions.py` verifies the sync (CI enforces it too).
2. Push `main`, wait for CI green.
3. Push the version tag: `git tag v0.3.8 && git push origin v0.3.8`
   (tag must equal the pyproject version, `v` prefix).
4. `.github/workflows/publish.yml` builds the sdist/wheel, runs
   `twine check`, and publishes to PyPI via **trusted publishing** —
   no stored credentials. First-time setup: add a pending trusted
   publisher at <https://pypi.org/manage/account/publishing/> (owner
   `patrykorwat`, repository `open-dream-rsi`, workflow `publish.yml`,
   environment left blank). Verify after: `pip index versions
   open-dream-rsi` or the project page.
5. **npm bundle** (`plugins/deepseek_harness/`, package `dsh-open-dream-rsi`):
   the version lives in the bundle's `package.json` (checked by
   `scripts/check_versions.py`). The `publish-npm` job of
   `.github/workflows/publish.yml` runs on the same `v*` tags — npm
   **trusted publishing** (OIDC), no `NPM_TOKEN` stored. One-time setup on
   npmjs.com (package → Settings → Trusted Publisher → GitHub Actions):
   owner `patrykorwat`, repository `open-dream-rsi`, workflow `publish.yml`
   (the same file that publishes to PyPI — npm validates the workflow file
   name), allow **direct publish**. A version whose tag predates the job:
   re-point the tag (`git tag -fa vX.Y.Z -m "..." <sha-with-the-job> &&
   git push -f origin vX.Y.Z`) — the PyPI job skips already-published
   versions, so the re-tag is safe.

# Changelog

All notable changes to `open-dream-rsi` are documented here. Versions 0.3.0 and
earlier are summarized from the commit history; the full log is the source of
truth.

## [0.3.9] — 2026-10-18

### Added
- **Hermes one-line plugin install**: the `odr-trigger` plugin now lives at
  the repo's top level (`odr-trigger/`), where Hermes plugin discovery finds
  it — `hermes plugins install
  "https://github.com/patrykorwat/open-dream-rsi#odr-trigger"` or the
  desktop **Install from Git** dialog; the old manual `cp -r` path is gone.
- **Evaluation and session-import docs split out of the README** —
  [docs/benchmarks.md](docs/benchmarks.md) (TravelPlanner protocol, tables, honest
  memory findings) and [docs/sessions.md](docs/sessions.md) (transcript import,
  corrections, stores); README down to ~470 lines with a per-agent install
  table as the Quick start; the key-free demo and Docker sections moved to
  [docs/try-it.md](docs/try-it.md).
- **`odr` console script** (`[project.scripts]`): `odr status`, `odr mcp …` —
  one-line MCP config blocks; `uvx --from open-dream-rsi odr …` works with no
  prior install.
- **Claude Code session importer** (`read_claude_code_sessions`,
  `dream --source claude`, `sessions export --source claude`): JSONL
  transcripts under `~/.claude/projects` become curator evidence — tool
  results joined to their calls, subagent sidechains skipped, resume
  re-appends deduplicated; same redaction and promotion gate as every other
  source.
- **Docker image** (`Dockerfile`, `.dockerignore`): one command to try the
  project in a pinned, non-root environment; CI builds the image on every
  push.
- **Clean mypy gate in CI** (`--ignore-missing-imports`, pinned version): the
  tree typechecks with zero errors — the `py.typed` promise is now enforced,
  not just declared.
- **Community files**: feature-request issue template, PR template,
  `CODE_OF_CONDUCT.md`, this changelog, `CITATION.cff` (the "Cite this
  repository" button), and a release job in `publish.yml` that creates a
  GitHub Release from every version tag with the matching changelog section.
- **[docs/comparison.md](docs/comparison.md)** — how the loop differs from
  memory plugins (Mem0, Letta), reflection (Reflexion), prompt optimizers
  (DSPy) and skill libraries: what is stored, how entries earn trust, what it
  costs.
- **[docs/holdout-reservations.md](docs/holdout-reservations.md)** — a
  walkthrough for `odr holdout` (single-use evaluation splits).
- `docs/README.md` — index of the documentation directory.

### Changed
- `docs/launch-kit.md` (internal launch notes) removed from the public
  repository.
- Git-backed lesson stores now carry **worlds** and **policies**: export ships
  redacted `trees/*.json` with sha256 in the manifest; imports verify
  checksums, drop unknown fields, and land policies as VALIDATED (an import
  never replaces an incumbent). New commands: `odr lessons
  worlds-export|worlds-import|policies-export|policies-import`.
- **Holdout reservations** (`open_dream_rsi/holdout.py`, `odr holdout
  claim|release|show|split`): single-use eval-split claims — same-purpose
  re-claim is idempotent (a crashed phase can resume), cross-purpose claims are
  refused. The loop never reads the registry.
- **Policy revise mode** (opt-in `policy_revive`): a rejected LLM-written
  policy gets a greedy-replay trace as revision feedback; same strict
  promotion gate.
- **Sandbox result cache** (opt-in): LRU+TTL keyed by file contents; only
  completed runs are cached.

## [0.3.8] — 2026-10-18

### Added
- **PyPI publishing** (tag-driven, trusted publishing; 0.3.8 live on PyPI) and
  **npm bundle publishing** in the same workflow.
- `py.typed` ships with the package; PEP 639 metadata
  (`License-Expression: MIT`).
- CI: vendored-copy drift test; version-sync check in the lint job;
  `set -o pipefail` on every piped step.
- Wilson 95% CIs on the TravelPlanner table (README + paper caption).

### Changed
- README split: per-agent setup moved to `docs/integrations.md`, self-check
  details to `docs/self-checks.md`.
- Evaluation scope note: the TravelPlanner gate arm measures the **fixed call
  cutoff** — no learned content in those episodes; the learned machinery is
  validated by the scripted suites.

## [0.3.7] — 2026-10-17
- Key-free CI (Python 3.10–3.13), `SECURITY.md`, `CONTRIBUTING.md`, working
  key-free demo.

## [0.3.6] — 2026-10-17
- Curator: lesson retrieval budget 3000 → 15000 chars.

## [0.3.4] — 2026-10-17
- Curator: lesson text cap 1200 → 80000 chars (detailed lessons).

## [0.3.3] — 2026-10-17
- Curator: detailed lessons — text cap 280 → 1200 chars, retrieval budget
  700 → 3000.

## [0.3.2] — 2026-10-17
- Fair task queue (least-processed-first) — fixes backlog starvation by
  processing, not pruning.

## [0.3.1] — 2026-10-13
- **User corrections as first-class evidence** (issue #6): correction /
  approach_redirect / preference / new_requirement classification, provenance
  recorded in the evidence itself, same trust gate as loop-collected failures.
- DSH bundle 0.3.1.

## [0.3.0] — 2026-10-12
- **Cursor plugin**: repository import works (`.cursor-plugin` manifest + root
  `hooks/` + `rules/`); hooks carry args, not code.
- **cursor-agent** headless CLI as the default dreamer brain (no proxy, no API
  key; Windows `.cmd` shims wrapped via `cmd.exe /c`).
- A dead endpoint **defers** the session (stays unseen) instead of burning the
  evidence backlog.

## Earlier versions
See the [commit history](https://github.com/patrykorwat/open-dream-rsi/commits/main)
for 0.2.x and the initial release.

[0.3.9]: https://github.com/patrykorwat/open-dream-rsi/compare/v0.3.8...HEAD
[0.3.8]: https://github.com/patrykorwat/open-dream-rsi/releases/tag/v0.3.8

# Importing real sessions: Hermes, Cursor, Claude Code

The loop distils lessons from failures it produces itself. This page
documents the second legitimate door: **transcripts from host agents are
evidence you already paid for**. Imports feed the *same* pipeline as
loop-collected failures — structural gate, staging-by-default, paired
replay promotion. Nothing imported is trusted; activation is still earned.
Transcripts are treated as **hostile input**: opened read-only,
credential-scrubbed, parsed defensively — and lessons that never passed
the promotion gate **never reach a prompt**.

The loop distils lessons from failures it produces itself. `sessions.py`
opens a second legitimate door: **transcripts from host agents are evidence
you already paid for**. Imports feed the *same* pipeline as loop-collected
failures — structural gate, staging-by-default, paired replay promotion.
Nothing imported is trusted; activation is still earned. Transcripts are
treated as **hostile input**: opened read-only, credential-scrubbed, parsed
defensively — and lessons that never passed the promotion gate **never reach
a prompt**.

## From Hermes sessions

Hermes persists every session to `<HERMES_HOME>/state.db` (SQLite:
`sessions` + `messages`). Export, then distil:

```bash
python -m open_dream_rsi --memory .dream_rsi sessions export \
    --source hermes --db ~/.hermes/state.db --limit 50 \
    --out episodes.jsonl

# inspect what WOULD be distilled — no LLM calls, no writes:
python -m open_dream_rsi --memory .dream_rsi sessions distill \
    episodes.jsonl --dry-run --limit 5

# real run: staging lessons into the KB (per-category = episode cwd name)
python -m open_dream_rsi --memory .dream_rsi sessions distill episodes.jsonl
```

The next `odr loop` cycle gates the staging entries exactly like
loop-collected ones; `odr artifacts --type lesson --history` shows the
lifecycle events behind every activation.

## User corrections (natural-language evidence, issue #6)

Host sessions also carry corrections stated in prose — "nie tak, użyj
istniejącego klienta", "don't create another HTTP client" — which error-marker
scanning never sees. `corrections.py` extracts them deterministically (no
extra LLM call per message), pairs each with the assistant turn it targets,
and labels four classes: `correction`, `approach_redirect`, `preference`,
`new_requirement`. Only the first three are distillation-ready; ordinary
follow-ups, new requirements and ambiguous negatives stay unclassified.
Provenance survives end to end: evidence actions read
`user_correction:<host>:<session>#<msg_index>`, and each record keeps source
host, session id, workspace and whether a later turn suggests the session
recovered (`outcome: confirmed|unverified`). Message text arrives already
secret-redacted from the readers; nothing is added back.

The trust model is unchanged: **a user correction is evidence worth testing,
not verified truth.** Candidates are deduplicated deterministically (Jaccard
on content words) *before* any paid curator call — repeats within one episode
do not strengthen evidence — then flow through the same curator prompt (with
an explicit "user wording is evidence, not verified truth" note), enter
`STAGING`, and face the same paired-replay gate. A correction-only session is
no longer skipped: its probe task is the **pre-correction** user request, so
the user's corrected answer never leaks into replay context. Every extraction
is auditable via the `user_correction_found` event in `events.jsonl`; source
model identity is provenance, never a trust score, and there is no
cross-model evaluation matrix (one target: the configured runtime model).

## Backfill: re-distilling burned sessions

A dream cycle consumes a host session the first time it distills it. While
the endpoint was broken (404 churn, connection refused, empty payloads), a
session could be marked seen while producing ZERO lessons: `seen_sessions`
grew, the knowledge base did not — the evidence was burned. Since 0.3.0
transport failures defer sessions instead of consuming them, but sessions
burned by the old behaviour stay invisible. `scripts/backfill_history.py`
audits that damage and repairs it:

```bash
# damage report (dry-run; reads only session ids + cwd, never transcripts):
python scripts/backfill_history.py plan --memory .dream_rsi \
    --state-db ~/.hermes/state.db

# make burned sessions unseen again (timestamped backup written first):
python scripts/backfill_history.py requeue --memory .dream_rsi \
    --state-db ~/.hermes/state.db --category radoskoppl --apply

# trim the replay-probe backlog to the newest N (manual tasks always kept):
python scripts/backfill_history.py prune-probes 60 --memory .dream_rsi --apply

# run cycles back-to-back through the real CLI (the dream lock collapses
# overlaps; transport failures defer, never burn):
python scripts/backfill_history.py drain 5 --memory .dream_rsi \
    --state-db ~/.hermes/state.db --provider local --budget 200
```

A session counts as burned when it is marked seen, still present in the
store, and never produced a single lesson. Rejections meaning "no failure
evidence in this transcript" are excluded — requeueing those would loop
forever with zero yield. Tests: `tests/test_backfill_history.py`.

## From Cursor chats

Cursor keeps conversations in `globalStorage/state.vscdb` (Linux:
`~/.config/Cursor/User`, macOS: `~/Library/Application Support/Cursor/User`,
Windows: `%APPDATA%\Cursor\User`), with `workspaceStorage` mapping chats to
project folders for the category. The reader handles the undocumented
layout and the bubble-ordering rules; re-verify after major Cursor
upgrades.

```bash
python -m open_dream_rsi --memory .dream_rsi sessions export \
    --source cursor --out episodes.jsonl --limit 100
python -m open_dream_rsi --memory .dream_rsi sessions distill episodes.jsonl
```

Notes: the live DB is write-ahead-logged — `immutable=1` may miss the
newest chats, so quit Cursor or copy `state.vscdb`+`-wal`+`-shm` together
and point at the copy for a complete snapshot. Chat history contains
everything ever pasted into it: export redacts credential-shaped substrings
by default (`--no-redact` exists for local processing only) — review
`episodes.jsonl` before sharing it.

## From Claude Code transcripts

Claude Code writes one JSONL transcript per session under
`~/.claude/projects/<slugified-cwd>/<session-uuid>.jsonl` (`$CLAUDE_CONFIG_DIR`
overrides the root). The `claude` reader parses them defensively: tool
results filed as user records are joined back to their `tool_use` calls,
subagent sidechains are skipped, resumed sessions deduplicate re-appended
records by `uuid`, and the real `cwd` comes from the records (the directory
slug is lossy). Same pipeline as every other source — redacted, staged,
gate-gated:

```bash
python -m open_dream_rsi --memory .dream_rsi dream --source claude
python -m open_dream_rsi --memory .dream_rsi sessions export \
    --source claude --out episodes.jsonl
```

0.3.9+ installs an `odr` console script, so `odr --memory .dream_rsi dream
--source claude` is the same thing.

## Curator lessons as Hermes skills

```bash
python -m open_dream_rsi --memory .dream_rsi skills export \
    --out ~/.hermes/skills/odr-curated
```

Renders only **active** (promotion-gated) lessons into Hermes-style skills —
one directory per category, declarative bullets, never imperative commands
(the measured hazard). The export is one-way and regenerated wholesale:
edit `lessons.json` (or distil again), not the skills.

## Sharing lessons: git-backed stores

`share.py` turns curated knowledge into a portable, verifiable store that
other instances (or other people) can consume — a directory of JSON files,
optionally a git checkout, so GitHub is just storage:

```bash
# one-time: point the store at a repo (clone/pull handled for you)
python -m open_dream_rsi --memory .dream_rsi lessons export \
    --store git@github.com:you/dream-rsi-lessons.git

# on the consumer side — someone else's store becomes your staging:
python -m open_dream_rsi --memory .dream_rsi lessons import \
    --store https://github.com/you/dream-rsi-lessons.git
```

Trust model: **export ships only what earned activation** (staging and
rejected lessons excluded by construction, secrets scrubbed, sha256
manifest); **import lands as staging, never active** (checksum mismatch
aborts the whole import — tampering detected, not trusted; each lesson
still needs *your* paired-replay gate to reach a prompt). A local directory
works identically (`--store ./store`) — git is just the transport.

The same store carries replay data and promoted policy programs:

```bash
# ship archived discovery trees (redacted, length-capped, checksummed) — the
# counterfactual worlds a policy was judged on, so a reviewer can re-run the
# promotion offline:
python -m open_dream_rsi --memory .dream_rsi lessons worlds-export \
    --store <store> [--task <task_id> ...]
python -m open_dream_rsi --memory .dream_rsi lessons worlds-import --store <store>

# ship promoted exploration-policy programs (the structural gate applies on
# export; a redaction that breaks a program makes it unshippable):
python -m open_dream_rsi --memory .dream_rsi lessons policies-export --store <store>
python -m open_dream_rsi --memory .dream_rsi lessons policies-import --store <store>
```

Worlds import as **evidence** into `trees/imported/` — never live tasks,
never the runtime's `load_tree` path; node fields unknown to `TreeNode` are
dropped, not trusted. Policy programs register as ALM
`CANDIDATE -> VALIDATED` — adoption stays the local promotion machinery's
decision; an import never replaces an incumbent.

## Holdout hygiene: single-use eval reservations

A preregistered evaluation task is consumed ONCE — the selection-contamination
rule (TravelPlanner protocol) made enforceable instead of procedural:

```bash
# before phase A starts: reserve the eval split
python -m open_dream_rsi --memory .dream_rsi holdout claim \
    --ids 102 103 104 --purpose travelplanner_eval --phase final

# before any later run: partition a task queue into allowed vs held-back
python -m open_dream_rsi --memory .dream_rsi holdout split --tasks tasks.json
```

First claim wins: a later phase claiming the same ID for a different purpose
is refused (same-purpose re-claims are idempotent, so resuming a crashed
phase loses nothing); `release` is the explicit operator correction, never
part of the protocol. The loop never reads the registry — the harness that
owns the preregistered protocol filters with `split`.

## Full Hermes wiring (what exists today)

| Path | Direction | What it does |
|---|---|---|
| `odr mcp` (stdio) / `--http` | Hermes → ODR | Hermes calls `odr_run_once` / `odr_dream` / `odr_status` as tools |
| `plugins/hermes_sentinel/` | Hermes → ODR engine | Sentinel observes tool results, annotates, gates |
| `odr-trigger/` | Hermes → ODR engine | session-end hook spawns the detached `odr dream` cycle (no shell/cron); installable via `hermes plugins install <repo-url>#odr-trigger` |
| `plugins/deepseek_harness/` | DeepSeek Harness (`dsh`) → ODR | Cordis overlay: the ODR MCP server behind `@deepseek-ai/dsh-mcp-client` |
| `hooks/` + `.cursor-plugin/` | Cursor → ODR (no MCP) | Plugin manifest (GitHub import) + hooks (sentinel notes, session-end dream; default brain: the cursor-agent CLI) + `task add` queue — for Cursor installs where MCP servers are blocked |
| `odr sessions export/distill` | Hermes → curator | session history becomes staging lessons |
| `odr skills export` | curator → Hermes | active lessons become discovered SKILL.md files |
| `odr dream` | any trigger | one automated cycle: evidence → gate → ALM → skills |

---

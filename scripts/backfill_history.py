#!/usr/bin/env python3
"""Requeue burned host sessions for Dream-RSI re-distillation (backfill).

A dream cycle consumes a host session the first time it distills it. While
the LLM endpoint is broken (404 churn, connection refused, empty payloads)
a session can be marked seen while producing ZERO lessons: ``seen_sessions``
grows, the knowledge base does not. The evidence is burned — the session is
never re-read because it is already marked seen. This tool audits that
damage and repairs it:

  plan          dry-run counts: visible / unseen / burned, per category,
                probe-backlog size, estimated cost of a full backfill
  requeue       remove burned session ids from dream_state.json (a timestamped
                backup of the state file is written first)
  prune-probes  trim the replay-probe backlog in tasks.json to the newest N
                probes (manual tasks are always kept; backup written)
  drain         run N dream cycles back-to-back through the real CLI (the
                dream lock collapses overlaps; transport failures defer
                sessions instead of burning them)

Transcripts are never opened by this script: ``plan``/``requeue`` read only
session ids and cwd metadata, and distillation redaction stays inside the
dream cycle. Run from the repo root (or with the repo on PYTHONPATH) so the
``drain`` subcommand can import ``open_dream_rsi``.

Usage:
  python scripts/backfill_history.py plan --memory .dream_rsi \
      --state-db ~/.hermes/state.db
  python scripts/backfill_history.py requeue --memory .dream_rsi \
      --state-db ~/.hermes/state.db --category radoskoppl --apply
  python scripts/backfill_history.py prune-probes 60 --memory .dream_rsi --apply
  python scripts/backfill_history.py drain 5 --memory .dream_rsi \
      --state-db ~/.hermes/state.db --provider local --budget 200
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

INGEST_LIMIT_PER_CYCLE = 25  # dream.ingest_sessions default


# -- stores -------------------------------------------------------------------

def load_state(memory: Path) -> dict:
    path = Path(memory) / "dream_state.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def save_state(memory: Path, state: dict) -> Path:
    """Atomic write with a timestamped backup; returns the backup path."""
    path = Path(memory) / "dream_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(f"{path.name}.bak-backfill-{int(time.time())}")
    if path.exists():
        shutil.copy2(path, backup)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)
    return backup


def event_sets(events_path: Path) -> tuple[set, dict]:
    """(curated session ids, {session_id: last rejection reason})."""
    curated: set = set()
    rejected: dict = {}
    if not events_path.exists():
        return curated, rejected
    with open(events_path, encoding="utf-8") as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            sid = ev.get("session_id")
            if not sid:
                continue
            kind = ev.get("kind")
            if kind == "lessons_curated":
                curated.add(sid)
            elif kind == "lesson_rejected":
                rejected[sid] = str(ev.get("reason", ""))[:120]
    return curated, rejected


def visible_sessions(state_db: Path) -> dict:
    """{session_id: cwd} for non-archived, non-hidden Hermes sessions.

    Only ids and cwd are read — never message content.
    """
    uri = f"file:{Path(state_db).as_posix()}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        cols = {r[1] for r in con.execute("pragma table_info(sessions)")}
        if not cols:
            return {}
        where, _ = [], []
        for flag in ("archived", "hidden"):
            if flag in cols:
                where.append(f"coalesce({flag}, 0) = 0")
        sql = "select id, cwd from sessions"
        if where:
            sql += " where " + " and ".join(where)
        return {str(i): str(c or "") for i, c in con.execute(sql)}
    finally:
        con.close()


def burned_sessions(curated: set, rejected: dict, visible: dict,
                    seen: set) -> set:
    """Seen-but-never-curated sessions still present in the store.

    A session that eventually produced at least one lesson is not burned;
    an unseen rejected session is not burned either — it re-distills on the
    next cycle anyway, there is nothing to requeue. 'no failure evidence'
    rejections are excluded: the transcript genuinely holds no failure, so
    re-distilling would requeue it forever without ever yielding a lesson.
    Everything else (transport-era 'llm error', 'empty payload', ...) counts
    as burned: the era, not the content, made the attempt useless.
    """
    return {s for s in rejected
            if s in seen and s not in curated and s in visible
            and rejected[s] != "no failure evidence"}


def category_of(cwd: str) -> str:
    return Path(cwd).name if cwd else "(no cwd)"


def load_tasks(memory: Path) -> list:
    path = Path(memory) / "tasks.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def save_tasks(memory: Path, tasks: list) -> Path:
    path = Path(memory) / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(f"{path.name}.bak-backfill-{int(time.time())}")
    if path.exists():
        shutil.copy2(path, backup)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tasks, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)
    return backup


def prune_probes(tasks: list, keep: int) -> tuple[list, int]:
    """Keep the newest ``keep`` probe tasks (ids embed a sortable timestamp);
    manual tasks are always kept. Returns (new_tasks, removed_count)."""
    probes = [(i, t) for i, t in enumerate(tasks)
              if str(t.get("task_id", "")).startswith("probe:")]
    manual = [(i, t) for i, t in enumerate(tasks)
              if not str(t.get("task_id", "")).startswith("probe:")]
    if len(probes) <= keep:
        return list(tasks), 0
    probes.sort(key=lambda it: str(it[1].get("task_id", "")))
    out = [t for i, t in sorted(manual + probes[-keep:],
                                key=lambda it: it[0])]
    return out, len(probes) - keep


# -- commands -----------------------------------------------------------------

def build_dream_cmd(python: str, memory: str, state_db: str, provider: str,
                    budget: int, skills_out=None) -> list:
    cmd = [python, "-m", "open_dream_rsi", "--memory", memory, "dream",
           "--sessions", state_db, "--source", "hermes",
           "--provider", provider, "--budget", str(budget)]
    if skills_out:
        cmd += ["--skills-out", skills_out]
    return cmd


def cmd_plan(args) -> int:
    visible = visible_sessions(Path(args.state_db))
    state = load_state(Path(args.memory))
    seen = set(state.get("seen_sessions", []))
    curated, rejected = event_sets(Path(args.memory) / "events.jsonl")
    burn = burned_sessions(curated, rejected, visible, seen)
    if args.category:
        burn = {s for s in burn
                if category_of(visible.get(s, "")) == args.category}
    new = {s for s in visible if s not in seen}
    tasks = load_tasks(Path(args.memory))
    n_probes = sum(1 for t in tasks
                   if str(t.get("task_id", "")).startswith("probe:"))
    by_cat = Counter(category_of(visible.get(s, "")) for s in burn)
    est_cycles = (len(burn) + INGEST_LIMIT_PER_CYCLE - 1) // INGEST_LIMIT_PER_CYCLE
    print(json.dumps({
        "visible_sessions": len(visible),
        "unseen": len(new),
        "seen": len(seen & set(visible)),
        "stale_seen_ids": len(seen - set(visible)),
        "burned_without_lesson": len(burn),
        "burned_by_category": dict(by_cat.most_common()),
        "est_distill_calls": len(burn) * 2,   # ~1 distill + repair headroom
        "est_cycles_at_25_per_cycle": est_cycles,
        "probe_backlog": n_probes,
        "note": "burned = seen but never curated (zero lessons); requeue "
                "makes them unseen again so the next dream re-distills them",
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_requeue(args) -> int:
    visible = visible_sessions(Path(args.state_db))
    state = load_state(Path(args.memory))
    seen = list(state.get("seen_sessions", []))
    curated, rejected = event_sets(Path(args.memory) / "events.jsonl")
    burn = burned_sessions(curated, rejected, visible, set(seen))
    if args.category:
        burn = {s for s in burn
                if category_of(visible.get(s, "")) == args.category}
    keep = [s for s in seen if s not in burn]
    removed = len(seen) - len(keep)
    print(f"burned sessions matched: {len(burn)}; "
          f"seen entries: {len(seen)} -> {len(keep)} (removing {removed})")
    if not args.apply:
        print("dry-run: nothing written (pass --apply to requeue)")
        return 0
    if not removed:
        print("nothing to do")
        return 0
    state["seen_sessions"] = keep
    backup = save_state(Path(args.memory), state)
    print(f"PASS dream_state.json rewritten; backup: {backup}")
    print(f"next: run 'drain' or let session-end fires re-distill "
          f"{removed} sessions ({(removed + INGEST_LIMIT_PER_CYCLE - 1) // INGEST_LIMIT_PER_CYCLE}"
          f" cycles at {INGEST_LIMIT_PER_CYCLE}/cycle)")
    return 0


def cmd_prune_probes(args) -> int:
    tasks = load_tasks(Path(args.memory))
    new_tasks, removed = prune_probes(tasks, args.keep)
    print(f"probe backlog: {sum(1 for t in tasks if str(t.get('task_id','')).startswith('probe:'))}"
          f" -> {sum(1 for t in new_tasks if str(t.get('task_id','')).startswith('probe:'))}"
          f" (removing {removed}; manual tasks kept)")
    if not args.apply or not removed:
        print("dry-run: nothing written (pass --apply)" if not args.apply
              else "nothing to do")
        return 0
    backup = save_tasks(Path(args.memory), new_tasks)
    print(f"PASS tasks.json rewritten; backup: {backup}")
    return 0


def cmd_drain(args) -> int:
    cmd = build_dream_cmd(sys.executable, str(args.memory), str(args.state_db),
                          args.provider, args.budget, args.skills_out)
    for i in range(1, args.cycles + 1):
        print(f"--- cycle {i}/{args.cycles}: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"cycle {i} rc={proc.returncode}: {proc.stderr[-400:]}")
            break
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            print(proc.stdout[-400:])
            continue
        if report.get("skipped"):
            reason = report.get("reason", "another dream is running")
            print(f"cycle {i}: skipped ({reason}) — the running cycle owns the memory "
                  "dir; drain stops instead of fighting the lock")
            break
        ing = report.get("ingest", {})
        cyc = report.get("cycle", {})
        print(f"cycle {i}: tier={report.get('tier')} "
              f"new={ing.get('new')} added={ing.get('added')} "
              f"deferred={ing.get('deferred')} "
              f"attempted={cyc.get('tasks_attempted')} "
              f"solved={cyc.get('tasks_solved')} "
              f"api={cyc.get('api_calls')} stopped={cyc.get('stopped_reason')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p, need_state=True):
        p.add_argument("--memory", default=".dream_rsi",
                       help="Dream-RSI memory dir (default .dream_rsi)")
        if need_state:
            p.add_argument("--state-db", required=True,
                           help="Hermes state.db (sessions + messages)")
        p.add_argument("--category", default=None,
                       help="restrict to one category (cwd basename)")

    plan = sub.add_parser("plan", help="dry-run damage report")
    common(plan)
    plan.set_defaults(func=cmd_plan)

    req = sub.add_parser("requeue", help="make burned sessions unseen again")
    common(req)
    req.add_argument("--apply", action="store_true",
                     help="write dream_state.json (default: dry-run)")
    req.set_defaults(func=cmd_requeue)

    pr = sub.add_parser("prune-probes", help="trim the probe backlog")
    pr.add_argument("keep", type=int, help="newest N probes to keep")
    pr.add_argument("--memory", default=".dream_rsi")
    pr.add_argument("--apply", action="store_true")
    pr.set_defaults(func=cmd_prune_probes)

    dr = sub.add_parser("drain", help="run N dream cycles sequentially")
    common(dr)
    dr.add_argument("cycles", type=int, help="number of dream cycles to run")
    dr.add_argument("--provider", default="local",
                    choices=["openai", "cursor-agent", "cursor", "local",
                             "goose"])
    dr.add_argument("--budget", type=int, default=200,
                    help="max API calls per cycle (default 200)")
    dr.add_argument("--skills-out", default=None,
                    help="render ACTIVE lessons here as SKILL.md files")
    dr.set_defaults(func=cmd_drain)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

"""Tests for scripts/backfill_history.py (burned-session requeue tooling)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import backfill_history as bf  # noqa: E402


# -- fixtures -------------------------------------------------------------------

def make_state_db(path: Path, sessions: list) -> Path:
    """sessions: (id, cwd, archived, hidden) tuples."""
    con = sqlite3.connect(path)
    con.execute("create table sessions (id text primary key, cwd text, "
                "archived integer default 0, hidden integer default 0)")
    con.executemany("insert into sessions (id, cwd, archived, hidden) "
                    "values (?, ?, ?, ?)", sessions)
    con.commit()
    con.close()
    return path


def make_memory(path: Path, seen: list, events: list, tasks: list = None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "dream_state.json").write_text(
        json.dumps({"seen_sessions": seen}), encoding="utf-8")
    (path / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if tasks is not None:
        (path / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path):
    db = make_state_db(tmp_path / "state.db", [
        ("s1", "/opt/data/workspace/radoskoppl", 0, 0),   # burned
        ("s2", "/opt/data/workspace/wiki", 0, 0),         # curated: not burned
        ("s3", "/opt/data/workspace/radoskoppl", 0, 0),   # rejected, unseen: not burned
        ("s4", "/opt/data/workspace/gdansk-network", 1, 0),  # archived: invisible
        ("s5", "", 0, 0),                                 # burned, no cwd
    ])
    mem = make_memory(tmp_path / "mem",
                      seen=["s1", "s2", "s4"],
                      events=[
                          {"kind": "lesson_rejected", "session_id": "s1",
                           "reason": "empty payload"},
                          {"kind": "lessons_curated", "session_id": "s2"},
                          {"kind": "lesson_rejected", "session_id": "s3",
                           "reason": "llm error: HTTP 404"},
                          {"kind": "lesson_rejected", "session_id": "s5",
                           "reason": "llm error: Connection refused"},
                          {"kind": "lessons_curated", "session_id": "gone"},
                      ],
                      tasks=[{"task_id": "probe:20260901_a"},
                             {"task_id": "manual-1"},
                             {"task_id": "probe:20261010_b"}])
    return db, mem


# -- burned logic -----------------------------------------------------------------

def test_burned_sessions_rules(workspace):
    db, mem = workspace
    visible = bf.visible_sessions(db)
    seen = {"s1", "s2", "s4"}
    curated, rejected = bf.event_sets(mem / "events.jsonl")
    burn = bf.burned_sessions(curated, rejected, visible, seen)
    assert burn == {"s1"}  # s2 curated; s3 unseen (re-distills anyway);
    #                          s5 unseen; archived s4 invisible


def test_burned_requires_visibility_and_seen(workspace):
    db, mem = workspace
    curated, rejected = bf.event_sets(mem / "events.jsonl")
    # not in store -> never burned; not seen -> never burned (re-distills
    # anyway); rejected+seen+visible and never curated -> burned
    assert bf.burned_sessions(curated, rejected, {}, {"s3"}) == set()
    assert bf.burned_sessions(curated, rejected, {"s3": "/x"}, set()) == set()
    assert bf.burned_sessions(curated, rejected, {"s3": "/x"}, {"s3"}) == {"s3"}


def test_burned_excludes_no_failure_evidence(workspace):
    db, mem = workspace
    # a session rejected for genuinely having no failure evidence must not
    # be flagged burned — requeueing it would loop forever with zero yield
    curated, rejected = bf.event_sets(mem / "events.jsonl")
    rejected["s9"] = "no failure evidence"
    assert "s9" not in bf.burned_sessions(curated, rejected,
                                          {"s9": "/x"}, {"s9"})


# -- plan ----------------------------------------------------------------------

def test_plan_reports_counts(workspace, capsys):
    db, mem = workspace
    args = type("A", (), {"memory": mem, "state_db": db, "category": None})()
    assert bf.cmd_plan(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["visible_sessions"] == 4          # s4 archived excluded
    assert out["burned_without_lesson"] == 1     # s1 (s5 unseen, s3 unseen)
    assert out["unseen"] == 2                    # s3, s5
    assert out["probe_backlog"] == 2
    assert out["burned_by_category"] == {"radoskoppl": 1}


def test_plan_category_filter(workspace, capsys):
    db, mem = workspace
    args = type("A", (), {"memory": mem, "state_db": db,
                          "category": "radoskoppl"})()
    bf.cmd_plan(args)
    out = json.loads(capsys.readouterr().out)
    assert out["burned_without_lesson"] == 1


# -- requeue ---------------------------------------------------------------------

def test_requeue_dry_run_writes_nothing(workspace, capsys):
    db, mem = workspace
    args = type("A", (), {"memory": mem, "state_db": db,
                          "category": None, "apply": False})()
    bf.cmd_requeue(args)
    assert "dry-run" in capsys.readouterr().out
    assert json.loads((mem / "dream_state.json").read_text())["seen_sessions"] \
        == ["s1", "s2", "s4"]


def test_requeue_applies_with_backup(workspace, capsys):
    db, mem = workspace
    args = type("A", (), {"memory": mem, "state_db": db,
                          "category": None, "apply": True})()
    assert bf.cmd_requeue(args) == 0
    state = json.loads((mem / "dream_state.json").read_text())
    assert state["seen_sessions"] == ["s2", "s4"]      # burned s1 removed
    backups = list(mem.glob("dream_state.json.bak-backfill-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text())["seen_sessions"] \
        == ["s1", "s2", "s4"]                          # restore point intact


def test_requeue_idempotent(workspace, capsys):
    db, mem = workspace
    for _ in range(2):
        args = type("A", (), {"memory": mem, "state_db": db,
                              "category": None, "apply": True})()
        bf.cmd_requeue(args)
    state = json.loads((mem / "dream_state.json").read_text())
    assert state["seen_sessions"] == ["s2", "s4"]      # stable, no dupes


# -- probe pruning ----------------------------------------------------------------

def test_prune_probes_keeps_manual_and_newest():
    tasks = [{"task_id": "probe:20260901_a"},
             {"task_id": "manual-1"},
             {"task_id": "probe:20261010_b"},
             {"task_id": "probe:20260815_c"}]
    out, removed = bf.prune_probes(tasks, 2)
    ids = [t["task_id"] for t in out]
    assert removed == 1
    assert "probe:20260815_c" not in ids                  # oldest probe dropped
    assert ids == ["probe:20260901_a", "manual-1", "probe:20261010_b"]
    assert "manual-1" in ids                              # original order kept


def test_prune_probes_noop_when_under_limit():
    tasks = [{"task_id": "probe:a"}, {"task_id": "manual-1"}]
    out, removed = bf.prune_probes(tasks, 5)
    assert removed == 0 and out == tasks


def test_prune_probes_command_roundtrip(tmp_path, capsys):
    make_memory(tmp_path / "mem", seen=[],
                events=[],
                tasks=[{"task_id": "probe:20260901_a"},
                       {"task_id": "manual-1"},
                       {"task_id": "probe:20261010_b"},
                       {"task_id": "probe:20260815_c"}])
    args = type("A", (), {"memory": tmp_path / "mem", "keep": 2,
                          "apply": True})()
    assert bf.cmd_prune_probes(args) == 0
    out = capsys.readouterr().out
    assert "removing 1" in out
    kept = json.loads((tmp_path / "mem" / "tasks.json").read_text())
    assert [t["task_id"] for t in kept] == ["probe:20260901_a", "manual-1",
                                            "probe:20261010_b"]
    assert list((tmp_path / "mem").glob("tasks.json.bak-backfill-*"))


# -- state save --------------------------------------------------------------------

def test_save_state_backup_and_atomic(tmp_path):
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "dream_state.json").write_text('{"seen_sessions": ["old"]}')
    backup = bf.save_state(mem, {"seen_sessions": ["new"]})
    assert json.loads(backup.read_text())["seen_sessions"] == ["old"]
    assert json.loads((mem / "dream_state.json").read_text())["seen_sessions"] \
        == ["new"]
    assert not (mem / "dream_state.json.tmp").exists()


# -- drain command builder -----------------------------------------------------------

def test_build_dream_cmd_defaults():
    cmd = bf.build_dream_cmd("py", "/mem", "/db", "local", 200)
    # --memory is a GLOBAL argparse flag: it must precede the subcommand
    assert cmd.index("--memory") < cmd.index("dream")
    assert cmd[cmd.index("--budget") + 1] == "200"
    assert "--source" in cmd and "hermes" in cmd

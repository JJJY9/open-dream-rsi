"""Tests for scripts/backfill_history.py (burned-session requeue tooling).

stdlib unittest — the suite must run with `python -m unittest discover`
on a bare interpreter (no pytest dependency).
"""

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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


class BackfillTests(unittest.TestCase):
    """One fresh workspace (state db + memory root) per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.db = make_state_db(base / "state.db", [
            ("s1", "/opt/data/workspace/radoskoppl", 0, 0),   # burned
            ("s2", "/opt/data/workspace/wiki", 0, 0),         # curated: not burned
            ("s3", "/opt/data/workspace/radoskoppl", 0, 0),   # rejected, unseen: not burned
            ("s4", "/opt/data/workspace/gdansk-network", 1, 0),  # archived: invisible
            ("s5", "", 0, 0),                                 # burned, no cwd
        ])
        self.mem = make_memory(base / "mem",
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

    # -- burned logic -----------------------------------------------------------

    def test_burned_sessions_rules(self):
        visible = bf.visible_sessions(self.db)
        seen = {"s1", "s2", "s4"}
        curated, rejected = bf.event_sets(self.mem / "events.jsonl")
        burn = bf.burned_sessions(curated, rejected, visible, seen)
        self.assertEqual(burn, {"s1"})  # s2 curated; s3 unseen (re-distills
        #                                  anyway); s5 unseen; archived s4 invisible

    def test_burned_requires_visibility_and_seen(self):
        curated, rejected = bf.event_sets(self.mem / "events.jsonl")
        # not in store -> never burned; not seen -> never burned (re-distills
        # anyway); rejected+seen+visible and never curated -> burned
        self.assertEqual(
            bf.burned_sessions(curated, rejected, {}, {"s3"}), set())
        self.assertEqual(
            bf.burned_sessions(curated, rejected, {"s3": "/x"}, set()), set())
        self.assertEqual(
            bf.burned_sessions(curated, rejected, {"s3": "/x"}, {"s3"}), {"s3"})

    def test_burned_excludes_no_failure_evidence(self):
        # a session rejected for genuinely having no failure evidence must not
        # be flagged burned — requeueing it would loop forever with zero yield
        curated, rejected = bf.event_sets(self.mem / "events.jsonl")
        rejected["s9"] = "no failure evidence"
        self.assertNotIn("s9", bf.burned_sessions(curated, rejected,
                                                  {"s9": "/x"}, {"s9"}))

    # -- plan -------------------------------------------------------------------

    def test_plan_reports_counts(self):
        args = type("A", (), {"memory": self.mem, "state_db": self.db,
                              "category": None})()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(bf.cmd_plan(args), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["visible_sessions"], 4)      # s4 archived excluded
        self.assertEqual(out["burned_without_lesson"], 1)  # s1 (s5 unseen, s3 unseen)
        self.assertEqual(out["unseen"], 2)                 # s3, s5
        self.assertEqual(out["probe_backlog"], 2)
        self.assertEqual(out["burned_by_category"], {"radoskoppl": 1})

    def test_plan_category_filter(self):
        args = type("A", (), {"memory": self.mem, "state_db": self.db,
                              "category": "radoskoppl"})()
        buf = io.StringIO()
        with redirect_stdout(buf):
            bf.cmd_plan(args)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["burned_without_lesson"], 1)

    # -- requeue ----------------------------------------------------------------

    def test_requeue_dry_run_writes_nothing(self):
        args = type("A", (), {"memory": self.mem, "state_db": self.db,
                              "category": None, "apply": False})()
        buf = io.StringIO()
        with redirect_stdout(buf):
            bf.cmd_requeue(args)
        self.assertIn("dry-run", buf.getvalue())
        state = json.loads((self.mem / "dream_state.json").read_text())
        self.assertEqual(state["seen_sessions"], ["s1", "s2", "s4"])

    def test_requeue_applies_with_backup(self):
        args = type("A", (), {"memory": self.mem, "state_db": self.db,
                              "category": None, "apply": True})()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(bf.cmd_requeue(args), 0)
        state = json.loads((self.mem / "dream_state.json").read_text())
        self.assertEqual(state["seen_sessions"], ["s2", "s4"])  # burned s1 removed
        backups = list(self.mem.glob("dream_state.json.bak-backfill-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["seen_sessions"],
                         ["s1", "s2", "s4"])               # restore point intact

    def test_requeue_idempotent(self):
        for _ in range(2):
            args = type("A", (), {"memory": self.mem, "state_db": self.db,
                                  "category": None, "apply": True})()
            with redirect_stdout(io.StringIO()):
                bf.cmd_requeue(args)
        state = json.loads((self.mem / "dream_state.json").read_text())
        self.assertEqual(state["seen_sessions"], ["s2", "s4"])  # stable, no dupes


# -- probe pruning ----------------------------------------------------------------

class PruneProbesTests(unittest.TestCase):
    def test_prune_probes_keeps_manual_and_newest(self):
        tasks = [{"task_id": "probe:20260901_a"},
                 {"task_id": "manual-1"},
                 {"task_id": "probe:20261010_b"},
                 {"task_id": "probe:20260815_c"}]
        out, removed = bf.prune_probes(tasks, 2)
        ids = [t["task_id"] for t in out]
        self.assertEqual(removed, 1)
        self.assertNotIn("probe:20260815_c", ids)          # oldest probe dropped
        self.assertEqual(ids, ["probe:20260901_a", "manual-1", "probe:20261010_b"])
        self.assertIn("manual-1", ids)                     # original order kept

    def test_prune_probes_noop_when_under_limit(self):
        tasks = [{"task_id": "probe:a"}, {"task_id": "manual-1"}]
        out, removed = bf.prune_probes(tasks, 5)
        self.assertEqual(removed, 0)
        self.assertEqual(out, tasks)

    def test_prune_probes_command_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = make_memory(Path(tmp) / "mem", seen=[], events=[],
                              tasks=[{"task_id": "probe:20260901_a"},
                                     {"task_id": "manual-1"},
                                     {"task_id": "probe:20261010_b"},
                                     {"task_id": "probe:20260815_c"}])
            args = type("A", (), {"memory": mem, "keep": 2, "apply": True})()
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(bf.cmd_prune_probes(args), 0)
            self.assertIn("removing 1", buf.getvalue())
            kept = json.loads((mem / "tasks.json").read_text())
            self.assertEqual([t["task_id"] for t in kept],
                             ["probe:20260901_a", "manual-1", "probe:20261010_b"])
            self.assertTrue(list(mem.glob("tasks.json.bak-backfill-*")))


# -- state save -------------------------------------------------------------------

class SaveStateTests(unittest.TestCase):
    def test_save_state_backup_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp) / "mem"
            mem.mkdir()
            (mem / "dream_state.json").write_text('{"seen_sessions": ["old"]}')
            backup = bf.save_state(mem, {"seen_sessions": ["new"]})
            self.assertEqual(json.loads(backup.read_text())["seen_sessions"],
                             ["old"])
            self.assertEqual(
                json.loads((mem / "dream_state.json").read_text())["seen_sessions"],
                ["new"])
            self.assertFalse((mem / "dream_state.json.tmp").exists())


# -- drain command builder ----------------------------------------------------------

class DrainTests(unittest.TestCase):
    def test_drain_reports_skip_and_stops(self):
        """The lock-holding case must print a clear skip line and stop, not
        print None fields (regression: the first live drain run did)."""
        class FakeProc:
            returncode = 0
            stdout = json.dumps({"skipped": True,
                                 "reason": "another dream is running"})
            stderr = ""

        calls = []

        def fake_run(cmd, capture_output, text):
            calls.append(cmd)
            return FakeProc()

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(bf.subprocess, "run", fake_run):
                args = type("A", (), {"memory": Path(tmp) / "mem",
                                      "state_db": Path(tmp) / "db",
                                      "cycles": 3, "provider": "local",
                                      "budget": 1, "skills_out": None})()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    self.assertEqual(bf.cmd_drain(args), 0)
        out = buf.getvalue()
        self.assertIn("skipped", out)
        self.assertIn("another dream is running", out)
        self.assertNotIn("None", out)
        self.assertEqual(len(calls), 1)  # break: no retry against a held lock


class BuildCmdTests(unittest.TestCase):
    def test_build_dream_cmd_defaults(self):
        cmd = bf.build_dream_cmd("py", "/mem", "/db", "local", 200)
        # --memory is a GLOBAL argparse flag: it must precede the subcommand
        self.assertLess(cmd.index("--memory"), cmd.index("dream"))
        self.assertEqual(cmd[cmd.index("--budget") + 1], "200")
        self.assertIn("--source", cmd)
        self.assertIn("hermes", cmd)


if __name__ == "__main__":
    unittest.main()

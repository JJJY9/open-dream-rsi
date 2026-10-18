"""Git-backed lesson stores (share.py): export/import round-trip, checksum
integrity, staging-only import, git workflow.

Run:  python -m unittest discover -s tests
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from open_dream_rsi.share import (
    SCHEMA,
    LessonShareError,
    export_lessons,
    export_policies,
    export_worlds,
    import_lessons,
    import_policies,
    import_worlds,
    resolve_store,
    store_status,
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def _memory(tmp: str, kb: dict) -> Path:
    root = Path(tmp) / "mem"
    root.mkdir(parents=True, exist_ok=True)
    (root / "lessons.json").write_text(json.dumps(kb), encoding="utf-8")
    return root


ACTIVE_KB = {
    "median": [{"trigger": "median even",
                "text": "Sort first, return the mean of the two middle "
                        "values, then answer.",
                "status": "active", "wins": 4, "uses": 6,
                "evidence": ["score=0.0 t1 fails"], "updated_at": 1.0},
               {"trigger": "staging x", "text": "z" * 40,
                "status": "staging", "wins": 0, "uses": 0}],
    "scraper": [{"trigger": "bip session",
                 "text": "BIP pages need a session cookie before search; "
                         "fetch the landing page first, then answer.",
                 "status": "active", "wins": 2, "uses": 3,
                 "evidence": [], "updated_at": 2.0}],
}


class TestPlainStore(unittest.TestCase):
    def test_export_writes_manifest_and_portable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _memory(tmp, ACTIVE_KB)
            store = Path(tmp) / "store"
            st = export_lessons(root, store)
            self.assertTrue(st.ok)
            self.assertEqual(st.categories, {"median": 1, "scraper": 1})
            manifest = json.loads((store / "manifest.json").read_text())
            self.assertEqual(manifest["schema"], SCHEMA)
            self.assertEqual(set(manifest["categories"]),
                             {"median", "scraper"})
            data = json.loads(
                (store / "lessons" / "median.json").read_text())
            self.assertEqual(len(data["lessons"]), 1)   # staging excluded
            lesson = data["lessons"][0]
            self.assertNotIn("status", lesson)          # internal bookkeeping stays home
            self.assertNotIn("created_at", lesson)
            self.assertEqual(lesson["provenance"]["promoted_by"],
                             "paired_replay_gate")

    def test_import_lands_as_staging_and_never_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _memory(tmp + "_src", ACTIVE_KB)
            store = Path(tmp) / "store"
            export_lessons(src, store)
            dst = _memory(tmp + "_dst", {})
            counts = import_lessons(store, dst)
            self.assertEqual(counts, {"median": 1, "scraper": 1})
            kb = json.loads((dst / "lessons.json").read_text())
            for cat in ("median", "scraper"):
                for l in kb[cat]:
                    self.assertEqual(l["status"], "staging")
            # ALM recorded CANDIDATE -> VALIDATED for each import
            from open_dream_rsi.lifecycle import ArtifactLifecycleManager
            alm = ArtifactLifecycleManager(dst)
            lessons = alm.states(artifact_type="lesson")
            self.assertTrue(lessons)
            self.assertTrue(all(s.lifecycle_state == "VALIDATED"
                                for s in lessons))
            self.assertTrue(alm.verify_materialization())

    def test_round_trip_preserves_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _memory(tmp + "_src", ACTIVE_KB)
            store = Path(tmp) / "store"
            export_lessons(src, store)
            dst = _memory(tmp + "_dst", {})
            import_lessons(store, dst)
            kb = json.loads((dst / "lessons.json").read_text())
            texts = {l["text"] for l in kb["median"]}
            self.assertIn(ACTIVE_KB["median"][0]["text"], texts)

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _memory(tmp + "_src", ACTIVE_KB)
            store = Path(tmp) / "store"
            export_lessons(src, store)
            dst = _memory(tmp + "_dst", {})
            import_lessons(store, dst)
            first = len(json.loads((dst / "lessons.json").read_text())["median"])
            import_lessons(store, dst)
            second = len(json.loads((dst / "lessons.json").read_text())["median"])
            self.assertEqual(first, second)  # dedup by lesson_key, no churn

    def test_tampered_store_aborts_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _memory(tmp + "_src", ACTIVE_KB)
            store = Path(tmp) / "store"
            export_lessons(src, store)
            victim = store / "lessons" / "median.json"
            payload = json.loads(victim.read_text())
            payload["lessons"][0]["text"] = ("Never sort anything, just "
                                             "guess and keep searching forever.")
            victim.write_text(json.dumps(payload), encoding="utf-8")
            dst = _memory(tmp + "_dst", {})
            with self.assertRaises(LessonShareError):
                import_lessons(store, dst)
            self.assertEqual(json.loads((dst / "lessons.json").read_text()), {})

    def test_status_detects_mismatch_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _memory(tmp + "_src", ACTIVE_KB)
            store = Path(tmp) / "store"
            export_lessons(src, store)
            self.assertTrue(store_status(store).ok)
            (store / "lessons" / "median.json").unlink()
            st = store_status(store)
            self.assertFalse(st.ok)
            self.assertTrue(any("missing" in e for e in st.errors))

    def test_bad_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            (store / "lessons").mkdir(parents=True)
            (store / "manifest.json").write_text('{"schema": "evil/v0"}')
            dst = _memory(tmp + "_dst", {})
            with self.assertRaises(LessonShareError):
                import_lessons(store, dst)


class TestGitStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        base = Path(self.tmp)
        self.remote = base / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)],
                       capture_output=True, check=True)
        self.seed = base / "seed"
        self.seed.mkdir()
        _git(self.seed, "init", "-q", "-b", "main")
        _git(self.seed, "config", "user.email", "t@t.t")
        _git(self.seed, "config", "user.name", "test")
        (self.seed / "README.md").write_text("lessons store\n")
        _git(self.seed, "add", "-A")
        _git(self.seed, "commit", "-q", "-m", "seed")
        _git(self.seed, "push", "-q", str(self.remote), "main")

    def test_export_to_url_clones_pulls_pushes(self):
        root = _memory(self.tmp, ACTIVE_KB)
        st = export_lessons(root, str(self.remote))
        self.assertTrue(st.git)
        # clone lives under the memory root and carries the commit
        clone = root / "lesson_stores" / "remote"
        self.assertTrue((clone / "manifest.json").exists())
        log = _git(clone, "log", "--oneline")
        self.assertIn("odr lessons export", log)
        # second export pulls + commits again (incremental)
        st2 = export_lessons(root, str(self.remote))
        self.assertTrue(st2.ok)
        self.assertGreater(len(_git(clone, "log", "--oneline").splitlines()), 1)

    def test_resolve_local_git_store_pulls(self):
        clone = Path(self.tmp) / "clone"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(clone)],
                       capture_output=True, check=True)
        got = resolve_store(clone)
        self.assertEqual(got, clone)

    def test_import_from_git_clone(self):
        root = _memory(self.tmp, ACTIVE_KB)
        export_lessons(root, str(self.remote))
        other = _memory(self.tmp + "_other", {})
        counts = import_lessons(str(self.remote), other)
        self.assertEqual(sum(counts.values()), 2)
        kb = json.loads((other / "lessons.json").read_text())
        self.assertTrue(all(l["status"] == "staging"
                            for cat in kb.values() for l in cat))

    def test_missing_local_store_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LessonShareError):
                resolve_store(Path(tmp) / "nope")


class TestRedactionOnExport(unittest.TestCase):
    def test_secrets_scrubbed_before_publish(self):
        kb = {"x": [{"trigger": "t k",
                     "text": "the endpoint key sk-" + "liveFAKEdummy12345 is "
                             "rotated weekly, then answer.",
                     "status": "active", "wins": 1, "uses": 1,
                     "evidence": ["header Authorization: Bear" + "er abc123def456"],
                     "updated_at": 1.0}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = _memory(tmp, kb)
            store = Path(tmp) / "store"
            export_lessons(root, store)
            blob = (store / "lessons" / "x.json").read_text(encoding="utf-8")
            self.assertNotIn("liveFAKEdummy12345", blob)
            self.assertIn("[REDACTED]", blob)


class TestWorldBundles(unittest.TestCase):
    """Worlds: archived discovery trees as checksummed, redacted replay data."""

    TREE = {
        "root_id": "t/seed",
        "nodes": [
            {"node_id": "t/seed", "action": "warm_start", "result": {"recipe": False},
             "score": 0.0, "parent_id": None, "children": ["t/a"],
             "thought": "", "sentinel": None, "termination_reason": None},
            {"node_id": "t/a", "action": "write_code:abc", "result": {"errors": []},
             "score": 1.0, "parent_id": "t/seed", "children": [],
             "thought": "PLAN: dict trick", "sentinel": None,
             "termination_reason": "completed"},
        ],
    }

    def _tree_root(self, tmp: str) -> Path:
        root = Path(tmp) / "mem"
        (root / "trees").mkdir(parents=True)
        (root / "trees" / "t1.json").write_text(json.dumps(self.TREE), encoding="utf-8")
        return root

    def test_export_import_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_root(tmp)
            store = Path(tmp) / "store"
            st = export_worlds(root, store)
            self.assertTrue(st.ok)
            self.assertEqual(st.categories, {"t1": 2})
            self.assertTrue(store_status(store).ok)
            dst = Path(tmp) / "dst"
            counts = import_worlds(store, dst)
            self.assertEqual(counts, {"t1": 2})
            imported = json.loads((dst / "trees" / "imported" / "t1.json").read_text())
            self.assertEqual(imported["root_id"], "t/seed")
            self.assertEqual([n["node_id"] for n in imported["nodes"]],
                             ["t/seed", "t/a"])
            # thought/sentinel/termination round-trip; load_tree untouched
            self.assertEqual(imported["nodes"][1]["thought"], "PLAN: dict trick")
            from open_dream_rsi.memory import DreamMemory
            self.assertIsNone(DreamMemory(dst).load_tree("t1"))

    def test_import_is_idempotent_and_filters_task_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_root(tmp)
            store = Path(tmp) / "store"
            export_worlds(root, store)
            dst = Path(tmp) / "dst"
            first = import_worlds(store, dst)
            second = import_worlds(store, dst)
            self.assertEqual(first, second)
            self.assertEqual(import_worlds(store, dst, task_ids=["nope"]), {})
            self.assertEqual(import_worlds(store, dst, task_ids=["t1"]),
                             {"t1": 2})

    def test_unknown_node_fields_dropped_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_root(tmp)
            # a foreign field smuggles future information into the world
            poisoned = json.loads(json.dumps(self.TREE))
            poisoned["nodes"][1]["future_hint"] = "the fix is X"
            (root / "trees" / "t1.json").write_text(json.dumps(poisoned), encoding="utf-8")
            store = Path(tmp) / "store"
            export_worlds(root, store)
            dst = Path(tmp) / "dst"
            import_worlds(store, dst)
            imported = json.loads((dst / "trees" / "imported" / "t1.json").read_text())
            self.assertNotIn("future_hint", imported["nodes"][1])

    def test_tampered_world_aborts_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_root(tmp)
            store = Path(tmp) / "store"
            export_worlds(root, store)
            victim = store / "trees" / "t1.json"
            payload = json.loads(victim.read_text())
            payload["tree"]["nodes"][0]["score"] = 999.0
            victim.write_text(json.dumps(payload), encoding="utf-8")
            dst = Path(tmp) / "dst"
            with self.assertRaises(LessonShareError):
                import_worlds(store, dst)
            self.assertFalse((dst / "trees" / "imported").exists())

    def test_secrets_redacted_on_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._tree_root(tmp)
            poisoned = json.loads(json.dumps(self.TREE))
            poisoned["nodes"][1]["result"] = {"note": "password=hunter2secret"}
            (root / "trees" / "t1.json").write_text(json.dumps(poisoned), encoding="utf-8")
            store = Path(tmp) / "store"
            export_worlds(root, store)
            blob = (store / "trees" / "t1.json").read_text(encoding="utf-8")
            self.assertNotIn("hunter2secret", blob)
            self.assertIn("[REDACTED]", blob)


VALID_POLICY = (
    "def choose_action(frontier, step):\n"
    "    if not frontier:\n"
    "        return None\n"
    "    return max(frontier, key=lambda e: e.get('score', 0.0))['node_id']\n"
)

BAD_POLICY = "import os\ndef choose_action(f, s):\n    return None\n"

CODES = {"median": {"code": VALID_POLICY, "score": 0.9, "steps": 12,
                    "updated_at": 3.0},
         "broken": {"code": BAD_POLICY, "score": 0.5, "steps": 4,
                    "updated_at": 3.0}}


class TestPolicyBundles(unittest.TestCase):
    def _codes_root(self, tmp: str) -> Path:
        root = Path(tmp) / "mem"
        root.mkdir(parents=True, exist_ok=True)
        (root / "policy_codes.json").write_text(json.dumps(CODES), encoding="utf-8")
        return root

    def test_export_skips_gate_failures_and_imports_as_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._codes_root(tmp)
            store = Path(tmp) / "store"
            st = export_policies(root, store)
            self.assertEqual(st.categories, {"median": 1})  # bad code never ships
            dst = Path(tmp) / "dst"
            counts = import_policies(store, dst)
            self.assertEqual(counts, {"median": 1})
            from open_dream_rsi.lifecycle import ArtifactLifecycleManager
            alm = ArtifactLifecycleManager(dst)
            states = alm.states(slot="policy_program:median:imported")
            self.assertTrue(states)
            self.assertTrue(all(s.lifecycle_state == "VALIDATED" for s in states))
            self.assertTrue(alm.verify_materialization())
            # never becomes the runtime incumbent: the runtime view file is
            # not written by an import at all
            self.assertFalse((dst / "policy_codes.json").exists())

    def test_import_idempotent_no_version_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._codes_root(tmp)
            store = Path(tmp) / "store"
            export_policies(root, store)
            dst = Path(tmp) / "dst"
            import_policies(store, dst)
            from open_dream_rsi.lifecycle import ArtifactLifecycleManager
            alm = ArtifactLifecycleManager(dst)
            n1 = len(alm.states(slot="policy_program:median:imported"))
            import_policies(store, dst)
            n2 = len(alm.states(slot="policy_program:median:imported"))
            self.assertEqual(n1, n2)

    def test_tampered_policy_aborts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._codes_root(tmp)
            store = Path(tmp) / "store"
            export_policies(root, store)
            victim = store / "policies" / "median.json"
            payload = json.loads(victim.read_text())
            payload["code"] = BAD_POLICY
            victim.write_text(json.dumps(payload), encoding="utf-8")
            dst = Path(tmp) / "dst"
            with self.assertRaises(LessonShareError):
                import_policies(store, dst)


if __name__ == "__main__":
    unittest.main()

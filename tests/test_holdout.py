"""Single-use holdout reservations (holdout.py): claim semantics, idempotent
same-purpose resume, cross-purpose refusal, split_reserved filtering."""

import tempfile
import unittest
from pathlib import Path

from open_dream_rsi.holdout import HoldoutRegistry, split_reserved
from open_dream_rsi.loop import Task


class TestClaim(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = HoldoutRegistry(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_claim_wins(self):
        self.assertTrue(self.reg.claim("t1", "final_pass", phase="eval"))
        self.assertEqual(self.reg.entries()["t1"]["purpose"], "final_pass")
        self.assertEqual(self.reg.entries()["t1"]["phase"], "eval")

    def test_different_purpose_refused(self):
        self.reg.claim("t1", "selection")
        self.assertFalse(self.reg.claim("t1", "final_pass"))
        # the original reservation is untouched
        self.assertEqual(self.reg.entries()["t1"]["purpose"], "selection")

    def test_same_purpose_idempotent(self):
        self.reg.claim("t1", "selection", phase="A")
        self.assertTrue(self.reg.claim("t1", "selection"))
        self.assertEqual(self.reg.entries()["t1"]["phase"], "A")  # first record kept

    def test_persists_across_instances(self):
        self.reg.claim("t1", "final_pass")
        reg2 = HoldoutRegistry(self.tmp.name)
        self.assertFalse(reg2.claim("t1", "other"))
        self.assertTrue(reg2.claim("t1", "final_pass"))

    def test_release_allows_reclaim(self):
        self.reg.claim("t1", "wrong_phase")
        self.assertTrue(self.reg.release("t1"))
        self.assertFalse(self.reg.release("t1"))  # nothing to release
        self.assertTrue(self.reg.claim("t1", "final_pass"))

    def test_empty_args_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.claim(" ", "p")
        with self.assertRaises(ValueError):
            self.reg.claim("t", " ")

    def test_corrupt_file_resets_to_empty(self):
        p = Path(self.tmp.name) / "holdout_reservations.json"
        p.write_text("{not json", encoding="utf-8")
        reg = HoldoutRegistry(self.tmp.name)
        self.assertEqual(reg.entries(), {})
        self.assertTrue(reg.claim("t1", "final_pass"))


class TestSplitReserved(unittest.TestCase):
    def test_task_objects_and_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = HoldoutRegistry(tmp)
            reg.claim("t2", "final_pass")
            tasks = [Task(task_id="t1", category="c", prompt="p", tests=[]),
                     {"task_id": "t2", "category": "c", "prompt": "p",
                      "tests": []},
                     Task(task_id="t3", category="c", prompt="p", tests=[])]
            allowed, held = split_reserved(tasks, reg)
            self.assertEqual([t.task_id for t in allowed], ["t1", "t3"])
            self.assertEqual(held, [{"task_id": "t2", "category": "c",
                                     "prompt": "p", "tests": []}])

    def test_nothing_reserved_everything_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed, held = split_reserved(
                [Task(task_id="t1", category="c", prompt="p", tests=[])],
                HoldoutRegistry(tmp))
            self.assertEqual(len(allowed), 1)
            self.assertEqual(held, [])


if __name__ == "__main__":
    unittest.main()

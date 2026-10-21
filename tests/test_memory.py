"""Discovery-tree archive filenames on hosts with Windows path rules.

Probe task ids are ``probe:<cursor-session>``; a colon is legal in a task id
but not in a Windows filename, so the archive maps ids to a portable stem.
"""
import json
import tempfile
import unittest
from pathlib import Path

from open_dream_rsi.core.tree import DiscoveryTree
from open_dream_rsi.memory import DreamMemory


def _tree() -> DiscoveryTree:
    tree = DiscoveryTree()
    tree.add_node("r", "seed", None, 0.0)
    return tree


class TaskTreeFilenameTests(unittest.TestCase):
    def test_probe_ids_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = DreamMemory(tmp)
            mem.archive_tree("probe:c-1", _tree())
            names = [p.name for p in (mem.root / "trees").glob("*.json")]
            self.assertEqual(names, ["probe%3Ac-1.json"])
            back = mem.load_tree("probe:c-1")
            self.assertIsNotNone(back)
            self.assertEqual(back.root_id, "r")
            payload = json.loads(
                (mem.root / "trees" / names[0]).read_text(encoding="utf-8"))
            self.assertEqual(payload["task_id"], "probe:c-1")

    def test_plain_ids_keep_their_historical_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = DreamMemory(tmp)
            mem.archive_tree("knapsack_t", _tree())
            self.assertTrue(
                (mem.root / "trees" / "knapsack_t.json").exists())
            self.assertIsNotNone(mem.load_tree("knapsack_t"))

    def test_reserved_and_separator_ids_stay_portable(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = DreamMemory(tmp)
            for task_id, stem in (("CON", "%5FCON"),
                                  ("a/b", "a%2Fb"),
                                  ("trailing.", "trailing%2E"),
                                  ("", "%")):
                mem.archive_tree(task_id, _tree())
                self.assertTrue((mem.root / "trees" / f"{stem}.json").exists())
                self.assertIsNotNone(mem.load_tree(task_id))


if __name__ == "__main__":
    unittest.main()

"""Fail the build when vendored copies of the package drift from upstream.

The npm bundle (``plugins/deepseek_harness/``) vendors the whole
``open_dream_rsi`` package so the bundle installs without a pip step. A
stale copy ships old code under the current version number, so the copy is
pinned byte-for-byte: change ``open_dream_rsi/`` and mirror the file into
the vendored tree in the same commit (``diff -rq open_dream_rsi
plugins/deepseek_harness/open_dream_rsi -x __pycache__`` must be empty;
CI enforces it too).
"""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "open_dream_rsi"
VENDORED = REPO / "plugins" / "deepseek_harness" / "open_dream_rsi"
IGNORED_DIRS = {"__pycache__"}


def _rel_paths(root: Path) -> set:
    return {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and not (IGNORED_DIRS & set(p.parts))
    }


class VendoredPackageDriftTest(unittest.TestCase):
    def test_vendored_tree_matches_upstream(self):
        up = _rel_paths(UPSTREAM)
        ven = _rel_paths(VENDORED)
        self.assertEqual(
            up - ven, set(),
            "files missing from the vendored npm bundle copy: "
            f"{sorted(up - ven)}",
        )
        self.assertEqual(
            ven - up, set(),
            "stale files only in the vendored npm bundle copy: "
            f"{sorted(ven - up)}",
        )
        drifted = [
            rel for rel in sorted(up)
            if (UPSTREAM / rel).read_bytes() != (VENDORED / rel).read_bytes()
        ]
        self.assertEqual(
            drifted, [],
            "vendored npm bundle copy drifted from open_dream_rsi/ — mirror "
            "the changed files into plugins/deepseek_harness/open_dream_rsi/ "
            f"in the same commit: {drifted}",
        )


if __name__ == "__main__":
    unittest.main()

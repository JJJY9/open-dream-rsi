"""Typecheck contract for the published py.typed promise.

The library ships ``open_dream_rsi/py.typed`` (PEP 561), which tells users the
annotations are reliable. As of the 0.3.9 external-review round, ``mypy
open_dream_rsi/ --ignore-missing-imports`` is CLEAN (pinned mypy version in
CI); these tests keep it that way: any new type error fails the suite. The
mypy run is cached per process — both tests read one output.

Skips when mypy is not installed (stdlib-only library; mypy is a dev tool).
"""

import os
import subprocess
import unittest

_MYPY_CACHE: dict = {}


def _run_mypy():
    import sys

    if "out" not in _MYPY_CACHE:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "mypy", "open_dream_rsi/",
                 "--ignore-missing-imports"],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True, text=True,
            )
            _MYPY_CACHE["out"] = proc.stdout + proc.stderr
        except FileNotFoundError:
            _MYPY_CACHE["out"] = None
    return _MYPY_CACHE["out"]


class TestMypyBaseline(unittest.TestCase):
    def test_no_type_errors(self):
        out = _run_mypy()
        if out is None:
            self.skipTest("mypy not installed")
        errors = [line for line in out.splitlines() if ": error:" in line]
        self.assertEqual(
            errors, [],
            f"py.typed promise: mypy must stay clean (pinned version in CI)\n"
            f"{chr(10).join(errors[-20:])}",
        )

    def test_clean_on_exact_baseline_fileset(self):
        out = _run_mypy()
        if out is None:
            self.skipTest("mypy not installed")
        files = {line.split(":")[0] for line in out.splitlines() if ": error:" in line}
        self.assertEqual(files, set(), f"unexpected error files: {sorted(files)}")


if __name__ == "__main__":
    unittest.main()

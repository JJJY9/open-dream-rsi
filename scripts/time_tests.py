"""Per-module wall-time profile of the test suite (slow-test triage).

Usage: python scripts/time_tests.py [top_n]

Ranks test modules by wall time so SLOW_MODULES in scripts/fast_tests.py
stays honest: a module belongs in the fast-path exclusion set only while it
is measured multi-second. Stdlib only; run on the interpreter CI uses
(3.10-3.13).
"""
import io
import sys
import time
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    top_n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    suite = unittest.TestLoader().discover("tests")

    mods = defaultdict(list)

    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite):
                walk(t)
            else:
                mods[t.__class__.__module__].append(t)

    walk(suite)

    rows = []
    for mod, tests in mods.items():
        runner = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0)
        t0 = time.time()
        result = runner.run(unittest.TestSuite(tests))
        rows.append((time.time() - t0, mod, len(tests),
                     len(result.failures) + len(result.errors)))

    rows.sort(reverse=True)
    print(f"SLOWEST {top_n} MODULES (wall time):")
    for dt, mod, n, bad in rows[:top_n]:
        print(f"{dt:7.1f}s {n:4d} tests {bad} bad  {mod}")
    total = sum(r[0] for r in rows)
    count = sum(len(v) for v in mods.values())
    print(f"TOTAL {total:.1f}s over {count} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

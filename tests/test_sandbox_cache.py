"""Sandbox result cache (sandbox.py): content-keyed identity, LRU/TTL bounds,
completed-runs-only caching, opt-in integration with CodeVerifier/PolicySandbox."""

import subprocess
import unittest

from open_dream_rsi.sandbox import (SandboxCache, cached_run_isolated,
                                    content_key)
from open_dream_rsi.tools import CodeVerifier


class FakeRun:
    """Stand-in for run_isolated: counts invocations, returns/raises on cue.

    ``fail_times``: raise ``exc`` for the first N calls, then return ``proc``
    (models "the environment hiccuped once, the retry succeeded")."""

    def __init__(self, proc=None, exc=None, fail_times: int = 0):
        self.proc = proc or subprocess.CompletedProcess([], 0, "out", "err")
        self.exc = exc
        self.fail_times = int(fail_times)
        self.calls = 0

    def __call__(self, argv, timeout, cwd=None, env=None):
        self.calls += 1
        if self.exc is not None and self.calls <= self.fail_times:
            raise self.exc
        return self.proc


class TestContentKey(unittest.TestCase):
    def test_same_content_same_key_regardless_of_paths(self):
        k1 = content_key({"harness": "H", "policy": "P"}, timeout=5.0)
        k2 = content_key({"policy": "P", "harness": "H"}, timeout=5.0)
        self.assertEqual(k1, k2)

    def test_different_content_different_key(self):
        base = content_key({"harness": "H", "policy": "P"}, timeout=5.0)
        self.assertNotEqual(base, content_key(
            {"harness": "H", "policy": "Q"}, timeout=5.0))
        self.assertNotEqual(base, content_key(
            {"harness": "H", "policy": "P"}, timeout=6.0))

    def test_nested_values_canonicalized(self):
        k1 = content_key({"world": {"b": 1, "a": [1, 2]}}, timeout=5.0)
        k2 = content_key({"world": {"a": [1, 2], "b": 1}}, timeout=5.0)
        self.assertEqual(k1, k2)


class TestSandboxCache(unittest.TestCase):
    def test_lru_eviction(self):
        cache = SandboxCache(max_entries=2)
        cache.store("a", subprocess.CompletedProcess([], 0))
        cache.store("b", subprocess.CompletedProcess([], 0))
        cache.store("c", subprocess.CompletedProcess([], 0))
        self.assertIsNone(cache.lookup("a"))       # oldest evicted
        self.assertIsNotNone(cache.lookup("c"))

    def test_ttl_expiry(self):
        cache = SandboxCache(ttl_seconds=3600)
        cache.store("k", subprocess.CompletedProcess([], 0))
        # backdate the entry past the TTL
        key, (ts, proc) = next(iter(cache._entries.items()))
        cache._entries[key] = (ts - 4000, proc)
        self.assertIsNone(cache.lookup("k"))

    def test_hit_returns_recorded_result(self):
        proc = subprocess.CompletedProcess(["argv"], 3, "stdout", "stderr")
        run = FakeRun(proc=proc)
        cache = SandboxCache()
        argv = ["python", "-I", "/tmp/whatever.py"]
        key = content_key({"script": "S"}, timeout=1.0)
        first = cached_run_isolated(run, argv, key=key, timeout=1.0, cache=cache)
        second = cached_run_isolated(run, argv, key=key, timeout=1.0, cache=cache)
        self.assertEqual(run.calls, 1)             # second served from cache
        self.assertEqual(first.returncode, 3)
        self.assertEqual(second.stdout, "stdout")
        self.assertEqual(second.stderr, "stderr")
        self.assertEqual(cache.hits, 1)

    def test_timeouts_never_cached(self):
        run = FakeRun(exc=subprocess.TimeoutExpired(cmd=[], timeout=1.0),
                      proc=subprocess.CompletedProcess([], 0, "ok", ""),
                      fail_times=1)
        cache = SandboxCache()
        key = content_key({"script": "S"}, timeout=1.0)
        with self.assertRaises(subprocess.TimeoutExpired):
            cached_run_isolated(run, ["python"], key=key, timeout=1.0, cache=cache)
        result = cached_run_isolated(run, ["python"], key=key, timeout=1.0, cache=cache)
        self.assertEqual(result.stdout, "ok")      # re-ran, not a cached failure
        self.assertEqual(run.calls, 2)
        # the completed retry IS cached: a third call serves it
        again = cached_run_isolated(run, ["python"], key=key, timeout=1.0, cache=cache)
        self.assertEqual(again.stdout, "ok")
        self.assertEqual(run.calls, 2)
        self.assertEqual(cache.hits, 1)

    def test_no_cache_passthrough(self):
        run = FakeRun(proc=subprocess.CompletedProcess([], 0, "x", ""))
        result = cached_run_isolated(run, ["python"], key="k", timeout=1.0, cache=None)
        self.assertEqual(result.stdout, "x")
        self.assertEqual(run.calls, 1)


class TestVerifierCacheIntegration(unittest.TestCase):
    CODE = "def add(a, b):\n    return a + b\n"
    TESTS = [{"call": "add(2, 3)", "expected": 5}]

    def test_repeat_run_is_cached(self):
        cache = SandboxCache()
        v = CodeVerifier(cache=cache)
        r1 = v.run(self.CODE, self.TESTS)
        r2 = v.run(self.CODE, self.TESTS)
        self.assertTrue(r1.ok and r2.ok)
        self.assertEqual(cache.hits, 1)
        self.assertEqual(r1.score, r2.score)

    def test_default_verifier_stays_uncached(self):
        cache = SandboxCache()
        v = CodeVerifier()                          # no cache wired
        v.run(self.CODE, self.TESTS)
        v.run(self.CODE, self.TESTS)
        self.assertEqual(cache.hits, 0)
        self.assertEqual(cache.misses, 0)


class TestPolicySandboxCacheIntegration(unittest.TestCase):
    SOURCE = ("def choose_action(frontier, step):\n"
              "    if not frontier:\n"
              "        return None\n"
              "    return max(frontier, key=lambda n: n['score'])['node_id']\n")

    def _tree(self):
        from open_dream_rsi.core.tree import DiscoveryTree
        tree = DiscoveryTree()
        tree.add_node("s", "warm_start", {}, 0.0)
        tree.add_node("a", "write_code:x", {"errors": ["t1"]}, 0.4, parent_id="s")
        tree.add_node("b", "write_code:y", {"errors": ["t1", "t2"]}, 0.2, parent_id="a")
        return tree

    def test_rollout_repeat_is_cached(self):
        from open_dream_rsi.core.policygen import PolicySandbox, rollout_world_payload
        cache = SandboxCache()
        sb = PolicySandbox(cache=cache)
        world = rollout_world_payload(self._tree())
        r1 = sb.rollout(self.SOURCE, world)
        r2 = sb.rollout(self.SOURCE, world)
        self.assertIsNone(r1[3])
        self.assertIsNone(r2[3])
        self.assertEqual(r1[0], r2[0])
        self.assertEqual(cache.hits, 1)


if __name__ == "__main__":
    unittest.main()

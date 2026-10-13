"""Replay test: the sentinel engine on the anonymized production audit fixture.

Fixtures/sentinel_audit.json is (class_id, session_id) event pairs in
arrival order, derived from a production agent session store (30 days,
4914 error events / 459 classes / 476 sessions), fully anonymized: no
message content, timestamps, tool names or real session ids. Class ids
are opaque; the fixture is order-preserving, so the engine replay must
reproduce the recorded note count exactly — it is a behavioral
regression test for the whole policy stack (signature stability,
thresholds, one-note-per-class-per-session), not a statistic.

stdlib unittest — the suite must run with `python -m unittest discover`
on a bare interpreter (no pytest dependency).
"""
import json
import tempfile
import unittest
from pathlib import Path

from open_dream_rsi.sentinel import SentinelEngine

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sentinel_audit.json"


def _payload_for(class_id: int) -> str:
    # stable, class-unique, keyword-bearing payload: normalizes to itself
    # (letters only), so one fixture class == one live error class
    return f"error class {class_id:06d}".translate(
        str.maketrans("0123456789", "abcdefghij"))


class SentinelAuditReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not FIXTURE.exists():
            raise unittest.SkipTest("anonymized audit fixture not present")
        cls.audit = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_meta_counts_are_self_consistent(self):
        meta, events = self.audit["meta"], self.audit["events"]
        self.assertEqual(len(events), meta["error_events"])
        self.assertEqual(len({e[0] for e in events}), meta["distinct_classes"])
        self.assertEqual(len({e[1] for e in events}), meta["sessions"])
        per = {}
        repeats = 0
        for c, s in events:
            k = (c, s)
            per[k] = per.get(k, 0) + 1
            if per[k] >= 2:
                repeats += 1
        self.assertEqual(repeats,
                         meta["repeat_events_same_class_same_session"])
        self.assertTrue(40 < meta["pct_repeats"] < 60)   # ~half of failures repeat

    def test_engine_replay_reproduces_recorded_note_count(self):
        meta, events = self.audit["meta"], self.audit["events"]
        with tempfile.TemporaryDirectory() as tmp:
            engine = SentinelEngine(state_path=Path(tmp) / "s.json")
            notes = sum(1 for c, s in events
                        if engine.observe("t", _payload_for(c), s, status="error"))
        self.assertEqual(notes, meta["notes_emitted_by_engine"])
        # the annotation tax is bounded: ~4 notes per 10 error events, and every
        # note is the threshold crossing of a class the session already suffered
        self.assertLess(notes / meta["error_events"], 0.5)

    def test_engine_is_stateless_across_restarts_on_the_fixture(self):
        """Restarting the process mid-stream must not change the outcome —
        durability is by state file, not by memory."""
        meta, events = self.audit["meta"], self.audit["events"]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "s.json"
            notes = 0
            for i in range(0, len(events), 500):      # simulated restarts
                chunk = events[i:i + 500]
                engine = SentinelEngine(state_path=state)
                notes += sum(1 for c, s in chunk
                             if engine.observe("t", _payload_for(c), s,
                                               status="error"))
        self.assertEqual(notes, meta["notes_emitted_by_engine"])


if __name__ == "__main__":
    unittest.main()

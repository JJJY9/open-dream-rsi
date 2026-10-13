"""Tests for user-correction extraction (issue #6).

Run:  python -m unittest tests.test_corrections
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from open_dream_rsi.corrections import (
    classify_user_message,
    dedupe_corrections,
    distillable,
    prioritize_corrections,
    user_corrections,
)
from open_dream_rsi.dream import ingest_sessions
from open_dream_rsi.memory import DreamMemory
from open_dream_rsi.sessions import Episode, SessionMessage


def _ep(*msgs, sid="s1", cwd="/repo/proj"):
    return Episode(source="hermes", session_id=sid, title="t", cwd=cwd,
                   messages=[SessionMessage(role=r, text=t)
                             for r, t in msgs])


_VALID_REPLY = json.dumps([{
    "trigger": "reuse shared http client",
    "text": "Within this workspace, reuse the shared HTTP client and its "
            "retry handling before creating another client.",
}])


class _OkLLM:
    def chat(self, *a, **k):
        return _VALID_REPLY


class TestClassification(unittest.TestCase):
    def test_correction_redirect_preference_requirement(self):
        self.assertEqual(classify_user_message(
            "Nie tak, to założenie jest błędne — to API zwraca stronicowane "
            "wyniki i trzeba tego użyć."), "correction")
        self.assertEqual(classify_user_message(
            "Nie twórz kolejnego klienta HTTP, zamiast tego użyj istniejącego "
            "wspólnego klienta z obsługą retry."), "correction")
        self.assertEqual(classify_user_message(
            "Don't create a new HTTP client; reuse the existing client with "
            "retry handling instead."), "correction")
        self.assertEqual(classify_user_message(
            "Myślę że powinieneś użyć wzorca repozytorium zamiast tego "
            "podejścia, bo łamie granicę transakcji."), "correction")
        self.assertEqual(classify_user_message(
            "Zawsze dziel commity na małe, niezależne porcje w tym projekcie."
            ), "preference")
        self.assertEqual(classify_user_message(
            "Preferuję małe, niezależne commity zamiast jednego dużego."
            ), "preference")
        self.assertEqual(classify_user_message(
            "Dodaj jeszcze obsługę retry przy okazji refactoru."
            ), "new_requirement")

    def test_ambiguity_and_noise_rejected(self):
        self.assertIsNone(classify_user_message("ok, spoko"))
        self.assertIsNone(classify_user_message("no"))
        self.assertIsNone(classify_user_message("a co z paginacją?"))
        self.assertIsNone(classify_user_message("why?"))
        self.assertIsNone(classify_user_message("krótko"))
        self.assertIsNone(classify_user_message(
            "rozwiń to jeszcze w następnym kroku i dodaj testy do tego."))


class TestExtraction(unittest.TestCase):
    def test_pairing_provenance_and_outcome(self):
        ep = _ep(
            ("user", "fix the pagination bug"),
            ("tool", "Traceback: KeyError 'page'"),
            ("assistant", "I created a brand-new HTTP client for this."),
            ("user", "Nie tak, nie twórz nowego klienta HTTP — użyj "
                     "istniejącego wspólnego klienta z retry."),
            ("assistant", "Gotowe, działa teraz — reused the shared client."),
        )
        recs = user_corrections(ep)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["kind"], "user_correction")
        self.assertEqual(r["class"], "correction")
        self.assertEqual(r["session_id"], "s1")
        self.assertEqual(r["cwd"], "/repo/proj")
        self.assertEqual(r["msg_index"], 3)
        self.assertTrue(r["action"].startswith("user_correction:hermes:s1#3"))
        self.assertTrue(any("user said" in e for e in r["errors"]))
        self.assertTrue(any("I created a brand-new" in e for e in r["errors"]))
        self.assertTrue(r["outcome_supported"])

    def test_tool_rows_skipped_when_pairing(self):
        ep = _ep(
            ("assistant", "wrote a new scraper"),
            ("tool", "exit_code 1"),
            ("user", "Nie tak — zamiast tego użyj istniejącego parsera "
                     "z biblioteki standardowej."),
        )
        recs = user_corrections(ep)
        self.assertEqual(len(recs), 1)
        self.assertTrue(any("wrote a new scraper" in e for e in recs[0]["errors"]))

    def test_requirement_not_distillable(self):
        ep = _ep(("assistant", "done"),
                 ("user", "Dodaj jeszcze obsługę retry przy okazji."))
        recs = user_corrections(ep)
        self.assertEqual(len(recs), 1)
        self.assertEqual(distillable(recs), [])


class TestDedupeAndPriority(unittest.TestCase):
    def _rec(self, text, sid, cls="correction", outcome=False):
        return {"action": "user_correction", "score": 0.0,
                "errors": [f"user said: {text}"],
                "kind": "user_correction", "class": cls,
                "source": "hermes", "session_id": sid, "cwd": "/w",
                "msg_index": 0, "outcome_supported": outcome,
                "repeats": 1, "occurrences": 1}

    def test_same_episode_repeats_do_not_strengthen(self):
        a = self._rec("nie twórz nowego klienta http użyj istniejącego", "s1")
        b = self._rec("nie twórz nowego klienta http użyj istniejącego", "s1")
        merged = dedupe_corrections([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["occurrences"], 2)
        self.assertEqual(merged[0]["repeats"], 1)

    def test_cross_episode_repeat_counts(self):
        a = self._rec("użyj istniejącego klienta zamiast nowego", "s1")
        b = self._rec("użyj istniejącego klienta zamiast nowego", "s2")
        merged = dedupe_corrections([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["repeats"], 2)

    def test_outcome_bubbles_up_on_merge(self):
        a = self._rec("użyj istniejącego klienta zamiast nowego", "s1")
        b = self._rec("użyj istniejącego klienta zamiast nowego", "s2",
                      outcome=True)
        merged = dedupe_corrections([a, b])
        self.assertTrue(merged[0]["outcome_supported"])

    def test_priority_order(self):
        bare = self._rec("popraw to proszęporządnie w tym miejscu", "s1")
        repeated = self._rec("użyj istniejącego klienta zamiast nowego", "s1")
        repeated["repeats"] = 2
        confirmed = self._rec("nie twórz nowego klienta tylko reuse", "s1",
                              outcome=True)
        out = prioritize_corrections([bare, repeated, confirmed])
        self.assertEqual(out[0]["action"], confirmed["action"])
        self.assertEqual(out[1]["action"], repeated["action"])


class TestEndToEnd(unittest.TestCase):
    def test_correction_only_session_reaches_staging_and_event_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.db"
            con = sqlite3.connect(db)
            con.execute("create table sessions (id text primary key,"
                        " title text, display_name text, cwd text,"
                        " started_at real, archived int default 0,"
                        " hidden int default 0)")
            con.execute("create table messages (id integer primary key,"
                        " session_id text, role text, content text,"
                        " tool_name text, timestamp real,"
                        " active int default 1)")
            con.execute("insert into sessions values ('s1','t','',"
                        "'/repo/proj',1737136400,0,0)")
            rows = [
                ("user", "fix the pagination bug"),
                ("assistant", "I created a brand-new HTTP client for this."),
                ("user", "Nie tak, nie twórz nowego klienta HTTP — użyj "
                         "istniejącego wspólnego klienta z retry."),
                ("assistant", "Gotowe, działa teraz."),
            ]
            for i, (role, text) in enumerate(rows, 1):
                con.execute("insert into messages values (?,?,?,?,NULL,?,1)",
                            (i, "s1", role, text, 1737136400 + i))
            con.commit()
            con.close()

            root = Path(tmp) / "mem"
            memory = DreamMemory(root)
            from open_dream_rsi.sessions import read_hermes_sessions
            self.assertEqual(len(read_hermes_sessions(db)), 1)
            # Full real path: the reader inside ingest_sessions reads the
            # same db; corrections flow through the shared pipeline.
            res = ingest_sessions(memory, str(db), client=_OkLLM())
            self.assertEqual(res["added"], 1)

            lessons = memory.get_lessons("proj")
            self.assertEqual(len(lessons), 1)
            self.assertEqual(lessons[0].get("status"), "staging")

            events = (root / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("user_correction_found", events)
            self.assertIn("lessons_curated", events)

            # The probe task is the PRE-correction user request; the
            # correction text must never leak into the replay prompt.
            tasks = json.loads((root / "tasks.json").read_text("utf-8"))
            probes = [t for t in tasks if str(t.get("task_id", "")).startswith("probe:")]
            self.assertEqual(len(probes), 1)
            self.assertIn("fix the pagination bug", probes[0]["prompt"])
            self.assertNotIn("klienta HTTP", probes[0]["prompt"])
            self.assertNotIn("reuse", probes[0]["prompt"].lower())

            # Gate stays the only path to ACTIVE: a rejected verdict never
            # activates, and the verdict is recorded in the event log.
            from open_dream_rsi.core.curator import lesson_gate_verdict
            verdict = lesson_gate_verdict({lessons[0]["trigger"]: [(False, False)]})
            self.assertEqual(verdict.promoted, [])
            memory.log_event("lesson_gate", category="proj", scope="selfcheck",
                             promoted=verdict.promoted, rejected=verdict.rejected)
            self.assertIn("lesson_gate", (root / "events.jsonl").read_text("utf-8"))


if __name__ == "__main__":
    unittest.main()

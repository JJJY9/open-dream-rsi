"""User-correction extraction (issue #6): natural-language evidence.

Host sessions contain corrections the user states in prose ("nie tak,
użyj istniejącego klienta", "don't create another client") — invisible to
:func:`open_dream_rsi.sessions.episode_failures`, which scans tool output
for error markers. This module turns such turns into evidence records
shaped like failure records (``action`` / ``score`` / ``errors``) so the
existing curator and replay-gate flow consumes them without a second
pipeline, while keeping the ``user_correction`` evidence kind and
provenance recoverable (README § Verdicts must be replayable).

Trust model is unchanged: a user correction is *evidence worth testing*,
not verified truth. Nothing here can make a lesson ACTIVE — candidates
enter staging like every other lesson and face the same paired-replay
gate. Extraction is deterministic and deliberately conservative: only
obvious, well-scoped candidates are kept; ambiguous negatives, ordinary
follow-ups and task expansions stay unclassified.
"""

import re
from typing import Any, Dict, List, Optional

__all__ = ["classify_user_message", "user_corrections", "dedupe_corrections",
           "prioritize_corrections", "distillable"]

#: Turns that reject a result or approach ("Correction" / "Approach
#: redirect" in issue #6). Kept tight on purpose — a broad "nie|not" net
#: would swallow ordinary follow-ups (the measured v3 lesson: trust is
#: earned per class, never by breadth).
_CORRECTION_HINTS = re.compile(
    r"\b(?:nie\s+tak|nie\s+o\s+to|nie\s+chodzi\s+o|chodzi\s+mi\s+o|"
    r"źle|błędnie|błędne|błędn|złe\s+założen|przecież|zamiast|"
    r"nadpis|nie\s+wolno|nie\s+rób|nie\s+używaj|nie\s+twórz|"
    r"weź\s+pod\s+uwagę|uwzględnij|użyj\s+istniejąc|skorzystaj\s+z\s+istniejąc|"
    r"jak\s+(?:napisałem|mówiłem|prosiłem)|już\s+(?:pisałem|mówiłem|prosiłem)|"
    r"znowu\s+(?:to\s+samo|piszesz|robisz)|"
    r"\bwrong\b|\bincorrectly?\b|that'?s\s+not|that\s+is\s+not|instead\s+of|"
    r"don't\s+(?:do|create|use|touch|add|overwrite)|do\s+not\s+(?:do|create|use|touch|add|overwrite)|"
    r"reuse\s+(?:the\s+)?(?:existing|shared)|as\s+i\s+(?:said|wrote|told|asked)|"
    r"we\s+already\s+(?:tried|did|fixed)|\bbreaks\b|\bbroke\b|stop\s+(?:doing|touching|creating)"
    r")", re.IGNORECASE)

#: Stated conventions ("Preference" in issue #6). Legitimate scoped-rule
#: evidence, but never framed as a failure lesson by the caller.
_PREFERENCE_HINTS = re.compile(
    r"\b(?:preferuję|wolę|zawsze\s+(?:używaj|pisz|rób|dziel)|"
    r"nigdy\s+(?:nie\s+)?(?:używaj|pisz|rób)|trzymaj\s+się\s+konwencji|"
    r"\bprefer\b|\bi\s+prefer\b|\bi\s+usually\b|always\s+(?:use|write|split)|"
    r"never\s+(?:use|do|commit)|convention\s+is\b)", re.IGNORECASE)

#: Task expansion / new requirement ("New requirement or clarification").
#: Extracted for completeness (the classes must be distinguishable) but
#: NOT distillation-ready by default: it is not evidence of a mistake.
_REQUIREMENT_HINTS = re.compile(
    r"\b(?:dodaj\s+jeszcze|dołóż|także\s+|poza\s+tym|oprócz\s+tego|"
    r"a\s+co\s+z\s+|możesz\s+też|przy\s+okazji|"
    r"what\s+about\b|also\s+add|in\s+addition|one\s+more\s+thing|"
    r"while\s+you'?re\s+at\s+it)", re.IGNORECASE)

#: Cheap ambiguity guards: short reactions, thanks, questions and bare
#: acknowledgements are never promoted (issue §1: reject or leave
#: unclassified rather than promote).
_AMBIGUITY = re.compile(
    r"^\s*(?:no|no,|nope|ok|okej|okay|super|spoko|git|dobrze|dziękuję|dzieki|thanks|"
    r"thank\s+you|thx|why|czemu|dlaczego|ale\b)[.!?,\s]|(\?)")

#: Assistant replies that suggest the session recovered after the
#: correction ("subsequent outcome supports the correction").
_OUTCOME_MARKERS = ("działa", "dziala", "zrobione", "gotowe", "naprawione",
                    "passes", "passed", "fixed", "works now", "solved")

_MIN_TEXT = 25
_MAX_RECORDS = 6
_MAX_TEXT = 220

_STOPWORDS = {
    "this", "that", "with", "have", "jest", "nie", "jak", "dla", "ale",
    "się", "sie", "tym", "tego", "który", "ktore", "ktora", "jestem",
    "made", "make", "want", "need", "please", "prosze", "proszę", "the",
    "and", "you", "your", "have", "that", "this", "with", "dont", "don't",
}


def classify_user_message(text: str) -> Optional[str]:
    """Classify one user turn: ``correction`` | ``approach_redirect`` |
    ``preference`` | ``new_requirement`` | ``None`` (not a candidate).

    ``correction`` wins over ``approach_redirect`` when both fire — a
    rejection with a proposed alternative is recorded as the correction
    it is; the redirect nuance lives in the text, not the label.
    """
    t = (text or "").strip()
    if len(t) < _MIN_TEXT or _AMBIGUITY.search(t[:24] or t):
        return None
    corr = _CORRECTION_HINTS.search(t)
    pref = _PREFERENCE_HINTS.search(t)
    # Earliest explicit signal wins: "Preferuję małe commity zamiast jednego
    # dużego" states a preference — the comparative "zamiast" is not a
    # rejection — while "Nie twórz X, zamiast tego użyj Y" leads with the
    # rejection. Ties resolve to correction (the class the gate and priority
    # ranking are calibrated for).
    if pref and (not corr or pref.start() < corr.start()):
        return "preference"
    if corr:
        return "correction"
    if _REQUIREMENT_HINTS.search(t):
        return "new_requirement"
    return None


def user_corrections(ep: Any, max_items: int = _MAX_RECORDS) -> List[Dict[str, Any]]:
    """Extract user-correction evidence records from one episode.

    Each record pairs the correction with the assistant turn it targets
    (nearest preceding assistant message, tool rows skipped) and carries
    provenance (source host, session id, workspace, message index) plus
    ``outcome_supported`` — whether the next assistant reply suggests the
    session recovered after the correction. Message text arrives already
    secret-redacted from the readers; nothing is added back.
    """
    records: List[Dict[str, Any]] = []
    msgs = list(getattr(ep, "messages", []))
    for i, m in enumerate(msgs):
        if getattr(m, "role", "") != "user":
            continue
        cls = classify_user_message(m.text or "")
        if cls is None:
            continue
        assistant_text = ""
        for j in range(i - 1, -1, -1):
            if msgs[j].role == "assistant":
                assistant_text = msgs[j].text or ""
                break
        outcome = False
        for j in range(i + 1, len(msgs)):
            if msgs[j].role == "assistant":
                low = (msgs[j].text or "").lower()
                outcome = any(k in low for k in _OUTCOME_MARKERS)
                break
        records.append({
            "action": f"user_correction:{getattr(ep, 'source', '')}:"
                      f"{str(getattr(ep, 'session_id', ''))[:12]}#{i}",
            "score": 0.0,
            "errors": [
                f"user said: {(m.text or '')[:_MAX_TEXT]}",
                f"assistant had: {assistant_text[:_MAX_TEXT]}",
                f"outcome: {'confirmed' if outcome else 'unverified'}",
            ],
            "kind": "user_correction",
            "class": cls,
            "source": getattr(ep, "source", ""),
            "session_id": getattr(ep, "session_id", ""),
            "cwd": getattr(ep, "cwd", ""),
            "msg_index": i,
            "outcome_supported": outcome,
            "repeats": 1,
            "occurrences": 1,
        })
    return records[-max_items:]


def _content_words(text: str) -> frozenset:
    words = re.findall(r"[a-ząćęłńóśźż]{4,}", (text or "").lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def dedupe_corrections(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse near-identical corrections before any paid curator call.

    Two records merge when their content words overlap (Jaccard >= 0.6).
    Repeats inside ONE episode do not strengthen the evidence: ``repeats``
    counts distinct episodes behind the observation, ``occurrences`` the
    raw message count (issue §3).
    """
    kept: List[Dict[str, Any]] = []
    sigs: List[frozenset] = []
    for rec in records:
        sig = _content_words(" ".join(rec.get("errors", [])))
        merged = False
        for k, (old, old_sig) in enumerate(zip(kept, sigs)):
            if old_sig and sig and (len(sig & old_sig) / len(sig | old_sig)) >= 0.6:
                old["occurrences"] += 1
                if old.get("session_id") != rec.get("session_id"):
                    old["repeats"] += 1
                if rec.get("outcome_supported") and not old.get("outcome_supported"):
                    old["outcome_supported"] = True
                    old["errors"] = list(old["errors"])[:2] + ["outcome: confirmed"]
                merged = True
                break
        if not merged:
            kept.append(rec)
            sigs.append(sig)
    return kept


def prioritize_corrections(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Highest-priority first (issue §3): confirmed outcome > repeated
    across episodes > bare correction > preference. Stable sort."""
    def rank(r: Dict[str, Any]) -> tuple:
        return (
            3 if r.get("outcome_supported") else 0,
            2 if r.get("repeats", 1) >= 2 else 0,
            1 if r.get("class") == "correction" else 0,
        )
    return sorted(records, key=rank, reverse=True)


def distillable(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Records eligible for the existing curator flow: corrections,
    redirects and preferences — never new requirements or unclassified
    turns (issue §1/§3: a task expansion is not evidence of a mistake)."""
    return [r for r in records
            if r.get("class") in ("correction", "approach_redirect", "preference")]

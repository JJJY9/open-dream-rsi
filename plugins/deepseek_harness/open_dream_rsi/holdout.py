"""Single-use holdout reservations for preregistered evaluations.

A preregistered evaluation task must be consumed ONCE: an ID that served as
holdout for one phase (a selection era, a paired gate, a final pass) must
never silently re-enter another validation pass — reuse contaminates the
second phase with a task the pipeline already fit against (the
selection-contamination rule the TravelPlanner protocol documents).

Inspired by the independent dream-rsi-sdk's single-use holdout
reservations; reimplemented for ODR's file-backed world.

This is a standalone primitive on purpose: the LOOP never reads it. The
harness that owns a preregistered protocol claims its eval task IDs here
BEFORE phase A starts and filters them out of any later task list with
:func:`split_reserved`. First claim wins; a different purpose cannot
re-claim the same ID (same-purpose re-claims are idempotent, so resuming a
crashed phase does not lose the reservation). ``release`` exists for
explicit corrections only — it is the operator undoing a mistake, never
part of the protocol.

Storage: ``<root>/holdout_reservations.json`` (atomic writes, corrupt file
resets to empty — the store records intent, it is not evidence itself).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RESERVATIONS_FILE = "holdout_reservations.json"


class HoldoutRegistry:
    """File-backed single-use reservation store (task_id -> provenance)."""

    def __init__(self, root: "str | Path"):
        self.root = Path(root)
        self._path = self.root / RESERVATIONS_FILE

    # -- low level ------------------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: Dict[str, Dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self._path)

    # -- API -------------------------------------------------------------------

    def claim(self, task_id: str, purpose: str,
              phase: Optional[str] = None) -> bool:
        """Reserve ``task_id`` for ``purpose``. False when held by another.

        First claim wins: a task consumed as holdout by one phase can never
        be re-claimed for a different purpose. Re-claiming with the SAME
        purpose succeeds (idempotent resume).
        """
        task_id = str(task_id).strip()
        purpose = str(purpose).strip()
        if not task_id or not purpose:
            raise ValueError("task_id and purpose are required")
        data = self._load()
        existing = data.get(task_id)
        if existing is not None:
            return str(existing.get("purpose", "")) == purpose
        entry: Dict[str, Any] = {"purpose": purpose, "reserved_at": time.time()}
        if phase:
            entry["phase"] = str(phase)
        data[task_id] = entry
        self._save(data)
        return True

    def holder(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._load().get(str(task_id).strip()) or None

    def release(self, task_id: str) -> bool:
        """Explicit correction path: forget a reservation. True if one existed."""
        data = self._load()
        if str(task_id).strip() in data:
            del data[str(task_id).strip()]
            self._save(data)
            return True
        return False

    def entries(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._load())


def _task_id_of(task: Any) -> Optional[str]:
    if isinstance(task, dict):
        tid = task.get("task_id")
        return str(tid) if tid else None
    tid = getattr(task, "task_id", None)
    return str(tid) if tid else None


def split_reserved(tasks: List[Any],
                   registry: HoldoutRegistry) -> Tuple[List[Any], List[Any]]:
    """Partition ``tasks`` into (allowed, held_back) by the registry.

    The harness-side filter for a preregistered protocol: run this BEFORE
    handing a task list to the runtime so a consumed eval ID cannot re-enter
    a later phase. Held-back tasks are returned, never dropped silently.
    """
    reserved = set(registry.entries())
    allowed: List[Any] = []
    held: List[Any] = []
    for t in tasks:
        tid = _task_id_of(t)
        (held if tid is not None and tid in reserved else allowed).append(t)
    return allowed, held

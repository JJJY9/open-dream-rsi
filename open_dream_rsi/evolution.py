"""Anytime-valid stopping for policy evolution.

Inspired by "When Is Enough Enough in Self-Evolving LLM Systems?"
(arXiv:2610.04756): self-evolving loops that run to a fixed budget waste
compute after improvement saturates and risk overfitting the evaluation
signal with late updates. The paper's answer is a betting-martingale
stopping rule over paired evaluation outcomes plus a change-point choice
of the artifact to output.

Mapped onto this loop (policy evolution only, opt-in):

* the paired outcome per round is binary — did the category's policy
  regeneration PROMOTE this cycle (evidence of life) or not;
* ``p0`` (the null "still improvable" rate) is calibrated from the first
  ``calibration`` rounds and floored at 0.5, so a dead category still
  alarms — just later (~8 betting rounds at lambda=0.5);
* each non-promoting round multiplies the wealth by
  ``1 - lam + lam * (1 - x) / (1 - p0)`` (> 1 on a miss, < 1 on a
  promotion — promotions crash the wealth, evidence of life resets
  progress); each factor is positive, so the test is anytime-valid at
  level ``alpha`` with threshold ``1/alpha``;
* "what to output" is trivial here: the loop never discards the incumbent
  on freezing — the last PROMOTED policy stays active and only
  regeneration spending stops.

Stdlib only. The stopper is in-memory runtime state; freezing is an
economic decision, not a correctness surface.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


class EvolutionStopper:
    """Per-category wealth process over promotion outcomes."""

    def __init__(self, alpha: float = 0.05, lam: float = 0.5,
                 calibration: int = 3, min_rounds: int = 4,
                 threshold: Optional[float] = None) -> None:
        self.alpha = float(alpha)
        self.lam = float(min(max(float(lam), 0.05), 0.95))
        self.calibration = max(int(calibration), 1)
        self.min_rounds = max(int(min_rounds), 1)
        self.threshold = float(threshold if threshold is not None
                               else 1.0 / self.alpha)
        self._state: Dict[str, Dict[str, Any]] = {}

    def observe(self, category: str, promoted: bool) -> Dict[str, Any]:
        """Record one round (cycle) for ``category``; return the decision."""
        st = self._state.setdefault(category, {
            "rounds": 0, "history": [], "wealth": 1.0,
            "p0": None, "frozen": False, "alarm_round": None,
        })
        if st["frozen"]:
            return {"frozen": True, "wealth": st["wealth"], "p0": st["p0"],
                    "rounds": st["rounds"], "alarm_round": st["alarm_round"]}
        st["rounds"] += 1
        x = 1 if promoted else 0
        st["history"].append(x)
        if st["p0"] is None:
            # calibration window: no betting yet
            if len(st["history"]) >= self.calibration:
                rate = sum(st["history"]) / len(st["history"])
                # conservative floor: a never-promoting category still
                # detects as dead, just slower (f(0) = 1.5 per miss);
                # cap at 0.99 — a perfect calibration window means the
                # first miss is massive evidence (f(0) = 50.5), not inf
                st["p0"] = min(max(rate, 0.5), 0.99)
        else:
            factor = 1.0 - self.lam + self.lam * ((1.0 - x) / (1.0 - st["p0"]))
            st["wealth"] *= factor
        if (st["rounds"] >= self.min_rounds
                and st["wealth"] >= self.threshold):
            st["frozen"] = True
            st["alarm_round"] = st["rounds"]
        return {"frozen": st["frozen"], "wealth": st["wealth"],
                "p0": st["p0"], "rounds": st["rounds"],
                "alarm_round": st["alarm_round"]}

    def is_frozen(self, category: str) -> bool:
        st = self._state.get(category)
        return bool(st and st["frozen"])

    def reset(self, category: Optional[str] = None) -> None:
        if category is None:
            self._state.clear()
        else:
            self._state.pop(category, None)

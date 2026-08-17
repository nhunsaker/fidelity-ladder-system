"""Expedition — the state of one idea climbing the ladder (mirrors a GitHub issue).

The controller mutates this; the surface (issue labels) and admin UI are lenses over it.
Slim demo instance: rungs 0-2 are the paper ladder (this phase); 3-5 land in P2/P3.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fls.adjudicator import Idea
from fls.anchor import Dial
from fls.llm import Call

# status values
CLIMBING, PARKED, DOCKED, NEEDS_HUMAN, AWAIT_PICK = (
    "climbing", "parked", "docked", "needs-human", "await-pick",
)
# v0.8 Phase 3 — a first-class status for an expedition just rebuilt by `climb.resume_from_ledger`
# whose trace tail was mid-flight ("climbing", with no terminal checkpoint reached before the
# harness that held it disappeared). Distinct from CLIMBING so a caller/human can tell "actively
# being worked" from "reconstructed from a trace, about to resume" — never silently relabeled
# back to CLIMBING until an actual climb call runs again.
RESUMING = "resuming"


@dataclass
class Expedition:
    number: int
    idea: Idea
    target_rung: int
    rung: int = 0
    dial: Dial = Dial.human_picks
    status: str = CLIMBING
    spec: str | None = None            # winning revised spec (rung 1)
    acceptance_stub: str | None = None  # rung-1 machine-checkable criteria (Yao); rung 4 builds against it
    wireframes: list[str] = field(default_factory=list)   # rung 2
    picked_wireframe: int | None = None
    reason: str | None = None          # dock/park/needs-human reason
    calls: list[Call] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    def add(self, calls: list[Call]) -> None:
        self.calls.extend(calls)

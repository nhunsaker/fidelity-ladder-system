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
# Harness PoC (2026-09-10): a rung whose dial is human-picks but whose artifact is not a pick-of-N
# (rung 3 prototype, rung 4 build) parks here after its verifier passes; `/approve` resumes, any
# feedback text re-runs the rung. Distinct from AWAIT_PICK (choose one of N) and AWAIT_SIGNOFF (rung 5).
AWAIT_APPROVE = "await-approve"


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
    # WHO ended it, when it is parked: "human" if a person pressed Stop, "failure" if a rung broke.
    # Both are PARKED and until now the only difference was prose in `reason`. It matters on the
    # surface: a run a person stopped must not offer to start itself again, and a run that broke
    # must. Sniffing the reason string for "killed by" would work until someone rewords it.
    parked_by: str = ""
    calls: list[Call] = field(default_factory=list)

    @property
    def spent_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    @property
    def normalized_usd(self) -> float:
        """What the work would have cost at list price.

        On the subscription lane `spent_usd` is genuinely zero, so a surface that shows only
        metered dollars reports $0.00 for every run however large — worse than showing nothing,
        because it reads as a measurement rather than an absence."""
        return round(sum(getattr(c, "normalized_usd", 0.0) or 0.0 for c in self.calls), 4)

    def add(self, calls: list[Call]) -> None:
        self.calls.extend(calls)

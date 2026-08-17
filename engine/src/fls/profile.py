"""fidelity_ladder.profile — the ladder expressed as DATA (rungs-as-config).

A rung is a row, not a hand-written stage:

    {number · name · artifact_kind · dial · verifier · context_budget_chars ·
     builder_max_tokens · max_retries · termination}

The 6-rung **web-UI ladder** ships here as the *reference profile*, not the engine. Swapping the
profile changes what ladder runs without touching `climb.py`/`controller.py` — the "rungs-as-config"
claim (Chase). Magic caps that used to be hardcoded in `rung4`/`climb` (builder 1500 tokens · 3
retries · acceptance-context 2000 chars) are lifted here so an ANCHOR can declare per-rung budgets
instead of the engine baking them in.

The `dial` on each rung is the DEFAULT autonomy setting; an ANCHOR (and a VESSEL) may only ever
*tighten* it past this via the tighten-only cascade — never loosen (DIAL_ORDER, `fls.anchor`).
"""
from __future__ import annotations

from dataclasses import dataclass

from fls.anchor import Dial


@dataclass(frozen=True)
class RungSpec:
    """One rung, as data. `climb`/`rung4` read caps from here rather than hardcoding them."""
    number: int
    name: str
    artifact_kind: str          # what climbing THIS rung produces
    dial: Dial                  # default autonomy dial (ANCHOR/VESSEL may only tighten past it)
    verifier: str               # the verifier kind that gates advancement off this rung
    context_budget_chars: int   # cap on the builder's bounded context at this rung (0 = n/a)
    builder_max_tokens: int     # cap on the builder's output tokens (0 = n/a)
    max_retries: int            # width/termination: retry budget before a descend-with-lesson
    termination: str            # human-readable: what ends this rung
    line_budget: int = 0        # enforced rung-5 reviewability cap (Wu): diff lines a human can
                                 # review in <=10 minutes. 0 = n/a (not a review-gated rung).


@dataclass(frozen=True)
class LadderProfile:
    """An ordered ladder of rungs. THE unit you swap to run a different ladder."""
    name: str
    rungs: tuple[RungSpec, ...]

    def rung(self, number: int) -> RungSpec:
        for r in self.rungs:
            if r.number == number:
                return r
        raise KeyError(f"no rung {number} in profile {self.name!r}")

    @property
    def height(self) -> int:
        return len(self.rungs)


# The reference profile — the web-UI ladder, 6 rungs (0..5). Numbers mirror fls.funnel's
# RUNG_INTENT/SPEC/WIRE/DEMO/MVP/FLAG = 0..5. Caps here reproduce the engine's prior hardcoded
# behavior exactly (builder_max_tokens=1500, max_retries=3, acceptance-context 2000 at rung 4).
WEB_LADDER_PROFILE = LadderProfile(
    name="web-ui",
    rungs=(
        RungSpec(0, "intent",    "idea",             Dial.human_picks,  "admission",      0,    0,    0, "admission gate — one door in"),
        RungSpec(1, "spec",      "spec",             Dial.auto_advance, "judge-rank",     3000, 1024, 1, "judge-ranked + one reflection pass"),
        RungSpec(2, "wireframe", "wireframe",        Dial.human_picks,  "human-pick",     1500, 1024, 0, "human picks the winning line"),
        RungSpec(3, "demo",      "interactive-demo", Dial.auto_advance, "walkthrough",    3000, 1500, 0, "walkthrough audit → advance | descend"),
        RungSpec(4, "mvp",       "mvp-code",         Dial.auto_advance, "acceptance-test",2000, 1500, 3, "retry to max → descend-with-lesson"),
        RungSpec(5, "flag",      "flagged-pr",       Dial.propose_only, "human-signoff",  4000, 1500, 0, "hard gate — propose only, never auto-ships", line_budget=400),
    ),
)

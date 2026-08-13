"""Funnel engine — assigns admitted ideas to fidelity lanes per the ANCHOR policy.

The funnel's shape IS the cost model (Wang): width per rung × cost per rung ≈ the envelope.
Demo defaults (ANCHOR): auto_build=1 · interactive_demos=3 · wireframes=all. The lanes are
NESTED and describe each idea's TARGET rung (how far it climbs before parking):

  rank 1                         -> target rung 5 (full auto-build climb)
  ranks 2 .. 1+interactive_demos -> target rung 3 (interactive demo, then park)
  everyone admitted (wireframes: all) -> target rung 2 (wireframe, then park)
  overflow beyond `queue`        -> queued (target rung 0, not spending)

Prune-early (Wang#2): ranking is done on cheap signal BEFORE any expensive render, so only the
ideas that advance pay for wireframes/demos/builds.
"""
from __future__ import annotations

from dataclasses import dataclass

from fls.anchor import Anchor

# rung ordinal for "how far this idea climbs"
RUNG_INTENT, RUNG_SPEC, RUNG_WIRE, RUNG_DEMO, RUNG_MVP, RUNG_FLAG = 0, 1, 2, 3, 4, 5


@dataclass
class RankedIdea:
    number: int
    rank: int          # 1 = best (by the ranking judge, cheap signal)
    target_rung: int = RUNG_INTENT


def assign_lanes(admitted: list[RankedIdea], anchor: Anchor) -> list[RankedIdea]:
    """Set each admitted idea's target_rung from its rank + the ANCHOR funnel policy."""
    f = anchor.funnel
    n = len(admitted)
    wire_all = f.wireframes == "all"
    wire_n = n if wire_all else int(f.wireframes)
    demo_n = f.interactive_demos
    build_n = f.auto_build
    # `queue` caps how many admitted-but-not-advancing ideas stay visible (0 = none parked below wire)
    visible = wire_n + (f.queue if not wire_all else 0)

    for idea in sorted(admitted, key=lambda x: x.rank):
        r = idea.rank
        if r <= build_n:
            idea.target_rung = RUNG_FLAG
        elif r <= build_n + demo_n:
            idea.target_rung = RUNG_DEMO
        elif r <= visible:
            idea.target_rung = RUNG_WIRE
        else:
            idea.target_rung = RUNG_INTENT  # queued, not spending
    return admitted


def est_batch_cost(admitted: list[RankedIdea], anchor: Anchor) -> float:
    """Sum the per-rung ANCHOR estimates each idea will incur climbing to its target rung.
    This is the utility-per-dollar denominator the verify lines report (Wang#1)."""
    order = ["1-spec", "2-wireframe", "3-demo", "4-mvp", "5-flagged"]
    ordinal = {"1-spec": RUNG_SPEC, "2-wireframe": RUNG_WIRE, "3-demo": RUNG_DEMO,
               "4-mvp": RUNG_MVP, "5-flagged": RUNG_FLAG}
    total = 0.0
    for idea in admitted:
        for key in order:
            if ordinal[key] <= idea.target_rung:
                total += anchor.rungs[key].est_usd
    return round(total, 4)

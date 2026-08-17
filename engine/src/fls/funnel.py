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

import json
import re
from dataclasses import dataclass, field

from fls.anchor import Anchor
from fls.llm import Call

# rung ordinal for "how far this idea climbs"
RUNG_INTENT, RUNG_SPEC, RUNG_WIRE, RUNG_DEMO, RUNG_MVP, RUNG_FLAG = 0, 1, 2, 3, 4, 5


@dataclass
class RankedIdea:
    number: int
    rank: int          # 1 = best (by the ranking judge, cheap signal)
    target_rung: int = RUNG_INTENT


@dataclass
class QueueTier:
    """A first-class staging tier below the active wire (RUNG_WIRE and above spend; this tier
    never does). Ideas parked here are admitted-but-not-advancing: tracked, ordered, and
    promotable, but NOT spending until explicitly promoted.

    Nesting (per the funnel's shape): flag ⊆ demo ⊆ wire ⊆ queue ⊆ admitted. `cap` bounds how
    many admitted-but-below-wire ideas the tier tracks at all; anything beyond `cap` is pure
    overflow — never enqueued, never visible, never promotable (recorded in `.dropped` for
    observability only).

    Ordering is best-rank-first (ascending `rank`); `promote_next`/`promote_many` always pull the
    best-ranked queued idea(s), so promotion is a deterministic, auditable FIFO-by-merit.
    """
    cap: int = 0
    items: list[RankedIdea] = field(default_factory=list)
    dropped: list[RankedIdea] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)

    @property
    def is_full(self) -> bool:
        return self.cap > 0 and len(self.items) >= self.cap

    def enqueue(self, idea: RankedIdea) -> bool:
        """Park `idea` in the queue tier without spending (forces target_rung to RUNG_INTENT).
        Returns True if it was enqueued, False if it overflowed `cap` (recorded in `.dropped`,
        not tracked further — pure overflow, per the funnel's fail-closed shape)."""
        idea.target_rung = RUNG_INTENT
        if self.cap <= 0 or self.is_full:
            self.dropped.append(idea)
            return False
        self.items.append(idea)
        self.items.sort(key=lambda x: x.rank)
        return True

    def peek(self, n: int = 1) -> list[RankedIdea]:
        """Look at the next `n` best-ranked queued ideas without removing them."""
        return self.items[:n]

    def promote_next(self, target_rung: int = RUNG_WIRE) -> RankedIdea | None:
        """Pop the best-ranked queued idea and promote it to `target_rung` (default: wireframe —
        the tier immediately above queue). Returns None if the queue is empty."""
        if not self.items:
            return None
        idea = self.items.pop(0)
        idea.target_rung = target_rung
        return idea

    def promote_many(self, count: int, target_rung: int = RUNG_WIRE) -> list[RankedIdea]:
        """Promote up to `count` best-ranked queued ideas in merit order; stops early if the
        queue empties first."""
        promoted: list[RankedIdea] = []
        for _ in range(count):
            idea = self.promote_next(target_rung)
            if idea is None:
                break
            promoted.append(idea)
        return promoted


def assign_lanes(admitted: list[RankedIdea], anchor: Anchor) -> list[RankedIdea]:
    """Set each admitted idea's target_rung from its rank + the ANCHOR funnel policy.

    Deprecated (v0.7): `controller.run_batch` now calls `assign_lanes_and_stage` instead, which
    stages the below-wire remainder through a first-class, promotable `QueueTier` rather than
    this function's bare `visible` arithmetic. Kept for back-compat (external/direct callers,
    `prune_early`'s hypothetical-cost calc); removal deferred to v0.8."""
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


def assign_lanes_and_stage(admitted: list[RankedIdea], anchor: Anchor) -> tuple[list[RankedIdea], QueueTier]:
    """Governed sibling of `assign_lanes`: same flag/demo/wire nesting, but the below-wire
    remainder is staged through a first-class `QueueTier` (enqueue/promote/cap) instead of a bare
    `visible` arithmetic extension. `assign_lanes` is untouched and remains the back-compat entry
    point (existing `Funnel.queue` behaviour — `queue` widening the wire-visible count — is
    preserved there unchanged); this function is the new governed path for callers that want an
    explicit, promotable staging tier.

    Nesting: flag (rank <= auto_build) -> demo (next interactive_demos) -> wire (next wire_n,
    cumulative from rank 1) -> queue tier (next `queue` ranks, capped, tracked, not spending) ->
    pure overflow (untracked, recorded in `QueueTier.dropped`).
    """
    f = anchor.funnel
    n = len(admitted)
    wire_all = f.wireframes == "all"
    wire_n = n if wire_all else int(f.wireframes)
    demo_n = f.interactive_demos
    build_n = f.auto_build
    tier = QueueTier(cap=f.queue)

    for idea in sorted(admitted, key=lambda x: x.rank):
        r = idea.rank
        if r <= build_n:
            idea.target_rung = RUNG_FLAG
        elif r <= build_n + demo_n:
            idea.target_rung = RUNG_DEMO
        elif r <= wire_n:
            idea.target_rung = RUNG_WIRE
        else:
            tier.enqueue(idea)  # queued (rung 0, not spending) up to cap; else pure overflow
    return admitted, tier


# ── prune-early (Wang#2) — kill weak branches BEFORE expensive renders ────────────────────────
_PRUNE_SYS = (
    "You prune weak idea branches for a fidelity ladder. Given the ANCHOR scope and numbered "
    "PARTIAL previews (cheap first-tokens, not full artifacts), score each 0-9 for how likely a "
    "full climb is worth its cost (anchor fit + coherence). Reply with a JSON array of integer "
    "scores in input order, e.g. [7,2,9]. Array only."
)
_ARR = re.compile(r"\[[^\]]*\]")


@dataclass
class PrunedBranch:
    number: int
    score: int
    saved_est_usd: float            # the climb cost this prune avoided (per-rung ANCHOR estimates)
    reason: str = "pruned-early: weak partial vs anchor"


@dataclass
class PruneReport:
    kept: list[RankedIdea]
    pruned: list[PrunedBranch]
    calls: list[Call] = field(default_factory=list)

    @property
    def saved_est_usd(self) -> float:
        return round(sum(p.saved_est_usd for p in self.pruned), 4)


def _hypothetical_climb_cost(idea: RankedIdea, cohort: list[RankedIdea], anchor: Anchor) -> float:
    """What this idea's climb WOULD cost had it not been pruned: assign lanes over the full
    cohort (copies), then sum the per-rung estimates up to its hypothetical target."""
    copies = [RankedIdea(i.number, i.rank) for i in cohort]
    assign_lanes(copies, anchor)
    target = next(c.target_rung for c in copies if c.number == idea.number)
    ordinal = {"1-spec": RUNG_SPEC, "2-wireframe": RUNG_WIRE, "3-demo": RUNG_DEMO,
               "4-mvp": RUNG_MVP, "5-flagged": RUNG_FLAG}
    return round(sum(p.est_usd for k, p in anchor.rungs.items()
                     if k in ordinal and ordinal[k] <= target), 4)


def prune_early(admitted: list[RankedIdea], partials: dict[int, str], anchor: Anchor,
                judge, ledger=None, cutoff: int = 4, max_chars: int = 200) -> PruneReport:
    """Judge scores CHEAP partial generations (first `max_chars` chars each) in ONE call and
    kills branches scoring below `cutoff` — before any wireframe/demo/build spend (Wang#2).

    Fail-open by design: if the judge call fails or parses badly, nothing is pruned and the
    funnel behaves exactly as v1 (pruning is an optimization; a judge glitch must never destroy
    admitted work). Pruned branches are recorded to the ledger as judge decisions (verdict
    "prune", human slot open) so a human override lands in the calibration flywheel.
    """
    if not admitted:
        return PruneReport([], [])
    numbered = "\n\n".join(f"[{i}] idea #{x.number}:\n{partials.get(x.number, '')[:max_chars]}"
                           for i, x in enumerate(admitted))
    scores: list[int] | None = None
    calls: list[Call] = []
    try:
        text, call = judge.complete(
            f"ANCHOR altitudes {anchor.altitude_allowed}; funnel {anchor.funnel.auto_build}/"
            f"{anchor.funnel.interactive_demos}/{anchor.funnel.wireframes}.\n\n"
            f"PARTIALS:\n{numbered}\n\nScore them.",
            max_tokens=64, system=_PRUNE_SYS,
        )
        calls.append(call)
        m = _ARR.search(text or "")
        parsed = [int(x) for x in json.loads(m.group(0))] if m else None
        if parsed is not None and len(parsed) == len(admitted):
            scores = parsed
    except Exception:  # noqa: BLE001 — fail-open is the contract; any judge failure = no pruning
        scores = None
    if scores is None:
        return PruneReport(list(admitted), [], calls)

    kept: list[RankedIdea] = []
    pruned: list[PrunedBranch] = []
    per_call_usd = (calls[0].usd / len(admitted)) if calls else 0.0
    for idea, score in zip(admitted, scores, strict=True):
        if score < cutoff:
            saved = _hypothetical_climb_cost(idea, admitted, anchor)
            pruned.append(PrunedBranch(idea.number, score, saved))
            if ledger is not None:
                from fls.ledger import Decision
                ledger.record(Decision(idea.number, "1-spec", "prune", None, per_call_usd))
        else:
            kept.append(idea)
    return PruneReport(kept, pruned, calls)


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

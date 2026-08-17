"""v0.6 #4 — first-class queue tier: governed staging below the active wire.

Covers: overflow enqueues (not spends), promotion pulls best-rank-first, cap enforcement
(pure overflow beyond cap), and that `assign_lanes` (the pre-existing back-compat entry point)
keeps its exact prior behaviour untouched.
"""
from pathlib import Path

from fls.anchor import Anchor
from fls.funnel import (
    RUNG_DEMO,
    RUNG_FLAG,
    RUNG_INTENT,
    RUNG_WIRE,
    QueueTier,
    RankedIdea,
    assign_lanes,
    assign_lanes_and_stage,
)

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


def _limited_wire_anchor(wireframes: int, queue: int):
    """Clone ANCHOR with a limited (non-'all') wireframes count + a queue cap, so the
    below-wire remainder is exercised (the demo ANCHOR ships wireframes: all / queue: 0)."""
    anchor = ANCHOR.model_copy(deep=True)
    anchor.funnel.wireframes = wireframes
    anchor.funnel.queue = queue
    return anchor


# ── QueueTier unit behaviour ───────────────────────────────────────────────────────────────────

def test_enqueue_forces_rung_intent_and_not_spending():
    tier = QueueTier(cap=5)
    idea = RankedIdea(number=1, rank=1, target_rung=RUNG_WIRE)
    assert tier.enqueue(idea) is True
    assert idea.target_rung == RUNG_INTENT
    assert len(tier) == 1


def test_enqueue_orders_best_rank_first_regardless_of_insertion_order():
    tier = QueueTier(cap=5)
    for n, r in [(3, 30), (1, 10), (2, 20)]:
        tier.enqueue(RankedIdea(number=n, rank=r))
    assert [i.number for i in tier.peek(3)] == [1, 2, 3]


def test_cap_enforced_overflow_beyond_cap_is_dropped_not_tracked():
    tier = QueueTier(cap=2)
    ok = [tier.enqueue(RankedIdea(number=i, rank=i)) for i in range(1, 5)]
    assert ok == [True, True, False, False]
    assert len(tier) == 2
    assert [i.number for i in tier.dropped] == [3, 4]
    assert tier.is_full


def test_zero_cap_means_nothing_is_tracked_pure_overflow():
    tier = QueueTier(cap=0)
    assert tier.enqueue(RankedIdea(number=1, rank=1)) is False
    assert len(tier) == 0
    assert len(tier.dropped) == 1


def test_promote_next_pulls_best_ranked_first_and_sets_target_rung():
    tier = QueueTier(cap=5)
    tier.enqueue(RankedIdea(number=2, rank=2))
    tier.enqueue(RankedIdea(number=1, rank=1))
    promoted = tier.promote_next()
    assert promoted.number == 1
    assert promoted.target_rung == RUNG_WIRE  # default promotion target
    assert len(tier) == 1


def test_promote_next_custom_target_rung():
    tier = QueueTier(cap=1)
    tier.enqueue(RankedIdea(number=1, rank=1))
    promoted = tier.promote_next(target_rung=RUNG_DEMO)
    assert promoted.target_rung == RUNG_DEMO


def test_promote_next_empty_queue_returns_none():
    tier = QueueTier(cap=1)
    assert tier.promote_next() is None


def test_promote_many_stops_early_when_queue_empties():
    tier = QueueTier(cap=5)
    tier.enqueue(RankedIdea(number=1, rank=1))
    tier.enqueue(RankedIdea(number=2, rank=2))
    promoted = tier.promote_many(5)
    assert [i.number for i in promoted] == [1, 2]
    assert len(tier) == 0
    assert tier.promote_many(1) == []


# ── assign_lanes_and_stage — governed integration ──────────────────────────────────────────────

def test_overflow_beyond_wire_enqueues_not_spends():
    # wireframes=5 (cumulative), queue cap=2, 8 admitted ideas, default funnel auto_build=1/demo=3
    anchor = _limited_wire_anchor(wireframes=5, queue=2)
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 9)]
    ranked, tier = assign_lanes_and_stage(ideas, anchor)
    by_rank = {i.rank: i for i in ranked}
    assert by_rank[1].target_rung == RUNG_FLAG
    assert by_rank[2].target_rung == RUNG_DEMO
    assert by_rank[4].target_rung == RUNG_DEMO
    assert by_rank[5].target_rung == RUNG_WIRE   # wire_n=5, cumulative from rank 1
    assert by_rank[6].target_rung == RUNG_INTENT  # beyond wire -> queue tier (not spending)
    assert by_rank[7].target_rung == RUNG_INTENT
    assert {i.number for i in tier.items} == {6, 7}
    assert {i.number for i in tier.dropped} == {8}  # rank 8 beyond cap(3): pure overflow


def test_wire_then_queue_then_overflow_nesting():
    # auto_build=1, interactive_demos=3 (from ANCHOR), wireframes=1 (cumulative, so no extra
    # wire slots beyond flag+demo), queue cap=2 -> ranks 5,6 queued; ranks 7,8 pure overflow.
    anchor = _limited_wire_anchor(wireframes=4, queue=2)
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 9)]
    ranked, tier = assign_lanes_and_stage(ideas, anchor)
    by_rank = {i.rank: i for i in ranked}
    assert by_rank[1].target_rung == RUNG_FLAG           # rank 1 -> flag
    assert by_rank[2].target_rung == RUNG_DEMO            # ranks 2-4 -> demo
    assert by_rank[4].target_rung == RUNG_DEMO
    # wireframes=4 is cumulative from rank 1, but ranks 1-4 already consumed by flag/demo, so
    # there is no separate wire-only rank left; ranks 5-6 fall to the queue tier (cap=2).
    assert by_rank[5].target_rung == RUNG_INTENT
    assert by_rank[6].target_rung == RUNG_INTENT
    assert {i.number for i in tier.items} == {5, 6}
    # ranks 7,8 are pure overflow beyond the queue cap: still present in the returned list
    # (rung forced to... they were never enqueued, so target_rung is whatever it started as,
    # i.e. untouched/default) but recorded as dropped by the tier.
    assert {i.number for i in tier.dropped} == {7, 8}
    assert len(tier) == 2


def test_wireframes_all_never_touches_queue_tier():
    # matches the shipped demo ANCHOR shape: wireframes: all means every admitted idea is
    # covered by flag/demo/wire, so the queue tier stays empty regardless of cap.
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 7)]
    ranked, tier = assign_lanes_and_stage(ideas, ANCHOR)
    assert len(tier) == 0
    assert len(tier.dropped) == 0
    by_rank = {i.rank: i.target_rung for i in ranked}
    assert by_rank[1] == RUNG_FLAG
    assert by_rank[5] == RUNG_WIRE
    assert by_rank[6] == RUNG_WIRE


def test_promotion_from_queue_tier_pulls_best_rank_and_frees_a_slot():
    anchor = _limited_wire_anchor(wireframes=4, queue=2)
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 9)]
    _, tier = assign_lanes_and_stage(ideas, anchor)
    assert len(tier) == 2
    promoted = tier.promote_next()
    assert promoted.number == 5           # best-ranked queued idea
    assert promoted.target_rung == RUNG_WIRE
    assert len(tier) == 1


# ── back-compat guard — assign_lanes (existing behaviour) is untouched ─────────────────────────

def test_assign_lanes_backcompat_unchanged_with_default_anchor():
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 7)]
    assign_lanes(ideas, ANCHOR)
    by_rank = {i.rank: i.target_rung for i in ideas}
    assert by_rank[1] == RUNG_FLAG
    assert by_rank[2] == RUNG_DEMO
    assert by_rank[4] == RUNG_DEMO
    assert by_rank[5] == RUNG_WIRE
    assert by_rank[6] == RUNG_WIRE


def test_assign_lanes_backcompat_queue_still_widens_visible_wire_count():
    # existing (pre-v0.6) semantics: `queue` widens the WIRE-eligible cumulative count when
    # wireframes is a limited int — assign_lanes must keep doing exactly this, unchanged.
    anchor = _limited_wire_anchor(wireframes=1, queue=2)
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 9)]
    assign_lanes(ideas, anchor)
    by_rank = {i.rank: i.target_rung for i in ideas}
    assert by_rank[1] == RUNG_FLAG
    assert by_rank[2] == RUNG_DEMO
    assert by_rank[4] == RUNG_DEMO
    # visible = wire_n(1) + queue(2) = 3 -> ranks <=3 already spoken for by flag/demo, so no
    # rank actually lands in WIRE here; but bump wireframes to make the widening visible:
    assert by_rank[5] == RUNG_INTENT


def test_assign_lanes_backcompat_queue_widening_visible_example():
    anchor = _limited_wire_anchor(wireframes=6, queue=2)
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 10)]
    assign_lanes(ideas, anchor)
    by_rank = {i.rank: i.target_rung for i in ideas}
    # visible = wire_n(6) + queue(2) = 8 -> ranks 5-8 get WIRE (not queued) under the OLD
    # assign_lanes semantics, ranks 9+ are INTENT.
    assert by_rank[5] == RUNG_WIRE
    assert by_rank[8] == RUNG_WIRE
    assert by_rank[9] == RUNG_INTENT

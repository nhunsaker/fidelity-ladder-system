"""P1: funnel lane assignment (pure, no spend) + rung 1 flow (stubbed builder/judge)."""
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.funnel import RUNG_DEMO, RUNG_FLAG, RUNG_WIRE, RankedIdea, assign_lanes, est_batch_cost
from fls.llm import Call
from fls.rung1 import run_rung1

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


def test_funnel_nesting_1_3_all():
    # 6 admitted ideas, policy 1 build / 3 demo / all wireframe
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 7)]
    assign_lanes(ideas, ANCHOR)
    by_rank = {i.rank: i.target_rung for i in ideas}
    assert by_rank[1] == RUNG_FLAG          # #1 -> full build
    assert by_rank[2] == RUNG_DEMO          # #2-4 -> demo
    assert by_rank[4] == RUNG_DEMO
    assert by_rank[5] == RUNG_WIRE          # rest -> wireframe (wireframes: all)
    assert by_rank[6] == RUNG_WIRE


def test_funnel_cost_is_the_shape():
    ideas = [RankedIdea(number=i, rank=i) for i in range(1, 7)]
    assign_lanes(ideas, ANCHOR)
    cost = est_batch_cost(ideas, ANCHOR)
    # #1 climbs to flag (spec+wire+demo+mvp+flag), #2-4 to demo, #5-6 to wire — all positive
    assert cost > 0
    # the single build lane dominates (mvp est is the big line)
    assert cost >= ANCHOR.rungs["4-mvp"].est_usd


class StubModel:
    """Returns canned specs / ranking / critique with token accounting but $0 (stub)."""
    def __init__(self):
        self.n = 0
    def complete(self, prompt, max_tokens=1024, system=None):
        self.n += 1
        if "Rank them" in prompt:
            return "[1,0,2]", Call("stub", "stub", 20, 3, 0.0)
        if "Critique" in prompt:
            return "- acceptance criteria not checkable; make them measurable", Call("stub", "stub", 20, 10, 0.0)
        return f"SPEC v{self.n}: user story + criteria", Call("stub", "stub", 30, 40, 0.0)


def test_rung1_flow_stubbed():
    idea = Idea(1, "keyboard shortcut to focus search", "Cmd-K focuses search", "feature")
    m = StubModel()
    r = run_rung1(idea, ANCHOR, builder=m, judge=m, n=3)
    assert len(r.specs) == 3
    assert r.top_index == 1               # ranking [1,0,2] -> winner is index 1
    assert r.ranking[0] == 1
    assert r.revised_top                  # reflection produced a revision
    assert "acceptance" in r.critique
    # cost accounting: 3 drafts + 1 rank + 1 critique + 1 revision = 6 calls
    assert len(r.calls) == 6
    assert r.cost_usd == 0.0              # stub


def test_rung1_bad_ranking_falls_back():
    idea = Idea(1, "x", "y", "feature")
    class Garbage:
        def complete(self, prompt, max_tokens=1024, system=None):
            if "Rank them" in prompt:
                return "no idea", Call("stub", "stub", 1, 1, 0.0)
            return "spec", Call("stub", "stub", 1, 1, 0.0)
    r = run_rung1(idea, ANCHOR, builder=Garbage(), judge=Garbage(), n=3)
    assert r.ranking == [0, 1, 2]        # graceful fallback to generation order

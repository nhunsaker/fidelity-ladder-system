"""P1: funnel lane assignment (pure, no spend) + rung 1 flow (stubbed builder/judge)."""
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.funnel import RUNG_DEMO, RUNG_FLAG, RUNG_WIRE, RankedIdea, assign_lanes, est_batch_cost
from fls.llm import Call
from fls.rung1 import compile_acceptance_stub, extract_acceptance_criteria, run_rung1

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
    """Returns canned specs / ranking / critique with token accounting but $0 (stub). Its specs
    never carry an ACCEPTANCE section, so it exercises the repair-then-fail-closed path."""
    def __init__(self):
        self.n = 0
    def complete(self, prompt, max_tokens=1024, system=None):
        self.n += 1
        if "Rank them" in prompt:
            return "[1,0,2]", Call("stub", "stub", 20, 3, 0.0)
        if "Critique" in prompt:
            return "- acceptance criteria not checkable; make them measurable", Call("stub", "stub", 20, 10, 0.0)
        return f"SPEC v{self.n}: user story + criteria", Call("stub", "stub", 30, 40, 0.0)


class StubModelWithAcceptance:
    """A builder that DOES emit the required ACCEPTANCE section — the criteria-compiled path."""
    def __init__(self):
        self.n = 0
    def complete(self, prompt, max_tokens=1024, system=None):
        self.n += 1
        if "Rank them" in prompt:
            return "[0,1,2]", Call("stub", "stub", 20, 3, 0.0)
        if "Critique" in prompt:
            return "- tighten the wording", Call("stub", "stub", 20, 10, 0.0)
        return (
            f"SPEC v{self.n}: user story + criteria\n\nACCEPTANCE:\n"
            "1. Cmd-K focuses the search input from any screen state.\n"
            "2. Escape clears focus and closes any open suggestions."
        ), Call("stub", "stub", 30, 40, 0.0)


def test_rung1_flow_stubbed():
    idea = Idea(1, "keyboard shortcut to focus search", "Cmd-K focuses search", "feature")
    m = StubModel()
    r = run_rung1(idea, ANCHOR, builder=m, judge=m, n=3)
    assert len(r.specs) == 3
    assert r.top_index == 1               # ranking [1,0,2] -> winner is index 1
    assert r.ranking[0] == 1
    assert r.revised_top                  # reflection produced a revision
    assert "acceptance" in r.critique
    # cost accounting: 3 drafts + 1 rank + 1 critique + 1 revision + 1 repair attempt = 7 calls
    assert len(r.calls) == 7
    assert r.cost_usd == 0.0              # stub
    # the theater fix: this builder never emits a parseable ACCEPTANCE section, even on repair —
    # fail CLOSED rather than pretend prose criteria are machine-checkable
    assert r.criteria == []
    assert r.acceptance_stub is None
    assert r.criteria_compiled is False


def test_rung1_criteria_compile_to_checkable_stub():
    idea = Idea(1, "keyboard shortcut to focus search", "Cmd-K focuses search", "feature")
    m = StubModelWithAcceptance()
    r = run_rung1(idea, ANCHOR, builder=m, judge=m, n=3)
    # no repair needed -> 3 drafts + 1 rank + 1 critique + 1 revision = 6 calls
    assert len(r.calls) == 6
    assert r.criteria_compiled is True
    assert len(r.criteria) == 2
    assert r.criteria[0].startswith("Cmd-K focuses")
    assert r.acceptance_stub is not None
    # the stub is a machine-checkable module: one test function per criterion, fail-closed body
    assert r.acceptance_stub.count("def test_criterion_") == 2
    assert "raise NotImplementedError" in r.acceptance_stub
    assert "Cmd-K focuses the search input" in r.acceptance_stub


def test_extract_acceptance_criteria_no_section_fails_closed():
    assert extract_acceptance_criteria("just a spec, no acceptance section") == []


def test_extract_acceptance_criteria_parses_numbered_lines():
    spec = "Spec body.\n\nACCEPTANCE:\n1. First thing.\n2. Second thing.\n"
    assert extract_acceptance_criteria(spec) == ["First thing.", "Second thing."]


def test_compile_acceptance_stub_empty_is_fail_closed():
    assert compile_acceptance_stub([]) is None


def test_rung1_bad_ranking_falls_back():
    idea = Idea(1, "x", "y", "feature")
    class Garbage:
        def complete(self, prompt, max_tokens=1024, system=None):
            if "Rank them" in prompt:
                return "no idea", Call("stub", "stub", 1, 1, 0.0)
            return "spec", Call("stub", "stub", 1, 1, 0.0)
    r = run_rung1(idea, ANCHOR, builder=Garbage(), judge=Garbage(), n=3)
    assert r.ranking == [0, 1, 2]        # graceful fallback to generation order

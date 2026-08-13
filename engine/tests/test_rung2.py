"""P1: rung 2 wireframe fan-out + suggested ranking (stubbed builder/judge, zero spend)."""
from pathlib import Path

from fls.adjudicator import Idea
from fls.llm import Call
from fls.rung2 import run_rung2


class StubModel:
    def complete(self, prompt, max_tokens=1024, system=None):
        if "Rank them" in prompt:
            return "[2,0,1]", Call("stub", "stub", 20, 3, 0.0)
        return '<div class="Box p-3"><input class="form-control" placeholder="Search"></div>', \
            Call("stub", "stub", 30, 60, 0.0)


def test_rung2_fans_out_and_ranks():
    idea = Idea(1, "cmd-k search", "focuses search", "feature")
    r = run_rung2(idea, "SPEC: cmd-k focuses search", builder=StubModel(), judge=StubModel(), n=3)
    assert len(r.wireframes) == 3
    assert all("Box" in w for w in r.wireframes)
    assert r.suggested_ranking == [2, 0, 1]
    assert r.picked_index is None        # human picks later via the controller
    assert len(r.calls) == 4             # 3 wireframes + 1 rank
    assert r.cost_usd == 0.0


def test_rung2_persists_artifacts(tmp_path):
    idea = Idea(7, "x", "y", "feature")
    r = run_rung2(idea, "spec", builder=StubModel(), judge=StubModel(), n=3)
    d = r.persist(tmp_path, expedition=7)
    assert (d / "candidate-0.html").exists()
    assert (d / "candidate-2.html").exists()
    assert (d / "ranking.json").read_text() == "[2, 0, 1]"


def test_rung2_bad_ranking_falls_back():
    class Garbage:
        def complete(self, prompt, max_tokens=1024, system=None):
            if "Rank them" in prompt:
                return "dunno", Call("stub", "stub", 1, 1, 0.0)
            return "<div></div>", Call("stub", "stub", 1, 1, 0.0)
    r = run_rung2(Idea(1, "x", "y", "feature"), "s", builder=Garbage(), judge=Garbage(), n=3)
    assert r.suggested_ranking == [0, 1, 2]

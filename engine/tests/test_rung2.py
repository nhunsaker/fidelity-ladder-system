"""P1: rung 2 wireframe fan-out + suggested ranking (stubbed builder/judge, zero spend)."""

from fls.adjudicator import Idea
from fls.llm import Call
from fls.rung2 import a11y_lint, run_rung2


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
    # a11y pre-check: the stub input has a placeholder, so it's clean — no reordering
    assert r.a11y_violations == [[], [], []]
    assert r.pre_check_passed is True
    assert r.clean_indices == [0, 1, 2]


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


# --- a11y_lint: the structural pre-check itself -----------------------------------------------

def test_a11y_lint_clean_html_has_no_violations():
    assert a11y_lint('<div class="Box p-3"><input placeholder="Search"></div>') == []


def test_a11y_lint_flags_img_without_alt():
    assert any("img" in v for v in a11y_lint('<img src="x.png">'))
    assert a11y_lint('<img src="x.png" alt="a search icon">') == []
    assert any("img" in v for v in a11y_lint('<img src="x.png" alt="">'))


def test_a11y_lint_flags_unlabeled_form_control():
    assert any("input" in v for v in a11y_lint("<input>"))
    assert a11y_lint('<input aria-label="Search">') == []
    assert a11y_lint('<label for="q">Search</label><input id="q">') == []


def test_a11y_lint_flags_empty_interactive_element():
    assert any("button" in v for v in a11y_lint("<button></button>"))
    assert a11y_lint('<button aria-label="Close">X</button>') == []
    assert a11y_lint("<button>Submit</button>") == []


def test_rung2_pre_check_reorders_clean_first_and_blocks_when_all_dirty():
    class DirtyModel:
        def complete(self, prompt, max_tokens=1024, system=None):
            if "Rank them" in prompt:
                return "[0,1,2]", Call("stub", "stub", 1, 1, 0.0)
            return "<img src='x.png'>", Call("stub", "stub", 1, 1, 0.0)   # every line a11y-dirty
    r = run_rung2(Idea(1, "x", "y", "feature"), "s", builder=DirtyModel(), judge=DirtyModel(), n=3)
    assert r.clean_indices == []
    assert r.pre_check_passed is False    # fail-closed: nothing safe to hand the human

    class MixedModel:
        def __init__(self):
            self.n = 0
        def complete(self, prompt, max_tokens=1024, system=None):
            if "Rank them" in prompt:
                return "[0,1,2]", Call("stub", "stub", 1, 1, 0.0)
            self.n += 1
            html = "<img src='x.png'>" if self.n == 1 else '<img src="x.png" alt="ok">'
            return html, Call("stub", "stub", 1, 1, 0.0)
    r2 = run_rung2(Idea(1, "x", "y", "feature"), "s", builder=MixedModel(), judge=MixedModel(), n=3)
    assert r2.pre_check_passed is True
    # dirty candidate (index 0) sorted after the clean ones (indices 1, 2)
    assert r2.suggested_ranking.index(0) > r2.suggested_ranking.index(1)
    assert r2.suggested_ranking.index(0) > r2.suggested_ranking.index(2)

"""V2-P1 engine gaps — prune-early [Wang#2] · human-latency [Yao#3] · preview serving [P2.2].
All stubbed, zero spend."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.anchor import Anchor
from fls.calibration import build_report
from fls.funnel import RankedIdea, assign_lanes, prune_early
from fls.ledger import Decision, Ledger
from fls.llm import Call

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


class ScoringJudge:
    """Returns fixed scores for the prune call (one cheap call, in order)."""
    def __init__(self, scores):
        self.scores = scores
        self.calls = 0

    def complete(self, prompt, max_tokens=1024, system=None):
        self.calls += 1
        return json.dumps(self.scores), Call("azure-openai", "gpt-5.4-nano", 200, 20,
                                             usd=0.0, normalized_usd=0.0002, funded_by="credits")


class BrokenJudge:
    def complete(self, prompt, max_tokens=1024, system=None):
        raise RuntimeError("judge down")


def _ideas(n):
    return [RankedIdea(number=100 + i, rank=i) for i in range(1, n + 1)]


def _partials(ideas):
    return {i.number: f"partial spec text for #{i.number} " * 10 for i in ideas}


# ── prune-early ────────────────────────────────────────────────────────────────
def test_prune_kills_weak_branches_before_render_spend():
    ideas = _ideas(4)
    judge = ScoringJudge([8, 2, 7, 1])           # ranks 2 and 4 are weak
    rpt = prune_early(ideas, _partials(ideas), ANCHOR, judge)
    assert [i.number for i in rpt.kept] == [101, 103]
    assert [p.number for p in rpt.pruned] == [102, 104]
    assert judge.calls == 1                       # ONE cheap call for the whole batch
    # a pruned branch never reaches assign_lanes -> never books render spend
    assign_lanes(rpt.kept, ANCHOR)
    assert all(i.number not in (102, 104) for i in rpt.kept)


def test_prune_records_saved_est_usd():
    ideas = _ideas(3)
    judge = ScoringJudge([1, 9, 9])              # rank 1 (the auto-build lane!) is weak
    rpt = prune_early(ideas, _partials(ideas), ANCHOR, judge)
    assert len(rpt.pruned) == 1
    # the pruned idea WOULD have climbed to 5-flagged: savings = full-climb estimate
    full_climb = sum(ANCHOR.rungs[k].est_usd
                     for k in ["1-spec", "2-wireframe", "3-demo", "4-mvp", "5-flagged"])
    assert rpt.pruned[0].saved_est_usd == round(full_climb, 4)
    assert rpt.saved_est_usd == rpt.pruned[0].saved_est_usd


def test_prune_fails_open_on_judge_failure(tmp_path):
    """A judge glitch must never destroy admitted work — no pruning, v1 behavior."""
    ideas = _ideas(3)
    rpt = prune_early(ideas, _partials(ideas), ANCHOR, BrokenJudge())
    assert len(rpt.kept) == 3 and rpt.pruned == []


def test_prune_fails_open_on_bad_parse():
    ideas = _ideas(2)
    class Junk:
        def complete(self, prompt, max_tokens=1024, system=None):
            return "no scores here", Call("stub", "stub", 1, 1)
    rpt = prune_early(ideas, _partials(ideas), ANCHOR, Junk())
    assert len(rpt.kept) == 2 and rpt.pruned == []


def test_prune_lands_in_ledger_with_open_human_slot(tmp_path):
    ideas = _ideas(3)
    led = Ledger(tmp_path / "ledger.jsonl")
    prune_early(ideas, _partials(ideas), ANCHOR, ScoringJudge([9, 0, 9]), ledger=led)
    rows = [d for d in led.rows if d.judge_verdict == "prune"]
    assert len(rows) == 1 and rows[0].expedition == 102
    assert rows[0].human_verdict is None          # a human override -> calibration flywheel


# ── human-latency ──────────────────────────────────────────────────────────────
def test_decision_human_latency(tmp_path):
    d = Decision(1, "2-wireframe", "advance", "advance", 0.001,
                 gate_opened_at=1000.0, human_responded_at=1930.0)
    assert d.human_latency_s == 930.0
    assert Decision(1, "2-wireframe", "advance", None, 0.0).human_latency_s is None


def test_ledger_latency_avg_and_calibration_surface(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.record(Decision(1, "2-wireframe", "advance", "advance", 0.001,
                        gate_opened_at=0.0, human_responded_at=60.0))
    led.record(Decision(2, "2-wireframe", "advance", "advance", 0.001,
                        gate_opened_at=0.0, human_responded_at=180.0))
    led.record(Decision(3, "2-wireframe", "advance", "advance", 0.001))  # no timestamps -> excluded
    assert led.human_latency_avg("2-wireframe") == 120.0
    rpt = build_report(led, ANCHOR)
    rung = next(r for r in rpt.rungs if r.rung == "2-wireframe")
    assert rung.human_latency_avg_s == 120.0
    assert "human-latency" in rpt.as_markdown()


def test_old_ledger_rows_still_load(tmp_path):
    """Rows written before the latency fields must load (backward-compatible schema)."""
    p = tmp_path / "l.jsonl"
    p.write_text(json.dumps({"expedition": 1, "rung": "0-intent", "judge_verdict": "admit",
                             "human_verdict": "admit", "judge_cost_usd": 0.0,
                             "judge_tokens_in": 1, "judge_tokens_out": 1}) + "\n")
    led = Ledger(p).load()
    assert led.rows[0].human_latency_s is None


# ── preview serving ────────────────────────────────────────────────────────────
def _client(tmp_path):
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = None
    return TestClient(appmod.app)


def test_preview_serves_demo(tmp_path):
    d = Path(tmp_path) / "expeditions" / "101" / "demo"
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body><button>demo</button></body></html>")
    c = _client(tmp_path)
    r = c.get("/preview/101")
    assert r.status_code == 200
    assert "<button>demo</button>" in r.text


def test_preview_404_when_missing(tmp_path):
    c = _client(tmp_path)
    assert c.get("/preview/999").status_code == 404


def test_preview_refuses_path_traversal(tmp_path):
    c = _client(tmp_path)
    assert c.get("/preview/..%2F..%2Fetc").status_code == 404


def test_rung3_result_carries_preview_url(tmp_path):
    from fls.adjudicator import Idea
    from fls.rung3 import WalkthroughResult, run_rung3

    class StubBuilder:
        def complete(self, prompt, max_tokens=1024, system=None):
            return "<html><body><button>hi</button></body></html>", Call("stub", "stub", 1, 1)

    class StubWalkthrough:
        def run(self, demo_path, acceptance):
            return WalkthroughResult(True, "clean", ["loaded"])

    idea = Idea(101, "x", "y", "feature")
    r = run_rung3(idea, "spec", "wire", StubBuilder(), StubWalkthrough(), str(tmp_path), 101)
    assert r.preview_url == "/preview/101"


def test_bounded_context_carries_component_inventory():
    """V2-P4: rung-4 builders compose from the target app's REAL component library."""
    from fls.rung4 import BoundedContext
    ctx = BoundedContext(spec="s", wireframe="w", acceptance_test="t",
                         component_inventory="Button, Card, Table (from @metatoy/bootstrap-styled)")
    r = ctx.render()
    assert "COMPONENT LIBRARY" in r and "bootstrap-styled" in r
    # inventory can never crowd out the failure feedback (the per-section caps hold)
    ctx2 = BoundedContext(spec="s", wireframe="w", component_inventory="X" * 10000,
                          prior_failures=["the-failure-that-steers"])
    assert "the-failure-that-steers" in ctx2.render()

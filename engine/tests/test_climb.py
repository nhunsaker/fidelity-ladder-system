"""P2: advance_expedition drives rung 3 -> 4 -> await-signoff, with descent paths.
Fully stubbed (zero spend)."""
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.climb import AWAIT_SIGNOFF, DESCENDED, advance_expedition
from fls.expedition import Expedition
from fls.funnel import RUNG_DEMO, RUNG_FLAG, RUNG_MVP, RUNG_WIRE
from fls.llm import Call
from fls.rung3 import WalkthroughResult
from fls.verifier import Outcome, VerifierResult

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


class StubBuilder:
    def complete(self, prompt, max_tokens=1024, system=None):
        return "<html>demo/mvp</html>", Call("stub", "stub", 100, 200, 0.0)


class Walk:
    def __init__(self, ok=True):
        self.ok = ok
    def run(self, demo_path, acceptance):
        return WalkthroughResult(self.ok, "ok" if self.ok else "flow broke at step 2")


class Verify:
    def __init__(self, outcome=Outcome.passed, ev=None):
        self.outcome, self.ev = outcome, ev or {"eval_score": "0.95"}
    def verify(self, artifact_dir):
        return VerifierResult(self.outcome, "d", self.ev)


def _exp(target):
    e = Expedition(1, Idea(1, "cmd-k search", "cmd-k focuses search from any screen", "feature"),
                   target_rung=target)
    e.spec = "cmd-k focuses search"
    return e


def test_full_climb_to_await_signoff(tmp_path):
    e = advance_expedition(_exp(RUNG_FLAG), "<div>wire</div>", ANCHOR, StubBuilder(),
                           Walk(ok=True), Verify(Outcome.passed), str(tmp_path), str(tmp_path/"L.md"))
    assert e.rung == RUNG_FLAG
    assert e.status == AWAIT_SIGNOFF          # hard gate: never auto-ships
    assert (tmp_path / "1" / "demo" / "index.html").exists()


def test_walkthrough_failure_descends(tmp_path):
    e = advance_expedition(_exp(RUNG_FLAG), "<div>wire</div>", ANCHOR, StubBuilder(),
                           Walk(ok=False), Verify(Outcome.passed), str(tmp_path), str(tmp_path/"L.md"))
    assert e.status == DESCENDED and e.rung == RUNG_WIRE
    assert "walkthrough failed" in e.reason


def test_rung4_design_failure_descends_with_lesson(tmp_path):
    lessons = tmp_path / "L.md"
    v = Verify(Outcome.design, {"acceptance_unmet": ["no focus from modal"]})
    e = advance_expedition(_exp(RUNG_MVP), "<div>wire</div>", ANCHOR, StubBuilder(),
                           Walk(ok=True), v, str(tmp_path), str(lessons))
    assert e.status == DESCENDED and e.rung == RUNG_WIRE
    assert lessons.exists()                    # durable lesson written


def test_demo_lane_parks_on_shelf(tmp_path):
    # target rung 3 only (an interactive-demo-lane idea) -> parks after passing walkthrough
    e = advance_expedition(_exp(RUNG_DEMO), "<div>wire</div>", ANCHOR, StubBuilder(),
                           Walk(ok=True), Verify(Outcome.passed), str(tmp_path), str(tmp_path/"L.md"))
    assert e.rung == RUNG_DEMO
    assert "shelf" in e.reason

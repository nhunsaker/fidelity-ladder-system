"""advance_expedition under the harness-poc profile: rung 3 and rung 4 park at AWAIT_APPROVE and
resume after approval (Phase 0)."""
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.climb import AWAIT_SIGNOFF, advance_expedition
from fls.expedition import AWAIT_APPROVE, Expedition
from fls.llm import Call
from fls.profile import HARNESS_POC_PROFILE, WEB_LADDER_PROFILE
from fls.rung3 import WalkthroughResult
from fls.verifier import VerifierResult


class B:
    def complete(self, prompt, max_tokens=1024, system=None):
        return "<html>ok</html>", Call("stub", "m", 1, 1)


class W:
    def run(self, html_path, expedition):
        return WalkthroughResult(passed=True, detail="ok")


class V:
    def verify(self, artifact_dir):
        return VerifierResult(outcome="passed", detail="green", evidence={"diff": "+1"})


def _exp(n=7):
    return Expedition(n, Idea(n, "add a share modal", "modal opens", "feature"), target_rung=5,
                      rung=2, spec="spec text")


ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


def _anchor():
    return ANCHOR


def test_web_ui_profile_runs_through_to_signoff(tmp_path):
    e = advance_expedition(_exp(), "<wire>", _anchor(), B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=WEB_LADDER_PROFILE)
    assert e.status == AWAIT_SIGNOFF and e.rung == 5


def test_harness_profile_parks_at_rung3_then_rung4_then_signoff(tmp_path):
    a = _anchor()
    e = advance_expedition(_exp(), "<wire>", a, B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=HARNESS_POC_PROFILE)
    assert e.status == AWAIT_APPROVE and e.rung == 3
    # approve -> re-enter: rung 3 is skipped (already done), rung 4 runs, parks again
    e = advance_expedition(e, "<wire>", a, B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=HARNESS_POC_PROFILE)
    assert e.status == AWAIT_APPROVE and e.rung == 4
    # approve again -> rung 5 gate
    e = advance_expedition(e, "<wire>", a, B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=HARNESS_POC_PROFILE)
    assert e.status == AWAIT_SIGNOFF and e.rung == 5


def test_feedback_reruns_rung3_by_resetting_rung(tmp_path):
    a = _anchor()
    e = advance_expedition(_exp(), "<wire>", a, B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=HARNESS_POC_PROFILE)
    n_calls = len(e.calls)
    e.rung = 2  # feedback: re-run rung 3
    e = advance_expedition(e, "<wire>", a, B(), W(), V(), str(tmp_path), str(tmp_path / "l.md"),
                           profile=HARNESS_POC_PROFILE)
    assert e.status == AWAIT_APPROVE and e.rung == 3 and len(e.calls) > n_calls

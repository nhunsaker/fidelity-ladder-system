"""Plan items 2d, 2e and 5: the expensive rung resumes, recovery spend is visible, and a broken
run offers a way back.

Every one of these is a thing expedition 18, 19 or 20 did wrong in front of someone.
"""
from __future__ import annotations

import subprocess

import pytest

from fls.builders.claude_code_builder import ClaudeCodeBuilder as FeatureBuilder
from fls.demo import actions_for, demo_view


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=False)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "vessel"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("v\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


# ── 2d · the expensive rung resumes instead of restarting ──────────────────────────────────

def test_a_worktree_with_work_in_it_is_adopted(repo, tmp_path):
    """THE EXPENSIVE ONE. Rung 4 runs up to eighty minutes and every attempt began by DELETING
    the worktree, so a build that died at minute seventy-five paid for all seventy-five again."""
    b = FeatureBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    wt = tmp_path / "mvp" / "wt"
    b.make_worktree(7, wt)
    (wt / "feature.py").write_text("# half a feature\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "wip: half the feature")

    standing = b.standing_work(7, wt)
    assert standing is not None, "a worktree with a commit in it was treated as disposable"
    base, carried = standing
    assert "wip: half the feature" in carried and "feature.py" in carried


def test_uncommitted_work_counts_too(repo, tmp_path):
    """A session killed mid-edit leaves a dirty tree, not a commit. That is still work."""
    b = FeatureBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    wt = tmp_path / "mvp" / "wt"
    b.make_worktree(7, wt)
    (wt / "feature.py").write_text("# half a feature\n")
    _git(wt, "add", "-A")
    assert b.standing_work(7, wt) is not None


def test_a_clean_worktree_is_not_work_in_progress(repo, tmp_path):
    """Adopting an untouched checkout would tell the session it was continuing something when it
    was not — and invite it to go looking for work that does not exist."""
    b = FeatureBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    wt = tmp_path / "mvp" / "wt"
    b.make_worktree(7, wt)
    assert b.standing_work(7, wt) is None


@pytest.mark.parametrize("wreck", ["not-a-git-dir", "wrong-branch"])
def test_an_unrecognisable_tree_is_rebuilt_rather_than_salvaged(repo, tmp_path, wreck):
    """FAIL-CLOSED. Half an hour saved is not worth building on a tree whose state nobody can
    describe."""
    b = FeatureBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    wt = tmp_path / "mvp" / "wt"
    if wreck == "not-a-git-dir":
        wt.mkdir(parents=True)
        (wt / "stuff.py").write_text("x\n")
    else:
        b.make_worktree(7, wt)
        (wt / "f.py").write_text("x\n")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "w")
        _git(wt, "checkout", "-q", "-b", "somebody-elses-branch")
    assert b.standing_work(7, wt) is None


def test_the_session_is_told_it_was_interrupted_not_rejected(repo, tmp_path):
    """`feedback` and `prior_failures` both mean "this was judged and found wanting". Interrupted
    work was never judged at all, and telling the session it failed invites it to throw away a
    nearly finished build."""
    from fls.rung4 import BoundedContext
    b = FeatureBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    p = b.prompt(BoundedContext(spec="a share sheet", wireframe=""), carried="commits already made:\n  abc wip")
    assert "INTERRUPTED, not rejected" in p
    assert "Keep what is sound and finish the job" in p
    assert "abc wip" in p


# ── 2e · recovery spend is visible ─────────────────────────────────────────────────────────

def test_spend_on_a_retry_is_counted_as_recovery():
    """A run that cost $8 climbing and one that cost $4 climbing and $4 recovering are not the
    same run, and the total cannot tell them apart. The second says something is breaking."""
    from fls.orchestration.types import RungResult
    from fls.orchestration.workflows import HarnessExpedition

    w = HarnessExpedition()
    w._absorb(RungResult(rung=2, passed=False, state="parked", normalized_usd=1.5), attempt=1)
    w._absorb(RungResult(rung=2, passed=True, state="await-pick", normalized_usd=2.0), attempt=2)
    assert w._spent == pytest.approx(3.5)
    assert w._recovered == pytest.approx(2.0), "the re-run was billed as progress"


def test_a_first_attempt_is_never_recovery():
    from fls.orchestration.types import RungResult
    from fls.orchestration.workflows import HarnessExpedition

    w = HarnessExpedition()
    w._absorb(RungResult(rung=2, passed=True, state="await-pick", normalized_usd=2.0), attempt=1)
    assert w._recovered == 0.0


# ── 5 · a broken run offers a way back; a stopped one does not ─────────────────────────────

def test_a_broken_run_offers_retry():
    """THE BRANCH THAT NEVER FIRED. `actions_for` had a "stopped" case written after expedition
    17 — but "stopped" is a label the view DERIVES and never a status the store holds. A broken
    run is stored `parked`, which is terminal, so every branch fell through to [] and expeditions
    18, 19 and 20 each showed a visitor a dead run with nothing to do about it."""
    assert actions_for("parked", "2-wireframe", "failure") == ["retry", "kill"]


def test_a_run_a_person_stopped_offers_nothing():
    """They meant to stop it. Offering to start it again is arguing with them."""
    assert actions_for("parked", "2-wireframe", "human") == []


def test_an_unlabelled_park_stays_silent():
    """Records written before `parked_by` existed carry no answer, and inventing one would be
    guessing about whether a person made a decision."""
    assert actions_for("parked", "2-wireframe", "") == []


def test_the_visitor_is_told_the_step_broke_in_words_they_can_act_on():
    """Expedition 18's stored reason was "rung 2 stopped: it ran past its 10 minute limit" — false
    (it ran 93 seconds) and then censored to a generic line anyway, because it contains the word
    "rung". The guard is right; the fix is to write the visitor's sentence rather than launder the
    operator's."""
    rec = {"number": 18, "intent": "a share sheet", "rung": "2-wireframe", "status": "parked",
           "source": "demo:n", "reason": "rung 2 stopped: it ran past its 10 minute limit",
           "parked_by": "failure", "spent": 0.0, "normalized_usd": 0.0}
    v = demo_view(rec, None)
    assert "try that step again" in v["detail"]
    assert v["actions"] == ["retry", "kill"]
    from fls.demo import _INTERNAL
    assert not any(w in v["detail"].lower() for w in _INTERNAL), "machinery reached the visitor"


def test_build_actually_adopts_rather_than_deleting(repo, tmp_path):
    """The wiring, not the capability.

    `standing_work` can be perfect and unreachable — `build()` opened by deleting the worktree,
    and a test that only calls the helper would never notice. The tell is that the previous
    attempt's file is still on disk afterwards, and that the session was told about it.
    """
    from fls.rung4 import BoundedContext

    seen = {}

    class Session:
        timeout_s = 600
        log_path = None

        def run(self, prompt, system=None):
            seen["prompt"] = prompt
            from fls.llm import Call
            class R:  # noqa: E306
                pass
            r = R()
            r.text, r.timed_out = "done", False
            r.call = Call("claude-code", "m", 0, 0, usd=0.0, normalized_usd=0.0)
            return r

    b = FeatureBuilder(str(repo), session_factory=lambda **k: Session(), test_cmd="true")
    art = tmp_path / "art"
    wt = art / "mvp" / "wt"
    b.make_worktree(7, wt)
    (wt / "half.py").write_text("# work from the attempt that died\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "wip: half done")

    b.build(7, BoundedContext(spec="a share sheet", wireframe=""), artifact_dir=str(art))

    assert (wt / "half.py").exists(), \
        "build() deleted the worktree — the interrupted attempt's work was thrown away"
    assert "INTERRUPTED, not rejected" in seen["prompt"]
    assert "wip: half done" in seen["prompt"]

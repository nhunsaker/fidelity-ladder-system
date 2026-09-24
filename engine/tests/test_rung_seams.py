"""The seams between rungs, tested by running one rung's real output into the next one's input.

WHY THIS FILE EXISTS. Expedition 22 climbed all five rungs and died at the last one on GitHub 422,
"No commits between main and exp-22", with 229 lines of finished and tested work sitting in the
worktree. Rung 4 said done because `git diff` against the base covers a dirty tree; rung 5 said
a pull request needs commits. Each rung was individually correct, individually green, and they had
never once been run against each other.

That is the shape of nearly every failure this system has had: not a component that is wrong, but
two components that were each tested alone and disagree at the join. Unit tests cannot see it by
construction — a mock of rung 4's output encodes what I BELIEVED rung 4 produces, which is exactly
the thing that turned out to be untrue.

So these tests use no mocks at the seam. They run the producer, take what it actually leaves
behind, and assert the consumer's real precondition against it.
"""
from __future__ import annotations

import subprocess

import pytest

from fls.builders.claude_code_builder import ClaudeCodeBuilder
from fls.rung4 import BoundedContext


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


def _session_that_writes(files: dict):
    """A session that does what a real one does: leaves files in the worktree and says so."""
    class S:
        timeout_s = 600
        log_path = None

        def __init__(self, cwd):
            self.cwd = cwd

        def run(self, prompt, system=None):
            from pathlib import Path

            from fls.llm import Call
            for name, body in files.items():
                p = Path(self.cwd) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body)
            class R:  # noqa: E306
                pass
            r = R()
            r.text, r.timed_out = "built it", False
            r.call = Call("claude-code", "m", 0, 0, usd=0.0, normalized_usd=0.0)
            return r
    return S


def _build(repo, tmp_path, files):
    S = _session_that_writes(files)
    b = ClaudeCodeBuilder(str(repo), session_factory=lambda cwd_=None, **k: S(cwd_ or str(tmp_path)),
                          test_cmd="true", line_budget=400)
    art = tmp_path / "art"
    return b, b.build(7, BoundedContext(spec="show the call price", wireframe=""),
                      artifact_dir=str(art)), art / "mvp" / "wt"


# ── rung 4 -> rung 5 ───────────────────────────────────────────────────────────────────────

def test_a_passing_build_leaves_a_branch_a_pull_request_can_be_opened_from(repo, tmp_path):
    """THE EXPEDITION 22 TEST. Rung 5's precondition is not "there is a diff", it is "there are
    commits between the base and this branch" — that is literally what GitHub checks and what it
    refused. Asserted here against the real worktree rung 4 leaves."""
    _, res, wt = _build(repo, tmp_path, {"src/feature.ts": "export const x = 1\n"})
    assert res.passed, res.detail
    commits = _git(wt, "log", "--oneline", "main..HEAD").stdout.strip()
    assert commits, ("rung 4 passed but left no commits — rung 5 will get GitHub 422 "
                     "'No commits between main and this branch'")


def test_the_committed_tree_is_clean_so_nothing_is_left_behind(repo, tmp_path):
    """Work half-committed is worse than work uncommitted: the pull request would carry some of
    the change and the worktree would quietly hold the rest."""
    _, res, wt = _build(repo, tmp_path, {"src/a.ts": "1\n", "src/b.ts": "2\n",
                                         "tests/a.test.ts": "3\n"})
    assert res.passed
    assert _git(wt, "status", "--porcelain").stdout.strip() == "", "files were left uncommitted"


def test_every_file_the_session_wrote_reaches_the_commit(repo, tmp_path):
    """A new file is the most normal thing a feature adds and the easiest for git to miss."""
    _, res, wt = _build(repo, tmp_path, {"src/new.ts": "1\n", "tests/new.test.ts": "2\n"})
    in_commit = set(_git(wt, "diff", "--name-only", "main", "HEAD").stdout.split())
    assert {"src/new.ts", "tests/new.test.ts"} <= in_commit


def test_a_failing_build_commits_nothing(repo, tmp_path):
    """A rung that did not pass must not leave a branch that looks shippable. The next rung reads
    the branch, not the verdict."""
    S = _session_that_writes({"src/f.ts": "x\n"})
    b = ClaudeCodeBuilder(str(repo), session_factory=lambda cwd_=None, **k: S(cwd_ or str(tmp_path)),
                          test_cmd="false", line_budget=400)          # the vessel check fails
    art = tmp_path / "art"
    res = b.build(7, BoundedContext(spec="s", wireframe=""), artifact_dir=str(art))
    wt = art / "mvp" / "wt"
    assert res.passed is False
    assert not _git(wt, "log", "--oneline", "main..HEAD").stdout.strip(), \
        "a failed build left commits a later rung would happily ship"


def test_a_session_that_changed_nothing_is_still_caught(repo, tmp_path):
    """The pre-existing guard, re-asserted at the seam: committing must not paper over an empty
    build by creating an empty commit."""
    _, res, wt = _build(repo, tmp_path, {})
    assert res.passed is False and "changed nothing" in res.detail


# ── the base a build branches from ─────────────────────────────────────────────────────────

def test_the_build_branches_from_the_remote_not_the_local_copy(repo, tmp_path):
    """The clone on the box sat FOUR COMMITS behind origin/main, so every expedition branched from
    a base that predated work already merged.

    Two things followed, both seen live. Pull requests drifted into conflict for no reason a
    reviewer could see — #6 and #7 disagreed about a `flags.json` they had started from different
    versions of. And expedition 27 was asked to change the reactions feature and found no reactions
    code, because the merge that added it was four commits ahead of where it stood.
    """
    origin = tmp_path / "origin"
    _git(repo, "clone", "-q", str(repo), str(origin))          # origin gets a commit repo does not
    (origin / "LATER.md").write_text("merged after the clone\n")
    _git(origin, "config", "user.email", "t@t")
    _git(origin, "config", "user.name", "t")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "a merge the local clone has not seen")
    _git(repo, "remote", "add", "origin", str(origin))

    b = ClaudeCodeBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    wt = tmp_path / "mvp" / "wt"
    b.make_worktree(7, wt)
    assert (wt / "LATER.md").exists(), \
        "the build branched from a stale local main and cannot see what is already merged"


def test_a_failed_fetch_still_builds_rather_than_failing_the_rung(repo, tmp_path):
    """Best effort by design. A network blip must not fail a rung that can still build against a
    slightly old base — that trades a real failure for a stale one. The base used is reported
    either way, so nobody has to guess which they got."""
    b = ClaudeCodeBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    assert b.base_ref() == "main", "no remote configured should fall back, not raise"
    wt = tmp_path / "mvp" / "wt"
    branch, sha = b.make_worktree(7, wt)
    assert branch == "exp-7" and sha


# ── rung 1: the theatre-gate, on the path this instance actually runs ───────────────────────

class _SpecSession:
    """Returns a spec whose ACCEPTANCE section is whatever the test wants it to be."""

    timeout_s = 600
    log_path = None

    def __init__(self, body):
        self.body = body

    def run(self, prompt, system=None):
        from fls.llm import Call
        class R:  # noqa: E306
            pass
        r = R()
        r.text, r.timed_out = self.body, False
        r.call = Call("claude-code", "m", 0, 0, usd=0.0, normalized_usd=0.0)
        r.num_turns, r.session_id, r.exit_code, r.raw = 1, "s", 0, {}
        return r


def _runner(tmp_path, body):
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    return LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(1,),
                      session_factory_=lambda *args, **k: (lambda **kk: _SpecSession(body)))


# The shape `_SPEC_SYS` demands: an `ACCEPTANCE:` line, then NUMBERED observable behaviours.
# Bullets do not parse, which is the point — `extract_acceptance_criteria` fails closed on prose.
CHECKABLE = """SPEC
The fold button reads "Fold hand".

ACCEPTANCE:
1. The action bar's fold button shows the text "Fold hand".
2. No other button label on the action bar changes.
"""

# Prose where the numbers should be: exactly what an unbuildable request produces.
VAGUE = """SPEC
Make the app feel more modern and delightful.

ACCEPTANCE:
It should feel better and more modern to use.
"""


def test_a_spec_with_checkable_criteria_climbs(tmp_path):
    from fls.orchestration.types import RungRequest
    r = _runner(tmp_path, CHECKABLE).spec(
        RungRequest(number=7, rung=1, intent="rename the fold button", success="it says Fold hand"))
    assert r.passed and r.state == "climbing", r.detail
    assert r.spec, "the spec itself has to travel — rungs 2-4 read it"
    assert r.artifacts.get("acceptance_stub"), "rung 4 builds against this"


def test_a_spec_nothing_could_check_parks_for_a_person(tmp_path):
    """EXPEDITION 24. "Make the app better and more modern" was admitted — correctly, under a
    permissive bar whose own words are "the spec rung exists to settle scope" — and then climbed
    to a pick gate, because the spec rung was a stub and nothing settled anything.

    The theatre-gate exists (`rung1.criteria_compiled`) and was enforced in `controller.py` and
    nowhere in the durable path, which is the only path this instance runs. Same shape as the
    budget ceiling, which was once enforced everywhere except here.
    """
    from fls.orchestration.types import RungRequest
    r = _runner(tmp_path, VAGUE).spec(
        RungRequest(number=7, rung=1, intent="make it better and more modern", success=""))
    assert r.passed is False
    assert r.state == "needs-human", "a request a person can still rescue must not be parked dead"
    assert "how you would know" in r.detail
    # And the refusal must be readable by the visitor it is written for.
    from fls.demo import _INTERNAL
    assert not any(w in r.detail.lower() for w in _INTERNAL), "machinery reached the visitor"


def test_rung_1_stays_a_stub_when_it_is_not_declared_live(tmp_path):
    """FLS_LIVE_RUNGS is how an instance says which rungs cost money. A rung that ignores it would
    start spending on every install that had not asked for it."""
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest
    r = LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(2, 3, 4, 5),
                   session_factory_=lambda *a, **k: (lambda **kk: _SpecSession(VAGUE))).spec(
        RungRequest(number=7, rung=1, intent="anything", success=""))
    assert r.passed is True and "stub" in r.detail.lower()


INSUFFICIENT_REPLY = "INSUFFICIENT: the request names no surface, no behaviour and no way to tell."


def test_a_spec_rung_may_say_the_request_contains_no_spec(tmp_path):
    """EXPEDITION 29, re-filed AFTER rung 1 went live. "Make the app better and more modern"
    produced four perfectly well-formed acceptance criteria — every specific invented, none of them
    in the request. The theatre-gate passed it, correctly: it checks whether criteria PARSE, not
    whether they are faithful. Form, not fidelity.

    Which is the same failure rung 2 had at expedition 28 — asked to produce a thing, a model
    produces the thing. A rung that cannot decline invents, and downstream treats the invention as
    what the person asked for. So rung 1 gets the exit rung 2 got.
    """
    from fls.orchestration.types import RungRequest
    r = _runner(tmp_path, INSUFFICIENT_REPLY).spec(
        RungRequest(number=7, rung=1, intent="make it better and more modern", success=""))
    assert r.passed is False
    # ASKS, DOES NOT CLOSE. This was `needs-human` — Stop and nothing else — which was right when
    # the alternative was a Retry that re-ran the identical words. Expedition 60 ("Make it bigger
    # and red", 2026-09-16) got that closed run with a sentence telling the person what to say
    # and nowhere to say it. A request with NO referent deserves a follow-up at least as much as
    # one with two, so it takes the same gate as an ambiguous request: their own words, no
    # lettered options, and rung 1 runs again with them.
    assert r.state == "await-answer"
    assert "names no surface" in r.detail
    assert "how you would know it worked" in r.detail
    assert r.artifacts["question"]["options"] == []
    assert r.artifacts["question"]["ask"] == r.detail
    assert r.spec == "", "an invented spec must not travel to rung 2 as though it were real"


def test_the_refusal_is_matched_at_the_start_not_anywhere():
    """A spec that MENTIONS the word while discussing edge cases is a spec. Rejecting good work
    for a coincidence of vocabulary would be its own kind of theatre."""
    from fls.rung1 import insufficient_reason
    assert insufficient_reason(INSUFFICIENT_REPLY).startswith("the request names no surface")
    assert insufficient_reason(
        "SPEC\nHandle the case where data is INSUFFICIENT: show an empty state.\n"
        "ACCEPTANCE:\n1. An empty state appears.\n") == ""
    assert insufficient_reason("") == ""


def test_a_bare_refusal_still_says_something_useful():
    """The marker with nothing after it is still a refusal, and the person still needs a sentence."""
    from fls.rung1 import insufficient_reason
    assert insufficient_reason("INSUFFICIENT:") == "the request does not say what to change"


def test_the_spec_prompt_offers_the_exit():
    """An exit nothing is told about is an exit nobody takes."""
    from fls.rung1 import _SPEC_SYS
    assert "INSUFFICIENT:" in _SPEC_SYS
    assert "correct answer, not a failure" in _SPEC_SYS


def test_a_refusal_reaches_the_visitor_as_something_they_can_act_on():
    """EXPEDITION 30. The spec rung declined a vague request in 40 seconds with a useful sentence,
    and the demo offered RETRY — which would re-run the identical request for the identical
    answer. A button that can only repeat itself is a false affordance.

    `needs-human` at the first stage offers only Stop, which is honest: nothing is broken and
    there is no gate holding a revision, so the way forward is to file again with what was
    missing. The detail says so.
    """
    from fls.demo import actions_for, demo_view
    assert actions_for("needs-human", "1-spec") == ["kill"], \
        "retry would re-run the same words and get the same refusal"
    rec = {"number": 30, "intent": "make it better", "rung": "1-spec", "status": "needs-human",
           "source": "demo:n", "spent": 0.0, "normalized_usd": 0.0,
           "reason": "No screens are named. Say what should change on screen, and how you would "
                     "know it worked."}
    v = demo_view(rec, None)
    assert v["actions"] == ["kill"]
    assert "how you would know it worked" in v["detail"]


def test_a_concluded_refusal_is_not_labelled_stopped(tmp_path):
    """EXPEDITION 31. The store said `needs-human` and the view said "Stopped", offering Retry.

    `stopped` is derived as "the workflow is not running and the status is not terminal" — which
    is true of a refusal, and wrong about it. Stopped means the run DIED WITHOUT CONCLUDING;
    needs-human is a conclusion. A derived label is a guess about a state the store already knows,
    and this is the second time today one of them overrode the truth.
    """
    from fls.demo import demo_view
    rec = {"number": 31, "intent": "make it better", "rung": "1-spec", "status": "needs-human",
           "source": "demo:n", "spent": 0.0, "normalized_usd": 0.0,
           "reason": "The idea names no target screens. Say what should change on screen."}
    v = demo_view(rec, {"running": False, "artifacts": {}})
    assert v["status"] != "Stopped", "a considered refusal was relabelled as a crash"
    assert v["actions"] == ["kill"], "retry would re-run the same words for the same answer"


def test_a_repo_with_no_remote_is_not_a_warning(repo, tmp_path, caplog):
    """A fixture vessel, or an instance pointed at a local checkout, is a real mode — `main` is
    the whole truth there. Warning about it put a red-looking line in the deploy gate's output on
    every green run, and a gate whose warnings are always present is a gate nobody reads."""
    import logging
    b = ClaudeCodeBuilder(str(repo), session_factory=lambda **k: None, test_cmd="true")
    with caplog.at_level(logging.WARNING, logger="fls.builders"):
        assert b.base_ref() == "main"
    assert not caplog.records, f"warned about a repo that simply has no remote: {caplog.text}"


def test_the_pull_request_number_survives_into_the_facts_rung_5_reads(tmp_path):
    """FOUND ON EXPEDITION 32. Rung 4 opened PR #8 and marked it ready; the facts written to disk
    kept the URL and dropped the NUMBER, so rung 5 — which runs as its own activity holding
    nothing but an expedition number — would have answered "there is no pull request to merge"
    about a pull request that was sitting there, mergeable.

    Same shape as expedition 22: rung 4 writes one thing, rung 5 reads another, each correct
    alone. A reducer is a seam like any other.
    """
    from fls.store import artifact_facts_from
    facts = artifact_facts_from({"ship": {
        "pr_url": "https://github.com/o/r/pull/8", "pr_number": 8, "branch": "exp-32",
        "flag": "four-colour-deck", "ready_for_review": True}})
    assert facts["pull_request"].endswith("/pull/8")
    assert facts["ship"]["pr_number"] == 8, "rung 5 cannot merge what it cannot address"
    assert facts["ship"]["flag"] == "four-colour-deck"


def test_a_build_that_opened_nothing_records_no_ship_facts(tmp_path):
    """An instance with no code host must not leave a `ship` block that looks like a pull request
    exists — rung 5 would then try to merge nothing."""
    from fls.store import artifact_facts_from
    assert "ship" not in artifact_facts_from({"build": {"files_changed": ["a"], "lines_changed": 3}})

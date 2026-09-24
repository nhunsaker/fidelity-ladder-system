"""Build hands back something you can open; Ship means merged.

The card used to read "2 file(s), 36 changed lines, check green" after the most expensive rung on
the ladder — a receipt, not a deliverable. The last thing a visitor could actually OPEN was the
rung-3 preview, which is a prototype from the design pack rather than their change. And "Ship"
meant a draft pull request existed, which is not shipping.

Build now ends at a pull request marked READY FOR REVIEW, which is the event the harness's own
webhook already listens for: checks go green, the branch is built, the change lands on stage.
Ship merges it.
"""
from __future__ import annotations

import pytest

from fls.builders.ship import PullRequestShipper


class FakeGitHub:
    """Records calls; answers from a script. No network, and no mock at the seam that matters."""

    def __init__(self, pr=None, merge=None):
        self.pr = pr or {"number": 6, "node_id": "PR_abc", "draft": True, "mergeable": True}
        self.merge_reply = merge if merge is not None else {"merged": True}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/merge"):
            return self.merge_reply
        return self.pr


def _ship(gh, graphql=None):
    return PullRequestShipper("/tmp/x", token="t", slug="o/r", api=gh,
                              graphql=graphql or (lambda q, v: {"data": {}}))


# ── ready for review: the act that produces the deliverable ────────────────────────────────

def test_marking_ready_is_what_puts_the_change_on_stage():
    """Until this happens the rung has produced a diff and nothing a person can open. It is also
    the only one of these that REST cannot do — draft state lives on GraphQL."""
    seen = {}

    def graphql(q, v):
        seen["query"], seen["vars"] = q, v
        return {"data": {"markPullRequestReadyForReview": {"pullRequest": {"isDraft": False}}}}

    ok, why = _ship(FakeGitHub(), graphql).mark_ready(6)
    assert ok and "ready" in why
    assert "markPullRequestReadyForReview" in seen["query"]
    assert seen["vars"] == {"id": "PR_abc"}


def test_a_pull_request_already_out_of_draft_reports_success():
    """A retry must not fail on work that is already done."""
    ok, why = _ship(FakeGitHub(pr={"number": 6, "node_id": "x", "draft": False})).mark_ready(6)
    assert ok and "already" in why


def test_a_graphql_refusal_is_reported_not_swallowed():
    ok, why = _ship(FakeGitHub(), lambda q, v: {"errors": [{"message": "insufficient scope"}]}
                    ).mark_ready(6)
    assert ok is False and "insufficient scope" in why


# ── ship means merged ──────────────────────────────────────────────────────────────────────

def test_ship_merges():
    gh = FakeGitHub(pr={"number": 6, "node_id": "x", "draft": False, "mergeable": True})
    ok, why = _ship(gh).merge(6)
    assert ok and "merged into main" in why
    assert any(m == "PUT" and p.endswith("/merge") for m, p, _ in gh.calls)


def test_a_conflicting_branch_is_refused_with_the_reason():
    """PR #7 conflicts with main right now. "could not merge: this branch has conflicts" is a far
    better last line than a silent success, and it tells the person the next step."""
    gh = FakeGitHub(pr={"number": 7, "node_id": "x", "draft": False, "mergeable": False})
    ok, why = _ship(gh).merge(7)
    assert ok is False and "conflicts" in why and "rebasing" in why
    assert not any(p.endswith("/merge") for _, p, _ in gh.calls), "it tried to merge anyway"


def test_a_draft_is_never_merged():
    """A draft was never made ready, so it was never staged, so nobody has reviewed it."""
    gh = FakeGitHub(pr={"number": 6, "node_id": "x", "draft": True})
    ok, why = _ship(gh).merge(6)
    assert ok is False and "still a draft" in why
    assert not any(p.endswith("/merge") for _, p, _ in gh.calls)


def test_an_already_merged_pull_request_is_not_merged_twice():
    gh = FakeGitHub(pr={"number": 6, "node_id": "x", "draft": False, "merged": True})
    ok, why = _ship(gh).merge(6)
    assert ok and "already merged" in why
    assert not any(p.endswith("/merge") for _, p, _ in gh.calls)


def test_a_refused_merge_says_what_github_said():
    gh = FakeGitHub(pr={"number": 6, "node_id": "x", "draft": False, "mergeable": True},
                    merge={"merged": False, "message": "Required status check is expected"})
    ok, why = _ship(gh).merge(6)
    assert ok is False and "Required status check" in why


# ── the rungs ──────────────────────────────────────────────────────────────────────────────

def _vessel(root):
    """rung 4 refuses a vessel that is not a git checkout, before it does anything else."""
    import subprocess
    v = root / "vessel"
    v.mkdir(parents=True, exist_ok=True)
    for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
              ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=str(v), capture_output=True, check=False)
    (v / "README.md").write_text("v\n")
    subprocess.run(["git", "add", "-A"], cwd=str(v), capture_output=True, check=False)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=str(v), capture_output=True, check=False)
    return v


@pytest.fixture
def runner(tmp_path):
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    return LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(5,))


def test_ship_refuses_when_the_build_was_never_green(runner, tmp_path):
    import json
    art = tmp_path / "expeditions" / "7" / "mvp"
    art.mkdir(parents=True)
    (art / "summary.json").write_text(json.dumps({"test_passed": False, "branch": "exp-7"}))
    from fls.orchestration.types import RungRequest
    r = runner.ship(RungRequest(number=7, rung=5, intent="i"))
    assert r.passed is False and "not green" in r.detail


def test_ship_refuses_when_the_build_opened_no_pull_request(runner, tmp_path):
    """An instance with no code host builds but publishes nothing. There is genuinely nothing to
    merge, and saying that is better than a merge call against a number nobody has."""
    import json
    art = tmp_path / "expeditions" / "7" / "mvp"
    art.mkdir(parents=True)
    (art / "summary.json").write_text(json.dumps({"test_passed": True, "branch": "exp-7"}))
    from fls.orchestration.types import RungRequest
    r = runner.ship(RungRequest(number=7, rung=5, intent="i"))
    assert r.passed is False and "no pull request to merge" in r.detail


def test_rung_4_marks_the_pull_request_ready_so_it_reaches_stage(tmp_path, monkeypatch):
    """THE WIRING, not the capability — `mark_ready` can be perfect and never called, which is
    exactly what a mutation proved: removing the call from rung 4 left every other test green.

    Marking ready is the whole point of the remap. It is the event `github_surface._stage_if_green`
    listens for, and without it the change never reaches stage and Build is a receipt again.
    """
    from fls.builders.claude_code_builder import BuildResult
    from fls.builders.ship import ShipOutcome
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    seen = {}

    class Ship:
        token = "t"

        def ship(self, *a, **k):
            return ShipOutcome(True, pr_url="https://gh/pr/6", pr_number=6, branch="exp-7",
                               slug="o/r", pushed=True, flag="four-colour-deck")

        def mark_ready(self, number):
            seen["ready"] = number
            return True, "ready for review"

    wt = tmp_path / "expeditions" / "7" / "mvp" / "wt"
    wt.mkdir(parents=True)
    vessel = _vessel(tmp_path)
    r = LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(4,),
                   vessel_repo=str(vessel), vessel_test_cmd="true")
    monkeypatch.setattr(r, "_shipper", lambda: Ship())
    monkeypatch.setattr(r, "_package", lambda req, res: None)
    monkeypatch.setattr(
        "fls.orchestration.live.ClaudeCodeBuilder",
        lambda *a, **k: type("B", (), {"build": lambda self, *a, **k: BuildResult(
            True, branch="exp-7", worktree=str(wt), detail="2 files, 36 lines, check green",
            test_passed=True)})())

    out = r.build(RungRequest(number=7, rung=4, intent="i", spec="s"))
    assert out.passed and out.state == "await-approve", out.detail
    assert seen.get("ready") == 6, "rung 4 opened a pull request and left it a draft"
    assert out.artifacts["ship"]["ready_for_review"] is True
    assert "ready for review" in out.detail


def test_a_build_with_no_code_host_still_passes_and_says_so(tmp_path, monkeypatch):
    """Local-mode is the fresh-install default. There the build IS the whole deliverable, and
    parking it would fail every install that never asked for GitHub. Degrade honestly, never
    pretend — the same rule the thread mirror follows."""
    from fls.builders.claude_code_builder import BuildResult
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    wt = tmp_path / "expeditions" / "7" / "mvp" / "wt"
    wt.mkdir(parents=True)
    vessel = _vessel(tmp_path)
    r = LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(4,),
                   vessel_repo=str(vessel), vessel_test_cmd="true")
    monkeypatch.setattr(r, "_shipper", lambda: type("S", (), {"token": ""})())
    monkeypatch.setattr(
        "fls.orchestration.live.ClaudeCodeBuilder",
        lambda *a, **k: type("B", (), {"build": lambda self, *a, **k: BuildResult(
            True, branch="exp-7", worktree=str(wt), detail="built", test_passed=True)})())

    out = r.build(RungRequest(number=7, rung=4, intent="i", spec="s"))
    assert out.passed is True
    assert "no code host configured" in out.detail
    assert out.artifacts["ship"]["no_outbound"] is True


# ── the link is the deliverable ────────────────────────────────────────────────────────────

def test_the_stage_link_carries_the_flag_already_on():
    """THE DETAIL THAT MATTERS MOST. Every change ships behind a flag that is off, so a bare stage
    link shows the app looking exactly as before and the visitor concludes nothing happened. That
    is not hypothetical — it happened here, and `_staged_comment` has carried the warning since.

    One click has to show the change, or the deliverable is worse than no link at all.
    """
    from fls.github_surface import _record_stage

    saved = {}

    class Store:
        def save_artifact_facts(self, n, facts):
            saved[n] = facts

    _record_stage(Store(), {"head": {"ref": "exp-26"}}, "https://stage.example.com",
                  "four-colour-deck")
    assert saved[26]["stage"]["url"] == \
        "https://stage.example.com?flags-four-colour-deck=true"
    assert saved[26]["stage"]["plain_url"] == "https://stage.example.com"


def test_a_change_with_no_single_flag_still_gets_a_link():
    """Two flags in one change leaves nothing honest to name, but the build is still on stage and
    the link is still worth having."""
    from fls.github_surface import _record_stage
    saved = {}

    class Store:
        def save_artifact_facts(self, n, facts):
            saved[n] = facts

    _record_stage(Store(), {"head": {"ref": "exp-9"}}, "https://s.example.com", "")
    assert saved[9]["stage"]["url"] == "https://s.example.com"


def test_a_branch_that_is_not_an_expedition_records_nothing():
    """Somebody's hand-made branch is not an expedition, and writing facts against expedition 0
    would put a stage link on a run that never asked for one."""
    from fls.github_surface import _record_stage
    saved = {}

    class Store:
        def save_artifact_facts(self, n, facts):
            saved[n] = facts

    _record_stage(Store(), {"head": {"ref": "dependabot/npm/lodash"}}, "https://s", "f")
    assert saved == {}


def test_the_visitor_sees_the_link():
    from fls.demo import demo_view
    rec = {"number": 26, "intent": "four colour deck", "rung": "4-mvp", "status": "await-approve",
           "source": "demo:n", "spent": 0.0, "normalized_usd": 0.0}
    wf = {"running": False, "artifacts": {
        "stage": {"url": "https://stage.example.com?flags-four-colour-deck=true",
                  "plain_url": "https://stage.example.com", "flag": "four-colour-deck"}}}
    v = demo_view(rec, wf)
    assert v["artifacts"]["stage_url"].endswith("?flags-four-colour-deck=true")
    assert v["artifacts"]["stage_flag"] == "four-colour-deck"


def test_the_five_promises_describe_what_is_handed_back():
    """The left rail is what a visitor reads BEFORE anything runs, so it is the promise the ladder
    is held to. Two of them described work done rather than a thing handed back — and one of them,
    "a pull request a person can review", was not true after the remap anyway."""
    from fls.demo import STAGE_NOTES, STAGES
    assert len(STAGE_NOTES) == len(STAGES) == 5
    assert "running where you can try it" in STAGE_NOTES[3], "Build still promises a receipt"
    assert "Merged" in STAGE_NOTES[4], "Ship still promises a draft pull request"


def test_the_client_fallback_says_the_same_thing_as_the_engine():
    """The client carries a copy for the empty state, and a copy that drifts is how the sign-in
    page ended up promising REQUESTED · WIREFRAMED · PREVIEWED long after those names were gone."""
    import re
    from pathlib import Path

    from fls.demo import STAGE_NOTES
    src = (Path(__file__).resolve().parents[2] / "admin" / "src" / "sections" / "Demo.jsx") \
        .read_text(encoding="utf-8")
    block = re.search(r"const NOTE_FALLBACK = \[(.*?)\]", src, re.S)
    assert block, "NOTE_FALLBACK is gone; this guard needs rewriting rather than deleting"
    for note in STAGE_NOTES:
        assert note in block.group(1), f"the client's copy has drifted from the engine: {note!r}"


# ── a concluded run does not hold the door shut ────────────────────────────────────────────

@pytest.mark.anyio
async def test_a_finished_workflow_does_not_block_the_next_request(tmp_path, monkeypatch):
    """EXPEDITION 31. The spec rung refused a vague request and told the person to say what should
    change — then held the request box shut against them, because `needs-human` is not terminal.

    It is not terminal for a good reason: a person really does have something to add. What was
    missing is the rule `_demo_in_flight`'s own docstring already claimed — the WORKFLOW decides,
    not the record. A finished workflow answers happily from history with `running: False`, and
    that was being read as "still going".
    """
    from fls import app as appmod
    from fls.adjudicator import Idea
    from fls.expedition import Expedition
    from fls.store import ExpeditionStore

    store = ExpeditionStore(tmp_path)
    store.save(Expedition(31, Idea(31, "make it better", "", "feature", source="demo:n"), 4,
                          rung=1, status="needs-human"))
    appmod.deps.root, appmod.deps._store = tmp_path, store
    monkeypatch.setattr("fls.orchestration.client.enabled", lambda: True)

    async def status(number, settings=None):
        return {"number": number, "running": False, "state": "needs-human"}

    monkeypatch.setattr("fls.orchestration.client.status", status)
    # The question the REQUEST BOX asks, not the one the display asks. `_demo_in_flight` still
    # returns the run so the page can show it as finished; what changed is that filing is no
    # longer refused because of it.
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FLS_DEMO_PASSCODE", "open-sesame")
    c = TestClient(appmod.app)
    tok = c.post("/v1/visitor/login",
                 json={"name": "V", "passcode": "open-sesame"}).json()["token"]
    r = c.post("/v1/visitor/requests", json={"intent": "a new one", "success": "s"},
               headers={"x-demo-token": tok})
    assert r.status_code != 409, \
        f"a concluded refusal still held the request box shut: {r.text[:160]}"


@pytest.mark.anyio
async def test_a_run_waiting_at_a_gate_is_still_in_flight(tmp_path, monkeypatch):
    """The other half, and the reason this cannot simply treat needs-human as terminal: a run
    parked at a pick gate has a LIVE workflow blocked on a signal. Letting a second request in
    then would start two runs against one budget."""
    from fls import app as appmod
    from fls.adjudicator import Idea
    from fls.expedition import Expedition
    from fls.store import ExpeditionStore

    store = ExpeditionStore(tmp_path)
    store.save(Expedition(32, Idea(32, "a share sheet", "", "feature", source="demo:n"), 4,
                          rung=2, status="await-pick"))
    appmod.deps.root, appmod.deps._store = tmp_path, store
    monkeypatch.setattr("fls.orchestration.client.enabled", lambda: True)

    async def status(number, settings=None):
        return {"number": number, "running": True, "state": "await-pick"}

    monkeypatch.setattr("fls.orchestration.client.status", status)
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FLS_DEMO_PASSCODE", "open-sesame")
    c = TestClient(appmod.app)
    tok = c.post("/v1/visitor/login",
                 json={"name": "V", "passcode": "open-sesame"}).json()["token"]
    r = c.post("/v1/visitor/requests", json={"intent": "a second one", "success": "s"},
               headers={"x-demo-token": tok})
    assert r.status_code == 409, "a live run at a gate must still hold the one-at-a-time rule"


def test_ship_finds_the_pull_request_by_branch_when_the_record_lost_it(tmp_path, monkeypatch):
    """EXPEDITION 32, and the reason a retry could not rescue it. Rung 4 opened PR #8 and marked
    it ready; the facts reducer of that moment kept the URL and dropped the number, so this rung
    announced "the build did not open one" about a pull request that was open, ready and
    mergeable — and re-running it read the same stale file and said the same thing.

    Reading the record was never the only way to answer. The branch is `exp-{n}`, assigned before
    any work started, so the code host can simply be ASKED.
    """
    import json

    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    art = tmp_path / "expeditions" / "32" / "mvp"
    art.mkdir(parents=True)
    (art / "summary.json").write_text(json.dumps({"test_passed": True, "branch": "exp-32"}))
    # The record exactly as expedition 32 had it: a URL, and no number anywhere.
    (tmp_path / "expeditions" / "32" / "artifacts.json").write_text(
        json.dumps({"pull_request": "https://github.com/o/r/pull/8"}))

    asked = {}

    class Ship:
        token = "t"

        def existing_pr(self, branch):
            asked["branch"] = branch
            return {"number": 8}

        def merge(self, number, method="squash"):
            asked["merged"] = number
            return True, "merged into main"

    r = LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(5,))
    monkeypatch.setattr(r, "_shipper", lambda: Ship())
    out = r.ship(RungRequest(number=32, rung=5, intent="four colour deck"))
    assert asked["branch"] == "exp-32"
    assert asked.get("merged") == 8, "it had the branch and still refused to look"
    assert out.passed and out.state == "done"


def test_ship_still_refuses_when_there_really_is_no_pull_request(tmp_path, monkeypatch):
    """Asking the host is a fallback, not a way to invent one. An instance with no code host, or a
    branch nobody pushed, still has nothing to merge."""
    import json

    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    art = tmp_path / "expeditions" / "9" / "mvp"
    art.mkdir(parents=True)
    (art / "summary.json").write_text(json.dumps({"test_passed": True, "branch": "exp-9"}))
    r = LiveRunner(None, StubRunner(), root=tmp_path, live_rungs=(5,))
    monkeypatch.setattr(r, "_shipper",
                        lambda: type("S", (), {"token": "t",
                                               "existing_pr": lambda self, b: {}})())
    out = r.ship(RungRequest(number=9, rung=5, intent="i"))
    assert out.passed is False and "no pull request to merge" in out.detail


# ── machinery has a shape, not only a vocabulary ────────────────────────────────────────────

def test_a_selector_dump_does_not_reach_a_visitor():
    """EXPEDITION 34. Rung 3's lint refused with a list of CSS selectors, and every word of it
    cleared the `_INTERNAL` wordlist — so the entire explanation a visitor got was

        walkthrough step 8 targets '#sc-uncalled', which is not in the page; …

    A denylist of words cannot be completed. This is the shape half of the same guard.
    """
    from fls.demo import visitor_detail

    leak = ("walkthrough step 8 targets '#sc-uncalled', which is not in the page; walkthrough "
            "step 9 targets '#sc-split', which is not in the page")
    assert "#sc-uncalled" not in visitor_detail(leak, blocked=True)
    assert "#sc-split" not in visitor_detail(leak, blocked=False)


def test_the_shape_guard_does_not_eat_ordinary_sentences():
    """The guard must never swallow a sentence a visitor was supposed to read. These are the real
    lines the surface sends, and every one of them has to survive untouched."""
    from fls.demo import visitor_detail

    for ok in (
        "This needs a bit more detail before it can start.",
        "Three rough shapes — you pick one.",
        "It stopped before finishing. Whatever it had already made is still below.",
        "The step it was on stopped before it finished, so the run is not going any further.",
        "Merged into the project, still switched off",
    ):
        assert visitor_detail(ok, blocked=False) == ok, f"guard ate a good sentence: {ok!r}"


def test_shapes_that_are_only_ever_written_for_an_operator():
    from fls.demo import looks_like_machinery

    for machinery in ("'#sc-fold'", '".seat-plate"', "fls.orchestration timed out",
                      "see builders/ship.py", "failed at line 214",
                      "walkthrough step 12 targets '#x'"):
        assert looks_like_machinery(machinery), f"should have been caught: {machinery!r}"
    for fine in ("It stopped before finishing.", "You have spent $2.35 so far.",
                 "Pick the one you want built.", "step 2 of 5"):
        assert not looks_like_machinery(fine), f"false positive: {fine!r}"

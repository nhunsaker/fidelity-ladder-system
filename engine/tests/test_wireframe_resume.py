"""A retry finds the work the last attempt left, instead of paying for it twice.

Expedition 18 died three times on rung 2 and recorded `artifacts: {}` — no page, no node ids,
nothing to come back to. The identity it needed had to be ASSIGNED before the work started rather
than read back off a contract the session never lived to declare.

Two identifiers doing two jobs, and both are needed:

* the **page id** says WHERE — one addressed call. Listing a document's pages is not an option:
  it returns what the client happens to have loaded, and answered "one page" against a file
  holding eight.
* the **slug** says WHICH — a page holds several frames, and "is candidate 2 already built?" is
  unanswerable against names the session chose for itself.

Proven on the real path before any of this was written (see the plan's Gate A): a fresh session
given only a page id read the page, listed the frame its predecessor had made, and added a second
one without creating a duplicate page.
"""
from __future__ import annotations

import pytest

from fls.builders.figma_wireframe import (
    FigmaWireframeBuilder,
    Resume,
    candidate_slug,
    page_id_from_log,
    page_slug,
)


class FakeSession:
    timeout_s = 600

    def __init__(self, text):
        self.text, self.prompt = text, None

    def run(self, prompt, system=None):
        self.prompt = prompt
        from fls.llm import Call
        class R:  # noqa: E306
            pass
        r = R()
        r.text, r.timed_out = self.text, False
        r.call = Call("claude-code", "m", 0, 0, usd=0.0, normalized_usd=0.0)
        return r


def _builder(text):
    return FigmaWireframeBuilder(file_key="K", session=FakeSession(text), n=3)


def _contract(page_id="12:0", names=("exp-7-c1", "exp-7-c2", "exp-7-c3")):
    cands = ", ".join(
        f'{{"name": "{n}", "node_id": "12:{i}", "title": "T{i}", "premise": "P{i}"}}'
        for i, n in enumerate(names, 1))
    return ('```json\n{"page_name": "exp-7", "page_id": "' + page_id + '", "lint": '
            '{"auto_layout": true, "named_layers": true, "detached_instances": false}, '
            '"candidates": [' + cands + ']}\n```')


# ── identity is assigned, not discovered ───────────────────────────────────────────────────

def test_the_slugs_are_derived_from_the_expedition_alone():
    """A retry computes these without reading anything — which is the point, because the thing it
    would read is what the dead session failed to write."""
    assert page_slug(18) == "exp-18"
    assert [candidate_slug(18, i) for i in (1, 2, 3)] == ["exp-18-c1", "exp-18-c2", "exp-18-c3"]


def test_the_page_id_is_recovered_from_a_killed_sessions_log():
    """The sentinel is printed the moment the page exists and before anything is drawn, so it is
    on disk even when the session is cancelled minutes later."""
    log = "some chatter\nFLS-PAGE: exp-18 13:2\nmore work...\n"
    assert page_id_from_log(log, 18) == "13:2"


def test_a_sentinel_for_a_different_expedition_is_refused():
    """FAIL-CLOSED. Adopting another run's page would point expedition 19's retry at expedition
    18's work, and the damage would look exactly like the feature working."""
    assert page_id_from_log("FLS-PAGE: exp-18 13:2\n", 19) == ""


def test_no_sentinel_means_no_page_and_that_is_said_by_returning_nothing():
    """A session killed before it made the page left nothing to find. That window is real and it
    is benign — there is no work in it to recover."""
    assert page_id_from_log("it never got that far", 18) == ""


# ── what the retry asks for ────────────────────────────────────────────────────────────────

def test_a_first_attempt_is_told_to_print_the_sentinel():
    b = _builder(_contract())
    p = b.prompt(7, "a share sheet")
    assert "FLS-PAGE: exp-7 <the page id>" in p
    assert "BEFORE you draw anything" in p


def test_a_retry_addresses_the_page_and_is_told_not_to_make_another():
    b = _builder(_contract())
    p = b.prompt(7, "a share sheet", resume=Resume(page_id="13:2"))
    assert "`13:2`" in p and "Do not create a new page" in p


def test_a_retry_keeps_what_stands_and_rebuilds_only_the_rest():
    """THE WHOLE POINT. A rung that died at minute 9 of 20 should not pay for minutes 1-9 again."""
    b = _builder(_contract())
    p = b.prompt(7, "a share sheet", resume=Resume(
        page_id="13:2", keep={"exp-7-c1": "13:6"},
        redo={"exp-7-c2": "frames are not on auto-layout"}, missing=("exp-7-c3",)))
    assert "leave these exactly as they are" in p and "exp-7-c1" in p
    assert "delete and rebuild" in p and "not on auto-layout" in p
    assert "STILL TO BUILD: exp-7-c3" in p


def test_leftovers_are_never_presented_as_the_humans_feedback():
    """`feedback` means A HUMAN ASKED FOR CHANGES, and the prompt leans on that sentence hard.
    Machine-observed debris in that slot would have the session reading its own wreckage as the
    founder's critique — so a resume with no human feedback must not trip it."""
    b = _builder(_contract())
    p = b.prompt(7, "a share sheet", resume=Resume(page_id="13:2", missing=("exp-7-c3",)))
    assert "THE HUMAN REVIEWED YOUR LAST ATTEMPT" not in p


def test_a_human_revision_still_reads_as_one_during_a_retry():
    """And the two inputs coexist: a run can be both resumed and revised."""
    b = _builder(_contract())
    p = b.prompt(7, "a share sheet", feedback="make it quieter",
                 resume=Resume(page_id="13:2", missing=("exp-7-c3",)))
    assert "THE HUMAN REVIEWED YOUR LAST ATTEMPT" in p and "make it quieter" in p
    assert "STILL TO BUILD" in p


# ── the drift check ────────────────────────────────────────────────────────────────────────

def test_a_session_that_makes_a_second_page_fails_the_rung():
    """FAIL-CLOSED, and the failure it prevents is silent: two pages leave neither findable, and
    every later attempt stacks another set of candidates onto one of them."""
    b = _builder(_contract(page_id="99:0"))
    r = b.build(7, "a share sheet", resume=Resume(page_id="13:2"))
    assert r.passed is False
    assert "13:2" in r.detail and "99:0" in r.detail


def test_the_page_it_was_given_is_accepted():
    b = _builder(_contract(page_id="13:2"))
    assert b.build(7, "a share sheet", resume=Resume(page_id="13:2")).passed is True


@pytest.mark.parametrize("names", [
    ("candidate-1", "candidate-2", "candidate-3"),          # the old free-text convention
    ("exp-7-c1", "exp-7-c2", "screen-three"),               # one frame off-contract
])
def test_frames_not_named_for_their_candidate_fail_the_rung(names):
    """Without the prefix a later attempt cannot tell which frame is which candidate, so the
    resume mechanism silently degrades to a full rebuild. Better to fail while someone is looking.
    """
    r = _builder(_contract(names=names)).build(7, "a share sheet")
    assert r.passed is False and "cannot match to a candidate" in r.detail


def test_a_frame_may_say_more_after_its_prefix():
    """The slug is a prefix, not the whole name — `exp-7-c1-avatar-anchored` is how expedition 17
    named things and it is genuinely useful to a reader."""
    r = _builder(_contract(names=("exp-7-c1-modal", "exp-7-c2-inline", "exp-7-c3-screen"))).build(
        7, "a share sheet")
    assert r.passed is True


# ── the wiring: rung 2 must actually use all of this ───────────────────────────────────────

def test_rung2_streams_its_log_per_attempt_and_resumes_from_the_last_one(tmp_path, monkeypatch):
    """The capability above is worth nothing if the rung never calls it.

    Attempt 1 is given a log path and no resume. Attempt 2 finds attempt 1's sentinel on disk and
    is handed the page — which is the entire feature, end to end, in the one place it has to work.
    """
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    seen = {}

    class Builder:
        def __init__(self, *a, **k):
            pass

        def build(self, number, spec, feedback="", budget_chars=6000, artifact_dir=None,
                  resume=None, log_path=None):
            seen["resume"], seen["log_path"] = resume, log_path
            from fls.builders.figma_wireframe import FigmaWireframeResult
            return FigmaWireframeResult(True, detail="ok")

    monkeypatch.setattr("fls.orchestration.live.FigmaWireframeBuilder", Builder)
    r = LiveRunner(None, StubRunner(), root=tmp_path, figma_file_key="K", live_rungs=(2,))

    # Attempt 1: nothing to resume from, and a log of its own.
    r.wireframe(RungRequest(number=7, rung=2, intent="a share sheet", spec="s", attempt=1))
    assert seen["resume"] is None, "a first attempt has nothing to resume and must not pretend"
    assert seen["log_path"].endswith("wireframes/session-1.log")

    # That attempt dies here, having printed its sentinel. Only the log survives.
    log = tmp_path / "expeditions" / "7" / "wireframes" / "session-1.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("working...\nFLS-PAGE: exp-7 13:2\ndrawing c1...\n")

    # Attempt 2: finds it.
    r.wireframe(RungRequest(number=7, rung=2, intent="a share sheet", spec="s", attempt=2))
    assert seen["resume"] is not None and seen["resume"].page_id == "13:2", \
        "the retry did not find the page the dead attempt left behind"
    assert seen["log_path"].endswith("wireframes/session-2.log"), \
        "attempt 2 overwrote attempt 1's log — the only record of where the work is"


def test_a_log_from_another_expedition_is_not_adopted(tmp_path, monkeypatch):
    """Fail-closed at the wiring level too, not only in the parser."""
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    seen = {}

    class Builder:
        def __init__(self, *a, **k):
            pass

        def build(self, number, spec, feedback="", budget_chars=6000, artifact_dir=None,
                  resume=None, log_path=None):
            seen["resume"] = resume
            from fls.builders.figma_wireframe import FigmaWireframeResult
            return FigmaWireframeResult(True, detail="ok")

    monkeypatch.setattr("fls.orchestration.live.FigmaWireframeBuilder", Builder)
    log = tmp_path / "expeditions" / "7" / "wireframes" / "session-1.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("FLS-PAGE: exp-99 13:2\n")
    LiveRunner(None, StubRunner(), root=tmp_path, figma_file_key="K",
               live_rungs=(2,)).wireframe(
        RungRequest(number=7, rung=2, intent="i", spec="s", attempt=2))
    assert seen["resume"] is None


def test_a_second_attempt_never_overwrites_the_first_ones_log(tmp_path, monkeypatch):
    """FOUND LIVE ON EXPEDITION 20. The log name came from `req.attempt`, which is the WORKFLOW's
    counter — and Temporal retries inside a single activity call, so it stays 1 while the activity
    runs again. Attempt 2 therefore wrote over the only record of where the work was.

    It survived only because the read happens before the write. A third attempt would have read an
    empty cupboard, and the page would have been abandoned with everything on it.
    """
    from fls.orchestration.activities import StubRunner
    from fls.orchestration.live import LiveRunner
    from fls.orchestration.types import RungRequest

    seen = []

    class Builder:
        def __init__(self, *a, **k):
            pass

        def build(self, number, spec, feedback="", budget_chars=6000, artifact_dir=None,
                  resume=None, log_path=None):
            seen.append(log_path)
            from fls.builders.figma_wireframe import FigmaWireframeResult
            pathlib_write(log_path)
            return FigmaWireframeResult(True, detail="ok")

    def pathlib_write(p):
        from pathlib import Path
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text("FLS-PAGE: exp-7 13:2\n")

    monkeypatch.setattr("fls.orchestration.live.FigmaWireframeBuilder", Builder)
    r = LiveRunner(None, StubRunner(), root=tmp_path, figma_file_key="K", live_rungs=(2,))
    # Temporal reports the SAME attempt number for all three, which is the trap.
    for _ in range(3):
        r.wireframe(RungRequest(number=7, rung=2, intent="i", spec="s", attempt=1))
    assert len({*seen}) == 3, f"attempts shared a log file: {seen}"
    assert seen[-1].endswith("session-3.log")


def test_a_resumed_attempt_re_announces_the_page():
    """FOUND LIVE ON EXPEDITION 20. The resume branch never asked for the sentinel, so a recovered
    attempt wrote none — and the chain broke after exactly one hop. An attempt is not the last one
    that can fail."""
    b = _builder(_contract(page_id="13:2"))
    p = b.prompt(7, "a share sheet", resume=Resume(page_id="13:2"))
    assert "FLS-PAGE: exp-7 13:2" in p


# ── misnamed is not wrong: the repair is a rename, not a redraw ─────────────────────────────

def test_a_rung_that_failed_only_on_names_is_repaired_by_renaming(tmp_path):
    """EXPEDITION 21. The system prompt's own output example showed `"name": "candidate-1"`, so
    the session used it, and the lint I had just added rejected the rung for it — three sound
    candidates thrown away over a label the instructions were simultaneously teaching.

    The contradiction is gone, but the repair matters more: the drawings exist and their node ids
    are on disk, so the fix is seconds of renaming rather than minutes of redrawing.
    """
    import json

    from fls.orchestration.live import _misnamed
    d = tmp_path / "figma.json"
    d.write_text(json.dumps({"page_id": "21:2", "candidates": [
        {"name": "candidate-1", "node_id": "21:4"},
        {"name": "candidate-2", "node_id": "21:22"},
        {"name": "candidate-3", "node_id": "21:39"}]}))
    assert _misnamed(d, 21) == {"21:4": "exp-21-c1", "21:22": "exp-21-c2", "21:39": "exp-21-c3"}


def test_correctly_named_frames_are_not_renamed(tmp_path):
    import json

    from fls.orchestration.live import _misnamed
    d = tmp_path / "figma.json"
    d.write_text(json.dumps({"candidates": [
        {"name": "exp-21-c1-strip", "node_id": "21:4"}]}))
    assert _misnamed(d, 21) == {}


def test_a_frame_with_no_node_id_cannot_be_renamed_and_is_left_to_rebuild(tmp_path):
    """Nothing to address means nothing to repair. Claiming otherwise would send the session
    looking for a frame that may not exist."""
    import json

    from fls.orchestration.live import _misnamed
    d = tmp_path / "figma.json"
    d.write_text(json.dumps({"candidates": [{"name": "candidate-1", "node_id": ""}]}))
    assert _misnamed(d, 21) == {}


def test_no_prior_contract_is_not_an_error(tmp_path):
    from fls.orchestration.live import _misnamed
    assert _misnamed(tmp_path / "nope.json", 21) == {}


def test_the_retry_is_told_to_rename_in_place():
    b = _builder(_contract())
    p = b.prompt(21, "a share sheet",
                 resume=Resume(page_id="21:2", rename={"21:4": "exp-21-c1"}))
    assert "RENAME them in place" in p and "do not redraw" in p and "21:4" in p


def test_the_system_prompt_no_longer_teaches_a_name_the_lint_rejects():
    """THE ROOT CAUSE. The strongest instruction in the session — its system prompt — contained
    the exact name that fails the rung. A guard that contradicts the instructions it guards is a
    trap, not a check."""
    from fls.builders.figma_wireframe import _SYSTEM
    assert '"candidate-1"' not in _SYSTEM
    assert "not yours to choose" in _SYSTEM


def test_the_slug_never_reaches_the_person_choosing():
    """FOUND LIVE ON EXPEDITION 23. The session put the slug in the title as well as the name, so
    the demo card offered a choice between "exp-23-c1 — One row…" and "exp-23-c2 — Two tiers…".

    The visitor surface's first rule is that the machinery never reaches it. The prompt now says
    name and title are different things — and this strips it anyway, because an instruction to a
    model is a request and this is a guarantee.
    """
    from fls.builders.figma_wireframe import clean_title
    assert clean_title("exp-23-c1 — One row: Fold hand inline", "exp-23-c1") == \
        "One row: Fold hand inline"
    assert clean_title("exp-23-c2: Two tiers", "exp-23-c2") == "Two tiers"
    # A title that never carried the slug is untouched, and the strip is idempotent.
    assert clean_title("One row: Fold hand inline", "exp-23-c1") == "One row: Fold hand inline"
    assert clean_title("", "exp-23-c1") == ""


def test_a_cleaned_title_reaches_the_candidate(tmp_path):
    """The wiring, not the helper — the same trap as rung 2 and rung 4."""
    b = _builder(
        '```json\n{"page_name": "exp-7", "page_id": "1:0", "lint": {"auto_layout": true, '
        '"named_layers": true, "detached_instances": false}, "candidates": ['
        '{"name": "exp-7-c1", "node_id": "1:1", "title": "exp-7-c1 — A modal", "premise": "p"},'
        '{"name": "exp-7-c2", "node_id": "1:2", "title": "exp-7-c2 — Inline", "premise": "p"},'
        '{"name": "exp-7-c3", "node_id": "1:3", "title": "exp-7-c3 — A screen", "premise": "p"}'
        ']}\n```')
    r = b.build(7, "a share sheet")
    assert r.passed, r.detail
    assert [c.title for c in r.candidates] == ["A modal", "Inline", "A screen"]


# ── a rung that can decline ────────────────────────────────────────────────────────────────

def _one_candidate(why=""):
    reason = f'"fewer_because": "{why}", ' if why else ""
    return ('```json\n{"page_name": "exp-7", "page_id": "1:0", ' + reason
            + '"lint": {"auto_layout": true, "named_layers": true, "detached_instances": false}, '
              '"candidates": [{"name": "exp-7-c1", "node_id": "1:1", "title": "The only shape", '
              '"premise": "there is one sensible arrangement here"}]}\n```')


def test_one_honest_candidate_beats_three_invented_ones():
    """EXPEDITION 28. The request asked for TESTS and this rung drew three wireframes of a
    test-viewer UI — a case list, a split view, a coverage grid, none of them requested. It had no
    way to say "there is nothing to draw here", so it invented a surface. Had a human picked one,
    that invention becomes the spec rung 4 builds against, and every gate downstream says yes,
    because each only checks the previous rung's artifact was built well."""
    r = _builder(_one_candidate("this changes behaviour, not appearance — there is one shape")).build(
        7, "remember my settings")
    assert r.passed, r.detail
    assert len(r.candidates) == 1
    assert "one shape" in r.fewer_because


def test_drawing_fewer_without_saying_why_still_fails():
    """The exit is a JUDGEMENT a rung may make, not a way to quietly under-deliver. Without the
    reason this is indistinguishable from a session that ran out of turns."""
    r = _builder(_one_candidate()).build(7, "remember my settings")
    assert r.passed is False and "no reason given" in r.detail


def test_no_candidates_at_all_is_still_a_failure():
    """"Nothing to draw" is a thing a rung may conclude; producing nothing is not the same act."""
    r = _builder('```json\n{"page_name": "exp-7", "page_id": "1:0", "fewer_because": "nothing", '
                 '"lint": {"auto_layout": true, "named_layers": true, '
                 '"detached_instances": false}, "candidates": []}\n```').build(7, "x")
    assert r.passed is False and "nothing to look at" in r.detail


def test_more_than_asked_for_is_still_refused():
    from fls.builders.figma_wireframe import lint_structure
    assert any("at most" in v for v in lint_structure({"candidates": [{}] * 5}, 3))


def test_the_reason_reaches_the_visitor_and_carries_no_machinery():
    """The page shows one option; without the sentence that reads as the rung having failed rather
    than having judged. And it goes through the same leak guard as every other visitor line."""
    from fls.demo import demo_view
    rec = {"number": 7, "intent": "remember my settings", "rung": "2-wireframe",
           "status": "await-pick", "source": "demo:n", "spent": 0.0, "normalized_usd": 0.0}
    wf = {"running": True, "artifacts": {
        "figma": {"page": "exp-7", "page_id": "1:0",
                  "fewer_because": "this changes behaviour, not appearance"},
        "wireframe": [{"name": "exp-7-c1", "title": "The only shape", "premise": "p",
                       "node_id": "1:1"}]}}
    v = demo_view(rec, wf)
    assert "behaviour, not appearance" in v["artifacts"]["fewer_because"]


def test_a_resumed_attempt_stays_under_the_same_colour_rule():
    """The policy is decided from the REQUEST, and a retry is the same request. It travels on the
    builder rather than in the prompt alone, so an attempt that adopts a half-drawn page inherits
    the rule the first attempt was under — otherwise the second attempt would quietly be allowed
    to finish in colour what the first was told to draw in grey.
    """
    from fls.builders.figma_wireframe import colour_policy_for
    b = _builder(_contract(page_id="12:0"))
    b.policy = colour_policy_for("a share sheet on the hand screen")
    assert b.policy.greyscale
    p = b.prompt(7, "a share sheet on the hand screen", resume=Resume(page_id="12:0"))
    assert "COLOUR: greyscale only" in p
    # and the check still bites on the resumed contract, which declares no fills
    r = b.build(7, "a share sheet on the hand screen", resume=Resume(page_id="12:0"))
    assert not r.passed and "colour rule" in r.detail

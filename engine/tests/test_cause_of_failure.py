"""A run that stops must say why, in the place the reader is already looking.

THE BUG THIS FILE EXISTS FOR. Expedition 17 died mid-build and every surface said the same
four words — "it stopped before finishing" — while the actual reason sat in five places at
once: a 300-character event, a session transcript nobody linked to, journald, Temporal's
`last_failure`, and the test output. A reader had to know all five to answer "what happened".

So a failure now writes ONE record, `expeditions/<n>/cause.json`, carrying the kind, the rung,
the attempt, the artifact it came from and that artifact's tail — written by whoever knew, at
the moment it knew. The visitor surface translates it; the operator surface shows it whole.
"""
from __future__ import annotations

import json

import pytest

from fls.orchestration import activities
from fls.orchestration.types import RungRequest, RungResult
from fls.store import ExpeditionStore, artifact_tail


class _Runner:
    """A runner that does whatever the test tells it to, and records nothing."""

    def __init__(self, outcome):
        self.outcome = outcome

    def record(self, *a, **kw) -> None:
        pass

    def wireframe(self, req: RungRequest) -> RungResult:
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A store rooted in a temp dir, with the activities module pointed at it."""
    monkeypatch.setenv("FLS_ROOT", str(tmp_path))
    d = tmp_path / "expeditions" / "7"
    (d / "wireframes").mkdir(parents=True)
    return ExpeditionStore(tmp_path)


def _rung(box, outcome, *, rung: int = 2):
    activities.RUNNER = _Runner(outcome)
    return activities._run_rung("fls.wireframe", "wireframe",
                                RungRequest(number=7, rung=rung, intent="a share sheet"))


def test_a_crash_writes_down_what_the_session_was_saying_when_it_died(box, tmp_path):
    """THE REGRESSION TEST. The exception still propagates — the workflow must see it — but the
    transcript's last words are on disk before it goes."""
    log = tmp_path / "expeditions" / "7" / "wireframes" / "session-1.log"
    log.write_text("opening the file\nasking for the frames\nconnection reset by peer\n")

    with pytest.raises(RuntimeError):
        _rung(box, RuntimeError("the socket went away"))

    cause = box.cause(7)
    assert cause["kind"] == "crash" and cause["rung"] == 2 and cause["attempt"] == 1
    assert cause["error"] == "RuntimeError" and "socket" in cause["message"]
    assert cause["artifact"] == "wireframes/session-1.log"
    assert cause["tail"][-1] == "connection reset by peer"


def test_a_refusal_is_recorded_as_a_refusal_not_as_a_crash(box):
    """A rung that ran, decided and said no is not a fault in the machine, and the record must
    not describe it as one — a reader who sees `crash` goes looking for a bug that isn't there."""
    _rung(box, RungResult(rung=2, passed=False, state="parked",
                          detail="the two candidates were the same layout twice"))
    cause = box.cause(7)
    assert cause["kind"] == "refused" and cause["error"] == ""
    assert "same layout twice" in cause["message"]


def test_a_question_is_not_a_failure_and_leaves_no_cause(box):
    """`needs-human` is the spec rung saying what it would need. Writing a cause for it would put
    "something went wrong" under a run that worked exactly as designed."""
    _rung(box, RungResult(rung=2, passed=False, state="needs-human",
                          detail="which of the two sheets did you mean"))
    assert box.cause(7) is None


def test_a_rung_that_passed_writes_no_cause(box):
    _rung(box, RungResult(rung=2, passed=True, state="await-pick", detail="three candidates"))
    assert box.cause(7) is None


def test_stderr_beats_the_transcript_because_a_crash_says_why_on_stderr(box, tmp_path):
    """A session that dies mid-sentence leaves a transcript that simply stops. The reason, when
    there is one, is on stderr — so the sibling wins whenever it has anything in it."""
    w = tmp_path / "expeditions" / "7" / "wireframes"
    (w / "session-1.log").write_text("thinking about the sheet\n")
    (w / "session-1.log.stderr").write_text("Error: MCP server 'figma' is not logged in\n")

    artifact, tail = artifact_tail(tmp_path, 7, 2)
    assert artifact == "wireframes/session-1.log.stderr"
    assert "not logged in" in tail[-1]


def test_an_empty_stderr_does_not_displace_the_transcript(box, tmp_path):
    """Every session leaves a `.stderr`; most are empty. An empty file is not an explanation."""
    w = tmp_path / "expeditions" / "7" / "wireframes"
    (w / "session-1.log").write_text("three candidates written\n")
    (w / "session-1.log.stderr").write_text("")

    artifact, tail = artifact_tail(tmp_path, 7, 2)
    assert artifact == "wireframes/session-1.log" and tail == ["three candidates written"]


def test_the_newest_attempt_is_the_one_asked_about(box, tmp_path):
    """A run retried twice is asked about the failure it is sitting in, not the first one."""
    import os
    w = tmp_path / "expeditions" / "7" / "wireframes"
    (w / "session-1.log").write_text("the first try\n")
    (w / "session-2.log").write_text("the second try\n")
    os.utime(w / "session-1.log", (1, 1))

    artifact, tail = artifact_tail(tmp_path, 7, 2)
    assert artifact == "wireframes/session-2.log" and tail == ["the second try"]


def test_a_build_falls_back_to_the_test_output_when_there_is_no_transcript(box, tmp_path):
    """Rung 4's own words are its test run; when the session left nothing, that is the evidence."""
    m = tmp_path / "expeditions" / "7" / "mvp"
    m.mkdir()
    (m / "test-output.txt").write_text("FAIL src/sheet.test.tsx\n1 failed, 12 passed\n")

    artifact, tail = artifact_tail(tmp_path, 7, 4)
    assert artifact == "mvp/test-output.txt" and "1 failed" in tail[-1]


def test_a_rung_with_no_artifact_still_gets_a_cause(box):
    """A crash before anything was written is the case with the LEAST evidence — so the record
    must still exist, saying what it can and admitting the rest."""
    with pytest.raises(ValueError):
        _rung(box, ValueError("no worktree"))
    cause = box.cause(7)
    assert cause["kind"] == "crash" and cause["artifact"] == "" and cause["tail"] == []


# --- the mirror: a park the WORKFLOW decided, where no activity lived to explain itself ---

def _park(box, tmp_path, detail: str, *, started: float = 100.0, attempt: int = 3):
    from fls.worker import _cause_for_park
    d = tmp_path / "expeditions" / "7"
    (d / "step.json").write_text(json.dumps({"started_at": started, "attempt": attempt}))
    _cause_for_park(box, 7, 2, detail)


@pytest.mark.parametrize("detail,kind", [
    ("it stopped answering while it worked", "heartbeat"),
    ("it ran past its 30 minute limit", "timeout"),
    ("the run ended", "stopped"),
])
def test_a_park_the_workflow_decided_becomes_a_cause(box, tmp_path, detail, kind):
    """No activity survives a heartbeat timeout, so nothing inside the rung can write the cause.
    The workflow's own sentence is all there is — and it carries the attempt and the tail."""
    (tmp_path / "expeditions" / "7" / "wireframes" / "session-1.log").write_text("half a frame\n")
    _park(box, tmp_path, detail)
    cause = box.cause(7)
    assert cause["kind"] == kind and cause["attempt"] == 3
    assert cause["message"] == detail
    assert cause["artifact"] == "wireframes/session-1.log" and cause["tail"] == ["half a frame"]


def test_the_mirror_never_overwrites_a_fresher_activity_cause(box, tmp_path):
    """An activity that explained itself knows the error class, the message and the attempt. The
    mirror knows one sentence written from outside. Whoever knew more must win."""
    box.write_cause(7, {"kind": "crash", "rung": 2, "attempt": 1,
                        "error": "FigmaAuthError", "message": "not logged in",
                        "artifact": "", "tail": []})
    _park(box, tmp_path, "it stopped answering while it worked", started=0.0)
    assert box.cause(7)["error"] == "FigmaAuthError"


def test_a_cause_from_a_previous_step_does_not_explain_this_one(box, tmp_path):
    """Stale is worse than missing: a cause written before this step started describes a failure
    the reader already lived through, sitting under the one they are looking at now."""
    box.write_cause(7, {"kind": "crash", "rung": 1, "attempt": 1, "error": "OldError",
                        "message": "an earlier life", "artifact": "", "tail": []})
    import time as _t
    _park(box, tmp_path, "it ran past its 30 minute limit", started=_t.time() + 60)
    assert box.cause(7)["kind"] == "timeout"


# --- the visitor's side: every kind must survive the leak guard ---

@pytest.mark.parametrize("kind", ["crash", "timeout", "heartbeat", "stopped"])
def test_every_cause_kind_reaches_a_visitor_in_plain_words(kind):
    from fls.demo import cause_words, looks_like_machinery
    words = cause_words({"kind": kind, "rung": 2}, "Wireframe")
    assert words and "Wireframe" in words
    low = words.lower()
    for leak in ("rung", "dial", "expedition", "activity", "temporal", "heartbeat", "traceback"):
        assert leak not in low, f"{leak!r} reached the visitor"
    assert not looks_like_machinery(words)


def test_a_refusals_own_sentence_goes_through_the_same_guard():
    """A refusal already has words — the rung's — and those were written for an operator."""
    from fls.demo import cause_words
    words = cause_words({"kind": "refused", "rung": 4,
                         "message": "vessel exp-7 failed lint at rung 4 (dial: agent-picks)"},
                        "Build")
    low = words.lower()
    assert "rung" not in low and "dial" not in low and "vessel" not in low


def test_an_unrecorded_cause_says_nothing_rather_than_guessing():
    from fls.demo import cause_words
    assert cause_words(None, "Build") == ""
    assert cause_words({"kind": "something-new", "rung": 2}, "Wireframe") == ""


def test_the_demo_view_shows_the_cause_only_on_a_run_that_actually_broke():
    from fls.demo import demo_view
    cause = {"kind": "heartbeat", "rung": 3}
    broke = demo_view({"number": 7, "intent": "x", "rung": 3, "status": "climbing"},
                      {"running": False}, {}, cause=cause)
    assert "cause" in broke and "stopped answering" in broke["cause"]

    signed_off = demo_view({"number": 7, "intent": "x", "rung": 5, "status": "done"},
                           {"running": False}, {}, cause=cause)
    assert "cause" not in signed_off


def test_a_human_park_is_a_decision_and_carries_no_cause():
    from fls.demo import demo_view
    view = demo_view({"number": 7, "intent": "x", "rung": 3, "status": "parked",
                      "parked_by": "nobody-in-particular"}, {"running": False}, {},
                     cause={"kind": "stopped", "rung": 3})
    assert "cause" not in view


def test_retry_is_withheld_with_the_reason_rather_than_offered_and_refused():
    """The button used to be drawn on every stopped run and its refusals discovered by pressing
    it — which teaches a visitor the button is unreliable, not that this run cannot be retried."""
    from fls.demo import demo_view
    view = demo_view({"number": 7, "intent": "x", "rung": 3, "status": "climbing"},
                     {"running": False}, {},
                     retry_refusal="expedition 7 has spent $12.00 of its $12.00 ceiling — "
                                   "retry refused (fail-closed)")
    assert "retry" not in view["actions"]
    assert "used up what it is allowed to spend" in view["retry_blocked"]
    assert "ceiling" not in view["retry_blocked"].lower()


def test_retry_stays_on_offer_when_nothing_would_refuse_it():
    from fls.demo import demo_view
    view = demo_view({"number": 7, "intent": "x", "rung": 3, "status": "climbing"},
                     {"running": False}, {})
    assert "retry" in view["actions"] and "retry_blocked" not in view


def test_the_engines_refusal_sentences_are_the_ones_the_visitor_surface_can_translate():
    """`retry_refusal` and `_retry_run` must keep saying the same words, because `_RETRY_ERRORS`
    matches on them. A reworded refusal would silently become "that did not go through"."""
    from fls.app import retry_refusal
    from fls.demo import _RETRY_ERRORS, visitor_error
    cases = [
        ({"status": "done"}, {"running": False}),
        ({"status": "climbing"}, None),
        ({"status": "climbing"}, {"running": True}),
        ({"status": "climbing", "normalized_usd": 99.0}, {"running": False}),
    ]
    marks = {m for m, _ in _RETRY_ERRORS}
    for rec, st in cases:
        why = retry_refusal(7, rec, st, 12.0)
        assert why, f"{rec} should refuse"
        assert any(m in why.lower() for m in marks), f"untranslatable refusal: {why!r}"
        assert visitor_error(409, why) != "That did not go through, and nothing was changed."


def test_a_retryable_run_is_refused_by_nothing():
    from fls.app import retry_refusal
    assert retry_refusal(7, {"status": "climbing", "normalized_usd": 3.0},
                         {"running": False}, 12.0) == ""


# ── the tail has to be readable, or it is not evidence ─────────────────────────────────────

SESSION = [
    '{"type":"system","subtype":"init","session_id":"x"}',
    '{"type":"system","subtype":"thinking_tokens","estimated_tokens":142}',
    '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"",'
    '"signature":"CAISrwQKqwEIERgCKkCqwItXicKqvGhVCyyB' + "A" * 600 + '"}]}}',
    '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash",'
    '"input":{"command":"pnpm test","description":"Run the suite"}}]}}',
    '{"type":"user","message":{"content":[{"type":"tool_result",'
    '"content":"2 failed, 40 passed"}]}}',
    '{"type":"system","subtype":"task_started","task_id":"t1"}',
    '{"type":"assistant","message":{"content":[{"type":"text","text":"The migration is missing."}]}}',
    '{"type":"result","subtype":"success","result":"done"}',
]


def test_the_tail_of_a_session_log_is_what_happened_not_what_was_counted(box, tmp_path):
    """THE BUG THIS EXISTS FOR. The first cause record shipped with forty raw NDJSON lines as its
    evidence — token counters and base64 thinking signatures, one of them longer than the function
    that now filters them. That is a worse answer than no evidence, because it looks like
    evidence."""
    m = tmp_path / "expeditions" / "7" / "mvp"
    m.mkdir()
    (m / "session-1.log").write_text("\n".join(SESSION) + "\n")

    _, tail = artifact_tail(tmp_path, 7, 4)
    blob = "\n".join(tail)
    assert "thinking_tokens" not in blob and "CAISrwQ" not in blob and "task_started" not in blob
    assert "Bash: pnpm test" in blob
    assert "-> 2 failed, 40 passed" in blob
    assert "The migration is missing." in blob
    assert tail[-1] == "result: done"
    assert all(len(line) <= 300 for line in tail)


def test_plain_text_passes_straight_through(box, tmp_path):
    """`mvp/test-output.txt` is not NDJSON and must not be filtered into nothing."""
    m = tmp_path / "expeditions" / "7" / "mvp"
    m.mkdir()
    (m / "test-output.txt").write_text("FAIL tests/profileMigration.test.ts\n1 failed\n")
    _, tail = artifact_tail(tmp_path, 7, 4)
    assert tail == ["FAIL tests/profileMigration.test.ts", "1 failed"]


def test_the_tail_counts_lines_that_say_something(box, tmp_path):
    """Forty lines of noise used to crowd out the one line that mattered. The limit now applies
    to what is left after the noise is dropped."""
    from fls.store import readable_tail
    noise = ['{"type":"system","subtype":"thinking_tokens"}'] * 200
    said = ['{"type":"assistant","message":{"content":[{"type":"text","text":"line '
            + str(i) + '"}]}}' for i in range(5)]
    out = readable_tail(noise[:100] + said + noise[100:], 40)
    assert out == [f"line {i}" for i in range(5)]


def test_an_unparseable_line_is_kept_rather_than_dropped(box):
    """A log that is not what we expected is still the only record there is."""
    from fls.store import readable_tail
    assert readable_tail(['{"type": broken', "plain words"], 40) == ['{"type": broken',
                                                                     "plain words"]


def test_the_visitor_is_not_shown_the_same_sentence_twice():
    """A refusal's own words go through the leak guard, and the guard is often right to drop them
    — rung 4's real refusal named the reviewability budget. What is left is the generic fallback,
    which is exactly what `detail` already says."""
    from fls.demo import demo_view
    refusal = ("the diff is 1857 changed lines, over the 400-line reviewability budget")
    # The shape expedition 42 actually had: the SAME sentence is the record's reason and the
    # cause's message, so both go through the guard and both come back as the same fallback.
    view = demo_view({"number": 7, "intent": "x", "rung": "4-mvp", "status": "parked",
                      "parked_by": "failure", "reason": refusal}, {"running": False}, {},
                     cause={"kind": "refused", "rung": 4, "message": refusal})
    assert view["detail"], "the detail should still say the run stopped"
    assert "cause" not in view, "a cause that only repeats the detail is not a cause"


def test_a_cause_that_adds_something_is_still_shown():
    from fls.demo import demo_view
    view = demo_view({"number": 7, "intent": "x", "rung": 3, "status": "climbing"},
                     {"running": False}, {}, cause={"kind": "heartbeat", "rung": 3})
    assert view["cause"] != view["detail"] and "stopped answering" in view["cause"]

"""Rung 1 asks which thing was meant, instead of picking one and building it.

THE RUN THIS FILE EXISTS FOR. Expedition 40's whole request was four words — "Move the button to
the other side." In poker "the button" is the dealer button, a marker that moves each hand; in
software it is a thing you tap. The gate did not ask. Rung 1 did not pick one of the two, either:
it invented a THIRD reading, an account-dialog footer with Save and Cancel, and rung 2 drew three
genuinely good wireframes of it, and rung 4 built it, and a merge-ready pull request exists for a
surface nobody ever named.

Every artifact along the way was well made. That is exactly why nothing stopped it: each gate
checks that the rung before it did good work, and all of them had.
"""
from __future__ import annotations

import pytest

from fls.rung1 import (
    AskedQuestion,
    Rung1Result,
    ambiguous_question,
    answered_grounding,
    insufficient_reason,
    resolve_answer,
    run_rung1,
)

ASKED = ("AMBIGUOUS: when you say 'it', which thing do you mean?\n"
         "(a) the Fold button in the action bar\n"
         "(b) the dealer button on the table\n"
         "(x) something else")


def test_a_question_is_parsed_with_its_options():
    q = ambiguous_question(ASKED)
    assert q.ask == "when you say 'it', which thing do you mean?"
    assert q.options == ("the Fold button in the action bar", "the dealer button on the table",
                         "something else")


def test_the_escape_hatch_is_always_there():
    """A person whose meaning is neither reading must not be made to pick one of them."""
    q = ambiguous_question("AMBIGUOUS: which?\n(a) one\n(b) two")
    assert q.options[-1] == "something else"


def test_a_spec_that_merely_discusses_ambiguity_is_a_spec():
    """Start-anchored, exactly like the INSUFFICIENT sentinel — otherwise good work is thrown
    away for a coincidence of vocabulary."""
    assert ambiguous_question("SPEC: handle the ambiguous case by asking. ACCEPTANCE:\n1. x") is None


def test_a_bare_sentinel_still_asks_something():
    q = ambiguous_question("AMBIGUOUS:")
    assert q.ask and q.options == ("something else",)


@pytest.mark.parametrize("typed,meant", [
    ("a", "the Fold button in the action bar"),
    ("(b)", "the dealer button on the table"),
    ("A.", "the Fold button in the action bar"),
    ("b)", "the dealer button on the table"),
    ("2", "the dealer button on the table"),
    ("option a", "the Fold button in the action bar"),
    ("the one I tap to fold", "the one I tap to fold"),
    ("z", "z"),
])
def test_a_letter_is_resolved_where_the_question_is(typed, meant):
    """People answer a lettered question with a letter, and the model that asked it is not
    holding the letters — so the spec rung is handed a sentence, never an initial."""
    assert resolve_answer(ambiguous_question(ASKED), typed) == meant


def test_choosing_something_else_with_no_words_says_so():
    """Otherwise the rung reads an empty answer as a settled referent."""
    assert "did not say" in resolve_answer(ambiguous_question(ASKED), "c")


def test_the_answer_reaches_the_prompt_with_the_question_it_answers():
    g = answered_grounding(ambiguous_question(ASKED).as_dict(), "b")
    assert "THE PERSON ANSWERED: the dealer button on the table" in g
    assert 'they typed: "b"' in g
    assert "Do NOT ask this question again" in g
    assert "(a) the Fold button in the action bar" in g


def test_without_a_question_the_grounding_is_just_the_words():
    """Every other rung's feedback is raw text and must stay that way."""
    assert answered_grounding(None, "make the chips bigger") == "make the chips bigger"


# ── the rung itself ────────────────────────────────────────────────────────────────────────

class _Panel:
    """A builder/judge whose replies are scripted, so the call count is the assertion."""

    def __init__(self, replies):
        self.replies, self.calls, self.prompts = list(replies), 0, []

    def complete(self, prompt, max_tokens=None, system=None):
        from fls.llm import Call
        self.prompts.append(prompt)
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return text, Call("stub", "m", 1, 1, usd=0.0, normalized_usd=0.0)


SPEC = "SPEC: a thing\n\nACCEPTANCE:\n1. the thing happens\nSIZE: small - one file"


def _idea():
    from fls.adjudicator import Idea
    return Idea(1, "move the button", "it moved", "feature")


def test_a_majority_asking_ends_the_rung_on_three_calls():
    """A question must never reach the revise step: "rewrite the spec addressing the critique" is
    an invitation to turn the question INTO a spec, and the repair step would then bolt an
    ACCEPTANCE section onto it — the rung answering a question it had just said it could not."""
    p = _Panel([ASKED])
    r = run_rung1(_idea(), None, p, p, n=3)
    assert r.question is not None and r.declined
    assert p.calls == 3, "no rank, no critique, no revise, no repair"
    assert r.criteria == [] and r.acceptance_stub is None


def test_one_dissenter_does_not_stop_the_rung():
    """Two thirds of the panel wrote a spec; rank those and let the winner through."""
    p = _Panel([ASKED, SPEC, SPEC, "[0]", "fine", SPEC])
    r = run_rung1(_idea(), None, p, p, n=3)
    assert r.question is None
    assert "AMBIGUOUS" not in r.revised_top


def test_a_question_from_the_revise_step_is_still_caught():
    """It is the same model under the same system prompt; the last word is checked too."""
    p = _Panel([SPEC, SPEC, SPEC, "[0]", "critique", ASKED])
    r = run_rung1(_idea(), None, p, p, n=3)
    assert r.question is not None


def test_an_answered_run_writes_a_spec():
    p = _Panel([SPEC])
    r = run_rung1(_idea(), None, p, p, n=3,
                  grounding=answered_grounding(ambiguous_question(ASKED).as_dict(), "a"))
    assert r.question is None and r.criteria
    assert "THE PERSON ANSWERED" in p.prompts[0], "the answer must reach the fan-out"


def test_a_refusal_is_still_a_refusal():
    """The INSUFFICIENT path is untouched by the new sentinel."""
    p = _Panel(["INSUFFICIENT: it names no surface"])
    r = run_rung1(_idea(), None, p, p, n=3)
    assert insufficient_reason(r.revised_top) and r.question is None and r.declined


def test_the_prompt_tells_the_rung_when_not_to_ask():
    """Over-asking is the failure mode on the other side: a rung that asks about scope, or asks
    again after it has been answered, costs a person a round trip for nothing."""
    from fls.rung1 import _SPEC_SYS
    assert "AMBIGUOUS:" in _SPEC_SYS
    assert "Never about scope" in _SPEC_SYS
    assert "If the request names the surface, do not ask" in _SPEC_SYS
    assert "never ask again" in _SPEC_SYS


def test_the_result_knows_it_declined():
    assert Rung1Result([], [], 0, "", "", question=AskedQuestion("q", ("a",))).declined
    assert not Rung1Result([], [], 0, "", SPEC).declined

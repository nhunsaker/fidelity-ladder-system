"""P1 core: admission gate (frozen interface, stubbed judge) + autonomy ledger."""
import json
from pathlib import Path

import pytest

from fls.adjudicator import Idea, adjudicate
from fls.anchor import Anchor, Dial, Verdict
from fls.ledger import Decision, Ledger
from fls.llm import Call

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"
ANCHOR = Anchor.load(ANCHOR_PATH)
ANCHOR_TEXT = ANCHOR_PATH.read_text()


class StubJudge:
    """Returns a canned JSON verdict — no network, no spend."""
    def __init__(self, verdict="admit", reasoning="traces to north star"):
        self._v, self._r = verdict, reasoning

    def complete(self, prompt, max_tokens=1024, system=None):
        text = json.dumps({"verdict": self._v, "reasoning": self._r})
        return text, Call("stub", "stub", 10, 5, 0.0)


def _idea(altitude="feature"):
    return Idea(1, "As a user I want X so that Y, tied to the north star", "X works", altitude)


def test_admit_when_judge_admits():
    j = adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, StubJudge("admit"))
    assert j.verdict == Verdict.admit
    assert j.cost.provider == "stub"


def test_dock_when_judge_docks():
    j = adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, StubJudge("dock", "no anchor trace"))
    assert j.verdict == Verdict.dock


def test_altitude_precheck_docks_without_spending():
    # 'migration' is not allowed in the demo ANCHOR — should dock deterministically, no LLM call
    class BoomJudge:
        def complete(self, *a, **k):
            raise AssertionError("judge should not be called when altitude is disallowed")
    j = adjudicate(_idea(altitude="migration"), ANCHOR, ANCHOR_TEXT, BoomJudge())
    assert j.verdict == Verdict.dock
    assert "altitude" in j.reasoning


def test_unparseable_reply_needs_human():
    class Garbage:
        def complete(self, *a, **k):
            return "sorry I can't do that", Call("stub", "stub", 1, 1, 0.0)
    j = adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, Garbage())
    assert j.verdict == Verdict.needs_human


def test_ledger_agreement_and_demote(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    # 10 decisions at rung 1, judge admits, human disagrees 4x -> 60% agreement < 80% threshold
    for i in range(10):
        human = "admit" if i >= 4 else "dock"
        led.record(Decision(1, "1-spec", "admit", human, 0.001, 10, 5))
    assert led.agreement_rate("1-spec", 10) == pytest.approx(0.6)
    assert led.cost_per_verdict("1-spec") == pytest.approx(0.001)
    # current dial human-picks -> demote one step tighter (propose-only)
    demoted = led.demote_check("1-spec", ANCHOR, Dial.human_picks)
    assert demoted == Dial.propose_only


def test_ledger_no_demote_when_agreement_high(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    for _ in range(10):
        led.record(Decision(1, "1-spec", "admit", "admit", 0.001))
    assert led.demote_check("1-spec", ANCHOR, Dial.human_picks) is None


def test_ledger_persists_and_reloads(tmp_path):
    p = tmp_path / "ledger.jsonl"
    Ledger(p).record(Decision(7, "2-wireframe", "admit", None, 0.002))
    reloaded = Ledger(p).load()
    assert len(reloaded.rows) == 1
    assert reloaded.rows[0].expedition == 7
    assert reloaded.rows[0].agreed is None  # no human yet


# ── the declared bar (adjudicator.bar) ──────────────────────────────────────────────────────
#
# An instance whose job is to SHOW the ladder run needs a lower gate than one guarding a real
# backlog. That is policy, so it is declared in the ANCHOR and not compiled into a prompt.

def _permissive():
    """The same ANCHOR, with the bar lowered. Copied rather than mutated so the module-level
    ANCHOR every other test in this file shares stays strict."""
    a = ANCHOR.model_copy(deep=True)
    a.adjudicator.bar = "permissive"
    return a


def test_the_default_bar_is_strict_and_unchanged():
    """Back-compat: an ANCHOR that declares no bar behaves exactly as it did before the field
    existed, which is the condition for shipping this without touching every instance."""
    assert ANCHOR.adjudicator.bar == "strict"
    j = adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, StubJudge("needs-human", "scope is ambiguous"))
    assert j.verdict == Verdict.needs_human


def test_a_permissive_bar_admits_an_idea_the_gate_found_merely_ambiguous():
    """The live case: "add way for a player to share their mood with an emoji" was held at the
    gate for lacking acceptance criteria — which is the spec rung's job, not the gate's."""
    j = adjudicate(_idea(), _permissive(), ANCHOR_TEXT,
                   StubJudge("needs-human", "lacks sufficient scope/acceptance criteria"))
    assert j.verdict == Verdict.admit
    # the gate's sentence survives: the spec rung and the operator both want to know what was
    # unclear, and a silent admission would throw that away
    assert "acceptance criteria" in j.reasoning


def test_a_permissive_bar_still_docks_what_does_not_trace():
    """"Low bar" is not "no bar". Docking is the check that protects the vessel — an idea that
    violates a non-negotiable is the one thing the gate exists to stop, and the ANCHOR's own
    feeder scope says so about in-hand assistance."""
    j = adjudicate(_idea(), _permissive(), ANCHOR_TEXT,
                   StubJudge("dock", "violates the north star: in-hand assistance"))
    assert j.verdict == Verdict.dock


def test_a_permissive_bar_does_not_admit_on_adjudicator_FAILURE():
    """The distinction the whole feature turns on. A gate that JUDGED an idea ambiguous has done
    its job; a gate that could not answer has not, and collapsing the two would make a broken
    adjudicator look like a generous one — every idea admitted, nothing recorded as wrong."""
    class Garbage:
        def complete(self, prompt, max_tokens=1024, system=None):
            return "the model said something that is not JSON", Call("stub", "stub", 1, 1, 0.0)

    class WrongSchema:
        def complete(self, prompt, max_tokens=1024, system=None):
            return json.dumps({"decision": "admit"}), Call("stub", "stub", 1, 1, 0.0)

    assert adjudicate(_idea(), _permissive(), ANCHOR_TEXT, Garbage()).verdict == Verdict.needs_human
    assert adjudicate(_idea(), _permissive(), ANCHOR_TEXT, WrongSchema()).verdict == Verdict.needs_human


def test_a_permissive_bar_still_docks_a_disallowed_altitude_without_spending():
    """The deterministic pre-check is upstream of the bar and stays there: it costs nothing and
    it is the one refusal that needs no judgement."""
    class BoomJudge:
        def complete(self, *a, **k):
            raise AssertionError("must not reach the judge")

    j = adjudicate(_idea(altitude="migration"), _permissive(), ANCHOR_TEXT, BoomJudge())
    assert j.verdict == Verdict.dock


def test_the_bar_is_told_to_the_judge_as_well_as_enforced_after_it():
    """Enforcing it after the fact makes the VERDICT right; telling the model makes the REASONING
    useful. Both, because an instruction is a request and this system does not take those on
    trust."""
    seen = {}

    class Spy(StubJudge):
        def complete(self, prompt, max_tokens=1024, system=None):
            seen["system"] = system
            return super().complete(prompt, max_tokens, system)

    adjudicate(_idea(), _permissive(), ANCHOR_TEXT, Spy("admit"))
    assert "PERMISSIVE" in seen["system"]
    seen.clear()
    adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, Spy("admit"))
    assert "PERMISSIVE" not in seen["system"]

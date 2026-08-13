"""P1 core: admission gate (frozen interface, stubbed judge) + autonomy ledger."""
import json
from pathlib import Path

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
    assert led.agreement_rate("1-spec", 10) == 0.6
    assert led.cost_per_verdict("1-spec") == 0.001
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

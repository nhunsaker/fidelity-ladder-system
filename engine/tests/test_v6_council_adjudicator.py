"""V6 pluggable adjudicators: council/multi-judge Judge + the selection factory.

The frozen adjudicate()/Judgment contract (fls.adjudicator) never changes here — a council is
just another Judge (fans a prompt to N members, folds verdicts into ONE combined reply before
.complete() returns), so these tests exercise it exactly like any other Judge: through
adjudicate() and directly via .complete().
"""
import json
from pathlib import Path

import pytest

from fls.adjudicator import CouncilJudge, Idea, adjudicate, make_adjudicator
from fls.anchor import Anchor, CouncilConfig, Verdict
from fls.llm import Call

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"
ANCHOR = Anchor.load(ANCHOR_PATH)
ANCHOR_TEXT = ANCHOR_PATH.read_text()


def _idea(altitude="feature"):
    return Idea(1, "As a user I want X so that Y, tied to the north star", "X works", altitude)


class StubMember:
    """A single member judge that always returns a canned verdict — no network, no spend."""
    def __init__(self, verdict="admit", reasoning="traces", model="stub-member"):
        self._v, self._r, self.model = verdict, reasoning, model

    def complete(self, prompt, max_tokens=1024, system=None):
        text = json.dumps({"verdict": self._v, "reasoning": self._r})
        return text, Call("stub", self.model, 10, 5, 0.001, 0.001, "credits")


class GarbageMember:
    def complete(self, prompt, max_tokens=1024, system=None):
        return "not json at all", Call("stub", "garbage", 1, 1, 0.0, 0.0, "credits")


# --- combining behaviour, exercised directly (fast, no adjudicate() plumbing) -------------

def test_council_majority_admits_when_most_members_admit():
    members = [StubMember("admit"), StubMember("admit"), StubMember("dock", "off-anchor")]
    council = CouncilJudge(members, combine="majority")
    text, call = council.complete("prompt")
    obj = json.loads(text)
    assert obj["verdict"] == "admit"
    assert call.provider == "council"
    assert call.input_tokens == 30  # 3 members x 10
    assert call.usd == pytest.approx(0.003)


def test_council_majority_ties_fail_toward_tighter_verdict():
    # 1 admit / 1 dock -> tie; must default to the tighter verdict (dock), never admit
    members = [StubMember("admit"), StubMember("dock", "no trace")]
    council = CouncilJudge(members, combine="majority")
    text, _ = council.complete("prompt")
    assert json.loads(text)["verdict"] == "dock"


def test_council_unanimous_to_admit_requires_every_member():
    members = [StubMember("admit"), StubMember("admit")]
    council = CouncilJudge(members, combine="unanimous-to-admit")
    text, _ = council.complete("prompt")
    assert json.loads(text)["verdict"] == "admit"

    members_split = [StubMember("admit"), StubMember("needs-human", "ambiguous scope")]
    council2 = CouncilJudge(members_split, combine="unanimous-to-admit")
    text2, _ = council2.complete("prompt")
    assert json.loads(text2)["verdict"] == "needs-human"


def test_council_unanimous_to_admit_docks_if_any_member_docks():
    members = [StubMember("admit"), StubMember("dock", "violates non-negotiable")]
    council = CouncilJudge(members, combine="unanimous-to-admit")
    text, _ = council.complete("prompt")
    assert json.loads(text)["verdict"] == "dock"


def test_council_unparseable_member_reply_fails_toward_needs_human_not_admit():
    members = [StubMember("admit"), GarbageMember()]
    council = CouncilJudge(members, combine="majority")
    text, _ = council.complete("prompt")
    # 1 admit / 1 needs-human (garbage) -> tie -> fails toward needs-human, never admit
    assert json.loads(text)["verdict"] == "needs-human"


def test_council_rejects_empty_membership():
    with pytest.raises(ValueError):
        CouncilJudge([])


# --- through the frozen adjudicate() seam --------------------------------------------------

def test_adjudicate_admits_via_council_majority():
    members = [StubMember("admit"), StubMember("admit"), StubMember("dock")]
    council = CouncilJudge(members, combine="majority")
    j = adjudicate(_idea(), ANCHOR, ANCHOR_TEXT, council)
    assert j.verdict == Verdict.admit
    assert j.cost.provider == "council"


def test_adjudicate_altitude_precheck_still_skips_the_whole_council():
    class BoomMember:
        def complete(self, *a, **k):
            raise AssertionError("no council member should be called when altitude is disallowed")
    council = CouncilJudge([BoomMember(), BoomMember()])
    j = adjudicate(_idea(altitude="migration"), ANCHOR, ANCHOR_TEXT, council)
    assert j.verdict == Verdict.dock
    assert "altitude" in j.reasoning


# --- selection factory -----------------------------------------------------------------

def test_make_adjudicator_default_kind_is_single_llm_azure_judge():
    from fls.llm import AzureJudge
    judge = make_adjudicator(ANCHOR)
    assert isinstance(judge, AzureJudge)
    assert judge.deployment == "gpt-5.4-nano"  # unchanged from historical hardcoded default


def test_make_adjudicator_council_kind_builds_a_council_of_the_configured_size():
    data = json.loads(ANCHOR.model_dump_json())
    data["adjudicator"]["kind"] = "council"
    data["adjudicator"]["council"] = {"size": 5, "combine": "unanimous-to-admit"}
    anchor = Anchor.model_validate(data)
    judge = make_adjudicator(anchor)
    assert isinstance(judge, CouncilJudge)
    assert len(judge.members) == 5
    assert judge.combine == "unanimous-to-admit"


def test_make_adjudicator_council_defaults_size_three_majority():
    data = json.loads(ANCHOR.model_dump_json())
    data["adjudicator"]["kind"] = "council"
    anchor = Anchor.model_validate(data)
    judge = make_adjudicator(anchor)
    assert isinstance(judge, CouncilJudge)
    assert len(judge.members) == 3
    assert judge.combine == "majority"


def test_council_config_defaults_are_back_compat():
    # an ANCHOR with no council: block at all still parses (default kind=single-llm)
    cfg = CouncilConfig()
    assert cfg.size == 3
    assert cfg.combine == "majority"
    assert cfg.model is None
    assert ANCHOR.adjudicator.kind == "single-llm"

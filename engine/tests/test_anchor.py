"""P0 verify: the demo ANCHOR.md parses and validates, with altitude + cost fields present."""
from pathlib import Path

from fls.anchor import Anchor, Dial

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"


def test_anchor_loads():
    a = Anchor.load(ANCHOR_PATH)
    assert a.version == 1
    assert a.mode == "slim"


def test_altitude_field_present():
    a = Anchor.load(ANCHOR_PATH)
    assert a.altitude_allowed  # non-empty
    assert "migration" not in a.altitude_allowed  # demo instance caps at feature


def test_adjudicator_cost_field_present():
    a = Anchor.load(ANCHOR_PATH)
    assert a.adjudicator.cost.max_tokens > 0
    assert a.adjudicator.cost.max_calls > 0
    assert "verdict" in a.adjudicator.output_contract


def test_funnel_demo_defaults():
    a = Anchor.load(ANCHOR_PATH)
    assert a.funnel.auto_build == 1
    assert a.funnel.interactive_demos == 3
    assert a.funnel.wireframes == "all"


def test_every_rung_has_dial_and_cost():
    a = Anchor.load(ANCHOR_PATH)
    for key, policy in a.rungs.items():
        assert isinstance(policy.dial, Dial), key
        assert policy.est_usd >= 0, key


def test_tighten_only_cascade():
    a = Anchor.load(ANCHOR_PATH)
    # loosening is refused; tightening/equal allowed
    assert a.can_tighten(Dial.human_picks, Dial.propose_only)
    assert a.can_tighten(Dial.human_picks, Dial.human_picks)
    assert not a.can_tighten(Dial.human_picks, Dial.autonomous)


def test_demote_trigger_defined():
    a = Anchor.load(ANCHOR_PATH)
    assert 0 < a.autonomy_demote.agreement_threshold <= 1
    assert a.autonomy_demote.window > 0


def test_the_demo_block_is_purely_additive(tmp_path):
    """An ANCHOR with no `demo:` parses identically and the surface simply suggests nothing."""
    from pathlib import Path as _P

    from fls.anchor import Anchor
    a = Anchor.load(_P(__file__).resolve().parents[2] / "ANCHOR.md")
    assert a.demo.suggestions == []


def test_suggestions_parse_with_and_without_a_success_line(tmp_path):
    from fls.anchor import DemoConfig
    d = DemoConfig(suggestions=[{"intent": "Show the blind schedule", "success": "I can see it"},
                                {"intent": "Add a what-beats-what card"}])
    assert [s.intent for s in d.suggestions] == ["Show the blind schedule",
                                                 "Add a what-beats-what card"]
    assert d.suggestions[1].success == ""

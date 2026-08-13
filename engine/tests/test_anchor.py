"""P0 verify: the demo ANCHOR.md parses and validates, with altitude + cost fields present."""
from pathlib import Path

import pytest

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

"""rungs-as-config: the ladder is data, and the reference profile reproduces the engine's
prior hardcoded caps exactly (behavior-preserving lift)."""
from fls.anchor import DIAL_ORDER, Dial
from fls.funnel import RUNG_FLAG, RUNG_MVP
from fls.profile import WEB_LADDER_PROFILE, LadderProfile, RungSpec


def test_web_ladder_is_six_rungs_0_to_5():
    p = WEB_LADDER_PROFILE
    assert p.height == 6
    assert [r.number for r in p.rungs] == [0, 1, 2, 3, 4, 5]
    assert [r.name for r in p.rungs] == ["intent", "spec", "wireframe", "demo", "mvp", "flag"]


def test_rung4_caps_match_the_engine_defaults():
    # the lift is behavior-preserving: profile caps == the old hardcoded rung-4 literals
    mvp = WEB_LADDER_PROFILE.rung(RUNG_MVP)
    assert mvp.max_retries == 3
    assert mvp.builder_max_tokens == 1500
    assert mvp.context_budget_chars == 2000


def test_top_rung_is_propose_only_the_tightest_dial():
    # rung 5 (flag) is the hard gate — its default dial is the tightest, never auto-ships
    assert WEB_LADDER_PROFILE.rung(RUNG_FLAG).dial == Dial.propose_only
    assert DIAL_ORDER[0] == Dial.propose_only  # tightest


def test_profile_is_swappable_data_not_engine():
    # a different ladder = a different LadderProfile, no engine edit
    tiny = LadderProfile(name="tiny", rungs=(
        RungSpec(0, "intent", "idea", Dial.human_picks, "admission", 0, 0, 0, "gate"),
        RungSpec(1, "code", "code", Dial.propose_only, "test", 4000, 2000, 1, "propose"),
    ))
    assert tiny.height == 2
    assert tiny.rung(1).dial == Dial.propose_only


def test_rung_lookup_fails_closed_on_unknown():
    import pytest
    with pytest.raises(KeyError):
        WEB_LADDER_PROFILE.rung(99)


def test_rung5_carries_a_line_budget_for_enforced_reviewability():
    # rung 5 (flag) is the only rung with a review-gated line budget; earlier rungs default 0/n-a
    assert WEB_LADDER_PROFILE.rung(RUNG_FLAG).line_budget == 400
    assert WEB_LADDER_PROFILE.rung(RUNG_MVP).line_budget == 0

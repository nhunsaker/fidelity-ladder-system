"""Harness PoC profile: shape, registry, env switch (Phase 0)."""
import pytest

from fls.anchor import Dial
from fls.profile import HARNESS_POC_PROFILE, PROFILES, WEB_LADDER_PROFILE, active_profile


def test_registry_has_both_profiles():
    assert set(PROFILES) == {"web-ui", "harness-poc"}
    assert PROFILES["web-ui"] is WEB_LADDER_PROFILE


def test_visible_rungs_are_human_gated():
    p = HARNESS_POC_PROFILE
    assert p.height == 6
    for n in (2, 3, 4):
        assert p.rung(n).dial is Dial.human_picks, n
    assert p.rung(5).dial is Dial.propose_only and p.rung(5).line_budget == 400
    assert p.rung(2).artifact_kind == "figma-frames"
    assert p.rung(3).artifact_kind == "prototype"
    assert p.rung(4).artifact_kind == "mvp-pr"


def test_rung3_is_tightened_relative_to_web_ui():
    assert WEB_LADDER_PROFILE.rung(3).dial is Dial.auto_advance
    assert HARNESS_POC_PROFILE.rung(3).dial is Dial.human_picks


def test_active_profile_env_switch(monkeypatch):
    monkeypatch.delenv("FLS_PROFILE", raising=False)
    assert active_profile() is WEB_LADDER_PROFILE
    monkeypatch.setenv("FLS_PROFILE", "harness-poc")
    assert active_profile() is HARNESS_POC_PROFILE
    assert active_profile("web-ui") is WEB_LADDER_PROFILE
    monkeypatch.setenv("FLS_PROFILE", "typo")
    with pytest.raises(KeyError):
        active_profile()

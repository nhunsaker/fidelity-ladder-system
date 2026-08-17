"""V6 #3 — per-vessel governance/dials/budgets: tighten-only cascade over ANCHOR defaults.

Uses the demo ANCHOR.md (single `acme-demo` vessel, no `governance:` block) plus in-memory
Anchor.model_validate() fixtures so we can exercise both a tightening override and a loosen
attempt without editing the checked-in demo instance.
"""
from pathlib import Path

import yaml

from fls.anchor import Anchor, Dial

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"


def _load_raw() -> dict:
    text = ANCHOR_PATH.read_text(encoding="utf-8")
    block = text.split("```anchor\n", 1)[1].split("\n```", 1)[0]
    return yaml.safe_load(block)


def test_no_governance_block_resolves_to_bare_anchor_defaults():
    a = Anchor.load(ANCHOR_PATH)
    eg = a.effective_governance("acme-demo")
    assert eg.daily_usd is None
    assert eg.per_idea_usd == a.budgets.per_expedition_ceiling_usd
    assert eg.max_rung == 5  # RUNG_FLAG
    assert eg.dials["4-mvp"] == a.rungs["4-mvp"].dial


def test_no_vessel_named_resolves_to_bare_anchor_defaults():
    a = Anchor.load(ANCHOR_PATH)
    eg = a.effective_governance(None)  # no default_vessel override in play here
    assert eg.per_idea_usd == a.budgets.per_expedition_ceiling_usd


def test_vessel_governance_tightens():
    data = _load_raw()
    data["vessels"][0]["governance"] = {
        "dials": {"4-mvp": "propose-only"},          # tighter than the anchor's human-picks
        "budget": {"daily_usd": 2.0, "per_idea_usd": 3.0},  # anchor per_idea ceiling is 8.00
        "rung_policy": {"max_rung": 4, "est_usd_by_rung": {"4-mvp": 0.50}},  # anchor est_usd=1.20
    }
    a = Anchor.model_validate(data)
    eg = a.effective_governance("acme-demo")

    assert eg.dials["4-mvp"] == Dial.propose_only
    assert eg.daily_usd == 2.0
    assert eg.per_idea_usd == 3.0
    assert eg.max_rung == 4
    assert eg.est_usd_by_rung["4-mvp"] == 0.50


def test_vessel_governance_loosen_attempt_is_clamped_not_applied():
    data = _load_raw()
    anchor_default_dial = data["rungs"]["4-mvp"]["dial"]  # human-picks
    anchor_ceiling = data["budgets"]["per_expedition_ceiling_usd"]  # 8.00
    anchor_max_rung = 5  # RUNG_FLAG
    anchor_4mvp_est = data["rungs"]["4-mvp"]["est_usd"]  # 1.20

    data["vessels"][0]["governance"] = {
        "dials": {"4-mvp": "autonomous"},                 # LOOSER than human-picks
        "budget": {"daily_usd": 999.0, "per_idea_usd": 999.0},  # LOOSER than the anchor ceiling
        "rung_policy": {"max_rung": 99, "est_usd_by_rung": {"4-mvp": 999.0}},  # LOOSER
    }
    a = Anchor.model_validate(data)
    eg = a.effective_governance("acme-demo")

    # every loosen attempt is rejected/clamped back to the anchor default — never applied
    assert eg.dials["4-mvp"] == Dial(anchor_default_dial)
    assert eg.dials["4-mvp"] != Dial.autonomous
    assert eg.per_idea_usd == anchor_ceiling
    assert eg.max_rung == anchor_max_rung
    assert eg.est_usd_by_rung["4-mvp"] == anchor_4mvp_est
    # daily_usd: anchor default is None (unbounded); a vessel MAY set one (that's always a
    # tightening relative to "no cap"), so 999.0 is legitimately accepted here.
    assert eg.daily_usd == 999.0


def test_vessel_governance_daily_usd_loosen_against_an_anchor_cap_is_clamped():
    data = _load_raw()
    data["budgets"]["daily_usd"] = 5.0  # anchor sets a daily cap this time
    data["vessels"][0]["governance"] = {"budget": {"daily_usd": 50.0}}  # vessel tries to loosen it
    a = Anchor.model_validate(data)
    eg = a.effective_governance("acme-demo")
    assert eg.daily_usd == 5.0  # clamped back to the anchor's tighter cap, not 50.0


def test_vessel_governance_daily_usd_tighten_against_an_anchor_cap_is_applied():
    data = _load_raw()
    data["budgets"]["daily_usd"] = 5.0
    data["vessels"][0]["governance"] = {"budget": {"daily_usd": 1.0}}  # genuinely tighter
    a = Anchor.model_validate(data)
    eg = a.effective_governance("acme-demo")
    assert eg.daily_usd == 1.0


def test_governance_parses_from_yaml_block_end_to_end():
    data = _load_raw()
    data["vessels"][0]["governance"] = {"budget": {"per_idea_usd": 1.0}}
    new_block = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip()
    text = ANCHOR_PATH.read_text(encoding="utf-8")
    pre, _, post = text.partition("```anchor\n")
    _, _, tail = post.partition("\n```")
    new_text = pre + "```anchor\n" + new_block + "\n```" + tail
    a = Anchor.model_validate(yaml.safe_load(new_block))
    assert a.vessel("acme-demo").governance.budget.per_idea_usd == 1.0
    assert "governance" in new_text  # sanity: the round-tripped text carries the block

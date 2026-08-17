"""V6 #2 — rung 5a (staged-behind-flag) / 5b (prod-promoted) sub-rung split.

Back-compat: RUNG_FLAG (the pre-split rung-5 ordinal) is untouched; the split is additive
labeling via ShipResult.sub_rung + Anchor.rung5_policy(), not a renumbering.
"""
from pathlib import Path

from fls.anchor import Anchor, Dial, RungPolicy
from fls.funnel import RUNG_FLAG
from fls.rung4 import PRPackage
from fls.rung5 import (
    LEGACY_RUNG_5,
    RUNG_5A,
    RUNG_5B,
    FlagStore,
    ReviewabilityRefused,
    enforce_reviewability,
    promote_to_prod,
    ship_to_stage,
    ship_to_stage_reviewed,
)

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"


class OkDeployer:
    def deploy(self, env, ref):
        return True


class FailDeployer:
    def deploy(self, env, ref):
        return False


def test_legacy_rung_5_alias_unchanged():
    assert LEGACY_RUNG_5 == RUNG_FLAG == 5


def test_ship_to_stage_reaches_5a(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text("{}", encoding="utf-8")
    fs = FlagStore(flags_path)
    r = ship_to_stage("cmd-k", "abc123", fs, OkDeployer(), smoke=lambda: True)
    assert r.stage_deployed
    assert r.sub_rung == RUNG_5A
    assert fs.get("cmd-k", "stage") is True
    assert fs.get("cmd-k", "prod") is False


def test_ship_to_stage_smoke_failure_never_reaches_5a(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text("{}", encoding="utf-8")
    fs = FlagStore(flags_path)
    r = ship_to_stage("cmd-k", "abc123", fs, OkDeployer(), smoke=lambda: False)
    assert not r.stage_deployed
    assert r.sub_rung is None


def test_promote_to_prod_reaches_5b_only_with_approval(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text('{"cmd-k": {"stage": true, "prod": false}}', encoding="utf-8")
    fs = FlagStore(flags_path)

    blocked = promote_to_prod("cmd-k", "abc123", fs, OkDeployer(), approved_by=None)
    assert blocked.sub_rung == RUNG_5A          # stays parked at 5a, never auto-ships to 5b
    assert not blocked.prod_deployed
    assert fs.get("cmd-k", "prod") is False

    ok = promote_to_prod("cmd-k", "abc123", fs, OkDeployer(), approved_by="nathan")
    assert ok.sub_rung == RUNG_5B
    assert ok.prod_deployed
    assert fs.get("cmd-k", "prod") is True


def test_promote_to_prod_deploy_failure_stays_at_5a(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text('{"cmd-k": {"stage": true, "prod": false}}', encoding="utf-8")
    fs = FlagStore(flags_path)
    r = promote_to_prod("cmd-k", "abc123", fs, FailDeployer(), approved_by="nathan")
    assert not r.prod_deployed
    assert r.sub_rung == RUNG_5A


def test_full_5a_to_5b_ship_flow(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text("{}", encoding="utf-8")
    fs = FlagStore(flags_path)

    staged = ship_to_stage("cmd-k", "abc123", fs, OkDeployer(), smoke=lambda: True)
    assert staged.sub_rung == RUNG_5A

    promoted = promote_to_prod("cmd-k", "abc123", fs, OkDeployer(), approved_by="nathan")
    assert promoted.sub_rung == RUNG_5B
    assert fs.get("cmd-k", "stage") is True and fs.get("cmd-k", "prod") is True


def test_anchor_rung5_policy_falls_back_to_legacy_5_flagged():
    a = Anchor.load(ANCHOR_PATH)
    # the checked-in demo ANCHOR now declares explicit 5a-staged/5b-prod entries (V6 #2)
    assert a.rung5_policy("5a").dial == Dial.propose_only
    assert a.rung5_policy("5b").dial == Dial.propose_only
    assert a.rungs["5a-staged"].est_usd != a.rungs["5-flagged"].est_usd


def test_anchor_rung5_policy_back_compat_without_split_keys():
    # an ANCHOR that predates the split has no "5a-staged"/"5b-prod" keys at all
    a = Anchor.load(ANCHOR_PATH)
    a.rungs = {k: v for k, v in a.rungs.items() if k not in ("5a-staged", "5b-prod")}
    assert a.rung5_policy("5a") == a.rungs["5-flagged"]
    assert a.rung5_policy("5b") == a.rungs["5-flagged"]
    assert isinstance(a.rung5_policy("5a"), RungPolicy)


# --- Enforced reviewability (Wu, Phase 3): line-budget refusal + mandatory walkthrough --------

def _pkg(diff="+1\n+2\n", walkthrough_url="https://example.test/walkthrough/1"):
    return PRPackage(diff=diff, test_output="ok", eval_score="0.9", corner_cuts=[],
                     walkthrough_url=walkthrough_url)


def test_enforce_reviewability_passes_clean_package():
    enforce_reviewability(_pkg(), line_budget=400)   # no raise


def test_enforce_reviewability_refuses_missing_walkthrough():
    import pytest
    pkg = _pkg(walkthrough_url=None)
    with pytest.raises(ReviewabilityRefused, match="walkthrough"):
        enforce_reviewability(pkg, line_budget=400)


def test_enforce_reviewability_refuses_blank_walkthrough():
    import pytest
    pkg = _pkg(walkthrough_url="   ")
    with pytest.raises(ReviewabilityRefused):
        enforce_reviewability(pkg, line_budget=400)


def test_enforce_reviewability_refuses_over_line_budget():
    import pytest
    huge_diff = "\n".join(f"+line {i}" for i in range(500))
    pkg = _pkg(diff=huge_diff)
    with pytest.raises(ReviewabilityRefused, match="400"):
        enforce_reviewability(pkg, line_budget=400)


def test_enforce_reviewability_counts_only_changed_lines_not_headers():
    diff = "--- a/f.py\n+++ b/f.py\n@@ -1,2 +1,2 @@\n-old\n+new\n context line\n"
    pkg = _pkg(diff=diff)
    enforce_reviewability(pkg, line_budget=2)   # only 1 '-' + 1 '+' changed line -> under budget


def test_ship_to_stage_reviewed_parks_on_refusal_never_deploys(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text("{}", encoding="utf-8")
    fs = FlagStore(flags_path)

    class ExplodingDeployer:
        def deploy(self, env, ref):
            raise AssertionError("deploy must not be called when reviewability is refused")

    r = ship_to_stage_reviewed(_pkg(walkthrough_url=None), 400, "cmd-k", "abc123", fs,
                               ExplodingDeployer(), smoke=lambda: True)
    assert r.reviewability_refused is True
    assert not r.stage_deployed
    assert r.sub_rung is None
    assert fs.get("cmd-k", "stage") is False


def test_ship_to_stage_reviewed_ships_when_clean(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text("{}", encoding="utf-8")
    fs = FlagStore(flags_path)
    r = ship_to_stage_reviewed(_pkg(), 400, "cmd-k", "abc123", fs, OkDeployer(),
                               smoke=lambda: True)
    assert r.reviewability_refused is False
    assert r.sub_rung == RUNG_5A
    assert fs.get("cmd-k", "stage") is True


def test_line_budget_zero_means_no_budget_enforced_walkthrough_still_required():
    # line_budget=0 follows RungSpec's "0 = n/a" convention — skip the size check, but the
    # mandatory walkthrough is never optional
    import pytest
    huge_diff = "\n".join(f"+line {i}" for i in range(5000))
    enforce_reviewability(_pkg(diff=huge_diff), line_budget=0)   # no raise: budget n/a
    with pytest.raises(ReviewabilityRefused):
        enforce_reviewability(_pkg(diff=huge_diff, walkthrough_url=""), line_budget=0)

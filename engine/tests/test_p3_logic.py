"""P3: calibration readout + rung-5 ship flow. Fully stubbed (zero spend)."""
import json
from pathlib import Path

from fls.anchor import Anchor
from fls.calibration import build_report, category_slice, rung_calibration
from fls.ledger import Decision, Ledger
from fls.rung5 import FlagStore, promote_to_prod, ship_to_stage

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


def _ledger(tmp_path, rows):
    led = Ledger(tmp_path / "l.jsonl")
    for r in rows:
        led.record(r)
    return led


def test_calibration_recommends_tighten_on_low_agreement(tmp_path):
    # 10 scored at 1-spec, 60% agreement -> below 80% threshold -> tighten
    rows = [Decision(1, "1-spec", "admit", ("admit" if i >= 4 else "dock"), 0.001) for i in range(10)]
    cal = rung_calibration(_ledger(tmp_path, rows), ANCHOR, "1-spec")
    assert cal.agreement < 0.8
    assert cal.recommendation == "tighten"
    assert cal.disagreements                      # mismatch examples surfaced


def test_calibration_eligible_to_loosen_on_high_agreement(tmp_path):
    rows = [Decision(1, "2-wireframe", "admit", "admit", 0.001) for _ in range(10)]
    cal = rung_calibration(_ledger(tmp_path, rows), ANCHOR, "2-wireframe")
    assert cal.agreement == 1.0
    assert cal.recommendation == "eligible-to-loosen"


def test_calibration_report_and_categories(tmp_path):
    rows = ([Decision(1, "1-spec", "admit", "dock", 0.001)] * 3
            + [Decision(2, "1-spec", "dock", "admit", 0.001)] * 2)
    led = _ledger(tmp_path, rows)
    rpt = build_report(led, ANCHOR)
    assert rpt.total_decisions == 5
    md = rpt.as_markdown()
    assert "Calibration readout" in md and "1-spec" in md
    cats = category_slice(led)
    assert cats["admit->dock"] == 3 and cats["dock->admit"] == 2


def test_ship_to_stage_then_gated_prod(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text(json.dumps({"cmd-k": {"stage": False, "prod": False}}))
    fs = FlagStore(flags_path)

    class OkDeployer:
        def deploy(self, env, ref):
            return True

    # stage: smoke passes -> deployed, flag on in stage, prod still gated
    r = ship_to_stage("cmd-k", "abc123", fs, OkDeployer(), smoke=lambda: True)
    assert r.stage_deployed and fs.get("cmd-k", "stage") is True
    assert fs.get("cmd-k", "prod") is False and r.awaiting_signoff

    # prod promotion blocked without an approver (Environment protection)
    blocked = promote_to_prod("cmd-k", "abc123", fs, OkDeployer(), approved_by=None)
    assert not blocked.prod_deployed and fs.get("cmd-k", "prod") is False
    assert "requires a human reviewer" in blocked.reason

    # with approval -> promoted, flag flipped
    ok = promote_to_prod("cmd-k", "abc123", fs, OkDeployer(), approved_by="nathan")
    assert ok.prod_deployed and fs.get("cmd-k", "prod") is True
    assert not ok.awaiting_signoff


def test_smoke_failure_blocks_stage(tmp_path):
    flags_path = tmp_path / "flags.json"
    flags_path.write_text(json.dumps({"cmd-k": {"stage": False, "prod": False}}))

    class OkDeployer:
        def deploy(self, env, ref):
            return True

    r = ship_to_stage("cmd-k", "abc", FlagStore(flags_path), OkDeployer(), smoke=lambda: False)
    assert not r.stage_deployed and "smoke self-check failed" in r.reason

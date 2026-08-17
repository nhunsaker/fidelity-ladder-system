"""v0.6 #7: judge-calibration mining layer over the ledger's mismatch/override data."""
from pathlib import Path

from fls.anchor import Anchor
from fls.ledger import Decision, Ledger
from fls.mining import (
    DEFAULT_MINE_MIN_INTERVAL_S,
    MiningReport,
    append_snapshot,
    default_history_path,
    mine,
    mine_and_persist,
    mine_if_due,
    read_history,
    should_mine,
)

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


def _ledger(tmp_path, rows, name="l.jsonl"):
    led = Ledger(tmp_path / name)
    for r in rows:
        led.record(r)
    return led


def test_empty_ledger_yields_empty_report():
    rpt = mine(Ledger(Path("unused.jsonl")), ANCHOR, computed_at="2026-08-16T00:00:00+00:00")
    assert rpt.per_rung == []
    assert rpt.mismatches == []
    assert rpt.recommendation == "hold — no calibration data yet"
    assert rpt.computed_at == "2026-08-16T00:00:00+00:00"


def test_report_shape_matches_frozen_contract(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "dock", 0.001),
            Decision(2, "1-spec", "admit", "admit", 0.001)]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR, computed_at="2026-08-16T00:00:00+00:00")
    d = rpt.to_dict()
    assert set(d.keys()) == {"computed_at", "per_rung", "mismatches", "recommendation"}
    assert isinstance(d["computed_at"], str)

    rung_row = d["per_rung"][0]
    assert set(rung_row.keys()) == {"rung", "samples", "agreement_rate", "human_override_rate",
                                     "drift_trend"}
    assert rung_row["rung"] == "1-spec"
    assert rung_row["samples"] == 2
    assert rung_row["agreement_rate"] == 0.5
    assert rung_row["human_override_rate"] == 0.5
    assert rung_row["drift_trend"] in {"improving", "flat", "declining"}

    mismatch_row = d["mismatches"][0]
    assert set(mismatch_row.keys()) == {"rung", "idea_id", "judge_verdict", "human_verdict",
                                         "note"}
    assert mismatch_row["idea_id"] == 1
    assert mismatch_row["judge_verdict"] == "admit"
    assert mismatch_row["human_verdict"] == "dock"


def test_mismatches_only_capture_disagreements(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "admit", 0.001),
            Decision(2, "1-spec", "admit", "dock", 0.001),
            Decision(3, "1-spec", "dock", "admit", 0.001)]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR)
    assert len(rpt.mismatches) == 2
    assert {m.idea_id for m in rpt.mismatches} == {2, 3}


def test_recommendation_tighten_on_low_agreement(tmp_path):
    # 10 scored at 1-spec, 60% agreement -> below the anchor's tighten floor
    rows = [Decision(1, "1-spec", "admit", ("admit" if i >= 4 else "dock"), 0.001)
            for i in range(10)]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR)
    assert "tighten" in rpt.recommendation
    assert "1-spec" in rpt.recommendation


def test_recommendation_eligible_to_loosen_on_high_agreement(tmp_path):
    rows = [Decision(1, "2-wireframe", "admit", "admit", 0.001) for _ in range(10)]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR)
    assert "eligible-to-loosen" in rpt.recommendation
    assert "2-wireframe" in rpt.recommendation


def test_drift_trend_improving_and_declining_against_history(tmp_path):
    # snapshot 1: 50% agreement at 1-spec
    rows_a = [Decision(i, "1-spec", "admit", ("admit" if i % 2 == 0 else "dock"), 0.001)
              for i in range(10)]
    snap_a = mine(_ledger(tmp_path, rows_a, "a.jsonl"), ANCHOR,
                  computed_at="2026-08-01T00:00:00+00:00")

    # snapshot 2: 100% agreement at 1-spec -> improving vs snap_a
    rows_b = [Decision(i, "1-spec", "admit", "admit", 0.001) for i in range(10)]
    snap_b = mine(_ledger(tmp_path, rows_b, "b.jsonl"), ANCHOR, history=[snap_a],
                  computed_at="2026-08-08T00:00:00+00:00")
    assert next(r for r in snap_b.per_rung if r.rung == "1-spec").drift_trend == "improving"

    # snapshot 3: back down to 50% -> declining vs snap_b
    snap_c = mine(_ledger(tmp_path, rows_a, "c.jsonl"), ANCHOR, history=[snap_a, snap_b],
                  computed_at="2026-08-15T00:00:00+00:00")
    assert next(r for r in snap_c.per_rung if r.rung == "1-spec").drift_trend == "declining"


def test_drift_trend_flat_with_no_prior_history(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "admit", 0.001)]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR, history=[])
    assert rpt.per_rung[0].drift_trend == "flat"


def test_append_and_read_history_round_trips(tmp_path):
    path = tmp_path / "mining-history.jsonl"
    rows = [Decision(1, "1-spec", "admit", "dock", 0.001)]
    rpt1 = mine(_ledger(tmp_path, rows, "l1.jsonl"), ANCHOR,
                computed_at="2026-08-01T00:00:00+00:00")
    append_snapshot(rpt1, path)
    assert read_history(path) == [rpt1]

    rpt2 = mine(_ledger(tmp_path, rows, "l2.jsonl"), ANCHOR,
                computed_at="2026-08-02T00:00:00+00:00")
    append_snapshot(rpt2, path)
    history = read_history(path)
    assert len(history) == 2
    assert [h.computed_at for h in history] == ["2026-08-01T00:00:00+00:00",
                                                  "2026-08-02T00:00:00+00:00"]


def test_read_history_missing_file_returns_empty(tmp_path):
    assert read_history(tmp_path / "nope.jsonl") == []


def test_mine_and_persist_uses_prior_snapshots_for_drift(tmp_path):
    path = tmp_path / "mining-history.jsonl"
    rows_low = [Decision(i, "3-demo", "admit", ("admit" if i % 2 == 0 else "dock"), 0.001)
                for i in range(10)]
    rows_high = [Decision(i, "3-demo", "admit", "admit", 0.001) for i in range(10)]

    r1 = mine_and_persist(_ledger(tmp_path, rows_low, "l1.jsonl"), ANCHOR, path,
                           computed_at="2026-08-01T00:00:00+00:00")
    assert next(r for r in r1.per_rung if r.rung == "3-demo").drift_trend == "flat"

    r2 = mine_and_persist(_ledger(tmp_path, rows_high, "l2.jsonl"), ANCHOR, path,
                           computed_at="2026-08-02T00:00:00+00:00")
    assert next(r for r in r2.per_rung if r.rung == "3-demo").drift_trend == "improving"
    assert len(read_history(path)) == 2


def test_default_history_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FLS_MINING_HISTORY_PATH", str(tmp_path / "custom.jsonl"))
    assert default_history_path() == tmp_path / "custom.jsonl"


def test_default_history_path_defaults_under_root(monkeypatch, tmp_path):
    monkeypatch.delenv("FLS_MINING_HISTORY_PATH", raising=False)
    assert default_history_path(tmp_path) == tmp_path / "mining-history.jsonl"


def test_mining_report_from_calibration_module_reexport(tmp_path):
    from fls.calibration import mine as mine_reexport

    rows = [Decision(1, "1-spec", "admit", "admit", 0.001)]
    rpt = mine_reexport(_ledger(tmp_path, rows), ANCHOR)
    assert isinstance(rpt, MiningReport)


# --- v0.7 #3: per-vessel slicing ---------------------------------------------------------

def test_mine_vessel_none_includes_all_rows_backcompat(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "admit", 0.001, vessel="woords"),
            Decision(2, "1-spec", "admit", "dock", 0.001, vessel="sorb"),
            Decision(3, "1-spec", "admit", "admit", 0.001)]  # untagged
    rpt = mine(_ledger(tmp_path, rows), ANCHOR)
    assert rpt.per_rung[0].samples == 3


def test_mine_vessel_filters_to_matching_rows_only(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "admit", 0.001, vessel="woords"),
            Decision(2, "1-spec", "admit", "dock", 0.001, vessel="woords"),
            Decision(3, "1-spec", "admit", "admit", 0.001, vessel="sorb")]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR, vessel="woords")
    assert rpt.per_rung[0].samples == 2
    assert rpt.per_rung[0].agreement_rate == 0.5


def test_mine_vessel_with_no_matching_rows_yields_empty_report(tmp_path):
    rows = [Decision(1, "1-spec", "admit", "admit", 0.001, vessel="sorb")]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR, vessel="woords")
    assert rpt.per_rung == []
    assert "hold" in rpt.recommendation


def test_mine_vessel_shape_still_matches_frozen_contract(tmp_path):
    # per-vessel slicing must not add fields to the frozen MiningReport contract.
    rows = [Decision(1, "1-spec", "admit", "dock", 0.001, vessel="woords")]
    rpt = mine(_ledger(tmp_path, rows), ANCHOR, vessel="woords")
    assert set(rpt.to_dict().keys()) == {"computed_at", "per_rung", "mismatches", "recommendation"}


# --- v0.7 #2: mining-persistence cadence guard ------------------------------------------

def test_should_mine_true_with_no_history():
    assert should_mine([]) is True


def test_should_mine_false_within_min_interval():
    hist = [MiningReport(computed_at="2026-08-16T00:00:00+00:00")]
    assert should_mine(hist, now="2026-08-16T01:00:00+00:00", min_interval_s=DEFAULT_MINE_MIN_INTERVAL_S) is False


def test_should_mine_true_past_min_interval():
    hist = [MiningReport(computed_at="2026-08-15T00:00:00+00:00")]
    assert should_mine(hist, now="2026-08-16T01:00:00+00:00", min_interval_s=DEFAULT_MINE_MIN_INTERVAL_S) is True


def test_should_mine_true_on_malformed_prior_timestamp_fail_open():
    hist = [MiningReport(computed_at="not-a-timestamp")]
    assert should_mine(hist, now="2026-08-16T01:00:00+00:00") is True


def test_should_mine_respects_custom_min_interval():
    hist = [MiningReport(computed_at="2026-08-16T00:00:00+00:00")]
    assert should_mine(hist, now="2026-08-16T00:00:30+00:00", min_interval_s=60) is False
    assert should_mine(hist, now="2026-08-16T00:02:00+00:00", min_interval_s=60) is True


def test_mine_if_due_persists_when_stale_and_skips_when_fresh(tmp_path):
    path = tmp_path / "mining-history.jsonl"
    rows = [Decision(1, "1-spec", "admit", "dock", 0.001)]
    led = _ledger(tmp_path, rows)

    r1 = mine_if_due(led, ANCHOR, path, now="2026-08-16T00:00:00+00:00")
    assert r1 is not None
    assert len(read_history(path)) == 1

    # a second call moments later (well within the default 24h interval) is a no-op
    r2 = mine_if_due(led, ANCHOR, path, now="2026-08-16T00:00:05+00:00")
    assert r2 is None
    assert len(read_history(path)) == 1  # unchanged — no duplicate accrual

    # a call a day later is due again
    r3 = mine_if_due(led, ANCHOR, path, now="2026-08-17T00:00:01+00:00")
    assert r3 is not None
    assert len(read_history(path)) == 2

"""`fls bench` — the three metrics compute correctly, false-advance detection is right, and a
run is deterministic. All zero-spend: stub judge + stub cost_model, no clock, no RNG."""
import pytest

from fls.bench import (
    BAD,
    GOOD,
    AltitudeStat,
    BenchSeed,
    FaithfulSeed,
    default_cost_model,
    make_faithful_bench_judge,
    oracle_judge,
    render_scoreboard,
    run_bench,
)
from fls.bench_seeds import ALL_SEEDS, WEB_UI_SEEDS
from fls.profile import WEB_LADDER_PROFILE

# --- seed contract ---------------------------------------------------------------------------

def test_bad_seed_must_declare_should_catch_by_rung():
    with pytest.raises(ValueError):
        BenchSeed("x", "web-ui", BAD, "wrong thing")  # no should_catch_by_rung


def test_direction_must_be_good_or_bad():
    with pytest.raises(ValueError):
        BenchSeed("x", "web-ui", "sideways", "?")


def test_good_seed_needs_no_bound():
    s = BenchSeed("g", "web-ui", GOOD, "the right thing")
    assert s.should_catch_by_rung is None


# --- metric 1: rung-of-catch -----------------------------------------------------------------

def test_rung_of_catch_uses_the_declared_bound_under_oracle():
    # oracle catches each bad seed exactly at its should_catch_by_rung
    seeds = [
        BenchSeed("b1", "v", BAD, "spec-visible wrong", should_catch_by_rung=1),
        BenchSeed("b4", "v", BAD, "contract wrong", should_catch_by_rung=4),
        BenchSeed("g1", "v", GOOD, "right"),
    ]
    rep = run_bench(seeds)
    by_id = {s.seed_id: s for s in rep.seeds}
    assert by_id["b1"].rung_of_catch == 1
    assert by_id["b4"].rung_of_catch == 4
    assert by_id["g1"].rung_of_catch is None          # good seeds advance clean
    assert rep.rung_of_catch == {1: 1, 4: 1}          # distribution over bad seeds only


def test_good_seed_advancing_is_not_a_false_catch_under_oracle():
    rep = run_bench([BenchSeed("g", "v", GOOD, "right")])
    assert rep.false_catch_rate == 0.0
    assert rep.seeds[0].false_catch is False


# --- metric 2: cost-to-catch per rung (fraction of full code-cost) ---------------------------

def test_cost_fraction_is_cumulative_over_full_climb():
    # with the default illustrative weights: 0,.05,.10,.25,1.0,.20 -> full = 1.60
    # catch at rung 1 -> cumulative through rung 1 = 0 + .05 = .05 ; frac = .05/1.60 = 0.0313
    seed = BenchSeed("b", "v", BAD, "spec wrong", should_catch_by_rung=1)
    rep = run_bench([seed])
    res = rep.seeds[0]
    assert res.full_climb_cost == pytest.approx(1.60)
    assert res.cost_to_catch == pytest.approx(0.05)
    assert res.cost_fraction == pytest.approx(0.05 / 1.60, abs=1e-3)
    # catching at rung 1 costs a small single-digit % of code-cost — the thesis, quantified
    assert res.cost_fraction < 0.05
    assert rep.cost_to_catch_per_rung[1] == pytest.approx(0.05 / 1.60, abs=1e-3)


def test_deeper_catch_costs_more():
    r1 = run_bench([BenchSeed("b1", "v", BAD, "x", should_catch_by_rung=1)])
    r4 = run_bench([BenchSeed("b4", "v", BAD, "y", should_catch_by_rung=4)])
    assert r4.seeds[0].cost_fraction > r1.seeds[0].cost_fraction  # code is the expensive place


# --- metric 3: false-advance detection -------------------------------------------------------

def test_false_advance_when_judge_catches_too_late():
    # a judge that never fires below rung 4: a seed whose wrongness was knowable at rung 1
    # advances past its bound -> false advance.
    def late_judge(seed, rung):
        return seed.direction == BAD and rung.number >= 4

    seeds = [BenchSeed("b", "v", BAD, "spec-visible", should_catch_by_rung=1)]
    rep = run_bench(seeds, judge=late_judge)
    assert rep.seeds[0].rung_of_catch == 4
    assert rep.seeds[0].false_advance is True
    assert rep.false_advance_rate == 1.0


def test_false_advance_when_never_caught():
    def blind_judge(seed, rung):
        return False

    seeds = [BenchSeed("b", "v", BAD, "slips through", should_catch_by_rung=2)]
    rep = run_bench(seeds, judge=blind_judge)
    assert rep.seeds[0].rung_of_catch is None
    assert rep.seeds[0].false_advance is True
    assert rep.rung_of_catch == {-1: 1}               # -1 == never caught
    assert rep.false_advance_rate == 1.0


def test_oracle_has_zero_false_advance_by_construction():
    rep = run_bench(ALL_SEEDS)
    assert rep.false_advance_rate == 0.0              # perfect ladder never advances a bad seed late


def test_false_catch_when_good_seed_is_rejected():
    def trigger_happy(seed, rung):
        return rung.number >= 1                        # catches everything, incl. good seeds

    rep = run_bench([BenchSeed("g", "v", GOOD, "right thing")], judge=trigger_happy)
    assert rep.seeds[0].false_catch is True
    assert rep.false_catch_rate == 1.0


# --- determinism -----------------------------------------------------------------------------

def test_run_is_deterministic():
    a = run_bench(ALL_SEEDS)
    b = run_bench(ALL_SEEDS)
    assert a == b                                     # frozen dataclasses compare by value


def test_report_is_frozen():
    from dataclasses import FrozenInstanceError

    rep = run_bench(WEB_UI_SEEDS)
    with pytest.raises(FrozenInstanceError):
        rep.false_advance_rate = 0.5                  # frozen — cannot mutate a scored number


# --- vessels ---------------------------------------------------------------------------------

def test_seed_set_spans_at_least_two_vessels():
    rep = run_bench(ALL_SEEDS)
    assert len(rep.vessels) >= 2
    assert set(rep.vessels) == {"web-ui", "dashboard"}


def test_per_vessel_slice():
    rep = run_bench(ALL_SEEDS)
    web = rep.per_vessel("web-ui")
    assert len(web) == len(WEB_UI_SEEDS)
    assert all(r.vessel == "web-ui" for r in web)


def test_every_starter_seed_carries_a_direction():
    for s in ALL_SEEDS:
        assert s.direction in (GOOD, BAD)
        if s.direction == BAD:
            assert s.should_catch_by_rung is not None


# --- altitude (second number) ----------------------------------------------------------------

def test_altitude_stat_rate_and_line():
    # the real N=10 ablation: 10/10 first-attempt with acceptance-as-code; 8/10 without
    on = AltitudeStat(n=10, first_attempt_passes=10, condition="acceptance-as-code in context")
    off = AltitudeStat(n=10, first_attempt_passes=8, condition="acceptance withheld (ablation)")
    assert on.rate == 1.0
    assert off.rate == 0.8
    assert "100%" in on.line()
    assert "N=10" in off.line()


def test_altitude_zero_n_is_safe():
    assert AltitudeStat(n=0, first_attempt_passes=0).rate == 0.0


# --- stubs & rendering -----------------------------------------------------------------------

def test_default_cost_model_is_monotone_toward_code():
    profile = WEB_LADDER_PROFILE
    seed = BenchSeed("s", "v", GOOD, "x")
    costs = [default_cost_model(seed, profile.rung(n)) for n in range(6)]
    assert costs[4] == max(costs)                     # rung 4 (mvp-code) is the dearest


def test_oracle_never_catches_good_seeds():
    seed = BenchSeed("g", "v", GOOD, "x")
    assert all(oracle_judge(seed, WEB_LADDER_PROFILE.rung(n)) is False for n in range(6))


def test_headline_reports_no_catch_when_ladder_is_blind():
    def blind_judge(seed, rung):
        return False

    rep = run_bench([BenchSeed("b", "v", BAD, "x", should_catch_by_rung=1)], judge=blind_judge)
    assert "caught NONE" in rep.headline


def test_render_scoreboard_is_a_string_with_the_three_metrics():
    out = render_scoreboard(run_bench(ALL_SEEDS))
    assert "rung-of-catch" in out
    assert "cost-to-catch" in out
    assert "false-advance" in out
    assert "HEADLINE" in out


# --- faithful seed model (v8) ----------------------------------------------------------------

def _faithful(id="s", vessel="v", direction=GOOD, should_catch_by_rung=None, artifacts=None):
    return FaithfulSeed(
        id, vessel, direction,
        intent="do the asked thing",
        artifacts=artifacts or {1: "spec", 2: "wire", 3: "demo", 4: "code"},
        should_catch_by_rung=should_catch_by_rung,
    )


def test_faithful_bad_seed_must_declare_should_catch_by_rung():
    with pytest.raises(ValueError):
        FaithfulSeed("x", "v", BAD, intent="i", artifacts={1: "a"})


def test_faithful_seed_needs_at_least_one_artifact():
    with pytest.raises(ValueError):
        FaithfulSeed("x", "v", GOOD, intent="i", artifacts={})


def test_faithful_direction_must_be_good_or_bad():
    with pytest.raises(ValueError):
        FaithfulSeed("x", "v", "sideways", intent="i", artifacts={1: "a"})


def test_artifact_at_falls_back_to_nearest_lower_rung():
    s = _faithful(artifacts={1: "spec", 4: "code"})
    assert s.artifact_at(0) is None          # rung 0: nothing built yet
    assert s.artifact_at(1) == "spec"
    assert s.artifact_at(3) == "spec"        # no rung-3 artifact -> most concrete built so far
    assert s.artifact_at(4) == "code"
    assert s.artifact_at(5) == "code"        # flag rung falls back to code


def test_faithful_description_shim_is_the_intent():
    s = _faithful()
    assert s.description == "do the asked thing"


class _ScriptedJudge:
    """A zero-spend fake Judge: returns whatever the (seed_id, rung) map says, else FAITHFUL."""
    def __init__(self, diverges_at):
        self.diverges_at = diverges_at   # set of (seed_id, rung_number) that should say DIVERGES
        self.calls = []

    def complete(self, prompt, max_tokens=16, system=None):
        # the fake keys off the prompt containing the seed's intent + artifact; the harness passes
        # rung + seed via the closure, so we recover them from a marker we plant in the artifact.
        from fls.llm import Call
        verdict = "DIVERGES" if self._hit(prompt) else "FAITHFUL"
        self.calls.append(verdict)
        return verdict, Call("stub", "stub", funded_by="none")

    def _hit(self, prompt):
        return any(marker in prompt for marker in self.diverges_at)


def test_faithful_judge_maps_diverges_to_caught_and_runs_through_harness():
    # a bad seed whose rung-2 artifact carries a marker the scripted judge flags as DIVERGES
    seed = FaithfulSeed(
        "fb", "v", BAD, should_catch_by_rung=2,
        intent="the asked thing",
        artifacts={1: "clean spec", 2: "DIVERGENT-WIRE marker", 3: "demo", 4: "code"},
    )
    judge = _ScriptedJudge(diverges_at={"DIVERGENT-WIRE"})
    rep = run_bench([seed], judge=make_faithful_bench_judge(judge))
    res = rep.seeds[0]
    assert res.rung_of_catch == 2            # caught exactly where the divergence appears
    assert res.false_advance is False        # on time (== should_catch_by_rung)


def test_faithful_judge_never_flags_a_clean_good_seed():
    seed = _faithful(direction=GOOD)         # all artifacts are plain, no divergence markers
    judge = _ScriptedJudge(diverges_at=set())
    rep = run_bench([seed], judge=make_faithful_bench_judge(judge))
    assert rep.seeds[0].false_catch is False
    assert rep.seeds[0].rung_of_catch is None


def test_faithful_judge_only_calls_model_on_explicit_artifact_rungs():
    # Only rungs with a DISTINCT builder artifact are automated-judge rungs. Rung 0 (bare intent)
    # and rung 5 (human sign-off) are never judged — nor any rung the builder didn't produce.
    seed = _faithful(direction=GOOD, artifacts={1: "spec", 4: "code"})
    judge = _ScriptedJudge(diverges_at=set())
    run_bench([seed], judge=make_faithful_bench_judge(judge))
    assert len(judge.calls) == 2                          # only rung 1 and rung 4 were judged


def test_faithful_judge_does_not_rejudge_code_at_the_flag_rung():
    # A full 1..4 corpus seed: the model is asked at rungs 1,2,3,4 — never at rung 0 or rung 5.
    seed = _faithful(direction=GOOD)                      # artifacts {1,2,3,4}
    judge = _ScriptedJudge(diverges_at=set())
    run_bench([seed], judge=make_faithful_bench_judge(judge))
    assert len(judge.calls) == 4


# --- faithful corpus integrity ---------------------------------------------------------------

def test_faithful_corpus_spans_three_vessels_and_is_direction_labeled():
    from fls.bench_faithful_seeds import _REVIEWER_B, _WHY, ALL_FAITHFUL

    vessels = {s.vessel for s in ALL_FAITHFUL}
    assert {"web-ui", "dashboard", "cli"} <= vessels     # v9 added a third vessel (cli)
    assert len(ALL_FAITHFUL) >= 24                        # v9 roughly doubled the corpus
    ids = [s.id for s in ALL_FAITHFUL]
    assert len(ids) == len(set(ids))                     # ids are unique
    for s in ALL_FAITHFUL:
        assert s.direction in (GOOD, BAD)
        assert s.intent and s.artifacts
        assert s.id in _WHY                              # reviewer-A labeling one-liner
        assert s.id in _REVIEWER_B                       # reviewer-B independent label
        if s.direction == BAD:
            assert s.should_catch_by_rung in (1, 2, 3, 4)
            # a bad seed's divergence must be reachable: an artifact at/after its catch rung exists
            assert any(r >= s.should_catch_by_rung for r in s.artifacts)


def test_faithful_corpus_has_good_and_bad_and_spans_catch_rungs():
    from fls.bench_faithful_seeds import ALL_FAITHFUL

    good = [s for s in ALL_FAITHFUL if s.direction == GOOD]
    bad = [s for s in ALL_FAITHFUL if s.direction == BAD]
    assert good and bad
    catch_rungs = {s.should_catch_by_rung for s in bad}
    assert catch_rungs == {1, 2, 3, 4}                  # every rung 1..4 is represented
    # the noisy part is the later rungs — ensure the corpus is weighted there, not just at spec
    assert sum(1 for s in bad if s.should_catch_by_rung >= 2) >= 8


# --- two-labeler agreement record (v9) -------------------------------------------------------

def test_every_admitted_seed_carries_both_reviewers_labels():
    from fls.bench_faithful_seeds import _REVIEWER_B, ALL_FAITHFUL

    for s in ALL_FAITHFUL:
        b_dir, b_scb, b_why = _REVIEWER_B[s.id]
        assert b_dir in (GOOD, BAD)
        assert b_why                                     # a non-empty independent one-liner
        if b_dir == GOOD:
            assert b_scb is None


def test_admitted_seeds_have_direction_agreement():
    # ALL_FAITHFUL is, by definition, the set both reviewers agreed on (direction). Verify it.
    from fls.bench_faithful_seeds import _REVIEWER_B, ALL_FAITHFUL

    for s in ALL_FAITHFUL:
        b_dir, _, _ = _REVIEWER_B[s.id]
        assert b_dir == s.direction, f"{s.id}: admitted but directions disagree"


def test_scb_disagreements_are_reconciled_to_the_lower_rung():
    # protocol §2.3: a one-rung scb gap is reconciled to the LOWER rung. The admitted seed's own
    # should_catch_by_rung must never be ABOVE reviewer B's — i.e. we always took the lower claim.
    from fls.bench_faithful_seeds import _REVIEWER_B, ALL_FAITHFUL

    for s in ALL_FAITHFUL:
        if s.direction != BAD:
            continue
        _, b_scb, _ = _REVIEWER_B[s.id]
        assert abs(s.should_catch_by_rung - b_scb) <= 1  # never more than a one-rung gap
        assert s.should_catch_by_rung <= b_scb           # kept the lower (earlier) rung


def test_excluded_seeds_are_recorded_not_scored():
    from fls.bench_faithful_seeds import _EXCLUDED, ALL_FAITHFUL

    admitted = {s.id for s in ALL_FAITHFUL}
    assert _EXCLUDED                                     # exclusions actually happened
    for xid, rec in _EXCLUDED.items():
        assert xid not in admitted                       # never scored
        assert rec["reviewer_a"] and rec["reviewer_b"]   # both one-liners recorded
        assert rec["reviewer_a"][:4] != rec["reviewer_b"][:4]  # they genuinely disagree


def test_two_labeler_agreement_numbers_are_honest():
    from fls.bench_faithful_seeds import two_labeler_agreement

    agr = two_labeler_agreement()
    assert agr["n_admitted"] >= 24
    assert agr["n_excluded"] >= 1
    # direction agreement is admitted / (admitted + excluded) — below 1.0 because exclusions exist
    assert 0.8 <= agr["direction_agreement"] < 1.0
    # every bad seed's scb is either an exact match or a one-rung reconciliation (no >1 conflicts)
    assert agr["scb_conflicts"] == 0
    assert agr["scb_exact"] + agr["scb_reconciled"] == agr["n_bad"]

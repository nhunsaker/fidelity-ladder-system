"""v0.8 Phase 3 — the ledger as a portable trace contract.

Three things under test:
  1. The trace contract round-trips through disk with every field intact (TraceLog.append/load).
  2. trace #3 (fls-v0.8-framework.md §10): an interrupted climb resumes from the trace alone —
     no in-memory harness object survives the "crash," only the jsonl file does — and reaches
     the same final state as an uninterrupted run, without re-running already-completed rungs.
  3. The lagged-outcome `Decision.outcome` column is additive: a legacy jsonl row written before
     the column existed still loads cleanly, with `outcome=None`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.climb import advance_expedition, resume_from_ledger
from fls.expedition import AWAIT_PICK, RESUMING, Expedition
from fls.funnel import RUNG_DEMO, RUNG_FLAG
from fls.ledger import Decision, Ledger, TraceLog, Transition
from fls.llm import Call
from fls.rung3 import WalkthroughResult
from fls.verifier import Outcome, VerifierResult

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


class StubBuilder:
    def complete(self, prompt, max_tokens=1024, system=None):
        return "<html>demo/mvp</html>", Call("stub", "stub", 100, 200, 0.01)


class CountingWalk:
    """A walkthrough stub that counts how many times it actually ran — the proof that a
    resumed climb does NOT re-run rung 3."""
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = 0

    def run(self, demo_path, acceptance):
        self.calls += 1
        return WalkthroughResult(self.ok, "ok" if self.ok else "flow broke")


class Verify:
    def __init__(self, outcome=Outcome.passed, ev=None):
        self.outcome, self.ev = outcome, ev or {"eval_score": "0.95"}

    def verify(self, artifact_dir):
        return VerifierResult(self.outcome, "d", self.ev)


def _idea(number=1):
    return Idea(number, "cmd-k search", "cmd-k focuses search from any screen", "feature")


def _exp(target, number=1):
    e = Expedition(number, _idea(number), target_rung=target)
    e.spec = "cmd-k focuses search"
    return e


# --- 1. trace contract completeness ------------------------------------------------------

def test_transition_round_trips_every_field(tmp_path):
    t = Transition(
        expedition=42, seq=0, kind="rung-advance", rung=RUNG_DEMO, status="climbing",
        target_rung=RUNG_FLAG, idea={"number": 42, "intent": "x", "success": "y",
                                      "altitude": "feature", "source": "manual"},
        dial="human-picks", spec="the spec", picked_wireframe=1, reason="on track",
        spent_usd=0.42, at=1000.0,
    )
    log = TraceLog(tmp_path / "trace.jsonl")
    log.append(t)

    reloaded = TraceLog(tmp_path / "trace.jsonl").load()
    assert len(reloaded.rows) == 1
    got = reloaded.rows[0]
    # every documented trace-contract field survives the round trip unchanged
    for f in ("expedition", "seq", "kind", "rung", "status", "target_rung", "idea", "dial",
              "spec", "picked_wireframe", "reason", "spent_usd", "at"):
        assert getattr(got, f) == getattr(t, f), f"field {f} did not round-trip"


def test_trace_log_next_seq_and_for_expedition_ordering(tmp_path):
    log = TraceLog(tmp_path / "trace.jsonl")
    for i, kind in enumerate(["admitted", "rung-advance", "await-pick"]):
        log.append(Transition(expedition=1, seq=log.next_seq(1), kind=kind, rung=i,
                              status="climbing", target_rung=RUNG_FLAG, idea={"number": 1}))
    # a second expedition interleaved shouldn't perturb #1's ordering/seq
    log.append(Transition(expedition=2, seq=log.next_seq(2), kind="admitted", rung=0,
                          status="climbing", target_rung=RUNG_FLAG, idea={"number": 2}))

    rows1 = log.for_expedition(1)
    assert [r.kind for r in rows1] == ["admitted", "rung-advance", "await-pick"]
    assert [r.seq for r in rows1] == [0, 1, 2]
    assert log.latest(1).kind == "await-pick"
    assert log.latest(2).kind == "admitted"
    assert log.latest(999) is None


# --- 2. trace #3: interrupt mid-rung -> resume from the ledger alone ---------------------

def test_resume_from_ledger_reaches_same_state_without_redoing_rung3(tmp_path):
    # --- reference: an uninterrupted climb straight to the rung-5 gate ---
    ref_walk = CountingWalk(ok=True)
    ref_e = advance_expedition(_exp(RUNG_FLAG, number=1), "<div>wire</div>", ANCHOR,
                               StubBuilder(), ref_walk, Verify(Outcome.passed),
                               str(tmp_path / "ref"), str(tmp_path / "ref" / "L.md"))
    assert ref_walk.calls == 1

    # --- the interrupted run: only get through rung 3, writing checkpoints as we go ---
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceLog(trace_path)
    walk = CountingWalk(ok=True)
    interrupted = advance_expedition(_exp(RUNG_DEMO, number=2), "<div>wire</div>", ANCHOR,
                                     StubBuilder(), walk, Verify(Outcome.passed),
                                     str(tmp_path / "live"), str(tmp_path / "live" / "L.md"),
                                     trace=trace)
    assert interrupted.rung == RUNG_DEMO
    assert interrupted.status == AWAIT_PICK  # demo-lane checkpoint, durably written
    assert walk.calls == 1

    # "the harness dies" — drop every in-memory object, keep only the jsonl file on disk
    del interrupted, trace, walk

    # --- a DIFFERENT process reads only the file and rebuilds the expedition ---
    fresh_trace = TraceLog(trace_path).load()
    resumed = resume_from_ledger(2, fresh_trace)
    assert resumed.rung == RUNG_DEMO
    assert resumed.spent_usd > 0  # the checkpoint's cumulative spend carried forward
    assert resumed.spec == "cmd-k focuses search"

    # the original climb was always meant to go all the way to the rung-5 gate; resume it
    resumed.target_rung = RUNG_FLAG
    resumed_walk = CountingWalk(ok=True)
    final = advance_expedition(resumed, "<div>wire</div>", ANCHOR, StubBuilder(), resumed_walk,
                               Verify(Outcome.passed), str(tmp_path / "live"),
                               str(tmp_path / "live" / "L.md"), trace=fresh_trace)

    # same final state as the uninterrupted reference run...
    assert final.rung == ref_e.rung
    assert final.status == ref_e.status
    assert final.reason == ref_e.reason
    # ...and rung 3 was NOT re-run on resume (the whole point of resume-from-ledger)
    assert resumed_walk.calls == 0

    # the trace file itself now has both halves of the climb for expedition #2: the rung-3
    # checkpoint(s) from the interrupted run, followed by the rung-4/5 checkpoint from resume
    rows = TraceLog(trace_path).load().for_expedition(2)
    assert [r.kind for r in rows] == [
        "rung-advance",  # rung 3 done (the interrupted run)
        "await-pick",    # demo-lane park (the interrupted run's last checkpoint)
        "rung-advance",  # rung 4 done (resume — rung 3 was skipped, not repeated)
        "await-signoff",  # rung 5 gate (resume)
    ]
    assert [r.seq for r in rows] == [0, 1, 2, 3]  # seq kept incrementing across the "restart"


def test_resume_from_ledger_raises_when_no_rows(tmp_path):
    trace = TraceLog(tmp_path / "trace.jsonl")
    with pytest.raises(ValueError):
        resume_from_ledger(999, trace)


def test_resume_from_ledger_flags_mid_flight_climbing_as_resuming(tmp_path):
    # a checkpoint written while status was still "climbing" (no terminal state reached) is the
    # genuinely-interrupted case — resume should surface RESUMING, not a stale "climbing"
    trace = TraceLog(tmp_path / "trace.jsonl")
    trace.append(Transition(expedition=5, seq=0, kind="rung-advance", rung=RUNG_DEMO,
                            status="climbing", target_rung=RUNG_FLAG,
                            idea={"number": 5, "intent": "x", "success": "y",
                                  "altitude": "feature", "source": "manual"}))
    resumed = resume_from_ledger(5, trace)
    assert resumed.status == RESUMING


def test_advance_expedition_without_trace_is_unaffected(tmp_path):
    # the historical call shape (no trace=) must behave exactly as before — no checkpoints,
    # no new required args
    e = advance_expedition(_exp(RUNG_FLAG, number=9), "<div>wire</div>", ANCHOR, StubBuilder(),
                           CountingWalk(ok=True), Verify(Outcome.passed), str(tmp_path),
                           str(tmp_path / "L.md"))
    assert e.status == "await-signoff"


# --- 3. the lagged-outcome column is additive/back-compat --------------------------------

def test_decision_outcome_defaults_none_and_is_additive(tmp_path):
    p = tmp_path / "ledger.jsonl"
    # a LEGACY row, written as if by pre-v0.8 code that has never heard of `outcome`
    legacy_row = {"expedition": 1, "rung": "1-spec", "judge_verdict": "admit",
                  "human_verdict": None, "judge_cost_usd": 0.001}
    p.write_text(json.dumps(legacy_row) + "\n", encoding="utf-8")

    loaded = Ledger(p).load()
    assert len(loaded.rows) == 1
    assert loaded.rows[0].outcome is None  # missing key -> default, not a load failure

    # a fresh row can now carry the lagged outcome once observed
    loaded.record(Decision(2, "1-spec", "admit", "admit", 0.001, outcome="shipped-and-kept"))
    reloaded = Ledger(p).load()
    assert reloaded.rows[-1].outcome == "shipped-and-kept"
    # the legacy row is untouched by the schema addition
    assert reloaded.rows[0].outcome is None

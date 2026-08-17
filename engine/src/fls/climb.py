"""advance_expedition — the upper-ladder climb (rungs 3->4->await-5), resumed after a human pick.

Separated from controller.run_batch (the admission+funnel+paper-ladder half) because this half
needs a human decision first: rung 2 is `human-picks`, so an expedition parks at AWAIT_PICK and a
human (or, for the auto_build lane in a demo, an auto-pick) supplies the winning wireframe. This
function resumes from that pick and drives:

  rung 3 (auto-advance-with-audit): build demo + walkthrough; a failed walkthrough DESCENDS.
  rung 4 (human-picks entry, then the retry/descend loop): build MVP; pass -> AWAIT rung-5 sign-off.
  rung 5 (propose-only, hard gate): draft PR behind a flag -> AWAIT_SIGNOFF (never auto-ships).

Descent at any design failure returns the expedition to rung 2 with the lesson recorded.

v0.8 Phase 3 — durability: `advance_expedition` takes an optional `trace` (`fls.ledger.TraceLog`)
and, when given one, writes a `Transition` checkpoint after every rung-3/4/5 state change. It is
also rung-AWARE now (`e.rung` gates each block, not just `e.target_rung`): a call on an expedition
that has already reached rung 3/4 (because it was reconstructed by `resume_from_ledger` after an
interruption) skips the already-completed work instead of re-running it and re-spending. Fresh
expeditions (the historical case — always `rung=RUNG_INTENT` on entry here) are unaffected: the
new guards are a strict superset of the old `target_rung`-only checks.
"""
from __future__ import annotations

from dataclasses import asdict

from fls.adjudicator import Idea
from fls.anchor import Anchor, Dial
from fls.expedition import AWAIT_PICK, CLIMBING, RESUMING, Expedition
from fls.funnel import RUNG_DEMO, RUNG_FLAG, RUNG_MVP, RUNG_WIRE
from fls.ledger import TraceLog, Transition
from fls.llm import Call
from fls.modules import dispatch_middleware
from fls.profile import WEB_LADDER_PROFILE, LadderProfile
from fls.rung1 import Builder
from fls.rung3 import Walkthrough, run_rung3
from fls.rung4 import BoundedContext, run_rung4
from fls.verifier import Verifier

AWAIT_SIGNOFF = "await-signoff"
DESCENDED = "descended"


def _checkpoint(e: Expedition, trace: TraceLog | None, kind: str, *, at: float | None = None) -> None:
    """Write one durable trace row for `e`'s current state, if a `trace` was supplied. A no-op
    when `trace` is None so `advance_expedition` stays usable exactly as before for callers that
    don't want durability (every existing call site/test)."""
    if trace is None:
        return
    trace.append(Transition(
        expedition=e.number,
        seq=trace.next_seq(e.number),
        kind=kind,
        rung=e.rung,
        status=e.status,
        target_rung=e.target_rung,
        idea=asdict(e.idea),
        dial=e.dial.value if e.dial else None,
        spec=e.spec,
        picked_wireframe=e.picked_wireframe,
        reason=e.reason,
        spent_usd=e.spent_usd,
        at=at,
    ))


def advance_expedition(e: Expedition, picked_wireframe: str, anchor: Anchor,
                       builder: Builder, walkthrough: Walkthrough, verifier: Verifier,
                       artifact_dir: str, lessons_path: str,
                       profile: LadderProfile = WEB_LADDER_PROFILE,
                       trace: TraceLog | None = None) -> Expedition:
    ceiling = anchor.budgets.per_expedition_ceiling_usd
    e.status = CLIMBING

    # ---- rung 3: interactive demo + walkthrough (auto-advance-with-audit) ----
    if e.target_rung >= RUNG_DEMO:
        if e.rung < RUNG_DEMO:  # not yet completed — fresh climb, or resumed before this point
            dispatch_middleware("before_rung", expedition=e, rung=RUNG_DEMO)
            r3 = run_rung3(e.idea, e.spec or e.idea.intent, picked_wireframe,
                           builder, walkthrough, artifact_dir, e.number)
            e.add(r3.calls)
            if e.spent_usd > ceiling:
                e.status, e.reason = "parked", f"budget ceiling ${ceiling} hit at rung 3"
                _checkpoint(e, trace, "parked")
                return e
            if not r3.walkthrough.passed:  # design signal -> descend to wireframe
                e.rung, e.status = RUNG_WIRE, DESCENDED
                e.reason = f"rung-3 walkthrough failed: {r3.walkthrough.detail}"
                dispatch_middleware("on_descend", expedition=e, rung=RUNG_DEMO, reason=e.reason)
                _checkpoint(e, trace, "descended")
                return e
            e.rung = RUNG_DEMO
            dispatch_middleware("after_rung", expedition=e, rung=RUNG_DEMO)
            _checkpoint(e, trace, "rung-advance")
        # else: resumed at/past rung 3 already — fall through without redoing the work/spend
    else:
        e.status = AWAIT_PICK  # demo lane only; parks after wireframe (shouldn't reach here)
        _checkpoint(e, trace, "await-pick")
        return e

    # ---- rung 4: MVP loop (retry vs descend) ----
    if e.target_rung >= RUNG_MVP:
        if e.rung < RUNG_MVP:  # not yet completed — fresh climb, or resumed before this point
            dispatch_middleware("before_rung", expedition=e, rung=RUNG_MVP)
            ctx = BoundedContext(spec=e.spec or e.idea.intent, wireframe=picked_wireframe,
                                 acceptance_test=getattr(e, "acceptance_stub", "") or "")
            dispatch_middleware("on_context_assembly", expedition=e, rung=RUNG_MVP, context=ctx)
            mvp = profile.rung(RUNG_MVP)  # rungs-as-config: caps from the profile, not hardcoded
            r4 = run_rung4(e.number, ctx, builder, verifier, artifact_dir, lessons_path,
                           max_retries=mvp.max_retries, from_rung=RUNG_MVP, to_rung=RUNG_WIRE,
                           builder_max_tokens=mvp.builder_max_tokens)
            e.add(r4.calls)
            if not r4.passed:  # descended with a lesson
                e.rung, e.status = RUNG_WIRE, DESCENDED
                e.reason = r4.lesson.detail if r4.lesson else "rung-4 design failure"
                dispatch_middleware("on_descend", expedition=e, rung=RUNG_MVP, reason=e.reason)
                _checkpoint(e, trace, "descended")
                return e
            e.rung = RUNG_MVP
            dispatch_middleware("after_rung", expedition=e, rung=RUNG_MVP)
            _checkpoint(e, trace, "rung-advance")
        # else: resumed at/past rung 4 already — fall through without redoing the work/spend

        # ---- rung 5: hard gate — draft PR behind flag, never auto-ships ----
        # V6 #2: rung 5 is governed as two sub-rungs (see fls.rung5) — 5a (staged behind the
        # flag, via ship_to_stage) then 5b (prod-promoted, via promote_to_prod). This climb
        # only ever parks an expedition at the gate entering 5a; a human/caller drives the
        # actual 5a->5b ship flow afterward (never auto-ships past this point).
        if e.target_rung >= RUNG_FLAG:
            e.rung, e.status = RUNG_FLAG, AWAIT_SIGNOFF
            policy_5a = anchor.rung5_policy("5a")
            e.reason = (
                f"draft PR behind feature flag (rung 5a dial={policy_5a.dial.value}); "
                "awaiting human sign-off to stage (5a), then Environment-gated prod "
                "promotion (5b)"
            )
        else:
            e.status = AWAIT_SIGNOFF
        _checkpoint(e, trace, "await-signoff")
        return e

    # demo lane (target == rung 3): parks after a passing walkthrough for the human shelf
    e.status = AWAIT_PICK
    e.reason = "interactive demo ready on the shelf"
    _checkpoint(e, trace, "await-pick")
    return e


def resume_from_ledger(expedition_id: int, trace: TraceLog) -> Expedition:
    """Reconstruct an `Expedition` purely from `trace`'s rows for `expedition_id` — no in-memory
    harness object required. This is the trace-#3 contract: a different process that has only
    the jsonl file (loaded via `TraceLog(path).load()`) can rebuild the expedition at its last
    durable checkpoint and continue the climb (another `advance_expedition` call) from exactly
    where it left off, instead of restarting.

    Every `Transition` field is a carried-forward snapshot (see the trace contract in
    `fls.ledger`), so only the LATEST row is needed — no folding of the whole history.

    Raises `ValueError` if the trace has no rows for this expedition (nothing to resume)."""
    last = trace.latest(expedition_id)
    if last is None:
        raise ValueError(f"no trace rows for expedition {expedition_id} — nothing to resume")

    idea = Idea(**last.idea)
    dial = Dial(last.dial) if last.dial is not None else None

    # A trace tail left at "climbing" with no terminal checkpoint means the harness that held
    # this expedition disappeared mid-rung (the interrupted case) — surface that honestly as
    # RESUMING rather than silently re-presenting the stale "climbing" label. Any other status
    # (await-pick, descended, parked, await-signoff, ...) was already a legitimate durable
    # checkpoint and is preserved as-is.
    status = RESUMING if last.status == CLIMBING else last.status

    kwargs = {"target_rung": last.target_rung, "rung": last.rung, "status": status,
              "spec": last.spec, "picked_wireframe": last.picked_wireframe, "reason": last.reason}
    if dial is not None:
        kwargs["dial"] = dial
    e = Expedition(number=expedition_id, idea=idea, **kwargs)
    if last.spent_usd:
        # A single synthetic checkpoint Call reproduces the cumulative spend for budget-ceiling
        # purposes without needing to replay the full per-call history (the trace intentionally
        # doesn't carry it — that's the calibration Ledger's job, not the trace's).
        e.add([Call(provider="trace-replay", model="trace-replay", input_tokens=0,
                    output_tokens=0, usd=last.spent_usd)])
    return e

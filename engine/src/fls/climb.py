"""advance_expedition — the upper-ladder climb (rungs 3->4->await-5), resumed after a human pick.

Separated from controller.run_batch (the admission+funnel+paper-ladder half) because this half
needs a human decision first: rung 2 is `human-picks`, so an expedition parks at AWAIT_PICK and a
human (or, for the auto_build lane in a demo, an auto-pick) supplies the winning wireframe. This
function resumes from that pick and drives:

  rung 3 (auto-advance-with-audit): build demo + walkthrough; a failed walkthrough DESCENDS.
  rung 4 (human-picks entry, then the retry/descend loop): build MVP; pass -> AWAIT rung-5 sign-off.
  rung 5 (propose-only, hard gate): draft PR behind a flag -> AWAIT_SIGNOFF (never auto-ships).

Descent at any design failure returns the expedition to rung 2 with the lesson recorded.
"""
from __future__ import annotations

from fls.anchor import Anchor
from fls.expedition import AWAIT_PICK, CLIMBING, Expedition
from fls.funnel import RUNG_DEMO, RUNG_FLAG, RUNG_MVP, RUNG_WIRE
from fls.rung1 import Builder
from fls.rung3 import Walkthrough, run_rung3
from fls.rung4 import BoundedContext, run_rung4
from fls.verifier import Verifier

AWAIT_SIGNOFF = "await-signoff"
DESCENDED = "descended"


def advance_expedition(e: Expedition, picked_wireframe: str, anchor: Anchor,
                       builder: Builder, walkthrough: Walkthrough, verifier: Verifier,
                       artifact_dir: str, lessons_path: str) -> Expedition:
    ceiling = anchor.budgets.per_expedition_ceiling_usd
    e.status = CLIMBING

    # ---- rung 3: interactive demo + walkthrough (auto-advance-with-audit) ----
    if e.target_rung >= RUNG_DEMO:
        r3 = run_rung3(e.idea, e.spec or e.idea.intent, picked_wireframe,
                       builder, walkthrough, artifact_dir, e.number)
        e.add(r3.calls)
        if e.spent_usd > ceiling:
            e.status, e.reason = "parked", f"budget ceiling ${ceiling} hit at rung 3"
            return e
        if not r3.walkthrough.passed:  # design signal -> descend to wireframe
            e.rung, e.status = RUNG_WIRE, DESCENDED
            e.reason = f"rung-3 walkthrough failed: {r3.walkthrough.detail}"
            return e
        e.rung = RUNG_DEMO
    else:
        e.status = AWAIT_PICK  # demo lane only; parks after wireframe (shouldn't reach here)
        return e

    # ---- rung 4: MVP loop (retry vs descend) ----
    if e.target_rung >= RUNG_MVP:
        ctx = BoundedContext(spec=e.spec or e.idea.intent, wireframe=picked_wireframe)
        r4 = run_rung4(e.number, ctx, builder, verifier, artifact_dir, lessons_path,
                       max_retries=3, from_rung=RUNG_MVP, to_rung=RUNG_WIRE)
        e.add(r4.calls)
        if r4.passed:
            e.rung = RUNG_MVP
            # ---- rung 5: hard gate — draft PR behind flag, never auto-ships ----
            if e.target_rung >= RUNG_FLAG:
                e.rung, e.status = RUNG_FLAG, AWAIT_SIGNOFF
                e.reason = "draft PR behind feature flag; awaiting human sign-off + staged rollout"
            else:
                e.status = AWAIT_SIGNOFF
        else:  # descended with a lesson
            e.rung, e.status = RUNG_WIRE, DESCENDED
            e.reason = r4.lesson.detail if r4.lesson else "rung-4 design failure"
        return e

    # demo lane (target == rung 3): parks after a passing walkthrough for the human shelf
    e.status = AWAIT_PICK
    e.reason = "interactive demo ready on the shelf"
    return e

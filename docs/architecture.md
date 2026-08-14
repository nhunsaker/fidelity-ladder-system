# Architecture

## The three layers

| Layer | Owns | Concretely |
|---|---|---|
| **Surface** | what humans see + the one decision protocol | GitHub issues (= expeditions), labels (= rung/dial state), signed webhooks, comment commands, Environments; the admin app is a *lens* over the same protocol, never a second source of truth |
| **Harness** | life-cycle context — what happens between calls | the FastAPI controller: admission, funnel, rung transitions, verifier dispatch, the ledger, the store |
| **Runtime** | model context + tool context — what each call sees and touches | builders (metered API or a self-hosted skill server) and judges (a different vendor, deliberately), under a fail-closed budget guard |

**Cross-family judging:** builders and judges come from different model families so the judge
has no self-preference stake in the builder's output.

## The rung state machine

```
0-intent → 1-spec → 2-wireframe → 3-demo → 4-mvp → 5-flagged
    │         │          │           │        │         │
  admit /   fan-out ×3  pick-of-3  clickable  build→verify  draft PR behind a flag;
  dock /    + judge     (human)    demo +     loop in a     stage auto-deploys;
  needs-    rank +                 Playwright isolated      prod requires a NAMED
  human     reflection             walkthrough worktree     approver
```

Each rung has an **autonomy dial** (`propose-only → human-picks → auto-advance-with-audit →
autonomous`). The funnel assigns each admitted idea a *target rung* (its lane): by default the
top idea auto-builds the full ladder, the next three park at an interactive demo, everything
admitted gets at least a wireframe — the backlog is a gallery, never a black hole.

**Rung 2 is fidelity-adaptive Exploration.** The rung classifies the expedition (fail-open to
structure): new flows get low-fi structural candidates; a tweak to an existing UI element gets
**concrete styled variants of the actual component** — real colors, weights, shapes, drawn
from the app's own component library. Candidates are *lines* (the path a climber reads up a
face before committing); the human picks the line.

**Vessels ground the climb.** A vessel is a named context pack between the north star and the
expedition — a team, an app, a site, a sprint, or a topic — carrying description, paths,
standards, and pointers to prior expeditions and lessons. Admission judges, ideation, and the
early rungs all read the expedition's vessel (default: the ANCHOR's `default_vessel`), so
judgments are informed and explorations are concrete instead of generic. The tighten-only
cascade runs ANCHOR → VESSEL → EXPEDITION.

## Descent — failure as a first-class transition

Rung 4 is a **loop, not a gate**: build → verify → classify. The verifier's failure taxonomy
drives what happens next:

| Classification | Signal | Action |
|---|---|---|
| mechanical | tests failed | retry, feeding the failure back (bounded retries) |
| flaky | timeout / nondeterminism | retry |
| design | an `ACCEPTANCE_UNMET` marker, a11y failure, retries exhausted | **descend** |
| budget | ceiling reached | park, visibly |

A descent does two things: re-arms the expedition at a lower rung *with the failure in
context*, and appends a **durable generalized lesson** to `LESSONS.md` — which future rung-1
judges read. This is the system's learning loop, and it's measurable: an N=10 A/B showed
builders passing 10/10 with acceptance criteria in their bounded context vs 8/10 without —
the precise pattern a live descent had taught.

**Context-bounding:** the rung-4 builder sees exactly {spec, picked wireframe, acceptance
test *as code*, corner-cut ledger, last-3 failures} under per-section compaction caps. The
target repo is navigated by tools, never inlined. Worktree isolation is blast-radius control;
context-bounding is the *judgment* control.

## Earned autonomy — the calibration flywheel

Every decision (judge verdict, human verdict, agreement, cost-per-verdict, human-latency)
lands in an append-only JSONL ledger. From it:

- **agreement per rung** over a rolling window → below the ANCHOR threshold, the dial
  tightens one step automatically-recommended, human-applied
- **`eligible-to-loosen`** appears only on a sustained track record — and a human applies it
- **human-latency** (gate-opened → human-responded) is a first-class metric: the system's
  real throughput is defined by its interactive reality, not pretended autonomy

## The two-column cost model

Every model call records `usd` (actual money) *and* `normalized_usd` (the same tokens at list
price) plus `funded_by` (`api` / `credits` / `subscription`). Subsidized lanes stay comparable
to metered ones; "utility per dollar" has a real denominator; and a $0-metered lane can still
blow a budget — the feeder's cost envelope bounds the *shadow* cost.

## Fail-closed, everywhere

No secret configured → webhook 403. No judge → admission parks as needs-human. No skill
server → the lane is unavailable (and fallback only fires if *authorized and budgeted*). No
named approver → no prod flip, no kill. A missing credential never fakes a success.

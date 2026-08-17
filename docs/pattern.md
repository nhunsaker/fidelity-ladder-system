# Pattern: Fidelity Ladder

A design pattern for governing agentic work, written in the classic
name · problem · forces · solution · consequences · known-uses form. The point of
writing it this way is that **the pattern is the deliverable, not our code** — GoF's
names outlived their C++ samples; 12-Factor shipped zero code; ReAct outlived every
harness that implemented it. If you take only the reference sketch at the bottom and
reimplement it against your own agents, you have taken the framework.

## Name

**Fidelity Ladder** (category: *progressive fidelity*). Related: the streaming
"bitrate ladder" (borrowed-credibility prior art — a fixed set of quality rungs you move
between under a policy).

## Intent

Govern *how real* an agent's output is allowed to become, advancing it up a fixed ladder
of fidelity rungs (spec → wireframe → interactive demo → MVP → shippable code) under a
policy that gates hard where blast radius is real and runs free where failure is cheap —
and that loosens a rung's autonomy only after evidence earns it.

## Problem

Agentic loops verify **correctness** (does the diff pass tests?) but not **direction**
(is this the right thing to build?). They jump straight to generating a pull request —
and code is the most expensive possible medium in which to discover the idea was wrong.
You have already paid for the most costly artifact before anyone checked the cheapest
question. Meanwhile the naive fix — "add a human approval step" — either gates everything
(and nobody reviews, so it rubber-stamps) or gates nothing (and the blast radius is
unbounded). And "just add an autonomy setting" makes it worse: a static `autonomy: high`
flag removes exactly the gates that were creating the value, on day one, before the system
has earned any trust.

## Forces

- **Direction is cheapest to test at low fidelity.** A wrong spec costs a paragraph; a
  wrong PR costs a build. But low fidelity is also *less certain* — you cannot fully verify
  a product from a wireframe.
- **Human judgment is scarce and expensive.** Spend it where blast radius earns it; waste
  it nowhere.
- **Autonomy must be granted, but ungoverned autonomy is a foot-gun.** You want agents to
  earn the right to run unattended — but not to *assert* that right via config.
- **Trust needs a denominator.** "It usually works" is not a claim you can act on; you need
  a measured track record.
- **Failure will happen; the system should learn from it**, not repeat it.
- **The whole thing must be legible.** If the policy is forty defaults across twelve files,
  nobody can say what the system will do — which is itself a failure mode.

## Solution

Model the work as a climb up a fixed ladder, governed by a single policy file:

1. **Rungs-as-data.** A rung is a record
   `{artifact-kind, verifier, dial, context-budget, termination}` — data, not a branch in
   code. The set of rungs is a list an instance declares; the *engine* iterates it and knows
   nothing about "wireframe" vs "MVP."

2. **One admission door.** Every idea — human-typed, brainstorm-emitted, agent-proposed —
   enters through one gate that asks only *does this trace to the policy (the ANCHOR)?* A
   source may file ideas; it may never admit its own.

3. **Per-rung verifier + dial + context-budget.** Each rung declares how it is checked
   (the verifier / LENS), how much autonomy it currently has (the dial:
   propose-only → human-picks → auto-advance-with-audit → autonomous), and how much context
   it may spend. All three are read from the policy file, never hardcoded.

4. **Tighten-only cascade.** Policy flows ANCHOR → (optional vessel) → expedition. Any level
   may make a constraint *stricter*; none may loosen one set above it. This is the ratchet.

5. **Fail closed.** A verifier error, an exhausted budget, or an ambiguous verdict parks the
   work. It never advances on optimism, and a check that did not run is never reported as
   passed.

6. **Calibration ledger + earned autonomy.** Every verdict and human decision is recorded.
   A rung's dial is a *function of that rung's track record* in the ledger — sustained
   judge-human agreement makes it eligible to loosen; disagreement tightens it one step.
   Loosening is not something you can type.

7. **Descend-and-learn.** A design-shaped failure drops the expedition down a rung and writes
   a durable lesson future verifiers read, so the same wrong turn isn't taken twice.

8. **A human owns every irreversible action.** Prod promotion, external posting, spend past a
   ceiling — each requires a named human decision through one protocol.

## Structure

```
                 ┌───────────────────────────────────────────────┐
   idea ───────▶ │  ADMISSION GATE  — does it trace to the ANCHOR? │──▶ park if no
                 └───────────────────────────────────────────────┘
                                    │ yes
                                    ▼
         rungs = [ spec, wireframe, demo, mvp, flagged ]   # data, not code
                                    │
        for each rung, in order:    ▼
        ┌──────────────────────────────────────────────────────────┐
        │  build(rung, budget=rung.context_budget)                  │
        │  verify(rung)          ← per-rung LENS (fail closed)       │
        │  dial = earned_dial(rung, ledger)                         │
        │  gate: propose-only / human-picks → wait for a human      │
        │        auto-advance-with-audit    → advance, record       │
        │  on design-failure: DESCEND one rung, write a lesson      │
        └──────────────────────────────────────────────────────────┘
                                    │ every verdict + decision
                                    ▼
                 ┌───────────────────────────────────────────────┐
                 │  CALIBRATION LEDGER                             │
                 │  sustained agreement → a rung may loosen        │
                 │  disagreement        → tighten one step         │
                 │  (the cascade only ever tightens)               │
                 └───────────────────────────────────────────────┘
```

## Consequences

**Benefits**
- Wrong-direction work is caught at the cheapest rung it can be caught at, not in code.
- Scarce human attention is spent only where blast radius earns it.
- Autonomy is calibrated (earned from a track record) rather than asserted (typed into a
  flag).
- The policy is legible — one file answers "what will this system do?"
- The system improves from its own failures instead of repeating them.

**Costs** (see the MANIFESTO for the honest version)
- Gates add latency; human-picks rungs wait for a human.
- The ANCHOR is only as trustworthy as its review discipline; a rubber-stamped policy
  launders bad decisions as governed ones.
- Rungs add ceremony to trivial work — the pattern earns its keep only where *direction* is
  genuinely in doubt.
- Earned autonomy is slower to reach than a YOLO config flag; on throwaway work the flag wins.

**Known scope.** Demonstrated on product/UI work, where low-fidelity rungs are cheap and
genuinely test direction. Whether the same ladder governs data pipelines, infra, or prose is
an open hypothesis, not a claim.

## Known uses

- **This repository** — a six-rung web-UI ladder (spec → wireframe → demo → MVP → flagged),
  driven over GitHub primitives, with cross-family judges and a calibration ledger. The
  ANCHOR is the policy file; expeditions are GitHub issues.
- **Prior art in spirit** — streaming bitrate ladders (fixed quality rungs under a switching
  policy); staged design processes in product teams (the practice this pattern names and
  automates); ReAct/Tree-of-Thoughts as evidence that a legible algorithm outlives its
  packaging.

## Reference implementation (~100 lines, no engine required)

This is the whole pattern. It has no dependency on this repo — swap `llm_*` for your own
agents and `Ledger` for a CSV file and you have a working fidelity ladder.

```python
from dataclasses import dataclass, field

# --- rungs are DATA -------------------------------------------------------------
@dataclass
class Rung:
    name: str
    verify: callable          # (artifact) -> Verdict ; a LENS
    base_dial: str            # propose-only | human-picks | auto-advance-with-audit | autonomous
    context_budget: int       # tokens this rung's build may spend

@dataclass
class Verdict:
    ok: bool
    ambiguous: bool = False
    design_failure: bool = False
    note: str = ""

# --- the calibration ledger: the ONLY thing that may loosen a dial --------------
class Ledger:
    def __init__(self): self.rows = []
    def record(self, rung, verdict, human):        # human ∈ {None, "approve", "reject"}
        self.rows.append((rung, verdict.ok, human))
    def lesson(self, rung, verdict):
        self.rows.append((rung, "LESSON", verdict.note))
    def earned_dial(self, rung):
        # loosen only on sustained judge↔human agreement; else hold the floor.
        window = [h == ("approve" if ok else "reject")
                  for (r, ok, h) in self.rows[-10:] if r == rung.name and h]
        agree = sum(window) / len(window) if window else 0.0
        if len(window) >= 5 and agree >= 0.8:
            return _loosen(rung.base_dial)
        return rung.base_dial

DIALS = ["propose-only", "human-picks", "auto-advance-with-audit", "autonomous"]
def _loosen(d): i = DIALS.index(d); return DIALS[min(i + 1, len(DIALS) - 1)]

# --- policy: one anchor, tighten-only -------------------------------------------
@dataclass
class Anchor:
    rungs: list                       # ordered ladder, declared as data
    def admits(self, idea) -> bool:   # one door: does it trace to the anchor?
        return idea.get("traces_to_anchor", False)

# --- the climb ------------------------------------------------------------------
def climb(idea, anchor, ledger, build, ask_human):
    if not anchor.admits(idea):
        return {"parked": "off-anchor"}
    i = 0
    while i < len(anchor.rungs):
        rung = anchor.rungs[i]
        artifact = build(rung, idea, budget=rung.context_budget)
        v = rung.verify(artifact)
        if v.ambiguous or not v.ok and not v.design_failure:
            return {"parked": rung.name, "why": v.note}    # FAIL CLOSED
        if v.design_failure:                                # DESCEND + LEARN
            ledger.lesson(rung, v); i = max(0, i - 1); continue
        dial = ledger.earned_dial(rung)                     # EARNED, not configured
        human = None
        if dial in ("propose-only", "human-picks"):         # human owns the gate
            human = ask_human(rung, artifact)
            if human == "reject":
                ledger.record(rung, v, human); i = max(0, i - 1); continue
        ledger.record(rung, v, human)
        i += 1                                              # advance ONE rung (tighten-only: never skip)
    return {"shipped": True}
```

What the production engine in `engine/` adds on top: durability (resume-from-ledger across
restarts), real budget accounting (actual + normalized spend per call), pluggable module slots
(AUTH/IDEAS/SOURCES/WORKERS/LENSES via `typing.Protocol` + registry), a GitHub surface, an MCP
control plane, and cross-family judges. All of that is *implementation*. The loop above is the
*pattern*.

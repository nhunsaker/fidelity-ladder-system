# The Fidelity Ladder — a manifesto

**Code is the most expensive place to discover you built the wrong thing.**
**Fidelity is a ratchet, not a throttle.**

Everything below follows from those two lines. The first names the problem: agentic
tooling jumped straight to "generate the PR," and a PR is the last place you want to
learn the idea was wrong — you've already paid for the most expensive medium there is.
The second names the answer: don't let an agent turn a throttle up and race to code.
Make it *climb* — spec → wireframe → interactive demo → MVP → flagged code — and let it
climb higher on its own only where it has earned the right. A ratchet moves one way. So
does fidelity here: constraints only ever tighten, autonomy is only ever earned.

## Where this sits

Spec-driven development (SDD, e.g. GitHub Spec Kit) governs *what artifact comes next* —
constitution, spec, plan, tasks, code. That is real and load-bearing, and the Fidelity
Ladder does not replace it. We govern a different axis:

> **SDD gates what artifact comes next; FLS gates how real it's allowed to get.**

Call the category **progressive fidelity** — SDD's sibling, not its competitor. You can
run both: SDD decides the sequence of documents; the Fidelity Ladder decides how much
reality each rung is permitted to commit, and refuses to let an agent skip rungs because
it feels confident.

## Principles

These are the doctrine — the "why it's built this way." They are distinct from the five
runtime **non-negotiables** (human owns every irreversible action · fail closed ·
accessibility floor · evidence over claims · provenance), which are the constitution an
instance runs under. Principles explain the shape; non-negotiables are the rules.

1. **Policy lives in the ANCHOR.** One file declares the north star, the dials, the
   budgets, the gates. Nothing important is scattered across code or hidden in env.
   *Prevents:* the config-drift failure where "the rules" are actually forty defaults in
   twelve files and nobody can say what the system will do.

2. **Trust lives in the ledger.** Every judge verdict and every human decision is
   recorded. Claims about the system's reliability are answered by reading the ledger, not
   by assertion. *Prevents:* the "it usually works" failure — confidence with no
   denominator.

3. **Loosening is not configuration.** You cannot type your way to more autonomy. A rung
   loosens only after the ledger shows sustained judge-human agreement at that rung;
   disagreement tightens it. *Prevents:* the YOLO-config failure where someone sets
   `autonomy: high` on day one and the gates that create the value are gone before the
   system has earned anything.

4. **Fail closed — nothing pretends.** A verifier error, an exhausted budget, or an
   ambiguous verdict parks the expedition. It never proceeds on optimism, and it never
   reports a check as passed when the check did not run. *Prevents:* the silent-green
   failure where a skipped or crashed verifier reads as success.

5. **One door for admission.** Every idea — typed by a human, emitted by a brainstorm, or
   proposed by another agent — enters through the same admission gate, which asks only
   whether it traces to the ANCHOR. A source can file ideas; it can never admit its own.
   *Prevents:* the backdoor failure where a generative source floods the system with work
   it also blessed.

6. **A human owns every irreversible action.** Prod promotion, external posting, and spend
   past a ceiling require a named human decision through the one protocol. *Prevents:* the
   unattended-blast-radius failure — the class of mistake you cannot roll back and nobody
   agreed to.

7. **Every claim carries its cost.** Each verdict is budget-bounded and each rung has a
   declared cost; spend is metered in the ledger (actual and normalized). *Prevents:* the
   runaway-agent failure where verification quietly costs more than the thing being built.

8. **Failure descends and leaves a lesson.** A design-shaped failure drops the expedition
   back down a rung and writes a durable lesson that future judges read. The system gets
   measurably smarter from its own mistakes rather than repeating them. *Prevents:* the
   amnesiac-loop failure where the same wrong turn is taken every run.

## The Fidelity Ladder is NOT

- **Not an agent runtime.** It does not schedule tools or manage a conversation. It sits
  *above* whatever runtime you use and governs how real that runtime's output may become.
- **Not autonomy-in-a-box.** Dial every rung to the top and you have bought nothing — the
  value is the gates you keep, not the ones you remove. A system with no gates is just an
  agent with a bigger blast radius.
- **Not an SDD replacement.** It gates a different axis (fidelity, not artifact-sequence)
  and composes with Spec Kit rather than competing with it.
- **Not (yet) medium-agnostic.** This is scoped to product and UI work — where low-fidelity
  rungs (spec, wireframe, clickable demo) are cheap and genuinely test *direction*. The
  claim that the same ladder governs data pipelines, infra changes, or prose is a
  **hypothesis we have not earned**, not a feature we ship. When we have run it on a
  second, non-UI medium and the ledger backs the claim, this line changes. Until then it
  stays narrow on purpose.

## The honesty number

A manifesto without a scoreboard is a mood. The thesis of this project is falsifiable:
*catching wrong-direction work at low fidelity is cheaper than catching it in code.* That
is a claim you can measure, and we intend to.

**The first number, honestly.** From an N=10 rung-4 ablation (`fls bench`; derivation in
`engine/docs/bench-results.md`):

- **Ticket-altitude — 100% vs 80% first-attempt pass, N=10.** With the acceptance criteria
  *in* the builder's bounded context, 10/10 passed on the first attempt; withheld, 8/10 — the
  two failures were contract misreads (building against an imagined interface), the exact
  lesson a live descent had already taught the ledger.
- **Cost-to-catch — a 4.4× multiplier.** In the ablation arm, a wrong-direction build that had
  to be caught at the code rung cost ~4.4× a clean pass. That is the thesis, quantified: work
  is most expensive to fix where it's most real.

**The rung-of-catch number, now earned — at the spec rung.** A faithful multi-rung bench closes
the gap the ablation left open: a real model judge on each rung, run on a subscription lane at
**zero spend**, over a 12-seed corpus (6 good / 6 bad, 2 vessels) whose seeds *embed* the
divergence in the artifact rather than state it.

- **Intent-contradicting wrong-direction is caught at rung 1 (the spec), reliably** — every run,
  at **~3% of code-cost** — with a **~0–3% false-catch rate** (mean 3.3% over 5 runs; the
  calibrated judge leaves good work alone). That is the central promise, measured: the cheapest
  rung catches the wrongness that is knowable there.

- **False-advance — ~10%.** On a bigger corpus (**N=27 seeds / 14 bad / 3 vessels**, seeds
  re-labeled in a second pass), the fraction of wrong-direction work that slipped past the rung where
  it was knowable was **~10% — 7–14% across 5 clean runs** (down from the small N=12 set's noisy
  ~20%). It is *characterized, not random*: one wireframe-visual contradiction the judge localizes a
  rung late **every** run, plus one of two subtle code-semantic cases that occasionally slips — **13
  of 14 wrong-direction seeds are caught on time**, and rung-of-catch spreads across all four rungs.
  The false-catch control was 7.7%: the judge leaves good work alone.

**The honest bound.** State it as *~10% false-advance (7–14% across 5 clean runs; N=27 / 14 bad / 3
vessels; single-author two-pass labels)*. Two caveats stay attached: the "second labeler" was a
disciplined second pass by the same author, not an independent human co-labeler; and the residual is
one known judge blind spot (a picture showing the wrong thing) plus tail noise, so a genuinely
independent labeler and a larger corpus are the next lift. A real number with its bounds shown, not a mood.

## The pattern, diagrammed

The engine in this repo is one implementation. The *pattern* is small enough to
reimplement in about a hundred lines against your own agents — and you should be able to,
because a pattern that only works as our code is not a pattern, it is a product. (This is
the ReAct lesson: the idea outlived every sample that shipped it.)

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
        │  build(rung)                                              │
        │  verify(rung)          ← per-rung verifier (fail closed)  │
        │  dial = earned_dial(rung, ledger)                         │
        │  context ≤ rung.budget ← declared, not implicit          │
        │  gate:                                                    │
        │     propose-only / human-picks → wait for a human         │
        │     auto-advance-with-audit    → advance, record          │
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

The load-bearing parts, in order:

1. **Rungs-as-data** — a rung is a record `{artifact-kind, verifier, dial, context-budget,
   termination}`, not a branch in code. Your ladder is a list; ours happens to have six
   entries.
2. **Per-rung verifier + dial + context-budget** — each rung declares how it is checked, how
   much autonomy it currently gets, and how much context it is allowed to spend. All three
   are read from the ANCHOR, not hardcoded.
3. **Tighten-only cascade** — ANCHOR → (optional vessel) → expedition. Any level may make a
   constraint stricter; none may loosen one set above it. The ratchet, in code.
4. **Calibration ledger** — the record that turns "we trust this rung" into a measurable
   claim, and the only thing allowed to loosen a dial.
5. **Earned autonomy** — the dial for a rung is a function of that rung's track record in the
   ledger, never a static setting. Autonomy is an output, not an input.

A pseudocode sketch of the whole loop:

```python
def climb(idea, anchor, ledger):
    if not admits(idea, anchor):            # one door; traces-to-ANCHOR only
        return park(idea, "off-anchor")
    exp = Expedition(idea, rung=anchor.rungs[0])
    while not exp.done:
        r = exp.rung
        artifact = build(r, exp, budget=r.context_budget)
        verdict  = r.verifier(artifact)     # fail closed: error/ambiguous -> park
        if verdict.is_error or verdict.ambiguous:
            return park(exp, verdict)
        ledger.record(r, verdict, human=None)
        dial = earned_dial(r, ledger)       # loosening is NOT configuration
        if verdict.design_failure:
            exp.descend(); ledger.lesson(r, verdict); continue
        if dial in ("propose-only", "human-picks"):
            decision = await_human(exp, r)  # a human owns irreversible actions
            ledger.record(r, verdict, human=decision)
            if decision.reject: exp.descend(); continue
        exp.advance()                        # tighten-only: never skip a rung
    return exp
```

That is the whole idea. Everything in `engine/` is this loop, made durable, budgeted,
observable, and wired to real judges and a real surface — but if you only take the sketch,
you have taken the framework.

## Consequences (the honest costs)

No pattern is free. If you adopt this one, you are choosing to pay:

- **Gates add latency.** Human-picks rungs wait for a human. That is the point, and it is
  slower than not waiting. If your work is genuinely low-stakes, this tax is real overhead.
- **Anchors need review discipline.** The ANCHOR is only trustworthy if edits are actually
  reviewed. A rubber-stamped ANCHOR is worse than none — it launders bad policy as governed.
- **Rungs add ceremony to trivial work.** A one-line change does not need five rungs. The
  ladder earns its keep on work where *direction* is genuinely in doubt; on trivial work it
  is friction, and you should say so and skip it.
- **Earned autonomy is slower than YOLO config.** A `autonomy: high` flag is instant; a rung
  that loosens only after the ledger backs it takes runs to get there. We think the trade is
  correct — you are buying calibrated trust instead of asserted trust — but it is a trade,
  and on throwaway work the flag wins.

If those costs are wrong for your work, this pattern is wrong for your work. We would rather
tell you that than sell you a ladder you will climb around.

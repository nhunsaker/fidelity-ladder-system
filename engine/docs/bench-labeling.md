# `fls bench` — the seed-direction labeling protocol

> **Read this before you write a single seed.** The scoreboard (`fls bench`) only means
> something if the seeds are labeled honestly. A seed whose *direction* is ambiguous doesn't
> measure the ladder — it measures the labeler's mood. This document is the two-reviewer
> protocol that keeps the scoreboard signal, not noise. It is written **before** the harness on
> purpose: if we can't agree what "wrong direction" means, no number the harness prints is real.

## 1. What we are labeling — and what we are NOT

`fls bench` asks one question of the ladder: **does it catch wrong-direction work before that
work reaches the expensive rung (code), and at what fraction of the code-cost?**

To ask that, every seed carries a **direction label**:

| label | meaning |
|---|---|
| `good` | The seed builds *the thing the intent asked for*. A healthy ladder should let it **advance** clean to the top. If the ladder catches (rejects/descends) a `good` seed, that is a **false catch** — the ladder cried wolf. |
| `bad`  | The seed builds *the wrong thing* — it contradicts the stated intent, the acceptance criteria, or an ANCHOR non-negotiable. A healthy ladder should **catch** it, and the earlier (cheaper) the better. If a `bad` seed advances past the rung where its wrongness first becomes visible, that is a **false advance** — the whole point of the ladder failed. |

**We are labeling *direction*, not *quality*.** A `good` seed may still be buggy, slow, or ugly
— that is what the rungs' verifiers are for. Direction is only: *is this seed pointed at the
thing the intent asked for, yes or no?* Do not smuggle a code-quality judgment into a direction
label. "It works but it's inefficient" is `good`. "It works perfectly but it solves a different
problem than the intent stated" is `bad`.

### The `should_catch_by_rung` field
Every `bad` seed also carries **`should_catch_by_rung`** — the number of the *earliest* rung
whose artifact makes the wrongness detectable. This is the reviewers' claim about *where the
evidence first exists*, not where our current verifiers happen to catch it:

- Wrongness visible in the **spec** (contradicts the written intent) → `should_catch_by_rung: 1`.
- Wrongness only visible once you can **see or click** it (a wireframe/demo reveals the wrong
  layout or interaction) → `should_catch_by_rung: 2` or `3`.
- Wrongness only provable by **running the acceptance test against code** → `should_catch_by_rung: 4`.

`should_catch_by_rung` is the honesty spine of the false-advance metric: a `bad` seed that the
ladder only catches at rung 4 when the evidence existed at rung 1 is a *late* catch — expensive,
and a defect in the ladder even though the seed was ultimately stopped. (`good` seeds leave this
field null.)

## 2. The two-reviewer protocol

1. **Independent first pass.** Two reviewers label each seed's `direction` (and, for `bad`
   seeds, `should_catch_by_rung`) **without seeing each other's labels**. Each writes a one-line
   *why* — the specific intent clause or acceptance criterion the seed honors or violates.
2. **Compare.** For each seed, compare the two `direction` labels.
3. **The agreement gate (hard rule):**
   - **`direction` labels agree** → the seed is **admitted** to the seed set with the agreed
     label. (If the two `should_catch_by_rung` values differ by one rung, take the **lower**
     one — the earliest rung either reviewer believed the evidence existed; a bigger gap goes to
     reconciliation.)
   - **`direction` labels disagree** → the seed is **excluded, not guessed.** Two humans looking
     at the same seed disagreeing about whether it builds the right thing is *itself the finding*:
     the seed's direction is not crisp enough to score the ladder against. Move it to
     `excluded/` with both reviewers' one-liners so the disagreement is auditable. **Never split
     the difference, never let a tiebreaker vote it in.** An excluded seed measures nothing; a
     guessed seed measures noise and pollutes every metric downstream.
4. **Reconciliation is allowed only for `should_catch_by_rung` when `direction` already agrees.**
   Direction disagreement is terminal (exclude). Rung disagreement of >1 rung goes to a short
   discussion; if the reviewers still can't agree the rung, the seed is *kept as `bad`* but its
   `should_catch_by_rung` is set to the **higher** rung (the conservative claim — we only assert
   a false advance when we're sure the evidence existed earlier).

## 3. Inter-rater agreement, reported honestly

Report the raw agreement alongside every scoreboard:

- **direction-agreement** = (seeds where both reviewers' `direction` matched) / (seeds labeled).
- Any run whose seed set has direction-agreement **< 0.8** is flagged on the scoreboard as
  *low-agreement — treat the numbers as directional only.* A scoreboard built on coin-flip seeds
  is worse than no scoreboard, because it looks quantitative.
- The count of **excluded** seeds is published too. A high exclusion rate is not a failure of the
  reviewers — it is honest evidence that the seed *authoring* needs sharper intents.

## 4. Why direction, not outcome

The thesis `fls bench` scores is narrow and causal: **verify *direction* where being wrong is
cheap.** Code is the most expensive place to discover you built the wrong thing; the ladder's
whole claim is that a wrong *direction* is visible in a spec or a wireframe — long before it is
compiled. If we labeled seeds by *outcome* ("did it eventually pass?") we'd be scoring the
verifiers, not the ladder. Labeling by *direction* is what lets the scoreboard say the honest
thing: *"the wrongness was knowable at rung N; did the ladder act on it there?"*

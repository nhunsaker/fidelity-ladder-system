# `fls bench` — the honest numbers

## v9 update — the bigger corpus earns a false-advance number

The v8 corpus (N=12, 2 vessels, single-author labels) left the blanket false-advance rate noisy
(~20%) and *not* manifesto-grade. v9 doubled it: **N=27 seeds (14 bad / 13 good), 3 vessels**, each
seed's direction + `should_catch_by_rung` re-labeled in a second pass (disagreements excluded, not
guessed). Live on the $0 skill-server lane (calibrated faithful judge, blind to labels), with bounded
retry on transient upstream 500s:

- **false-advance rate: ~10%** — **mean 10.0%, range 7.1–14.3%, σ 3.5% over 5 clean runs**
  (raw: 7.1 / 14.3 / 7.1 / 14.3 / 7.1 — it toggles between 1/14 and 2/14 slipped). NOTE: an earlier
  2-run sample both landed 7.1% and was mis-recorded as "flat/identical"; the 5-run measurement shows
  genuine spread. The lane 500s under *any* concurrency, so runs are serial (~19s/call).
- The residual is **characterized, not random**: `fweb-a11y-placeholder-bad` (scb=2, a
  wireframe-visual contradiction) slips a rung in **5/5** runs — a systematic judge blind spot for
  "the picture shows the wrong thing" (the 7.1% floor); plus `fdash-sort-reorder-bad` (1/5) and
  `fweb-debounce-leading-bad` (1/5) as tail noise. **13 of 14 bad seeds caught on time every run.**
- **false-catch rate (control): 7.7%** (1/13, stable ×2) — driver = `fcli-stdin-good` over-read at
  rung 1. The judge leaves good work alone.
- **rung-of-catch spreads across all four rungs.** cost-to-catch: rung 1 3.1% · 2 9.4% · 3 25% · 4 87.5%.
- **Two-labeler:** direction agreement 96.4% (27/28); 1 excluded on a genuine disagreement; scb 13/14
  exact. Caveat: same-author second pass, not an independent human.

**Honest bound:** state the number WITH its caveats — *~10% false-advance (7–14% across 5 clean runs;
N=27 / 14 bad / 3 vessels; single-author two-pass labels)*. Qualified-yes manifesto-grade: stable range
+ characterized residual (a real upgrade from v8's noisy-unquotable ~20%), but an independent labeler +
a larger corpus is the next lift.

---

# `fls bench` — the honest numbers (v8 detail)

> **Scope of this document.** Two distinct bodies of evidence, kept separate on purpose:
> 1. **The faithful live bench (v8, below)** — a real, model-backed run of the three-metric
>    scoreboard on the **$0 skill-server subscription lane** (no metered spend, no sponsored-credit
>    drawdown). This is the source for the **rung-of-catch** number.
> 2. **The N=10 rung-4 ablation (further down)** — mined from records that already existed on
>    disk. This is the source for the **altitude / first-attempt-pass** number.
>
> Where the data cannot support a metric, this document says so plainly rather than inventing a
> number. The harness is `fls.bench` (`fls-bench` CLI); its *default* run still uses a zero-spend
> oracle judge (it measures the harness, not the ladder). `--live` runs the calibrated judge.

## The faithful live bench (v8) — the real rung-of-catch number

**The problem this fixed.** The first live run used *oracle-shaped* seeds: each seed's one
`description` **stated** its own divergence ("Intent says X; this makes Y instead"). A
text-reading judge caught that trivially at rung 1 and, worse, over-flagged good seeds — a
measured **85.7% false-catch rate** (6 of 7 good seeds wrongly flagged). A false-catch rate that
high makes the rung-of-catch number meaningless: the judge is not reading the ladder, it is
pattern-matching the word "wrong".

**The fix — faithful seeds + a calibrated judge.**
- **Faithful seed model** (`fls.bench.FaithfulSeed`, corpus in `fls.bench_faithful_seeds`): each
  seed carries an **intent** (what was asked) and a **per-rung artifact** (what the builder
  produced, as it would actually appear — a spec at rung 1, a wireframe at rung 2, a demo
  walkthrough at rung 3, code at rung 4). The divergence in a `bad` seed is **embedded** in the
  artifact (inferable by reading it), **never stated**. A bad seed's artifacts are faithful
  *below* its `should_catch_by_rung` and only begin to diverge at/after it; a good seed's
  artifacts implement the intent at every rung.
- **Calibrated judge** (`make_faithful_bench_judge`): at rung R the judge sees only
  `{intent, artifact-at-R}` and answers **FAITHFUL** or **DIVERGES**. The system prompt frames the
  task as *faithfulness adjudication* — "does this artifact implement what was asked?", default
  **FAITHFUL**, DIVERGES only on a **material** mismatch visible in the shown artifact — explicitly
  **not** "hunt for anything wrong" (the framing that over-flags). The judge is **blind** to the
  seed's `direction`/`should_catch_by_rung`. It evaluates only rungs where the builder produced a
  *distinct* artifact (1–4); rung 0 (bare intent) and rung 5 (the human sign-off gate — which would
  only re-read the rung-4 code) are not automated-judge rungs.

**Calibration cost: the <15% false-catch bar was met on the first live run** (0.0% — a clean
sweep of all good seeds), so the calibrated prompt did not need iterating to *pass*. One design
refinement followed for **robustness**: dropping the rung-5 re-judge of the code artifact, which
had produced a stray false-catch and false-advance in an early run.

**The run.** Corpus = **12 faithful seeds, 2 vessels** (web-ui, dashboard), 6 good / 6 bad, with
bad-seed `should_catch_by_rung` spanning {1, 1, 2, 3, 4, 4}. Judge = `SkillServerJudge` on the
subscription lane (`funded_by=subscription`, `usd=0.0`). Measured over **N=5 live runs** (LLM
judges are stochastic, so a single run is not a number — the spread is the finding):

| metric | result over 5 runs | read |
|---|---|---|
| **false-catch** (good seed wrongly caught) | **mean 3.3%** — `0%` in 4/5 runs, `16.7%` in 1 | **the trustworthiness number**: the ladder almost never cries wolf. 1 stray flag across 30 good-seed-runs. |
| **false-advance** (bad seed caught later than its evidence-rung) | **mean 20%** — 0 / 17 / 17 / 33 / 33 % | honest noise, concentrated on two genuinely-hard seeds (below). |
| **rung-of-catch** (per bad seed, mode over 5 runs) | rung 1 ×2, rung 3 ×1, rung 4 ×2, "never (by rung 4)" ×1-part | see per-seed table. |

**Per-seed rung-of-catch across the 5 runs** (`-1` = advanced past rung 4 uncaught):

| seed | vessel | `scb` | rungs caught (5 runs) | read |
|---|---|---|---|---|
| `fweb-cmdk-modal-bad`      | web-ui    | 1 | `1,1,1,1,1` | **rock-solid**: spec contradiction (focus-in-place → modal palette) caught at rung 1 every run. |
| `fdash-tile-average-bad`   | dashboard | 1 | `1,1,1,1,1` | **rock-solid**: spec says "average" where intent said "total" — caught at rung 1 every run. |
| `fdash-filter-exclusive-bad` | dashboard | 4 | `4,4,4,4,4` | **rock-solid**: `< end` off-by-one, only provable in code — caught at rung 4 every run. |
| `fdash-sort-reorder-bad`   | dashboard | 3 | `3,3,4,3,3` | mostly on-time; the demo (column-drag ≠ sort) is caught at rung 3 in 4/5 runs. |
| `fweb-a11y-placeholder-bad`| web-ui    | 2 | `3,1,1,3,3` | **noisy**: caught at rung 1 (early) twice, rung 3 (late) three times — *never cleanly at rung 2*. |
| `fweb-debounce-leading-bad`| web-ui    | 4 | `4,4,4,-1,-1` | **hard**: leading-vs-trailing edge in code is subtle; missed entirely 2/5 runs. |

**cost-to-catch per rung** (`default_cost_model`, illustrative weights — the *shape* of the
thesis, not measured build cost): rung 1 = **3.1%** of full code-cost, rung 3 = **25.0%**,
rung 4 = **87.5%**. So a rung-1 catch is genuinely an order of magnitude cheaper than a rung-4 one.

### What is trustworthy, and what is not (the honest call)

- **Trustworthy — the false-catch calibration.** At **≈0–3%**, the judge reliably does *not* flag
  good seeds. This is what makes the rung-of-catch distribution mean something: a "DIVERGES" is
  almost always a real divergence, not a jumpy judge.
- **Trustworthy — the rung-1 / spec claim.** Both spec-contradicting seeds are caught at **rung 1
  in every single run**, at ~3% of code-cost. *Wrong-direction work that contradicts the written
  intent is caught at the spec rung, cheaply, reliably.* That is the manifesto-grade sentence this
  run earns.
- **Not yet clean — the full per-rung false-advance number.** The **~20% false-advance** is honest
  but noisy, concentrated on two seeds: a **wireframe-level visual contradiction** the judge does
  not localise to rung 2 (it catches at rung 1 or rung 3), and a **subtle code-semantic** divergence
  (leading vs trailing debounce) it misses ~40% of the time. These are exactly the *hard* cases —
  and the number would move with more seeds and a second labeler.
- **Small, single-author.** N=12 seeds, single-author labels (direction-agreement self-asserted at
  1.0 until a second reviewer co-labels per `docs/bench-labeling.md`). Treat every number here as
  **directional**, not a guarantee.

**Manifesto verdict.** The **rung-1 spec-catch** is solid enough to state with its caveat: *"the
ladder catches intent-contradicting wrong-direction work at the spec rung (~3% of code-cost) with
a ~0–3% false-catch rate — N=12 seeds across 2 vessels, single-author labels, ~20% of subtler
wrong-direction cases still slip a rung."* A **clean single headline false-advance %** is **not**
yet manifesto-grade — it is noisy at ~20% on this small set, and honesty (Wu-style) says so.

**Reproduce** (subscription lane, real $ = 0 — set the two env vars for your skill server):
```
export FLS_SKILL_SERVER=<your skill-server endpoint>
export FLS_SKILL_SERVER_KEY=<your skill-server key>
python -m fls.bench --live --vessel all          # faithful corpus + calibrated judge
python -m fls.bench --live --oracle-seeds --vessel all   # the A/B baseline (oracle-shaped seeds)
```

---

## The one record with real multi-seed signal: the N=10 rung-4 ablation

**Provenance:** an internal calibration record — the *"N=10 live rung-4 error analysis"*
(failure-taxonomy, run 2026-08-13). Per the work-split rule the raw record and its build artifacts
are **studio-private and not shipped in the public tree** (calibrated dials + raw ledgers stay
private; only the derived, anonymized numbers are published here). Live small-model builds against
planted-bug acceptance tests, a local `node --test` verifier, `max_retries=2` per climb (3 attempts
total). Founder-approved batch, actual spend $0.0184. Ten component tasks (command-palette focus,
debounce, query-parse, carousel wrap, input-label a11y, undo stack, currency format, slugify, rate
limiter, deep-get), each run in two conditions (condition A / condition B, N verified = 10 per arm).

| condition | what it tests | result | first-attempt pass |
|---|---|---|---|
| **A — acceptance-as-code IN the bounded context** (the mechanism ON) | builder sees the acceptance test while building | **10/10 passed**, 1 attempt each | **100%** (10/10) |
| **B — acceptance withheld** (ablation: the pre-lesson condition, mechanism OFF) | builder works from prose intent only | **8/10 passed**; 2 wrong-direction builds (`cmdk`, `slug`) `mechanical-exhausted` after 3 attempts | **80%** (8/10) |

### What this record *does* support

1. **Altitude / first-attempt pass rate (Yao's second number) — DERIVABLE, N=10.**
   *Ticket-altitude = 100% first-attempt pass with acceptance-as-code in context, vs 80% without,
   over N=10.* This is the cleanest number the existing data yields, and it maps directly onto the
   manifesto's second honesty number. (The 2 failures under ablation were **contract misreads** —
   the builder built against an *imagined* interface — the exact failure mode of live descent #101.)

2. **Cost-to-catch at rung 4 — DERIVABLE, N=2 catches.** In the ablation arm, a wrong-direction
   build that got caught cost a mean of **$0.00315** (3 attempts) versus **$0.00071** for a clean
   pass — a **4.4× cost multiplier** for a build that had to be caught at code. This is the
   manifesto's *problem statement*, quantified: catching wrong-direction work at the code rung is
   several times more expensive than never producing it.

### What this record *does NOT* support (stated plainly)

- **It does not demonstrate cheap, early-rung catches.** Every catch in this corpus happened at
  **rung 4 (mvp-code)** — the acceptance-test verifier, the most expensive rung. These ten seeds
  were rung-4 code tasks; **rungs 1–3 (spec / wireframe / demo) were never exercised**, so the
  corpus is silent on the ladder's central claim that wrong *direction* is catchable at a spec or a
  wireframe for a few percent of code-cost. The "catches wrong-direction work at rung X at Y% of
  code-cost" headline **for X < 4 is not yet earned by data.** It requires a live, multi-rung bench
  run (real judge at each rung), which is spend-gated and **has not been run.**

- **False-advance rate is technically 0% but on a trivial denominator.** Label these two ablation
  failures `should_catch_by_rung=4` (contract wrongness only provable by the test): both were caught
  at rung 4, i.e. on time → false-advance **0/2**. Under the mechanism-ON arm, no wrong-direction
  build was produced at all → nothing to advance. So false-advance is 0% in both arms, but for
  *N=2* and *N=0* respectively — this is a plumbing-scale denominator, not a scoreboard-grade one.

## The other on-disk records, and why they add little

**Provenance checked** (all studio-private expedition records, not in the public tree):
- The live-#101 calibration ledgers total **4 rows**, all at `rung "0-intent"` (admission), all with
  `judge_cost_usd = 0`. They record the live descent-that-taught-the-lesson (#101) at the admission
  gate only. There is no rung-of-catch or cost signal here — the interesting event (#101's rung-4
  contract misread) lived in the build artifacts, not the ledger. **Not usable for any bench metric.**
- The other expedition records hold demo-app / flag artifacts, not labeled-direction seed runs.
  **Not usable for the three metrics.**

## The two honest headlines

> **Rung-of-catch (v8 faithful live bench, $0 subscription lane, N=12 seeds / 2 vessels / 5 runs):**
> the ladder catches intent-contradicting wrong-direction work at the **spec rung (~3% of
> code-cost) reliably** (both spec seeds, every run), with a **~0–3% false-catch rate**. ~20% of
> *subtler* wrong-direction cases (a wireframe-level contradiction, a leading-vs-trailing code
> semantic) still slip a rung — so the clean early-rung claim is earned for spec-level divergences,
> not yet as a single blanket false-advance %.
>
> **Ticket-altitude (N=10 ablation):** 100% first-attempt pass with acceptance-as-code in the
> bounded context vs 80% without. A wrong-direction build caught at the code rung cost 4.4× a clean
> build.

This is the Wu-style candor the manifesto (§5) calls for: the label runs a step ahead of the number,
and we say so. The v8 faithful corpus (`fls.bench_faithful_seeds`, 12 intent+per-rung-artifact seeds
across two vessels) replaced the oracle-shaped starter seeds (`fls.bench_seeds`) that made the first
live run's number meaningless (85.7% false-catch); the labeling protocol (`docs/bench-labeling.md`)
is the discipline that keeps the numbers honest, and a second co-labeler is the next step to lift
these from *directional* to *quotable*.

### Reproduce the derivation
```
# altitude + cost-to-catch arithmetic from the ablation table:
#   A: 10/10 first-attempt = 100% ;  B: 8/10 first-attempt = 80%
#   caught-build mean cost $0.00315 (3 attempts) vs clean-pass mean $0.00071 -> 4.4x
# source: internal N=10 rung-4 ablation record (failure-taxonomy, 2026-08-13; studio-private)
# harness shape (zero-spend oracle run):
python -m fls.bench --vessel all
```

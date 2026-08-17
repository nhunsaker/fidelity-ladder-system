"""`fls bench` — the scoreboard that puts a number on the manifesto (Yao's ask).

The manifesto claims: *code is the most expensive place to discover you built the wrong thing,*
so the ladder catches wrong-*direction* work at a low, cheap rung. `fls bench` is the harness
that measures whether that's true, on labeled seeds, across ≥2 vessels. It reports three numbers:

  1. **rung-of-catch** — for each wrong-direction (`bad`) seed, which rung caught it.
  2. **cost-to-catch-per-rung** — the code-cost incurred by the time a catch happened, as a
     *fraction of the full-climb (code) cost*. This is the "at Y% of code-cost" number: catching
     at rung 1 (a spec review) should cost a few percent of building the whole thing.
  3. **false-advance rate** — the fraction of `bad` seeds that advanced *past* the rung where
     their wrongness was knowable (`should_catch_by_rung`). This is the metric that can shame the
     ladder: a wrong seed the ladder let through is the failure the whole pattern exists to prevent.

Design constraints (from the plan):
- **Deterministic + injectable.** `run_bench` takes a `judge` callable (does rung R catch this
  seed?) and a `cost_model` callable (what does rung R cost for this seed?). Both are pure
  functions of (seed, rung). With a stub judge the whole harness runs with **zero spend** and is
  fully testable. A live, model-backed judge is a spend-gated caller's concern — never wired here.
- **No wall-clock, no randomness** — nothing in this module reads the clock or an RNG, so a bench
  run is reproducible byte-for-byte.

The seed's `direction` label is defined by `docs/bench-labeling.md` (written before this harness,
on purpose): two reviewers must agree a seed's direction or it is excluded, not guessed.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fls.profile import WEB_LADDER_PROFILE, LadderProfile, RungSpec

# ---------------------------------------------------------------------------------------------
# Seed contract
# ---------------------------------------------------------------------------------------------

Direction = str  # 'good' | 'bad' — see docs/bench-labeling.md
GOOD: Direction = "good"
BAD: Direction = "bad"


@dataclass(frozen=True)
class BenchSeed:
    """One labeled bench case. `direction` and `should_catch_by_rung` come from the two-reviewer
    labeling protocol (docs/bench-labeling.md), NOT from the harness.

    - `direction`: 'good' (should advance clean) | 'bad' (should be caught).
    - `should_catch_by_rung`: for a `bad` seed, the earliest rung whose artifact makes the
      wrongness knowable. `None` for `good` seeds (and treated as "no bound" if ever set on one).
    """
    id: str
    vessel: str
    direction: Direction
    description: str
    should_catch_by_rung: int | None = None

    def __post_init__(self) -> None:
        if self.direction not in (GOOD, BAD):
            raise ValueError(f"seed {self.id!r}: direction must be 'good' or 'bad', got {self.direction!r}")
        if self.direction == BAD and self.should_catch_by_rung is None:
            raise ValueError(f"seed {self.id!r}: a 'bad' seed must declare should_catch_by_rung")


@dataclass(frozen=True)
class FaithfulSeed:
    """A *faithful* bench case — the fix for the oracle-shaped seed problem.

    The starter `BenchSeed` carries a single `description` that STATES the divergence
    ("Intent says X; this makes Y instead"). A text-reading judge catches that trivially at
    rung 1 and (worse) over-flags good seeds, because the prompt frames the task as "hunt for
    anything wrong". The measured result was an 85.7% false-catch rate — an untrustworthy number.

    A faithful seed instead carries:
      - `intent`   : what was ASKED (one paragraph of plain intent — never says "wrong").
      - `artifacts`: what the BUILDER PRODUCED at each rung, as it would actually appear
                     ({rung_number: artifact_text}) — a spec at rung 1, a wireframe at rung 2, a
                     demo walkthrough at rung 3, code at rung 4. The judge compares intent-vs-
                     artifact and decides FAITHFUL or DIVERGES.

    The divergence in a `bad` seed is **embedded** in the artifact (inferable by reading it),
    never stated. Crucially, a bad seed's artifacts are FAITHFUL below `should_catch_by_rung`
    and only begin diverging at/after it — so a well-calibrated judge says FAITHFUL on the early
    rungs (no false catch) and DIVERGES exactly where the evidence first appears. A `good` seed's
    artifacts faithfully implement the intent at every rung.

    Harness-compatible: exposes the same `id/vessel/direction/should_catch_by_rung` that
    `run_bench`/`_climb_one` read, so it flows through the existing scoreboard unchanged; only the
    *judge* is faithful-aware (see `make_faithful_bench_judge`).
    """
    id: str
    vessel: str
    direction: Direction
    intent: str
    artifacts: dict[int, str]
    should_catch_by_rung: int | None = None

    def __post_init__(self) -> None:
        if self.direction not in (GOOD, BAD):
            raise ValueError(f"seed {self.id!r}: direction must be 'good' or 'bad', got {self.direction!r}")
        if self.direction == BAD and self.should_catch_by_rung is None:
            raise ValueError(f"seed {self.id!r}: a 'bad' seed must declare should_catch_by_rung")
        if not self.artifacts:
            raise ValueError(f"seed {self.id!r}: a faithful seed must carry at least one rung artifact")

    @property
    def description(self) -> str:
        """Back-compat shim: anything expecting a `.description` sees the intent (never a stated
        divergence — that is the whole point of a faithful seed)."""
        return self.intent

    def artifact_at(self, rung_number: int) -> str | None:
        """The artifact a builder would have in hand at `rung_number`. If this rung has no explicit
        artifact, fall back to the most concrete lower rung's artifact (the work produced *so far*);
        rung 0 (bare intent, nothing built yet) returns None → the judge cannot 'diverge' on nothing."""
        arts = self.artifacts
        if rung_number in arts:
            return arts[rung_number]
        lower = [k for k in arts if k <= rung_number]
        return arts[max(lower)] if lower else None


# ---------------------------------------------------------------------------------------------
# Cost model — the "code is the most expensive place" schedule
# ---------------------------------------------------------------------------------------------
# DEFAULT weights are ILLUSTRATIVE, not empirical: they encode the *shape* of the thesis (fidelity
# gets exponentially more expensive as you approach code) so the harness has a runnable default.
# A real bench passes a cost_model derived from measured ledger judge_cost_usd / build tokens.
# Weight = the marginal cost of producing THIS rung's artifact (talking is free; code is dear).
_DEFAULT_RUNG_WEIGHT: dict[int, float] = {
    0: 0.0,    # intent — a sentence; free
    1: 0.05,   # spec — cheap to write, cheap to reject
    2: 0.10,   # wireframe — a little more
    3: 0.25,   # interactive demo — real front-end work
    4: 1.00,   # mvp-code — the expensive rung; "the most expensive place"
    5: 0.20,   # flag — human sign-off / wiring
}


def default_cost_model(seed: BenchSeed, rung: RungSpec) -> float:
    """Marginal cost of producing `rung`'s artifact. Illustrative default (see above)."""
    return _DEFAULT_RUNG_WEIGHT.get(rung.number, 1.0)


def oracle_judge(seed: BenchSeed, rung: RungSpec) -> bool:
    """A perfect-ladder stub judge: catches each `bad` seed exactly at its `should_catch_by_rung`,
    never catches a `good` seed. Used to exercise the harness plumbing with zero spend and as the
    reference for tests. It is NOT an empirical result — a perfect oracle has false-advance 0 by
    construction; real signal needs a live, spend-gated judge.
    """
    if seed.direction != BAD:
        return False
    return seed.should_catch_by_rung is not None and rung.number >= seed.should_catch_by_rung


# ---------------------------------------------------------------------------------------------
# Result contract (frozen)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SeedResult:
    """One seed's climb through the ladder under a given judge + cost_model."""
    seed_id: str
    vessel: str
    direction: Direction
    should_catch_by_rung: int | None
    rung_of_catch: int | None      # None = advanced clean to the top (never caught)
    cost_to_catch: float           # cumulative cost through rung_of_catch (or full climb if uncaught)
    full_climb_cost: float         # cost if this seed were built all the way up the ladder
    cost_fraction: float           # cost_to_catch / full_climb — the "Y% of code-cost" number
    false_advance: bool            # bad seed caught later than should_catch_by_rung (or never)
    false_catch: bool              # good seed that got caught (the ladder cried wolf)


@dataclass(frozen=True)
class BenchReport:
    """The scoreboard. Frozen so a run's numbers can't be mutated after the fact."""
    vessels: tuple[str, ...]
    seeds: tuple[SeedResult, ...]
    n_good: int
    n_bad: int
    # metric 1 — rung-of-catch distribution over bad seeds: {rung_number: count caught there}.
    #            key -1 means "never caught" (advanced clean).
    rung_of_catch: dict[int, int]
    # metric 2 — mean cost-fraction (of full code-cost) at which a catch happened, per rung.
    cost_to_catch_per_rung: dict[int, float]
    # metric 3 — bad seeds that advanced past should_catch_by_rung, over all bad seeds.
    false_advance_rate: float
    # control — good seeds the ladder wrongly caught, over all good seeds.
    false_catch_rate: float
    headline: str

    def per_vessel(self, vessel: str) -> tuple[SeedResult, ...]:
        return tuple(s for s in self.seeds if s.vessel == vessel)


# ---------------------------------------------------------------------------------------------
# The harness
# ---------------------------------------------------------------------------------------------

def _climb_one(
    seed: BenchSeed,
    profile: LadderProfile,
    judge: Callable[[BenchSeed, RungSpec], bool],
    cost_model: Callable[[BenchSeed, RungSpec], float],
) -> SeedResult:
    """Send one seed up the ladder rung by rung. Accrue each rung's cost as the seed produces
    that rung's artifact; the first rung whose judge returns True is the rung-of-catch (the seed
    stops there). Cost is the sum of every rung's cost *up to and including* the catch."""
    rungs = sorted(profile.rungs, key=lambda r: r.number)
    full_climb_cost = sum(cost_model(seed, r) for r in rungs)

    cumulative = 0.0
    rung_of_catch: int | None = None
    for r in rungs:
        cumulative += cost_model(seed, r)   # producing this rung's artifact costs something
        if judge(seed, r):
            rung_of_catch = r.number
            break

    cost_to_catch = cumulative  # if never caught, cumulative == full_climb_cost
    cost_fraction = (cost_to_catch / full_climb_cost) if full_climb_cost > 0 else 0.0

    false_advance = False
    false_catch = False
    if seed.direction == BAD:
        bound = seed.should_catch_by_rung
        # advanced past its bound = caught too late OR never caught at all
        false_advance = rung_of_catch is None or (bound is not None and rung_of_catch > bound)
    else:  # good
        false_catch = rung_of_catch is not None

    return SeedResult(
        seed_id=seed.id,
        vessel=seed.vessel,
        direction=seed.direction,
        should_catch_by_rung=seed.should_catch_by_rung,
        rung_of_catch=rung_of_catch,
        cost_to_catch=round(cost_to_catch, 6),
        full_climb_cost=round(full_climb_cost, 6),
        cost_fraction=round(cost_fraction, 4),
        false_advance=false_advance,
        false_catch=false_catch,
    )


def make_live_bench_judge(judge, log=None):
    """Adapt a Judge (`.complete(prompt, max_tokens, system) -> (text, Call)`) into a bench judge
    `(seed, rung) -> bool`, run on whatever lane the Judge uses. With `SkillServerJudge` the whole
    live bench runs on the $0 subscription lane — no sponsored-credit drawdown.

    Judges BLIND: the prompt never reveals `seed.direction` or `should_catch_by_rung`. It asks the
    model to reason about rung-INSPECTABILITY — a wrongness counts as caught at a rung only if that
    rung's artifact actually makes it visible (a spec contradiction is catchable at the spec rung;
    a code-only logic bug is not, until code). Faithfulness is bounded by how much each seed's
    description *states* vs *embeds* the divergence — a caveat the results doc must carry.
    """
    def bench_judge(seed, rung):
        prompt = (
            f'You review a proposed change at fidelity rung {rung.number} ("{rung.name}": a '
            f"{rung.artifact_kind}, gate = {rung.verifier}). At this rung you can only inspect a "
            f"{rung.artifact_kind} — nothing more concrete exists yet.\n\n"
            f"PROPOSED CHANGE:\n{seed.description}\n\n"
            f"Is there ENOUGH VISIBLE AT THIS RUNG to catch that this change goes in the WRONG "
            f"DIRECTION (misreads the intended contract/behavior)? A wrongness is catchable at a "
            f"rung only if that rung's artifact makes it inspectable; if it would only surface in a "
            f"more concrete artifact than a {rung.artifact_kind}, answer CLEAR.\n\n"
            f"Answer with ONE word: CAUGHT or CLEAR."
        )
        text, _ = judge.complete(prompt, max_tokens=16, system=None)
        verdict = text.strip().upper()
        caught = verdict.startswith("CAUGHT") or "CAUGHT" in verdict.split()
        if log:
            log(seed.id, rung.number, caught, verdict[:30])
        return caught
    return bench_judge


# ---------------------------------------------------------------------------------------------
# The FAITHFUL judge — the calibrated one (v8). Compares intent-vs-artifact; does NOT hunt.
# ---------------------------------------------------------------------------------------------

# The system prompt does the calibration work: it frames the task as *faithfulness adjudication*
# (does this artifact implement what was asked?) — NOT "find anything wrong". The default is
# FAITHFUL; DIVERGES requires a concrete, material mismatch visible IN the shown artifact. This is
# what pulls the false-catch rate down: a good seed's artifact has nothing that materially
# contradicts the intent, so the honest answer is FAITHFUL, and the judge is told so explicitly.
_FAITHFUL_JUDGE_SYSTEM = (
    "You adjudicate FAITHFULNESS: given what was asked (the intent) and one artifact a builder "
    "produced, decide whether that artifact implements what the intent asked for.\n"
    "Rules:\n"
    "- Judge ONLY what is visible in the artifact shown. Never speculate about code, behavior, or "
    "details not present at this stage of the work.\n"
    "- The DEFAULT verdict is FAITHFUL. Answer DIVERGES only when the artifact, as written, does "
    "something MATERIALLY DIFFERENT from what the intent asked for (a different behavior, a "
    "different output, a different interaction, a contradicted requirement).\n"
    "- Wording differences, added polish, extra detail, vagueness, or an incomplete-but-consistent "
    "artifact are FAITHFUL — an artifact that does not yet contradict the intent has not diverged.\n"
    "- Do NOT hunt for bugs, quality issues, or things that are merely missing. Only a concrete "
    "mismatch with the intent counts.\n"
    "Answer with exactly one word: FAITHFUL or DIVERGES."
)


def make_faithful_bench_judge(judge, log=None):
    """Adapt a Judge into a bench judge `(seed, rung) -> bool` over FAITHFUL seeds (v8).

    At rung R the judge sees {intent, artifact_at(R)} and answers FAITHFUL | DIVERGES. `caught`
    (the ladder rejects/descends here) == DIVERGES. Runs on whatever lane the Judge uses; with
    `SkillServerJudge` the whole bench is the $0 subscription lane.

    The prompt is deliberately NON-adversarial (see `_FAITHFUL_JUDGE_SYSTEM`): faithfulness
    adjudication, default FAITHFUL. That is the calibration that keeps false-catch low — the judge
    is not asked "is anything wrong here?" (which over-flags good seeds) but "does this artifact do
    what was asked?". The seed's `direction`/`should_catch_by_rung` are NEVER shown — the judge is
    blind to the label it is being measured against.
    """
    def bench_judge(seed, rung):
        # The automated judge evaluates a rung ONLY where the builder produced a DISTINCT artifact
        # for it. Rung 0 (bare intent — nothing built yet) and rung 5 (flagged-pr — the human
        # sign-off gate, which would only re-read the rung-4 code artifact) are NOT automated-judge
        # rungs; re-judging the same artifact there just adds a spurious false-catch/false-advance
        # surface. A bad seed not caught by the last artifact rung is a genuine false advance.
        artifact = seed.artifacts.get(rung.number)
        if artifact is None:
            if log:
                log(seed.id, rung.number, False, "(not a judged rung)")
            return False
        prompt = (
            f"INTENT (what was asked):\n{seed.intent}\n\n"
            f"ARTIFACT — produced at the '{rung.name}' stage (a {rung.artifact_kind}); this is all "
            f"that has been built so far:\n{artifact}\n\n"
            f"Does this {rung.artifact_kind} faithfully implement the INTENT, or does it DIVERGE "
            f"from what the intent asked for? Answer with one word: FAITHFUL or DIVERGES."
        )
        # Bounded retry on a transient skill-server 500/timeout — a live bench makes many calls, so
        # one flaky upstream response shouldn't sink the whole run. Only ever sleeps on a real live
        # failure (a stub judge never raises SkillServerError), so the test suite stays fast.
        from fls.llm import SkillServerError
        text = None
        for _a in range(3):
            try:
                text, _ = judge.complete(prompt, max_tokens=16, system=_FAITHFUL_JUDGE_SYSTEM)
                break
            except SkillServerError:
                if _a == 2:
                    raise
                import time as _t
                _t.sleep(1.0)
        verdict = text.strip().upper()
        caught = verdict.startswith("DIVERG") or "DIVERGES" in verdict.split()
        if log:
            log(seed.id, rung.number, caught, verdict[:30])
        return caught
    return bench_judge


def run_bench(
    seeds: list[BenchSeed],
    *,
    profile: LadderProfile = WEB_LADDER_PROFILE,
    judge: Callable[[BenchSeed, RungSpec], bool] = oracle_judge,
    cost_model: Callable[[BenchSeed, RungSpec], float] = default_cost_model,
) -> BenchReport:
    """Run the scoreboard over `seeds`.

    `judge(seed, rung)` -> True if the rung's verifier CATCHES (rejects/descends) the seed there.
    `cost_model(seed, rung)` -> the code-cost of producing that rung's artifact.

    Both default to the zero-spend stubs (`oracle_judge` / `default_cost_model`) so the harness is
    runnable and testable without any model spend. A live bench injects a model-backed judge and a
    measured cost_model — that path is spend-gated and lives in the caller, never here.

    Deterministic: no clock, no RNG. Same seeds + same judge + same cost_model -> same report.
    """
    results = [_climb_one(s, profile, judge, cost_model) for s in seeds]

    good = [r for r in results if r.direction == GOOD]
    bad = [r for r in results if r.direction == BAD]

    # metric 1 — rung-of-catch distribution over bad seeds (-1 == never caught)
    rung_of_catch: dict[int, int] = {}
    for r in bad:
        key = r.rung_of_catch if r.rung_of_catch is not None else -1
        rung_of_catch[key] = rung_of_catch.get(key, 0) + 1

    # metric 2 — mean cost-fraction at which a catch happened, grouped by rung-of-catch
    by_rung_fracs: dict[int, list[float]] = {}
    for r in bad:
        if r.rung_of_catch is not None:
            by_rung_fracs.setdefault(r.rung_of_catch, []).append(r.cost_fraction)
    cost_to_catch_per_rung = {
        rung: round(sum(fracs) / len(fracs), 4) for rung, fracs in by_rung_fracs.items()
    }

    # metric 3 — false-advance rate over bad seeds; control — false-catch over good seeds
    false_advance_rate = round(sum(1 for r in bad if r.false_advance) / len(bad), 4) if bad else 0.0
    false_catch_rate = round(sum(1 for r in good if r.false_catch) / len(good), 4) if good else 0.0

    vessels = tuple(sorted({s.vessel for s in seeds}))
    headline = _headline(bad, cost_to_catch_per_rung, false_advance_rate, len(seeds), vessels)

    return BenchReport(
        vessels=vessels,
        seeds=tuple(results),
        n_good=len(good),
        n_bad=len(bad),
        rung_of_catch=rung_of_catch,
        cost_to_catch_per_rung=cost_to_catch_per_rung,
        false_advance_rate=false_advance_rate,
        false_catch_rate=false_catch_rate,
        headline=headline,
    )


def _headline(
    bad: list[SeedResult],
    cost_to_catch_per_rung: dict[int, float],
    false_advance_rate: float,
    n_seeds: int,
    vessels: tuple[str, ...],
) -> str:
    """The one-line honesty number for the manifesto."""
    if not bad:
        return f"no bad-direction seeds in the set (N={n_seeds}) — nothing to catch."
    caught = [r for r in bad if r.rung_of_catch is not None]
    if not caught:
        return (f"the ladder caught NONE of {len(bad)} wrong-direction seeds — "
                f"false-advance {false_advance_rate:.0%}. The pattern failed on this set.")
    # earliest rung that did the most catching, and its cost fraction
    earliest = min(cost_to_catch_per_rung) if cost_to_catch_per_rung else None
    frac = cost_to_catch_per_rung.get(earliest, 0.0) if earliest is not None else 0.0
    return (
        f"catches wrong-direction work by rung {earliest} at {frac:.0%} of code-cost "
        f"(N={len(bad)} bad / {n_seeds} seeds, {len(vessels)} vessels); "
        f"false-advance {false_advance_rate:.0%}."
    )


# ---------------------------------------------------------------------------------------------
# Altitude (Yao's second number) — first-attempt pass rate over N
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class AltitudeStat:
    """'ticket-altitude at X% first-attempt pass over N' — the second manifesto number.

    A `pass` is a good-direction ticket that reached the top rung on its first attempt (no
    descend-with-lesson). Computed from records, not simulated here — the caller supplies the
    counts (e.g. mined from a ledger / an ablation table)."""
    n: int
    first_attempt_passes: int
    condition: str = ""   # human label, e.g. "acceptance-as-code in context"

    @property
    def rate(self) -> float:
        return round(self.first_attempt_passes / self.n, 4) if self.n else 0.0

    def line(self) -> str:
        cond = f" [{self.condition}]" if self.condition else ""
        return f"ticket-altitude {self.rate:.0%} first-attempt pass over N={self.n}{cond}"


# ---------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------

_RUNG_NAMES = {r.number: r.name for r in WEB_LADDER_PROFILE.rungs}


def render_scoreboard(report: BenchReport, profile: LadderProfile = WEB_LADDER_PROFILE) -> str:
    """A plain-text scoreboard for the CLI. Deterministic ordering throughout."""
    names = {r.number: r.name for r in profile.rungs}
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  fls bench — the scoreboard")
    lines.append("=" * 72)
    lines.append(f"  vessels : {', '.join(report.vessels)}  ({len(report.vessels)})")
    lines.append(f"  seeds   : {len(report.seeds)}  ({report.n_bad} bad / {report.n_good} good)")
    lines.append("")
    lines.append("  metric 1 — rung-of-catch (bad-direction seeds)")
    for rung in sorted(report.rung_of_catch):
        label = "NEVER (false advance)" if rung == -1 else f"rung {rung} ({names.get(rung, '?')})"
        lines.append(f"      {label:<28} {report.rung_of_catch[rung]}")
    lines.append("")
    lines.append("  metric 2 — cost-to-catch per rung (% of full code-cost)")
    if report.cost_to_catch_per_rung:
        for rung in sorted(report.cost_to_catch_per_rung):
            frac = report.cost_to_catch_per_rung[rung]
            lines.append(f"      rung {rung} ({names.get(rung, '?'):<10}) {frac:6.1%}")
    else:
        lines.append("      (no catches)")
    lines.append("")
    lines.append(f"  metric 3 — false-advance rate : {report.false_advance_rate:.1%}")
    lines.append(f"  control  — false-catch  rate : {report.false_catch_rate:.1%}")
    lines.append("")
    lines.append("  HEADLINE")
    lines.append(f"      {report.headline}")
    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# CLI — `python -m fls.bench` (also the `fls-bench` console script; see pyproject)
# ---------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Print the scoreboard for the starter seed set using the zero-spend oracle judge.

    This is intentionally spend-free: it exercises the harness and prints the *shape* of the
    scoreboard. A live, model-backed bench (real judge + measured cost_model) is a separate,
    spend-gated caller — never wired into this default entry point.
    """
    import argparse

    from fls.bench_seeds import ALL_SEEDS, DASHBOARD_SEEDS, WEB_UI_SEEDS

    parser = argparse.ArgumentParser(
        prog="fls bench",
        description="The Fidelity Ladder scoreboard: rung-of-catch, cost-to-catch, false-advance.",
    )
    parser.add_argument(
        "--vessel", choices=["web-ui", "dashboard", "cli", "all"], default="all",
        help="which vessel's seeds to score (default: all).",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="run a LIVE model judge on the $0 skill-server subscription lane (needs "
             "FLS_SKILL_SERVER + FLS_SKILL_SERVER_KEY). No real spend, no sponsored-credit drawdown. "
             "Uses the FAITHFUL seed corpus (intent-vs-artifact) + the calibrated faithful judge.",
    )
    parser.add_argument(
        "--oracle-seeds", action="store_true",
        help="with --live, judge the legacy oracle-shaped seeds (bench_seeds) with the "
             "description-reading judge instead of the faithful corpus — for A/B comparison only.",
    )
    args = parser.parse_args(argv)

    if args.live:
        from fls.llm import SkillServerJudge
        judge = SkillServerJudge()
        if not judge.available():
            print("live judge unavailable — set FLS_SKILL_SERVER + FLS_SKILL_SERVER_KEY.")
            return 2

        def _log(sid, rung, caught, verdict):
            print(f"    {sid:<26} rung {rung}: {'DIVERGES' if caught else 'faithful'}  ({verdict})")

        if args.oracle_seeds:
            oracle = {"web-ui": WEB_UI_SEEDS, "dashboard": DASHBOARD_SEEDS,
                      "all": ALL_SEEDS}.get(args.vessel, ALL_SEEDS)  # legacy set has no 'cli' vessel
            print("  LIVE bench — LEGACY oracle seeds + description-reading judge (A/B baseline):")
            report = run_bench(oracle, judge=make_live_bench_judge(judge, log=_log))
            print(render_scoreboard(report))
            return 0

        from fls.bench_faithful_seeds import (
            ALL_FAITHFUL,
            CLI_FAITHFUL,
            DASHBOARD_FAITHFUL,
            WEB_UI_FAITHFUL,
        )
        fseeds = {"web-ui": WEB_UI_FAITHFUL, "dashboard": DASHBOARD_FAITHFUL,
                  "cli": CLI_FAITHFUL, "all": ALL_FAITHFUL}[args.vessel]
        print("  LIVE bench — FAITHFUL corpus + calibrated intent-vs-artifact judge")
        print("  (funded_by=subscription, real $ = 0; no sponsored-credit drawdown):")
        report = run_bench(fseeds, judge=make_faithful_bench_judge(judge, log=_log))
        print(render_scoreboard(report))
        print()
        print("  LIVE run — real model judgment on the free subscription lane. The judge sees only")
        print("  {intent, artifact-at-this-rung} and answers FAITHFUL | DIVERGES; the divergence in")
        print("  each bad seed is EMBEDDED in the artifact, never stated. See docs/bench-results.md.")
        return 0

    seeds = {"web-ui": WEB_UI_SEEDS, "dashboard": DASHBOARD_SEEDS, "all": ALL_SEEDS}[args.vessel]

    report = run_bench(seeds)  # oracle judge — zero spend
    print(render_scoreboard(report))
    print()
    print("  note: default run uses the zero-spend oracle judge (perfect ladder) — it verifies")
    print("  the harness, not the real ladder. Run with --live for a real skill-server judge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

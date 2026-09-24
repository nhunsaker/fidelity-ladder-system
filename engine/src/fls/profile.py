"""fidelity_ladder.profile — the ladder expressed as DATA (rungs-as-config).

A rung is a row, not a hand-written stage:

    {number · name · artifact_kind · dial · verifier · context_budget_chars ·
     builder_max_tokens · max_retries · termination}

The 6-rung **web-UI ladder** ships here as the *reference profile*, not the engine. Swapping the
profile changes what ladder runs without touching `climb.py`/`controller.py` — the "rungs-as-config"
claim (Chase). Magic caps that used to be hardcoded in `rung4`/`climb` (builder 1500 tokens · 3
retries · acceptance-context 2000 chars) are lifted here so an ANCHOR can declare per-rung budgets
instead of the engine baking them in.

The `dial` on each rung is the DEFAULT autonomy setting; an ANCHOR (and a VESSEL) may only ever
*tighten* it past this via the tighten-only cascade — never loosen (DIAL_ORDER, `fls.anchor`).
"""
from __future__ import annotations

from dataclasses import dataclass

from fls.anchor import Dial


@dataclass(frozen=True)
class RungSpec:
    """One rung, as data. `climb`/`rung4` read caps from here rather than hardcoding them."""
    number: int
    name: str
    artifact_kind: str          # what climbing THIS rung produces
    dial: Dial                  # default autonomy dial (ANCHOR/VESSEL may only tighten past it)
    verifier: str               # the verifier kind that gates advancement off this rung
    context_budget_chars: int   # cap on the builder's reading at this rung (0 = n/a). See NO_CAP.
    builder_max_tokens: int     # cap on the builder's output tokens (0 = n/a)
    max_retries: int            # width/termination: retry budget before a descend-with-lesson
    termination: str            # human-readable: what ends this rung
    line_budget: int = 0        # enforced rung-5 reviewability cap (Wu): diff lines a human can
                                 # review in <=10 minutes. 0 = n/a (not a review-gated rung).


@dataclass(frozen=True)
class LadderProfile:
    """An ordered ladder of rungs. THE unit you swap to run a different ladder."""
    name: str
    rungs: tuple[RungSpec, ...]

    def rung(self, number: int) -> RungSpec:
        for r in self.rungs:
            if r.number == number:
                return r
        raise KeyError(f"no rung {number} in profile {self.name!r}")

    @property
    def height(self) -> int:
        return len(self.rungs)


# The reference profile — the web-UI ladder, 6 rungs (0..5). Numbers mirror fls.funnel's
# THE READING CAP IS LARGE ON PURPOSE. A rung's reading material — the house rules, the API notes,
# the craft digest, the design pack — is a small fraction of an agentic session's window, and the
# only thing a small cap ever did was cut "No brand color at this rung" off the wireframe prompt
# on every run for weeks (the 6,000-character budget split three ways put the cut at character
# 2,000; the rule starts at 2,070). Rung 3's build rules were being cut the same way and nobody
# had noticed. The mechanism stays so it can be lowered later WITH EVIDENCE — never by feel.
NO_CAP = 1_000_000

# RUNG_INTENT/SPEC/WIRE/DEMO/MVP/FLAG = 0..5. Caps here reproduce the engine's prior hardcoded
# behavior exactly (builder_max_tokens=1500, max_retries=3, acceptance-context 2000 at rung 4).
WEB_LADDER_PROFILE = LadderProfile(
    name="web-ui",
    rungs=(
        RungSpec(0, "intent",    "idea",             Dial.human_picks,  "admission",      0,    0,    0, "admission gate — one door in"),
        RungSpec(1, "spec",      "spec",             Dial.auto_advance, "judge-rank",     3000, 1024, 1, "judge-ranked + one reflection pass"),
        RungSpec(2, "wireframe", "wireframe",        Dial.human_picks,  "human-pick",     NO_CAP, 1024, 0, "human picks the winning line"),
        RungSpec(3, "demo",      "interactive-demo", Dial.auto_advance, "walkthrough",    NO_CAP, 1500, 0, "walkthrough audit → advance | descend"),
        RungSpec(4, "mvp",       "mvp-code",         Dial.auto_advance, "acceptance-test",2000, 1500, 3, "retry to max → descend-with-lesson"),
        RungSpec(5, "flag",      "flagged-pr",       Dial.propose_only, "human-signoff",  4000, 1500, 0, "hard gate — propose only, never auto-ships", line_budget=400),
    ),
)


# Harness PoC profile (2026-09-10): the same six rungs, three of them VISIBLE to a demo user and
# every visible rung on `human-picks` — the founder's rule "only proceeds when approved with no
# revisions". Rung 2 produces Figma frames in a real file; rung 3 a prototype from a design-system
# pack (dial TIGHTENED from auto-advance to human-picks); rung 4 an agentic Claude Code build in a
# worktree of the stub repo. Caps are wider than web-ui because the builders are agentic sessions
# whose real budget is turns + wall clock (see fls.claude_code); token caps stay as guard rails.
HARNESS_POC_PROFILE = LadderProfile(
    name="harness-poc",
    rungs=(
        RungSpec(0, "intent",    "idea",             Dial.human_picks,  "admission",      0,    0,    0, "admission gate — one door in"),
        RungSpec(1, "spec",      "spec",             Dial.auto_advance, "judge-rank",     3000, 1024, 1, "judge-ranked + one reflection pass"),
        # Uncapped in practice (NO_CAP): every source arrives whole. The 8,000 before it was the
        # minimum that fit the two house rule files; the 6,000 before THAT cut the colour rule off
        # every prompt — see `figma_wireframe.reading` and the note on NO_CAP above.
        RungSpec(2, "wireframe", "figma-frames",     Dial.human_picks,  "human-pick",     NO_CAP, 2048, 0, "human picks the winning frame"),
        RungSpec(3, "demo",      "prototype",        Dial.human_picks,  "walkthrough",    NO_CAP, 4096, 0, "walkthrough audit, then human approves with no revisions"),
        RungSpec(4, "mvp",       "mvp-pr",           Dial.human_picks,  "acceptance-test",4000, 4096, 3, "agent-written test plan; retry to max → descend-with-lesson; human approves"),
        RungSpec(5, "flag",      "flagged-pr",       Dial.propose_only, "human-signoff",  4000, 1500, 0, "hard gate — propose only, never auto-ships", line_budget=400),
    ),
)

PROFILES: dict[str, LadderProfile] = {
    WEB_LADDER_PROFILE.name: WEB_LADDER_PROFILE,
    HARNESS_POC_PROFILE.name: HARNESS_POC_PROFILE,
}


def active_profile(name: str | None = None) -> LadderProfile:
    """The profile an instance runs: `name`, else env `FLS_PROFILE`, else the reference web-ui
    ladder. Unknown names fail loudly — a misspelled profile must never silently run web-ui."""
    import os
    key = name or os.environ.get("FLS_PROFILE") or WEB_LADDER_PROFILE.name
    try:
        return PROFILES[key]
    except KeyError:
        raise KeyError(f"unknown ladder profile {key!r}; known: {sorted(PROFILES)}") from None

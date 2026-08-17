"""fidelity_ladder — the importable core of the Fidelity Ladder.

    Code is the most expensive place to discover you built the wrong thing.
    Fidelity is a ratchet, not a throttle.

This is the framework surface: a *curated, semver'd* re-export of the reference implementation
(`fls`, the studio's own instance). It holds **mechanisms only** — zero web / GitHub / MCP imports
(grep-gated). The FastAPI harness, the GitHub surface, and ladder-mcp are optional extras
(`pip install fidelity-ladder[harness]` / `[mcp]`); you never need them to run a ladder.

The six module slots are the legos — AUTH · IDEAS · SOURCES · WORKERS · LENSES · ENVIRONMENT —
each a `typing.Protocol` + a `kind -> factory` registry, extended via the `FLS_MODULES` hook.
Four published **middleware seams** (`before_rung` / `after_rung` / `on_descend` /
`on_context_assembly`) let a module observe the climb without touching engine state. The
tighten-only cascade (ANCHOR -> VESSEL -> EXPEDITION) is law; the calibration ledger is how
autonomy is *earned*, not configured.

Anything importable from here is the public contract. Reach into `fls.*` for the reference
implementation's internals at your own semver risk.
"""
from __future__ import annotations

__version__ = "0.8.0"

# --- Policy: the one ANCHOR ---------------------------------------------------------------
# --- Adjudication: the pluggable Judge seam ----------------------------------------------
from fls.adjudicator import CouncilJudge, Idea, Judge, Judgment, make_adjudicator
from fls.anchor import Anchor, Dial, Verdict, Vessel, apply_anchor_edits, guardrails_prose

# --- The scoreboard: a number on the manifesto (Yao's `fls bench`) -----------------------
from fls.bench import (
    AltitudeStat,
    BenchReport,
    BenchSeed,
    SeedResult,
    run_bench,
)

# --- Durability: the climb resume entrypoint (v0.8 Phase 3) ------------------------------
from fls.climb import advance_expedition, resume_from_ledger

# --- Admission: one door -----------------------------------------------------------------
from fls.controller import on_idea, run_batch

# --- The climb unit + its states ---------------------------------------------------------
from fls.expedition import (
    AWAIT_PICK,
    CLIMBING,
    DOCKED,
    NEEDS_HUMAN,
    PARKED,
    RESUMING,
    Expedition,
)
from fls.funnel import RankedIdea

# --- Trust: the calibration ledger + the portable trace contract -------------------------
from fls.ledger import TRANSITION_KINDS, Decision, Ledger, TraceLog, Transition

# --- The cost unit every Judge/Worker returns (the "every claim carries its cost" primitive) -
from fls.llm import Call
from fls.mining import MiningReport, Mismatch, RungMining, mine

# --- The six slots: the legos ------------------------------------------------------------
from fls.modules import (
    AUTH,
    ENVIRONMENTS,
    IDEAS,
    LENSES,
    MIDDLEWARE,
    MIDDLEWARE_HOOKS,
    SOURCES,
    WORKERS,
    Auth,
    Environment,
    EnvironmentHandle,
    IdeaSource,
    Lens,
    Middleware,
    Source,
    VerifyResult,
    Worker,
    WorktreeEnvironment,
    dispatch_middleware,
    load_modules,
    register_middleware,
)

# --- Rungs-as-config: the ladder as data -------------------------------------------------
from fls.profile import WEB_LADDER_PROFILE, LadderProfile, RungSpec

__all__ = [
    "__version__",
    # policy
    "Anchor", "Dial", "Verdict", "Vessel", "apply_anchor_edits", "guardrails_prose",
    # admission
    "on_idea", "run_batch", "Call",
    # scoreboard (fls bench)
    "run_bench", "BenchSeed", "BenchReport", "SeedResult", "AltitudeStat",
    # adjudication
    "Judge", "Judgment", "Idea", "CouncilJudge", "make_adjudicator",
    # trust / calibration
    "Ledger", "Decision", "mine", "MiningReport", "Mismatch", "RungMining",
    # trust / portable trace contract (v0.8 Phase 3)
    "TraceLog", "Transition", "TRANSITION_KINDS", "resume_from_ledger",
    # rungs-as-config
    "LadderProfile", "RungSpec", "WEB_LADDER_PROFILE",
    # climb
    "Expedition", "RankedIdea", "advance_expedition",
    "CLIMBING", "PARKED", "DOCKED", "NEEDS_HUMAN", "AWAIT_PICK", "RESUMING",
    # the six slots
    "Worker", "IdeaSource", "Lens", "Source", "Auth", "Environment",
    "WORKERS", "IDEAS", "LENSES", "SOURCES", "AUTH", "ENVIRONMENTS", "load_modules",
    "EnvironmentHandle", "VerifyResult", "WorktreeEnvironment",
    # the middleware seams
    "Middleware", "MIDDLEWARE", "MIDDLEWARE_HOOKS",
    "register_middleware", "dispatch_middleware",
]

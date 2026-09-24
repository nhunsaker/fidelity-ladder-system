"""Payload dataclasses shared by the workflow and its activities (JSON-serializable by Temporal's
default data converter). Keep them flat and primitive: no engine objects cross this boundary."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExpeditionInput:
    number: int
    intent: str
    success: str = ""
    altitude: str = "feature"
    source: str = "demo"
    profile: str = "harness-poc"


@dataclass
class WorkflowConfig:
    """Per-rung wall-clock caps (seconds) — the ANCHOR `worker:` block, flattened."""
    # DOUBLED 2026-09-13 (founder: durability over cost). A rung has no resumption: a wall clock
    # that expires throws away everything the session did and charges for it. Wall clock is also
    # the cheapest durability there is — a rung that finishes in five minutes bills five minutes
    # whether the cap is ten or twenty, so headroom is only ever spent by work that needs it.
    #
    # What makes generous caps safe is the heartbeat: a DEAD worker is now caught in 60s
    # regardless (activities._Beat), so these bound only work that is slow and alive. Before the
    # heartbeat was fixed the two were indistinguishable and expedition 17 waited out the full
    # 900s having already stopped existing.
    spec_s: int = 600
    wireframe_s: int = 1200
    prototype_s: int = 1800
    build_s: int = 4800
    ship_s: int = 1200
    max_feedback_rounds: int = 5      # per rung; past this the expedition parks (never loops forever)
    # How many times rung 1 may ask what a word meant. Separate from feedback rounds and much
    # smaller: a revision loop is a conversation, but a referent nobody can settle in two tries is
    # a request that needs rewriting, not another question.
    max_answer_rounds: int = 2
    # The ANCHOR's `budgets.per_expedition_ceiling_usd`, in NORMALIZED dollars.
    #
    # It was enforced in `controller.py` and `climb.py` and nowhere in this package — which is the
    # only path this instance actually runs. Expedition 12 spent $6.25 against a declared $6.00
    # and nothing stopped it; it parked on the line budget by coincidence. Meanwhile the Budgets
    # screen called the number "the fail-closed money line — it does not creep and it does not ask
    # again", which was not true here.
    #
    # NORMALIZED, not metered, because this instance's builder runs on the subscription lane where
    # metered spend is genuinely $0.00 — a ceiling measured in metered dollars can never bite, and
    # the ANCHOR's own non-negotiable says the ledger records subscription work at its normalized
    # cost. 0.0 means unenforced, so an instance that declares no ceiling behaves as before.
    ceiling_usd: float = 0.0


@dataclass
class HarnessRun:
    """The single workflow argument (Temporal's recommended shape: one dataclass, evolvable)."""
    input: ExpeditionInput
    cfg: WorkflowConfig = field(default_factory=WorkflowConfig)


@dataclass
class RungRequest:
    """What an activity needs to run one rung once. `feedback` carries the human's latest
    request-for-changes (re-run semantics); `picked` the chosen candidate index at rung 2."""
    number: int
    rung: int
    intent: str
    success: str = ""
    spec: str = ""
    picked: int | None = None
    feedback: str = ""
    attempt: int = 1
    # The question rung 1 asked, when this run is answering one. JSON-safe and defaulted, so a
    # payload written by an older worker deserializes unchanged.
    question: dict | None = None


@dataclass
class RungResult:
    """One rung's outcome. `artifacts` is what the Demo view shows (links, paths); `state` is the
    parked state the workflow should wait in next (await-pick | await-approve | await-signoff |
    descended | parked | done)."""
    rung: int
    passed: bool
    state: str
    detail: str = ""
    spec: str = ""
    artifacts: dict = field(default_factory=dict)
    normalized_usd: float = 0.0
    calls: int = 0


@dataclass
class Status:
    """The query result the Demo view polls (through the harness, never Temporal directly)."""
    number: int
    rung: int
    state: str
    stage: str                       # demo-user words: requested | wireframed | previewed | built | shipped
    detail: str = ""
    artifacts: dict = field(default_factory=dict)
    spent_normalized_usd: float = 0.0
    # Of that total, how much went on re-doing work an interrupted attempt had already paid for.
    # Reported rather than gated: a run that spent half its budget recovering is telling you
    # something is breaking, and that is worth knowing even though the ceiling bounds normalized
    # spend rather than real money.
    recovered_normalized_usd: float = 0.0
    feedback_log: list[str] = field(default_factory=list)
    killed: bool = False
    attempts: dict = field(default_factory=dict)


STAGE_WORDS = {0: "requested", 1: "requested", 2: "wireframed", 3: "previewed", 4: "built", 5: "shipped"}

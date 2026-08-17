"""Autonomy ledger — the flywheel data (Chase#2, Wang#5). Full schema from decision one.

Each decision logs: rung, expedition, judge verdict, human verdict, agreement, judge
cost-per-verdict. The demote trigger (defined in ANCHOR) reads a rolling window of agreement
per rung; below threshold it tightens the dial one step and flags the gatekeeper. The P3 admin
button READS this; it does not define it.

Append-only JSONL so it doubles as an audit trail.

v0.8 Phase 3 (Chase's "ledger as portable trace contract" — see `Transition`/`TraceLog` below):
the calibration `Decision` stream above answers "was this verdict trustworthy"; the `Transition`
stream answers "where is this expedition" — a framework-agnostic, replayable record of every
expedition state change, independent of any in-memory harness object or process. The two are
deliberately separate JSONL streams (own path, own class) so existing `ledger.jsonl` deployments
(Decision-only) are untouched; a harness that wants durability opts in by also writing to a
`TraceLog`.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fls.anchor import DIAL_ORDER, Anchor, Dial


@dataclass
class Decision:
    expedition: int
    rung: str
    judge_verdict: str
    human_verdict: str | None       # None until a human weighs in
    judge_cost_usd: float
    judge_tokens_in: int = 0
    judge_tokens_out: int = 0
    # human-latency (Yao#3): success is defined against the interactive reality — how long a
    # gate actually waits for its human. Epoch seconds, injected by the caller (the harness
    # stamps gate_opened_at when it posts the ask, human_responded_at on the reply).
    gate_opened_at: float | None = None
    human_responded_at: float | None = None
    # v0.7 #3 — optional vessel tag (Vessel.name) so per-vessel slices (mining.mine(vessel=...))
    # can filter the ledger without a schema migration. None = untagged/anchor-level, the
    # historical default; purely additive, back-compat with every existing jsonl row.
    vessel: str | None = None
    # v0.8 Phase 2 P2c — lagged-outcome column (schema only; inference/loosening logic is
    # explicitly DEFERRED, see fls-v0.8-framework.md §7). Once an expedition's real-world
    # outcome is known (shipped-and-kept, shipped-and-reverted, never-shipped, ...) a caller can
    # backfill this field on the ORIGINAL Decision's re-recorded row (the ledger is append-only,
    # so a backfill is a new row referencing the same expedition/rung, not a mutation in place).
    # None = unknown/not-yet-observed, the default for every row today. Purely additive:
    # back-compat with every existing jsonl row (missing key -> None via dataclass default).
    outcome: str | None = None

    @property
    def agreed(self) -> bool | None:
        if self.human_verdict is None:
            return None
        return self.judge_verdict == self.human_verdict

    @property
    def human_latency_s(self) -> float | None:
        if self.gate_opened_at is None or self.human_responded_at is None:
            return None
        return max(0.0, self.human_responded_at - self.gate_opened_at)


@dataclass
class Ledger:
    path: Path
    rows: list[Decision] = field(default_factory=list)

    def record(self, d: Decision) -> None:
        self.rows.append(d)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(d)) + "\n")

    def load(self) -> Ledger:
        if Path(self.path).exists():
            self.rows = [Decision(**json.loads(line)) for line in Path(self.path).read_text().splitlines() if line]
        return self

    def agreement_rate(self, rung: str, window: int) -> float | None:
        """Rolling judge-vs-human agreement at a rung (None if no human-scored rows yet)."""
        scored = deque(
            (d.agreed for d in self.rows if d.rung == rung and d.agreed is not None),
            maxlen=window,
        )
        if not scored:
            return None
        return sum(1 for x in scored if x) / len(scored)

    def human_latency_avg(self, rung: str | None = None) -> float | None:
        """Mean time-to-human-response (s) across gates that have both timestamps (Yao#3)."""
        lats = [d.human_latency_s for d in self.rows
                if (rung is None or d.rung == rung) and d.human_latency_s is not None]
        if not lats:
            return None
        return round(sum(lats) / len(lats), 1)

    def cost_per_verdict(self, rung: str | None = None) -> float | None:
        rows = [d for d in self.rows if rung is None or d.rung == rung]
        if not rows:
            return None
        return sum(d.judge_cost_usd for d in rows) / len(rows)

    def demote_check(self, rung: str, anchor: Anchor, current: Dial) -> Dial | None:
        """Returns the tightened dial if the rung has fallen below the ANCHOR agreement
        threshold over the window; else None. Tighten-only: never loosens."""
        trig = anchor.autonomy_demote
        rate = self.agreement_rate(rung, trig.window)
        if rate is None or rate >= trig.agreement_threshold:
            return None
        idx = DIAL_ORDER.index(current)
        return DIAL_ORDER[max(0, idx - 1)]  # one step tighter


# === Transition / TraceLog — the portable trace contract (v0.8 Phase 3) =====================
#
# THE TRACE CONTRACT — every `Transition` row carries exactly these fields, and ONLY these
# fields are load-bearing for replay. A harness other than this one, reading the same
# `trace.jsonl`, reconstructs identical expedition state from them alone:
#
#   expedition    int            join key — same id space as Decision.expedition
#   seq           int            0-based, strictly increasing PER expedition; the authoritative
#                                 replay order (append order in a shared file is not, once more
#                                 than one expedition interleaves writes)
#   kind          str            the transition kind, one of TRANSITION_KINDS below
#   rung          int            the expedition's rung ordinal immediately AFTER this transition
#                                 (RUNG_INTENT..RUNG_FLAG, see fls.funnel)
#   status        str            the expedition's status string immediately after this
#                                 transition (see fls.expedition status constants)
#   target_rung   int            the ceiling this expedition is climbing toward — a resumed
#                                 climb needs this to know how far to keep going
#   dial          str | None     Dial.value in effect at this transition, if known
#   spec          str | None     the winning rung-1 spec text, carried forward once set
#   picked_wireframe int | None  the human's rung-2 pick, carried forward once set
#   reason        str | None     dock/park/descend/signoff reason text, if any
#   spent_usd     float          CUMULATIVE spend checkpoint (a running total, not a per-call
#                                 delta) — lets a resumed expedition's budget-ceiling checks stay
#                                 correct without replaying the full Call history
#   idea          dict           a full snapshot of the immutable Idea (number/intent/success/
#                                 altitude/source) — replay never needs a side lookup into the
#                                 harness's own store to know what idea this expedition is
#   at            float | None   caller-supplied wall-clock (epoch seconds) of the transition —
#                                 observability only, never consulted by replay logic
#
# Fields are carried-forward snapshots (like Expedition itself), not deltas: the LATEST row for
# an expedition alone is sufficient to reconstruct its current state — you never need to fold
# the whole history, only find the tail. History is still kept (append-only) for audit/replay-
# from-any-point, but `resume_from_ledger` only ever needs `rows[-1]`.

TRANSITION_KINDS = (
    "admitted",        # idea passed the admission gate, expedition spawned
    "rung-advance",     # e.rung moved forward (e.g. -> demo, -> mvp)
    "await-pick",       # parked waiting on a human wireframe/lane pick
    "picked",           # a human supplied the pick; climb resumes
    "descended",        # a design failure sent the expedition back down a rung, with a lesson
    "parked",           # budget ceiling or explicit park; climbing paused, not failed
    "await-signoff",    # rung-5 hard gate; never auto-ships past this
    "killed",           # a named human stopped the expedition
    "resumed",          # the expedition was reconstructed from the trace after an interruption
)


@dataclass
class Transition:
    expedition: int
    seq: int
    kind: str
    rung: int
    status: str
    target_rung: int
    idea: dict
    dial: str | None = None
    spec: str | None = None
    picked_wireframe: int | None = None
    reason: str | None = None
    spent_usd: float = 0.0
    at: float | None = None


@dataclass
class TraceLog:
    """Append-only JSONL of `Transition` rows — the framework-agnostic trace/emit contract.
    Deliberately a separate stream/file from the calibration `Ledger` (own path, own class) so
    existing Decision-only `ledger.jsonl` deployments are unaffected; a harness durable-by-choice
    opts in by also constructing a `TraceLog` alongside its `Ledger`."""
    path: Path
    rows: list[Transition] = field(default_factory=list)

    def append(self, t: Transition) -> None:
        self.rows.append(t)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(t)) + "\n")

    def load(self) -> TraceLog:
        if Path(self.path).exists():
            self.rows = [Transition(**json.loads(line))
                         for line in Path(self.path).read_text().splitlines() if line]
        return self

    def for_expedition(self, expedition: int) -> list[Transition]:
        """All rows for one expedition, in replay order (by `seq`, not file-append order)."""
        return sorted((t for t in self.rows if t.expedition == expedition), key=lambda t: t.seq)

    def latest(self, expedition: int) -> Transition | None:
        rows = self.for_expedition(expedition)
        return rows[-1] if rows else None

    def next_seq(self, expedition: int) -> int:
        """The next `seq` to use for `expedition` — callers building a `Transition` don't have
        to track sequence numbers themselves."""
        rows = self.for_expedition(expedition)
        return (rows[-1].seq + 1) if rows else 0

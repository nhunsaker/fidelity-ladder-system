"""Judge-calibration mining layer (v0.6 #7) — turns the calibration ledger's mismatch/override
data into a stable, snapshotted `MiningReport` for the earning-history UI (v0.6 #6) to render.

`calibration.py` already computes judge-vs-human agreement per rung from the ledger
(`rung_calibration`, `build_report`). Mining sits alongside it and adds two things
calibration's single-readout shape doesn't have:

1. A FROZEN output contract (`MiningReport`) — see the dataclasses below — so the earning-
   history worker has a fixed schema to render against, independent of calibration's own
   internal shape.
2. An append-only snapshot ledger (JSONL, one `MiningReport` per line) so `drift_trend` can
   compare the latest agreement_rate against prior runs, not just report a single point.

Nothing here writes into `ledger.jsonl` or reads from `anchor.py`/`funnel.py`/`adjudicator.py`/
`rung5.py` beyond the existing `Ledger`/`Anchor` types — it is a pure read+derive layer.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fls.anchor import Anchor
from fls.ledger import Ledger

_DEFAULT_HISTORY_FILE = "mining-history.jsonl"
# agreement-rate delta below this magnitude reads as "flat" (no noise-chasing on n=1 wobble)
_DRIFT_EPSILON = 0.02
# v0.7 — mining-persistence cadence floor: don't accrue mining-history.jsonl on every read, only
# once per this interval (default: once/day). Read paths call `mine_if_due` instead of
# `mine_and_persist` directly so the guard is centralized here, not duplicated per call site.
DEFAULT_MINE_MIN_INTERVAL_S = 24 * 60 * 60


def default_history_path(root: str | Path | None = None) -> Path:
    """Resolve the mining-snapshot ledger path.

    Precedence: `FLS_MINING_HISTORY_PATH` env override, else `<root>/mining-history.jsonl`,
    else `./mining-history.jsonl`. Mirrors the env-config pattern used elsewhere in this repo
    (e.g. `FLS_REPO`, `FLS_WEBHOOK_SECRET`) — identity/paths are instance config, never
    hardcoded.
    """
    env = os.environ.get("FLS_MINING_HISTORY_PATH")
    if env:
        return Path(env)
    base = Path(root) if root is not None else Path(".")
    return base / _DEFAULT_HISTORY_FILE


# --- frozen output contract -------------------------------------------------------------
# NOTE: the build spec describes `rung` as `int`. The ledger's actual `Decision.rung` field
# (see ledger.py / funnel.py) is a stable string label ("1-spec", "2-wireframe", ...) — the
# same type `RungCalibration.rung` already uses in calibration.py. Mining reports that string
# label as-is rather than inventing an ordinal mapping calibration.py doesn't have. Flagged for
# the earning-history consumer to confirm; everything else matches the contract exactly.

@dataclass
class RungMining:
    rung: str
    samples: int
    agreement_rate: float
    human_override_rate: float
    drift_trend: str = "flat"   # "improving" | "flat" | "declining"


@dataclass
class Mismatch:
    rung: str
    idea_id: int
    judge_verdict: str
    human_verdict: str
    note: str


@dataclass
class MiningReport:
    computed_at: str                                    # iso8601
    per_rung: list[RungMining] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)
    recommendation: str = "hold — no calibration data yet"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> MiningReport:
        return cls(
            computed_at=d["computed_at"],
            per_rung=[RungMining(**r) for r in d.get("per_rung", [])],
            mismatches=[Mismatch(**m) for m in d.get("mismatches", [])],
            recommendation=d.get("recommendation", "hold — no calibration data yet"),
        )


# --- mining ------------------------------------------------------------------------------

def mine(ledger: Ledger, anchor: Anchor, history: list[MiningReport] | None = None,
         *, computed_at: str | None = None, vessel: str | None = None) -> MiningReport:
    """Derive a MiningReport from the ledger's current state. `history` (oldest-first prior
    snapshots, e.g. from `read_history()`) drives `drift_trend`; omit/empty for a first run.

    `vessel` (v0.7 #3) optionally slices to only rows tagged with that Vessel.name (see
    `Decision.vessel`, `controller.on_idea(vessel=...)`); rows with no vessel tag (or when
    `vessel` is omitted/None) are all included — the historical, anchor-level behavior. This is
    a pure read-side filter: the frozen `MiningReport` shape is unchanged, so existing callers
    (mine_and_persist, the anchor-level /mining-history history file) are unaffected."""
    ts = computed_at or datetime.now(UTC).isoformat()
    history = history or []
    rows_scope = [d for d in ledger.rows if vessel is None or getattr(d, "vessel", None) == vessel]
    rungs = sorted({d.rung for d in rows_scope})
    trig = anchor.autonomy_demote

    per_rung: list[RungMining] = []
    mismatches: list[Mismatch] = []
    for rung in rungs:
        rows = [d for d in rows_scope if d.rung == rung]
        scored = [d for d in rows if d.agreed is not None]
        overrides = [d for d in scored if not d.agreed]
        agreement = (sum(1 for d in scored if d.agreed) / len(scored)) if scored else 0.0
        override_rate = (len(overrides) / len(scored)) if scored else 0.0
        trend = _drift_trend(rung, agreement, history)
        per_rung.append(RungMining(rung, len(rows), round(agreement, 4), round(override_rate, 4),
                                    trend))
        for d in overrides:
            mismatches.append(Mismatch(rung, d.expedition, d.judge_verdict, d.human_verdict,
                                        f"judge={d.judge_verdict} human={d.human_verdict}"))

    rec = _recommend(per_rung, trig)
    return MiningReport(ts, per_rung, mismatches, rec)


def _drift_trend(rung: str, latest_agreement: float, history: list[MiningReport]) -> str:
    """Compare `latest_agreement` against the most recent prior snapshot that scored this
    rung. No prior snapshot -> "flat" (nothing to compare against yet)."""
    prior = None
    for snap in reversed(history):
        match = next((r for r in snap.per_rung if r.rung == rung), None)
        if match is not None:
            prior = match.agreement_rate
            break
    if prior is None:
        return "flat"
    delta = latest_agreement - prior
    if delta > _DRIFT_EPSILON:
        return "improving"
    if delta < -_DRIFT_EPSILON:
        return "declining"
    return "flat"


def _recommend(per_rung: list[RungMining], trig) -> str:
    if not per_rung:
        return "hold — no calibration data yet"
    tighten = [r.rung for r in per_rung
               if r.samples >= trig.window and r.agreement_rate < trig.agreement_threshold]
    declining = [r.rung for r in per_rung if r.drift_trend == "declining"]
    loosen = [r.rung for r in per_rung if r.samples >= trig.window and r.agreement_rate >= 0.95]
    if tighten:
        return f"tighten: {', '.join(tighten)} below agreement floor"
    if declining:
        return f"watch: {', '.join(declining)} trending down"
    if loosen:
        return f"eligible-to-loosen: {', '.join(loosen)}"
    return "hold — within calibration band"


# --- persistence (append-only snapshot ledger) ------------------------------------------

def append_snapshot(report: MiningReport, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(report.to_dict()) + "\n")


def read_history(path: str | Path) -> list[MiningReport]:
    """Oldest-first list of prior snapshots. Missing file -> [] (empty-history is a normal
    first-run state, not an error)."""
    path = Path(path)
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [MiningReport.from_dict(json.loads(ln)) for ln in lines]


def mine_and_persist(ledger: Ledger, anchor: Anchor, path: str | Path,
                      *, computed_at: str | None = None) -> MiningReport:
    """Convenience wrapper: read prior snapshots, mine a fresh report against them (so
    drift_trend has something to compare to), append it, and return it."""
    history = read_history(path)
    report = mine(ledger, anchor, history, computed_at=computed_at)
    append_snapshot(report, path)
    return report


# --- persistence cadence (v0.7) -----------------------------------------------------------
# mine_and_persist is spend-free (it only reads the ledger + appends a snapshot line), but
# calling it on every read-path hit would still make mining-history.jsonl grow unboundedly and
# make drift_trend noisy (n=1-request wobble). should_mine/mine_if_due gate it to a min-interval
# cadence (default: once/day) so the file accrues a real, spaced-out earned track record.

def should_mine(history: list[MiningReport], *, now: str | None = None,
                 min_interval_s: float = DEFAULT_MINE_MIN_INTERVAL_S) -> bool:
    """True when a fresh mine_and_persist is due: no prior snapshot, the prior snapshot's
    `computed_at` can't be parsed (fail-open — never get permanently stuck), or it's older than
    `min_interval_s`. `now` overrides the reference instant (ISO8601) for testability; omitted
    uses the real UTC now."""
    if not history:
        return True
    try:
        last = datetime.fromisoformat(history[-1].computed_at)
    except (ValueError, TypeError):
        return True
    ref = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=UTC)
    return (ref - last).total_seconds() >= min_interval_s


def mine_if_due(ledger: Ledger, anchor: Anchor, path: str | Path, *, now: str | None = None,
                 min_interval_s: float = DEFAULT_MINE_MIN_INTERVAL_S) -> MiningReport | None:
    """Idempotent cadence wrapper: mine_and_persist's a fresh snapshot ONLY when `should_mine`
    says the last one is stale/absent; otherwise a no-op returning None. Read paths (e.g.
    `GET /mining-history`) call this before `read_history` so the file accrues real snapshots
    over time without persisting on every request."""
    history = read_history(path)
    if not should_mine(history, now=now, min_interval_s=min_interval_s):
        return None
    return mine_and_persist(ledger, anchor, path, computed_at=now)

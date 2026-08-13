"""Autonomy ledger — the flywheel data (Chase#2, Wang#5). Full schema from decision one.

Each decision logs: rung, expedition, judge verdict, human verdict, agreement, judge
cost-per-verdict. The demote trigger (defined in ANCHOR) reads a rolling window of agreement
per rung; below threshold it tightens the dial one step and flags the gatekeeper. The P3 admin
button READS this; it does not define it.

Append-only JSONL so it doubles as an audit trail.
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

    @property
    def agreed(self) -> bool | None:
        if self.human_verdict is None:
            return None
        return self.judge_verdict == self.human_verdict


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

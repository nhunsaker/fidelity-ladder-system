"""Calibration readout (Yao#4, Ng#3) — ships at P3, NOT deferred to P6.

The autonomy ledger has collected judge-vs-human agreement + cost since decision one. This turns
that data into a periodic readout: per-rung agreement, disagreement categories, cost-per-verdict
trend, and a dial RECOMMENDATION per rung. The admin UI's autonomy panel renders it; a human
still applies any dial change. Data collected from P1 finally gets LOOKED AT here.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from fls.anchor import Anchor
from fls.ledger import Ledger


@dataclass
class RungCalibration:
    rung: str
    decisions: int
    scored: int                       # decisions a human also weighed in on
    agreement: float | None           # None if nothing scored yet
    cost_per_verdict: float | None
    disagreements: list[str] = field(default_factory=list)   # judge->human mismatch examples
    recommendation: str = "hold"      # hold | tighten | eligible-to-loosen


def rung_calibration(ledger: Ledger, anchor: Anchor, rung: str) -> RungCalibration:
    rows = [d for d in ledger.rows if d.rung == rung]
    scored = [d for d in rows if d.agreed is not None]
    agree = (sum(1 for d in scored if d.agreed) / len(scored)) if scored else None
    cpv = ledger.cost_per_verdict(rung)
    trig = anchor.autonomy_demote

    mismatches = [f"judge={d.judge_verdict} human={d.human_verdict}"
                  for d in scored if not d.agreed][:5]

    rec = "hold"
    if agree is not None and len(scored) >= trig.window:
        if agree < trig.agreement_threshold:
            rec = "tighten"                       # falling below floor -> demote
        elif agree >= 0.95:
            rec = "eligible-to-loosen"            # earned autonomy (human confirms)
    return RungCalibration(rung, len(rows), len(scored), agree, cpv, mismatches, rec)


@dataclass
class CalibrationReport:
    rungs: list[RungCalibration]
    total_decisions: int
    total_cost: float

    def as_markdown(self) -> str:
        lines = ["## Calibration readout\n",
                 "| rung | decisions | agreement | $/verdict | recommendation |",
                 "|---|---|---|---|---|"]
        for r in self.rungs:
            ag = "-" if r.agreement is None else f"{r.agreement:.0%}"
            cp = "-" if r.cost_per_verdict is None else f"${r.cost_per_verdict:.4f}"
            lines.append(f"| {r.rung} | {r.decisions} | {ag} | {cp} | {r.recommendation} |")
        lines.append(f"\n_total decisions: {self.total_decisions} · total judge cost: "
                     f"${self.total_cost:.4f}_")
        return "\n".join(lines)


def build_report(ledger: Ledger, anchor: Anchor) -> CalibrationReport:
    rungs = sorted({d.rung for d in ledger.rows})
    cals = [rung_calibration(ledger, anchor, r) for r in rungs]
    total_cost = round(sum(d.judge_cost_usd for d in ledger.rows), 4)
    return CalibrationReport(cals, len(ledger.rows), total_cost)


def category_slice(ledger: Ledger) -> dict[str, int]:
    """Disagreement categories across all rungs — 'what does the judge get wrong most'."""
    c: Counter[str] = Counter()
    for d in ledger.rows:
        if d.agreed is False:
            c[f"{d.judge_verdict}->{d.human_verdict}"] += 1
    return dict(c.most_common())

"""Rung 2 — wireframe fan-out + pick-of-3 (dial: human-picks).

Builder produces N low-fidelity Primer HTML skeletons from the winning rung-1 spec (structure
only: layout, regions, placeholder labels — no real styling). A judge ranks them to SEED the
human's pick, but the pick itself is a human decision through the one protocol (issue comment).
Cheapest rung after intent; runs at full funnel width ("wireframes: all").

Artifacts persist to expeditions/<id>/wireframes/ so the issue/admin UI can render them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fls.adjudicator import Idea, Judge
from fls.llm import Call
from fls.rung1 import Builder

_WIRE_SYS = (
    "You produce a LOW-FIDELITY wireframe as a single self-contained HTML fragment using Primer "
    "CSS utility classes (Box, p-*, d-flex, form-control, btn) for structure only. No colors, no "
    "copy beyond placeholder labels, no scripts. Show layout + regions the spec implies. Vary the "
    "layout approach from other candidates. Return ONLY the HTML fragment, under 350 tokens."
)
_RANK_SYS = (
    "You rank low-fi wireframes by how clearly each expresses the spec's flow and structure. "
    "Reply with a JSON array of indices, best first, e.g. [1,0,2]. Array only."
)
_ARR = re.compile(r"\[[^\]]*\]")


@dataclass
class Rung2Result:
    wireframes: list[str]           # HTML fragments, index-aligned
    suggested_ranking: list[int]    # judge suggestion; human makes the real pick
    calls: list[Call] = field(default_factory=list)
    picked_index: int | None = None  # set when the human picks (via controller)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    def persist(self, expeditions_dir: str | Path, expedition: int) -> Path:
        d = Path(expeditions_dir) / str(expedition) / "wireframes"
        d.mkdir(parents=True, exist_ok=True)
        for i, w in enumerate(self.wireframes):
            (d / f"candidate-{i}.html").write_text(w, encoding="utf-8")
        (d / "ranking.json").write_text(json.dumps(self.suggested_ranking), encoding="utf-8")
        return d


def run_rung2(idea: Idea, spec: str, builder: Builder, judge: Judge,
              n: int = 3, max_tokens: int = 360) -> Rung2Result:
    calls: list[Call] = []
    wires: list[str] = []
    for i in range(n):
        text, call = builder.complete(
            f"SPEC:\n{spec}\n\nWireframe candidate #{i+1}. Return the HTML fragment only.",
            max_tokens=max_tokens, system=_WIRE_SYS,
        )
        wires.append(text.strip())
        calls.append(call)

    numbered = "\n\n".join(f"[{i}] {w[:400]}" for i, w in enumerate(wires))
    rtext, rcall = judge.complete(
        f"SPEC:\n{spec}\n\nWIREFRAMES:\n{numbered}\n\nRank them.",
        max_tokens=48, system=_RANK_SYS,
    )
    calls.append(rcall)
    m = _ARR.search(rtext or "")
    try:
        ranking = [int(x) for x in json.loads(m.group(0))] if m else list(range(n))
    except (ValueError, TypeError):
        ranking = list(range(n))
    ranking = [i for i in ranking if 0 <= i < n] or list(range(n))
    return Rung2Result(wires, ranking, calls)

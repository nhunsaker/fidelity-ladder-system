"""Rung 2 — Exploration: fidelity-adaptive fan-out + pick-of-N (dial: human-picks).

The human picks the LINE (climbing lexicon: candidates are "lines" — you pick the line you'll
climb). Two fidelities, chosen by what the expedition is:

  - "structure" (default, today's behavior): LOW-FIDELITY Primer skeletons — layout/regions/
    placeholder labels, no real styling. Right for a NEW flow/screen where structure is the
    question.
  - "variants" (V3): CONCRETE styled variants of the ACTUAL element — real colors/weights/
    shapes/sizes, composed from the app's component library named in the grounding. Right for a
    UI TWEAK ("make the button bolder") where gray boxes answer nothing (Ng: the gray-boxes
    complaint is a context problem — grounding carries the real library in).
  - "auto": one cheap judge call classifies the expedition, FAIL-OPEN to "structure".

A judge ranks the lines to SEED the human's pick, but the pick is a human decision through the
one protocol (issue comment). Markdown code fences are stripped from every line before storing
(the #4 climb needed this by hand — encoded here). Artifacts persist to
expeditions/<id>/wireframes/ (file contract unchanged: candidate-*.html + ranking.json, plus a
mode.json the admin viewer can read) so the issue/admin UI keeps rendering.
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
_VARIANTS_SYS = (
    "You produce ONE concrete design VARIANT (a 'line') of a specific EXISTING UI element as a "
    "single self-contained HTML fragment. This is EXPLORATION, not wireframing: use REAL colors, "
    "font weights, shapes, and sizes. Compose from the component library named in the CONTEXT "
    "(its buttons, tokens, classes) rather than hand-rolling bare HTML. Make this variant visually "
    "DISTINCT from the others — e.g. a bolder button might differ in weight, color treatment, and "
    "shape+size. No scripts. Return ONLY the HTML fragment, under 350 tokens."
)
_RANK_SYS = (
    "You rank the candidate design lines by how clearly each expresses the spec's intent. "
    "Reply with a JSON array of indices, best first, e.g. [1,0,2]. Array only."
)
_CLASSIFY_SYS = (
    "Classify a fidelity-ladder expedition for its exploration fidelity. Is it a UI tweak to an "
    "existing element (answer VARIANTS) or a new flow/screen/structure (answer STRUCTURE)? "
    "Answer with ONE word only: VARIANTS or STRUCTURE."
)
_ARR = re.compile(r"\[[^\]]*\]")
_FENCE = re.compile(r"^\s*```")

MODES = ("structure", "variants", "auto")


def _strip_fences(text: str) -> str:
    """Strip markdown code-fence lines (```), keeping the HTML between them. The #4 climb needed
    this hand-cleanup before the admin viewer would render the candidate — so encode it, both modes."""
    kept = [ln for ln in (text or "").splitlines() if not _FENCE.match(ln)]
    return "\n".join(kept).strip()


def _classify(idea: Idea, spec: str, judge: Judge) -> tuple[str, Call | None]:
    """One cheap judge call → 'variants' | 'structure'. FAIL-OPEN to 'structure' on any error or
    ambiguity (exploration should never block; low-fi structure is the safe default)."""
    try:
        text, call = judge.complete(
            f"EXPEDITION:\nIntent: {idea.intent}\nSpec: {spec[:400]}\n\n"
            "UI tweak to an existing element, or a new flow/screen/structure?",
            max_tokens=8, system=_CLASSIFY_SYS,
        )
    except Exception:
        return "structure", None
    return ("variants" if "variant" in (text or "").strip().lower() else "structure"), call


@dataclass
class Rung2Result:
    wireframes: list[str]           # HTML fragments ("lines"), index-aligned
    suggested_ranking: list[int]    # judge suggestion; human makes the real pick
    calls: list[Call] = field(default_factory=list)
    picked_index: int | None = None  # set when the human picks (via controller)
    mode: str = "structure"          # resolved fidelity: structure | variants

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    def persist(self, expeditions_dir: str | Path, expedition: int) -> Path:
        d = Path(expeditions_dir) / str(expedition) / "wireframes"
        d.mkdir(parents=True, exist_ok=True)
        for i, w in enumerate(self.wireframes):
            (d / f"candidate-{i}.html").write_text(w, encoding="utf-8")
        (d / "ranking.json").write_text(json.dumps(self.suggested_ranking), encoding="utf-8")
        (d / "mode.json").write_text(json.dumps({"mode": self.mode}), encoding="utf-8")
        return d


def run_rung2(idea: Idea, spec: str, builder: Builder, judge: Judge,
              n: int = 3, max_tokens: int = 360, mode: str = "structure",
              grounding: str = "") -> Rung2Result:
    calls: list[Call] = []

    resolved = mode if mode in ("structure", "variants") else "structure"
    if mode == "auto":
        resolved, ccall = _classify(idea, spec, judge)
        if ccall is not None:
            calls.append(ccall)

    variants = resolved == "variants"
    system = _VARIANTS_SYS if variants else _WIRE_SYS
    context = f"\n\nCONTEXT:\n{grounding}" if grounding.strip() else ""

    wires: list[str] = []
    for i in range(n):
        if variants:
            prompt = (f"TARGET ELEMENT / CHANGE:\n{spec}\n\nDesign line #{i+1}: a distinct concrete "
                      f"styled variant of the element. Return the HTML fragment only.{context}")
        else:
            prompt = (f"SPEC:\n{spec}\n\nWireframe candidate #{i+1}. Return the HTML fragment "
                      f"only.{context}")
        text, call = builder.complete(prompt, max_tokens=max_tokens, system=system)
        wires.append(_strip_fences(text))
        calls.append(call)

    numbered = "\n\n".join(f"[{i}] {w[:400]}" for i, w in enumerate(wires))
    rtext, rcall = judge.complete(
        f"SPEC:\n{spec}\n\nLINES:\n{numbered}\n\nRank them.",
        max_tokens=48, system=_RANK_SYS,
    )
    calls.append(rcall)
    m = _ARR.search(rtext or "")
    try:
        ranking = [int(x) for x in json.loads(m.group(0))] if m else list(range(n))
    except (ValueError, TypeError):
        ranking = list(range(n))
    ranking = [i for i in ranking if 0 <= i < n] or list(range(n))
    return Rung2Result(wires, ranking, calls, mode=resolved)

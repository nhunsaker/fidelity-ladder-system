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

Self-verify pre-check (Wu, Phase 3): before the human is asked to pick a line, a cheap
structural a11y lint runs over every candidate — the human shouldn't have to pick among
a11y-broken wireframes. Clean lines are ranked ahead of dirty ones; if every candidate is dirty,
`Rung2Result.pre_check_passed` is False, which a caller MUST treat as a park (nothing safe to
hand the human), not a silent pass-through.
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

_IMG_TAG = re.compile(r"(?is)<img\b([^>]*)>")
_ALT_ATTR = re.compile(r'(?is)\balt\s*=\s*(".*?"|\'.*?\'|\S+)')
_CONTROL_TAG = re.compile(r"(?is)<(input|textarea|select)\b([^>]*)>")
_SELF_LABEL_ATTR = re.compile(r"(?is)\b(aria-label|aria-labelledby|placeholder|title)\s*=")
_ID_ATTR = re.compile(r'(?is)\bid\s*=\s*(".*?"|\'.*?\')')
_LABEL_FOR = re.compile(r'(?is)<label\b[^>]*\bfor\s*=\s*(".*?"|\'.*?\')')
_EMPTY_INTERACTIVE = re.compile(r"(?is)<(button|a)\b([^>]*)>(.*?)</\1>")
_TEXT_CONTENT = re.compile(r"(?is)<[^>]*>")


def a11y_lint(html: str) -> list[str]:
    """Cheap structural a11y lint over an HTML fragment (no browser, no deps — just the patterns
    that make a candidate unreviewable-by-a-screen-reader). NOT a replacement for axe-core; this
    is the rung-2 pre-check gate, not the eventual verifier. Returns [] when clean."""
    html = html or ""
    violations: list[str] = []

    for m in _IMG_TAG.finditer(html):
        attrs = m.group(1)
        alt = _ALT_ATTR.search(attrs)
        if not alt or re.sub(r'^["\']|["\']$', "", alt.group(1)).strip() == "":
            violations.append("<img> missing a non-empty alt attribute")

    label_targets = {m.group(1).strip('"\'') for m in _LABEL_FOR.finditer(html)}
    for m in _CONTROL_TAG.finditer(html):
        attrs = m.group(2)
        if _SELF_LABEL_ATTR.search(attrs):
            continue  # aria-label/aria-labelledby/placeholder/title all count for a wireframe
        idm = _ID_ATTR.search(attrs)
        if idm and idm.group(1).strip('"\'') in label_targets:
            continue  # <label for="..."> associates it
        tag = m.group(1).lower()
        violations.append(f"<{tag}> has no accessible name (label/aria-label/placeholder)")

    for m in _EMPTY_INTERACTIVE.finditer(html):
        tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
        if _SELF_LABEL_ATTR.search(attrs):
            continue
        text = _TEXT_CONTENT.sub("", inner).strip()
        if not text:
            violations.append(f"<{tag}> has no visible text and no aria-label")

    return violations


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
    suggested_ranking: list[int]    # judge suggestion, RE-SORTED clean-first by the a11y pre-check
    calls: list[Call] = field(default_factory=list)
    picked_index: int | None = None  # set when the human picks (via controller)
    mode: str = "structure"          # resolved fidelity: structure | variants
    a11y_violations: list[list[str]] = field(default_factory=list)  # index-aligned to wireframes

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    @property
    def clean_indices(self) -> list[int]:
        return [i for i, v in enumerate(self.a11y_violations) if not v]

    @property
    def pre_check_passed(self) -> bool:
        """Self-verify pre-check (Wu, Phase 3): False only when EVERY candidate is a11y-dirty —
        there is nothing safe to hand the human. A caller MUST park rather than present dirty
        lines when this is False (fail-closed, not advisory)."""
        return bool(self.clean_indices) or not self.wireframes

    def persist(self, expeditions_dir: str | Path, expedition: int) -> Path:
        d = Path(expeditions_dir) / str(expedition) / "wireframes"
        d.mkdir(parents=True, exist_ok=True)
        for i, w in enumerate(self.wireframes):
            (d / f"candidate-{i}.html").write_text(w, encoding="utf-8")
        (d / "ranking.json").write_text(json.dumps(self.suggested_ranking), encoding="utf-8")
        (d / "mode.json").write_text(json.dumps({"mode": self.mode}), encoding="utf-8")
        (d / "a11y.json").write_text(json.dumps(self.a11y_violations), encoding="utf-8")
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

    # self-verify pre-check (Wu, Phase 3): lint every line, then stable-sort clean-first so the
    # human's candidate list never leads with a broken one. Order among equally-clean/dirty
    # candidates is preserved (stable sort keeps the judge's relative preference).
    a11y_violations = [a11y_lint(w) for w in wires]
    ranking = sorted(ranking, key=lambda i: 1 if a11y_violations[i] else 0)

    return Rung2Result(wires, ranking, calls, mode=resolved, a11y_violations=a11y_violations)

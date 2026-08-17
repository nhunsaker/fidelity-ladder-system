"""Rung 1 — spec fan-out + reflection pass + judge rank (Ng#1: the highest-leverage loop).

Flow: builder drafts N candidate specs -> judge ranks them vs ANCHOR -> judge critiques the
top spec -> builder revises it ONCE (the reflection pass) -> return ranked specs with the top
revised. Cheap and it's the single biggest quality lift per Ng's 48->67->95 HumanEval point.

Builders default to claude-haiku (cost floor for paper-ladder specs); judges use the mini panel.
All model calls return (text, Call) so cost lands in the ledger. Stub-friendly for tests.

Yao's "theater fix" (v0.8 Phase 2): a spec's acceptance criteria are worthless as a gate if
they're prose a human has to eyeball at rung 4. The revised top spec's ACCEPTANCE section is
parsed into discrete criteria and COMPILED into a test-stub module — a machine-checkable form
(`Rung1Result.acceptance_stub`) that rung 4's `BoundedContext.acceptance_test` consumes directly.
This is also the rung-1 self-verify pre-check (Scott Wu, Phase 3): if the criteria don't parse
into checkable form, compilation fails CLOSED (`criteria_compiled=False`, `acceptance_stub=None`)
rather than silently pretending prose criteria are checkable — a caller MUST check
`criteria_compiled` before letting rung 1 advance past the (today unvetted) human/auto gate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from fls.adjudicator import Idea, Judge
from fls.anchor import Anchor
from fls.llm import Call

# a "builder" has the same .complete signature as a judge
Builder = Judge

_SPEC_SYS = (
    "You are a product spec writer for a fidelity-ladder system. Write a TIGHT spec for the "
    "idea: user story, constraints, non-goals, and 2-4 checkable acceptance criteria. Under 150 "
    "words. Vary your approach from other candidates. End the spec with a line reading exactly "
    "'ACCEPTANCE:' followed by each criterion on its own line, numbered '1.', '2.', etc., each "
    "phrased as a single observable behavior (e.g. '1. Cmd-K focuses the search input from any "
    "screen state.'). This numbered section is REQUIRED and is parsed by machine — do not "
    "paraphrase it into a paragraph."
)
_RANK_SYS = (
    "You rank candidate specs for one idea by how well each traces to the ANCHOR and how "
    "checkable its acceptance criteria are. Reply with a JSON array of spec indices, best first, "
    'e.g. [2,0,1]. Reply with the array only.'
)
_CRIT_SYS = (
    "You are a critical reviewer. In 2-3 bullet points, name the single most important weakness "
    "of this spec against the idea's success criteria and how to fix it. Be specific and terse."
)
_ARR = re.compile(r"\[[^\]]*\]")
_ACCEPTANCE_HEADER = re.compile(r"(?im)^\s*ACCEPTANCE:\s*$")
_ACCEPTANCE_ITEM = re.compile(r"(?m)^\s*\d+[.)]\s+(\S.*\S|\S)\s*$")


def extract_acceptance_criteria(spec: str) -> list[str]:
    """Pull the numbered criteria out of a spec's 'ACCEPTANCE:' section. Returns [] if the
    section is missing or has no parseable numbered lines — the honest, fail-closed signal that
    this spec's criteria are prose, not machine-checkable (Yao's theater fix)."""
    m = _ACCEPTANCE_HEADER.search(spec or "")
    if not m:
        return []
    tail = spec[m.end():]
    return [item.strip() for item in _ACCEPTANCE_ITEM.findall(tail) if item.strip()]


def _slug(text: str, n: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:6]
    return "_".join(words) or f"criterion_{n}"


def compile_acceptance_stub(criteria: list[str]) -> str | None:
    """Compile parsed criteria into a machine-checkable test-stub module (Yao's theater fix):
    one stub test function per criterion, each carrying its criterion text and a required-fix
    marker (NotImplementedError) so rung 4's builder must satisfy it with a REAL assertion, not
    prose. Returns None (fail-closed) if there are no criteria to compile — an empty stub would
    silently pass everything, which is worse than refusing.
    """
    if not criteria:
        return None
    lines = [
        '"""Rung-1 compiled acceptance criteria — machine-checkable stubs (Yao\'s theater fix).',
        "",
        "Each function below is ONE acceptance criterion. Rung 4's builder must replace the",
        "NotImplementedError with a real assertion that exercises the behavior. A verifier that",
        "still finds NotImplementedError raised is an unmet criterion, not a pass.",
        '"""',
        "",
    ]
    for i, criterion in enumerate(criteria, start=1):
        safe = criterion.replace('"""', "'''")
        lines.append(f"def test_criterion_{i}_{_slug(criterion, i)}():")
        lines.append(f'    """{safe}"""')
        lines.append(f'    raise NotImplementedError("unmet acceptance criterion: {safe}")')
        lines.append("")
    return "\n".join(lines)


@dataclass
class Rung1Result:
    specs: list[str]                 # candidate specs, index-aligned to generation order
    ranking: list[int]              # indices best-first
    top_index: int
    critique: str
    revised_top: str
    calls: list[Call] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)     # parsed from revised_top's ACCEPTANCE
    acceptance_stub: str | None = None                    # compiled test-stub module, or None

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    @property
    def criteria_compiled(self) -> bool:
        """The rung-1 self-verify pre-check (Wu, Phase 3): True only if the revised spec's
        acceptance criteria parsed into a checkable stub. A caller MUST gate rung-1 advancement
        on this — False means the criteria are prose, not a machine-checkable gate for rung 4."""
        return self.acceptance_stub is not None


def run_rung1(idea: Idea, anchor: Anchor, builder: Builder, judge: Judge,
              n: int = 3, max_tokens: int = 320, grounding: str = "") -> Rung1Result:
    calls: list[Call] = []
    context = f"\n\nCONTEXT:\n{grounding}" if grounding.strip() else ""

    # 1. fan out N candidate specs
    specs: list[str] = []
    for i in range(n):
        text, call = builder.complete(
            f"Idea: {idea.intent}\nSuccess: {idea.success}{context}\nCandidate #{i+1}. Write the spec.",
            max_tokens=max_tokens, system=_SPEC_SYS,
        )
        specs.append(text.strip())
        calls.append(call)

    # 2. judge ranks (cheap mini call) — prune-early: only the winner gets the reflection spend
    numbered = "\n\n".join(f"[{i}]\n{s}" for i, s in enumerate(specs))
    rtext, rcall = judge.complete(
        f"IDEA: {idea.intent}\nSuccess: {idea.success}\n\nCANDIDATES:\n{numbered}\n\nRank them.",
        max_tokens=64, system=_RANK_SYS,
    )
    calls.append(rcall)
    m = _ARR.search(rtext or "")
    try:
        ranking = [int(x) for x in json.loads(m.group(0))] if m else list(range(n))
    except (ValueError, TypeError):
        ranking = list(range(n))
    ranking = [i for i in ranking if 0 <= i < n] or list(range(n))
    top = ranking[0]

    # 3. reflection pass: judge critiques the top spec, builder revises once
    ctext, ccall = judge.complete(
        f"IDEA: {idea.intent}\nSuccess: {idea.success}\n\nSPEC:\n{specs[top]}\n\nCritique it.",
        max_tokens=180, system=_CRIT_SYS,
    )
    calls.append(ccall)
    revised, vcall = builder.complete(
        f"Idea: {idea.intent}\nSuccess: {idea.success}{context}\n\nOriginal spec:\n{specs[top]}\n\n"
        f"Reviewer critique:\n{ctext}\n\nRewrite the spec addressing the critique. Keep it tight.",
        max_tokens=max_tokens, system=_SPEC_SYS,
    )
    calls.append(vcall)
    revised = revised.strip()

    # 4. self-verify pre-check (Wu, Phase 3): parse + compile the criteria BEFORE this result
    # can advance. One cheap repair attempt if the builder dropped the required ACCEPTANCE
    # section; otherwise fail closed (criteria_compiled=False) rather than fake a stub.
    criteria = extract_acceptance_criteria(revised)
    if not criteria:
        repair_text, rpcall = builder.complete(
            f"Idea: {idea.intent}\nSuccess: {idea.success}\n\nSPEC:\n{revised}\n\n"
            "This spec is missing its required 'ACCEPTANCE:' section. Reply with ONLY the "
            "ACCEPTANCE section: the line 'ACCEPTANCE:' followed by 2-4 numbered criteria.",
            max_tokens=120, system=_SPEC_SYS,
        )
        calls.append(rpcall)
        repair_criteria = extract_acceptance_criteria(repair_text or "")
        if repair_criteria:
            revised = revised + "\n\nACCEPTANCE:\n" + "\n".join(
                f"{i}. {c}" for i, c in enumerate(repair_criteria, start=1)
            )
            criteria = repair_criteria

    stub = compile_acceptance_stub(criteria)

    return Rung1Result(specs, ranking, top, ctext.strip(), revised, calls,
                        criteria=criteria, acceptance_stub=stub)

"""Rung 1 — spec fan-out + reflection pass + judge rank (Ng#1: the highest-leverage loop).

Flow: builder drafts N candidate specs -> judge ranks them vs ANCHOR -> judge critiques the
top spec -> builder revises it ONCE (the reflection pass) -> return ranked specs with the top
revised. Cheap and it's the single biggest quality lift per Ng's 48->67->95 HumanEval point.

Builders default to claude-haiku (cost floor for paper-ladder specs); judges use the mini panel.
All model calls return (text, Call) so cost lands in the ledger. Stub-friendly for tests.
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
    "words. Vary your approach from other candidates."
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


@dataclass
class Rung1Result:
    specs: list[str]                 # candidate specs, index-aligned to generation order
    ranking: list[int]              # indices best-first
    top_index: int
    critique: str
    revised_top: str
    calls: list[Call] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)


def run_rung1(idea: Idea, anchor: Anchor, builder: Builder, judge: Judge,
              n: int = 3, max_tokens: int = 320) -> Rung1Result:
    calls: list[Call] = []

    # 1. fan out N candidate specs
    specs: list[str] = []
    for i in range(n):
        text, call = builder.complete(
            f"Idea: {idea.intent}\nSuccess: {idea.success}\nCandidate #{i+1}. Write the spec.",
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
        f"Idea: {idea.intent}\nSuccess: {idea.success}\n\nOriginal spec:\n{specs[top]}\n\n"
        f"Reviewer critique:\n{ctext}\n\nRewrite the spec addressing the critique. Keep it tight.",
        max_tokens=max_tokens, system=_SPEC_SYS,
    )
    calls.append(vcall)

    return Rung1Result(specs, ranking, top, ctext.strip(), revised.strip(), calls)

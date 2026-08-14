"""Controller — the harness orchestration that ties the paper ladder together.

on_idea:   admission gate -> dock or spawn expedition (records the ledger decision).
run_batch: admit a batch -> rank admitted (funnel) -> assign lanes -> climb each expedition
           to its target rung (rung 1 spec+reflection, rung 2 wireframe), enforcing the
           per-expedition budget ceiling (fail-closed: park, never creep).

Everything below rung 3 is the paper ladder (this phase). rungs 3-5 (demo/MVP/flag) attach in
P2/P3. All LLM work goes through the injected judge/builder so this is stub-testable (zero spend).
"""
from __future__ import annotations

import json
import re

from fls.adjudicator import Idea, Judge, adjudicate
from fls.anchor import Anchor, Verdict
from fls.expedition import AWAIT_PICK, DOCKED, NEEDS_HUMAN, PARKED, Expedition
from fls.funnel import RUNG_SPEC, RUNG_WIRE, RankedIdea, assign_lanes
from fls.ledger import Decision, Ledger
from fls.rung1 import Builder, run_rung1
from fls.rung2 import run_rung2

_ARR = re.compile(r"\[[^\]]*\]")
_RANK_SYS = (
    "Rank these admitted ideas by how strongly each traces to the ANCHOR north star and how "
    "checkable its success criteria are. Reply with a JSON array of idea NUMBERS, best first. "
    "Array only."
)


def on_idea(idea: Idea, anchor: Anchor, anchor_text: str, judge: Judge,
            ledger: Ledger, grounding: str = "") -> tuple[Verdict, str]:
    """Admission. Records the ledger decision (human_verdict None until a human weighs in)."""
    j = adjudicate(idea, anchor, anchor_text, judge, grounding=grounding)
    c = j.cost
    ledger.record(Decision(
        expedition=idea.number, rung="0-intent", judge_verdict=j.verdict.value,
        human_verdict=None, judge_cost_usd=(c.usd if c else 0.0),
        judge_tokens_in=(c.input_tokens if c else 0), judge_tokens_out=(c.output_tokens if c else 0),
    ))
    return j.verdict, j.reasoning


def _rank_admitted(ideas: list[Idea], anchor: Anchor, judge: Judge) -> list[RankedIdea]:
    if len(ideas) == 1:
        return [RankedIdea(number=ideas[0].number, rank=1)]
    listing = "\n".join(f"#{i.number}: {i.intent} (success: {i.success})" for i in ideas)
    text, _ = judge.complete(f"IDEAS:\n{listing}\n\nRank by number.", max_tokens=64, system=_RANK_SYS)
    m = _ARR.search(text or "")
    try:
        order = [int(x) for x in json.loads(m.group(0))] if m else [i.number for i in ideas]
    except (ValueError, TypeError):
        order = [i.number for i in ideas]
    nums = [i.number for i in ideas]
    order = [n for n in order if n in nums] + [n for n in nums if n not in order]
    return [RankedIdea(number=n, rank=order.index(n) + 1) for n in nums]


def run_batch(ideas: list[Idea], anchor: Anchor, anchor_text: str, judge: Judge,
              builder: Builder, ledger: Ledger, expeditions_dir: str,
              grounding: str = "") -> list[Expedition]:
    ceiling = anchor.budgets.per_expedition_ceiling_usd

    # 1. admission
    admitted: list[Idea] = []
    exps: dict[int, Expedition] = {}
    for idea in ideas:
        verdict, reason = on_idea(idea, anchor, anchor_text, judge, ledger, grounding=grounding)
        if verdict == Verdict.admit:
            admitted.append(idea)
        else:  # dock / needs-human both stop here with a reason
            e = Expedition(idea.number, idea, target_rung=0,
                           status=DOCKED if verdict == Verdict.dock else NEEDS_HUMAN, reason=reason)
            exps[idea.number] = e

    # 2. rank admitted (cheap) -> 3. assign funnel lanes
    ranked = assign_lanes(_rank_admitted(admitted, anchor, judge), anchor)
    target = {r.number: r.target_rung for r in ranked}
    dial1 = anchor.rungs["1-spec"].dial

    # 4. climb each admitted expedition to its target rung (paper-ladder cap = rung 2)
    idea_by_num = {i.number: i for i in admitted}
    for r in ranked:
        idea = idea_by_num[r.number]
        e = Expedition(idea.number, idea, target_rung=target[idea.number], dial=dial1, rung=RUNG_SPEC)

        # rung 1: spec + reflection
        if e.target_rung >= RUNG_SPEC:
            r1 = run_rung1(idea, anchor, builder, judge, grounding=grounding)
            e.add(r1.calls)
            e.spec = r1.revised_top
            if e.spent_usd > ceiling:
                e.status, e.reason = PARKED, f"budget ceiling ${ceiling} hit at rung 1"
                exps[idea.number] = e
                continue
            e.rung = RUNG_SPEC

        # rung 2: wireframe fan-out (human pick pending)
        if e.target_rung >= RUNG_WIRE:
            r2 = run_rung2(idea, e.spec or idea.intent, builder, judge, grounding=grounding)
            e.add(r2.calls)
            e.wireframes = r2.wireframes
            r2.persist(expeditions_dir, idea.number)
            if e.spent_usd > ceiling:
                e.status, e.reason = PARKED, f"budget ceiling ${ceiling} hit at rung 2"
            else:
                e.rung, e.status = RUNG_WIRE, AWAIT_PICK  # parks for the human pick-of-3
        else:
            e.status = AWAIT_PICK  # target was rung 1 only (queued below wireframe width)

        exps[idea.number] = e

    return [exps[i.number] for i in ideas]

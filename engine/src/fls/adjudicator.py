"""The admission gate — the FROZEN adjudicator interface (v1 single-LLM).

Contract (frozen for V3 pluggable adjudicators — council / system-design personas drop in here
without a rewrite): input = (idea, anchor) → Judgment(verdict, reasoning, cost). The verdict is
one of admit / dock / needs-human. The persona/model determines *how* it judges, never the
schema. Cost is bounded by anchor.adjudicator.cost.

v1 asks: does this idea trace to the ANCHOR north star + non-negotiables, and is its altitude
allowed? A `Judge` is anything with .complete(prompt, max_tokens, system) -> (text, Call);
tests pass a stub, production passes AzureJudge(nano).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from fls.anchor import Anchor, Verdict
from fls.llm import Call


@dataclass
class Idea:
    number: int
    intent: str
    success: str
    altitude: str
    source: str = "manual"


@dataclass
class Judgment:
    verdict: Verdict
    reasoning: str
    cost: Call | None = None


class Judge(Protocol):
    def complete(self, prompt: str, max_tokens: int = ..., system: str | None = ...) -> tuple[str, Call]: ...


# --- V6 pluggable adjudicators -----------------------------------------------------------
# The frozen seam above (Judge / adjudicate / Judgment) never changes. A council is just
# another Judge: it fans a prompt out to N member judges and folds their independent verdicts
# into ONE combined JSON reply + ONE aggregate Call before returning from .complete() — so
# adjudicate() (below) is completely unaware it talked to more than one model.

_VERDICT_VALUES = {"admit", "dock", "needs-human"}


def _parse_vote(text: str) -> dict:
    m = _JSON.search(text or "")
    if m:
        try:
            obj = json.loads(m.group(0))
            v = obj.get("verdict")
            if v in _VERDICT_VALUES:
                return {"verdict": v, "reasoning": str(obj.get("reasoning", ""))[:280]}
        except (KeyError, ValueError):
            pass
    # unparseable/invalid member reply fails toward the safe middle ground, never toward admit
    return {"verdict": "needs-human", "reasoning": f"unparseable member reply: {(text or '')[:120]!r}"}


def _combine_votes(votes: list[dict], combine: str) -> tuple[str, str]:
    verdicts = [v["verdict"] for v in votes]
    reasons = "; ".join(v["reasoning"] for v in votes)[:280]
    if combine == "unanimous-to-admit":
        if all(v == "admit" for v in verdicts):
            return "admit", f"unanimous admit ({len(verdicts)} judges): {reasons}"
        if "dock" in verdicts:
            return "dock", f"not unanimous (a member docked): {reasons}"
        return "needs-human", f"not unanimous: {reasons}"
    # majority (default): ties fail toward the tighter verdict (dock > needs-human > admit)
    counts = Counter(verdicts)
    top_n = max(counts.values())
    tied = [v for v, n in counts.items() if n == top_n]
    if len(tied) > 1:
        for pref in ("dock", "needs-human", "admit"):
            if pref in tied:
                return pref, f"tied vote {dict(counts)}, defaulted to {pref}: {reasons}"
    winner = tied[0]
    return winner, f"majority {winner} {dict(counts)}: {reasons}"


def _verdict_locked(votes: list[dict], combine: str, remaining: int) -> bool:
    """EcoOptiGen short-circuit: can any of the `remaining` uncast members still change the
    combined verdict? If not, stop polling. Conservative — only returns True when the outcome is
    provably fixed (never prunes a call that could flip the result)."""
    verdicts = [v["verdict"] for v in votes]
    if combine == "unanimous-to-admit":
        # a single non-admit already forces the (non-admit) result; all-admit-so-far is not safe
        # to stop on — a later member could still dock.
        return any(v != "admit" for v in verdicts)
    # majority: locked when the leader out-counts the runner-up by more than the uncast votes.
    counts = Counter(verdicts)
    if not counts:
        return False
    ordered = counts.most_common()
    top_n = ordered[0][1]
    second_n = ordered[1][1] if len(ordered) > 1 else 0
    return top_n > second_n + remaining


def _aggregate_call(calls: list[Call]) -> Call:
    if not calls:
        return Call(provider="council", model="council", funded_by="none")
    funded = {c.funded_by for c in calls}
    return Call(
        provider="council",
        model="+".join(sorted({c.model for c in calls})),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        usd=sum(c.usd for c in calls),
        normalized_usd=sum(c.normalized_usd for c in calls),
        funded_by=funded.pop() if len(funded) == 1 else "mixed",
        latency_ms=max((c.latency_ms for c in calls), default=0),
    )


class CouncilJudge:
    """A council of N member Judges presented as a single Judge (V6). Every member answers the
    SAME prompt/system independently; verdicts combine per `combine` ("majority" | "unanimous-
    to-admit") before .complete() returns — so the frozen adjudicate()/Judgment contract never
    has to know a council was consulted. Cost is the sum of every member's Call folded into one
    aggregate row (provider="council") so the ledger records a single line per admission."""

    def __init__(self, members: list[Judge], combine: str = "majority",
                 max_calls: int | None = None):
        if not members:
            raise ValueError("CouncilJudge needs at least one member judge")
        self.members = members
        self.combine = combine
        # EcoOptiGen pruning (Chi Wang, v0.8): cap the number of member calls at `max_calls`
        # (~2 cheap judges + a tiebreak), and short-circuit as soon as the combined verdict is
        # locked regardless of the uncast members. None = poll every member (v0.6 behavior).
        self.max_calls = max_calls

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        votes: list[dict] = []
        calls: list[Call] = []
        cap = min(self.max_calls or len(self.members), len(self.members))
        pruning = self.max_calls is not None  # short-circuit is part of the opt-in pruning path
        for i in range(cap):
            text, call = self.members[i].complete(prompt, max_tokens=max_tokens, system=system)
            calls.append(call)
            votes.append(_parse_vote(text))
            if pruning and _verdict_locked(votes, self.combine, remaining=cap - (i + 1)):
                break  # no uncast member could change the outcome — stop paying for calls
        verdict, reasoning = _combine_votes(votes, self.combine)
        return json.dumps({"verdict": verdict, "reasoning": reasoning}), _aggregate_call(calls)


def make_adjudicator(anchor: Anchor) -> Judge:
    """Selection factory (V6 pluggable adjudicators): builds the Judge behind the frozen
    adjudicate() seam per ANCHOR `adjudicator.kind`.

    kind=single-llm (default, UNCHANGED) -> one AzureJudge, same as v1.
    kind=council                          -> N member AzureJudges (adjudicator.council.size,
                                              optionally council.model) combined behind one
                                              Judge per adjudicator.council.combine.
    """
    from fls.llm import AzureJudge  # deferred: keeps adjudicator.py import-light for tests

    def _deployment(model: str) -> str:
        return model.split(":", 1)[1] if ":" in model else model

    cfg = anchor.adjudicator
    if cfg.kind == "council":
        deployment = _deployment(cfg.council.model or cfg.model)
        members = [AzureJudge(deployment) for _ in range(max(1, cfg.council.size))]
        # EcoOptiGen: cap member calls at the ANCHOR's adjudicator.cost.max_calls (0 = poll all)
        max_calls = cfg.cost.max_calls if cfg.cost.max_calls else None
        return CouncilJudge(members, combine=cfg.council.combine, max_calls=max_calls)
    return AzureJudge(_deployment(cfg.model))


_SYSTEM = (
    "You are the admission gate of a fidelity-ladder system. You decide whether an idea may "
    "enter the ladder. You do NOT judge whether the idea is good — only whether it TRACES to "
    "the ANCHOR (north star + non-negotiables) and fits an allowed altitude. Reply with a single "
    "JSON object: {\"verdict\": \"admit\"|\"dock\"|\"needs-human\", \"reasoning\": \"one sentence\"}. "
    "admit = clearly traces; dock = does not trace or violates a non-negotiable; needs-human = "
    "right direction but ambiguous scope/size that a person should resolve."
)

_JSON = re.compile(r"\{.*\}", re.DOTALL)


def _anchor_summary(a: Anchor, anchor_text: str) -> str:
    # north star + non-negotiables live in prose; pass the human header, machine caps from model
    header = anchor_text.split("```anchor")[0]
    return f"{header}\nAllowed altitudes: {a.altitude_allowed}"


def adjudicate(idea: Idea, anchor: Anchor, anchor_text: str, judge: Judge,
               grounding: str = "") -> Judgment:
    # cheap deterministic pre-check: altitude must be allowed (no LLM spend if it fails)
    if idea.altitude not in anchor.altitude_allowed:
        return Judgment(Verdict.dock,
                        f"altitude '{idea.altitude}' not in allowed {anchor.altitude_allowed}")
    context = f"CONTEXT:\n{grounding}\n\n" if grounding.strip() else ""
    prompt = (
        f"ANCHOR:\n{_anchor_summary(anchor, anchor_text)}\n\n"
        f"{context}"
        f"IDEA #{idea.number}\nIntent: {idea.intent}\nSuccess: {idea.success}\n"
        f"Altitude: {idea.altitude}\nSource: {idea.source}\n\n"
        "Does this trace to the ANCHOR? Reply with the JSON object only."
    )
    text, call = judge.complete(prompt, max_tokens=anchor.adjudicator.cost.max_tokens, system=_SYSTEM)
    m = _JSON.search(text or "")
    if not m:
        return Judgment(Verdict.needs_human, f"unparseable adjudicator reply: {text[:120]!r}", call)
    try:
        obj = json.loads(m.group(0))
        return Judgment(Verdict(obj["verdict"]), str(obj.get("reasoning", ""))[:280], call)
    except (KeyError, ValueError) as e:
        return Judgment(Verdict.needs_human, f"invalid adjudicator schema: {e}", call)

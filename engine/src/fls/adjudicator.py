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

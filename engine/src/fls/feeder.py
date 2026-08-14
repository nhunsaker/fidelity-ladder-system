"""P4 — the feeder: ideas from the studio brainstorm (the second idea_source door).

A headless "virtual brainstorm" runs the studio's council/brainstorm pattern, parameterized
ENTIRELY by ANCHOR (scope · guardrails-into-prompt · cost/volume caps · model tier · context cap
on what a workspace checkout may feed the prompt). Surviving ideas are filed through the STANDARD
door — the same idea-issue → admission gate a human uses — so the feeder can NEVER self-admit
(mirrors ladder_mcp.file_idea). It rides the skill-server (subscription lane, P7), so a nightly
cadence costs nothing metered; the cost envelope bounds the *shadow* cost (normalized_usd) so a
run can't balloon token usage even when the money column is zero.

Triggers (live-gated, §5): on-demand (run_feeder called directly / MCP studio_trigger_brainstorm)
and a nightly schedule on the operator's infrastructure, which reports an honest exit status +
weekly health line per the durability rules; that infra step is the one remaining live-gated bit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol

from fls.anchor import Anchor, FeederParams, guardrails_prose
from fls.llm import Call
from fls.rung1 import Builder

# rough chars-per-token for the context cap (same heuristic the harness uses elsewhere)
_CHARS_PER_TOKEN = 4
_ARR = re.compile(r"\[.*\]", re.DOTALL)

_BRAINSTORM_SYS = (
    "You are the studio's virtual brainstorm council for a fidelity-ladder system. Propose "
    "DIVERSE, buildable ideas that trace to the ANCHOR (north star + non-negotiables) and fit the "
    "given scope. Each idea must name a checkable success signal and an altitude (ticket|feature). "
    "You are NOT the admission gate — propose freely; a separate gate decides what enters. "
    'Reply with a JSON array ONLY: [{"intent": str, "success": str, "altitude": "ticket"|"feature", '
    '"rationale": str}]. No prose outside the array.'
)


@dataclass
class Candidate:
    intent: str
    success: str
    altitude: str = "feature"
    rationale: str = ""


@dataclass
class FiledIdea:
    ref: object            # whatever the sink returns (issue number, id, ...)
    candidate: Candidate


class IdeaSink(Protocol):
    """The standard door. file() posts an idea-issue for the admission gate to judge — it does
    NOT admit. Production: a GitHub issue via the App. Tests: an in-memory list."""
    def file(self, candidate: Candidate, source: str) -> object: ...


@dataclass
class ListSink:
    """In-memory sink for tests / dry runs."""
    filed: list[FiledIdea] = field(default_factory=list)

    def file(self, candidate: Candidate, source: str) -> object:
        ref = len(self.filed) + 1
        self.filed.append(FiledIdea(ref, candidate))
        return ref


@dataclass
class FeederRun:
    candidates: list[Candidate]        # everything the brainstorm proposed
    filed: list[FiledIdea]             # the top-N (volume_cap) actually filed through the door
    calls: list[Call]
    proposed: int                      # raw count before the cap
    capped_to: int                     # volume_cap applied
    within_envelope: bool              # shadow cost stayed under cost_envelope_usd
    source: str = "studio-brainstorm"

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    @property
    def normalized_usd(self) -> float:
        return round(sum(c.normalized_usd for c in self.calls), 4)


def _parse_candidates(text: str) -> list[Candidate]:
    m = _ARR.search(text or "")
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    out: list[Candidate] = []
    for o in raw:
        if not isinstance(o, dict) or not o.get("intent"):
            continue
        out.append(Candidate(
            intent=str(o.get("intent", "")).strip(),
            success=str(o.get("success", "")).strip(),
            altitude=str(o.get("altitude", "feature")).strip() or "feature",
            rationale=str(o.get("rationale", "")).strip(),
        ))
    return out


def build_prompt(params: FeederParams, anchor_text: str, workspace_context: str = "") -> str:
    """Assemble the ideation prompt from ANCHOR — guardrails injected (if configured) and the
    workspace context hard-capped at context_cap_tokens (never let a checkout blow the prompt)."""
    parts = []
    if params.guardrails_into_prompt:
        parts.append("ANCHOR (ideas MUST trace to this):\n" + guardrails_prose(anchor_text))
    parts.append(f"SCOPE: {params.scope}")
    if params.grounding.strip():   # V3 grounding pack (vessel + lessons + prior expeditions)
        parts.append("CONTEXT (grounding):\n" + params.grounding.strip())
    if workspace_context:
        cap = params.context_cap_tokens * _CHARS_PER_TOKEN
        parts.append("WORKSPACE CONTEXT (grounding, truncated):\n" + workspace_context[:cap])
    parts.append(f"Propose up to {params.volume_cap * 2} diverse ideas. Best first.")
    return "\n\n".join(parts)


def run_feeder(anchor: Anchor, anchor_text: str, brainstorm: Builder, sink: IdeaSink,
               workspace_context: str = "", max_tokens: int = 1200,
               source: str = "studio-brainstorm") -> FeederRun:
    """Run one brainstorm → parse → cap → file through the standard door. Pure w.r.t. the sink:
    the feeder proposes and files idea-issues; admission remains the gate (no self-admit)."""
    params = anchor.feeder()
    prompt = build_prompt(params, anchor_text, workspace_context)
    text, call = brainstorm.complete(prompt, max_tokens=max_tokens, system=_BRAINSTORM_SYS)
    calls = [call]

    candidates = _parse_candidates(text)
    # the cost envelope bounds the SHADOW cost (normalized_usd) — meaningful even on the sub lane
    normalized = sum(c.normalized_usd for c in calls)
    within_envelope = normalized <= params.cost_envelope_usd

    # volume cap: file only the top-N through the standard door
    to_file = candidates[: params.volume_cap]
    filed = [FiledIdea(sink.file(c, source), c) for c in to_file]

    return FeederRun(
        candidates=candidates, filed=filed, calls=calls,
        proposed=len(candidates), capped_to=params.volume_cap,
        within_envelope=within_envelope, source=source,
    )

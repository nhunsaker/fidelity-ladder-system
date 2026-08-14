"""A ~60-line reference IdeaSource: brainstorm ideas with Claude, file each through the door.

It rides `fls.llm.ClaudeBuilder` (a Worker) to propose N ideas from the anchor text, then files
every idea through the injected `sink` — the STANDARD door. It is NOT the admission gate: it
proposes, the gate decides. Passing a stub Worker makes it run with zero credentials and zero
network (see test_module.py).
"""
from __future__ import annotations

import json
import re

from fls.feeder import Candidate, FeederRun, FiledIdea
from fls.llm import ClaudeBuilder

_ARR = re.compile(r"\[.*\]", re.DOTALL)
_SYS = (
    "You are a demo ideation agent for a fidelity-ladder system. Propose diverse, buildable "
    "ideas that trace to the given ANCHOR. You are NOT the admission gate — propose freely; a "
    'separate gate decides what enters. Reply with a JSON array ONLY: '
    '[{"intent": str, "success": str, "altitude": "ticket"|"feature"}]. No prose outside it.'
)


def _parse(text: str) -> list[Candidate]:
    m = _ARR.search(text or "")
    if not m:
        return []
    try:
        raw = json.loads(m.group(0))
    except (ValueError, TypeError):
        return []
    out: list[Candidate] = []
    for o in raw:
        if isinstance(o, dict) and o.get("intent"):
            out.append(Candidate(
                intent=str(o.get("intent", "")).strip(),
                success=str(o.get("success", "")).strip(),
                altitude=str(o.get("altitude", "feature")).strip() or "feature",
            ))
    return out


class ClaudeDemoAgent:
    """An IdeaSource. `run` proposes N ideas and files each through the sink — never admits."""

    SOURCE = "claude-demo-agent"

    def __init__(self, builder=None, n: int = 3):
        self.builder = builder or ClaudeBuilder()
        self.n = n

    def available(self) -> bool:
        return self.builder.available()

    def run(self, anchor, anchor_text: str, sink) -> FeederRun:
        prompt = (f"Propose {self.n} diverse, buildable ideas. Best first.\n\n"
                  f"ANCHOR (ideas MUST trace to this):\n{anchor_text[:4000]}")
        text, call = self.builder.complete(prompt, max_tokens=800, system=_SYS)
        candidates = _parse(text)[: self.n]
        # file each through the standard door — the sink returns whatever ref it uses
        filed = [FiledIdea(sink.file(c, self.SOURCE), c) for c in candidates]
        return FeederRun(
            candidates=candidates, filed=filed, calls=[call],
            proposed=len(candidates), capped_to=self.n,
            within_envelope=True, source=self.SOURCE,
        )

"""Grounding pack — the rung-4 lesson (component_inventory) applied a rung earlier.

Rung 4 learned the hard way that a builder which never sees the app hand-rolls bare HTML
(V2-P4 added `component_inventory` to BoundedContext). The gray-boxes complaint at rung 2 is the
SAME context problem one rung down: exploration never sees the real component library, tokens, or
what's already been tried. `build_grounding` assembles that missing context ONCE — deterministic,
capped, empty-safe — so admission, the feeder, and rung-1/2 prompts can all inject the same block.

Sections (each omitted entirely when empty — never a placeholder):
  VESSEL (name/kind/description/standards) → RECENT LESSONS → PRIOR EXPEDITIONS →
  COMPONENT LIBRARY → extra. Order is fixed so the same inputs always yield the same text.
"""
from __future__ import annotations

from fls.anchor import Anchor

_CAP = 2000  # compact by design: grounding is context, not a document


def build_grounding(anchor: Anchor | None, store=None, vessel_name: str | None = None,
                    component_inventory: str = "", extra: str = "") -> str:
    """Assemble the deterministic grounding block (cap ~2000 chars). All inputs optional; empty
    inputs contribute nothing (no placeholders). `store` is any ExpeditionStore-shaped object
    exposing lessons() and wall()."""
    parts: list[str] = []

    v = anchor.vessel(vessel_name) if anchor is not None else None
    if v is not None:
        vp = [f"VESSEL: {v.name} ({v.kind})"]
        if v.description.strip():
            vp.append(v.description.strip())
        if v.standards:
            vp.append("Standards:\n" + "\n".join(f"- {s}" for s in v.standards))
        parts.append("\n".join(vp))

    if store is not None:
        lessons = store.lessons()[-3:]  # most recent 3 (LESSONS.md appends chronologically)
        if lessons:
            parts.append("RECENT LESSONS:\n" + "\n".join(f"- {ln[:200]}" for ln in lessons))
        wall = store.wall()[-5:]        # 5 most recent expeditions (wall() sorts by number asc)
        if wall:
            parts.append("PRIOR EXPEDITIONS:\n" + "\n".join(
                f"- #{e['number']}: {str(e.get('intent', ''))[:80]} [{e.get('status', '')}]"
                for e in wall))

    if component_inventory.strip():
        parts.append("COMPONENT LIBRARY:\n" + component_inventory.strip())

    if extra.strip():
        parts.append(extra.strip())

    return "\n\n".join(parts)[:_CAP]

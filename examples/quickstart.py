#!/usr/bin/env python3
"""Fidelity Ladder — quickstart (no spend, no web, no harness).

    pip install fidelity-ladder
    python examples/quickstart.py

Proves the framework claim (Chase's trace #1): the ladder runs from the IMPORTABLE CORE plus a
config file alone — no FastAPI harness, no GitHub, no MCP, no model spend. Everything below comes
from `import fidelity_ladder`; the only I/O is reading the bundled ANCHOR.md next to this script.

What it shows, in order:
  1. rungs-as-config — the ladder is data you can print and swap.
  2. one door — an idea is adjudicated against the ANCHOR by a stub judge (zero spend).
  3. the ledger — every decision (and its cost) is written down; trust lives here, not in vibes.
"""
from pathlib import Path

import fidelity_ladder as fl


class StubJudge:
    """A Judge is anything with .complete(prompt, max_tokens, system) -> (text, Call). This one
    docks anything the idea itself flags as off-anchor ('scope creep') and admits the rest — no
    network, no spend. Swap in a real model-backed Judge (or a CouncilJudge) and nothing else
    changes: that's the seam."""

    def complete(self, prompt, max_tokens=1024, system=None):
        off_anchor = "scope creep" in prompt.lower()
        verdict = "dock" if off_anchor else "admit"
        text = f'{{"verdict": "{verdict}", "reasoning": "stub: off_anchor={off_anchor}"}}'
        return text, fl.Call("stub", "stub", 0, 0, 0.0)  # usd=0 — no spend


def main() -> None:
    here = Path(__file__).resolve().parent
    anchor_path = here / "quickstart" / "ANCHOR.md"
    anchor = fl.Anchor.load(anchor_path)
    anchor_text = anchor_path.read_text()

    print("1. RUNGS-AS-CONFIG — the ladder is data:")
    for r in fl.WEB_LADDER_PROFILE.rungs:
        print(f"   rung {r.number} {r.name:<9} produces {r.artifact_kind:<16} "
              f"dial={r.dial.value:<22} verifier={r.verifier}")
    print(f"   (swap WEB_LADDER_PROFILE for any LadderProfile to run a different ladder)\n")

    print("2. ONE DOOR — adjudicate two ideas against the ANCHOR (stub judge, $0):")
    ledger = fl.Ledger(here / "quickstart" / "quickstart-ledger.jsonl")
    ideas = [
        fl.Idea(1, "a feature tied to the north star", "it traces", "feature"),
        fl.Idea(2, "an unrelated bit of scope creep", "it does not trace", "feature"),
    ]
    for idea in ideas:
        verdict, _ = fl.on_idea(idea, anchor, anchor_text, StubJudge(), ledger)
        print(f"   idea #{idea.number}: {verdict}")

    print("\n3. THE LEDGER — every decision is written down (trust in the ledger):")
    rows = (here / "quickstart" / "quickstart-ledger.jsonl").read_text().strip().splitlines()
    print(f"   {len(rows)} decision(s) recorded at examples/quickstart/quickstart-ledger.jsonl")

    print("\nDone — a governed admission ran from the importable core alone. "
          "No harness, no web deps, no spend.")


if __name__ == "__main__":
    main()

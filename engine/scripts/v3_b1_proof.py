"""V3-B1 LIVE proof: rung 2 as fidelity-adaptive EXPLORATION for expedition #4.

The #4 idea is "make the restock button bolder" — a UI TWEAK, not a new flow. Under V2 rung 2
produced gray Primer skeletons (the gray-boxes complaint). Here we ground the builder in the
demo vessel + a bootstrap-styled component inventory and run rung 2 in mode="variants", so each
line is a CONCRETE styled button (real weight/color/shape) — three lines the founder picks from.

Mirrors climb_4_rung12.py: budget-capped $0.05, haiku builder + mini judge, the PICK stays human.
Lines persist to expeditions/4-v3/wireframes/ for the admin viewer. DO NOT auto-pick.

Run by the lead (needs creds); this file only has to be correct + consistent with climb_4_rung12.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.grounding import build_grounding
from fls.llm import AzureJudge, BudgetGuard, ClaudeBuilder
from fls.rung1 import run_rung1
from fls.rung2 import run_rung2
from fls.store import ExpeditionStore

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "expeditions" / "4-v3"
EXP.mkdir(parents=True, exist_ok=True)

guard = BudgetGuard(claude_cap_usd=0.05)
builder = ClaudeBuilder("claude-haiku-4-5-20251001", guard=guard)
judge_mini = AzureJudge("gpt-5.4-mini")

anchor = Anchor.load(ROOT / "ANCHOR.md")

# The grounding pack: the demo vessel (acme-demo) + the bootstrap-styled library the demo app
# builds from + recent lessons/prior expeditions. This is the rung-4 component_inventory lesson,
# applied a rung earlier — the reason exploration can now show a REAL button, not a gray box.
COMPONENT_INVENTORY = (
    "@metatoy/bootstrap-styled components (compose from these, do not hand-roll):\n"
    "- <Button variant=primary|secondary|danger size=sm|md|lg> — bootstrap .btn .btn-* under the hood\n"
    "- Design tokens: --bs-primary #0d6efd, --bs-body-color #212529, --bs-border-radius .375rem,\n"
    "  font-weight-bold 700, .btn-lg padding .5rem 1rem / font-size 1.25rem\n"
    "- The restock button currently renders as a default secondary <Button>."
)
grounding = build_grounding(
    anchor, store=ExpeditionStore(ROOT), vessel_name="acme-demo",
    component_inventory=COMPONENT_INVENTORY,
)

# The idea exactly as filed on issue #4, post-/advance by the founder.
idea = Idea(4,
    "Make the restock button bolder (blue background with white text, or larger) so the "
    "action is more obvious to the end user",
    "takes less time for people to find and click the restock button on the page",
    "ticket")

print("=== RUNG 1 (3 specs + reflection, haiku + mini, grounded) ===")
r1 = run_rung1(idea, anchor, builder, judge_mini, grounding=grounding)
(EXP / "spec.md").write_text(r1.revised_top)
print(f"ranking: {r1.ranking} | critique: {r1.critique[:90]}")
print(f"spend: ${guard.spent_usd:.4f}")

print("\n=== RUNG 2 EXPLORATION (mode=variants, 3 concrete button lines) — pick stays HUMAN ===")
r2 = run_rung2(idea, r1.revised_top, builder, judge_mini, mode="variants", grounding=grounding)
r2.persist(ROOT / "expeditions", "4-v3")
print(f"mode: {r2.mode} (fidelity-adaptive; expected 'variants' for a UI tweak)")
print(f"judge's suggested ranking: {r2.suggested_ranking} (advisory; founder picks in the admin)")
print(f"lines: {sorted(p.name for p in (EXP / 'wireframes').glob('candidate-*.html'))}")
print(f"total spend: ${guard.spent_usd:.4f}")

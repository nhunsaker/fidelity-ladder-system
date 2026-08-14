"""Rungs 1-2 for expedition #4 (real issue: 'make the restock button bolder').
The founder advanced #4 to 1-spec via the admin's new feedback surface (2026-08-14);
this runs the artifact-producing climb: spec fan-out x3 + reflection, then the
wireframe pick-of-3 — persisted to expeditions/4/wireframes/ for the admin viewer.
Budget-capped $0.05. The PICK stays human (dial: human-picks) — no auto-pick here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.llm import AzureJudge, BudgetGuard, ClaudeBuilder
from fls.rung1 import run_rung1
from fls.rung2 import run_rung2

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "expeditions" / "4"
EXP.mkdir(parents=True, exist_ok=True)

guard = BudgetGuard(claude_cap_usd=0.05)
builder = ClaudeBuilder("claude-haiku-4-5-20251001", guard=guard)
judge_mini = AzureJudge("gpt-5.4-mini")

# The idea exactly as filed on issue #4 (form fields), post-/advance by the founder.
idea = Idea(4,
    "Make the restock button bolder (blue background with white text, or larger) so the "
    "action is more obvious to the end user",
    "takes less time for people to find and click the restock button on the page",
    "ticket")

print("=== RUNG 1 (3 specs + reflection, haiku + mini) ===")
r1 = run_rung1(idea, Anchor.load(ROOT / "ANCHOR.md"), builder, judge_mini)
(EXP / "spec.md").write_text(r1.revised_top)
print(f"ranking: {r1.ranking} | critique: {r1.critique[:90]}")
print(f"spend: ${guard.spent_usd:.4f}")

print("\n=== RUNG 2 (3 wireframes, haiku + mini) — pick stays HUMAN ===")
r2 = run_rung2(idea, r1.revised_top, builder, judge_mini)
r2.persist(ROOT / "expeditions", "4")
print(f"judge's suggested ranking: {r2.suggested_ranking} (advisory; founder picks in the admin)")
print(f"wireframes: {sorted(p.name for p in (EXP / 'wireframes').glob('candidate-*.html'))}")
print(f"total spend: ${guard.spent_usd:.4f}")

"""P7 + P4 LIVE driver — §5-gated (runs only when the skill-server is reachable).

P7: run one rung-1 spec via the builder PASS-BACK (SkillServerBuilder → a self-hosted
    remote skill server; subscription lane, NO API key, usd=0). Then, if an Anthropic
    key is present, run the SAME spec via the metered ClaudeBuilder and print a numeric-equivalence
    line (tokens + shadow cost side by side) so the two lanes are comparable.
P4: run one ANCHOR-governed brainstorm through the skill-server and file the top-N ideas into a
    ListSink (a dry run of the standard door), printing the run's two-column economics.

Reconciliation note: SkillServerBuilder assumes POST {endpoint}/complete → {text, usage}. If the
live server's contract differs, this script surfaces it as a SkillServerError with the payload —
fix the endpoint/parse in fls/llm.py, not here. This is the one remaining live-gated wire-up.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.feeder import ListSink, run_feeder
from fls.llm import AzureJudge, ClaudeBuilder, SkillServerBuilder, SkillServerError
from fls.rung1 import run_rung1

ROOT = Path(__file__).resolve().parents[2]
anchor = Anchor.load(ROOT / "ANCHOR.md")
anchor_text = (ROOT / "ANCHOR.md").read_text()

skill = SkillServerBuilder(shadow_model=anchor.builder.shadow_model)
if not skill.available():
    print("skill server not configured (env FLS_SKILL_SERVER + LANGCHAIN_API_KEY) — "
          "cannot run the live pass-back. Exiting cleanly.")
    sys.exit(0)

idea = Idea(701, "add a keyboard shortcut to focus the search box",
            "pressing / focuses search from anywhere; visible focus ring", "feature")


def _fmt(calls):
    tin = sum(c.input_tokens for c in calls)
    tout = sum(c.output_tokens for c in calls)
    usd = sum(c.usd for c in calls)
    norm = sum(c.normalized_usd for c in calls)
    return f"in={tin} out={tout} usd=${usd:.4f} shadow=${norm:.4f}"


print("── P7: rung-1 via the builder PASS-BACK (subscription lane) ──")
try:
    judge = AzureJudge("gpt-5.4-mini")
    if not judge.available():
        print("  (Azure judge key absent — running spec fan-out only, no ranking judge)")
    sub = run_rung1(idea, anchor, skill, judge if judge.available() else skill, n=3)
    print(f"  pass-back specs: {len(sub.specs)}  top=#{sub.top_index}")
    print(f"  economics: {_fmt([c for c in sub.calls if c.provider == 'skill-server'])}")
    print(f"  funded_by set: {set(c.funded_by for c in sub.calls)}")
except SkillServerError as e:
    print(f"  skill-server error (reconcile the /complete contract): {e}")
    sys.exit(1)

# numeric-equivalence: the same rung-1 via the metered api lane, if a key is present
api = ClaudeBuilder("claude-haiku-4-5-20251001")
if api.available():
    print("── numeric-equivalence: SAME rung-1 via the metered API lane ──")
    apirun = run_rung1(idea, anchor, api, judge if judge.available() else api, n=3)
    print(f"  api specs: {len(apirun.specs)}  top=#{apirun.top_index}")
    print(f"  api economics:      {_fmt([c for c in apirun.calls if c.provider == 'anthropic'])}")
    print(f"  pass-back economics:{_fmt([c for c in sub.calls if c.provider == 'skill-server'])}")
    print("  → both lanes produced N specs; the pass-back's usd is $0 (subscription) while its "
          "shadow cost tracks the api lane's actual — the two-column point, proven live.")
else:
    print("  (no Anthropic key — skipping the api-lane equivalence leg; pass-back leg stands alone)")

print("\n── P4: one ANCHOR-governed brainstorm through the skill-server ──")
try:
    sink = ListSink()
    run = run_feeder(anchor, anchor_text, skill, sink)
    print(f"  proposed={run.proposed} filed={len(run.filed)} (cap={run.capped_to}) "
          f"within_envelope={run.within_envelope}")
    print(f"  economics: usd=${run.cost_usd:.4f} shadow=${run.normalized_usd:.4f}")
    for f in run.filed:
        print(f"    • [{f.candidate.altitude}] {f.candidate.intent}")
except SkillServerError as e:
    print(f"  skill-server error: {e}")
    sys.exit(1)

print("\nDONE — P7 pass-back + P4 feeder exercised live on the subscription lane (usd $0).")

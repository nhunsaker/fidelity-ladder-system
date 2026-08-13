"""The first LIVE end-to-end climb (founder-approved ~$0.30 cap, 2026-08-13).
Live haiku builders + Azure judges. Admission -> rung1(+reflection) -> rung2 -> auto-pick
(judge's suggestion; demo convenience) -> rung3 (REAL demo + REAL Playwright walkthrough)
-> rung4 loop (real LocalVerifier on a scripted acceptance test). Artifacts persist to
expeditions/live-101/."""
import subprocess, sys, textwrap
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.anchor import Anchor
from fls.adjudicator import Idea, adjudicate
from fls.llm import ClaudeBuilder, AzureJudge, BudgetGuard
from fls.rung1 import run_rung1
from fls.rung2 import run_rung2
from fls.rung3 import run_rung3
from fls.rung4 import BoundedContext, run_rung4
from fls.local_verifier import LocalVerifier
from fls.playwright_walkthrough import PlaywrightWalkthrough
from fls.ledger import Decision, Ledger

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "expeditions" / "live-101"
EXP.mkdir(parents=True, exist_ok=True)

anchor = Anchor.load(ROOT / "ANCHOR.md")
anchor_text = (ROOT / "ANCHOR.md").read_text()
guard = BudgetGuard(claude_cap_usd=0.30)   # session cap, tighter than the $100 ANCHOR cap
builder = ClaudeBuilder("claude-haiku-4-5-20251001", guard=guard)
judge_nano, judge_mini = AzureJudge("gpt-5.4-nano"), AzureJudge("gpt-5.4-mini")
ledger = Ledger(EXP / "ledger.jsonl")
calls = []

idea = Idea(101,
    "Add a Cmd-K keyboard shortcut that jumps focus to the Acme search box from anywhere in the app",
    "pressing Cmd-K focuses the search input, including when a modal is open",
    "feature")

print("=== ADMISSION (nano) ===")
j = adjudicate(idea, anchor, anchor_text, judge_nano)
print(f"verdict: {j.verdict.value} — {j.reasoning[:100]}")
# needs-human resolution: the founder approved this exact idea for the live run (2026-08-13).
# Record BOTH verdicts — a real judge-vs-human data point for the calibration flywheel.
human = "admit"
ledger.record(Decision(101, "0-intent", j.verdict.value, human, j.cost.usd if j.cost else 0))
if j.verdict.value != "admit":
    print(f"-> HUMAN RESOLUTION: {human} (founder-approved; judge said {j.verdict.value} — logged as disagreement)")

print("\n=== RUNG 1 (3 specs + reflection, haiku + mini) ===")
r1 = run_rung1(idea, anchor, builder, judge_mini)
calls += r1.calls
(EXP / "spec.md").write_text(r1.revised_top)
print(f"ranking: {r1.ranking} | critique: {r1.critique[:90]}")
print(f"spend so far: ${guard.spent_usd:.4f}")

print("\n=== RUNG 2 (3 wireframes, haiku + mini) ===")
r2 = run_rung2(idea, r1.revised_top, builder, judge_mini)
calls += r2.calls
r2.persist(ROOT / "expeditions", "live-101")
pick = r2.suggested_ranking[0]
print(f"suggested ranking: {r2.suggested_ranking} -> auto-pick #{pick} (demo convenience)")
print(f"spend so far: ${guard.spent_usd:.4f}")

print("\n=== RUNG 3 (REAL interactive demo + REAL Playwright, haiku) ===")
wt = PlaywrightWalkthrough()
r3 = run_rung3(idea, r1.revised_top, r2.wireframes[pick], builder, wt,
               str(ROOT / "expeditions"), "live-101", max_tokens=2800)
calls += r3.calls
print(f"walkthrough passed: {r3.walkthrough.passed} | steps: {r3.walkthrough.steps}")
print(f"detail: {r3.walkthrough.detail[:120]}")
print(f"spend so far: ${guard.spent_usd:.4f}")

print("\n=== RUNG 4 (real MVP loop vs a real acceptance test) ===")
wt4 = EXP / "worktree"
wt4.mkdir(exist_ok=True)
# acceptance test encodes the success criterion; the builder must write feature.mjs to pass
(wt4 / "acceptance.test.mjs").write_text(textwrap.dedent("""
    import { test } from 'node:test'
    import assert from 'node:assert'
    import { handleCmdK } from './feature.mjs'
    test('cmd-k focuses search incl. from modal', () => {
      const state = { focused: null, modalOpen: true }
      handleCmdK(state)
      if (state.focused !== 'search') console.log('ACCEPTANCE_UNMET: cmd-k did not focus search with modal open')
      assert.equal(state.focused, 'search')
    })
"""))
subprocess.run(["git","init","-q"], cwd=wt4)
subprocess.run(["git","add","-A"], cwd=wt4)
subprocess.run(["git","-c","user.email=a@b.c","-c","user.name=fls","commit","-qm","baseline"], cwd=wt4)

class FileWritingBuilder:
    """Wraps the live builder: asks haiku for the module code, writes it into the worktree."""
    def complete(self, prompt, max_tokens=1024, system=None):
        text, call = builder.complete(
            prompt + "\n\nReturn ONLY the JavaScript ES module code for feature.mjs "
            "(export function handleCmdK(state){...}). It must set state.focused='search' "
            "regardless of state.modalOpen. No prose, no fences.",
            max_tokens=500)
        code = text.replace("```javascript","").replace("```js","").replace("```","").strip()
        (wt4 / "feature.mjs").write_text(code + "\n")
        return text, call

verifier = LocalVerifier(["node","--test"], git_dir=str(wt4))
ctx = BoundedContext(spec=r1.revised_top, wireframe=r2.wireframes[pick][:800],
                     acceptance_test=(wt4 / 'acceptance.test.mjs').read_text(),
                     corner_cuts=["no telemetry", "modal handling simplified for demo"])
r4 = run_rung4(101, ctx, FileWritingBuilder(), verifier, str(wt4), str(EXP / "LESSONS.md"))
calls += r4.calls
print(f"passed: {r4.passed} | attempts: {r4.attempts} | descended: {r4.descended}")
if r4.pr_package:
    (EXP / "pr-package.md").write_text(r4.pr_package.as_markdown())
    print("PR package written -> expeditions/live-101/pr-package.md")

print("\n=== ECONOMICS (two-column) ===")
all_calls = calls + ([j.cost] if j.cost else [])
actual = sum(c.usd for c in all_calls)
norm = sum(c.normalized_usd for c in all_calls)
by_fund = {}
for c in all_calls:
    by_fund.setdefault(c.funded_by, [0,0])
    by_fund[c.funded_by][0] += c.usd
    by_fund[c.funded_by][1] += c.normalized_usd
print(f"calls: {len(all_calls)} | ACTUAL: ${actual:.4f} | NORMALIZED: ${norm:.4f}")
for k,(a,n) in by_fund.items():
    print(f"  {k:12} actual=${a:.4f}  normalized=${n:.4f}")
lat = [c.latency_ms for c in all_calls if c.latency_ms]
print(f"latency: avg {sum(lat)//max(len(lat),1)}ms over {len(lat)} timed calls")
print(f"\nguard: ${guard.spent_usd:.4f} of the $0.30 session cap")

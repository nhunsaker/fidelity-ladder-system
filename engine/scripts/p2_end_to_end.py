"""P2 verify (REAL): planted-bug expedition -> real verifier catches it -> descend + LESSONS.md
-> re-climb -> pass -> PR package. Real node:test execution, real git diff. Zero LLM spend
(scripted builder writes buggy-then-fixed artifact
the VERIFIER machinery is 100% real)."""
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.descent import read_lessons
from fls.llm import Call
from fls.local_verifier import LocalVerifier
from fls.rung4 import BoundedContext, run_rung4

wt = Path(tempfile.mkdtemp(prefix="fls-exp-"))
LESSONS = wt / "LESSONS.md"

# acceptance test = the success criterion encoded (fixed); it imports the MVP the builder writes
(wt / "acceptance.test.mjs").write_text(textwrap.dedent("""
    import { test } from 'node:test'
    import assert from 'node:assert'
    import { focusSearchFromModal } from './feature.mjs'
    test('cmd-k focuses search even from a modal', () => {
      if (focusSearchFromModal() !== true) { console.log('ACCEPTANCE_UNMET: cmd-k did not focus search from an open modal')
      }
      assert.equal(focusSearchFromModal(), true)
    })
"""))
subprocess.run(["git","init","-q"], cwd=wt)
subprocess.run(["git","add","-A"], cwd=wt)
subprocess.run(["git","-c","user.email=a@b.c","-c","user.name=x","commit","-qm","baseline"], cwd=wt)

BUGGY = "export function focusSearchFromModal(){ return false }  // ignores modal state (bug)\n"
FIXED = "export function focusSearchFromModal(){ return true }   // registers at root, beats the modal\n"

class ScriptedBuilder:
    def __init__(self, code): self.code = code
    def complete(self, prompt, max_tokens=1024, system=None):
        (wt / "feature.mjs").write_text(self.code)   # a real builder writes to the worktree
        return "wrote feature.mjs", Call("scripted", "none", 0, 0, 0.0)

verifier = LocalVerifier(["node","--test"], git_dir=str(wt))
ctx = BoundedContext(spec="cmd-k focuses search from any screen incl. modals",
                     wireframe="<input aria-label=Search>", corner_cuts=["no telemetry"])

print("=== ROUND 1: MVP build (planted bug) ===")
r1 = run_rung4(42, ctx, ScriptedBuilder(BUGGY), verifier, str(wt), str(LESSONS), max_retries=1)
print(f"passed={r1.passed}  descended={r1.descended}  attempts={r1.attempts}")
print(f"lesson (per-expedition): {r1.lesson.detail if r1.lesson else '-'}")
print(f"LESSONS.md now: {read_lessons(LESSONS)}")

print("\n=== ROUND 2: re-climb (fixed) ===")
r2 = run_rung4(42, ctx, ScriptedBuilder(FIXED), verifier, str(wt), str(LESSONS))
print(f"passed={r2.passed}  attempts={r2.attempts}")
if r2.pr_package:
    md = r2.pr_package.as_markdown()
    print("\n--- PR PACKAGE (excerpt, the <=10-min review bar) ---")
    print(md[:520])
    print(f"\nreal git diff present: {'feature.mjs' in r2.pr_package.diff}")
print(f"\ncost-per-task (Anthropic): ${round(r1.cost_usd + r2.cost_usd, 4)} (scripted builder; verifier real)")
shutil.rmtree(wt, ignore_errors=True)

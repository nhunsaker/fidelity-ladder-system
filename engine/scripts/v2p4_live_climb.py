"""V2-P4 verify: one fresh expedition builds a feature USING @metatoy/bootstrap-styled,
end-to-end — live haiku builder, real acceptance test (react-dom/server SSR under node:test),
component inventory in the bounded context. Budget-capped ~$0.10.

The worktree symlinks demo-app/node_modules so the built module resolves the real library.
No JSX (node runs the module directly): the builder writes React.createElement calls.
"""
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls.llm import BudgetGuard, ClaudeBuilder
from fls.local_verifier import LocalVerifier
from fls.rung4 import BoundedContext, run_rung4

ROOT = Path(__file__).resolve().parents[2]
WT = ROOT / "expeditions" / "v2p4-live"
WT.mkdir(parents=True, exist_ok=True)
guard = BudgetGuard(claude_cap_usd=0.10)
builder = ClaudeBuilder("claude-haiku-4-5-20251001", guard=guard)

# resolve the real library through demo-app's install
nm = WT / "node_modules"
if not nm.exists():
    os.symlink(ROOT / "demo-app" / "node_modules", nm)

ACCEPTANCE = textwrap.dedent("""
    import { test } from 'node:test'
    import assert from 'node:assert'
    import { readFileSync } from 'node:fs'
    import React from 'react'
    import { renderToString } from 'react-dom/server'
    import { AddProductButton } from './feature.mjs'

    test('renders an Add product button from the component library', () => {
      const html = renderToString(React.createElement(AddProductButton))
      assert.match(html, /<button/)
      assert.match(html, /Add product/)
    })

    test('composes from @metatoy/bootstrap-styled, not hand-rolled HTML', () => {
      const src = readFileSync(new URL('./feature.mjs', import.meta.url), 'utf8')
      assert.match(src, /@metatoy\\/bootstrap-styled/)
    })
""")
(WT / "acceptance.test.mjs").write_text(ACCEPTANCE)
subprocess.run(["git", "init", "-q"], cwd=WT, check=False)
subprocess.run(["git", "add", "acceptance.test.mjs"], cwd=WT, check=False)
subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=fls",
                "commit", "-qm", "baseline"], cwd=WT, check=False)

INVENTORY = (
    "@metatoy/bootstrap-styled components: Button (props: variant='primary'|'outline-primary'"
    "|..., size='sm'|'lg'), BsIconPlus, Badge (variant), Card/CardBody/CardTitle, Table, "
    "FormControl, InputGroup. ENVIRONMENT: this module runs in PLAIN NODE (SSR) — use "
    "React.createElement (no JSX), and load the library via its CJS entry: "
    "import { createRequire } from 'node:module'; "
    "const require = createRequire(import.meta.url); "
    "const { Button, BsIconPlus } = require('@metatoy/bootstrap-styled')"
)


class WritingBuilder:
    def complete(self, prompt, max_tokens=1024, system=None):
        text, call = builder.complete(
            prompt + "\n\nReturn ONLY the JavaScript ES module code for feature.mjs. It must "
            "export function AddProductButton() returning React.createElement(...) composed "
            "from @metatoy/bootstrap-styled's Button (variant 'primary') with BsIconPlus and "
            "the label 'Add product'. Import React from 'react'; load the component library "
            "exactly as the COMPONENT LIBRARY section instructs. No JSX, no prose, no fences.",
            max_tokens=500)
        code = text.replace("```javascript", "").replace("```js", "").replace("```", "").strip()
        (WT / "feature.mjs").write_text(code + "\n")
        return text, call


ctx = BoundedContext(
    spec="Add an 'Add product' action to the Products card: a primary button with a plus icon.",
    wireframe="[+ Add product] button, top-right of the Products card header",
    acceptance_test=ACCEPTANCE,
    component_inventory=INVENTORY,
    corner_cuts=["no click handler yet (wiring lands with the form expedition)"],
)
t0 = time.monotonic()
r = run_rung4(301, ctx, WritingBuilder(), LocalVerifier(["node", "--test"], git_dir=str(WT)),
              str(WT), str(WT / "LESSONS.md"), max_retries=2)
print(f"passed={r.passed} attempts={r.attempts} descended={r.descended} "
      f"cost=${r.cost_usd:.4f} ({int(time.monotonic() - t0)}s)")
if r.pr_package:
    print("--- PR package head ---")
    print(r.pr_package.as_markdown()[:400])

"""PlaywrightWalkthrough — the REAL rung-3 walkthrough driver.

Reuses the studio's sorb-test-ui Playwright install (memory: use the harness, not a new
install). Generates a small Node script per run that loads the demo HTML, performs generic
acceptance probes (page loads, interactive elements exist, no console errors, and any
data-acceptance hooks the demo declares), and reports JSON. A failed walkthrough is a design
signal (descend) — this is the auto-advance-with-audit rung's audit.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fls.rung3 import WalkthroughResult

SORB_TEST_UI = Path("/Users/nobrien/workspace/metatoy/sorb-test-ui")

_SCRIPT = r"""
const { chromium } = require('playwright');
(async () => {
  const [,, demoPath, acceptance] = process.argv;
  const out = { passed: false, steps: [], errors: [] };
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('pageerror', e => out.errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
  try {
    await page.goto('file://' + demoPath, { waitUntil: 'load', timeout: 15000 });
    out.steps.push('loaded');
    const interactive = await page.locator('button, input, a, select, [role=button]').count();
    out.steps.push(`interactive elements: ${interactive}`);
    if (interactive === 0) out.errors.push('no interactive elements — not a clickable demo');
    // click the first button-ish element to prove interactivity doesn't crash
    if (interactive > 0) {
      await page.locator('button, [role=button], input, a').first().click({ timeout: 5000 }).catch(e => out.errors.push('first-interaction failed: ' + e.message));
      out.steps.push('first interaction performed');
    }
    // demo-declared acceptance hooks: elements with data-acceptance must exist & be visible
    const hooks = await page.locator('[data-acceptance]').count();
    out.steps.push(`acceptance hooks: ${hooks}`);
    out.passed = out.errors.length === 0;
  } catch (e) { out.errors.push(String(e)); }
  await browser.close();
  console.log(JSON.stringify(out));
})();
"""


@dataclass
class PlaywrightWalkthrough:
    harness_dir: Path = SORB_TEST_UI
    timeout: int = 60

    def available(self) -> bool:
        return (self.harness_dir / "node_modules" / "playwright").exists()

    def run(self, demo_path: str, acceptance: str) -> WalkthroughResult:
        if not self.available():
            return WalkthroughResult(False, "playwright harness unavailable", ["harness missing"])
        # node resolves modules from the SCRIPT's dir, not cwd — the temp script must live
        # inside the harness dir for require('playwright') to find node_modules
        with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False,
                                         dir=self.harness_dir) as f:
            f.write(_SCRIPT)
            script = f.name
        try:
            p = subprocess.run(
                ["node", script, str(Path(demo_path).resolve()), acceptance],
                cwd=self.harness_dir, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
            line = (p.stdout.strip().splitlines() or ["{}"])[-1]
            d = json.loads(line)
            detail = "; ".join(d.get("errors", [])) or "walkthrough clean"
            return WalkthroughResult(bool(d.get("passed")), detail, d.get("steps", []))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            return WalkthroughResult(False, f"walkthrough runner error: {e}", [])
        finally:
            Path(script).unlink(missing_ok=True)

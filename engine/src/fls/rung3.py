"""Rung 3 — interactive throwaway demo + scripted walkthrough (dial: auto-advance-with-audit).

Builder assembles a clickable throwaway prototype (self-contained HTML/JS, fake data, no prod
code) from the winning spec + picked wireframe. A Walkthrough then drives it against the
acceptance criteria — the real impl is Playwright (reuse the sorb-test-ui harness pattern); a
stub returns canned results for tests. A failed walkthrough is a design signal -> descend.

Demos persist to expeditions/<id>/demo/index.html and are served at
stage.../preview/<id> in P2/P3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from fls.adjudicator import Idea
from fls.llm import Call
from fls.rung1 import Builder

_DEMO_SYS = (
    "You build a SELF-CONTAINED interactive HTML demo (inline CSS/JS, fake data, no build step) "
    "that lets a reviewer click through the flow the spec describes. Throwaway quality is fine — "
    "it exists to test direction, not to ship. PRIORITIZE the interactive body: write the "
    "markup and JS FIRST, keep CSS under 20 lines. You have a hard output limit — a complete "
    "plain demo beats a truncated styled one. Return ONLY the HTML document."
)


@dataclass
class WalkthroughResult:
    passed: bool
    detail: str = ""
    steps: list[str] = field(default_factory=list)


class Walkthrough(Protocol):
    def run(self, demo_path: str, acceptance: str) -> WalkthroughResult: ...


@dataclass
class Rung3Result:
    demo_html: str
    walkthrough: WalkthroughResult
    preview_url: str = ""            # served route (harness /preview/<id> · stage…/preview/<id>)
    calls: list[Call] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)


def run_rung3(idea: Idea, spec: str, wireframe: str, builder: Builder, walkthrough: Walkthrough,
              artifact_dir: str, expedition: int, max_tokens: int = 2800) -> Rung3Result:
    html, call = builder.complete(
        f"SPEC:\n{spec}\n\nPICKED WIREFRAME:\n{wireframe[:1500]}\n\nBuild the interactive demo.",
        max_tokens=max_tokens, system=_DEMO_SYS,
    )
    # models love markdown fences; a fenced demo renders as text -> strip defensively
    html = html.strip()
    for fence in ("```html", "```HTML", "```"):
        if html.startswith(fence):
            html = html[len(fence):]
    if html.rstrip().endswith("```"):
        html = html.rstrip()[:-3]
    html = html.strip()
    d = Path(artifact_dir) / str(expedition) / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    wt = walkthrough.run(str(d / "index.html"), idea.success)
    # the served route (P2.2): harness GET /preview/<id>; stage maps the same path. Feeds the
    # PR package's walkthrough link so a reviewer clicks straight into the artifact.
    return Rung3Result(html, wt, preview_url=f"/preview/{expedition}", calls=[call])

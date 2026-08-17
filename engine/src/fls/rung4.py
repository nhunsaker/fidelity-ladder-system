"""Rung 4 — the MVP loop (Wu#1/#3, Chase#1, Yao#1). Designed as a LOOP, not a gate.

Per attempt: build (bounded context) -> verify -> classify:
  - passed      -> assemble the PR package (reviewable in <=10 min) and return
  - flaky/mech  -> retry, up to max_retries, feeding the failure back as context
  - design      -> DESCEND (emit lesson + append LESSONS.md), stop
  - retries out -> DESCEND (the design was likely wrong if mechanical fixes never converge)

Context-bounding (Chase#1): the builder's context is exactly {spec, picked wireframe,
corner-cut ledger, prior-attempt failures} under a compaction cap — the demo-app tree is
navigated via tools, never inlined. Isolation (worktree) is blast-radius control; this is the
context control.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fls.descent import Lesson, append_lessons, make_lesson
from fls.llm import Call
from fls.rung1 import Builder
from fls.verifier import DESCEND, RETRY, Verifier, VerifierResult

MAX_CONTEXT_CHARS = 8000  # compaction cap for the builder's bounded context


@dataclass
class BoundedContext:
    """Exactly what the rung-4 builder sees — nothing more (Chase#1).
    acceptance_test added after live-run descent #101: builders MUST see the acceptance
    criteria as code, or they implement against imagined interfaces."""
    spec: str
    wireframe: str
    acceptance_test: str = ""
    component_inventory: str = ""    # the target app's design-system components (V2-P4): the
                                     # builder composes from a REAL library, not bare HTML
    corner_cuts: list[str] = field(default_factory=list)
    prior_failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        # per-section caps so a huge spec can never crowd out the recent failures (the part
        # that actually steers the retry). Bounding intelligently > truncating the tail.
        parts = [f"SPEC:\n{self.spec[:3000]}", f"PICKED WIREFRAME:\n{self.wireframe[:1500]}"]
        if self.acceptance_test:
            parts.append(f"ACCEPTANCE TEST (your code must pass exactly this):\n{self.acceptance_test[:2000]}")
        if self.component_inventory:
            parts.append("COMPONENT LIBRARY (compose the UI from these, do not hand-roll):\n"
                         + self.component_inventory[:800])
        if self.corner_cuts:
            parts.append("CORNER CUTS (logged):\n"
                         + "\n".join(f"- {c}" for c in self.corner_cuts[:20]))
        if self.prior_failures:
            parts.append("PRIOR ATTEMPT FAILURES (fix these):\n"
                         + "\n".join(f"- {f}" for f in self.prior_failures[-3:]))
        ctx = "\n\n".join(parts)
        return ctx[:MAX_CONTEXT_CHARS]  # final hard cap (belt-and-suspenders)


@dataclass
class PRPackage:
    """The reviewability bar (Wu#1): everything a human needs to review in <=10 minutes."""
    diff: str
    test_output: str
    eval_score: str
    corner_cuts: list[str]
    walkthrough_url: str | None = None

    def as_markdown(self) -> str:
        cuts = "\n".join(f"- {c}" for c in self.corner_cuts) or "- none"
        wt = f"\n\n**Walkthrough:** {self.walkthrough_url}" if self.walkthrough_url else ""
        return (f"## Rung-4 MVP — review package\n\n"
                f"**Eval:** {self.eval_score}\n\n"
                f"**Tests:**\n```\n{self.test_output[:800]}\n```\n\n"
                f"**Corner cuts (logged):**\n{cuts}{wt}\n\n"
                f"<details><summary>Diff</summary>\n\n```diff\n{self.diff[:4000]}\n```\n</details>")


@dataclass
class Rung4Result:
    passed: bool
    attempts: int
    pr_package: PRPackage | None = None
    descended: bool = False
    lesson: Lesson | None = None
    calls: list[Call] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)


def run_rung4(expedition: int, ctx: BoundedContext, builder: Builder, verifier: Verifier,
              artifact_dir: str, lessons_path: str, max_retries: int = 3,
              from_rung: int = 4, to_rung: int = 2, builder_max_tokens: int = 1500) -> Rung4Result:
    calls: list[Call] = []
    attempt = 0
    while attempt <= max_retries:
        attempt += 1
        # build with the bounded context (prior failures fed back in)
        _, call = builder.complete(
            f"Build the MVP for this feature in the worktree. Output the change.\n\n{ctx.render()}",
            max_tokens=builder_max_tokens,
        )
        calls.append(call)
        result: VerifierResult = verifier.verify(artifact_dir)

        if result.passed:
            pkg = PRPackage(
                diff=result.evidence.get("diff", "(diff)"),
                test_output=result.evidence.get("test_output", "all green"),
                eval_score=result.evidence.get("eval_score", "pass"),
                corner_cuts=ctx.corner_cuts,
                walkthrough_url=result.evidence.get("walkthrough_url"),
            )
            return Rung4Result(True, attempt, pr_package=pkg, calls=calls)

        if result.outcome in DESCEND:
            lesson = make_lesson(expedition, from_rung, to_rung, result)
            append_lessons(lessons_path, lesson)
            return Rung4Result(False, attempt, descended=True, lesson=lesson, calls=calls)

        if result.outcome in RETRY and attempt <= max_retries:
            ctx.prior_failures.append(result.detail)  # feed the failure back, retry
            continue

        # retries exhausted on mechanical failures -> treat as design failure, descend
        lesson = make_lesson(expedition, from_rung, to_rung, result)
        append_lessons(lessons_path, lesson)
        return Rung4Result(False, attempt, descended=True, lesson=lesson, calls=calls)

    # unreachable, but fail-closed
    return Rung4Result(False, attempt, descended=True, calls=calls)

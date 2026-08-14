"""Verifier + failure taxonomy — the rung-4 exit gate, and what a failure MEANS.

Wu#3: rung 4 is a loop, not a single gate. A failure is classified so the loop knows whether
to RETRY (flaky/mechanical — cheap to re-attempt) or DESCEND (design-shaped — the wireframe/spec
was wrong, go back down with the lesson). Yao#2: the demo's descent must be a REAL failure a
real verifier catches, never a scripted animation.

A Verifier runs the exit battery on an artifact dir: tests + eval + a11y/perf budget. The real
impl shells out to pytest/axe-core/lighthouse; a StubVerifier returns canned results for tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Outcome(StrEnum):
    passed = "passed"
    flaky = "flaky"          # transient — retry
    mechanical = "mechanical"  # fixable in place (import, typo, lint) — retry
    design = "design"        # the spec/wireframe was wrong — DESCEND with a lesson
    budget = "budget"        # ceiling hit — park


# which outcomes retry vs descend vs stop
RETRY = {Outcome.flaky, Outcome.mechanical}
DESCEND = {Outcome.design}


@dataclass
class VerifierResult:
    outcome: Outcome
    detail: str = ""
    evidence: dict = field(default_factory=dict)   # test log, eval score, a11y report, etc.

    @property
    def passed(self) -> bool:
        return self.outcome == Outcome.passed


class Verifier(Protocol):
    def verify(self, artifact_dir: str) -> VerifierResult: ...


def classify(raw: dict) -> VerifierResult:
    """Map a raw verifier report to the retry/descend taxonomy.

    raw keys (any subset): tests_failed[list], a11y_violations[int], perf_over_budget[bool],
    acceptance_unmet[list], flaky[bool]. The ORDER matters: design failures (acceptance criteria
    unmet, a11y floor breached) descend; mechanical/flaky retry; else pass.
    """
    if raw.get("acceptance_unmet"):
        return VerifierResult(Outcome.design,
                              f"acceptance criteria unmet: {raw['acceptance_unmet']}", raw)
    if raw.get("a11y_violations", 0) > 0:
        # a11y is a non-negotiable floor — an unmet floor is a design failure, descend
        return VerifierResult(Outcome.design,
                              f"{raw['a11y_violations']} a11y violations (floor breached)", raw)
    if raw.get("flaky"):
        return VerifierResult(Outcome.flaky, "transient/flaky failure", raw)
    if raw.get("tests_failed") or raw.get("perf_over_budget"):
        return VerifierResult(Outcome.mechanical,
                              f"mechanical: tests={raw.get('tests_failed')} "
                              f"perf_over={raw.get('perf_over_budget')}", raw)
    return VerifierResult(Outcome.passed, "all checks green", raw)

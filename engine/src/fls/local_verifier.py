"""LocalVerifier — a REAL verifier (replaces the stub seam). Runs a command in the artifact
dir, captures exit/output, and classifies it via the failure taxonomy.

Design failures (acceptance criteria unmet, a11y floor breached) descend; mechanical/flaky
retry; exit 0 passes. Markers in the command output drive the design classification so a real
test suite can signal "this is a direction problem, not a typo" (e.g. print `ACCEPTANCE_UNMET: ...`).

Also assembles real evidence: the git diff of the worktree + the captured test output, so the
rung-4 PR package is a real reviewable artifact.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from fls.verifier import Outcome, VerifierResult, classify


@dataclass
class LocalVerifier:
    command: list[str]                      # e.g. ["node", "--test"]
    a11y_command: list[str] | None = None   # optional axe/pa11y run
    timeout: int = 120
    git_dir: str | None = None              # worktree root for the diff evidence

    def _run(self, cmd: list[str], cwd: str) -> tuple[int, str]:
        try:
            p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                               timeout=self.timeout, check=False)
            return p.returncode, (p.stdout + p.stderr)
        except subprocess.TimeoutExpired:
            return 124, "TIMEOUT"

    def _diff(self, cwd: str) -> str:
        root = self.git_dir or cwd
        try:
            # intent-to-add so NEW files (the MVP's added code) appear in the diff, not just edits
            subprocess.run(["git", "add", "-N", "."], cwd=root,
                           capture_output=True, text=True, timeout=30, check=False)
            p = subprocess.run(["git", "diff", "HEAD"], cwd=root,
                               capture_output=True, text=True, timeout=30, check=False)
            return p.stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    def verify(self, artifact_dir: str) -> VerifierResult:
        rc, out = self._run(self.command, artifact_dir)
        raw: dict = {"test_output": out[-4000:], "diff": self._diff(artifact_dir),
                     "eval_score": "pass" if rc == 0 else "fail"}

        # explicit design signals a real test can emit
        if "ACCEPTANCE_UNMET" in out:
            reasons = [ln.split("ACCEPTANCE_UNMET:", 1)[1].strip()
                       for ln in out.splitlines() if "ACCEPTANCE_UNMET:" in ln]
            raw["acceptance_unmet"] = reasons or ["acceptance criteria unmet"]
        if rc == 124:
            raw["flaky"] = True

        # optional a11y battery — any violation breaches the non-negotiable floor -> design
        if self.a11y_command:
            arc, aout = self._run(self.a11y_command, artifact_dir)
            if arc != 0:
                raw["a11y_violations"] = aout.count("violation") or 1

        if rc != 0 and not any(k in raw for k in ("acceptance_unmet", "a11y_violations", "flaky")):
            raw["tests_failed"] = [ln for ln in out.splitlines()
                                   if "not ok" in ln or "fail" in ln.lower()][:10] or ["exit " + str(rc)]

        result = classify(raw)
        # ensure the rich evidence (diff/output) rides along even on a pass
        result.evidence = {**raw, **(result.evidence or {})}
        return result if rc != 0 or result.outcome == Outcome.passed else \
            VerifierResult(result.outcome, result.detail, raw)

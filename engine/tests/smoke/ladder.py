"""The smoke ladder: a scripted climb through every rung, asserting each SEAM.

Six runs, five failures, and every one was the first execution of a never-run path. The sharpest
was expedition 22: it climbed all five rungs and died at the last one on GitHub 422, "No commits
between main and exp-22", with 229 lines of finished, tested work in the worktree. Rung 4 passed
on a dirty tree; rung 5 needed commits. Each rung correct, each rung green, and the two had never
been run against each other.

THE SESSIONS ARE SCRIPTED, NOT MOCKED, and the distinction is the whole point. Each one writes the
files a real session would and returns the contract a real one returns. Only the thinking is
skipped — every seam is the real seam. A *mock* of a rung's output encodes what its author believed
that rung produces, which is exactly the belief that was false in #22.

Each check asserts the CONSUMER'S precondition, never the producer's self-report.

Runs standalone (`python -m tests.smoke.ladder`) and under pytest. Budget: two minutes. Past that
it gets skipped on deploys, and a skipped gate is not a gate.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from fls.llm import Call

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.smoke.vessel import git, make_vessel  # noqa: E402


@dataclass
class Check:
    seam: str
    ok: bool
    detail: str = ""


class ScriptedSession:
    """Writes what a real session writes; returns what a real one returns."""

    timeout_s = 600
    log_path = None

    def __init__(self, cwd: str, text: str = "", files: dict | None = None):
        self.cwd, self.text, self.files = cwd, text, files or {}
        self.prompt = None

    def run(self, prompt, system=None):
        self.prompt = prompt
        for name, body in self.files.items():
            p = Path(self.cwd) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        if self.log_path:                      # the streaming contract, kept honest
            lp = Path(self.log_path)
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_text(self.text)

        class R:
            pass
        r = R()
        r.text, r.timed_out, r.raw = self.text, False, {}
        r.call = Call("claude-code", "smoke", 0, 0, usd=0.0, normalized_usd=0.0)
        r.num_turns, r.session_id, r.exit_code = 1, "smoke", 0
        return r


def _wireframe_contract(n: int) -> str:
    cands = ", ".join(
        f'{{"name": "exp-{n}-c{i}", "node_id": "9:{i}", "title": "Shape {i}", '
        f'"premise": "a structurally different arrangement, number {i}"}}'
        for i in (1, 2, 3))
    # The fills are part of the contract now, and they are grey: the smoke ladder walks the same
    # seams a real run does, and a fixture that skipped the colour read-back would prove the rung
    # green while leaving the one check that catches a colour violation unexercised.
    fills = ", ".join(f'"exp-{n}-c{i}": ["#F5F5F5", "#E0E0E0", "#212121"]' for i in (1, 2, 3))
    return ('done\n\n```json\n{"page_name": "exp-' + str(n) + '", "page_id": "9:0", '
            '"lint": {"auto_layout": true, "named_layers": true, "detached_instances": false, '
            '"fills": {' + fills + '}}, '
            '"candidates": [' + cands + ']}\n```')


def run(root: Path, number: int = 901) -> list[Check]:
    """Climb, and report one Check per seam. Never raises for a failed seam — a smoke ladder that
    dies on the first problem hides the rest, and the deploy log should carry all of them."""
    from fls.builders.claude_code_builder import ClaudeCodeBuilder
    from fls.builders.figma_wireframe import (
        FigmaWireframeBuilder,
        candidate_slug,
        colour_policy_for,
        page_slug,
    )
    from fls.rung4 import BoundedContext

    out: list[Check] = []
    vessel = make_vessel(root)
    art = root / "expeditions" / str(number)
    art.mkdir(parents=True, exist_ok=True)
    spec = "show the call price on the action bar"

    # ── rung 2 ─────────────────────────────────────────────────────────────────────────────
    s2 = ScriptedSession(str(root), _wireframe_contract(number))
    # Under the greyscale policy, so the smoke ladder exercises the colour check rather
    # than the None-policy path no live run ever takes.
    b2 = FigmaWireframeBuilder("SMOKEKEY", session_factory=lambda **k: s2, n=3,
                               policy=colour_policy_for(spec))
    r2 = b2.build(number, spec, artifact_dir=str(art), log_path=str(art / "wireframes" / "s1.log"))
    out.append(Check("1->2 · the spec reaches the wireframe prompt",
                     spec in (s2.prompt or ""), "the rung-2 prompt did not carry the spec"))
    out.append(Check("2 · the contract is accepted and named by slug",
                     r2.passed and all(c.name.startswith(candidate_slug(number, i))
                                       for i, c in enumerate(r2.candidates, 1)),
                     r2.detail))
    out.append(Check("2 · the page is named for the expedition",
                     r2.page_name == page_slug(number), f"page_name={r2.page_name!r}"))

    # ── the pick ───────────────────────────────────────────────────────────────────────────
    from fls.builders.prototype import picked_wireframe
    picked = picked_wireframe(str(art), 2)
    out.append(Check("2->3 · /pick 2 resolves to the second candidate",
                     bool(picked) and "number 2" in str(picked),
                     f"pick resolved to {str(picked)[:80]!r}"))

    # ── rung 4 ─────────────────────────────────────────────────────────────────────────────
    files = {"src/components/CallPrice.tsx": "export const CallPrice = () => null\n",
             "tests/callPrice.test.ts": "test('it', () => {})\n"}
    s4 = ScriptedSession("", "built it", files)

    def f4(cwd_=None, **k):
        s4.cwd = cwd_ or str(root)
        return s4

    b4 = ClaudeCodeBuilder(str(vessel), session_factory=f4, test_cmd="true", line_budget=400)
    r4 = b4.build(number, BoundedContext(spec=spec, wireframe=str(picked or "")),
                  artifact_dir=str(art))
    wt = art / "mvp" / "wt"
    out.append(Check("3->4 · the picked shape reaches the build prompt",
                     "number 2" in (s4.prompt or ""), "rung 4 never saw the pick"))
    out.append(Check("4 · the build passes and writes its evidence",
                     r4.passed and (art / "mvp" / "summary.json").exists(), r4.detail))

    # THE SEAM EXPEDITION 22 DIED ON. Not "is there a diff" — GitHub asks for COMMITS.
    commits = git(wt, "log", "--oneline", "main..HEAD").stdout.strip()
    out.append(Check("4->5 · commits exist between base and branch (the exp-22 seam)",
                     bool(commits),
                     "rung 4 passed but left no commits — rung 5 gets GitHub 422 "
                     "'No commits between main and this branch'"))
    out.append(Check("4 · nothing is left uncommitted in the worktree",
                     git(wt, "status", "--porcelain").stdout.strip() == "",
                     "files were left staged; the PR would carry only part of the change"))

    # ── rung 5's package ───────────────────────────────────────────────────────────────────
    summary = json.loads((art / "mvp" / "summary.json").read_text())
    out.append(Check("4->5 · the evidence rung 5 reads is on disk",
                     bool(summary.get("branch")) and (art / "mvp" / "diff.patch").exists()
                     and (art / "mvp" / "test-output.txt").exists(),
                     "rung 5 runs in a later activity and has only the expedition number"))
    out.append(Check("4->5 · the branch in the summary is the branch that has the commits",
                     summary.get("branch") == f"exp-{number}",
                     f"summary says {summary.get('branch')!r}"))

    # The facts reducer is a seam like any other, and it dropped the pull request's NUMBER while
    # keeping its URL — so rung 5, which holds only an expedition number, could not address the
    # pull request rung 4 had just opened. Found on expedition 32, after the smoke ladder had
    # passed on it, because nothing here looked at the reduced facts.
    from fls.store import artifact_facts_from
    facts = artifact_facts_from({"ship": {"pr_url": "https://gh/pull/8", "pr_number": 8,
                                          "flag": "a-flag", "ready_for_review": True}})
    out.append(Check("4->5 · the pull request's NUMBER survives the facts reducer",
                     (facts.get("ship") or {}).get("pr_number") == 8,
                     "rung 5 reads these off disk and cannot merge what it cannot address"))
    out.append(Check("4->5 · the flag survives too, so the stage link can carry it",
                     (facts.get("ship") or {}).get("flag") == "a-flag",
                     "without the flag the stage link shows the app unchanged"))
    return out


def main() -> int:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="fls-smoke-") as d:
        checks = run(Path(d))
    bad = [c for c in checks if not c.ok]
    for c in checks:
        print(f"  {'ok  ' if c.ok else 'FAIL'}  {c.seam}")
        if not c.ok and c.detail:
            print(f"          {c.detail}")
    print(f"\nsmoke ladder: {len(checks) - len(bad)}/{len(checks)} seams ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

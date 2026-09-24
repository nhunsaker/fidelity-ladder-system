"""P2: rung-4 loop (retry vs descend), context-bounding, PR package, descent -> LESSONS.md.
Fully stubbed (zero spend)."""
from pathlib import Path

from fls.descent import read_lessons
from fls.llm import Call
from fls.rung4 import BoundedContext, run_rung4
from fls.verifier import Outcome, VerifierResult, classify


class StubBuilder:
    def complete(self, prompt, max_tokens=1024, system=None):
        return "built the mvp", Call("stub", "stub", 100, 200, 0.0)


class SeqVerifier:
    """Returns a scripted sequence of results, one per verify() call."""
    def __init__(self, results):
        self._r = list(results)
        self.calls = 0
    def verify(self, artifact_dir):
        self.calls += 1
        return self._r.pop(0)


def _ctx():
    return BoundedContext(spec="cmd-k focuses search", wireframe="<div>search</div>",
                          corner_cuts=["no telemetry yet"])


def test_passes_first_try_produces_pr_package(tmp_path):
    v = SeqVerifier([VerifierResult(Outcome.passed, "green",
                                    {"diff": "d", "test_output": "8 passed", "eval_score": "0.95"})])
    r = run_rung4(1, _ctx(), StubBuilder(), v, str(tmp_path), str(tmp_path / "LESSONS.md"))
    assert r.passed and r.attempts == 1
    assert r.pr_package is not None
    md = r.pr_package.as_markdown()
    # Corner cuts surface, and the body leads with what the change IS rather than with a
    # rung ordinal — "Rung-4 MVP — review package" was the harness's vocabulary in a
    # document written for whoever opens the pull request.
    assert "What this changes" in md and "no telemetry yet" in md
    assert "rung" not in md.lower(), "the ladder's vocabulary reached the pull request"


def test_mechanical_failure_retries_then_passes(tmp_path):
    v = SeqVerifier([
        VerifierResult(Outcome.mechanical, "import error"),
        VerifierResult(Outcome.passed, "green", {"eval_score": "0.9"}),
    ])
    r = run_rung4(1, _ctx(), StubBuilder(), v, str(tmp_path), str(tmp_path / "LESSONS.md"))
    assert r.passed and r.attempts == 2       # retried once, then passed


def test_design_failure_descends_and_writes_lesson(tmp_path):
    lessons = tmp_path / "LESSONS.md"
    v = SeqVerifier([VerifierResult(Outcome.design, "acceptance unmet",
                                    {"acceptance_unmet": ["cmd-k didn't focus from modal"]})])
    r = run_rung4(7, _ctx(), StubBuilder(), v, str(tmp_path), str(lessons))
    assert not r.passed and r.descended
    assert r.lesson is not None
    # both halves: per-expedition detail + durable pattern in LESSONS.md
    assert "re-climb" in r.lesson.detail
    patterns = read_lessons(lessons)
    assert len(patterns) == 1
    assert "exp #7" in Path(lessons).read_text()


def test_retries_exhausted_descends(tmp_path):
    lessons = tmp_path / "LESSONS.md"
    v = SeqVerifier([VerifierResult(Outcome.mechanical, "still broken")] * 5)
    r = run_rung4(1, _ctx(), StubBuilder(), v, str(tmp_path), str(lessons), max_retries=3)
    assert not r.passed and r.descended
    assert r.attempts == 4                     # initial + 3 retries, then descend
    assert len(read_lessons(lessons)) == 1


def test_context_is_bounded():
    """Bounded by COUNT — the last three failures, twenty corner cuts — and no longer by
    characters. The 8,000-char cap this used to assert meant rung 4 built against a spec cut at
    character 3,000 on every run; see `profile.NO_CAP`."""
    from fls.rung4 import MAX_CONTEXT_CHARS
    ctx = BoundedContext(spec="s" * 20000, wireframe="w" * 20000,
                         prior_failures=["f1", "f2", "f3", "f4", "f5"])
    rendered = ctx.render()
    assert len(rendered) <= MAX_CONTEXT_CHARS
    assert "f5" in rendered and "f3" in rendered  # keeps the last 3 failures
    assert "f1" not in rendered


def test_the_spec_reaches_rung_4_whole():
    """A 5,000-character spec used to arrive as its first 3,000 and nobody knew."""
    spec = "\n".join(f"criterion line {i}: the thing must do the {i}th thing" for i in range(120))
    assert len(spec) > 5000
    rendered = BoundedContext(spec=spec, wireframe="w").render()
    assert spec in rendered


def test_classify_taxonomy():
    assert classify({"acceptance_unmet": ["x"]}).outcome == Outcome.design
    assert classify({"a11y_violations": 3}).outcome == Outcome.design   # floor breach
    assert classify({"flaky": True}).outcome == Outcome.flaky
    assert classify({"tests_failed": ["t1"]}).outcome == Outcome.mechanical
    assert classify({}).outcome == Outcome.passed

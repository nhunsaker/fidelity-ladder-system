"""The scope box on the Feeder screen posts a scope. The endpoint used to drop it.

The screen said "Changed for this run only. The ANCHOR's scope is unaffected", which reads as a
promise that the run used the edited value. It did not — `run_feeder` always read the ANCHOR, so
the box was decorative and its caption was false. Shipped 2026-09-11, found the same day while
explaining to the founder how a run is steered.

Scope is the one knob an operator may turn without a PR, and it is safe to expose because it
cannot loosen anything: guardrails are still injected, the volume cap still applies, and every
candidate still faces the gate.
"""
from __future__ import annotations

from conftest import ANCHOR_MD

from fls.anchor import Anchor
from fls.feeder import ListSink, run_feeder
from fls.llm import Call


class _Echo:
    """Captures the prompt it was handed, so the test asserts on what the model would SEE."""
    def __init__(self):
        self.prompt = ""

    def available(self):
        return True

    def complete(self, prompt, max_tokens=1024, system=None):
        self.prompt = prompt
        return ('[{"intent": "x", "success": "y", "altitude": "ticket", "rationale": "z"}]',
                Call(provider="stub", model="stub", input_tokens=1, output_tokens=1, usd=0.0))


def _anchor():
    return Anchor.load(ANCHOR_MD)


def test_a_posted_scope_reaches_the_prompt():
    a, b = _anchor(), _Echo()
    run = run_feeder(a, "anchor text", b, ListSink(), scope="only the drills screen")
    assert "SCOPE: only the drills screen" in b.prompt
    assert run.scope == "only the drills screen", "the run reports what it actually used"


def test_no_scope_uses_the_anchor_and_says_so():
    a, b = _anchor(), _Echo()
    run = run_feeder(a, "anchor text", b, ListSink())
    assert f"SCOPE: {a.feeder().scope}" in b.prompt
    assert run.scope == a.feeder().scope


def test_a_blank_or_whitespace_scope_falls_back_to_the_anchor():
    """An empty box must not ideate against nothing."""
    a = _anchor()
    for blank in ("", "   ", "\n"):
        b = _Echo()
        run = run_feeder(a, "anchor text", b, ListSink(), scope=blank)
        assert run.scope == a.feeder().scope, f"blank {blank!r} should fall back"


def test_the_override_does_not_touch_the_anchor():
    """Policy is unchanged by a run. The next run with no scope gets the ANCHOR's again."""
    a = _anchor()
    before = a.feeder().scope
    run_feeder(a, "anchor text", _Echo(), ListSink(), scope="something else entirely")
    assert a.feeder().scope == before
    b = _Echo()
    assert run_feeder(a, "anchor text", b, ListSink()).scope == before


def test_an_override_cannot_drop_the_guardrails():
    """Scope steers; it does not loosen. The non-negotiables are in the prompt either way."""
    a = _anchor()
    b = _Echo()
    run_feeder(a, "ANCHOR PROSE HERE", b, ListSink(), scope="anything at all")
    assert "ideas MUST trace to this" in b.prompt


def test_the_volume_cap_still_applies_under_an_override():
    class _Many(_Echo):
        def complete(self, prompt, max_tokens=1024, system=None):
            self.prompt = prompt
            items = ",".join(
                f'{{"intent":"i{i}","success":"s","altitude":"ticket","rationale":"r"}}'
                for i in range(20))
            return f"[{items}]", Call(provider="stub", model="stub", input_tokens=1, output_tokens=1, usd=0.0)

    a = _anchor()
    sink = ListSink()
    run = run_feeder(a, "anchor text", _Many(), sink, scope="wide open")
    assert run.proposed == 20
    assert len(run.filed) == a.feeder().volume_cap, "the cap is policy, not a suggestion"

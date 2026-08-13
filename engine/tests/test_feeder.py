"""P4 — the studio-brainstorm feeder. No spend: the brainstorm Builder is a stub returning a
canned JSON array. We assert ANCHOR-governed prompt assembly (guardrails injected · scope ·
context cap), JSON parsing, the volume cap, filing through the standard door (never self-admit),
and the cost-envelope flag on the shadow cost.
"""
import json
from pathlib import Path

from fls.anchor import Anchor, FeederParams
from fls.feeder import (
    Candidate,
    ListSink,
    build_prompt,
    run_feeder,
)
from fls.llm import Call

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"
ANCHOR_TEXT = ANCHOR_PATH.read_text(encoding="utf-8")


class _StubBrainstorm:
    """Returns a fixed idea array + a subscription-lane Call (usd 0, shadow-priced)."""
    def __init__(self, n=8, normalized_usd=0.02):
        self.n = n
        self.normalized_usd = normalized_usd
        self.last_prompt = None
        self.last_system = None

    def complete(self, prompt, max_tokens=1024, system=None):
        self.last_prompt = prompt
        self.last_system = system
        ideas = [{"intent": f"idea {i}", "success": f"metric {i}",
                  "altitude": "feature" if i % 2 else "ticket", "rationale": "because"}
                 for i in range(self.n)]
        text = "Here you go:\n" + json.dumps(ideas)
        return text, Call("skill-server", "claude-haiku-4-5-20251001", 500, 300,
                          usd=0.0, normalized_usd=self.normalized_usd, funded_by="subscription")


def _anchor():
    return Anchor.load(ANCHOR_PATH)


def test_feeder_params_parse_from_anchor():
    p = _anchor().feeder()
    assert p.volume_cap == 5
    assert p.guardrails_into_prompt is True
    assert p.cost_envelope_usd == 5.00
    assert p.context_cap_tokens == 30000


def test_prompt_injects_guardrails_and_scope():
    p = _anchor().feeder()
    prompt = build_prompt(p, ANCHOR_TEXT)
    assert "North star" in prompt            # guardrails prose is in the prompt
    assert "Non-negotiables" in prompt
    assert p.scope[:20] in prompt            # scope carried through


def test_prompt_caps_workspace_context():
    p = FeederParams(context_cap_tokens=10)  # 10 tokens -> ~40 chars
    huge = "x" * 100_000
    prompt = build_prompt(p, ANCHOR_TEXT, workspace_context=huge)
    # the 100k-char blob is truncated to exactly the cap (10 tokens * 4 chars): a run of 40 x's
    # survives, a run of 41 does not
    assert "x" * 40 in prompt
    assert "x" * 41 not in prompt


def test_prompt_omits_guardrails_when_disabled():
    p = FeederParams(guardrails_into_prompt=False, scope="widgets")
    prompt = build_prompt(p, ANCHOR_TEXT)
    assert "North star" not in prompt
    assert "widgets" in prompt


def test_run_feeder_files_top_n_through_door():
    a = _anchor()  # volume_cap = 5
    sink = ListSink()
    run = run_feeder(a, ANCHOR_TEXT, _StubBrainstorm(n=8), sink)
    assert run.proposed == 8
    assert len(run.filed) == 5               # capped to volume_cap
    assert len(sink.filed) == 5              # actually posted to the sink (the standard door)
    assert run.filed[0].candidate.intent == "idea 0"  # top-first order preserved


def test_run_feeder_never_self_admits():
    """The feeder only FILES idea-issues; nothing in its return path admits or creates an
    expedition. The sink is the standard door — admission stays a separate gate."""
    a = _anchor()
    sink = ListSink()
    run = run_feeder(a, ANCHOR_TEXT, _StubBrainstorm(n=3), sink)
    # every filed item is a raw candidate awaiting admission, not an admitted expedition
    assert all(isinstance(f.candidate, Candidate) for f in run.filed)
    assert not hasattr(run, "expeditions")


def test_run_feeder_reports_subscription_economics():
    a = _anchor()
    run = run_feeder(a, ANCHOR_TEXT, _StubBrainstorm(normalized_usd=0.02), ListSink())
    assert run.cost_usd == 0.0               # subscription lane: nothing metered
    assert run.normalized_usd == 0.02        # but shadow cost is tracked
    assert run.within_envelope is True       # 0.02 well under the 5.00 envelope


def test_run_feeder_flags_envelope_breach():
    a = _anchor()  # envelope 5.00
    run = run_feeder(a, ANCHOR_TEXT, _StubBrainstorm(normalized_usd=6.0), ListSink())
    assert run.within_envelope is False      # shadow cost 6.0 > 5.00 envelope


def test_run_feeder_survives_unparseable_reply():
    class _Junk:
        def complete(self, prompt, max_tokens=1024, system=None):
            return "no json here", Call("skill-server", "claude-haiku-4-5-20251001",
                                        10, 5, funded_by="subscription")
    a = _anchor()
    run = run_feeder(a, ANCHOR_TEXT, _Junk(), ListSink())
    assert run.proposed == 0
    assert run.filed == []

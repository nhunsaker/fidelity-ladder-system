"""P7 — builder pass-back to the skill-server (subscription lane) + fallback guardrails.

All HTTP is stubbed (no spend, no network): the skill-server transport is monkeypatched and the
ClaudeBuilder fallback is replaced by a fake. We assert the accounting columns, the backend
selection from ANCHOR, and the three fallback guardrails (authorized · budgeted · per-run pin).
"""
from pathlib import Path

import pytest

from fls.anchor import Anchor, BuilderConfig
from fls.llm import (
    BudgetExceeded,
    Call,
    ClaudeBuilder,
    FallbackBuilder,
    SkillServerBuilder,
    SkillServerError,
    make_builder,
)

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"


# ── fakes ─────────────────────────────────────────────────────────────────────
class _FakeClaude:
    """Stand-in for ClaudeBuilder: every call spends a fixed metered $0.20 on the api lane."""
    def __init__(self, per_call_usd: float = 0.20):
        self.per_call_usd = per_call_usd
        self.calls = 0

    def complete(self, prompt, max_tokens=1024, system=None):
        self.calls += 1
        return f"api:{prompt[:10]}", Call("anthropic", "claude-haiku-4-5-20251001",
                                          100, 50, usd=self.per_call_usd,
                                          normalized_usd=self.per_call_usd, funded_by="api")


def _skill_builder(monkeypatch, *, text="ok", raises=False):
    b = SkillServerBuilder(shadow_model="claude-haiku-4-5-20251001")
    b._key = "test-key"  # bypass keychain

    def fake_urlopen(req, timeout=0):
        if raises:
            raise OSError("connection refused")
        import io
        import json as _j
        # real server shape: {skill, output}; we also pass usage so the shadow cost is deterministic
        payload = {"skill": "complete", "output": text,
                   "usage": {"input_tokens": 1000, "output_tokens": 500}}
        return io.BytesIO(_j.dumps(payload).encode())

    monkeypatch.setattr("fls.llm.urllib.request.urlopen", fake_urlopen)
    return b


# ── ANCHOR wiring ──────────────────────────────────────────────────────────────
def test_anchor_parses_builder_block():
    a = Anchor.load(ANCHOR_PATH)
    assert a.builder.backend == "skill-server"
    assert a.builder.fallback == "api"
    assert a.builder.fallback_budget_usd == 0.50
    assert a.builder.fallback_pin == "per-run"


def test_builder_block_is_optional():
    """An ANCHOR without a builder: block still parses (default = api backend, no fallback)."""
    assert BuilderConfig().backend == "api"
    assert BuilderConfig().fallback == "none"


def test_make_builder_api_backend_returns_claude():
    a = Anchor.load(ANCHOR_PATH)
    a.builder = BuilderConfig(backend="api")
    assert isinstance(make_builder(a), ClaudeBuilder)


def test_make_builder_skill_server_wraps_fallback_when_authorized():
    a = Anchor.load(ANCHOR_PATH)  # fallback=api in the real ANCHOR
    b = make_builder(a)
    assert isinstance(b, FallbackBuilder)
    assert isinstance(b.primary, SkillServerBuilder)
    assert isinstance(b.fallback, ClaudeBuilder)


def test_make_builder_skill_server_no_fallback_when_unauthorized():
    a = Anchor.load(ANCHOR_PATH)
    a.builder = BuilderConfig(backend="skill-server", fallback="none")
    b = make_builder(a)
    assert isinstance(b, FallbackBuilder)
    assert b.fallback is None


# ── subscription accounting ─────────────────────────────────────────────────────
def test_skill_server_call_is_subscription_funded_zero_usd(monkeypatch):
    b = _skill_builder(monkeypatch, text="spec body")
    text, call = b.complete("write a spec")
    assert text == "spec body"
    assert call.provider == "skill-server"
    assert call.funded_by == "subscription"
    assert call.usd == 0.0                 # nothing metered
    assert call.normalized_usd > 0.0       # but shadow-priced for the comparable column
    # 1000 in @ $1/M + 500 out @ $5/M = 0.001 + 0.0025 = 0.0035
    assert call.normalized_usd == pytest.approx(0.0035)


def test_skill_server_unreachable_raises_skillservererror(monkeypatch):
    b = _skill_builder(monkeypatch, raises=True)
    with pytest.raises(SkillServerError):
        b.complete("write a spec")


# ── fallback guardrails ─────────────────────────────────────────────────────────
def test_fallback_fires_when_primary_down_and_authorized(monkeypatch):
    primary = _skill_builder(monkeypatch, raises=True)
    fake = _FakeClaude()
    fb = FallbackBuilder(primary, fake, fallback_budget_usd=0.50)
    text, call = fb.complete("build it")
    assert call.funded_by == "api"
    assert fake.calls == 1


def test_fallback_refused_when_unauthorized(monkeypatch):
    primary = _skill_builder(monkeypatch, raises=True)
    fb = FallbackBuilder(primary, None, fallback_budget_usd=0.50)  # fallback not authorized
    with pytest.raises(SkillServerError):
        fb.complete("build it")  # fail closed -> expedition parks


def test_fallback_refuses_at_budget(monkeypatch):
    """A new fallback call is refused once cumulative fallback spend has reached the cap."""
    primary = _skill_builder(monkeypatch, raises=True)
    fake = _FakeClaude(per_call_usd=0.30)
    fb = FallbackBuilder(primary, fake, fallback_budget_usd=0.30)
    fb.complete("call one")            # spent 0 -> fires -> 0.30 (at cap now)
    with pytest.raises(BudgetExceeded):
        fb.complete("call two")        # cumulative 0.30 >= cap 0.30 -> refused before firing
    assert fake.calls == 1             # second call never hit the api


def test_per_run_pin_keeps_run_on_fallback(monkeypatch):
    """Once a run falls back it stays on api even if the skill-server recovers (no flapping)."""
    calls = {"n": 0}

    def flaky_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("down")      # first call: skill-server down -> pin to fallback
        import io
        import json as _j
        return io.BytesIO(_j.dumps({"text": "recovered",
                                    "usage": {"input_tokens": 10, "output_tokens": 5}}).encode())

    primary = SkillServerBuilder()
    primary._key = "k"
    monkeypatch.setattr("fls.llm.urllib.request.urlopen", flaky_urlopen)
    fake = _FakeClaude()
    fb = FallbackBuilder(primary, fake, fallback_budget_usd=1.0, pin="per-run")
    _, c1 = fb.complete("one")
    _, c2 = fb.complete("two")
    assert c1.funded_by == "api" and c2.funded_by == "api"  # pinned; never retried the primary
    assert calls["n"] == 1                                  # primary only attempted once

"""V3-B3 — module reflection (`describe` / `GET /system`), registries, and the FLS_MODULES hook.

All $0: no network, no creds. We assert booleans-only reflection (no env VALUE leaks into the
JSON), the /system endpoint shape, registry pre-population + a live registration via the example
wiring, and the fail-closed import hook (a bogus path refuses to start).
"""
import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fls import app as appmod
from fls import modules
from fls.anchor import Anchor

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "modules"


def _anchor() -> Anchor:
    return Anchor.load(ROOT / "ANCHOR.md")


# ── describe(): shapes + booleans-only ────────────────────────────────────────
def test_describe_shapes_all_four_seams():
    slots = modules.describe(_anchor())
    assert set(slots) == {"auth", "ideas", "sources", "workers"}
    # ideas is a LIST (manual door + feeder); the others are single status dicts
    assert isinstance(slots["ideas"], list)
    kinds = {s["kind"] for s in slots["ideas"]}
    assert kinds == {"manual", "feeder"}
    manual = next(s for s in slots["ideas"] if s["kind"] == "manual")
    assert manual["configured"] is True and manual["available"] is True
    for slot in ("auth", "sources", "workers"):
        s = slots[slot]
        assert s["slot"] == slot
        assert isinstance(s["configured"], bool) and isinstance(s["available"], bool)
        assert s["docs_url"] == f"/docs/modules.md#{slot}"


def test_describe_kinds_track_anchor():
    a = _anchor()
    slots = modules.describe(a)
    assert slots["workers"]["kind"] == a.builder.backend
    assert slots["workers"]["detail"]["fallback"] == a.builder.fallback
    assert slots["sources"]["kind"] == "github"
    assert slots["auth"]["kind"] == "github-app"


def test_describe_never_leaks_secret_values(monkeypatch):
    # set every secret to a recognizable sentinel; NONE may appear in the reflected JSON
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "SENTINEL_webhook_secret")
    monkeypatch.setenv("GITHUB_TOKEN", "SENTINEL_github_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SENTINEL_anthropic_key")
    monkeypatch.setenv("FLS_SKILL_SERVER_KEY", "SENTINEL_skill_key")
    monkeypatch.setenv("FLS_REPO", "acme/widgets")          # repo NAME is not a secret
    monkeypatch.setenv("FLS_REPO_DEV", "acme/widgets-dev")
    blob = json.dumps(modules.describe(_anchor()))
    for sentinel in ("SENTINEL_webhook_secret", "SENTINEL_github_token",
                     "SENTINEL_anthropic_key", "SENTINEL_skill_key"):
        assert sentinel not in blob
    # but presence booleans flipped true, and the (non-secret) repo names surfaced
    slots = modules.describe(_anchor())
    assert slots["auth"]["configured"] is True
    assert slots["sources"]["detail"] == {"prod_repo": "acme/widgets", "dev_repo": "acme/widgets-dev"}
    assert slots["sources"]["available"] is True


def test_describe_fail_closed_when_unconfigured(monkeypatch):
    for k in ("FLS_WEBHOOK_SECRET", "GITHUB_TOKEN", "FLS_REPO", "FLS_REPO_DEV"):
        monkeypatch.delenv(k, raising=False)
    slots = modules.describe(_anchor())
    assert slots["auth"]["configured"] is False and slots["auth"]["available"] is False
    assert slots["sources"]["configured"] is False
    assert slots["sources"]["detail"] == {"prod_repo": None, "dev_repo": None}


# ── GET /system ───────────────────────────────────────────────────────────────
def test_system_endpoint(tmp_path):
    appmod.deps.root = ROOT
    appmod.deps._store = None
    c = TestClient(appmod.app)
    r = c.get("/system")
    assert r.status_code == 200
    data = r.json()
    assert data["anchor_version"] == _anchor().version
    assert set(data["slots"]) == {"auth", "ideas", "sources", "workers"}


# ── registries + the FLS_MODULES import hook ──────────────────────────────────
def test_registries_prepopulated_with_builtins():
    assert set(modules.WORKERS) >= {"api", "skill-server"}
    assert "feeder" in modules.IDEAS
    assert "github" in modules.SOURCES
    assert "github-app" in modules.AUTH


def test_fls_modules_hook_registers_example(monkeypatch):
    # the example package is importable from examples/modules
    monkeypatch.syspath_prepend(str(EXAMPLES))
    modules.IDEAS.pop("claude-demo-agent", None)
    sys.modules.pop("ideas_claude_demo_agent.wiring", None)
    loaded = modules.load_modules("ideas_claude_demo_agent.wiring")
    assert loaded == ["ideas_claude_demo_agent.wiring"]
    assert "claude-demo-agent" in modules.IDEAS
    # the registered factory yields a working IdeaSource
    source = modules.IDEAS["claude-demo-agent"](builder=_StubBuilder(), n=2)
    assert source.available() is True


def test_fls_modules_hook_fails_closed_on_unknown():
    with pytest.raises(ImportError):
        modules.load_modules("no_such_module.nowhere")


def test_startup_refuses_on_bogus_fls_modules(monkeypatch):
    monkeypatch.setenv("FLS_MODULES", "totally_bogus.module.path")
    appmod.deps.root = ROOT
    appmod.deps._store = None
    with pytest.raises(ImportError):
        with TestClient(appmod.app):  # entering fires startup -> load_modules raises
            pass


# ── the example agent: files through the door, cannot self-admit ──────────────
class _StubBuilder:
    def available(self) -> bool:
        return True

    def complete(self, prompt, max_tokens=1024, system=None):
        from fls.llm import Call
        text = ('[{"intent": "a", "success": "s", "altitude": "ticket"},'
                ' {"intent": "b", "success": "s", "altitude": "feature"}]')
        return text, Call("stub", "stub")


def test_example_agent_files_through_listsink(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLES))
    mod = importlib.import_module("ideas_claude_demo_agent.module")
    from fls.feeder import ListSink
    sink = ListSink()
    agent = mod.ClaudeDemoAgent(builder=_StubBuilder(), n=2)
    run = agent.run(anchor=None, anchor_text="north star", sink=sink)
    assert len(sink.filed) == 2 and len(run.filed) == 2
    assert not hasattr(sink, "admit")  # no self-admit path exists


def test_registered_idea_kinds_surface_in_describe(monkeypatch):
    """A kind loaded via FLS_MODULES appears in the ideas slot with its own status."""
    from fls import modules

    class FakeBrainstorm:
        def configured(self):
            return True
        def available(self):
            return True
        def detail(self):
            return {"url": "https://example.test"}

    monkeypatch.setitem(modules.IDEAS, "temporal-brainstorm", FakeBrainstorm)
    try:
        from fls.anchor import Anchor
        from pathlib import Path
        a = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")
        kinds = {i["kind"]: i for i in modules.describe(a)["ideas"]}
        assert "temporal-brainstorm" in kinds
        assert kinds["temporal-brainstorm"]["available"] is True
        assert kinds["temporal-brainstorm"]["detail"] == {"url": "https://example.test"}
    finally:
        modules.IDEAS.pop("temporal-brainstorm", None)

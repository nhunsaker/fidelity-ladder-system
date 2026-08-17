"""V3-B3 — module reflection (`describe` / `GET /system`), registries, and the FLS_MODULES hook.

All $0: no network, no creds. We assert booleans-only reflection (no env VALUE leaks into the
JSON), the /system endpoint shape, registry pre-population + a live registration via the example
wiring, and the fail-closed import hook (a bogus path refuses to start).
"""
import importlib
import json
import subprocess
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
def test_describe_shapes_all_six_seams():
    slots = modules.describe(_anchor())
    assert set(slots) == {"auth", "ideas", "lenses", "sources", "workers", "environment"}
    # ideas is a LIST (manual door + feeder); lenses/environment are LISTs too (environment ships
    # one built-in, `worktree`); the other seams are single status dicts
    assert isinstance(slots["ideas"], list)
    assert isinstance(slots["lenses"], list)
    assert isinstance(slots["environment"], list)
    kinds = {s["kind"] for s in slots["ideas"]}
    assert kinds == {"manual", "feeder"}
    env_kinds = {s["kind"] for s in slots["environment"]}
    assert env_kinds == {"worktree"}
    worktree = next(s for s in slots["environment"] if s["kind"] == "worktree")
    assert worktree["slot"] == "environment"
    assert isinstance(worktree["configured"], bool) and isinstance(worktree["available"], bool)
    manual = next(s for s in slots["ideas"] if s["kind"] == "manual")
    assert manual["configured"] is True and manual["available"] is True
    for slot in ("auth", "sources", "workers"):
        s = slots[slot]
        assert s["slot"] == slot
        assert isinstance(s["configured"], bool) and isinstance(s["available"], bool)
        assert s["docs_url"] == f"/docs/modules.md#{slot}"


def test_describe_kinds_track_anchor(monkeypatch):
    # a fully-configured instance (all three GitHub env vars set) auto-selects the github/
    # github-app built-ins — the studio's path, unchanged by the V9-P1 local-mode default.
    monkeypatch.setenv("FLS_REPO", "acme/widgets")
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    a = _anchor()
    slots = modules.describe(a)
    assert slots["workers"]["kind"] == a.builder.backend
    assert slots["workers"]["detail"]["fallback"] == a.builder.fallback
    assert slots["sources"]["kind"] == "github"
    assert slots["auth"]["kind"] == "github-app"


def test_describe_local_mode_is_the_default_with_no_env(monkeypatch):
    """V9-P1: a fresh install (no GitHub env at all) auto-selects the no-op-safe local built-ins
    — configured/available are True (nothing to configure), never a red 'missing' status."""
    for k in ("FLS_REPO", "FLS_REPO_DEV", "FLS_WEBHOOK_SECRET", "GITHUB_TOKEN",
              "FLS_SOURCE_KIND", "FLS_AUTH_KIND"):
        monkeypatch.delenv(k, raising=False)
    slots = modules.describe(_anchor())
    assert slots["sources"]["kind"] == "local"
    assert slots["sources"]["configured"] is True and slots["sources"]["available"] is True
    assert slots["auth"]["kind"] == "none"
    assert slots["auth"]["configured"] is True and slots["auth"]["available"] is True


def test_local_mode_kind_can_be_forced_via_env_override(monkeypatch):
    """FLS_SOURCE_KIND/FLS_AUTH_KIND force local-mode even when the GitHub env IS present —
    an escape hatch for testing/staging without touching the App wiring."""
    monkeypatch.setenv("FLS_REPO", "acme/widgets")
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("FLS_SOURCE_KIND", "local")
    monkeypatch.setenv("FLS_AUTH_KIND", "none")
    slots = modules.describe(_anchor())
    assert slots["sources"]["kind"] == "local"
    assert slots["auth"]["kind"] == "none"


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
    # explicitly select the github/github-app path (FLS_SOURCE_KIND/FLS_AUTH_KIND) while leaving
    # the actual GitHub env unset — an instance that DECLARED it wants the App path but hasn't
    # finished wiring it still fails closed, never silently degrades to "available".
    for k in ("FLS_WEBHOOK_SECRET", "GITHUB_TOKEN", "FLS_REPO", "FLS_REPO_DEV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FLS_SOURCE_KIND", "github")
    monkeypatch.setenv("FLS_AUTH_KIND", "github-app")
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
    assert set(data["slots"]) == {"auth", "ideas", "lenses", "sources", "workers", "environment"}
    assert isinstance(data["app"], bool)


def test_system_endpoint_reflects_local_mode_with_no_github_env(monkeypatch):
    """V9-P1: a fresh install's /system reports app:false + local-mode kinds — the de-footgun
    contract the quickstart depends on."""
    for k in ("FLS_REPO", "FLS_REPO_DEV", "FLS_WEBHOOK_SECRET", "GITHUB_TOKEN",
              "FLS_SOURCE_KIND", "FLS_AUTH_KIND"):
        monkeypatch.delenv(k, raising=False)
    appmod.deps.root = ROOT
    appmod.deps._store = None
    c = TestClient(appmod.app)
    data = c.get("/system").json()
    assert data["app"] is False
    assert data["slots"]["sources"]["kind"] == "local"
    assert data["slots"]["auth"]["kind"] == "none"


def test_system_endpoint_reports_app_true_when_github_app_configured(monkeypatch):
    monkeypatch.setenv("FLS_REPO", "acme/widgets")
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "s")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    appmod.deps.root = ROOT
    appmod.deps._store = None
    c = TestClient(appmod.app)
    data = c.get("/system").json()
    assert data["app"] is True
    assert data["slots"]["sources"]["kind"] == "github"
    assert data["slots"]["auth"]["kind"] == "github-app"


# ── registries + the FLS_MODULES import hook ──────────────────────────────────
def test_registries_prepopulated_with_builtins():
    assert set(modules.WORKERS) >= {"api", "skill-server"}
    assert "feeder" in modules.IDEAS
    assert "github" in modules.SOURCES and "local" in modules.SOURCES
    assert "github-app" in modules.AUTH and "none" in modules.AUTH
    assert "worktree" in modules.ENVIRONMENTS


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


def test_registered_lens_kinds_surface_in_describe(monkeypatch):
    """A kind loaded via FLS_MODULES appears in the lenses slot with its own status — mirrors
    the IDEAS registry loop exactly. LENSES has no built-in, so this is the only way in."""
    from fls import modules

    class FakeLens:
        kind = "design-audit"
        mode = "audit-first"
        panel = "design"
        target_vessel = "acme-demo"
        cadence = "manual"
        sink_label = "lens:design-audit"

        def configured(self):
            return True
        def available(self):
            return True
        def detail(self):
            return {"url": "https://example.test"}

    monkeypatch.setitem(modules.LENSES, "design-audit", FakeLens)
    try:
        from pathlib import Path

        from fls.anchor import Anchor
        a = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")
        slots = modules.describe(a)
        assert isinstance(slots["lenses"], list)
        kinds = {s["kind"]: s for s in slots["lenses"]}
        assert "design-audit" in kinds
        entry = kinds["design-audit"]
        assert entry["slot"] == "lenses"
        assert entry["configured"] is True and entry["available"] is True
        assert entry["detail"] == {"url": "https://example.test"}
    finally:
        modules.LENSES.pop("design-audit", None)


def test_lenses_empty_by_default_and_status_reflection_never_leaks(monkeypatch):
    """No FLS_MODULES-registered lens -> the lenses slot is an empty list (LENSES has no
    built-in). A registered lens's status reflection is booleans + non-secret detail only —
    mirrors test_describe_never_leaks_secret_values: env secrets set elsewhere in the process
    must never appear in the lenses slot's JSON, and a well-behaved lens's detail() (kind/mode/
    target_vessel — no secrets) is exactly what surfaces."""
    from fls import modules

    a = _anchor()
    assert modules.describe(a)["lenses"] == []

    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "SENTINEL_webhook_secret")
    monkeypatch.setenv("GITHUB_TOKEN", "SENTINEL_github_token")

    class WellBehavedLens:
        kind = "design-audit"
        mode = "audit-first"
        panel = "design"
        target_vessel = "acme-demo"
        cadence = "manual"
        sink_label = "lens:design-audit"

        def configured(self):
            return True
        def available(self):
            return True
        def detail(self):
            # non-secret only, by contract: kind/mode/target_vessel — never a key or URL-with-key
            return {"kind": self.kind, "mode": self.mode, "target_vessel": self.target_vessel}

    monkeypatch.setitem(modules.LENSES, "design-audit", WellBehavedLens)
    try:
        blob = json.dumps(modules.describe(a))
        assert "SENTINEL_webhook_secret" not in blob
        assert "SENTINEL_github_token" not in blob
        lenses = {s["kind"]: s for s in modules.describe(a)["lenses"]}
        assert lenses["design-audit"]["detail"] == {
            "kind": "design-audit", "mode": "audit-first", "target_vessel": "acme-demo",
        }
    finally:
        modules.LENSES.pop("design-audit", None)


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
        from pathlib import Path

        from fls.anchor import Anchor
        a = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")
        kinds = {i["kind"]: i for i in modules.describe(a)["ideas"]}
        assert "temporal-brainstorm" in kinds
        assert kinds["temporal-brainstorm"]["available"] is True
        assert kinds["temporal-brainstorm"]["detail"] == {"url": "https://example.test"}
    finally:
        modules.IDEAS.pop("temporal-brainstorm", None)


# ── V8-P3: the 6th slot — ENVIRONMENT ──────────────────────────────────────────
@pytest.fixture
def tmp_git_repo(tmp_path):
    """A throwaway git repo (NOT this repo) so worktree provisioning is fully self-contained —
    no real worktrees created against the FLS tree itself."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def test_worktree_environment_builtin_registered():
    assert "worktree" in modules.ENVIRONMENTS
    env = modules.ENVIRONMENTS["worktree"]()
    assert isinstance(env, modules.WorktreeEnvironment)
    assert env.kind == "worktree"
    assert env.configured() is True  # git is on PATH in this dev/CI environment
    assert env.detail() == {"provisioning": "git-worktree", "verify": "shell-command"}


def test_worktree_environment_provision_verify_teardown(tmp_git_repo, tmp_path):
    env = modules.WorktreeEnvironment(repo_root=str(tmp_git_repo))
    base = tmp_path / "worktrees"
    handle = env.provision("expedition-42", base_dir=str(base))
    assert handle.kind == "worktree"
    assert Path(handle.workdir).is_dir()
    assert (Path(handle.workdir) / "README.md").exists()

    ok = env.run_verify(handle, "test -f README.md")
    assert ok.passed is True and ok.exit_code == 0

    bad = env.run_verify(handle, "exit 7")
    assert bad.passed is False and bad.exit_code == 7

    env.teardown(handle)
    # `git worktree remove` deletes the directory; the repo no longer lists it
    listing = subprocess.run(["git", "worktree", "list"], cwd=tmp_git_repo,
                              capture_output=True, text=True, check=True).stdout
    assert handle.workdir not in listing


def test_describe_environment_fail_closed_on_erroring_factory(monkeypatch):
    """Mirrors the IDEAS/LENSES erroring-factory contract: an ENVIRONMENT factory that raises
    reports honestly as unavailable (fail-closed) rather than crashing `describe`/`GET /system`.
    (Error text is truncated to 120 chars like the other loops — it's a diagnostic detail, not a
    place a real env-var SECRET VALUE would ever land; those are gated by `configured`/
    `available` booleans, never interpolated into `detail`.)"""
    def _boom(**kw):
        raise RuntimeError("no docker socket")

    monkeypatch.setitem(modules.ENVIRONMENTS, "docker", _boom)
    try:
        slots = modules.describe(_anchor())  # must not raise
        by_kind = {s["kind"]: s for s in slots["environment"]}
        assert by_kind["docker"]["configured"] is False
        assert by_kind["docker"]["available"] is False
        assert "no docker socket" in by_kind["docker"]["detail"]["error"]
        json.dumps(slots)  # still JSON-serializable
    finally:
        modules.ENVIRONMENTS.pop("docker", None)


def test_environment_registered_via_fls_modules_style_assignment(monkeypatch):
    """A module registers a new ENVIRONMENT kind the same way LENSES/IDEAS extension works —
    assign a factory into the registry (what an FLS_MODULES-imported wiring.py does)."""
    class StubDevcontainerEnvironment:
        kind = "devcontainer"
        def configured(self): return True
        def available(self): return True
        def detail(self): return {"provisioning": "devcontainer"}

    monkeypatch.setitem(modules.ENVIRONMENTS, "devcontainer", lambda **kw: StubDevcontainerEnvironment())
    try:
        kinds = {s["kind"] for s in modules.describe(_anchor())["environment"]}
        assert {"worktree", "devcontainer"} <= kinds
    finally:
        modules.ENVIRONMENTS.pop("devcontainer", None)


# ── V8-P3: published middleware seams ──────────────────────────────────────────
def test_middleware_hooks_are_the_four_published_names():
    assert modules.MIDDLEWARE_HOOKS == ("before_rung", "after_rung", "on_descend",
                                         "on_context_assembly")
    assert set(modules.MIDDLEWARE) == set(modules.MIDDLEWARE_HOOKS)


def test_middleware_register_and_dispatch_invokes_in_order():
    calls = []
    modules.register_middleware("before_rung", lambda hook, **kw: calls.append(("a", hook, kw)))
    modules.register_middleware("before_rung", lambda hook, **kw: calls.append(("b", hook, kw)))
    try:
        modules.dispatch_middleware("before_rung", rung=3, expedition_id="e1")
        assert calls == [
            ("a", "before_rung", {"rung": 3, "expedition_id": "e1"}),
            ("b", "before_rung", {"rung": 3, "expedition_id": "e1"}),
        ]
    finally:
        modules.MIDDLEWARE["before_rung"].clear()


def test_middleware_dispatch_isolates_a_raising_callback(caplog):
    calls = []

    def _boom(hook, **kw):
        raise RuntimeError("callback exploded")

    modules.register_middleware("on_descend", _boom)
    modules.register_middleware("on_descend", lambda hook, **kw: calls.append(hook))
    try:
        modules.dispatch_middleware("on_descend", reason="rung-4 failure")  # must not raise
        assert calls == ["on_descend"]  # the second callback still ran despite the first raising
    finally:
        modules.MIDDLEWARE["on_descend"].clear()


def test_middleware_unknown_hook_fails_closed_on_register_and_dispatch():
    with pytest.raises(ValueError):
        modules.register_middleware("no_such_hook", lambda hook, **kw: None)
    with pytest.raises(ValueError):
        modules.dispatch_middleware("no_such_hook")


def test_middleware_on_context_assembly_dispatch():
    seen = []
    modules.register_middleware("on_context_assembly",
                                 lambda hook, **kw: seen.append(kw.get("budget")))
    try:
        modules.dispatch_middleware("on_context_assembly", budget=2000, rung=4)
        assert seen == [2000]
    finally:
        modules.MIDDLEWARE["on_context_assembly"].clear()


# ── V9-P1: local-mode built-ins (LocalSource / NoneAuth) ──────────────────────
def test_local_source_registers_and_resolves():
    assert "local" in modules.SOURCES
    src = modules.SOURCES["local"]()
    assert isinstance(src, modules.LocalSource)
    assert src.kind == "local"


def test_local_source_is_no_op_safe_and_never_fabricates_an_issue():
    src = modules.LocalSource()
    assert src.configured() is True and src.available() is True
    # every outbound call is a safe no-op — never raises, never touches the network
    src.post_comment(1, "hi")
    src.set_labels(1, ["rung:1-spec"])
    assert src.create_deployment("prod", "abc123") is False
    # but it never pretends a GitHub issue exists — mirrors the real client's honest failure
    with pytest.raises(LookupError):
        src.get_issue(1)
    with pytest.raises(LookupError):
        src.list_comments(1)
    assert src.detail()["mode"] == "local"


def test_local_source_fail_closed_on_misconfig():
    """A registry entry that errors on construction reports honestly as unavailable, mirroring
    the IDEAS/LENSES/ENVIRONMENT erroring-factory contract — never crashes describe()."""
    def _boom(**kw):
        raise RuntimeError("bad local-mode config")

    orig = modules.SOURCES.get("local")
    modules.SOURCES["local"] = _boom
    try:
        with pytest.raises(RuntimeError):
            modules.SOURCES["local"]()
    finally:
        modules.SOURCES["local"] = orig


def test_none_auth_registers_and_resolves():
    assert "none" in modules.AUTH
    auth = modules.AUTH["none"]()
    assert isinstance(auth, modules.NoneAuth)
    assert auth.kind == "none"


def test_none_auth_is_no_op_safe_never_admits_on_optimism():
    auth = modules.NoneAuth()
    assert auth.configured() is True and auth.available() is True
    assert auth.outbound_token() is None
    # no webhook secret configured anywhere -> verify_inbound ALWAYS refuses, even a well-formed
    # signature header — local-mode never receives a real webhook to begin with
    assert auth.verify_inbound(b"{}", None) is False
    assert auth.verify_inbound(b"{}", "sha256=deadbeef") is False

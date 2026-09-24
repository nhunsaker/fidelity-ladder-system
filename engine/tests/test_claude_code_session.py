"""ClaudeCodeSession: envelope parsing, accounting, caps, failures — subprocess stubbed."""
import json
import subprocess

import pytest

from fls.claude_code import ClaudeCodeBuilder, ClaudeCodeError, ClaudeCodeSession
from fls.llm import BudgetGuard

ENVELOPE = {"type": "result", "subtype": "success", "result": "done: added modal",
            "total_cost_usd": 0.0421, "num_turns": 7, "session_id": "sess-1",
            "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 5000}}


class FakeProc:
    def __init__(self, stdout="", stderr="", code=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, code


def test_args_carry_the_budget_and_tools(tmp_path):
    s = ClaudeCodeSession(cwd=tmp_path, allowed_tools=("Read", "Bash(pnpm *)"), mcp_config="/x/mcp.json",
                          max_turns=12, model="claude-sonnet-5")
    a = s.args(system="be brief")
    # stream-json, not json: the buffered form emits one envelope at the END, so a session killed
    # mid-rung leaves an EMPTY log and the page id a retry needs is lost with it. Proven live on
    # expedition 19 — the rung succeeded and the sentinel was nowhere in the streamed file.
    assert a[:5] == [s.bin, "-p", "--output-format", "stream-json", "--verbose"]
    assert "--max-turns" in a and a[a.index("--max-turns") + 1] == "12"
    assert a[a.index("--allowedTools") + 1] == "Read,Bash(pnpm *)"
    assert "--mcp-config" in a and "--strict-mcp-config" in a
    assert a[a.index("--append-system-prompt") + 1] == "be brief"
    assert a[a.index("--model") + 1] == "claude-sonnet-5"


def test_run_parses_envelope_into_subscription_call(monkeypatch, tmp_path):
    seen = {}
    def fake_run(args, **kw):
        seen["args"], seen["input"], seen["cwd"] = args, kw["input"], kw["cwd"]
        return FakeProc(stdout=json.dumps(ENVELOPE))
    monkeypatch.setattr(subprocess, "run", fake_run)
    g = BudgetGuard(claude_cap_usd=1.0)
    s = ClaudeCodeSession(cwd=tmp_path, guard=g)
    r = s.run("build it")
    assert seen["input"] == "build it" and seen["cwd"] == str(tmp_path)
    assert r.text == "done: added modal" and r.num_turns == 7 and r.session_id == "sess-1"
    c = r.call
    assert c.provider == "claude-code" and c.funded_by == "subscription" and c.usd == 0.0
    assert c.normalized_usd == pytest.approx(0.0421)
    assert c.input_tokens == 6200 and c.output_tokens == 300
    assert g.spent_usd == 0.0  # subscription lane never trips the metered cap


def test_run_without_cost_field_uses_shadow_price(monkeypatch, tmp_path):
    env = dict(ENVELOPE)
    env.pop("total_cost_usd")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=json.dumps(env)))
    r = ClaudeCodeSession(cwd=tmp_path).run("x")
    assert r.call.normalized_usd > 0


def test_run_tolerates_leading_noise(monkeypatch, tmp_path):
    out = "warning: something\n" + json.dumps(ENVELOPE) + "\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=out))
    assert ClaudeCodeSession(cwd=tmp_path).run("x").text == "done: added modal"


def test_timeout_is_a_result_not_an_exception(monkeypatch, tmp_path):
    def boom(args, **kw):
        raise subprocess.TimeoutExpired(cmd=args, timeout=kw["timeout"], output=b'{"partial":1}')
    monkeypatch.setattr(subprocess, "run", boom)
    r = ClaudeCodeSession(cwd=tmp_path, timeout_s=5).run("x")
    assert r.timed_out and r.exit_code == -9 and r.call.funded_by == "subscription"
    text, call = ClaudeCodeBuilder(ClaudeCodeSession(cwd=tmp_path, timeout_s=5)).complete("x")
    assert text.startswith("[timed out after 5s]")


def test_unauthenticated_cli_fails_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout="", stderr="Not logged in", code=1))
    with pytest.raises(ClaudeCodeError, match="Not logged in"):
        ClaudeCodeSession(cwd=tmp_path).run("x")


def test_missing_binary_fails_loud(monkeypatch, tmp_path):
    def nf(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", nf)
    with pytest.raises(ClaudeCodeError, match="not found"):
        ClaudeCodeSession(cwd=tmp_path, bin="claude-nope").run("x")


def test_make_builder_claude_code_backend(monkeypatch, tmp_path):
    from fls.anchor import Anchor
    from fls.llm import make_builder
    monkeypatch.setenv("FLS_WORKER_ROOT", str(tmp_path))
    # minimal anchor via the pydantic model directly
    from fls.anchor import (
        Adjudicator,
        AdjudicatorCost,
        Budgets,
        BuilderConfig,
        DemoteTrigger,
        Funnel,
        WorkerConfig,
    )
    anchor = Anchor(version=1, mode="slim",
                    adjudicator=Adjudicator(kind="single-llm", model="azure-openai:x",
                                            cost=AdjudicatorCost(max_tokens=1, max_calls=1),
                                            output_contract=["verdict", "reasoning", "cost"]),
                    builder=BuilderConfig(backend="claude-code", shadow_model="claude-sonnet-5"),
                    worker=WorkerConfig(rungs={"0": {"max_turns": 3, "wall_clock_s": 9}}),
                    idea_sources=[], funnel=Funnel(auto_build=1, interactive_demos=0, wireframes="all"),
                    rungs={}, budgets=Budgets(per_expedition_ceiling_usd=1, claude_api_hard_cap_usd=0),
                    autonomy_demote=DemoteTrigger(agreement_threshold=0.8, window=10, action="tighten_one_step"),
                    altitude_allowed=["feature"])
    b = make_builder(anchor)
    assert isinstance(b, ClaudeCodeBuilder)
    assert b.session.max_turns == 3 and b.session.timeout_s == 9 and str(b.session.cwd) == str(tmp_path)


def test_error_envelope_fails_loud(monkeypatch, tmp_path):
    env = {"type": "result", "is_error": True, "result": "Not logged in · Please run /login", "num_turns": 1}
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc(stdout=json.dumps(env), code=1))
    with pytest.raises(ClaudeCodeError, match="Not logged in"):
        ClaudeCodeSession(cwd=tmp_path).run("x")


# ── the agent's environment: a prompt is not a control ─────────────────────────────────────

def test_credentials_do_not_reach_the_agents_environment(monkeypatch):
    """Rung 4 is the first rung with Bash, and a shell inherits whatever the worker unit was
    given. Telling an agent not to push is advice; not handing it the token is a control."""
    from fls.claude_code import ClaudeCodeSession
    for k, v in {"GITHUB_TOKEN": "ghp_x", "FLS_WEBHOOK_SECRET": "s", "AZURE_OPENAI_KEY": "k",
                 "FLS_DEMO_PASSCODE": "p", "SOME_API_AUTH": "a"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("FLS_ROOT", "/tmp/x")
    env = ClaudeCodeSession(cwd=".").child_env()
    for k in ("GITHUB_TOKEN", "FLS_WEBHOOK_SECRET", "AZURE_OPENAI_KEY", "FLS_DEMO_PASSCODE",
              "SOME_API_AUTH"):
        assert k not in env, f"{k} reached the agent"
    # the non-secret configuration it legitimately needs survives
    assert env["FLS_ROOT"] == "/tmp/x"
    # Set, not set to a particular spelling. `child_env` uses `setdefault`, so a parent that
    # already says CI keeps its own word for it — GitHub Actions says "true" — and every tool this
    # is for treats any non-empty value the same way. Pinning "1" made this the one test that
    # failed only on CI, which is the worst place to have a test that is wrong about CI.
    assert "PATH" in env and env.get("CI")


def test_the_clis_own_credential_is_the_one_thing_kept(monkeypatch):
    from fls.claude_code import ClaudeCodeSession
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep-me")
    monkeypatch.setenv("GITHUB_TOKEN", "drop-me")
    env = ClaudeCodeSession(cwd=".").child_env()
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep-me"
    assert "GITHUB_TOKEN" not in env


def test_the_allowlist_is_configurable_per_session(monkeypatch):
    from fls.claude_code import ClaudeCodeSession
    monkeypatch.setenv("VESSEL_DEPLOY_KEY", "needed-by-this-rung")
    assert "VESSEL_DEPLOY_KEY" not in ClaudeCodeSession(cwd=".").child_env()
    s = ClaudeCodeSession(cwd=".", env_allow=("VESSEL_DEPLOY_KEY",))
    assert s.child_env()["VESSEL_DEPLOY_KEY"] == "needed-by-this-rung"

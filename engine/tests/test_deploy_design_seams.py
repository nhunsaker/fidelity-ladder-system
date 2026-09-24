"""V10 — the DEPLOY and DESIGN seams, the contradiction checks, and the rung-5a gate move.

Three claims are pinned here because each one, if it silently regressed, would put the system back
to making a statement it cannot back:

  1. A `deploy: none` instance REFUSES rung 5a with a reason. Before this seam existed, `Deployer`
     was a Protocol nothing injected, so the ladder advertised a 5a rung with a dial and a cost
     estimate behind machinery that was never connected — a claim by omission.
  2. Half-wiring is NAMED. A GitHub token with no FLS_REPO rendered as a calm `LOCAL DEFAULT`,
     the posture the docs call "the fresh-install steady state, not an error to chase".
  3. The 5a gate moved, and ONLY the right half moved: staging happens without a human; prod and
     merge do not.
"""
from __future__ import annotations

import pytest
from conftest import ANCHOR_MD

from fls import modules
from fls.anchor import Anchor
from fls.rung5 import FlagStore, promote_to_prod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every seam here reads env. A developer's own exported FLS_* would otherwise decide the
    result, which is how a test starts passing for a reason the assertion does not name."""
    for k in ("FLS_DEPLOY_KIND", "FLS_STAGE_DIR", "FLS_REPO", "GITHUB_TOKEN", "FLS_VESSEL_REPO",
              "FLS_DESIGN_KIND", "FLS_FIGMA_FILE_KEY", "FLS_MCP_CONFIG", "FLS_DESIGN_PACK"):
        monkeypatch.delenv(k, raising=False)


# ── DEPLOY ────────────────────────────────────────────────────────────────────
def test_deploy_defaults_to_none_and_that_deployer_never_reports_success():
    st = modules._deploy_status()
    assert st["kind"] == "none"
    assert st["available"] is False
    # The load-bearing part: the no-op deployer must return False, not True. A deployer that
    # returned True here would mark a build 5a-staged with nothing standing behind it.
    assert modules.make_deployer("none").deploy("stage", "HEAD") is False


def test_static_dir_is_configured_but_unavailable_when_the_path_is_missing(tmp_path, monkeypatch):
    """`configured` and `available` are different questions, and this is the case that proves it:
    the operator named a target, so it is configured; the path is not writable, so nothing can
    land there. Collapsing these into one boolean is what makes a status screen lie."""
    monkeypatch.setenv("FLS_STAGE_DIR", str(tmp_path / "does-not-exist"))
    st = modules._deploy_status()
    assert st["kind"] == "static-dir"
    assert st["configured"] is True
    assert st["available"] is False
    assert "writable" in st["detail"]["note"]


def test_static_dir_deploy_writes_an_observable_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_STAGE_DIR", str(tmp_path))
    st = modules._deploy_status()
    assert st["available"] is True
    assert modules.make_deployer("static-dir").deploy("stage", "exp-42") is True
    # evidence over claims: the deploy is readable off disk, not merely reported
    assert (tmp_path / "stage" / "DEPLOYED").read_text().strip() == "exp-42"


def test_an_unknown_deploy_kind_refuses_rather_than_falling_back_to_one_that_deploys(monkeypatch):
    monkeypatch.setenv("FLS_DEPLOY_KIND", "vercel-typo")
    assert modules.make_deployer().deploy("stage", "HEAD") is False


# ── DESIGN ────────────────────────────────────────────────────────────────────
def test_design_defaults_to_html_and_needs_nothing():
    st = modules._design_status(None)
    assert (st["kind"], st["configured"], st["available"]) == ("html", True, True)


def test_figma_named_without_tools_is_configured_but_unavailable(monkeypatch):
    monkeypatch.setenv("FLS_FIGMA_FILE_KEY", "abc123")
    st = modules._design_status(None)
    assert st["kind"] == "figma"
    assert st["configured"] is True
    assert st["available"] is False, "no MCP config means no session can reach the file"
    assert st["detail"]["file_key"] == "abc123"   # the key is an identifier, not a secret


def test_figma_with_tools_is_available(monkeypatch):
    monkeypatch.setenv("FLS_FIGMA_FILE_KEY", "abc123")
    monkeypatch.setenv("FLS_MCP_CONFIG", "/etc/fls/mcp.json")
    assert modules._design_status(None)["available"] is True


# ── contradictions ────────────────────────────────────────────────────────────
def test_a_token_with_no_repo_is_named_not_rendered_as_a_neutral_default(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    slots = {"deploy": {"kind": "static-dir"}}
    reasons = [c["reason"] for c in modules.contradictions(slots) if c["slot"] == "sources"]
    assert reasons, "a token with no FLS_REPO is half-wiring, not a fresh-install default"
    assert "FLS_REPO" in reasons[0]


def test_a_vessel_checkout_with_no_source_repo_is_named(monkeypatch):
    monkeypatch.setenv("FLS_VESSEL_REPO", "/srv/vessel")
    reasons = [c["reason"] for c in modules.contradictions({"deploy": {"kind": "static-dir"}})]
    assert any("expedition" in r for r in reasons)


def test_a_coherent_instance_stays_silent(monkeypatch):
    """The common case. A contradiction list that cries wolf on a healthy instance is worse than
    no list at all — it trains the operator to skip the row that matters."""
    monkeypatch.setenv("FLS_REPO", "acme/app")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("FLS_STAGE_DIR", "/srv/stage")
    assert modules.contradictions({"deploy": {"kind": "static-dir"}}) == []


# ── the gate moved, and only the right half moved ─────────────────────────────
class _Runner:
    """What `LiveRunner._stage` actually reads. Constructing a real LiveRunner would drag in
    Temporal and a worker host; the method under test is deliberately small enough that its
    collaborators are the anchor, the deploy seam, and the vessel's own build declaration.

    `vessel_build_cmd` empty = the marker-only mode this seam has always had: record the ref,
    publish no files. An instance declaring no build must keep working exactly as before."""
    def __init__(self, anchor, root=".", build_cmd="", build_dir=""):
        self.anchor = anchor
        self.root = __import__("pathlib").Path(root)
        self.vessel_build_cmd = build_cmd
        self.vessel_build_dir = build_dir

    _stage = None            # bound below
    _build_for_deploy = None  # bound below


def _runner(dial: str, tmp_path):
    from fls.orchestration.live import LiveRunner
    src = (tmp_path / "A.md")
    base = ANCHOR_MD.read_text()
    src.write_text(base.replace('"5a-staged":    { dial: propose-only', f'"5a-staged":    {{ dial: {dial}'))
    r = _Runner(Anchor.load(src), root=tmp_path)
    r._stage = LiveRunner._stage.__get__(r, _Runner)
    r._build_for_deploy = LiveRunner._build_for_deploy.__get__(r, _Runner)
    return r


def test_5a_stages_without_a_human_when_the_dial_permits(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_STAGE_DIR", str(tmp_path / "stage"))
    (tmp_path / "stage").mkdir()
    msg = _runner("auto-advance-with-audit", tmp_path)._stage("exp-7")
    assert "Staged for review" in msg, msg
    assert (tmp_path / "stage" / "stage" / "DEPLOYED").read_text().strip() == "exp-7"
    # The GUARANTEE, not its capitalisation: staging never implies prod.
    assert "prod still needs a human" in msg.lower()
    # ...and it says WHERE. "Staged for review on static-dir" sent a reviewer looking for
    # something to open, and static-dir deliberately writes a marker rather than a build.
    assert str(tmp_path / "stage") in msg, msg
    # ...and that it was a REF, not a site: this instance declares no build command, so a
    # reviewer must not be told there is a page to open.
    assert "ref only" in msg, msg


def test_5a_does_not_stage_when_the_dial_says_a_human_presses_it(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_STAGE_DIR", str(tmp_path / "stage"))
    (tmp_path / "stage").mkdir()
    msg = _runner("propose-only", tmp_path)._stage("exp-7")
    assert "Not staged" in msg and "propose-only" in msg
    assert not (tmp_path / "stage" / "stage").exists(), "nothing may be deployed"


def test_5a_refuses_with_a_reason_when_there_is_no_deploy_target(tmp_path):
    msg = _runner("auto-advance-with-audit", tmp_path)._stage("exp-7")
    assert "Not staged" in msg
    assert "no deploy target configured" in msg


def test_prod_still_refuses_without_an_approver(tmp_path):
    """The half that must NOT have moved."""
    fp = tmp_path / "flags.json"
    fp.write_text('{"f": {"stage": true, "prod": false}}')

    class _Ok:
        def deploy(self, env, ref): return True

    blocked = promote_to_prod("f", "HEAD", FlagStore(fp), _Ok(), approved_by=None)
    assert blocked.prod_deployed is False
    assert "requires a human reviewer" in blocked.reason
    import json
    assert json.loads(fp.read_text())["f"]["prod"] is False, "the prod flag must stay off"


def test_nothing_in_the_ship_path_merges():
    """The founder's rule is 'not ship to prod or merge without human'. `ship_to_stage`'s docstring
    claimed it merged until 2026-09-11; it never did. This pins the absence, because a docstring
    is not enforcement and the next person to read it should find a test instead."""
    import inspect

    from fls import climb, rung5
    for mod in (rung5, climb):
        src = inspect.getsource(mod)
        assert "git merge" not in src
        assert ".merge(" not in src


def test_setting_fls_repo_does_not_move_where_a_5a_build_lands(tmp_path, monkeypatch):
    """Regression, 2026-09-11. FLS_REPO and GITHUB_TOKEN are set because issues are expeditions
    and the token posts back — neither is a statement about deploying. Auto-select read them as
    one, so fixing the `sources` contradiction (set FLS_REPO) would have silently moved rung 5a
    off the operator's configured stage directory and onto GitHub Deployments."""
    monkeypatch.setenv("FLS_STAGE_DIR", str(tmp_path))
    assert modules._deploy_status()["kind"] == "static-dir"
    monkeypatch.setenv("FLS_REPO", "acme/app")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    assert modules._deploy_status()["kind"] == "static-dir", \
        "an explicit stage dir must outrank an incidental repo+token"


def test_repo_and_token_still_select_github_deployments_when_no_stage_dir(monkeypatch):
    monkeypatch.setenv("FLS_REPO", "acme/app")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    st = modules._deploy_status()
    assert st["kind"] == "github-environment"
    assert st["available"] is True


# ── publishing a real site, not a marker ────────────────────────────────────────────────────

def test_static_dir_publishes_a_built_directory_and_replaces_what_was_there(tmp_path):
    """Rung 5a published a seven-byte marker and called it "staged for review", which sent a
    reviewer looking for something to open. A stage worth a domain has to be the actual site."""
    import os

    from fls.modules import make_deployer
    base = tmp_path / "pub"
    base.mkdir()
    os.environ["FLS_STAGE_DIR"] = str(base)
    build = tmp_path / "out"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<h1>v1</h1>")
    (build / "assets" / "a.js").write_text("//v1")

    d = make_deployer("static-dir")
    assert d.deploy("stage", "exp-15", build) is True
    stage = base / "stage"
    assert (stage / "index.html").read_text() == "<h1>v1</h1>"
    assert (stage / "assets" / "a.js").exists()
    assert (stage / "DEPLOYED").read_text().strip() == "exp-15"

    # A second deploy REPLACES: a file the new build dropped must not survive as a ghost of the
    # last one. A stage showing a page the branch no longer has is its own falsehood.
    (build / "assets" / "a.js").unlink()
    (build / "index.html").write_text("<h1>v2</h1>")
    assert d.deploy("stage", "exp-16", build) is True
    assert (stage / "index.html").read_text() == "<h1>v2</h1>"
    assert not (stage / "assets" / "a.js").exists(), "a dropped file survived the redeploy"
    assert (stage / "DEPLOYED").read_text().strip() == "exp-16"

    # no artifact -> the mode this seam has always had: record the ref, publish nothing new
    assert d.deploy("prod", "exp-16") is True
    assert (base / "prod" / "DEPLOYED").read_text().strip() == "exp-16"


def test_prod_promotes_the_reviewed_artifact_and_never_rebuilds():
    """Rebuilding at promotion would publish bytes no human looked at: the branch may have moved
    and a dependency may have floated, so the thing signed off on stage would not be the thing
    that reached prod. "Promote" means move what was reviewed."""
    from fls.rung5 import FlagStore, promote_to_prod
    seen = []

    class Spy:
        def deploy(self, env, ref, artifact=None):
            seen.append((env, ref, artifact))
            return True

    import json
    import tempfile
    fp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump({"f": {"stage": True, "prod": False}}, fp)
    fp.close()

    r = promote_to_prod("f", "exp-15", FlagStore(fp.name), Spy(), None, "/published/stage")
    assert r.prod_deployed is False and seen == [], "prod deployed without an approver"

    r = promote_to_prod("f", "exp-15", FlagStore(fp.name), Spy(), "nate", "/published/stage")
    assert r.prod_deployed is True
    assert seen == [("prod", "exp-15", "/published/stage")], seen
    assert json.load(open(fp.name))["f"]["prod"] is True


def test_a_deployer_written_against_the_old_protocol_still_works():
    """`Deployer` is a published FLS_MODULES extension seam. One written against deploy(env, ref)
    must keep working after the artifact argument was added — in the mode it was written for."""
    from fls.rung5 import _deploy

    class OldStyle:
        def deploy(self, env, ref):
            return True

    assert _deploy(OldStyle(), "stage", "exp-1", None) is True

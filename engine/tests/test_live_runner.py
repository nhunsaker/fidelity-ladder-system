"""LiveRunner: real rung 2, honest refusal for rungs without a builder (Phase 1)."""
import json

import pytest

from fls.orchestration.activities import StubRunner
from fls.orchestration.live import LiveRunner
from fls.orchestration.types import RungRequest

GOOD = {"page_name": "exp-9", "page_id": "1:0",
        # Named for the candidate they are: the prefix is how a retry tells which frame is which
        # after the session that made them is gone.
        "candidates": [{"name": f"exp-9-c{i}", "node_id": f"1:{i}", "title": f"T{i}",
                        "premise": f"P{i}"} for i in (1, 2, 3)],
        # The fills the session read back off its own canvas. Grey, because "add a share-result
        # modal" names no colour and turns on no state — so this run is under the greyscale policy
        # and a coloured fill here would be a violation.
        "lint": {"auto_layout": True, "named_layers": True, "detached_instances": False,
                 "fills": {f"exp-9-c{i}": ["#F5F5F5", "#E0E0E0", "#212121"] for i in (1, 2, 3)}}}


class FakeSession:
    timeout_s = 600

    def __init__(self, text):
        self.text, self.timed_out_flag, self.tools = text, False, None

    def run(self, prompt, system=None):
        from fls.claude_code import SessionResult
        from fls.llm import Call
        return SessionResult(text=self.text, call=Call("claude-code", "m", 5, 5, usd=0.0,
                                                       normalized_usd=0.03,
                                                       funded_by="subscription"))


def _runner(tmp_path, text=None, **kw):
    text = text if text is not None else "```json\n" + json.dumps(GOOD) + "\n```"
    captured = {}

    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            captured["tools"] = tools
            captured["rung"] = rung
            captured["cwd"] = cwd_
            return FakeSession(text)
        return make
    r = LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, figma_file_key="KEY123",
                   session_factory_=factory, **kw)
    return r, captured


def _req(rung, **kw):
    return RungRequest(number=9, rung=rung, intent="add a share-result modal", **kw)


def test_rung2_runs_for_real_and_reports_cost(tmp_path):
    r, cap = _runner(tmp_path)
    out = r.wireframe(_req(2))
    assert out.passed and out.state == "await-pick" and out.rung == 2
    assert len(out.artifacts["wireframe"]) == 3
    assert out.artifacts["figma"]["page"] == "exp-9"
    assert out.normalized_usd == 0.03 and out.calls == 1
    assert cap["tools"][0] == "mcp__figma__use_figma" and cap["rung"] == 2
    saved = json.loads((tmp_path / "expeditions" / "9" / "wireframes" / "figma.json").read_text())
    assert len(saved["candidates"]) == 3


def test_the_ledger_call_travels_so_the_store_can_mirror_it(tmp_path):
    r, _ = _runner(tmp_path)
    out = r.wireframe(_req(2))
    assert out.artifacts["calls"][0]["funded_by"] == "subscription"


def test_a_bad_contract_parks_instead_of_passing(tmp_path):
    r, _ = _runner(tmp_path, text="I drew three wireframes, they look great.")
    out = r.wireframe(_req(2))
    assert not out.passed and out.state == "parked" and "no output contract" in out.detail


def test_missing_file_key_parks(tmp_path):
    r, _ = _runner(tmp_path)
    r.figma_file_key = ""
    out = r.wireframe(_req(2))
    assert not out.passed and "FLS_FIGMA_FILE_KEY" in out.detail


def test_rung2_not_live_falls_back_to_the_stub(tmp_path):
    r, _ = _runner(tmp_path, live_rungs=())
    out = r.wireframe(_req(2))
    assert out.passed and out.detail == "stub frames"


# Every rung now has a real builder; `_todo` remains for the next one that does not.


@pytest.mark.parametrize("rung,method", [(3, "prototype"), (4, "build"), (5, "ship")])
def test_rungs_not_yet_live_still_stub_through(tmp_path, rung, method):
    r, _ = _runner(tmp_path)   # only rung 2 live
    assert getattr(r, method)(_req(rung)).passed


# ── rung 3: the prototype, built from the committed pack ───────────────────────────────────

PACK = {
    "name": "Test System", "id": "TS-1.0",
    "tokens": {"color": {"room": {"felt": {"value": "#121110", "var": "--ns-felt",
                                           "role": "the ground"}}}},
    "components": [{"name": "Button", "class": "ns-btn", "role": "the action"}],
    "rules": ["one accented action per screen"],
}

PROTO_HTML = """<!doctype html><html lang="en"><head><style>
:root { --ns-felt: #121110; }
body { background: var(--ns-felt); }
</style></head><body><h1>Share</h1>
<button id="go" class="ns-btn">Share hand</button></body></html>"""


class WritingSession:
    """A session that writes its files, the way the real one does."""

    timeout_s = 900

    def __init__(self, files):
        self.files = files
        self.cwd = None

    def run(self, prompt, system=None):
        from pathlib import Path as _P

        from fls.claude_code import SessionResult
        from fls.llm import Call
        for name, body in self.files.items():
            _P(self.cwd).mkdir(parents=True, exist_ok=True)
            (_P(self.cwd) / name).write_text(body, encoding="utf-8")
        return SessionResult(text="wrote the screen",
                             call=Call("claude-code", "m", 5, 5, usd=0.0, normalized_usd=0.05,
                                       funded_by="subscription"))


def _proto_runner(tmp_path, files=None, pack=True, **kw):
    files = PROTO_HTML if files is None else files
    payload = {"index.html": files,
               "walkthrough.json": json.dumps(
                   {"steps": [{"action": "click", "selector": "#go", "expect": "it shares"}]})}
    captured = {}

    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            captured["tools"] = tools
            captured["rung"] = rung
            s = WritingSession(payload)
            s.cwd = cwd_
            return s
        return make

    pack_path = ""
    if pack:
        pack_path = str(tmp_path / "pack.json")
        (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    return LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(3,),
                      session_factory_=factory, design_pack=pack_path, **kw), captured


def test_rung3_builds_the_prototype_where_preview_serves_it(tmp_path):
    r, cap = _proto_runner(tmp_path)
    out = r.prototype(_req(3, spec="a share sheet"))
    assert out.passed, out.detail
    assert out.state == "await-approve" and out.rung == 3
    assert out.normalized_usd == 0.05 and out.calls == 1
    assert cap["tools"] == ("Write", "Read", "Edit") and cap["rung"] == 3
    # GET /preview/9 serves exactly this path
    assert (tmp_path / "expeditions" / "9" / "demo" / "index.html").exists()
    assert out.artifacts["prototype"]["components_used"] == ["ns-btn"]


def test_rung3_without_a_pack_parks_and_says_which_variable(tmp_path):
    r, _ = _proto_runner(tmp_path, pack=False)
    out = r.prototype(_req(3))
    assert not out.passed and out.state == "parked" and "FLS_DESIGN_PACK" in out.detail


def test_rung3_with_a_missing_pack_file_parks(tmp_path):
    r, _ = _proto_runner(tmp_path)
    r.design_pack = str(tmp_path / "nope.json")
    out = r.prototype(_req(3))
    assert not out.passed and "not found" in out.detail


def test_rung3_parks_when_the_page_ignores_the_design_system(tmp_path):
    r, _ = _proto_runner(tmp_path, files="""<!doctype html><html lang="en"><body><h1>x</h1>
    <button id="go" style="background:#121110">go</button></body></html>""")
    out = r.prototype(_req(3))
    assert not out.passed and out.state == "parked"
    assert "hardcoded" in out.detail or "no design token" in out.detail


def test_rung3_feeds_the_picked_wireframe_into_the_build(tmp_path):
    # rung 2's artifact is where the human's choice lives; rung 3 must build THAT one.
    d = tmp_path / "expeditions" / "9" / "wireframes"
    d.mkdir(parents=True)
    (d / "figma.json").write_text(json.dumps({"page_name": "Expedition 9", "candidates": [
        {"name": "candidate-1", "premise": "stacked"},
        {"name": "candidate-2", "premise": "side by side"}]}), encoding="utf-8")
    captured_prompt = {}

    class Recording(WritingSession):
        def run(self, prompt, system=None):
            captured_prompt["p"] = prompt
            return super().run(prompt, system)

    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            s = Recording({"index.html": PROTO_HTML, "walkthrough.json": json.dumps(
                {"steps": [{"action": "click", "selector": "#go", "expect": "x"}]})})
            s.cwd = cwd_
            return s
        return make

    (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    r = LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(3,),
                   session_factory_=factory, design_pack=str(tmp_path / "pack.json"))
    r.prototype(_req(3, picked=2))
    assert "candidate-2" in captured_prompt["p"] and "side by side" in captured_prompt["p"]


# ── rung 4: the feature, built in a worktree of the real vessel ────────────────────────────

def _vessel(tmp_path):
    """A real checkout for the build rung to branch from."""
    import subprocess
    r = tmp_path / "vessel"
    r.mkdir()
    for args in (("git", "init", "-b", "main"), ("git", "config", "user.email", "t@example.invalid"),
                 ("git", "config", "user.name", "T")):
        subprocess.run(args, cwd=r, capture_output=True, check=True)
    (r / "README.md").write_text("# vessel\n", encoding="utf-8")
    subprocess.run(("git", "add", "-A"), cwd=r, capture_output=True, check=True)
    subprocess.run(("git", "commit", "-m", "init"), cwd=r, capture_output=True, check=True)
    return r


def _build_runner(tmp_path, files=None, test_cmd="true", repo=None, **kw):
    files = {"feature.txt": "new\n"} if files is None else files

    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            s = WritingSession(files)
            s.cwd = cwd_
            return s
        return make

    (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    return LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(4,),
                      session_factory_=factory, design_pack=str(tmp_path / "pack.json"),
                      vessel_repo=str(repo) if repo else "",
                      vessel_test_cmd=test_cmd, **kw)


def test_rung4_builds_in_a_worktree_and_reports_the_diff(tmp_path):
    r = _build_runner(tmp_path, repo=_vessel(tmp_path))
    out = r.build(_req(4, spec="add a share control"))
    assert out.passed, out.detail
    assert out.state == "await-approve" and out.rung == 4
    b = out.artifacts["build"]
    assert b["branch"] == "exp-9" and b["test_passed"] is True
    assert "feature.txt" in b["files_changed"] and "+new" in b["diff"]
    assert out.normalized_usd == 0.05


def test_rung4_without_a_vessel_checkout_parks(tmp_path):
    r = _build_runner(tmp_path)
    out = r.build(_req(4))
    assert not out.passed and "FLS_VESSEL_REPO" in out.detail


def test_rung4_pointed_at_a_non_repo_parks(tmp_path):
    (tmp_path / "notarepo").mkdir()
    r = _build_runner(tmp_path, repo=tmp_path / "notarepo")
    out = r.build(_req(4))
    assert not out.passed and "not a git checkout" in out.detail


def test_rung4_without_a_check_refuses_rather_than_verifying_nothing(tmp_path):
    r = _build_runner(tmp_path, repo=_vessel(tmp_path), test_cmd="")
    out = r.build(_req(4))
    assert not out.passed and "FLS_VESSEL_TEST_CMD" in out.detail


def test_rung4_parks_when_the_vessels_own_check_fails(tmp_path):
    r = _build_runner(tmp_path, repo=_vessel(tmp_path), test_cmd="false")
    out = r.build(_req(4))
    assert not out.passed and out.state == "parked" and "not green" in out.detail


# ── rung 5: the branch becomes a draft pull request ────────────────────────────────────────

def _ship_runner(tmp_path, live_rungs=(5,), **kw):
    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            raise AssertionError("rung 5 must not start a session — it ships what rung 4 built")
        return make
    return LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=live_rungs,
                      session_factory_=factory, **kw)


def test_rung5_without_a_rung4_build_parks(tmp_path):
    out = _ship_runner(tmp_path).ship(_req(5))
    assert not out.passed and out.state == "parked" and "nothing was built" in out.detail


def test_rung5_refuses_to_ship_a_red_build(tmp_path):
    art = tmp_path / "expeditions" / "9" / "mvp"
    (art / "wt").mkdir(parents=True)
    (art / "summary.json").write_text(json.dumps({"branch": "exp-9", "test_passed": False}),
                                      encoding="utf-8")
    out = _ship_runner(tmp_path).ship(_req(5))
    assert not out.passed and "not green" in out.detail


def test_rung5_stubs_through_when_not_live(tmp_path):
    out = _ship_runner(tmp_path, live_rungs=()).ship(_req(5))
    assert out.rung == 5 and out.passed


# ── every long rung leaves a transcript, because a dead rung is asked what it was doing ──

def _capturing_factory(sessions, payload):
    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            s = WritingSession(payload)
            s.cwd = cwd_
            sessions.append(s)
            return s
        return make
    return factory


def test_rung3_streams_its_session_to_disk_like_the_wireframe_rung_does(tmp_path):
    """A preview that dies used to leave nothing at all: the rung buffered, so the transcript
    lived in a pipe inside a process that no longer existed."""
    sessions = []
    payload = {"index.html": PROTO_HTML,
               "walkthrough.json": json.dumps(
                   {"steps": [{"action": "click", "selector": "#go", "expect": "x"}]})}
    (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    r = LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(3,),
                   session_factory_=_capturing_factory(sessions, payload),
                   design_pack=str(tmp_path / "pack.json"))
    r.prototype(_req(3, spec="a share sheet"))

    log = tmp_path / "expeditions" / "9" / "demo" / "session-1.log"
    assert sessions and sessions[0].log_path == str(log)


def test_rung4_streams_its_session_to_disk_because_it_is_the_longest_one(tmp_path):
    """Twenty minutes is a normal build. It was the only rung that buffered, so a build killed
    mid-flight left a stack trace and no record of the work — the most expensive thing to lose."""
    sessions = []

    def factory(anchor, rung, cwd=None, guard=None):
        def make(tools=(), cwd_=None):
            s = WritingSession({"feature.txt": "new\n"})
            s.cwd = cwd_
            sessions.append(s)
            return s
        return make

    (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    r = LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(4,),
                   session_factory_=factory, design_pack=str(tmp_path / "pack.json"),
                   vessel_repo=str(_vessel(tmp_path)), vessel_test_cmd="true")
    r.build(_req(4, spec="add a share control"))

    log = tmp_path / "expeditions" / "9" / "mvp" / "session-1.log"
    assert sessions and sessions[0].log_path == str(log)


def test_a_second_attempt_does_not_overwrite_the_first_ones_transcript(tmp_path):
    """`_next_log` names by what is on disk, not by the workflow's attempt counter — Temporal
    retries inside one activity call, so that counter stays 1 while the work runs again."""
    sessions = []
    payload = {"index.html": PROTO_HTML,
               "walkthrough.json": json.dumps(
                   {"steps": [{"action": "click", "selector": "#go", "expect": "x"}]})}
    (tmp_path / "pack.json").write_text(json.dumps(PACK), encoding="utf-8")
    r = LiveRunner(anchor=None, stub=StubRunner(), root=tmp_path, live_rungs=(3,),
                   session_factory_=_capturing_factory(sessions, payload),
                   design_pack=str(tmp_path / "pack.json"))
    d = tmp_path / "expeditions" / "9" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "session-1.log").write_text("the first attempt\n", encoding="utf-8")
    r.prototype(_req(3, spec="a share sheet"))

    assert sessions[0].log_path == str(d / "session-2.log")
    assert (d / "session-1.log").read_text() == "the first attempt\n"

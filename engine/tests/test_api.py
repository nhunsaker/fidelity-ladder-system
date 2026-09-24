"""P5: the harness API (FastAPI TestClient, stubbed judge, zero spend)."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.expedition import AWAIT_PICK, Expedition
from fls.llm import Call
from fls.store import ExpeditionStore


class StubJudge:
    def complete(self, prompt, max_tokens=1024, system=None):
        return json.dumps({"verdict": "admit", "reasoning": "traces to north star"}), \
            Call("stub", "stub", 10, 5, 0.0)


def _client(tmp_path):
    store = ExpeditionStore(tmp_path)
    # seed one expedition + a ledger row
    e = Expedition(101, Idea(101, "cmd-k search", "cmd-k focuses search", "feature"),
                   target_rung=2, rung=2, status=AWAIT_PICK, reason="wireframe pick pending")
    store.save(e)
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    appmod.deps.judge = StubJudge()
    return TestClient(appmod.app)


def test_health_and_anchor(tmp_path):
    c = _client(tmp_path)
    assert c.get("/health").json()["status"] == "ok"
    a = c.get("/anchor").json()
    assert a["funnel"]["auto_build"] == 1
    assert "feature" in a["altitude_allowed"]
    # V3-B2 additive fields: version (Constitution) + vessels/default_vessel (Vessels screen)
    assert a["version"] == 1
    assert a["default_vessel"] == "acme-demo"
    assert any(v["name"] == "acme-demo" and v["kind"] == "app" for v in a["vessels"])


def test_wall_and_expedition(tmp_path):
    c = _client(tmp_path)
    wall = c.get("/wall").json()
    assert len(wall) == 1 and wall[0]["number"] == 101
    assert wall[0]["rung"] == "2-wireframe"
    detail = c.get("/expeditions/101").json()
    assert detail["intent"] == "cmd-k search"
    assert "artifacts" in detail
    assert c.get("/expeditions/999").status_code == 404


def test_file_idea_runs_admission(tmp_path):
    c = _client(tmp_path)
    r = c.post("/ideas", json={"number": 202, "intent": "keyboard nav", "success": "works",
                               "altitude": "feature"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "admit"
    # the admission decision was logged to the ledger
    assert c.get("/calibration").json()["total_decisions"] >= 1


def test_calibration_and_lessons(tmp_path):
    c = _client(tmp_path)
    (Path(tmp_path) / "LESSONS.md").write_text("# LESSONS\n\n- (exp #1) make criteria checkable\n")
    assert c.get("/lessons").json() == ["(exp #1) make criteria checkable"]
    cal = c.get("/calibration").json()
    assert "rungs" in cal and "disagreement_categories" in cal


# ── V4: GET /snapshot — server-side read-union (no RAG shaping) ───────────────
def test_snapshot_is_the_union_admin_loadall_composites(tmp_path):
    c = _client(tmp_path)
    (Path(tmp_path) / "LESSONS.md").write_text("# LESSONS\n\n- (exp #1) make criteria checkable\n")
    snap = c.get("/snapshot").json()
    assert set(snap) >= {"wall", "lessons", "calibration", "anchor", "system", "prose", "goal"}
    # each slice matches its standalone endpoint
    assert snap["wall"] == c.get("/wall").json()
    assert snap["lessons"] == c.get("/lessons").json()
    assert snap["anchor"] == c.get("/anchor").json()
    assert snap["system"] == c.get("/system").json()
    cal = c.get("/calibration").json()
    assert snap["calibration"]["total_decisions"] == cal["total_decisions"]
    assert snap["calibration"]["disagreement_categories"] == cal["disagreement_categories"]


def test_snapshot_exposes_prose_and_goal(tmp_path):
    c = _client(tmp_path)
    snap = c.get("/snapshot").json()
    # prose = the human header (north star + non-negotiables) preceding the machine block
    assert isinstance(snap["prose"], str) and len(snap["prose"]) > 0
    assert "```anchor" not in snap["prose"]
    # the fixture ANCHOR.md carries no `goal:` today -> back-compat, resolves to None
    assert snap["goal"] is None


def test_snapshot_never_leaks_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "SENTINEL_webhook_secret")
    monkeypatch.setenv("GITHUB_TOKEN", "SENTINEL_github_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "SENTINEL_anthropic_key")
    monkeypatch.setenv("FLS_SKILL_SERVER_KEY", "SENTINEL_skill_key")
    c = _client(tmp_path)
    blob = json.dumps(c.get("/snapshot").json())
    for sentinel in ("SENTINEL_webhook_secret", "SENTINEL_github_token",
                     "SENTINEL_anthropic_key", "SENTINEL_skill_key"):
        assert sentinel not in blob


# ── what a surface reports about spend and about the GitHub surface ────────────────────────

def test_an_expedition_reports_list_price_as_well_as_metered_spend(tmp_path):
    """The subscription lane meters $0. A record that carries only `spent` makes every run look
    free, which is why the admin showed $0.00 for a $5 build."""
    from fls.adjudicator import Idea
    from fls.expedition import CLIMBING, Expedition
    from fls.llm import Call
    from fls.store import ExpeditionStore
    store = ExpeditionStore(tmp_path)
    e = Expedition(77, Idea(77, "a feature", "shipped", "feature"), 4, rung=4, status=CLIMBING)
    e.add([Call("claude-code", "m", 10, 5, usd=0.0, normalized_usd=5.1,
                funded_by="subscription")])
    store.save(e)
    rec = store.get(77)
    assert rec["spent"] == 0.0
    assert rec["normalized_usd"] == 5.1


def test_the_thread_names_which_half_of_the_github_surface_is_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fls import app as appmod
    from fls.adjudicator import Idea
    from fls.expedition import CLIMBING, Expedition
    from fls.store import ExpeditionStore
    store = ExpeditionStore(tmp_path)
    store.save(Expedition(78, Idea(78, "x", "y", "feature"), 2, rung=2, status=CLIMBING))
    appmod.deps.root = tmp_path
    appmod.deps._store = store
    appmod.deps.github = None
    c = TestClient(appmod.app)

    # a token but no repo — the instance this was written for. Saying "no token" would be false.
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_x")
    monkeypatch.setattr("fls.github_surface.REPO", "", raising=False)
    body = c.get("/expeditions/78/thread").json()
    assert body["available"] is False
    assert "FLS_REPO" in body["reason"] and "GITHUB_TOKEN" not in body["reason"]

    # neither: both are named
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    body = c.get("/expeditions/78/thread").json()
    assert "GITHUB_TOKEN" in body["reason"] and "FLS_REPO" in body["reason"]


def test_the_api_reads_the_instance_anchor_not_the_engines(tmp_path, monkeypatch):
    """The worker honoured FLS_ANCHOR_PATH and the API did not, so a real deployment judged every
    admission against the ANCHOR shipped with the engine while climbing against the operator's.
    Found live: GET /anchor reported the example vessel `acme-demo` on an instance whose own
    ANCHOR names a different one."""
    import importlib

    other = tmp_path / "instance-ANCHOR.md"
    other.write_text("# instance\n", encoding="utf-8")
    monkeypatch.setenv("FLS_ANCHOR_PATH", str(other))
    import fls.app as appmod
    reloaded = importlib.reload(appmod)
    assert reloaded.ANCHOR_PATH == other

    monkeypatch.delenv("FLS_ANCHOR_PATH", raising=False)
    back = importlib.reload(appmod)
    assert back.ANCHOR_PATH.name == "ANCHOR.md"
    assert "instance-ANCHOR" not in str(back.ANCHOR_PATH)

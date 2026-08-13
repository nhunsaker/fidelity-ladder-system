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

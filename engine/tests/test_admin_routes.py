"""V2-P3 — the admin's write routes: kill switch, anchor validate/propose, feeder run.
All stubbed ($0)."""
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.anchor import apply_anchor_edits
from fls.expedition import CLIMBING, Expedition
from fls.store import ExpeditionStore

ANCHOR_TEXT = (Path(__file__).resolve().parents[2] / "ANCHOR.md").read_text()


def _client(tmp_path, seed=True):
    store = ExpeditionStore(tmp_path)
    if seed:
        store.save(Expedition(101, Idea(101, "cmd-k", "focus", "feature"), 2, rung=2,
                              status=CLIMBING))
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return TestClient(appmod.app)


# ── kill switch ────────────────────────────────────────────────────────────────
def test_kill_requires_named_actor(tmp_path):
    c = _client(tmp_path)
    r = c.post("/expeditions/101/kill", json={"reason": "nope"})
    assert r.status_code == 400                      # fail-closed: no name, no kill
    assert appmod.deps.store.get(101)["status"] == "climbing"


def test_kill_parks_and_ledgers(tmp_path):
    c = _client(tmp_path)
    r = c.post("/expeditions/101/kill", json={"actor": "nathan", "reason": "wrong direction"})
    assert r.status_code == 200
    rec = appmod.deps.store.get(101)
    assert rec["status"] == "parked"
    assert "killed by nathan" in rec["reason"]
    led = appmod.deps.store.ledger()
    assert any(d.human_verdict == "kill:nathan" for d in led.rows)


def test_kill_404_unknown(tmp_path):
    c = _client(tmp_path, seed=False)
    assert c.post("/expeditions/999/kill", json={"actor": "n"}).status_code == 404


# ── anchor edits ───────────────────────────────────────────────────────────────
def test_apply_anchor_edits_roundtrip():
    new_text, anchor = apply_anchor_edits(ANCHOR_TEXT, "funnel", {"interactive_demos": "4"})
    assert anchor.funnel.interactive_demos == 4
    assert "interactive_demos: 4" in new_text
    # the prose header is untouched
    assert new_text.split("```anchor")[0] == ANCHOR_TEXT.split("```anchor")[0]


def test_apply_anchor_edits_rejects_invalid_section():
    try:
        apply_anchor_edits(ANCHOR_TEXT, "rungs", {"x": 1})
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "not console-editable" in str(e)


def test_anchor_validate_route(tmp_path):
    c = _client(tmp_path)
    ok = c.post("/anchor/validate", json={"section": "budgets",
                                          "edits": {"per_expedition_ceiling_usd": "6"}})
    assert ok.json()["valid"] is True
    bad = c.post("/anchor/validate", json={"section": "budgets",
                                           "edits": {"per_expedition_ceiling_usd": "banana"}})
    assert bad.json()["valid"] is False and bad.json()["errors"]


def test_anchor_propose_without_token_is_simulated(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    c = _client(tmp_path)
    r = c.post("/anchor/propose", json={"section": "funnel", "edits": {"queue": "1"}})
    d = r.json()
    assert d["simulated"] is True and "nothing pushed" in d["note"]  # honest, not pretended


# ── feeder run ─────────────────────────────────────────────────────────────────
def test_feeder_run_fails_closed_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("FLS_SKILL_SERVER_KEY", raising=False)
    monkeypatch.setattr("fls.llm._keychain", lambda s: None)
    c = _client(tmp_path)
    d = c.post("/feeder/run", json={"scope": "x"}).json()
    assert d["triggered"] is False and "fail-closed" in d["reason"]

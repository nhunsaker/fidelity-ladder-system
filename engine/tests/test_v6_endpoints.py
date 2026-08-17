"""FLS v0.6 — the two integrate-time endpoints wiring the admin lanes:
GET /mining-history (#7 → earning-history UI) and POST /panels/propose (#5 panel-authoring).
Both $0 / read-or-validate only; /panels/propose is proposal-only (never mutates ANCHOR)."""
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.expedition import CLIMBING, Expedition
from fls.store import ExpeditionStore


def _client(tmp_path):
    store = ExpeditionStore(tmp_path)
    store.save(Expedition(101, Idea(101, "cmd-k", "focus", "feature"), 2, rung=2, status=CLIMBING))
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return TestClient(appmod.app)


def test_mining_history_returns_snapshot_list(tmp_path):
    c = _client(tmp_path)
    r = c.get("/mining-history")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # empty history -> one fresh snapshot from the current ledger (frozen MiningReport shape)
    assert len(data) >= 1
    snap = data[0]
    assert set(("computed_at", "per_rung", "mismatches", "recommendation")) <= set(snap)
    assert isinstance(snap["per_rung"], list)


def test_mining_history_persists_a_snapshot_under_instance_root(tmp_path):
    # v0.7 #2 — the read path now drives the persistence cadence: a hit with no prior history
    # mines+persists a real snapshot into <instance root>/mining-history.jsonl (not the cwd).
    c = _client(tmp_path)
    assert not (tmp_path / "mining-history.jsonl").exists()
    c.get("/mining-history")
    assert (tmp_path / "mining-history.jsonl").exists()
    from fls.mining import read_history
    assert len(read_history(tmp_path / "mining-history.jsonl")) == 1


def test_mining_history_cadence_guard_skips_within_min_interval(tmp_path):
    c = _client(tmp_path)
    c.get("/mining-history")
    c.get("/mining-history")
    c.get("/mining-history")
    from fls.mining import read_history
    # three hits in immediate succession accrue exactly one snapshot (min-interval guard)
    assert len(read_history(tmp_path / "mining-history.jsonl")) == 1


def test_mining_history_vessel_query_returns_live_slice(tmp_path):
    c = _client(tmp_path)
    r = c.get("/mining-history?vessel=woords")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1  # a single live snapshot, not the persisted history array
    # a vessel-filtered read must not perturb the anchor-level persistence cadence
    assert not (tmp_path / "mining-history.jsonl").exists()


def test_panels_propose_valid_registry_name(tmp_path):
    c = _client(tmp_path)
    r = c.post("/panels/propose", json={"panel": "default", "target_vessel": "checkout"})
    assert r.status_code == 200
    b = r.json()
    assert b["valid"] is True and b["errors"] == []
    assert b["proposed_change"] == {"panel": "default", "target_vessel": "checkout"}


def test_panels_propose_valid_persona_list(tmp_path):
    c = _client(tmp_path)
    r = c.post("/panels/propose", json={"panel": ["p-flow", "p-perf"]})
    assert r.json()["valid"] is True


def test_panels_propose_rejects_dupes_and_empty(tmp_path):
    c = _client(tmp_path)
    assert c.post("/panels/propose", json={"panel": ["a", "a"]}).json()["valid"] is False
    assert c.post("/panels/propose", json={"panel": ""}).json()["valid"] is False
    assert c.post("/panels/propose", json={"panel": 42}).json()["valid"] is False
    # invalid never returns a proposed_change (proposal-only, fail-closed)
    assert c.post("/panels/propose", json={"panel": ["a", "a"]}).json()["proposed_change"] is None

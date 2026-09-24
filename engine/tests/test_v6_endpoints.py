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


# ── the feeder tells the truth (audit B2 + B3) ────────────────────────────────
def test_anchor_exposes_the_instance_s_own_feeder_params(tmp_path):
    """B2: the admin hardcoded {volume_cap 5, envelope $5, context 30k} while labelling them
    "All from the ANCHOR's feeder block". The screen can only be honest if the route carries the
    real thing — so this asserts a CHANGED anchor moves the payload, not that a default matches."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from fls import app as appmod
    src = Path(appmod.ANCHOR_PATH).read_text()
    assert "volume_cap: 5" in src, "fixture anchor changed; update this test's edit"
    edited = src.replace("volume_cap: 5", "volume_cap: 9")
    target = tmp_path / "ANCHOR.md"
    target.write_text(edited)
    old = appmod.ANCHOR_PATH
    try:
        appmod.ANCHOR_PATH = target
        body = TestClient(appmod.app).get("/anchor").json()
        assert "feeder" in body, "the Feeder screen has nothing to read"
        assert body["feeder"]["volume_cap"] == 9, "the route is not reading this instance's ANCHOR"
        # and /snapshot must carry the identical slice — the two drifted the moment one changed
        assert TestClient(appmod.app).get("/snapshot").json()["anchor"] == body
    finally:
        appmod.ANCHOR_PATH = old


def test_anchor_says_whether_the_feeder_numbers_are_the_instance_s_or_the_engine_s(tmp_path):
    """`declared` alone cannot answer the question the screen asks. An ANCHOR may declare the
    feeder source and set no `params:`, in which case every number is a library default — and a
    card captioned "from your ANCHOR" over library defaults is the same lie B2 was about, just
    one level up. `params_set` is the field that distinguishes them, so both states are pinned."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from fls import app as appmod
    src = Path(appmod.ANCHOR_PATH).read_text()
    old = appmod.ANCHOR_PATH

    def feeder_block(text: str) -> dict:
        target = tmp_path / "ANCHOR.md"
        target.write_text(text)
        appmod.ANCHOR_PATH = target
        return TestClient(appmod.app).get("/anchor").json()["feeder"]

    try:
        # the fixture declares a feeder source WITH params
        f = feeder_block(src)
        assert f["declared"] is True
        assert f["params_set"] is True

        # a feeder source declared with no params: still declared, but the numbers are defaults
        assert "- kind: feeder" in src, "fixture anchor changed; update this test's edit"
        head, _, _ = src.partition("- kind: feeder")
        bare = head + "- kind: feeder\nfunnel:" + src.partition("\nfunnel:")[2]
        f = feeder_block(bare)
        assert f["declared"] is True, "the source is declared; only its params are absent"
        assert f["params_set"] is False, "no params: block, so these numbers are the engine's"
        assert f["volume_cap"] == 5, "with no params the engine's own default is what is served"

        # no feeder source at all
        f = feeder_block(src.replace("- kind: feeder", "- kind: nothing-here"))
        assert f["declared"] is False
        assert f["params_set"] is False
    finally:
        appmod.ANCHOR_PATH = old


def test_a_dry_run_names_itself_and_files_nothing(tmp_path, monkeypatch):
    """B3: /feeder/run called run_feeder(..., ListSink()) — whose own docstring says "for tests /
    dry runs" — and the UI reported "N filed". Both paths were dry and neither said so."""
    from fastapi.testclient import TestClient

    from fls import app as appmod
    from fls import feeder as feedermod
    from fls.feeder import Candidate, FeederRun

    class _Brainstorm:
        def available(self): return True

    def _fake_run(anchor, anchor_text, brainstorm, sink, **kw):
        for c in [Candidate("a", "s"), Candidate("b", "s")]:
            sink.file(c, "studio-brainstorm")
        return FeederRun(candidates=[], filed=list(sink.filed), calls=[], proposed=2,
                         capped_to=2, within_envelope=True)

    monkeypatch.setattr("fls.llm.make_builder", lambda *a, **kw: _Brainstorm())
    monkeypatch.setattr(feedermod, "run_feeder", _fake_run)
    c = TestClient(appmod.app)
    r = c.post("/feeder/run", json={"dry_run": True}).json()
    assert r["sink"] == "dry-run", r
    assert r["dry_run"] is True


def test_a_real_run_without_a_judge_refuses_rather_than_dry_running(tmp_path, monkeypatch):
    """A feeder that files past an absent gate is the backdoor the one-door rule exists to stop.
    It must refuse with a reason, never quietly fall back to the in-memory sink."""
    from fastapi.testclient import TestClient

    from fls import app as appmod

    class _Brainstorm:
        def available(self): return True

    monkeypatch.setattr("fls.llm.make_builder", lambda *a, **kw: _Brainstorm())
    old = appmod.deps.judge
    try:
        appmod.deps.judge = None
        r = TestClient(appmod.app).post("/feeder/run", json={"dry_run": False}).json()
        assert r["triggered"] is False
        assert "gate" in r["reason"]
        assert r["sink"] is None
    finally:
        appmod.deps.judge = old


def test_feeder_run_defaults_to_dry(monkeypatch):
    """Back-compat: every caller written before `dry_run` existed keeps the safe behaviour."""
    from fastapi.testclient import TestClient

    from fls import app as appmod

    class _Unavailable:
        def available(self): return False

    monkeypatch.setattr("fls.llm.make_builder", lambda *a, **kw: _Unavailable())
    r = TestClient(appmod.app).post("/feeder/run", json={}).json()
    assert r["triggered"] is False          # unchanged shape for the unavailable path
    assert "sink" in r


def test_the_admission_sink_files_through_the_real_gate():
    """The sink that was promised in IdeaSink's docstring and never written. It must call the
    SAME admission path a human filing hits — a parallel door that merely looks similar is the
    thing the one-door rule forbids."""
    from fls.feeder import AdmissionSink, Candidate
    seen = []

    async def _admit(idea):
        seen.append(idea)
        return {"verdict": "admit", "number": idea.number}

    sink = AdmissionSink(admit=_admit, next_number=lambda: 42)
    ref = sink.file(Candidate("add a share modal", "it opens"), "studio-brainstorm")
    assert ref == 42
    assert sink.name == "admission"
    assert len(seen) == 1
    assert seen[0].intent == "add a share modal"
    assert seen[0].source == "studio-brainstorm"      # provenance survives the door
    assert len(sink.filed) == 1


def test_anchor_says_whether_a_feeder_is_actually_declared(tmp_path):
    """`a.feeder()` returns FeederParams defaults when no feeder source is declared, so the block
    alone cannot tell an operator whether they are looking at their settings or the library's.
    A screen that showed defaults as "what governs this run" would restate B2 in a new form."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from fls import app as appmod
    src = Path(appmod.ANCHOR_PATH).read_text()
    body = TestClient(appmod.app).get("/anchor").json()
    declared_in_file = "kind: feeder" in src
    assert body["feeder"]["declared"] is declared_in_file

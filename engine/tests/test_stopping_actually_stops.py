"""Stop has to stop the run, not just the label on the screen.

Two independent bugs made the most consequential button on the surface a no-op, and either one
alone was enough to produce the same symptom — so they get a test each rather than one end-to-end
test that would go green the moment either was fixed.

  1. `_park_expedition` marked the store `parked` and never signalled the workflow. The run kept
     climbing and kept spending — the money the button exists to stop.
  2. The worker's state mirror wrote the workflow's own `climbing` back over the park at the next
     rung transition, so even the label did not survive.

The third claim here is about honesty rather than mechanism: when the signal cannot be delivered,
the caller is TOLD, because a Stop reported as successful that never reached the run is exactly
the falsehood this system exists to refuse.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.expedition import CLIMBING, PARKED, Expedition
from fls.store import ExpeditionStore

PASS = "open-sesame"


def _client(tmp_path, seed=None):
    store = ExpeditionStore(tmp_path)
    for e in seed or []:
        store.save(e)
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return TestClient(appmod.app)


def _exp(number=1, status=CLIMBING, rung=2):
    return Expedition(number, Idea(number, "a share sheet", "shared", "feature",
                                   source="demo:nate"), 4, rung=rung, status=status)


class _Orch:
    """Stands in for the durable-scheduler client: records signals, or refuses them."""

    def __init__(self, on=True, boom=None):
        self.on, self.boom, self.sent = on, boom, []

    def enabled(self):
        return self.on

    async def signal(self, number, name, payload=None, settings=None):
        if self.boom:
            raise RuntimeError(self.boom)
        self.sent.append((number, name, payload))


def _stop(c, tok, number=7, body="/kill changed my mind"):
    return c.post(f"/demo/expeditions/{number}/feedback", json={"body": body},
                  headers={"x-demo-token": tok})


def _logged_in(tmp_path, monkeypatch, seed):
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed)
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    return c, tok


# ── 1 · the signal reaches the run ─────────────────────────────────────────────────────────

def test_stopping_signals_the_run_and_not_only_the_store(tmp_path, monkeypatch):
    """THE BUG. Parking wrote a label; the run never heard about it. A visitor watching the
    screen saw "stopped" over a climb that went on for another rung and another few dollars."""
    orch = _Orch()
    monkeypatch.setattr("fls.orchestration.client.enabled", orch.enabled)
    monkeypatch.setattr("fls.orchestration.client.signal", orch.signal)
    c, tok = _logged_in(tmp_path, monkeypatch, [_exp(7)])

    r = _stop(c, tok)
    assert r.status_code == 200, r.text
    assert orch.sent == [(7, "kill", "changed my mind")], "the run was never told to stop"
    assert r.json()["signalled"] is True
    assert appmod.deps.store.get(7)["status"] == PARKED


def test_a_signal_that_cannot_be_delivered_is_reported_not_swallowed(tmp_path, monkeypatch):
    """The store change is durable and must land even when the scheduler is unreachable — but
    the caller has to know the run may still be climbing. "Stopped" over a run that never got
    the message is the one answer this system may not give."""
    orch = _Orch(boom="connection refused")
    monkeypatch.setattr("fls.orchestration.client.enabled", orch.enabled)
    monkeypatch.setattr("fls.orchestration.client.signal", orch.signal)
    c, tok = _logged_in(tmp_path, monkeypatch, [_exp(7)])

    body = _stop(c, tok).json()
    assert body["status"] == "parked", "the human decision must survive a scheduler outage"
    assert body["signalled"] is False
    assert "connection refused" in body["signal_detail"]


def test_with_no_scheduler_wired_the_store_is_said_to_be_the_whole_state(tmp_path, monkeypatch):
    """An install with no durable runs behind it still stops expeditions. `signalled: false`
    there means "there was nothing to signal", and saying which keeps it from reading as a
    failure."""
    orch = _Orch(on=False)
    monkeypatch.setattr("fls.orchestration.client.enabled", orch.enabled)
    monkeypatch.setattr("fls.orchestration.client.signal", orch.signal)
    c, tok = _logged_in(tmp_path, monkeypatch, [_exp(7)])

    body = _stop(c, tok).json()
    assert body["status"] == "parked" and body["signalled"] is False
    assert "no durable run" in body["signal_detail"]
    assert orch.sent == []


def test_the_operator_kill_switch_signals_the_run_too(tmp_path, monkeypatch):
    """Both doors reach the same function, and an operator stopping a run has exactly the same
    expectation a visitor does."""
    orch = _Orch()
    monkeypatch.setattr("fls.orchestration.client.enabled", orch.enabled)
    monkeypatch.setattr("fls.orchestration.client.signal", orch.signal)
    c = _client(tmp_path, [_exp(7)])

    r = c.post("/v1/operator/runs/7/kill", json={"actor": "nate", "reason": "wrong idea"})
    assert r.status_code == 200, r.text
    assert orch.sent == [(7, "kill", "wrong idea")]


# ── 2 · the park survives the mirror ───────────────────────────────────────────────────────

def _mirror(tmp_path, monkeypatch, seed):
    """The worker's real state mirror, built against a real store at FLS_ROOT."""
    from fls.worker import _store_recorder
    store = ExpeditionStore(tmp_path)
    for e in seed:
        store.save(e)
    monkeypatch.setenv("FLS_ROOT", str(tmp_path))
    return _store_recorder(), store


def test_a_parked_run_is_not_put_back_on_the_ladder_by_its_own_mirror(tmp_path, monkeypatch):
    """THE SECOND BUG. Killing is honoured at the next gate, so the rung already in flight
    finishes and mirrors its outcome afterwards — writing `climbing` straight back over the
    park. The button appeared to do nothing at all: the run kept moving on screen."""
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=PARKED, rung=2)])
    rec(7, "climbing", 3, "running rung 3", {})
    assert store.get(7)["status"] == PARKED, "the mirror un-parked a run a human stopped"


def test_a_gate_state_cannot_un_park_it_either(tmp_path, monkeypatch):
    """The rung in flight can finish into a gate rather than into `climbing`, which is the same
    resurrection wearing a different word."""
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=PARKED, rung=2)])
    rec(7, "await-pick", 2, "three ways it could work", {})
    assert store.get(7)["status"] == PARKED


def test_the_work_that_did_happen_is_still_recorded(tmp_path, monkeypatch):
    """Refusing the STATE is not refusing the facts. The rung that was already running really
    did run and really did cost money, and a record that drops that is a different kind of lie
    from the one being fixed."""
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=PARKED, rung=2)])
    rec(7, "climbing", 3, "running rung 3",
        {"calls": [{"provider": "anthropic", "model": "m", "usd": 1.25,
                    "normalized_usd": 1.25}]})
    got = store.get(7)
    assert got["status"] == PARKED
    assert float(got["spent"]) == 1.25, "the spend from the in-flight rung vanished"


def test_a_running_expedition_still_mirrors_normally(tmp_path, monkeypatch):
    """The guard is narrow by construction — everything that is not a park is untouched. Without
    this, "parked wins" could have been written as "the mirror never changes state"."""
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=CLIMBING, rung=2)])
    rec(7, "await-pick", 2, "three ways it could work", {})
    assert store.get(7)["status"] == "await-pick"


# ── 3 · a run that is over lets go of its worktree; a failure park keeps it ────────────────

def _vessel_with_tree(tmp_path, monkeypatch, number=7):
    """A vessel clone and an expedition worktree under FLS_ROOT, wired the way the box is."""
    import subprocess

    def git(where, *args):
        return subprocess.run(("git", "-C", str(where), *args), capture_output=True, text=True,
                              check=True)

    repo = tmp_path / "vessel"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "T")
    (repo / "README.md").write_text("v\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "init")
    wt = tmp_path / "expeditions" / str(number) / "mvp" / "wt"
    wt.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-b", f"exp-{number}", str(wt), "main")
    monkeypatch.setenv("FLS_VESSEL_REPO", str(repo))
    return wt


def test_a_human_stop_releases_the_worktree(tmp_path, monkeypatch):
    wt = _vessel_with_tree(tmp_path, monkeypatch)
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=PARKED, rung=4)])
    store.save(_exp(7, status=PARKED, rung=4))
    e = store.get(7)
    # the store records WHO stopped it before the workflow's mirror arrives, exactly as
    # `_park_expedition` does
    from fls.github_surface import _rehydrate
    ex = _rehydrate(e, 4, PARKED)
    ex.parked_by = "nate"
    store.save(ex)
    rec(7, PARKED, 4, "killed: released by the test loop", {})
    assert not wt.exists(), "a stopped run has no future; its checkout should go"


def test_a_merged_run_releases_the_worktree(tmp_path, monkeypatch):
    wt = _vessel_with_tree(tmp_path, monkeypatch)
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=CLIMBING, rung=5)])
    rec(7, "done", 5, "merged into main", {})
    assert not wt.exists()


def test_a_failure_park_keeps_the_worktree_for_the_retry(tmp_path, monkeypatch):
    """`/retry` adopts the standing tree — that is the whole point of `standing_work`, and
    releasing it here would turn every retry into a rebuild from scratch."""
    wt = _vessel_with_tree(tmp_path, monkeypatch)
    rec, store = _mirror(tmp_path, monkeypatch, [_exp(7, status=CLIMBING, rung=4)])
    rec(7, PARKED, 4, "the vessel's own check is not green", {})
    assert store.get(7)["parked_by"] == "failure"
    assert wt.exists(), "a failure park must keep its worktree"

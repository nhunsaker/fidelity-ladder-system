"""POST /expeditions/{n}/preview — where the rung-3 prototype can be looked at.

The point of these tests is the refusals. A preview URL that 404s when a reviewer opens it is worse
than a plain "there isn't one yet", and a `pr` mode that silently did nothing would be worse still.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.expedition import CLIMBING, Expedition
from fls.store import ExpeditionStore


def _client(tmp_path, seed=True):
    store = ExpeditionStore(tmp_path)
    if seed:
        store.save(Expedition(101, Idea(101, "a share sheet", "shared", "feature"), 3, rung=3,
                              status=CLIMBING))
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return TestClient(appmod.app)


def _write_demo(tmp_path, number=101, html="<!doctype html><html lang=en><h1>hi</h1></html>"):
    d = Path(tmp_path) / "expeditions" / str(number) / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    return d / "index.html"


def test_stage_mode_returns_the_url_the_harness_actually_serves(tmp_path):
    f = _write_demo(tmp_path)
    c = _client(tmp_path)
    r = c.post("/expeditions/101/preview", json={"mode": "stage"})
    assert r.status_code == 200
    body = r.json()
    assert body["url"] == "/preview/101"
    assert body["bytes"] == f.stat().st_size
    # and the URL it names really serves the file, which is the whole claim being made
    assert c.get("/preview/101").status_code == 200


def test_stage_is_the_default_mode(tmp_path):
    _write_demo(tmp_path)
    c = _client(tmp_path)
    assert c.post("/expeditions/101/preview", json={}).json()["mode"] == "stage"


def test_no_prototype_yet_refuses_rather_than_naming_a_url_that_404s(tmp_path):
    c = _client(tmp_path)
    r = c.post("/expeditions/101/preview", json={"mode": "stage"})
    assert r.status_code == 409
    assert "no prototype yet" in r.json()["detail"]


def test_pr_mode_refuses_instead_of_pretending(tmp_path):
    _write_demo(tmp_path)
    c = _client(tmp_path)
    r = c.post("/expeditions/101/preview", json={"mode": "pr"})
    assert r.status_code == 501
    assert "not implemented" in r.json()["detail"]


def test_unknown_mode_is_rejected(tmp_path):
    _write_demo(tmp_path)
    c = _client(tmp_path)
    assert c.post("/expeditions/101/preview", json={"mode": "carrier-pigeon"}).status_code == 400


def test_unknown_expedition_is_404(tmp_path):
    c = _client(tmp_path, seed=False)
    assert c.post("/expeditions/999/preview", json={"mode": "stage"}).status_code == 404

"""Thread mirror + feedback + wireframe serving (the admin's human-in-the-loop surface).

The feedback endpoint posts COMMENTS — it never mutates the store; commands only take
effect when GitHub echoes them back through the signed webhook (one protocol, no side door).
"""
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.expedition import NEEDS_HUMAN, Expedition
from fls.github_surface import NullClient
from fls.store import ExpeditionStore


def _client(tmp_path, github=None):
    store = ExpeditionStore(tmp_path)
    store.save(Expedition(4, Idea(4, "restock button bolder", "focus ring visible", "ticket"),
                          0, rung=0, status=NEEDS_HUMAN, reason="ambiguous success criteria"))
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    appmod.deps.judge = None
    appmod.deps.github = github
    return TestClient(appmod.app)


def test_thread_unavailable_without_token(tmp_path):
    c = _client(tmp_path, github=None)
    r = c.get("/expeditions/4/thread").json()
    assert r["available"] is False and "token" in r["reason"]


def test_thread_mirrors_issue_comments(tmp_path):
    gh = NullClient()
    gh.post_comment(4, "🤔 **Needs a human** — ambiguous")
    c = _client(tmp_path, github=gh)
    r = c.get("/expeditions/4/thread").json()
    assert r["available"] is True
    assert r["comments"][0]["body"].startswith("🤔")
    assert c.get("/expeditions/999/thread").status_code == 404


def test_feedback_fail_closed(tmp_path):
    gh = NullClient()
    c = _client(tmp_path, github=gh)
    assert c.post("/expeditions/4/feedback", json={"body": "x", "actor": ""}).status_code == 400
    assert c.post("/expeditions/4/feedback", json={"body": "", "actor": "nate"}).status_code == 400
    assert gh.comments == []  # nothing posted on refusal
    # no outbound client -> 503, never a silent pretend
    c2 = _client(tmp_path, github=None)
    assert c2.post("/expeditions/4/feedback",
                   json={"body": "x", "actor": "nate"}).status_code == 503


def test_feedback_posts_comment_never_mutates_store(tmp_path):
    gh = NullClient()
    c = _client(tmp_path, github=gh)
    r = c.post("/expeditions/4/feedback",
               json={"body": "success = axe-clean focus ring on every control", "actor": "nate"})
    assert r.json()["posted"] is True and r.json()["command"] is False
    assert "nate" in gh.comments[0][1]
    # a command formats as-is (parser needs the leading /token) + attribution suffix
    r2 = c.post("/expeditions/4/feedback", json={"body": "/advance", "actor": "nate"})
    assert r2.json()["command"] is True
    assert gh.comments[1][1].startswith("/advance")
    # the store did NOT change — mutation only via the webhook echo
    assert appmod.deps.store.get(4)["status"] == NEEDS_HUMAN


def test_wireframe_serving_fail_closed(tmp_path):
    c = _client(tmp_path)
    wf = Path(tmp_path) / "expeditions" / "4" / "wireframes"
    wf.mkdir(parents=True)
    (wf / "candidate-1.html").write_text("<div>wf-1</div>")
    assert c.get("/wireframes/4/candidate-1.html").status_code == 200
    assert "wf-1" in c.get("/wireframes/4/candidate-1.html").text
    assert c.get("/wireframes/4/candidate-9.html").status_code == 404
    assert c.get("/wireframes/4/evil.html").status_code == 404
    assert c.get("/wireframes/..%2F4/candidate-1.html").status_code == 404

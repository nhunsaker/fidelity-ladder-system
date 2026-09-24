"""The demo surface: what a visitor sees, and what it refuses.

Two properties matter more than the happy path. The machinery must not leak — no rung numbers, no
dial names, no verifier kinds reach the payload. And one request at a time: the surface is public,
and a queue of anonymous requests against a live budget is an invoice, not a demo.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fls import app as appmod
from fls.adjudicator import Idea
from fls.demo import STAGES, DemoAuth, actions_for, demo_view, stage_index, status_words
from fls.expedition import CLIMBING, DOCKED, Expedition
from fls.store import ExpeditionStore

PASS = "open-sesame"


def _client(tmp_path, seed=None):
    store = ExpeditionStore(tmp_path)
    for e in seed or []:
        store.save(e)
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return TestClient(appmod.app)


def _exp(number=1, status=CLIMBING, rung=2, intent="a share sheet", source="demo:nate"):
    """A run filed THROUGH the demo by default — the public surface ignores anything else."""
    return Expedition(number, Idea(number, intent, "shared", "feature", source=source), 4,
                      rung=rung, status=status)


# ── the translation: rungs and dials never reach a visitor ─────────────────────────────────

def test_every_rung_maps_to_one_of_the_five_visible_stages():
    assert [stage_index(r) for r in range(6)] == [0, 0, 1, 2, 3, 4]
    assert stage_index("4-mvp") == 3          # the stored form carries the name too
    assert len(STAGES) == 5


def test_status_becomes_words_and_says_who_is_holding_it_up():
    assert status_words("await-pick") == ("Waiting for you to choose", True)
    assert status_words("climbing") == ("Working on it", False)
    assert status_words("descended")[1] is False
    # an unknown status still reads as English rather than as a slug
    assert status_words("some-new-state")[0] == "Some new state"


def test_pick_and_approve_are_one_decision_to_a_visitor():
    assert actions_for("await-pick") == ["pick", "changes", "kill"]
    assert actions_for("await-approve") == ["approve", "changes", "kill"]
    # A working run offers Stop and nothing else: there is no gate holding a decision mid-rung,
    # but forty minutes of work with no exit is not a defensible alternative either.
    assert actions_for("climbing") == ["kill"]


def test_the_view_never_leaks_the_machinery():
    rec = {"number": 7, "intent": "a share sheet", "rung": "4-mvp", "status": "await-approve",
           "dial": "human-picks", "target": "2-wireframe", "normalized_usd": 5.1}
    view = demo_view(rec, {"detail": "5 files, 258 lines"}, {})
    blob = repr(view).lower()
    for leak in ("rung", "dial", "human-picks", "mvp", "verifier", "await-approve"):
        assert leak not in blob, f"{leak!r} reached the visitor's payload"
    assert view["stage_name"] == "Build"
    assert view["status"] == "Waiting for your approval" and view["waiting_on_you"] is True


def test_the_view_shows_only_what_a_visitor_can_look_at():
    arts = {"wireframe": [{"name": "candidate-1", "title": "Sheet", "premise": "one step",
                           "url": "https://figma/1", "node_id": "1:2"}],
            "build": {"files_changed": ["a", "b"], "lines_changed": 258, "test_passed": True,
                      "note": "built it", "diff": "SHOULD NOT REACH THE VIEW"},
            "ship": {"pr_url": "https://github.com/o/r/pull/1", "branch": "exp-7"}}
    view = demo_view({"number": 7, "intent": "x", "rung": 5, "status": "await-signoff"},
                     None, arts, preview_base="https://demo.invalid/")
    assert view["artifacts"]["candidates"][0]["title"] == "Sheet"
    assert "node_id" not in view["artifacts"]["candidates"][0]
    assert view["artifacts"]["build"]["files"] == 2
    assert "diff" not in view["artifacts"]["build"]
    assert view["artifacts"]["pull_request"].endswith("/pull/1")
    # The run owns its artifacts: /runs/7/preview, not /preview/7. A link a visitor sends.
    assert view["artifacts"]["preview_url"] == "https://demo.invalid/runs/7/preview"


# ── login ──────────────────────────────────────────────────────────────────────────────────

def test_a_token_round_trips_and_a_forged_one_does_not():
    a = DemoAuth(secret=PASS)
    t = a.mint("nate")
    assert a.verify(t) == "nate"
    assert a.verify(t[:-1] + ("0" if t[-1] != "0" else "1")) == ""
    assert a.verify("nate:9999999999:deadbeef") == ""
    assert a.verify("") == "" and a.verify("garbage") == ""


def test_an_expired_token_is_refused():
    a = DemoAuth(secret=PASS, ttl_s=-1)
    assert a.verify(a.mint("nate")) == ""


def test_with_no_passcode_configured_nothing_authenticates():
    a = DemoAuth(secret="")
    assert a.configured is False
    assert a.check_passcode("") is False and a.check_passcode("anything") is False
    assert a.verify(DemoAuth(secret="x").mint("nate")) == ""


def test_login_requires_the_passcode_and_a_name(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path)
    assert c.post("/demo/login", json={"name": "nate", "passcode": "wrong"}).status_code == 401
    assert c.post("/demo/login", json={"name": "", "passcode": PASS}).status_code == 400
    ok = c.post("/demo/login", json={"name": "nate", "passcode": PASS})
    assert ok.status_code == 200 and ok.json()["name"] == "nate" and ok.json()["token"]


def test_login_is_refused_outright_when_no_passcode_is_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("FLS_DEMO_PASSCODE", raising=False)
    c = _client(tmp_path)
    assert c.post("/demo/login", json={"name": "nate", "passcode": ""}).status_code == 503


# ── the active expedition, and the one-at-a-time rule ──────────────────────────────────────

def test_with_nothing_in_flight_the_surface_invites_a_request(tmp_path):
    c = _client(tmp_path)
    body = c.get("/demo/active").json()
    assert body["active"] is None and body["can_request"] is True


def test_a_finished_expedition_does_not_block_the_next_request(tmp_path):
    c = _client(tmp_path, seed=[_exp(1, status=DOCKED, rung=5)])
    assert c.get("/demo/active").json()["can_request"] is True


def test_the_active_expedition_is_shown_in_a_visitors_words(tmp_path):
    c = _client(tmp_path, seed=[_exp(3, status=CLIMBING, rung=2)])
    body = c.get("/demo/active").json()
    assert body["can_request"] is False
    a = body["active"]
    assert a["number"] == 3 and a["request"] == "a share sheet"
    assert a["stage_name"] == "Wireframe" and a["stages"] == list(STAGES)


def test_filing_a_request_needs_a_signed_in_visitor(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path)
    assert c.post("/demo/ideas", json={"intent": "a thing"}).status_code == 401


def test_a_second_request_while_one_is_in_flight_is_refused_in_plain_words(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[_exp(4, status=CLIMBING)])
    token = c.post("/demo/login", json={"name": "nate", "passcode": PASS}).json()["token"]
    r = c.post("/demo/ideas", json={"intent": "another thing"},
               headers={"x-demo-token": token})
    assert r.status_code == 409
    assert "one at a time" in r.json()["detail"]


def test_an_empty_request_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path)
    token = c.post("/demo/login", json={"name": "nate", "passcode": PASS}).json()["token"]
    r = c.post("/demo/ideas", json={"intent": "   "}, headers={"x-demo-token": token})
    assert r.status_code == 400


def test_a_parked_run_does_not_wedge_the_surface(tmp_path):
    """A failure must not block every future request. Parked means it stopped and will not
    progress on its own; treating it as in-flight would jam the demo the first time anything
    went wrong — which is exactly what happened on the live instance."""
    from fls.demo import is_active
    assert is_active("parked") is False
    assert is_active("climbing") is True and is_active("await-pick") is True
    c = _client(tmp_path, seed=[_exp(5, status="parked", rung=5)])
    assert c.get("/demo/active").json()["can_request"] is True


def test_a_run_whose_workflow_has_finished_is_not_offered_as_live(tmp_path, monkeypatch):
    """The store can say "awaiting sign-off" about a run whose workflow completed long ago.
    Trusting the record alone gave a visitor three buttons that all returned 409, and blocked
    every future request behind a run nothing was driving. Seen live on expedition 3."""
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def dead(number):
        raise RuntimeError("workflow execution already completed")

    monkeypatch.setattr(orch, "status", dead)
    c = _client(tmp_path, seed=[_exp(3, status="await-signoff", rung=5)])
    body = c.get("/demo/active").json()
    assert body["active"] is None
    assert body["can_request"] is True, "a dead workflow must not wedge the surface"


def test_a_live_workflow_is_offered_normally(tmp_path, monkeypatch):
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def alive(number):
        # the engine's own detail strings are written for an operator too: "running rung 2"
        return {"detail": "running rung 2", "artifacts": {}}

    monkeypatch.setattr(orch, "status", alive)
    c = _client(tmp_path, seed=[_exp(6, status="await-pick", rung=2)])
    body = c.get("/demo/active").json()
    assert body["active"]["number"] == 6
    assert body["active"]["actions"] == ["pick", "changes", "kill"]
    # ...so it does not reach the visitor verbatim
    assert "rung" not in body["active"]["detail"].lower()


def test_the_public_surface_shows_only_what_was_filed_through_it(tmp_path):
    """An operator's expedition is not a visitor's business, and a stale one from a test must not
    wedge the request box behind work the visitor cannot act on. Seen live: expeditions 1, 2 and 3
    were old internal runs, and each in turn took over the public page."""
    operator = _exp(8, status=CLIMBING, intent="internal work", source="manual")
    visitor = _exp(9, status=CLIMBING, intent="a share sheet")
    c = _client(tmp_path, seed=[operator, visitor])
    a = c.get("/demo/active").json()["active"]
    assert a["number"] == 9 and a["request"] == "a share sheet"

    # a fresh store: the first client persisted to tmp_path, so reusing it would still hold #9
    solo = tmp_path / "operator-only"
    solo.mkdir()
    c2 = _client(solo, seed=[_exp(8, status=CLIMBING, intent="internal work", source="manual")])
    body = c2.get("/demo/active").json()
    assert body["active"] is None and body["can_request"] is True


def test_the_page_and_the_request_box_agree(tmp_path, monkeypatch):
    """They asked the same question two different ways and diverged: the page said "go ahead",
    the request box said "#3 is still in flight". Whatever the answer, it must be one answer."""
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    operator = _exp(3, status="await-signoff", rung=5, source="manual")
    c = _client(tmp_path, seed=[operator])
    token = c.post("/demo/login", json={"name": "nate", "passcode": PASS}).json()["token"]

    can_request = c.get("/demo/active").json()["can_request"]
    filed = c.post("/demo/ideas", json={"intent": "a thing"}, headers={"x-demo-token": token})
    # the surface invited a request, so filing one must not be refused as "already in flight"
    assert can_request is True
    assert filed.status_code != 409, filed.json()


def test_the_judges_reasoning_does_not_reach_a_visitor():
    """The admission judge writes for an operator — its prose cites verifiers, budgets and north
    stars — and it was reaching the public page through the detail line. Seen live on #11."""
    from fls.demo import visitor_detail
    judged = ("It plausibly traces to the north star, but the idea is underspecified about "
              "whether any verifier/budget/a11y requirements are satisfied")
    out = visitor_detail(judged)
    for w in ("verifier", "north star", "a11y", "budget"):
        assert w not in out.lower()
    assert "more detail" in out
    # our own prose is written for a visitor already and passes through untouched
    assert visitor_detail("5 files changed, 258 lines") == "5 files changed, 258 lines"
    assert visitor_detail("") == ""


def test_a_pasted_passcode_still_works():
    """A shared passcode is copied out of a terminal or a password manager, and both carry a
    trailing newline. Rejecting the correct passcode over an invisible character tells the person
    they typed it wrong, which is unhelpful and untrue. Reported from the live surface."""
    a = DemoAuth(secret=PASS)
    for variant in (PASS, PASS + "\n", PASS + " ", " " + PASS, f"  {PASS}\n"):
        assert a.check_passcode(variant) is True, repr(variant)
    # a genuinely wrong passcode is still refused, and so is an empty one
    assert a.check_passcode(PASS + "x") is False
    assert a.check_passcode("   ") is False and a.check_passcode("") is False


# ── the three buttons, and whether any of them reach anything ──────────────────────────────
#
# On 2026-09-11 all three were broken at once on the live harness and the screen said nothing:
# "Yes, carry on" 500'd, "Send changes" and "Stop" 400'd, and a 5s poller wiped every error
# inside five seconds. The tests below are one per cause, because a single end-to-end test would
# have gone green again the moment any one of them was fixed.

def test_stop_never_depends_on_a_notification_going_through(tmp_path, monkeypatch):
    """Stopping is a state change the store owns.

    It used to be posted as `/kill` through the feedback path, so the most important control on
    the surface needed either a live workflow or a real GitHub issue — and a run the admission
    gate declined has neither. It answered 400 and the run stayed in flight forever, wedging the
    surface against a request nobody could clear.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, [_exp(7, status="needs-human", rung=0)])
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    r = c.post("/demo/expeditions/7/feedback", json={"body": "/kill changed my mind"},
               headers={"x-demo-token": tok})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "parked"
    assert appmod.deps.store.get(7)["status"] == "parked"


def test_saying_what_to_change_is_prose_and_is_not_refused_as_an_unknown_command(tmp_path,
                                                                                monkeypatch):
    """The surface draws a box captioned "Or say what to change" and then refused its contents:
    the visitor allowlist required the text to START WITH one of three slash-commands, which no
    sentence a person types ever does."""
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, [_exp(8, status="await-pick", rung=2)])
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    prose = c.post("/demo/expeditions/8/feedback", json={"body": "the amount is hard to find"},
                   headers={"x-demo-token": tok})
    assert prose.status_code != 400, prose.text
    # ...while an unknown COMMAND is still refused: a slash prefix is someone addressing the
    # protocol, not a visitor typing.
    assert c.post("/demo/expeditions/8/feedback", json={"body": "/drop table"},
                  headers={"x-demo-token": tok}).status_code == 400


def test_an_idea_that_never_cleared_admission_offers_only_stop():
    """`needs-human` at the admission rung has no run behind it and no issue behind it, so
    approve and changes have nowhere to land. The screen drew all three anyway."""
    assert actions_for("needs-human", 0) == ["kill"]
    assert actions_for("needs-human", "0-intent") == ["kill"]
    # ...but the same status mid-climb still has a run to talk to
    assert actions_for("needs-human", "3-demo") == ["approve", "changes", "kill"]
    assert actions_for("await-pick", "2-wireframe") == ["pick", "changes", "kill"]


def test_a_refusal_reaches_the_visitor_in_visitor_words():
    """Rule 1 of this surface is that the machinery never shows. An engine refusal names the
    repo, the workflow and the seam, because an operator needs those words."""
    from fls.demo import visitor_error
    engine_said = ("expedition 13 has no issue on acme/vessel and no running "
                   "workflow, so there is nothing to accept this decision (fail-closed)")
    said = visitor_error(409, engine_said)
    assert said != engine_said
    for leak in ("workflow", "expedition", "fail-closed", "acme/", "issue"):
        assert leak not in said.lower(), said
    assert visitor_error(503, "no outbound GitHub token") != "no outbound GitHub token"
    # 400 is the one case already written for a stranger, and it is kept rather than blurred
    assert visitor_error(400, "that is not one of this surface's actions").startswith("that is")


# ── where a decision is sent ────────────────────────────────────────────────────────────────

class _Boom404:
    """A GitHub client for a repo where this expedition simply is not an issue."""
    def get_issue(self, issue):
        from urllib.error import HTTPError
        raise HTTPError(f"https://api.github.com/repos/x/y/issues/{issue}",
                        404, "Not Found", {}, None)

    def post_comment(self, issue, text):
        raise AssertionError("must not post when the number resolves to nothing")


class _NumberIsAPullRequest:
    """The repo HAS a #N — and it is a pull request, because GitHub numbers issues and PRs from
    one sequence while expedition numbers are minted locally from another."""
    def __init__(self): self.posted = []

    def get_issue(self, issue):
        return {"number": issue, "html_url": f"https://github.com/x/y/pull/{issue}",
                "title": "some unrelated PR", "pull_request": {"url": "..."}}

    def post_comment(self, issue, text):
        self.posted.append((issue, text))

    def list_comments(self, issue):
        raise AssertionError("a pull request's conversation must never be fetched")


def _fake_orch(monkeypatch, *, enabled=True, has_workflow=True, signals=None, state="climbing"):
    from fls.orchestration import client as orch

    async def status(number, settings=None):
        return {"rung": "2-wireframe", "state": state} if has_workflow else None

    async def signal(number, name, payload=None, settings=None):
        (signals if signals is not None else []).append((number, name, payload))

    monkeypatch.setattr(orch, "enabled", lambda: enabled)
    monkeypatch.setattr(orch, "status", status)
    monkeypatch.setattr(orch, "signal", signal)


def test_a_decision_goes_to_the_run_when_there_is_one_even_though_github_is_configured(
        tmp_path, monkeypatch):
    """THE BUG, in one sentence: the engine chose its path from a fact about the INSTANCE ("is a
    GitHub token configured") instead of a fact about the RUN ("where does this one live").

    A harness wired to both therefore always chose GitHub — so a run filed through /demo/ideas,
    which mints a local number and opens no issue, posted its approval as a comment on an issue
    number belonging to nobody. 404 from the API, 500 to the browser, and a screen that looked
    inert because a 5s poller wiped the error before it could be read.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    sent = []
    _fake_orch(monkeypatch, has_workflow=True, state="await-pick", signals=sent)
    c = _client(tmp_path, [_exp(21, status="await-pick", rung=2)])
    monkeypatch.setattr(appmod, "_github", lambda: _Boom404())   # configured, and wrong for this run
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    r = c.post("/demo/expeditions/21/feedback", json={"body": "/pick 2"},
               headers={"x-demo-token": tok})
    assert r.status_code == 200, r.text
    assert r.json()["via"] == "temporal"
    assert sent == [(21, "pick", 2)]


def test_a_run_with_neither_an_issue_nor_a_workflow_refuses_legibly(tmp_path, monkeypatch):
    """It used to be a 500 with a urllib traceback in the journal. A refusal has to SAY it
    refused — the whole complaint was "nothing happens"."""
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    _fake_orch(monkeypatch, has_workflow=False, state="await-signoff")
    c = _client(tmp_path, [_exp(22, status="await-signoff", rung=5)])
    monkeypatch.setattr(appmod, "_github", lambda: _Boom404())
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    r = c.post("/demo/expeditions/22/feedback", json={"body": "/approve"},
               headers={"x-demo-token": tok})
    assert r.status_code == 409, r.status_code
    # ...and in the visitor's words, not the engine's
    assert "workflow" not in r.json()["detail"].lower()


def test_the_thread_endpoint_says_where_a_decision_would_land(tmp_path, monkeypatch):
    """The operator screen printed "no linked GitHub issue for this expedition" two lines under
    "your feedback below goes onto the issue", with Advance enabled between them. It had the
    fact and no word for the consequence."""
    _fake_orch(monkeypatch, has_workflow=False)
    c = _client(tmp_path, [_exp(23, status="needs-human", rung=0)])
    monkeypatch.setattr(appmod, "_github", lambda: _Boom404())
    body = c.get("/expeditions/23/thread").json()
    assert body["available"] is False
    assert body["route"] == "none"

    _fake_orch(monkeypatch, has_workflow=True)
    assert c.get("/expeditions/23/thread").json()["route"] == "workflow"


def test_an_approve_the_run_would_absorb_is_refused_rather_than_recorded(tmp_path, monkeypatch):
    """At a pick gate the workflow waits on `picked | feedback | kill`. An `approve` signal sets a
    flag its wait condition never reads — so the signal was accepted, absorbed, and nothing moved,
    while the engine answered 200 and wrote a Decision to the ledger.

    A ledger row for a decision that provably had no effect is worse than no row at all: this
    system's whole claim is that the ledger shows it or it did not happen.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    sent = []
    _fake_orch(monkeypatch, has_workflow=True, state="await-pick", signals=sent)
    c = _client(tmp_path, [_exp(31, status="await-pick", rung=2)])
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]

    r = c.post("/demo/expeditions/31/feedback", json={"body": "/approve"},
               headers={"x-demo-token": tok})
    # 422 — "not what this gate wants", distinct from 409 "nowhere to send it at all". Both were
    # 409 at first, so a visitor who approved at a pick gate was told their request had never made
    # it through the front door, while looking at the candidates it had produced.
    assert r.status_code == 422, r.text
    assert sent == []                                    # nothing was signalled
    rows = list(appmod.deps.store.ledger().read()) if hasattr(appmod.deps.store.ledger(), "read") else []
    assert not [d for d in rows if getattr(d, "expedition", None) == 31], "no phantom decision"

    # ...and the pick it IS waiting for still goes through
    ok = c.post("/demo/expeditions/31/feedback", json={"body": "/pick 2"},
                headers={"x-demo-token": tok})
    assert ok.status_code == 200, ok.text
    assert sent == [(31, "pick", 2)]


def test_every_face_of_the_absorbed_signal_is_refused(tmp_path, monkeypatch):
    """The general rule, not the one face that got reported.

    The workflow's gate resets on entry and then waits on exactly one field. Any other signal is
    set, never read, and wiped by the next gate — accepted by Temporal, answered 200 by the
    engine, recorded in the ledger, and with no effect whatsoever.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    cases = [
        ("await-pick", "/approve", 422),      # the reported one
        ("await-approve", "/pick 1", 422),    # its mirror image
        ("climbing", "/approve", 422),        # mid-rung: no gate is open at all
        ("climbing", "/pick 1", 422),
        ("await-approve", "/approve", 200),   # ...and the matching signal still goes through
        ("await-pick", "/pick 1", 200),
        ("await-signoff", "/approve", 200),
    ]
    for state, body, expected in cases:
        sent = []
        _fake_orch(monkeypatch, has_workflow=True, state=state, signals=sent)
        c = _client(tmp_path, [_exp(41, status=state, rung=2)])
        tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
        r = c.post("/demo/expeditions/41/feedback", json={"body": body},
                   headers={"x-demo-token": tok})
        assert r.status_code == expected, f"{state} + {body} -> {r.status_code}: {r.text}"
        assert bool(sent) is (expected == 200), f"{state} + {body} signalled: {sent}"

    # kill is the one signal no gate resets, so it is accepted in every state including mid-rung
    for state in ("climbing", "await-pick", "await-approve"):
        _fake_orch(monkeypatch, has_workflow=True, state=state)
        c = _client(tmp_path, [_exp(42, status=state, rung=2)])
        tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
        assert c.post("/demo/expeditions/42/feedback", json={"body": "/kill enough"},
                      headers={"x-demo-token": tok}).status_code == 200, state


def test_a_climbing_run_is_never_told_it_cannot_start():
    """`status` and `detail` are rendered side by side, so they have to agree.

    The admission reason explains ADMISSION. Falling back to it while a run climbs kept a
    sentence about the request's scope on screen for the whole climb; and because an admitted
    idea's reasoning routinely mentions altitude or non-negotiables, the leak-guard replaced it
    with "This needs a bit more detail before it can start" — printed directly under "Working on
    it". Under the permissive bar that became the common case, not the edge one.
    """
    from fls.demo import demo_view, visitor_detail
    reason = ("fits the Pocket product and maps to an allowed altitude without violating any "
              "stated non-negotiables, though the exact scope still needs settling")

    climbing = demo_view({"number": 14, "intent": "share a mood with an emoji",
                          "status": "climbing", "rung": 1, "reason": reason})
    assert climbing["status"] == "Working on it"
    assert "before it can start" not in climbing["detail"], climbing["detail"]

    # ...while a run that really is stopped still gets the sentence, because there it is true
    stopped = demo_view({"number": 15, "intent": "x", "status": "needs-human", "rung": 0,
                         "reason": reason})
    assert "before it can start" in stopped["detail"]

    # and the leak guard itself still guards, under both readings. `altitude` and
    # `non-negotiable` were NOT in the guard list until this test used the real words the gate
    # writes — the permissive bar puts them in almost every admitting reason.
    for word in ("altitude", "non-negotiable"):
        assert word not in visitor_detail(reason, blocked=True).lower()
        assert word not in visitor_detail(reason, blocked=False).lower()
    assert visitor_detail(reason, blocked=False) == ""


def test_a_decision_is_never_posted_onto_a_pull_request(tmp_path, monkeypatch):
    """The worst bug of the whole pass, and it reported success.

    Expeditions filed locally are numbered `max(wall) + 1`. GitHub numbers issues AND pull
    requests from one sequence, and `POST /issues/{n}/comments` accepts a PR without complaint.
    On 2026-09-12 an Advance on local expedition 2 posted `/advance` onto pull request #2 — closed
    and unrelated — the signed webhook echoed it back, and the harness acted on it: "Advanced to
    5-flagged". A decision about one thing was executed against another, and the operator was
    shown a success toast.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    _fake_orch(monkeypatch, has_workflow=False)
    gh = _NumberIsAPullRequest()
    c = _client(tmp_path, [_exp(2, status="await-signoff", rung=5)])
    monkeypatch.setattr(appmod, "_github", lambda: gh)
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]

    r = c.post("/demo/expeditions/2/feedback", json={"body": "/approve"},
               headers={"x-demo-token": tok})
    assert r.status_code == 409, r.text
    assert gh.posted == [], f"a decision reached a pull request: {gh.posted}"


def test_a_demo_run_is_still_a_demo_run_after_it_moves(tmp_path):
    """Provenance has to survive a rung transition, and it did not.

    `_rehydrate` rebuilt the Idea as `Idea(number, intent, "", "feature")`, dropping `source`.
    The workflow re-saves on every transition, so a run filed through the demo was relabelled
    `manual` the first time it climbed. After that the demo surface no longer recognised the
    expedition it had just filed: /demo/active showed nothing while a run was visibly in flight,
    and the visitor door answered "that expedition was not filed here" about its own run.

    Verified live on expedition 14, which reached a pick gate that the surface that created it
    could not see.
    """
    from fls.github_surface import _rehydrate
    from fls.store import summary

    store = ExpeditionStore(tmp_path)
    store.save(_exp(60, status=CLIMBING, rung=0, source="demo:visitor"))
    assert store.get(60)["source"] == "demo:visitor"

    # ...one rung later, written back the way the worker's mirror writes it
    moved = _rehydrate(store.get(60), 2, CLIMBING)
    assert moved.idea.source == "demo:visitor", "provenance lost on rehydration"
    store.save(moved)
    assert store.get(60)["source"] == "demo:visitor", "provenance lost on the round trip"
    assert summary(moved)["source"] == "demo:visitor"


def test_the_demo_surface_keeps_showing_a_run_after_it_climbs(tmp_path, monkeypatch):
    """The user-visible half of the same bug: the surface losing its own run."""
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    from fls.github_surface import _rehydrate
    c = _client(tmp_path, [_exp(61, status=CLIMBING, rung=0, source="demo:visitor")])
    appmod.deps.store.save(_rehydrate(appmod.deps.store.get(61), 2, "await-pick"))
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    r = c.post("/demo/expeditions/61/feedback", json={"body": "/pick 1"},
               headers={"x-demo-token": tok})
    assert r.status_code != 403, f"the demo door disowned its own run: {r.text}"


def test_the_two_refusals_do_not_borrow_each_others_words():
    """A live run at an open gate and a run with nowhere to send anything are different problems,
    and telling a visitor the wrong one is worse than saying nothing.

    Both were 409, so approving at a pick gate produced "This request never made it through the
    front door" — about a run three stages in, on the same screen as its candidates.
    """
    from fls.demo import visitor_error
    nowhere = visitor_error(409, "engine words")
    wrong_verb = visitor_error(422, "engine words")
    assert nowhere != wrong_verb
    assert "front door" in nowhere
    assert "front door" not in wrong_verb
    assert "waiting for" in wrong_verb


def test_a_run_at_a_gate_is_not_told_it_cannot_start():
    """The pick gate's own detail line trips the leak guard on the word "Expedition", and the
    replacement said the request needed more detail before it could start — while it was
    showing three candidates and asking which one."""
    from fls.demo import demo_view
    v = demo_view({"number": 14, "intent": "x", "status": "await-pick", "rung": 2,
                   "reason": "3 candidates in Expedition 14"})
    assert v["status"] == "Waiting for you to choose"
    assert "before it can start" not in v["detail"], v["detail"]
    assert "Expedition" not in v["detail"]


def test_the_thread_never_mirrors_a_pull_requests_conversation(tmp_path, monkeypatch):
    """The read half of the number collision.

    `expedition_thread` asked GitHub for issue #N with no check on what came back, so for a
    locally-numbered expedition whose number happens to be a PR it returned that PR's title, URL
    and entire comment list as "this expedition's issue thread" — mirroring a stranger's
    discussion into a governance screen. Separate falsehood from acting on it, same root cause.
    """
    _fake_orch(monkeypatch, has_workflow=False)
    c = _client(tmp_path, [_exp(2, status="await-signoff", rung=5)])
    monkeypatch.setattr(appmod, "_github", lambda: _NumberIsAPullRequest())
    body = c.get("/expeditions/2/thread").json()
    assert body["available"] is False, body
    assert body["route"] == "none"
    assert "pull request" in body["reason"]
    assert body["comments"] == []


def test_the_prototype_builder_is_told_the_rules_it_is_judged_by():
    """Expedition 14 died at "Previewed" with `the page has no <h1>`.

    The rung-3 verifier enforces five mechanical rules and the builder's prompt stated none of
    them, so a prototype was judged against a rubric it had never been shown. The fix is to state
    the rubric, never to lower it — the a11y floor is a non-negotiable in the ANCHOR.

    This test pins prompt to checker: if a rule is added to the verifier and not to the prompt,
    it fails here rather than in a parked run somebody has to diagnose.
    """
    from fls.builders.prototype import _SYSTEM
    low = _SYSTEM.lower()
    for rule in ("<h1>", "lang", "<button>", "focus", "design system"):
        assert rule in low, f"the builder is never told about {rule!r}"


def test_the_workers_seam_publishes_the_backends_it_accepts():
    """The Modules screen told a working instance its ANCHOR was misspelled.

    `make_builder` dispatches on api / claude-code / skill-server. The screen kept its own copy of
    that list, missing `claude-code`, so a claude-code instance got "not one of the registered
    kinds — check the spelling" printed directly under "claude-code — Reachable", while that
    builder was mid-way through a rung-4 build.

    The engine now publishes the list it actually dispatches on, so the screen has nothing to keep
    stale. This test pins the published list to the factory.
    """
    import inspect

    from fls.llm import BUILDER_BACKENDS, make_builder
    src = inspect.getsource(make_builder)
    for backend in BUILDER_BACKENDS:
        assert f'"{backend}"' in src or backend == "skill-server", \
            f"{backend} is published but make_builder does not dispatch on it"
    assert "claude-code" in BUILDER_BACKENDS


def test_the_build_rung_states_its_block_target_and_that_nothing_is_refused_for_size():
    """Expedition 12 produced a complete, green, tested rung-4 build and it was thrown away for
    sixteen lines: 416 against a budget of 400.

    That used to be the argument for stating the threshold LOUDER — the number was mentioned once,
    softly, at the end of a long prompt, so it moved into the standing rules as a park condition.
    The 2026-09-16 batch then showed what a hard threshold actually does: its only two refusals
    were a stale-base bug counting 1,450 lines the builds had not written, and the thirteen that
    shipped had visibly sized themselves to land at 397-400. It was shaping the work, not catching
    it, and expedition 12 was the cost.

    So the number stays in the standing rules and stops being a threshold: it is the size of BLOCK
    the session is asked to commit in, and the prompt says plainly that nothing is refused for
    going over. Size is told to a person (`claude_code_builder.size_notes`), never enforced.
    """
    from fls.builders.claude_code_builder import ClaudeCodeBuilder
    b = ClaudeCodeBuilder("/tmp", session_factory=lambda *a, **k: None, line_budget=400)
    sysp = b.system_prompt()
    assert "400 CHANGED LINES" in sysp
    assert "COMMIT AS YOU GO" in sysp
    assert "NOTHING is refused for size" in sysp
    assert "PARKS" not in sysp, "a size threshold that discards finished work is gone"
    # an instance with no budget must not be shown a bare "0"
    b0 = ClaudeCodeBuilder("/tmp", session_factory=lambda *a, **k: None, line_budget=0)
    assert "0 CHANGED LINES" not in b0.system_prompt()


def test_the_admin_offers_every_kind_the_engine_can_dispatch():
    """Modules.jsx keeps its own copy of nine registries. One went stale and the screen told a
    working instance to check its spelling of `claude-code` — two lines under "claude-code —
    Reachable", while that builder was mid-way through a rung-4 build.

    The screen now prefers the kinds the engine publishes, but eight of its nine lists are still
    local copies. This asserts the direction that actually bites: every kind the ENGINE can
    dispatch must appear in the screen's list. A kind the screen lists and the engine does not is
    a different (documented, harmless) case — built-ins like `manual` and `html` live outside the
    registries — so this is deliberately a one-way check.
    """
    import re
    from pathlib import Path

    from fls import modules as m
    from fls.llm import BUILDER_BACKENDS

    src = (Path(__file__).resolve().parents[2] / "admin/src/sections/Modules.jsx").read_text()
    listed = {}
    # `key:`, not `slot:` — the first draft of this regex matched nothing, so the test passed
    # while proving nothing. The assertion below that `listed` is non-empty is the guard against
    # that happening again silently.
    for slot, kinds in re.findall(r"key:\s*'([a-z]+)'[\s\S]{0,400}?kinds:\s*\[([^\]]*)\]", src):
        listed[slot] = {k.strip().strip("'\"") for k in kinds.split(",") if k.strip()}

    assert listed, "parsed no kinds lists out of Modules.jsx — this test would prove nothing"
    engine = {"auth": set(m.AUTH), "identity": set(m.IDENTITY), "sources": set(m.SOURCES),
              "environment": set(m.ENVIRONMENTS), "deploy": set(m.DEPLOYERS),
              "workers": set(BUILDER_BACKENDS)}
    for slot, kinds in engine.items():
        if slot not in listed:          # the file's shape changed; that is its own failure
            continue
        missing = kinds - listed[slot]
        assert not missing, f"the admin's {slot} list is missing engine kinds: {sorted(missing)}"


def test_anchor_validate_refuses_rather_than_crashing(tmp_path, monkeypatch):
    """The console's `validate()` caught every exception and answered "valid: true, proceed", so
    an edit this endpoint could not even parse became a pull request against the constitution.

    Only ValidationError was handled here; an unknown section or a bad key escaped as a 500, which
    is exactly the shape that catch swallowed. The whole job of this route is to answer "may these
    edits be applied" — "I crashed" is a no, and it has to say so in the answer's own shape.
    """
    c = _client(tmp_path)
    r = c.post("/anchor/validate", json={"section": "not-a-real-section", "edits": {"x": 1}})
    assert r.status_code == 200, r.text          # a refusal, not a server error
    body = r.json()
    assert body["valid"] is False
    assert body["errors"], "a refusal has to say why"


def test_the_surface_keeps_showing_the_run_that_just_finished(tmp_path, monkeypatch):
    """`TERMINAL` answers "may the surface take a new request". It was also, by accident,
    answering "is this still worth showing" — one flag doing two jobs, and the second answer was
    wrong. A visitor who watched five stages arrived at the payoff and found the request box back,
    with no pull request, no staged build and no sign anything had happened.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    from fls.demo import last_finished
    c = _client(tmp_path, [
        _exp(80, status="done", rung=5, intent="a finished demo run", source="demo:v"),
        _exp(81, status="parked", rung=0, intent="an operator's run", source="manual"),
    ])
    body = c.get("/demo/active").json()
    assert body["active"] is None
    assert body["can_request"] is True, "a finished run must not wedge the surface"
    assert body["finished"] is not None, "the surface forgot the run the visitor came to see"
    assert body["finished"]["request"] == "a finished demo run"
    assert body["finished"]["stage_name"] == "Ship"

    # an operator's expedition is not a stranger's to read, finished or not
    assert last_finished([{"number": 9, "source": "manual", "status": "done"}]) is None
    # and the newest demo run wins
    assert last_finished([{"number": 1, "source": "demo:v", "status": "done"},
                          {"number": 7, "source": "demo:v", "status": "parked"}])["number"] == 7


# ── a row shows what a run PRODUCED, never what its rung implies ─────────────────────────────

def test_artifact_facts_are_derived_from_what_exists_not_the_rung():
    """The Wall computed `demo: i >= 3, pr: i >= 4` from the RUNG INDEX, so four expeditions
    showed a PR chip and exactly one had opened a pull request. A row may show what a run
    produced and nothing else."""
    from fls.store import artifact_facts_from

    # a run that reached rung 5 and shipped nothing claims nothing
    assert artifact_facts_from({}) == {}
    assert "pull_request" not in artifact_facts_from({"build": {"lines_changed": 10}})

    rich = artifact_facts_from({
        "wireframe": [{"name": "c1", "url": "https://figma.com/x"}, {"name": "c2"}],
        "prototype": {"file": "index.html"},
        "build": {"files_changed": ["a", "b"], "lines_changed": 151, "test_passed": True},
        "ship": {"pr_url": "https://github.com/o/r/pull/4"},
    })
    assert rich["frames"] == {"count": 2, "url": "https://figma.com/x"}
    assert rich["preview"] is True
    assert rich["build"]["files"] == 2 and rich["build"]["lines"] == 151
    assert rich["pull_request"].endswith("/pull/4")

    # a ship with no PR url must not produce a pull_request key at all
    assert "pull_request" not in artifact_facts_from({"ship": {"stage": "ok"}})


def test_artifact_facts_persist_and_accumulate_across_rungs(tmp_path):
    """Rungs report one at a time. A later rung must not erase what an earlier one made, or the
    row would show only the last thing produced instead of everything the run produced."""
    store = ExpeditionStore(tmp_path)
    store.save_artifact_facts(7, {"frames": {"count": 3}})
    store.save_artifact_facts(7, {"build": {"files": 6, "lines": 151}})
    got = store.artifact_facts(7)
    assert got["frames"]["count"] == 3, "an earlier rung's artifact was erased"
    assert got["build"]["lines"] == 151
    assert store.artifact_facts(999) == {}


def test_the_wall_rows_carry_their_artifacts(tmp_path, monkeypatch):
    """`/snapshot` is what the Wall renders. Reading the rich bag from the durable run would mean
    one Temporal query per row on every load of the screen that most needs to say what each run
    produced."""
    c = _client(tmp_path, [_exp(21, status="done", rung=5, source="demo:v")])
    appmod.deps.store.save_artifact_facts(21, {"pull_request": "https://github.com/o/r/pull/9"})
    rows = c.get("/snapshot").json()["wall"]
    row = next(r for r in rows if r["number"] == 21)
    assert row["artifacts"]["pull_request"].endswith("/pull/9")
    # ...and a row with nothing produced carries no artifacts key rather than an empty claim
    c2 = _client(tmp_path / "b", [_exp(22, status="climbing", rung=0, source="demo:v")])
    row2 = next(r for r in c2.get("/snapshot").json()["wall"] if r["number"] == 22)
    assert not row2.get("artifacts")


def test_the_demo_read_surface_is_public_but_actions_are_not(tmp_path, monkeypatch):
    """Both halves of the same design, asserted together because the SPLIT is what confuses people:
    the page and the run render for anyone, and only doing something needs the passcode.

    A visitor seeing content while being asked to sign in is not a bug — it is the ANCHOR's
    `identity.public_surfaces` working. What WAS a bug is the screen claiming "Signed in as …"
    over a token that had lapsed twelve hours earlier.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, [_exp(90, status="await-pick", rung=2, source="demo:v")])

    # read: no token, still served
    r = c.get("/demo/active")
    assert r.status_code == 200, "the demo read surface must not require a credential"
    assert r.json()["active"]["request"]

    # act: no token, refused
    assert c.post("/demo/expeditions/90/feedback", json={"body": "/pick 1"}).status_code == 401


def test_an_expired_token_is_refused_and_says_so():
    """The client decides whether to trust a stored token by reading its `exp`; the SERVER is what
    actually enforces it. This pins the server half — a lapsed token is worth nothing."""
    import time

    from fls.demo import DemoAuth
    auth = DemoAuth(secret="s", ttl_s=12 * 3600)
    good = auth.mint("founder")
    assert auth.verify(good) == "founder"

    # the shape the client parses: name:exp:signature
    name, exp, _sig = good.rsplit(":", 2)
    assert name == "founder" and int(exp) > time.time()

    stale = DemoAuth(secret="s", ttl_s=-1).mint("founder")
    assert auth.verify(stale) == "", "an expired token must carry no identity"
    assert auth.verify(good + "x") == "", "a tampered token must carry no identity"


class _AdmitJudge:
    """Admits everything, spends nothing — these tests are about the ATTACHMENT, not the gate."""
    def complete(self, prompt, max_tokens=1024, system=None):
        from fls.llm import Call
        self.last_prompt = prompt
        return ('{"verdict": "admit", "reasoning": "fine"}',
                Call("stub", "stub", 1, 1, 0.0))


# ── one attached file ───────────────────────────────────────────────────────────────────────

def test_an_attachment_is_bounded_by_type_and_size():
    """This is a public URL that spends money. The bounds are the feature."""
    from fls.demo import ATTACH_MAX_BYTES, attachment_error
    assert attachment_error("shot.png", "image/png", 1024) == ""
    assert attachment_error("notes.md", "text/markdown", 10) == ""
    assert "not one this surface takes" in attachment_error("x.exe", "application/x-msdownload", 10)
    assert "not one this surface takes" in attachment_error("p.html", "text/html", 10)
    assert "limit is 4MB" in attachment_error("big.png", "image/png", ATTACH_MAX_BYTES + 1)
    assert attachment_error("e.png", "image/png", 0) == "that file is empty"
    assert attachment_error("", "image/png", 10) == "that file has no name"


def test_only_text_grounds_the_gate():
    """"The details are in the attached file" is actionable for a .md and not for a .png, so the
    two are recorded differently rather than both being called an attachment and left at that."""
    from fls.demo import attachment_grounding
    assert attachment_grounding("text/markdown", b"# what I want\nmore detail") == "# what I want\nmore detail"
    assert attachment_grounding("image/png", b"\x89PNG\r\n") == ""
    assert attachment_grounding("application/pdf", b"%PDF-1.4") == ""
    # a text file too large to hand a model is truncated, not refused
    assert len(attachment_grounding("text/plain", b"x" * 50_000)) == 8_000


def test_filing_with_an_attachment_stores_it_under_a_name_the_server_chose(tmp_path, monkeypatch):
    """A filename off the internet is a path-traversal and content-type problem: `../../x`, or a
    `.html` that would be served back from our own origin and run as our page. The stored name
    comes from the validated TYPE; the uploaded one is kept only as a label."""
    import base64
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path)
    judge = _AdmitJudge()
    monkeypatch.setattr(appmod.deps, "judge", judge, raising=False)
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]

    r = c.post("/demo/ideas", headers={"x-demo-token": tok}, json={
        "intent": "make the recap clearer", "success": "",
        "attachment": {"name": "../../evil.html", "type": "text/markdown",
                       "data": base64.b64encode(b"# the detail").decode()},
    })
    assert r.status_code == 200, r.text
    n = r.json()["number"]
    d = tmp_path / "expeditions" / str(n)
    assert (d / "attachment.md").exists(), "stored under a name derived from the type"
    assert not (d / "evil.html").exists()
    assert not (tmp_path / "evil.html").exists(), "the path never escaped"
    import json as _json
    meta = _json.loads((d / "attachment.json").read_text())
    assert meta["label"] == "../../evil.html"      # kept only as a label
    assert meta["read_by_gate"] is True
    # and the text genuinely reached the gate, rather than being stored and forgotten
    assert "# the detail" in judge.last_prompt

    # ...and it comes back, as a download rather than something this origin will render
    got = c.get(f"/demo/expeditions/{n}/attachment")
    assert got.status_code == 200
    assert "attachment" in got.headers.get("content-disposition", "")


def test_a_refused_attachment_files_nothing(tmp_path, monkeypatch):
    """The request and its file are one act. Half-filing it would leave an expedition whose
    context the requester thinks it has."""
    import base64
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path)
    tok = c.post("/demo/login", json={"name": "Vis", "passcode": PASS}).json()["token"]
    before = len(appmod.deps.store.wall())
    r = c.post("/demo/ideas", headers={"x-demo-token": tok}, json={
        "intent": "x", "attachment": {"name": "x.exe", "type": "application/x-msdownload",
                                      "data": base64.b64encode(b"MZ").decode()}})
    assert r.status_code == 415
    assert len(appmod.deps.store.wall()) == before, "a refused attachment must not file the idea"


def test_a_running_step_says_what_it_is_doing():
    """"Working on it" was the whole message while a run climbed, because the only detail the
    workflow offers is "running rung 2" and every useful word in it is machinery the leak guard
    strips. Translating beats dropping — the guard exists to keep the vocabulary out, not the
    meaning."""
    from fls.demo import demo_view, working_on

    w = working_on("2-wireframe")
    assert w["doing"] == "Drawing the options"
    assert "pick one" in w["means"]
    assert working_on(4)["doing"] == "Writing the code"

    climbing = demo_view({"number": 17, "intent": "x", "status": "climbing",
                          "rung": "2-wireframe", "reason": "running rung 2"})
    assert climbing["working"]["doing"] == "Drawing the options"
    # ...and none of the machinery survives into it
    blob = f"{climbing['status']} {climbing['detail']} {climbing['working']}"
    for leak in ("rung", "workflow", "expedition", "activity"):
        assert leak not in blob.lower(), blob

    # AT A GATE the visitor is the one holding it up; saying the machine is busy would invert it
    for gate in ("await-pick", "await-approve", "await-signoff"):
        assert demo_view({"number": 17, "intent": "x", "status": gate, "rung": 2})["working"] is None
    assert demo_view({"number": 17, "intent": "x", "status": "parked", "rung": 2})["working"] is None


def test_the_running_step_carries_its_start_and_its_limit():
    """The clock was measured from when the PAGE first saw the step, so a refresh reset it and
    someone arriving late saw 0s on a step that had run for minutes. The start is server-side now.

    The limit is the ANCHOR's own wall clock — a bound this instance enforces, not a guess at how
    long things usually take. It is shown as "stops at", because a cap is a promise the system
    keeps and an average is one it cannot."""
    from fls.demo import working_detail
    w = working_detail({"rung": "4-mvp", "step_started_at": 1_700_000_000.0, "step_limit_s": 2400})
    assert w["doing"] == "Writing the code"
    assert w["started_at"] == 1_700_000_000.0
    assert w["limit_s"] == 2400
    # no stamp yet -> no invented one
    bare = working_detail({"rung": "2-wireframe"})
    assert "started_at" not in bare and "limit_s" not in bare


# ── the chosen direction ───────────────────────────────────────────────────────────────────

def _three_candidates():
    return [{"name": f"candidate-{i}", "title": f"Way {i}", "premise": "p", "url": f"https://f/{i}"}
            for i in (1, 2, 3)]


def test_the_pick_marks_exactly_the_candidate_that_was_chosen():
    """`/pick 2` is 1-based, so the SECOND candidate is the one being built.

    Off by one here would show the visitor a direction they did not choose, on the same screen
    that asks them to trust what it says it is doing.
    """
    view = demo_view({"number": 9, "intent": "x", "rung": 3, "status": "climbing"},
                     {"artifacts": {"wireframe": _three_candidates(), "picked": 2}}, {})
    cands = view["artifacts"]["candidates"]
    assert [c["chosen"] for c in cands] == [False, True, False]


def test_no_pick_means_no_candidate_claims_to_be_chosen():
    view = demo_view({"number": 9, "intent": "x", "rung": 2, "status": "await-pick"},
                     {"artifacts": {"wireframe": _three_candidates()}}, {})
    assert [c["chosen"] for c in view["artifacts"]["candidates"]] == [False, False, False]


def test_an_out_of_range_pick_marks_nothing_rather_than_guessing():
    """A pick the candidate list cannot contain is no pick. Clamping to the first one would put a
    green check on a direction nobody chose — the failure this system is least allowed to make."""
    for bad in (0, 4, 99, -1, "2", None, True):
        view = demo_view({"number": 9, "intent": "x", "rung": 3, "status": "climbing"},
                         {"artifacts": {"wireframe": _three_candidates(), "picked": bad}}, {})
        assert not any(c["chosen"] for c in view["artifacts"]["candidates"]), f"picked={bad!r}"


def test_the_step_clock_survives_the_rung_being_a_label(tmp_path, monkeypatch):
    """The store keeps a rung as "3-demo"; the worker writes step.json with 3. Comparing the two
    directly is never true, so the start time was dropped every single time and the demo showed a
    "stops at 15 min" bar with nothing counting beside it — a deadline with no clock, which reads
    as broken rather than as bounded. Found live on expedition 17.
    """
    import json as _json

    from fls import app as app_mod

    d = tmp_path / "expeditions" / "17"
    d.mkdir(parents=True)
    (d / "step.json").write_text(_json.dumps({"rung": 3, "started_at": 1_789_237_534.0}))
    monkeypatch.setattr(app_mod.deps, "root", tmp_path)

    out = app_mod._with_step({"number": 17, "rung": "3-demo", "status": "climbing"})
    assert out["step_started_at"] == 1_789_237_534.0

    # ...and a step.json left over from an EARLIER rung is still ignored, which is the reason the
    # comparison exists at all.
    stale = app_mod._with_step({"number": 17, "rung": "4-mvp", "status": "climbing"})
    assert "step_started_at" not in stale


# ── a run that died must not be shown as a run that is working ─────────────────────────────

def test_a_dead_workflow_is_not_reported_as_working():
    """A Temporal query answers from REPLAYED HISTORY, so it works fine on a workflow that is
    dead and returns whatever state it died in. Expedition 17 died mid-rung-3 on 2026-09-12 and
    went on answering "climbing" — so the demo showed a spinner, "Building a preview", and a
    clock counting past the 15-minute cap it had just promised, over nothing at all. For twenty
    minutes, on the page whose entire premise is that nothing pretends.
    """
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing",
           "step_started_at": 1_789_237_534.0, "step_limit_s": 900}
    wf = {"detail": "running rung 3", "running": False}
    view = demo_view(rec, wf, {})
    assert view["working"] is None, "a dead run was rendered as busy"
    assert view["status"] == "Stopped"
    assert view["waiting_on_you"] is False
    assert "stopped before finishing" in view["detail"].lower()


def test_a_live_workflow_still_reports_what_it_is_working_on():
    """The other direction, or the guard above would be indistinguishable from deleting the
    feature: a run that IS alive must still show its step, its clock and its limit."""
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing",
           "step_started_at": 1_789_237_534.0, "step_limit_s": 900}
    view = demo_view(rec, {"detail": "running rung 3", "running": True}, {})
    assert view["working"]["doing"] == "Building a preview"
    assert view["working"]["started_at"] == 1_789_237_534.0
    assert view["status"] != "Stopped"


def test_an_instance_with_no_workflow_at_all_is_left_alone():
    """`running` is absent on a store-only instance. Absent is not dead — there is nothing to
    contradict the record, so the record stands."""
    rec = {"number": 3, "intent": "x", "rung": "3-demo", "status": "climbing"}
    assert demo_view(rec, None, {})["working"]["doing"] == "Building a preview"
    assert demo_view(rec, {"detail": "d"}, {})["working"]["doing"] == "Building a preview"


def test_a_run_that_died_mid_climb_is_shown_as_finished_and_frees_the_box(tmp_path, monkeypatch):
    """The workflow ANSWERS — a query replays history fine on a dead run — it just answers
    "climbing" forever. So the record and the query agree, and both are wrong.

    Expedition 17 sat like this: shown as the live run, no actions (there are none while
    climbing), can_request False. Once it stopped claiming to be working it said "you can start a
    new request" over a box that refused to take one. Honest about the run, stuck as a surface.
    """
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def died(number):
        return {"state": "climbing", "detail": "running rung 3", "artifacts": {}, "running": False}

    monkeypatch.setattr(orch, "status", died)
    body = _client(tmp_path, seed=[_exp(17, status=CLIMBING, rung=3)]).get("/demo/active").json()
    assert body["active"] is None
    assert body["can_request"] is True, "a run nothing is driving still blocked the request box"
    assert body["finished"]["number"] == 17
    assert body["finished"]["status"] == "Stopped"
    assert body["finished"]["working"] is None


# ── retry: the way back from a stopped run ─────────────────────────────────────────────────

def test_a_stopped_run_offers_a_way_back():
    """Expedition 17 sat stopped with `actions: []`. The record said "climbing", climbing has no
    actions, and so the page showed a visitor a dead run and nothing whatever to do about it.
    Retry and Stop; no "changes", because no gate is holding a revision."""
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing"}
    view = demo_view(rec, {"detail": "running rung 3", "running": False}, {})
    assert view["actions"] == ["retry", "kill"]


def test_a_live_run_is_not_offered_a_retry():
    """The other direction: a run that is climbing is not stuck, and a Retry button on it would
    invite a visitor to restart work that is happening in front of them. Stop is offered, because
    a long operation must always have an exit — retry is the thing that must not be."""
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing"}
    actions = demo_view(rec, {"detail": "d", "running": True}, {})["actions"]
    assert "retry" not in actions
    assert actions == ["kill"]


def test_a_second_attempt_says_so_without_saying_attempt():
    """A re-run restarts the clock, so with nothing said it reads as a stall — the visitor watches
    a counter go back to zero for no visible reason. It says it is trying again, and says nothing
    about attempts, activities or workers: that is the operator's screen."""
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing",
           "step_started_at": 1_789_237_534.0, "step_limit_s": 900}
    health = {"attempt": 2, "max_attempts": 3, "activity": "fls.prototype",
              "worker": "198379@fls-harness-1", "last_heartbeat_at": 1_789_237_600.0}
    w = demo_view(rec, {"detail": "d", "running": True, "run_health": health}, {})["working"]
    assert w["retrying"] is True
    assert w["alive_at"] == 1_789_237_600.0
    blob = repr(w).lower()
    for leak in ("attempt", "activity", "fls.", "worker", "harness-1"):
        assert leak not in blob, f"{leak!r} reached the visitor's payload"


def test_a_first_attempt_does_not_claim_to_be_retrying():
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing"}
    health = {"attempt": 1, "max_attempts": 3}
    w = demo_view(rec, {"detail": "d", "running": True, "run_health": health}, {})["working"]
    assert "retrying" not in w


def _demo_token(c):
    return c.post("/demo/login", json={"name": "nate", "passcode": PASS}).json()["token"]


def test_retry_refuses_a_run_that_is_still_going(tmp_path, monkeypatch):
    """Restarting a run underneath itself would abandon work in progress and pay for it twice.
    Every refusal here names the rule it hit, because a button that just says no teaches nobody
    anything."""
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def alive(number):
        return {"state": "climbing", "running": True}

    monkeypatch.setattr(orch, "status", alive)
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[_exp(9, status=CLIMBING, rung=3)])
    r = c.post("/demo/expeditions/9/feedback", json={"body": "/retry"},
               headers={"x-demo-token": _demo_token(c)})
    assert r.status_code == 409
    assert "still going" in r.json()["detail"]
    assert "front door" not in r.json()["detail"], "the wrong canned 409 was served"


def test_retry_refuses_past_the_ceiling(tmp_path, monkeypatch):
    """The ANCHOR's per-expedition ceiling is the money line. A Retry button that could step over
    it would make the ceiling advisory, and this instance's Budgets screen calls it "the
    fail-closed money line — it does not creep and it does not ask again"."""
    import fls.orchestration.client as orch
    from fls.llm import Call

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def dead(number):
        return {"state": "climbing", "running": False}

    monkeypatch.setattr(orch, "status", dead)
    e = _exp(9, status=CLIMBING, rung=4)
    e.add([Call(provider="p", model="m", usd=0.0, normalized_usd=999.0)])
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[e])
    r = c.post("/demo/expeditions/9/feedback", json={"body": "/retry"},
               headers={"x-demo-token": _demo_token(c)})
    assert r.status_code == 409
    assert "used up what it is allowed to spend" in r.json()["detail"]
    assert "$" not in r.json()["detail"], "the engine's figures reached the visitor"


def test_retry_refuses_a_run_a_human_already_finished(tmp_path, monkeypatch):
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[_exp(9, status="killed", rung=3)])
    r = c.post("/demo/expeditions/9/feedback", json={"body": "/retry"},
               headers={"x-demo-token": _demo_token(c)})
    assert r.status_code == 409
    assert "already finished" in r.json()["detail"]


def test_retry_rewinds_a_stopped_run_and_writes_it_down(tmp_path, monkeypatch):
    """The happy path, and the event: a retry is a decision somebody made about money, so it is
    recorded where the rest of the run's history is rather than only in a log line."""
    import fls.orchestration.client as orch

    monkeypatch.setattr(orch, "enabled", lambda: True)

    async def dead(number):
        return {"state": "climbing", "running": False}

    rewound = {}

    async def rewind(number, reason="retry", settings=None):
        rewound.update(number=number, reason=reason)
        return "run-abc"

    monkeypatch.setattr(orch, "status", dead)
    monkeypatch.setattr(orch, "rewind", rewind)
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[_exp(9, status=CLIMBING, rung=3)])
    r = c.post("/demo/expeditions/9/feedback", json={"body": "/retry"},
               headers={"x-demo-token": _demo_token(c)})
    assert r.status_code == 200, r.text
    assert r.json() == {"retried": True, "number": 9, "run_id": "run-abc"}
    assert rewound["number"] == 9
    kinds = [e["kind"] for e in appmod.deps.store.events(9)]
    assert "retried" in kinds, "a retry left no trace in the run's own record"


def test_every_retry_refusal_has_its_own_visitor_sentence():
    """The claim in demo.py is that each engine refusal is pinned by a test. This is the pin: the
    engine's four literal refusals, each mapped to a sentence that fits it. Reword one in app.py
    and this fails, rather than the page silently serving the generic 409 — which is the exact
    failure the generic 409 caused once already."""
    from fls.demo import visitor_error

    pairs = [
        ("expedition 9 is still running — nothing to retry", "still going"),
        ("expedition 9 has spent $12.50 of its $12.00 ceiling — retry refused (fail-closed)",
         "used up what it is allowed to spend"),
        ("expedition 9 is killed — nothing to retry", "already finished"),
        ("expedition 9 has no run to retry", "nothing left running"),
    ]
    for engine_says, visitor_reads in pairs:
        got = visitor_error(409, engine_says)
        assert visitor_reads in got, f"{engine_says!r} fell through to {got!r}"
        assert "expedition" not in got.lower() and "$" not in got


# ── revisions: the visitor's own words, kept ───────────────────────────────────────────────

def test_revisions_are_listed_with_the_stage_they_were_asked_at():
    """`feedback_log` has recorded every revision since the beginning and no screen ever showed
    one. A visitor typed what they wanted changed, pressed Send, and their words vanished — the
    box emptied, the step re-ran, and nothing said the request had been heard."""
    wf = {"feedback_log": ["r2: make the chips bigger", "r3: the emoji should fade slower"]}
    view = demo_view({"number": 5, "intent": "x", "rung": 3, "status": "climbing"}, wf, {})
    assert view["revisions"] == [
        {"stage": "Wireframe", "at": 1, "asked": "make the chips bigger"},
        {"stage": "Preview", "at": 2, "asked": "the emoji should fade slower"},
    ]


def test_a_revision_that_cannot_be_placed_is_still_shown():
    """A revision the system cannot attribute to a stage is still a revision somebody wrote.
    Dropping it would be a worse lie than showing it bare."""
    view = demo_view({"number": 5, "intent": "x", "rung": 3, "status": "climbing"},
                     {"feedback_log": ["no rung prefix here"]}, {})
    assert view["revisions"] == [{"stage": "", "at": None, "asked": "no rung prefix here"}]


def test_the_rung_number_does_not_travel_with_the_revision():
    """The stored form carries the rung — "r3: …". It is translated to a stage, never shown: this
    payload has a leak guard for exactly this reason and a visitor's own screen is the last place
    a rung ordinal should appear."""
    view = demo_view({"number": 5, "intent": "x", "rung": 2, "status": "await-pick"},
                     {"feedback_log": ["r2: bigger"]}, {})
    blob = repr(view["revisions"])
    assert "r2" not in blob and "rung" not in blob.lower()


def test_a_run_with_no_feedback_lists_nothing():
    """An empty list, not a heading over nothing: the card is absent for a run nobody revised."""
    for wf in (None, {}, {"feedback_log": []}, {"feedback_log": ["  "]}):
        view = demo_view({"number": 5, "intent": "x", "rung": 2, "status": "climbing"}, wf, {})
        assert view["revisions"] == []


def test_a_run_that_is_working_can_be_stopped():
    """Rung 4 may run forty minutes and the page offered no exit — a spinner, a clock and a stated
    cap with nothing beside them. An operation that blocks that long without a Stop is precisely
    what Tidwell's Cancelability pattern forbids.

    Only Stop: approve and changes belong to gates, the workflow refuses both mid-rung (422), and
    a false affordance on the screen a visitor is already waiting on is the worst place for one.
    """
    rec = {"number": 4, "intent": "x", "rung": "4-mvp", "status": "climbing"}
    view = demo_view(rec, {"detail": "d", "running": True}, {})
    assert view["actions"] == ["kill"]
    assert view["working"] is not None, "it must still say what it is doing"


def test_a_gate_still_offers_the_gate_actions():
    """The other direction, or the change above would be indistinguishable from replacing every
    action list with Stop."""
    for status, expected in (("await-pick", ["pick", "changes", "kill"]),
                             ("await-approve", ["approve", "changes", "kill"]),
                             ("await-signoff", ["approve", "changes", "kill"])):
        rec = {"number": 4, "intent": "x", "rung": "3-demo", "status": status}
        assert demo_view(rec, {"detail": "d", "running": True}, {})["actions"] == expected, status


def test_every_stage_says_what_it_produces():
    """Five stage names are five words, and a visitor arriving cold cannot know what any of them
    hands back until they get there — a progress indicator that is not a map. The notes live with
    the other visitor vocabulary because the view invents none of its own: a phrase written in the
    client is a phrase nothing tests and no leak-guard sees."""
    view = demo_view({"number": 1, "intent": "x", "rung": 0, "status": "climbing"}, None, {})
    notes = view["stage_notes"]
    assert len(notes) == len(view["stages"])
    assert all(n.strip() for n in notes), "a stage with no note is a word with no meaning"
    blob = " ".join(notes).lower()
    for leak in ("rung", "dial", "wireframe builder", "temporal", "workflow"):
        assert leak not in blob, f"{leak!r} reached the visitor's ladder"


def test_the_code_says_where_it_is_when_there_is_no_pull_request_yet():
    """The build card showed six files, 356 lines and passing tests, then stopped — so "where is
    it, then?" had no answer on the page and read as a missing link. It is not missing: the pull
    request is made at the LAST step and the run has not been approved past this one.

    Saying so costs a sentence. Fabricating a link is the failure this system exists to refuse —
    the Wall once showed four expeditions claiming a pull request when one had opened it.
    """
    arts = {"build": {"files_changed": ["a"], "lines_changed": 12, "test_passed": True, "note": "did it"}}
    view = demo_view({"number": 8, "intent": "x", "rung": 4, "status": "await-approve"}, None, arts)
    b = view["artifacts"]["build"]
    assert "no pull request" in b["next"]
    assert view["artifacts"].get("pull_request") is None, "a PR was invented for a run without one"


def test_once_it_ships_the_card_stops_explaining_and_links():
    """The other direction: with a pull request on the run, the sentence would be false and the
    link is the answer."""
    arts = {"build": {"files_changed": ["a"], "lines_changed": 12, "test_passed": True, "note": "did it"},
            "ship": {"pr_url": "https://github.com/o/r/pull/9"}}
    view = demo_view({"number": 8, "intent": "x", "rung": 5, "status": "await-signoff"}, None, arts)
    assert view["artifacts"]["build"]["next"] == ""
    assert view["artifacts"]["pull_request"].endswith("/pull/9")


# ── the routes name their audience ─────────────────────────────────────────────────────────

def test_the_canonical_paths_put_the_audience_first(tmp_path, monkeypatch):
    """Audience first, then the noun. The old table had visitor routes under `/demo/` and
    operator routes under no prefix at all, so "unprefixed means privileged" was a convention
    nothing enforced and no reviewer could see — and this session produced exactly that bug, the
    demo page posting to the operator feedback route.

    Under the new spelling the two are `/v1/visitor/runs/{n}/feedback` and
    `/v1/operator/runs/{n}/feedback`: the same mistake is now visible in a diff.
    """
    monkeypatch.setenv("FLS_DEMO_PASSCODE", PASS)
    c = _client(tmp_path, seed=[_exp(3, status=CLIMBING, rung=2)])

    # public: readable with no credential at all
    assert c.get("/v1/public/runs/active").status_code == 200

    # visitor: mints and spends a demo pass
    tok = c.post("/v1/visitor/login", json={"name": "nate", "passcode": PASS}).json()["token"]
    assert tok
    r = c.post("/v1/visitor/requests", json={"intent": "x"}, headers={"x-demo-token": tok})
    assert r.status_code in (200, 409)          # 409 = one already in flight, which is a real answer

    # operator: the same nouns, a different audience
    assert c.get("/v1/operator/runs").status_code == 200
    assert c.get("/v1/operator/runs/3").status_code == 200


def test_the_old_paths_still_answer_and_are_the_same_endpoint(tmp_path):
    """The old spellings stay live because some are held outside this repo — the GitHub App posts
    to /webhook/github, and somewhere a browser holds a bookmark. They are the SAME endpoint
    functions, not copies, so a fix to one is a fix to both and neither can drift."""
    from fastapi.routing import APIRoute

    import fls.app as appmod

    by_path = {r.path: r for r in appmod.app.routes if isinstance(r, APIRoute)}
    for new, old in appmod._LEGACY_PATHS.items():
        assert old in by_path, f"{old} stopped answering"
        assert by_path[old].endpoint is by_path[new].endpoint, f"{old} drifted from {new}"

    c = _client(tmp_path, seed=[_exp(3, status=CLIMBING, rung=2)])
    assert c.get("/wall").status_code == 200
    assert c.get("/v1/operator/runs").json() == c.get("/wall").json()


def test_the_sign_in_flow_did_not_move():
    """`/auth/*` is deliberately absent from the rename: FLS_AUTH_REDIRECT_URI is registered with
    the identity provider, and moving it breaks sign-in until that registration changes too."""
    import fls.app as appmod

    assert not any(p.startswith("/auth") for p in appmod._LEGACY_PATHS.values())
    assert not any("/auth" in p for p in appmod._LEGACY_PATHS)


def test_a_run_that_finished_is_not_called_stopped():
    """A workflow that ENDED is not a run that STOPPED, and both leave `running` false.

    Treating them alike put "Stopped · It stopped before finishing" on expedition 17 after it was
    signed off — on the payoff screen, directly above its own detail line reading "signed off;
    staged behind the flag". The last thing the demo shows anyone, calling a success a failure.

    The record tells them apart: a terminal status means the run reached an ending, and its own
    word for that ending is the true one.
    """
    for status, expect in (("done", "Finished"), ("docked", "Finished"), ("killed", "Killed")):
        rec = {"number": 17, "intent": "x", "rung": 5, "status": status,
               "reason": "signed off; staged behind the flag"}
        view = demo_view(rec, {"detail": "d", "running": False}, {})
        assert view["status"] == expect, f"{status} was reported as {view['status']!r}"
        assert view["actions"] == [], f"{status} offered {view['actions']}"
        assert "stopped before finishing" not in (view["detail"] or "").lower()


def test_a_run_still_climbing_with_nothing_running_it_IS_stopped():
    """The other direction, and the reason the check exists at all: the record says climbing, the
    workflow is gone, and nobody is coming. That is the case expedition 17 was actually in when
    the demo showed a spinner over it for twenty minutes."""
    rec = {"number": 17, "intent": "x", "rung": "3-demo", "status": "climbing"}
    view = demo_view(rec, {"detail": "running rung 3", "running": False}, {})
    assert view["status"] == "Stopped"
    assert view["actions"] == ["retry", "kill"]
    assert "stopped before finishing" in view["detail"].lower()


def test_the_five_steps_are_actions_not_past_participles():
    """Requested, Wireframed, Previewed, Built, Shipped read as a list of things that have
    happened — on a ladder where four of the five have not, and where the one a run is standing on
    has not either. "Shipped" sat over a run waiting for its sign-off and said the work was
    finished while the last gate was still open.

    The check mark carries "done" instead: a shape rather than a tense, and only on rungs that
    actually are.
    """
    from fls.demo import STAGES

    assert STAGES == ("Request", "Wireframe", "Preview", "Build", "Ship")
    for s in STAGES:
        assert not s.endswith("ed"), f"{s!r} is phrased as already done"


def test_a_revision_carries_the_stage_index_so_the_names_can_change():
    """The UI matched revisions to artifacts on the stage NAME, so renaming a stage would have
    silently stopped every "remade after a change you asked for" note appearing, with nothing
    failing to say so. The index is the join; the name is only ever display."""
    wf = {"feedback_log": ["r2: bigger chips", "r4: tests too", "no prefix"]}
    revs = demo_view({"number": 5, "intent": "x", "rung": 4, "status": "climbing"}, wf, {})["revisions"]
    assert [r["at"] for r in revs] == [1, 3, None]
    assert [r["stage"] for r in revs] == ["Wireframe", "Build", ""]


def test_the_finished_run_says_how_to_see_it(monkeypatch):
    """"Behind a flag" is true and useless on its own: a reviewer who then wants to look at the
    thing has two acts to perform and the card named neither. Both are facts about this run —
    staging is what marking the pull request ready for review does, and the flag is the one this
    change introduced, read off the branch."""
    monkeypatch.setenv("FLS_STAGE_URL", "https://stage.example.com")
    arts = {"ship": {"pr_url": "https://github.com/o/r/pull/5", "branch": "exp-17",
                     "flag": "table-reactions"}}
    view = demo_view({"number": 17, "intent": "x", "rung": 5, "status": "done"}, None, arts)
    r = view["artifacts"]["review"]
    assert r == {"stage_url": "https://stage.example.com", "flag": "table-reactions",
                 "branch": "exp-17"}


def test_it_names_no_flag_rather_than_the_wrong_one(monkeypatch):
    """A change that introduces two flags, or none, has no single flag to name. Naming the wrong
    one is worse than naming none: the reviewer edits something real and unrelated."""
    monkeypatch.setenv("FLS_STAGE_URL", "https://stage.example.com")
    arts = {"ship": {"pr_url": "https://github.com/o/r/pull/5", "branch": "exp-17"}}
    view = demo_view({"number": 17, "intent": "x", "rung": 5, "status": "done"}, None, arts)
    assert view["artifacts"]["review"]["flag"] == ""


def test_an_instance_that_stages_nowhere_promises_nothing(monkeypatch):
    """The card is built from `stage_url`; an install with no stage configured gets no steps
    rather than instructions pointing at a URL that does not exist."""
    monkeypatch.delenv("FLS_STAGE_URL", raising=False)
    arts = {"ship": {"pr_url": "https://github.com/o/r/pull/5", "flag": "f", "branch": "b"}}
    view = demo_view({"number": 17, "intent": "x", "rung": 5, "status": "done"}, None, arts)
    assert view["artifacts"]["review"]["stage_url"] == ""


def test_the_clients_fallback_ladder_matches_the_servers():
    """The demo keeps a copy of the five stage names, for the moment before the first payload
    arrives — otherwise the ladder is a blank column. That copy went stale the instant the stages
    were renamed to actions: the empty state read "Requested · Wireframed · …" in past tense while
    a live run read "Request · Wireframe · …", on the same page.

    This is the cost of a second copy of anything the server owns. The copy stays, because a blank
    spine is worse — but it is pinned here, so the two cannot drift again without a test saying so.
    """
    import re
    from pathlib import Path

    from fls.demo import STAGE_NOTES, STAGES

    src = Path(__file__).resolve().parents[2] / "admin" / "src" / "sections" / "Demo.jsx"
    text = src.read_text(encoding="utf-8")

    stages = re.search(r"const STAGE_FALLBACK = \[(.*?)\]", text, re.S).group(1)
    assert [s.strip().strip("'\"") for s in stages.split(",") if s.strip()] == list(STAGES)

    notes = re.search(r"const NOTE_FALLBACK = \[(.*?)\n\]", text, re.S).group(1)
    got = re.findall(r"[\"'](.+?)[\"'],", notes)
    assert len(got) == len(STAGE_NOTES), "the client lists a different number of steps"


# ── why it stopped, in a visitor's words ───────────────────────────────────────────────────

def test_a_cause_never_carries_the_machinery_into_the_payload():
    """The cause record is written for an operator: it names the rung, the attempt, the error
    class, the artifact path and forty lines of transcript. Exactly one sentence of that may
    reach a stranger, and the whole payload is checked, not just the sentence."""
    cause = {"kind": "crash", "rung": 4, "attempt": 2, "error": "ClaudeCodeError",
             "message": "rung 4 (dial: agent-picks) died in vessel exp-9",
             "artifact": "mvp/session-2.log.stderr",
             "tail": ["Traceback (most recent call last):", "  File \"/srv/fls/engine/x.py\""]}
    view = demo_view({"number": 9, "intent": "a share sheet", "rung": "4-mvp",
                      "status": "climbing"}, {"running": False}, {}, cause=cause)
    assert "stopped" in view["status"].lower()
    assert view["cause"] == "Something went wrong inside the Build step."
    blob = repr(view).lower()
    for leak in ("rung", "dial", "vessel", "traceback", "claudecodeerror", "session-2",
                 "attempt", "/srv"):
        assert leak not in blob, f"{leak!r} reached the visitor's payload"


def test_each_kind_of_failure_reads_as_a_different_sentence():
    """Four causes that mean four different things to whoever fixes it. "It stopped" for all of
    them is what the surface said before, and it is what sent every reader to the logs."""
    said = set()
    for kind in ("crash", "timeout", "heartbeat", "stopped"):
        view = demo_view({"number": 9, "intent": "x", "rung": 3, "status": "climbing"},
                         {"running": False}, {}, cause={"kind": kind, "rung": 3})
        said.add(view["cause"])
        assert "Preview" in view["cause"]
    assert len(said) == 4


def test_a_refused_build_says_so_without_the_refusals_own_vocabulary():
    view = demo_view({"number": 9, "intent": "x", "rung": "4-mvp", "status": "parked",
                      "parked_by": "failure"}, {"running": False}, {},
                     cause={"kind": "refused", "rung": 4,
                            "message": "the vessel's check failed at rung 4: 2 tests red"})
    blob = repr(view).lower()
    assert "cause" in view
    for leak in ("rung", "vessel", "dial"):
        assert leak not in blob, f"{leak!r} reached the visitor's payload"


# ── how big it looks, told early and corrected honestly ────────────────────────────────────

def test_the_request_card_says_how_big_it_looks():
    """Rung 1 is the earliest rung that can tell somebody what they are waiting for."""
    view = demo_view({"number": 9, "intent": "x", "rung": 1, "status": "climbing"},
                     {"running": True, "artifacts": {"estimate": {"size": "small",
                                                                  "reason": "one file"}}}, {})
    assert view["estimate"]["size"] == "small"
    assert "one sitting" in view["estimate"]["says"]


def test_no_estimate_means_no_claim():
    view = demo_view({"number": 9, "intent": "x", "rung": 1, "status": "climbing"},
                     {"running": True}, {})
    assert "estimate" not in view


def test_a_change_that_outgrew_its_estimate_says_so_and_offers_nothing_to_fix():
    """FOUNDER'S RULE: size is information. The build is finished, tested and on a pull request;
    the page corrects the size it promised and does not offer a retry, because nothing failed."""
    arts = {"build": {"files_changed": ["a", "b"], "lines_changed": 900, "test_passed": True,
                      "note": "built it", "size": "small",
                      "commits": [{"sha": "a" * 40, "subject": "one", "lines": 450},
                                  {"sha": "b" * 40, "subject": "two", "lines": 450}],
                      "size_notes": ["estimated **small**, grew from that: 900 changed lines "
                                     "across 2 commits — **large**. Nothing was cut to fit."]},
            "ship": {"pr_url": "https://github.com/o/r/pull/1", "ready_for_review": True}}
    view = demo_view({"number": 9, "intent": "x", "rung": "4-mvp", "status": "await-approve"},
                     None, arts)
    grew = view["artifacts"]["build"]["grew"]
    assert "estimated a small change" in grew and "came out a large change" in grew
    assert "retry" not in view["actions"]
    assert view["artifacts"]["build"]["commits"] == 2
    blob = repr(view).lower()
    for leak in ("rung", "budget", "reviewability", "violation"):
        assert leak not in blob, f"{leak!r} reached the visitor's payload"


def test_an_estimate_that_held_says_nothing_extra():
    arts = {"build": {"files_changed": ["a"], "lines_changed": 300, "test_passed": True,
                      "note": "x", "size": "small", "size_notes": [],
                      "commits": [{"sha": "a" * 40, "subject": "one", "lines": 300}]}}
    view = demo_view({"number": 9, "intent": "x", "rung": "4-mvp", "status": "await-approve"},
                     None, arts)
    assert view["artifacts"]["build"]["grew"] == ""


# ── the question gate, on the surface a stranger sees ──────────────────────────────────────

def test_the_question_is_shown_with_its_options_and_a_way_to_answer():
    q = {"ask": "when you say 'it', which do you mean?",
         "options": ["the Fold button", "the dealer button", "something else"]}
    view = demo_view({"number": 9, "intent": "make it red", "rung": 1, "status": "await-answer"},
                     {"running": True, "artifacts": {"question": q}}, {})
    assert view["status"] == "Waiting for your answer" and view["waiting_on_you"] is True
    assert view["question"]["ask"] == q["ask"]
    assert [o["key"] for o in view["question"]["options"]] == ["a", "b", "c"]
    assert view["question"]["options"][1]["text"] == "the dealer button"
    assert "changes" in view["actions"] and "approve" not in view["actions"]


def test_an_answered_question_never_renders_again():
    """Gated on the STATE, not the artifact: a stale question under a later stage would ask a
    person to decide something they already decided."""
    q = {"ask": "which?", "options": ["a thing", "something else"]}
    view = demo_view({"number": 9, "intent": "x", "rung": 2, "status": "await-pick"},
                     {"running": True, "artifacts": {"question": q}}, {})
    assert "question" not in view


def test_a_question_that_trips_the_leak_guard_still_asks_something():
    """Half a question is worse than a plain one, and the textarea works either way."""
    view = demo_view({"number": 9, "intent": "x", "rung": 1, "status": "await-answer"},
                     {"running": True, "artifacts": {"question": {
                         "ask": "which rung did you mean?", "options": ["the vessel", "other"]}}},
                     {})
    assert view["question"]["options"] == []
    assert "more than one thing" in view["question"]["ask"]
    blob = repr(view).lower()
    assert "rung" not in blob and "vessel" not in blob
    assert "changes" in view["actions"], "it must still be answerable"


def test_the_waiting_sentence_does_not_say_it_never_started():
    """`_NEEDS_DETAIL` says "before it can start" — false here. It started, wrote a spec, and
    found one word that could mean two things."""
    view = demo_view({"number": 9, "intent": "x", "rung": 1, "status": "await-answer"},
                     {"running": True}, {})
    assert "before it can go on" in view["detail"]
    assert "start" not in view["detail"]


def test_the_leak_guard_matches_words_not_substrings():
    """"dial" is inside "dialog", "gate" is inside "navigate" — and a question naming a dialog
    was being silently replaced by a generic sentence."""
    from fls.demo import visitor_detail
    for kept in ("the dialog closes when you tap outside", "navigate to settings",
                 "aggregate the totals", "delegate it to the host"):
        assert visitor_detail(kept, blocked=False, fallback="DROPPED") != "DROPPED", kept
    for dropped in ("3 candidates in Expedition 14", "the non-negotiables", "which rung is it on",
                    "the north star says no", "check the vessel's standards"):
        assert visitor_detail(dropped, blocked=False, fallback="DROPPED") == "DROPPED", dropped


def test_a_run_that_is_asking_holds_the_door_and_says_so(tmp_path):
    """Same as every other gate: one at a time. The difference is what it is waiting for."""
    c = _client(tmp_path, seed=[_exp(3, status="await-answer", rung=1)])
    body = c.get("/demo/active").json()
    assert body["can_request"] is False
    assert body["active"]["status"] == "Waiting for your answer"


def test_only_an_answer_moves_a_run_that_is_asking(tmp_path, monkeypatch):
    """`/pick` would write the wireframe check-mark artifact — there are no wireframes yet — and
    `/approve` would approve nothing. Both are refused where the run cannot use them."""
    from fls.app import _SIGNALS_A_RUN_CAN_USE, _WHAT_IT_WANTS
    assert _SIGNALS_A_RUN_CAN_USE["await-answer"] == {"feedback"}
    assert "ANSWER" in _WHAT_IT_WANTS["await-answer"]


def test_an_open_question_does_not_mention_letters():
    """INSUFFICIENT asks in words and has no options; a hint about letters there sends the person
    looking for a list that does not exist."""
    view = demo_view({"number": 9, "intent": "make it bigger", "rung": 1, "status": "await-answer"},
                     {"running": True, "artifacts": {"question": {
                         "ask": "The request names no surface. Say what should change on screen.",
                         "options": []}}}, {})
    assert view["question"]["options"] == []
    assert "letter" not in view["question"]["how"]
    lettered = demo_view({"number": 9, "intent": "x", "rung": 1, "status": "await-answer"},
                         {"running": True, "artifacts": {"question": {
                             "ask": "which?", "options": ["a thing", "something else"]}}}, {})
    assert "letter" in lettered["question"]["how"]


# ── something to try, for a visitor who has not thought of a request ───────────────────────

def _sugg(*pairs):
    from fls.anchor import Suggestion
    return [Suggestion(intent=i, success=s) for i, s in pairs]


def test_the_first_unused_suggestion_is_the_one_offered():
    from fls.demo import suggestion_for
    subs = _sugg(("Show the blind schedule", "I can see it before I buy in"),
                 ("Add a what-beats-what card", "It opens from the table"))
    assert suggestion_for(subs, [])["intent"] == "Show the blind schedule"
    assert suggestion_for(subs, [{"intent": "Show the blind schedule"}])["intent"] == \
        "Add a what-beats-what card"


def test_an_idea_leaves_the_list_by_being_used_however_it_was_typed():
    """A queue, not a rotation — and nothing is written back when a visitor takes one, because
    the record of what was filed IS the record of what was consumed."""
    from fls.demo import suggestion_for
    subs = _sugg(("Show the blind schedule", ""), ("Add a what-beats-what card", ""))
    wall = [{"intent": "  show   THE Blind   schedule\n"}]
    assert suggestion_for(subs, wall)["intent"] == "Add a what-beats-what card"


def test_an_exhausted_list_offers_nothing_rather_than_repeating():
    from fls.demo import suggestion_for
    subs = _sugg(("One", ""), ("Two", ""))
    assert suggestion_for(subs, [{"intent": "One"}, {"intent": "Two"}]) is None
    assert suggestion_for([], []) is None
    assert suggestion_for(None, None) is None


def test_a_suggestion_that_trips_the_leak_guard_is_skipped_not_blanked():
    """These are authored in an ANCHOR beside text that is not written for a stranger. A
    suggestion with half its words missing is worse than the next one down."""
    from fls.demo import suggestion_for
    subs = _sugg(("check the rung budget before the gate", ""), ("Show the blind schedule", ""))
    assert suggestion_for(subs, [])["intent"] == "Show the blind schedule"


def test_a_suggestion_needs_no_success_line():
    from fls.demo import suggestion_for
    assert suggestion_for(_sugg(("Show the blind schedule", "")), [])["success"] == ""


def test_the_public_payload_always_carries_the_key(tmp_path):
    """All three shapes of /demo/active, so the page never has to test for its absence."""
    c = _client(tmp_path)
    assert "suggestion" in c.get("/demo/active").json()
    c2 = _client(tmp_path, seed=[_exp(3, status=CLIMBING, rung=2)])
    assert "suggestion" in c2.get("/demo/active").json()
    c3 = _client(tmp_path, seed=[_exp(1, status=DOCKED, rung=5)])
    assert "suggestion" in c3.get("/demo/active").json()


def test_an_anchor_with_no_demo_block_suggests_nothing(tmp_path):
    """The shipped example ANCHOR declares no suggestions, so the OSS default is a page that
    offers none — the mechanism is generic, the content is an instance's own."""
    from fls.anchor import Anchor
    # Resolved from this file, not the working directory: three modules already read ANCHOR.md by
    # a relative path and break when pytest is run from `engine/` instead of the repo root.
    shipped = Path(__file__).resolve().parents[2] / "ANCHOR.md"
    assert Anchor.load(shipped).demo.suggestions == []
    assert _client(tmp_path).get("/demo/active").json()["suggestion"] is None


def test_a_broken_anchor_costs_the_suggestion_and_not_the_page(tmp_path, monkeypatch):
    """This is a public surface. An ANCHOR that cannot be read is a reason to suggest nothing,
    never a reason to 500 at a stranger."""
    from fls import app as appmod
    monkeypatch.setattr(appmod, "_anchor", lambda: (_ for _ in ()).throw(RuntimeError("no anchor")))
    body = _client(tmp_path).get("/demo/active").json()
    assert body["suggestion"] is None and body["can_request"] is True


def test_the_instance_list_can_be_shown_to_a_stranger():
    """Every suggestion this instance actually ships passes the leak guard. Skipped where the
    instance ANCHOR is not checked out — the OSS tree must not depend on it."""
    import os

    from fls.anchor import Anchor
    from fls.demo import suggestion_for
    path = os.environ.get("FLS_ANCHOR_PATH") or os.path.expanduser(
        "~/workspace/acme/governance/ANCHOR.md")
    if not os.path.exists(path):
        pytest.skip("no instance ANCHOR here")
    subs = Anchor.load(path).demo.suggestions
    if not subs:
        pytest.skip("this instance declares no suggestions")
    for one in subs:
        got = suggestion_for([one], [])
        assert got is not None, f"a shipped suggestion is unshowable: {one.intent[:60]!r}"
        assert got["intent"] == one.intent

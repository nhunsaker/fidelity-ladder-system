"""Marking a pull request ready for review is what puts a change on the stage site.

Until now nothing did: staging happened at rung 5a the moment the draft opened — decided by
nobody, and before the checks had necessarily finished. A draft is by definition not ready, and
marking it ready is a person saying so, which is the kind of decision this system gives to a
person rather than to a timer.

The gate is fail-closed in all three ways it can fail, and each says which on the pull request:
pending checks wait, failing checks refuse and name what failed, and an unreadable gate refuses —
a gate that opens when it cannot see is not a gate.
"""
from __future__ import annotations

from pathlib import Path

from fls.anchor import Anchor
from fls.github_surface import handle_event
from fls.ledger import Ledger
from fls.store import ExpeditionStore

ANCHOR = Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


class FakeClient:
    """Records comments; answers check state from a script."""

    def __init__(self, state=("green", "3 checks passed"), pr=None):
        self.state, self.comments, self._pr = state, [], pr or {}

    def checks_state(self, sha):
        return self.state

    def post_comment(self, number, body):
        self.comments.append((number, body))

    def add_label(self, *a, **k):
        pass

    def _req(self, method, path, payload=None):
        return self._pr


class FakeDeployer:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def deploy(self, env, ref, artifact=None):
        # `artifact` is recorded because it is the whole difference between publishing a site and
        # publishing a seven-byte marker — the bug this file grew a section for.
        self.calls.append((env, ref, artifact is not None))
        return self.ok


def _pr(number=5, sha="a" * 40, draft=False):
    return {"number": number, "draft": draft, "head": {"sha": sha}}


def _fire(payload, client, deploy, tmp_path, event="pull_request", action="ready_for_review"):
    store = ExpeditionStore(tmp_path)
    return handle_event(event, {"action": action, **payload}, ANCHOR, "", None,
                        store, Ledger(tmp_path / "l.jsonl"), client, deploy=deploy)


def test_green_checks_start_the_build_and_promise_nothing_yet(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_STAGE_URL", "https://stage.example.com")
    c, d = FakeClient(), FakeDeployer()
    out = _fire({"pull_request": _pr()}, c, d, tmp_path)
    # The webhook only STARTS the work now — building takes minutes and GitHub gives a webhook
    # ten seconds. The publish step is exercised directly further down.
    assert out["staged"] == "building"
    assert "Building" in c.comments[-1][1] and "aaaaaaa" in c.comments[-1][1]


def test_failing_checks_refuse_and_name_what_failed(tmp_path):
    """"Not staged" on its own teaches nobody anything — the reviewer needs to know which check,
    because the next thing they do is fix it."""
    c = FakeClient(state=("red", "failing: Check types (failure)"))
    d = FakeDeployer()
    out = _fire({"pull_request": _pr()}, c, d, tmp_path)
    assert out["staged"] is False and d.calls == []
    assert "Check types" in c.comments[-1][1]


def test_pending_checks_wait_rather_than_refuse(tmp_path):
    """A PR marked ready while CI is still running is the common case, and refusing it would be
    wrong twice: nothing has failed, and the reviewer would have to do something to retry."""
    c = FakeClient(state=("pending", "still running: Build static export"))
    d = FakeDeployer()
    out = _fire({"pull_request": _pr()}, c, d, tmp_path)
    assert out["staged"] is False and d.calls == []
    assert "not finished" in c.comments[-1][1].lower()


def test_an_unreadable_gate_refuses(tmp_path):
    """A gate that opens when it cannot see is not a gate."""
    c = FakeClient(state=("unknown", "could not read the checks: 403"))
    d = FakeDeployer()
    assert _fire({"pull_request": _pr()}, c, d, tmp_path)["staged"] is False
    assert d.calls == []


def test_a_deployer_that_refuses_is_not_reported_as_staged(tmp_path):
    """Every built-in deployer fails closed to False. Saying "staged" over one of those would be
    the falsehood this whole system exists to refuse."""
    c, d = FakeClient(), FakeDeployer(ok=False)
    from fls.github_surface import _publish
    _publish("a" * 40, 5, "ok", c, c, d, _pr())
    assert d.calls and d.calls[0][2] is False      # no build configured -> ref only
    assert "did not happen" in c.comments[-1][1]


def test_a_draft_is_never_staged(tmp_path):
    c, d = FakeClient(), FakeDeployer()
    out = _fire({"pull_request": _pr(draft=True)}, c, d, tmp_path)
    assert out.get("staged") is not True and d.calls == []


def test_checks_completing_later_stages_the_pull_request(tmp_path):
    """The other half of the pending case. Without this, a PR marked ready before CI finished
    would simply never deploy — and a gate that silently does nothing is indistinguishable from
    a feature that does not work."""
    c = FakeClient(pr=_pr(number=5, sha="b" * 40))
    d = FakeDeployer()
    out = _fire({"check_suite": {"pull_requests": [{"number": 5}]}}, c, d, tmp_path,
                event="check_suite", action="completed")
    assert out["staged"] == "building" and out["sha"] == "b" * 40


def test_checks_completing_on_a_draft_stage_nothing(tmp_path):
    """A check_suite payload carries a THIN pull-request stub with no `draft` flag, so the real
    one is fetched. Deciding from the stub would stage every draft whose CI went green."""
    c = FakeClient(pr=_pr(number=5, draft=True))
    d = FakeDeployer()
    out = _fire({"check_suite": {"pull_requests": [{"number": 5}]}}, c, d, tmp_path,
                event="check_suite", action="completed")
    assert out.get("staged") is not True and d.calls == []


# ── what the comment claims ────────────────────────────────────────────────────────────────

def test_the_staged_comment_does_not_claim_the_feature_is_live():
    """The first version read "Staged from <sha>. It is live at <url>." The BUILD is live; the
    FEATURE is not, because it ships behind a flag that is off. Somebody following that link sees
    the app exactly as it was and reasonably concludes the deploy did nothing.

    Confirmed on the real thing: PR #5 staged from 93d1dd4 and said "It is live at
    stage.example.com" while `table-reactions` was false in both environments.
    """
    from fls.github_surface import _staged_comment

    body = _staged_comment("93d1dd4aaa", "1 checks passed", "https://stage.example.com",
                           "table-reactions")
    assert "It is live" not in body
    assert "looks unchanged" in body
    assert "table-reactions" in body and "flags.json" in body
    assert "prod" in body, "the reader is not told production stays off"


def test_with_no_flag_to_name_it_still_says_the_feature_is_off():
    """Two flags in one change leaves nothing honest to name — but "the site will look unchanged"
    is the part that stops somebody thinking the deploy failed, and it is true either way."""
    from fls.github_surface import _staged_comment

    body = _staged_comment("93d1dd4aaa", "ok", "https://stage.example.com", "")
    assert "It is live" not in body and "look unchanged" in body


def test_no_public_url_is_said_rather_than_implied():
    """An instance that stages to a directory nobody serves should not print a link to nothing."""
    from fls.github_surface import _staged_comment

    body = _staged_comment("93d1dd4aaa", "ok", "", "some-flag")
    assert "http" not in body and "no public URL" in body


# ── the publish step: what actually reaches the stage directory ────────────────────────────

def test_a_marker_is_never_reported_as_a_staged_site(tmp_path, monkeypatch):
    """THE BUG THIS SECTION EXISTS FOR. The static-dir deployer publishes FILES only when handed
    an already-built directory; called with a ref alone it writes a seven-byte DEPLOYED marker and
    returns True. The webhook called it that way, then commented "🚀 Staged from a9793ac" while
    the stage site went on serving bytes from hours earlier.

    An instance that declares no build command is in a real mode — record the ref, publish no
    files — and it is now SAID, because "staged" over a marker is the same falsehood in a quieter
    voice.
    """
    from fls.github_surface import _publish

    monkeypatch.delenv("FLS_VESSEL_BUILD_CMD", raising=False)
    c, d = FakeClient(), FakeDeployer()
    _publish("a" * 40, 5, "ok", c, c, d, _pr())
    body = c.comments[-1][1]
    assert "Recorded" in body and "no files were published" in body
    assert "Staged" not in body


def test_a_built_site_is_handed_to_the_deployer(tmp_path, monkeypatch):
    """And when there IS a build, the built directory reaches the seam — which is the only way
    files ever move."""
    import fls.github_surface as gs

    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setattr("fls.stage_build.build_ref", lambda sha, **k: (site, None))
    monkeypatch.setenv("FLS_STAGE_URL", "https://stage.example.com")
    c, d = FakeClient(), FakeDeployer()
    gs._publish("a" * 40, 5, "1 checks passed", c, c, d, _pr())
    assert d.calls and d.calls[0][2] is True, "the deployer got a ref with no artifact"
    assert "Staged from" in c.comments[-1][1]


def test_a_failing_build_publishes_nothing_and_says_so(tmp_path, monkeypatch):
    import fls.github_surface as gs

    monkeypatch.setattr("fls.stage_build.build_ref",
                        lambda sha, **k: (None, "the vessel build failed: type error"))
    c, d = FakeClient(), FakeDeployer()
    gs._publish("a" * 40, 5, "ok", c, c, d, _pr())
    assert d.calls == []
    assert "type error" in c.comments[-1][1] and "Nothing was published" in c.comments[-1][1]


def test_the_comment_offers_the_url_not_a_file_edit():
    """"Edit flags.json and push" is a commit, a CI run and a deploy to answer "what does it look
    like" — the slow way round for the first thing a reviewer does. The override exists now, and
    it is stage-only by design, which is exactly what this comment is about."""
    from fls.github_surface import _staged_comment

    body = _staged_comment("015c2e5aa", "ok", "https://stage.example.com", "table-reactions")
    assert "https://stage.example.com?flags-table-reactions=true" in body
    assert "your browser only" in body and "?flags-reset" in body
    # The durable route still gets a mention — it is how everyone else sees it.
    assert "flags.json" in body and "prod" in body
    # And the URL is offered BEFORE the file edit, because it is the one they want first.
    assert body.index("flags-table-reactions=true") < body.index("flags.json")

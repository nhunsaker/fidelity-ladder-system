"""A notification we cannot deliver must not re-open a decision we already made.

2026-09-11, live: the fine-grained PAT lacked `Issues: write`. The admission gate ran, judged and
SAVED expedition #3 — and then `set_labels` raised straight out of `handle_event`. The endpoint
answered 500 and GitHub logged a failed delivery. Redelivering that payload would have re-run the
gate: a second adjudicator call against a paid API, a second ledger row, for a decision already
taken. A cosmetic permission gap was one click away from costing money and corrupting the record.

Fail-closed governs DECISIONS. It must never govern notifications.
"""
from __future__ import annotations

import pytest
from conftest import ANCHOR_MD

from fls.anchor import Anchor, Verdict
from fls.github_surface import handle_event
from fls.ledger import Ledger
from fls.store import ExpeditionStore


class _RefusingClient:
    """Every write raises, exactly as a token without `Issues: write` does."""
    def __init__(self):
        self.attempts = []

    def post_comment(self, issue, text):
        self.attempts.append("post_comment")
        raise PermissionError("403: Resource not accessible by personal access token")

    def set_labels(self, issue, labels):
        self.attempts.append("set_labels")
        raise PermissionError("403: Resource not accessible by personal access token")

    def create_deployment(self, env, ref):
        return False

    def get_issue(self, issue):
        return {}

    def list_comments(self, issue):
        return []


class _Judge:
    def decide(self, *a, **k):
        raise AssertionError("unused")


@pytest.fixture
def _harness(tmp_path):
    store = ExpeditionStore(tmp_path)
    return store, Ledger(tmp_path / "ledger.jsonl")


def _payload(number=3):
    return {"action": "opened",
            "issue": {"number": number, "title": "[idea] a small thing",
                      "body": "### Intent\na small thing\n\n### Success criteria\nit works\n"}}


def test_a_refused_label_does_not_raise_and_the_decision_stands(_harness, monkeypatch, tmp_path):
    store, ledger = _harness
    anchor = Anchor.load(ANCHOR_MD)
    client = _RefusingClient()

    # a judge that admits, so we take the branch that failed in production
    monkeypatch.setattr("fls.github_surface.on_idea",
                        lambda *a, **k: (Verdict.admit, "in scope"))

    result = handle_event("issues", _payload(), anchor, "", object(), store, ledger, client)

    assert result["verdict"] == "admit"
    assert store.get(3) is not None, "the expedition must be saved despite the failed write-back"
    # the failure is REPORTED, not swallowed silently and not raised
    assert result["notify_errors"], "a failure nobody can see is the other way to get this wrong"
    assert any("403" in e for e in result["notify_errors"])
    assert "set_labels" in client.attempts and "post_comment" in client.attempts, \
        "one failed notification must not skip the next"


def test_a_deployment_failure_is_NOT_swallowed():
    """The line between the two. A deployment is an action the caller branches on; reporting one
    that did not happen is the failure mode the whole deploy seam exists to prevent."""
    from fls.github_surface import _Notifier

    class _Boom:
        def create_deployment(self, env, ref):
            return False

    assert _Notifier(_Boom()).create_deployment("stage", "HEAD") is False

"""GitHub sends a webhook as EITHER JSON or form-encoded, and the form is its own DEFAULT.

This handler assumed JSON. A hook created by hand in GitHub's UI — which is how the harness's own
hook was created on 2026-09-11 — therefore arrived form-encoded, `request.json()` raised, and the
endpoint answered 500. The signature had already verified, so the only thing wrong was ours.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from fls import app as appmod

SECRET = "test-secret"
PING = {"zen": "Non-blocking is better than blocking.", "hook_id": 1}


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", SECRET)


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def _post(body: bytes, content_type: str, event: str = "ping"):
    return TestClient(appmod.app).post(
        "/webhook/github", content=body,
        headers={"content-type": content_type, "X-GitHub-Event": event,
                 "X-Hub-Signature-256": _sig(body)})


def test_form_encoded_ping_is_accepted():
    """The exact shape that 500'd in production."""
    body = urlencode({"payload": json.dumps(PING)}).encode()
    r = _post(body, "application/x-www-form-urlencoded")
    assert r.status_code == 200, r.text
    assert r.json()["event"] == "ping"


def test_json_ping_is_accepted():
    body = json.dumps(PING).encode()
    r = _post(body, "application/json")
    assert r.status_code == 200, r.text
    assert r.json()["event"] == "ping"


def test_both_encodings_verify_against_the_same_signature():
    """Signing is over the RAW bytes, so switching content type must not change verification.
    Pinning this because 'the signature broke when we changed the content type' is the wrong
    conclusion someone could reach from the outage this test came from."""
    for body, ct in ((json.dumps(PING).encode(), "application/json"),
                     (urlencode({"payload": json.dumps(PING)}).encode(),
                      "application/x-www-form-urlencoded")):
        assert _post(body, ct).status_code == 200


def test_an_unparseable_body_is_refused_with_a_reason_not_a_500():
    body = b"not json and not a form"
    r = _post(body, "application/json")
    assert r.status_code == 400, "a body we cannot parse is a refusal, never a traceback"
    assert "neither JSON nor a form" in r.text


def test_a_form_body_with_no_payload_field_is_refused():
    body = urlencode({"something_else": "x"}).encode()
    assert _post(body, "application/x-www-form-urlencoded").status_code == 400


def test_a_bad_signature_is_still_refused_for_both_encodings():
    """The fix must not have widened what gets in. 403 before any parsing happens."""
    for body, ct in ((json.dumps(PING).encode(), "application/json"),
                     (urlencode({"payload": json.dumps(PING)}).encode(),
                      "application/x-www-form-urlencoded")):
        r = TestClient(appmod.app).post(
            "/webhook/github", content=body,
            headers={"content-type": ct, "X-GitHub-Event": "ping",
                     "X-Hub-Signature-256": "sha256=" + "0" * 64})
        assert r.status_code == 403

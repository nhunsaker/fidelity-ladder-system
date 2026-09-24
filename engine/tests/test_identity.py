"""The identity seam — Principal, SignedSession, Policy, and the fail-closed `none` default.

All $0: no network, no creds, no clock-sleeping (every expiry test injects `now`, the
`now=time.time()` precedent app.py already sets). Fixtures use `octocat` / `alice@example.com` —
never a real person's handle, because test fixtures outlive the person who wrote them.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from fls import app as appmod
from fls import modules
from fls.anchor import Anchor
from fls.identity import (
    OPERATOR_AUDIENCE,
    NoneIdentity,
    Policy,
    Principal,
    SignedSession,
    active_kind,
    resolve,
)

ALICE = Principal(subject="583231", login="octocat", name="Alice Example",
                  email="alice@example.com", provider="github")


def _anchor() -> Anchor:
    from pathlib import Path
    return Anchor.load(Path(__file__).resolve().parents[2] / "ANCHOR.md")


# ── the default posture ───────────────────────────────────────────────────────
def test_identity_defaults_to_none_with_no_env(monkeypatch):
    monkeypatch.delenv("FLS_IDENTITY_KIND", raising=False)
    assert active_kind() == "none"
    assert isinstance(resolve(), NoneIdentity)


def test_identity_none_reports_unconfigured_and_unavailable(monkeypatch):
    """The deliberate inversion of `auth`'s `none`, which reports True/True.

    Local-mode AUTH is a complete posture: no App, so no webhook, so refusing every signature is
    correct. Nobody authenticating an exposed console is not a posture, it is a hazard — and
    reflection has to say so or the System card presents an open door as a settled setting.
    """
    monkeypatch.delenv("FLS_IDENTITY_KIND", raising=False)
    slots = modules.describe(_anchor())
    ident, auth = slots["identity"], slots["auth"]
    assert ident["kind"] == "none"
    assert ident["configured"] is False and ident["available"] is False
    assert auth["configured"] is True and auth["available"] is True  # the contrast, asserted
    assert ident["detail"]["scope"] == "session"
    assert auth["detail"]["scope"] == "message"


def test_describe_exposes_identity_through_the_system_route(monkeypatch):
    monkeypatch.delenv("FLS_IDENTITY_KIND", raising=False)
    body = TestClient(appmod.app).get("/system").json()
    assert body["slots"]["identity"]["kind"] == "none"


def test_unknown_kind_falls_back_to_none_rather_than_500(monkeypatch, caplog):
    """A typo in FLS_IDENTITY_KIND must not turn every request into a 500. It surfaces on
    /system instead — visible, and not an outage."""
    monkeypatch.setenv("FLS_IDENTITY_KIND", "githubb-oauth")
    assert isinstance(resolve(), NoneIdentity)


def test_none_identity_refuses_to_begin_and_completes_nobody():
    ident = NoneIdentity()
    with pytest.raises(RuntimeError):
        ident.begin(redirect_uri="https://x.test/cb", state="s", nonce="n")
    assert ident.complete({"code": "anything"}, redirect_uri="https://x.test/cb", nonce="n") is None


# ── SignedSession ─────────────────────────────────────────────────────────────
def test_session_round_trips_a_principal():
    s = SignedSession(secrets=("k1",))
    got = s.verify(s.mint(ALICE, now=1000), now=1001)
    assert got == ALICE


def test_session_unconfigured_mints_nothing_and_verifies_nothing():
    """No secret is not 'sign with an empty key'. It is refuse."""
    s = SignedSession(secrets=())
    assert s.mint(ALICE) == ""
    assert s.verify("anything.at.all") is None


def test_expired_and_forged_sessions_refuse():
    s = SignedSession(secrets=("k1",), ttl_s=60)
    token = s.mint(ALICE, now=1000)
    assert s.verify(token, now=1000 + 61) is None            # expired
    assert SignedSession(secrets=("other",)).verify(token, now=1001) is None   # forged
    payload, _, _sig = token.rpartition(".")
    assert s.verify(f"{payload}.deadbeef", now=1001) is None  # tampered signature


@pytest.mark.parametrize("junk", ["", "nodot", ".", "..", "a.b.c", "x" * 500])
def test_malformed_tokens_never_raise(junk):
    assert SignedSession(secrets=("k1",)).verify(junk) is None


def test_a_colon_in_a_display_name_survives():
    """The reason the payload is base64url JSON and not colon-joined: `rsplit(":", 2)` on a
    name containing a colon silently produced the wrong fields."""
    weird = Principal(subject="1", login="octocat", name="Smith: J", provider="github")
    s = SignedSession(secrets=("k1",))
    assert s.verify(s.mint(weird, now=1000), now=1001).name == "Smith: J"


def test_secret_rotation_verifies_old_signs_new():
    """Rotation must not be a forced logout — that is the thing that makes people not rotate."""
    old, new = SignedSession(secrets=("old",)), SignedSession(secrets=("new", "old"))
    token = old.mint(ALICE, now=1000)
    assert new.verify(token, now=1001) == ALICE          # sessions minted under the old key live
    fresh = new.mint(ALICE, now=1000)
    assert old.verify(fresh, now=1001) is None           # ...and new ones are signed with the new


def test_epoch_bump_invalidates_all():
    a = SignedSession(secrets=("k1",), epoch="1")
    token = a.mint(ALICE, now=1000)
    assert SignedSession(secrets=("k1",), epoch="2").verify(token, now=1001) is None


def test_session_payload_carries_no_secret():
    import base64
    s = SignedSession(secrets=("supersecretkey",))
    payload = s.mint(ALICE, now=1000).rpartition(".")[0]
    body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert "supersecretkey" not in json.dumps(body)
    assert body["audience"] == OPERATOR_AUDIENCE


def test_session_from_env_reads_at_call_time(monkeypatch):
    monkeypatch.setenv("FLS_SESSION_SECRET", " k1 , k2 ")
    assert SignedSession.from_env().secrets == ("k1", "k2")
    monkeypatch.delenv("FLS_SESSION_SECRET")
    assert SignedSession.from_env().configured is False


# ── Policy ────────────────────────────────────────────────────────────────────
def test_policy_allowlist_denies_non_member():
    p = Policy(allowed=frozenset({"octocat"}))
    assert p.permits(ALICE) is True
    assert p.permits(Principal(subject="9", login="stranger")) is False


def test_policy_matches_login_case_insensitively_and_by_subject():
    p = Policy(allowed=frozenset({"octocat", "583231"}))
    assert p.permits(Principal(subject="0", login="OctoCat")) is True
    assert p.permits(Principal(subject="583231", login="renamed")) is True  # survives a rename


def test_policy_fails_closed_when_neither_mode_set():
    """Identity on and nobody named is a half-finished deployment far more often than it is a
    deliberate invitation to the internet."""
    p = Policy()
    assert p.configured is False and p.name == "unset"
    assert p.permits(ALICE) is False


def test_policy_allow_any_admits_any_authenticated():
    p = Policy(allow_any=True)
    assert p.permits(ALICE) is True and p.name == "any-authenticated"


def test_allowlist_beats_allow_any():
    p = Policy(allowed=frozenset({"octocat"}), allow_any=True)
    assert p.permits(Principal(subject="9", login="stranger")) is False


def test_policy_refuses_a_non_operator_audience():
    """The audience-conflation guard, at the policy layer. A demo visitor's session must never
    satisfy an operator check even if every other field lines up."""
    visitor = Principal(subject="583231", login="octocat", audience="demo")
    assert Policy(allowed=frozenset({"octocat"})).permits(visitor) is False
    assert Policy(allow_any=True).permits(visitor) is False


def test_policy_from_env(monkeypatch):
    monkeypatch.setenv("FLS_ALLOWED_USERS", "Octocat, hubot ")
    monkeypatch.delenv("FLS_ALLOW_ANY_AUTHENTICATED", raising=False)
    p = Policy.from_env()
    assert p.allowed == frozenset({"octocat", "hubot"})
    assert p.detail() == {"policy": "allowlist", "allowlist_count": 2}


# ── the reflection leak gate ──────────────────────────────────────────────────
def test_system_never_leaks_client_secret_or_allowlist_values(monkeypatch):
    monkeypatch.setenv("FLS_IDENTITY_KIND", "none")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "shhh-secret-value")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "Ov23liEXAMPLEID")
    monkeypatch.setenv("FLS_SESSION_SECRET", "sessionsecretvalue")
    monkeypatch.setenv("FLS_ALLOWED_USERS", "octocat,hubot")
    raw = json.dumps(TestClient(appmod.app).get("/system").json())
    for leaked in ("shhh-secret-value", "Ov23liEXAMPLEID", "sessionsecretvalue",
                   "octocat", "hubot"):
        assert leaked not in raw, f"/system leaked {leaked!r}"
    ident = json.loads(raw)["slots"]["identity"]
    assert ident["detail"]["allowlist_count"] == 2      # the count is fine; the names are not
    assert ident["detail"]["session_secret_set"] is True


# ── hosted providers (Clerk, Auth0, WorkOS ...) ───────────────────────────────
def test_policy_can_allowlist_an_email():
    """Many OIDC providers issue no `preferred_username`, so the only identifier a human can
    type into a config file is the address they sign in with."""
    p = Policy(allowed=frozenset({"alice@example.com"}))
    who = Principal(subject="user_2abc", login="", email="Alice@Example.com", provider="oidc")
    assert p.permits(who) is True
    assert p.permits(Principal(subject="user_9", email="mallory@example.com")) is False


def test_allowlisting_by_email_does_not_put_it_in_the_ledger():
    """Matching on an address must not make it the recorded actor — the ledger is append-only."""
    from fls.identity import Principal as P
    who = P(subject="user_2abc", login="", email="alice@example.com", provider="oidc")
    assert Policy(allowed=frozenset({"alice@example.com"})).permits(who) is True
    assert who.subject == "user_2abc"        # what the ledger stores
    assert "@" not in who.subject


def test_allow_any_authenticated_admits_a_hosted_provider_user():
    """The other mode the founder asked for: Clerk (or whoever) decides WHO may authenticate,
    FLS admits all of them."""
    who = Principal(subject="user_2abc", email="anyone@example.com", provider="oidc")
    assert Policy(allow_any=True).permits(who) is True
    assert Policy().permits(who) is False     # neither mode set still fails closed


def test_discovery_falls_back_to_the_oauth_metadata_path(monkeypatch):
    """OIDC defines openid-configuration; RFC 8414 defines oauth-authorization-server. Providers
    publish one, the other, or both — Clerk documents the latter."""
    from fls import identity as ident
    monkeypatch.setenv("FLS_OIDC_ISSUER", "https://clerk.example.com")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "csec")
    seen = []

    def get_json(url, headers=None):
        seen.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return {}                                    # not published here
        return {"authorization_endpoint": "https://clerk.example.com/oauth/authorize"}

    monkeypatch.setattr(ident, "_get_json", get_json)
    doc = ident.OidcIdentity().discover()
    assert doc["authorization_endpoint"].endswith("/oauth/authorize")
    assert any("oauth-authorization-server" in u for u in seen)


def test_a_refusal_names_what_to_add_without_dumping_the_email():
    """"Refused by policy" alone is a dead end — different providers issue different
    identifiers, so the operator cannot tell what to put in the allowlist."""
    c = Policy.candidates(Principal(subject="user_2abc", login="nate",
                                    email="alice@example.com"))
    assert "sub=user_2abc" in c and "login=nate" in c
    assert "a***@example.com" in c
    assert "alice@example.com" not in c          # masked, not harvestable
    bare = Policy.candidates(Principal(subject="user_9"))
    assert bare == "sub=user_9"

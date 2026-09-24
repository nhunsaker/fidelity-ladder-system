"""The /auth routes, the deny-by-default guard, and the structural route-inventory gate.

Offline throughout: a stub provider kind is registered into `modules.IDENTITY` for the browser
leg, and the two transport functions are monkeypatched for the real kinds. Nothing here touches
the network, and nothing sleeps — every expiry test injects `now`.

Assertions about cookie flags read the RAW `set-cookie` header, not httpx's cookie jar: the jar
does not expose HttpOnly or SameSite, so asserting through it would pass while the flags were
missing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fls import app as appmod
from fls import modules
from fls.identity import (
    Principal,
    SignedSession,
    StateSigner,
    principal_from_github,
    principal_from_oidc,
    safe_return_to,
)

SECRET = "test-session-secret"
ALICE = Principal(subject="583231", login="octocat", name="Alice Example", provider="stub")


class StubIdentity:
    """A provider that authenticates one fixed person with no network. Registered as a kind so
    the routes exercise the real registry path rather than a patched function."""
    kind = "stub"
    principal: Principal | None = ALICE

    def begin(self, *, redirect_uri, state, nonce, verifier=""):
        from fls.identity import Challenge
        return Challenge(redirect_url=f"https://idp.test/authorize?state={state}",
                         state=state, nonce=nonce, verifier=verifier)

    def complete(self, params, *, redirect_uri, nonce, verifier=""):
        return type(self).principal

    def configured(self): return True
    def available(self): return True
    def detail(self): return {"provider": "stub"}


@pytest.fixture
def stub_kind(monkeypatch):
    monkeypatch.setitem(modules.IDENTITY, "stub", lambda **kw: StubIdentity())
    monkeypatch.setenv("FLS_IDENTITY_KIND", "stub")
    monkeypatch.setenv("FLS_SESSION_SECRET", SECRET)
    monkeypatch.setenv("FLS_AUTH_REDIRECT_URI", "https://harness.test/api/auth/callback")
    monkeypatch.setenv("FLS_ALLOWED_USERS", "octocat")
    monkeypatch.setenv("FLS_COOKIE_SECURE", "0")   # TestClient speaks http://testserver
    StubIdentity.principal = ALICE
    yield
    StubIdentity.principal = ALICE


@pytest.fixture
def client():
    return TestClient(appmod.app, follow_redirects=False)



def _refused(r, reason: str | None = None) -> bool:
    """A sign-in refusal: bounced back to the console with an error, and NO session issued.

    Asserting "no session" rather than "status 400" is the assertion that actually matters —
    the status code is a delivery detail, whereas a refusal that still set a cookie would be
    the bug. The callback stopped returning JSON errors because reputation crawlers follow this
    URL without a cookie, and handing them a machine-shaped body while a human gets a page is
    cloaking-shaped.
    """
    if r.status_code != 302:
        return False
    if "auth_error" not in r.headers.get("location", ""):
        return False
    if reason and reason not in r.headers["location"]:
        return False
    return "fls_session" not in r.cookies


def _signed_in(client) -> str:
    """Drive the real browser leg and return the session cookie value."""
    start = client.get("/auth/login?return_to=/%23/exp/12")
    assert start.status_code == 302
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    done = client.get(f"/auth/callback?code=abc&state={state}",
                      cookies={"fls_auth_nonce": nonce})
    assert done.status_code == 302, done.text
    return done.cookies["fls_session"]


# ── the default: dormant ──────────────────────────────────────────────────────
def test_guard_is_dormant_with_no_identity_configured(monkeypatch, client):
    monkeypatch.delenv("FLS_IDENTITY_KIND", raising=False)
    assert client.get("/wall").status_code == 200
    me = client.get("/auth/me").json()
    assert me["authenticated"] is False and me["identity"] == "none"


def test_login_404s_when_no_provider_is_configured(monkeypatch, client):
    monkeypatch.delenv("FLS_IDENTITY_KIND", raising=False)
    assert client.get("/auth/login").status_code == 404


# ── the structural gate ───────────────────────────────────────────────────────
def test_every_route_is_classified_public_or_protected(stub_kind, client):
    """The mechanism that keeps this from rotting.

    Every route on the app must be either declared public (with the mechanism that guards it
    named) or return 401 without a session. Add a route and forget to decide which — this fails.
    It is a route inventory, not a code trick, so it also catches a route added in a module that
    nobody thought to re-read.
    """
    paths = sorted({r.path for r in appmod.app.routes if getattr(r, "path", None)})
    allowed = appmod.public_paths()
    unguarded = []
    for path in paths:
        if appmod._is_public(path, allowed):
            continue
        probe = path.replace("{number}", "1").replace("{name}", "x")
        r = client.request("GET", probe)
        if r.status_code != 401:
            unguarded.append((path, r.status_code))
    assert not unguarded, f"routes neither public nor guarded: {unguarded}"


def test_public_paths_name_the_mechanism_not_just_the_path(stub_kind):
    """A set of exempt paths loses the difference between 'open' and 'guarded by something
    else'. /webhook/github is not open — it is HMAC-verified."""
    allowed = appmod.public_paths()
    assert "HMAC" in allowed["/webhook/github"]
    assert all(v.strip() for v in allowed.values())


def test_webhook_stays_reachable_without_a_session(stub_kind, client):
    """The guard must not shadow the webhook's own fail-closed HMAC check: a 401 here would
    make every delivery look like a signature problem."""
    r = client.post("/webhook/github", json={}, headers={"X-GitHub-Event": "ping"})
    assert r.status_code == 403           # refused by signature verification, NOT by the guard
    assert "signature" in r.text


def test_anchor_policy_decides_whether_preview_is_public(stub_kind, client, monkeypatch):
    r = client.get("/preview/999")
    assert r.status_code == 404           # public per the default ANCHOR: missing, not refused

    real = appmod._anchor()
    narrowed = real.model_copy(update={"identity": real.identity.model_copy(
        update={"public_surfaces": ["demo"]})})
    monkeypatch.setattr(appmod, "_anchor", lambda: narrowed)
    assert client.get("/preview/999").status_code == 401     # now behind the login
    assert client.get("/demo/active").status_code in (200, 500)  # still public


def test_an_unreadable_anchor_does_not_open_surfaces(stub_kind, client, monkeypatch):
    """Fail-closed: if the ANCHOR cannot be read we must not fall back to 'everything public'."""
    def boom():
        raise OSError("ANCHOR.md is gone")
    monkeypatch.setattr(appmod, "_anchor", boom)
    assert client.get("/preview/999").status_code == 401


# ── the guard ─────────────────────────────────────────────────────────────────
def test_protected_route_401s_without_cookie(stub_kind, client):
    assert client.get("/wall").status_code == 401
    assert client.get("/system").status_code == 401       # reads are gated too, by decision


def test_protected_route_200s_with_cookie(stub_kind, client):
    token = _signed_in(client)
    r = client.get("/wall", cookies={"fls_session": token})
    assert r.status_code == 200


def test_401_response_carries_cors_headers(stub_kind, client):
    """Catches the middleware-ordering bug. If the guard is registered below the CORS block it
    runs outermost, the 401 ships without CORS headers, and the browser reports an opaque CORS
    failure instead — so the admin's 401 handling never fires and the user sees nothing."""
    r = client.get("/wall", headers={"Origin": "http://localhost:8792"})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == "http://localhost:8792"


def test_options_preflight_is_never_401(stub_kind, client):
    r = client.options("/wall", headers={"Origin": "http://localhost:8792",
                                         "Access-Control-Request-Method": "GET"})
    assert r.status_code != 401


def test_a_forged_cookie_is_refused(stub_kind, client):
    assert client.get("/wall", cookies={"fls_session": "aaa.bbb"}).status_code == 401


def test_an_authenticated_but_unlisted_user_is_403(stub_kind, client, monkeypatch):
    """The allowlist, not the provider, is the gate — a public OAuth app authenticates the
    whole internet."""
    monkeypatch.setenv("FLS_ALLOWED_USERS", "somebody-else")
    start = client.get("/auth/login")
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    r = client.get(f"/auth/callback?code=abc&state={state}",
                   cookies={"fls_auth_nonce": nonce})
    assert _refused(r, "not+authorised") or _refused(r, "not%20authorised"), r.headers


def test_demo_token_session_cannot_reach_operator_routes(stub_kind, client):
    """The audience-conflation guard. A visitor's session must never satisfy an operator check,
    which is why the demo surface was NOT folded into this seam."""
    visitor = Principal(subject="583231", login="octocat", audience="demo")
    token = SignedSession(secrets=(SECRET,)).mint(visitor)
    assert client.get("/wall", cookies={"fls_session": token}).status_code == 401
    assert client.post("/expeditions/1/kill", json={"reason": "x"},
                       cookies={"fls_session": token}).status_code == 401


# ── the callback's CSRF halves ────────────────────────────────────────────────
def test_callback_rejects_mismatched_state(stub_kind, client):
    client.get("/auth/login")
    nonce = client.cookies.get("fls_auth_nonce")
    forged = StateSigner(secrets=("wrong",)).mint(nonce=nonce, return_to="/")
    r = client.get(f"/auth/callback?code=abc&state={forged}",
                   cookies={"fls_auth_nonce": nonce})
    assert _refused(r)


def test_callback_rejects_missing_state_cookie(stub_kind, client):
    start = client.get("/auth/login")
    state = start.headers["location"].split("state=")[1]
    client.cookies.clear()
    assert _refused(client.get(f"/auth/callback?code=abc&state={state}"))


def test_callback_rejects_a_replayed_state_from_another_browser(stub_kind, client):
    """Signed state alone is replayable inside its TTL and bound to nobody — which is why the
    cookie half exists."""
    start = client.get("/auth/login")
    state = start.headers["location"].split("state=")[1]
    other = TestClient(appmod.app, follow_redirects=False)   # a browser with no nonce cookie
    assert _refused(other.get(f"/auth/callback?code=abc&state={state}"))


def test_callback_rejects_an_expired_state(stub_kind):
    signer = StateSigner(secrets=(SECRET,), ttl_s=600)
    state = signer.mint(nonce="n", return_to="/", now=1000)
    assert signer.verify(state, now=1000 + 601) is None


def test_state_cookie_is_cleared_on_completion(stub_kind, client):
    start = client.get("/auth/login")
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    done = client.get(f"/auth/callback?code=abc&state={state}",
                      cookies={"fls_auth_nonce": nonce})
    assert 'fls_auth_nonce=""' in done.headers["set-cookie"] or \
           "fls_auth_nonce=;" in done.headers["set-cookie"]


def test_provider_that_confirms_nobody_is_401(stub_kind, client):
    StubIdentity.principal = None
    start = client.get("/auth/login")
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    r = client.get(f"/auth/callback?code=abc&state={state}",
                   cookies={"fls_auth_nonce": nonce})
    assert _refused(r, "not+confirmed") or _refused(r, "not%20confirmed"), r.headers


# ── cookie flags + return_to ──────────────────────────────────────────────────
def test_session_cookie_flags(stub_kind, client, monkeypatch):
    start = client.get("/auth/login")
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    raw = client.get(f"/auth/callback?code=abc&state={state}",
                     cookies={"fls_auth_nonce": nonce}).headers["set-cookie"]
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw.replace("SameSite=Lax", "SameSite=lax")
    assert "Path=/" in raw
    assert "Secure" not in raw        # FLS_COOKIE_SECURE=0 in this fixture


def test_secure_flag_is_on_by_default(stub_kind, client, monkeypatch):
    monkeypatch.delenv("FLS_COOKIE_SECURE", raising=False)
    start = client.get("/auth/login")
    assert "Secure" in start.headers["set-cookie"]


@pytest.mark.parametrize("hostile", [
    "https://evil.test/steal", "//evil.test", "/\\evil.test", "javascript:alert(1)",
    "http:/evil.test", "", None, "x" * 600,
])
def test_return_to_rejects_absolute_and_protocol_relative(hostile):
    """An open redirect on a login route is worth more than on any other: the victim arrives
    having just proven they trust this origin."""
    assert safe_return_to(hostile) == "/"


@pytest.mark.parametrize("ok", ["/", "/#/exp/12", "/wall?x=1"])
def test_return_to_accepts_same_site_paths(ok):
    assert safe_return_to(ok) == ok


def test_deep_link_survives_the_round_trip(stub_kind, client):
    start = client.get("/auth/login?return_to=/%23/exp/12")
    nonce = client.cookies.get("fls_auth_nonce")
    state = start.headers["location"].split("state=")[1]
    done = client.get(f"/auth/callback?code=abc&state={state}",
                      cookies={"fls_auth_nonce": nonce})
    assert done.headers["location"] == "/#/exp/12"


def test_logout_clears_the_session(stub_kind, client):
    token = _signed_in(client)
    assert client.get("/wall", cookies={"fls_session": token}).status_code == 200
    out = client.post("/auth/logout", cookies={"fls_session": token})
    assert out.status_code == 200
    assert 'fls_session=""' in out.headers["set-cookie"] or \
           "fls_session=;" in out.headers["set-cookie"]


def test_me_returns_the_principal(stub_kind, client):
    token = _signed_in(client)
    body = client.get("/auth/me", cookies={"fls_session": token}).json()
    assert body["authenticated"] is True
    assert body["principal"]["login"] == "octocat"
    assert "secret" not in str(body).lower()


# ── login is fail-closed on missing configuration ─────────────────────────────
def test_login_refuses_without_a_session_secret(stub_kind, client, monkeypatch):
    """Never auto-generate one: under `uvicorn --workers N` each process would mint a different
    secret, which presents as intermittent 401s that look like a cookie bug and are not."""
    monkeypatch.delenv("FLS_SESSION_SECRET", raising=False)
    assert client.get("/auth/login").status_code == 503


def test_login_refuses_without_a_configured_redirect_uri(stub_kind, client, monkeypatch):
    """Deriving it from the request is what Caddy's `handle_path /api/*` breaks — url_for()
    returns a URL missing /api and the provider exact-matches."""
    monkeypatch.delenv("FLS_AUTH_REDIRECT_URI", raising=False)
    assert client.get("/auth/login").status_code == 503


# ── CSRF on mutating routes ───────────────────────────────────────────────────
def test_cross_site_mutating_request_is_refused(stub_kind, client):
    """`await request.json()` parses a body regardless of Content-Type, so a plain text/plain
    form POST reaches /kill with no preflight. Harmless until a cookie exists; this change
    creates the cookie, so the check lands in the same change."""
    token = _signed_in(client)
    r = client.post("/expeditions/1/kill", json={"reason": "x"},
                    cookies={"fls_session": token},
                    headers={"Origin": "https://evil.test", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_same_origin_mutating_request_passes_the_origin_check(stub_kind, client):
    token = _signed_in(client)
    r = client.post("/expeditions/999999/kill", json={"actor": "octocat", "reason": "x"},
                    cookies={"fls_session": token},
                    headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 404      # reached the route; no such expedition


def test_a_toolcall_with_no_origin_headers_is_allowed(stub_kind, client):
    """curl, an MCP tool and a server-to-server call carry no cookie to abuse; refusing them
    would break every non-browser caller for no security gain."""
    token = _signed_in(client)
    r = client.post("/expeditions/999999/kill", json={"actor": "octocat", "reason": "x"},
                    cookies={"fls_session": token})
    assert r.status_code == 404


# ── provider JSON -> Principal (pure) ─────────────────────────────────────────
def test_principal_from_github_uses_the_numeric_id_as_subject():
    p = principal_from_github({"id": 583231, "login": "octocat", "name": "Alice Example"})
    assert p.subject == "583231" and p.login == "octocat" and p.provider == "github"


def test_principal_from_github_refuses_an_incomplete_payload():
    assert principal_from_github({}) is None
    assert principal_from_github({"login": "octocat"}) is None      # no id


def test_principal_from_oidc_maps_standard_claims():
    p = principal_from_oidc({"sub": "abc", "preferred_username": "octocat",
                             "name": "Alice Example", "email": "alice@example.com"})
    assert p.subject == "abc" and p.login == "octocat" and p.email == "alice@example.com"


def test_github_token_endpoint_error_with_http_200_is_treated_as_failure(monkeypatch):
    """GitHub returns token-endpoint errors with HTTP 200 and an `error` key. Checking the
    status code alone reads a refused exchange as a success."""
    from fls import identity as ident
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "Ov23liEXAMPLE")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "s" * 40)
    monkeypatch.setattr(ident, "_post_form",
                        lambda *a, **k: {"error": "bad_verification_code"})
    called = []
    monkeypatch.setattr(ident, "_get_json", lambda *a, **k: called.append(a) or {})
    got = ident.GitHubOAuthIdentity().complete({"code": "x"}, redirect_uri="https://h.test/cb",
                                               nonce="n")
    assert got is None
    assert not called, "must not call /user after a refused exchange"


def test_github_happy_path(monkeypatch):
    from fls import identity as ident
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "Ov23liEXAMPLE")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "s" * 40)
    monkeypatch.setattr(ident, "_post_form", lambda *a, **k: {"access_token": "gho_x"})
    monkeypatch.setattr(ident, "_get_json",
                        lambda *a, **k: {"id": 583231, "login": "octocat"})
    got = ident.GitHubOAuthIdentity().complete({"code": "x"}, redirect_uri="https://h.test/cb",
                                               nonce="n")
    assert got.login == "octocat" and got.provider == "github"


def test_github_authorize_url_requests_only_read_user(monkeypatch):
    from fls import identity as ident
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "Ov23liEXAMPLE")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "s" * 40)
    url = ident.GitHubOAuthIdentity().begin(
        redirect_uri="https://h.test/api/auth/callback", state="s", nonce="n").redirect_url
    assert "scope=read%3Auser" in url
    assert "repo" not in url


# ── oidc ──────────────────────────────────────────────────────────────────────
DISCOVERY = {
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "userinfo_endpoint": "https://idp.test/userinfo",
    "code_challenge_methods_supported": ["S256"],
}


def _oidc(monkeypatch, token_response, userinfo=None):
    from fls import identity as ident
    monkeypatch.setenv("FLS_OIDC_ISSUER", "https://idp.test")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "client-123")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "shh")
    def get_json(url, headers=None):
        if "openid-configuration" in url:
            return DISCOVERY
        return userinfo or {}
    monkeypatch.setattr(ident, "_get_json", get_json)
    monkeypatch.setattr(ident, "_post_form", lambda *a, **k: token_response)
    return ident.OidcIdentity()


def _id_token(claims: dict) -> str:
    import base64
    import json as _j
    body = base64.urlsafe_b64encode(_j.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{body}.sig"


def test_oidc_sends_pkce_only_when_discovery_advertises_it(monkeypatch):
    ident_obj = _oidc(monkeypatch, {})
    with_pkce = ident_obj.begin(redirect_uri="https://h.test/cb", state="s", nonce="n",
                                verifier="v" * 43).redirect_url
    assert "code_challenge_method=S256" in with_pkce

    from fls import identity as ident
    monkeypatch.setattr(ident, "_get_json",
                        lambda url, headers=None: {k: v for k, v in DISCOVERY.items()
                                                   if k != "code_challenge_methods_supported"})
    without = ident.OidcIdentity().begin(redirect_uri="https://h.test/cb", state="s",
                                         nonce="n", verifier="v" * 43).redirect_url
    assert "code_challenge" not in without


def test_oidc_nonce_mismatch_is_refused(monkeypatch):
    import time
    obj = _oidc(monkeypatch, {"access_token": "at",
                              "id_token": _id_token({"iss": "https://idp.test",
                                                     "aud": "client-123",
                                                     "exp": time.time() + 600,
                                                     "nonce": "SOMETHING-ELSE"})},
                userinfo={"sub": "abc"})
    assert obj.complete({"code": "c"}, redirect_uri="https://h.test/cb", nonce="n") is None


@pytest.mark.parametrize("claim,value", [("iss", "https://evil.test"), ("aud", "other-client")])
def test_oidc_refuses_a_token_minted_for_someone_else(monkeypatch, claim, value):
    import time
    claims = {"iss": "https://idp.test", "aud": "client-123",
              "exp": time.time() + 600, "nonce": "n"}
    claims[claim] = value
    obj = _oidc(monkeypatch, {"access_token": "at", "id_token": _id_token(claims)},
                userinfo={"sub": "abc"})
    assert obj.complete({"code": "c"}, redirect_uri="https://h.test/cb", nonce="n") is None


def test_oidc_happy_path_takes_identity_from_userinfo(monkeypatch):
    import time
    obj = _oidc(monkeypatch, {"access_token": "at",
                              "id_token": _id_token({"iss": "https://idp.test",
                                                     "aud": "client-123",
                                                     "exp": time.time() + 600, "nonce": "n"})},
                userinfo={"sub": "abc", "preferred_username": "octocat"})
    got = obj.complete({"code": "c"}, redirect_uri="https://h.test/cb", nonce="n")
    assert got.subject == "abc" and got.login == "octocat"


def test_oidc_refuses_when_the_exchange_fails(monkeypatch):
    obj = _oidc(monkeypatch, {"error": "invalid_grant"})
    assert obj.complete({"code": "c"}, redirect_uri="https://h.test/cb", nonce="n") is None


# ── proxy-header ──────────────────────────────────────────────────────────────
def test_proxy_header_ignored_when_kind_not_configured(monkeypatch):
    """A stray X-Forwarded-User on an instance running any other kind means nothing."""
    from fls.identity import ProxyHeaderIdentity
    monkeypatch.delenv("FLS_TRUSTED_PROXIES", raising=False)
    p = ProxyHeaderIdentity()
    assert p.configured() is False
    assert p.complete({"_headers": {"X-Forwarded-User": "octocat"}, "_peer": "10.0.0.1"},
                      redirect_uri="", nonce="") is None


def test_proxy_header_ignored_when_peer_untrusted(monkeypatch):
    from fls.identity import ProxyHeaderIdentity
    monkeypatch.setenv("FLS_TRUSTED_PROXIES", "10.0.0.1")
    p = ProxyHeaderIdentity()
    assert p.complete({"_headers": {"X-Forwarded-User": "octocat"}, "_peer": "203.0.113.9"},
                      redirect_uri="", nonce="") is None


def test_proxy_header_accepts_a_trusted_peer(monkeypatch):
    from fls.identity import ProxyHeaderIdentity
    monkeypatch.setenv("FLS_TRUSTED_PROXIES", "10.0.0.1")
    got = ProxyHeaderIdentity().complete(
        {"_headers": {"X-Forwarded-User": "octocat"}, "_peer": "10.0.0.1"},
        redirect_uri="", nonce="")
    assert got.login == "octocat" and got.provider == "proxy-header"


def test_proxy_header_has_no_browser_leg(monkeypatch):
    from fls.identity import ProxyHeaderIdentity
    monkeypatch.setenv("FLS_TRUSTED_PROXIES", "10.0.0.1")
    with pytest.raises(RuntimeError):
        ProxyHeaderIdentity().begin(redirect_uri="x", state="s", nonce="n")


# ── the verified actor replaces the typed one ─────────────────────────────────
def _seed(tmp_path):
    """A store holding one climbing expedition, seeded exactly as test_admin_routes does it."""
    from pathlib import Path

    from fls.adjudicator import Idea
    from fls.expedition import CLIMBING, Expedition
    from fls.store import ExpeditionStore
    store = ExpeditionStore(tmp_path)
    store.save(Expedition(101, Idea(101, "cmd-k", "focus", "feature"), 2, rung=2,
                          status=CLIMBING))
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = store
    return store


def test_typed_actor_is_ignored_when_identity_is_on(stub_kind, client, tmp_path):
    """Not a fallback — ignored. A fallback would mean a request that omits the cookie but
    supplies a name still records a name, which is the defect this replaces."""
    store = _seed(tmp_path)
    number = 101
    token = _signed_in(client)
    r = client.post(f"/expeditions/{number}/kill",
                    json={"actor": "somebody-else-entirely", "reason": "x"},
                    cookies={"fls_session": token})
    assert r.status_code == 200
    assert r.json()["by"] == "Alice Example"      # the session's principal, not the body
    assert "somebody-else-entirely" not in str(store.get(number))


def test_kill_records_principal_in_decision_actor_field_not_human_verdict(
        stub_kind, client, tmp_path):
    store = _seed(tmp_path)
    number = 101
    token = _signed_in(client)
    client.post(f"/expeditions/{number}/kill", json={"reason": "x"},
                cookies={"fls_session": token})
    rows = store.ledger().rows
    killed = [d for d in rows if d.judge_verdict == "kill"]
    assert killed, "no kill row in the ledger"
    assert killed[-1].human_verdict == "kill"          # bare: `agreed` works again
    assert killed[-1].actor == "583231"                # the opaque subject...
    assert "alice@" not in str(killed[-1])             # ...never an email, in an append-only file


def test_decision_actor_is_additive_and_old_rows_still_parse(tmp_path):
    """Old jsonl rows have no `actor` key at all; a missing key must read as None."""
    import json

    from fls.ledger import Decision, Ledger
    path = tmp_path / "ledger.jsonl"
    path.write_text(json.dumps({"expedition": 1, "rung": "r", "judge_verdict": "admit",
                                "human_verdict": "admit", "judge_cost_usd": 0.0}) + "\n")
    rows = Ledger(path=path).load().rows
    assert rows[0].actor is None and rows[0].agreed is True
    assert "actor" in json.dumps(Decision(1, "r", "a", "a", 0.0, actor="583231").__dict__)


def test_agreed_works_again_now_that_the_actor_is_not_concatenated():
    """The bug this column exists to fix: a colon-joined human_verdict could never agree."""
    from fls.ledger import Decision
    assert Decision(1, "r", "kill", "kill:alice", 0.0).agreed is False   # the old shape
    assert Decision(1, "r", "kill", "kill", 0.0, actor="583231").agreed is True


# ── regressions: every one of these was a live defect found by review ─────────
def test_a_non_ascii_signature_does_not_raise(stub_kind, client):
    """`hmac.compare_digest` RAISES on a str with a codepoint > 127, and a cookie is
    attacker-controlled — so one byte turned the deny-by-default guard into an unhandled 500
    with a traceback, pre-auth, on every request."""
    assert SignedSession(secrets=("k",)).verify("abcd." + "é" * 32) is None
    assert StateSigner(secrets=("k",)).verify("abcd." + "é" * 32) is None
    # httpx refuses to SEND a non-ASCII cookie, so pass raw bytes the way a hostile client
    # does — the server is what is under test here, not the convenience of the test client.
    hostile = b"fls_session=abcd." + b"\xe9" * 32
    assert client.get("/wall", headers=[(b"cookie", hostile)]).status_code == 401
    assert _refused(client.get("/auth/callback", headers=[(b"cookie", hostile)],
                               params={"state": "abc.\xe9"}))


def test_auth_me_applies_the_allowlist(stub_kind, client, monkeypatch):
    """/auth/me sits on the public /auth/ prefix, so it needs its own policy check. Without it
    a de-allowlisted operator got `authenticated: true` here and 403 everywhere else — and the
    admin, seeing a signed-in user, rendered its fixtures fallback as a real dashboard."""
    token = _signed_in(client)
    monkeypatch.setenv("FLS_ALLOWED_USERS", "somebody-else")
    assert client.get("/auth/me", cookies={"fls_session": token}).status_code == 403
    assert client.get("/wall", cookies={"fls_session": token}).status_code == 403


def test_oidc_refuses_when_the_token_response_has_no_id_token(monkeypatch):
    """This skipped iss, aud, exp AND nonce wholesale, making the replay and cross-client
    defences optional at the provider's discretion."""
    obj = _oidc(monkeypatch, {"access_token": "at"},          # no id_token at all
                userinfo={"sub": "attacker-sub", "preferred_username": "mallory"})
    assert obj.complete({"code": "c"}, redirect_uri="x", nonce="EXPECTED") is None


def test_oidc_refuses_an_unparseable_id_token(monkeypatch):
    obj = _oidc(monkeypatch, {"access_token": "at", "id_token": "not-a-jwt"},
                userinfo={"sub": "attacker-sub"})
    assert obj.complete({"code": "c"}, redirect_uri="x", nonce="EXPECTED") is None


def test_the_pkce_verifier_never_travels_in_state(stub_kind, client):
    """`state` is signed but NOT encrypted and rides the authorization URL. A verifier in it is
    readable by the IdP, browser history, a Referer leak or any logging proxy — which defeats
    PKCE entirely while still looking enabled."""
    import base64
    import json as _j
    start = client.get("/auth/login")
    state = start.headers["location"].split("state=")[1]
    payload = state.rpartition(".")[0]
    body = _j.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert "verifier" not in body, body
    # it is in the HttpOnly cookie on our own origin instead
    assert "." in client.cookies.get("fls_auth_nonce")


def test_proxy_header_kind_can_actually_authenticate(monkeypatch):
    """It could not. `begin()` raises, /auth/login 503s, and nothing else minted a session — so
    the guard denied every request forever and the instance was locked out. The kind the docs
    call the most likely deployment was dead on arrival."""
    monkeypatch.setenv("FLS_IDENTITY_KIND", "proxy-header")
    monkeypatch.setenv("FLS_TRUSTED_PROXIES", "testclient")
    monkeypatch.setenv("FLS_ALLOWED_USERS", "octocat")
    monkeypatch.setenv("FLS_SESSION_SECRET", SECRET)
    c = TestClient(appmod.app, follow_redirects=False)
    assert c.get("/wall", headers={"X-Forwarded-User": "octocat"}).status_code == 200
    assert c.get("/wall").status_code == 401                       # no header, no entry
    assert c.get("/wall", headers={"X-Forwarded-User": "stranger"}).status_code == 403


def test_an_unknown_identity_kind_refuses_to_start(monkeypatch):
    """Fail-closed AND unexplained is the worst combination: the guard stayed on with no
    provider behind it, so every route 401d and nobody could sign in to find out why."""
    monkeypatch.setenv("FLS_IDENTITY_KIND", "githuboauth")
    with pytest.raises(RuntimeError, match="not a registered identity kind"):
        with TestClient(appmod.app):
            pass


def test_logout_is_not_csrf_able(stub_kind, client):
    """A public route can still be mutating and cookie-bearing. Forcing a sign-out from any
    page on the internet is a nuisance and a step in a login-CSRF chain."""
    r = client.post("/auth/logout", headers={"Origin": "https://evil.test",
                                             "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_public_prefixes_only_match_whole_segments(stub_kind):
    """A bare `startswith` made every public entry a trap for the next route added: `/health`
    would have exempted a future `/healthcheck`, `/webhook/github` a future
    `/webhook/github-app`. Nothing collides today, which is why it would have been found late."""
    allowed = appmod.public_paths()
    assert appmod._is_public("/health", allowed) is True
    assert appmod._is_public("/healthcheck", allowed) is False
    assert appmod._is_public("/health-secret", allowed) is False
    assert appmod._is_public("/webhook/github", allowed) is True
    assert appmod._is_public("/webhook/github-app", allowed) is False
    assert appmod._is_public("/preview/1", allowed) is True        # real prefix still works
    assert appmod._is_public("/preview-admin", allowed) is False


def test_an_email_never_becomes_the_login(monkeypatch):
    """`login` flows into `display`, which is written to the expedition record and posted to a
    public GitHub issue comment. For any IdP that omits preferred_username that quietly
    published the operator's email address."""
    p = principal_from_oidc({"sub": "abc", "email": "alice@example.com", "name": "Alice"})
    assert p.login == ""
    assert "@" not in p.login
    assert p.display == "Alice"
    bare = principal_from_oidc({"sub": "abc", "email": "alice@example.com"})
    assert bare.display == "abc"          # the opaque subject, not the address


def test_the_demo_buttons_still_work_with_the_guard_on(stub_kind, client, tmp_path,
                                                       monkeypatch):
    """The demo page posted its approve/pick straight to the OPERATOR feedback route with a
    self-typed name. Invisible while nothing was authenticated; a 401 on a public page the
    moment the guard went on."""
    monkeypatch.setenv("FLS_DEMO_PASSCODE", "let-me-in")
    store = _seed(tmp_path)
    from fls.adjudicator import Idea
    from fls.expedition import CLIMBING, Expedition
    # `source` lives on the Idea, not the Expedition — the store reads `e.idea.source`.
    store.save(Expedition(202, Idea(202, "a share modal", "it opens", "feature",
                                    source="demo:Vis Itor"), 2, rung=2, status=CLIMBING))

    tok = client.post("/demo/login",
                      json={"name": "Vis Itor", "passcode": "let-me-in"}).json()["token"]
    r = client.post("/demo/expeditions/202/feedback", json={"body": "/approve"},
                    headers={"x-demo-token": tok})
    # Assert what it IS, not merely what it is not: `!= 401` passed while the call was 403 for
    # an unrelated reason, which is how a test ends up proving nothing.
    assert r.status_code in (200, 503), r.text      # 503 = no outbound token in this env

    # ...and the visitor door is not a way around the operator one
    assert client.post("/demo/expeditions/202/feedback",
                       json={"body": "/approve"}).status_code == 401      # no demo token
    assert client.post("/demo/expeditions/101/feedback", json={"body": "/approve"},
                       headers={"x-demo-token": tok}).status_code == 403  # not a demo expedition
    # An unknown COMMAND is still refused — a slash-prefixed string is somebody addressing
    # the protocol, and the surface offers four verbs.
    assert client.post("/demo/expeditions/202/feedback", json={"body": "/rm -rf"},
                       headers={"x-demo-token": tok}).status_code == 400
    # Prose is NOT refused, and the old assertion that it was is what broke the surface's own
    # "say what to change" button: it posted free text into a door that answered 400. It is a
    # comment, it cannot move the ladder, and only its length is policed.
    assert client.post("/demo/expeditions/202/feedback",
                       json={"body": "the amount is hard to find"},
                       headers={"x-demo-token": tok}).status_code in (200, 503)
    assert client.post("/demo/expeditions/202/feedback", json={"body": "x" * 2001},
                       headers={"x-demo-token": tok}).status_code == 413
    assert client.post("/expeditions/202/feedback", json={"body": "/approve"},
                       headers={"x-demo-token": tok}).status_code == 401  # operator door shut


def test_the_401_names_the_provider_so_the_button_can_say_github(stub_kind, client):
    """The sign-in screen renders exactly when /auth/me refuses, so if that 401 carries no kind
    the admin cannot label its own button and every instance offers a generic "Sign in"."""
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["identity"] == "stub"


def test_the_401_body_still_carries_no_secret(stub_kind, client, monkeypatch):
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "shhh-secret-value")
    body = client.get("/auth/me").text
    assert "shhh-secret-value" not in body and "octocat" not in body


def test_the_callback_never_serves_a_machine_shaped_error(stub_kind, client):
    """Reputation crawlers follow this URL and can never carry the nonce cookie, so an error is
    all they will ever see. Serving them JSON while a human gets a page is cloaking-shaped, and
    that is a phishing signal generated by our own CSRF defence."""
    r = client.get("/auth/callback?code=x&state=garbage")
    assert r.status_code == 302
    assert "application/json" not in r.headers.get("content-type", "")
    assert r.headers["location"].startswith("/app/?auth_error=")
    assert "fls_session" not in r.cookies


# ── Clerk, against its real discovery document ────────────────────────────────
# Captured 2026-09-11 from a live Clerk instance. Kept verbatim rather than hand-written,
# because the point of this test is compatibility with what Clerk actually serves — a fixture
# invented to match the code would only prove the code matches itself.
CLERK_DISCOVERY = {
    "issuer": "https://clerk.example.com",
    "authorization_endpoint": "https://clerk.example.com/oauth/authorize",
    "token_endpoint": "https://clerk.example.com/oauth/token",
    "userinfo_endpoint": "https://clerk.example.com/oauth/userinfo",
    "jwks_uri": "https://clerk.example.com/.well-known/jwks.json",
    "scopes_supported": ["offline_access", "user:org:read", "email", "profile",
                         "public_metadata", "private_metadata", "openid"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
    "claims_supported": ["email", "email_verified", "given_name", "name", "sub", "aud", "exp",
                         "iat", "family_name", "preferred_username", "picture", "iss", "org_id"],
    "token_endpoint_auth_methods_supported": ["client_secret_basic", "none",
                                              "client_secret_post"],
}


def _clerk(monkeypatch, token_response, userinfo):
    from fls import identity as ident
    monkeypatch.setenv("FLS_OIDC_ISSUER", "https://clerk.example.com")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "clerk-client-id")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "clerk-client-secret")
    monkeypatch.setattr(ident, "_get_json",
                        lambda url, headers=None: CLERK_DISCOVERY
                        if "well-known" in url else userinfo)
    monkeypatch.setattr(ident, "_post_form", lambda *a, **k: token_response)
    return ident.OidcIdentity()


def _clerk_id_token(nonce="n"):
    import time
    return _id_token({"iss": "https://clerk.example.com", "aud": "clerk-client-id",
                      "exp": time.time() + 600, "nonce": nonce})


def test_clerk_is_usable_by_the_generic_oidc_kind(monkeypatch):
    obj = _clerk(monkeypatch, {}, {})
    assert obj.configured() is True
    doc = obj.discover()
    assert doc["token_endpoint"].endswith("/oauth/token")
    assert "client_secret_post" in doc["token_endpoint_auth_methods_supported"]


def test_clerk_authorize_url_carries_pkce_and_the_right_scopes(monkeypatch):
    url = _clerk(monkeypatch, {}, {}).begin(
        redirect_uri="https://h.test/api/auth/callback", state="s", nonce="n",
        verifier="v" * 43).redirect_url
    assert url.startswith("https://clerk.example.com/oauth/authorize?")
    assert "code_challenge_method=S256" in url          # Clerk advertises S256
    assert "scope=openid+profile+email" in url
    assert "v" * 43 not in url                          # the verifier never travels


def test_clerk_sign_in_yields_a_principal(monkeypatch):
    obj = _clerk(monkeypatch,
                 {"access_token": "at", "id_token": _clerk_id_token()},
                 {"sub": "user_2abcDEF", "preferred_username": "nate",
                  "email": "alice@example.com", "name": "Alice Example"})
    p = obj.complete({"code": "c"}, redirect_uri="https://h.test/api/auth/callback", nonce="n")
    assert p.subject == "user_2abcDEF"        # Clerk's opaque id — what the ledger records
    assert p.login == "nate"
    assert p.provider == "oidc"


def test_a_clerk_user_with_no_username_is_still_allowlistable(monkeypatch):
    """Clerk instances that use email-only sign-in issue no preferred_username. Before the
    allowlist matched email, a correctly-configured instance would have refused everyone."""
    obj = _clerk(monkeypatch,
                 {"access_token": "at", "id_token": _clerk_id_token()},
                 {"sub": "user_2xyz", "email": "alice@example.com"})
    p = obj.complete({"code": "c"}, redirect_uri="https://h.test/api/auth/callback", nonce="n")
    assert p.login == ""                                   # nothing to match on but the email
    from fls.identity import Policy
    assert Policy(allowed=frozenset({"alice@example.com"})).permits(p) is True
    assert Policy(allow_any=True).permits(p) is True
    assert Policy().permits(p) is False                     # still fails closed
    assert "@" not in p.subject                             # and the ledger stays PII-free


def test_clerk_replay_is_refused(monkeypatch):
    obj = _clerk(monkeypatch,
                 {"access_token": "at", "id_token": _clerk_id_token(nonce="OTHER")},
                 {"sub": "user_2abc"})
    assert obj.complete({"code": "c"}, redirect_uri="https://h.test/api/auth/callback",
                        nonce="n") is None

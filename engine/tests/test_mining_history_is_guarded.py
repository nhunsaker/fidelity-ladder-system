"""The trail an operator reads before loosening a dial must be real or absent — never invented.

`EarningHistory.jsx` fetched /mining-history with a bare `fetch` carrying no session cookie. On a
guarded instance every load 401'd and the component fell back to MOCK_MINING_HISTORY, while the
badge blamed an endpoint that "had not landed" — false since v0.6. An operator deciding how much
autonomy to grant was reading agreement rates that had been made up.

The component fix (use the credentialled client, delete the mock) cannot be asserted from Python.
What CAN be pinned here is the half that made the fallback reachable: the route exists and it is
behind the guard, so a request without a session gets 401 rather than data.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from fls import app as appmod


def test_mining_history_exists():
    """The component claimed for months that it did not."""
    paths = {r.path for r in appmod.app.routes if hasattr(r, "path")}
    assert "/mining-history" in paths


def test_mining_history_is_behind_the_operator_guard(monkeypatch):
    """Which is WHY a credential-less fetch fell back. 401, not data, and not a crash."""
    monkeypatch.setenv("FLS_IDENTITY_KIND", "oidc")
    monkeypatch.setenv("FLS_OIDC_ISSUER", "https://example.invalid")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "s")
    monkeypatch.setenv("FLS_SESSION_SECRET", "z" * 32)
    r = TestClient(appmod.app).get("/mining-history")
    assert r.status_code in (401, 403), (
        "an unauthenticated read must be refused — a 200 here would mean the trail is public"
    )


def test_it_is_not_in_public_paths():
    """A route a signed-out browser can read is a route that never needed credentials. The trail
    is governance evidence; it stays behind the guard."""
    public = getattr(appmod, "PUBLIC_PATHS", {})
    assert not any(str(p).startswith("/mining-history") for p in public)


# ── the audience boundary, pinned before the routes move ───────────────────────────────────

def test_every_route_is_guarded_by_the_audience_its_path_names(tmp_path, monkeypatch):
    """The guard map IS the audience boundary, and until the paths were renamed it was invisible:
    visitor routes were prefixed `/demo/`, and operator routes had no prefix at all, so "unprefixed
    means privileged" was a convention nothing enforced and no reviewer could see. This session
    produced exactly that bug — the demo page posting to the OPERATOR feedback route with a name it
    had typed itself, invisible until the guard went on.

    This pins the contract itself rather than a list of paths, so it holds across the rename: a
    route is exempt from the operator guard if and only if its path sits under a surface the
    ANCHOR opened, or is one of the three standing public entries.
    """
    import fls.app as appmod

    allowed = appmod.public_paths()

    # The three standing exemptions, each for a reason that is not "we forgot".
    assert appmod._is_public("/health", allowed)          # liveness
    assert appmod._is_public("/auth/login", allowed)      # the sign-in flow itself
    assert appmod._is_public("/auth/callback", allowed)
    assert appmod._is_public("/webhook/github", allowed)  # HMAC-verified, fail-closed

    # Operator surfaces are NOT public under any spelling. These are the ones a mis-wired client
    # would reach for, and the ones that move money or stop work.
    for path in ("/wall", "/expeditions/4", "/expeditions/4/feedback", "/expeditions/4/kill",
                 "/expeditions/4/retry", "/anchor", "/anchor/propose", "/system", "/snapshot",
                 "/feeder/run", "/panels/propose", "/ideas", "/mining-history"):
        assert not appmod._is_public(path, allowed), f"{path} escaped the operator guard"

    # A prefix only ever matches a WHOLE segment, so opening one surface cannot open its
    # neighbour: /webhook/github must not exempt a future /webhook/github-app.
    assert not appmod._is_public("/webhook/github-app", allowed)
    assert not appmod._is_public("/healthcheck", allowed)


def _guarded(monkeypatch):
    """An instance with identity actually configured. Without this the operator guard is inert
    (`active_kind() == "none"` returns early), so a test that asks "is this refused?" answers yes
    to everything and proves nothing — which is exactly how the two assertions below first went in
    green against a guard map that had been broken on purpose."""
    monkeypatch.setenv("FLS_IDENTITY_KIND", "oidc")
    monkeypatch.setenv("FLS_OIDC_ISSUER", "https://example.invalid")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("FLS_OAUTH_CLIENT_SECRET", "s")
    monkeypatch.setenv("FLS_SESSION_SECRET", "z" * 32)
    return TestClient(appmod.app)


def test_a_guarded_instance_refuses_operator_paths_and_admits_visitor_ones(monkeypatch):
    """The audience boundary, exercised rather than described.

    Both spellings of an operator route are refused without a session; both spellings of the
    visitor and public surfaces get past the operator guard (their own credential is checked by
    the route). Break the prefix table in either direction and one half of this flips.
    """
    c = _guarded(monkeypatch)

    for path in ("/v1/operator/runs", "/v1/operator/anchor", "/v1/operator/system",
                 "/wall", "/anchor", "/system"):
        assert c.get(path).status_code in (401, 403), f"{path} answered without a session"

    # Past the operator guard — whatever they then answer, it is not the operator's 401.
    for path in ("/v1/public/runs/active", "/demo/active"):
        assert c.get(path).status_code != 401, f"{path} was caught by the operator guard"

    # The visitor door refuses a BAD PASSCODE, which is its own guard doing its own job — the
    # point is that the operator guard let the request reach it at all.
    for path in ("/v1/visitor/login", "/demo/login"):
        r = c.post(path, json={"name": "x", "passcode": "wrong"})
        assert r.status_code != 401 or "sign in required" not in r.text, f"{path} hit the wrong guard"

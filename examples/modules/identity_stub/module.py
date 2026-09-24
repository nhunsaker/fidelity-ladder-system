"""A ~50-line reference `Identity`: a header-shaped provider with no network and no OAuth.

Three jobs, all real:

  1. **The BYO-identity doc.** If you want to authenticate operators against something FLS does
     not ship a kind for — an internal SSO, a signed assertion from a gateway, a corporate
     directory — this is the shape to copy. `begin`/`complete` and four reflection methods.
  2. **The `FLS_MODULES` registration fixture.** Proof the seventh registry really is
     extensible from outside the engine, exercised by `test_module.py`.
  3. **An offline test double.** Every route test needs a provider that authenticates somebody
     without a network, and a real one in the tree beats a mock defined in six test files.

⚠️ It is a REFERENCE, not a deployable kind. It trusts a header with no proxy verification of
any sort. If you want header-based identity in production, use the built-in `proxy-header` kind,
which refuses any peer that is not in `FLS_TRUSTED_PROXIES`.
"""
from __future__ import annotations

from fls.identity import Challenge, Principal


class StubIdentity:
    """Authenticates whoever the configured header names. Registered as kind `stub`."""

    kind = "stub"

    def __init__(self, header: str = "X-Stub-User", provider: str = "stub"):
        self.header = header
        self.provider = provider

    # -- the browser leg ------------------------------------------------------
    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge:
        """A kind with no provider to visit still has to hand the caller somewhere to go. This
        one bounces straight back to the callback, which is what makes it usable as an
        end-to-end test double: the whole round trip runs, offline, in-process."""
        return Challenge(redirect_url=f"{redirect_uri}?state={state}", state=state,
                         nonce=nonce, verifier=verifier)

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None:
        """`params` carries the query string plus the reserved keys `_headers` and `_peer`,
        which the callback route supplies to every kind."""
        headers = params.get("_headers") or {}
        login = str(headers.get(self.header) or headers.get(self.header.lower()) or "").strip()
        if not login:
            return None
        # `subject` must be STABLE across a rename — a login is not, which is why the built-in
        # GitHub kind uses the numeric id. A stub has nothing better, so it says so here.
        return Principal(subject=login, login=login, provider=self.provider)

    # -- reflection (booleans and non-secret names only) ----------------------
    def configured(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def detail(self) -> dict:
        return {"header": self.header, "note": "reference module — not for production"}

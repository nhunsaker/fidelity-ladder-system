"""$0 test for the reference Identity module: registration, the round trip, and reflection."""
from __future__ import annotations

from fls import modules
from fls.identity import Policy, Principal

from .module import StubIdentity
from .wiring import _factory


def test_wiring_registers_the_kind():
    modules.IDENTITY["stub"] = _factory
    assert modules.IDENTITY["stub"]().kind == "stub"


def test_completes_from_the_header():
    got = StubIdentity().complete({"_headers": {"X-Stub-User": "octocat"}},
                                  redirect_uri="/cb", nonce="n")
    assert got == Principal(subject="octocat", login="octocat", provider="stub")


def test_no_header_authenticates_nobody():
    assert StubIdentity().complete({"_headers": {}}, redirect_uri="/cb", nonce="n") is None


def test_the_allowlist_still_applies_to_a_custom_kind():
    """A registered kind does not get to bypass Policy — authentication and authorization stay
    separate no matter who wrote the provider."""
    p = StubIdentity().complete({"_headers": {"X-Stub-User": "stranger"}},
                                redirect_uri="/cb", nonce="n")
    assert Policy(allowed=frozenset({"octocat"})).permits(p) is False


def test_begin_round_trips_to_the_callback():
    ch = StubIdentity().begin(redirect_uri="https://h.test/api/auth/callback", state="s",
                              nonce="n")
    assert ch.redirect_url.startswith("https://h.test/api/auth/callback?state=s")

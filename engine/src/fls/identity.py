"""The `identity` seam — WHO a human operator is, as opposed to whether a message is authentic.

FLS already has an `auth` slot, and this is deliberately not it. `auth` is **message-level**:
`verify_inbound(body, signature_header)` + `outbound_token()` — it answers "did GitHub really
send this webhook". Nothing in it can answer "which person is holding the kill switch", because
a human session has no body to sign and no shared secret to sign it with.

The seams could not be merged even if the shapes were close. `modules.AUTH` is a **published
extension point** third parties populate through `FLS_MODULES`, and `Auth` is a *structural*
Protocol: widening it is silently breaking. An external module implementing only the two
existing methods keeps registering fine and then `AttributeError`s at session time, at the
worst possible moment — mid-request, on the path that decides whether a stranger may spend
money. A new registry is purely additive and cannot do that to anyone.

What lives here:

  * `Principal`      — a verified human, as the engine understands one.
  * `Identity`       — the Protocol a provider kind implements (`begin` / `complete`).
  * `SignedSession`  — the cookie carrier: HMAC-SHA256 over a base64url JSON payload, with
                       multi-key verification (rotation without a forced logout) and an epoch
                       (one env var bump logs everyone out, with no session store).
  * `Policy`         — who, of the people a provider will authenticate, this instance admits.
  * `NoneIdentity`   — the fail-closed default: nobody authenticates.

The provider kinds themselves (`oidc`, `github-oauth`, `proxy-header`) arrive in the next
slice. This module is stdlib-only and stays that way: outbound HTTP is `urllib.request`,
lazy-imported inside the transport functions exactly as `fls.modules` lazy-imports
`fls.github_surface`, so `pyproject.toml` keeps the core web-free and the grep-gate keeps
passing.

**Read env at call time. Never cache a module-level singleton.** `_auth_status()` and
`_demo_auth()` both already work this way and the test suite's `monkeypatch.setenv` depends on
it; resolving identity once at import (or in a startup event) would make every env-patching
test silently test the wrong thing.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger("fls.identity")

# The audience a session is minted for. The demo surface deliberately does NOT share this — see
# `fls.demo`. A visitor's self-chosen name is unverified by design ("it makes the ledger say
# who", not "it proves who"); an operator session authorizes spending money and killing work.
# One Principal flowing through one guard is one missing check away from conflating the two, so
# the audience is carried IN the signed payload and asserted on the way out.
OPERATOR_AUDIENCE = "operator"


@dataclass(frozen=True)
class Principal:
    """A verified human.

    `subject` is the provider's opaque stable id (OIDC `sub`, GitHub's numeric user id) and is
    the ONLY field written to the ledger. It is stable across a rename, and it is not PII — an
    email in an append-only JSONL is a decision you cannot take back, and the engine tree is
    grep-gated against exactly that kind of leak.

    `login` is the human-readable handle the allowlist matches on and the admin displays.
    """
    subject: str
    login: str = ""
    name: str = ""
    email: str = ""
    provider: str = ""
    audience: str = OPERATOR_AUDIENCE
    picture: str = ""          # the provider's avatar URL, when it issues one

    @property
    def display(self) -> str:
        """What a person should see. Falls back through the fields that might be blank."""
        return self.name or self.login or self.subject

    def public(self) -> dict:
        """The `/auth/me` payload. No token, no email unless the provider volunteered one."""
        return {"subject": self.subject, "login": self.login, "name": self.name,
                "email": self.email, "provider": self.provider, "audience": self.audience,
                "picture": self.picture}


@dataclass(frozen=True)
class Challenge:
    """What `begin()` hands back: where to send the browser, and the two secrets the callback
    will check it against. `state` is signed and travels through the provider; `nonce` is set as
    a short-lived cookie on our own origin. Both are needed — see `fls.app`'s callback route for
    why either alone is insufficient."""
    redirect_url: str
    state: str
    nonce: str
    verifier: str = ""


class Identity(Protocol):
    """A provider kind.

    Deliberately NOT named `authorize_url`/`exchange`: `proxy-header` performs no redirect at
    all, and a Protocol that assumes OAuth's shape would force it to lie. `begin` may raise for
    a kind that has no browser leg; `complete` reads whatever the request carries.

    `browser_leg` says which of the two shapes this kind is, and it is load-bearing rather than
    documentation. A kind that only raises from `begin` and is never asked for a session any
    other way cannot authenticate anybody — the guard denies every request forever and the
    instance is locked out. Kinds with `browser_leg = False` are authenticated per-request from
    what the request already carries, with no redirect and no session cookie.
    """
    kind: str
    browser_leg: bool

    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge: ...

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None: ...

    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...


# ── the session carrier ───────────────────────────────────────────────────────
def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class SignedSession:
    """HMAC-SHA256 bearer session, generalised from `fls.demo.DemoAuth`.

    Three deliberate differences from the demo signer it grew out of:

    * **base64url JSON payload** instead of colon-joined fields. A `Principal` carries several
      values and a display name can contain a colon; `rsplit(":", 2)` on that is a parser bug
      waiting for someone named "Smith: J".
    * **Multi-key verification.** Sign with the first secret, accept any. Rotating
      `FLS_SESSION_SECRET` then means appending the new key and later dropping the old one,
      instead of logging every operator out mid-shift — which is the thing that makes people
      not rotate.
    * **An epoch.** `FLS_SESSION_EPOCH` is mixed into the payload and compared on verify, so
      bumping one env var invalidates every outstanding session immediately. That is the
      "revoke everything now" button, and it costs no session store to have.

    Fail-closed with no secret, exactly like `DemoAuth`: an unconfigured signer mints nothing
    and verifies nothing. It does not fall back to an unsigned session, and it does not
    auto-generate a secret — under `uvicorn --workers N` a generated secret differs per process,
    which shows up as intermittent 401s that look like a bug in the cookie code and are not.
    """
    secrets: tuple[str, ...] = ()
    ttl_s: int = 12 * 3600
    epoch: str = "1"

    @classmethod
    def from_env(cls, ttl_s: int | None = None) -> SignedSession:
        """Read at call time. `FLS_SESSION_SECRET` may hold several comma-separated keys; the
        first is the signing key and the rest are accepted on verify (rotation)."""
        raw = os.environ.get("FLS_SESSION_SECRET", "")
        secrets = tuple(s.strip() for s in raw.split(",") if s.strip())
        env_ttl = os.environ.get("FLS_SESSION_TTL_S")
        if ttl_s is None and env_ttl:
            try:
                ttl_s = int(env_ttl)
            except ValueError:
                log.warning("FLS_SESSION_TTL_S is not an integer; using the default")
        return cls(secrets=secrets, ttl_s=ttl_s or 12 * 3600,
                   epoch=os.environ.get("FLS_SESSION_EPOCH", "1"))

    @property
    def configured(self) -> bool:
        return bool(self.secrets)

    def _sign(self, payload: str, secret: str) -> str:
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

    def mint(self, principal: Principal, now: float | None = None) -> str:
        """A token for this principal, or "" when unconfigured (never an unsigned token)."""
        if not self.configured:
            return ""
        exp = int((now if now is not None else time.time()) + self.ttl_s)
        body = dict(principal.public(), exp=exp, epoch=self.epoch)
        payload = _b64u(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        return f"{payload}.{self._sign(payload, self.secrets[0])}"

    def verify(self, token: str, now: float | None = None) -> Principal | None:
        """The principal the token carries, or None when it is missing, malformed, forged,
        expired, or minted under a superseded epoch. Never raises on hostile input — every
        failure path is the same None, so a caller cannot accidentally distinguish "forged"
        from "expired" and leak that distinction to an attacker."""
        if not self.configured or not token or "." not in token:
            return None
        payload, _, sig = token.rpartition(".")
        # `hmac.compare_digest` RAISES TypeError on a str containing a codepoint > 127, and a
        # cookie is attacker-controlled: one non-ASCII byte in the signature turned the
        # deny-by-default guard into an unhandled 500 with a traceback, pre-auth, on every
        # request. A real signature is hex, so anything non-ASCII is simply not one.
        if not sig.isascii() or not payload.isascii():
            return None
        if not any(hmac.compare_digest(sig, self._sign(payload, s)) for s in self.secrets):
            return None
        try:
            body = json.loads(_unb64u(payload))
        except Exception:  # noqa: BLE001 — any malformed payload is simply not a session
            return None
        if not isinstance(body, dict):
            return None
        if str(body.get("epoch", "")) != self.epoch:
            return None
        try:
            if float(body.get("exp", 0)) < (now if now is not None else time.time()):
                return None
        except (TypeError, ValueError):
            return None
        subject = str(body.get("subject") or "")
        if not subject:
            return None
        return Principal(
            subject=subject, login=str(body.get("login") or ""),
            name=str(body.get("name") or ""), email=str(body.get("email") or ""),
            provider=str(body.get("provider") or ""),
            audience=str(body.get("audience") or OPERATOR_AUDIENCE),
            picture=str(body.get("picture") or ""),
        )


# ── who this instance admits ──────────────────────────────────────────────────
@dataclass(frozen=True)
class Policy:
    """Authorization, which the provider does not do for you.

    An OAuth App is public by construction: *any* GitHub user on earth can complete the flow
    against it. GitHub authenticates; it does not decide who runs your harness. This does.

    Two modes, and **fail-closed when neither is set** — an instance that has turned identity on
    but named nobody is far more likely to be a half-finished deployment than a deliberate
    "everyone on the internet is welcome to kill my expeditions".
    """
    allowed: frozenset[str] = frozenset()
    allow_any: bool = False

    @classmethod
    def from_env(cls) -> Policy:
        raw = os.environ.get("FLS_ALLOWED_USERS", "")
        allowed = frozenset(u.strip().lower() for u in raw.split(",") if u.strip())
        flag = os.environ.get("FLS_ALLOW_ANY_AUTHENTICATED", "").strip().lower()
        return cls(allowed=allowed, allow_any=flag in {"1", "true", "yes", "on"})

    @property
    def name(self) -> str:
        if self.allowed:
            return "allowlist"
        return "any-authenticated" if self.allow_any else "unset"

    @property
    def configured(self) -> bool:
        return bool(self.allowed) or self.allow_any

    def permits(self, principal: Principal) -> bool:
        """Matched case-insensitively against `login`, `subject`, or `email` — whichever the
        operator listed. An allowlist that is set wins over allow-any: naming people is the
        more specific intent.

        `email` is here because many OIDC providers issue no `preferred_username` at all, and
        for those the only identifier a human can reasonably type into a config file is the
        address they sign in with. Matching on it does NOT put it in the ledger: the ledger
        stores `subject`, and `login` still never falls back to the email, so the address stays
        out of the append-only record and out of anything posted to a GitHub issue.
        """
        if principal.audience != OPERATOR_AUDIENCE:
            return False
        if self.allowed:
            return any((v or "").lower() in self.allowed
                       for v in (principal.login, principal.subject, principal.email))
        return self.allow_any

    def detail(self) -> dict:
        """Reflection payload. A COUNT, never the names — the list is operational detail a
        stranger reading `/system` has no business enumerating."""
        return {"policy": self.name, "allowlist_count": len(self.allowed)}

    @staticmethod
    def candidates(principal: Principal) -> str:
        """What the operator would have to add to admit this person — for the refusal log.

        "Refused by policy" with nothing else is a dead end: the person configuring the
        allowlist cannot see which identifier the provider actually issued, and different
        providers issue different ones (a GitHub login, a Clerk email, an opaque sub). So the
        refusal names the candidates.

        The email is MASKED to its first character and domain. That is enough for someone to
        recognise their own address and paste the right thing into the config, and not enough
        to harvest an address list out of a log file.
        """
        email = principal.email or ""
        if "@" in email:
            local, _, domain = email.partition("@")
            email = f"{local[:1]}***@{domain}"
        parts = [f"sub={principal.subject}"]
        if principal.login:
            parts.append(f"login={principal.login}")
        if email:
            parts.append(f"email={email}")
        return " ".join(parts)


# ── the fail-closed default ───────────────────────────────────────────────────
class NoneIdentity:
    """No operator identity configured — nobody authenticates.

    ⚠️ This reports `configured=False, available=False`, which is the **opposite** of
    `auth`'s `none` kind, and the difference is intentional rather than an oversight.

    `auth`'s local mode is a complete, coherent posture: there is no GitHub App, so there is no
    webhook to verify, and refusing every signature is exactly right. Nobody authenticating an
    exposed operator console is not a posture — it is a hazard. The console holds a kill switch
    and two endpoints that spend money. Reflection says so plainly so that `/system` and the
    admin's Modules card can show it as something to fix, not as a settled configuration.
    """
    kind = "none"
    browser_leg = True

    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge:
        raise RuntimeError("no identity provider is configured (FLS_IDENTITY_KIND is 'none')")

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None:
        return None

    def configured(self) -> bool:
        return False

    def available(self) -> bool:
        return False

    def detail(self) -> dict:
        return {"mode": "open",
                "note": "no operator identity configured — every API route is unauthenticated"}


def active_kind() -> str:
    """Which identity kind this instance is running, read at call time.

    Explicit via `FLS_IDENTITY_KIND`; otherwise auto-selected. Auto-selection deliberately does
    NOT sniff for OAuth credentials and switch itself on: turning on a deny-by-default guard as
    a side effect of an env var appearing is how a deploy locks its own operator out. Identity
    is opt-in, and the opt-in is naming the kind.
    """
    return (os.environ.get("FLS_IDENTITY_KIND") or "none").strip() or "none"


def validate_kind() -> None:
    """Refuse to start on an unknown `FLS_IDENTITY_KIND`. Called from the startup hook.

    This exists because the alternative failure is silent and miserable. The guard activates on
    any kind that is not `none`, so a typo — `githuboauth` — left the guard on with no provider
    behind it: every route 401s, `/auth/login` 503s, and nobody can sign in to find out why.
    Fail-closed is the right posture for an auth misconfiguration; being fail-closed *and*
    unexplained is not.

    Refusing to boot is the precedent `load_modules` already sets for the same class of
    mistake, and an operator reading "not a registered kind, have: ..." in the service log is
    two minutes from fixed instead of an hour.
    """
    from fls.modules import IDENTITY
    kind = active_kind()
    if kind not in IDENTITY:
        raise RuntimeError(
            f"FLS_IDENTITY_KIND='{kind}' is not a registered identity kind "
            f"(have: {', '.join(sorted(IDENTITY))}). Refusing to start: the guard would be "
            "active with no provider behind it, locking every operator out with no way to "
            "sign in and no visible reason.")


def resolve(kind: str | None = None):
    """The active `Identity`, built fresh from env on every call.

    An unknown kind resolves to `NoneIdentity` here, as defence in depth — `validate_kind()`
    has already refused to boot on one, so reaching this branch means the registry changed
    under a running process. It is a deny, not a fallback to open: `NoneIdentity` authenticates
    nobody, and the guard stays on.
    """
    from fls.modules import IDENTITY
    name = kind or active_kind()
    factory = IDENTITY.get(name)
    if factory is None:
        log.error("FLS_IDENTITY_KIND='%s' is not a registered kind (have: %s) — "
                  "falling back to 'none'", name, ", ".join(sorted(IDENTITY)))
        return NoneIdentity()
    return factory()


# ── the short-lived state token ───────────────────────────────────────────────
@dataclass(frozen=True)
class StateSigner:
    """The `state` parameter, signed, carrying what the callback needs to check itself.

    CSRF on an OAuth callback needs **both halves**, and it is worth writing down why neither
    is sufficient alone, because shipping one of them looks like shipping the defence:

    * **Signed state alone** is replayable inside its TTL and is bound to nobody. An attacker
      who observes one can feed it back from their own browser.
    * **A cookie alone** cannot carry `return_to` — the provider round-trips only `state`, so a
      deep link would have to travel through the attacker-influenced URL to survive.

    So: a random nonce goes in a short-lived cookie on our own origin, and the same nonce goes
    in the signed state that travels through the provider. The callback demands both and
    compares them. Ten minutes is plenty for a human to click "Authorize".
    """
    secrets: tuple[str, ...] = ()
    ttl_s: int = 600

    @classmethod
    def from_env(cls) -> StateSigner:
        return cls(secrets=SignedSession.from_env().secrets)

    @property
    def configured(self) -> bool:
        return bool(self.secrets)

    def _sign(self, payload: str, secret: str) -> str:
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

    def mint(self, *, nonce: str, return_to: str = "/",
             now: float | None = None) -> str:
        """⚠️ The PKCE `code_verifier` is deliberately NOT carried here.

        `state` is base64url JSON travelling in the authorization URL: signed, but not
        encrypted, and readable by the IdP, browser history, a Referer leak or any logging
        proxy. Putting the verifier in it hands away the one secret PKCE exists to keep, which
        defeats the extension entirely while looking like it is enabled. The verifier rides the
        nonce cookie instead — our own origin, HttpOnly, never sent to the provider.
        """
        if not self.configured:
            return ""
        exp = int((now if now is not None else time.time()) + self.ttl_s)
        body = {"nonce": nonce, "exp": exp, "return_to": return_to}
        payload = _b64u(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        return f"{payload}.{self._sign(payload, self.secrets[0])}"

    def verify(self, state: str, now: float | None = None) -> dict | None:
        if not self.configured or not state or "." not in state:
            return None
        payload, _, sig = state.rpartition(".")
        if not sig.isascii() or not payload.isascii():   # see SignedSession.verify — same trap
            return None
        if not any(hmac.compare_digest(sig, self._sign(payload, s)) for s in self.secrets):
            return None
        try:
            body = json.loads(_unb64u(payload))
        except Exception:  # noqa: BLE001 — malformed is simply not a state
            return None
        if not isinstance(body, dict):
            return None
        try:
            if float(body.get("exp", 0)) < (now if now is not None else time.time()):
                return None
        except (TypeError, ValueError):
            return None
        if not body.get("nonce"):
            return None
        return body


def safe_return_to(raw: str | None, default: str = "/") -> str:
    """A same-site path, or the default. Never a caller-supplied absolute URL.

    An open redirect on a login route is worth more to an attacker than on any other route: the
    victim arrives having *just* proven they trust this origin enough to sign into it. The rules
    are deliberately narrow — one leading slash, no scheme, no netloc — because every clever
    relaxation of them is a CVE somebody already wrote.

    `//evil.test` and `/\\evil.test` are the two that catch people: a browser reads both as
    protocol-relative absolute URLs while a naive "starts with /" check waves them through.
    """
    from urllib.parse import urlsplit
    if not raw or not isinstance(raw, str):
        return default
    raw = raw.strip()
    if len(raw) > 512 or not raw.startswith("/"):
        return default
    if raw.startswith("//") or raw.startswith("/\\"):
        return default
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc:
        return default
    return raw


def cookie_secure() -> bool:
    """Whether session cookies carry `Secure`. On by default; `FLS_COOKIE_SECURE=0` turns it off
    for plain-HTTP local development.

    This has to be configurable and it is not a weakening. `TestClient` speaks
    `http://testserver`, so an unconditional `Secure` flag means the browser (and httpx's jar)
    never sends the cookie back — every integration test 401s with no visible reason, and the
    obvious conclusion is that the session code is broken when it is fine.
    """
    raw = os.environ.get("FLS_COOKIE_SECURE", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def redirect_uri() -> str:
    """The callback URL, from `FLS_AUTH_REDIRECT_URI`. Required; "" when unset (fail closed).

    **Never derived from the request.** Two independent reasons, and the first one bites the
    reference deploy specifically:

    1. The reference Caddyfile proxies with `handle_path /api/*`, which **strips** the prefix
       before the app sees it. `request.url_for()` therefore returns a URL missing `/api`, and
       the provider — which exact-matches this string against what is registered — refuses it.
    2. Deriving it from `Host` or `X-Forwarded-*` turns host-header injection into redirect_uri
       manipulation, which is how an authorization code ends up at somebody else's server.

    So it is configuration, it must match the provider's registered callback byte for byte, and
    an unset value disables the flow rather than guessing.
    """
    return (os.environ.get("FLS_AUTH_REDIRECT_URI") or "").strip()


# ── transport (the only outbound I/O in this module) ──────────────────────────
_UA = "fls-identity/1.0"
_TIMEOUT = 10


def _post_form(url: str, data: dict, headers: dict | None = None) -> dict:
    """POST an x-www-form-urlencoded body, parse a JSON response. Lazy-imports urllib so the
    engine core stays web-dependency-free (the same rule `fls.modules` follows for
    `fls.github_surface`). Tests monkeypatch this function, never the network."""
    import urllib.error
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")  # noqa: S310 — https URL from config/discovery
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", _UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        # A provider that reports failure with a status code still owes us its body — the error
        # description in it is the difference between a useful log line and "it didn't work".
        try:
            return json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return {"error": f"http_{e.code}"}
    except Exception as e:  # noqa: BLE001 — a transport failure is a failed login, not a 500
        log.warning("identity: token request failed: %s", str(e)[:200])
        return {"error": "transport"}


def _get_json(url: str, headers: dict | None = None) -> dict:
    """GET a JSON document (userinfo, GitHub's /user, OIDC discovery)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, method="GET")  # noqa: S310 — https URL from config/discovery
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            return json.loads(resp.read().decode() or "{}")
    except Exception as e:  # noqa: BLE001
        log.warning("identity: GET %s failed: %s", url.split("?")[0], str(e)[:200])
        return {}


def _client_pair() -> tuple[str, str]:
    return (os.environ.get("FLS_OAUTH_CLIENT_ID", "").strip(),
            os.environ.get("FLS_OAUTH_CLIENT_SECRET", "").strip())


def _unverified_claims(id_token: str) -> dict:
    """The ID token's payload, WITHOUT verifying its signature.

    **OIDC Core §3.1.3.7 explicitly permits this** when the token was received directly from the
    token endpoint over TLS by a confidential client using the authorization-code flow: the TLS
    channel and the client secret are what authenticate it, so the signature is redundant. This
    is the sanctioned path, not a corner cut, and it is why FLS needs no JWT dependency.

    The claims are still checked (`iss`, `aud`, `exp`, `nonce`) — TLS is what makes them
    meaningful — and identity itself is taken from `userinfo`, not from here.

    The shortcut stops being defensible in five situations, listed so that the day one of them
    arrives, the docs already say to reach for a real JWT library:

      1. A public client (no secret) — nothing authenticates the channel's other end.
      2. Any front-channel token (an implicit/hybrid `id_token` in a redirect). Never add one.
      3. Forwarding the ID token onward as proof to another service — it must then stand alone.
      4. A provider with no real `userinfo` endpoint (some Azure AD configurations), where the
         ID token becomes the only source of identity rather than a corroborating one.
      5. Caching it and re-reading claims later for authorization decisions — the TLS context
         that justified trusting it is long gone by then.
    """
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(_unb64u(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ── kind: oidc ────────────────────────────────────────────────────────────────
class OidcIdentity:
    """The general mechanism: authorization-code flow against any OIDC issuer.

    This kind is the reason the seam is worth building. GitHub's OAuth is a special case (see
    `GitHubOAuthIdentity`); OIDC is the standard every other provider speaks, so an instance
    that outgrows GitHub repoints one env var instead of gaining a second auth code path.
    """
    kind = "oidc"
    browser_leg = True

    def __init__(self, issuer: str | None = None):
        self.issuer = (issuer if issuer is not None
                       else os.environ.get("FLS_OIDC_ISSUER", "")).strip().rstrip("/")
        self.client_id, self.client_secret = _client_pair()

    # -- discovery ------------------------------------------------------------
    # Two well-known paths, tried in order. OIDC defines `openid-configuration`; RFC 8414
    # defines `oauth-authorization-server`, and some providers (Clerk documents the latter)
    # publish one, the other, or both. Trying both costs one extra request on a cold path and
    # removes an entire class of "discovery failed" that looks like a broken issuer URL.
    _WELL_KNOWN = ("/.well-known/openid-configuration", "/.well-known/oauth-authorization-server")

    def discover(self) -> dict:
        """The issuer's discovery document. Not cached: this module reads its world at call
        time, and a login is not a hot path."""
        if not self.issuer:
            return {}
        for path in self._WELL_KNOWN:
            doc = _get_json(f"{self.issuer}{path}")
            if doc.get("authorization_endpoint"):
                return doc
        return {}

    def configured(self) -> bool:
        return bool(self.issuer and self.client_id and self.client_secret)

    def available(self) -> bool:
        """Cheap and offline, like every other slot's `available()` — configuration presence,
        not a live probe. Reflection must never make a network call; a `/system` that hangs
        because an IdP is slow is worse than one that reports a boolean."""
        return self.configured()

    def detail(self) -> dict:
        return {"issuer": self.issuer or None, "client_id_set": bool(self.client_id)}

    # -- the browser leg ------------------------------------------------------
    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge:
        from urllib.parse import urlencode
        doc = self.discover()
        authorize = doc.get("authorization_endpoint")
        if not authorize:
            raise RuntimeError(f"OIDC discovery failed for issuer {self.issuer!r}")
        params = {
            "response_type": "code", "client_id": self.client_id,
            "redirect_uri": redirect_uri, "scope": "openid profile email",
            "state": state, "nonce": nonce,
        }
        # PKCE only when discovery advertises it. Sending a challenge to a provider that does
        # not support the extension is, at best, ignored — and at worst rejected outright.
        methods = doc.get("code_challenge_methods_supported") or []
        if verifier and "S256" in methods:
            digest = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = _b64u(digest)
            params["code_challenge_method"] = "S256"
        return Challenge(redirect_url=f"{authorize}?{urlencode(params)}",
                         state=state, nonce=nonce, verifier=verifier)

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None:
        code = (params.get("code") or "").strip()
        if not code:
            return None
        doc = self.discover()
        token_endpoint = doc.get("token_endpoint")
        if not token_endpoint:
            return None
        form = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": redirect_uri, "client_id": self.client_id,
                "client_secret": self.client_secret}
        if verifier and "S256" in (doc.get("code_challenge_methods_supported") or []):
            form["code_verifier"] = verifier
        tok = _post_form(token_endpoint, form)
        if tok.get("error") or not tok.get("access_token"):
            log.warning("identity(oidc): token exchange refused: %s",
                        str(tok.get("error") or "no access_token")[:120])
            return None
        # Claim checks on the unverified payload — see `_unverified_claims` for why that is the
        # sanctioned path here, and for the five conditions under which it stops being one.
        #
        # ⚠️ FAIL CLOSED when there is no id_token, or it will not parse. This was previously
        # `if claims:` — so a token response that simply omitted the id_token skipped the iss,
        # aud, exp AND nonce checks wholesale and built a Principal straight from userinfo. That
        # makes the nonce binding and the audience check (the defence against a code minted for
        # a different client of the same IdP) optional at the attacker's discretion, which is
        # the same as not having them. An OIDC provider always returns an id_token; one that
        # does not is not speaking OIDC and is not something to authenticate against.
        claims = _unverified_claims(tok.get("id_token") or "")
        if not claims:
            log.warning("identity(oidc): no parseable id_token in the token response — refused")
            return None
        iss = str(claims.get("iss", "")).rstrip("/")
        if iss and self.issuer and iss != self.issuer:
            log.warning("identity(oidc): issuer mismatch")
            return None
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if self.client_id and self.client_id not in [str(a) for a in audiences if a]:
            log.warning("identity(oidc): audience mismatch")
            return None
        try:
            if float(claims.get("exp", 0)) < time.time():
                log.warning("identity(oidc): id_token expired")
                return None
        except (TypeError, ValueError):
            return None
        if nonce and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            log.warning("identity(oidc): nonce mismatch (replay refused)")
            return None
        userinfo_endpoint = doc.get("userinfo_endpoint")
        info = (_get_json(userinfo_endpoint,
                          {"Authorization": f"Bearer {tok['access_token']}"})
                if userinfo_endpoint else {})
        return principal_from_oidc(info or claims, provider=self.kind)


def principal_from_oidc(info: dict, provider: str = "oidc") -> Principal | None:
    """Provider JSON -> Principal. Pure: no I/O, so the mapping is testable from a fixture."""
    subject = str(info.get("sub") or "")
    if not subject:
        return None
    # `email` is deliberately NOT a fallback for `login`. `login` flows into `display`, which
    # is written to the expedition record and posted to a public GitHub issue comment, and for
    # any IdP that omits `preferred_username` that quietly published the operator's email
    # address. An empty login is fine — `display` falls through to `name`, then the subject.
    return Principal(
        subject=subject,
        login=str(info.get("preferred_username") or ""),
        name=str(info.get("name") or ""),
        email=str(info.get("email") or ""),
        provider=provider,
        picture=str(info.get("picture") or ""),
    )


# ── kind: github-oauth ────────────────────────────────────────────────────────
GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class GitHubOAuthIdentity:
    """The one special case that pays for itself, because FLS is already GitHub-centric.

    ⚠️ **GitHub's OAuth is not OpenID Connect.** There is no discovery document and no ID token
    for user login, which is precisely why it cannot ride the `oidc` kind. (This is unrelated to
    GitHub Actions OIDC, which is workload identity for CI — a different thing with a confusingly
    similar name.)

    Scope is `read:user`, or nothing at all: `GET /user` returns the public profile either way.
    The access token is discarded the moment the profile is read — we want identity, not
    delegation, and a consent screen asking for repo access in order to log into a console is a
    smell an operator is right to distrust.
    """
    kind = "github-oauth"
    browser_leg = True

    def __init__(self):
        self.client_id, self.client_secret = _client_pair()

    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def available(self) -> bool:
        return self.configured()

    def detail(self) -> dict:
        return {"provider": "github", "client_id_set": bool(self.client_id),
                "scope": "read:user",
                "note": "GitHub OAuth is not OIDC — no discovery, no id_token"}

    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge:
        from urllib.parse import urlencode
        params = {"client_id": self.client_id, "redirect_uri": redirect_uri,
                  "scope": "read:user", "state": state}
        return Challenge(redirect_url=f"{GITHUB_AUTHORIZE}?{urlencode(params)}",
                         state=state, nonce=nonce, verifier=verifier)

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None:
        code = (params.get("code") or "").strip()
        if not code:
            return None
        tok = _post_form(GITHUB_TOKEN_URL, {
            "client_id": self.client_id, "client_secret": self.client_secret,
            "code": code, "redirect_uri": redirect_uri,
        })
        # ⚠️ GitHub returns token-endpoint errors with **HTTP 200** and an `error` key in the
        # body. Checking the status code alone reads a refused exchange as a success and then
        # fails further along with a confusing message, so the body is what decides.
        if tok.get("error") or not tok.get("access_token"):
            log.warning("identity(github): token exchange refused: %s",
                        str(tok.get("error") or "no access_token")[:120])
            return None
        info = _get_json(GITHUB_USER_URL, {
            "Authorization": f"Bearer {tok['access_token']}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        return principal_from_github(info)


def principal_from_github(info: dict) -> Principal | None:
    """GitHub `/user` JSON -> Principal. Pure; the numeric `id` is the stable subject (a login
    can be renamed, an id cannot). `email` is usually null without the `user:email` scope, which
    we deliberately do not request."""
    subject = str(info.get("id") or "")
    login = str(info.get("login") or "")
    if not subject or not login:
        return None
    return Principal(subject=subject, login=login, name=str(info.get("name") or ""),
                     email=str(info.get("email") or ""), provider="github",
                     picture=str(info.get("avatar_url") or ""))


# ── kind: proxy-header ────────────────────────────────────────────────────────
class ProxyHeaderIdentity:
    """Trust a header set by an authenticating reverse proxy (oauth2-proxy, Caddy
    `forward_auth`, an ingress with OIDC already terminated).

    Twenty-five lines, no OAuth code, and — since Caddy is already the reference deploy — very
    likely how most installs will actually run.

    The whole security of this kind is that the header is unforgeable, which is only true if
    nothing but the proxy can reach the app. Two non-negotiables enforce that here:

      * It is active **only when explicitly configured**. A stray `X-Forwarded-User` on an
        instance running any other kind is ignored completely, which is asserted by a test.
      * The peer must be in `FLS_TRUSTED_PROXIES`. Without that list, this kind refuses to
        authenticate anyone rather than trusting a header from an arbitrary client.
    """
    kind = "proxy-header"
    # No redirect, no session cookie: the proxy in front already authenticated the request, and
    # every request carries the proof. The guard authenticates this kind per-request.
    browser_leg = False

    def __init__(self):
        self.header = (os.environ.get("FLS_PROXY_USER_HEADER") or "X-Forwarded-User").strip()
        raw = os.environ.get("FLS_TRUSTED_PROXIES", "")
        self.trusted = frozenset(p.strip() for p in raw.split(",") if p.strip())

    def configured(self) -> bool:
        return bool(self.trusted)

    def available(self) -> bool:
        return self.configured()

    def detail(self) -> dict:
        return {"header": self.header, "trusted_proxy_count": len(self.trusted)}

    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge:
        raise RuntimeError(
            "proxy-header identity has no browser leg — the proxy in front of this app "
            "performs the sign-in and sets the header (see `browser_leg`)")

    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None:
        """`params` carries the reserved keys `_headers` (a case-insensitive mapping) and
        `_peer` (the immediate client address), which the route supplies for every kind."""
        if not self.configured():
            return None
        peer = str(params.get("_peer") or "")
        if peer not in self.trusted:
            log.warning("identity(proxy-header): refused a header from untrusted peer")
            return None
        headers = params.get("_headers") or {}
        login = ""
        try:
            login = str(headers.get(self.header) or headers.get(self.header.lower()) or "").strip()
        except Exception:  # noqa: BLE001
            return None
        if not login:
            return None
        return Principal(subject=login, login=login, provider="proxy-header")

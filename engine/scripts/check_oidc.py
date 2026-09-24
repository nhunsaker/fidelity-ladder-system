#!/usr/bin/env python3
"""Preflight an OIDC issuer before wiring it into an instance.

    engine/.venv/bin/python engine/scripts/check_oidc.py https://clerk.example.com

Answers the question that otherwise costs a deploy and a locked-out console: *will this engine's
`oidc` kind actually work against that issuer?* Read-only, no credentials, no browser. It checks
what FLS genuinely depends on and nothing it does not.

Exit 0 = usable, 1 = it would fail.
"""
from __future__ import annotations

import json
import sys
import urllib.request

WELL_KNOWN = ("/.well-known/openid-configuration", "/.well-known/oauth-authorization-server")
OK, WARN, BAD = "ok  ", "warn", "FAIL"


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "fls-check-oidc/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - operator-supplied https URL
            return json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}


def check(issuer: str) -> list[tuple[str, str]]:
    issuer = issuer.strip().rstrip("/")
    rows: list[tuple[str, str]] = []
    doc, used = {}, None
    for path in WELL_KNOWN:
        d = get(issuer + path)
        if d.get("authorization_endpoint"):
            doc, used = d, path
            break
        rows.append((WARN, f"{path} -> {d.get('_error') or 'no authorization_endpoint'}"))
    if not doc:
        rows.append((BAD, "no usable discovery document at either well-known path"))
        return rows
    rows.append((OK, f"discovery found at {used}"))

    declared = str(doc.get("issuer", "")).rstrip("/")
    if declared == issuer:
        rows.append((OK, f"issuer matches: {declared}"))
    else:
        rows.append((BAD, f"issuer MISMATCH: doc says {declared!r}, you configured {issuer!r}. "
                          "The id_token check compares these, so every sign-in would be refused"))

    for key in ("authorization_endpoint", "token_endpoint"):
        if doc.get(key):
            rows.append((OK, f"{key}: {doc[key]}"))
        else:
            rows.append((BAD, f"{key} missing - the authorization-code flow cannot run"))

    if doc.get("userinfo_endpoint"):
        rows.append((OK, f"userinfo_endpoint: {doc['userinfo_endpoint']}"))
    else:
        rows.append((WARN, "no userinfo_endpoint - identity would fall back to id_token claims, "
                           "which is one of the five cases where skipping signature "
                           "verification stops being defensible (see _unverified_claims)"))

    methods = doc.get("token_endpoint_auth_methods_supported") or []
    if not methods or "client_secret_post" in methods:
        rows.append((OK, "client_secret_post supported (how this engine authenticates)"))
    elif "client_secret_basic" in methods:
        rows.append((BAD, "issuer accepts client_secret_basic but NOT client_secret_post - "
                          "the token exchange would be rejected"))

    pkce = doc.get("code_challenge_methods_supported") or []
    if "S256" in pkce:
        rows.append((OK, "PKCE S256 advertised - it will be used"))
    else:
        rows.append((WARN, "no S256 PKCE advertised - it will be skipped (acceptable for a "
                           "confidential client with an exact-match redirect URI)"))

    scopes = doc.get("scopes_supported") or []
    missing = [s for s in ("openid", "profile", "email") if scopes and s not in scopes]
    if missing:
        rows.append((WARN, f"scopes not advertised: {missing}"))
    else:
        rows.append((OK, "openid/profile/email available"))

    claims = doc.get("claims_supported") or []
    if claims:
        has_user = [c for c in ("preferred_username", "email") if c in claims]
        if has_user:
            rows.append((OK, f"FLS_ALLOWED_USERS can match on: {', '.join(has_user)}"))
        else:
            rows.append((WARN, "neither preferred_username nor email in claims_supported - the "
                               "allowlist would have to name opaque subject ids"))
    return rows


def main(issuer: str) -> int:
    rows = check(issuer)
    print(f"\nOIDC preflight - {issuer}\n" + "-" * 74)
    for status, msg in rows:
        print(f"  [{status}] {msg}")
    bad = sum(1 for s, _ in rows if s == BAD)
    print("-" * 74)
    if bad:
        print("  VERDICT: unusable as configured\n")
        return 1
    print("  VERDICT: usable - set FLS_IDENTITY_KIND=oidc and FLS_OIDC_ISSUER to the above\n")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))

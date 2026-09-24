# Modules — the connector slots

The ladder's connections to the outside world are **module slots**. The code in this repo
holds the mechanisms; your instance chooses a `kind` per slot and wires it with environment
variables. The split is strict and load-bearing:

> **Choice = ANCHOR (policy, PR-reviewed) · connection = env (identity + secrets) ·
> status = `GET /system` (kinds + booleans, never a secret value).**

| Slot | What it is | Built-in kind(s) |
|---|---|---|
| [`auth`](#auth) | inbound webhook verification + the outbound token (MESSAGE level) | `github-app`, `none` |
| [`identity`](#identity) | who the human operating the console is (SESSION level) | `github-oauth`, `oidc`, `proxy-header`, `none` |
| [`ideas`](#ideas) | where ideas come from — every source enters by the ONE admission door | `manual`, `feeder` |
| [`lenses`](#lenses) | managed audit/brainstorm passes over a vessel (files through a sink, same as `ideas`) | none — FLS_MODULES-only |
| [`sources`](#sources) | the repo(s) whose issues ARE expeditions, + deploy targets | `github`, `local` |
| [`workers`](#workers) | who fulfils builder work ("pass-back") | `api`, `skill-server` |
| [`environment`](#environment) | where a rung's builder/verifier work actually runs | `worktree` |

**Local-mode is the fresh-install default.** With no GitHub env set, `auth` auto-selects
`none` and `sources` auto-selects `local` — both no-op-safe, needing zero configuration. `GET
/system` also reports a top-level `app` boolean (`true` only when `auth.kind == "github-app"`).
Set `FLS_REPO` + `FLS_WEBHOOK_SECRET` + `GITHUB_TOKEN` (see [getting-started §3](getting-started.md))
to switch to the real GitHub surface — auto-detected, or force it explicitly with
`FLS_SOURCE_KIND=github` / `FLS_AUTH_KIND=github-app` (and the reverse, `local`/`none`, to force
local-mode even with GitHub env present).

Check your wiring any time:

```bash
curl -s https://<your-harness>/system | python3 -m json.tool
```

Every slot reports `kind`, `configured` (required env present — booleans only), `available`
(the module's own cheap check), and a `docs_url` pointing back here. An unconfigured slot
**fails closed** — the ladder refuses the affected action rather than pretending.

## auth

Two responsibilities, one small Protocol: `verify_inbound(body, signature_header)` (fail-closed
HMAC check on every webhook delivery) and `outbound_token()` (what posts labels + comments
back). The built-in `github-app` kind reads `FLS_WEBHOOK_SECRET` + `GITHUB_TOKEN` — see
[getting-started §3](getting-started.md) for the full connect flow, including the PAT-vs-App-
installation-token identity tradeoff.

`none` is the built-in local-mode kind (auto-selected when the App env isn't set): there is no
inbound webhook to verify, so `verify_inbound` always refuses (no-op-safe, not permissive — it
never admits on optimism just because nothing is configured) and `outbound_token` returns
`None`. Nothing in the local-only flow (admission, climb, kill, wall) needs a webhook or token.

## identity

**Who the human at the console is.** Distinct from [`auth`](#auth), and the distinction is the
reason this slot exists rather than being folded into it:

| | `auth` | `identity` |
|---|---|---|
| Scope | a **message** | a **session** |
| Asks | "did the App really send this webhook?" | "which person is holding the kill switch?" |
| Mechanism | HMAC over a request body | a browser sign-in + a signed cookie |

They are not interchangeable. A human session has no body to sign and no shared secret to sign
it with; `verify_inbound(body, signature)` cannot be made to answer the question. And widening
the published `Auth` Protocol would be silently breaking — a third-party module implementing
only the two existing methods keeps registering fine through `FLS_MODULES` and then fails at
session time, mid-request, on the path that decides whether a stranger may spend money. A new
registry is purely additive and cannot do that to anyone.

### The default is `none`, and it is reported as a hazard

`identity.kind` defaults to `none`: nobody authenticates, every route is open, and the guard is
dormant. This is the right default for a laptop and the wrong one for anything reachable.

⚠️ Unlike `auth`'s `none` — which reports `configured: true, available: true`, because local mode
genuinely is a complete posture — `identity`'s `none` reports **`false` / `false`**. Nobody
authenticating an exposed operator console is not a posture, it is a hazard: the console holds a
kill switch and two endpoints that spend money. `GET /system` says so plainly so the System card
can show it as something to fix rather than as a settled setting.

Identity is **opt-in by naming the kind**. Auto-selection deliberately does not sniff for
credentials and switch itself on — turning a deny-by-default guard on as a side effect of an env
var appearing is how a deploy locks its own operator out.

### Authorization is separate from authentication

A provider tells you the sign-in succeeded. It does not tell you this person may run your
harness — a public OAuth app will happily authenticate any stranger on the internet. That
decision is `Policy`:

| Env | Effect |
|---|---|
| `FLS_ALLOWED_USERS` | comma-separated logins (or provider subject ids); case-insensitive |
| `FLS_ALLOW_ANY_AUTHENTICATED` | admit anyone the provider vouches for — for an instance already behind an SSO perimeter |

**Neither set fails closed.** An instance that turned identity on and named nobody is far more
often a half-finished deployment than a deliberate invitation. An allowlist that *is* set beats
allow-any: naming people is the more specific intent.

`/system` reports the policy NAME and an allowlist **count**. Never the names — who can kill
your expeditions is operational detail a stranger reading a status endpoint has no business
enumerating.

### Sessions

`SignedSession` carries the principal in an HMAC-SHA256-signed, base64url JSON cookie. No
session store, and three properties worth knowing:

- **`FLS_SESSION_SECRET` is required and never auto-generated.** Under `uvicorn --workers N` a
  generated secret differs per process, which presents as intermittent 401s that look like a bug
  in the cookie code and are not.
- **Rotation is not a forced logout.** The variable accepts several comma-separated keys: the
  first signs, all of them verify. Append the new key, let old sessions drain, drop the old key.
  A rotation that logs everyone out mid-shift is a rotation nobody performs.
- **`FLS_SESSION_EPOCH` is the revoke-everything button.** It is mixed into every payload and
  compared on verify, so bumping it invalidates every outstanding session at once — again with
  no session store to maintain.

Only the provider's `subject` is ever written to the ledger — an opaque, rename-stable id for
`oidc` and `github-oauth`. Not an email: an append-only JSONL is a decision you cannot take
back, and `login` deliberately does not fall back to the `email` claim, because `login` also
flows into the display name that gets posted to a public GitHub issue comment. (For
`proxy-header` the subject is whatever the proxy asserts — see that kind's warning.)

### The kinds

| kind | When it is the right one |
|---|---|
| `github-oauth` | The harness is already GitHub-centric and the operators have GitHub accounts |
| `oidc` | Anything else — Google, Microsoft, Okta, or a broker federating several |
| `proxy-header` | An authenticating reverse proxy already sits in front (oauth2-proxy, Caddy `forward_auth`) |
| `none` | A laptop |

**`github-oauth`** wants a GitHub **OAuth App**, not a GitHub App — an OAuth App answers "who is
this person", a GitHub App is an installable bot with repository permissions. Register the
callback URL, set `FLS_OAUTH_CLIENT_ID` / `FLS_OAUTH_CLIENT_SECRET`, done. Scope is `read:user`
and the access token is discarded the moment the profile is read: we want identity, not
delegation, and a consent screen asking for repo access in order to log into a console is a
smell an operator is right to distrust.

⚠️ **GitHub's OAuth is not OpenID Connect.** There is no discovery document and no ID token for
user login, which is exactly why it needs its own kind rather than riding `oidc`. (Unrelated to
GitHub Actions OIDC, which is workload identity for CI — a confusingly similar name for a
different thing.)

**`oidc`** is the general mechanism: discovery, authorization-code flow, `userinfo`. The ID
token's signature is deliberately **not** verified locally, which is the sanctioned path rather
than a corner cut — [OIDC Core §3.1.3.7](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation)
permits it when the token arrives straight from the token endpoint over TLS to a confidential
client. The claims (`iss`, `aud`, `exp`, `nonce`) are still checked, identity is taken from
`userinfo`, and FLS needs no JWT dependency. The docstring on `_unverified_claims` lists the
five conditions under which that stops being true and you should reach for one.

**`proxy-header`** trusts a header from the proxy that already authenticated the request. The
header is only unforgeable if nothing but the proxy can reach the app, so the kind refuses any
peer that is not in `FLS_TRUSTED_PROXIES`, and a stray `X-Forwarded-User` on an instance running
any other kind is ignored entirely.

It sets `browser_leg = False`, which is not documentation — it is what makes the kind work.
There is no sign-in to perform and no session cookie to mint: every request already carries its
proof, so the guard authenticates this kind per-request. A kind that declared no browser leg and
had no per-request path could never authenticate anybody at all — `begin()` raises,
`/auth/login` 503s, and the guard then denies every request forever.

⚠️ Whatever the proxy puts in that header becomes the subject, including in the ledger. If your
proxy sends an email address there, that address lands in an append-only file — configure it to
send a stable non-PII id instead.

### Using a hosted provider (Clerk, Auth0, WorkOS, Okta)

These all speak OIDC, so they need **no engine change** — that is the whole reason `oidc` exists
alongside `github-oauth`. Point three env vars at them:

```bash
FLS_IDENTITY_KIND=oidc
FLS_OIDC_ISSUER=https://clerk.your-domain.com     # or https://<slug>.clerk.accounts.dev
FLS_OAUTH_CLIENT_ID=...                            # from the provider's OAuth application
FLS_OAUTH_CLIENT_SECRET=...
FLS_AUTH_REDIRECT_URI=https://your-harness/api/auth/callback
```

**Preflight the issuer before you deploy anything** — this turns "will it work" into a command,
and costs nothing:

```bash
engine/.venv/bin/python engine/scripts/check_oidc.py https://clerk.your-domain.com
```

It fetches the discovery document and checks only what this engine actually depends on: that the
declared `issuer` matches what you configured (a mismatch refuses every sign-in, and the symptom
looks nothing like the cause), that the token endpoint accepts `client_secret_post`, whether
there is a `userinfo_endpoint`, whether S256 PKCE will engage, and whether the provider issues a
claim your allowlist can match. Exit 0 means usable.

Two practical notes learned from wiring one up:

- **Discovery is tried at two paths.** OIDC defines `/.well-known/openid-configuration`; RFC 8414
  defines `/.well-known/oauth-authorization-server`. Providers publish one, the other, or both
  (Clerk documents the second). Both are attempted, so the issuer URL is all you configure.
- **Many hosted providers issue no `preferred_username`.** The allowlist therefore matches on
  `login`, `subject` **or `email`** — whichever identifier the operator listed. Matching on an
  address does not put it in the ledger: the ledger stores `subject`, and `login` still never
  falls back to the email.

There is a second, quieter benefit. With a hosted provider the **sign-in page lives on the
provider's domain**, not yours, and the browser's return trip is from them rather than straight
from a social provider to a hostname nobody has seen before. New deployments that put a
"Sign in with <big brand>" page on a fresh domain sometimes collect a browser phishing warning for
exactly that shape; moving the credential UI to an established domain removes the signal.

### Clerk, concretely

Verified against a live Clerk instance on 2026-09-11 — the preflight passes on every check, and
`test_identity_routes.py` carries Clerk's real discovery document as a fixture.

In the **Clerk dashboard**:

1. Use a **separate Clerk application** for the harness rather than an existing product's. A
   Clerk application is a user pool; pointing an operator console at the pool that holds your
   customers means every customer can *authenticate* against it, and only the allowlist is then
   standing between them and the console. Keep the blast radius small.
2. **Configure → OAuth Applications → New**. Scopes `openid profile email`. Redirect URI must be
   the full public callback, byte-for-byte:
   `https://<your-harness>/api/auth/callback`
3. Copy the **Client ID** and **Client Secret** (shown once).
4. The **issuer** is your Frontend API URL — `https://clerk.<your-domain>.com` in production, or
   `https://<slug>.clerk.accounts.dev` for a development instance.

Then on the instance:

```bash
FLS_IDENTITY_KIND=oidc
FLS_OIDC_ISSUER=https://clerk.your-domain.com
FLS_OAUTH_CLIENT_ID=...
FLS_OAUTH_CLIENT_SECRET=...
FLS_AUTH_REDIRECT_URI=https://<your-harness>/api/auth/callback
FLS_ALLOWED_USERS=you@example.com        # or FLS_ALLOW_ANY_AUTHENTICATED=1
```

What Clerk gives you that a raw GitHub OAuth app does not: **the sign-in page is on Clerk's
domain**, so your own host stops serving a branded credential page, and the browser's return trip
comes from Clerk rather than straight from a social provider to a hostname nobody has seen.
Clerk also owns which methods exist (Google, GitHub, email codes, passkeys) — FLS keeps deciding
which *people*.

### The two authorization modes

Independent of provider, and this is the part the provider does not decide for you:

| Mode | Env | Use when |
|---|---|---|
| **Anyone the provider vouches for** | `FLS_ALLOW_ANY_AUTHENTICATED=1` | The provider already limits who can authenticate — a private Clerk instance, a corporate SSO tenant, an org-restricted directory |
| **A named list** | `FLS_ALLOWED_USERS=alice@example.com,octocat` | The provider is public. **A public OAuth app authenticates the entire internet** |

Both unset fails closed. With a hosted provider the layering is the useful bit: the provider
decides which *sign-in methods* exist (Google, GitHub, email codes, passkeys), and FLS decides
which *people* get in.

### Wanting more than one provider

Do not add a second auth code path. Run an **OIDC broker** upstream and keep pointing the one
`oidc` kind at it — [Dex](https://dexidp.io/) is the small one: a single Go binary, CNCF, holds
no user state, federates connectors (GitHub, Google, LDAP, SAML, OIDC) and presents them
downstream as one OIDC provider. It fits beside whatever else your instance already runs.

Adjacent options, named so the choice is informed: **oauth2-proxy** (already covered by
`proxy-header`), and **Keycloak / Authentik / Zitadel** — full identity platforms, right when
you need user management and account lifecycle, oversized for gating one console.

### What the guard does and does not cover

The guard is Starlette middleware, not a per-route dependency: a dependency is opt-in and fails
OPEN on a route somebody forgot to decorate, and middleware also covers 404/405 so probing for
an unlisted route tells an anonymous caller nothing. `PUBLIC_PATHS` maps a prefix to **the
mechanism that guards it** rather than listing exempt paths, because "open" and "guarded by
something else" are different facts — `/webhook/github` is HMAC-verified, not public.

A route-inventory test enumerates `app.routes` and asserts every path is either declared public
or 401s without a session, so adding a route without deciding which it is fails the suite.
Public prefixes must end in `/` so they can only match a whole path segment — otherwise
declaring `/health` public would silently exempt a later `/healthcheck`.

The cross-site Origin check runs on **every** mutating request, public ones included: a public
route can still be cookie-bearing, and `/auth/logout` is the plain example.

An unknown `FLS_IDENTITY_KIND` **refuses to start**, the same treatment `FLS_MODULES` gives an
unknown module path. The alternative is worse than it sounds: the guard activates on any kind
that is not `none`, so a typo left it on with no provider behind it — every route 401ing, and
nobody able to sign in to find out why.

⚠️ **`ladder_mcp` is not behind this guard.** It touches the store directly rather than over
HTTP, so an MCP client with filesystem access to the store is not gated by anything here. That
is the same trust boundary it has always had; the guard does not change it, and nobody should
assume otherwise.

### Bring your own

Implement the `Identity` Protocol and register the kind:

```python
from fls.identity import Challenge, Principal

class Identity(Protocol):
    kind: str
    def begin(self, *, redirect_uri: str, state: str, nonce: str,
              verifier: str = "") -> Challenge: ...
    def complete(self, params: dict, *, redirect_uri: str, nonce: str,
                 verifier: str = "") -> Principal | None: ...
    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...
```

It is `begin`/`complete` rather than `authorize_url`/`exchange` on purpose: not every kind
performs a redirect, and a Protocol shaped around OAuth would force the others to lie about what
they do.

## ideas

Idea sources are pluggable, but they all share one invariant: **a source files ideas through
the admission sink; it can never admit its own ideas.** The gate stays the gate no matter who
knocks.

- `manual` — the issue template and the admin's "File an idea" door. Always available.
- `feeder` — ANCHOR-governed generative brainstorming (scope, guardrails, cost envelope, volume
  cap all declared in the ANCHOR; the feeder can run narrower than its params, never wider).
  Rides the `workers` slot's subscription lane; unavailable = fail-closed, honestly reported.
- **Bring your own** — implement the `IdeaSource` Protocol. A complete ~60-line example ships
  in [`examples/modules/ideas_claude_demo_agent/`](../examples/modules/): a Claude-backed
  ideation agent with a zero-credential dry-run test. Schedule it however you like (cron, a
  durable-workflow engine, by hand) — the ladder only sees ideas arriving at the door.

## lenses

A **lens** is a managed audit or brainstorm pass over a vessel, running on its own cadence. It
shares the `ideas` invariant exactly: **a lens files everything it finds through the standard
sink and can never admit its own findings.** The gate stays the gate no matter who knocks.

No built-in lens ships here. A lens kind arrives entirely through `FLS_MODULES` wiring — the
same treatment a private idea source gets — because what a lens looks for is a property of the
instance, not of the engine. `modules.LENSES` is empty by default and `GET /system` reports
whatever an instance registered.

```python
class Lens(Protocol):
    kind: str
    mode: Literal["generative", "audit-first"]   # propose new work, or start from what's wrong
    panel: str                                    # which review panel it speaks as
    target_vessel: str
    cadence: str
    sink_label: str

    def run(self, anchor, anchor_text: str, snapshot, sink) -> object: ...
    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...
```

`mode` is the interesting field. `generative` proposes work that could be done; `audit-first`
starts from what is already wrong. Both file through the sink; neither decides anything.

## sources

Where expeditions live and ship. The built-in `github` kind: `FLS_REPO` (required — issues,
labels, comments, deployments) and optionally `FLS_REPO_DEV` for a prod/dev pair. Repo names
are identity, not policy, so they live in env; the ANCHOR never names a repo.

`local` is the built-in local-mode kind (auto-selected when `FLS_REPO` isn't set): every
outbound call (`post_comment`/`set_labels`/`create_deployment`) is a safe no-op instead of a
network call, and `get_issue`/`list_comments` raise honestly rather than fabricate a GitHub
issue. Expeditions still fully live and climb through the local `ExpeditionStore` — a GitHub
repo is only needed if you want issues-as-expeditions and webhook-driven admission.

## workers

The builder lane ("pass-back"): who actually writes specs, explorations, and MVP code.

- `api` — metered Anthropic API (`ANTHROPIC_API_KEY`), two-column cost accounting.
- `skill-server` — a subscription lane: any server speaking
  `POST {FLS_SKILL_SERVER}/invoke/{skill}` with Bearer auth. Spend is $0 metered,
  shadow-priced against `builder.shadow_model` so utility-per-dollar keeps a denominator.
  Fallback to `api` is ANCHOR-declared, budgeted, and per-run pinned.
- The Protocol is two methods (`available()`, `complete(prompt, ...)`) — a GitHub-Copilot-
  style worker or any other backend is a small class away.

## environment

Where a rung's builder call and its verify command actually execute. The built-in `worktree`
kind is the ladder's historical implicit behavior, made explicit and swappable: `provision()`
adds (or reuses) a git worktree, `run_verify()` shells a command inside it, `teardown()` removes
it. `devcontainer` / `nix` / `docker` are documented extension kinds — provisioning a real
container is instance-specific work, but the seam (the `Environment` Protocol +
`modules.ENVIRONMENTS` registry) is real and registerable exactly like every other slot.

```python
from fls.modules import Environment, EnvironmentHandle, VerifyResult

class Environment(Protocol):
    def provision(self, expedition_id: str, base_dir: str | None = None) -> EnvironmentHandle: ...
    def run_verify(self, handle: EnvironmentHandle, command: str) -> VerifyResult: ...
    def teardown(self, handle: EnvironmentHandle) -> None: ...
    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...
```

## Middleware seams

Four published hook points let a module **observe** the climb without touching engine state —
mirrors how an `IdeaSource` proposes but never admits:

| Hook | Fires | Intended call site |
|---|---|---|
| `before_rung` / `after_rung` | bracketing a rung's body | `fls.climb.advance_expedition` |
| `on_descend` | once per DESCENDED transition, after the lesson is recorded | `fls.climb` / `fls.rung4`'s retry-vs-descend loop |
| `on_context_assembly` | when context is bounded before a builder call | rung 4's `BoundedContext`, the feeder's anchor-text read |

```python
from fls.modules import register_middleware, dispatch_middleware

def log_rung(hook, **kw):
    print(hook, kw)

register_middleware("before_rung", log_rung)
dispatch_middleware("before_rung", rung=4, expedition_id="e-123")  # what the engine call site does
```

Dispatch is **isolated**: a callback that raises is logged and skipped, never crashes the climb.
Registering or dispatching an unrecognized hook name raises immediately — that's a wiring bug,
not a runtime condition to swallow.

## Swapping or adding a kind

1. Implement the slot's Protocol (they're small on purpose — 2–3 methods; see
   [`examples/modules/README.md`](../examples/modules/README.md) for the full contract).
2. Register it: `modules.IDEAS["my-kind"] = my_factory` in an importable wiring module.
3. Point `FLS_MODULES=my_pkg.wiring` at it (comma-separated for several). An unimportable
   path refuses to start — fail-closed, never half-wired.
4. Select the kind in your ANCHOR where the slot is policy-driven (e.g. `builder.backend`),
   and set the env vars your module needs.

Nothing about your instance belongs in this repo's tree: mechanisms here, policy in your
ANCHOR, identity and secrets in env. `GET /system` will tell you — truthfully — how you did.

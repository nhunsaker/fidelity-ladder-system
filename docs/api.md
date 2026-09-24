# Harness API

FastAPI app at `engine/src/fls/app.py`. All instance specifics come from the environment
(`instance.env.example`); CORS is an explicit allowlist, never a wildcard.

## Who can call any of this

With `FLS_IDENTITY_KIND` set, **every route below returns 401 without a valid operator
session** — reads included. The exceptions are declared, and each is guarded by something else
rather than being open: `/health` (liveness), `/auth/*` (the sign-in flow), `/webhook/github`
(HMAC-verified), and whichever of `/demo/*`, `/preview/*`, `/wireframes/*` the ANCHOR's
`identity.public_surfaces` lists. Unset, nothing is gated and the whole API is open — see
[modules.md#identity](modules.md#identity).

## Sign-in

| Route | Behaviour |
|---|---|
| `GET /auth/login?return_to=` | 302 to the provider; sets a short-lived nonce cookie. `return_to` must be a same-site path |
| `GET /auth/callback` | checks signed state **and** the nonce cookie, then the allowlist; 302 back to `return_to` with the session cookie |
| `POST /auth/logout` | clears the session cookie |
| `GET /auth/me` | the principal, or 401. With identity off: `{authenticated: false, identity: "none"}` |

## Reads

| Route | Returns |
|---|---|
| `GET /health` | `{status, anchor_version, mode}` |
| `GET /anchor` | funnel · altitude_allowed · budgets (the admin's config source) |
| `GET /wall` | every expedition: number · intent · rung · dial · status · target · spent · reason |
| `GET /expeditions/{n}` | one expedition + its artifact list |
| `GET /calibration` | per-rung agreement, cost-per-verdict, human-latency, recommendation + disagreement categories |
| `GET /lessons` | the durable anti-pattern list (what rung-1 judges read) |
| `GET /preview/{id}` | the expedition's rung-3 interactive demo (path-safe ids only) |

## Writes (all gated)

| Route | Body | Gate |
|---|---|---|
| `POST /ideas` | `{number, intent, success, altitude, source?}` | runs the REAL admission gate; no judge configured → parks `needs-human`, never silently admits |
| `POST /expeditions/{n}/kill` | `{actor, reason?}` | **named actor required** (400 without); parks + ledger row. With identity on the body's `actor` is **ignored** — the session's verified principal is used and its subject lands in `Decision.actor` |
| `POST /anchor/validate` | `{section, edits}` | full-constitution pydantic re-validation |
| `POST /anchor/propose` | `{section, edits}` | validated edit → a PR (branch + commit + PR via the contents API); **no token → returns `{simulated: true}` honestly, nothing pushed** |
| `POST /feeder/run` | `{scope?}` | one brainstorm on the skill-server lane; unavailable → `{triggered: false, reason}` (fail-closed) |

## The webhook contract

`POST /webhook/github` — the GitHub App's event stream.

- **Signature:** `X-Hub-Signature-256: sha256=<hmac>` over the raw body with
  `FLS_WEBHOOK_SECRET`. Missing secret, missing header, or bad HMAC → **403, unprocessed**.
- **`issues` / `opened`:** the issue-form body (`### Intent` / `### Success criteria` /
  `### Altitude` sections) becomes an Idea → admission runs → the verdict mirrors back as
  labels (`rung:*`, `dial:*`, `docked`) + a comment.
- **`issue_comment` / `created`** — the human protocol:
  - `/advance` — bump the rung; label flips; ledger row with human-latency timestamps
  - `/pick N` — record the wireframe/demo pick
  - `/approve` — the prod gate: a named approver arrived through the one protocol

Outbound (comments, labels, deployments) rides `GITHUB_TOKEN` against `FLS_REPO`; both unset
→ outbound refuses (fail-closed), inbound processing still works.

## MCP

`engine/src/fls/ladder_mcp.py` (FastMCP) exposes the same reads plus gate-enforced writes
(`ladder_file_idea` cannot self-admit; `ladder_promote` refuses without an approver) and a
private `studio_trigger_brainstorm`. The gates are the same code paths as the HTTP routes —
there is no privileged bypass surface.

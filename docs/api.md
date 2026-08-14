# Harness API

FastAPI app at `engine/src/fls/app.py`. All instance specifics come from the environment
(`instance.env.example`); CORS is an explicit allowlist, never a wildcard.

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
| `POST /expeditions/{n}/kill` | `{actor, reason?}` | **named actor required** (400 without); parks + ledger row |
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

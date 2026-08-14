# Modules — the four connector slots

The ladder's connections to the outside world are four **module slots**. The code in this repo
holds the mechanisms; your instance chooses a `kind` per slot and wires it with environment
variables. The split is strict and load-bearing:

> **Choice = ANCHOR (policy, PR-reviewed) · connection = env (identity + secrets) ·
> status = `GET /system` (kinds + booleans, never a secret value).**

| Slot | What it is | Built-in kind(s) |
|---|---|---|
| [`auth`](#auth) | inbound webhook verification + the outbound token | `github-app` |
| [`ideas`](#ideas) | where ideas come from — every source enters by the ONE admission door | `manual`, `feeder` |
| [`sources`](#sources) | the repo(s) whose issues ARE expeditions, + deploy targets | `github` |
| [`workers`](#workers) | who fulfils builder work ("pass-back") | `api`, `skill-server` |

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

## sources

Where expeditions live and ship. The built-in `github` kind: `FLS_REPO` (required — issues,
labels, comments, deployments) and optionally `FLS_REPO_DEV` for a prod/dev pair. Repo names
are identity, not policy, so they live in env; the ANCHOR never names a repo.

## workers

The builder lane ("pass-back"): who actually writes specs, explorations, and MVP code.

- `api` — metered Anthropic API (`ANTHROPIC_API_KEY`), two-column cost accounting.
- `skill-server` — a subscription lane: any server speaking
  `POST {FLS_SKILL_SERVER}/invoke/{skill}` with Bearer auth. Spend is $0 metered,
  shadow-priced against `builder.shadow_model` so utility-per-dollar keeps a denominator.
  Fallback to `api` is ANCHOR-declared, budgeted, and per-run pinned.
- The Protocol is two methods (`available()`, `complete(prompt, ...)`) — a GitHub-Copilot-
  style worker or any other backend is a small class away.

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

# Modules — the connector slots

The ladder's connections to the outside world are **module slots**. The code in this repo
holds the mechanisms; your instance chooses a `kind` per slot and wires it with environment
variables. The split is strict and load-bearing:

> **Choice = ANCHOR (policy, PR-reviewed) · connection = env (identity + secrets) ·
> status = `GET /system` (kinds + booleans, never a secret value).**

| Slot | What it is | Built-in kind(s) |
|---|---|---|
| [`auth`](#auth) | inbound webhook verification + the outbound token | `github-app`, `none` |
| [`ideas`](#ideas) | where ideas come from — every source enters by the ONE admission door | `manual`, `feeder` |
| `lenses` | managed audit/brainstorm passes over a vessel (files through a sink, same as `ideas`) | none — FLS_MODULES-only |
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

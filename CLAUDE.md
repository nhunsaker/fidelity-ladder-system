# CLAUDE.md — fidelity-ladder-system

Guidance for Claude Code (and any agent) working in this repo. This is the **private
upstream** of a two-repo OSS project; the public mirror is refreshed from `main` by squash
(`public-main` → github.com/nhunsaker/fidelity-ladder-system, MIT).

## THE WORK-SPLIT RULE (required on every change — no exceptions)

Every piece of work must land on the correct side of the OSS/instance seam:

| Side | What belongs there | Where it lives |
|---|---|---|
| **OSS (this repo's tree)** | Mechanisms, interfaces, module slots, UI, docs, examples — anything ANY install can use | code + `docs/` + `examples/` |
| **Instance: policy** | Which kinds/dials/budgets/vessels an instance chooses | its `ANCHOR.md` (PR-reviewed) |
| **Instance: identity + secrets** | Repos, endpoints, tokens, keys, domains | **env only** (`instance.env.example` documents the contract; values never in the tree) |
| **Studio-private** | Deploy runbooks, VM/host details, as-built notes, strategy | `../spec/fidelity-ladder-system/` (outside this repo) |

Concretely, when building a feature:
- Ship the **generic mechanism** here, parameterized by ANCHOR (policy) and env (connection).
  The studio's specific wiring (its brainstorm, its hosts, its keys) is configuration or a
  separate private module — never hardcoded here.
- **No studio internals in the tree, ever**: no metatoy/n8plusus/sorbcloud domains in code or
  docs (deploy.example uses placeholders), no personal or org names beyond git metadata, no
  keychain service names, no `/Users/...` paths, no NAS/infra references. Generic phrasing
  ("a durable-workflow scheduler", "your secret store") is fine.
- **Grep-gate before any public-main refresh**: `git grep -i "metatoy\|n8plusus\|sorbcloud\|
  nobrien\|nhunsaker" main` over the publishable tree; every hit must be on the allowlist —
  **published public npm packages** (`@metatoy/*`, `@sorb/*`) and the **public repo owner
  handle** in docs/demo transcripts. Anything else (domains, hosts, infra, keychain names,
  `/Users/` paths, personal names in code) blocks the release.
- Status surfaces (e.g. `GET /system`) expose **kinds + booleans only** — never secret values.

Rationale: this split IS the product's 12-factor promise ("the code holds mechanisms; your
instance is entirely variables") and the studio's privacy boundary. A change that blurs it is
wrong even if it works.

## Everything else

- **Engine:** Python 3.11+ (FastAPI + pydantic), tests `engine/.venv/bin/python -m pytest
  engine/tests -q`, lint `ruff check engine/src engine/tests`. Fail-closed everywhere; the
  tighten-only cascade (ANCHOR → VESSEL → EXPEDITION) is law.
- **Admin + demo-app:** JS only + JSDoc, never TypeScript. Styling via `var(--token,
  fallback)` against the Primer token set (through the Sorb pipeline). Axe-clean is a
  non-negotiable.
- **One protocol:** mutations flow through GitHub (issues/comments/PRs) and the signed
  webhook; the admin is a lens, MCP tools cannot bypass gates, feedback endpoints never
  mutate the store directly.
- Commit/push only when asked; branch first from `main`; PR per phase; no Claude-Session
  trailers. Don't commit generated outputs (`dist/`, `expeditions/` artifacts beyond seeds).
- Canonical specs/plans: `../spec/fidelity-ladder-system/` (private, in the studio umbrella).

# 🪜 Fidelity Ladder System

**Today's agentic loops iterate on code diffs. This one iterates on design fidelity** — spec →
wireframe → interactive demo → MVP → feature-flagged code — with autonomy dialed independently
per rung: the agent runs free where failure is cheap and gates hard where blast radius is real.

The insight underneath: *code is the most expensive possible medium in which to discover you
built the wrong thing.* Current loops verify **correctness**; none verify **direction** — and
direction is cheapest to test at low fidelity. Product teams already know this (that's why
design processes exist); agentic tooling skipped it and jumped straight to "generate the PR."

## How it works

```
ANCHOR ──> [VESSEL]* ──> EXPEDITION
```

One **ANCHOR** file governs everything: the north star, five non-negotiables, the funnel
policy, per-rung autonomy dials, budgets, and the demote trigger. Ideas are filed as GitHub
issues; an **admission gate** (a budget-bounded LLM adjudicator) decides whether each one
*traces to the ANCHOR* — not whether it's good. Admitted ideas become **expeditions** climbing
six rungs:

| Rung | Artifact | Default dial |
|---|---|---|
| 0-intent | the idea, admitted | propose-only |
| 1-spec | spec fan-out ×3 + a reflection pass | human-picks |
| 2-wireframe | pick-of-3 | human-picks |
| 3-demo | clickable throwaway + a real Playwright walkthrough | auto-advance-with-audit |
| 4-mvp | build→verify loop in an isolated worktree | human-picks |
| 5-flagged | draft PR behind a feature flag; prod gated by a named approver | propose-only |

**Autonomy is earned, not configured**: every judge verdict and human decision lands in a
calibration ledger; sustained agreement makes a rung eligible to loosen, disagreement tightens
it one step (the cascade only ever tightens). Failures **descend** — a design-shaped failure
drops the expedition back down and writes a durable lesson that future judges read. The system
gets smarter from its own failures, measurably: in an N=10 ablation, builders passed 10/10
with acceptance criteria in context vs 8/10 without — the exact lesson a live descent taught.

## The three layers

- **Surface** — GitHub primitives: issues are expeditions, labels are rung/dial state, signed
  webhooks carry every event, `/advance` · `/pick N` · `/approve` comments are the human
  protocol, Environments gate prod.
- **Harness** — the expedition controller (FastAPI): admission, funnel, rung transitions,
  verifier dispatch, the two-column cost ledger (actual vs normalized spend per call).
- **Runtime** — the builders and judges: cross-family by design (one vendor's models judge
  another's builds — no self-preference), with a metered API lane and an optional self-hosted
  skill-server lane, both under a fail-closed client-side budget guard.

An admin app (React; tokens delivered through the [Sorb](https://www.npmjs.com/package/@sorb/leaf)
design-token pipeline) gives the gatekeeper an inbox ranked by information value, the wall of
ladders, guided flows for filing ideas and editing the ANCHOR (edits become PRs — never
live-poked), and a kill switch that requires a name.

## Quickstart (~5 minutes, $0)

Requires **Python ≥3.11** and Node 20+ (for the admin and the rung-4 verifier).

```bash
git clone <this repo> && cd fidelity-ladder-system/engine
python3.11 -m venv .venv               # or: uv venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # the whole engine, stubbed judges — no keys, no spend
.venv/bin/uvicorn fls.app:app          # the harness API
```

Then open `admin/` (`pnpm install && pnpm run dev`) for the UI, and read
[docs/getting-started.md](docs/getting-started.md) to install the ladder on your own repo —
the entire instance is [environment configuration](instance.env.example); the code contains no
deployment-specific values.

## Status

Engine complete (rungs 0–5, 99 tests, CI) · harness API + signed-webhook surface · admin app ·
MCP server (`ladder-mcp`) with non-bypassable gates · reference deploy configs in
[deploy.example/](deploy.example/). Honest seams: issue-mirroring needs a GitHub App token;
Environments' reviewer rule needs a plan that supports it (the harness gate enforces
regardless — fail-closed either way).

## Principles (the non-negotiables)

1. **A human owns every irreversible action.** 2. **Fail closed** — ambiguity parks, never
proceeds. 3. **Accessibility floor** — axe-core clean before anything ships. 4. **Evidence
over claims** — the ledger shows it or it didn't happen. 5. **Provenance** — agent-authored
code says so.

This repo practices what it preaches: the code is largely agent-authored, every merge was
human-gated, and the ledger discipline above ran the build itself.

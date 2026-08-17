# 🪜 Fidelity Ladder System

> **SDD gates what artifact comes next; FLS gates how real it's allowed to get.**

Spec-driven development (like GitHub Spec Kit) governs the *sequence* of artifacts —
constitution → spec → plan → tasks → code. The Fidelity Ladder governs a different axis:
**how much reality each step is allowed to commit.** We call the category **progressive
fidelity** — SDD's sibling, not its competitor. Run both: SDD picks the next document; the
ladder decides how real it gets, and refuses to let an agent skip rungs because it feels
confident.

**Today's agentic loops iterate on code diffs. This one iterates on design fidelity** — spec →
wireframe → interactive demo → MVP → feature-flagged code — with autonomy dialed independently
per rung: the agent runs free where failure is cheap and gates hard where blast radius is real.

The insight underneath: *code is the most expensive possible medium in which to discover you
built the wrong thing.* Current loops verify **correctness**; none verify **direction** — and
direction is cheapest to test at low fidelity. Product teams already know this (that's why
design processes exist); agentic tooling skipped it and jumped straight to "generate the PR."

**Read the [MANIFESTO](MANIFESTO.md)** for the full thesis, the named principles, the honest
costs, and a ~100-line reference sketch of the pattern.

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

## The slots are the legos

The ladder's connections to the outside world are **module slots** — the extension points that
make this a framework and not just an app. The code holds the mechanisms; your instance chooses
a `kind` per slot and wires it with environment variables. Choice is **ANCHOR** (policy,
PR-reviewed); connection is **env** (identity + secrets); status is `GET /system` (kinds +
booleans only, never a secret value).

| Slot | What it is | Built-in kind(s) |
|---|---|---|
| **AUTH** | inbound webhook verification + the outbound token | `github-app` |
| **IDEAS** | where ideas come from — every source enters by the ONE admission door | `manual`, `feeder` |
| **SOURCES** | the repo(s) whose issues ARE expeditions, + deploy targets | `github` |
| **WORKERS** | who fulfils builder work ("pass-back") — specs, demos, MVP code | `api`, `skill-server` |
| **LENSES** | verifiers a rung runs before it may advance (a11y, design-drift, …) | fail-closed `detector_ran` envelope |

Each slot is a small `typing.Protocol` (2–3 methods on purpose). Implement one, register it,
point `FLS_MODULES=` at your wiring module, and select the kind in your ANCHOR. An
unconfigured slot **fails closed** — the ladder refuses the affected action rather than
pretending. See [docs/modules.md](docs/modules.md) for the full contract and
[docs/pattern.md](docs/pattern.md) for the pattern written GoF-style. For the pattern in
motion — one idea climbing, descending at the expensive rung, and leaving a lesson — read
[docs/worked-expedition.md](docs/worked-expedition.md).

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

**Time-to-first-ladder-run: under a minute.** The importable core pulls just two small deps
(`pydantic` + `pyyaml` — no web, GitHub, or MCP), and a first governed climb runs in **~0.1s**:

```bash
pip install fidelity-ladder          # core only — pydantic + pyyaml, seconds
python examples/quickstart.py        # a governed admission runs — no harness, no keys, no spend (~0.1s)
```

The full setup below (harness API + admin UI + rung-4 verifier) is a few minutes more.

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

> **On "framework."** The extension model above is real and load-bearing today — protocols,
> a registry, fail-closed wiring, `GET /system` reflection. As of **v0.8.0-p1** the ladder core
> (`Anchor`/tighten-only cascade/calibration ledger + rungs-as-data) IS factored out as the
> importable **`fidelity_ladder`** package with **zero web/GitHub/MCP dependencies** — a ladder
> runs from `import fidelity_ladder` + one config today (see [`examples/quickstart.py`](examples/quickstart.py),
> which runs a governed admission with no harness, no web deps, and no model spend). What is
> *still in flight*: the public PyPI publish (so it's `pip install fidelity-ladder`, not an
> editable checkout) and the full trace suite (a live climb on a second real repo). See the
> [MANIFESTO's honesty section](MANIFESTO.md#the-honesty-number).

## Status

Engine complete (rungs 0–5, 227 tests, CI) · **importable `fidelity_ladder` core (v0.8.0-p1,
zero web/GitHub deps) + rungs-as-config + runnable quickstart** · harness API + signed-webhook
surface · admin app · MCP server (`ladder-mcp`) with non-bypassable gates · reference deploy
configs in [deploy.example/](deploy.example/). Honest seams: issue-mirroring needs a GitHub App
token; Environments' reviewer rule needs a plan that supports it (the harness gate enforces
regardless — fail-closed either way). Not yet: the public PyPI publish (founder-gated) and the
`fls bench` scoreboard (see the MANIFESTO's honesty number).

## Principles (the non-negotiables)

1. **A human owns every irreversible action.** 2. **Fail closed** — ambiguity parks, never
proceeds. 3. **Accessibility floor** — axe-core clean before anything ships. 4. **Evidence
over claims** — the ledger shows it or it didn't happen. 5. **Provenance** — agent-authored
code says so.

These five are the runtime constitution. The broader *doctrine* — why it's shaped this way —
lives in the [MANIFESTO](MANIFESTO.md).

## OSS & the 12-factor promise

MIT-licensed. The design rule is strict and load-bearing: **the code holds mechanisms; your
instance is entirely variables.** Policy lives in your `ANCHOR.md` (PR-reviewed); identity and
secrets live in env ([instance.env.example](instance.env.example) documents the contract, values
never in the tree); status surfaces expose kinds and booleans, never secret values. That split
is the 12-factor promise and it is checkable — `GET /system` will tell you, truthfully, how you
wired it.

This repo practices what it preaches: the code is largely agent-authored, every merge was
human-gated, and the ledger discipline above ran the build itself.

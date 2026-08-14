# Fidelity Ladder System

An agentic loop that iterates on **design fidelity** — spec → wireframe → interactive demo →
MVP → feature-flagged code — with **per-rung earned autonomy**, governed end-to-end by one
[`ANCHOR.md`](./ANCHOR.md). A studio product and the live demo + code artifact for the GitHub
Next pursuit.

Plan of record: `spec/fidelity-ladder-system/build-plan.md` (in the metatoy umbrella).

## Architecture (three layers)
- **Surface** — GitHub primitives: issues = expeditions, labels = rung/dial state, checks =
  verifiers, draft PR + Environments = rung 5. Plus the admin UI (a lens, never a second
  source of truth).
- **Harness** — the expedition controller (`engine/`, FastAPI): admission, funnel, rung
  transitions, verifier dispatch, autonomy ledger. Owns *life-cycle context*.
- **Runtime** — agent execution on the Azure VM: Claude builders in isolated worktrees, judge
  calls. Owns *model context* and *tool context*.

## Layout
```
ANCHOR.md            the constitution (machine-parsed `anchor` block)
engine/              FastAPI harness + runtime glue (Python)
admin/               React + Primer admin UI (a lens over the GitHub App protocol)
demo-app/            neutral "Acme" React + Primer app — what expeditions modify
expeditions/         per-expedition artifacts (specs, wireframes, demos)
.github/             issue templates, labels, Actions, Environments
```

## Models & budgets
- **Judges**: Azure OpenAI (`gpt-5.4-mini`/`nano`) — cross-family with the builders to avoid
  self-preference bias; cheap, high-volume.
- **Builders**: Claude API — **$100 hard cap**, console-enforced, alert at $50.
- **Compute**: Azure VM (`fidelity-ladder-rg`, sponsored credits).

## Domains
- `admin.fidelity-ladder-system.n8plusus.com` — admin UI
- `stage.fidelity-ladder-system.n8plusus.com` — demo app (stage env; rung-3 previews at `/preview/<id>`)
- `prod.fidelity-ladder-system.n8plusus.com` — demo app (production env)

## Status
Engine complete (rungs 0–5, 99 tests) · three live domains + the harness API
(`api.fidelity-ladder-system.n8plusus.com`) · admin v2 deployed (React + @sorb/leaf token
pipeline, Primer paint). Remaining: GitHub App registration (docs/github-app-setup.md) and
the nightly feeder schedule.

# docs/

Public documentation for the Fidelity Ladder System:

- `getting-started.md` — install the ladder on your repo
- `modules.md` — the four connector slots (auth · ideas · sources · workers), `GET /system`,
  and how to bring your own implementation
- `anchor-reference.md` — every ANCHOR section, key, and default
- `architecture.md` — layers, the rung state machine, descent, the cost model
- `api.md` — harness routes + the webhook contract

**The system has three parts, and the admin mirrors them:** **Workbench** (daily work — an
inbox of every decision waiting on a human, evidence inline) · **Anchor** (governance — the
constitution, vessels, budgets, autonomy dials; edits are PRs) · **System** (instance wiring —
the module slots, status only, never a secret).

Instance configuration is environment-only — see `../instance.env.example` and
`../deploy.example/`. The split is a rule, not a habit: mechanisms live in this repo; policy
lives in your ANCHOR; identity and secrets live in env.

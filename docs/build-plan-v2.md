# fidelity-ladder-system — v2 build plan (gap closure + admin v2)

> Spec destination on approval: `spec/fidelity-ladder-system/build-plan-v2.md` (+ TODO.md rows,
> mirror to repo `docs/`). Work lands on a new branch off `feat/p7-passback-p4-feeder` (or off
> main after PR #1 merges — founder's call at run time).

## Context

V1 (P0–P7) built the whole engine — 69 tests green, one real $0.0266 climb, three live domains —
but the 2026-08-13 audit surfaced what was planned and never built: the GitHub surface is
simulated (webhook only logs), three admin sections are missing (expedition detail + kill switch,
ANCHOR console, feeder control), and four persona-dock items quietly slipped (prune-early
[Wang#2], human-latency [Yao#3], error-analysis discipline [Ng#2], conversational beat). The
admin is also a static-vanilla lens, not the specced React build.

V2 closes those gaps and rebuilds the admin as a best-in-class guided UI:
- **Theme (founder-decided):** Primer primitive tokens (GitHub's own color system — the lens
  already hand-uses `#0969da`/`#f6f8fa`/`#1f2328`/`#cf222e`) expressed as a **DTCG token set
  flowing through the Sorb pipeline** (`SorbProvider` + `var(--token, fallback)`). Sorb is the
  engine, Primer is the paint. NOT the Sorb Blaze-Orange brand palette (founder 2026-08-13).
  Supersedes the earlier @primer/react call — Primer *tokens*, custom lightweight components
  (styled-components-based @primer/react would fight the Sorb var() idiom).
- **UX (founder-directed):** guided step flow in the callout-admin style, implemented ONLY from
  the founder's abstract description (the `mono`/callout_admin_ui repo is BF day-job IP,
  out of scope, never consulted): **0** home = listing → **1** pick work to create/edit →
  **2** onboarding step that explains what each input does → **3** map + validate selections
  before submit (fixture-backed where the live API isn't required).
- **Process (founder-directed):** Claude Design produces **3 explorations first; founder approval
  of a direction is a hard gate** before any admin build.
- **bootstrap-styled** goes in the Acme demo app (the "customer's" stack), not the admin.
- **Dry-run batch (founder-decided):** N=10 live climbs (~$0.50) for the Ng#2 pass.

## Phases

### V2-P0 — Design explorations + token foundation (GATE: founder picks a direction)
1. **Primer-primitive DTCG token set**: `admin-v2/tokens/*.json` (primitive: Primer light-mode
   scale incl. `#0969da` accent, `#f6f8fa` canvas, `#1f2328` fg, `#1a7f37`/`#9a6700`/`#cf222e`/
   `#8250df` semantic hues; semantic layer: `--color-accent`, `--color-canvas`, rung/status/dial
   colors) → Style Dictionary (`sd.config.js`, copy the `sorb-demo/sd.config.js` pattern) →
   `variables.css` + `tokens.js`.
2. **Claude Design: 3 explorations** of the two key screens each (home listing + one guided-wizard
   step), all constrained to the Primer token palette; distinct directions (e.g. dense-console /
   card-forward / rail-navigation). Per the pipeline gotchas memory: write_files inline-only,
   screenshot-QA every board via Playwright, pre-empt the .dc.html render bugs.
3. **Founder approval**: pick one direction (or a blend). HARD GATE — no admin build before this.
**Verify:** 3 rendered boards screenshot-verified + a picked direction recorded in the spec.

> **✅ V2-P0 DONE 2026-08-13.** Token set built + committed (`admin-v2/tokens/` → Style
> Dictionary → `variables.css` + `tokens.js`, commit `ae98583`, branch `feat/v2-p0-design`).
> Three explorations rendered + screenshot-QA'd in Claude Design (project "Fidelity Ladder —
> Admin v2 Explorations"): 1a dense-console · 1b card-forward · 1c rail-navigation — each =
> Home + one wizard step on shared fixture data, Primer palette only, artifact chains
> (issue·demo·PR) per row. **GATE CLEARED — founder picked `1c` Rail navigation** (left rail
> scaling to ANCHOR console/feeder/calibration; vertical-stepper wizard with map-and-validate).
> V2-P3 builds to 1c.

### V2-P1 — Engine gaps (parallel-safe with P0; no UI dependency)
1. **Prune-early funnel** [Wang#2]: in `engine/src/fls/funnel.py` — judges score cheap partial
   generations (first ~200 chars of each rung-1 candidate) and kill weak branches BEFORE the
   full-spec/wireframe spend; `assign_lanes` gains a prune step; ledger records pruned branches
   + saved est_usd.
2. **Human-latency metric** [Yao#3]: `ledger.py` Decision rows gain `gate_opened_at` /
   `human_responded_at` → `human_latency_s`; calibration report + `/calibration` API surface a
   per-gate latency slice. (Timestamps injected by caller; no Date.now in workflow scripts.)
3. **Rung-3 preview serving** [P2.2 debt]: harness route `GET /preview/{expedition}` serving
   `expeditions/<n>/demo/index.html` + Caddy route on stage (`stage…/preview/<id>`); rung-3
   result records the URL into the PR package walkthrough link.
4. **Error-analysis discipline** [Ng#2]: `engine/scripts/error_analysis.py` — N=10 live climbs
   against planted-bug variants (~$0.50 cap via BudgetGuard); categorize every rung-4 failure
   (mechanical/design/flaky/budget buckets); write `spec/fidelity-ladder-system/
   failure-taxonomy.md` + confirm the biggest bucket is encoded by the LESSONS mechanism
   (add the missing lesson patterns if not).
**Verify:** funnel tests show a pruned branch never reaches render spend · ledger rows carry
human_latency_s · `curl stage…/preview/101` serves the live demo · taxonomy doc with 10-run
data + lesson-coverage statement. Engine suite stays green, ruff clean.

### V2-P2 — Real GitHub surface (the claim becomes true) [P0.5 debt]
1. **Deploy the harness API on the VM** (uvicorn service + Caddy reverse-proxy on an api
   subdomain or path) — prerequisite for webhooks AND the admin's live API.
2. **GitHub App registration** (§5 founder: create the App on github.com/metatoy, install on
   fidelity-ladder-system, webhook → the VM) — agent preps the manifest/permissions
   (issues:rw, checks:rw, deployments), founder clicks.
3. **Webhook round-trip made real**: `app.py /webhook/github` verifies the App signature and
   maps issue events → ExpeditionStore (issue opened w/ idea form = admission; label changes =
   rung/dial sync; comments = advance/pick commands). Expedition state mirrors TO the issue
   (labels + comment posts) via the App token — issues become the real surface.
4. **Environments**: `staging` auto, `production` w/ required-reviewer; rung-5
   `promote_to_prod` goes through a real Environment approval (deployment API), replacing the
   noop deployer.
**Verify (live):** file a real issue → expedition appears in the store + labels flip as it
climbs · prod promotion blocked until the founder approves the GitHub Environment review ·
the harness log shows the signed round-trip.

### V2-P3 — Admin v2 (post-P0-gate): the guided Sorb+Primer app
Stack: **Vite + React 18, JS-only + JSDoc** (`admin-v2/`), `@sorb/leaf@^0.2` from npm (published
0.2.1), `pnpm install --ignore-workspace` (standalone-repo gotcha). `SorbProvider` wired with the
P0 token set (`namespace: fls-admin`, committed tokens, preview enabled for localhost — the
Figma-plugin re-skin demo beat). Components styled exclusively `var(--token, fallback)`.
1. **Home = the listing** (step 0): merged wall+inbox — every expedition, ranked
   needs-you-first (reuse `infoValue` logic), filters by rung/status; each row shows its
   artifact chain (issue · +demo · +draft PR) fixing the "are these PRs?" confusion.
2. **Guided flows** (steps 1→2→3, one shared wizard shell):
   - **File an idea** — 1: pick "new idea" · 2: onboarding panes explaining intent/success/
     altitude (copy sourced from `configuration.md`) · 3: validate against `/anchor` (altitude
     allowed? traces?) with a dock-prediction preview, then submit → the standard door.
   - **ANCHOR console** [P3.2 debt] — 1: pick the section (adjudicator/builder/funnel/rungs/
     budgets/feeder…) · 2: each key explained inline (configuration.md as the blueprint it was
     written to be) · 3: schema-validate the edit (pydantic shapes mirrored client-side or via
     a `/anchor/validate` route) → submit opens a **PR** (edits are PRs, never live-poked).
   - **Feeder control** [P3.2 debt] — 1: trigger/inspect · 2: params explained (scope,
     volume_cap, envelope) · 3: dry-run preview (ListSink fixture) → real trigger; run history
     with two-column economics.
3. **Expedition detail + kill switch** [P3.2 debt]: full climb timeline (rungs, calls, costs,
   artifacts, lessons), the PR package view, and a kill switch (parks the expedition; fail-closed
   confirm modal reusing the named-approver pattern).
4. **Live API wiring**: all reads from the VM harness (`/wall`, `/expeditions/{n}`,
   `/calibration`, `/lessons`, `/anchor`); writes through the harness → GitHub App (single
   protocol). `fixtures.json` remains the offline/dev fallback mode.
5. **Deploy** to `admin.fidelity-ladder-system.n8plusus.com` (static Vite build via Caddy);
   keep the v1 static lens at `/v1/` as the week-one artifact.
**Verify (live):** every wizard completes end-to-end against the live harness · an ANCHOR
console edit opens a real PR · kill switch parks a live expedition · axe-core clean (the
a11y non-negotiable) · Playwright walkthrough of all three flows (sorb-test-ui harness).

### V2-P4 — Acme on bootstrap-styled
1. Rebuild the Acme demo app as a small React app using `@metatoy/bootstrap-styled@1.0.0`
   (neutral "Acme" branding — the library stays Sorb-free per its standing rule; consuming it
   here is fine).
2. Keep the flags mechanism (`flags.json` + `isEnabled`) and the ⌘K feature behind its flag;
   rung-4 builders now target a real component library (BoundedContext gains the lib's
   component inventory as context).
**Verify:** stage/prod redeployed; ⌘K still flag-gated; one fresh expedition builds a feature
using bootstrap-styled components end-to-end.

### V2-P5 — Conversational beat + demo refresh [P5.3 debt]
1. **Conversational demo beat**: the 6-minute script driven from a Claude Code conversation via
   `ladder-mcp` (file → watch climb → review PR package → approve prod), recorded as a
   transcript artifact in the spec.
2. **demo-walkthrough v2**: refresh the 12 beats against the now-real surface (GitHub issues,
   live admin, preview URLs); re-verify every Do/See/Verify line; founder dry-run gate before
   any external showing (standing).
**Verify:** the MCP-driven run completes with gates refused/honored correctly · walkthrough
beats all pass on the live stack.

## Budgets · gates · sequencing
- **Model spend:** ~$0.50 (P1.4 N=10) + incidental climb tests (~$0.10) + Claude Design
  explorations (subscription lane). Everything else $0.
- **§5 founder gates:** exploration-direction pick (P0.3) · GitHub App creation + install
  (P2.2) · Environment required-reviewer config · each VM deploy · the dry-run gate (P5.2).
- **Order:** P0 ∥ P1 first (P0 is the admin gate; P1 is pure engine) → P2 (surface) → P3
  (admin, needs P0 pick + P2 API) → P4 → P5. PR-per-phase off the working branch.
- **Out of scope (unchanged P6):** V3 pluggable adjudicators · gh-aw/spec-kit stunt ·
  ladder-mcp OSS publish · VESSEL.

## Key reuse (found, not rebuilt)
- Sorb: `SorbProvider`/hooks (`sorb-leaf/src/index.js`), consumer wiring pattern
  (`sorb-demo/main.jsx` + `src/sorbConfig.js` + `sd.config.js`), published `@sorb/leaf@0.2.1`.
- Engine: `app.py` routes (extend, don't replace) · `store.py` shapes (the admin data contract)
  · `funnel.py assign_lanes` · `ledger.py` Decision · `rung5.promote_to_prod` gate ·
  `local_verifier.py` + `playwright_walkthrough.py` for P1.4 · `infoValue()` ranking from the
  v1 lens.
- Docs as blueprints: `configuration.md` (ANCHOR console copy + fields) · `failure taxonomy`
  section of `verifier.py` · `demo-walkthrough.md` (refresh target).

## Verification (program-level)
Each phase ends live-demoable: P0 = 3 boards + a pick · P1 = taxonomy doc + preview URL ·
P2 = a real issue climbing with labels flipping · P3 = the three guided flows on the live
harness · P4 = a bootstrap-styled feature shipped by an expedition · P5 = the conversation-
driven 6-minute run. The v2 acceptance test: **beat-for-beat demo-walkthrough v2 with zero
simulated steps left in the 🔴 column.**

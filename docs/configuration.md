# Fidelity Ladder System — configuration spec

> The full configurable surface of a fidelity-ladder instance, grounded in the as-built
> `ANCHOR.md` + `engine/src/fls/anchor.py` (pydantic models) on branch
> `feat/p7-passback-p4-feeder`, 2026-08-13. This doc is also the blueprint for the admin UI's
> **ANCHOR console** section (P3 nicety): this outline rendered as a form whose submit is a PR.

**Design rule:** policy lives in ANCHOR (one reviewable file; edits are PRs, never live-poked) ·
**trust** lives in the ledger (earned, not configured) · **secrets** live in the keychain (never
in either). The tighten-only cascade governs every override below ANCHOR: stricter is always
allowed, looser never.

---

## 1. Instance shape

| Key | Values | Default (demo instance) |
|---|---|---|
| `version` | int | `1` |
| `mode` | `slim` \| `full` | `slim` — ANCHOR + EXPEDITION, no VESSEL layer |

Plus the **prose header** — north star + the five non-negotiables. Human-written, machine-injected
into the admission prompt and (if enabled) the feeder's ideation prompt. Changing the north star
changes what gets admitted; that is the point of it being one file.

The five non-negotiables (fixed for this instance, restatable per instance):
human owns every irreversible action · fail closed · a11y floor before rung 5 ·
evidence over claims · provenance.

## 2. `adjudicator:` — the front door

| Key | Values | Default |
|---|---|---|
| `kind` | `single-llm` (v1); V3 = pluggable (council / persona bench) | `single-llm` |
| `model` | any judge model | `azure-openai:gpt-5.4-nano` |
| `cost.max_tokens` | int — every verdict is budget-bounded | `4000` |
| `cost.max_calls` | int | `2` |
| `output_contract` | must contain `verdict` + `reasoning` (schema-validated at load) | `[verdict, reasoning, cost]` |

Verdict vocabulary is fixed: `admit` / `dock` / `needs-human`. The interface is **frozen** so V3
adjudicators drop in without a rewrite. A deterministic altitude pre-check runs before any LLM
spend (see §9).

## 3. `builder:` — who fulfils builder work (P7; optional block)

| Key | Values | Default |
|---|---|---|
| `backend` | `api` (metered Anthropic) \| `skill-server` (subscription pass-back) | `skill-server` |
| `shadow_model` | list-price model the subscription lane is normalized against | `claude-haiku-4-5-20251001` |
| `fallback` | `api` \| `none` — authorized metered spend when the skill-server is down | `api` |
| `fallback_budget_usd` | per-run ceiling; a new fallback call is refused once spend reaches it | `0.50` |
| `fallback_pin` | `per-run` — once fallen back, the run stays on api (no mid-climb flapping) | `per-run` |

Omitting the whole block = historical behaviour (`api`, no fallback). `make_builder(anchor)` is
the single construction point; no code selects a backend directly.

## 4. `idea_sources:` — the doors in

Two kinds; both terminate at the same admission gate:

- `manual` — the issue form. Always present.
- `feeder` — the studio brainstorm (P4), with `params:`:

| Param | Controls | Default |
|---|---|---|
| `scope` | one line steering what gets proposed | studio-ops/demo scope |
| `guardrails_into_prompt` | non-negotiables shape *ideation*, not just the gate | `true` |
| `cost_envelope_usd` | bounds the shadow cost per run (`within_envelope` flag) | `5.00` |
| `volume_cap` | top-N ideas filed per run | `5` |
| `cadence` | `manual` \| `nightly` (nightly = Temporal schedule, §5-gated) | `manual` |
| `model_tier` | `economy` … | `economy` |
| `context_cap_tokens` | hard-truncates the workspace checkout fed to the prompt | `30000` |

Structural invariant (not configurable): the feeder files through the standard door and **can
never self-admit**.

## 5. `funnel:` — what happens to admitted ideas

| Key | Meaning | Default |
|---|---|---|
| `auto_build` | top-N climb the full ladder hands-off | `1` |
| `interactive_demos` | next-N advance to a rung-3 clickable demo, then park | `3` |
| `wireframes` | `all` or int — the floor every admitted idea gets | `all` |
| `queue` | how many may sit invisible | `0` |

The demo posture is deliberate: nothing admitted is invisible; the backlog is a gallery.

## 6. `rungs:` — the autonomy dials + cost estimates (the heart)

Per rung `0-intent` · `1-spec` · `2-wireframe` · `3-demo` · `4-mvp` · `5-flagged`, two knobs:

- **`dial`** ∈ `propose-only → human-picks → auto-advance-with-audit → autonomous` (ordered;
  `DIAL_ORDER` in code). The cascade permits moving a dial only **toward tighter** below ANCHOR
  (`Anchor.can_tighten`).
- **`est_usd`** — the per-rung cost estimate the ledger reports against.

Defaults (demo): intent + flagged = `propose-only` (the hard gates) · spec/wireframe/mvp =
`human-picks` · demo = `auto-advance-with-audit` (its audit = the Playwright walkthrough).

**Loosening is not configuration.** A dial loosens only via the earned track record (§8's inverse):
the calibration readout marks a rung `eligible-to-loosen`, and a human applies the change. The
file sets the starting posture only.

## 7. `budgets:`

| Key | Meaning | Default |
|---|---|---|
| `per_expedition_ceiling_usd` | expedition parks visibly at ceiling; never creeps | `8.00` |
| `claude_api_hard_cap_usd` | metered-builder cap — console-enforced AND client-side `BudgetGuard` (fail-closed, raises before overspend) | `100` (alert 50) |
| `azure_resource_group` | where engine-room resources live | `fidelity-ladder-rg` |

Cost accounting is two-column everywhere: `usd` (actual) vs `normalized_usd` (list-price shadow)
+ `funded_by` ∈ `api | credits | subscription`, so free lanes stay comparable.

## 8. `autonomy_demote:` — when trust is revoked

| Key | Meaning | Default |
|---|---|---|
| `agreement_threshold` | judge-vs-human agreement below this… | `0.80` |
| `window` | …over the last N decisions at a rung… | `10` |
| `action` | …triggers | `tighten_one_step` + notify the gatekeeper |

Defined at P1 (the ledger schema), read by the P3 admin panel's demote button — the button reads
the trigger, it does not define it.

## 9. `altitude_allowed:` — the unit of work rung 4 may own

List ∈ `{ticket, feature, migration}`. Demo instance: `[ticket, feature]` — a migration-sized
idea docks **deterministically at $0** in the pre-check, before any LLM spend.

---

## Outside the ANCHOR — environment & keys (operational, not policy)

| Item | Where | Purpose |
|---|---|---|
| `anthropic-api-key` | macOS keychain (or `ANTHROPIC_API_KEY` env) | metered builders |
| `langchain-api-key` | keychain (or `LANGCHAIN_API_KEY` / `FLS_SKILL_SERVER_KEY` env) | skill-server pass-back (Bearer) |
| `AZURE_OPENAI_KEY` | env | judges |
| `FLS_SKILL_SERVER` | env | skill-server endpoint override (default `https://langchain.n8plusus.com`) |
| Azure endpoint | env `AZURE_OPENAI_ENDPOINT` | default `metatoy-kb-openai` |
| Surfaces | infra (§5-gated) | 3 domains (`admin/stage/prod.fidelity-ladder-system.n8plusus.com`), GitHub repo + 12 labels, VM `fls-engine-1` |

Secret values never appear in ANCHOR, code, or commits — keychain only.

## Cascade summary (what may override what)

```
ANCHOR ──> [VESSEL]* ──> EXPEDITION
```
Any lower level may set a **stricter** scope, budget, or dial than the level above — never
looser. VESSEL absent in slim mode; the rule already governs ANCHOR → EXPEDITION and a VESSEL
slots in without rework. The admission gate refuses any idea that cannot trace to the ANCHOR.

## Related

- `ANCHOR.md` (repo root) — the live instance of everything above.
- `engine/src/fls/anchor.py` — the typed schema (`Anchor`, `BuilderConfig`, `FeederParams`,
  `Funnel`, `RungPolicy`, `Budgets`, `DemoteTrigger`).
- `build-plan.md` (this dir) — the phase plan; `demo-walkthrough.md` — the 12-beat demo script.

# ANCHOR reference — every section, key, and default

The ANCHOR is one reviewable file: prose for humans (north star + non-negotiables) around one
fenced ```` ```anchor ```` YAML block the whole system machine-reads (`fls/anchor.py` validates
it with pydantic on load — an invalid ANCHOR never runs).

**Design rule:** policy lives in the ANCHOR · **trust** lives in the ledger (earned, not
configured) · **secrets live in the environment** (never in this file, never in code).

## 1. Instance shape

| Key | Values | Notes |
|---|---|---|
| `version` | int | schema version |
| `mode` | `slim` \| `full` | slim = ANCHOR + EXPEDITION, no VESSEL layer between them |

The prose header is load-bearing: it is injected into the admission prompt and (optionally)
the feeder's ideation prompt. Changing the north star changes what gets admitted.

## 2. `adjudicator:` — the front door

| Key | Meaning |
|---|---|
| `kind` | `single-llm` (v1; the interface is frozen so pluggable panels drop in later) |
| `model` | the judge model |
| `cost.max_tokens` / `cost.max_calls` | every verdict is budget-bounded |
| `output_contract` | must include `verdict` + `reasoning` (schema-enforced) |

Verdict vocabulary is fixed: `admit` / `dock` / `needs-human`. A deterministic altitude
pre-check runs **before any model spend** — a disallowed altitude docks at $0.

## 3. `builder:` — who fulfils builder work (optional block)

| Key | Values | Default |
|---|---|---|
| `backend` | `api` (metered) \| `skill-server` (self-hosted, subscription-funded) | `api` |
| `shadow_model` | list-price model the skill-server lane is normalized against | claude-haiku |
| `fallback` | `api` \| `none` — may metered spend fire when the skill server is down? | `none` |
| `fallback_budget_usd` | per-run ceiling; a new fallback call is refused at the cap | `0` |
| `fallback_pin` | `per-run` — once fallen back, the run stays on the fallback (no flapping) | `per-run` |

Omit the block entirely for plain metered behavior.

## 4. `idea_sources:` — the doors in

- `manual` — the issue form. Always present.
- `feeder` — a headless brainstorm, with `params:`:

| Param | Controls | Demo default |
|---|---|---|
| `scope` | one line steering what gets proposed | — |
| `guardrails_into_prompt` | non-negotiables shape ideation, not just the gate | `true` |
| `cost_envelope_usd` | bounds the run's shadow cost (`within_envelope` flag) | `5.00` |
| `volume_cap` | top-N ideas filed per run | `5` |
| `cadence` | `manual` \| `nightly` | `manual` |
| `context_cap_tokens` | hard-truncates any workspace context fed to the prompt | `30000` |

Structural invariant (not configurable): the feeder files through the standard door and
**can never self-admit**.

## 5. `funnel:` — what happens to admitted ideas

| Key | Meaning | Demo default |
|---|---|---|
| `auto_build` | top-N climb the full ladder hands-off | `1` |
| `interactive_demos` | next-N advance to a rung-3 clickable demo, then park | `3` |
| `wireframes` | `all` or int — the floor every admitted idea gets | `all` |
| `queue` | how many admitted ideas may sit invisible | `0` |

The funnel's shape *is* the cost model: width per rung × cost per rung ≈ the spend envelope.
A prune step scores cheap partial generations and kills weak branches **before** any
expensive render (fail-open: a judge glitch never destroys admitted work).

## 6. `rungs:` — the autonomy dials (the heart)

Per rung `0-intent` … `5-flagged`:

- **`dial`** ∈ `propose-only → human-picks → auto-advance-with-audit → autonomous` (ordered)
- **`est_usd`** — the per-rung estimate the ledger reports against

**Loosening is not configuration.** The calibration readout marks a rung `eligible-to-loosen`
only on a sustained agreement track record, and a human applies the change. The file sets the
starting posture; the cascade below the ANCHOR only ever tightens (`Anchor.can_tighten`).

## 7. `budgets:`

| Key | Meaning |
|---|---|
| `per_expedition_ceiling_usd` | an expedition parks **visibly** at its ceiling; never creeps |
| `claude_api_hard_cap_usd` | metered-builder cap — enforce it at your provider console AND client-side (`BudgetGuard` raises before overspending) |

Cost accounting is two-column everywhere: `usd` (actual) vs `normalized_usd` (list-price
shadow) + `funded_by` ∈ `api | credits | subscription` — free lanes stay comparable.

## 8. `autonomy_demote:` — when trust is revoked

| Key | Meaning | Demo default |
|---|---|---|
| `agreement_threshold` | judge-vs-human agreement below this… | `0.80` |
| `window` | …over the last N decisions at a rung… | `10` |
| `action` | …triggers | `tighten_one_step` |

## 9. `altitude_allowed:` — the unit of work rung 4 may own

List ∈ `{ticket, feature, migration}`. Anything not listed docks deterministically at $0.

## Editing the ANCHOR

Edits are **PRs, never live-pokes** — the admin's ANCHOR console validates a proposed edit
against the full schema and opens a PR; the running system picks the change up on restart.
The cascade rule: `ANCHOR → [VESSEL]* → EXPEDITION`; any lower level may tighten a
constraint, never loosen one set above it.

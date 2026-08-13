<!--
ANCHOR.md — the constitution of a fidelity-ladder instance.
Everything reads from this file. Edits are reviewed changes (PR), never live-poked.
Machine-parsed from the fenced `anchor` YAML block below; the prose around it is for humans.
Tighten-only cascade: a VESSEL or EXPEDITION may make a constraint STRICTER, never looser.
This is the demo instance (slim mode: ANCHOR + EXPEDITION, no VESSEL).
-->

# ANCHOR — Fidelity Ladder System (demo instance)

## North star
Turn a stated intent into a shipped, feature-flagged change by climbing fidelity rungs
(spec → wireframe → interactive demo → MVP → flagged code), spending scarce human judgment only
where blast radius earns it.

## Non-negotiables (never drift; a rung may add stricter, never remove)
- **Human owns every irreversible action.** No prod promotion, external post, or spend past an
  expedition's ceiling without a human decision through the one protocol (GitHub App).
- **Fail closed.** A verifier error, a budget exhaustion, or an ambiguous verdict parks the
  expedition; it does not proceed on optimism.
- **Accessibility floor.** Every UI artifact meets the a11y budget (axe-core clean on changed
  surfaces) before rung 5. Non-negotiable, cannot be dialed off by any expedition.
- **Evidence over claims.** Ship evidence of what was verified; never assert an outcome the
  ledger can't show.
- **Provenance.** Agent-authored code carries its provenance; no unlicensed third-party assets
  enter an artifact.

```anchor
# ── machine-parsed constitution ───────────────────────────────────────────────
version: 1
mode: slim            # slim = ANCHOR + EXPEDITION (no VESSEL layer)
adjudicator:
  kind: single-llm    # v1; interface frozen for V3 pluggable (council/system-design personas)
  model: azure-openai:gpt-5.4-nano
  cost:               # every verdict is budget-bounded
    max_tokens: 4000
    max_calls: 2
  output_contract: [verdict, reasoning, cost]   # verdict ∈ {admit, dock, needs-human}

idea_sources:
  - kind: manual              # issue form — the default door
  - kind: feeder              # the studio brainstorm (P4)
    name: studio-brainstorm
    params:
      scope: "fidelity-ladder demo app (Acme); studio-ops tooling"
      guardrails_into_prompt: true      # non-negotiables shape ideation, not just the gate
      cost_envelope_usd: 5.00           # per feeder run
      volume_cap: 5                     # top-N ideas per run
      cadence: "manual | nightly"
      model_tier: economy               # azure-openai mini/nano for ideation
      context_cap_tokens: 30000         # what the workspace checkout may feed the prompt

funnel:                       # what happens to admitted ideas — the funnel's shape
  auto_build: 1               # top-ranked idea climbs the full ladder hands-off
  interactive_demos: 3        # next 3 advance to rung-3 clickable demo, then park
  wireframes: all             # every admitted idea gets a wireframe (backlog = gallery)
  queue: 0                    # demo scale: nothing admitted sits invisible

rungs:                        # per-rung autonomy defaults + cost estimate (USD)
  # dial ∈ {propose-only, human-picks, auto-advance-with-audit, autonomous}
  # autonomy is EARNED: loosening requires verifier track record; tightening is always allowed.
  "0-intent":     { dial: propose-only,            est_usd: 0.01 }
  "1-spec":       { dial: human-picks,             est_usd: 0.15 }   # fan-out ×3 + reflection pass
  "2-wireframe":  { dial: human-picks,             est_usd: 0.20 }
  "3-demo":       { dial: auto-advance-with-audit, est_usd: 0.40 }
  "4-mvp":        { dial: human-picks,             est_usd: 1.20 }   # gated entry AND exit
  "5-flagged":    { dial: propose-only,            est_usd: 0.30 }   # hard gate: draft PR + sign-off

budgets:
  per_expedition_ceiling_usd: 8.00      # expedition parks visibly at ceiling; never creeps
  claude_api_hard_cap_usd: 100          # console-enforced; builders only; alert at 50
  azure_resource_group: fidelity-ladder-rg

autonomy_demote:              # the ledger's demote trigger (P1 defines, P3 button reads)
  agreement_threshold: 0.80   # judge-vs-human agreement below this...
  window: 10                  # ...over the last N decisions at a rung...
  action: tighten_one_step    # ...drops that rung's dial one step and notifies the gatekeeper

altitude_allowed: [ticket, feature]   # units of work rung-4 may own in this instance (no migration)
```

## Cascade rule
`ANCHOR ──> [VESSEL]* ──> EXPEDITION`. VESSEL is optional and absent in this slim demo instance;
expeditions inherit directly from ANCHOR. Any level may tighten a constraint (stricter scope,
lower budget, lower autonomy) but never loosen one set above it. The admission gate refuses any
idea that cannot trace to this ANCHOR.

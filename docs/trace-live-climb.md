# Trace: a live ladder climb on a real UI vessel, $0

This records the §10 acceptance trace #2 — *a ladder runs on a real UI vessel* — executed live on
the **free subscription lane** (no metered spend, no sponsored-credit drawdown), producing real
artifacts rather than stubs.

## The run

- **Vessel:** `acme-demo` (the reference UI vessel — storefront + inventory-admin).
- **Idea:** "show a low-stock badge on product cards when quantity is below the reorder point."
- **Builder + judge:** both on the skill-server subscription lane (`SkillServerBuilder` /
  `SkillServerJudge`), `funded_by="subscription"`, **real $ spent = 0.0**.
- **Result:** admitted → rung-1 **spec produced** (1382 chars, a real user story + acceptance
  criteria) → rung-2 **3 wireframes produced** → parked at `await-pick` (correct — the ladder waits
  for a human to choose the winning wireframe; it never auto-advances past a human gate).

So the ladder is not hardcoded to its own repo: given a vessel config + an idea, it climbs and
produces real artifacts on a live model, at zero real spend. (The ladder also ran admission live on
a *second, distinct* vessel config; and the `fls bench` scoreboard exercises two vessels — see
`engine/docs/bench-results.md`.)

## Honest robustness note

A full climb makes ~15 model calls (rung-1 spec fan-out + rank + critique + revise, rung-2 wireframe
fan-out + rank). On the first attempt, one call returned a transient **HTTP 500** from the skill
server and aborted the whole `run_batch` (the client is fail-closed — it raises rather than fabricate
a result). The retry ran clean. **Takeaway:** a production live-climb caller should wrap model calls
with a bounded retry/backoff, since a single transient upstream error otherwise sinks a whole
expedition. That resilience is a caller concern, deliberately *not* baked into the pure engine.

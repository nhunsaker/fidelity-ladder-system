# A worked expedition — the descent that taught the lesson

One idea, climbing the ladder, hitting a wall at the expensive rung, and leaving a lesson behind.
This is the concrete story under the manifesto line *"code is the most expensive place to discover
you built the wrong thing."* Nothing here is hand-waved — every transition below is a real state the
engine writes to the ledger.

The vessel is the reference `@acme/ui` demo app (a small storefront). The idea: **"add a restock
button to the inventory table."**

## The climb

**Admission (one door).** The idea traces to the ANCHOR's north star (inventory operators need
faster restocks) → **admitted**. A ledger row is written; nothing enters the ladder any other way.

**Rung 1 — spec.** The builder drafts a tight spec; the judge ranks it and critiques it once. The
spec ends with a machine-checkable `ACCEPTANCE:` block:

```
ACCEPTANCE:
1. clicking Restock on a row calls restock(sku) exactly once
2. the row's quantity reflects the new stock after the call resolves
3. a failed restock leaves the quantity unchanged and shows an error
```

Because those criteria *compile to a test stub*, the expedition is allowed past the rung-1 gate
(the theater-gate: prose criteria a human can only eyeball would have parked here).

**Rung 2 — wireframe.** Three wireframes fan out; an a11y pre-check lints each before a human sees
them (no asking a person to choose among broken options). A human picks the winning line.

**Rung 3 — demo.** A clickable throwaway is built and a real walkthrough audits it. It passes —
advance.

## The descent

**Rung 4 — MVP (first attempt).** The builder writes the real code. But it builds against an
*imagined* interface — it calls `api.updateStock(sku, qty)`, a function that doesn't exist; the real
contract is `restock(sku)`. The verifier runs acceptance criterion #1 and it **fails**.

This is the whole point of the ladder. The wrongness — a **contract misread** — was *knowable*, but
the builder only discovered it at rung 4, the most expensive rung, after writing code. The
expedition **descends** to rung 2, and the engine records a **lesson**:

```
lesson (expedition #, rung 4 → 2): builder built against an imagined interface
(api.updateStock) instead of the real contract (restock). Root cause: the acceptance
test was not in the builder's bounded context — it inferred the interface.
```

## The re-climb

**Rung 4 — MVP (second attempt).** On the re-climb, the lesson has changed the context: the
acceptance criteria are now *in* the builder's bounded context (rung 1's compiled stub, carried
forward). The builder sees criterion #1 as code — `restock(sku)` called exactly once — and builds
against the real contract. The verifier passes all three criteria.

**Rung 5 — flag (hard gate).** The engine drafts a PR behind a feature flag and **parks** at
`await-signoff`. It refuses to present the PR unless it's reviewable in the line budget and carries a
walkthrough URL — and it never auto-ships. A human owns the irreversible action.

## What it cost, and what it taught

The contract misread cost a full rung-4 build to surface. Had the same misread been catchable a rung
earlier — in the spec or the wireframe — it would have cost a few percent of that (see the
[scoreboard](../engine/docs/bench-results.md)). That gap is the thesis, and the lesson the ledger
kept — *acceptance criteria belong in the builder's context* — is now a permanent part of how this
ladder climbs. **Failure descends and leaves a lesson.**

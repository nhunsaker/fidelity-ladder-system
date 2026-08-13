# Fidelity Ladder System — end-to-end demo walkthrough

> **For founder review.** This is the full arc, beat by beat, as you'd run it to verify the
> system (and, later, to demo it for GitHub Next). Each beat has **Do** (what to run/open),
> **See** (what should appear), **Say** (the one-line narration — why it matters), and **Verify**
> (the checkable claim). Mark anything that doesn't match; that's the feedback loop.

**Legend for honesty:** 🟢 live now · 🟡 runs locally (needs keys) · 🔴 gated (needs a deploy).

---

## Pre-flight (2 min)

```bash
cd fidelity-ladder-system/engine
uv venv && uv pip install -e ".[dev,mcp]"
.venv/bin/python -m pytest -q            # expect: 69 passed
```

Keys (keychain, auto-read — nothing to export): `anthropic-api-key` (builders),
`langchain-api-key` (pass-back/feeder), `AZURE_OPENAI_KEY` env (judges).

Two honesty notes before you start, so nothing surprises you mid-demo:
- The **admin UI** currently reads `admin/fixtures.json`, not the live harness API. It's a faithful
  lens over the data shape; wiring it to the live API is a queued P3-live nicety.
- The deployed **stage** page has the `cmd-k-search` flag baked **ON** (it reflects expedition
  #101's shipped-to-stage state); the repo's `demo-app/flags.json` shows both off. The deployed
  state is the source of truth for the two-URL close.

---

## The 30-second frame (say this first)

> "This is a loop that turns a *stated intent* into a *shipped, feature-flagged change* by
> climbing fidelity rungs — spec, wireframe, interactive demo, MVP, flagged code — and it spends
> scarce human judgment only where blast radius earns it. The whole thing is governed by one file:
> the **ANCHOR**. Agents propose; humans own every irreversible step; and every claim is backed by
> evidence in a ledger, never asserted."

---

## Beat 1 — The ANCHOR (the constitution) 🟢

**Do:** open `ANCHOR.md`.
**See:** a human header (north star + five non-negotiables) and one fenced ` ```anchor ` block that
the whole system machine-reads — funnel policy (1 auto-build · 3 demos · wireframes-all), per-rung
autonomy dials, per-rung cost estimates, budgets, the demote trigger, the builder backend.
**Say:** "Nothing is hard-coded. Change this file — reviewed, as a PR — and the system's behavior
follows. Tighten-only: any rung may make a rule *stricter*, never looser."
**Verify:** `.venv/bin/python -c "from fls.anchor import Anchor; a=Anchor.load('../ANCHOR.md'); print(a.funnel, a.rungs['4-mvp'].dial)"`
→ prints the funnel + `Dial.human_picks`.

---

## Beat 2 — Admission: an idea that doesn't trace gets docked 💰 🟡

The first money moment: the gate refuses work that doesn't trace to the ANCHOR — *with a reason*,
not silently.

**Do:** run the paper-ladder driver (or the admission unit path):
```bash
.venv/bin/python -c "
from fls.anchor import Anchor
from fls.adjudicator import Idea, adjudicate
from fls.llm import AzureJudge
a = Anchor.load('../ANCHOR.md'); txt = open('../ANCHOR.md').read()
j = AzureJudge('gpt-5.4-nano')
bad = Idea(1, 'add a crypto trading bot to the app', 'users can day-trade', 'feature')
print(adjudicate(bad, a, txt, j))
"
```
**See:** `Judgment(verdict=Verdict.dock, reasoning='…does not trace to the north star…', cost=Call(...))`.
**Say:** "It didn't judge whether a trading bot is a *good* idea — only whether it traces to *this*
ANCHOR. It doesn't, so it docks, and it says why. That reason is the audit trail."
**Verify:** the verdict is `dock` and the `cost` field is populated (every verdict is budget-bounded).
*(No Azure key? The altitude pre-check still docks a `migration`-altitude idea deterministically at $0.)*

---

## Beat 3 — The funnel fills the gallery 🟡

**Say:** "An *admitted* idea doesn't just build. The funnel applies the ANCHOR policy: the top idea
climbs the full ladder hands-off, the next three get clickable demos, and *every* admitted idea gets
a wireframe — so the backlog is a gallery, never an invisible queue."
**Verify (concept):** `a.funnel` → `auto_build=1 interactive_demos=3 wireframes='all' queue=0`. The
wall in Beat 9 is where this becomes visible.

---

## Beat 4 — Rung 1: spec fan-out + the reflection pass 🟡

**Say:** "Rung 1 is the cheapest, highest-leverage loop. Three candidate specs fan out, a judge
ranks them against the ANCHOR, then the judge *critiques the winner* and the builder revises it
once. That reflection pass is the single biggest quality lift in the system."
**Where:** this is the first stage of `scripts/live_end_to_end.py` (Beat 7 runs the whole thing).
**Verify:** the run prints 3 specs, a ranking, and a revised top spec; the ledger row carries the
judge's cost-per-verdict.

---

## Beat 5 — Rung 2: pick a wireframe 🟡

**Say:** "Three Primer-styled wireframes, pick-of-three by a human. Low fidelity, cheap to throw
away — we're still buying *direction*, not committing to *build*."
**Verify:** three wireframe artifacts; the pick is recorded on the expedition.

---

## Beat 6 — Rung 3: an interactive demo, then a real Playwright walkthrough 🟡

**Say:** "Rung 3 is a *clickable* throwaway — self-contained HTML, fake data — and then a real
Playwright walkthrough drives it against the acceptance criteria. A demo that isn't actually
interactive *fails the walkthrough* and that's a design signal — we descend."
**Verify:** `expeditions/live-101/demo/index.html` renders and the walkthrough reports `passed:true`
with steps (`loaded`, `interactive elements: N`, `first interaction performed`). A static page would
report *"no interactive elements — not a clickable demo."*

---

## Beat 7 — Rung 4: the MVP loop and an UNSCRIPTED descent 💰 🟡

The centerpiece. A planted bug is caught by the exit verifier — not by a scripted animation.

**Do:**
```bash
.venv/bin/python scripts/live_end_to_end.py     # ~$0.30 session cap, real haiku + Azure
```
**See (the arc):** admission → rung-1 (+reflection) → rung-2 → auto-pick → rung-3 (real Playwright
PASS) → rung-4 loop, ending with either a PR package or a descent. On a build that fails its
acceptance test you'll see:
```
passed: False | attempts: N | descended: True
```
and a new line appended to `expeditions/live-101/LESSONS.md`, e.g.:
```
- (exp #101, rung 4) Design failure at rung 4: mechanical: tests=['not ok 1 - cmd-k focuses
  search incl. from modal', ...] 
```
**Say:** "The builder wrote code against an *imagined* interface, the exit verifier ran `node --test`
against the *real* acceptance test, it failed honestly, and the system **descended** — it didn't
paper over it. The failure became a durable lesson that future rung-1 judges read. That's the loop
teaching itself."
**Verify:** (1) the descent was driven by a *real* test failure in the output, not a hardcoded
branch; (2) `LESSONS.md` gained a generalized entry; (3) on a passing build, the PR package at
`expeditions/live-101/pr-package.md` is reviewable in ≤10 minutes (diff + tests + eval + corner
cuts).

---

## Beat 8 — Rung 5: stage auto-deploys, prod is gated 💰 🟢

The two-URL close. Same app, one flag, two environments.

**Do:** open both:
- 🟢 **stage** → https://stage.fidelity-ladder-system.n8plusus.com  → press **⌘K**
- 🟢 **prod**  → https://prod.fidelity-ladder-system.n8plusus.com  → press **⌘K**
**See:** on **stage** the Cmd-K search focuses (flag **ON** — the change shipped to stage on merge).
On **prod** nothing happens (flag **OFF** — awaiting the promotion gate).
**Say:** "Rung 5 merged the PR, ran a smoke self-check, and auto-deployed to **stage**. Prod is a
hard gate — a required human reviewer on a GitHub Environment. Same code, same flag, gated by a
person. *That's* 'human owns every irreversible action,' made physical in two URLs."
**Verify:** stage responds to ⌘K, prod does not; both are real Let's-Encrypt TLS.

---

## Beat 9 — The admin UI: one lens over the whole protocol 🟢

**Do:** open 🟢 https://admin.fidelity-ladder-system.n8plusus.com
**See:** four sections —
- **Gatekeeper inbox** — ranked by *information value* (judge↔human disagreement, novelty, budget
  anomaly), **not** recency. The thing most worth your attention is on top.
- **Wall of ladders** — every expedition at its rung/dial/status/spend.
- **Autonomy panel · calibration readout** — per-rung judge-vs-human agreement + cost-per-verdict,
  with the one-click demote that reads the ANCHOR demote trigger.
- **LESSONS** — the durable anti-patterns from descents.
**Say:** "The admin UI is a *lens*, never a second source of truth. Every decision still flows
through one protocol — GitHub issues/reviews via the App. This just makes the state legible."
**Verify:** the four sections render; the inbox is ordered by information value, not time.
*(Honesty: this reads fixtures today; live-API wiring is queued.)*

---

## Beat 10 — The feeder: ideas from the studio brainstorm 🟡/🔴

**Do (🟡 offline, $0 — proves the shape):**
```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from fls.anchor import Anchor
from fls.feeder import run_feeder, ListSink
from fls.llm import Call
ROOT=Path('..').resolve(); a=Anchor.load(ROOT/'ANCHOR.md'); t=(ROOT/'ANCHOR.md').read_text()
class Stub:
    def complete(self,p,max_tokens=1024,system=None):
        import json
        return json.dumps([{"intent":f"idea {i}","success":"win","altitude":"feature","rationale":"traces"} for i in range(7)]), \
               Call("skill-server","claude-haiku-4-5-20251001",500,300,usd=0.0,normalized_usd=0.02,funded_by="subscription")
r=run_feeder(a,t,Stub(),ListSink())
print(f"proposed={r.proposed} filed={len(r.filed)} cap={r.capped_to} within_envelope={r.within_envelope} shadow=${r.normalized_usd}")
PY
```
**See:** `proposed=7 filed=5 cap=5 within_envelope=True shadow=$0.02`.
**Say:** "A headless brainstorm, governed entirely by the ANCHOR — scope, guardrails injected into
the prompt, a volume cap, a cost envelope. Surviving ideas are filed through the *standard door* —
the same admission gate a human uses. The feeder can **never** self-admit."
**Verify:** 7 proposed, 5 filed (the `volume_cap`), and each filed item is a raw candidate awaiting
admission — not an admitted expedition. 🔴 The live subscription-lane feeder (`$0`) and the nightly
Temporal schedule need the skill-server deploy (Beat 12 note).

---

## Beat 11 — The pass-back + the two-column money story 🟡/🔴

**Say:** "Builder work can run two ways. The **API** lane is metered Anthropic. The **pass-back**
lane routes the same work through the studio skill-server on the subscription — *no API key, nothing
metered*. And we account for both in one ledger."

**Do (🟢 transport proof, live now):**
```bash
.venv/bin/python scripts/live_passback_and_feeder.py
```
**See:** `HTTP Error 404: Not Found` on `/invoke/complete`.
**Say:** "That 404 is the *good* failure — auth and Cloudflare are fully clear, the request reached
the origin; the server just doesn't have the `complete` skill deployed yet. 🔴 That deploy is the one
remaining gate."

**The economics readout (from Beat 7's run):**
```
=== ECONOMICS (two-column) ===
calls: N | ACTUAL: $0.0266 | NORMALIZED: $0.0266
  api          actual=$0.0212  normalized=$0.0212
  credits      actual=$0.0000  normalized=$0.0054   ← Azure judges, funded by sponsorship
latency: avg NNNms over M timed calls
guard: $0.0266 of the $0.30 session cap
```
**Say:** "`actual` is money out the door. `normalized` is the same tokens at list price. The gap is
the subsidy — Azure credits here, the Claude subscription once the pass-back is live. That's how we
claim *utility-per-dollar*, not vibes: the denominator is real."
**Verify:** `funded_by` splits the spend by pool; the client-side budget guard shows it stayed under
cap (fail-closed — it would have *raised* before overspending).

---

## Beat 12 — The conversational / MCP beat 🟡

**Say:** "Everything the admin UI shows, an agent can do through `ladder-mcp`: read the wall, read
the calibration, file an idea, request an advance, promote — and the gates are **non-bypassable**."
**Verify (the governance property, deterministic, $0):**
```bash
.venv/bin/python -m pytest tests/test_ladder_mcp.py -q -k promote
```
→ `promote_to_prod` refuses without an approver and succeeds with one. An MCP tool cannot bypass the
prod gate. `file_idea` cannot self-admit. 🔴 The live `studio_trigger_brainstorm` needs the
skill-server deploy.

---

## The close (say this last)

> "Five rungs, one ANCHOR. Agents did the fan-out, the ranking, the building. A human docked the
> bad idea, picked the wireframe, and owns the prod gate. The system caught its own planted bug and
> wrote itself a lesson. And every number — agreement, cost-per-verdict, utility-per-dollar,
> time-to-human — is in the ledger, not in the pitch."

---

## Scoreboard for your review

| # | Beat | State | Your verdict |
|---|---|---|---|
| 1 | ANCHOR constitution | 🟢 | |
| 2 | Admission dock 💰 | 🟡 | |
| 3 | Funnel policy | 🟡 | |
| 4 | Rung 1 + reflection | 🟡 | |
| 5 | Rung 2 wireframe pick | 🟡 | |
| 6 | Rung 3 demo + Playwright | 🟡 | |
| 7 | Rung 4 unscripted descent 💰 | 🟡 | |
| 8 | Rung 5 stage/prod close 💰 | 🟢 | |
| 9 | Admin UI lens | 🟢 (fixtures) | |
| 10 | Feeder | 🟡 / 🔴 live | |
| 11 | Pass-back + economics | 🟡 / 🔴 live | |
| 12 | MCP non-bypassable gates | 🟡 | |

**Known gaps to weigh in on:** (a) admin UI on fixtures vs live API; (b) the one skill-server deploy
that flips 🔴→🟢 for the pass-back + live feeder — blocked on reconciling ~85 lines of undeployed
`skills.js` drift on the NAS; (c) nightly Temporal schedule; (d) whether the demo runs live-keyed on
stage or fully local for the interview.

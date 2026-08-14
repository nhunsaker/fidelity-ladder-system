# Using the builder pass-back (P7) + the feeder (P4)

A hands-on walkthrough of the two backends you just built: routing **builder work**
through the studio skill-server instead of the metered Anthropic API (P7), and the
**studio-brainstorm feeder** that files ideas into the ladder (P4).

Everything here is on branch `feat/p7-passback-p4-feeder` (PR #1). Run commands from
the `engine/` directory unless noted.

---

## 0. What works today vs. what's gated

| Capability | Status today | Needs |
|---|---|---|
| Run the whole engine on the **API** backend | ✅ works now | `anthropic-api-key` (in keychain) |
| Run the **feeder** offline (stub, $0) | ✅ works now | nothing |
| Run the **feeder** API-backed (real ideas) | ✅ works now | `anthropic-api-key` |
| **Pass-back** transport / auth / WAF | ✅ verified live | `langchain-api-key` (in keychain) |
| **Pass-back** end-to-end (real completion) | ⛔ gated | the `complete` skill deployed to the NAS |
| **Feeder** via skill-server (subscription, $0) | ⛔ gated | same deploy |
| **Nightly** feeder | ⛔ gated | Temporal schedule on the NAS |

The two ⛔ rows are one founder step — see [§6](#6-the-one-gated-step-deploy-the-complete-skill).

---

## 1. One-time setup

```bash
cd fidelity-ladder-system/engine
uv venv                          # creates .venv
uv pip install -e ".[dev,mcp]"   # dev = tests+ruff, mcp = ladder-mcp
.venv/bin/python -m pytest -q    # expect: 69 passed
```

Keys are read from the macOS keychain automatically (no plaintext, nothing to export):

- **API builder** → `anthropic-api-key`
- **Pass-back / feeder** → `langchain-api-key`
- **Judges (optional)** → `AZURE_OPENAI_KEY` env

You can override any of them with env vars (`ANTHROPIC_API_KEY`, `LANGCHAIN_API_KEY`,
`FLS_SKILL_SERVER` for a non-default endpoint).

---

## 2. The one knob that switches backends: the ANCHOR `builder:` block

Open `ANCHOR.md` and find the machine-parsed block. The builder backend lives here:

```yaml
builder:
  backend: skill-server        # skill-server = pass-back (subscription) · api = metered Anthropic
  shadow_model: claude-haiku-4-5-20251001   # list price the subscription lane is normalized against
  fallback: api                # api | none — may we spend metered $ when the skill-server is down?
  fallback_budget_usd: 0.50    # hard ceiling on that fallback spend, per run
  fallback_pin: per-run        # once a run falls back, it STAYS on api (no mid-climb flapping)
```

Nothing in code picks a backend — `make_builder(anchor)` reads this block and hands
you the right object. Change `backend:` and the whole engine follows. Edits to ANCHOR
are reviewed changes (a PR), never live-poked — that's the constitution rule.

```python
from fls.anchor import Anchor
from fls.llm import make_builder

anchor = Anchor.load("../ANCHOR.md")
builder = make_builder(anchor)     # SkillServerBuilder wrapped in FallbackBuilder, or ClaudeBuilder
```

---

## 3. The feeder (P4) — file ideas into the ladder

The feeder runs one ANCHOR-governed brainstorm and files the top-N ideas through the
**standard door** (the same idea-issue → admission path a human uses). It **never
self-admits** — admission is still a separate gate.

### 3a. Offline dry run — $0, works right now

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from fls.anchor import Anchor
from fls.feeder import run_feeder, ListSink
from fls.llm import Call

ROOT = Path("..").resolve()
anchor = Anchor.load(ROOT / "ANCHOR.md")
anchor_text = (ROOT / "ANCHOR.md").read_text()

# a stub "brainstorm" so this costs nothing — swap for a real builder in 3b
class Stub:
    def complete(self, prompt, max_tokens=1024, system=None):
        import json
        ideas = [{"intent": f"idea {i}", "success": "measurable win",
                  "altitude": "feature", "rationale": "traces to anchor"} for i in range(7)]
        return json.dumps(ideas), Call("skill-server", "claude-haiku-4-5-20251001",
                                       500, 300, usd=0.0, normalized_usd=0.02, funded_by="subscription")

run = run_feeder(anchor, anchor_text, Stub(), ListSink())
print(f"proposed={run.proposed}  filed={len(run.filed)} (cap={run.capped_to})")
print(f"within_envelope={run.within_envelope}  usd=${run.cost_usd}  shadow=${run.normalized_usd}")
for f in run.filed:
    print(f"  • [{f.candidate.altitude}] {f.candidate.intent}")
PY
```

You'll see 7 proposed, **5 filed** (the ANCHOR `volume_cap`), a `within_envelope`
flag, and the two-column economics. This is exactly the shape the real run produces.

### 3b. Real ideas via the API backend — spends ~$0.001 (one haiku call)

Swap the `Stub` above for a live builder:

```python
from fls.llm import ClaudeBuilder
run = run_feeder(anchor, anchor_text, ClaudeBuilder("claude-haiku-4-5-20251001"), ListSink())
```

Now the ideas are model-generated and grounded in your ANCHOR (north star +
non-negotiables are injected into the prompt; the scope line steers them).

### 3c. Via the MCP tool (once the skill-server `complete` skill is deployed)

```
studio_trigger_brainstorm(topic="onboarding polish")
→ { triggered: true, proposed: 7, filed: 5, within_envelope: true,
    cost_usd: 0.0, normalized_usd: 0.03, ideas: [...] }
```

This rides the **subscription** lane (`usd=$0`) and fails closed with a reason if the
skill-server is unreachable.

### The feeder's ANCHOR knobs (all in `idea_sources[feeder].params`)

| Knob | Effect |
|---|---|
| `scope` | one line that steers what gets proposed |
| `guardrails_into_prompt` | inject the non-negotiables into ideation (not just the gate) |
| `volume_cap` | how many ideas get filed (top-N) |
| `cost_envelope_usd` | bounds the **shadow** cost per run; sets the `within_envelope` flag |
| `context_cap_tokens` | hard-truncates any workspace checkout you feed the prompt |

---

## 4. The pass-back (P7) — builder work with no API spend

`SkillServerBuilder` sends builder prompts to the studio skill-server
(`POST /invoke/complete`, Bearer `langchain-api-key`), which runs them through the
local `claude -p` CLI on the NAS. **No Anthropic API key, nothing metered** — the work
rides your Claude subscription.

### Run the live driver

```bash
.venv/bin/python scripts/live_passback_and_feeder.py
```

**Today** this prints:

```
── P7: rung-1 via the builder PASS-BACK (subscription lane) ──
  skill-server error (reconcile the /complete contract):
  skill-server unreachable: HTTP Error 404: Not Found
```

That 404 is the *good* failure — it means **auth and the Cloudflare WAF are fully
clear** and the request reached the origin; the server just doesn't have the `complete`
skill yet. (Earlier this was a 403 — Cloudflare's bot-fight blocks the default
`Python-urllib` User-Agent. The builder now sends an explicit `fls-engine/0.1` UA, fixed
and verified live.)

**After the deploy** ([§6](#6-the-one-gated-step-deploy-the-complete-skill)) the same
command runs a real rung-1 spec fan-out through the pass-back and, if an Anthropic key
is present, prints the **numeric-equivalence** line — the same rung via the metered API
lane, side by side, proving the subscription lane produces comparable output at `usd=$0`.

### Switch the whole engine to the pass-back

Set `builder.backend: skill-server` in `ANCHOR.md` (it already is on this branch). Every
rung that builds — specs, wireframes, demos, MVP — now routes through the skill-server.
The `FallbackBuilder` wrapper handles the skill-server being down:

- **authorized** — it only falls back to the API if `fallback: api` is set;
- **budgeted** — it refuses a fallback call once cumulative fallback spend reaches
  `fallback_budget_usd`, *before* firing;
- **pinned** — once a run falls back, it stays on the API for the rest of that climb
  (no flapping that would scatter one expedition across two providers).

If the skill-server is down and `fallback: none`, the expedition **parks** (fail-closed) —
it never proceeds on optimism.

---

## 5. Reading the two-column economics

Every model call records both a real and a normalized cost, so the subscription and API
lanes are comparable even though one is free:

| Field | Meaning |
|---|---|
| `usd` | actual money out the door — `$0` for the subscription and Azure-credit lanes |
| `normalized_usd` | the same tokens priced at list rate (the shadow cost) — always > 0 |
| `funded_by` | `api` \| `subscription` \| `credits` — which pool paid |
| `latency_ms` | round-trip time |

`savings = normalized_usd − usd`. On the pass-back lane that's the *entire* shadow cost,
because `usd` is zero. That's the number that justifies the pass-back: same work, priced
at what it *would* have cost, funded by the subscription instead.

The skill-server doesn't report token counts, so on that lane the shadow cost is
**estimated** (~4 chars/token). It's a comparability signal, not an invoice.

---

## 6. The one gated step: deploy the `complete` skill

The pass-back needs a generic `complete` skill on the skill-server. It's written and
tested but **source-only** — publishing it is a founder NAS action.

1. In `metatoy-ops/langchain` — the change is already in your working tree:
   - `src/skills.js` — the additive `complete` skill (raw prompt → text, no template
     interpolation so untrusted `{braces}` are safe)
   - `src/complete-skill.test.js` — 4 tests (`npm test` → its suite stays 49🟢)

   Commit those two files (on a branch of your choosing — they're on an unrelated
   feature branch right now).

2. **Redeploy the NAS skill-server** (the `metatoy-temporal` Docker stack). See the
   `langchain-skill-server-nas` runbook for the exact deploy invocation (docker-compose
   v1, `--env-file`, full docker path + sudo, remotely-managed CF tunnel).

3. Verify it's live:
   ```bash
   curl -s https://langchain.n8plusus.com/skills | grep -o complete
   ```
   Then re-run `scripts/live_passback_and_feeder.py` — the 404 becomes a real spec.

4. **Nightly feeder** — add a Temporal schedule that calls the feeder on the cadence in
   ANCHOR (`cadence: nightly`), with an honest exit status + weekly health line per the
   durability rules.

---

## 7. Quick reference

```bash
# tests
.venv/bin/python -m pytest -q

# lint (what CI runs)
.venv/bin/ruff check src

# live P7 + P4 driver (honest about what's deployed)
.venv/bin/python scripts/live_passback_and_feeder.py

# is the complete skill live yet?
curl -s https://langchain.n8plusus.com/skills | grep -o complete || echo "not deployed"
```

Files: `engine/src/fls/llm.py` (`SkillServerBuilder`, `FallbackBuilder`, `make_builder`),
`engine/src/fls/feeder.py` (the feeder), `engine/src/fls/anchor.py` (`BuilderConfig`,
`FeederParams`), `ANCHOR.md` (the `builder:` block + feeder params).

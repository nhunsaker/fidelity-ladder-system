# Getting started — install the ladder on your repo

The ladder is a generic loop; **your instance is entirely environment configuration**
([`instance.env.example`](../instance.env.example)). A fresh install runs in **local-mode**
out of the box — no GitHub App, no token, no repo — via the built-in `sources.kind=local` /
`auth.kind=none` seams (see [modules.md](modules.md)). Step 3 (wiring the real GitHub surface)
is **optional**, only needed if you want issues-as-expeditions + webhook-driven admission.

## 1. Run it locally first ($0, local-mode)

```bash
cd engine
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q     # stubbed judges — no keys, no spend
.venv/bin/uvicorn fls.app:app     # harness API on :8000
```

```bash
cd admin && pnpm install && pnpm run dev   # the admin UI (Vite, :8792)
```

With no keys configured everything **fails closed** where it should: admission parks ideas as
`needs-human`, the skill-server lane reports unavailable. `sources`/`auth` are the exception —
with no GitHub env set they auto-select the no-op-safe `local`/`none` built-ins (nothing to
configure, nothing pretends a GitHub repo exists). Check `curl -s localhost:8000/system` — a
fresh install shows `"app": false` and `slots.sources.kind == "local"`; that's expected, not
broken. Nothing else pretends, either.

## 2. Write your ANCHOR

Copy [`ANCHOR.md`](../ANCHOR.md) and make it yours — the north star and non-negotiables are
prose (they steer the admission gate and the feeder's ideation); the fenced ```` ```anchor ````
block is machine-read. Every knob is documented in
[anchor-reference.md](anchor-reference.md). The one rule the code enforces everywhere:
**tighten-only** — anything below the ANCHOR may make a constraint stricter, never looser.

## 3. Wire the GitHub surface (optional — skip to stay in local-mode)

1. Load the labels: `gh label create` from [.github/labels.yml](../.github/labels.yml)
   (`rung:*`, `dial:*`, `docked`).
2. The issue template ([.github/ISSUE_TEMPLATE/expedition.yml](../.github/ISSUE_TEMPLATE/expedition.yml))
   is the manual door — one issue = one expedition.
3. Create a GitHub App on your org: webhook URL → `https://<your-harness>/webhook/github`,
   a webhook secret (becomes `FLS_WEBHOOK_SECRET` — the two must match), permissions
   **Issues RW + Deployments RW**, events **Issues + Issue comment**. Then **install it on the
   repo** — creating the App is not enough; webhook delivery only starts after Install App →
   your repo. *(GitHub will prompt "you must generate a private key to install" — you can skip
   it. The private key only matters for the App-token path in step 4b.)*
4. Outbound token (how the harness posts labels + verdict comments back). Two separate objects —
   the App *receives* webhooks; this token *writes back*:
   - **(a) Fine-grained PAT** (quickest): Settings → Developer settings → Fine-grained tokens;
     resource owner = your org, only the ladder repo, Issues RW + Deployments RW. Becomes
     `GITHUB_TOKEN`. Note: comments will post **as the token's owner**.
   - **(b) App installation token** (bot identity): mint via the App's private key + JWT and
     refresh ~hourly into the same `GITHUB_TOKEN` (a separate minter process — keep the private
     key out of the harness). Comments post as `<your-app>[bot]`; the right posture for shared
     or public instances.

   Deliver the token to the server via **stdin, never argv** (it leaks into `ps` and shell
   history otherwise):
   ```bash
   read -rs TOKEN   # paste, or pipe from your secret store
   printf 'GITHUB_TOKEN=%s\n' "$TOKEN" >> <install-dir>/.env && unset TOKEN
   ```
   Set `FLS_REPO=owner/repo` in the same env.
5. **Verify before opening an issue** — three quick checks, then the live round-trip:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" -o /dev/null -w "%{http_code}\n" \
     https://api.github.com/repos/<owner>/<repo>          # 200 = token sees the repo
   curl -s https://<your-harness>/health                   # {"status":"ok"}
   curl -s -o /dev/null -w "%{http_code}\n" -X POST \
     https://<your-harness>/webhook/github -d '{}'         # 403 = fail-closed working
   ```
   Then open an issue with the expedition template: within seconds you should see admission run,
   `rung:*`/`dial:*` (or `docked`) labels land, and a verdict comment. Comment `/advance` and
   watch the rung label flip. **If nothing happens**, the usual cause is the App was created but
   never installed on the repo; second most common is a webhook-secret mismatch (deliveries 403).

The webhook is **HMAC-verified and fail-closed**: unsigned or unconfigured requests get a 403,
always. The human protocol is issue comments: `/advance` · `/pick N` · `/approve` — every one
lands in the calibration ledger with a human-latency timestamp.

> **Plan requirement — Environments on private repos.** Environment *protection rules*
> (required reviewers, wait timers) work on **public repos on every plan**, but on **private
> repos they need a paid plan** (GitHub Team for orgs / Pro for users; Free = public only).
> Two gotchas from the field: the API returns a misleading `422 "billing plan"` error rather
> than a clear message, and **after upgrading, the feature can lag the billing change** —
> if the 422 persists right after purchase, wait and retry. Until the rule is active, the
> harness's own `/approve` gate enforces prod promotion regardless (fail-closed either way).

## 4. Configure judges + builders

- **Adjudicator (judges):** an Azure OpenAI deployment (`AZURE_OPENAI_ENDPOINT` +
  `AZURE_OPENAI_KEY`). Keep it a *different vendor* from your builders — cross-family judging
  avoids self-preference bias.
- **Builders:** either the metered lane (`ANTHROPIC_API_KEY`, guarded by the ANCHOR's hard
  cap) or a self-hosted **skill server** (`FLS_SKILL_SERVER` + `FLS_SKILL_SERVER_KEY`) speaking
  `POST /invoke/{skill}` with Bearer auth — any server returning `{skill, output}` works.
  The ANCHOR's `builder:` block picks the lane and authorizes (and budgets) fallback.

## 5. Deploy

[`deploy.example/`](../deploy.example/) is the reference: one small VM, the harness as a
systemd service on `127.0.0.1:8700`, Caddy for TLS with the admin served statically and
`/api/*` proxied to the harness (the admin's default fetch base is same-origin `/api` — no
build-time config needed). Three hosts: admin, stage, prod.

## 6. Check your wiring

`GET https://<your-harness>/system` is the install health check: all six module slots
(auth · ideas · lenses · sources · workers · environment) with `configured`/`available`
booleans and a docs link per slot — see [modules.md](modules.md), plus a top-level `app`
boolean (whether the GitHub App auth path is active). Anything unconfigured fails closed and
says so; fix by setting the env var the slot's docs name, never by editing code. `auth`/
`sources` are the one pair that fails *open* to a safe local default instead of closed —
`app: false` / `sources.kind: "local"` with no GitHub env set is the fresh-install steady
state, not an error to chase.

## The gates you'll own

The ladder never removes these from the human: prod promotion (a named `/approve`), the kill
switch (a named actor), ANCHOR edits (PRs only), enabling any scheduled feeder, and every
loosening of an autonomy dial (the calibration readout recommends; you apply).

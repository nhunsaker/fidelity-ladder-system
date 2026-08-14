# Getting started — install the ladder on your repo

The ladder is a generic loop; **your instance is entirely environment configuration**
([`instance.env.example`](../instance.env.example)). Installing it on a repo takes four pieces:
an ANCHOR, labels, a GitHub App, and the harness running somewhere.

## 1. Run it locally first ($0)

```bash
cd engine
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q     # 99 tests, stubbed judges — no keys, no spend
.venv/bin/uvicorn fls.app:app     # harness API on :8000
```

```bash
cd admin && pnpm install && pnpm run dev   # the admin UI (Vite, :8792)
```

With no keys configured everything **fails closed**: admission parks ideas as `needs-human`,
the skill-server lane reports unavailable, outbound GitHub calls refuse. Nothing pretends.

## 2. Write your ANCHOR

Copy [`ANCHOR.md`](../ANCHOR.md) and make it yours — the north star and non-negotiables are
prose (they steer the admission gate and the feeder's ideation); the fenced ```` ```anchor ````
block is machine-read. Every knob is documented in
[anchor-reference.md](anchor-reference.md). The one rule the code enforces everywhere:
**tighten-only** — anything below the ANCHOR may make a constraint stricter, never looser.

## 3. Wire the GitHub surface

1. Load the labels: `gh label create` from [.github/labels.yml](../.github/labels.yml)
   (`rung:*`, `dial:*`, `docked`).
2. The issue template ([.github/ISSUE_TEMPLATE/expedition.yml](../.github/ISSUE_TEMPLATE/expedition.yml))
   is the manual door — one issue = one expedition.
3. Create a GitHub App on your org: webhook URL → `https://<your-harness>/webhook/github`,
   a webhook secret (becomes `FLS_WEBHOOK_SECRET`), permissions Issues RW + Deployments RW,
   events `Issues` + `Issue comment`. Install it on the repo.
4. Outbound token: an App installation token or a fine-grained PAT (Issues RW + Deployments
   RW) → `GITHUB_TOKEN`. Set `FLS_REPO=owner/repo`.

The webhook is **HMAC-verified and fail-closed**: unsigned or unconfigured requests get a 403,
always. The human protocol is issue comments: `/advance` · `/pick N` · `/approve` — every one
lands in the calibration ledger with a human-latency timestamp.

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

## The gates you'll own

The ladder never removes these from the human: prod promotion (a named `/approve`), the kill
switch (a named actor), ANCHOR edits (PRs only), enabling any scheduled feeder, and every
loosening of an autonomy dial (the calibration readout recommends; you apply).

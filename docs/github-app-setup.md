# GitHub App registration — the §5 founder step (V2-P2)

The harness is live and verified: `https://api.fidelity-ladder-system.n8plusus.com` accepts
**signed** webhooks (fail-closed on anything unsigned), runs real admission on
`issues.opened`, and handles the `/advance` · `/pick N` · `/approve` comment commands. This
doc is the one remaining click-path: registering the App so real GitHub issues drive it.

## 1. Create the App (~3 minutes)

Go to: **github.com → metatoy org → Settings → Developer settings → GitHub Apps → New GitHub App**
(direct URL: `https://github.com/organizations/metatoy/settings/apps/new`)

| Field | Value |
|---|---|
| GitHub App name | `fls-harness` |
| Homepage URL | `https://admin.fidelity-ladder-system.n8plusus.com` |
| Webhook → Active | ✅ checked |
| Webhook URL | `https://api.fidelity-ladder-system.n8plusus.com/webhook/github` |
| Webhook secret | run locally: `security find-generic-password -s fls-webhook-secret -w` and paste the value (it is already on the VM; the two must match) |

**Permissions (Repository):**
- Issues — **Read and write** (labels + comments mirror)
- Deployments — **Read and write** (rung-5 Environment deployments)
- Metadata — Read-only (mandatory default)

**Subscribe to events:** `Issues` · `Issue comment`

**Where can this App be installed:** Only on this account. → **Create GitHub App**.

## 2. Install it

On the new App's page → **Install App** → metatoy → **Only select repositories** →
`fidelity-ladder-system` → Install.

## 3. Outbound token (so the harness can post labels/comments back)

Two options; (a) is simpler for now:

**(a) Fine-grained PAT (recommended for the demo):** github.com → your avatar → Settings →
Developer settings → Fine-grained tokens → Generate new token. Resource owner `metatoy`,
repository `fidelity-ladder-system` only, permissions: Issues RW + Deployments RW. Then put it
on the VM:
```bash
ssh -i ~/.ssh/id_ed25519_sorb fls@20.102.85.204 \
  "echo 'GITHUB_TOKEN=<the-token>' >> /home/fls/fls-app/.env && sudo systemctl restart fls-harness"
```

**(b) App installation token** (rotates hourly; proper long-term path): mint via the App's
private key + JWT out-of-band and refresh into the same env var. Deferred until a rotation
job exists — the harness deliberately never holds the App private key.

## 4. Verify the real round-trip (1 minute)

Open a new issue on `metatoy/fidelity-ladder-system` using the **🧭 Expedition (idea)**
template. Within seconds the App should: run admission (real gpt-5.4-nano), set the
`rung:0-intent` + `dial:*` labels (or `docked`), and post the verdict comment. Then comment
`/advance` and watch the rung label flip. Check `journalctl -u fls-harness` on the VM if
anything is silent.

## Environments note (honest constraint, discovered 2026-08-13)

`staging` and `production` Environments exist on the repo, but **GitHub's required-reviewer
protection rule on a PRIVATE repo needs a paid org plan** (API returns 422 on the free plan).
Until a decision (make the repo public, or upgrade to Team), the enforcing prod gate is the
**harness layer** — `promote_to_prod` refuses without a named approver, and the only door in
is the signed `/approve` comment through this App. Founder decision recorded in
`build-plan-v2.md`.

## What's already live (no action needed)

- Harness API: `api.fidelity-ladder-system.n8plusus.com` (systemd `fls-harness`, uvicorn
  :8700 behind Caddy auto-TLS)
- Env on the VM: Azure judge key · webhook secret · `FLS_REPO` (`/home/fls/fls-app/.env`)
- Verified live: unsigned POST → 403 · signed `issues.opened` → real admit → wall ·
  `/advance` → rung flip + human-latency ledger row · `/preview/live-101` → 200

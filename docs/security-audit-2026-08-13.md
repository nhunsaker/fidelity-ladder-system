# Pre-public security audit — 2026-08-13

Scope: the FULL git history (33 commits, 92 unique paths across all branches), not just the
working tree. Secret values were verified by comparison against the live keychain/Azure values
— never printed, never logged.

## Findings

| # | Check | Result |
|---|---|---|
| 1 | Secret-named files ever committed (`.env`, `.pem`, `.key`, `id_*`, `*secret*`, `*credential*`) | ✅ none, ever |
| 2 | Key-shaped patterns in all history (`sk-ant-`, `ghp_`, `github_pat_`, `AKIA…`, `PRIVATE KEY` blocks, `xoxb-`, `AIza…`) | ✅ 0 matches |
| 3 | **Literal live secret values** vs full history — webhook secret · `langchain-api-key` · `anthropic-api-key` · `cloudflare-dns` token · Azure OpenAI key | ✅ all 5 absent |
| 4 | Hardcoded password/api_key assignments in any diff | ✅ none |
| 5 | Expedition/ledger runtime data | ✅ only `expeditions/.gitkeep`; live run data is gitignored |
| 6 | Dependency lockfile (registry URLs/tokens) | ✅ clean |
| 7 | VM SSH posture (its IP appears in docs) | ✅ `passwordauthentication no` · `kbdinteractiveauthentication no` · root key-only — verified live via `sshd -T` |

## Accepted informational exposures (deliberate, not leaks)

- **VM IP `20.102.85.204` + user `fls`** in `deploy/README.md` and `docs/github-app-setup.md`.
  The IP is already public via DNS (grey-cloud A records) and TLS cert transparency; SSH is
  key-only (verified above). Publishing the docs adds no practical attack surface beyond what
  DNS already reveals.
- **Author emails** in commit metadata: `hello@metatoy.com`, `n8plusus@gmail.com` — both
  already-public studio/founder addresses.
- **Domains + keychain item NAMES** (never values) referenced in docs — by design; the
  keychain-only secret discipline is itself documented.

## Bonus on going public

GitHub enables **secret scanning + push protection free on public repos** — an extra tripwire
this repo doesn't get while private.

## Verdict

**SAFE to flip public.** No secret has ever been committed; the only exposures are
informational and already-public via other channels. Re-run the value-comparison check (§3)
before publishing again if the repo ever goes private → public after new work.

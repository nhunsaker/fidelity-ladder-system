# Deploy — engine room (as-built 2026-08-13)
VM: `fls-engine-1` (Standard_D2als_v7, eastus, `fidelity-ladder-rg`) @ 20.102.85.204 · user `fls`,
key `~/.ssh/id_ed25519_sorb` · Caddy (auto-TLS) serving /srv/{admin,stage,prod}.
DNS: 3 A records (grey-cloud) in the n8plusus.com CF zone. Stage flag cmd-k-search=ON, prod off
(expedition #101's rung-5 state). Note: B-family SKUs unavailable to this sub in eastus; az CLI
2.88/py3.14 `vm create` is broken — deploy via ARM template over `az rest` (see handoff).

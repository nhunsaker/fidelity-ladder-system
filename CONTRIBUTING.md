# Contributing

This project practices its own constitution — read [`ANCHOR.md`](ANCHOR.md) first. The short
version of what that means for contributions:

- **Ideas enter through the door.** Open an issue with the expedition template; the admission
  question is *does it trace to the ANCHOR*, not *is it clever*.
- **Evidence over claims.** PRs ship with tests (`cd engine && pytest`, `ruff check src`) and
  say what was verified. The reviewability bar: a human review in ≤10 minutes.
- **Fail closed.** New code paths that touch credentials, spend, or deployment must refuse on
  missing configuration — never proceed on optimism, never fake a success.
- **Provenance.** Agent-authored code is welcome and should say so in the PR description;
  every merge is human-gated regardless of author.
- **JavaScript stays JavaScript** (JSDoc types, no TypeScript) and **Python stays ≥3.11**.

Instance details (endpoints, tokens, org names) never enter the code — they belong in the
environment (`instance.env.example`).

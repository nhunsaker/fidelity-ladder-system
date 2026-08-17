# Contributing

Thanks for your interest in the Fidelity Ladder. This repository is the MIT-licensed reference
implementation of the pattern described in [MANIFESTO.md](MANIFESTO.md) and
[docs/pattern.md](docs/pattern.md).

## Ground rules

- **The pattern is the product; the code is disposable.** Changes that make the ladder easier to
  *reimplement* (clearer protocols, better docs, a cleaner reference profile) are as welcome as
  feature work. If you take only the ~100-line sketch from the manifesto, you've taken the framework.
- **Fail closed.** Every gate, verifier, and adjudicator defaults to the safe answer when it can't be
  sure. A change that trades a fail-closed default for convenience is wrong even if it works.
- **Policy lives in the ANCHOR, connection lives in the environment.** Code holds mechanisms only —
  no hardcoded repos, endpoints, tokens, or domains. An instance is entirely variables
  (`instance.env.example` documents the contract). This 12-factor split is load-bearing.
- **The core stays dependency-light.** `import fidelity_ladder` must pull zero web / GitHub / MCP
  dependencies (there's a CI job that enforces this). Web/GitHub/MCP integrations are optional extras.

## Working locally

```bash
pip install fidelity-ladder            # the importable core (pydantic + pyyaml only)
python examples/quickstart.py          # a governed admission runs — no keys, no spend
```

For the full harness + tests, see [docs/getting-started.md](docs/getting-started.md).
Engine tests: `cd engine && pip install -e ".[dev,harness,mcp]" && pytest -q`. Python only (JSDoc
typedefs, never TypeScript, in the JS surfaces); `ruff` clean; fail-closed everywhere.

## Pull requests

Keep changes small and reviewable, add tests for behavior, and describe the *why*. Discussions and
issues are welcome for anything larger before you write code.

Licensed under [MIT](LICENSE).

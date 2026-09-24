"""fls.builders — artifact producers that run as agentic sessions rather than one-shot completions.

A rung's builder turns a bounded context into a real artifact somewhere outside the process: frames
in a design file, a deployed prototype, a branch with a diff. Each returns a small JSON contract the
rung code can verify, plus the ledger `Call` for the session that produced it.

`FigmaWireframeBuilder` (rung 2) is the first. Prototype and code builders follow the same shape:
construct a `ClaudeCodeSession` with exactly the tools that rung may use, hand it a prompt built from
the rung's own reading material, and parse a declared output contract — never prose.
"""

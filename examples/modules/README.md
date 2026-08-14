# Modules — bring your own AUTH · IDEAS · SOURCES · WORKERS

The engine has four pluggable seams. Each is a tiny `typing.Protocol` plus a `kind -> factory`
registry that ships with one built-in. You add a `kind` by importing your module at startup — no
fork, no engine change. This page is the whole contract.

## The two-part config split

Every seam splits the same way (the builder precedent):

- **ANCHOR** (the versioned policy file) carries the **kind** and **policy knobs** — reviewed by PR.
- **Environment** carries **endpoints and secrets** — never committed, never rendered.

Reflection (`GET /system`) reports **booleans and non-secret names only** (kinds, repo names,
budget numbers). It never emits a secret value. Keep that invariant in anything you add.

## The four Protocols

```python
class Worker(Protocol):        # who fulfils builder work (specs / explorations / demos / MVP)
    def available(self) -> bool: ...
    def complete(self, prompt: str, max_tokens: int = ..., system: str | None = ...) -> tuple[str, Call]: ...

class IdeaSource(Protocol):    # where ideas come from — it PROPOSES, it never admits
    def run(self, anchor, anchor_text: str, sink: IdeaSink) -> FeederRun: ...

class Source(Protocol):        # where work lives (issues / comments / labels / deployments)
    def post_comment(self, issue: int, text: str) -> None: ...
    def set_labels(self, issue: int, labels: list[str]) -> None: ...
    def create_deployment(self, env: str, ref: str) -> bool: ...
    def get_issue(self, issue: int) -> dict: ...
    def list_comments(self, issue: int) -> list: ...

class Auth(Protocol):          # inbound signature check + outbound token
    def verify_inbound(self, body: bytes, signature_header: str | None) -> bool: ...
    def outbound_token(self) -> str | None: ...
```

`Call`, `IdeaSink`, and `FeederRun` are imported from the engine (`fls.llm`, `fls.feeder`). You
implement the Protocol structurally — no base class to inherit.

## The registries

Four plain dicts live in `fls.modules`, each pre-populated with its built-in:

```python
WORKERS = {"api": ..., "skill-server": ...}
IDEAS   = {"feeder": ...}
SOURCES = {"github": ...}
AUTH    = {"github-app": ...}
```

A registry maps a **kind string** to a **factory** that returns an instance of the seam's
Protocol. To add a kind, import the target dict and assign into it:

```python
from fls import modules
from .module import MyIdeaAgent

modules.IDEAS["my-agent"] = lambda **kw: MyIdeaAgent(**kw)
```

## Wiring your module in — `FLS_MODULES`

`FLS_MODULES` is a comma-separated list of importable module paths. At startup the engine
`importlib.import_module`s each one, purely for its registration side effects:

```bash
export FLS_MODULES="my_pkg.ideas.wiring,my_pkg.workers.wiring"
```

Put your registry assignments in that module (a `wiring.py` is the convention). Your package must
be importable on `PYTHONPATH`.

## The fail-closed rules (non-negotiable)

1. **Unknown module path → the engine refuses to start.** An `ImportError` from `FLS_MODULES` is
   logged and re-raised. A half-wired module set never runs.
2. **An `IdeaSource` PROPOSES, it never admits.** File every idea through the `sink` (the one
   door); the admission gate decides what enters. A source that admits its own ideas is a bug.
3. **`Auth.verify_inbound` fails closed.** No configured secret, or a missing/bad signature,
   returns `False` — never processed on optimism.
4. **Never render a secret.** Reflection and status surfaces expose presence booleans only.

## Reference: the demo ideas module

`ideas_claude_demo_agent/` is a ~60-line `IdeaSource` that brainstorms N ideas from the anchor
text and files each through the sink. Its test runs against an in-memory `ListSink` with a stub
worker — zero credentials, zero network — and proves the source cannot self-admit. Copy it as a
starting point.

> A durable-workflow scheduler (or any long-running brainstorm backend) is just another `kind`
> behind this same seam — nothing about the contract changes.

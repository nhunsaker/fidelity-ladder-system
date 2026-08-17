# fidelity-ladder

> Code is the most expensive place to discover you built the wrong thing.
> Fidelity is a ratchet, not a throttle.

The importable core of the **Fidelity Ladder** — progressive-fidelity governance for agentic work.
An idea climbs rungs of increasing fidelity (spec → wireframe → demo → code), each gated by a
verifier and a per-rung autonomy dial; wrong *direction* is caught at the cheapest rung where it's
knowable, not after you've written the code. One **ANCHOR** file holds policy; a **calibration
ledger** is how autonomy is *earned*, not configured; everything **fails closed**.

```bash
pip install fidelity-ladder          # core only — pydantic + pyyaml, zero web/GitHub/MCP deps
```

```python
import fidelity_ladder as fl
# rungs are data you can print and swap:
for r in fl.WEB_LADDER_PROFILE.rungs:
    print(r.number, r.name, r.dial.value)
```

`import fidelity_ladder` pulls **zero** web dependencies (enforced in CI). The FastAPI harness, the
GitHub surface, and the MCP server are optional extras — `pip install fidelity-ladder[harness]` /
`[mcp]`. The five module slots (AUTH · IDEAS · SOURCES · WORKERS · LENSES) plus an environment slot
are the extension points; swap the `LadderProfile` to run a different ladder without touching the
engine.

- **Manifesto** — the thesis, named principles, and the honest scoreboard numbers.
- **Pattern** — written GoF-style, reimplementable in ~100 lines without this engine.
- **Quickstart** — a governed admission runs in ~0.1s, no keys, no spend.

See the [project repository](https://github.com/nhunsaker/fidelity-ladder-system) for the full
manifesto, the pattern doc, the worked expedition, and `docs/getting-started.md`.

MIT licensed.

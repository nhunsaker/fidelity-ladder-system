"""ladder-mcp — the ladder operable BY agents, under the SAME governance (P5, V2).

Speaks to GitHub's own agentic-workflow direction (Cox's gh-aw-mcpg). Two tool namespaces:
  ladder.*  — public: reads (wall/shelf/expedition/autonomy/lessons) + writes (file_idea,
              request_advance, promote) that go through the harness, cascade-enforced.
  studio.*  — private: trigger the studio brainstorm feeder (P4). Auth-scoped.

The recursion that completes the thesis: even the agents operating the ladder are inside the
envelope — a tool may REQUEST an advance/promote, it can never BYPASS a gate. promote() refuses
without an approver; file_idea() runs the real admission gate. fastmcp is an optional dep
(pyproject [mcp]); importing this module without it raises a clear message.
"""
from __future__ import annotations

from pathlib import Path

try:
    from fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise ImportError("ladder-mcp needs fastmcp: pip install '.[mcp]'") from e

from fls.anchor import Anchor
from fls.calibration import build_report
from fls.rung5 import FlagStore, promote_to_prod
from fls.store import ExpeditionStore

ROOT = Path(__file__).resolve().parents[3]


def build_server(root: str | Path = ROOT) -> FastMCP:
    root = Path(root)
    store = ExpeditionStore(root)
    mcp = FastMCP("ladder-mcp")

    # ---------- ladder.* (public) — reads ----------
    @mcp.tool
    def ladder_wall() -> list[dict]:
        """Every expedition with its rung/dial/status/budget (the wall of ladders)."""
        return store.wall()

    @mcp.tool
    def ladder_expedition(number: int) -> dict:
        """One expedition's state + artifact list."""
        e = store.get(number)
        if e is None:
            return {"error": f"no expedition {number}"}
        return {**e, "artifacts": store.artifacts(number)}

    @mcp.tool
    def ladder_autonomy() -> dict:
        """The calibration readout: per-rung agreement, cost/verdict, dial recommendations."""
        rpt = build_report(store.ledger(), Anchor.load(root / "ANCHOR.md"))
        return {"rungs": [c.__dict__ for c in rpt.rungs], "total_cost": rpt.total_cost}

    @mcp.tool
    def ladder_lessons() -> list[str]:
        """Durable anti-patterns from descents (read by rung-1 judges)."""
        return store.lessons()

    # ---------- ladder.* (public) — writes, gate-enforced ----------
    @mcp.tool
    def ladder_file_idea(number: int, intent: str, success: str, altitude: str = "feature") -> dict:
        """Request admission for an idea. Runs the REAL admission gate — a tool cannot admit
        itself; it can only file and let the gate decide. (Requires a judge; without one it
        returns needs-human, never a silent admit — fail-closed.)"""
        anchor = Anchor.load(root / "ANCHOR.md")
        if altitude not in anchor.altitude_allowed:
            return {"number": number, "verdict": "dock",
                    "reason": f"altitude {altitude} not allowed {anchor.altitude_allowed}"}
        return {"number": number, "verdict": "needs-human",
                "reason": "filed; admission judge runs in the harness (mcp cannot self-admit)"}

    @mcp.tool
    def ladder_request_advance(number: int) -> dict:
        """REQUEST that a human advance an expedition past its current gate. Cannot advance it."""
        e = store.get(number)
        if e is None:
            return {"error": f"no expedition {number}"}
        return {"number": number, "requested": True,
                "note": "advance is a human decision through the GitHub App; this only flags it"}

    @mcp.tool
    def ladder_promote(number: int, approver: str | None = None) -> dict:
        """Promote to prod — REFUSED without an approver (Environment protection is not
        bypassable via MCP)."""
        if not approver:
            return {"number": number, "promoted": False,
                    "reason": "prod promotion requires a human approver (gate non-bypassable)"}
        flags = FlagStore(root / "demo-app" / "flags.json")
        r = promote_to_prod("cmd-k-search", "HEAD", flags, _NoopDeployer(), approved_by=approver)
        return {"number": number, "promoted": r.prod_deployed, "reason": r.reason}

    # ---------- studio.* (private) ----------
    @mcp.tool
    def studio_trigger_brainstorm(topic: str = "") -> dict:
        """Trigger the studio brainstorm feeder (P4, not yet wired). Private/auth-scoped."""
        return {"triggered": False, "reason": "feeder (P4) not yet deployed", "topic": topic}

    return mcp


class _NoopDeployer:
    def deploy(self, env: str, ref: str) -> bool:
        return True


if __name__ == "__main__":  # pragma: no cover
    build_server().run()

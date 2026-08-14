"""Register the demo agent into the IDEAS registry under kind "claude-demo-agent".

Point the engine at this module to load it:  FLS_MODULES=ideas_claude_demo_agent.wiring
Importing it (the engine does this via importlib) runs the registration side effect below.
"""
from __future__ import annotations

from fls import modules

from .module import ClaudeDemoAgent


def _factory(builder=None, n: int = 3) -> ClaudeDemoAgent:
    return ClaudeDemoAgent(builder=builder, n=n)


modules.IDEAS["claude-demo-agent"] = _factory

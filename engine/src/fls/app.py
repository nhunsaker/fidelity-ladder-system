"""FastAPI harness entry — P0 skeleton.

Owns the GitHub App webhook receiver + a health check. The controller (admission, funnel,
rung transitions), verifier bank, and autonomy ledger land in P1. For P0 this proves the
round-trip: a GitHub event reaches the harness and is logged.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request

from fls.anchor import Anchor

log = logging.getLogger("fls")
logging.basicConfig(level=logging.INFO)

ANCHOR_PATH = Path(__file__).resolve().parents[3] / "ANCHOR.md"

app = FastAPI(title="Fidelity Ladder System — engine", version="0.0.1")


@app.get("/health")
def health() -> dict:
    """Liveness + ANCHOR validity in one probe (fail-closed: bad anchor => not healthy)."""
    a = Anchor.load(ANCHOR_PATH)
    return {"status": "ok", "anchor_version": a.version, "mode": a.mode}


@app.post("/webhook/github")
async def github_webhook(request: Request) -> dict:
    """P0: receive + log the event round-trip. P1: route to the admission gate / controller."""
    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = await request.json()
    action = payload.get("action")
    issue = (payload.get("issue") or {}).get("number")
    log.info("github event=%s action=%s issue=%s", event, action, issue)
    # P1 hook point: if event == "issues" and labeled/opened -> controller.on_idea(payload)
    return {"received": True, "event": event, "action": action, "issue": issue}

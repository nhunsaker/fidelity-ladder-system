"""FastAPI harness — the API the admin UI + ladder-mcp consume.

Read endpoints (wall / expedition / calibration / anchor / lessons) need only the store.
Write endpoints (file an idea -> admission) use an injected judge so this stays testable with a
stub (zero spend). In production the GitHub App posts issue events to /webhook/github; the same
controller logic runs. `deps` is the injection point — tests override deps.judge / deps.store.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.calibration import build_report, category_slice
from fls.controller import on_idea
from fls.store import ExpeditionStore

log = logging.getLogger("fls")
logging.basicConfig(level=logging.INFO)

ROOT = Path(__file__).resolve().parents[3]
ANCHOR_PATH = ROOT / "ANCHOR.md"


@dataclass
class Deps:
    """Injection point. Defaults are lazy so import never needs creds; tests override."""
    root: Path = ROOT
    judge: Any = None            # set to AzureJudge() in prod, a stub in tests
    _store: ExpeditionStore | None = None

    @property
    def store(self) -> ExpeditionStore:
        if self._store is None:
            self._store = ExpeditionStore(self.root)
        return self._store


deps = Deps()
app = FastAPI(title="Fidelity Ladder System — engine", version="0.1.0")


@app.on_event("startup")
def _prod_init() -> None:
    """Prod wiring: give the harness a real adjudicator when the Azure key is present.
    Without one, admission fails closed (needs-human) — never a silent admit."""
    import os as _os
    if deps.judge is None and _os.environ.get("AZURE_OPENAI_KEY"):
        from fls.llm import AzureJudge
        deps.judge = AzureJudge("gpt-5.4-nano")
        log.info("adjudicator: AzureJudge(gpt-5.4-nano)")


def _anchor() -> Anchor:
    return Anchor.load(ANCHOR_PATH)


@app.get("/health")
def health() -> dict:
    a = _anchor()
    return {"status": "ok", "anchor_version": a.version, "mode": a.mode}


@app.get("/anchor")
def anchor() -> dict:
    a = _anchor()
    return {"mode": a.mode, "funnel": a.funnel.__dict__,
            "altitude_allowed": a.altitude_allowed,
            "budgets": a.budgets.__dict__}


@app.get("/wall")
def wall() -> list[dict]:
    return deps.store.wall()


@app.get("/expeditions/{number}")
def expedition(number: int) -> dict:
    e = deps.store.get(number)
    if e is None:
        raise HTTPException(404, f"no expedition {number}")
    return {**e, "artifacts": deps.store.artifacts(number)}


@app.get("/calibration")
def calibration() -> dict:
    a, led = _anchor(), deps.store.ledger()
    rpt = build_report(led, a)
    return {
        "rungs": [c.__dict__ for c in rpt.rungs],
        "total_decisions": rpt.total_decisions,
        "total_cost": rpt.total_cost,
        "disagreement_categories": category_slice(led),
    }


@app.get("/lessons")
def lessons() -> list[str]:
    return deps.store.lessons()


@app.get("/preview/{number}")
def preview(number: str) -> Any:
    """Serve an expedition's rung-3 interactive demo (P2.2 debt: stage…/preview/<id>).
    `number` is a path-safe expedition id (e.g. 101 or live-101) — never a path."""
    from fastapi.responses import FileResponse
    if not number.replace("-", "").isalnum():  # fail-closed on anything path-like
        raise HTTPException(404, "bad expedition id")
    demo = deps.root / "expeditions" / number / "demo" / "index.html"
    if not demo.exists():
        raise HTTPException(404, f"no demo for expedition {number}")
    return FileResponse(demo, media_type="text/html")


@app.post("/ideas")
async def file_idea(request: Request) -> dict:
    """File an idea -> run admission (needs deps.judge). Returns the verdict + reasoning."""
    if deps.judge is None:
        raise HTTPException(503, "no judge configured")
    body = await request.json()
    idea = Idea(number=int(body["number"]), intent=body["intent"],
                success=body.get("success", ""), altitude=body.get("altitude", "feature"),
                source=body.get("source", "manual"))
    verdict, reason = on_idea(idea, _anchor(), ANCHOR_PATH.read_text(), deps.judge,
                              deps.store.ledger())
    return {"number": idea.number, "verdict": verdict.value, "reason": reason}


@app.post("/webhook/github")
async def github_webhook(request: Request) -> dict:
    """The real round-trip (V2-P2): verify the App's HMAC signature (fail-closed), then map
    the event onto the harness — admission for issues.opened, /advance /pick /approve commands
    on comments — and mirror state back to the issue via the outbound client."""
    import os as _os
    import time as _time

    from fls.github_surface import NullClient, RestGitHubClient, handle_event, verify_signature

    body = await request.body()
    secret = _os.environ.get("FLS_WEBHOOK_SECRET")
    if not verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        # no secret configured OR bad/missing signature -> refused, never processed on optimism
        raise HTTPException(403, "webhook signature refused (fail-closed)")
    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = await request.json()
    log.info("github event=%s action=%s", event, payload.get("action"))
    client = RestGitHubClient() if _os.environ.get("GITHUB_TOKEN") else NullClient()
    result = handle_event(event, payload, _anchor(), ANCHOR_PATH.read_text(), deps.judge,
                          deps.store, deps.store.ledger(), client, now=_time.time())
    return {"received": True, **result}

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

# CORS: explicit allowlist from env (FLS_CORS_ORIGINS, comma-separated) + local dev — never a
# wildcard. Same-origin /api deployments (deploy.example) need no CORS at all.
import os as _os  # noqa: E402

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_origins = [o.strip() for o in _os.environ.get("FLS_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins + ["http://localhost:8792"],
    allow_methods=["GET", "POST"], allow_headers=["content-type"],
)


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
    # persist the expedition so the wall shows it (same mapping the webhook path uses)
    from fls.anchor import Verdict
    from fls.expedition import CLIMBING, DOCKED, NEEDS_HUMAN, Expedition
    status = (CLIMBING if verdict == Verdict.admit
              else DOCKED if verdict == Verdict.dock else NEEDS_HUMAN)
    deps.store.save(Expedition(idea.number, idea, 2 if verdict == Verdict.admit else 0,
                               status=status, reason=None if verdict == Verdict.admit else reason))
    return {"number": idea.number, "verdict": verdict.value, "reason": reason}


@app.post("/expeditions/{number}/kill")
async def kill_expedition(number: int, request: Request) -> dict:
    """The kill switch — parks an expedition. Fail-closed: requires a NAMED actor; the kill
    lands in the ledger under their name."""
    body = await request.json()
    actor = (body.get("actor") or "").strip()
    if not actor:
        raise HTTPException(400, "kill requires a named actor (gate is non-bypassable)")
    rec = deps.store.get(number)
    if rec is None:
        raise HTTPException(404, f"no expedition {number}")
    from fls.expedition import PARKED
    from fls.github_surface import _rehydrate
    from fls.ledger import Decision
    from fls.store import RUNG_NAMES
    rung = RUNG_NAMES.index(rec["rung"]) if rec["rung"] in RUNG_NAMES else 0
    e = _rehydrate(rec, rung, PARKED)
    e.reason = f"killed by {actor}: {body.get('reason') or 'no reason given'}"
    deps.store.save(e)
    import time as _t
    deps.store.ledger().record(Decision(number, rec["rung"], "kill", f"kill:{actor}", 0.0,
                                        human_responded_at=_t.time()))
    return {"number": number, "status": "parked", "by": actor}


@app.post("/anchor/validate")
async def anchor_validate(request: Request) -> dict:
    """Schema-validate proposed console edits against the FULL constitution (pydantic)."""
    from pydantic import ValidationError

    from fls.anchor import apply_anchor_edits
    body = await request.json()
    try:
        apply_anchor_edits(ANCHOR_PATH.read_text(), body.get("section", ""),
                           body.get("edits", {}))
        return {"valid": True, "errors": []}
    except ValidationError as e:
        return {"valid": False,
                "errors": [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
                           for err in e.errors()]}
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}


@app.post("/anchor/propose")
async def anchor_propose(request: Request) -> dict:
    """Turn validated console edits into a PR — the constitution changes by PR only. With no
    outbound token the payload is prepared and returned (simulated: nothing pushed), honestly."""
    import os as _os

    from fls.anchor import apply_anchor_edits
    body = await request.json()
    section, edits = body.get("section", ""), body.get("edits", {})
    try:
        new_text, _ = apply_anchor_edits(ANCHOR_PATH.read_text(), section, edits)
    except Exception as e:  # noqa: BLE001 — surface the validation reason
        raise HTTPException(422, f"invalid edit: {e}") from e
    branch = f"anchor-edit-{section}"
    if not _os.environ.get("GITHUB_TOKEN"):
        return {"simulated": True, "branch": branch, "section": section, "edits": edits,
                "note": "no outbound token (github-app-setup.md) — payload staged, nothing pushed"}
    from fls.github_surface import open_anchor_pr
    pr_url = open_anchor_pr(branch, new_text, section, edits)
    return {"simulated": False, "branch": branch, "pr_url": pr_url}


@app.post("/feeder/run")
async def feeder_run(request: Request) -> dict:
    """Trigger one feeder run on the subscription lane. Fail-closed with a reason when the
    skill-server is unavailable — never pretends."""
    from fls.feeder import ListSink, run_feeder
    from fls.llm import SkillServerBuilder, SkillServerError
    a = _anchor()
    brainstorm = SkillServerBuilder(shadow_model=a.builder.shadow_model)
    if not brainstorm.available():
        return {"triggered": False, "reason": "skill-server key unavailable (fail-closed)"}
    try:
        run = run_feeder(a, ANCHOR_PATH.read_text(), brainstorm, ListSink())
    except SkillServerError as e:
        return {"triggered": False, "reason": f"skill-server error: {e}"}
    return {"triggered": True, "proposed": run.proposed, "filed": len(run.filed),
            "within_envelope": run.within_envelope, "cost_usd": run.cost_usd,
            "normalized_usd": run.normalized_usd,
            "ideas": [{"intent": f.candidate.intent, "altitude": f.candidate.altitude}
                      for f in run.filed]}


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

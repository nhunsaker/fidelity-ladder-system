"""FastAPI harness — the API the admin UI + ladder-mcp consume.

Read endpoints (wall / expedition / calibration / anchor / lessons) need only the store.
Write endpoints (file an idea -> admission) use an injected judge so this stays testable with a
stub (zero spend). In production the GitHub App posts issue events to /webhook/github; the same
controller logic runs. `deps` is the injection point — tests override deps.judge / deps.store.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from fls.adjudicator import Idea
from fls.anchor import Anchor, guardrails_prose
from fls.calibration import build_report, category_slice
from fls.controller import on_idea
from fls.store import ExpeditionStore

log = logging.getLogger("fls")
logging.basicConfig(level=logging.INFO)

ROOT = Path(__file__).resolve().parents[3]
# The instance's constitution, not the engine's example one. `FLS_ANCHOR_PATH` is the same
# variable the worker already honours; this module hardcoded the repo-local file, so on a real
# deployment the API judged every admission against the ANCHOR that ships WITH the engine — the
# neutral demo instance — while the worker climbed against the operator's. Two constitutions, one
# system. The default is unchanged, so a checkout with no env set behaves exactly as before.
ANCHOR_PATH = Path(os.environ.get("FLS_ANCHOR_PATH") or (ROOT / "ANCHOR.md"))


@dataclass
class Deps:
    """Injection point. Defaults are lazy so import never needs creds; tests override."""
    root: Path = ROOT
    judge: Any = None            # set to AzureJudge() in prod, a stub in tests
    github: Any = None           # tests inject a NullClient; prod resolves from env lazily
    _store: ExpeditionStore | None = None

    @property
    def store(self) -> ExpeditionStore:
        if self._store is None:
            self._store = ExpeditionStore(self.root)
        return self._store


def _github() -> Any:
    """Outbound GitHub client, or None when unconfigured (callers fail closed/honest)."""
    if deps.github is not None:
        return deps.github

    from fls.github_surface import REPO, RestGitHubClient
    if os.environ.get("GITHUB_TOKEN") and REPO:
        return RestGitHubClient()
    return None


deps = Deps()
app = FastAPI(title="Fidelity Ladder System — engine", version="0.1.0")


# ── the operator guard ───────────────────────────────────────────────────────────────────────
# Deny-by-default, and deliberately MIDDLEWARE rather than a per-route `Depends`. A dependency
# is opt-in: it protects the routes somebody remembered to decorate and fails OPEN on the one
# they forgot, which is the wrong direction for a console holding a kill switch. Middleware also
# covers 404/405, so probing for an unlisted route tells an anonymous caller nothing.
#
# Dormant unless `FLS_IDENTITY_KIND` names a real kind — a fresh install and every existing test
# run through here unchanged and unauthenticated.

# prefix -> WHICH MECHANISM guards it. A mapping rather than a set of exempt paths, because
# "public" and "guarded by something else" are different facts and an undifferentiated exempt
# list loses the difference. /webhook/github is not open; it is HMAC-verified.
PUBLIC_PATHS: dict[str, str] = {
    "/health": "unauthenticated by design (liveness probe)",
    "/auth/": "the sign-in flow itself",
    "/v1/hooks/github": "HMAC-verified by the auth slot (fail-closed)",
    "/webhook/github": "HMAC-verified by the auth slot (fail-closed) — the same hook under"
                       " its old path, until the GitHub App is repointed",
}
# Surfaces whose public-ness is ANCHOR policy (`identity.public_surfaces`), not an engine
# constant — see `fls.anchor.IdentityPolicy`.
# A surface can be reachable under more than one prefix while a rename is in flight, so each
# name maps to a TUPLE. Getting this wrong in either direction is serious: miss a new prefix and
# every visitor call answers 401; miss an old one and a live client breaks. Both spellings stay
# listed until the old paths are retired.
SURFACE_PREFIXES = {
    "demo": ("/v1/visitor/", "/v1/public/runs/", "/demo/"),
    "preview": ("/v1/public/runs/", "/preview/"),
    "wireframes": ("/v1/public/runs/", "/wireframes/"),
}
SURFACE_GUARDS = {
    "demo": "the demo passcode (x-demo-token), a separate audience",
    "preview": "a shareable artifact link (ANCHOR identity.public_surfaces)",
    "wireframes": "a shareable artifact link (ANCHOR identity.public_surfaces)",
}
# Mutating methods need an Origin check on top of SameSite=Lax — see `_origin_ok`.
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def public_paths(a: Anchor | None = None) -> dict[str, str]:
    """The full prefix -> guarding-mechanism map for this instance, ANCHOR policy included."""
    out = dict(PUBLIC_PATHS)
    try:
        surfaces = (a or _anchor()).identity.public_surfaces
    except Exception:  # noqa: BLE001 — an unreadable ANCHOR must not silently open surfaces
        surfaces = []
    for name in surfaces:
        for prefix in SURFACE_PREFIXES.get(name, ()):
            out[prefix] = SURFACE_GUARDS[name]
    return out


def _is_public(path: str, allowed: dict[str, str]) -> bool:
    """Exact match, or a prefix that ends in `/` so it can only match a whole path segment.

    A bare `startswith` made every public entry a trap for whoever adds the next route:
    `/health` would have silently exempted a future `/healthcheck`, and `/webhook/github` a
    future `/webhook/github-app`. Nothing in the current route table collides, which is exactly
    why it would have been found late.
    """
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in allowed)


def _origin_ok(request: Request) -> bool:
    """Reject a cross-site mutating request.

    `await request.json()` parses a body regardless of its Content-Type, so a plain
    `text/plain` form POST from any page on the internet reaches /kill and /feedback with a
    JSON body and no preflight. Today those routes are un-CSRF-able only because there is no
    ambient credential to ride; a session cookie creates one, so the check has to arrive in the
    same change that creates the cookie.

    `SameSite=Lax` already stops most of this. This is the belt to its braces, and it is ten
    lines. A request with neither header (a curl, an MCP tool, a server-to-server call) is
    allowed: those carry no cookie to abuse.
    """
    site = request.headers.get("sec-fetch-site")
    if site in {"same-origin", "same-site", "none"}:
        return True
    if site == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    from urllib.parse import urlsplit
    return urlsplit(origin).netloc == host


def _actor(request: Request, body: dict) -> tuple[str, str | None]:
    """Who is taking this action: `(display_name, verified_subject)`.

    When identity is configured the body's `actor` field is **ignored entirely** rather than
    used as a fallback. A fallback would mean a request that omits the cookie but supplies a
    name still records a name, which is the whole defect this replaces: the old check was only
    `if not actor: 400`, i.e. "is a non-empty string present". A verified principal strictly
    strengthens that, and only if the typed value cannot sneak back in.

    With identity off, behaviour is exactly as before: the typed name, unverified, and a None
    subject — which is what every historical ledger row already carries.
    """
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return (principal.display, principal.subject)
    from fls.identity import active_kind
    if active_kind() != "none":
        return ("", None)          # identity is on and the guard admitted nobody: no actor
    return ((body.get("actor") or "").strip(), None)


def _principal_for(request: Request):
    """The verified operator behind this request, or None.

    Two shapes, because the kinds genuinely differ. A redirect kind (`oidc`, `github-oauth`)
    signs in once and carries a session cookie. A kind with `browser_leg = False`
    (`proxy-header`) has no sign-in to perform — the proxy in front already did it and every
    request carries the proof — so it is authenticated per-request and mints no cookie at all.
    Without this second path that kind could never authenticate anybody: `begin()` raises,
    `/auth/login` 503s, and the guard denies every request forever.
    """
    from fls.identity import OPERATOR_AUDIENCE, SignedSession, resolve
    provider = resolve()
    if not getattr(provider, "browser_leg", True):
        return provider.complete(
            {"_headers": dict(request.headers),
             "_peer": request.client.host if request.client else ""},
            redirect_uri="", nonce="")
    principal = SignedSession.from_env().verify(request.cookies.get(SESSION_COOKIE, ""))
    if principal is None or principal.audience != OPERATOR_AUDIENCE:
        return None
    return principal


@app.middleware("http")
async def operator_guard(request: Request, call_next):
    """401 unless the caller carries a valid operator session. Reads are gated too."""
    from fastapi.responses import JSONResponse

    from fls.identity import active_kind

    if active_kind() == "none":
        return await call_next(request)
    # Preflight must never be answered with a 401 — the browser reads the CORS headers off the
    # OPTIONS response, and a 401 there surfaces as an opaque CORS error that hides the real one.
    if request.method == "OPTIONS":
        return await call_next(request)
    # The cross-site check runs BEFORE the public/protected split, because some public routes
    # are mutating and cookie-bearing: /auth/logout is the plain case, and forcing a sign-out
    # from any page on the internet is both a nuisance and a step in a login-CSRF chain.
    if request.method in _MUTATING and not _origin_ok(request):
        return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
    path = request.url.path
    if not _is_public(path, public_paths()):
        principal = _principal_for(request)
        if principal is None:
            return JSONResponse({"detail": "sign in required"}, status_code=401)
        if not identity_policy().permits(principal):
            return JSONResponse({"detail": "not authorised for this instance"}, status_code=403)
        request.state.principal = principal
    return await call_next(request)


# CORS: explicit allowlist from env (FLS_CORS_ORIGINS, comma-separated) + local dev — never a
# wildcard. Same-origin /api deployments (deploy.example) need no CORS at all.
#
# ⚠️ ORDER IS LOAD-BEARING. `add_middleware` PREPENDS, so the middleware added last runs
# OUTERMOST. CORS is registered below the guard precisely so it wraps it: a 401 from the guard
# must carry CORS headers, or the browser reports an opaque CORS failure instead and the admin's
# 401 handling never fires. Moving this block above the guard silently breaks the login screen
# on any cross-origin deploy — `test_401_response_carries_cors_headers` is what catches it.

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_origins = [o.strip() for o in os.environ.get("FLS_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins + ["http://localhost:8792"],
    allow_methods=["GET", "POST"], allow_headers=["content-type"],
    # The admin fetches with `credentials: 'include'` — it has to, the session lives in a cookie.
    # A browser DISCARDS any cross-origin response whose CORS headers omit this, so without it
    # every call fails and the admin falls back to fixtures while the server logs 200s. The
    # harness itself is same-origin (/api), so CORS never applies there and this stayed invisible;
    # it bites any cross-origin deploy and every `VITE_FLS_API=` dev session. Safe here only
    # because `allow_origins` is an explicit allowlist — Starlette refuses to pair credentials
    # with a wildcard, which is the rule this setup already followed.
    allow_credentials=True,
)


@app.on_event("startup")
def _prod_init() -> None:
    """Prod wiring: give the harness a real adjudicator when the Azure key is present.
    Without one, admission fails closed (needs-human) — never a silent admit.

    V6: the adjudicator is now selected via ANCHOR `adjudicator.kind` (make_adjudicator).
    Default kind=single-llm resolves to the same AzureJudge(gpt-5.4-nano) as before this
    field existed; kind=council is opt-in per ANCHOR. If the ANCHOR can't be read at startup,
    fall back to the historical hardcoded single judge rather than fail to boot."""
    if deps.judge is None and os.environ.get("AZURE_OPENAI_KEY"):
        from fls.adjudicator import make_adjudicator
        try:
            anchor = _anchor()
            deps.judge = make_adjudicator(anchor)
            log.info(f"adjudicator: kind={anchor.adjudicator.kind} model={anchor.adjudicator.model}")
        except Exception as e:  # noqa: BLE001 - fail open to the known-good default, never refuse to boot
            from fls.llm import AzureJudge
            deps.judge = AzureJudge("gpt-5.4-nano")
            log.warning(f"adjudicator: ANCHOR unreadable ({e}), falling back to AzureJudge(gpt-5.4-nano)")
    # FLS_MODULES extension hook — importlib-import each declared module (fail-closed: an
    # unknown path RAISES here, so the process refuses to start rather than run half-wired).
    from fls.modules import load_modules
    load_modules()
    # Same fail-closed treatment, same reason: a half-wired auth setup should refuse to start
    # rather than present as a console nobody can sign into for no visible reason.
    from fls.identity import validate_kind
    validate_kind()


def _anchor() -> Anchor:
    return Anchor.load(ANCHOR_PATH)


@app.get("/health")
def health() -> dict:
    a = _anchor()
    return {"status": "ok", "anchor_version": a.version, "mode": a.mode}


def _system_card(a: Anchor) -> dict:
    """The /system payload (kinds + booleans only — never secret values). Shared by /system and
    /snapshot so the two can never drift (test_snapshot_is_the_union_admin_loadall_composites)."""
    from fls.modules import contradictions, describe
    from fls.orchestration import client as orch
    from fls.profile import active_profile
    slots = describe(a)
    return {"anchor_version": a.version, "app": slots["auth"]["kind"] == "github-app",
            "slots": slots,
            # The cross-seam read `describe` cannot make: it reflects each seam in ISOLATION,
            # which is how an instance with a token, a vessel checkout and no FLS_REPO renders as
            # a calm LOCAL DEFAULT. Empty on a coherent instance — the common case.
            "contradictions": contradictions(slots),
            # harness PoC: which ladder runs, and whether a durable workflow engine sequences it
            # (`temporal` = FLS_ORCHESTRATION=temporal set in the instance env).
            "profile": active_profile().name,
            "orchestration": {"kind": "temporal" if orch.enabled() else "in-process",
                              "enabled": orch.enabled()}}


@app.get("/v1/operator/system")
def system() -> dict:
    """Reflect the nine module seams as booleans + kinds + docs links — the admin's Modules
    cards consume this. Read-only, fast, no network probes, no secrets.

    `app` is a top-level convenience boolean (V9-P1): whether the GitHub App auth path is
    active (`slots.auth.kind == "github-app"`). A fresh install with no App configured reports
    `app: false` — that's local-mode, the default, not an error."""
    return _system_card(_anchor())


def _anchor_card(a: Anchor) -> dict:
    """The /anchor payload. Shared by /anchor and /snapshot so the two can never drift —
    `test_snapshot_is_the_union_admin_loadall_composites` asserts they are identical, and it
    caught exactly that drift when the feeder block was added to one of them.
    (The same reason `_system_card` exists for /system.)"""
    # version + vessels are additive (V3-B2): the admin Constitution/Vessels screens read them.
    # North-star prose + non-negotiables stay in ANCHOR.md's human header; GET /snapshot (V4)
    # is where that prose (+ the resolved goal) is surfaced — this route stays machine-only.
    return {"version": a.version, "mode": a.mode, "funnel": a.funnel.__dict__,
            "altitude_allowed": a.altitude_allowed,
            "budgets": a.budgets.__dict__,
            "vessels": [v.model_dump() for v in a.vessels],
            "default_vessel": a.default_vessel,
            # The feeder's ANCHOR knobs. The admin's Feeder screen used to HARDCODE these while
            # telling the operator "all from the ANCHOR's feeder block" — so an instance that
            # tuned its feeder was shown someone else's defaults. Params only, never a secret:
            # the same rule the rest of this payload follows.
            # `declared` is the difference between "this is what your feeder is set to" and
            # "no feeder is declared, so these are library defaults". Without it a screen showing
            # the block would repeat the exact sin this field was added to fix — stating
            # provenance it cannot back.
            # `params_set` is the finer cut `declared` cannot make: an ANCHOR may declare the
            # feeder source and carry no `params:`, in which case every value below is still a
            # library default. A screen that reads `declared` alone would caption those "from
            # your ANCHOR" — true of the source, false of the numbers, and the numbers are what
            # the operator is reading.
            # The rung dials and the demote trigger: policy, not secrets, and the two facts the
            # Autonomy screen is ABOUT. It read neither — the dial an operator is deciding whether
            # to loosen was not in any payload, and the trigger that tightens it rendered as "—"
            # on the console that claims to edit it.
            "rungs": {k: v.model_dump() for k, v in a.rungs.items()},
            "autonomy_demote": a.autonomy_demote.model_dump(),
            "feeder": {**a.feeder().model_dump(),
                       "declared": any(src.get("kind") == "feeder" for src in a.idea_sources),
                       "params_set": any(src.get("kind") == "feeder" and src.get("params")
                                         for src in a.idea_sources)}}


@app.get("/v1/operator/anchor")
def anchor() -> dict:
    return _anchor_card(_anchor())


def _rung_index(rung) -> int:
    """A rung as its number, whether it arrives as 3, "3", or "3-demo"."""
    head = str(rung if rung is not None else 0).split("-", 1)[0]
    return int(head) if head.isdigit() else 0


def _with_step(rec: dict) -> dict:
    """The record plus when its current step began and how long it is allowed to run.

    The LIMIT is the ANCHOR's own per-rung wall clock — a real bound this instance enforces, not
    an estimate of how long things usually take. Shown as "stops at" rather than "takes about",
    because a cap is a promise the system keeps and an average is a guess it cannot.
    """
    if not rec:
        return rec
    out = dict(rec)
    # The store keeps the rung as a LABEL ("3-demo"); the worker writes step.json with the rung as
    # an INT (3). Comparing them directly is never true, so the clock this file exists to expose
    # was never once shown — the visitor got a stop-limit bar with nothing counting beside it.
    # Both sides are normalized to the index they both mean.
    idx = _rung_index(rec.get("rung", 0))
    p = deps.root / "expeditions" / str(rec.get("number")) / "step.json"
    if p.exists():
        try:
            step = json.loads(p.read_text(encoding="utf-8"))
            if _rung_index(step.get("rung")) == idx:
                out["step_started_at"] = step.get("started_at")
        except json.JSONDecodeError:
            pass
    try:
        out["step_limit_s"] = _anchor().worker.caps(idx).wall_clock_s
    except Exception:  # noqa: BLE001 — no declared cap simply means none is shown
        pass
    return out


def _with_attachment(rec: dict) -> dict:
    """The store record plus the attachment the requester put on it, when there is one."""
    if not rec:
        return rec
    p = deps.root / "expeditions" / str(rec.get("number")) / "attachment.json"
    if not p.exists():
        return rec
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return rec
    return {**rec, "attachment": {
        "label": meta.get("label"), "type": meta.get("type"), "bytes": meta.get("bytes"),
        "read_by_gate": meta.get("read_by_gate", False),
        "url": f"/demo/expeditions/{rec.get('number')}/attachment",
    }}


def _local_artifact_facts(number: int) -> dict:
    """Facts the FILESYSTEM can answer without asking the durable run: is there a prototype to
    preview, and is there a diff to read. Both are written to disk by the rungs that make them,
    so they stay true even for an expedition whose workflow history has expired."""
    d = deps.root / "expeditions" / str(number)
    out: dict = {}
    if (d / "demo" / "index.html").exists():
        out["preview"] = True
    if (d / "mvp" / "diff.patch").exists():
        out["diff"] = True
    return out


@app.get("/v1/operator/snapshot")
def snapshot() -> dict:
    """V4 — a single plain server-side read-union of the same data the admin composites
    client-side today (admin/src/api.js loadAll() fans out /wall + /calibration + /lessons +
    /anchor + /system). NO RAG shaping here, just a union of existing reads, plus the two
    slices that were previously unexposed: `prose` (the north-star/non-negotiables human
    header — closes the NORTH_STAR duplication app.py's /anchor docstring earmarks) and
    `goal` (V4 additive; resolved via the default vessel, falling back to the anchor-level
    goal). Reuses existing accessors only — no new reads, no secrets."""
    a = _anchor()
    anchor_text = ANCHOR_PATH.read_text()
    led = deps.store.ledger()
    rpt = build_report(led, a)
    # Each row carries what it PRODUCED. The Wall inferred `demo` and `PR` chips from the rung
    # index (`demo: i>=3, pr: i>=4`), so four expeditions claimed a pull request and exactly one
    # had opened it. A row may show what a run produced and nothing else — which means facts.
    wall = []
    for row in deps.store.wall():
        n = row.get("number")
        merged = {**deps.store.artifact_facts(n), **_local_artifact_facts(n)}
        wall.append({**row, "artifacts": merged} if merged else row)
    return {
        "wall": wall,
        "lessons": deps.store.lessons(),
        "calibration": {
            "rungs": [c.__dict__ for c in rpt.rungs],
            "total_decisions": rpt.total_decisions,
            "total_cost": rpt.total_cost,
            "disagreement_categories": category_slice(led),
        },
        "anchor": _anchor_card(a),
        "system": _system_card(a),
        "prose": guardrails_prose(anchor_text),
        "goal": a.resolved_goal(),
    }


@app.get("/v1/operator/runs")
def wall() -> list[dict]:
    return deps.store.wall()


@app.get("/v1/operator/runs/{number}")
async def expedition(number: int) -> dict:
    e = deps.store.get(number)
    if e is None:
        raise HTTPException(404, f"no expedition {number}")
    out = {**e, "artifacts": deps.store.artifacts(number)}
    from fls.orchestration import client as orch
    if orch.enabled():
        try:
            st = await orch.status(number)
        except Exception as ex:  # Temporal down: say so, never pretend
            st = None
            out["orchestration_error"] = str(ex)[:200]
        out["workflow"] = st
    # What happened to this run, in order. The screens an operator opens when something has gone
    # wrong used to have exactly one source — a status string that says where the run is, never
    # how it got there.
    out["events"] = deps.store.events(number)
    # WHY it stopped, and whether the button that fixes that would work — answered here rather
    # than found out by pressing it. `workflow` was already fetched above, so this costs nothing.
    out["cause"] = deps.store.cause(number)
    why = retry_refusal(number, e, out.get("workflow"),
                        float(_anchor().budgets.per_expedition_ceiling_usd or 0.0))
    out["retry"] = {"allowed": not why, "because": why}
    return out


@app.post("/v1/operator/runs/{number}/retry")
async def expedition_retry(number: int, request: Request) -> dict:
    """Operator door for retrying a stopped run. Same helper as the visitor's `/retry`, so the two
    cannot drift into different rules about when a retry is allowed."""
    actor, subject = _actor(request, await request.json())
    if not actor:
        raise HTTPException(400, "retry requires a named actor (gate is non-bypassable)")
    return await _retry_run(number, subject or actor)


@app.get("/v1/operator/calibration")
def calibration() -> dict:
    a, led = _anchor(), deps.store.ledger()
    rpt = build_report(led, a)
    return {
        "rungs": [c.__dict__ for c in rpt.rungs],
        "total_decisions": rpt.total_decisions,
        "total_cost": rpt.total_cost,
        "disagreement_categories": category_slice(led),
    }


@app.get("/v1/operator/lessons")
def lessons() -> list[str]:
    return deps.store.lessons()


@app.get("/v1/operator/mining-history")
def mining_history(vessel: str | None = None) -> list[dict]:
    """Append-only judge-calibration mining snapshots (v0.6 #7) for the earning-history lens.

    v0.7: this read path now DRIVES the persistence cadence — `mine_if_due` mines+appends a
    fresh anchor-level snapshot when the last one is stale (default: once/day guard in
    mining.py; a no-op most calls), so `mining-history.jsonl` actually accrues an earned track
    record instead of only ever being read. Empty history still falls back to one fresh
    (unpersisted) snapshot.

    v0.7 #3: `?vessel=<Vessel.name>` returns a single LIVE snapshot sliced to that vessel's
    ledger rows instead of the persisted anchor-level history (per-vessel snapshots aren't
    accrued to the shared history file, to avoid polluting the anchor-level drift_trend) — the
    admin's EarningHistory renders this as a one-point trail; omitting `vessel` is unchanged,
    back-compat anchor-level behavior."""
    from fls.mining import default_history_path, mine, mine_if_due, read_history

    # v0.7 fix: resolve alongside ledger.jsonl (deps.root — the store's instance root), not the
    # process cwd — the pre-v0.7 read-only call site never wrote a file so the cwd-relative
    # default was latent; now that this path DRIVES persistence it must be instance-rooted (the
    # `FLS_MINING_HISTORY_PATH` env override still takes precedence, per default_history_path).
    path = default_history_path(deps.root)
    if vessel:
        return [mine(deps.store.ledger(), _anchor(), vessel=vessel).to_dict()]
    mine_if_due(deps.store.ledger(), _anchor(), path)
    hist = read_history(path)
    if not hist:
        hist = [mine(deps.store.ledger(), _anchor())]
    return [r.to_dict() for r in hist]


@app.post("/v1/operator/panels/propose")
async def panels_propose(request: Request) -> dict:
    """Validate a proposed panel-authoring edit (v0.6 #5) and return the reviewable change —
    proposal-only (the 'edits are PRs' protocol; never auto-applies to ANCHOR). A panel is a
    registry name (str) or an explicit persona-id list; it binds to a vessel via a lenses
    LensParams entry."""
    body = await request.json()
    panel = body.get("panel")
    target_vessel = body.get("target_vessel")
    errors: list[str] = []
    if isinstance(panel, str):
        if not panel.strip():
            errors.append("panel name must be non-empty")
    elif isinstance(panel, list):
        if not panel or not all(isinstance(p, str) and p.strip() for p in panel):
            errors.append("panel list must be a non-empty list of persona-id strings")
        elif len(set(panel)) != len(panel):
            errors.append("panel list has duplicate persona ids")
    else:
        errors.append("panel must be a registry name (string) or a persona-id list")
    if target_vessel is not None and not isinstance(target_vessel, str):
        errors.append("target_vessel must be a string or omitted")
    valid = not errors
    return {
        "valid": valid,
        "errors": errors,
        "proposed_change": {"panel": panel, "target_vessel": target_vessel} if valid else None,
        "note": "proposal-only — apply via an ANCHOR lenses PR (panel + target_vessel live in a LensParams entry)",
    }


@app.get("/v1/public/runs/{number}/preview")
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


@app.post("/v1/operator/requests")
async def file_idea(request: Request) -> dict:
    """File an idea -> run admission (needs deps.judge). Returns the verdict + reasoning."""
    body = await request.json()
    return await admit_idea(Idea(
        number=int(body["number"]), intent=body["intent"], success=body.get("success", ""),
        altitude=body.get("altitude", "feature"), source=body.get("source", "manual")))


def _next_expedition_number() -> int:
    """The next free expedition number. Same rule the demo door uses — one source, not two."""
    return max((e.get("number", 0) for e in deps.store.wall()), default=0) + 1


async def admit_idea(idea: Idea, grounding: str = "") -> dict:
    """Admission for one idea, whatever filed it.

    A plain function rather than a handler so the demo surface can file through exactly this path
    instead of re-dispatching a hand-mutated Request — which is as fragile as it sounds.
    """
    if deps.judge is None:
        raise HTTPException(503, "no judge configured")
    # `grounding` carries a text attachment's content, so "the details are in the file" is a
    # thing the gate can actually act on rather than a sentence it cannot check.
    verdict, reason = on_idea(idea, _anchor(), ANCHOR_PATH.read_text(), deps.judge,
                              deps.store.ledger(), grounding=grounding)
    # persist the expedition so the wall shows it (same mapping the webhook path uses)
    from fls.anchor import Verdict
    from fls.expedition import CLIMBING, DOCKED, NEEDS_HUMAN, Expedition
    status = (CLIMBING if verdict == Verdict.admit
              else DOCKED if verdict == Verdict.dock else NEEDS_HUMAN)
    deps.store.save(Expedition(idea.number, idea, 2 if verdict == Verdict.admit else 0,
                               status=status, reason=None if verdict == Verdict.admit else reason))
    out = {"number": idea.number, "verdict": verdict.value, "reason": reason}
    from fls.orchestration import client as orch
    if verdict == Verdict.admit and orch.enabled():
        # harness PoC: an admitted idea becomes ONE durable workflow (id exp-{n}); the worker
        # climbs it and the human protocol reaches it as signals. Failure to start is reported,
        # never hidden — the expedition stays saved as CLIMBING for a retry.
        from fls.orchestration.types import ExpeditionInput, WorkflowConfig
        a = _anchor()
        # Carry the ANCHOR's money ceiling into the run. `start()` was called with no cfg at all,
        # so the workflow climbed on dataclass defaults and never knew what this instance had
        # declared it was allowed to spend.
        cfg = WorkflowConfig(ceiling_usd=float(a.budgets.per_expedition_ceiling_usd or 0.0))
        try:
            out["workflow_id"] = await orch.start(ExpeditionInput(
                number=idea.number, intent=idea.intent, success=idea.success,
                altitude=idea.altitude, source=idea.source), cfg=cfg)
        except Exception as ex:
            out["workflow_error"] = str(ex)[:200]
    return out


async def _park_expedition(number: int, actor: str, subject: str | None, reason: str) -> dict:
    """Stop one expedition: record who stopped it, then tell the run to stop climbing.

    Extracted so that stopping never depends on a notification succeeding. The comment protocol
    (`/kill` in an issue) and the workflow signal are both ways of ASKING a run to stop; this is
    the state change itself, and an expedition with neither an issue nor a workflow behind it —
    one the admission gate declined, say — must still be stoppable. It was not: the demo's Stop
    button posted `/kill` into the feedback path, which had nowhere to send it.

    THE SIGNAL IS THE OTHER HALF, and it was missing. This function marked the store `parked`
    and stopped there, so Stop changed a label on a screen while the run went on climbing and
    went on spending — the money the button exists to stop. Worse, the workflow mirrors its own
    state as it climbs, so the next rung transition wrote `climbing` back over the park and the
    button appeared to have done nothing at all.

    Order is deliberate: the STORE first, because it is the durable record of a human decision
    and must survive a scheduler that is down; the SIGNAL second, because it is the part that
    can fail. When it fails it is SAID (`signalled: false` with the reason) rather than swallowed
    — a Stop that did not reach the run is exactly the kind of thing this system refuses to
    report as success.

    What "stopped" means in time: the workflow honours a kill at its next gate, so a rung already
    in flight finishes first. That is the same line the budget ceiling holds — a rung is the unit
    of work, and abandoning one halfway leaves a worktree and a half-written artifact behind for
    nothing. The overshoot is bounded by one rung, and the surface says so rather than promising
    an instant stop it cannot deliver.
    """
    rec = deps.store.get(number)
    if rec is None:
        raise HTTPException(404, f"no expedition {number}")
    from fls.expedition import PARKED
    from fls.github_surface import _rehydrate
    from fls.ledger import Decision
    from fls.store import RUNG_NAMES
    rung = RUNG_NAMES.index(rec["rung"]) if rec["rung"] in RUNG_NAMES else 0
    e = _rehydrate(rec, rung, PARKED)
    e.reason = f"killed by {actor}: {reason or 'no reason given'}"
    e.parked_by = "human"
    deps.store.save(e)
    import time as _t
    deps.store.ledger().record(Decision(number, rec["rung"], "kill", "kill", 0.0,
                                        human_responded_at=_t.time(), actor=subject))
    out = {"number": number, "status": "parked", "by": actor, "signalled": False}
    from fls.orchestration import client as orch
    if not orch.enabled():
        # No scheduler wired: there is no run to signal, and the store IS the whole state. Said
        # plainly so that `signalled: false` never has to be read as a failure.
        out["signal_detail"] = "no durable run behind this expedition; the record is the whole of it"
        return out
    try:
        await orch.signal(number, "kill", reason or f"stopped by {actor}")
        out["signalled"] = True
    except Exception as ex:  # noqa: BLE001 — the reason travels to the caller, never to a log alone
        out["signal_detail"] = str(ex)[:200]
    return out


@app.post("/v1/operator/runs/{number}/kill")
async def kill_expedition(number: int, request: Request) -> dict:
    """The kill switch — parks an expedition. Fail-closed: requires an actor; the kill lands in
    the ledger under them."""
    body = await request.json()
    actor, subject = _actor(request, body)
    if not actor:
        raise HTTPException(400, "kill requires a named actor (gate is non-bypassable)")
    return await _park_expedition(number, actor, subject, body.get("reason") or "")


@app.get("/v1/operator/runs/{number}/thread")
async def expedition_thread(number: int) -> dict:
    """Mirror the expedition's GitHub issue thread into the admin — issues ARE expeditions,
    so the conversation lives there; the admin is a lens on it. Honest degradation: no
    outbound token or no linked issue -> available: false with the reason, never a pretend.

    Also answers WHERE A DECISION ON THIS EXPEDITION WOULD LAND, as `route`:

        issue     a comment on the linked GitHub issue; the signed webhook enacts commands
        workflow  a signal straight to the durable run
        none      nowhere — and the buttons must say so instead of being drawn live

    The screen had the first fact and not this one, so it printed "no linked GitHub issue for
    this expedition" directly beneath a sentence promising that feedback goes onto the issue,
    with Advance enabled between them. `route` is computed from the SAME two questions
    `_post_feedback` asks, in the same order, so the screen cannot describe a path the engine
    would not take.
    """
    if deps.store.get(number) is None:
        raise HTTPException(404, f"no expedition {number}")
    from fls.orchestration import client as orch
    route = "workflow" if (orch.enabled() and await orch.status(number)) else None
    client = _github()
    if client is None:
        # Name the missing half. "no token" when a repo is configured but a token is not is
        # actively misleading, and this instance deliberately runs with a token and no repo.
        from fls.github_surface import REPO
        missing = []
        if not os.environ.get("GITHUB_TOKEN"):
            missing.append("no outbound token (GITHUB_TOKEN)")
        if not REPO:
            missing.append("no linked repository (FLS_REPO)")
        return {"available": False, "route": route or "none",
                "reason": " and ".join(missing) + " — fail-closed" if missing
                else "GitHub surface unavailable",
                "comments": []}
    try:
        issue = client.get_issue(number)
    except Exception:  # noqa: BLE001 — e.g. admin/MCP-filed expedition with no issue
        return {"available": False, "route": route or "none",
                "reason": "no linked GitHub issue for this expedition", "comments": []}
    # The SAME collision the write path has, in the read direction. GitHub numbers issues and
    # pull requests from one sequence while expedition numbers are minted locally, so #N may be
    # somebody's PR — and this would then have shown that PR's title, URL and whole conversation
    # as "this expedition's issue thread". Mirroring a stranger's discussion into a governance
    # screen is its own falsehood, separate from acting on it.
    #
    # Checked BEFORE the comments are fetched, so an unrelated conversation is never even
    # requested, let alone dropped afterwards.
    if "pull_request" in (issue or {}):
        return {"available": False, "route": route or "none",
                "reason": f"#{number} in this repo is a pull request, not this expedition's "
                          "issue — expedition numbers are local and collide with the repo's",
                "comments": []}
    try:
        comments = client.list_comments(number)
    except Exception:  # noqa: BLE001 — the issue exists; its comments are a nice-to-have
        comments = []
    return {"available": True, "route": route or "issue",
            "url": issue.get("html_url"), "title": issue.get("title"),
            "comments": [{"author": c.get("user", {}).get("login", "?"),
                          "body": c.get("body", ""), "at": c.get("created_at", "")}
                         for c in comments]}


# ── operator sign-in ────────────────────────────────────────────────────────────────────────
# Four routes and two cookies. The cookie flags are the security here, so each one is spelled
# out where it is set rather than hidden in a helper.

SESSION_COOKIE = "fls_session"
STATE_COOKIE = "fls_auth_nonce"


def identity_policy():
    """Read at call time — `monkeypatch.setenv` in the suite depends on it, and so does an
    operator who edits instance.env and restarts one worker at a time."""
    from fls.identity import Policy
    return Policy.from_env()


def _set_session_cookie(response, token: str) -> None:
    from fls.identity import SignedSession, cookie_secure
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SignedSession.from_env().ttl_s,
        httponly=True,           # a session no script can read is a session no XSS can steal
        samesite="lax",          # NOT strict: strict withholds the cookie on the top-level
                                 # cross-site navigation that IS the provider's 302 back here,
                                 # so the callback would never see its own session
        secure=cookie_secure(),
        path="/",                # explicit: Caddy's `handle_path /api/*` strips the prefix, so
                                 # a path derived from request.url.path yields "/auth" and the
                                 # cookie is never sent back for /wall
    )


@app.get("/auth/login")
async def auth_login(request: Request):
    """Start the sign-in. Mints the nonce cookie + signed state, then redirects to the provider."""
    import secrets

    from fastapi.responses import RedirectResponse

    from fls.identity import (
        StateSigner,
        active_kind,
        cookie_secure,
        redirect_uri,
        resolve,
        safe_return_to,
    )
    if active_kind() == "none":
        raise HTTPException(404, "no identity provider is configured")
    signer = StateSigner.from_env()
    if not signer.configured:
        raise HTTPException(503, "FLS_SESSION_SECRET is not set — sign-in is disabled")
    uri = redirect_uri()
    if not uri:
        raise HTTPException(503, "FLS_AUTH_REDIRECT_URI is not set — sign-in is disabled")
    nonce = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    return_to = safe_return_to(request.query_params.get("return_to"))
    state = signer.mint(nonce=nonce, return_to=return_to)
    try:
        challenge = resolve().begin(redirect_uri=uri, state=state, nonce=nonce,
                                    verifier=verifier)
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e
    resp = RedirectResponse(challenge.redirect_url, status_code=302)
    # nonce AND verifier, on our own origin, HttpOnly. The verifier must never travel through
    # the provider — `state` is signed but not encrypted, so putting it there would hand away
    # the one secret PKCE exists to keep while still looking enabled.
    resp.set_cookie(STATE_COOKIE, f"{nonce}.{verifier}", max_age=600, httponly=True,
                    samesite="lax", secure=cookie_secure(), path="/")
    return resp


def _auth_error(reason: str):
    """Every sign-in failure ends the same way: back at the console with a message.

    Never a JSON body. This URL is followed by things that are not the user — reputation
    crawlers, link scanners, previewers — and none of them carry the nonce cookie, so an error
    is all they can ever get. Handing them a machine-shaped response while a human gets a page
    is cloaking-shaped, and that is a phishing signal we were generating ourselves.
    """
    from urllib.parse import quote

    from fastapi.responses import RedirectResponse
    admin = (os.environ.get("FLS_ADMIN_URL") or "/app/").rstrip("/") + "/"
    resp = RedirectResponse(f"{admin}?auth_error={quote(reason)}", status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Finish the sign-in. Both CSRF halves are checked before anything else happens."""
    from fastapi.responses import RedirectResponse

    from fls.identity import (
        OPERATOR_AUDIENCE,
        SignedSession,
        StateSigner,
        active_kind,
        redirect_uri,
        resolve,
        safe_return_to,
    )
    if active_kind() == "none":
        raise HTTPException(404, "no identity provider is configured")
    state = request.query_params.get("state", "")
    claims = StateSigner.from_env().verify(state)
    cookie_nonce, _, cookie_verifier = request.cookies.get(STATE_COOKIE, "").partition(".")
    if claims is None or not cookie_nonce or claims.get("nonce") != cookie_nonce:
        # One outcome for a forged state, a replayed state, a missing cookie and an expired one.
        # The caller learns that it failed, not which check caught them.
        #
        # An HTML redirect rather than a JSON 400, and the reason is not cosmetic. A URL-
        # reputation crawler that follows this link has no nonce cookie, so it lands here every
        # time — and what it used to get was a bare JSON error body at a URL reached from
        # github.com. Serving a crawler something different from what the user sees is the
        # definition of cloaking, which is a phishing signal, so our own CSRF defence was
        # feeding the classifier that flagged us. Now everyone gets the same ordinary page.
        return _auth_error("could not verify")
    params = dict(request.query_params)
    params["_headers"] = {k: v for k, v in request.headers.items()}
    params["_peer"] = request.client.host if request.client else ""
    principal = resolve().complete(params, redirect_uri=redirect_uri(),
                                  nonce=claims["nonce"], verifier=cookie_verifier)
    if principal is None:
        return _auth_error("not confirmed")
    if principal.audience != OPERATOR_AUDIENCE or not identity_policy().permits(principal):
        # Authenticated, and still refused. The provider says who you are; the allowlist says
        # who runs this instance, and a public OAuth app authenticates the whole internet.
        log.warning("identity: refused sign-in (not permitted by policy). To admit this "
                    "person add ONE of these to FLS_ALLOWED_USERS: %s",
                    identity_policy().candidates(principal))
        return _auth_error("not authorised")
    log.info("identity: sign-in subject=%s provider=%s", principal.subject, principal.provider)
    # Mint fresh. Never upgrade an existing cookie — session fixation is exactly the trick of
    # planting a session before the victim authenticates and inheriting it afterwards.
    token = SignedSession.from_env().mint(principal)
    resp = RedirectResponse(safe_return_to(claims.get("return_to")), status_code=302)
    _set_session_cookie(resp, token)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@app.post("/auth/logout")
async def auth_logout():
    from fastapi.responses import JSONResponse
    resp = JSONResponse({"signed_out": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/auth/me")
async def auth_me(request: Request) -> dict:
    """Who the caller is. The admin asks this on mount, and a 401 here is what renders the
    sign-in screen instead of a dashboard."""
    from fls.identity import active_kind
    kind = active_kind()
    if kind == "none":
        # An honest answer, not a fake session: this instance gates nobody, and the admin shows
        # an unauthenticated banner rather than pretending someone is signed in.
        return {"authenticated": False, "identity": "none",
                "note": "this instance has no operator identity configured"}
    principal = _principal_for(request)
    if principal is None:
        # The 401 carries the KIND. The sign-in screen renders precisely when this route
        # refuses, so without it the admin cannot label its own button and every instance shows
        # a generic "Sign in" regardless of provider. The kind is not a secret — /auth/login
        # redirects to a URL that names the provider outright.
        raise HTTPException(401, {"detail": "sign in required", "identity": kind})
    # The allowlist has to be applied HERE too, not only in the guard. /auth/me sits on the
    # public /auth/ prefix, so without this a de-allowlisted operator got `authenticated: true`
    # from this route and 403 from every other — and the admin, seeing a signed-in user, went
    # on to render its fixtures fallback as a real dashboard.
    if not identity_policy().permits(principal):
        raise HTTPException(403, "that account is not authorised for this instance")
    return {"authenticated": True, "identity": kind, "principal": principal.public()}


# ── the demo surface ────────────────────────────────────────────────────────────────────────
# The ladder as a visitor sees it: no rung numbers, no dials, one expedition at a time. The
# translation lives in `fls.demo`, so the machinery cannot leak into the view by accident.

def _demo_auth():
    from fls.demo import DemoAuth
    return DemoAuth.from_env()


def _demo_actor(request: Request) -> str:
    """The signed-in visitor's name, or "" — every demo action records it in the ledger, so a
    demo still says WHO approved rather than "someone"."""
    token = request.headers.get("x-demo-token", "")
    return _demo_auth().verify(token)


async def _demo_in_flight():
    """The one demo run actually in flight, and its workflow — or (None, None).

    The single source of truth for "is the surface busy". Two rules, and both were learned by
    deploying it:

    * **Only runs filed through the demo.** An operator's expedition is not a visitor's business,
      and letting one count as in-flight wedges the request box behind work the visitor cannot act
      on.
    * **The workflow decides, not the record.** A run can sit recorded as "awaiting sign-off" long
      after its workflow finished; believing the record offers three buttons that all fail.
    """
    from fls.demo import is_active
    from fls.orchestration import client as orch
    candidates = sorted(
        (e for e in deps.store.wall()
         if is_active(e.get("status", "")) and str(e.get("source", "")).startswith("demo")),
        key=lambda e: e.get("number", 0), reverse=True)
    for cand in candidates:
        if not orch.enabled():
            return cand, None
        try:
            return cand, await orch.status(cand["number"])
        except Exception:  # noqa: BLE001 — a closed or unknown workflow means this one is over
            continue
    return None, None


@app.post("/v1/visitor/login")
async def demo_login(request: Request) -> dict:
    """Name + the shared passcode. Fail-closed: with no passcode configured nobody gets in,
    because a public surface that authenticates nobody is an open door with a form drawn on it."""
    auth = _demo_auth()
    if not auth.configured:
        raise HTTPException(503, "the demo surface has no passcode configured")
    body = await request.json()
    name = (body.get("name") or "").strip()[:40]
    if not name:
        raise HTTPException(400, "a name is required — it is recorded against every decision")
    if not auth.check_passcode(body.get("passcode") or ""):
        raise HTTPException(401, "that passcode is not right")
    return {"name": name, "token": auth.mint(name)}


def _retry_refusal_for(rec: dict, wf: dict | None) -> str:
    """The visitor surface's copy of the retry question, asked with what it already has.

    Never raises: this decides whether to draw a button, and a page must not fail to render
    because the ANCHOR could not be read.
    """
    try:
        return retry_refusal(int(rec.get("number", 0)), rec, wf,
                             float(_anchor().budgets.per_expedition_ceiling_usd or 0.0))
    except Exception:  # noqa: BLE001
        return ""


def _suggestion(wall: list[dict]) -> dict | None:
    """The demo's next suggested request. Never raises: this is a public page, and an ANCHOR that
    cannot be read is a reason to suggest nothing, not to fail the whole surface."""
    try:
        from fls.demo import suggestion_for
        return suggestion_for(_anchor().demo.suggestions, wall)
    except Exception:  # noqa: BLE001
        return None


@app.get("/v1/public/runs/active")
async def demo_active() -> dict:
    """The one expedition in flight, in a visitor's words. `{"active": null}` when there is none —
    which is the signal the request box uses to offer a new one."""
    from fls.demo import demo_view, last_finished
    base = os.environ.get("FLS_PUBLIC_BASE", "")
    wall = deps.store.wall()
    # SOMETHING TO TRY, for a visitor who has not thought of a change to an app they have never
    # used. Computed here rather than behind its own endpoint because this is the one thing the
    # page polls, so a suggestion taken by one visitor is gone from the next poll for everyone.
    suggested = _suggestion(wall)
    rec, wf = await _demo_in_flight()
    if rec is not None:
        view = demo_view(_with_step(_with_attachment(rec)), wf, deps.store.artifacts(rec["number"]),
                         preview_base=base, cause=deps.store.cause(rec["number"]),
                         retry_refusal=_retry_refusal_for(rec, wf))
        # A run whose workflow has ended is not in flight, whatever the record still says. It is
        # shown as the FINISHED one — with everything it did manage to make — and the request box
        # comes back. Blocking it would leave the visitor holding a screen that says "you can
        # start a new request" above a box that refuses to take one, which is how expedition 17
        # left the demo: not lying about the run any more, just stuck.
        if wf is not None and not wf.get("running", True):
            return {"active": None, "can_request": True, "finished": view,
                    "suggestion": suggested}
        return {"active": view, "can_request": False, "finished": None,
                "suggestion": suggested}
    # Nothing in flight — but "does not block a new request" and "is not worth showing" were one
    # flag, and the surface forgot the run the instant it ended. A visitor who watched five stages
    # went to the payoff and found the request box back, with no pull request, no staged build and
    # no sign that anything had happened. On a page called "Watch it build something", the moment
    # it finishes building is the one moment that matters.
    done = last_finished(wall)
    if done is None:
        return {"active": None, "can_request": True, "finished": None,
                "suggestion": suggested}
    # The run's OWN artifacts, not just the store's. The pull request lives in the workflow's bag
    # (`ship.pr_url`), so passing None here kept the payoff off the payoff screen — the finished
    # run rendered with a preview link and no sign of the thing it had actually opened. A
    # completed workflow still answers its status query from history; if it cannot, the store's
    # artifacts still render and the view degrades instead of failing.
    from fls.orchestration import client as orch
    wf_done = None
    if orch.enabled():
        try:
            wf_done = await orch.status(done["number"])
        except Exception:  # noqa: BLE001 — history expired or Temporal down; show what we have
            wf_done = None
    return {"active": None, "can_request": True, "suggestion": suggested,
            "finished": demo_view(_with_attachment(done), wf_done,
                                  deps.store.artifacts(done["number"]), preview_base=base,
                                  cause=deps.store.cause(done["number"]),
                                  retry_refusal=_retry_refusal_for(done, wf_done))}


@app.post("/v1/visitor/requests")
async def demo_file_idea(request: Request) -> dict:
    """File the one request. Refuses a second while one is in flight: a public queue against a
    live budget is not a demo, it is an invoice."""
    actor = _demo_actor(request)
    if not actor:
        raise HTTPException(401, "sign in first")
    # The SAME question the surface asked, asked the same way. When these two diverged the page
    # invited a request and then refused it.
    in_flight, wf = await _demo_in_flight()
    # A run whose WORKFLOW HAS ENDED does not block a new request, whatever the record still says.
    # The GET endpoint already knew this and showed such a run as finished with the box open; this
    # one did not, so the two asked the same question different ways — the exact divergence the
    # comment above warns about, back again.
    #
    # It surfaced when rung 1 learned to refuse. A refusal is `needs-human`, which is not terminal
    # for a good reason (a person really does have something to add) — so expedition 31 told
    # somebody to say what should change and then held the request box shut against them.
    if in_flight is not None and wf is not None and not wf.get("running", True):
        in_flight = None
    if in_flight is not None:
        raise HTTPException(409, f"request #{in_flight.get('number')} is still in flight — one at "
                                 "a time, so you can watch it happen")
    body = await request.json()
    intent = (body.get("intent") or "").strip()
    if not intent:
        raise HTTPException(400, "say what you would like built")
    number = max((e.get("number", 0) for e in deps.store.wall()), default=0) + 1

    # ONE optional attachment. Validated before anything is written, and the stored name is
    # derived from the TYPE rather than from what was uploaded — a filename off the internet is a
    # path-traversal and content-type problem, and a .html saved under our own origin would run as
    # our page.
    grounding = ""
    att = body.get("attachment") or None
    if att:
        import base64

        from fls.demo import ATTACH_TYPES, attachment_error, attachment_grounding
        name, mime = str(att.get("name", "")), str(att.get("type", ""))
        try:
            data = base64.b64decode(att.get("data", ""), validate=True)
        except Exception as ex:  # noqa: BLE001
            raise HTTPException(400, "that attachment could not be read") from ex
        if why := attachment_error(name, mime, len(data)):
            raise HTTPException(413 if len(data) > 0 and "limit is" in why else 415, why)
        d = deps.root / "expeditions" / str(number)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"attachment{ATTACH_TYPES[mime]}").write_bytes(data)
        (d / "attachment.json").write_text(json.dumps({
            "label": name[:120], "type": mime, "bytes": len(data),
            "stored": f"attachment{ATTACH_TYPES[mime]}",
            # Whether the GATE could read it, recorded rather than inferred later.
            "read_by_gate": bool(attachment_grounding(mime, data)),
        }, indent=2), encoding="utf-8")
        grounding = attachment_grounding(mime, data)

    return await admit_idea(Idea(
        number=number, intent=intent, success=body.get("success", ""),
        altitude=body.get("altitude", "feature"), source=f"demo:{actor}"), grounding=grounding)


@app.post("/v1/operator/runs/{number}/preview")
async def expedition_preview(number: int, request: Request) -> dict:
    """Where the rung-3 prototype can be looked at.

    `mode: "stage"` (the default) is the one that works today: the prototype already sits at the
    path `GET /preview/{number}` serves, because rung 3 writes it there. This endpoint exists to
    answer "is there one, and what is its URL" without a reviewer guessing at a path — and to
    refuse plainly when the rung has not produced one, rather than handing back a URL that 404s.

    `mode: "pr"` is declared in the plan and NOT implemented: opening a branch with the prototype
    in it needs GitHub branch and pull-request plumbing that arrives with the rung-4 build surface,
    along with the outbound token it requires. It refuses rather than pretending, on the same rule
    the live runner follows for a rung with no builder.
    """
    body = await request.json() if await request.body() else {}
    mode = (body.get("mode") or "stage").strip().lower()
    if deps.store.get(number) is None:
        raise HTTPException(404, f"no expedition {number}")
    if mode == "pr":
        raise HTTPException(501, "preview mode 'pr' is not implemented: it needs the GitHub "
                                 "branch/PR surface that lands with the build rung. Use 'stage'.")
    if mode != "stage":
        raise HTTPException(400, f"unknown preview mode {mode!r} (stage | pr)")
    demo = deps.root / "expeditions" / str(number) / "demo" / "index.html"
    if not demo.exists():
        raise HTTPException(409, f"expedition {number} has no prototype yet — rung 3 has not "
                                 "written one")
    return {"number": number, "mode": "stage", "url": f"/preview/{number}",
            "bytes": demo.stat().st_size}


# Which signals a run can actually ACT ON, by the state it is sitting in.
#
# The workflow's gate resets itself on entry (`g.approved, g.picked, g.feedback = False, None,
# None`) and then waits on exactly one of them depending on the rung. Every other signal sets a
# field the wait condition does not read, and is wiped by the next gate that opens. Temporal
# accepts it, the engine answers 200, a Decision lands in the ledger — and nothing moves.
#
# That is the "Advance does nothing" bug in its general form, and it has three faces: approve at
# a pick gate, pick at an approve gate, and anything at all while the run is mid-rung. Naming the
# rule once is the fix; special-casing the face that happened to be reported is not.
#
# `kill` is absent from the values because it is accepted everywhere: it sets `_killed`, which no
# gate resets, so it is the one signal that is never absorbed.
_SIGNALS_A_RUN_CAN_USE = {
    "await-pick": {"pick", "feedback"},
    "await-approve": {"approve", "feedback"},
    "await-signoff": {"approve", "feedback"},
    # Rung 1 asked what a word meant. Only an ANSWER moves it: `/pick` would write the wireframe
    # check-mark artifact (there are no wireframes yet) and `/approve` would approve nothing.
    "await-answer": {"feedback"},
}
_WHAT_IT_WANTS = {
    "await-pick": "one of its candidates to be PICKED",
    "await-approve": "your APPROVAL to carry on",
    "await-signoff": "your SIGN-OFF",
    "await-answer": "an ANSWER to the question it asked",
}


def _refuse_absorbed_signal(number: int, name: str, state: str) -> None:
    """Fail closed on a decision the run provably cannot act on.

    The alternative — send it anyway — is the worst possible shape: it succeeds, it is recorded,
    and it changes nothing. A ledger row for a decision that had no effect is worse than no row,
    because the whole claim this system makes is that the ledger shows it or it did not happen.
    """
    if name == "kill":
        return
    if name in _SIGNALS_A_RUN_CAN_USE.get(state, set()):
        return
    wants = _WHAT_IT_WANTS.get(state)
    because = (f"is waiting for {wants}" if wants
               else "is working and is not at a gate, so nothing is waiting to be decided")
    # 422, not 409. 409 on this surface means "there is nowhere to send this at all"; this is a
    # live run at an open gate being handed the wrong verb, and a visitor told the former about
    # the latter is told their request never started — while looking at its candidates.
    raise HTTPException(422, f"expedition {number} {because} — a '{name}' would be accepted and "
                             "then ignored, so it is refused instead (fail-closed)")


def retry_refusal(number: int, rec: dict, st: dict | None, ceiling: float) -> str:
    """Why a retry would be refused, in the sentence it would be refused with — or "".

    Split out of `_retry_run` so a surface can ask the question BEFORE offering the button.
    Both doors showed "try that step again" on every stopped run and discovered the four
    refusals only after the press, as an error toast — which teaches a visitor that the button
    is unreliable rather than that this particular run cannot be retried.

    The sentences are unchanged, because `demo._RETRY_ERRORS` matches on their words to
    translate them for a visitor.
    """
    status = rec.get("status")
    if status in ("done", "docked", "killed"):
        return f"expedition {number} is {status} — nothing to retry"
    if st is None:
        return f"expedition {number} has no run to retry"
    if st.get("running", False):
        return f"expedition {number} is still running — nothing to retry"
    spent = float(rec.get("normalized_usd") or 0.0)
    if ceiling and spent >= ceiling:
        return (f"expedition {number} has spent ${spent:.2f} of its ${ceiling:.2f} "
                "ceiling — retry refused (fail-closed)")
    return ""


async def _retry_run(number: int, actor: str) -> dict:
    """Try a stopped run again, from the step that stopped it.

    Its own path, not a signal, because the thing it acts on cannot receive signals: a failed
    workflow is closed, and every `approve`/`pick`/`kill` sent to one comes back 409. That is
    precisely the hole expedition 17 fell into — stopped, with no action on the page that could
    reach it, because every action the protocol had was a signal.

    Fail-closed, and the refusal always names which rule it hit. Four of them, each learned:
    a run still climbing is not stuck and must not be restarted underneath itself; a run with no
    workflow has nothing to rewind; a run past the ANCHOR's ceiling must not be handed more money
    by a button; and a run a human already finished or killed stays finished.
    """
    rec = deps.store.get(number)
    if rec is None:
        raise HTTPException(404, f"no expedition {number}")

    from fls.orchestration import client as orch
    if not orch.enabled():
        raise HTTPException(503, "no durable runs on this instance — retry refused (fail-closed)")
    st = await orch.status(number) if rec.get("status") not in ("done", "docked", "killed") else None
    if why := retry_refusal(number, rec, st, float(_anchor().budgets.per_expedition_ceiling_usd or 0.0)):
        raise HTTPException(409, why)
    try:
        run_id = await orch.rewind(number, reason=f"retry by {actor}")
    except Exception as ex:  # noqa: BLE001 — say what Temporal said, never a smoothed-over 500
        raise HTTPException(409, f"expedition {number} could not be retried: {str(ex)[:160]}") from ex
    deps.store.append_event(number, "retried", actor=actor, run_id=run_id)
    log.info("retry: expedition=%s actor=%s run_id=%s", number, actor, run_id)
    return {"retried": True, "number": number, "run_id": run_id}


async def _post_feedback(number: int, text: str, actor: str, subject: str | None) -> dict:
    """The one feedback path, shared by the operator door and the visitor door.

    Extracted rather than duplicated because the two doors differ ONLY in who is allowed through
    them and how sure we are of the name. The protocol itself — a command takes effect only when
    GitHub echoes the comment back through the signed webhook, or when the durable workflow
    accepts it as a signal — must be identical, or the demo becomes a side door around the gate.
    """
    if not text:
        raise HTTPException(400, "empty feedback")
    if deps.store.get(number) is None:
        raise HTTPException(404, f"no expedition {number}")
    client = _github()
    is_command = text.startswith("/")
    # Before anything else: retry is not a signal. A stopped run cannot receive one, so routing it
    # down the signal path would answer 409 to the only button that could have helped.
    if text.startswith("/retry"):
        return await _retry_run(number, subject or actor)
    from fls.orchestration import client as orch
    # WHERE THIS EXPEDITION LIVES decides how a command reaches it. The old test was
    # `client is None` — a fact about the instance, not about the expedition. On a harness wired
    # to both GitHub and Temporal it always chose GitHub, so a run filed through /demo/ideas (a
    # locally-minted number, no issue behind it) posted its approval as a comment on an issue
    # number belonging to nobody: 404 from the API, 500 to the browser, and three buttons that
    # looked inert. Asking the workflow whether it exists is cheap, and it is the only question
    # whose answer is about this run.
    workflow = await orch.status(number) if orch.enabled() else None
    if workflow is not None:
        # The durable workflow is the gate; the store is never written here. The decision lands
        # in the ledger under the actor's name.
        import time as _t

        from fls.ledger import Decision
        mapped = orch.command_to_signal(text)
        if mapped is None:
            raise HTTPException(400, "empty feedback")
        name, payload = mapped
        _refuse_absorbed_signal(number, name, workflow.get("state") or "")
        rec = deps.store.get(number)
        try:
            await orch.signal(number, name, payload)
        except Exception as ex:  # completed / unknown workflow, or Temporal down: say which
            raise HTTPException(409, f"workflow exp-{number} did not accept {name}: {str(ex)[:160]}") from ex
        deps.store.ledger().record(Decision(number, rec["rung"], name, name, 0.0,
                                            human_responded_at=_t.time(), actor=subject))
        return {"posted": True, "number": number, "command": is_command, "signal": name,
                "via": "temporal"}
    if client is None:
        raise HTTPException(503, "no outbound GitHub token — feedback refused (fail-closed)")
    formatted = (f"{text}\n\n_(via admin by {actor})_" if is_command
                 else f"💬 **{actor}** (via admin): {text}")
    from urllib.error import HTTPError

    from fls.github_surface import REPO
    # AN EXPEDITION NUMBER IS NOT A GITHUB NUMBER, and treating it as one is a governance bug,
    # not a routing inconvenience.
    #
    # Expeditions filed through /ideas or /demo/ideas are numbered `max(wall) + 1`, in a namespace
    # that has nothing to do with the repo's. GitHub numbers issues and pull requests from ONE
    # sequence, and `POST /issues/{n}/comments` happily accepts a PR. So on 2026-09-12 an Advance
    # on local expedition 2 posted `/advance` as a comment on pull request #2 — a closed,
    # unrelated PR — the signed webhook echoed it back, and the harness ACTED on it:
    # "Advanced to 5-flagged". A decision about one thing was executed against another, and the
    # screen was told it worked.
    #
    # So the number is verified before it is used: it must resolve to an ISSUE in this repo. A
    # `pull_request` key means the number belongs to a PR and this expedition is not GitHub-backed
    # at all. Refusing costs one API call; not refusing cost a wrong advance on a closed PR.
    try:
        target = client.get_issue(number)
    except HTTPError as ex:
        target = None if ex.code == 404 else {}
    except Exception:  # noqa: BLE001 — an unreachable API is not proof of anything
        target = {}
    if target is not None and "pull_request" in (target or {}):
        raise HTTPException(
            409, f"#{number} on {REPO} is a PULL REQUEST, not this expedition's issue — expedition "
                 "numbers are local and collide with the repo's own numbering, so this decision "
                 "has nowhere to go (fail-closed)")
    if target is None:
        raise HTTPException(
            409, f"expedition {number} has no issue on {REPO or 'the configured repo'} and no "
                 "running workflow, so there is nothing to accept this decision (fail-closed)")
    try:
        client.post_comment(number, formatted)
    except HTTPError as ex:
        # An expedition with no workflow AND no issue has nowhere to put a decision. Say that,
        # with the seam named, rather than letting a urllib traceback become a 500 the screen
        # renders as nothing at all.
        if ex.code == 404:
            raise HTTPException(
                409, f"expedition {number} has no issue on {REPO or 'the configured repo'} and "
                     "no running workflow, so there is nothing to accept this decision "
                     "(fail-closed)") from ex
        raise HTTPException(502, f"GitHub refused the comment: {ex.code} {ex.reason}") from ex
    return {"posted": True, "number": number, "command": is_command}


@app.post("/v1/operator/runs/{number}/feedback")
async def expedition_feedback(number: int, request: Request) -> dict:
    """The operator door. Fail-closed: requires an actor and an outbound token."""
    body = await request.json()
    actor, subject = _actor(request, body)
    if not actor:
        raise HTTPException(400, "feedback requires a named actor (gate is non-bypassable)")
    return await _post_feedback(number, (body.get("body") or "").strip(), actor, subject)


# The commands a VISITOR may send. The operator door takes any text; this one is an allowlist,
# because the demo surface offers exactly three buttons and anything else arriving here is not a
# visitor using the page.
#
# `/kill` belongs here and its absence was a bug, not a policy: the surface has always drawn a
# Stop button, and it posted `/kill …` into a door that answered 400. A visitor may stop the run
# they filed — that is the least dangerous of the three actions, and refusing it while accepting
# `/approve` had it exactly backwards.
_DEMO_COMMANDS = ("/approve", "/advance", "/pick", "/kill", "/retry")

# The third button is "say what to change", which is free prose by definition — there is no
# allowlist that can contain it. So the rule is shaped by what the text IS: a COMMAND must be one
# of the four above (an unknown slash-command is somebody probing the protocol, not a visitor
# typing), and anything else is treated as a comment and capped. The cap is the whole defence: a
# comment cannot make the ladder move, only a command can.
_DEMO_FEEDBACK_MAX = 2000


@app.post("/v1/visitor/runs/{number}/feedback")
async def demo_feedback(number: int, request: Request) -> dict:
    """The visitor door — the demo's approve / pick / advance buttons.

    This exists because the demo page was calling the OPERATOR feedback route directly, passing
    a name it had typed itself. That was invisible while nothing was authenticated; the moment
    the guard went on it would have 401'd the public demo's buttons, and the fix is not to
    exempt an operator route. It is for the visitor audience to have its own door, which is what
    the rest of the demo surface already does.

    Three things are checked that the operator door does not check, all because the caller is a
    stranger: a valid demo token, that the expedition was actually FILED through the demo (an
    operator's work is not a visitor's to advance), and that the command is one the page offers.
    """
    actor = _demo_actor(request)
    if not actor:
        raise HTTPException(401, "sign in first")
    rec = deps.store.get(number)
    if rec is None:
        raise HTTPException(404, f"no expedition {number}")
    if not str(rec.get("source", "")).startswith("demo"):
        raise HTTPException(403, "that expedition was not filed here")
    text = (await request.json()).get("body", "").strip()
    if text.startswith("/") and not text.startswith(_DEMO_COMMANDS):
        raise HTTPException(400, "that is not one of this surface's actions")
    if len(text) > _DEMO_FEEDBACK_MAX:
        raise HTTPException(413, f"say it in under {_DEMO_FEEDBACK_MAX} characters")
    if text.startswith("/kill"):
        # Stopping is a state change, not a message. Routing it through the notification path
        # made the most important button on the surface the most fragile one — it needed a live
        # workflow or a real issue, and a run the gate declined has neither.
        return await _park_expedition(number, actor, None, text[len("/kill"):].strip())
    # subject stays None: a visitor's name is self-chosen and deliberately UNVERIFIED. It makes
    # the ledger say who; it does not prove who, and the column that means "verified" must not
    # start quietly meaning "typed".
    try:
        return await _post_feedback(number, text, actor, None)
    except HTTPException as ex:
        # Translate on the way OUT, the same way the status line is translated on the way out.
        # The engine's refusals are written for an operator — they name the repo, the workflow,
        # the seam — and this door opens onto a page whose first rule is that none of that
        # appears. The status code is preserved so the surface can still tell a refusal from an
        # outage; only the sentence changes.
        from fls.demo import visitor_error
        raise HTTPException(ex.status_code, visitor_error(ex.status_code, str(ex.detail))) from ex


@app.get("/v1/visitor/runs/{number}/attachment")
def demo_attachment(number: int) -> Any:
    """The file a visitor attached, served back.

    Under /demo/, which the ANCHOR already declares a public surface — the same reasoning as the
    preview: it is the requester's own file on their own request, and a credential to look at it
    would make the run unreviewable by the person you sent the link to.

    Served from a name the SERVER chose (`attachment.<ext>` from the validated type), never from
    the uploaded filename, and always as an attachment download rather than inline — so a file
    that slipped the type check still cannot execute as a page on this origin.
    """
    from fastapi.responses import FileResponse
    d = deps.root / "expeditions" / str(number)
    meta_path = d / "attachment.json"
    if not meta_path.exists():
        raise HTTPException(404, f"expedition {number} has no attachment")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    f = d / meta["stored"]
    if not f.exists():
        raise HTTPException(404, "the attachment record has no file behind it")
    return FileResponse(f, media_type=meta["type"], filename=meta["label"],
                        content_disposition_type="attachment")


@app.get("/v1/public/runs/{number}/frames/{name}")
def wireframe(number: str, name: str) -> Any:
    """Serve one rung-2 wireframe candidate (expeditions/<id>/wireframes/candidate-N.html)."""
    import re as _re

    from fastapi.responses import FileResponse
    if not number.replace("-", "").isalnum():  # fail-closed on anything path-like
        raise HTTPException(404, "bad expedition id")
    if not _re.fullmatch(r"candidate-\d+\.html", name):
        raise HTTPException(404, "bad wireframe name")
    p = deps.root / "expeditions" / number / "wireframes" / name
    if not p.exists():
        raise HTTPException(404, f"no wireframe {name} for expedition {number}")
    return FileResponse(p, media_type="text/html")


@app.post("/v1/operator/anchor/validate")
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
    except Exception as e:  # noqa: BLE001 — an unknown section, a bad key, an unreadable ANCHOR
        # A REFUSAL, not a 500. Anything other than a ValidationError escaped as a server error,
        # and the console's catch turned that into "valid: true, proceed" — so an edit this
        # endpoint could not even parse became a pull request against the constitution. The whole
        # job of this route is to answer "may these edits be applied"; "I crashed" is a no.
        return {"valid": False, "errors": [f"{type(e).__name__}: {str(e)[:160]}"]}
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}


@app.post("/v1/operator/anchor/propose")
async def anchor_propose(request: Request) -> dict:
    """Turn validated console edits into a PR — the constitution changes by PR only. With no
    outbound token the payload is prepared and returned (simulated: nothing pushed), honestly."""

    from fls.anchor import apply_anchor_edits
    body = await request.json()
    section, edits = body.get("section", ""), body.get("edits", {})
    try:
        new_text, _ = apply_anchor_edits(ANCHOR_PATH.read_text(), section, edits)
    except Exception as e:  # noqa: BLE001 — surface the validation reason
        raise HTTPException(422, f"invalid edit: {e}") from e
    branch = f"anchor-edit-{section}"
    if not os.environ.get("GITHUB_TOKEN"):
        return {"simulated": True, "branch": branch, "section": section, "edits": edits,
                "note": "no outbound token (github-app-setup.md) — payload staged, nothing pushed"}
    # WHERE the PR goes is a third instance fact, and not FLS_REPO. FLS_REPO is the repo whose
    # ISSUES are expeditions; the constitution is versioned wherever ANCHOR.md actually lives.
    # Derived from that file's own checkout so it cannot drift from the file being edited.
    from fls.modules import anchor_remote
    repo = anchor_remote(ANCHOR_PATH)
    if not repo or "/" not in repo:
        return {"simulated": True, "branch": branch, "section": section, "edits": edits,
                "note": "cannot determine which repo ANCHOR.md is versioned in "
                        f"({ANCHOR_PATH.parent} is not a GitHub checkout) — payload staged, "
                        "nothing pushed. Opening a PR against a guessed repo is how a "
                        "constitution ends up committed to the wrong one."}
    from fls.github_surface import open_anchor_pr
    pr_url = open_anchor_pr(branch, new_text, section, edits, repo=repo)
    return {"simulated": False, "branch": branch, "repo": repo, "pr_url": pr_url}


@app.post("/v1/operator/feeder/run")
async def feeder_run(request: Request) -> dict:
    """Trigger one feeder run on the subscription lane. Fail-closed with a reason when the
    skill-server is unavailable — never pretends."""
    from fls.feeder import AdmissionSink, ListSink, run_feeder
    from fls.llm import SkillServerError, make_builder
    body = await request.json() if await request.body() else {}
    # Dry by default. A caller that does not say otherwise gets the safe path — and every caller
    # written before this parameter existed keeps the behaviour it was written against.
    dry_run = bool(body.get("dry_run", True))
    a = _anchor()
    # The ANCHOR names the builder; hardcoding the skill-server here meant a claude-code
    # instance could never run its feeder — it refused with "skill-server key unavailable"
    # for a backend it was not configured to use.
    brainstorm = make_builder(a)
    if not brainstorm.available():
        return {"triggered": False, "sink": None,
                "reason": "skill-server key unavailable (fail-closed)"}
    if dry_run:
        sink = ListSink()
    elif deps.judge is None:
        # A real run means the admission gate judges every candidate. No judge, no gate — and a
        # feeder that files past an absent gate is exactly the backdoor the one-door rule exists
        # to prevent. Refuse with the reason rather than quietly dry-running.
        return {"triggered": False, "sink": None,
                "reason": "no adjudicator configured — a real run would file past the gate "
                          "(fail-closed); use dry_run to preview"}
    else:
        sink = AdmissionSink(admit=admit_idea, next_number=_next_expedition_number)
    try:
        # The screen's scope box posts here. It used to be silently dropped — the run always
        # ideated against the ANCHOR while the UI said "changed for this run only", which is the
        # screen stating something the engine did not do.
        run = run_feeder(a, ANCHOR_PATH.read_text(), brainstorm, sink,
                         scope=(body.get("scope") or "").strip() or None)
    except SkillServerError as e:
        return {"triggered": False, "sink": sink.name, "reason": f"skill-server error: {e}"}
    # `sink` is the honest part: it names where the ideas went. The screen reporting "N filed"
    # while ListSink discarded them is what this field exists to make impossible.
    return {"triggered": True, "sink": sink.name, "dry_run": dry_run, "scope": run.scope,
            "proposed": run.proposed, "filed": len(run.filed),
            "within_envelope": run.within_envelope, "cost_usd": run.cost_usd,
            "normalized_usd": run.normalized_usd,
            "ideas": [{"intent": f.candidate.intent, "altitude": f.candidate.altitude,
                       "ref": f.ref} for f in run.filed]}


def _webhook_payload(body: bytes, content_type: str) -> dict | None:
    """GitHub sends a webhook as EITHER `application/json` or `application/x-www-form-urlencoded`
    (the latter is the default in its own new-hook form, and therefore the common case for a hook
    created by hand). Both are signed over the same raw bytes, so verification is unaffected —
    only parsing differs. Returns None when the body is neither, so the caller can refuse with a
    reason rather than raise."""
    import json as _json
    from urllib.parse import parse_qs
    if "form-urlencoded" in content_type:
        try:
            raw = parse_qs(body.decode("utf-8")).get("payload", [""])[0]
        except UnicodeDecodeError:
            return None
        if not raw:
            return None
        body = raw.encode("utf-8")
    try:
        parsed = _json.loads(body or b"")
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


@app.post("/v1/hooks/github")
async def github_webhook(request: Request) -> dict:
    """The real round-trip (V2-P2): verify the App's HMAC signature (fail-closed), then map
    the event onto the harness — admission for issues.opened, /advance /pick /approve commands
    on comments — and mirror state back to the issue via the outbound client."""
    import time as _time

    from fls.github_surface import NullClient, RestGitHubClient, handle_event, verify_signature

    body = await request.body()
    secret = os.environ.get("FLS_WEBHOOK_SECRET")
    if not verify_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        # no secret configured OR bad/missing signature -> refused, never processed on optimism
        raise HTTPException(403, "webhook signature refused (fail-closed)")
    event = request.headers.get("X-GitHub-Event", "unknown")
    payload = _webhook_payload(body, request.headers.get("content-type", ""))
    if payload is None:
        # A 500 here is OUR defect, not the sender's: GitHub offers two content types and this
        # handler used to assume JSON, so a webhook left on the form-encoded DEFAULT crashed with
        # a traceback and GitHub's delivery log showed a 500 against us. Refuse honestly instead.
        log.warning("github event=%s: unparseable body (content-type=%r)",
                    event, request.headers.get("content-type"))
        raise HTTPException(400, "webhook body is neither JSON nor a form-encoded payload")
    log.info("github event=%s action=%s", event, payload.get("action"))
    if event == "ping":
        # GitHub pings once when a hook is created. Answering it is how the delivery log shows a
        # green tick, which is the only confirmation an operator gets that the wiring is real.
        return {"ok": True, "event": "ping", "zen": payload.get("zen", "")}
    client = RestGitHubClient() if os.environ.get("GITHUB_TOKEN") else NullClient()
    # The deploy seam is handed in rather than imported inside the handler: a `ready_for_review`
    # is the one event that can move bytes, and which target it moves them to is instance policy.
    from fls.modules import make_deployer

    result = handle_event(event, payload, _anchor(), ANCHOR_PATH.read_text(), deps.judge,
                          deps.store, deps.store.ledger(), client, now=_time.time(),
                          deploy=make_deployer())
    from fls.orchestration import client as orch
    if orch.enabled() and event == "issue_comment" and result.get("number") is not None:
        # the echo IS the authorization: only comments GitHub signed reach the workflow
        mapped = orch.command_to_signal((payload.get("comment") or {}).get("body", ""))
        if mapped is not None:
            try:
                await orch.signal(result["number"], mapped[0], mapped[1])
                result["signal"] = mapped[0]
            except Exception as ex:
                result["signal_error"] = str(ex)[:200]
    return {"received": True, **result}


# ── the old paths, still answering ──────────────────────────────────────────────────────────
#
# Every route above moved so that its AUDIENCE is the first thing in its path. The old spellings
# stay live rather than 404ing, because some of them are held outside this repo: the GitHub App
# posts to /webhook/github, and a browser somewhere is holding a bookmark. They are the same
# endpoint functions, not copies — a fix to one is a fix to both, and neither can drift.
#
# `/auth/*` is absent from the move entirely: FLS_AUTH_REDIRECT_URI is registered with the
# identity provider, and changing it breaks sign-in until that registration changes too.
_LEGACY_PATHS = {
    "/v1/public/runs/active": "/demo/active",
    "/v1/public/runs/{number}/preview": "/preview/{number}",
    "/v1/public/runs/{number}/frames/{name}": "/wireframes/{number}/{name}",
    "/v1/visitor/login": "/demo/login",
    "/v1/visitor/requests": "/demo/ideas",
    "/v1/visitor/runs/{number}/feedback": "/demo/expeditions/{number}/feedback",
    "/v1/visitor/runs/{number}/attachment": "/demo/expeditions/{number}/attachment",
    "/v1/operator/runs": "/wall",
    "/v1/operator/runs/{number}": "/expeditions/{number}",
    "/v1/operator/runs/{number}/feedback": "/expeditions/{number}/feedback",
    "/v1/operator/runs/{number}/kill": "/expeditions/{number}/kill",
    "/v1/operator/runs/{number}/retry": "/expeditions/{number}/retry",
    "/v1/operator/runs/{number}/preview": "/expeditions/{number}/preview",
    "/v1/operator/runs/{number}/thread": "/expeditions/{number}/thread",
    "/v1/operator/requests": "/ideas",
    "/v1/operator/anchor": "/anchor",
    "/v1/operator/anchor/validate": "/anchor/validate",
    "/v1/operator/anchor/propose": "/anchor/propose",
    "/v1/operator/system": "/system",
    "/v1/operator/snapshot": "/snapshot",
    "/v1/operator/lessons": "/lessons",
    "/v1/operator/calibration": "/calibration",
    "/v1/operator/mining-history": "/mining-history",
    "/v1/operator/feeder/run": "/feeder/run",
    "/v1/operator/panels/propose": "/panels/propose",
    "/v1/hooks/github": "/webhook/github",
}


def _mount_legacy_aliases() -> None:
    """Re-register each moved endpoint at the path it used to have.

    Added to the router rather than redirected: a 307 would work for a GET and quietly lose the
    body and the `x-demo-token` header on the POSTs that matter, which is the kind of half-working
    that shows up as a visitor's button doing nothing.
    """
    from fastapi.routing import APIRoute

    by_path: dict[str, APIRoute] = {r.path: r for r in app.routes if isinstance(r, APIRoute)}
    for new, old in _LEGACY_PATHS.items():
        route = by_path.get(new)
        if route is None or old in by_path:
            continue
        app.add_api_route(old, route.endpoint, methods=sorted(route.methods),
                          include_in_schema=False, name=f"legacy:{route.name}")


_mount_legacy_aliases()

"""V3-B3 (+ V8-P3) — the module seams, formalized (not invented).

The system has always had pluggable seams; this module names them and makes them
reflectable + extensible without changing any behavior:

  - AUTH        ⇐ github_surface.verify_signature + GITHUB_TOKEN  (inbound HMAC · outbound token)
  - IDEAS       ⇐ feeder.run_feeder / IdeaSink                    (every source enters by one door)
  - LENSES      ⇐ FLS_MODULES-registered kinds only (P2a)         (managed audit/brainstorm passes
                                                                    over a vessel; files through a sink)
  - SOURCES     ⇐ github_surface.GitHubClient + FLS_REPO(/_DEV)   (where expeditions live)
  - WORKERS     ⇐ llm.make_builder backends                        (who fulfils builder work)
  - ENVIRONMENT ⇐ V8-P3, the 6th slot                              (where a rung's builder/verifier
                                                                    runs — worktree+verify-command is
                                                                    the built-in, historical default,
                                                                    made explicit + registerable)

V8-P3 also publishes the **middleware seams** — `before_rung` / `after_rung` / `on_descend` /
`on_context_assembly` — a registerable hook system (see "SLICE 3" below). A module registers a
callback against a hook name; the engine dispatches it at that point in the climb. Dispatch is
isolated: one bad callback is logged and skipped, never crashes the climb.

Two things live here:
  1. `describe(anchor)` — a BOOLEANS-ONLY reflection of each seam (kind · configured · available
     · docs link), consumed by `GET /system`. It NEVER emits a secret value — only presence
     booleans and non-secret names (repo names, backend kinds, budget numbers).
  2. Tiny registries (WORKERS/IDEAS/SOURCES/AUTH: kind -> factory) pre-populated with the
     built-ins by importing the existing factories, plus `load_modules()` — the `FLS_MODULES`
     importlib extension hook (fail-closed: an unknown module path RAISES, refusing to start).

Config split follows the builder precedent: ANCHOR carries kind + policy knobs; env carries
endpoints + secrets. This module reads env for BOOLEANS ONLY.
"""
from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from fls.feeder import FeederRun, IdeaSink, run_feeder
from fls.llm import Call, ClaudeBuilder, SkillServerBuilder, make_builder

# NOTE: `fls.github_surface` is deliberately NOT imported at module load. The module REGISTRY is
# framework core (zero web/GitHub deps — grep-gated); the built-in `github`/`github-app` factories
# below lazy-import it so `import fls.modules` stays clean when the [harness] extra isn't installed.

log = logging.getLogger("fls.modules")


@dataclass
class ModuleStatus:
    """One seam's reflected state — presence booleans + non-secret names only, never a value."""
    slot: str
    kind: str
    configured: bool
    available: bool
    docs_url: str = ""
    detail: dict = field(default_factory=dict)


def _docs(slot: str) -> str:
    """The System-card docs anchor for a slot (page lands in B4; placeholder path is fine)."""
    return f"/docs/modules.md#{slot}"


# ── SLICE 1 — reflection (zero behavior change) ───────────────────────────────
def _auth_status() -> dict:
    """AUTH: which built-in is active. Explicit override via `FLS_AUTH_KIND`; otherwise
    auto-selected — `github-app` when both the inbound secret and the outbound token are
    present, else the no-op-safe `none` kind. This makes local-mode the fresh-install default
    (no env at all) while a fully-configured instance keeps reporting `github-app` unchanged."""
    has_app = bool(os.environ.get("FLS_WEBHOOK_SECRET")) and bool(os.environ.get("GITHUB_TOKEN"))
    kind = os.environ.get("FLS_AUTH_KIND") or ("github-app" if has_app else "none")
    if kind == "github-app":
        configured = has_app
        available = configured
    else:
        configured, available = True, True  # local-mode: nothing to configure, no-op-safe
    return asdict(ModuleStatus(
        slot="auth", kind=kind,
        configured=configured, available=available, docs_url=_docs("auth"),
    ))


def _ideas_status(anchor) -> list[dict]:
    """IDEAS is a LIST: the always-on manual door + the optional studio feeder."""
    out = [asdict(ModuleStatus(
        slot="ideas", kind="manual",
        configured=True, available=True, docs_url=_docs("ideas"),
    ))]
    has_feeder = any(s.get("kind") == "feeder" for s in anchor.idea_sources)
    # cheap construction, NO network: available() only reads env (endpoint + key presence)
    feeder_available = SkillServerBuilder(shadow_model=anchor.builder.shadow_model).available()
    out.append(asdict(ModuleStatus(
        slot="ideas", kind="feeder",
        configured=has_feeder, available=feeder_available, docs_url=_docs("ideas"),
    )))
    # Registered (FLS_MODULES) idea kinds surface too — a module the instance loaded is part
    # of its wiring truth. status() on the factory's product stays cheap/no-network by the
    # same rule as everything here; a factory that errors reports honestly as unavailable.
    for kind, factory in IDEAS.items():
        if kind == "feeder":
            continue
        try:
            mod = factory()
            configured = bool(getattr(mod, "configured", lambda: True)())
            available = bool(getattr(mod, "available", lambda: False)())
            detail = dict(getattr(mod, "detail", lambda: {})())
        except Exception as e:  # noqa: BLE001 — an erroring module is an unavailable module
            configured, available, detail = False, False, {"error": str(e)[:120]}
        out.append(asdict(ModuleStatus(
            slot="ideas", kind=kind, configured=configured, available=available,
            docs_url=_docs("ideas"), detail=detail,
        )))
    return out


def _lenses_status(anchor) -> list[dict]:
    """LENSES is a LIST: every FLS_MODULES-registered lens kind, probed exactly like the IDEAS
    registry loop. No built-in lens ships in modules.py — a lens kind arrives entirely via
    FLS_MODULES wiring (mirrors how a studio-private idea source is wired, not baked in)."""
    out: list[dict] = []
    for kind, factory in LENSES.items():
        try:
            mod = factory()
            configured = bool(getattr(mod, "configured", lambda: True)())
            available = bool(getattr(mod, "available", lambda: False)())
            detail = dict(getattr(mod, "detail", lambda: {})())
        except Exception as e:  # noqa: BLE001 — an erroring module is an unavailable module
            configured, available, detail = False, False, {"error": str(e)[:120]}
        out.append(asdict(ModuleStatus(
            slot="lenses", kind=kind, configured=configured, available=available,
            docs_url=_docs("lenses"), detail=detail,
        )))
    return out


def _sources_status() -> dict:
    """SOURCES: which built-in is active. Explicit override via `FLS_SOURCE_KIND`; otherwise
    auto-selected — `github` when `FLS_REPO` is set, else the local kind (a fresh install's
    default: expeditions live only in the local `ExpeditionStore`, no GitHub repo required).
    Repo NAMES are not secrets; the token presence is a boolean."""
    prod = os.environ.get("FLS_REPO") or None
    dev = os.environ.get("FLS_REPO_DEV") or None
    kind = os.environ.get("FLS_SOURCE_KIND") or ("github" if prod else "local")
    if kind == "github":
        configured = bool(prod)
        available = configured and bool(os.environ.get("GITHUB_TOKEN"))
        detail = {"prod_repo": prod, "dev_repo": dev}
    else:
        configured, available = True, True  # local-mode: nothing to configure, no-op-safe
        detail = {"note": "local-mode: no GitHub repo configured; "
                           "expeditions live only in the local store"}
    return asdict(ModuleStatus(
        slot="sources", kind=kind,
        configured=configured, available=available, docs_url=_docs("sources"),
        detail=detail,
    ))


def _workers_status(anchor) -> dict:
    """WORKERS: who fulfils builder work — kind is the ANCHOR builder backend; key presence via
    the same llm helpers make_builder uses (api -> ANTHROPIC_API_KEY; skill-server -> endpoint+key)."""
    cfg = anchor.builder
    if cfg.backend == "api":
        ok = ClaudeBuilder().available()          # reads ANTHROPIC_API_KEY only, no network
    else:
        ok = SkillServerBuilder(shadow_model=cfg.shadow_model).available()  # endpoint + key
    return asdict(ModuleStatus(
        slot="workers", kind=cfg.backend,
        configured=ok, available=ok, docs_url=_docs("workers"),
        detail={"fallback": cfg.fallback, "fallback_budget_usd": cfg.fallback_budget_usd},
    ))


def _environment_status() -> list[dict]:
    """ENVIRONMENT is a LIST, mirroring IDEAS: the built-in `worktree` provider (always present —
    the historical implicit "just run it in a worktree" behavior, made explicit) plus any
    FLS_MODULES-registered kind (devcontainer/nix/docker/...). Probed exactly like the IDEAS/
    LENSES registry loops: a factory that errors reports honestly as unavailable, never raises
    into reflection."""
    out: list[dict] = []
    for kind, factory in ENVIRONMENTS.items():
        try:
            env = factory()
            configured = bool(getattr(env, "configured", lambda: True)())
            available = bool(getattr(env, "available", lambda: False)())
            detail = dict(getattr(env, "detail", lambda: {})())
        except Exception as e:  # noqa: BLE001 — an erroring module is an unavailable module
            configured, available, detail = False, False, {"error": str(e)[:120]}
        out.append(asdict(ModuleStatus(
            slot="environment", kind=kind, configured=configured, available=available,
            docs_url=_docs("environment"), detail=detail,
        )))
    return out


def describe(anchor) -> dict:
    """Reflect all six seams as booleans + kinds + non-secret detail. Read-only, no network.
    Consumed by `GET /system`; B2's System cards render exactly this."""
    return {
        "auth": _auth_status(),
        "ideas": _ideas_status(anchor),
        "lenses": _lenses_status(anchor),
        "sources": _sources_status(),
        "workers": _workers_status(anchor),
        "environment": _environment_status(),
    }


# ── SLICE 2 — pluggability (protocols + registries + the FLS_MODULES hook) ─────
class Worker(Protocol):
    """A builder worker — mirrors the existing llm.py builder shape exactly."""
    def available(self) -> bool: ...
    def complete(self, prompt: str, max_tokens: int = ...,
                 system: str | None = ...) -> tuple[str, Call]: ...


class IdeaSource(Protocol):
    """An idea source — mirrors feeder.run_feeder's contract: it PROPOSES and files through the
    sink (the one door), never admits. Returns a FeederRun."""
    def run(self, anchor, anchor_text: str, sink: IdeaSink) -> FeederRun: ...


class Lens(Protocol):
    """P2a — a managed LENS: an audit/brainstorm pass over a vessel that runs on its own cadence
    and files everything it finds through the STANDARD door (a sink), exactly like IdeaSource —
    the lens itself never self-admits or writes directly. Fields describe what the lens is
    (kind/mode/panel/target_vessel/cadence/sink_label); `run` is the one call the engine makes."""
    kind: str
    mode: Literal["generative", "audit-first"]
    panel: str
    target_vessel: str
    cadence: str
    sink_label: str

    def run(self, anchor, anchor_text: str, snapshot, sink) -> object: ...
    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...


class Source(Protocol):
    """A work source — mirrors github_surface.GitHubClient's Protocol methods."""
    def post_comment(self, issue: int, text: str) -> None: ...
    def set_labels(self, issue: int, labels: list[str]) -> None: ...
    def create_deployment(self, env: str, ref: str) -> bool: ...
    def get_issue(self, issue: int) -> dict: ...
    def list_comments(self, issue: int) -> list: ...


class Auth(Protocol):
    """Inbound signature verification + outbound token — extracted from github_surface."""
    def verify_inbound(self, body: bytes, signature_header: str | None) -> bool: ...
    def outbound_token(self) -> str | None: ...


@dataclass
class EnvironmentHandle:
    """What `Environment.provision` hands back: where the work actually runs."""
    kind: str
    workdir: str
    meta: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    """What `Environment.run_verify` hands back — never raises; a broken verify command is a
    failed result, not an exception, so a rung's descend logic can read it uniformly."""
    passed: bool
    output: str
    exit_code: int


class Environment(Protocol):
    """The 6th slot (V8-P3) — provisions WHERE a rung's builder/verifier work runs. The built-in
    `worktree` kind is the historical implicit default (a git worktree + a shell verify command)
    made explicit and swappable; `devcontainer`/`nix`/`docker` are documented extension kinds a
    module can register — real container provisioning is out of scope here, only the seam."""
    kind: str
    def provision(self, expedition_id: str, base_dir: str | None = None) -> EnvironmentHandle: ...
    def run_verify(self, handle: EnvironmentHandle, command: str) -> VerifyResult: ...
    def teardown(self, handle: EnvironmentHandle) -> None: ...
    def configured(self) -> bool: ...
    def available(self) -> bool: ...
    def detail(self) -> dict: ...


class GitHubAppAuth:
    """Built-in AUTH: wraps github_surface.verify_signature + the env GITHUB_TOKEN. Fail-closed —
    no configured secret or a bad signature -> False (never processed on optimism)."""

    def __init__(self, secret: str | None = None, token: str | None = None):
        self._secret = secret if secret is not None else os.environ.get("FLS_WEBHOOK_SECRET")
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def verify_inbound(self, body: bytes, signature_header: str | None) -> bool:
        from fls.github_surface import verify_signature
        return verify_signature(self._secret, body, signature_header)

    def outbound_token(self) -> str | None:
        return self._token or None


class LocalSource:
    """Built-in SOURCES for local-mode: no GitHub repo configured, so expeditions live only in
    the local `ExpeditionStore` (filesystem-backed — see `fls.store`). Every outbound call is a
    safe no-op instead of a network call, so a fresh install runs the whole climb loop end to
    end with no GitHub App, no token, and no repo. `get_issue`/`list_comments` raise honestly
    (mirrors the real client's "no linked issue" case) rather than fabricate a GitHub issue that
    doesn't exist."""

    kind = "local"

    def post_comment(self, issue: int, text: str) -> None:
        log.debug("local-mode SOURCES: post_comment(%s) is a no-op (no GitHub repo configured)",
                   issue)

    def set_labels(self, issue: int, labels: list[str]) -> None:
        log.debug("local-mode SOURCES: set_labels(%s) is a no-op (no GitHub repo configured)",
                   issue)

    def create_deployment(self, env: str, ref: str) -> bool:
        log.debug("local-mode SOURCES: create_deployment(%s) is a no-op (no GitHub repo "
                   "configured)", env)
        return False

    def get_issue(self, issue: int) -> dict:
        raise LookupError(f"local-mode SOURCES: no GitHub issue {issue} (no repo configured)")

    def list_comments(self, issue: int) -> list:
        raise LookupError(f"local-mode SOURCES: no GitHub issue {issue} (no repo configured)")

    def configured(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def detail(self) -> dict:
        return {"mode": "local",
                "note": "no GitHub repo configured; expeditions live only in the local store"}


class NoneAuth:
    """Built-in AUTH for local-mode: no GitHub App configured, so there is no inbound webhook to
    verify and no outbound token to present. `verify_inbound` is no-op-SAFE, not permissive — it
    always refuses, because local-mode never receives a real signed webhook to begin with
    (fail-closed: nothing here ever admits a request on optimism just because no secret is set)."""

    kind = "none"

    def verify_inbound(self, body: bytes, signature_header: str | None) -> bool:
        return False

    def outbound_token(self) -> str | None:
        return None

    def configured(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def detail(self) -> dict:
        return {"mode": "local", "note": "no GitHub App configured; no inbound webhook to verify"}


class FeederIdeaSource:
    """Built-in IDEAS: the studio-brainstorm feeder. Rides the skill-server (subscription lane)
    and files every surviving idea through the STANDARD door via run_feeder — it cannot self-admit."""

    def __init__(self, brainstorm: Worker | None = None):
        self._brainstorm = brainstorm

    def run(self, anchor, anchor_text: str, sink: IdeaSink) -> FeederRun:
        brainstorm = self._brainstorm or SkillServerBuilder(shadow_model=anchor.builder.shadow_model)
        return run_feeder(anchor, anchor_text, brainstorm, sink)


class WorktreeEnvironment:
    """Built-in ENVIRONMENT: git worktree + shell verify-command — the historical implicit
    behavior, made explicit and registerable. `provision()` adds (or reuses) a worktree at
    `base_dir/expedition_id` off the given repo; `run_verify()` shells the caller's verify
    command inside it; `teardown()` removes the worktree. Fail-closed in spirit: a broken git or
    verify command surfaces as a failed `VerifyResult`/raised `CalledProcessError` rather than
    silently reporting success — nothing here pretends work happened when it didn't."""

    kind = "worktree"

    def __init__(self, repo_root: str | None = None):
        self._repo_root = repo_root or os.getcwd()

    def configured(self) -> bool:
        return shutil.which("git") is not None

    def available(self) -> bool:
        return self.configured()

    def detail(self) -> dict:
        return {"provisioning": "git-worktree", "verify": "shell-command"}

    def provision(self, expedition_id: str, base_dir: str | None = None) -> EnvironmentHandle:
        base = Path(base_dir or tempfile.gettempdir()) / "fls-worktrees"
        base.mkdir(parents=True, exist_ok=True)
        workdir = base / expedition_id
        if not workdir.exists():
            subprocess.run(
                ["git", "worktree", "add", "-f", str(workdir)],
                cwd=self._repo_root, check=True, capture_output=True, text=True,
            )
        return EnvironmentHandle(kind=self.kind, workdir=str(workdir))

    def run_verify(self, handle: EnvironmentHandle, command: str) -> VerifyResult:
        proc = subprocess.run(command, shell=True, cwd=handle.workdir,  # noqa: S602 — caller-supplied verify command, by design (same trust boundary as ANCHOR-declared verify today)
                               capture_output=True, text=True)
        return VerifyResult(passed=proc.returncode == 0,
                             output=(proc.stdout + proc.stderr)[-4000:],
                             exit_code=proc.returncode)

    def teardown(self, handle: EnvironmentHandle) -> None:
        subprocess.run(["git", "worktree", "remove", "-f", handle.workdir],
                        cwd=self._repo_root, capture_output=True, text=True)


# built-in factories — wrap the existing constructors, never modify them
def _worker_api(anchor=None, guard=None) -> Worker:
    return ClaudeBuilder(guard=guard)


def _worker_skill_server(anchor=None, guard=None) -> Worker:
    # honor make_builder's fallback wiring when an anchor is available
    return make_builder(anchor, guard=guard) if anchor is not None else SkillServerBuilder(guard=guard)


def _ideas_feeder(brainstorm=None) -> IdeaSource:
    return FeederIdeaSource(brainstorm)


def _source_github(repo=None, token=None) -> Source:
    from fls.github_surface import REPO, RestGitHubClient
    return RestGitHubClient(repo=repo or REPO, token=token)


def _auth_github_app(secret=None, token=None) -> Auth:
    return GitHubAppAuth(secret=secret, token=token)


def _source_local(**kw) -> Source:
    return LocalSource()


def _auth_none(**kw) -> Auth:
    return NoneAuth()


def _environment_worktree(repo_root=None) -> Environment:
    return WorktreeEnvironment(repo_root=repo_root)


# kind -> factory registries, pre-populated with the built-ins. Modules extend these.
WORKERS: dict = {"api": _worker_api, "skill-server": _worker_skill_server}
IDEAS: dict = {"feeder": _ideas_feeder}
# LENSES has no built-in — a lens kind (e.g. "design-audit") arrives entirely via FLS_MODULES
# wiring, same as a studio-private idea source. Empty by default; modules extend this.
LENSES: dict = {}
# `local` needs no GitHub repo/token — the fresh-install default (see `_sources_status`).
SOURCES: dict = {"github": _source_github, "local": _source_local}
# `none` needs no GitHub App — the fresh-install default (see `_auth_status`).
AUTH: dict = {"github-app": _auth_github_app, "none": _auth_none}
# ENVIRONMENT ships ONE built-in (`worktree` — the historical implicit default made explicit);
# `devcontainer`/`nix`/`docker` arrive entirely via FLS_MODULES wiring, same pattern as LENSES.
ENVIRONMENTS: dict = {"worktree": _environment_worktree}


def load_modules(spec: str | None = None) -> list[str]:
    """The `FLS_MODULES` extension hook: comma-separated importable module paths, each
    importlib.import_module'd for its registration side effects. Fail-closed: an ImportError is
    logged and RE-RAISED so the process refuses to start with a half-wired module set."""
    spec = spec if spec is not None else os.environ.get("FLS_MODULES", "")
    loaded: list[str] = []
    for path in (p.strip() for p in spec.split(",")):
        if not path:
            continue
        try:
            importlib.import_module(path)
        except ImportError as e:
            log.error("FLS_MODULES: cannot import module '%s' (fail-closed, refusing to start): %s",
                      path, e)
            raise
        loaded.append(path)
    if loaded:
        log.info("FLS_MODULES: loaded %s", ", ".join(loaded))
    return loaded


# ── SLICE 3 (V8-P3) — published middleware seams ────────────────────────────────
# Four named hook points, published as part of the framework contract. A module registers a
# callback against one of these hook names (typically at FLS_MODULES import time, alongside its
# registry assignments); the engine dispatches registered callbacks at that point in the climb.
#
# This module defines the seam — the registry, the Protocol, register/dispatch — and is the
# complete public API a module author needs. It does NOT thread call sites through the climb
# loop itself (that's fls.climb/fls.controller territory); the intended call sites are:
#   - `before_rung` / `after_rung` — fls.climb.advance_expedition, bracketing each rung's body
#     (rung 3's walkthrough, rung 4's MVP loop, rung 5's draft-PR gate).
#   - `on_descend`                 — the DESCENDED transition (fls.climb / fls.rung4's
#     retry-vs-descend loop) — fires once per descent, after the lesson is recorded.
#   - `on_context_assembly`        — wherever context is bounded before a builder call (rung 4's
#     BoundedContext construction, the feeder's anchor-text read) — fires with the assembled
#     context payload before it reaches a Worker.
MIDDLEWARE_HOOKS = ("before_rung", "after_rung", "on_descend", "on_context_assembly")
MIDDLEWARE: dict[str, list] = {hook: [] for hook in MIDDLEWARE_HOOKS}


class Middleware(Protocol):
    """A middleware callback's shape: receives the hook name it was invoked for plus whatever
    kwargs the call site passes (expedition/rung/context/lesson — call-site-specific), returns
    nothing. Middleware OBSERVES; it is not a place to mutate engine state or veto a climb — the
    admission/descend/gate decisions stay in controller.py/climb.py, exactly like an IdeaSource
    proposes but never admits."""
    def __call__(self, hook: str, **kwargs) -> None: ...


def register_middleware(hook: str, callback: Middleware) -> None:
    """Register a callback against a published hook name. Fail-closed on typos: an unknown hook
    raises immediately at registration time (a module author's mistake surfaces at import/wiring
    time, not silently at climb time)."""
    if hook not in MIDDLEWARE:
        raise ValueError(f"unknown middleware hook '{hook}' (must be one of {sorted(MIDDLEWARE)})")
    MIDDLEWARE[hook].append(callback)


def dispatch_middleware(hook: str, **kwargs) -> None:
    """Call every callback registered for `hook`, in registration order. Isolation policy: a
    callback that raises is logged and skipped — it can NEVER crash the climb or block later
    callbacks. (An unknown hook name is still a raise: that's a call-site bug, not a callback
    failure, so it does NOT get the isolation treatment.)"""
    if hook not in MIDDLEWARE:
        raise ValueError(f"unknown middleware hook '{hook}' (must be one of {sorted(MIDDLEWARE)})")
    for callback in list(MIDDLEWARE[hook]):
        try:
            callback(hook, **kwargs)
        except Exception as e:  # noqa: BLE001 — isolation: one bad callback never crashes the climb
            log.error("middleware hook '%s' callback %r raised (isolated, continuing): %s",
                      hook, callback, e)

"""V3-B3 — the four module seams, formalized (not invented).

The system has always had four pluggable seams; this module names them and makes them
reflectable + extensible without changing any behavior:

  - AUTH    ⇐ github_surface.verify_signature + GITHUB_TOKEN  (inbound HMAC · outbound token)
  - IDEAS   ⇐ feeder.run_feeder / IdeaSink                    (every source enters by one door)
  - SOURCES ⇐ github_surface.GitHubClient + FLS_REPO(/_DEV)   (where expeditions live)
  - WORKERS ⇐ llm.make_builder backends                        (who fulfils builder work)

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
from dataclasses import asdict, dataclass, field
from typing import Protocol

from fls.feeder import FeederRun, IdeaSink, run_feeder
from fls.github_surface import REPO, RestGitHubClient, verify_signature
from fls.llm import Call, ClaudeBuilder, SkillServerBuilder, make_builder

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
    """AUTH: the GitHub App seam. configured = inbound secret AND outbound token both present."""
    configured = bool(os.environ.get("FLS_WEBHOOK_SECRET")) and bool(os.environ.get("GITHUB_TOKEN"))
    return asdict(ModuleStatus(
        slot="auth", kind="github-app",
        configured=configured, available=configured, docs_url=_docs("auth"),
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


def _sources_status() -> dict:
    """SOURCES: the GitHub repo(s). Repo NAMES are not secrets; the token presence is a boolean."""
    prod = os.environ.get("FLS_REPO") or None
    dev = os.environ.get("FLS_REPO_DEV") or None
    configured = bool(prod)
    available = configured and bool(os.environ.get("GITHUB_TOKEN"))
    return asdict(ModuleStatus(
        slot="sources", kind="github",
        configured=configured, available=available, docs_url=_docs("sources"),
        detail={"prod_repo": prod, "dev_repo": dev},
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


def describe(anchor) -> dict:
    """Reflect all four seams as booleans + kinds + non-secret detail. Read-only, no network.
    Consumed by `GET /system`; B2's System cards render exactly this."""
    return {
        "auth": _auth_status(),
        "ideas": _ideas_status(anchor),
        "sources": _sources_status(),
        "workers": _workers_status(anchor),
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


class GitHubAppAuth:
    """Built-in AUTH: wraps github_surface.verify_signature + the env GITHUB_TOKEN. Fail-closed —
    no configured secret or a bad signature -> False (never processed on optimism)."""

    def __init__(self, secret: str | None = None, token: str | None = None):
        self._secret = secret if secret is not None else os.environ.get("FLS_WEBHOOK_SECRET")
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def verify_inbound(self, body: bytes, signature_header: str | None) -> bool:
        return verify_signature(self._secret, body, signature_header)

    def outbound_token(self) -> str | None:
        return self._token or None


class FeederIdeaSource:
    """Built-in IDEAS: the studio-brainstorm feeder. Rides the skill-server (subscription lane)
    and files every surviving idea through the STANDARD door via run_feeder — it cannot self-admit."""

    def __init__(self, brainstorm: Worker | None = None):
        self._brainstorm = brainstorm

    def run(self, anchor, anchor_text: str, sink: IdeaSink) -> FeederRun:
        brainstorm = self._brainstorm or SkillServerBuilder(shadow_model=anchor.builder.shadow_model)
        return run_feeder(anchor, anchor_text, brainstorm, sink)


# built-in factories — wrap the existing constructors, never modify them
def _worker_api(anchor=None, guard=None) -> Worker:
    return ClaudeBuilder(guard=guard)


def _worker_skill_server(anchor=None, guard=None) -> Worker:
    # honor make_builder's fallback wiring when an anchor is available
    return make_builder(anchor, guard=guard) if anchor is not None else SkillServerBuilder(guard=guard)


def _ideas_feeder(brainstorm=None) -> IdeaSource:
    return FeederIdeaSource(brainstorm)


def _source_github(repo=None, token=None) -> Source:
    return RestGitHubClient(repo=repo or REPO, token=token)


def _auth_github_app(secret=None, token=None) -> Auth:
    return GitHubAppAuth(secret=secret, token=token)


# kind -> factory registries, pre-populated with the built-ins. Modules extend these.
WORKERS: dict = {"api": _worker_api, "skill-server": _worker_skill_server}
IDEAS: dict = {"feeder": _ideas_feeder}
SOURCES: dict = {"github": _source_github}
AUTH: dict = {"github-app": _auth_github_app}


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

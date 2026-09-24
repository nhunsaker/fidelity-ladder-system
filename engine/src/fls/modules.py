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
  - IDENTITY    ⇐ fls.identity, the 7th slot                       (WHO a human operator is — session
                                                                    level, as opposed to AUTH's
                                                                    message level; see the note in
                                                                    `_identity_status`)

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

import configparser
import importlib
import logging
import os
import re
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
        # `scope` exists because an operator now sees two auth-ish slots on the System card and
        # deserves to know why both are there. AUTH signs and verifies MESSAGES; IDENTITY
        # establishes a PERSON's session. Neither substitutes for the other.
        detail={"scope": "message"},
    ))


def _identity_status() -> dict:
    """IDENTITY: who the human driving the console is (V-login, the 7th slot).

    Booleans and non-secret names only, like every other seam — the kind, whether a provider is
    wired, whether a session can actually be signed, the POLICY NAME, and an allowlist COUNT.
    Never the client secret, never the client id, never a login. A count is not a secret; the
    list of people who can kill your expeditions is operational detail a stranger reading
    `/system` has no business enumerating.

    `available` is stricter than `configured` on purpose: a provider can be fully wired and the
    instance still be unable to log anyone in, because `FLS_SESSION_SECRET` is missing (no
    session can be signed) or because `Policy` names nobody (fail-closed, so every successful
    sign-in is refused at the last step). Both are the kind of half-deployment that otherwise
    presents to the operator as "GitHub worked and then it just bounced me".
    """
    from fls.identity import Policy, SignedSession, active_kind, resolve
    kind = active_kind()
    try:
        provider = resolve(kind)
        configured = bool(provider.configured())
        detail = dict(provider.detail())
    except Exception as e:  # noqa: BLE001 — an erroring provider is an unavailable provider
        configured, detail = False, {"error": str(e)[:120]}
    policy = Policy.from_env()
    session = SignedSession.from_env()
    detail.update(policy.detail())
    detail["scope"] = "session"
    detail["session_secret_set"] = session.configured
    detail["redirect_uri_set"] = bool(os.environ.get("FLS_AUTH_REDIRECT_URI"))
    available = configured and session.configured and policy.configured
    return asdict(ModuleStatus(
        slot="identity", kind=kind,
        configured=configured, available=available, docs_url=_docs("identity"),
        detail=detail,
    ))


def _ideas_status(anchor) -> list[dict]:
    """IDEAS is a LIST: the always-on manual door + the optional studio feeder."""
    out = [asdict(ModuleStatus(
        slot="ideas", kind="manual",
        configured=True, available=True, docs_url=_docs("ideas"),
    ))]
    has_feeder = any(s.get("kind") == "feeder" for s in anchor.idea_sources)
    # cheap construction, NO network: available() only reads env (endpoint + key presence)
    # The feeder runs on whatever builder the ANCHOR declares, not on the skill-server
    # specifically — see `_workers_status`. Asking the wrong backend made the feeder report
    # unavailable on every claude-code instance.
    try:
        feeder_available = bool(make_builder(anchor).available())
    except Exception:  # noqa: BLE001
        feeder_available = False
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


def git_remote(root) -> str | None:
    """The `origin` remote of the checkout at `root`, as an `owner/repo` slug when it is GitHub.

    Read from `.git/config` with the stdlib rather than shelling out to `git`: a plain filesystem
    read, the same class as the `isdir`/`access` calls `_deploy_status` makes, so reflection keeps
    its "no probes" contract and needs no git binary.

    Returns the raw URL for a non-GitHub remote, so a caller's slug check refuses it rather than
    inventing a github.com URL for a host that is not GitHub. Never raises: a missing path, a bare
    directory or an unreadable config all mean "no remote", which is the truthful answer.
    """
    if not root:
        return None
    cfg = Path(root) / ".git" / "config"
    try:
        parser = configparser.ConfigParser()
        parser.read(cfg)
        url = parser['remote "origin"'].get("url", "").strip()
    except Exception:  # noqa: BLE001 — not a repo, unreadable, or no origin: all mean "none"
        return None
    if not url:
        return None
    m = re.match(r"^(?:https?://github\.com/|git@github\.com:)(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group("slug") if m else url


def anchor_remote(anchor_path) -> str | None:
    """The repo the CONSTITUTION lives in.

    A THIRD instance fact, distinct from both of the others, and conflating it with either is how
    an ANCHOR edit gets aimed at the wrong repository:
      FLS_REPO         — the repo whose ISSUES are expeditions
      FLS_VESSEL_REPO  — the checkout where CODE lands
      this             — where ANCHOR.md itself is versioned

    `open_anchor_pr` used to default to FLS_REPO, so on an instance where the constitution lives in
    one repo and expeditions in another, "Open the PR" would branch off the wrong one — and had
    that repo happened to contain an ANCHOR.md, it would have committed the instance's constitution
    into the product's repository.

    `FLS_ANCHOR_REPO` wins when set, because a deployed instance HAS no checkout to derive from:
    the deploy rsyncs `--exclude .git`, correctly — a server should not carry git metadata. So the
    env var is the deployment's answer and derivation is the zero-config answer for a developer
    running against a real clone. An explicit value is only ever set on purpose, which is the same
    precedence rule the deploy seam follows for FLS_STAGE_DIR.
    """
    explicit = os.environ.get("FLS_ANCHOR_REPO", "").strip()
    if explicit:
        return explicit
    return git_remote(Path(anchor_path).parent) if anchor_path else None


def _vessel_remote() -> str | None:
    """Where the builder actually writes code, derived from the checkout itself.

    `FLS_REPO` is the repo whose ISSUES are expeditions; `FLS_VESSEL_REPO` is the checkout a
    builder writes into and pushes a branch from. They are different jobs and can be different
    repos, and until now nothing surfaced the second one — the Connections screen could say where
    decisions are recorded but not where the work lands.

    Read from `.git/config` with the stdlib rather than shelling out to `git`: a plain filesystem
    read, the same class as the `isdir`/`access` calls `_deploy_status` already makes, so
    reflection keeps its "no probes" contract and needs no git binary. Derived, not declared —
    the repo URL is instance identity, which the work-split rule puts in env, and a copy of it in
    the ANCHOR could drift from the checkout it claims to describe.

    Returns an `owner/repo` slug for a GitHub remote (https or ssh), the raw URL for anything
    else, or None. Never raises: a missing path, a bare directory or an unreadable config is
    simply "no vessel remote", which is the truthful answer.
    """
    return git_remote(os.environ.get("FLS_VESSEL_REPO"))


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
        detail = {"prod_repo": prod, "dev_repo": dev, "vessel_repo": _vessel_remote()}
    else:
        configured, available = True, True  # local-mode: nothing to configure, no-op-safe
        detail = {"note": "local-mode: no GitHub repo configured; "
                           "expeditions live only in the local store",
                  "vessel_repo": _vessel_remote()}
    return asdict(ModuleStatus(
        slot="sources", kind=kind,
        configured=configured, available=available, docs_url=_docs("sources"),
        detail=detail,
    ))


def _workers_status(anchor) -> dict:
    """WORKERS: who fulfils builder work. Probes THE BUILDER THAT WOULD ACTUALLY RUN, by asking
    `make_builder` — the same factory the rungs call.

    It used to re-derive the choice with its own `api` / else-skill-server branch, which silently
    omitted `claude-code`. A `backend: claude-code` instance was therefore probed for a
    skill-server endpoint and key it neither has nor needs, and reported NEEDS ATTENTION while its
    builder was sitting on PATH working perfectly. A reflection that re-implements the decision it
    is reflecting will drift from it — so it must not re-implement it.

    Construct-only: every backend's `available()` reads env or checks PATH. No network, no spend."""
    cfg = anchor.builder
    try:
        builder = make_builder(anchor)
        ok = bool(builder.available())
        detail = {"fallback": cfg.fallback, "fallback_budget_usd": cfg.fallback_budget_usd,
                  "builder": type(builder).__name__}
    except Exception as e:  # noqa: BLE001 — a builder that cannot be built is an unavailable one
        ok = False
        detail = {"fallback": cfg.fallback, "fallback_budget_usd": cfg.fallback_budget_usd,
                  "error": f"{type(e).__name__}: {str(e)[:110]}"}
    # The kinds this instance will actually accept, straight from the factory that dispatches on
    # them. A screen that keeps its own copy of this list drifts from it, and told a working
    # claude-code instance to check its spelling.
    from fls.llm import BUILDER_BACKENDS
    detail["kinds"] = list(BUILDER_BACKENDS)
    return asdict(ModuleStatus(
        slot="workers", kind=cfg.backend,
        configured=ok, available=ok, docs_url=_docs("workers"),
        detail=detail,
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


def _deploy_status() -> dict:
    """DEPLOY (V10, the 8th slot): WHERE a rung-5a build lands. Formalizing, not inventing — the
    `Deployer` Protocol has been in `rung5.py` since the ship flow was written, and
    `GitHubEnvDeployer` has implemented it for just as long; what was missing is that nothing
    injected one, nothing declared a kind, and nothing reflected it. So the ladder advertised a
    5a rung with a dial and a cost estimate behind machinery that was never connected, and no
    screen could say so.

    Kind is `FLS_DEPLOY_KIND`, else auto-selected: `github-environment` when a repo and token are
    present (the deployer that can actually create a Deployment), `static-dir` when
    `FLS_STAGE_DIR` names a writable directory, else `none`.

    `none` is a real, honest posture, not a fault: an instance with no deploy target simply has
    rung 5a refuse with a reason. It is NOT a hazard the way `identity: none` is — nobody gets
    hurt, work just parks — so it reports as a default, not a warning.

    Paths and environment names are not secrets; the token is a boolean."""
    stage_dir = os.environ.get("FLS_STAGE_DIR") or None
    repo = os.environ.get("FLS_REPO") or None
    token = bool(os.environ.get("GITHUB_TOKEN"))
    # Precedence: an explicit FLS_STAGE_DIR beats repo+token. `FLS_REPO` and `GITHUB_TOKEN` are
    # set for reasons that have nothing to do with deploying (issues are expeditions; the token
    # posts back), so treating their presence as a deploy instruction lets an unrelated change —
    # setting FLS_REPO to fix the sources seam — silently move where a 5a build lands.
    # FLS_STAGE_DIR is only ever set on purpose, so it is the stronger signal.
    kind = os.environ.get("FLS_DEPLOY_KIND") or (
        "static-dir" if stage_dir else ("github-environment" if (repo and token) else "none"))

    if kind == "github-environment":
        configured = bool(repo)
        available = configured and token
        detail = {"stage_environment": "staging", "prod_environment": "production",
                  "repo": repo, "token_present": token}
    elif kind == "static-dir":
        configured = bool(stage_dir)
        # A directory that does not exist or cannot be written is CONFIGURED but UNAVAILABLE —
        # the distinction the four-state chip exists to draw. Never create it here: reflection
        # reads, it does not provision.
        available = bool(stage_dir) and os.path.isdir(stage_dir) and os.access(stage_dir, os.W_OK)
        detail = {"stage_dir": stage_dir,
                  "note": "" if available else "path is missing or not writable by this process"}
    else:
        configured, available = True, False
        detail = {"note": "no deploy target configured; rung 5a refuses with a reason rather "
                          "than parking as though a human were expected"}
    return asdict(ModuleStatus(
        slot="deploy", kind=kind, configured=configured, available=available,
        docs_url=_docs("deploy"), detail=detail,
    ))


def _design_status(anchor) -> dict:
    """DESIGN (V10, the 9th slot): WHERE a rung-2 candidate is saved. The rung-2 builder keeps
    owning the WORK; this seam owns the DESTINATION and its reflection — the same split
    `workers` and `environment` already draw.

    `html` is the reference builder's fragments stored as expedition artifacts: always available,
    needs nothing, and is the honest default. `figma` draws real frames in a real design file and
    needs `FLS_FIGMA_FILE_KEY` (the file) plus `FLS_MCP_CONFIG` (the tools the session gets).

    The file KEY is not a secret — it is the identifier in a URL anyone with access already sees.
    No credential is read here or anywhere in the rung-2 path: the CLI holds the design tool's
    OAuth on the worker host."""
    file_key = os.environ.get("FLS_FIGMA_FILE_KEY") or None
    mcp = os.environ.get("FLS_MCP_CONFIG") or None
    kind = os.environ.get("FLS_DESIGN_KIND") or ("figma" if file_key else "html")
    if kind == "figma":
        configured = bool(file_key)
        available = configured and bool(mcp)
        detail = {"file_key": file_key, "mcp_config_set": bool(mcp),
                  "design_pack": os.environ.get("FLS_DESIGN_PACK") or None}
        if configured and not available:
            detail["note"] = ("a design file is named but no MCP config is set, so no session can "
                              "reach it — rung 2 falls back to the reference builder")
    else:
        configured, available = True, True   # html fragments need nothing
        detail = {"note": "rung-2 candidates are HTML fragments stored as expedition artifacts"}
    return asdict(ModuleStatus(
        slot="design", kind=kind, configured=configured, available=available,
        docs_url=_docs("design"), detail=detail,
    ))


def contradictions(slots: dict) -> list[dict]:
    """Half-wiring, named.

    `describe()` reflects each seam in ISOLATION, which is how an instance with a GitHub token, a
    vessel checkout and no `FLS_REPO` renders as a calm `LOCAL DEFAULT` — the posture the docs
    call "the fresh-install steady state, not an error to chase". It is not that. It is a
    half-wired instance reported as a clean one, which is the same falsehood the feeder screen
    was built to kill, one layer out.

    Each entry names the SEAM a human can act on, so the admin can render it as that card's
    "IS THAT OK?" row rather than inventing a fourth status state. Returns [] on a coherent
    instance — the common case, and the one that must stay silent."""
    out: list[dict] = []
    repo = os.environ.get("FLS_REPO") or None
    token = bool(os.environ.get("GITHUB_TOKEN"))
    vessel = os.environ.get("FLS_VESSEL_REPO") or None

    if token and not repo:
        out.append({"slot": "sources", "reason":
                    "a GitHub token is configured but FLS_REPO is not, so expeditions are staying "
                    "in the local store. Set FLS_REPO to the repo whose issues are expeditions."})
    if vessel and not repo:
        out.append({"slot": "sources", "reason":
                    "FLS_VESSEL_REPO names a checkout the worker writes code into, but this "
                    "instance tracks no source repo, so none of that work becomes an expedition."})
    deploy_kind = (slots.get("deploy") or {}).get("kind")
    if deploy_kind == "none":
        out.append({"slot": "deploy", "reason":
                    "the ladder declares a 5a-staged rung, but no deploy target is configured — "
                    "a build that passes rung 4 has nowhere to go for review."})
    return out


def describe(anchor) -> dict:
    """Reflect all NINE seams as booleans + kinds + non-secret detail. Read-only, no network.
    Consumed by `GET /system`; the admin's Modules cards render exactly this.

    `deploy` and `design` (V10) are the two destinations the seven original seams never covered:
    the seams answer "what implementation fills this engine slot", and neither "where does a
    rung-5a build land" nor "where is a rung-2 candidate saved" is a slot. Both default to kinds
    that describe today's behaviour, so an ANCHOR declaring neither resolves exactly as before."""
    return {
        "auth": _auth_status(),
        "identity": _identity_status(),
        "ideas": _ideas_status(anchor),
        "lenses": _lenses_status(anchor),
        "sources": _sources_status(),
        "workers": _workers_status(anchor),
        "environment": _environment_status(),
        "deploy": _deploy_status(),
        "design": _design_status(anchor),
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


# The IDENTITY Protocol itself lives in `fls.identity` (it carries `Principal`/`Challenge` with
# it, and those are request-path types, not registry types). This module owns only the registry —
# the same split the SOURCES slot already uses for `github_surface`.


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
        brainstorm = self._brainstorm or make_builder(anchor)
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


def _identity_none(**kw):
    from fls.identity import NoneIdentity
    return NoneIdentity()


def _identity_oidc(**kw):
    from fls.identity import OidcIdentity
    return OidcIdentity()


def _identity_github_oauth(**kw):
    from fls.identity import GitHubOAuthIdentity
    return GitHubOAuthIdentity()


def _identity_proxy_header(**kw):
    from fls.identity import ProxyHeaderIdentity
    return ProxyHeaderIdentity()


def _deploy_none():
    """The honest no-op. `deploy(env, ref)` returns False ALWAYS — never True, never a silent
    success. rung 5a reads that as "nowhere to deploy" and refuses with a reason; a deployer that
    returned True here would fake a stage deploy and let a build be marked 5a-staged with nothing
    standing behind it."""
    class _None:
        kind = "none"

        def deploy(self, env: str, ref: str) -> bool:
            return False
    return _None()


def _deploy_static_dir():
    """Write the deployed ref into `FLS_STAGE_DIR/<env>/DEPLOYED`. Deliberately a marker, not a
    build: what to build and how is the vessel's business (`FLS_VESSEL_TEST_CMD` and friends), and
    a deploy seam that shelled out to a build command would be inventing policy this seam does not
    own. The marker is what makes the deploy OBSERVABLE — evidence over claims — and what a
    static-dir instance's own deploy script consumes."""
    class _StaticDir:
        kind = "static-dir"

        def deploy(self, env: str, ref: str, artifact: str | Path | None = None) -> bool:
            base = os.environ.get("FLS_STAGE_DIR") or ""
            if not base:
                return False
            try:
                target = Path(base) / env
                target.mkdir(parents=True, exist_ok=True)
                if artifact:
                    # Publish an ALREADY-BUILT directory. Replacing rather than merging, so a file
                    # deleted in the new build does not survive on the environment as a ghost of
                    # the last one — a stage showing a page the branch no longer has is its own
                    # falsehood. The marker is rewritten afterwards so it always names what is
                    # actually there.
                    import shutil
                    src = Path(artifact)
                    if not src.is_dir():
                        return False
                    for child in target.iterdir():
                        shutil.rmtree(child) if child.is_dir() else child.unlink()
                    shutil.copytree(src, target, dirs_exist_ok=True)
                (target / "DEPLOYED").write_text(f"{ref}\n", encoding="utf-8")
                return True
            except OSError:
                return False           # fail closed: an unwritable path is not a deploy
    return _StaticDir()


def _deploy_github_environment():
    """The existing `GitHubEnvDeployer` — a real GitHub Deployment, Environment-gated for prod.
    Lazy-imported for the same reason the github source factories are: the registry is framework
    core and stays free of web/GitHub deps."""
    from fls.github_surface import GitHubEnvDeployer, RestGitHubClient
    return GitHubEnvDeployer(RestGitHubClient())


def make_deployer(kind: str | None = None):
    """Resolve the DEPLOY seam to something with `.deploy(env, ref) -> bool`.

    Unknown kind -> the `none` deployer, never a crash and never a fallback to something that
    deploys. An instance that typos its kind gets refusals with a reason, which is visible, rather
    than a surprise deploy to a target it did not name."""
    k = kind or _deploy_status()["kind"]
    factory = DEPLOYERS.get(k)
    if factory is None:
        log.warning("unknown FLS_DEPLOY_KIND %r; refusing to deploy (kind=none)", k)
        factory = _deploy_none
    try:
        return factory()
    except Exception as e:  # noqa: BLE001 — an erroring deployer is a non-deployer, never a crash
        log.warning("deploy kind %r failed to construct (%s); refusing to deploy", k, e)
        return _deploy_none()


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
# IDENTITY ships `none` (fail-closed: nobody authenticates) and, once the provider slice lands,
# `oidc` / `github-oauth` / `proxy-header`. A third party can register a kind here exactly as it
# would an idea source — which is the whole reason this is a NEW registry rather than a widened
# `Auth` Protocol: adding to a registry cannot break a module that is already in it.
IDENTITY: dict = {"none": _identity_none, "oidc": _identity_oidc,
                  "github-oauth": _identity_github_oauth,
                  "proxy-header": _identity_proxy_header}
# DEPLOY ships three: `none` (refuses, the honest default), the existing GitHub Deployment path,
# and a plain directory. A vercel/netlify/ssh kind arrives via FLS_MODULES like any other.
DEPLOYERS: dict = {"none": _deploy_none, "static-dir": _deploy_static_dir,
                   "github-environment": _deploy_github_environment}


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

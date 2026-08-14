"""LLM clients — Azure OpenAI judges × Claude builders (cross-family, per ANCHOR).

Two providers behind one thin interface so the harness is testable with stubs (no spend)
and the same code makes real calls once creds are present. A client-side budget guard reads
the ANCHOR Claude hard cap so builder spend cannot exceed it even before the console cap is set
(fail-closed belt-and-suspenders).

Creds resolution (no plaintext committed):
  - Anthropic: env ANTHROPIC_API_KEY, else macOS keychain service `anthropic-api-key`.
  - Azure OpenAI: env AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_KEY (or `az` token).
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field


def _keychain(service: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def anthropic_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or _keychain("anthropic-api-key")


def skill_server_key() -> str | None:
    # the skill-server's flat LANGCHAIN_API_KEY (Bearer / x-api-key). Keychain service is
    # `langchain-api-key` (verified against metatoy-ops/langchain/src/server.js).
    return (os.environ.get("FLS_SKILL_SERVER_KEY") or os.environ.get("LANGCHAIN_API_KEY")
            or _keychain("langchain-api-key"))


@dataclass
class Call:
    """One model call's accounting — the ledger row's cost half.

    Two-column cost model (founder 2026-08-13): `usd` = actual money out the door
    (0 for credit/subscription lanes); `normalized_usd` = the same tokens priced at list
    rate regardless of funding, so lanes stay comparable (utility-per-dollar's denominator).
    `funded_by` names the pool: api (metered) | credits (Azure sponsorship) | subscription
    (skill-server pass-back, P7). savings = normalized_usd - usd.
    """
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0                 # actual spend
    normalized_usd: float = 0.0      # shadow price at list rate (comparable metric)
    funded_by: str = "api"           # api | credits | subscription | none(stub)
    latency_ms: int = 0


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    """Client-side hard cap (reads ANCHOR budgets.claude_api_hard_cap_usd). Fail-closed."""
    claude_cap_usd: float
    spent_usd: float = 0.0
    calls: list[Call] = field(default_factory=list)

    def record(self, call: Call) -> None:
        if call.provider == "anthropic" and self.spent_usd + call.usd > self.claude_cap_usd:
            raise BudgetExceeded(
                f"Claude spend {self.spent_usd + call.usd:.4f} would exceed cap {self.claude_cap_usd}"
            )
        self.spent_usd += call.usd
        self.calls.append(call)


# list prices ($/1M tokens) — actual spend for metered lanes AND the shadow price for
# credit/subscription lanes (normalized_usd), so all lanes report comparable economics
_PRICE = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    # azure openai judges (approx list; funded by credits -> usd=0, normalized>0)
    "gpt-5.4-nano": (0.05, 0.40),
    "gpt-5.4-mini": (0.25, 2.00),
}


def _usd(model: str, tin: int, tout: int) -> float:
    pin, pout = _PRICE.get(model, (3.0, 15.0))
    return (tin * pin + tout * pout) / 1_000_000


class ClaudeBuilder:
    """Anthropic messages client for builder agents (spec/wireframe/demo/MVP)."""

    def __init__(self, model: str = "claude-sonnet-5", guard: BudgetGuard | None = None):
        self.model = model
        self.guard = guard
        self._key = anthropic_key()

    def available(self) -> bool:
        return bool(self._key)

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        if not self._key:
            raise RuntimeError("no Anthropic key (env ANTHROPIC_API_KEY / keychain anthropic-api-key)")
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={"x-api-key": self._key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
        )
        import time as _t
        t0 = _t.monotonic()
        d = json.loads(urllib.request.urlopen(req, timeout=120).read())
        ms = int((_t.monotonic() - t0) * 1000)
        text = "".join(b.get("text", "") for b in d.get("content", []))
        u = d.get("usage", {})
        cost = _usd(self.model, u.get("input_tokens", 0), u.get("output_tokens", 0))
        call = Call("anthropic", self.model, u.get("input_tokens", 0), u.get("output_tokens", 0),
                    usd=cost, normalized_usd=cost, funded_by="api", latency_ms=ms)
        if self.guard:
            self.guard.record(call)
        return text, call


class AzureJudge:
    """Azure OpenAI chat client for judges (admission gate = nano, panels = mini)."""

    def __init__(self, deployment: str = "gpt-5.4-nano"):
        self.deployment = deployment
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://metatoy-kb-openai.openai.azure.com")
        self.key = os.environ.get("AZURE_OPENAI_KEY")

    def available(self) -> bool:
        return bool(self.key)

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        if not self.key:
            raise RuntimeError("no Azure OpenAI key (env AZURE_OPENAI_KEY)")
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
        url = (f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions"
               f"?api-version=2024-10-21")
        req = urllib.request.Request(
            url, data=json.dumps({"messages": msgs, "max_completion_tokens": max_tokens}).encode(),
            headers={"api-key": self.key, "content-type": "application/json"},
        )
        import time as _t
        t0 = _t.monotonic()
        d = json.loads(urllib.request.urlopen(req, timeout=120).read())
        ms = int((_t.monotonic() - t0) * 1000)
        text = d["choices"][0]["message"]["content"]
        u = d.get("usage", {})
        tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        call = Call("azure-openai", self.deployment, tin, tout,
                    usd=0.0, normalized_usd=_usd(self.deployment, tin, tout),
                    funded_by="credits", latency_ms=ms)
        return text, call


class SkillServerError(RuntimeError):
    """Raised when the skill-server is unreachable or returns a non-completion — the signal the
    FallbackBuilder catches to decide whether an (authorized, budgeted) API fallback may fire."""


class SkillServerBuilder:
    """P7 — builder work fulfilled by the studio skill-server (Temporal/LangChain over the local
    `claude -p` CLI on the NAS; memory: langchain-skill-server-nas). NO Anthropic API key and NO
    metered spend — the work rides the founder's Claude subscription. Accounting: usd=0.0 (nothing
    metered), normalized_usd = the same tokens priced at `shadow_model`'s list rate so the
    subscription lane stays comparable to the api lane; funded_by="subscription".

    Real contract (verified against metatoy-ops/langchain/src/server.js + skills.js): the server
    exposes named skills at POST {endpoint}/invoke/{skill}, auth = `Authorization: Bearer <key>`
    (LANGCHAIN_API_KEY), request body = the skill's input, response = {skill, output}. Builder work
    rides a generic `complete` skill (input {prompt, system?} -> the model text). The server does
    NOT report token usage, so the shadow cost is ESTIMATED from text length (~4 chars/token) unless
    a future server response includes a `usage` object. Endpoint + skill name are configurable.
    """

    def __init__(self, shadow_model: str = "claude-haiku-4-5-20251001",
                 endpoint: str | None = None, skill: str = "complete",
                 guard: BudgetGuard | None = None):
        self.shadow_model = shadow_model
        self.skill = skill
        self.endpoint = (endpoint or os.environ.get("FLS_SKILL_SERVER")
                         or "https://langchain.n8plusus.com").rstrip("/")
        self.guard = guard  # subscription calls don't count against the claude cap, but recorded
        self._key = skill_server_key()

    def available(self) -> bool:
        return bool(self._key)

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        if not self._key:
            raise SkillServerError("no skill-server key (env LANGCHAIN_API_KEY / keychain langchain-api-key)")
        body: dict = {"prompt": prompt, "max_tokens": max_tokens}
        if system:
            body["system"] = system
        req = urllib.request.Request(
            f"{self.endpoint}/invoke/{self.skill}", data=json.dumps(body).encode(),
            # explicit UA: Cloudflare's bot-fight WAF 403s the default "Python-urllib/*" UA
            # (verified 2026-08-13). Any non-library UA passes; keep it identifiable.
            headers={"authorization": f"Bearer {self._key}", "x-api-key": self._key,
                     "content-type": "application/json", "user-agent": "fls-engine/0.1"},
        )
        import time as _t
        t0 = _t.monotonic()
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=180).read())
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise SkillServerError(f"skill-server unreachable: {e}") from e
        ms = int((_t.monotonic() - t0) * 1000)
        # server wraps skill output as {skill, output}; support {text} + a raw string too
        text = d.get("output") if isinstance(d, dict) else d
        if isinstance(text, dict):
            text = text.get("text") or text.get("output") or json.dumps(text)
        if not isinstance(text, str):
            text = d.get("text") if isinstance(d, dict) else None
        if not isinstance(text, str):
            raise SkillServerError(f"skill-server returned no text: {d!r}")
        u = d.get("usage", {}) if isinstance(d, dict) else {}
        # estimate tokens when the server doesn't report usage (~4 chars/token)
        tin = u.get("input_tokens") or (len(prompt) + len(system or "")) // 4
        tout = u.get("output_tokens") or len(text) // 4
        # subscription lane: nothing metered (usd=0), but shadow-price for the comparable column
        call = Call("skill-server", self.shadow_model, tin, tout,
                    usd=0.0, normalized_usd=_usd(self.shadow_model, tin, tout),
                    funded_by="subscription", latency_ms=ms)
        if self.guard:
            self.guard.record(call)  # usd=0 -> never trips the cap, but lands in the ledger
        return text, call


class FallbackBuilder:
    """Wraps a primary builder (skill-server) with an authorized, budgeted fallback (api).

    Guardrails (P7 v2 persona findings):
      - fallback must be AUTHORIZED (fallback="api") before it can ever fire;
      - fallback spend is capped per run (fallback_budget_usd): a new fallback call is refused
        once cumulative fallback spend has REACHED the cap (checked before firing — at most one
        call's worth of overshoot, since a call's exact cost isn't known until it returns);
      - per-run pin: once a run falls back, it STAYS on api for the rest of the run (no flapping
        that would scatter a single climb across two providers mid-flight).
    Every returned Call already carries funded_by, so the ledger shows exactly which lane paid.
    """

    def __init__(self, primary: SkillServerBuilder, fallback: ClaudeBuilder | None,
                 fallback_budget_usd: float = 0.0, pin: str = "per-run"):
        self.primary = primary
        self.fallback = fallback
        self.fallback_budget_usd = fallback_budget_usd
        self.pin = pin
        self._pinned_to_fallback = False
        self._fallback_spent = 0.0

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        if not self._pinned_to_fallback:
            try:
                return self.primary.complete(prompt, max_tokens=max_tokens, system=system)
            except SkillServerError:
                if self.fallback is None:
                    raise  # fallback not authorized -> fail closed, park the expedition
                # authorized: pin for the rest of the run (if configured) and fall through
                if self.pin == "per-run":
                    self._pinned_to_fallback = True
        if self.fallback is None:
            raise SkillServerError("skill-server down and no api fallback authorized")
        if self._fallback_spent >= self.fallback_budget_usd:
            raise BudgetExceeded(
                f"fallback (api) spend {self._fallback_spent:.4f} at cap {self.fallback_budget_usd}"
            )
        text, call = self.fallback.complete(prompt, max_tokens=max_tokens, system=system)
        self._fallback_spent += call.usd
        return text, call


def make_builder(anchor, guard: BudgetGuard | None = None):
    """Factory: build the right builder from ANCHOR's `builder` block (P7).

    backend=api          -> ClaudeBuilder (historical behaviour)
    backend=skill-server -> SkillServerBuilder, optionally wrapped in FallbackBuilder when
                            fallback=api is authorized.
    """
    cfg = anchor.builder
    if cfg.backend == "api":
        return ClaudeBuilder(guard=guard)
    primary = SkillServerBuilder(shadow_model=cfg.shadow_model, guard=guard)
    if cfg.fallback == "api":
        fb = ClaudeBuilder(guard=guard)
        return FallbackBuilder(primary, fb, cfg.fallback_budget_usd, cfg.fallback_pin)
    return FallbackBuilder(primary, None, cfg.fallback_budget_usd, cfg.fallback_pin)

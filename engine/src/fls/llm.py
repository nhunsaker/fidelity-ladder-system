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

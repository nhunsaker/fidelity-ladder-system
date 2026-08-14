"""ANCHOR parsing + validation — the keystone the whole system reads from.

The ANCHOR.md file carries a fenced ```anchor YAML block; everything else is human prose.
This module extracts and validates that block into a typed model. P0 verify target:
`Anchor.load(path)` succeeds on the demo ANCHOR.md with altitude + cost fields present.

Tighten-only cascade is enforced elsewhere (harness), but the model exposes the primitives.
"""
from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_ANCHOR_BLOCK = re.compile(r"```anchor\s*\n(.*?)\n```", re.DOTALL)


_SECTION_MAP = {  # console section id -> (yaml key, model field types)
    "funnel": "funnel",
    "budgets": "budgets",
    "demote": "autonomy_demote",
}


def apply_anchor_edits(anchor_text: str, section: str, edits: dict) -> tuple[str, Anchor]:
    """Apply console edits to the machine block and RE-VALIDATE the whole constitution.
    Returns (new_anchor_md_text, validated_anchor). Raises ValueError/ValidationError on any
    invalid edit — the caller never writes an invalid ANCHOR (edits are PRs, never live-pokes).
    """
    if section not in _SECTION_MAP:
        raise ValueError(f"section '{section}' is not console-editable")
    m = _ANCHOR_BLOCK.search(anchor_text)
    if not m:
        raise ValueError("no anchor block")
    data = yaml.safe_load(m.group(1))
    target = data.setdefault(_SECTION_MAP[section], {})
    for k, v in edits.items():
        if v in (None, ""):
            continue
        try:  # numeric coercion (console inputs arrive as strings)
            v = int(v) if str(v).lstrip("-").isdigit() else float(v)
        except ValueError:
            pass
        target[k] = v
    validated = Anchor.model_validate(data)  # the whole constitution must still hold
    new_block = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).rstrip()
    new_text = anchor_text[: m.start(1)] + new_block + anchor_text[m.end(1):]
    return new_text, validated


def guardrails_prose(anchor_text: str) -> str:
    """The human header of ANCHOR.md (north star + non-negotiables) — everything before the
    machine block. Injected into feeder ideation prompts (P4) so the guardrails shape ideas, not
    just gate them, and passed to the admission summary. Same slice adjudicator._anchor_summary uses.
    """
    return anchor_text.split("```anchor")[0].strip()


class Verdict(StrEnum):
    admit = "admit"
    dock = "dock"
    needs_human = "needs-human"


class Dial(StrEnum):
    propose_only = "propose-only"
    human_picks = "human-picks"
    auto_advance = "auto-advance-with-audit"
    autonomous = "autonomous"


# dial ordering for the tighten-only cascade (index 0 = tightest)
DIAL_ORDER = [Dial.propose_only, Dial.human_picks, Dial.auto_advance, Dial.autonomous]


class AdjudicatorCost(BaseModel):
    max_tokens: int
    max_calls: int


class Adjudicator(BaseModel):
    kind: str
    model: str
    cost: AdjudicatorCost
    output_contract: list[str]

    @field_validator("output_contract")
    @classmethod
    def _contract_has_verdict(cls, v: list[str]) -> list[str]:
        if "verdict" not in v or "reasoning" not in v:
            raise ValueError("adjudicator output_contract must include verdict + reasoning")
        return v


class BuilderConfig(BaseModel):
    """P7 — how builder work is fulfilled. Default keeps the historical behaviour (metered
    Anthropic API), so an ANCHOR without a `builder:` block parses and behaves as before."""
    backend: str = "api"                 # api | skill-server
    shadow_model: str = "claude-haiku-4-5-20251001"  # list-price anchor for the subscription lane
    fallback: str = "none"               # api | none
    fallback_budget_usd: float = 0.0     # hard ceiling on fallback spend per run
    fallback_pin: str = "per-run"        # per-run = once fallen back, stay fallen back


class Funnel(BaseModel):
    auto_build: int
    interactive_demos: int
    wireframes: str | int  # "all" or an int
    queue: int = 0


class RungPolicy(BaseModel):
    dial: Dial
    est_usd: float


class Budgets(BaseModel):
    per_expedition_ceiling_usd: float
    claude_api_hard_cap_usd: float
    azure_resource_group: str


class DemoteTrigger(BaseModel):
    agreement_threshold: float
    window: int
    action: str


class FeederParams(BaseModel):
    """P4 — the studio-brainstorm feeder's ANCHOR-set knobs. The feeder is fully governed by
    these; it holds no policy of its own."""
    scope: str = ""
    guardrails_into_prompt: bool = True   # non-negotiables shape ideation, not just the gate
    cost_envelope_usd: float = 5.00       # per feeder run (bounds the shadow cost on the sub lane)
    volume_cap: int = 5                   # top-N ideas filed per run
    cadence: str = "manual"
    model_tier: str = "economy"
    context_cap_tokens: int = 30000       # what the workspace checkout may feed the prompt


class Anchor(BaseModel):
    version: int
    mode: str
    adjudicator: Adjudicator
    builder: BuilderConfig = Field(default_factory=BuilderConfig)
    idea_sources: list[dict]
    funnel: Funnel
    rungs: dict[str, RungPolicy]
    budgets: Budgets
    autonomy_demote: DemoteTrigger
    altitude_allowed: list[str] = Field(min_length=1)

    @classmethod
    def load(cls, path: str | Path) -> Anchor:
        text = Path(path).read_text(encoding="utf-8")
        m = _ANCHOR_BLOCK.search(text)
        if not m:
            raise ValueError(f"no fenced ```anchor block found in {path}")
        data = yaml.safe_load(m.group(1))
        return cls.model_validate(data)

    def rung(self, key: str) -> RungPolicy:
        return self.rungs[key]

    def feeder(self) -> FeederParams:
        """The studio-brainstorm feeder's params (P4), or defaults if no feeder source declared."""
        for src in self.idea_sources:
            if src.get("kind") == "feeder":
                return FeederParams.model_validate(src.get("params", {}))
        return FeederParams()

    def can_tighten(self, current: Dial, proposed: Dial) -> bool:
        """A rung/expedition may only move a dial toward tighter (or equal), never looser."""
        return DIAL_ORDER.index(proposed) <= DIAL_ORDER.index(current)

"""ANCHOR parsing + validation — the keystone the whole system reads from.

The ANCHOR.md file carries a fenced ```anchor YAML block; everything else is human prose.
This module extracts and validates that block into a typed model. P0 verify target:
`Anchor.load(path)` succeeds on the demo ANCHOR.md with altitude + cost fields present.

Tighten-only cascade is enforced elsewhere (harness), but the model exposes the primitives.
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_ANCHOR_BLOCK = re.compile(r"```anchor\s*\n(.*?)\n```", re.DOTALL)


class Verdict(str, Enum):
    admit = "admit"
    dock = "dock"
    needs_human = "needs-human"


class Dial(str, Enum):
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


class Anchor(BaseModel):
    version: int
    mode: str
    adjudicator: Adjudicator
    idea_sources: list[dict]
    funnel: Funnel
    rungs: dict[str, RungPolicy]
    budgets: Budgets
    autonomy_demote: DemoteTrigger
    altitude_allowed: list[str] = Field(min_length=1)

    @classmethod
    def load(cls, path: str | Path) -> "Anchor":
        text = Path(path).read_text(encoding="utf-8")
        m = _ANCHOR_BLOCK.search(text)
        if not m:
            raise ValueError(f"no fenced ```anchor block found in {path}")
        data = yaml.safe_load(m.group(1))
        return cls.model_validate(data)

    def rung(self, key: str) -> RungPolicy:
        return self.rungs[key]

    def can_tighten(self, current: Dial, proposed: Dial) -> bool:
        """A rung/expedition may only move a dial toward tighter (or equal), never looser."""
        return DIAL_ORDER.index(proposed) <= DIAL_ORDER.index(current)

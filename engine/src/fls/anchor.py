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
from typing import Literal

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


class CouncilConfig(BaseModel):
    """V6 — knobs for `kind: council`. Only read when the adjudicator kind selects council;
    an ANCHOR without this block (or with `kind: single-llm`) parses and behaves identically
    to before this field existed."""
    size: int = 3                                                  # member judges polled
    combine: Literal["majority", "unanimous-to-admit"] = "majority"
    model: str | None = None    # overrides adjudicator.model for every seat; None = inherit


class Adjudicator(BaseModel):
    kind: str = "single-llm"    # single-llm (v1, default) | council (V6 pluggable adjudicators)
    model: str
    cost: AdjudicatorCost
    output_contract: list[str]
    council: CouncilConfig = Field(default_factory=CouncilConfig)  # only read when kind == council

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
    daily_usd: float | None = None   # V6 #3 — optional anchor-level daily cap; None = unbounded
    # (purely additive; an ANCHOR without it parses identically to before this field existed)


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
    grounding: str = ""                   # V3 grounding pack folded into ideation when set (empty = off)


class LensParams(BaseModel):
    """P2a — a managed lens's ANCHOR-set knobs. Mirrors FeederParams: the lens is fully governed
    by these; it holds no policy of its own. An ANCHOR with no matching (or no `lenses:` block
    at all) parses identically and Anchor.lens() falls back to these defaults."""
    mode: Literal["generative", "audit-first"] = "audit-first"
    panel: str = ""
    target_vessel: str = ""
    cadence: str = "manual"
    sink_label: str = ""
    cost_envelope_usd: float = 5.00      # per lens run (bounds shadow/API cost)
    volume_cap: int = 5                  # top-N findings/ideas filed per run


class VesselBudgetOverride(BaseModel):
    """V6 #3 — a vessel's tighten-only budget override. Both fields optional/additive; an unset
    field means "inherit the anchor default", never "unbounded"."""
    daily_usd: float | None = None
    per_idea_usd: float | None = None


class VesselRungPolicyOverride(BaseModel):
    """V6 #3 — a vessel's tighten-only rung-policy override. `max_rung` caps how far an
    expedition under this vessel may climb; `est_usd_by_rung` tightens per-rung cost estimates
    (keyed like `Anchor.rungs`, e.g. "4-mvp", "5-flagged", "5a-staged", "5b-prod")."""
    max_rung: int | None = None
    est_usd_by_rung: dict[str, float] = Field(default_factory=dict)


class VesselGovernance(BaseModel):
    """V6 #3 — FROZEN CONTRACT (build-plan-v6.md). An optional per-vessel governance override.
    Every field cascades **tighten-only** over the anchor defaults via `Anchor.effective_governance`
    (reusing `Anchor.can_tighten` for dials): a vessel may only make things stricter — lower a
    budget, lower `max_rung`, move a dial tighter — never loosen past what the anchor allows. A
    vessel without a `governance:` block parses identically (purely additive, back-compat)."""
    dials: dict[str, Dial] = Field(default_factory=dict)          # rung-key -> Dial override
    budget: VesselBudgetOverride | None = None
    rung_policy: VesselRungPolicyOverride | None = None


class EffectiveGovernance(BaseModel):
    """V6 #3 — the resolved governance for a vessel (or the bare anchor defaults when the vessel
    has no override / no vessel is named): tighten(anchor_default, vessel_override)."""
    dials: dict[str, Dial] = Field(default_factory=dict)
    daily_usd: float | None = None
    per_idea_usd: float
    max_rung: int
    est_usd_by_rung: dict[str, float] = Field(default_factory=dict)


class Vessel(BaseModel):
    """V3 — a context pack sitting between the north star and an expedition (Ng's concrete cut:
    NOT a per-vessel-dials layer). It names the surface being worked (team/app/site/sprint/topic)
    plus the grounding an expedition needs to explore concretely — paths, standards, refs. An
    ANCHOR without a `vessels:` block parses identically (slim mode); the block is purely additive.

    V6 #3 adds an OPTIONAL `governance` override (see `VesselGovernance`) — still not a general
    per-vessel-dials layer by default; a vessel only gains dials/budget/rung-policy teeth when it
    explicitly declares `governance:`, and even then only to tighten, never loosen."""
    name: str
    kind: Literal["team", "app", "site", "sprint", "topic"]
    description: str = ""
    paths: list[str] = Field(default_factory=list)
    standards: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    goal: str | None = None    # V4 — purely additive; overrides anchor-level goal when set
    audit_scope: list[str] = Field(default_factory=list)   # V4 — path globs an audit is confined to;
    # purely additive — a vessel without it parses identically (see effective_audit_scope)
    governance: VesselGovernance | None = None   # V6 #3 — purely additive; see VesselGovernance

    def effective_audit_scope(self) -> list[str]:
        """Effective audit scope: the vessel's own `audit_scope` when set, else its `paths`
        (so a vessel that already declares paths gets sensible scoping for free), else []."""
        if self.audit_scope:
            return self.audit_scope
        return self.paths


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
    vessels: list[Vessel] = Field(default_factory=list)   # V3 context packs (empty = slim mode)
    default_vessel: str | None = None                     # which vessel an expedition inherits by default
    goal: str | None = None    # V4 — top-level goal; an ANCHOR without it parses identically
    lenses: list[dict] = Field(default_factory=list)      # P2a — declared lens instances (kind + params); empty = no lenses configured

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

    def vessel(self, name: str | None = None) -> Vessel | None:
        """Resolve the named vessel, or the default_vessel when name is None. Returns None if no
        vessel matches (or none is declared) — callers fail-open to no grounding, never a stub."""
        target = name or self.default_vessel
        if target is None:
            return None
        return next((v for v in self.vessels if v.name == target), None)

    def resolved_goal(self, vessel_name: str | None = None) -> str | None:
        """Effective goal: the resolved vessel's `goal` overrides the anchor-level `goal` when
        set; falls back to the anchor goal, then None. Never raises — fail-open like vessel()."""
        v = self.vessel(vessel_name)
        if v is not None and v.goal:
            return v.goal
        return self.goal

    def feeder(self) -> FeederParams:
        """The studio-brainstorm feeder's params (P4), or defaults if no feeder source declared."""
        for src in self.idea_sources:
            if src.get("kind") == "feeder":
                return FeederParams.model_validate(src.get("params", {}))
        return FeederParams()

    def lens(self, kind: str) -> LensParams:
        """A declared lens's params (P2a), matched by `kind` in the `lenses:` list, or defaults
        if absent/no matching entry. Additive/back-compat: an ANCHOR with no `lenses:` block (or
        no entry for this kind) parses and resolves identically to before this field existed."""
        for entry in self.lenses:
            if entry.get("kind") == kind:
                return LensParams.model_validate(entry.get("params", {}))
        return LensParams()

    def can_tighten(self, current: Dial, proposed: Dial) -> bool:
        """A rung/expedition may only move a dial toward tighter (or equal), never looser."""
        return DIAL_ORDER.index(proposed) <= DIAL_ORDER.index(current)

    def effective_governance(self, vessel_name: str | None = None) -> EffectiveGovernance:
        """V6 #3 — resolve effective governance = tighten(anchor_default, vessel_override).

        Anchor defaults: every `rungs` dial, `budgets.per_expedition_ceiling_usd` as the
        per-idea ceiling, `budgets.daily_usd` as the daily cap (None = unbounded when the
        anchor hasn't set one), the top of the ladder (`RUNG_FLAG`, imported lazily to avoid a
        hard funnel.py dependency at module load) as `max_rung`, and each rung's `est_usd`.

        A vessel's `governance` override is applied field-by-field, but ONLY when it tightens:
        a dial move that isn't `can_tighten`, or a budget/est_usd/max_rung that is larger than
        the anchor default, is a loosen attempt and is CLAMPED back to the anchor value rather
        than applied or raised — same fail-closed-safe posture as the rest of this module.
        Never raises; a vessel with no `governance` block (or no matching vessel) resolves to
        the bare anchor defaults, byte-for-byte.
        """
        from fls.funnel import (
            RUNG_FLAG,  # local import: anchor.py must not hard-depend on funnel.py
        )

        eg = EffectiveGovernance(
            dials={key: policy.dial for key, policy in self.rungs.items()},
            daily_usd=self.budgets.daily_usd,
            per_idea_usd=self.budgets.per_expedition_ceiling_usd,
            max_rung=RUNG_FLAG,
            est_usd_by_rung={key: policy.est_usd for key, policy in self.rungs.items()},
        )

        v = self.vessel(vessel_name)
        if v is None or v.governance is None:
            return eg
        gov = v.governance

        for key, proposed in gov.dials.items():
            current = eg.dials.get(key)
            if current is None or self.can_tighten(current, proposed):
                eg.dials[key] = proposed
            # else: loosen attempt — clamp, keep the (already-tighter) anchor value

        if gov.budget is not None:
            if gov.budget.daily_usd is not None:
                if eg.daily_usd is None or gov.budget.daily_usd <= eg.daily_usd:
                    eg.daily_usd = gov.budget.daily_usd
                # else: clamp — keep the tighter anchor daily_usd
            if gov.budget.per_idea_usd is not None:
                if gov.budget.per_idea_usd <= eg.per_idea_usd:
                    eg.per_idea_usd = gov.budget.per_idea_usd
                # else: clamp — keep the anchor per-idea ceiling

        if gov.rung_policy is not None:
            rp = gov.rung_policy
            if rp.max_rung is not None:
                if rp.max_rung <= eg.max_rung:
                    eg.max_rung = rp.max_rung
                # else: clamp — keep the anchor max_rung
            for key, usd in rp.est_usd_by_rung.items():
                baseline = eg.est_usd_by_rung.get(key)
                if baseline is None or usd <= baseline:
                    eg.est_usd_by_rung[key] = usd
                # else: clamp — keep the anchor est_usd for this rung

        return eg

    def rung5_policy(self, sub: Literal["5a", "5b"]) -> RungPolicy:
        """V6 #2 — the 5a (staged-behind-flag) / 5b (prod-promoted) sub-rung policy. Looks for a
        dedicated `"5a-staged"` / `"5b-prod"` entry in `rungs:`; falls back to the legacy
        `"5-flagged"` entry when an ANCHOR hasn't been split yet (back-compat: every pre-v0.6
        ANCHOR resolves identically for both sub-rungs)."""
        key = "5a-staged" if sub == "5a" else "5b-prod"
        return self.rungs.get(key) or self.rungs["5-flagged"]

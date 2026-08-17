"""Rung 5 — the ship flow (hard gate). Draft PR behind a flag -> smoke self-check ->
stage auto-deploy -> Environment-gated prod promotion -> staged flag flip. Never auto-ships.

The two-layer safety (Wang/sketch §4e): (1) the GitHub Environment protection rule gates
stage->prod promotion (a required human reviewer); (2) the feature flag is OFF in prod until
sign-off, so even a promoted deploy exposes nothing. Modeled here as logic (a Deployer + an
approval token); the real GitHub Environment/Actions wiring lands with the VM at deploy time.

V6 #2 — rung 5 splits into two finer sub-rungs so ANCHOR policy (and the climb gate) can govern
each independently: **5a** (`RUNG_5A` = "5a-staged") is reached once `ship_to_stage` lands the
change behind the flag in stage; **5b** (`RUNG_5B` = "5b-prod") is reached once `promote_to_prod`
clears the Environment-gated human approval and flips the flag in prod. `ShipResult.sub_rung`
stamps whichever sub-rung the call actually reached (or `None` if it didn't get that far), so a
caller can drive/observe the split without changing the existing call shape. `RUNG_FLAG` (the
legacy, unsplit rung-5 ordinal) is unchanged and still what `Expedition.rung` carries — the split
is additive labeling, not a renumbering (back-compat).

Enforced reviewability (Scott Wu, v0.8 Phase 3): the rung-5 sign-off gate is only as honest as
the package a human is asked to review. `enforce_reviewability` REFUSES (raises
`ReviewabilityRefused`, never a warning that proceeds anyway) a `PRPackage` that either exceeds
the rung's line-budget (the "reviewable in <=10 minutes" bar) or lacks a `walkthrough_url`.
`ship_to_stage_reviewed` wraps `ship_to_stage` with that check as a hard park — the same
ShipResult-returns-a-reason pattern already used for a failed smoke self-check — so a caller
never needs to remember to call the check separately.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from fls.funnel import RUNG_FLAG

if TYPE_CHECKING:
    from fls.rung4 import PRPackage

RUNG_5A = "5a-staged"   # staged behind the flag (ship_to_stage)
RUNG_5B = "5b-prod"     # prod-promoted, flag staged-flipped (promote_to_prod)
LEGACY_RUNG_5 = RUNG_FLAG   # re-exported for callers keying policy off the pre-split ordinal


class Deployer(Protocol):
    def deploy(self, env: str, ref: str) -> bool: ...


@dataclass
class FlagStore:
    """flags.json: {flag: {stage: bool, prod: bool}}. The flag gates exposure per environment."""
    path: str | Path

    def _load(self) -> dict:
        return json.loads(Path(self.path).read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        Path(self.path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def set(self, flag: str, env: str, on: bool) -> None:
        data = self._load()
        data.setdefault(flag, {"stage": False, "prod": False})[env] = on
        self._save(data)

    def get(self, flag: str, env: str) -> bool:
        return bool(self._load().get(flag, {}).get(env))


class ReviewabilityRefused(Exception):
    """Raised by `enforce_reviewability` when a PR package fails the rung-5 sign-off pre-check.
    A refusal, not a warning: the caller must not present this package for human sign-off."""


def _diff_line_count(diff: str) -> int:
    # count changed lines only (unified-diff +/- lines), not context/headers, so a large
    # surrounding context doesn't inflate the reviewability estimate.
    return sum(
        1 for line in (diff or "").splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    )


def enforce_reviewability(pkg: PRPackage, line_budget: int) -> None:
    """Fail-closed pre-check upstream of the rung-5 human sign-off gate (Wu): refuses rather than
    silently presenting a PR nobody could actually review in <=10 minutes, or one with no
    walkthrough to orient the reviewer. Raises `ReviewabilityRefused`; never returns a "just a
    warning" result — callers that want a park-not-raise flow should use
    `ship_to_stage_reviewed`."""
    if not pkg.walkthrough_url or not pkg.walkthrough_url.strip():
        raise ReviewabilityRefused(
            "walkthrough_url is required before rung-5 sign-off — none provided"
        )
    if line_budget > 0:
        lines = _diff_line_count(pkg.diff)
        if lines > line_budget:
            raise ReviewabilityRefused(
                f"diff changes {lines} lines, exceeds the {line_budget}-line rung-5 "
                "reviewability budget (not reviewable in <=10 minutes)"
            )


@dataclass
class ShipResult:
    stage_deployed: bool = False
    smoke_passed: bool = False
    prod_deployed: bool = False
    awaiting_signoff: bool = True
    reason: str = ""
    sub_rung: str | None = None   # V6 #2 — RUNG_5A / RUNG_5B once reached, else None
    reviewability_refused: bool = False   # Wu Phase 3 — enforce_reviewability parked this ship


def ship_to_stage(flag: str, ref: str, flags: FlagStore, deployer: Deployer,
                  smoke) -> ShipResult:
    """Merge -> smoke self-check -> stage auto-deploy, flag ON in stage. Prod stays gated.
    Reaches sub-rung 5a (RUNG_5A) on success."""
    r = ShipResult()
    r.smoke_passed = smoke()                    # pre-reviewer smoke self-check (Ng#4)
    if not r.smoke_passed:
        r.reason = "smoke self-check failed; not deploying to stage"
        return r
    r.stage_deployed = deployer.deploy("stage", ref)
    if r.stage_deployed:
        flags.set(flag, "stage", True)          # exposed in stage only
        r.sub_rung = RUNG_5A
        r.reason = "on stage (rung 5a); awaiting human sign-off for prod (Environment gate + flag)"
    return r


def ship_to_stage_reviewed(pkg: PRPackage, line_budget: int, flag: str, ref: str,
                           flags: FlagStore, deployer: Deployer, smoke) -> ShipResult:
    """`ship_to_stage`, but ENFORCING rung-5 reviewability first (Wu, Phase 3): a PR package that
    exceeds the line-budget or lacks a walkthrough_url is PARKED here — never staged, never put
    in front of the human sign-off gate. This is the entrypoint rung 4 -> rung 5 should use;
    `ship_to_stage` alone stays available for non-PR ships (e.g. a config-only flag flip) that
    have no package to review."""
    try:
        enforce_reviewability(pkg, line_budget)
    except ReviewabilityRefused as e:
        return ShipResult(reason=str(e), reviewability_refused=True)
    return ship_to_stage(flag, ref, flags, deployer, smoke)


def promote_to_prod(flag: str, ref: str, flags: FlagStore, deployer: Deployer,
                    approved_by: str | None) -> ShipResult:
    """Environment protection: prod promotion requires an approver. Then STAGED flag flip.
    Assumes 5a (stage) already happened; reaches sub-rung 5b (RUNG_5B) on success, else stays
    parked at 5a."""
    r = ShipResult(stage_deployed=True, smoke_passed=True, sub_rung=RUNG_5A)
    if not approved_by:
        r.reason = "prod promotion blocked: Environment protection requires a human reviewer"
        return r
    r.prod_deployed = deployer.deploy("prod", ref)
    if r.prod_deployed:
        flags.set(flag, "prod", True)           # staged flag flip AFTER promotion + approval
        r.awaiting_signoff = False
        r.sub_rung = RUNG_5B
        r.reason = f"promoted to prod by {approved_by}; flag flipped on (staged) — rung 5b"
    return r

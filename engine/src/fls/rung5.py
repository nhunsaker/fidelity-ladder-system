"""Rung 5 — the ship flow (hard gate). Draft PR behind a flag -> smoke self-check ->
stage auto-deploy -> Environment-gated prod promotion -> staged flag flip. Never auto-ships.

The two-layer safety (Wang/sketch §4e): (1) the GitHub Environment protection rule gates
stage->prod promotion (a required human reviewer); (2) the feature flag is OFF in prod until
sign-off, so even a promoted deploy exposes nothing. Modeled here as logic (a Deployer + an
approval token); the real GitHub Environment/Actions wiring lands with the VM at deploy time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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


@dataclass
class ShipResult:
    stage_deployed: bool = False
    smoke_passed: bool = False
    prod_deployed: bool = False
    awaiting_signoff: bool = True
    reason: str = ""


def ship_to_stage(flag: str, ref: str, flags: FlagStore, deployer: Deployer,
                  smoke) -> ShipResult:
    """Merge -> smoke self-check -> stage auto-deploy, flag ON in stage. Prod stays gated."""
    r = ShipResult()
    r.smoke_passed = smoke()                    # pre-reviewer smoke self-check (Ng#4)
    if not r.smoke_passed:
        r.reason = "smoke self-check failed; not deploying to stage"
        return r
    r.stage_deployed = deployer.deploy("stage", ref)
    if r.stage_deployed:
        flags.set(flag, "stage", True)          # exposed in stage only
        r.reason = "on stage; awaiting human sign-off for prod (Environment gate + flag)"
    return r


def promote_to_prod(flag: str, ref: str, flags: FlagStore, deployer: Deployer,
                    approved_by: str | None) -> ShipResult:
    """Environment protection: prod promotion requires an approver. Then STAGED flag flip."""
    r = ShipResult(stage_deployed=True, smoke_passed=True)
    if not approved_by:
        r.reason = "prod promotion blocked: Environment protection requires a human reviewer"
        return r
    r.prod_deployed = deployer.deploy("prod", ref)
    if r.prod_deployed:
        flags.set(flag, "prod", True)           # staged flag flip AFTER promotion + approval
        r.awaiting_signoff = False
        r.reason = f"promoted to prod by {approved_by}; flag flipped on (staged)"
    return r

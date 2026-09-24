"""The smoke ladder, run under pytest so it cannot rot unnoticed.

It is a deploy gate first and a test second, but a gate that only ever runs on the box is a gate
nobody edits safely.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# The suite is run from the repo root (`pytest engine/tests`), where `engine/` is not on the path
# — but the smoke ladder is also a standalone deploy gate run from `engine/`, so it has to import
# both ways. Cheaper than a conftest that only exists for this one file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.smoke.ladder import run  # noqa: E402


def test_every_seam_is_green(tmp_path):
    checks = run(tmp_path)
    bad = [f"{c.seam}: {c.detail}" for c in checks if not c.ok]
    assert not bad, "broken seams:\n  " + "\n  ".join(bad)
    assert len(checks) >= 10, "seams were removed rather than fixed"


def test_it_finishes_well_inside_the_deploy_budget(tmp_path):
    """Two minutes is the budget. Past it the gate gets skipped on deploys, and a skipped gate is
    not a gate — so the runtime is asserted rather than hoped for."""
    t0 = time.monotonic()
    run(tmp_path)
    assert time.monotonic() - t0 < 60, "the smoke ladder got slow enough to be skipped"

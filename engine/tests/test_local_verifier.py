"""P2: the REAL verifier runs actual `node --test` and classifies correctly.
Skips if node is unavailable (keeps CI robust); on GitHub ubuntu runners node is present."""
import shutil
from pathlib import Path

import pytest

from fls.local_verifier import LocalVerifier
from fls.verifier import Outcome

NODE = shutil.which("node")
ACME = Path(__file__).resolve().parents[2] / "demo-app"
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def _write(d: Path, body: str):
    (d / "t.test.mjs").write_text(body, encoding="utf-8")


def test_passing_suite_is_passed():
    r = LocalVerifier(["node", "--test"]).verify(str(ACME))
    assert r.outcome == Outcome.passed
    assert "pass 2" in r.evidence["test_output"]


def test_failing_suite_is_mechanical(tmp_path):
    _write(tmp_path, "import {test} from 'node:test';import a from 'node:assert';"
                     "test('x',()=>a.equal(1,2));")
    r = LocalVerifier(["node", "--test"]).verify(str(tmp_path))
    assert r.outcome == Outcome.mechanical
    assert r.evidence["tests_failed"]


def test_acceptance_marker_is_design(tmp_path):
    _write(tmp_path, "import {test} from 'node:test';"
                     "test('acc',()=>{console.log('ACCEPTANCE_UNMET: cmd-k did not focus from modal');"
                     "throw new Error('unmet');});")
    r = LocalVerifier(["node", "--test"]).verify(str(tmp_path))
    assert r.outcome == Outcome.design
    assert "modal" in r.detail

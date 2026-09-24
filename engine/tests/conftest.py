"""Shared fixtures — and the one path every ANCHOR-reading test needs.

`Path("ANCHOR.md")` is relative to the WORKING DIRECTORY, and this repo is run from two of them:
the runbook and CLAUDE.md say `pytest engine/tests` from the root, while `.github/workflows/ci.yml`
sets `working-directory: engine`. So fourteen tests that loaded the shipped ANCHOR by a bare
relative path passed locally and had never once passed in CI — `FileNotFoundError: 'ANCHOR.md'`,
every run, for as long as the workflow has existed.

Resolved from this file instead, so it does not matter where pytest was started.
"""
from pathlib import Path

import pytest

#: The shipped example ANCHOR at the repository root (NOT an instance's — that lives in env).
ANCHOR_MD = Path(__file__).resolve().parents[2] / "ANCHOR.md"


@pytest.fixture(scope="session")
def anchor_md() -> Path:
    return ANCHOR_MD

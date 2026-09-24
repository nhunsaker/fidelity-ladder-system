"""A throwaway vessel for the smoke ladder.

Not the real one. A smoke test that mutates `fls-harness-demo` is a smoke test nobody runs twice —
and one that opens pull requests against it is worse. This is a handful of files, one commit, and a
check command that is honestly green.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def git(cwd, *a):
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, check=False)


def make_vessel(root: Path) -> Path:
    """A minimal git repo shaped like the real vessel: a flags file, a component, a test command."""
    r = Path(root) / "vessel"
    (r / "src" / "components").mkdir(parents=True, exist_ok=True)
    (r / "tests").mkdir(parents=True, exist_ok=True)

    (r / "flags.json").write_text(json.dumps({
        "_comment": "one entry per surface; every new surface ships off in BOTH until a human "
                    "turns it on",
    }, indent=2) + "\n")
    (r / "package.json").write_text(json.dumps({
        "name": "smoke-vessel", "private": True,
        # Honestly green, and cheap. The smoke ladder is testing the seams, not a test runner.
        "scripts": {"test": "true"},
    }, indent=2) + "\n")
    (r / "src" / "components" / "ActionBar.tsx").write_text(
        "export function ActionBar() {\n  return null\n}\n")
    (r / "README.md").write_text("# smoke vessel\n\nA fixture. Nothing here is real.\n")

    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "smoke@fixture")
    git(r, "config", "user.name", "smoke")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "vessel base")
    return r

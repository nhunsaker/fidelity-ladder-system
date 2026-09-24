"""Build a pushed ref and hand the built site to the deploy seam.

The `static-dir` deployer publishes FILES only when it is given an already-built directory; called
with a ref alone it writes a seven-byte `DEPLOYED` marker and returns True. Rung 5a knew that and
built first (`LiveRunner._build_for_deploy`). The ready-for-review webhook did not, so it wrote a
marker, reported "🚀 Staged from a9793ac", and left the stage site serving bytes from hours
earlier — a deploy that claimed to have happened and had not, which is the one thing this system
exists to refuse.

Rung 5a builds from the rung-4 worktree, which is the right source for a rung-4 build and the
wrong one here: a reviewer can push to the branch after the run finished, and the worktree does
not have those commits. This builds from the COMMIT GITHUB NAMED, in a throwaway worktree, so
what gets published is what the pull request actually says it is.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("fls.stage")


def build_ref(sha: str, *, repo_dir: str | None = None, cmd: str | None = None,
              out_dir: str | None = None, timeout_s: int = 1200) -> tuple[Path | None, str | None]:
    """`(built directory, refusal)` for one commit. Exactly one of the two is ever set.

    Nothing here guesses: with no build command declared, an instance is in the mode this seam
    has always had — record the ref, publish no files — and that is a different answer from a
    failure, so it returns `(None, None)` and the caller says which.
    """
    repo = repo_dir or os.environ.get("FLS_VESSEL_REPO") or ""
    build = cmd or os.environ.get("FLS_VESSEL_BUILD_CMD") or ""
    rel = out_dir or os.environ.get("FLS_VESSEL_BUILD_DIR") or ""
    if not repo or not build or not rel:
        return None, None
    if not Path(repo, ".git").exists():
        return None, f"no vessel checkout at {repo}"

    work = Path(tempfile.mkdtemp(prefix="fls-stage-"))
    tree = work / "wt"
    try:
        # Fetch by SHA rather than by branch: the branch may have moved again while this ran, and
        # publishing a commit the pull request did not name would be the same falsehood in a
        # subtler form.
        fetch = _git(repo, "fetch", "--quiet", "origin", sha, timeout=300)
        if fetch.returncode != 0:
            _git(repo, "fetch", "--quiet", "origin", timeout=300)
        add = _git(repo, "worktree", "add", "--detach", str(tree), sha, timeout=300)
        if add.returncode != 0:
            return None, f"could not check out {sha[:7]}: {_tail(add)}"

        r = subprocess.run(build, cwd=tree, shell=True, capture_output=True, text=True,
                           timeout=timeout_s)
        if r.returncode != 0:
            return None, f"the vessel build failed: {_tail(r)}"
        built = tree / rel
        if not built.is_dir():
            return None, f"the build left no {rel}/ to publish"

        # Copied out of the worktree before it is removed, because the caller publishes AFTER this
        # returns and a directory inside a worktree we are about to delete is not an artifact.
        keep = work / "site"
        shutil.copytree(built, keep)
        return keep, None
    except subprocess.TimeoutExpired:
        return None, f"the vessel build timed out after {timeout_s // 60} minutes"
    except Exception as e:  # noqa: BLE001 — a build that blew up published nothing
        return None, f"the build could not run: {str(e)[:140]}"
    finally:
        # The worktree always goes; the copied site is the caller's to clean up.
        _git(repo, "worktree", "remove", "--force", str(tree), timeout=120)


def _git(repo: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          timeout=timeout, check=False)


def _tail(r: subprocess.CompletedProcess) -> str:
    lines = (r.stderr or r.stdout or "").strip().splitlines()
    return (lines[-1] if lines else "")[:140]

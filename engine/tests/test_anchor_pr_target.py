"""An ANCHOR edit opens a PR against the repo the ANCHOR lives in — not FLS_REPO.

Found 2026-09-11 while designing the console screen that triggers it. `open_anchor_pr` defaulted
to `repo=REPO` (FLS_REPO), which is the repo whose ISSUES are expeditions. On this very instance
the constitution lives in acme/governance while FLS_REPO is acme/vessel, so
"Open the PR" would have branched off the product repo — and had that repo contained an ANCHOR.md,
it would have committed the instance's constitution into it.

Three repos, three jobs, and conflating any two of them is a governance bug:
    FLS_REPO         issues are expeditions
    FLS_VESSEL_REPO  code lands here
    ANCHOR's own     the constitution is versioned here
"""
from __future__ import annotations

import inspect

import pytest

from fls import modules


def _checkout(tmp_path, url):
    git = tmp_path / ".git"
    git.mkdir(exist_ok=True)
    (git / "config").write_text(f'[remote "origin"]\n\turl = {url}\n')
    return tmp_path


def test_the_anchor_repo_comes_from_the_anchor_s_own_checkout(tmp_path):
    root = _checkout(tmp_path, "https://github.com/acme/governance.git")
    assert modules.anchor_remote(root / "ANCHOR.md") == "acme/governance"


def test_it_is_not_fls_repo(tmp_path, monkeypatch):
    """The actual shape of the bug: FLS_REPO set to something else entirely must not leak in."""
    monkeypatch.setenv("FLS_REPO", "acme/vessel")
    root = _checkout(tmp_path, "https://github.com/acme/governance.git")
    assert modules.anchor_remote(root / "ANCHOR.md") == "acme/governance"


@pytest.mark.parametrize("path", [None, ""])
def test_no_anchor_path_means_no_repo(path):
    assert modules.anchor_remote(path) is None


def test_an_anchor_outside_a_checkout_has_no_repo(tmp_path):
    assert modules.anchor_remote(tmp_path / "ANCHOR.md") is None


def test_open_anchor_pr_has_no_default_repo():
    """The default WAS the bug. A default that is right on some instances and silently wrong on
    others is worse than no default — the caller must say where the constitution lives."""
    from fls.github_surface import open_anchor_pr
    sig = inspect.signature(open_anchor_pr)
    assert sig.parameters["repo"].default is inspect.Parameter.empty


def test_propose_refuses_rather_than_guessing_when_the_repo_is_unknown(tmp_path, monkeypatch):
    """Fail closed with a reason. Pushing at whatever FLS_REPO happens to be is the failure."""
    from fastapi.testclient import TestClient

    from fls import app as appmod
    src = appmod.ANCHOR_PATH.read_text()
    target = tmp_path / "ANCHOR.md"          # deliberately NOT inside a git checkout
    target.write_text(src)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setattr(appmod, "ANCHOR_PATH", target)

    r = TestClient(appmod.app).post("/anchor/propose",
                                    json={"section": "funnel", "edits": {"queue": 2}})
    assert r.status_code == 200
    body = r.json()
    assert body["simulated"] is True, "nothing may be pushed when the target is unknown"
    assert "pr_url" not in body
    assert "cannot determine which repo" in body["note"]


def test_propose_targets_the_anchor_s_repo_when_it_is_known(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from fls import app as appmod
    root = _checkout(tmp_path, "https://github.com/acme/governance.git")
    target = root / "ANCHOR.md"
    target.write_text(appmod.ANCHOR_PATH.read_text())
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("FLS_REPO", "acme/vessel")   # the wrong answer, present
    monkeypatch.setattr(appmod, "ANCHOR_PATH", target)

    seen = {}

    def _fake_open(branch, new_text, section, edits, repo):
        seen["repo"] = repo
        return f"https://github.com/{repo}/pull/1"
    monkeypatch.setattr("fls.github_surface.open_anchor_pr", _fake_open)

    body = TestClient(appmod.app).post(
        "/anchor/propose", json={"section": "funnel", "edits": {"queue": 2}}).json()
    assert seen["repo"] == "acme/governance", "must be the ANCHOR's repo, not FLS_REPO"
    assert body["repo"] == "acme/governance"
    assert body["simulated"] is False


def test_an_explicit_anchor_repo_wins_because_a_deployment_has_no_checkout(tmp_path, monkeypatch):
    """The deploy rsyncs --exclude .git, correctly: a server should not carry git metadata. So a
    deployed instance cannot derive, and FLS_ANCHOR_REPO is its answer. Explicit beats derived for
    the same reason FLS_STAGE_DIR beats an incidental repo+token on the deploy seam — it is only
    ever set on purpose."""
    root = _checkout(tmp_path, "https://github.com/derived/from-disk.git")
    monkeypatch.setenv("FLS_ANCHOR_REPO", "explicit/wins")
    assert modules.anchor_remote(root / "ANCHOR.md") == "explicit/wins"


def test_derivation_is_the_fallback_when_no_override_is_set(tmp_path, monkeypatch):
    monkeypatch.delenv("FLS_ANCHOR_REPO", raising=False)
    root = _checkout(tmp_path, "https://github.com/derived/from-disk.git")
    assert modules.anchor_remote(root / "ANCHOR.md") == "derived/from-disk"


def test_a_blank_override_does_not_count_as_set(tmp_path, monkeypatch):
    """An empty env var is how a .env with `FLS_ANCHOR_REPO=` and no value would read."""
    root = _checkout(tmp_path, "https://github.com/derived/from-disk.git")
    for blank in ("", "   "):
        monkeypatch.setenv("FLS_ANCHOR_REPO", blank)
        assert modules.anchor_remote(root / "ANCHOR.md") == "derived/from-disk"

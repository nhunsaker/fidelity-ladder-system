"""Where code lands, as opposed to where decisions are recorded.

`FLS_REPO` is the repo whose ISSUES are expeditions. `FLS_VESSEL_REPO` is the checkout a builder
writes into and pushes a branch from. Different jobs, possibly different repos — and until now
nothing surfaced the second, so the Connections screen could say where decisions go but not where
the work lands.

Derived from the checkout's own .git/config, never declared: a repo URL is instance identity,
which CLAUDE.md's work-split rule puts in env, and a copy in the ANCHOR could drift from the
checkout it claims to describe.
"""
from __future__ import annotations

import pytest

from fls import modules


def _repo(tmp_path, url: str | None):
    """A minimal checkout: just enough .git/config for the reader to find (or not find) a remote."""
    git = tmp_path / ".git"
    git.mkdir()
    if url is not None:
        (git / "config").write_text(
            "[core]\n\trepositoryformatversion = 0\n"
            f'[remote "origin"]\n\turl = {url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n')
    return tmp_path


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("FLS_VESSEL_REPO", raising=False)


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/acme/vessel.git", "acme/vessel"),
    ("https://github.com/acme/vessel", "acme/vessel"),
    ("git@github.com:acme/vessel.git", "acme/vessel"),
    # not GitHub: returned verbatim, so the UI's slug check refuses to link it rather than
    # inventing a github.com URL for a host that is not GitHub.
    ("https://gitlab.com/acme/thing.git", "https://gitlab.com/acme/thing.git"),
])
def test_a_github_remote_becomes_a_slug(tmp_path, monkeypatch, url, expected):
    monkeypatch.setenv("FLS_VESSEL_REPO", str(_repo(tmp_path, url)))
    assert modules._vessel_remote() == expected


@pytest.mark.parametrize("setup", ["unset", "missing-dir", "not-a-repo", "no-origin"])
def test_every_way_of_having_no_vessel_remote_returns_none_not_an_error(tmp_path, monkeypatch, setup):
    """Reflection never raises. Each of these is honestly 'no vessel remote', not a failure."""
    if setup == "missing-dir":
        monkeypatch.setenv("FLS_VESSEL_REPO", str(tmp_path / "nope"))
    elif setup == "not-a-repo":
        monkeypatch.setenv("FLS_VESSEL_REPO", str(tmp_path))       # no .git at all
    elif setup == "no-origin":
        monkeypatch.setenv("FLS_VESSEL_REPO", str(_repo(tmp_path, None)))
    assert modules._vessel_remote() is None


def test_the_sources_seam_carries_it_in_both_kinds(tmp_path, monkeypatch):
    """local-mode too: an instance with a vessel checkout and no FLS_REPO is the half-wired state
    the contradiction checks already name, and the screen needs the value to show it."""
    monkeypatch.setenv("FLS_VESSEL_REPO",
                       str(_repo(tmp_path, "https://github.com/acme/app.git")))
    monkeypatch.delenv("FLS_REPO", raising=False)
    monkeypatch.delenv("FLS_SOURCE_KIND", raising=False)
    local = modules._sources_status()
    assert local["kind"] == "local"
    assert local["detail"]["vessel_repo"] == "acme/app"

    monkeypatch.setenv("FLS_REPO", "acme/planning")
    gh = modules._sources_status()
    assert gh["kind"] == "github"
    assert gh["detail"]["prod_repo"] == "acme/planning"
    assert gh["detail"]["vessel_repo"] == "acme/app", "issues and code can be different repos"

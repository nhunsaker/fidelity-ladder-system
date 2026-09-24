"""Rung 5: the branch becomes a pull request, with the feature switched off.

The pushes here are real — against a bare repository in a temp directory — because the failures
worth catching are git-shaped. The GitHub calls are injected, so no test touches the network.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from fls.builders.ship import (
    PullRequestShipper,
    ShipOutcome,
    flags_switched_on,
    slug_from_remote,
)
from fls.rung4 import PRPackage


def _run(*args, cwd):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def vessel(tmp_path):
    """A checkout whose `origin` is a real bare repository we can actually push to."""
    bare = tmp_path / "origin.git"
    _run("git", "init", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    repo = tmp_path / "vessel"
    _run("git", "clone", str(bare), str(repo), cwd=tmp_path)
    _run("git", "config", "user.email", "t@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "T", cwd=repo)
    (repo / "flags.json").write_text(
        json.dumps({"_comment": "notes are not flags", "share-result":
                    {"stage": False, "prod": False}}), encoding="utf-8")
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-m", "init", cwd=repo)
    _run("git", "push", "origin", "main", cwd=repo)
    return repo, bare


PKG = PRPackage(diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n+one\n", test_output="ok", eval_score="n/a",
                corner_cuts=["none"], walkthrough_url="https://example.invalid/preview/10")


class FakeAPI:
    """Records calls; returns what GitHub would."""

    def __init__(self, existing=None, pr=None):
        self.existing = existing or []
        self.pr = pr or {"html_url": "https://github.com/o/r/pull/7", "number": 7}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "GET":
            return self.existing
        return self.pr


def _branch(repo, name="exp-10", body="feature\n"):
    _run("git", "checkout", "-b", name, cwd=repo)
    (repo / "feature.txt").write_text(body, encoding="utf-8")
    _run("git", "add", "-A", cwd=repo)
    _run("git", "commit", "-m", "the feature", cwd=repo)
    return name


# ── the repository is read from the checkout, not from configuration ───────────────────────

@pytest.mark.parametrize("url,expected", [
    ("https://github.com/owner/name.git", "owner/name"),
    ("https://github.com/owner/name", "owner/name"),
    ("git@github.com:owner/name.git", "owner/name"),
    ("https://example.com/owner/name.git", ""),
])
def test_slug_is_derived_from_the_remote(tmp_path, url, expected):
    r = tmp_path / "r"
    r.mkdir()
    _run("git", "init", "-b", "main", cwd=r)
    _run("git", "remote", "add", "origin", url, cwd=r)
    assert slug_from_remote(r) == expected


# ── the flag must be off ───────────────────────────────────────────────────────────────────

def test_flags_switched_on_ignores_notes_and_finds_real_ones(tmp_path):
    f = tmp_path / "flags.json"
    f.write_text(json.dumps({"_comment": "x", "a": {"stage": False, "prod": False},
                             "b": {"stage": True, "prod": False}}), encoding="utf-8")
    assert flags_switched_on(f) == ["b.stage"]


def test_a_missing_flags_file_is_not_a_violation(tmp_path):
    assert flags_switched_on(tmp_path / "nope.json") == []


def test_a_branch_arriving_with_its_flag_on_is_refused(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)
    (repo / "flags.json").write_text(
        json.dumps({"share-result": {"stage": True, "prod": False}}), encoding="utf-8")
    api = FakeAPI()
    s = PullRequestShipper(repo, token="t", api=api, slug="o/r")
    out = s.ship(10, branch, PKG, worktree=repo)
    assert not out.passed
    assert any("would go live on merge" in v for v in out.violations)
    assert api.calls == []          # nothing was pushed and no pull request was opened


# ── reviewability is enforced before anyone is asked to look ───────────────────────────────

def test_an_oversized_diff_is_shipped_and_not_refused(tmp_path, vessel):
    """THIS USED TO REFUSE BEFORE THE PUSH — finished, tested work discarded for a line count.
    Founder's rule, 2026-09-16: size is told to a person, never a reason to throw the work away.
    The size reaches the reviewer as a note on the pull request instead."""
    repo, _ = vessel
    branch = _branch(repo)
    big = PRPackage(diff="\n".join(f"+{i}" for i in range(500)), test_output="ok",
                    eval_score="n/a", corner_cuts=[], walkthrough_url="https://x.invalid/p",
                    size="small",
                    size_notes=["estimated **small**, grew from that: 500 changed lines"])
    api = FakeAPI()
    out = PullRequestShipper(repo, token="t", api=api, slug="o/r", line_budget=50).ship(
        10, branch, big, worktree=repo)
    assert out.passed, out.violations
    assert not any("reviewability budget" in v for v in out.violations)
    body = next(p["body"] for m, _, p in api.calls if m == "POST" and p)
    assert "grew from that" in body, "the reviewer is told the size, not protected from the work"


def test_no_walkthrough_is_refused(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)
    pkg = PRPackage(diff="+one\n", test_output="ok", eval_score="n/a", corner_cuts=[],
                    walkthrough_url="")
    out = PullRequestShipper(repo, token="t", api=FakeAPI(), slug="o/r").ship(10, branch, pkg, worktree=repo)
    assert not out.passed and any("walkthrough" in v for v in out.violations)


def test_no_token_says_so_plainly(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)
    out = PullRequestShipper(repo, token="", api=FakeAPI(), slug="o/r").ship(10, branch, PKG, worktree=repo)
    assert not out.passed and any("GITHUB_TOKEN" in v for v in out.violations)


# ── the happy path: a real push, then the pull request ─────────────────────────────────────

def test_it_pushes_the_branch_and_opens_a_draft_pull_request(tmp_path, vessel):
    repo, bare = vessel
    branch = _branch(repo)
    api = FakeAPI()
    out = PullRequestShipper(repo, token="t", api=api, slug="o/r").ship(10, branch, PKG, worktree=repo)
    assert out.passed, out.violations
    assert out.pushed and out.pr_url.endswith("/pull/7") and out.pr_number == 7
    # the branch really is on the remote
    refs = subprocess.run(["git", "-C", str(bare), "for-each-ref", "--format=%(refname)"],
                          capture_output=True, text=True, check=True).stdout
    assert f"refs/heads/{branch}" in refs
    # and it was opened as a draft, against main, with the review package as the body
    method, path, payload = api.calls[-1]
    assert method == "POST" and path.endswith("/pulls")
    assert payload["draft"] is True and payload["base"] == "main" and payload["head"] == branch
    assert "What this changes" in payload["body"]
    # The reviewer is told what their own next action does, where they already are.
    assert "ready for review" in payload["body"]


def test_main_is_untouched_on_the_remote(tmp_path, vessel):
    repo, bare = vessel
    branch = _branch(repo)
    before = subprocess.run(["git", "-C", str(bare), "rev-parse", "main"], capture_output=True,
                            text=True, check=True).stdout.strip()
    PullRequestShipper(repo, token="t", api=FakeAPI(), slug="o/r").ship(10, branch, PKG, worktree=repo)
    after = subprocess.run(["git", "-C", str(bare), "rev-parse", "main"], capture_output=True,
                           text=True, check=True).stdout.strip()
    assert before == after, "rung 5 must never move the default branch"


def test_a_second_run_reuses_the_open_pull_request(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)
    api = FakeAPI(existing=[{"html_url": "https://github.com/o/r/pull/3", "number": 3}])
    out = PullRequestShipper(repo, token="t", api=api, slug="o/r").ship(10, branch, PKG, worktree=repo)
    assert out.passed and out.already_open and out.pr_number == 3
    assert not any(m == "POST" for m, _, _ in api.calls), "must not open a second pull request"


def test_a_github_error_is_reported_not_raised(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)

    def boom(method, path, payload=None):
        if method == "GET":
            return []
        raise RuntimeError("GitHub POST /pulls -> 403: forbidden")

    out = PullRequestShipper(repo, token="t", api=boom, slug="o/r").ship(10, branch, PKG, worktree=repo)
    assert not out.passed and out.pushed and "403" in out.detail


def test_the_token_never_appears_in_the_git_arguments(tmp_path, vessel, monkeypatch):
    """A token in argv is visible in `ps` and lands in the reflog. It must travel in the env."""
    repo, _ = vessel
    branch = _branch(repo)
    seen = {}
    import fls.builders.ship as shipmod
    real = shipmod._git

    def spy(cwd, *args, env=None, timeout=180):
        if "push" in args:
            seen["args"] = args
            seen["env_has_token"] = bool(env and env.get("FLS_GIT_TOKEN"))
        return real(cwd, *args, env=env, timeout=timeout)

    monkeypatch.setattr(shipmod, "_git", spy)
    PullRequestShipper(repo, token="sekret-value", api=FakeAPI(), slug="o/r").ship(
        10, branch, PKG, worktree=repo)
    assert "sekret-value" not in " ".join(seen["args"])
    assert seen["env_has_token"] is True


def test_outcome_artifacts_carry_the_pr_for_the_demo_view(tmp_path, vessel):
    repo, _ = vessel
    branch = _branch(repo)
    out = PullRequestShipper(repo, token="t", api=FakeAPI(), slug="o/r").ship(10, branch, PKG, worktree=repo)
    a = out.artifacts()["ship"]
    assert a["pr_url"].endswith("/pull/7") and a["branch"] == branch and a["pushed"] is True


def test_ship_outcome_defaults_are_a_refusal():
    assert ShipOutcome(False).passed is False


def test_the_flag_a_change_introduces_is_derived_from_git(tmp_path):
    """"The flags in this file" and "the flag this change added" stop being the same list the
    moment a vessel has more than one — and the demo tells a reviewer which flag to turn on."""
    import json as _json
    import subprocess

    from fls.builders.ship import flags_added

    wt = tmp_path / "wt"
    wt.mkdir()
    def run(*a):
        subprocess.run(["git", "-C", str(wt), *a], capture_output=True, check=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (wt / "flags.json").write_text(_json.dumps({"_note": "x", "already-there": {"stage": False}}))
    run("add", "-A")
    run("commit", "-qm", "base")
    (wt / "flags.json").write_text(_json.dumps(
        {"_note": "x", "already-there": {"stage": False}, "table-reactions": {"stage": False}}))

    assert flags_added(wt) == ["table-reactions"], "the pre-existing flag was reported as new"

    # Nothing to compare against is not a licence to guess.
    assert flags_added(tmp_path / "nope") == []

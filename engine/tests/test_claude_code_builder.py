"""Rung 4's agentic builder, against a real git repository.

These tests build an actual repo in a temp dir and let the builder make a real worktree, because
the failures worth catching here are git-shaped: a diff that omits added files, a retry that cannot
reuse its branch, a session that claims success and changed nothing.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from fls.builders.claude_code_builder import ClaudeCodeBuilder, diff_line_count
from fls.llm import Call
from fls.rung4 import BoundedContext


def _run(*args, cwd):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A real repository with one commit on `main`."""
    r = tmp_path / "repo"
    r.mkdir()
    _run("git", "init", "-b", "main", cwd=r)
    _run("git", "config", "user.email", "t@example.invalid", cwd=r)
    _run("git", "config", "user.name", "Test", cwd=r)
    (r / "README.md").write_text("# vessel\n", encoding="utf-8")
    (r / "app.txt").write_text("one\ntwo\n", encoding="utf-8")
    _run("git", "add", "-A", cwd=r)
    _run("git", "commit", "-m", "initial", cwd=r)
    return r


@dataclass
class _Res:
    text: str
    call: Call
    timed_out: bool = False


class FakeSession:
    """Writes files into its cwd, the way a real session does."""

    timeout_s = 2400

    def __init__(self, files: dict[str, str] | None = None, note: str = "did the work",
                 timed_out: bool = False, edits: dict[str, str] | None = None):
        self.files = files or {}
        self.edits = edits or {}
        self.note = note
        self.timed_out = timed_out
        self.cwd: str | None = None
        self.prompt: str | None = None

    def run(self, prompt: str, system: str = "") -> _Res:
        self.prompt = prompt
        for name, body in {**self.files, **self.edits}.items():
            p = Path(self.cwd) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        return _Res(self.note, Call("claude-code", "m", 100, 50, usd=0.0, normalized_usd=0.9,
                                    funded_by="subscription"), self.timed_out)


def _builder(repo, session, **kw):
    kw.setdefault("test_cmd", "true")
    b = ClaudeCodeBuilder(repo, session=session, **kw)
    return b


CTX = BoundedContext(spec="add a share control", wireframe="candidate-1: a bottom sheet")


def test_diff_line_count_ignores_headers():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n context\n+added\n-removed\n"
    assert diff_line_count(diff) == 2


def test_a_real_change_passes_and_the_diff_includes_added_files(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "new\n", "app.txt": "one\ntwo\nthree\n"})
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert r.passed, r.violations
    assert r.branch == "exp-11"
    # the added file must be in the diff, not merely on disk — a reviewer reads the diff
    assert "feature.txt" in r.files_changed and "app.txt" in r.files_changed
    assert "+new" in r.diff
    assert r.lines_changed > 0 and r.test_passed


def test_a_session_that_changed_nothing_fails_however_confident_its_note(tmp_path, repo):
    session = FakeSession(files={}, note="Implemented the feature and all tests pass.")
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert not r.passed
    assert any("changed nothing" in v for v in r.violations)


def test_the_suite_is_re_run_and_its_real_result_is_what_counts(tmp_path, repo):
    # The session insists it is green; the vessel's own check disagrees, and the check wins.
    session = FakeSession(files={"feature.txt": "x\n"}, note="All tests pass. Ready to ship.")
    b = _builder(repo, session, test_cmd="false")
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert not r.passed and not r.test_passed
    assert any("not green" in v for v in r.violations)


def test_no_test_command_is_a_failure_not_a_pass(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "x\n"})
    b = _builder(repo, session, test_cmd="")
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert not r.passed
    assert "no test command" in r.test_output


def test_a_big_diff_ships_with_a_note_instead_of_being_refused(tmp_path, repo):
    """THIS USED TO PARK THE RUN. Founder's rule, 2026-09-16: never refuse a build because of
    its size — tell the person. The batch's only two size refusals were a stale-base bug counting
    lines the builds had not written, and the thirteen that shipped had visibly sized themselves
    to land just under the limit, so the budget was shaping work rather than catching it."""
    session = FakeSession(files={"big.txt": "\n".join(str(i) for i in range(500))})
    b = _builder(repo, session, line_budget=50)
    b.size = "small"
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert r.passed, r.violations
    assert not any("reviewability budget" in v for v in r.violations)
    assert r.size_notes, "a change this far past its estimate should say so"
    assert any("the target is 50" in n for n in r.size_notes)


def test_the_worktree_is_reusable_so_a_retry_is_possible(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "first\n"})
    b = _builder(repo, session)
    art = str(tmp_path / "art")
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    first = b.build(11, CTX, artifact_dir=art)
    assert first.passed
    # second attempt on the same expedition: same branch name, same path, must not blow up
    session.files = {"feature.txt": "second\n"}
    second = b.build(11, CTX, feedback="use the other wording", artifact_dir=art)
    assert second.passed, second.violations
    assert second.branch == "exp-11"
    assert "second" in (Path(second.worktree) / "feature.txt").read_text()


def test_the_branch_is_not_main_and_main_is_untouched(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "x\n"})
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert r.branch != "main"
    # the base checkout still has exactly its original files
    assert not (repo / "feature.txt").exists()
    head = subprocess.run(["git", "-C", str(repo), "log", "--oneline"], capture_output=True,
                          text=True, check=True).stdout.strip().splitlines()
    assert len(head) == 1


def test_feedback_and_the_standards_reach_the_prompt(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "x\n"})
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    b.build(11, CTX, feedback="the control is unreachable by keyboard",
            standards=("every surface behind a flag", "compose from the pack"),
            artifact_dir=str(tmp_path / "art"))
    assert "unreachable by keyboard" in session.prompt
    assert "every surface behind a flag" in session.prompt
    assert "add a share control" in session.prompt
    assert "commits of about 400 changed lines" in session.prompt


def test_a_timeout_is_a_failure_with_its_budget_named(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "x\n"}, timed_out=True)
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"))
    assert not r.passed and "wall clock" in r.detail


def test_cleanup_removes_the_worktree(tmp_path, repo):
    session = FakeSession(files={"feature.txt": "x\n"})
    b = _builder(repo, session)
    session.cwd = str(tmp_path / "art" / "mvp" / "wt")
    r = b.build(11, CTX, artifact_dir=str(tmp_path / "art"), keep_worktree=False)
    assert r.passed
    assert not Path(r.worktree).exists()


def test_builder_needs_a_session_or_a_factory(repo):
    with pytest.raises(ValueError):
        ClaudeCodeBuilder(repo)


# ── an adopted worktree measures itself against the same base a fresh one does ─────────────

def _stale_clone(tmp_path):
    """A clone whose `origin/main` has moved on and whose local `main` has not — the shape every
    long-lived vessel checkout takes, because nothing ever pulls it."""
    import subprocess

    def git(where, *args):
        return subprocess.run(("git", "-C", str(where), *args), capture_output=True, text=True,
                              check=True)

    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-b", "main")
    git(origin, "config", "user.email", "t@example.invalid")
    git(origin, "config", "user.name", "T")
    (origin / "seed.txt").write_text("seed\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "seed")

    work = tmp_path / "work"
    subprocess.run(("git", "clone", str(origin), str(work)), capture_output=True, check=True)
    git(work, "config", "user.email", "t@example.invalid")
    git(work, "config", "user.name", "T")

    # 300 lines merge upstream that this clone's local `main` will never see.
    (origin / "merged.txt").write_text("\n".join(f"line {i}" for i in range(300)) + "\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-m", "300 lines of somebody else's work")
    return work, git


def test_an_adopted_worktree_is_measured_against_the_remote_not_the_stale_local_branch(tmp_path):
    """THE REGRESSION TEST. `standing_work` runs BEFORE `make_worktree`, so `_resolved_base` was
    always empty on the one path that reached it and the fallback was the clone's local `main`.
    Expeditions 42 and 52 were both refused for a diff of ~1850 lines against a 400-line budget
    while their own sessions had measured 366 — the extra was everything merged since the clone.
    """
    from fls.builders.claude_code_builder import ClaudeCodeBuilder

    work, git = _stale_clone(tmp_path)
    wt = tmp_path / "wt"
    b = ClaudeCodeBuilder(str(work), session=object(), line_budget=400)

    # a branch carrying three lines of its own
    git(work, "worktree", "add", "-b", "exp-9", str(wt), "origin/main")
    (wt / "feature.txt").write_text("a\nb\nc\n")
    git(wt, "add", "-A")
    git(wt, "commit", "-m", "the actual change")

    standing = b.standing_work(9, wt)
    assert standing, "a branch with a commit on it is standing work"
    base, _ = standing
    changed = git(wt, "diff", "--numstat", base).stdout.split()
    assert changed and int(changed[0]) == 3, (
        f"the adopted tree must measure ITS OWN three lines, not the 300 that merged "
        f"upstream — got {changed}")


def test_the_primary_checkout_is_fast_forwarded_after_a_fetch(tmp_path):
    """`git fetch origin main` moves `origin/main` and nothing else. The clone on the box sat
    eight commits behind on its own `main`, and three bugs came out of code asking it a question.
    After `base_ref()` the local branch should say the same thing the remote does."""
    from fls.builders.claude_code_builder import ClaudeCodeBuilder

    work, git = _stale_clone(tmp_path)
    before = git(work, "rev-parse", "main").stdout.strip()
    b = ClaudeCodeBuilder(str(work), session=object())
    assert b.base_ref() == "origin/main"
    after = git(work, "rev-parse", "main").stdout.strip()
    assert after != before
    assert after == git(work, "rev-parse", "origin/main").stdout.strip()


def test_a_dirty_primary_checkout_is_left_alone(tmp_path):
    """A fast-forward on a tree with local changes would move somebody's work out from under
    them. The resolved base is still `origin/main`; only the local branch stays behind."""
    from fls.builders.claude_code_builder import ClaudeCodeBuilder

    work, git = _stale_clone(tmp_path)
    (work / "scratch.txt").write_text("uncommitted\n")
    before = git(work, "rev-parse", "main").stdout.strip()
    b = ClaudeCodeBuilder(str(work), session=object())
    assert b.base_ref() == "origin/main"
    assert git(work, "rev-parse", "main").stdout.strip() == before
    assert (work / "scratch.txt").exists()


# ── a finished run lets go of its worktree ─────────────────────────────────────────────────

def _repo_with_worktree(tmp_path):
    """A vessel clone with one expedition worktree on branch exp-7, the way a build leaves it."""
    import subprocess

    def git(where, *args):
        return subprocess.run(("git", "-C", str(where), *args), capture_output=True, text=True,
                              check=True)

    repo = tmp_path / "vessel"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "T")
    (repo / "README.md").write_text("v\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "init")
    wt = tmp_path / "expeditions" / "7" / "mvp" / "wt"
    wt.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-b", "exp-7", str(wt), "main")
    (wt.parent / "diff.patch").write_text("+ evidence\n")     # the evidence lives BESIDE the tree
    return repo, wt, git


def test_a_merged_run_releases_its_checkout_and_its_branch(tmp_path):
    """NOTHING DID THIS: twenty-seven expedition worktrees on the box, each a full checkout of
    the vessel, none of them ever going to be read again."""
    from fls.builders.claude_code_builder import release_worktree
    repo, wt, git = _repo_with_worktree(tmp_path)
    said = release_worktree(repo, wt, branch="exp-7", delete_branch=True)
    assert not wt.exists()
    assert "exp-7" not in git(repo, "branch", "--list").stdout
    assert (wt.parent / "diff.patch").exists(), "the evidence beside the tree must survive"
    assert "removed the checkout" in said and "deleted local exp-7" in said


def test_a_stopped_run_releases_its_checkout_but_keeps_the_branch(tmp_path):
    from fls.builders.claude_code_builder import release_worktree
    repo, wt, git = _repo_with_worktree(tmp_path)
    release_worktree(repo, wt, branch="exp-7", delete_branch=False)
    assert not wt.exists()
    assert "exp-7" in git(repo, "branch", "--list").stdout


def test_releasing_an_absent_worktree_is_a_quiet_no_op(tmp_path):
    from fls.builders.claude_code_builder import release_worktree
    repo, wt, _ = _repo_with_worktree(tmp_path)
    release_worktree(repo, wt, branch="exp-7", delete_branch=True)
    assert release_worktree(repo, wt, branch="exp-7", delete_branch=True) == "nothing to release"


# ── size is told, never enforced ───────────────────────────────────────────────────────────

def _blocks(tmp_path, sizes):
    """A branch carrying one commit per entry in `sizes`, each of that many changed lines."""
    import subprocess

    def git(where, *args):
        return subprocess.run(("git", "-C", str(where), *args), capture_output=True, text=True,
                              check=True)

    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "T")
    (r / "seed.txt").write_text("seed\n")
    git(r, "add", "-A")
    git(r, "commit", "-m", "seed")
    base = git(r, "rev-parse", "HEAD").stdout.strip()
    for i, n in enumerate(sizes, 1):
        (r / f"block{i}.txt").write_text("\n".join(f"line {j}" for j in range(n)) + "\n")
        git(r, "add", "-A")
        git(r, "commit", "-m", f"block {i}: one part of the work")
    return r, base


def test_the_blocks_the_work_landed_in_are_recorded(tmp_path):
    """A reviewer reading 600 lines in two named blocks is doing something different from a
    reviewer reading a 600-line wall, and until now there was only ever the wall."""
    from fls.builders.claude_code_builder import commit_blocks
    r, base = _blocks(tmp_path, [300, 300])
    blocks = commit_blocks(r, base)
    assert [b["lines"] for b in blocks] == [300, 300]
    assert blocks[0]["subject"] == "block 1: one part of the work"
    assert all(len(b["sha"]) == 40 for b in blocks)


def test_a_block_over_the_target_is_a_note_and_not_a_violation(tmp_path):
    """THE FOUNDER'S RULE. Finished, tested work is never thrown away for a number."""
    from fls.builders.claude_code_builder import commit_blocks, size_notes
    r, base = _blocks(tmp_path, [500])
    notes = size_notes(commit_blocks(r, base), 500, "medium", 400)
    assert any("500 changed lines" in n and "the target is 400" in n for n in notes)


def test_a_change_that_outgrew_its_estimate_says_so_and_still_ships(tmp_path):
    from fls.builders.claude_code_builder import commit_blocks, size_notes
    r, base = _blocks(tmp_path, [300, 300, 300])
    notes = size_notes(commit_blocks(r, base), 900, "small", 400)
    grew = next(n for n in notes if "estimated" in n)
    assert "**small**" in grew and "grew from" in grew and "**large**" in grew
    assert "Nothing was cut to fit" in grew


def test_an_estimate_that_held_produces_no_growth_note(tmp_path):
    from fls.builders.claude_code_builder import commit_blocks, size_notes
    r, base = _blocks(tmp_path, [200, 150])
    assert size_notes(commit_blocks(r, base), 350, "small", 400) == []


def test_coming_in_under_the_estimate_is_also_worth_saying(tmp_path):
    from fls.builders.claude_code_builder import commit_blocks, size_notes
    r, base = _blocks(tmp_path, [80])
    notes = size_notes(commit_blocks(r, base), 80, "large", 400)
    assert any("came in under" in n for n in notes)


def test_the_build_prompt_asks_for_blocks_and_promises_nothing_is_refused():
    from fls.builders.claude_code_builder import ClaudeCodeBuilder
    b = ClaudeCodeBuilder("/tmp/x", session=object(), line_budget=400)
    sysp = b.system_prompt()
    assert "COMMIT AS YOU GO" in sysp and "400 CHANGED LINES" in sysp
    assert "NOTHING is refused for size" in sysp
    assert "PARKS the expedition" not in sysp

"""Rung 4 — the feature, built in a real checkout by an agentic session.

The reference rung-4 builder asks a model for a patch. This one gives a session a **git worktree of
the actual repository** and lets it work: read the tree, write code, write its own tests, run them,
and iterate until they pass. What comes back is judged the way a reviewer would judge it:

* **The diff is the artifact.** Computed with git against the commit the worktree started from, so
  it covers what the session did whether or not it remembered to commit. A session that reports
  success and changed nothing fails here.
* **The tests are re-run by us.** The session is told to iterate until its tests pass; then this
  code runs the suite itself and believes only that. "All tests pass" in a final message is not
  evidence — it is the single most common false claim an agentic build makes, and the one that
  costs a reviewer the most when it turns out to be wrong.
* **Reviewability is enforced, not hoped for.** A diff past the line budget is refused before a
  human is asked to look at it, on the same rule `enforce_reviewability` applies at rung 5.

Isolation is a worktree, so a failed attempt is thrown away by deleting a directory and never
touches the checkout anyone else is using. Nothing here reads a credential: git talks to the remote
with whatever the host is already configured to use.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from fls.claude_code import ClaudeCodeSession
from fls.llm import Call
from fls.rung4 import BoundedContext

log = logging.getLogger("fls.builders")

# Read the tree, change it, and run the project's own commands. Bash is unavoidable here — the
# session has to be able to run the test suite it is being judged on — which is exactly why the
# worktree exists: the blast radius is one throwaway directory.
BUILD_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash")

_SYSTEM = """You implement ONE feature in a real repository you have been given a checkout of.

Work like an engineer who will not be there to explain it:

1. Read the project's own guide (CLAUDE.md, AGENTS.md, README) FIRST and follow it. Its rules
   outrank your habits — including which test runner, which package manager, and how UI is
   composed.
2. Write the test before the implementation where you can. A feature with no test is unfinished.
3. Run the project's full check command and iterate until it is GREEN. Do not stop at "should work".
4. COMMIT AS YOU GO, in blocks of about THE LINE BUDGET changed lines or fewer, each with a
   one-line message saying what that block does. A reviewer reads your work a block at a time,
   so land it that way: the schema, then the logic, then the screen, then the tests. This is a
   target and not a limit — going over is not a failure and NOTHING is refused for size. Build
   the whole feature properly; do not cut scope to hit a number, and if the work came out bigger
   than it was estimated at, say so plainly in your final note.
5. NEVER push, never open a pull request, never commit on the default branch, and never change
   git remotes or history. You are on a working branch; leave your work there.

Your final message is a SHORT note: what you changed, what you tested, and every corner you cut.
The diff and the test suite are checked mechanically afterwards, so an inaccurate summary only
misleads the human who reviews you."""


@dataclass
class BuildResult:
    passed: bool
    branch: str = ""
    worktree: str = ""
    diff: str = ""
    files_changed: list[str] = field(default_factory=list)
    lines_changed: int = 0
    commits: list[dict] = field(default_factory=list)   # the blocks the work landed in
    size: str = ""                                      # what rung 1 estimated
    size_notes: list[str] = field(default_factory=list)  # things to TELL, never violations
    test_passed: bool = False
    test_output: str = ""
    note: str = ""
    violations: list[str] = field(default_factory=list)
    detail: str = ""
    calls: list[Call] = field(default_factory=list)

    def artifacts(self) -> dict:
        return {"build": {
            "branch": self.branch, "worktree": self.worktree,
            "files_changed": self.files_changed, "lines_changed": self.lines_changed,
            "commits": self.commits, "size": self.size, "size_notes": self.size_notes,
            "test_passed": self.test_passed, "test_output": self.test_output[-4000:],
            "note": self.note, "violations": self.violations,
            "diff": self.diff[:20000]}}


def _git(repo: str | Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=timeout, check=False)


def commit_blocks(wt: str | Path, base_sha: str) -> list[dict]:
    """The commits this branch added, oldest first, each with its own changed-line count.

    A reviewer reading 600 lines in two named blocks is doing something different from a
    reviewer reading a 600-line wall, and until now there was only ever the wall: the session
    was told "never commit on the default branch" and nothing about committing at all, so
    `build()` made one commit at the end however big the change was.
    """
    out: list[dict] = []
    log = _git(wt, "log", "--reverse", "--format=%H%x09%s", f"{base_sha}..HEAD").stdout
    for line in log.splitlines():
        sha, _, subject = line.partition("\t")
        if not sha.strip():
            continue
        stat = _git(wt, "show", "--numstat", "--format=", sha.strip()).stdout
        n = 0
        for row in stat.splitlines():
            cols = row.split("\t")
            if len(cols) >= 2:
                # "-" is git's marker for a binary file; it contributes no readable lines
                n += sum(int(c) for c in cols[:2] if c.isdigit())
        out.append({"sha": sha.strip(), "subject": subject.strip()[:120], "lines": n})
    return out


def size_notes(commits: list[dict], total: int, size: str, target: int) -> list[str]:
    """Things worth TELLING somebody about how big this came out. Never violations.

    The founder's rule, after a batch where the 400-line budget refused two builds for lines
    they had not written and shaped thirteen more into landing at 397-400: size is information.
    Throwing away finished, tested work over a number is the one thing this must not do.
    """
    from fls.rung4 import size_for
    notes = []
    if target:
        over = [c for c in commits if int(c.get("lines") or 0) > target]
        for c in over:
            notes.append(f"block `{c.get('subject', '')}` is {c['lines']} changed lines "
                         f"(the target is {target}) — read it in its own sitting")
    actual = size_for(total)
    if size and actual != size:
        grew = ("grew from" if _rank(actual) > _rank(size) else "came in under")
        notes.append(f"estimated **{size}**, {grew} that: {total} changed lines across "
                     f"{len(commits)} commit{'s' if len(commits) != 1 else ''} — **{actual}**. "
                     "Nothing was cut to fit.")
    return notes


def _rank(size: str) -> int:
    from fls.rung4 import SIZE_ORDER
    return SIZE_ORDER.index(size) if size in SIZE_ORDER else 1


def diff_line_count(diff: str) -> int:
    """Changed lines only — the same measure rung 5's reviewability check uses."""
    return sum(1 for line in (diff or "").splitlines()
               if (line.startswith("+") or line.startswith("-"))
               and not line.startswith(("+++", "---")))


class ClaudeCodeBuilder:
    """Build a feature in a worktree of `repo_dir`. `session_factory(tools=…, cwd_=…)` returns a
    `ClaudeCodeSession`; injecting it keeps this testable without a CLI."""

    def __init__(self, repo_dir: str | Path, session: ClaudeCodeSession | None = None,
                 session_factory=None, test_cmd: str = "", base: str = "main",
                 line_budget: int = 400, test_timeout_s: int = 1800):
        if session is None and session_factory is None:
            raise ValueError("ClaudeCodeBuilder needs a session or a session_factory")
        self.repo_dir = Path(repo_dir)
        self.session = session
        self.session_factory = session_factory
        self.test_cmd = test_cmd
        self.base = base
        self._resolved_base = ""
        self.line_budget = line_budget
        # What rung 1 said this would be. Told to the session and printed on the pull request;
        # never enforced. See `rung4.SIZE_CLASSES`.
        self.size = ""
        self.test_timeout_s = test_timeout_s

    def _session(self, cwd: str) -> ClaudeCodeSession:
        if self.session is not None:
            return self.session
        return self.session_factory(tools=BUILD_TOOLS, cwd_=cwd)

    # ---- the worktree ---------------------------------------------------------------------

    def base_ref(self) -> str:
        """The commit a build branches from — WHAT IS ON THE REMOTE, not what this clone last saw.

        The clone on the box sat four commits behind `origin/main`, so every expedition branched
        from a base that predated work already merged. Two things followed. Pull requests drifted
        into conflict with each other for no reason a reviewer could see — #7 and #6 both edited a
        `flags.json` whose contents they disagreed about because they started from different
        truths. And "change the thing that already exists" was impossible: expedition 27 was asked
        to change the reactions feature and found no reactions code, because the merge that added
        it was four commits ahead of where it was standing.

        Fetch is best-effort by design. A network blip must not fail a rung that can still build
        against a slightly old base — that trades a real failure for a stale one — but the base
        that gets used is reported either way, so nobody has to guess which they got.
        """
        # A repo with no remote is not a problem to warn about — a fixture vessel, or an instance
        # pointed at a local checkout, is a real mode and `main` is the whole truth there. Warning
        # about it put a red-looking line in the deploy gate's output on every green run, and a
        # gate whose warnings are always there is a gate whose warnings nobody reads.
        if _git(self.repo_dir, "remote", "get-url", "origin").returncode != 0:
            log.debug("no origin configured; building against local %s", self.base)
            return self.base
        r = _git(self.repo_dir, "fetch", "--quiet", "origin", self.base)
        if r.returncode != 0:
            log.warning("could not fetch %s from origin (%s); building against the local copy",
                        self.base, r.stderr.strip()[:160])
            return self.base
        remote = f"origin/{self.base}"
        ok = _git(self.repo_dir, "rev-parse", "--verify", "--quiet", remote).returncode == 0
        if ok:
            self._fast_forward_local(remote)
        return remote if ok else self.base

    def _fast_forward_local(self, remote: str) -> None:
        """Move the clone's own `main` up to what was just fetched, when that is safe.

        `git fetch origin main` updates `origin/main` and nothing else; the clone's
        `refs/heads/main` stays where the clone was made. On this instance that was EIGHT
        commits behind, and three separate bugs came out of code asking that stale branch a
        question — a pull request that said no flag was added, a retried build refused for 1,450
        lines it had not written, and expeditions branching from a base that predated work they
        needed. The resolved base is already `origin/main`, so this costs nothing when it is
        refused; it only makes the local branch stop lying to whoever asks it next.

        Only when the primary checkout is ON `main` and CLEAN. A fast-forward on a dirty tree or a
        different branch would move somebody's work out from under them, and no work is ever
        done in the primary checkout on purpose — every build lives in a worktree.
        """
        on = _git(self.repo_dir, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if on != self.base:
            log.info("primary checkout is on %r, not %r; leaving its branch alone", on, self.base)
            return
        if _git(self.repo_dir, "status", "--porcelain").stdout.strip():
            log.warning("primary checkout of %s has local changes; not fast-forwarding %s",
                        self.repo_dir, self.base)
            return
        r = _git(self.repo_dir, "merge", "--ff-only", "--quiet", remote)
        if r.returncode != 0:
            log.warning("could not fast-forward %s to %s: %s", self.base, remote,
                        r.stderr.strip()[:160])

    def standing_work(self, expedition: int, path: Path) -> tuple[str, str] | None:
        """What a previous attempt left in the worktree, or None if there is nothing usable.

        THE EXPENSIVE RUNG. Rung 4 runs for up to eighty minutes, and until now every attempt began
        by DELETING the worktree — so a build that died at minute seventy-five paid for all
        seventy-five again. That was the right trade when a broken worktree was the likelier
        failure; it is the wrong one now that a worker restart is.

        Fail-closed on anything it does not recognise. A directory that is not a git worktree, or
        is sitting on some other branch, or cannot be read, is not salvaged — it is rebuilt. Half
        an hour saved is not worth building on top of a tree whose state nobody can describe.

        Returns (base sha, a description of what is there) so the session can be told.
        """
        if not (path / ".git").exists():
            return None
        try:
            on = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
            if on != f"exp-{expedition}":
                return None                     # someone else's tree, or a detached head
            # RESOLVED HERE TOO, not just in `make_worktree`. This runs BEFORE that method, so
            # `_resolved_base` is still empty on the one path that reaches this line, and the
            # fallback was the clone's local `main` — which on this box is every commit merged
            # since it was cloned, behind. An adopted worktree was therefore merge-based against
            # an ancient commit and its diff counted ~1,450 lines of other people's merged work as
            # its own: expeditions 42 and 52 were both refused for "the diff is 1857/1846 changed
            # lines, over the 400-line reviewability budget" while their own sessions had measured
            # 366. Two plausible-looking refusals, two wasted runs, and a number a reader would
            # have believed.
            self._resolved_base = self._resolved_base or self.base_ref()
            base = _git(path, "merge-base", "HEAD", self._resolved_base).stdout.strip()
            if not base:
                return None
            files = sorted(set(_git(path, "diff", "--name-only", base).stdout.split()))
            log = _git(path, "log", "--oneline", f"{base}..HEAD").stdout.strip()
        except Exception:  # noqa: BLE001 — an unreadable tree is a tree we rebuild
            return None
        if not files and not log:
            return None                         # a clean checkout is not "work in progress"
        what = []
        if log:
            what.append("commits already made:\n" + "\n".join(f"  {ln}" for ln in log.splitlines()))
        if files:
            what.append(f"files changed so far ({len(files)}): " + ", ".join(files[:40]))
        return base, "\n".join(what)

    def make_worktree(self, expedition: int, path: Path) -> tuple[str, str]:
        """A throwaway checkout on its own branch. Returns (branch, base commit sha).

        `-B` so a retry reuses the branch name instead of failing on the second attempt, and the
        worktree directory is removed first for the same reason: a rung that cannot retry is a rung
        that descends on its first mechanical hiccup.
        """
        branch = f"exp-{expedition}"
        if path.exists():
            _git(self.repo_dir, "worktree", "remove", "--force", str(path))
            shutil.rmtree(path, ignore_errors=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._resolved_base = self.base_ref()
        r = _git(self.repo_dir, "worktree", "add", "--force", "-B", branch, str(path),
                 self._resolved_base)
        if r.returncode != 0:
            raise RuntimeError(f"could not create worktree: {r.stderr.strip()[:300]}")
        sha = _git(path, "rev-parse", "HEAD").stdout.strip()
        return branch, sha

    def cleanup(self, path: Path) -> None:
        _git(self.repo_dir, "worktree", "remove", "--force", str(path))
        shutil.rmtree(path, ignore_errors=True)


    # ---- the prompt -----------------------------------------------------------------------

    def prompt(self, context: BoundedContext, feedback: str = "", standards: tuple = (),
               carried: str = "") -> str:
        parts = [context.render()]
        if carried:
            # Kept out of `prior_failures` and out of `feedback` for the same reason rung 2 keeps
            # its inventory out of feedback: those two mean "this was judged and found wanting".
            # This is work that was never judged at all — it was interrupted — and telling the
            # session it failed would invite it to throw away a nearly finished build.
            parts.append(
                "AN EARLIER ATTEMPT AT THIS WAS INTERRUPTED, not rejected. Its work is already in "
                "this worktree and you are continuing it:\n" + carried
                + "\n\nRead what is there before you change anything. Keep what is sound and "
                  "finish the job; do not start over, and do not redo work to your own taste.")
        if standards:
            parts.append("THE VESSEL'S STANDARDS (non-negotiable):\n"
                         + "\n".join(f"- {s}" for s in standards))
        if self.test_cmd:
            parts.append(f"THE CHECK THAT MUST BE GREEN: `{self.test_cmd}`\n"
                         "It is re-run after you finish, and only its real result counts.")
        if feedback.strip():
            parts.append("THE HUMAN REVIEWED YOUR LAST ATTEMPT AND ASKED FOR CHANGES. This is the "
                         f"whole reason you are running again:\n{feedback.strip()}")
        parts.append(
            f"This was estimated a {self.size or 'medium'}-sized change. Land it in commits of "
            f"about {self.line_budget} changed lines each so a reviewer can read one block at a "
            "time. The estimate is not a budget and nothing is refused for exceeding it — build "
            "the feature properly and say in your note if it came out bigger.")
        return "\n\n".join(parts)

    def system_prompt(self) -> str:
        """The standing rules, with THIS instance's line budget substituted in.

        The budget was mentioned once, softly, as the last line of a long user prompt — "keep the
        diff under N changed lines" — while the system prompt's own rule 4 said only "small enough
        that a human can review it in ten minutes". Expedition 12 came in at 416 against 400 and
        parked, losing a complete, green, tested build over sixteen lines. A hard mechanical
        threshold belongs in the standing rules, stated as the park condition it actually is.
        """
        if not self.line_budget:
            return _SYSTEM.replace("THE LINE BUDGET", "the reviewability budget")
        return _SYSTEM.replace("THE LINE BUDGET", f"{self.line_budget} CHANGED LINES")

    # ---- run the tests ourselves ----------------------------------------------------------

    def run_tests(self, cwd: Path) -> tuple[bool, str]:
        """Run the project's own check. Its exit status is the only evidence that counts."""
        if not self.test_cmd:
            return False, "no test command configured for this vessel"
        try:
            r = subprocess.run(self.test_cmd, cwd=str(cwd), shell=True, capture_output=True,
                               text=True, timeout=self.test_timeout_s, check=False)
        except subprocess.TimeoutExpired:
            return False, f"the check exceeded {self.test_timeout_s}s and was killed"
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out

    # ---- build ----------------------------------------------------------------------------

    def build(self, expedition: int, context: BoundedContext, feedback: str = "",
              artifact_dir: str | None = None, standards: tuple = (),
              keep_worktree: bool = True, log_path: str | None = None) -> BuildResult:
        wt = Path(artifact_dir or ".") / "mvp" / "wt"
        # ADOPT rather than destroy, when there is something recognisable to adopt.
        standing = self.standing_work(expedition, wt)
        if standing:
            base_sha, carried = standing
            branch = f"exp-{expedition}"
        else:
            carried = ""
            try:
                branch, base_sha = self.make_worktree(expedition, wt)
            except RuntimeError as e:
                return BuildResult(False, detail=str(e))

        session = self._session(str(wt))
        if log_path:
            # Stream to disk like the wireframe rung does. This is the LONGEST session in the
            # ladder — twenty minutes is normal — and it was the only one that buffered, so a
            # build killed mid-flight left a stack trace and no transcript at all: the one rung
            # where "what was it doing when it died" is most expensive to re-derive.
            session.log_path = log_path
        res = session.run(self.prompt(context, feedback, standards, carried),
                          system=self.system_prompt())
        calls = [res.call]
        if res.timed_out:
            return BuildResult(False, branch=branch, worktree=str(wt), calls=calls,
                               detail=(f"the build session hit its {session.timeout_s}s wall clock "
                                       "before finishing"))

        # Stage everything first. A new file is the most normal thing a feature adds, and `git
        # diff` cannot see one until it is tracked — without this the diff a human reviews, and the
        # line count measured against the budget, would both silently omit every added file.
        _git(wt, "add", "-A")

        # The diff against the commit the worktree started from: covers the session's work whether
        # it committed or left the tree dirty, so "did you actually change anything" has one answer.
        diff = _git(wt, "diff", base_sha).stdout
        files = sorted(set(_git(wt, "diff", "--name-only", base_sha).stdout.split()))

        violations: list[str] = []
        if not files:
            violations.append("the session changed nothing — there is no diff to review")

        lines = diff_line_count(diff)

        test_passed, test_output = self.run_tests(wt)
        if not test_passed:
            violations.append("the vessel's own check is not green")

        # Persist the evidence next to the expedition. Rung 5 needs the diff and the check's real
        # output to assemble a review package, and it runs in a later activity that has nothing but
        # the expedition number — so what rung 4 proved has to survive on disk, not in memory.
        art = Path(artifact_dir or ".") / "mvp"
        art.mkdir(parents=True, exist_ok=True)
        (art / "diff.patch").write_text(diff, encoding="utf-8")
        (art / "test-output.txt").write_text(test_output, encoding="utf-8")
        (art / "summary.json").write_text(json.dumps({
            "branch": branch, "base": base_sha, "files_changed": files, "lines_changed": lines,
            "test_passed": test_passed, "violations": violations,
            "commits": commit_blocks(wt, base_sha), "size": self.size,
            "size_notes": size_notes(commit_blocks(wt, base_sha), lines, self.size,
                                     self.line_budget),
            "note": (res.text or "").strip()[:1200]}, indent=2), encoding="utf-8")

        # COMMIT WHAT THE RUNG PROVED. The comment above says the diff covers the session's work
        # "whether or not it remembered to commit" — which is true, and which quietly made this
        # rung's definition of done incompatible with the next one's. Rung 4 measured a dirty tree
        # and passed; rung 5 asked GitHub for a pull request from a branch with no commits and got
        # 422 "No commits between main and exp-22", with 229 lines of finished, tested work sitting
        # right there in the worktree.
        #
        # Each rung was correct on its own and they had never once been run together. So the rung
        # that does the work now leaves it in the form the next rung needs: the BRANCH is the
        # artifact, not the working tree. That also makes an interrupted build easier to resume —
        # a commit survives anything, staged state is one `git checkout` from gone.
        if not violations:
            # Whatever the session left uncommitted becomes the LAST block. It used to be the
            # only one: the session was told "never commit on the default branch" and nothing
            # else, so every change arrived as a single commit however large.
            if _git(wt, "diff", "--cached", "--quiet").returncode != 0:
                _git(wt, "commit", "-q", "-m",
                     f"exp-{expedition}: {(context.spec or '').strip().splitlines()[0][:72]}")
            head = _git(wt, "rev-parse", "HEAD").stdout.strip()
            if head == base_sha:
                violations.append(
                    "the work was not committed, so there is nothing to open a pull request from")

        commits = commit_blocks(wt, base_sha)
        notes = size_notes(commits, lines, self.size, self.line_budget)
        result = BuildResult(
            passed=not violations, branch=branch, worktree=str(wt), diff=diff,
            files_changed=files, lines_changed=lines, test_passed=test_passed,
            test_output=test_output, note=(res.text or "").strip()[:1200],
            commits=commits, size=self.size, size_notes=notes,
            violations=violations, calls=calls,
            detail=("; ".join(violations) if violations else
                    f"{len(files)} file(s), {lines} changed lines, check green on {branch}"))
        if not keep_worktree:
            self.cleanup(wt)
        return result


def release_worktree(repo_dir: str | Path, wt: str | Path, *, branch: str = "",
                     delete_branch: bool = False) -> str:
    """Let go of a worktree a run no longer needs. Returns a one-line account of what it did.

    NOTHING DID THIS. `cleanup()` above is reachable only through `build(keep_worktree=False)`,
    and every live build keeps its tree — correctly, because rung 5 ships from it and a retry
    adopts it. But a run that MERGED, or that a person STOPPED, will never come back for the tree,
    and none of that code ever said so: twenty-seven expedition worktrees on the box, each a full
    checkout of the vessel, none of them ever going to be read again.

    The rule is "as long as the run might still need it": removed on `done`/`docked` (the code is
    on main; the remote branch is GitHub's) and on a human kill; kept on a failure park, because
    `/retry` adopts it and that is the whole point of `standing_work`. Only the checkout goes —
    `mvp/diff.patch`, `test-output.txt`, `summary.json` and the session logs are the evidence the
    Detail screen and the cause record read, and they live beside the tree, not in it.

    Best effort throughout: bookkeeping must never fail a rung.
    """
    wt = Path(wt)
    did = []
    if wt.exists():
        r = _git(repo_dir, "worktree", "remove", "--force", str(wt))
        if r.returncode != 0:
            shutil.rmtree(wt, ignore_errors=True)
        did.append("removed the checkout")
    if delete_branch and branch:
        if _git(repo_dir, "branch", "-D", branch).returncode == 0:
            did.append(f"deleted local {branch}")
    _git(repo_dir, "worktree", "prune")
    return "; ".join(did) or "nothing to release"

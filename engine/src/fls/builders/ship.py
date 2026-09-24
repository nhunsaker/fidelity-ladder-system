"""The GitHub surface: the branch becomes a pull request, and then — on a human yes — a merge.

This module is used by two rungs, which is the part worth stating plainly. **Rung 4** pushes the
branch, opens the pull request with the feature switched off, and marks it ready for review, which
is the event that gets it onto stage. **Rung 5** merges it.

Rung 5 is still `propose-only`: without a person it does nothing at all. What changed is what it
proposes — a merge, rather than the mere existence of a draft pull request. That is defensible
*only* because of the flag contract: every change merges with its flag off in both environments, so
a merge moves code without releasing a feature. Turning the flag on is a separate deliberate act,
outside the ladder entirely. Take the contract away and an automated merge stops being defensible
immediately.

It still never deploys to production and never turns a flag on. Everything it refuses, it refuses
*before* asking for anyone's attention:

* **Reviewability** — a diff past the line budget, or one with no walkthrough to orient the
  reviewer, is parked rather than presented (`enforce_reviewability`).
* **The flag is off** — the whole point of shipping behind a flag is that merging changes nothing
  until a person decides otherwise. A branch whose `flags.json` has any flag switched on is
  refused, because it would go live the moment it merged.
* **A credential is required to push, and its absence is said plainly** rather than discovered
  halfway through.

The repository is read from the checkout's own remote, so the pull request cannot be opened against
a repository the vessel is not actually a clone of. The token is passed to git through a credential
helper reading the environment, never in the URL or the argument list, where it would be visible in
`ps` and left behind in the reflog.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from fls.rung4 import PRPackage
from fls.rung5 import ReviewabilityRefused, enforce_reviewability

# Ask git for the token through a helper that reads the environment. The alternatives all leak:
# a token in the remote URL is written to the reflog and to `git remote -v`, and one passed with
# `-c http.extraheader=` is visible in `ps` for the life of the push.
_CRED_HELPER = ('!f() { echo "username=x-access-token"; echo "password=$FLS_GIT_TOKEN"; }; f')

_SLUG = re.compile(r"github\.com[:/]+([^/]+/[^/.]+?)(?:\.git)?/?$")


@dataclass
class ShipOutcome:
    passed: bool
    pr_url: str = ""
    pr_number: int | None = None
    branch: str = ""
    slug: str = ""
    pushed: bool = False
    already_open: bool = False
    violations: list[str] = field(default_factory=list)
    detail: str = ""
    # The flag this change introduced, when there is exactly one. A reviewer has to turn it on to
    # see the feature, and the surface that tells them cannot invent its name.
    flag: str = ""

    def artifacts(self) -> dict:
        return {"ship": {"pr_url": self.pr_url, "pr_number": self.pr_number,
                         "branch": self.branch, "repo": self.slug, "pushed": self.pushed,
                         "already_open": self.already_open, "violations": self.violations,
                         "flag": self.flag}}


def _git(cwd: str | Path, *args: str, env: dict | None = None,
         timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          timeout=timeout, check=False, env=env)


def slug_from_remote(repo_dir: str | Path, remote: str = "origin") -> str:
    """`owner/name` from the checkout's own remote.

    Derived rather than configured on purpose: a pull request opened against a repository the
    vessel is not a clone of would be nonsense, and a variable can drift from the checkout while a
    remote cannot.
    """
    url = _git(repo_dir, "remote", "get-url", remote).stdout.strip()
    m = _SLUG.search(url)
    return m.group(1) if m else ""


def base_ref(worktree: str | Path, base: str = "main", remote: str = "origin") -> str:
    """The ref to compare a branch against: `origin/main` when it exists, else `main`.

    THE REMOTE-TRACKING REF WINS, and the reason is a bug that shipped. The build rung works in a
    worktree of a long-lived vessel checkout that nothing ever pulls, so its local `main` is as
    fresh as the day it was cloned. On this instance that meant a `main` with NO flags in it while
    the real one had four — so `flags_added` saw the branch adding five, "exactly one or none"
    fired, and the pull request told a reviewer that a change which added `street-jump` had added
    no flag at all. The stage link in the same pull request named the flag correctly, because the
    webhook asks GitHub rather than the local checkout.

    `origin/main` is also the honest answer to the question being asked: it is what the pull
    request will be merged into.
    """
    for ref in (f"{remote}/{base}", base):
        if _git(worktree, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0:
            return ref
    return ""


def flags_added(worktree: str | Path, flags_file: str = "flags.json",
                base: str = "main") -> list[str]:
    """Flag names this branch introduces that its base does not have.

    Derived from git rather than read off the branch alone, because "the flags in this file" and
    "the flag this change added" stop being the same list the moment a vessel has more than one.
    The demo names the flag a reviewer has to turn on, and naming the wrong one is worse than
    naming none — so anything that cannot be determined returns empty and the surface says less.
    """
    def _keys(text: str) -> set:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return set()
        return {k for k in data if isinstance(data, dict) and not k.startswith("_")}

    here = Path(worktree) / flags_file
    if not here.exists():
        return []
    ref = base_ref(worktree, base)
    if not ref:
        return []
    try:
        before = _git(worktree, "show", f"{ref}:{flags_file}")
        prior = _keys(before.stdout) if before.returncode == 0 else set()
    except Exception:  # noqa: BLE001 — no base to compare against means no claim to make
        return []
    return sorted(_keys(here.read_text(encoding="utf-8")) - prior)


def flags_switched_on(flags_path: str | Path) -> list[str]:
    """Flags that are on. Keys beginning with `_` are notes, not flags."""
    p = Path(flags_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ["flags.json is not valid JSON"]
    on = []
    for name, state in data.items():
        if name.startswith("_") or not isinstance(state, dict):
            continue
        for env_name, value in state.items():
            if value is True:
                on.append(f"{name}.{env_name}")
    return sorted(on)


class PullRequestShipper:
    """Push the rung-4 branch and open a draft pull request against the vessel's own repository."""

    def __init__(self, repo_dir: str | Path, token: str | None = None, slug: str | None = None,
                 remote: str = "origin", base: str = "main", line_budget: int = 400,
                 draft: bool = True, api=None, flags_file: str = "flags.json",
                 graphql=None):
        self.repo_dir = Path(repo_dir)
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._slug = slug
        self.remote = remote
        self.base = base
        self.line_budget = line_budget
        self.draft = draft
        self.flags_file = flags_file
        self._api = api or self._request
        self._graphql_call = graphql


    # ---- the GitHub call ------------------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(
            f"https://api.github.com{path}",
            data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={"authorization": f"Bearer {self.token}",
                     "accept": "application/vnd.github+json",
                     "user-agent": "fls-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"GitHub {method} {path} -> {e.code}: {body}") from e

    def _graphql(self, query: str, variables: dict) -> dict:
        """The one thing REST cannot do: clearing a pull request's draft flag.

        Kept beside `_request` and swappable the same way (`api=` in the constructor overrides
        REST; `graphql=` overrides this), so a test never reaches the network.
        """
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(), method="POST",
            headers={"authorization": f"Bearer {self.token}",
                     "accept": "application/vnd.github+json",
                     "user-agent": "fls-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return {"errors": [{"message": f"{e.code}: {e.read().decode(errors='replace')[:300]}"}]}

    # ---- the steps ------------------------------------------------------------------------

    def slug(self) -> str:
        if self._slug is None:
            self._slug = slug_from_remote(self.repo_dir, self.remote)
        return self._slug

    def push(self, worktree: str | Path, branch: str) -> subprocess.CompletedProcess:
        """Push the working branch. The token reaches git through the environment, never argv."""
        env = dict(os.environ)
        env["FLS_GIT_TOKEN"] = self.token
        env["GIT_TERMINAL_PROMPT"] = "0"      # fail rather than hang waiting for a password
        return _git(worktree, "-c", f"credential.helper={_CRED_HELPER}",
                    "push", "--force-with-lease", self.remote,
                    f"HEAD:refs/heads/{branch}", env=env, timeout=300)

    def existing_pr(self, branch: str) -> dict:
        owner = self.slug().split("/")[0]
        found = self._api("GET", f"/repos/{self.slug()}/pulls?head={owner}:{branch}&state=open")
        return found[0] if isinstance(found, list) and found else {}

    def open_pr(self, branch: str, title: str, body: str) -> tuple[dict, bool]:
        """Open the pull request, or return the one already open for this branch.

        Idempotent because a rung can legitimately run twice — a retry after a transient failure
        must not fail on GitHub's "a pull request already exists" 422.
        """
        if existing := self.existing_pr(branch):
            # A REUSED PULL REQUEST GETS THE NEW BODY. The idempotence below is about not failing
            # on GitHub's 422; it was also, by accident, freezing the description at whatever the
            # FIRST attempt wrote. A retried build changes the diff, the test output and the flag
            # it added — and the reviewer was reading the previous attempt's account of all three.
            # Best effort: a body that could not be updated is a stale description, not a failed
            # ship, and refusing here would throw away a push that already succeeded.
            try:
                self._api("PATCH", f"/repos/{self.slug()}/pulls/{existing['number']}",
                          {"title": title, "body": body})
            except Exception:  # noqa: BLE001
                pass
            return existing, True
        pr = self._api("POST", f"/repos/{self.slug()}/pulls",
                       {"title": title, "body": body, "head": branch, "base": self.base,
                        "draft": self.draft})
        return pr, False

    def mark_ready(self, number: int) -> tuple[bool, str]:
        """Take the pull request out of draft. Returns (did it, what to say).

        This is the act that produces the deliverable. Marking ready is the event the harness's own
        webhook listens for (`github_surface._stage_if_green`): checks go green, the branch is
        built, and the change lands on the stage site. Until this happens rung 4 has produced a
        diff and nothing a person can open.

        Idempotent — a PR already out of draft reports success, because a retry must not fail on
        work that is already done.
        """
        pr = self._api("GET", f"/repos/{self.slug()}/pulls/{number}")
        if not isinstance(pr, dict) or "number" not in pr:
            return False, f"could not read pull request #{number}"
        if pr.get("draft") is False:
            return True, "already ready for review"
        # Draft state lives on the GraphQL API; the REST `PATCH` cannot clear it.
        node = pr.get("node_id") or ""
        if not node:
            return False, "the pull request did not report a node id, so draft cannot be cleared"
        call = self._graphql_call or self._graphql
        out = call(
            "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
            "{pullRequest{isDraft}}}", {"id": node})
        if out.get("errors"):
            return False, f"could not mark ready: {str(out['errors'])[:160]}"
        return True, "ready for review"

    def merge(self, number: int, method: str = "squash") -> tuple[bool, str]:
        """Merge the pull request, or say plainly why it cannot be.

        SHIP MEANS MERGED. It used to mean "a draft pull request exists", which is not shipping,
        and the ladder's last stage promised something it had not done.

        Safe to put behind one human yes ONLY because of the flag contract: every change merges
        with its flag off in both environments, so this moves code without releasing a feature.
        Turning the flag on stays outside the ladder, which is the whole reason an automated merge
        is defensible here and would not be anywhere else.

        A branch that cannot merge is refused with the reason. Pull request #7 conflicts with main
        right now, and "could not merge: this branch has conflicts" is a far better last line than
        a silent success.
        """
        pr = self._api("GET", f"/repos/{self.slug()}/pulls/{number}")
        if not isinstance(pr, dict) or "number" not in pr:
            return False, f"could not read pull request #{number}"
        if pr.get("merged"):
            return True, "already merged"
        if pr.get("draft"):
            return False, "the pull request is still a draft — it was never made ready for review"
        if pr.get("mergeable") is False:
            return False, ("this branch has conflicts with the base and cannot be merged as it "
                           "stands — it needs rebasing on the latest main")
        out = self._api("PUT", f"/repos/{self.slug()}/pulls/{number}/merge",
                        {"merge_method": method})
        if isinstance(out, dict) and out.get("merged"):
            return True, f"merged into {self.base}"
        why = (out or {}).get("message") if isinstance(out, dict) else ""
        return False, f"the merge was refused: {str(why or out)[:180]}"

    # ---- ship -----------------------------------------------------------------------------

    def ship(self, expedition: int, branch: str, package: PRPackage,
             worktree: str | Path, title: str = "") -> ShipOutcome:
        slug = self.slug()
        violations: list[str] = []
        if not self.token:
            violations.append("no outbound token (GITHUB_TOKEN unset) — cannot push")
        if not slug:
            violations.append(f"cannot read a GitHub repository from the {self.remote} remote")
        try:
            enforce_reviewability(package, self.line_budget)
        except ReviewabilityRefused as e:
            violations.append(str(e))

        # The flag must be OFF. Shipping behind a flag only means anything if merging changes
        # nothing; a branch that arrives with its flag on would go live on merge.
        on = flags_switched_on(Path(worktree) / self.flags_file)
        if on:
            violations.append("these flags are switched ON and would go live on merge: "
                              + ", ".join(on))

        if violations:
            return ShipOutcome(False, branch=branch, slug=slug, violations=violations,
                               detail="; ".join(violations))

        pushed = self.push(worktree, branch)
        if pushed.returncode != 0:
            detail = (pushed.stderr or pushed.stdout).strip()[-300:]
            return ShipOutcome(False, branch=branch, slug=slug,
                               violations=[f"push failed: {detail}"],
                               detail=f"push failed: {detail}")

        # Exactly one, or none. Two flags in one change is a real possibility and there is no
        # honest way to tell a reviewer "turn on the flag" when there are two of them.
        #
        # ASKED BEFORE THE BODY IS RENDERED, not after. The package's "How to verify" section is
        # the link a reviewer actually opens, and it needs the flag name to build that link — but
        # this question was asked one line AFTER `as_markdown()` had already run, so the body was
        # always rendered by something that did not yet know the answer.
        added = flags_added(worktree, self.flags_file)
        package.flag = added[0] if len(added) == 1 else ""

        try:
            pr, already = self.open_pr(branch, title or f"Expedition {expedition}", package.as_markdown())
        except RuntimeError as e:
            return ShipOutcome(False, branch=branch, slug=slug, pushed=True,
                               violations=[str(e)], detail=str(e))

        url = pr.get("html_url", "")
        return ShipOutcome(
            True, pr_url=url, pr_number=pr.get("number"), branch=branch, slug=slug, pushed=True,
            already_open=already, flag=added[0] if len(added) == 1 else "",
            detail=(f"{'reused open' if already else 'opened'} {'draft ' if self.draft else ''}"
                    f"pull request {url} — flag off, awaiting human sign-off"))

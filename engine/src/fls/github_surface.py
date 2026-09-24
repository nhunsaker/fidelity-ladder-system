"""The GitHub surface made real (V2-P2) — issues ARE expeditions.

Inbound: the GitHub App posts signed webhooks; we verify the HMAC (fail-closed: no configured
secret or a bad signature = refused, never processed on optimism) and map events onto the
harness — issues.opened runs the REAL admission gate; issue-comment commands (/advance,
/pick N, /approve) are the human protocol.

Outbound: expedition state mirrors TO the issue (labels + comments) through a small client.
Auth is a token (installation token or fine-grained PAT) from env GITHUB_TOKEN — the App's
JWT flow can mint one out-of-band; the harness never holds the App private key.

Every human decision that arrives here lands in the ledger with human-latency timestamps
(gate_opened_at = when the harness asked, human_responded_at = the webhook's arrival).
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from fls.adjudicator import Idea
from fls.anchor import Anchor, Verdict
from fls.controller import on_idea
from fls.expedition import CLIMBING, DOCKED, NEEDS_HUMAN, Expedition
from fls.ledger import Decision, Ledger
from fls.store import RUNG_NAMES, ExpeditionStore

REPO = os.environ.get("FLS_REPO", "")  # instance config; outbound refuses when unset


# ── inbound: signature (fail-closed) ──────────────────────────────────────────
def verify_signature(secret: str | None, body: bytes, signature_header: str | None) -> bool:
    """GitHub X-Hub-Signature-256 check. No secret configured or no/bad header -> False."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# ── issue-form parsing (the expedition template renders ### sections) ─────────
_SECTION = re.compile(r"###\s+(?P<key>[^\n]+)\n+(?P<val>.*?)(?=\n###\s|\Z)", re.DOTALL)


def parse_issue_form(body_md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _SECTION.finditer(body_md or ""):
        out[m.group("key").strip().lower()] = m.group("val").strip()
    return out


log = logging.getLogger("fls.github")


# ── outbound client ───────────────────────────────────────────────────────────
class GitHubClient(Protocol):
    def post_comment(self, issue: int, text: str) -> None: ...
    def set_labels(self, issue: int, labels: list[str]) -> None: ...
    def create_deployment(self, env: str, ref: str) -> bool: ...
    def get_issue(self, issue: int) -> dict: ...
    def list_comments(self, issue: int) -> list: ...


@dataclass
class RestGitHubClient:
    """Minimal REST client. Token from env GITHUB_TOKEN (installation token / fine-grained PAT)."""
    repo: str = REPO
    token: str | None = None

    def __post_init__(self) -> None:
        self.token = self.token or os.environ.get("GITHUB_TOKEN")

    def checks_state(self, sha: str) -> tuple[str, str]:
        """`(state, detail)` for a commit's checks — "green" | "pending" | "red" | "unknown".

        Both surfaces are read, because a repo can use either: check RUNS come from GitHub
        Actions and the combined STATUS from older integrations, and a repo using only one would
        look like it had no signal at all if the other were consulted alone. Anything the API
        will not answer is `unknown`, which the caller must treat as "do not deploy" — this is a
        gate, and a gate that opens when it cannot see is not a gate.
        """
        try:
            runs = self._req("GET", f"/commits/{sha}/check-runs")
            items = runs.get("check_runs", []) if isinstance(runs, dict) else []
        except Exception as ex:  # noqa: BLE001 — an unreadable gate is a closed gate
            return "unknown", f"could not read the checks: {str(ex)[:120]}"
        if not items:
            try:
                st = self._req("GET", f"/commits/{sha}/status")
                state = st.get("state", "") if isinstance(st, dict) else ""
            except Exception as ex:  # noqa: BLE001
                return "unknown", f"could not read the checks: {str(ex)[:120]}"
            if state == "success":
                return "green", "all checks passed"
            if state in ("pending", ""):
                return "pending", "the checks have not finished"
            return "red", f"the commit status is {state}"

        unfinished = [c for c in items if c.get("status") != "completed"]
        if unfinished:
            names = ", ".join(c.get("name", "?") for c in unfinished[:3])
            return "pending", f"still running: {names}"
        # `neutral` and `skipped` are not failures; a skipped job is one that decided it had
        # nothing to do, and treating that as red would block every PR that skips a matrix leg.
        bad = [c for c in items
               if c.get("conclusion") not in ("success", "neutral", "skipped")]
        if bad:
            names = ", ".join(f"{c.get('name', '?')} ({c.get('conclusion')})" for c in bad[:3])
            return "red", f"failing: {names}"
        return "green", f"{len(items)} checks passed"

    def _req(self, method: str, path: str, payload: dict | None = None) -> dict | list:
        if not self.repo:
            raise RuntimeError("FLS_REPO not set — outbound GitHub calls refuse (fail-closed)")
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}{path}",
            data=json.dumps(payload).encode() if payload is not None else None, method=method,
            headers={"authorization": f"Bearer {self.token}",
                     "accept": "application/vnd.github+json",
                     "user-agent": "fls-engine/0.1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")

    def post_comment(self, issue: int, text: str) -> None:
        self._req("POST", f"/issues/{issue}/comments", {"body": text})

    def set_labels(self, issue: int, labels: list[str]) -> None:
        self._req("PUT", f"/issues/{issue}/labels", {"labels": labels})

    def create_deployment(self, env: str, ref: str) -> bool:
        d = self._req("POST", "/deployments",
                      {"ref": ref, "environment": env, "auto_merge": False,
                       "required_contexts": []})
        return "id" in d

    def get_issue(self, issue: int) -> dict:
        d = self._req("GET", f"/issues/{issue}")
        return d if isinstance(d, dict) else {}

    def list_comments(self, issue: int) -> list:
        d = self._req("GET", f"/issues/{issue}/comments?per_page=100")
        return d if isinstance(d, list) else []


@dataclass
class NullClient:
    """Records outbound calls instead of sending (tests + no-token dev)."""
    comments: list[tuple[int, str]] = field(default_factory=list)
    labels: list[tuple[int, list[str]]] = field(default_factory=list)
    deployments: list[tuple[str, str]] = field(default_factory=list)
    issues: dict[int, dict] = field(default_factory=dict)

    def post_comment(self, issue: int, text: str) -> None:
        self.comments.append((issue, text))

    def set_labels(self, issue: int, labels: list[str]) -> None:
        self.labels.append((issue, labels))

    def create_deployment(self, env: str, ref: str) -> bool:
        self.deployments.append((env, ref))
        return True

    def get_issue(self, issue: int) -> dict:
        return self.issues.get(issue, {"html_url": f"https://example.test/issues/{issue}",
                                       "title": f"issue {issue}", "body": ""})

    def list_comments(self, issue: int) -> list:
        return [{"user": {"login": "harness"}, "body": t, "created_at": ""}
                for n, t in self.comments if n == issue]


# ── event handling: the round-trip ────────────────────────────────────────────
def _rung_label(rung: int) -> str:
    return f"rung:{RUNG_NAMES[rung]}" if 0 <= rung < len(RUNG_NAMES) else "rung:0-intent"


class _Notifier:
    """Outbound notifications, best-effort and recorded.

    The harness's decisions are fail-closed: an ambiguous verdict parks, a missing adjudicator
    never admits. Its NOTIFICATIONS must not be, and conflating the two cost real money on
    2026-09-11. The token lacked `Issues: write`, so `set_labels` raised straight out of
    `handle_event` AFTER the admission gate had already run, judged and saved the expedition. The
    endpoint answered 500, GitHub logged a failed delivery, and redelivering that payload would
    have re-run the gate — a second adjudicator call, a second ledger row, for a decision already
    made.

    A comment we could not post is worth saying out loud; it is not worth re-deciding. Failures
    land in `errors`, which the caller returns to GitHub alongside a 200.
    """

    def __init__(self, client):
        self._c = client
        self.errors: list[str] = []

    def set_labels(self, issue: int, labels: list[str]) -> None:
        self._try("set_labels", lambda: self._c.set_labels(issue, labels))

    def post_comment(self, issue: int, text: str) -> None:
        self._try("post_comment", lambda: self._c.post_comment(issue, text))

    def create_deployment(self, env: str, ref: str) -> bool:
        """NOT best-effort. A deployment is a real action whose success the caller branches on;
        swallowing its failure would let the harness report a deploy that never happened."""
        return self._c.create_deployment(env, ref)

    def __getattr__(self, name):
        return getattr(self._c, name)   # reads (get_issue, list_comments) pass straight through

    def _try(self, what: str, fn) -> None:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a notification failure is never a decision failure
            msg = f"{what}: {type(e).__name__}: {str(e)[:120]}"
            log.warning("outbound %s failed (decision stands): %s", what, msg)
            self.errors.append(msg)


def handle_event(event: str, payload: dict, anchor: Anchor, anchor_text: str, judge,
                 store: ExpeditionStore, ledger: Ledger, client: GitHubClient,
                 now: float | None = None, deploy=None) -> dict:
    """Map one verified webhook event onto the harness. Returns a summary dict.

    `client` is wrapped so a failed label/comment is RECORDED, not raised: the decision this
    function makes is already saved by the time we try to talk back, and letting a notification
    error escape turns a cosmetic permission gap into a re-run of the adjudicator."""
    client = _Notifier(client)
    action = payload.get("action", "")
    issue = payload.get("issue", {})
    number = int(issue.get("number", 0) or 0)

    # ---- a new idea-issue: run the REAL admission gate --------------------------------
    if event == "issues" and action == "opened" and number:
        form = parse_issue_form(issue.get("body", ""))
        intent = form.get("intent") or issue.get("title", "").removeprefix("[idea]").strip()
        idea = Idea(number, intent, form.get("success criteria", form.get("success", "")),
                    form.get("altitude", "feature"), form.get("source", "manual"))
        if judge is None:  # fail-closed: no adjudicator -> park as needs-human, never admit
            store.save(Expedition(number, idea, 0, status=NEEDS_HUMAN,
                                  reason="no adjudicator configured (fail-closed)"))
            client.set_labels(number, ["rung:0-intent"])
            client.post_comment(number, "⚠️ Admission parked: no adjudicator configured "
                                        "(fail-closed). A human must resolve.")
            return {"handled": "issues.opened", "number": number, "verdict": "needs-human"}
        verdict, reason = on_idea(idea, anchor, anchor_text, judge, ledger)
        if verdict == Verdict.admit:
            store.save(Expedition(number, idea, 2, status=CLIMBING))
            client.set_labels(number, ["rung:0-intent", f"dial:{anchor.rungs['1-spec'].dial.value}"])
            client.post_comment(number, f"✅ **Admitted** — {reason}\n\nThe funnel will assign "
                                        f"a lane; spec fan-out is next.")
        elif verdict == Verdict.dock:
            store.save(Expedition(number, idea, 0, status=DOCKED, reason=reason))
            client.set_labels(number, ["docked"])
            client.post_comment(number, f"🛑 **Docked** — {reason}")
        else:
            store.save(Expedition(number, idea, 0, status=NEEDS_HUMAN, reason=reason))
            client.set_labels(number, ["rung:0-intent"])
            client.post_comment(number, f"🤔 **Needs a human** — {reason}")
        return {"handled": "issues.opened", "number": number, "verdict": verdict.value,
                "notify_errors": client.errors}

    # ---- comment commands: the human protocol -----------------------------------------
    if event == "issue_comment" and action == "created" and number:
        body = (payload.get("comment", {}).get("body") or "").strip()
        author = payload.get("comment", {}).get("user", {}).get("login", "")
        rec = store.get(number)
        if rec is None:
            return {"handled": "issue_comment", "number": number, "note": "no expedition"}
        cur_rung = RUNG_NAMES.index(rec["rung"]) if rec["rung"] in RUNG_NAMES else 0

        if body.startswith("/advance"):
            new_rung = min(cur_rung + 1, len(RUNG_NAMES) - 1)
            e = _rehydrate(rec, new_rung, CLIMBING)
            store.save(e)
            client.set_labels(number, [_rung_label(new_rung)])
            client.post_comment(number, f"⬆️ Advanced to **{RUNG_NAMES[new_rung]}** by @{author}")
            _record_human(ledger, number, rec, "advance", author, now)
            return {"handled": "/advance", "number": number, "rung": RUNG_NAMES[new_rung]}

        if body.startswith("/pick"):
            m = re.search(r"/pick\s+(\d)", body)
            pick = int(m.group(1)) if m else 0
            e = _rehydrate(rec, cur_rung, CLIMBING)
            e.picked_wireframe = pick
            store.save(e)
            client.post_comment(number, f"🖼️ Pick **#{pick}** recorded by @{author}; advancing.")
            _record_human(ledger, number, rec, f"pick-{pick}", author, now)
            return {"handled": "/pick", "number": number, "pick": pick}

        if body.startswith("/approve"):
            # the prod gate: a named approver arrived through the one protocol
            _record_human(ledger, number, rec, "approve-prod", author, now)
            client.post_comment(number, f"🚀 Prod promotion approved by @{author} — flag flip "
                                        f"proceeds via the Environment gate.")
            return {"handled": "/approve", "number": number, "approved_by": author}

        return {"handled": "issue_comment", "number": number, "note": "no command"}

    # ---- a human marked the pull request ready for review ------------------------------
    #
    # This is the act that puts a change on the stage site, and until now nothing did: staging
    # happened at rung 5a the moment the draft opened, decided by nobody and before the checks
    # had necessarily finished. A draft is by definition not ready; marking it ready is a
    # person saying so, which is exactly the kind of decision this system gives to a person.
    if event == "pull_request" and action in ("ready_for_review", "reopened"):
        return _stage_if_green(payload.get("pull_request") or {}, client, store, deploy)

    # The same path, from the other side. If the checks were still running when it was marked
    # ready, nothing could be decided then — and without this the feature would simply appear
    # not to work, which is the worst way for a gate to fail.
    if event == "check_suite" and action == "completed":
        suite = payload.get("check_suite") or {}
        for pr in suite.get("pull_requests") or []:
            full = _pr_detail(client, int(pr.get("number", 0) or 0))
            if full and not full.get("draft"):
                return _stage_if_green(full, client, store, deploy)
        return {"handled": "check_suite", "note": "no ready-for-review pull request for this commit"}

    return {"handled": "ignored", "event": event, "action": action}


def _pr_detail(client, number: int) -> dict | None:
    """The pull request as GitHub has it now. A check_suite payload carries a THIN pull-request
    stub with no `draft` flag, so deciding from it would stage a draft."""
    if not number:
        return None
    try:
        inner = getattr(client, "inner", client)
        got = inner._req("GET", f"/pulls/{number}")
        return got if isinstance(got, dict) else None
    except Exception:  # noqa: BLE001 — unreadable means undecidable, and undecidable means no
        return None


_STORE: dict = {}


def _stage_if_green(pr: dict, client, store: ExpeditionStore, deploy) -> dict:
    """Deploy a ready-for-review pull request to stage, if and only if its checks are green.

    Fail-closed in all three ways it can fail, each saying which on the pull request itself:
    pending checks wait (the check_suite event returns here), failing checks refuse and name
    what failed, and an unreadable gate refuses too — a gate that opens when it cannot see is
    not a gate.
    """
    # `_publish` is three calls down and does not take a store. Parking it for the duration of
    # this event is smaller than threading it through every signature between here and there, and
    # the handler is the only thing that ever reads it back.
    _STORE["store"] = store
    number = int(pr.get("number", 0) or 0)
    sha = ((pr.get("head") or {}).get("sha") or "")[:40]
    if not number or not sha:
        return {"handled": "pull_request", "note": "no head commit to judge"}
    if pr.get("draft"):
        return {"handled": "pull_request", "number": number, "note": "still a draft"}

    inner = getattr(client, "inner", client)
    state, detail = inner.checks_state(sha) if hasattr(inner, "checks_state") else ("unknown", "no check reader")
    if state == "pending":
        client.post_comment(number, f"⏳ Checks are not finished ({detail}). Nothing is staged yet "
                                    f"— this will run again when they complete.")
        return {"handled": "pull_request", "number": number, "staged": False, "checks": state}
    if state != "green":
        client.post_comment(number, f"⛔ Not staged — {detail}. Stage deploys only from a green "
                                    f"build; push a fix and this runs again.")
        return {"handled": "pull_request", "number": number, "staged": False, "checks": state}

    # Building takes minutes and GitHub gives a webhook ten seconds, so the work happens off the
    # request and says what it found when it is done. The first comment promises nothing.
    client.post_comment(number, f"⏳ Checks green ({detail}). Building `{sha[:7]}` for stage…")
    started = _run_off_request(_publish, sha, number, detail, client, inner, deploy, pr)
    return {"handled": "pull_request", "number": number, "staged": "building" if started else False,
            "sha": sha}


def _run_off_request(fn, *args) -> bool:
    """Run `fn` in a daemon thread. Returns whether it started, never whether it worked."""
    import threading
    try:
        threading.Thread(target=fn, args=args, daemon=True, name="fls-stage").start()
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not start the stage build")
        return False


def _expedition_of(pr: dict) -> int:
    """Which expedition a pull request belongs to, from the branch it is built on.

    The branch is `exp-{n}`, assigned by rung 4 before any work starts — the same "assign, don't
    discover" rule the Figma page follows, and for the same reason: a later process has to find
    this again holding nothing but what is in front of it.
    """
    ref = ((pr.get("head") or {}).get("ref") or "")
    m = re.match(r"^exp-(\d+)$", ref.strip())
    return int(m.group(1)) if m else 0


def _record_stage(store: ExpeditionStore, pr: dict, url: str, flag: str) -> None:
    """Put the stage URL where the DEMO can find it, not only in a comment on GitHub.

    Build's deliverable is a link a person can open, and until this it existed only as prose in a
    pull-request comment — which is exactly the audience that does not read GitHub. The link
    carries the flag parameter already set: every change ships behind a flag that is off, so a bare
    stage link shows the app looking exactly as before and the visitor concludes nothing happened.
    That confusion has already happened here once.
    """
    n = _expedition_of(pr)
    if not (n and url):
        return
    with contextlib.suppress(Exception):
        store.save_artifact_facts(n, {"stage": {
            "url": f"{url}?flags-{flag}=true" if flag else url,
            "plain_url": url, "flag": flag}})


def _publish(sha: str, number: int, detail: str, client, inner, deploy, pr: dict) -> None:
    """Build the named commit, publish it, and say which of those actually happened.

    The bug this replaces: the deploy seam was called with a ref and no artifact, which writes a
    seven-byte marker and returns True. The comment then said "🚀 Staged from a9793ac" while the
    stage site went on serving bytes from hours earlier. A deploy that claims to have happened and
    has not is the failure this whole system is built to refuse, and it shipped here.
    """
    from fls.stage_build import build_ref

    where = (os.environ.get("FLS_STAGE_URL") or "").strip().rstrip("/")
    site, refusal = build_ref(sha)
    if refusal:
        client.post_comment(number, f"⛔ Not staged — {refusal}. Nothing was published.")
        return
    try:
        ok = bool(deploy and deploy.deploy("stage", sha, site) if site
                  else deploy and deploy.deploy("stage", sha))
    except Exception:  # noqa: BLE001 — a deployer that raises has not deployed
        log.exception("stage deploy raised")
        ok = False
    finally:
        if site:
            import shutil
            shutil.rmtree(site.parent, ignore_errors=True)

    if not ok:
        client.post_comment(number, "⛔ The checks are green but the deploy did not happen — "
                                    "nothing is staged. This instance's deploy target refused.")
        return
    if site is None:
        # No build configured: the seam records the ref and publishes no files. That is a real
        # mode, and saying "staged" over it would be the same lie in a quieter voice.
        client.post_comment(number, f"📌 Recorded `{sha[:7]}` as the stage ref. This instance "
                                    f"declares no build command, so no files were published.")
        return
    flag = _new_flag(inner, pr)
    # The demo needs this too, and it is the audience that does not read GitHub.
    _record_stage(_STORE.get("store"), pr, where, flag)
    client.post_comment(number, _staged_comment(sha, detail, where, flag,
                                                _criteria_for(_STORE.get("store"), pr),
                                                _migrations_for(_STORE.get("store"), pr)))


def _new_flag(inner, pr: dict) -> str:
    """The flag this branch introduces, or "" — the same question `flags_added` answers locally,
    asked over the API because the webhook has no worktree.

    Exactly one or none: two flags in one change leaves nothing honest to name, and naming the
    wrong flag is worse than naming none — the reviewer would go and edit something real and
    unrelated.
    """
    import base64

    def keys(ref: str) -> set:
        try:
            got = inner._req("GET", f"/contents/flags.json?ref={ref}")
            data = json.loads(base64.b64decode(got["content"]).decode())
        except Exception:  # noqa: BLE001 — unreadable means unnameable
            return set()
        return {k for k in data if isinstance(data, dict) and not k.startswith("_")}

    head = (pr.get("head") or {}).get("ref") or ""
    base = (pr.get("base") or {}).get("ref") or "main"
    if not head:
        return ""
    added = sorted(keys(head) - keys(base))
    return added[0] if len(added) == 1 else ""


def _checklist(criteria: list[str] | None) -> str:
    """The same boxes as the pull-request body, on the comment that says it is live.

    Repeated rather than linked because this comment arrives minutes after the body was written
    and lands at the bottom of the thread, which is where a reviewer is actually reading when the
    change first becomes openable. Nothing is invented: no criteria, no section.
    """
    items = [c for c in (criteria or []) if str(c).strip()]
    if not items:
        return ""
    return "\n\n**What to check**\n\n" + "\n".join(f"- [ ] {c}" for c in items)


def _migration_note(migrations: list[str] | None) -> str:
    """The same paragraph the pull-request body carries, on the comment that says it is live —
    because the moment a change first becomes openable is the moment a reviewer starts deciding
    about the merge, and a flag that is off does not undo a migration."""
    items = [m for m in (migrations or []) if str(m).strip()]
    if not items:
        return ""
    listed = ", ".join(f"`{m}`" for m in items[:6])
    return ("\n\n**Merging and deploying this PR will apply migrations to support this new "
            f"feature** ({listed}). These changes can be undone if you choose not to go forward "
            "with the feature — but leaving the flag off does not undo them.")


def _migrations_for(store, pr: dict) -> list[str]:
    """Read back from the expedition's own facts, exactly like `_criteria_for`."""
    if store is None:
        return []
    try:
        facts = store.artifact_facts(_expedition_of(pr)) or {}
        return list((facts.get("verify") or {}).get("migrations") or [])
    except Exception:  # noqa: BLE001
        return []


def _criteria_for(store, pr: dict) -> list[str]:
    """What this change said it would do, read back from the expedition's own facts.

    The webhook holds a pull request and nothing else — no spec, no run — so the checklist that
    rung 4 put in the pull-request body would otherwise have no way of reaching the comment that
    says where the change is now live. It is read rather than re-derived: the criteria came from
    the spec once, and asking a second source would be a second chance to disagree.
    """
    if store is None:
        return []
    try:
        facts = store.artifact_facts(_expedition_of(pr)) or {}
        return list((facts.get("verify") or {}).get("criteria") or [])
    except Exception:  # noqa: BLE001 — a comment with no checklist beats no comment
        return []


def _staged_comment(sha: str, detail: str, where: str, flag: str,
                    criteria: list[str] | None = None,
                    migrations: list[str] | None = None) -> str:
    """What is true after a stage deploy, which is less than "it is live".

    The first version said "Staged from <sha>. It is live at <url>." — the BUILD is live; the
    FEATURE is not, because it ships behind a flag that is off. Somebody following that link
    sees the app exactly as it was and reasonably concludes the deploy did nothing. Saying where
    it went without saying it is still switched off is the more useful half of a misleading
    sentence.
    """
    head = f"🚀 Staged from `{sha[:7]}` — checks green ({detail})."
    if not where:
        return head + " This instance stages to a directory with no public URL."
    if not flag:
        return (f"{head}\n\nThe build is on {where}. The change itself is behind a feature flag "
                f"that is **off**, so the site will look unchanged until that flag is turned on."
                + _checklist(criteria) + _migration_note(migrations))
    # The URL override, not the file edit. Editing flags.json and pushing is a commit, a CI run
    # and a deploy to answer "what does it look like" — the slow way round for the thing a
    # reviewer does first. The override is stage-only by design, and `where` IS stage, so it is
    # the right instruction to give here and would be the wrong one to give anywhere else.
    return (f"{head}\n\nThe build is on {where} — but the change is behind `{flag}`, which is "
            f"**off**, so the site looks unchanged.\n\n"
            f"**To see it:** {where}?flags-{flag}=true\n\n"
            f"That switches it on for your browser only, on stage only — nothing is committed and "
            f"nobody else is affected. `?flags-reset` puts it back. To turn it on for everyone, "
            f"set `{flag}` → `stage` to `true` in `flags.json` and push; `prod` stays off either "
            f"way until somebody turns it on there separately." + _checklist(criteria)
            + _migration_note(migrations))


def _rehydrate(rec: dict, rung: int, status: str) -> Expedition:
    """Rebuild an Expedition from its stored record.

    `source` MUST be carried across. It was not, and because the workflow re-saves on every rung
    transition, a run filed through the demo was relabelled `manual` the first time it moved —
    after which the demo surface no longer recognised its own expedition. /demo/active showed
    nothing while a run was plainly in flight, and the visitor door answered "that expedition was
    not filed here" about the one it had just filed. Found 2026-09-12 on expedition 14.

    `success` and `altitude` are read back for the same reason. They are not stored today (see
    `summary`), so they fall back to the old defaults rather than pretending — but they are read
    from the record so that storing them later is a one-line change and not another round of
    this.
    """
    idea = Idea(rec["number"], rec["intent"], rec.get("success", "") or "",
                rec.get("altitude", "") or "feature", source=rec.get("source", "") or "manual")
    target = RUNG_NAMES.index(rec["target"]) if rec.get("target") in RUNG_NAMES else rung
    return Expedition(rec["number"], idea, target, rung=rung, status=status,
                      reason=rec.get("reason") or None)


def _record_human(ledger: Ledger, number: int, rec: dict, verdict: str, author: str,
                  now: float | None) -> None:
    """A human decision arrived via the surface — ledger row w/ latency when we know the ask time."""
    ledger.record(Decision(
        expedition=number, rung=rec.get("rung", "0-intent"), judge_verdict=verdict,
        human_verdict=f"{verdict}:{author}", judge_cost_usd=0.0,
        gate_opened_at=rec.get("gate_opened_at"), human_responded_at=now,
    ))


def open_anchor_pr(branch: str, new_anchor_text: str, section: str, edits: dict,
                   repo: str) -> str:
    """Create branch → commit ANCHOR.md → open the PR (contents API). Requires GITHUB_TOKEN;
    callers check availability first. Returns the PR html_url.

    `repo` is REQUIRED and has no default. It used to default to `REPO` (i.e. FLS_REPO), which is
    the repo whose ISSUES are expeditions — not necessarily the one the CONSTITUTION is versioned
    in. On an instance where those differ, "Open the PR" branched off the wrong repository, and had
    that repo contained an ANCHOR.md it would have committed the instance's constitution into the
    product's repo. A default that is right on some instances and silently wrong on others is worse
    than no default, so the caller must now say where the ANCHOR lives.
    """
    import base64
    c = RestGitHubClient(repo=repo)
    main = c._req("GET", "/git/ref/heads/main")["object"]["sha"]
    try:
        c._req("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": main})
    except Exception:  # noqa: BLE001 — branch may exist from a prior proposal; reuse it
        pass
    cur = c._req("GET", f"/contents/ANCHOR.md?ref={branch}")
    c._req("PUT", "/contents/ANCHOR.md", {
        "message": f"anchor console: edit {section} ({', '.join(edits)})",
        "content": base64.b64encode(new_anchor_text.encode()).decode(),
        "sha": cur["sha"], "branch": branch,
    })
    pr = c._req("POST", "/pulls", {
        "title": f"ANCHOR edit: {section}", "head": branch, "base": "main",
        "body": f"Proposed from the admin ANCHOR console.\n\nSection `{section}`: "
                + ", ".join(f"`{k}` → `{v}`" for k, v in edits.items())
                + "\n\nSchema-validated by the harness; a human reviews and merges — "
                  "the running system never live-pokes.",
    })
    return pr["html_url"]


# ── rung-5 deployer backed by real GitHub Deployments ─────────────────────────
@dataclass
class GitHubEnvDeployer:
    """Deployer that creates a real GitHub Deployment (Environment-gated for production).
    Falls back closed (False) when no token — a missing credential never fakes a deploy."""
    client: GitHubClient

    def deploy(self, env: str, ref: str, artifact=None) -> bool:
        # `artifact` is accepted and ignored ON PURPOSE: a GitHub Deployment records that a ref
        # was deployed and lets GitHub's own environment protection gate it — the bytes travel by
        # whatever pipeline that environment runs, not through us. Silently accepting a directory
        # we will not publish would be worse than refusing it, so it is named here rather than
        # left to be discovered.
        try:
            return self.client.create_deployment(
                {"stage": "staging", "prod": "production"}.get(env, env), ref)
        except Exception:  # noqa: BLE001 — fail closed on any API failure
            return False

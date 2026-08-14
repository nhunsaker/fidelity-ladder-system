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

import hashlib
import hmac
import json
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


def handle_event(event: str, payload: dict, anchor: Anchor, anchor_text: str, judge,
                 store: ExpeditionStore, ledger: Ledger, client: GitHubClient,
                 now: float | None = None) -> dict:
    """Map one verified webhook event onto the harness. Returns a summary dict."""
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
        return {"handled": "issues.opened", "number": number, "verdict": verdict.value}

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

    return {"handled": "ignored", "event": event, "action": action}


def _rehydrate(rec: dict, rung: int, status: str) -> Expedition:
    idea = Idea(rec["number"], rec["intent"], "", "feature")
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
                   repo: str = REPO) -> str:
    """Create branch → commit ANCHOR.md → open the PR (contents API). Requires GITHUB_TOKEN;
    callers check availability first. Returns the PR html_url."""
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

    def deploy(self, env: str, ref: str) -> bool:
        try:
            return self.client.create_deployment(
                {"stage": "staging", "prod": "production"}.get(env, env), ref)
        except Exception:  # noqa: BLE001 — fail closed on any API failure
            return False

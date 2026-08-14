"""V2-P2 — the GitHub surface made real. Signed-webhook round-trip, event mapping, outbound
mirror, real-deployments deployer. All stubbed ($0)."""
import hashlib
import hmac
import json
from pathlib import Path

from fastapi.testclient import TestClient

from fls import app as appmod
from fls.anchor import Anchor
from fls.github_surface import (
    GitHubEnvDeployer,
    NullClient,
    handle_event,
    parse_issue_form,
    verify_signature,
)
from fls.ledger import Ledger
from fls.llm import Call
from fls.store import ExpeditionStore

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"
ANCHOR = Anchor.load(ANCHOR_PATH)
ANCHOR_TEXT = ANCHOR_PATH.read_text()

FORM_BODY = (
    "### Intent\n\nAdd keyboard shortcuts to the settings page\n\n"
    "### Success criteria\n\nevery setting reachable without the mouse\n\n"
    "### Altitude\n\nfeature\n\n### Source\n\nmanual\n"
)


class AdmitJudge:
    def complete(self, prompt, max_tokens=1024, system=None):
        return json.dumps({"verdict": "admit", "reasoning": "traces to north star"}), \
            Call("stub", "stub", 10, 5, 0.0)


class DockJudge:
    def complete(self, prompt, max_tokens=1024, system=None):
        return json.dumps({"verdict": "dock", "reasoning": "does not trace"}), \
            Call("stub", "stub", 10, 5, 0.0)


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ── signature (fail-closed) ────────────────────────────────────────────────────
def test_signature_roundtrip():
    body = b'{"x":1}'
    assert verify_signature("s3cr3t", body, _sig("s3cr3t", body))
    assert not verify_signature("s3cr3t", body, _sig("wrong", body))
    assert not verify_signature("s3cr3t", body, None)
    assert not verify_signature(None, body, _sig("s3cr3t", body))  # unconfigured -> refused


def test_webhook_route_refuses_bad_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "s3cr3t")
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = None
    c = TestClient(appmod.app)
    r = c.post("/webhook/github", content=b"{}",
               headers={"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "issues"})
    assert r.status_code == 403


def test_webhook_route_processes_signed_event(tmp_path, monkeypatch):
    monkeypatch.setenv("FLS_WEBHOOK_SECRET", "s3cr3t")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    appmod.deps.root = Path(tmp_path)
    appmod.deps._store = None
    appmod.deps.judge = AdmitJudge()
    c = TestClient(appmod.app)
    payload = {"action": "opened", "issue": {"number": 7, "title": "[idea] x", "body": FORM_BODY}}
    body = json.dumps(payload).encode()
    r = c.post("/webhook/github", content=body,
               headers={"X-Hub-Signature-256": _sig("s3cr3t", body),
                        "X-GitHub-Event": "issues", "content-type": "application/json"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "admit"
    assert appmod.deps.store.get(7)["status"] == "climbing"


# ── issue-form parsing ─────────────────────────────────────────────────────────
def test_parse_issue_form():
    f = parse_issue_form(FORM_BODY)
    assert f["intent"].startswith("Add keyboard")
    assert f["altitude"] == "feature"
    assert f["success criteria"].startswith("every setting")


# ── event mapping: the round-trip in one place ─────────────────────────────────
def _env(tmp_path):
    store = ExpeditionStore(tmp_path)
    return store, Ledger(tmp_path / "ledger.jsonl"), NullClient()


def test_issue_opened_admit_mirrors_labels_and_comment(tmp_path):
    store, ledger, client = _env(tmp_path)
    payload = {"action": "opened", "issue": {"number": 7, "title": "[idea] x", "body": FORM_BODY}}
    out = handle_event("issues", payload, ANCHOR, ANCHOR_TEXT, AdmitJudge(),
                       store, ledger, client)
    assert out["verdict"] == "admit"
    assert store.get(7)["status"] == "climbing"
    assert client.labels[0][1][0] == "rung:0-intent"      # labels mirrored TO the issue
    assert "Admitted" in client.comments[0][1]
    assert ledger.rows[0].judge_verdict == "admit"        # admission in the ledger


def test_issue_opened_dock(tmp_path):
    store, ledger, client = _env(tmp_path)
    payload = {"action": "opened", "issue": {"number": 8, "title": "[idea] y", "body": FORM_BODY}}
    out = handle_event("issues", payload, ANCHOR, ANCHOR_TEXT, DockJudge(),
                       store, ledger, client)
    assert out["verdict"] == "dock"
    assert store.get(8)["status"] == "docked"
    assert client.labels[0][1] == ["docked"]


def test_issue_opened_without_judge_fails_closed(tmp_path):
    store, ledger, client = _env(tmp_path)
    payload = {"action": "opened", "issue": {"number": 9, "title": "[idea] z", "body": FORM_BODY}}
    out = handle_event("issues", payload, ANCHOR, ANCHOR_TEXT, None, store, ledger, client)
    assert out["verdict"] == "needs-human"                # never a silent admit
    assert store.get(9)["status"] == "needs-human"


def test_advance_command_bumps_rung_and_records_latency(tmp_path):
    store, ledger, client = _env(tmp_path)
    handle_event("issues", {"action": "opened",
                            "issue": {"number": 7, "title": "[idea] x", "body": FORM_BODY}},
                 ANCHOR, ANCHOR_TEXT, AdmitJudge(), store, ledger, client)
    payload = {"action": "created", "issue": {"number": 7},
               "comment": {"body": "/advance", "user": {"login": "nathan"}}}
    out = handle_event("issue_comment", payload, ANCHOR, ANCHOR_TEXT, AdmitJudge(),
                       store, ledger, client, now=1234.5)
    assert out["handled"] == "/advance"
    assert store.get(7)["rung"] == "1-spec"
    assert any(row[1] == ["rung:1-spec"] for row in client.labels)
    human = [d for d in ledger.rows if d.judge_verdict == "advance"]
    assert human and human[0].human_verdict == "advance:nathan"
    assert human[0].human_responded_at == 1234.5          # Yao#3 lands at the surface


def test_pick_command_records_choice(tmp_path):
    store, ledger, client = _env(tmp_path)
    handle_event("issues", {"action": "opened",
                            "issue": {"number": 7, "title": "[idea] x", "body": FORM_BODY}},
                 ANCHOR, ANCHOR_TEXT, AdmitJudge(), store, ledger, client)
    payload = {"action": "created", "issue": {"number": 7},
               "comment": {"body": "/pick 2", "user": {"login": "nathan"}}}
    out = handle_event("issue_comment", payload, ANCHOR, ANCHOR_TEXT, AdmitJudge(),
                       store, ledger, client)
    assert out == {"handled": "/pick", "number": 7, "pick": 2}


def test_deployer_creates_real_deployment_and_fails_closed():
    client = NullClient()
    d = GitHubEnvDeployer(client)
    assert d.deploy("prod", "HEAD") is True
    assert client.deployments == [("production", "HEAD")]   # env name mapped

    class Boom:
        def create_deployment(self, env, ref):
            raise RuntimeError("api down")
        def post_comment(self, i, t): ...
        def set_labels(self, i, labels): ...
    assert GitHubEnvDeployer(Boom()).deploy("prod", "HEAD") is False  # never fakes a deploy

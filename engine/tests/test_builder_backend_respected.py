"""The ANCHOR names the builder. Five places assumed the skill-server instead.

Found 2026-09-11 from the Connections screen, which reported the harness's builder as NEEDS
ATTENTION. The builder was fine — `/usr/bin/claude`, on the service's PATH, working. The SEAM was
probing `SkillServerBuilder.available()` for an instance whose ANCHOR says `backend: claude-code`,
so it asked about an endpoint and key that instance neither has nor needs.

The same assumption sat in `/feeder/run`, where it was not cosmetic: the feeder refused every run
with "skill-server key unavailable (fail-closed)" on a backend it was never configured to use.

A reflection that re-implements the decision it reflects will drift from it. These pin the rule:
whatever `make_builder` returns is what gets probed and what gets run.
"""
from __future__ import annotations

from conftest import ANCHOR_MD

from fls import modules
from fls.anchor import Anchor


def _anchor_with_backend(tmp_path, backend: str) -> Anchor:
    src = ANCHOR_MD.read_text()
    assert "backend: skill-server" in src, "fixture anchor changed; update this test's edit"
    t = tmp_path / "A.md"
    t.write_text(src.replace("backend: skill-server", f"backend: {backend}"))
    return Anchor.load(t)


def test_a_claude_code_instance_is_probed_for_the_cli_not_a_skill_server(tmp_path, monkeypatch):
    """The exact false alarm. With no skill-server env at all, a claude-code instance whose CLI
    exists must report available — the skill-server's absence is irrelevant to it."""
    monkeypatch.delenv("FLS_SKILL_SERVER_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)

    st = modules._workers_status(_anchor_with_backend(tmp_path, "claude-code"))
    assert st["kind"] == "claude-code"
    assert st["available"] is True, "the CLI is on PATH; the skill-server is not its business"
    assert st["detail"]["builder"] == "ClaudeCodeBuilder", "probed the builder that would run"


def test_a_claude_code_instance_without_the_cli_reports_unavailable(tmp_path, monkeypatch):
    """The fix must not have made the seam optimistic — only accurate."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    st = modules._workers_status(_anchor_with_backend(tmp_path, "claude-code"))
    assert st["available"] is False


def test_the_feeder_is_available_when_the_declared_backend_is(tmp_path, monkeypatch):
    """`ideas.feeder` carried the same assumption, so the Feeder screen called itself unavailable
    on every claude-code instance."""
    monkeypatch.delenv("FLS_SKILL_SERVER_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None)

    slots = modules._ideas_status(_anchor_with_backend(tmp_path, "claude-code"))
    feeder = next(s for s in slots if s["kind"] == "feeder")
    assert feeder["available"] is True


def test_a_builder_that_cannot_be_constructed_reports_unavailable_not_a_crash(tmp_path, monkeypatch):
    """Reflection never raises. An erroring builder is an unavailable builder, with the reason."""
    def _boom(*a, **k):
        raise RuntimeError("worker root missing")
    monkeypatch.setattr("fls.llm.make_builder", _boom)
    monkeypatch.setattr("fls.modules.make_builder", _boom)
    st = modules._workers_status(_anchor_with_backend(tmp_path, "claude-code"))
    assert st["available"] is False
    assert "worker root missing" in st["detail"]["error"]


# ── FallbackBuilder answers the question every other builder answers ──────────
def test_fallback_builder_has_an_availability_probe():
    """`make_builder` returns this whenever an ANCHOR authorizes an api fallback, so a caller that
    probed before working hit AttributeError on a perfectly ordinary configuration."""
    from fls.llm import FallbackBuilder

    class _B:
        def __init__(self, ok): self._ok = ok
        def available(self): return self._ok

    assert FallbackBuilder(_B(True), _B(False)).available() is True, "primary carries it"
    assert FallbackBuilder(_B(False), _B(True)).available() is True, "fallback carries it"
    assert FallbackBuilder(_B(False), _B(False)).available() is False
    assert FallbackBuilder(_B(False), None).available() is False, "no fallback authorized"

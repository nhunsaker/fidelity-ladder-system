"""Rung 3's prototype builder: the lint reads the artifact, never the builder's own account of it.

The failure these tests exist to stop is a rung that passes because the session said it did the
work. Every assertion here is about what is on disk.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from fls.builders.prototype import (
    INDEX,
    WALKTHROUGH,
    PrototypeBuilder,
    lint_prototype,
    pack_tokens,
    picked_wireframe,
    render_pack,
)
from fls.llm import Call

PACK = {
    "name": "Test System",
    "id": "TS-1.0",
    "premise": "a premise",
    "tokens": {
        "color": {
            "room": {"felt": {"value": "#121110", "var": "--ns-felt", "role": "the ground"}},
            "signal": {"base": {"value": "#39D0E8", "var": "--ns-signal",
                                "role": "the clock is waiting on you"}},
        },
        "space": {"control": {"tap": {"value": "44px", "var": "--ns-tap"}}},
    },
    "components": [
        {"name": "Button", "class": "ns-btn", "role": "the action",
         "variant_classes": {"act": "ns-btn--act"}, "usage": "one accented action per screen"},
    ],
    "rules": ["the signal means the clock is waiting on you"],
    "refuses": ["green felt"],
}

GOOD_HTML = """<!doctype html>
<html lang="en"><head><style>
:root { --ns-felt: #121110; --ns-signal: #39D0E8; --ns-tap: 44px; }
body { background: var(--ns-felt); }
.ns-btn { min-height: var(--ns-tap); outline: none; }
.ns-btn:focus-visible { outline: 2px solid var(--ns-signal); }
</style></head>
<body><h1>A screen</h1>
<button id="raise" class="ns-btn ns-btn--act">Raise 4,000</button>
<span data-pot>8,000</span>
</body></html>"""

STEPS = [{"action": "click", "selector": "#raise", "expect": "the pot grows"},
         {"action": "assert", "selector": "[data-pot]", "expect": "reads 12,000"}]


def test_pack_tokens_flattens_the_grouping():
    assert pack_tokens(PACK) == {"--ns-felt": "#121110", "--ns-signal": "#39D0E8",
                                 "--ns-tap": "44px"}


def test_render_pack_leads_with_rules_and_respects_the_budget():
    text = render_pack(PACK, 4000)
    assert "RULES" in text and text.index("RULES") < text.index("TOKENS")
    assert "ns-btn" in text and "--ns-signal" in text
    assert len(render_pack(PACK, 200)) <= 200


def test_a_clean_prototype_passes_and_reports_what_it_used():
    v, used, comps = lint_prototype(GOOD_HTML, STEPS, PACK)
    assert v == []
    assert used == ["--ns-felt", "--ns-signal", "--ns-tap"]
    assert comps == ["ns-btn"]


def test_a_hardcoded_value_that_has_a_token_is_a_violation():
    # The drift that matters: the token layer is declared and then bypassed in the body.
    html = GOOD_HTML.replace("background: var(--ns-felt);", "background: #121110;")
    v, _, _ = lint_prototype(html, STEPS, PACK)
    assert any("hardcoded" in x and "--ns-felt" in x for x in v)


def test_the_root_declaration_itself_is_not_counted_as_hardcoding():
    # :root is where the literals legitimately live; flagging them would make the rung unpassable.
    v, _, _ = lint_prototype(GOOD_HTML, STEPS, PACK)
    assert not any("hardcoded" in x for x in v)


def test_a_prototype_that_ignores_the_system_fails():
    html = """<!doctype html><html lang="en"><body><h1>x</h1>
    <button style="background:#ff00aa">go</button></body></html>"""
    v, used, comps = lint_prototype(html, [{"selector": "button"}], PACK)
    assert used == [] and comps == []
    assert any("no design token" in x for x in v)
    assert any("components" in x for x in v)


def test_an_external_asset_breaks_self_containment():
    html = GOOD_HTML.replace("<head>", '<head><script src="https://cdn.example.com/x.js"></script>')
    v, _, _ = lint_prototype(html, STEPS, PACK)
    assert any("self-contained" in x for x in v)


def test_the_accessibility_floor_is_checked():
    html = GOOD_HTML.replace(
        '<button id="raise" class="ns-btn ns-btn--act">Raise 4,000</button>',
        '<div id="raise" class="ns-btn" onclick="go()">Raise 4,000</div>')
    v, _, _ = lint_prototype(html, STEPS, PACK)
    assert any("onclick" in x for x in v)

    no_lang = GOOD_HTML.replace('<html lang="en">', "<html>")
    assert any("lang" in x for x in lint_prototype(no_lang, STEPS, PACK)[0])

    no_h1 = GOOD_HTML.replace("<h1>A screen</h1>", "<p>A screen</p>")
    assert any("<h1>" in x for x in lint_prototype(no_h1, STEPS, PACK)[0])


def test_removing_focus_is_only_a_violation_when_nothing_replaces_it():
    assert not any("focus" in x for x in lint_prototype(GOOD_HTML, STEPS, PACK)[0])
    stripped = GOOD_HTML.replace(".ns-btn:focus-visible { outline: 2px solid var(--ns-signal); }", "")
    assert any("focus" in x for x in lint_prototype(stripped, STEPS, PACK)[0])


def test_a_walkthrough_step_naming_a_missing_element_fails():
    steps = [*STEPS, {"action": "click", "selector": "#nope", "expect": "..."}]
    v, _, _ = lint_prototype(GOOD_HTML, steps, PACK)
    assert any("#nope" in x for x in v)


def test_no_walkthrough_steps_is_a_violation():
    v, _, _ = lint_prototype(GOOD_HTML, [], PACK)
    assert any("no steps" in x for x in v)


# ── the builder end to end, with a session that writes files like the real one ──────────────

@dataclass
class _Res:
    text: str
    call: Call
    timed_out: bool = False


class FakeSession:
    """Stands in for a Claude Code session: writes whatever it was constructed with into its cwd."""

    timeout_s = 900

    def __init__(self, files: dict[str, str], note: str = "built it", timed_out: bool = False):
        self.files = files
        self.note = note
        self.timed_out = timed_out
        self.prompt: str | None = None

    def run(self, prompt: str, system: str = "") -> _Res:
        self.prompt = prompt
        for name, body in self.files.items():
            (Path(self.cwd) / name).write_text(body, encoding="utf-8")
        return _Res(self.note, Call("claude-code", 10, 5, 0.0), self.timed_out)


def _builder(tmp_path, files, **kw):
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps(PACK), encoding="utf-8")
    session = FakeSession(files, **kw)
    b = PrototypeBuilder(pack, session=session)
    return b, session


def test_build_writes_into_the_directory_preview_serves(tmp_path):
    b, session = _builder(tmp_path, {INDEX: GOOD_HTML,
                                     WALKTHROUGH: json.dumps({"steps": STEPS})})
    session.cwd = str(tmp_path / "exp" / "demo")
    r = b.build(7, "add a raise control", artifact_dir=str(tmp_path / "exp"))
    assert r.passed, r.violations
    # GET /preview/{n} serves expeditions/{n}/demo/index.html — the rung writes exactly there.
    assert Path(r.html_path) == tmp_path / "exp" / "demo" / INDEX
    assert r.steps == STEPS
    assert r.components_used == ["ns-btn"]
    assert r.artifacts()["prototype"]["tokens_used"] == ["--ns-felt", "--ns-signal", "--ns-tap"]


def test_a_session_that_writes_nothing_fails_however_confident_its_note(tmp_path):
    b, session = _builder(tmp_path, {}, note="Done! Fully token-driven and accessible.")
    session.cwd = str(tmp_path / "exp" / "demo")
    r = b.build(7, "a screen", artifact_dir=str(tmp_path / "exp"))
    assert not r.passed
    assert "wrote no index.html" in r.detail


def test_a_missing_walkthrough_fails_even_with_a_good_page(tmp_path):
    b, session = _builder(tmp_path, {INDEX: GOOD_HTML})
    session.cwd = str(tmp_path / "exp" / "demo")
    r = b.build(7, "a screen", artifact_dir=str(tmp_path / "exp"))
    assert not r.passed
    assert any("wrote no walkthrough.json" in x for x in r.violations)


def test_malformed_walkthrough_json_is_reported_not_raised(tmp_path):
    b, session = _builder(tmp_path, {INDEX: GOOD_HTML, WALKTHROUGH: "{not json"})
    session.cwd = str(tmp_path / "exp" / "demo")
    r = b.build(7, "a screen", artifact_dir=str(tmp_path / "exp"))
    assert not r.passed
    assert any("not valid JSON" in x for x in r.violations)


def test_a_timeout_is_a_failure_with_its_budget_named(tmp_path):
    b, session = _builder(tmp_path, {}, timed_out=True)
    session.cwd = str(tmp_path / "exp" / "demo")
    r = b.build(7, "a screen", artifact_dir=str(tmp_path / "exp"))
    assert not r.passed and "wall clock" in r.detail


def test_feedback_and_the_picked_wireframe_reach_the_prompt(tmp_path):
    b, session = _builder(tmp_path, {INDEX: GOOD_HTML,
                                     WALKTHROUGH: json.dumps({"steps": STEPS})})
    session.cwd = str(tmp_path / "exp" / "demo")
    b.build(7, "a screen", wireframe="candidate: candidate-2\npremise: two columns",
            feedback="the pot is buried", artifact_dir=str(tmp_path / "exp"))
    assert "the pot is buried" in session.prompt
    assert "candidate-2" in session.prompt
    assert "RULES" in session.prompt


def test_builder_needs_a_session_or_a_factory(tmp_path):
    with pytest.raises(ValueError):
        PrototypeBuilder(tmp_path / "pack.json")


# ── the human's pick, read back from rung 2's artifact ─────────────────────────────────────

def _write_figma(tmp_path) -> Path:
    d = tmp_path / "wireframes"
    d.mkdir(parents=True)
    (d / "figma.json").write_text(json.dumps({
        "page_name": "Expedition 7",
        "candidates": [
            {"name": "candidate-1", "title": "One column", "premise": "stacked",
             "url": "https://figma/1"},
            {"name": "candidate-2", "title": "Two column", "premise": "side by side",
             "url": "https://figma/2"},
        ]}), encoding="utf-8")
    return tmp_path


def test_picked_wireframe_reads_the_human_choice(tmp_path):
    _write_figma(tmp_path)
    text = picked_wireframe(tmp_path, 2)
    assert "candidate-2" in text and "side by side" in text and "Expedition 7" in text


def test_pick_is_one_based_and_out_of_range_falls_back_to_the_first(tmp_path):
    _write_figma(tmp_path)
    assert "candidate-1" in picked_wireframe(tmp_path, 1)
    assert "candidate-1" in picked_wireframe(tmp_path, 99)
    assert "candidate-1" in picked_wireframe(tmp_path, None)


def test_no_rung_two_artifact_is_an_empty_string_not_an_error(tmp_path):
    assert picked_wireframe(tmp_path, 1) == ""


def test_the_prompt_says_the_check_greps_the_file_rather_than_running_the_page():
    """FOUND LIVE, expedition 53 — the same rung, one layer deeper than expedition 45.

    That session DID re-read the file, which is what the previous fix asked for. It still lost the
    rung, because its walkthrough targeted `#streak-d5`, `#practise-d9`, `#choiceWrong1` — ids its
    own JavaScript builds at runtime. They would exist in a browser. The audit greps the file, so
    they do not exist to it.

    It had been told the rule and not how the rule is checked, which is a different omission from
    the one before and produces the same parked run.
    """
    from fls.builders.prototype import _SYSTEM
    assert "LITERALLY IN THE TEXT" in _SYSTEM
    assert "does not run your page" in _SYSTEM
    assert "STATIC id" in _SYSTEM


def test_the_prompt_says_how_to_verify_the_selectors_and_that_there_is_no_shell():
    """FOUND LIVE, expedition 45. The rule "every walkthrough selector must exist in the page"
    was already stated, and the session obeyed it as best it could: it tried three times to check
    with `node -e ...` and was refused each time, because rung 3's tool surface is Write/Read/Edit.
    Unable to verify, it wrote a walkthrough targeting six seats it had never rendered, and the
    rung parked the run for exactly that.

    Knowing a rule and being able to check it are different things, and this prompt only carried
    the first.
    """
    from fls.builders.prototype import _SYSTEM
    assert "NO SHELL" in _SYSTEM
    assert "Read tool" in _SYSTEM
    assert "Write, Read and Edit" in _SYSTEM



def test_rung_3s_build_rules_arrive_whole_at_the_profiles_budget():
    """The cut nobody had noticed: rung 3 split its budget two-thirds pack, one-third rules, and
    `fe_build_rules.md` (3,516 chars) was arriving as its first 2,000 on every run."""
    from fls.builders.prototype import PROMPTS, reading
    from fls.profile import active_profile
    budget = active_profile().rung(3).context_budget_chars // 3
    whole = (PROMPTS / "fe_build_rules.md").read_text(encoding="utf-8")
    assert whole in reading(("fe_build_rules.md",), budget)

"""Rung-2 Figma builder: prompt shape, output contract, structure lint, artifacts (Phase 1)."""
import json

import pytest

from fls.builders.figma_wireframe import (
    FIGMA_TOOLS,
    FigmaWireframeBuilder,
    file_url,
    lint_structure,
    parse_contract,
    reading,
)
from fls.llm import Call

GOOD = {
    "page_name": "exp-7", "page_id": "12:0",
    "candidates": [
        {"name": "exp-7-c1", "node_id": "12:1", "title": "Modal", "premise": "Share opens a modal over the results."},
        {"name": "exp-7-c2", "node_id": "12:2", "title": "Inline panel", "premise": "The share controls expand inline under the result."},
        {"name": "exp-7-c3", "node_id": "12:3", "title": "Second screen", "premise": "Share routes to a dedicated screen with options."},
    ],
    "lint": {"auto_layout": True, "named_layers": True, "detached_instances": False, "notes": ""},
}


class FakeSession:
    """Stands in for a ClaudeCodeSession. Records the prompt so the test can assert on context."""
    timeout_s = 600

    def __init__(self, text="", timed_out=False):
        self.text, self.timed_out_flag = text, timed_out
        self.prompt = self.system = None

    def run(self, prompt, system=None):
        self.prompt, self.system = prompt, system
        from fls.claude_code import SessionResult
        call = Call("claude-code", "claude-sonnet-5", 100, 10, usd=0.0, normalized_usd=0.02,
                    funded_by="subscription")
        return SessionResult(text=self.text, call=call, timed_out=self.timed_out_flag)


def _b(text, timed_out=False, **kw):
    s = FakeSession(text, timed_out=timed_out)
    return FigmaWireframeBuilder("ABC123", session=s, **kw), s


def _fenced(d):
    return "Here is what I built.\n\n```json\n" + json.dumps(d) + "\n```"


def test_contract_parsed_from_the_last_fenced_block():
    noise = "```json\n{\"candidates\": \"draft\"}\n```\n" + _fenced(GOOD)
    assert parse_contract(noise)["page_id"] == "12:0"


def test_missing_contract_is_a_loud_failure():
    with pytest.raises(ValueError, match="no output contract"):
        parse_contract("I made three lovely wireframes.")


def test_build_happy_path():
    b, s = _b(_fenced(GOOD))
    r = b.build(7, "add a share-result modal", artifact_dir=None)
    assert r.passed and len(r.candidates) == 3 and not r.violations
    assert r.candidates[0].url == "https://www.figma.com/design/ABC123?node-id=12-1"
    assert r.calls[0].funded_by == "subscription"
    assert "3 candidates" in r.detail


def test_prompt_carries_file_key_spec_and_reading():
    b, s = _b(_fenced(GOOD))
    b.build(7, "add a share-result modal")
    assert "ABC123" in s.prompt and "exp-7" in s.prompt
    assert "add a share-result modal" in s.prompt
    assert "auto-layout" in s.prompt.lower()          # conventions came along
    assert "0 to 1" in s.prompt or "0 to 1," in s.prompt  # api rules came along
    assert "fenced JSON block" in s.system


def test_feedback_is_foregrounded_on_a_rerun():
    b, s = _b(_fenced(GOOD))
    b.build(7, "spec", feedback="the header is too small")
    assert "the header is too small" in s.prompt
    assert "asked for changes" in s.prompt.lower()


def test_timeout_fails_without_a_contract():
    b, s = _b("partial", timed_out=True)
    r = b.build(7, "spec")
    assert not r.passed and "wall clock" in r.detail and r.calls


@pytest.mark.parametrize("mutate,expected", [
    # Fewer is allowed now, but only with a reason — see test_wireframe_resume.py.
    (lambda d: d["candidates"].pop(), "no reason given"),
    (lambda d: d["candidates"][0].update(node_id=""), "no node_id"),
    (lambda d: d["candidates"][1].update(premise="  "), "declares no premise"),
    (lambda d: d["candidates"][2].update(name="exp-7-c1"), "duplicate candidate name"),
    (lambda d: d["lint"].update(auto_layout=False), "not on auto-layout"),
    (lambda d: d["lint"].update(named_layers=False), "not named for their role"),
    (lambda d: d["lint"].update(detached_instances=True), "detached instances"),
])
def test_lint_catches_each_failure(mutate, expected):
    import copy
    d = copy.deepcopy(GOOD)
    mutate(d)
    v = lint_structure(d, 3)
    assert any(expected in x for x in v), v


def test_a_false_clean_still_fails_the_rung():
    """The session claims everything is fine but built nothing — the rung must not park a human
    in front of an empty page."""
    d = {"page_name": "p", "candidates": [], "lint": {"auto_layout": True, "named_layers": True,
                                                      "detached_instances": False}}
    b, s = _b(_fenced(d))
    r = b.build(7, "spec")
    assert not r.passed and "nothing to look at" in r.detail


def test_artifacts_written(tmp_path):
    b, s = _b(_fenced(GOOD))
    b.build(7, "spec", artifact_dir=str(tmp_path))
    f = tmp_path / "wireframes" / "figma.json"
    d = json.loads(f.read_text())
    assert d["page_name"] == "exp-7" and len(d["candidates"]) == 3
    assert d["candidates"][0]["url"].endswith("node-id=12-1")


def test_reading_is_budgeted_and_shared_evenly():
    small = reading(("wireframe_conventions.md", "figma_api_rules.md"), 1000)
    assert len(small) < 1400 and "wireframe_conventions.md" in small and "figma_api_rules.md" in small


def test_rung2_reads_the_construction_digest_by_default():
    from fls.builders.figma_wireframe import DIGESTS, PROMPTS
    b, s = _b(_fenced(GOOD))
    b.build(7, "spec")
    assert "staiano-figma-craft.md" in s.prompt
    for name in DIGESTS.values():
        assert (PROMPTS / name).exists(), name


def test_tool_surface_is_narrow():
    assert FIGMA_TOOLS == ("mcp__figma__use_figma", "mcp__figma__get_metadata",
                           "mcp__figma__get_screenshot")


def test_file_url_without_node():
    assert file_url("K") == "https://www.figma.com/design/K"


def test_builder_requires_a_session():
    with pytest.raises(ValueError, match="session"):
        FigmaWireframeBuilder("ABC123")


# ── colour: grey unless something actually needs otherwise ─────────────────────────────────
#
# THE BUG THIS BLOCK EXISTS FOR. Every wireframe came back in brand blue, and the rule that says
# it should not have ("No brand color at this rung") had been in `wireframe_conventions.md` the
# whole time. It was never SENT: `reading()` split the 6,000-character budget three ways and cut
# each source at 2,000, and that sentence starts around character 2,070. Meanwhile the surviving
# slice of the craft digest discussed accent palettes and the API rules taught red as the example
# colour. Nothing anywhere checked the result.

GREY = {f"exp-7-c{i}": ["#F5F5F5", "#E0E0E0", "#212121"] for i in (1, 2, 3)}


def _contract(fills=None, **lint):
    import copy
    c = copy.deepcopy(GOOD)
    if fills is not None:
        c["lint"]["fills"] = fills
    c["lint"].update(lint)
    return c


def test_the_colour_rule_survives_the_budget_whole():
    """THE REGRESSION TEST. At the rung's real budget the sentence must be in the text that is
    actually sent, not merely in the file on disk."""
    from fls.builders.figma_wireframe import reading
    text = reading(("wireframe_conventions.md", "figma_api_rules.md", "staiano-figma-craft.md"),
                   8000)
    assert "No brand color at this rung" in text
    assert "Fill 0xF5 for surfaces" in text


def test_the_house_rules_go_in_whole_and_the_digest_takes_what_is_left():
    from fls.builders.figma_wireframe import PROMPTS, reading
    whole = (PROMPTS / "wireframe_conventions.md").read_text(encoding="utf-8")
    text = reading(("wireframe_conventions.md", "figma_api_rules.md", "staiano-figma-craft.md"),
                   8000)
    assert whole in text
    assert "staiano-figma-craft.md" in text, "the digest must still be there"


def test_a_budget_too_small_for_the_house_rules_falls_back_to_an_even_split():
    """No un-arbitrary answer exists below that line, and an arbitrary rule that is stable beats
    a clever one that surprises."""
    from fls.builders.figma_wireframe import reading
    text = reading(("wireframe_conventions.md", "figma_api_rules.md"), 1000)
    assert "wireframe_conventions.md" in text and "figma_api_rules.md" in text
    assert len(text) < 1400


def test_the_rung_2_budget_fits_both_house_files_whole():
    """The budget is policy and the rules are a file; a budget smaller than the rules it is meant
    to deliver is the bug this whole block is about, expressed in config instead of code.

    Only the profile that actually draws Figma frames is held to it — `web-ui` builds its rung-2
    lines a different way and reads none of this.
    """
    from fls.builders.figma_wireframe import HOUSE_SOURCES, PROMPTS
    from fls.profile import PROFILES
    need = sum(len((PROMPTS / n).read_text(encoding="utf-8")) for n in HOUSE_SOURCES)
    figma = [p for p in PROFILES.values() if p.rung(2).artifact_kind == "figma-frames"]
    assert figma, "no profile draws Figma frames any more — this test is watching nothing"
    for profile in figma:
        assert profile.rung(2).context_budget_chars > need, (
            f"{profile.name}'s rung-2 budget cannot carry its own rules whole")


@pytest.mark.parametrize("text", [
    "a share sheet on the hand screen",
    "let me sit out a hand",
    "how far to the next venue",
    "which five cards make my hand",
])
def test_an_ordinary_request_is_greyscale(text):
    from fls.builders.figma_wireframe import colour_policy_for
    p = colour_policy_for(text)
    assert p.greyscale and "nothing in the request" in p.reason


@pytest.mark.parametrize("text,word", [
    ("make the primary button blue", "blue"),
    ("use the brand colour on the header", "colour"),
    ("a red badge for the count", "red"),
    ("match the palette from the settings screen", "palette"),
])
def test_a_request_that_names_a_colour_gets_one(text, word):
    """Arguing with a person who asked for a colour would be the system overruling the person it
    is building for."""
    from fls.builders.figma_wireframe import colour_policy_for
    p = colour_policy_for(text)
    assert not p.greyscale and word in p.reason


@pytest.mark.parametrize("text,word", [
    ("show won / lost / folded at showdown", "won"),
    ("say when the entry is invalid", "invalid"),
    ("a failed payment needs somewhere to go", "failed"),
    ("an error state for a dropped connection", "error"),
    ("which option is selected", "selected"),
])
def test_a_semantic_state_gets_colour_because_grey_would_lie(text, word):
    from fls.builders.figma_wireframe import colour_policy_for
    p = colour_policy_for(text)
    assert not p.greyscale and word in p.reason


@pytest.mark.parametrize("text", [
    "the reaction sits there long after the moment has passed",
    "show the active hand larger",
    "a status line under the table",
])
def test_a_word_that_merely_sounds_like_a_state_does_not_turn_colour_on(text):
    """Read-only pass over 38 real requests: "long after the moment has passed" is a tense, not a
    state. A word earns its place in that list by what it does to real text."""
    from fls.builders.figma_wireframe import colour_policy_for
    assert colour_policy_for(text).greyscale


def test_the_reason_is_carried_so_a_person_can_disagree_with_it():
    """A policy with no stated reason is a policy nobody can audit — and this one is decided from
    words a person wrote, which is exactly the kind of decision that needs showing."""
    from fls.builders.figma_wireframe import colour_policy_for
    assert colour_policy_for("a red badge").reason
    assert colour_policy_for("a badge").reason


def test_the_prompt_states_which_rule_this_run_is_under():
    from fls.builders.figma_wireframe import colour_policy_for
    b, s = _b(_fenced(_contract(GREY)))
    b.policy = colour_policy_for("a share sheet")
    b.build(7, "a share sheet")
    assert "COLOUR: greyscale only" in s.prompt and "r, g and b equal" in s.prompt

    b2, s2 = _b(_fenced(_contract(GREY)))
    b2.policy = colour_policy_for("an error state")
    b2.build(7, "an error state")
    assert "COLOUR ALLOWED" in s2.prompt and "error" in s2.prompt


def test_the_system_prompt_carries_the_rule_where_no_budget_can_cut_it():
    """The instructions are trimmed to a budget; the system prompt is not. The one rule that must
    never be lost belongs in the half that cannot be."""
    from fls.builders.figma_wireframe import _SYSTEM
    assert "GREY unless" in _SYSTEM and "0xF5" in _SYSTEM
    assert '"fills"' in _SYSTEM


def test_a_grey_read_back_passes_under_the_greyscale_policy():
    from fls.builders.figma_wireframe import colour_policy_for, lint_structure
    assert lint_structure(_contract(GREY), 3, colour_policy_for("a share sheet")) == []


def test_a_coloured_fill_names_the_candidate_and_the_colour():
    from fls.builders.figma_wireframe import colour_policy_for, lint_structure
    v = lint_structure(_contract({**GREY, "exp-7-c2": ["#F5F5F5", "#0969DA"]}), 3,
                       colour_policy_for("a share sheet"))
    assert len(v) == 1 and "exp-7-c2" in v[0] and "#0969DA" in v[0]


def test_a_missing_read_back_fails_the_rung_rather_than_passing_quietly():
    """A session that simply omitted the field would otherwise sail through every check this rung
    has — which is exactly how runs of blue wireframes passed a lint whose job is to catch them."""
    from fls.builders.figma_wireframe import colour_policy_for, lint_structure
    v = lint_structure(_contract(), 3, colour_policy_for("a share sheet"))
    assert len(v) == 1 and "cannot check its own colour rule" in v[0]


def test_an_unreadable_fill_is_not_grey():
    """A fill the rung cannot parse is a fill it cannot vouch for, and "probably fine" is the
    answer this whole check exists to stop giving."""
    from fls.builders.figma_wireframe import colour_policy_for, lint_structure
    v = lint_structure(_contract({"exp-7-c1": ["cornflowerblue"]}), 3,
                       colour_policy_for("a share sheet"))
    assert v and "cornflowerblue" in v[0]


def test_near_grey_survives_a_rounding_error():
    """#F5F5F4 is grey by any honest reading, and failing a rung over one hex digit would teach a
    session to stop reporting its fills at all."""
    from fls.builders.figma_wireframe import _is_grey
    assert _is_grey("#F5F5F4") and _is_grey("F5F5F5") and _is_grey("#000000")
    assert not _is_grey("#0969DA") and not _is_grey("#D1242F") and not _is_grey("")


def test_colour_is_not_checked_when_colour_is_allowed():
    """The policy answers one question. A run that may use colour is not then audited on which
    colours it used — that is a design judgement, and this rung does not have one."""
    from fls.builders.figma_wireframe import colour_policy_for, lint_structure
    assert lint_structure(_contract({"exp-7-c1": ["#D1242F"]}), 3,
                          colour_policy_for("an error state")) == []


def test_no_policy_means_no_colour_check_so_every_old_caller_still_means_what_it_meant():
    from fls.builders.figma_wireframe import lint_structure
    assert lint_structure(_contract(), 3) == []


def test_the_decision_is_recorded_beside_the_frames(tmp_path):
    from fls.builders.figma_wireframe import colour_policy_for
    b, _ = _b(_fenced(_contract(GREY)))
    b.policy = colour_policy_for("a share sheet")
    r = b.build(7, "a share sheet", artifact_dir=str(tmp_path))
    assert r.passed, r.detail
    d = json.loads((tmp_path / "wireframes" / "figma.json").read_text())
    assert d["greyscale"] is True and d["colour_reason"]
    assert r.artifacts()["figma"]["greyscale"] is True


def test_a_colour_word_counts_only_when_a_person_wrote_it():
    """FOUND LIVE, expedition 44. The request never mentions colour and the policy still reported
    `the request names a colour ("color")` — the word came from rung 1's own spec. A system that
    reads its own output and calls it the customer's instruction lets a spec authorise itself,
    including one whose sentence is "do not use colour"."""
    from fls.builders.figma_wireframe import colour_policy_for
    p = colour_policy_for("show me which five cards make my hand",
                          spec="Do not rely on colour alone to distinguish them.")
    assert p.greyscale, p.reason


def test_a_semantic_state_still_counts_from_the_spec():
    """A state is a fact about the feature, not a preference about it — rung 1 naming one is rung
    1 correctly noticing something the request implied."""
    from fls.builders.figma_wireframe import colour_policy_for
    p = colour_policy_for("tell me how the hand ended",
                          spec="The banner reports whether the player won or lost the pot.")
    assert not p.greyscale and "won" in p.reason


def test_the_visitors_own_success_criteria_can_ask_for_colour():
    """The second box is the visitor's words too."""
    from fls.builders.figma_wireframe import colour_policy_for
    assert not colour_policy_for("mark the fold button\nit should be red").greyscale


def test_the_prompt_says_the_sentinel_is_not_the_deliverable():
    """FOUND LIVE, expedition 51. The session created its page, printed `FLS-PAGE: exp-51 61:2`,
    and ended its turn — `num_turns` 6 of 30, `stop_reason: end_turn`, fifteen seconds, no
    candidates and no contract. It was not cut off; it believed it was finished.

    "Print it first; everything else follows" is emphatic enough to read as the task if you stop
    there, and once in twelve live runs it did.
    """
    from fls.builders.figma_wireframe import _SYSTEM, FigmaWireframeBuilder
    b, _ = _b(_fenced(GOOD))
    prompt = b.prompt(51, "let me sit out a hand")
    assert "PRINTING IT IS NOT THE JOB" in prompt
    assert "YOUR TURN IS NOT OVER" in _SYSTEM
    assert isinstance(b, FigmaWireframeBuilder)


def test_a_contract_less_final_message_still_fails_the_rung():
    """The guard that caught it is unchanged — the prompt fix is so the guard stops firing."""
    from fls.builders.figma_wireframe import parse_contract
    with pytest.raises(ValueError, match="no output contract"):
        parse_contract("FLS-PAGE: exp-51 61:2")



def test_at_the_profiles_budget_every_default_source_arrives_whole():
    """THE PROPERTY ACTUALLY WANTED. Not "the rules fit" — everything the rung reads arrives
    byte for byte, so the question "what got cut" always answers "nothing"."""
    from fls.builders.figma_wireframe import PROMPTS, FigmaWireframeBuilder, reading
    from fls.profile import active_profile
    budget = active_profile().rung(2).context_budget_chars
    sources = FigmaWireframeBuilder.__init__.__defaults__[3]   # the default `sources` tuple
    text = reading(sources, budget)
    for name in sources:
        assert (PROMPTS / name).read_text(encoding="utf-8") in text, f"{name} was cut"

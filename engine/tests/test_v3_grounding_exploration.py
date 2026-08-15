"""V3-B1: vessel context pack, grounding assembly, grounding injection, fidelity-adaptive rung 2.

Zero network, zero spend — every model is a stub that captures its prompt/system so we can prove
the grounding actually reaches the prompt and the mode actually swaps the system.
"""
from pathlib import Path

import yaml

from fls.adjudicator import Idea, adjudicate
from fls.anchor import _ANCHOR_BLOCK, Anchor
from fls.grounding import build_grounding
from fls.llm import Call
from fls.rung1 import run_rung1
from fls.rung2 import _VARIANTS_SYS, _WIRE_SYS, run_rung2

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"


# ── stubs ─────────────────────────────────────────────────────────────────────
class CaptureModel:
    """Records every (prompt, system) it sees; returns benign fixed output."""
    def __init__(self, reply="<div>x</div>"):
        self.reply = reply
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    def complete(self, prompt, max_tokens=1024, system=None):
        self.prompts.append(prompt)
        self.systems.append(system)
        if "Rank them" in prompt:
            return "[0,1,2]", Call("stub", "stub", 1, 1, 0.0)
        return self.reply, Call("stub", "stub", 1, 1, 0.0)


class StubStore:
    def __init__(self, lessons, wall):
        self._lessons, self._wall = lessons, wall

    def lessons(self):
        return list(self._lessons)

    def wall(self):
        return list(self._wall)


# ── vessel context pack ───────────────────────────────────────────────────────
def test_vessel_block_parses_and_default_resolves():
    a = Anchor.load(ANCHOR_PATH)
    assert a.default_vessel == "acme-demo"
    v = a.vessel()                       # default
    assert v is not None and v.kind == "app"
    assert a.vessel("acme-demo") is v or a.vessel("acme-demo").name == "acme-demo"
    assert any("bootstrap-styled" in s for s in v.standards)
    assert a.vessel("nonexistent") is None


def test_absent_vessel_block_is_backcompat():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data.pop("vessels", None)
    data.pop("default_vessel", None)
    a = Anchor.model_validate(data)      # slim ANCHOR must still validate identically
    assert a.vessels == []
    assert a.default_vessel is None
    assert a.vessel() is None


def test_absent_goal_is_backcompat():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data.pop("goal", None)
    a = Anchor.model_validate(data)      # ANCHOR without goal must still validate identically
    assert a.goal is None
    assert a.resolved_goal() is None


# ── V4: vessel-level audit scope ───────────────────────────────────────────────
def test_vessel_audit_scope_defaults_to_paths():
    a = Anchor.load(ANCHOR_PATH)
    v = a.vessel()                       # default vessel (acme-demo), has paths but no audit_scope
    assert v.audit_scope == []
    assert v.paths                       # sanity: the fixture vessel declares paths
    assert v.effective_audit_scope() == v.paths


def test_vessel_audit_scope_overrides_paths():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    for vessel in data["vessels"]:
        if vessel["name"] == "acme-demo":
            vessel["audit_scope"] = ["src/pages/LandingPage.jsx", "src/pages/**"]
    a = Anchor.model_validate(data)
    v = a.vessel("acme-demo")
    assert v.effective_audit_scope() == ["src/pages/LandingPage.jsx", "src/pages/**"]
    assert v.effective_audit_scope() != v.paths


def test_absent_audit_scope_is_backcompat():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    for vessel in data["vessels"]:
        vessel.pop("audit_scope", None)
    a = Anchor.model_validate(data)      # a vessel block with no audit_scope must still validate identically
    v = a.vessel()
    assert v.audit_scope == []
    assert v.effective_audit_scope() == v.paths


# ── P2a: managed lenses seam ───────────────────────────────────────────────────
def test_lens_block_present_validates_and_resolves():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data["lenses"] = [{
        "kind": "design-audit",
        "params": {
            "mode": "audit-first",
            "panel": "design",
            "target_vessel": "acme-demo",
            "cadence": "weekly",
            "sink_label": "lens:design-audit",
            "cost_envelope_usd": 2.5,
            "volume_cap": 3,
        },
    }]
    a = Anchor.model_validate(data)
    params = a.lens("design-audit")
    assert params.mode == "audit-first"
    assert params.panel == "design"
    assert params.target_vessel == "acme-demo"
    assert params.cadence == "weekly"
    assert params.sink_label == "lens:design-audit"
    assert params.cost_envelope_usd == 2.5
    assert params.volume_cap == 3
    # a kind not present in the lenses: list resolves to defaults, not an error
    defaults = a.lens("no-such-kind")
    assert defaults.mode == "audit-first"
    assert defaults.target_vessel == ""


def test_absent_lenses_block_is_backcompat():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data.pop("lenses", None)
    a = Anchor.model_validate(data)      # ANCHOR without lenses: must still validate identically
    assert a.lenses == []
    params = a.lens("design-audit")      # fails open to defaults, never raises
    assert params.mode == "audit-first"
    assert params.target_vessel == ""
    assert params.volume_cap == 5


# ── grounding assembly ────────────────────────────────────────────────────────
def test_grounding_sections_and_determinism():
    a = Anchor.load(ANCHOR_PATH)
    store = StubStore(
        lessons=["l1", "l2", "l3", "l4"],
        wall=[{"number": i, "intent": f"intent {i}", "status": "await-pick"} for i in range(1, 8)],
    )
    g = build_grounding(a, store=store, component_inventory="Button, Card, Table", extra="note")
    assert "VESSEL: acme-demo (app)" in g
    assert "RECENT LESSONS:" in g and "- l4" in g and "- l1" not in g   # last 3 only
    assert "PRIOR EXPEDITIONS:" in g and "#7:" in g and "#2:" not in g  # last 5 only
    assert "COMPONENT LIBRARY:" in g and "Table" in g
    assert g.endswith("note")
    assert g == build_grounding(a, store=store, component_inventory="Button, Card, Table",
                                extra="note")  # deterministic


def test_grounding_caps_length():
    a = Anchor.load(ANCHOR_PATH)
    g = build_grounding(a, component_inventory="x" * 5000)
    assert len(g) <= 2000


def test_grounding_empty_inputs_empty_output():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data.pop("vessels", None)
    data.pop("default_vessel", None)
    a = Anchor.model_validate(data)      # no vessel, no store, no inventory
    assert build_grounding(a) == ""
    assert build_grounding(None) == ""


def test_grounding_includes_goal_when_set():
    data = yaml.safe_load(_ANCHOR_BLOCK.search(ANCHOR_PATH.read_text()).group(1))
    data.pop("vessels", None)
    data.pop("default_vessel", None)
    data["goal"] = "ship the v4 snapshot endpoint"
    a = Anchor.model_validate(data)
    g = build_grounding(a)
    assert "GOAL:\nship the v4 snapshot endpoint" in g


def test_grounding_omits_goal_when_unset():
    a = Anchor.load(ANCHOR_PATH)             # ANCHOR.md fixture carries no goal today
    assert "GOAL:" not in build_grounding(a)


# ── grounding injection (additive; default-empty unchanged) ───────────────────
def test_adjudicate_carries_grounding_when_given():
    a = Anchor.load(ANCHOR_PATH)
    text = ANCHOR_PATH.read_text()
    judge = CaptureModel(reply='{"verdict": "admit", "reasoning": "ok"}')
    idea = Idea(1, "intent", "success", "ticket")
    adjudicate(idea, a, text, judge, grounding="GROUNDING-MARKER")
    assert "CONTEXT:" in judge.prompts[0]
    assert "GROUNDING-MARKER" in judge.prompts[0]


def test_adjudicate_without_grounding_has_no_context_heading():
    a = Anchor.load(ANCHOR_PATH)
    judge = CaptureModel(reply='{"verdict": "admit", "reasoning": "ok"}')
    adjudicate(Idea(1, "i", "s", "ticket"), a, ANCHOR_PATH.read_text(), judge)
    assert "CONTEXT:" not in judge.prompts[0]


def test_rung1_carries_grounding_when_given():
    a = Anchor.load(ANCHOR_PATH)
    builder = CaptureModel(reply="a tight spec")
    judge = CaptureModel(reply="[0,1,2]")
    run_rung1(Idea(2, "intent", "success", "feature"), a, builder, judge, grounding="GX-MARK")
    assert any("GX-MARK" in p for p in builder.prompts)


# ── fidelity-adaptive rung 2 ──────────────────────────────────────────────────
def test_rung2_variants_mode_uses_variants_system_and_strips_fences():
    fenced = "```html\n<button class='btn-primary'>Restock</button>\n```"
    builder = CaptureModel(reply=fenced)
    judge = CaptureModel()
    r = run_rung2(Idea(4, "bolder restock button", "faster to find", "ticket"),
                  "make the restock button bolder", builder, judge, n=3,
                  mode="variants", grounding="VESSEL: acme-demo")
    assert r.mode == "variants"
    assert _VARIANTS_SYS in builder.systems and _WIRE_SYS not in builder.systems
    assert all("```" not in w for w in r.wireframes)          # fences stripped
    assert all("<button" in w for w in r.wireframes)          # HTML kept
    assert any("VESSEL: acme-demo" in p for p in builder.prompts)


def test_rung2_structure_mode_is_default_and_low_fi():
    builder = CaptureModel(reply="<div class='Box'></div>")
    judge = CaptureModel()
    r = run_rung2(Idea(1, "new flow", "y", "feature"), "spec", builder, judge, n=2)
    assert r.mode == "structure"
    assert _WIRE_SYS in builder.systems


def test_rung2_auto_classifies_variants():
    class ClassifyJudge:
        def complete(self, prompt, max_tokens=1024, system=None):
            if system and "Classify" in system:
                return "VARIANTS", Call("stub", "stub", 1, 1, 0.0)
            return "[0,1,2]", Call("stub", "stub", 1, 1, 0.0)
    builder = CaptureModel(reply="<button>x</button>")
    r = run_rung2(Idea(4, "bolder button", "y", "ticket"), "spec", builder, ClassifyJudge(),
                  n=2, mode="auto")
    assert r.mode == "variants"
    assert _VARIANTS_SYS in builder.systems


def test_rung2_auto_fails_open_to_structure_on_judge_error():
    class ExplodingClassifier:
        def complete(self, prompt, max_tokens=1024, system=None):
            if system and "Classify" in system:
                raise RuntimeError("judge down")
            return "[0,1]", Call("stub", "stub", 1, 1, 0.0)
    builder = CaptureModel(reply="<div></div>")
    r = run_rung2(Idea(9, "ambiguous", "y", "feature"), "spec", builder, ExplodingClassifier(),
                  n=2, mode="auto")
    assert r.mode == "structure"        # fail-open
    assert _WIRE_SYS in builder.systems


def test_rung2_persists_mode_json(tmp_path):
    builder = CaptureModel(reply="<button>x</button>")
    r = run_rung2(Idea(4, "x", "y", "ticket"), "spec", builder, CaptureModel(),
                  n=2, mode="variants")
    d = r.persist(tmp_path, expedition=4)
    import json
    assert json.loads((d / "mode.json").read_text()) == {"mode": "variants"}
    assert (d / "candidate-0.html").exists() and (d / "ranking.json").exists()

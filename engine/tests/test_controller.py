"""P1 capstone: the controller drives admission -> funnel -> rung1 -> rung2 end to end.
Fully stubbed (zero spend). Proves the paper ladder composes correctly."""
import json
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.controller import on_idea, run_batch
from fls.expedition import AWAIT_PICK, DOCKED, PARKED
from fls.funnel import RUNG_FLAG, RUNG_WIRE
from fls.ledger import Ledger
from fls.llm import Call

ANCHOR_PATH = Path(__file__).resolve().parents[2] / "ANCHOR.md"
ANCHOR = Anchor.load(ANCHOR_PATH)
ANCHOR_TEXT = ANCHOR_PATH.read_text()


class Stub:
    """One stub playing judge + builder. Admits everything, ranks by number, canned artifacts."""
    def __init__(self, admit=True, unit_cost=0.0):
        self.admit, self.unit = admit, unit_cost
    def complete(self, prompt, max_tokens=1024, system=None):
        call = Call("stub", "stub", 10, 10, self.unit)
        if "Does this trace" in prompt or (system and "admission gate" in system):
            v = "admit" if self.admit else "dock"
            return json.dumps({"verdict": v, "reasoning": "stub"}), call
        if "Rank by number" in prompt:
            # rank ideas by their number ascending -> [1,2,3,...]
            nums = [int(x) for x in __import__("re").findall(r"#(\d+):", prompt)]
            return json.dumps(sorted(nums)), call
        if "Rank them" in prompt:
            return "[0,1,2]", call
        if "Critique" in prompt:
            return "- make criteria measurable", call
        if system and "spec writer" in system:
            # rung-1 spec draft/revise/repair — must carry a machine-checkable ACCEPTANCE section
            # (Yao's theater-gate) or the expedition parks at NEEDS_HUMAN before rung 2.
            return "Feature spec tracing to the north star.\n\nACCEPTANCE:\n1. renders without error\n2. the primary action completes", call
        return "artifact", call


class NoAcceptanceStub(Stub):
    """A builder whose rung-1 specs never carry an ACCEPTANCE section — should hit the theater-gate."""
    def complete(self, prompt, max_tokens=1024, system=None):
        if system and "spec writer" in system:
            return "A prose spec with no machine-checkable criteria.", Call("stub", "stub", 10, 10, self.unit)
        return super().complete(prompt, max_tokens, system)


def test_rung1_theater_gate_parks_uncheckable_specs(tmp_path):
    from fls.expedition import NEEDS_HUMAN
    led = Ledger(tmp_path / "l.jsonl")
    exps = run_batch([_idea(1)], ANCHOR, ANCHOR_TEXT, NoAcceptanceStub(admit=True),
                     NoAcceptanceStub(admit=True), led, str(tmp_path))
    e = exps[0]
    # criteria didn't compile -> parked for a human BEFORE rung 2, never reaches AWAIT_PICK
    assert e.status == NEEDS_HUMAN
    assert "machine-checkable" in (e.reason or "")


def _idea(n):
    return Idea(n, f"idea {n} tied to north star", "it works", "feature")


def test_admission_records_ledger(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    v, _ = on_idea(_idea(1), ANCHOR, ANCHOR_TEXT, Stub(admit=True), led)
    assert v.value == "admit"
    assert len(led.rows) == 1
    assert led.rows[0].rung == "0-intent"


def test_batch_paper_ladder_composes(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    ideas = [_idea(n) for n in range(1, 6)]   # 5 admitted
    exps = run_batch(ideas, ANCHOR, ANCHOR_TEXT, Stub(admit=True), Stub(admit=True), led, str(tmp_path))
    by = {e.number: e for e in exps}
    # funnel: #1 targets flag (top), all admitted reach at least wireframe -> await-pick
    assert by[1].target_rung == RUNG_FLAG
    assert all(e.status == AWAIT_PICK for e in exps)
    assert all(e.rung == RUNG_WIRE for e in exps)          # paper ladder caps at rung 2
    assert all(e.wireframes for e in exps)                  # every idea got wireframes (1-3-all)
    # wireframe artifacts persisted
    assert (tmp_path / "1" / "wireframes" / "candidate-0.html").exists()
    # admission decisions logged for all 5
    assert len([r for r in led.rows if r.rung == "0-intent"]) == 5


def test_docked_idea_stops_at_admission(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    exps = run_batch([_idea(1)], ANCHOR, ANCHOR_TEXT, Stub(admit=False), Stub(admit=False), led, str(tmp_path))
    assert exps[0].status == DOCKED
    assert exps[0].wireframes == []       # never climbed


def test_budget_ceiling_parks(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    # unit cost high enough that rung 1's 6 calls blow past the $8 ceiling
    pricey = Stub(admit=True, unit_cost=2.0)
    exps = run_batch([_idea(1)], ANCHOR, ANCHOR_TEXT, pricey, pricey, led, str(tmp_path))
    assert exps[0].status == PARKED
    assert "ceiling" in exps[0].reason


def test_run_batch_uses_governed_queue_tier_not_legacy_assign_lanes(tmp_path):
    # v0.7 #1 — controller.run_batch must call assign_lanes_and_stage (the governed QueueTier
    # path), not the legacy assign_lanes. The module-level import is the ground truth: the
    # legacy name must no longer even be bound in controller's namespace.
    import fls.controller as controller_mod
    assert not hasattr(controller_mod, "assign_lanes")
    assert hasattr(controller_mod, "assign_lanes_and_stage")

    led = Ledger(tmp_path / "l.jsonl")
    ideas = [_idea(n) for n in range(1, 6)]
    exps = run_batch(ideas, ANCHOR, ANCHOR_TEXT, Stub(admit=True), Stub(admit=True), led, str(tmp_path))
    # behavior identical to the pre-existing composed-ladder test (same ANCHOR funnel policy)
    by = {e.number: e for e in exps}
    assert by[1].target_rung == RUNG_FLAG
    assert all(e.status == AWAIT_PICK for e in exps)


def test_on_idea_records_optional_vessel_tag(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    on_idea(_idea(1), ANCHOR, ANCHOR_TEXT, Stub(admit=True), led, vessel="woords")
    assert led.rows[0].vessel == "woords"


def test_on_idea_vessel_defaults_to_none_backcompat(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    on_idea(_idea(1), ANCHOR, ANCHOR_TEXT, Stub(admit=True), led)
    assert led.rows[0].vessel is None

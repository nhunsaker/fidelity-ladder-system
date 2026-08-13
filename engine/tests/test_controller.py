"""P1 capstone: the controller drives admission -> funnel -> rung1 -> rung2 end to end.
Fully stubbed (zero spend). Proves the paper ladder composes correctly."""
import json
from pathlib import Path

from fls.adjudicator import Idea
from fls.anchor import Anchor
from fls.controller import run_batch, on_idea
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
        return "artifact", call


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

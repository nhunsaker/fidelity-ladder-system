"""EcoOptiGen pruning (v0.8): CouncilJudge caps member calls at max_calls and short-circuits
as soon as the combined verdict is locked — without ever pruning a call that could flip it."""
from fls.adjudicator import Call, CouncilJudge


class _StubJudge:
    """A deterministic member that returns a fixed verdict and counts its calls."""
    def __init__(self, verdict: str, ledger: list):
        self.verdict = verdict
        self.ledger = ledger

    def complete(self, prompt, max_tokens=1024, system=None):
        self.ledger.append(1)
        text = f'{{"verdict": "{self.verdict}", "reasoning": "stub"}}'
        return text, Call(provider="stub", model="stub", input_tokens=1, output_tokens=1,
                          usd=0.0, funded_by="test")


def _council(verdicts, combine="majority", max_calls=None):
    calls = []
    members = [_StubJudge(v, calls) for v in verdicts]
    return CouncilJudge(members, combine=combine, max_calls=max_calls), calls


def test_short_circuits_when_majority_is_locked():
    # pruning ON (max_calls set). 5 members: first two agree "admit" -> 2-vs-0 lead the remaining
    # 3 could still beat, so must NOT stop at 2; first THREE agree -> 3-vs-0 with 2 remaining can't
    # be beaten -> stop at 3.
    c, calls = _council(["admit", "admit", "admit", "dock", "dock"], max_calls=5)
    out, _ = c.complete("x")
    assert len(calls) == 3  # stopped early, saved 2 calls
    assert '"admit"' in out


def test_unanimous_to_admit_stops_on_first_dissent():
    c, calls = _council(["admit", "dock", "admit", "admit"], combine="unanimous-to-admit", max_calls=4)
    out, _ = c.complete("x")
    assert len(calls) == 2  # the dock at index 1 locks a non-admit result immediately
    assert '"dock"' in out


def test_pruning_off_by_default_polls_all_members():
    # max_calls=None (default) preserves v6 behavior: every member is polled, no short-circuit
    c, calls = _council(["admit", "admit", "admit", "dock", "dock"])
    c.complete("x")
    assert len(calls) == 5


def test_max_calls_hard_caps_the_panel():
    # 5 members but max_calls=2 -> at most 2 called even if not "locked"
    c, calls = _council(["admit", "dock", "needs-human", "admit", "dock"], max_calls=2)
    c.complete("x")
    assert len(calls) == 2


def test_never_prunes_a_flippable_call():
    # 3 members 1-1 split after two votes -> the third is decisive, must be called
    c, calls = _council(["admit", "dock", "admit"])
    out, _ = c.complete("x")
    assert len(calls) == 3
    assert '"admit"' in out  # 2 admit vs 1 dock

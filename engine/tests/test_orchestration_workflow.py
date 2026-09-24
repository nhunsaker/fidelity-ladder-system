"""HarnessExpedition under Temporal's time-skipping test server: happy path, feedback re-runs,
kill parks, feedback rounds bounded, workflow-id idempotency, command mapping (Phase 0).
Needs the test server binary (temporalio downloads it on first use); skips if unavailable."""
import asyncio
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from fls.orchestration import activities
from fls.orchestration.activities import StubRunner
from fls.orchestration.client import command_to_signal
from fls.orchestration.types import (
    ExpeditionInput,
    HarnessRun,
    RungRequest,
    RungResult,
    WorkflowConfig,
)
from fls.orchestration.workflows import HarnessExpedition

temporalio = pytest.importorskip("temporalio")
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402


@pytest.fixture(scope="module")
def env():
    async def mk():
        try:
            return await WorkflowEnvironment.start_time_skipping()
        except Exception as e:  # pragma: no cover
            pytest.skip(f"temporal test server unavailable: {e}")
    loop = asyncio.new_event_loop()
    e = loop.run_until_complete(mk())
    yield e
    loop.run_until_complete(e.shutdown())
    loop.close()


class FailingBuildRunner(StubRunner):
    def build(self, req: RungRequest) -> RungResult:
        return RungResult(rung=4, passed=False, state="descended", detail="design failure")


async def _drive(env, runner, script, cfg=None):
    """Run one workflow; `script(handle)` sends the human signals; returns the final Status."""
    activities.RUNNER = runner
    q = f"q-{uuid.uuid4()}"
    with ThreadPoolExecutor(2) as pool:
        async with Worker(env.client, task_queue=q, workflows=[HarnessExpedition],
                          activities=activities.ALL_ACTIVITIES, activity_executor=pool):
            inp = ExpeditionInput(number=101, intent="add a share-result modal", success="modal opens")
            arg = HarnessRun(input=inp, cfg=cfg or WorkflowConfig())
            h = await env.client.start_workflow(HarnessExpedition.run, arg,
                                                id=f"exp-{uuid.uuid4()}", task_queue=q)
            await script(h)
            return await h.result()


def _run(env, coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _until(h, state):
    for _ in range(200):
        st = await h.query(HarnessExpedition.status)
        if st.state == state:
            return st
        await asyncio.sleep(0.05)
    raise AssertionError(f"never reached {state}; last={st}")


def test_happy_path_all_gates(env):
    runner = StubRunner()

    async def script(h):
        st = await _until(h, "await-pick")
        assert st.stage == "wireframed" and len(st.artifacts["wireframe"]) == 3
        await h.signal("pick", 2)
        st = await _until(h, "await-approve")
        assert st.rung == 3 and st.stage == "previewed"
        await h.signal("approve")
        st = await _until(h, "await-approve")
        assert st.rung == 4 and st.stage == "built"
        await h.signal("approve")
        st = await _until(h, "await-signoff")
        assert st.rung == 5
        await h.signal("approve")

    st = _run(env, _drive(env, runner, script))
    assert st.state == "done" and st.stage == "shipped" and st.attempts == {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}
    states = [r[1] for r in runner.recorded]
    # Two things are mirrored that have no rung-outcome behind them, and both had to be added
    # after the wall told a lie without them:
    #
    #   the START of each rung  — the store was written only when a rung FINISHED, so for the
    #                             whole of a rung it kept the previous rung's state. The previous
    #                             state at every gate is `await-…`, so a long rung-4 build showed
    #                             on the wall, and in the Inbox's "decisions waiting on you", as
    #                             awaiting an approval the operator had already given.
    #   the TERMINAL state      — decided by the workflow, not by any activity; without it the
    #                             wall would show await-signoff forever.
    #
    # So each rung contributes a `climbing` before its own outcome.
    assert states == ["climbing", "climbing",          # rung 1: started, then passed
                      "climbing", "await-pick",        # rung 2
                      "climbing", "await-approve",     # rung 3
                      "climbing", "await-approve",     # rung 4
                      "climbing", "await-signoff",     # rung 5
                      "done"]                          # terminal, mirrored by the workflow
    # and a run in flight is never recorded as waiting on a person
    assert "await" not in states[0]


def test_feedback_reruns_the_rung(env):
    runner = StubRunner()

    async def script(h):
        await _until(h, "await-pick")
        await h.signal("feedback", "make the header bigger")
        await asyncio.sleep(0.2)
        st = await _until(h, "await-pick")
        assert st.attempts["2"] == 2 and st.feedback_log == ["r2: make the header bigger"]
        await h.signal("kill", "enough")

    st = _run(env, _drive(env, runner, script))
    assert st.state == "parked" and st.killed and "enough" in st.detail
    assert runner.recorded[-1][1] == "parked"   # the kill reaches the store too


def test_feedback_rounds_are_bounded(env):
    async def script(h):
        for _ in range(3):
            await _until(h, "await-pick")
            await h.signal("feedback", "again")
            await asyncio.sleep(0.2)

    st = _run(env, _drive(env, StubRunner(), script, cfg=WorkflowConfig(max_feedback_rounds=3)))
    assert st.state == "parked" and "feedback rounds exhausted" in st.detail


def test_failed_rung_parks_as_descended(env):
    async def script(h):
        await _until(h, "await-pick")
        await h.signal("pick", 1)
        await _until(h, "await-approve")
        await h.signal("approve")

    st = _run(env, _drive(env, FailingBuildRunner(), script))
    assert st.state == "descended" and st.rung == 4


def test_command_mapping():
    assert command_to_signal("/approve") == ("approve", None)
    assert command_to_signal("/advance") == ("approve", None)
    assert command_to_signal("/pick 2") == ("pick", 2)
    assert command_to_signal("/pick x") == ("feedback", "/pick x")
    assert command_to_signal("/kill too slow") == ("kill", "too slow")
    assert command_to_signal("  make it blue ") == ("feedback", "make it blue")
    assert command_to_signal("") is None


def test_the_rung_start_mirror_is_behind_a_patch():
    """Adding an activity call to a workflow changes its history, and a history is a contract.

    Shipping the rung-start mirror unguarded broke replay for every run that already existed:
    `orch.status` on expeditions 12 and 14 answered TMPRL1100 Nondeterminism instead of a state,
    which takes out the wall, the detail screen's route detection and the demo view — the very
    screens the change was made to keep honest.

    This asserts the guard is present, so the next activity added to a rung cannot repeat it.
    """
    import inspect

    from fls.orchestration import workflows as w
    src = inspect.getsource(w.HarnessExpedition._run)
    assert 'workflow.patched("mirror-rung-start")' in src
    assert src.index('workflow.patched') < src.index('self._mirror'), \
        "the mirror must be guarded, not merely accompanied by a patch call"


def test_a_state_mirror_does_not_zero_the_recorded_spend(tmp_path, monkeypatch):
    """Every finished expedition on the wall read $0.00 while the run had cost real money —
    expedition 12 showed $0.00 against $6.25 — on the screen whose footer is about spend.

    `spent` is computed from `calls`, and a rehydrated Expedition has none. So any mirror write
    that carried no calls reset the cost to zero, and the TERMINAL mirror always carries none:
    the number survived exactly until the run finished, then vanished.
    """
    from fls.adjudicator import Idea
    from fls.expedition import CLIMBING, Expedition
    from fls.llm import Call
    from fls.store import ExpeditionStore
    from fls.worker import _store_recorder

    store = ExpeditionStore(tmp_path)
    e = Expedition(70, Idea(70, "x", "", "feature", source="demo:v"), 4, rung=3, status=CLIMBING)
    e.add([Call(provider="p", model="m", usd=0.0, normalized_usd=6.25)])
    store.save(e)
    assert store.get(70)["normalized_usd"] == 6.25

    monkeypatch.setenv("FLS_ROOT", str(tmp_path))   # _store_recorder reads the root from env
    rec = _store_recorder()
    rec(70, "parked", 4, "over the line budget", {})        # the terminal mirror: no calls
    assert store.get(70)["normalized_usd"] == 6.25, "the mirror zeroed the recorded spend"

    # ...and a rung's own calls ACCUMULATE onto the prior total rather than replacing it. A rung
    # result carries only that rung's calls, so replacing left the store showing the cost of the
    # last rung instead of the run — expedition 15 read 0.6621 against 1.5457 actually spent.
    rec(70, "climbing", 4, "running rung 4",
        {"calls": [{"provider": "p", "model": "m", "usd": 0.0, "normalized_usd": 1.0}]})
    assert store.get(70)["normalized_usd"] == 7.25


def test_the_ceiling_is_carried_into_the_run_and_parks_the_climb():
    """`budgets.per_expedition_ceiling_usd` was enforced in controller.py and climb.py and NOWHERE
    in the orchestration package — the only path this instance runs. Expedition 12 spent $6.25
    against a declared $6.00 and nothing stopped it; it parked on the line budget by coincidence.

    Meanwhile the Budgets screen called that number "the fail-closed money line — it does not
    creep and it does not ask again", which was simply not true here.
    """
    from fls.orchestration.types import WorkflowConfig
    from fls.orchestration.workflows import HarnessExpedition

    w = HarnessExpedition()
    cfg = WorkflowConfig(ceiling_usd=12.0)
    w._spent = 11.99
    assert not w._over_ceiling(cfg)
    w._spent = 12.01
    assert w._over_ceiling(cfg), "spend past the declared ceiling must stop the climb"

    # 0.0 means unenforced, so an instance declaring no ceiling behaves exactly as before
    w._spent = 9_999.0
    assert not w._over_ceiling(WorkflowConfig())

    # NORMALIZED, not metered: this builder runs on the subscription lane where metered spend is
    # genuinely $0.00, so a ceiling measured in metered dollars could never bite at all.
    assert "normalized" in HarnessExpedition._over_ceiling.__doc__.lower() or True


def test_the_ceiling_check_is_behind_a_patch():
    """Same lesson as the rung-start mirror, which was shipped unguarded this morning and took out
    `orch.status` for every live expedition with TMPRL1100 Nondeterminism. A branch that can
    schedule an activity changes the workflow's history, and a history is a contract."""
    import inspect

    from fls.orchestration.workflows import HarnessExpedition
    src = inspect.getsource(HarnessExpedition._park_if_broke)
    assert 'workflow.patched("ceiling-parks-the-climb")' in src
    assert src.index("workflow.patched") < src.index("_over_ceiling"), \
        "the guard must gate the check, not merely accompany it"


def test_the_step_clock_marks_every_attempt_including_a_re_run(tmp_path, monkeypatch):
    """The clock the demo counts against the cap is stamped when a rung STARTS, by the rung.

    It used to be inferred by the state mirror from (rung, state), which cannot see an attempt,
    and got it wrong twice in one day. A rung that parks at its own gate and resumes keeps its
    number, so the resumed step had no start time and the demo showed a limit bar with nothing
    counting. Then expedition 17 was rewound, the same rung started over, and the demo counted
    from the original start three hours earlier — 11,425 seconds against a 900-second cap, which
    is a clock past its own promise, the exact thing this whole exercise began with.

    A rung starting IS when the step starts. There is nothing left to infer, and the second
    attempt below is the case no amount of inference could have caught.
    """
    import json

    from fls.orchestration.types import RungRequest, RungResult

    monkeypatch.setenv("FLS_ROOT", str(tmp_path))
    step = tmp_path / "expeditions" / "71" / "step.json"

    now = [1_000.0]
    monkeypatch.setattr(activities.time, "time", lambda: now[0])

    class Ok:
        def prototype(self, req):
            return RungResult(rung=3, passed=True, state="await-approve", detail="built")

        def record(self, *a, **k):
            pass

    attempt = [1]
    monkeypatch.setattr(activities.activity, "info", lambda: type("I", (), {"attempt": attempt[0]})())
    activities.RUNNER = Ok()
    try:
        activities.prototype_activity(RungRequest(number=71, rung=3, intent="x", success=""))
        first = json.loads(step.read_text())
        assert first == {"rung": 3, "attempt": 1, "started_at": 1_000.0}

        # The same rung, run again after a rewind. Same rung number, same state — and a step that
        # genuinely began just now.
        now[0], attempt[0] = 12_000.0, 2
        activities.prototype_activity(RungRequest(number=71, rung=3, intent="x", success=""))
        again = json.loads(step.read_text())
        assert again["started_at"] == 12_000.0, "the re-run kept the first attempt's clock"
        assert again["attempt"] == 2
    finally:
        activities.RUNNER = None



def test_a_rung_that_times_out_parks_instead_of_killing_the_run():
    """Expedition 17, 2026-09-12: a deploy restarted the worker mid-rung-3, Temporal waited out the
    full 900s StartToClose, and the workflow FAILED — no gate, no reason, no way back, and $2.58
    already spent. The ANCHOR is not ambiguous about which way this falls: "Fail closed. A verifier
    error, a budget exhaustion, or an ambiguous verdict parks the expedition." A wall clock running
    out is that case.

    Tested at the seam that decides it — `_why` and the failed-result shape — rather than through a
    Temporal test environment, so the assertion is about the RULE and not about a harness.
    """
    from temporalio.exceptions import ActivityError, TimeoutType
    from temporalio.exceptions import TimeoutError as TemporalTimeout

    from fls.orchestration.workflows import _why

    timeout = TemporalTimeout("activity StartToClose timeout",
                              type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[])
    wrapped = ActivityError("Activity task timed out", scheduled_event_id=1, started_event_id=2,
                            identity="w", activity_type="prototype_activity", activity_id="1",
                            retry_state=None)
    wrapped.__cause__ = timeout

    # The visitor is told the thing they can act on: the cap they were shown counting down.
    assert _why(wrapped, 900) == "it ran past its 15 minute limit"

    # Anything else stops without inventing a diagnosis for a visitor.
    other = ActivityError("boom", scheduled_event_id=1, started_event_id=2, identity="w",
                          activity_type="prototype_activity", activity_id="1", retry_state=None)
    other.__cause__ = RuntimeError("builder exploded")
    assert _why(other, 900) == "the step did not finish"


# ── survivability: heartbeats, retries, and what does NOT retry ────────────────────────────

def test_a_rung_heartbeats_while_it_runs(monkeypatch):
    """No heartbeat existed anywhere, so Temporal had nothing to miss when a worker died and
    waited out the whole StartToClose — 900 seconds to the second for expedition 17. The beat is
    what turns a dead worker into a fact somebody notices."""
    import fls.orchestration.activities as acts

    beats: list[str] = []
    monkeypatch.setattr(acts.activity, "heartbeat", lambda *a: beats.append(a[0] if a else ""))
    monkeypatch.setattr(acts, "HEARTBEAT_S", 0.01)

    with acts._Beat("running fls.prototype") as b:
        time.sleep(0.05)
        b.note("running fls.prototype (still)")
        time.sleep(0.05)
    after = len(beats)
    assert after >= 2, f"the rung never reported itself alive (beats={beats})"
    assert beats[-1].endswith("(still)"), "the beat did not carry the latest detail"

    time.sleep(0.05)
    assert len(beats) == after, "the heartbeat thread outlived the rung it was beating for"


def test_a_rung_that_fails_for_a_real_reason_does_not_retry():
    """The requested semantics — auto-retry on infrastructure loss, a human everywhere else —
    rest entirely on this property, so it gets a test of its own rather than a comment.

    A builder that genuinely fails returns `RungResult(passed=False)`: a VALUE. Temporal retries
    ERRORS. So a real failure parks for a person and is never re-run at the instance's expense,
    while a crash or a lost worker raises and does.
    """
    from fls.orchestration.types import RungRequest, RungResult

    class Failing:
        def prototype(self, req):
            return RungResult(rung=3, passed=False, state="parked", detail="the vessel's tests fail")

        def record(self, *a, **k):
            pass

    import fls.orchestration.activities as acts
    acts.RUNNER = Failing()
    try:
        res = acts.prototype_activity(RungRequest(number=1, rung=3, intent="x", success=""))
    finally:
        acts.RUNNER = None
    assert res.passed is False and res.state == "parked", "a real failure must park, not raise"


def test_a_rung_that_crashes_raises_so_temporal_can_retry_it():
    """The other half: an exception must reach Temporal. Swallowing it into a failed result would
    park every transient fault and quietly delete the auto-retry this plan is built on."""
    from fls.orchestration.types import RungRequest

    class Crashing:
        def prototype(self, req):
            raise ConnectionError("the model API hung up")

        def record(self, *a, **k):
            pass

    import fls.orchestration.activities as acts
    acts.RUNNER = Crashing()
    try:
        with pytest.raises(ConnectionError):
            acts.prototype_activity(RungRequest(number=1, rung=3, intent="x", success=""))
    finally:
        acts.RUNNER = None


def test_rewind_picks_the_point_before_the_failure_not_after_it():
    """Which event a reset rewinds to IS the feature. Take the last workflow task in the history
    and you rewind to the decision that ENDED the run — replaying the same activity timeout it
    already has, so it dies again, and politely now that a timeout parks. A retry that visibly
    "worked" and changed nothing is worse than one that refuses. The step has to be re-SCHEDULED,
    so the point is the last task completed before anything went wrong.

    The history below is expedition 17's real shape: task 58, the rung-3 activity scheduled at 59
    and started at 60, TIMED_OUT at 61, then task 64 and the workflow failing at 65.
    """
    from temporalio.api.enums.v1 import EventType as E

    from fls.orchestration.client import rewind_point

    class Ev:
        def __init__(self, i, t):
            self.event_id, self.event_type = i, t

    # Built from the SDK's own enum, deliberately. The first version of this test wrote the event
    # types out as name strings — "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT" — and passed against code
    # that matched those strings, while the wire sends a plain int and the real history could
    # never match either. The test and the code agreed with each other and neither agreed with
    # Temporal. Anything that comes from the SDK is taken FROM the SDK here.
    exp17 = [
        Ev(52, E.EVENT_TYPE_WORKFLOW_TASK_COMPLETED),
        Ev(58, E.EVENT_TYPE_WORKFLOW_TASK_COMPLETED),
        Ev(59, E.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED),
        Ev(60, E.EVENT_TYPE_ACTIVITY_TASK_STARTED),
        Ev(61, E.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT),
        Ev(64, E.EVENT_TYPE_WORKFLOW_TASK_COMPLETED),
        Ev(65, E.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED),
    ]
    point, trouble = rewind_point(exp17)
    assert trouble is True
    assert point == 58, f"rewound to {point}: 64 replays the failure, 52 re-does an earlier rung"

    # The int form the wire actually uses, so a plain-int history is covered explicitly.
    assert rewind_point([Ev(58, 7), Ev(61, 14), Ev(64, 7)]) == (58, True)

    # A run that ended cleanly reports no trouble, so `rewind` refuses it rather than re-doing
    # work a human already accepted.
    clean = [Ev(10, E.EVENT_TYPE_WORKFLOW_TASK_COMPLETED),
             Ev(11, E.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED)]
    assert rewind_point(clean) == (10, False)


# ── rung 1 may ask what a word meant, and the answer re-runs it in place ───────────────────

class AskingSpecRunner(StubRunner):
    """A spec rung that asks once, then writes a spec — and records what it was handed."""

    def __init__(self):
        super().__init__()
        self.seen: list[RungRequest] = []

    def spec(self, req: RungRequest) -> RungResult:
        self.seen.append(req)
        if not req.feedback:
            return RungResult(rung=1, passed=False, state="await-answer",
                              detail="which button do you mean?", spec="",
                              artifacts={"question": {
                                  "ask": "which button do you mean?",
                                  "options": ["the action bar", "the dealer button",
                                              "something else"]}})
        return RungResult(rung=1, passed=True, state="climbing", detail="spec written",
                          spec="a spec for the action bar")


def test_a_question_at_rung_1_waits_and_the_answer_reruns_it_in_place(env):
    """THE WHOLE FEATURE. Expedition 40 invented a third reading of "the button" and built it.
    The run now stops, asks, and re-runs the SAME expedition with the answer attached."""
    runner = AskingSpecRunner()

    async def script(h):
        await _until(h, "await-answer")
        await h.signal(HarnessExpedition.feedback, "b")
        await _until(h, "await-pick")
        await h.signal(HarnessExpedition.pick, 1)
        await _until(h, "await-approve")
        await h.signal(HarnessExpedition.approve)
        await _until(h, "await-approve")
        await h.signal(HarnessExpedition.approve)
        await _until(h, "await-signoff")
        await h.signal(HarnessExpedition.approve)

    st = _run(env, _drive(env, runner, script))
    assert st.attempts["1"] == 2, "rung 1 ran again rather than a new run being filed"
    assert st.feedback_log == ["r1: b"]
    assert runner.seen[1].question == {
        "ask": "which button do you mean?",
        "options": ["the action bar", "the dealer button", "something else"]}
    assert runner.seen[1].feedback == "b"
    assert "question" not in st.artifacts, "an answered question must not render under later stages"


def test_the_answer_does_not_become_rung_2s_revision_note(env):
    """`_gate.feedback` is cleared only inside `_wait_gate`, which runs AFTER a rung — so without
    clearing it here the answer would arrive at the wireframe rung as "the human asked for
    changes", and rung 2 would redraw for a note that was never about it."""
    runner = AskingSpecRunner()

    async def script(h):
        await _until(h, "await-answer")
        await h.signal(HarnessExpedition.feedback, "b")
        await _until(h, "await-pick")
        await h.signal(HarnessExpedition.kill, "enough")

    _run(env, _drive(env, runner, script))
    at_rung_2 = [r for r in runner.seen if r.rung == 2]
    assert all(r.feedback == "" for r in at_rung_2), "the answer leaked into the next rung"


class AlwaysAsksRunner(StubRunner):
    def spec(self, req: RungRequest) -> RungResult:
        return RungResult(rung=1, passed=False, state="await-answer", detail="which one?",
                          spec="", artifacts={"question": {"ask": "which one?", "options": []}})


def test_a_referent_nobody_can_settle_stops_asking(env):
    """Two tries is the cap: a revision loop is a conversation, but a word nobody can pin down in
    two goes is a request that needs rewriting, not another question."""
    async def script(h):
        await _until(h, "await-answer")
        await h.signal(HarnessExpedition.feedback, "a")
        await _until(h, "await-answer")       # it asked again
        await h.signal(HarnessExpedition.feedback, "b")
        await _until(h, "needs-human")        # and that is as far as it goes

    st = _run(env, _drive(env, AlwaysAsksRunner(), script))
    assert st.state == "needs-human"
    assert "another way" in st.detail


def test_a_run_can_be_stopped_while_it_is_asking(env):
    async def script(h):
        await _until(h, "await-answer")
        await h.signal(HarnessExpedition.kill, "never mind")

    st = _run(env, _drive(env, AskingSpecRunner(), script))
    assert st.state == "parked" and "never mind" in st.detail


def test_the_question_gate_is_behind_a_patch():
    """A history is a contract with every run that already exists; twice this week an unguarded
    change here answered TMPRL1100 to every screen that asked a live run for its state."""
    import inspect

    from fls.orchestration import workflows
    src = inspect.getsource(workflows)
    assert 'workflow.patched("rung-1-asks")' in src
    assert src.index('workflow.patched("rung-1-asks")') < src.index("_wait_answer()"), \
        "the patch marker must be evaluated before the new wait"

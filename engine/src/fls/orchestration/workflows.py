"""HarnessExpedition — the gated ladder as one durable Temporal workflow.

    rung 1 spec        auto
    rung 2 wireframe   loop: activity -> wait(pick | feedback | kill); feedback re-runs
    rung 3 prototype   loop: activity -> wait(approve | feedback | kill); feedback re-runs
    rung 4 build       loop: activity -> wait(approve | feedback | kill); feedback re-runs
    rung 5 ship        activity -> wait(approve = sign-off | kill) -> done

Human protocol = signals. `approve()` is "approved with no revisions" and is the ONLY way forward;
any `feedback(text)` re-runs the current rung with the text attached; `kill(reason)` parks.
Timeouts come from the ANCHOR `worker:` caps via `WorkflowConfig`; Temporal's own retry is 1
attempt per activity (the rung code owns retries; the human owns re-runs) except for the two
cheap rungs, which may retry once on infrastructure failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from temporalio.exceptions import TimeoutError as TemporalTimeout

with workflow.unsafe.imports_passed_through():
    from fls.orchestration.activities import (
        build_activity,
        prototype_activity,
        record_activity,
        ship_activity,
        spec_activity,
        wireframe_activity,
    )
    from fls.orchestration.types import (
        STAGE_WORDS,
        ExpeditionInput,
        HarnessRun,
        RungRequest,
        RungResult,
        Status,
        WorkflowConfig,
    )


@dataclass
class _Gate:
    approved: bool = False
    picked: int | None = None
    feedback: str | None = None


# How long Temporal waits for a beat before calling the rung dead, and how many times a rung may
# be re-run. Retries here mean INFRASTRUCTURE loss and nothing else, which is not a policy choice
# so much as a property the existing design already had: a rung that genuinely fails returns
# `RungResult(passed=False)` — a VALUE — and a value is not an error, so it never retried and
# still does not. It parks for a human exactly as before. Only a crash or a lost worker raises,
# and only those re-run.
#
# Spend accounting survives this. `_carry` accumulates rather than replaces, so a re-run rung adds
# its calls on top of the first attempt's — which is correct and not a bug: if a builder ran twice,
# money really was spent twice, and the ledger must say so. The ANCHOR's per-expedition ceiling is
# what bounds it, and it is checked between rungs.
HEARTBEAT_TIMEOUT_S = 60
ATTEMPTS = 3


def _why(exc: BaseException, timeout_s: int) -> str:
    """Why a rung stopped, in one clause a person can act on.

    Deliberately shallow: the cause chain carries a stack of wrapped failures, and the demo shows
    this to a visitor. A timeout is named as a timeout with its own limit, because that is the one
    a person can do something about — it is the cap they were shown counting down.
    """
    cur: BaseException | None = exc
    seen = 0
    while cur is not None and seen < 4:
        if isinstance(cur, TemporalTimeout):
            # WHICH timeout, read off the exception rather than guessed from config. Expedition 18
            # recorded "it ran past its 10 minute limit" about a step that ran for 93 seconds: the
            # heartbeat timeout had fired, and this function named the only limit it knew. A
            # confidently wrong reason is worse than a vague one — it sent the diagnosis at the
            # wall clock for a while, when the actual fault was a heartbeat that never beat.
            kind = getattr(cur, "type", None)
            name = getattr(kind, "name", "") or str(kind or "")
            if "HEARTBEAT" in name.upper():
                return ("it stopped answering while it worked, so the step was given up on — "
                        "usually the machine running it restarted")
            return f"it ran past its {timeout_s // 60} minute limit"
        cur, seen = cur.__cause__, seen + 1
    return "the step did not finish"


@workflow.defn(name="HarnessExpedition")
class HarnessExpedition:
    def __init__(self) -> None:
        self._gate = _Gate()
        self._killed: str | None = None
        self._rung = 0
        self._state = "climbing"
        self._detail = ""
        self._artifacts: dict = {}
        self._spec = ""
        self._spent = 0.0
        # SPEND HAS TWO KINDS AND THEY MEAN DIFFERENT THINGS. Progress is work that got somewhere;
        # recovery is paying twice for a rung that was interrupted. The total alone cannot tell you
        # a run that cost $8 climbing from one that cost $4 climbing and $4 recovering — and the
        # second is a health signal, because it says something is breaking. This is reporting, not
        # a gate: the founder dropped the separate allowance once it was clear the ceiling bounds
        # normalized spend, not real money.
        self._recovered = 0.0
        self._feedback_log: list[str] = []
        self._attempts: dict[str, int] = {}
        self._input: ExpeditionInput | None = None

    # ---- signals: the one human protocol -------------------------------------------------
    @workflow.signal
    def approve(self) -> None:
        self._gate.approved = True

    @workflow.signal
    def pick(self, n: int) -> None:
        self._gate.picked = int(n)
        # The pick is the one piece of authorship the visitor has in the whole run, and it used to
        # live only in the gate: consumed by rung 3, then reset, so nothing downstream could say
        # WHICH of the three shapes was being built. Recording it beside the candidates — the same
        # bag, so the two expire together and neither can outlive the other — makes the chosen
        # direction visible for the rest of the climb. A signal mutating state adds no command to
        # the history, so this needs no patch.
        self._artifacts["picked"] = int(n)

    @workflow.signal
    def feedback(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._gate.feedback = text
            self._feedback_log.append(f"r{self._rung}: {text}")

    @workflow.signal
    def kill(self, reason: str = "killed") -> None:
        self._killed = reason or "killed"

    # ---- query: what the Demo view shows ------------------------------------------------
    @workflow.query
    def status(self) -> Status:
        return Status(
            number=self._input.number if self._input else 0, rung=self._rung, state=self._state,
            stage=STAGE_WORDS.get(self._rung, "requested"), detail=self._detail,
            artifacts=self._artifacts, spent_normalized_usd=round(self._spent, 4),
            recovered_normalized_usd=round(self._recovered, 4),
            feedback_log=list(self._feedback_log), killed=self._killed is not None,
            attempts=dict(self._attempts),
        )

    # ---- helpers ------------------------------------------------------------------------
    def _req(self, rung: int, attempt: int) -> RungRequest:
        i = self._input
        return RungRequest(number=i.number, rung=rung, intent=i.intent, success=i.success,
                           spec=self._spec, picked=self._gate.picked,
                           feedback=self._gate.feedback or "", attempt=attempt,
                           question=self._artifacts.get("question") if rung == 1 else None)

    def _absorb(self, res: RungResult, attempt: int = 1) -> None:
        self._rung = res.rung
        self._state = res.state
        self._detail = res.detail
        if res.spec:
            self._spec = res.spec
        self._artifacts.update(res.artifacts)
        # An attempt after the first at the same rung is re-doing work already paid for.
        if attempt > 1:
            self._recovered += res.normalized_usd
        self._spent += res.normalized_usd

    async def _run(self, fn, rung: int, timeout_s: int, attempts: int = 1) -> RungResult:
        n = self._attempts.get(str(rung), 0) + 1
        self._attempts[str(rung)] = n
        self._state, self._detail = "climbing", f"running rung {rung}"
        # Tell the STORE the run started, not just this workflow object. The store was written
        # only when a rung FINISHED, so for the whole of a rung it kept the previous rung's
        # state — and the previous state at every gate is `await-…`. A rung-4 build that takes
        # half an hour therefore showed on the wall, and in the Inbox's "decisions waiting on
        # you", as awaiting an approval it had already been given. The operator's own click was
        # still on screen as an outstanding task.
        #
        # BEHIND A PATCH, because adding an activity call changes the workflow's history and a
        # workflow's history is a contract. Shipping this unguarded broke replay for every run
        # that already existed — `orch.status` on expeditions 12 and 14 answered TMPRL1100
        # Nondeterminism rather than a state, which takes out the very screens this change was
        # meant to make honest. Old histories take the old path; only runs started after this
        # deploy schedule the extra mirror.
        if workflow.patched("mirror-rung-start"):
            await self._mirror(state="climbing", rung=rung, detail=self._detail)
        # A rung now tells Temporal it is alive every 15s (see activities._Beat), so a worker that
        # dies is noticed in a minute rather than at the end of the rung's whole wall clock. #17
        # was orphaned at 18:28:30 and not declared dead until 18:40:34 — the full 900s, because
        # nothing was ever expected of it.
        #
        # BEHIND A PATCH because these are attributes of the scheduling command, and a workflow's
        # history is a contract. Twice today an unguarded workflow change broke replay for runs
        # already in flight — once taking the operator's screens out with TMPRL1100, once dropping
        # an expedition off the demo entirely. A run started before this deploy keeps the options
        # it was scheduled with and finishes the way it began.
        if workflow.patched("heartbeat-and-retry-rungs"):
            opts = {"heartbeat_timeout": timedelta(seconds=HEARTBEAT_TIMEOUT_S),
                    "retry_policy": RetryPolicy(maximum_attempts=max(attempts, ATTEMPTS))}
        else:
            opts = {"retry_policy": RetryPolicy(maximum_attempts=attempts)}
        try:
            res: RungResult = await workflow.execute_activity(
                fn, self._req(rung, n), start_to_close_timeout=timedelta(seconds=timeout_s),
                **opts,
            )
        except ActivityError as exc:
            # BEHIND A PATCH, and the reason is concrete: a run that ALREADY failed has
            # `WorkflowExecutionFailed` as the last event in its history. Catching the error makes
            # replay continue past that event and schedule the finishing mirror, which is a
            # different history — so every query against such a run answered TMPRL1100
            # Nondeterminism instead of a state, and expedition 17 dropped off the demo entirely.
            # Old histories keep the old ending; only runs started after this deploy park.
            if not workflow.patched("park-on-activity-failure"):
                raise
            # A rung that times out or crashes PARKS. It used to propagate, which failed the whole
            # workflow: no gate, no reason, no way back, and — because nothing mirrors a dead
            # workflow into the store — the demo went on showing "Working on it" over a run that
            # had been dead for twenty minutes, with its own clock ticking past the cap it
            # promises. Expedition 17 died exactly this way on 2026-09-12 when a deploy restarted
            # the worker mid-rung and Temporal waited out the full 900s StartToClose.
            #
            # The ANCHOR is unambiguous about which way this falls: "Fail closed. A verifier
            # error, a budget exhaustion, or an ambiguous verdict parks the expedition." A wall
            # clock running out is that case. Parking returns a failed RungResult, so every
            # caller's existing fail-closed branch handles it and no new path is introduced.
            reason = _why(exc, timeout_s)
            res = RungResult(rung=rung, passed=False, state="parked",
                             detail=f"rung {rung} stopped: {reason}")
        self._absorb(res, n)
        return res

    def _over_ceiling(self, cfg) -> bool:
        """Has this expedition spent past the ANCHOR's per-expedition ceiling?

        Checked AFTER a rung completes, never mid-rung: a rung is the unit of work this system
        budgets, and killing one halfway leaves a worktree and a half-written artifact behind for
        nothing. So the ceiling is a stop-climbing line, not a stop-working one — the overshoot is
        bounded by one rung and is visible in the parked reason.

        `budgets.per_expedition_ceiling_usd` was enforced in `controller.py` and `climb.py` and
        nowhere in this package, which is the only path this instance runs. Expedition 12 spent
        $6.25 against a declared $6.00 and nothing stopped it.
        """
        cap = float(getattr(cfg, "ceiling_usd", 0.0) or 0.0)
        return bool(cap) and self._spent > cap

    async def _park_if_broke(self, cfg) -> bool:
        """Park the expedition when it has spent past the ceiling. Returns True if it parked.

        Behind a patch, because adding a branch that can schedule an activity changes the
        workflow's history and a history is a contract with every run that already exists. The
        rung-start mirror was shipped unguarded earlier today and took out `orch.status` for every
        live expedition with TMPRL1100 Nondeterminism.
        """
        if not workflow.patched("ceiling-parks-the-climb"):
            return False
        if not self._over_ceiling(cfg):
            return False
        cap = float(getattr(cfg, "ceiling_usd", 0.0) or 0.0)
        self._state = "parked"
        self._detail = (f"budget ceiling ${cap:.2f} reached — ${self._spent:.2f} spent, so the "
                        "climb stops here rather than creeping past it")
        return True

    async def _mirror(self, state: str | None = None, rung: int | None = None,
                      detail: str | None = None) -> None:
        """Push a state into the expedition store.

        Rung activities mirror their own OUTCOME. Two kinds of state have no activity behind
        them and would otherwise never reach the store: the ones the workflow itself decides
        (done / parked / killed), and the start of a rung — which is why the arguments exist.
        Without either, the wall shows the last rung's state for the whole of the next one.
        """
        n = self._input.number if self._input else 0
        try:
            await workflow.execute_activity(
                record_activity,
                args=[n, state or self._state,
                      self._rung if rung is None else rung,
                      detail or self._detail],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2))
        except Exception:  # bookkeeping must never change the outcome the human already saw
            pass

    async def _finish(self) -> Status:
        await self._mirror()
        return self.status()

    async def _wait_gate(self, *, need_pick: bool) -> str:
        """Block until the human acts. Returns 'approve' | 'pick' | 'feedback' | 'kill'."""
        g = self._gate
        g.approved, g.picked, g.feedback = False, None, None
        await workflow.wait_condition(
            lambda: self._killed is not None or g.feedback is not None
            or (g.picked is not None if need_pick else g.approved))
        if self._killed is not None:
            return "kill"
        if g.feedback is not None:
            return "feedback"
        return "pick" if need_pick else "approve"

    async def _wait_answer(self) -> str:
        """Block until the person answers rung 1's question, or stops the run.

        Deliberately NOT `_wait_gate`: that also wakes on `approved`, and an `/approve` arriving
        through the GitHub webhook path does not pass `app._refuse_absorbed_signal` — so a stray
        approval would advance past an unanswered question and build whichever reading the model
        happened to prefer, which is the exact failure this gate exists to stop.
        """
        g = self._gate
        g.feedback = None
        await workflow.wait_condition(
            lambda: self._killed is not None or g.feedback is not None)
        return "kill" if self._killed is not None else "feedback"

    async def _gated_rung(self, fn, rung: int, timeout_s: int, cfg: WorkflowConfig, *,
                          need_pick: bool, attempts: int = 1) -> bool:
        """Run a human-picks rung: activity, then wait; feedback re-runs (bounded); returns True to
        continue up the ladder, False when the expedition is parked."""
        rounds = 0
        while True:
            res = await self._run(fn, rung, timeout_s, attempts)
            if not res.passed:
                self._state = res.state or "descended"
                return False
            act = await self._wait_gate(need_pick=need_pick)
            if act == "kill":
                self._state, self._detail = "parked", f"killed: {self._killed}"
                return False
            if act == "feedback":
                rounds += 1
                if rounds >= cfg.max_feedback_rounds:
                    self._state, self._detail = "parked", f"rung {rung}: feedback rounds exhausted"
                    return False
                continue
            return True

    # ---- the ladder ---------------------------------------------------------------------
    @workflow.run
    async def run(self, arg: HarnessRun) -> Status:
        cfg = arg.cfg
        self._input = arg.input

        res = await self._run(spec_activity, 1, cfg.spec_s, attempts=2)
        # RUNG 1 MAY ASK INSTEAD OF GUESSING. "Move the button to the other side" has two real
        # readings in a poker app; expedition 40 invented a third, drew three good wireframes of
        # it, built it and opened a pull request for a surface nobody had named. Every gate said
        # yes because every artifact was well made.
        #
        # So this is the one rung that now has a gate of its own. The answer re-runs the spec in
        # place — same expedition, the question and their words carried into the prompt — because
        # a clarification is not a new request.
        #
        # Behind a patch: this changes what the workflow writes, and a history is a contract with
        # every run that already exists.
        if workflow.patched("rung-1-asks"):
            asked = 0
            while not res.passed and res.state == "await-answer":
                if await self._wait_answer() == "kill":
                    self._state, self._detail = "parked", f"killed: {self._killed}"
                    return await self._finish()
                asked += 1
                if asked >= cfg.max_answer_rounds:
                    self._state = "needs-human"
                    self._detail = ("asked twice and still could not tell what was meant — say it "
                                    "another way in a new request")
                    return await self._finish()
                res = await self._run(spec_activity, 1, cfg.spec_s, attempts=2)
            if res.passed:
                # The question is answered: it must not render under every later stage, and the
                # answer must not arrive at rung 2 as though it were a revision of the wireframes.
                self._artifacts.pop("question", None)
                self._gate.feedback = None
        if not res.passed:
            # A RUNG-1 REFUSAL IS NOT A BREAKAGE, and flattening both to `parked` made the surface
            # lie. Expedition 30 asked for "make it better and more modern", the spec rung declined
            # it in 40 seconds with a genuinely useful sentence — and the demo then offered RETRY,
            # which would re-run the identical request and get the identical answer. A button that
            # can only repeat itself is the false affordance this system exists to refuse.
            #
            # `needs-human` says the truth: nothing is broken, a person has something to add. The
            # honest actions there are stop it, or file again with what was missing.
            #
            # Behind a patch because this changes what the workflow writes, and a history is a
            # contract with every run that already exists — twice this week an unguarded change
            # here answered TMPRL1100 to every screen that asked a live run for its state.
            if workflow.patched("rung-1-may-refuse"):
                self._state = res.state or "parked"
            else:
                self._state = "parked"
            return await self._finish()
        if await self._park_if_broke(cfg):
            return await self._finish()

        if not await self._gated_rung(wireframe_activity, 2, cfg.wireframe_s, cfg, need_pick=True, attempts=2):
            return await self._finish()
        if await self._park_if_broke(cfg):
            return await self._finish()
        if not await self._gated_rung(prototype_activity, 3, cfg.prototype_s, cfg, need_pick=False):
            return await self._finish()
        if await self._park_if_broke(cfg):
            return await self._finish()
        if not await self._gated_rung(build_activity, 4, cfg.build_s, cfg, need_pick=False):
            return await self._finish()
        if await self._park_if_broke(cfg):
            return await self._finish()

        res = await self._run(ship_activity, 5, cfg.ship_s)
        if not res.passed:
            self._state = "parked"
            return await self._finish()
        act = await self._wait_gate(need_pick=False)
        if act == "kill":
            self._state, self._detail = "parked", f"killed: {self._killed}"
        elif act == "approve":
            self._state, self._detail = "done", "signed off; staged behind the flag"
        else:
            self._state, self._detail = "await-signoff", "feedback at rung 5 is recorded; sign-off still required"
        return await self._finish()

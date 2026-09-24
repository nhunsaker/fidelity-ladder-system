"""Activities — one per rung, each a thin wrapper over a pluggable Runner.

The Runner is the seam between Temporal and the engine: `LiveRunner` (worker) calls the real
rung code with real builders; `StubRunner` (Gate 0, tests) proves the plumbing with a trivial
Claude CLI turn or no model at all. Activities are SYNC functions (the engine is sync); the
worker runs them on a thread pool. Every activity persists its outcome to the expedition store
before returning so the Wall shows state even if the workflow is mid-wait.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from typing import Protocol

from temporalio import activity

from fls.orchestration.types import RungRequest, RungResult

log = logging.getLogger("fls.orchestration")


class Runner(Protocol):
    def spec(self, req: RungRequest) -> RungResult: ...
    def wireframe(self, req: RungRequest) -> RungResult: ...
    def prototype(self, req: RungRequest) -> RungResult: ...
    def build(self, req: RungRequest) -> RungResult: ...
    def ship(self, req: RungRequest) -> RungResult: ...
    def record(self, number: int, state: str, rung: int, detail: str, artifacts: dict) -> None: ...


class StubRunner:
    """Gate-0 runner: no engine builders. `wireframe` optionally runs ONE real `claude -p` turn
    (when `session` is given) so the expedition record carries a genuine claude-code call;
    everything else returns canned passes. Records nothing unless a `store` callable is given."""

    def __init__(self, session=None, store=None):
        self.session = session
        self.store = store
        self.recorded: list[tuple] = []

    def _r(self, req: RungRequest, state: str, detail: str, artifacts: dict | None = None,
           usd: float = 0.0, calls: int = 0) -> RungResult:
        return RungResult(rung=req.rung, passed=True, state=state, detail=detail,
                          spec=req.spec, artifacts=artifacts or {}, normalized_usd=usd, calls=calls)

    def spec(self, req: RungRequest) -> RungResult:
        r = self._r(req, "climbing", "stub spec")
        r.spec = f"SPEC (stub): {req.intent}"
        return r

    def wireframe(self, req: RungRequest) -> RungResult:
        if self.session is None:
            return self._r(req, "await-pick", "stub frames",
                           {"wireframe": [{"name": f"candidate-{i}"} for i in range(1, 4)]})
        res = self.session.run(f"Reply with exactly: ok (expedition {req.number})")
        from dataclasses import asdict
        # the call travels in the result so the worker's store mirror can attach it to the
        # expedition record (the wall's evidence of a real claude-code session)
        return self._r(req, "await-pick", f"claude-code turn: {res.text.strip()[:60]}",
                       {"wireframe": [{"name": f"candidate-{i}"} for i in range(1, 4)],
                        "session_id": res.session_id, "calls": [asdict(res.call)]},
                       usd=res.call.normalized_usd, calls=1)

    def prototype(self, req: RungRequest) -> RungResult:
        return self._r(req, "await-approve", "stub prototype", {"preview": {"url": f"/preview/{req.number}"}})

    def build(self, req: RungRequest) -> RungResult:
        return self._r(req, "await-approve", "stub build", {"pr": {"url": None, "tests": "stub green"}})

    def ship(self, req: RungRequest) -> RungResult:
        return self._r(req, "await-signoff", "stub stage", {"stage": {"url": None}})

    def record(self, number: int, state: str, rung: int, detail: str, artifacts: dict) -> None:
        self.recorded.append((number, state, rung, detail))
        if self.store is not None:
            self.store(number, state, rung, detail, artifacts)


# The worker sets this before starting; tests set it to a StubRunner. Module-level on purpose:
# Temporal activities are plain functions, and the runner holds the (non-serializable) engine.
RUNNER: Runner | None = None


def _runner() -> Runner:
    if RUNNER is None:
        raise RuntimeError("fls.orchestration.activities.RUNNER is not configured (worker not initialised)")
    return RUNNER


def _finish(req: RungRequest, res: RungResult) -> RungResult:
    _runner().record(req.number, res.state, res.rung, res.detail, res.artifacts)
    return res


# How often a running rung tells Temporal it is still alive. Paired with the workflow's
# `heartbeat_timeout`; well under it, so one slow beat is not mistaken for a dead worker.
HEARTBEAT_S = 15.0


def _store():
    """The expedition store, or None when this process has none (tests, Gate-0 stubs).

    Events are a diary, not a dependency: every caller here treats None as "write nothing".
    """
    try:
        import os

        from fls.store import ExpeditionStore
        return ExpeditionStore(os.environ.get("FLS_ROOT", "."))
    except Exception:  # noqa: BLE001 — no store is a fine answer; a broken diary is not an outage
        return None


def _event(number: int, kind: str, **fields) -> None:
    st = _store()
    if st is not None:
        st.append_event(number, kind, **fields)


def _cause(number: int, rung: int, attempt: int, *, kind: str, error: str, message: str) -> None:
    """Write down why this rung stopped, with the tail of whatever it was writing.

    Here rather than in the workflow because this is the only place that knows the attempt and
    can still reach the disk the session was writing to. The workflow gets a serialized result;
    it cannot read a transcript.
    """
    st = _store()
    if st is None:
        return
    from fls.store import artifact_tail
    artifact, tail = artifact_tail(st.root, number, rung)
    st.write_cause(number, {
        "kind": kind, "rung": rung, "attempt": attempt,
        "error": error, "message": message, "artifact": artifact, "tail": tail,
    })


class _Beat:
    """Heartbeats a sync rung from a side thread for as long as it runs.

    The rungs are SYNC functions on a thread pool — one long blocking call into a builder — so
    there is no point inside them at which to heartbeat. A daemon thread beside the work is the
    whole mechanism, and it buys two things that expedition 17 did without:

    * **A dead worker is noticed.** Without heartbeats Temporal has nothing to miss, so it waits
      out the full StartToClose. #17 was orphaned at 18:28:30 and not declared dead until
      18:40:34 — 900 seconds, to the second, of a run that had already stopped existing.
    * **Progress becomes visible for free.** The detail travels with the heartbeat and Temporal
      hands it back on `describe()` as `pending_activities[].heartbeat_details`, so the demo can
      show what the builder is doing with no new store and no new protocol.
    """

    def __init__(self, detail: str) -> None:
        self._detail = detail
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def note(self, detail: str) -> None:
        self._detail = detail

    def __enter__(self) -> _Beat:
        # THE FIRST BEAT HAPPENS HERE, on the activity's own thread, and it is the test of whether
        # heartbeating works at all. `activity.heartbeat()` finds its activity through a
        # ContextVar, and a plain `threading.Thread` starts with an EMPTY context — so the side
        # thread raised "Not in activity context" on its very first tick, hit a bare
        # `except: return`, and died without a word. No heartbeat ever reached Temporal.
        #
        # That turned a liveness mechanism into a kill switch: `heartbeat_timeout=60` shipped in
        # the same change, so Temporal cancelled every rung at 60 seconds. Expedition 18 died
        # three times in four minutes on a rung that needs five — and the recorded reason blamed
        # a ten-minute wall clock it never came close to.
        try:
            activity.heartbeat(self._detail)
        except Exception as ex:  # noqa: BLE001
            # No activity context at all: a unit test calling the rung directly. There is nothing
            # to beat to and nothing is watching for one, so run without a beat rather than
            # spawning a thread that cannot work.
            log.debug("no activity context; running without a heartbeat (%s)", ex)
            return self

        # Carry THIS thread's context across to the side thread, which is the whole fix.
        ctx = contextvars.copy_context()

        def loop() -> None:
            while not self._stop.wait(HEARTBEAT_S):
                try:
                    activity.heartbeat(self._detail)
                except Exception as ex:  # noqa: BLE001 — the activity ended, or was cancelled
                    # Said rather than swallowed. A beat that stops mid-rung means the rung is
                    # running blind from here on and Temporal will cancel it at the heartbeat
                    # timeout — which is exactly the failure that took four minutes to diagnose
                    # from a stack trace that named the wrong cause.
                    log.warning("heartbeat stopped mid-rung (%s): %s", type(ex).__name__, ex)
                    return

        self._t = threading.Thread(target=lambda: ctx.run(loop), daemon=True, name="fls-heartbeat")
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._t is not None:
            self._t.join(timeout=2.0)


def _stamp_step(number: int, rung: int, attempt: int) -> None:
    """When THIS attempt at this rung began — the clock the demo counts against the cap.

    Written here rather than by the worker's state mirror because this is the only place that
    knows the attempt. The mirror was guessing from (rung, state) and could not see a re-run at
    all: after expedition 17 was rewound, the same rung started over and the demo went on counting
    from the original start three hours earlier — 11,425 seconds against a cap of 900, which is
    the same "clock past its own limit" the whole exercise began with.

    A rung STARTING is exactly when a step starts. There is nothing to infer.
    """
    st = _store()
    if st is None:
        return
    import json as _json
    d = st.root / "expeditions" / str(number)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "step.json").write_text(
            _json.dumps({"rung": rung, "attempt": attempt, "started_at": time.time()}),
            encoding="utf-8")
    except OSError:
        pass


def _run_rung(name: str, method: str, req: RungRequest) -> RungResult:
    """One rung: heartbeat while it works, log what happened, write it down, hand it back.

    Every rung went through `_finish` and nothing else — no heartbeat, no log line, no event. The
    worker logged two lines at startup and then nothing for the rest of its life, so when a run
    died the only evidence that it had ever run was Temporal's own history. This is the one place
    all five rungs pass through, so it is the one place worth instrumenting.
    """
    attempt = 1
    try:
        attempt = activity.info().attempt
    except RuntimeError:
        pass  # not inside an activity (unit tests call the rung directly)
    started = time.monotonic()
    log.info("rung start: expedition=%s rung=%s attempt=%s activity=%s",
             req.number, req.rung, attempt, name)
    _event(req.number, "rung-start", rung=req.rung, attempt=attempt, activity=name)
    _stamp_step(req.number, req.rung, attempt)
    try:
        with _Beat(f"running {name}"):
            res = getattr(_runner(), method)(req)
    except BaseException as exc:
        # Logged and written down BEFORE it propagates. A rung that dies on the way out is the
        # case with the least evidence and the most need for it.
        took = time.monotonic() - started
        log.exception("rung failed: expedition=%s rung=%s attempt=%s after=%.1fs error=%s",
                      req.number, req.rung, attempt, took, type(exc).__name__)
        _event(req.number, "rung-failed", rung=req.rung, attempt=attempt, took_s=round(took, 1),
               error=type(exc).__name__, message=str(exc)[:300])
        _cause(req.number, req.rung, attempt, kind="crash",
               error=type(exc).__name__, message=str(exc)[:1000])
        raise
    took = time.monotonic() - started
    log.info("rung done: expedition=%s rung=%s attempt=%s passed=%s state=%s took=%.1fs usd=%.4f",
             req.number, req.rung, attempt, res.passed, res.state, took, res.normalized_usd)
    _event(req.number, "rung-done", rung=req.rung, attempt=attempt, took_s=round(took, 1),
           passed=res.passed, state=res.state, detail=res.detail[:300],
           normalized_usd=round(res.normalized_usd, 4))
    # A rung that REFUSED is not a crash — it ran, decided, and said no. It still owes the
    # reader an explanation, and it is the only one that can point at the test output that
    # made the decision. `parked` is the refusal; `needs-human` is a question, not a failure.
    if not res.passed and res.state == "parked":
        _cause(req.number, req.rung, attempt, kind="refused", error="", message=res.detail[:1000])
    return _finish(req, res)


@activity.defn(name="fls.spec")
def spec_activity(req: RungRequest) -> RungResult:
    return _run_rung("fls.spec", "spec", req)


@activity.defn(name="fls.wireframe")
def wireframe_activity(req: RungRequest) -> RungResult:
    return _run_rung("fls.wireframe", "wireframe", req)


@activity.defn(name="fls.prototype")
def prototype_activity(req: RungRequest) -> RungResult:
    return _run_rung("fls.prototype", "prototype", req)


@activity.defn(name="fls.build")
def build_activity(req: RungRequest) -> RungResult:
    return _run_rung("fls.build", "build", req)


@activity.defn(name="fls.ship")
def ship_activity(req: RungRequest) -> RungResult:
    return _run_rung("fls.ship", "ship", req)


@activity.defn(name="fls.record")
def record_activity(number: int, state: str, rung: int, detail: str) -> None:
    _runner().record(number, state, rung, detail, {})


ALL_ACTIVITIES = [spec_activity, wireframe_activity, prototype_activity, build_activity,
                  ship_activity, record_activity]

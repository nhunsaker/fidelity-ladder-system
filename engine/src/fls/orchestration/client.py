"""Harness-side client: start a workflow per expedition, forward the human protocol as signals,
read the status query. Async (the FastAPI harness is async); one cached connection per process.
Every call is guarded so a harness without Temporal (web-ui profile, tests) keeps working —
`available()` is False and the callers fall back to the in-process climb."""
from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from datetime import timedelta

from fls.orchestration.settings import TemporalSettings, workflow_id
from fls.orchestration.types import ExpeditionInput, HarnessRun, Status, WorkflowConfig

_client = None


def enabled() -> bool:
    """Orchestration is on when the instance says so (FLS_ORCHESTRATION=temporal)."""
    return os.environ.get("FLS_ORCHESTRATION", "").lower() == "temporal"


async def connect(settings: TemporalSettings | None = None):
    global _client
    if _client is None:
        from temporalio.client import Client
        s = settings or TemporalSettings.from_env()
        _client = await Client.connect(s.address, namespace=s.namespace)
    return _client


def reset() -> None:
    """Tests: drop the cached connection."""
    global _client
    _client = None


async def start(inp: ExpeditionInput, settings: TemporalSettings | None = None, cfg=None) -> str:
    """Start `HarnessExpedition` for this expedition; idempotent on workflow id (a second start
    for the same number returns the existing run's id rather than forking a duplicate)."""
    from temporalio.client import WorkflowFailureError  # noqa: F401  (documented failure type)
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from fls.orchestration.workflows import HarnessExpedition
    s = settings or TemporalSettings.from_env()
    c = await connect(s)
    arg = HarnessRun(input=inp, cfg=cfg or WorkflowConfig())
    try:
        h = await c.start_workflow(HarnessExpedition.run, arg, id=workflow_id(inp.number),
                                   task_queue=s.task_queue,
                                   execution_timeout=timedelta(days=7))
        return h.id
    except WorkflowAlreadyStartedError:
        return workflow_id(inp.number)


async def signal(number: int, name: str, payload=None, settings: TemporalSettings | None = None) -> None:
    """name ∈ approve | pick | feedback | kill. Unknown names raise (fail-closed)."""
    if name not in ("approve", "pick", "feedback", "kill"):
        raise ValueError(f"unknown signal {name!r}")
    c = await connect(settings)
    h = c.get_workflow_handle(workflow_id(number))
    if payload is None:
        await h.signal(name)
    else:
        await h.signal(name, payload)


async def status(number: int, settings: TemporalSettings | None = None) -> dict | None:
    """The workflow's status query as a plain dict, or None when no workflow exists for it.

    Carries `running`: whether the EXECUTION is still alive. A query answers from replayed history
    and works perfectly well on a workflow that is dead, returning whatever the last state was —
    so a run that died mid-rung answers "climbing" forever. Expedition 17 did exactly that, and
    the demo showed "Working on it" over a corpse for twenty minutes. The query says what the run
    last thought; only the execution status says whether anything is still thinking it.
    """
    from temporalio.service import RPCError
    c = await connect(settings)
    h = c.get_workflow_handle(workflow_id(number))
    from fls.orchestration.workflows import HarnessExpedition
    try:
        st: Status = await h.query(HarnessExpedition.status)
    except RPCError:
        return None
    out = asdict(st) if hasattr(st, "__dataclass_fields__") else dict(st)
    try:
        desc = await h.describe()
        # `None` is Temporal's answer for a running execution; anything else is a closed one.
        out["running"] = getattr(desc, "close_time", None) is None
        out["run_health"] = _health(desc)
    except RPCError:
        pass
    return out


def _health(desc) -> dict:
    """What Temporal already knows about the step in flight, as plain data.

    Nothing here is computed or stored by us: `pending_activities[]` carries the attempt, the last
    heartbeat, the last failure and when the next attempt fires, and it has carried them all
    along. The reason a dead expedition looked alive for twenty minutes was never that the
    information did not exist — it was that nothing asked.

    Returns `{}` when no activity is pending, which is the true answer at a gate: nothing is
    running, and the visitor is the one being waited on.
    """
    pend = list(getattr(desc.raw_description, "pending_activities", []) or [])
    if not pend:
        return {}
    a = pend[0]

    def _t(ts):
        return ts.ToSeconds() if ts is not None and ts.seconds else None

    beat = list(a.heartbeat_details.payloads) if a.HasField("heartbeat_details") else []
    return {
        "activity": a.activity_type.name,
        "attempt": a.attempt,
        "max_attempts": a.maximum_attempts or None,
        "last_heartbeat_at": _t(a.last_heartbeat_time),
        "started_at": _t(a.last_started_time),
        "next_attempt_at": _t(a.next_attempt_schedule_time),
        "worker": a.last_worker_identity or "",
        # The builder's own words, straight off the wire. Decoded best-effort: a payload we cannot
        # read is left out rather than guessed at.
        "doing": _beat_text(beat),
        "last_failure": (a.last_failure.message or "")[:300] if a.HasField("last_failure") else "",
    }


def _beat_text(payloads) -> str:
    import json as _json
    for pl in payloads:
        try:
            val = _json.loads(pl.data.decode("utf-8"))
        except (UnicodeDecodeError, _json.JSONDecodeError):
            continue
        if isinstance(val, list) and val:
            val = val[0]
        if isinstance(val, str):
            return val[:200]
    return ""


def rewind_point(events) -> tuple[int, bool]:
    """`(event id to rewind to, did anything go wrong)` for a run's history.

    Its own function so the choice can be tested against a real history shape rather than
    described in a comment — the event id IS the feature, and getting it wrong fails quietly in
    the worst direction: rewinding to the LAST workflow task replays the decision that ended the
    run, so it dies again, and it dies politely now that a timeout parks. A retry that visibly
    "worked" and changed nothing is worse than one that refuses.

    Matched on `EventType` VALUES. The first version of this matched on the stringified event
    type — `"TIMED_OUT" in str(ev.event_type)` — which cannot ever be true: `event_type` is a
    plain int on the wire, so `str()` of it is "14". It went out believing it worked because the
    test built its own history out of fabricated name strings, so the test and the code agreed
    with each other and neither agreed with Temporal. The enum is imported here for the same
    reason: a constant that comes from the SDK cannot drift away from what the SDK sends.
    """
    from temporalio.api.enums.v1 import EventType as E

    trouble = {E.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT, E.EVENT_TYPE_ACTIVITY_TASK_FAILED,
               E.EVENT_TYPE_ACTIVITY_TASK_CANCELED, E.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED,
               E.EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT,
               E.EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED}
    point = 0
    for ev in events:
        t = int(ev.event_type)
        if t in trouble:
            return point, True
        if t == E.EVENT_TYPE_WORKFLOW_TASK_COMPLETED:
            point = ev.event_id
    return point, False


async def rewind(number: int, reason: str = "retry", settings: TemporalSettings | None = None) -> str:
    """Rewind a run to just before the step that killed it, and let it climb again.

    Named `rewind` rather than `reset` because this module's `reset()` already means something
    else entirely — drop the cached client connection — and two functions called reset in one file,
    one of which restarts a run that has spent real money, is a mistake waiting to be made.

    A failed workflow cannot be resumed — that is Temporal's rule, not a limitation of this code —
    so "try again" for expedition 17 would otherwise have meant filing the request a second time
    and paying for rungs 0 through 2 again to get back to where it already was. Reset replays the
    history up to the last workflow task BEFORE the failure and carries on from there, so the
    spec, the visitor's pick and the $2.58 already spent all survive.

    Fail-closed in the one way that matters: a run with no failure point to rewind to is refused
    rather than reset to somewhere arbitrary. Returns the new run id.
    """
    from temporalio.api.workflowservice.v1 import ResetWorkflowExecutionRequest

    c = await connect(settings)
    h = c.get_workflow_handle(workflow_id(number))
    desc = await h.describe()
    if getattr(desc, "close_time", None) is None:
        raise ValueError(f"expedition {number} is still running; nothing to retry")

    # The last completed workflow task BEFORE THE FIRST THING THAT WENT WRONG — not the last one
    # in the history, which is the decision that ended the run. Rewinding to that would replay the
    # failure itself: for expedition 17 it would hand the workflow the same activity timeout it
    # already has, and the run would simply die again (politely, now that a timeout parks). The
    # step has to be re-SCHEDULED, which means rewinding to before it was scheduled at all.
    point, seen_trouble = rewind_point([ev async for ev in h.fetch_history_events()])
    if not point:
        raise ValueError(f"expedition {number} has no point to rewind to")
    if not seen_trouble:
        # A run that ended cleanly has nothing to retry, and rewinding one would re-do work a
        # human already accepted. The caller's own checks should have caught this; this is the
        # backstop that sits closest to the button.
        raise ValueError(f"expedition {number} ended without a failure — nothing to retry")

    # `request_id` is required, and it is Temporal's idempotency key rather than a formality: two
    # clicks on Retry inside the same moment would otherwise be two rewinds, and a rewind starts a
    # builder that costs money. A fresh uuid per call is the honest version — each deliberate
    # press is its own request — and Temporal collapses a retransmit of the same one.
    resp = await c.workflow_service.reset_workflow_execution(
        ResetWorkflowExecutionRequest(
            namespace=c.namespace,
            workflow_execution=desc.raw_description.workflow_execution_info.execution,
            reason=reason[:200],
            workflow_task_finish_event_id=point,
            request_id=str(uuid.uuid4()),
        ))
    return resp.run_id


def command_to_signal(text: str) -> tuple[str, object] | None:
    """Map the issue-comment protocol onto signals: `/approve`, `/pick N`, `/kill [reason]`,
    anything else = feedback text. Returns None for empty input."""
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("/approve") or t.startswith("/advance"):
        return ("approve", None)
    if t.startswith("/pick"):
        parts = t.split()
        try:
            return ("pick", int(parts[1]))
        except (IndexError, ValueError):
            return ("feedback", t)
    if t.startswith("/kill"):
        return ("kill", t[len("/kill"):].strip() or "killed")
    return ("feedback", t)

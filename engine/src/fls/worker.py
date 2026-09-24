"""python -m fls.worker — the Claude Code worker: a Temporal Worker on task queue `fls-harness`
running the HarnessExpedition workflow and its rung activities.

Runner selection (env `FLS_WORKER_RUNNER`):
  stub        Gate 0: canned rungs; rung 2 runs ONE real `claude -p` turn so the ledger shows a
              genuine claude-code row (set FLS_WORKER_STUB_NO_CLI=1 to skip even that).
  live        (Phase 1+) real builders — registered as they land; refuses to start until then.

Activities are sync engine calls, so they run on a thread pool sized by FLS_WORKER_THREADS
(default 2: one long build plus one cheap rung). Never more Claude sessions than that at once.
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger("fls.worker")


def _cause_for_park(store, number: int, rung: int, detail: str) -> None:
    """Turn a workflow's park sentence into a cause record, if nothing else wrote one.

    `workflows._why()` already writes the honest sentence for a reader — "it stopped answering
    while it worked", "it ran past its N minute limit". What it cannot do is name the artifact
    or carry its tail, because by then it only has a serialized failure. This does both.
    """
    import json as _json

    from fls.store import artifact_tail
    d = store.root / "expeditions" / str(number)
    fresh = 0.0
    try:
        fresh = _json.loads((d / "step.json").read_text(encoding="utf-8")).get("started_at", 0.0)
    except Exception:  # noqa: BLE001
        pass
    existing = store.cause(number)
    if existing and float(existing.get("at") or 0.0) >= fresh:
        return          # the activity explained itself; the mirror knows less
    attempt = 1
    try:
        attempt = int(_json.loads((d / "step.json").read_text(encoding="utf-8")).get("attempt", 1))
    except Exception:  # noqa: BLE001
        pass
    low = (detail or "").lower()
    kind = ("heartbeat" if "stopped answering" in low
            else "timeout" if "limit" in low
            else "stopped")
    artifact, tail = artifact_tail(store.root, number, rung)
    store.write_cause(number, {
        "kind": kind, "rung": rung, "attempt": attempt,
        "error": "", "message": (detail or "")[:1000], "artifact": artifact, "tail": tail,
    })


def _store_recorder():
    """Persist rung state into the expedition store so the Wall shows it (best effort)."""
    try:
        from fls.store import ExpeditionStore
        root = Path(os.environ.get("FLS_ROOT", Path(__file__).resolve().parents[3]))
        store = ExpeditionStore(root)
    except Exception as e:  # pragma: no cover — store is optional for the worker
        log.warning("expedition store unavailable (%s); worker will not mirror state", e)
        return None

    def _carry(e, rec_dict) -> None:
        """Re-attach the totals the store already held, as one labelled summary row.

        `spent` is computed from `calls`, and a rehydrated Expedition has none — so every write
        started from zero. The ledger holds the per-call truth; the store's number has always been
        a total, and a total that restates its own previous value invents nothing.
        """
        from fls.llm import Call as _C
        prior = float(rec_dict.get("normalized_usd") or 0.0)
        metered = float(rec_dict.get("spent") or 0.0)
        if prior or metered:
            e.add([_C(provider="carried-forward", model="", usd=metered, normalized_usd=prior)])

    def rec(number: int, state: str, rung: int, detail: str, artifacts: dict) -> None:
        try:
            from fls.github_surface import _rehydrate
            from fls.llm import Call
            r = store.get(number)   # the store hands back a dict view, not an Expedition
            if r is None:
                return
            # A PARK IS A HUMAN DECISION AND A MIRROR IS A MACHINE'S REPORT, which is always at
            # least one rung out of date. Stopping a run signals the workflow, and the workflow
            # honours that at its next gate — so the rung already in flight finishes and mirrors
            # its own outcome afterwards, writing `climbing` or `await-pick` straight back over
            # the park. The Stop button then appeared to do nothing: the run kept moving on the
            # screen, which is the one thing the button promises it will not do.
            #
            # So a parked expedition stays parked. The money and the artifacts from the rung that
            # was already running still land below — that work happened and the record should say
            # so — but its STATE does not, because nothing a machine reports afterwards makes a
            # stopped run unstopped.
            from fls.expedition import PARKED
            if r.get("status") == PARKED:
                state, detail = PARKED, r.get("reason") or detail
            e = _rehydrate(r, rung, state)
            # WHO stopped it. A human park is stamped where the person pressed the button and must
            # survive every mirror after it; a park the workflow decided is a failure, and it is
            # the only one the surface may offer to retry.
            was = r.get("parked_by") or ""
            e.parked_by = was or ("failure" if state == PARKED else "")
            e.reason = detail
            # The prior total ALWAYS carries; a rung's own calls are added ON TOP. A rung result
            # carries only that rung's calls, so replacing rather than accumulating left the store
            # showing the cost of the last rung instead of the run: expedition 15 read 0.6621
            # while the run it came from had spent 1.5457.
            calls = artifacts.get("calls", [])
            if calls:
                _carry(e, r)
                for c in calls:                       # real builder sessions -> the record
                    e.add([Call(**c)])
            else:
                # A STATE mirror must not zero the money. `spent` is computed from `calls`, and a
                # rehydrated Expedition has none — so any write carrying no calls reset the
                # recorded cost to 0. The terminal mirror always carries none, which is why every
                # FINISHED expedition on the wall read $0.00 while the run had cost real money:
                # #12 showed $0.00 against $6.25 actually spent, on the screen whose footer is
                # about spend.
                #
                # Carried forward as one summary row, labelled as exactly that. The ledger holds
                # the per-call truth; the store's number has always been a total, and a total that
                # restates its own previous value invents nothing.
                _carry(e, r)
            store.save(e)
            # WHEN this step started, recorded server-side. The client was measuring from when
            # the page first saw the step, so a refresh reset the clock and someone arriving
            # late saw "0s" on a step that had been running for minutes. A timestamp on the
            # server is the only version that survives a reload.
            import json as _json
            d = store.root / "expeditions" / str(number)
            d.mkdir(parents=True, exist_ok=True)
            p_step = d / "step.json"
            prev = {}
            if p_step.exists():
                try:
                    prev = _json.loads(p_step.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    prev = {}
            # The step clock is stamped by the ACTIVITY now (activities._stamp_step), which is
            # the only place that knows which ATTEMPT this is. This mirror was inferring it from
            # (rung, state) and got it wrong twice: a rung resuming after its own gate kept the
            # same number, and a rung re-run after a rewind kept both — so #17's demo counted
            # 11,425 seconds against a 900-second cap on a step that had just started.
            #
            # What remains here is only the END of a step: once a run stops climbing, the marker
            # must not go on describing a step as though it were still running.
            if state != "climbing" and prev.get("state") == "climbing":
                prev["state"] = state
                p_step.write_text(_json.dumps(prev), encoding="utf-8")
            # Record WHAT THE RUNG PRODUCED, as facts, beside the state. The rich bag lives in
            # the durable run and is reachable only by querying Temporal — and the Wall renders
            # every expedition at once, so reading it from the run would mean one query per row
            # on every load. The Wall is the screen that most needs to say what each run made.
            from fls.store import artifact_facts_from
            if facts := artifact_facts_from(artifacts or {}):
                store.save_artifact_facts(number, facts)
            # A park the WORKFLOW decided — a heartbeat that stopped, a rung past its limit —
            # leaves no cause behind, because no activity lived to write one. The workflow's own
            # sentence is all there is, so it becomes the cause here, with the tail of whatever
            # the dead session had written by the time it went.
            #
            # Only when nothing already explained this stop: an activity that wrote its own
            # cause knows more than the mirror does, and must not be overwritten by it.
            if state == PARKED and not was:
                _cause_for_park(store, number, rung, detail)
            # A RUN THAT IS OVER LETS GO OF ITS WORKTREE. Merged, or stopped by a person — never a
            # failure park, which a retry adopts. This is the one place every terminal transition
            # already passes, so it is the one place to say so.
            _release_if_over(store, number, state, was)
        except Exception as ex:  # never let bookkeeping fail a rung
            log.warning("store mirror failed for %s: %s", number, ex)
    return rec


def _release_if_over(store, number: int, state: str, parked_by: str) -> None:
    """Remove `expeditions/N/mvp/wt` when the run has ended for good.

    `done`/`docked`: the code is on main — the checkout AND the local `exp-N` branch go.
    A human park (`parked_by` is a name, not "failure"): the checkout goes, the branch stays in
    case somebody wants to look. A failure park keeps both: `/retry` builds on them.
    """
    from fls.expedition import PARKED
    merged = state in ("done", "docked")
    stopped = state == PARKED and bool(parked_by) and parked_by != "failure"
    if not (merged or stopped):
        return
    repo = os.environ.get("FLS_VESSEL_REPO", "")
    wt = store.root / "expeditions" / str(number) / "mvp" / "wt"
    if not repo or not wt.exists():
        return
    from fls.builders.claude_code_builder import release_worktree
    log.info("expedition %s is over (%s): %s", number, state,
             release_worktree(repo, wt, branch=f"exp-{number}", delete_branch=merged))


def build_runner(kind: str):
    from fls.orchestration.activities import StubRunner
    if kind == "stub":
        session = None
        if os.environ.get("FLS_WORKER_STUB_NO_CLI") != "1":
            from fls.claude_code import ClaudeCodeSession
            session = ClaudeCodeSession(cwd=os.environ.get("FLS_WORKER_ROOT", "."), max_turns=1,
                                        timeout_s=120, allowed_tools=(),
                                        mcp_config=None)
        return StubRunner(session=session, store=_store_recorder())
    if kind == "live":
        # Real builders for the rungs that have one; the stub supplies the rest and the store
        # mirror. FLS_LIVE_RUNGS names which rungs are real (default: 2, the wireframe rung).
        from fls.anchor import Anchor
        from fls.orchestration.live import LiveRunner
        anchor_path = os.environ.get("FLS_ANCHOR_PATH")
        if not anchor_path:
            raise SystemExit("live runner needs FLS_ANCHOR_PATH (the instance ANCHOR)")
        anchor = Anchor.load(anchor_path)
        rungs = tuple(int(x) for x in os.environ.get("FLS_LIVE_RUNGS", "2").split(",") if x.strip())
        root = Path(os.environ.get("FLS_ROOT", Path(__file__).resolve().parents[3]))
        stub = StubRunner(session=None, store=_store_recorder())
        log.info("live runner: rungs=%s figma_file=%s", rungs,
                 "set" if os.environ.get("FLS_FIGMA_FILE_KEY") else "UNSET")
        return LiveRunner(anchor, stub, root=root, live_rungs=rungs)
    raise SystemExit(f"unknown FLS_WORKER_RUNNER={kind!r} (stub | live)")


async def main() -> None:
    logging.basicConfig(level=os.environ.get("FLS_LOG_LEVEL", "INFO"))
    from temporalio.worker import Worker

    from fls.orchestration import activities
    from fls.orchestration.client import connect
    from fls.orchestration.settings import TemporalSettings
    from fls.orchestration.workflows import HarnessExpedition

    s = TemporalSettings.from_env()
    activities.RUNNER = build_runner(os.environ.get("FLS_WORKER_RUNNER", "stub"))
    client = await connect(s)
    threads = int(os.environ.get("FLS_WORKER_THREADS", "2"))
    log.info("fls-worker: %s ns=%s queue=%s runner=%s threads=%d", s.address, s.namespace,
             s.task_queue, os.environ.get("FLS_WORKER_RUNNER", "stub"), threads)
    with ThreadPoolExecutor(max_workers=threads) as pool:
        worker = Worker(client, task_queue=s.task_queue, workflows=[HarnessExpedition],
                        activities=activities.ALL_ACTIVITIES, activity_executor=pool,
                        max_concurrent_activities=threads)
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())

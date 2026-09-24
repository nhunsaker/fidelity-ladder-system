"""The heartbeat has to reach Temporal, and the test has to prove it from another thread.

THE BUG THIS FILE EXISTS FOR. `_Beat` heartbeats a long sync rung from a daemon thread beside the
work. `activity.heartbeat()` resolves the running activity through a `ContextVar`, and a plain
`threading.Thread` starts with an EMPTY context — so the beat raised "Not in activity context" on
its very first tick, hit a bare `except Exception: return`, and the thread died without a word.

Nothing noticed, because the mechanism's only job was to be silent. But `heartbeat_timeout=60`
shipped in the same change, so Temporal cancelled every rung at 60 seconds: expedition 18 died
three times in four minutes on a rung that needs five, and the reason it recorded blamed a
ten-minute wall clock it never came within eight minutes of.

The test that would have caught it has to assert the beat arrives on the SIDE thread, not merely
that `_Beat` can be entered. A test that patched `activity.heartbeat` and called it directly would
have passed against the broken version, because the bug was never in the call — it was in which
thread the call was made from.
"""
from __future__ import annotations

import contextvars
import threading
import time

import pytest

from fls.orchestration import activities as act


@pytest.fixture
def beats(monkeypatch):
    """Record heartbeats, and refuse any that arrive without the activity context set.

    This mirrors what the real SDK does: `_Context.current()` reads a ContextVar and raises when
    it is missing. Without that refusal the fake would accept beats from a context-less thread and
    the test would pass against exactly the bug it exists to catch.
    """
    got: list[tuple[str, str]] = []

    def fake_heartbeat(*details):
        if act.activity.in_activity() is not True:      # the SDK's own question
            raise RuntimeError("Not in activity context")
        got.append((threading.current_thread().name, details[0] if details else ""))

    monkeypatch.setattr(act.activity, "heartbeat", fake_heartbeat)
    return got


@pytest.fixture
def in_activity(monkeypatch):
    """Stand in for a running activity: a ContextVar that is set on THIS thread only."""
    var = contextvars.ContextVar("in-activity")
    var.set(True)
    monkeypatch.setattr(act.activity, "in_activity", lambda: var.get(False) is True)
    return var


def test_the_side_thread_beats_while_the_rung_runs(monkeypatch, in_activity, beats):
    """THE REGRESSION TEST. The beat must arrive from the daemon thread, which only happens if
    the activity's context was carried across to it."""
    monkeypatch.setattr(act, "HEARTBEAT_S", 0.02)
    with act._Beat("drawing three candidates"):
        time.sleep(0.15)                                  # the "rung", running

    side = [b for b in beats if b[0] == "fls-heartbeat"]
    assert side, "no heartbeat ever arrived from the side thread — the rung is running blind"
    assert side[0][1] == "drawing three candidates", "the detail did not travel with the beat"


def test_the_first_beat_is_sent_before_any_waiting(monkeypatch, in_activity, beats):
    """A rung that beats only every 15s is unwatched for its first 15 seconds. The opening beat
    also proves, on the activity's own thread, that heartbeating works at all — which is the
    check that was missing."""
    monkeypatch.setattr(act, "HEARTBEAT_S", 3600)         # the loop will never tick
    with act._Beat("starting"):
        pass
    assert beats and beats[0][1] == "starting", "nothing was sent before the first interval"


def test_the_detail_travels_with_later_beats(monkeypatch, in_activity, beats):
    """Progress is carried by the heartbeat — Temporal hands it back on `describe()`, which is
    how the demo can say what a builder is doing with no new store and no new protocol. A beat
    pinned to its opening string would make that permanently useless."""
    monkeypatch.setattr(act, "HEARTBEAT_S", 0.02)
    with act._Beat("first") as b:
        time.sleep(0.08)
        b.note("second")
        time.sleep(0.08)
    assert "second" in [d for _, d in beats], "note() never reached a beat"


def test_without_an_activity_context_it_runs_without_a_beat(monkeypatch, beats):
    """A unit test calling a rung directly is not in an activity. There is nothing to beat to and
    nothing watching for one, so the rung must simply run — not raise, and not spawn a thread
    that cannot work."""
    monkeypatch.setattr(act.activity, "in_activity", lambda: False)
    monkeypatch.setattr(act, "HEARTBEAT_S", 0.02)
    with act._Beat("no context here"):
        time.sleep(0.05)
    assert beats == []


def test_a_beat_from_a_bare_thread_would_fail_this_fixture():
    """The fixture's own teeth, asserted rather than assumed.

    If a context-less thread could heartbeat, every test above would pass against the broken
    version. This pins the property the whole file rests on: a plain `threading.Thread` does NOT
    inherit its creator's context.
    """
    var = contextvars.ContextVar("probe")
    var.set("set on the main thread")
    seen: dict[str, object] = {}
    t = threading.Thread(target=lambda: seen.update(v=var.get(None)))
    t.start()
    t.join()
    assert seen["v"] is None, "contextvars now cross threads; _Beat's fix may be unnecessary"

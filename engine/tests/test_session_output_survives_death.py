"""A session that is killed from outside must still say what it did.

THE BUG THIS FILE EXISTS FOR. `run()` captured stdout into a pipe, which lives in this process and
dies with it. Temporal cancelled expedition 18's three rung-2 sessions from inside
`communicate()` — an exception the class did not catch — so every word those sessions produced was
discarded. What was left was a stack trace naming the wrong timeout.

That is not only a diagnosis problem. It is the reason a retry cannot find the work a dead attempt
left behind: the Figma page id travels in the session's own output, and there is no other channel.
The session's tool surface is three Figma tools — it cannot write a file, and it cannot reach the
harness any other way. So "the transcript is on disk before anything goes wrong" IS the recovery
mechanism, not a convenience beside it.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from fls.claude_code import ClaudeCodeError, ClaudeCodeSession

ENVELOPE = '{"result": "done", "usage": {"input_tokens": 10, "output_tokens": 2}, "num_turns": 1}'


def _fake_cli(tmp_path, script: str):
    """A stand-in for the `claude` binary: a python script we fully control."""
    p = tmp_path / "fake-claude"
    p.write_text(f"#!{sys.executable}\n" + script)
    p.chmod(0o755)
    return p


def _session(tmp_path, cli, **kw):
    return ClaudeCodeSession(cwd=str(tmp_path), bin=str(cli), **kw)


def test_a_cancelled_session_leaves_its_transcript_on_disk(tmp_path):
    """THE REGRESSION TEST. The work is killed the way Temporal kills it — a BaseException raised
    while we are blocked on the child — and what it had already printed must survive.

    CancelledError is deliberately modelled as a BaseException subclass, because that is what it
    is, and catching `Exception` would have missed it exactly as the old code did.
    """
    log = tmp_path / "wireframes" / "session-1.log"
    cli = _fake_cli(tmp_path, "import sys,time\n"
                              "print('FLS-PAGE: exp-18 13:2', flush=True)\n"
                              "time.sleep(30)\n")
    s = _session(tmp_path, cli, log_path=log, timeout_s=30)

    class Cancelled(BaseException):
        pass

    real = subprocess.Popen.communicate

    def boom(self, *a, **k):
        # let the child actually print first, then die the way a cancellation does
        import time
        time.sleep(1.0)
        raise Cancelled()

    subprocess.Popen.communicate = boom
    try:
        with pytest.raises(Cancelled):
            s.run("go")
    finally:
        subprocess.Popen.communicate = real

    assert log.exists(), "the session died and took its transcript with it"
    assert "FLS-PAGE: exp-18 13:2" in log.read_text(), \
        "the page id a retry needs was lost — this is the whole recovery channel"


def test_the_child_is_killed_rather_than_orphaned(tmp_path):
    """An abandoned claude session goes on holding the design file and the subscription. The
    cancellation path must take the child down with it."""
    log = tmp_path / "s.log"
    cli = _fake_cli(tmp_path, "import time\ntime.sleep(60)\n")
    s = _session(tmp_path, cli, log_path=log, timeout_s=60)
    seen = {}

    class Cancelled(BaseException):
        pass

    real_comm, real_kill = subprocess.Popen.communicate, subprocess.Popen.kill

    def boom(self, *a, **k):
        seen["proc"] = self
        raise Cancelled()

    def kill(self):
        seen["killed"] = True
        real_kill(self)

    subprocess.Popen.communicate, subprocess.Popen.kill = boom, kill
    try:
        with pytest.raises(Cancelled):
            s.run("go")
    finally:
        subprocess.Popen.communicate, subprocess.Popen.kill = real_comm, real_kill
    assert seen.get("killed") is True, "the child was left running after the rung was cancelled"


def test_a_normal_streamed_run_returns_the_same_result_as_a_buffered_one(tmp_path):
    """Streaming changes WHERE the bytes go, not what a caller gets back. Without this, the whole
    accounting path could quietly break on the streamed path and every test above still pass."""
    cli = _fake_cli(tmp_path, f"print({ENVELOPE!r})\n")
    buffered = _session(tmp_path, cli).run("go")
    streamed = _session(tmp_path, cli, log_path=tmp_path / "s.log").run("go")
    assert buffered.text == streamed.text == "done"
    assert buffered.call.input_tokens == streamed.call.input_tokens
    assert streamed.call.normalized_usd == buffered.call.normalized_usd
    assert streamed.exit_code == 0


def test_a_timeout_on_the_streamed_path_still_returns_what_was_written(tmp_path):
    """A wall-clock expiry is not an exception here — it comes back as `timed_out` with whatever
    the session managed to say, so the rung can feed it forward. That has to hold on both paths."""
    log = tmp_path / "s.log"
    cli = _fake_cli(tmp_path, "import time\nprint('partial work', flush=True)\ntime.sleep(30)\n")
    r = _session(tmp_path, cli, log_path=log, timeout_s=2).run("go")
    assert r.timed_out is True and r.exit_code == -9
    assert "partial work" in r.text


def test_a_failing_cli_still_raises_loudly_when_streamed(tmp_path):
    """An unauthenticated CLI must never be smoothed into an empty result on either path."""
    cli = _fake_cli(tmp_path, "import sys\nsys.stderr.write('Not logged in\\n')\nsys.exit(1)\n")
    with pytest.raises(ClaudeCodeError, match="no envelope"):
        _session(tmp_path, cli, log_path=tmp_path / "s.log").run("go")


def test_the_log_directory_is_created(tmp_path):
    """The log lands beside the expedition's other artifacts, in a directory that may not exist
    on the first attempt of the first rung."""
    log = tmp_path / "expeditions" / "18" / "wireframes" / "session-1.log"
    cli = _fake_cli(tmp_path, f"print({ENVELOPE!r})\n")
    _session(tmp_path, cli, log_path=log).run("go")
    assert log.exists()


def test_the_result_envelope_is_found_among_streamed_events(tmp_path):
    """Under stream-json the output is many events and only one is the accounting envelope.

    It is matched BY NAME, not by being last: the CLI also emits `rate_limit_event`, and a parser
    that simply took the final JSON object would read the cost off whichever line happened to come
    last. Expedition 19's real output carried system/rate_limit_event/assistant/result, in that
    order — this is that shape.
    """
    from fls.claude_code import ClaudeCodeSession
    stream = "\n".join([
        '{"type":"system","subtype":"init"}',
        '{"type":"rate_limit_event"}',
        '{"type":"assistant","message":{"content":"FLS-PAGE: exp-19 18:2"}}',
        '{"type":"result","subtype":"success","result":"done","num_turns":3,'
        '"usage":{"input_tokens":5,"output_tokens":7},"total_cost_usd":0.25}',
        # The envelope is NOT always last. A trailing event taken for the envelope would hand the
        # ledger a call with no tokens and no cost, and the run would look free.
        '{"type":"rate_limit_event"}',
    ])
    env = ClaudeCodeSession._parse(stream)
    assert env.get("result") == "done" and env.get("total_cost_usd") == 0.25


def test_a_sentinel_is_readable_from_a_stream_that_never_reached_its_result(tmp_path):
    """THE POINT OF ALL OF IT. A session cancelled mid-rung has no result event at all — but the
    events it already wrote are on disk, and the page id is in one of them."""
    from fls.builders.figma_wireframe import page_id_from_log
    partial = "\n".join([
        '{"type":"system","subtype":"init"}',
        '{"type":"assistant","message":{"content":"FLS-PAGE: exp-19 18:2\\nnow drawing c1"}}',
    ])
    assert page_id_from_log(partial, 19) == "18:2"


def test_stderr_is_kept_beside_the_transcript_because_that_is_where_the_reason_is(tmp_path):
    """stdout is the narration; stderr is where the CLI says it could not log in, could not reach
    the MCP endpoint, or ran out of quota. It used to survive only inside `SessionResult`, clipped
    to 800 characters, folded into the rung's detail and clipped again to 300 in the event — so
    the one sentence that explains a failure was cut in half twice before anybody read it."""
    log = tmp_path / "wireframes" / "session-1.log"
    cli = _fake_cli(tmp_path, "import sys\n"
                              "sys.stderr.write('MCP server \"figma\" is not logged in\\n')\n"
                              f"print({ENVELOPE!r})\n")
    _session(tmp_path, cli, log_path=log).run("go")

    kept = log.with_suffix(log.suffix + ".stderr")
    assert kept.exists(), "the reason was thrown away with the process"
    assert "not logged in" in kept.read_text()


def test_a_session_with_nothing_on_stderr_leaves_no_empty_file(tmp_path):
    """Every session would otherwise leave a `.stderr`, and `artifact_tail` prefers that sibling —
    an empty file that displaced the transcript would make every failure look silent."""
    log = tmp_path / "s.log"
    cli = _fake_cli(tmp_path, f"print({ENVELOPE!r})\n")
    _session(tmp_path, cli, log_path=log).run("go")
    assert not log.with_suffix(log.suffix + ".stderr").exists()

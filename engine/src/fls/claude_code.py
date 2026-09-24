"""fls.claude_code — an AGENTIC builder session on the Claude Code CLI (harness PoC, 2026-09-10).

The existing builders are single-shot `complete(prompt) -> text`. The harness PoC's rungs need a
session with tools: a working directory, an allowed-tool list, MCP servers (Figma, Claude Design),
and a hard budget. That budget is TURNS + WALL CLOCK, not output tokens — an agent that loops is
bounded by `--max-turns` and a subprocess timeout, never by hope.

Same shape as a plain CLI runner (prompt on stdin, SIGKILL on timeout, loud non-zero exit) plus
the envelope fields a text-only runner ignores: `total_cost_usd`,
`num_turns`, `session_id`, `usage`. Accounting rides the subscription lane: `usd=0`,
`normalized_usd` = the CLI's own cost figure when present (it is the list-rate equivalent), else
tokens priced at the shadow model, so the ledger's two-column model still compares lanes.

Nothing here reads a credential. The CLI finds its own login in `$HOME/.claude` — on the VM that
is the one-time interactive login (see fls-harness/provision/one-time-logins.md).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from fls.llm import BudgetGuard, Call, _usd


class ClaudeCodeError(RuntimeError):
    """The CLI failed (unauthenticated, crashed, timed out, or returned no envelope)."""


@dataclass
class SessionResult:
    text: str                    # the `result` field (the agent's final message)
    call: Call                   # ledger accounting for this session
    num_turns: int = 0
    session_id: str | None = None
    timed_out: bool = False
    exit_code: int = 0
    raw: dict = field(default_factory=dict)


# What a credential looks like in an environment variable name. Deliberately broad: a false
# positive costs an agent a variable it did not need, a false negative hands it a live secret.
_SECRETISH = re.compile(r"TOKEN|SECRET|KEY|PASSWORD|PASSWD|PASSCODE|CREDENTIAL|AUTH", re.I)


class _Done:
    """stdout/stderr/returncode from either path, so `_finish` reads the same for both."""

    __slots__ = ("stdout", "stderr", "returncode")

    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout, self.stderr, self.returncode = stdout or "", stderr or "", returncode


@dataclass
class ClaudeCodeSession:
    """One configured way to run `claude -p`. Immutable config; `run()` per prompt.

    cwd            working directory the agent operates in (a worktree, a temp dir, ...)
    allowed_tools  passed as --allowedTools (e.g. ["Read","Edit","Write","Bash(pnpm *)"])
    mcp_config     path to a Claude Code --mcp-config JSON (figma remote + claude-design)
    max_turns      --max-turns hard cap (the agent's real budget)
    timeout_s      wall-clock cap; SIGKILL past it and the call is recorded as timed out
    model          --model override; None = CLI default
    shadow_model   list-price model for normalized_usd when the CLI reports no cost
    bin            the CLI binary (env CLAUDE_BIN, default "claude")
    """
    cwd: str | Path
    allowed_tools: tuple[str, ...] = ()
    mcp_config: str | None = None
    max_turns: int = 30
    timeout_s: int = 600
    model: str | None = None
    shadow_model: str = "claude-sonnet-5"
    bin: str = field(default_factory=lambda: os.environ.get("CLAUDE_BIN", "claude"))
    guard: BudgetGuard | None = None
    permission_mode: str = "acceptEdits"   # unattended: never prompt; Bash stays allow-listed
    # Where this session's stdout is streamed AS IT HAPPENS. The default (None) keeps the output
    # in a pipe buffer, which means it exists only in this process — and a session killed from
    # outside takes every word of it to the grave. Expedition 18 lost three sessions that way:
    # Temporal cancelled them from inside `communicate()`, an exception this class does not catch,
    # so what the builder had actually done was simply gone. Give this a path and the transcript
    # is on disk before anything reads it back.
    log_path: str | Path | None = None
    extra_args: tuple[str, ...] = ()
    # Environment variables the child MAY keep even though they look secret-ish. The CLI's own
    # credential is the only thing that belongs here.
    env_allow: tuple[str, ...] = ("CLAUDE_CODE_OAUTH_TOKEN",)

    def args(self, system: str | None = None) -> list[str]:
        # STREAM-JSON, NOT JSON, and the difference is the whole recovery story. `--output-format
        # json` buffers the entire session and emits ONE envelope when it finishes — so streaming
        # stdout to a file bought nothing: a cancelled session left a file containing zero bytes,
        # because nothing had been written yet. Expedition 19 proved it live: the log existed, the
        # rung succeeded, and the page-id sentinel the session had been told to print first was
        # nowhere in it, having only ever existed inside the final envelope.
        #
        # `stream-json` writes one newline-delimited event as each happens, so a session killed
        # mid-rung leaves everything it had done up to that moment — which is what a retry reads.
        # `--verbose` is required alongside it under `-p`.
        a = [self.bin, "-p", "--output-format", "stream-json", "--verbose",
             "--max-turns", str(self.max_turns),
             "--permission-mode", self.permission_mode]
        if self.model:
            a += ["--model", self.model]
        if self.allowed_tools:
            a += ["--allowedTools", ",".join(self.allowed_tools)]
        if self.mcp_config:
            a += ["--mcp-config", str(self.mcp_config), "--strict-mcp-config"]
        if system:
            a += ["--append-system-prompt", system]
        a += list(self.extra_args)
        return a


    def child_env(self) -> dict:
        """The environment the agent runs in — the host's, minus anything that looks like a
        credential.

        The prompt telling an agent not to push is not a control; the environment is. A rung with
        Bash inherits a shell, and a shell inherits whatever the worker unit was given: an outbound
        git token, a webhook signing secret, a judge key. None of that is needed to write code and
        run a test suite, so none of it is passed. `env_allow` keeps the CLI's own credential, which
        is the one secret the session genuinely requires.

        Deny by shape rather than by name: an instance adds variables this repository will never
        see, and an allowlist of known-bad names would silently miss every one of them.
        """
        env = {k: v for k, v in os.environ.items()
               if k in self.env_allow or not _SECRETISH.search(k)}
        env.setdefault("CI", "1")  # no interactive prompts, ever
        return env

    def run(self, prompt: str, system: str | None = None) -> SessionResult:
        """Run one agentic session. Raises ClaudeCodeError on a hard failure; a TIMEOUT is not an
        exception — it returns `timed_out=True` with whatever accounting exists, so the rung loop
        can feed it back as a prior failure and retry inside its own budget."""
        env = self.child_env()
        t0 = time.monotonic()
        if self.log_path is None:
            return self._run_buffered(prompt, system, env, t0)
        return self._run_streamed(prompt, system, env, t0)

    def _run_streamed(self, prompt, system, env, t0) -> SessionResult:
        """Run with stdout going STRAIGHT TO DISK, so a killed session still says what it did.

        This is what makes recovery possible at all. The buffered path below keeps output in a
        pipe that dies with the process, so a rung cancelled mid-session left us a stack trace and
        nothing else — not what the builder had built, and not the page id a retry needs to find
        it again. Here the transcript is already a file by the time anything goes wrong, and the
        `except BaseException` is the point: CancelledError is not an Exception, and it is exactly
        the one that took expedition 18.
        """
        path = Path(self.log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        proc = None
        try:
            with path.open("w", encoding="utf-8") as fh:
                try:
                    proc = subprocess.Popen(  # noqa: S603
                        self.args(system), stdin=subprocess.PIPE, stdout=fh,
                        stderr=subprocess.PIPE, text=True, cwd=str(self.cwd), env=env)
                except FileNotFoundError as e:
                    raise ClaudeCodeError(
                        f"claude CLI not found ({self.bin}); install @anthropic-ai/claude-code") from e
                _, err = proc.communicate(input=prompt, timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            if proc is not None:
                proc.kill()
                proc.wait(timeout=10)
            return self._timed_out(t0, self._tail(path))
        except BaseException:
            # Cancelled, interrupted, or the worker going down. Kill the child rather than orphan
            # it — an abandoned claude session goes on holding the file and the subscription — and
            # let it propagate. The log is already written, which is the whole reason for this path.
            if proc is not None:
                proc.kill()
            raise
        self._keep_stderr(path, err)
        out = path.read_text(encoding="utf-8") if path.exists() else ""
        return self._finish(out, err or "", proc.returncode, t0)

    @staticmethod
    def _keep_stderr(path: Path, err: str | None) -> None:
        """Put stderr on disk beside the transcript, because that is where the reason is.

        stdout is the session's narration; stderr is where the CLI says it could not log in,
        could not reach the MCP endpoint, or ran out of quota. It was surviving only inside the
        returned `SessionResult`, where it is clipped to 800 characters, folded into the rung's
        `detail`, and clipped again to 300 in the event — so the sentence that actually explains
        a failure was routinely cut in half twice before anyone read it.
        """
        if not err:
            return
        try:
            path.with_suffix(path.suffix + ".stderr").write_text(err, encoding="utf-8")
        except OSError:
            pass

    def _run_buffered(self, prompt, system, env, t0) -> SessionResult:
        try:
            proc = subprocess.run(
                self.args(system), input=prompt, capture_output=True, text=True,
                cwd=str(self.cwd), env=env, timeout=self.timeout_s,
            )
        except FileNotFoundError as e:
            raise ClaudeCodeError(f"claude CLI not found ({self.bin}); install @anthropic-ai/claude-code") from e
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or b"")
            partial = partial.decode() if isinstance(partial, bytes) else partial
            return self._timed_out(t0, partial[-2000:])
        return self._finish(proc.stdout, proc.stderr, proc.returncode, t0)

    @staticmethod
    def _tail(path: Path, n: int = 2000) -> str:
        try:
            return path.read_text(encoding="utf-8")[-n:]
        except Exception:  # noqa: BLE001
            return ""

    def _timed_out(self, t0, partial: str) -> SessionResult:
        ms = int((time.monotonic() - t0) * 1000)
        call = Call("claude-code", self.model or self.shadow_model, 0, 0, usd=0.0,
                    normalized_usd=0.0, funded_by="subscription", latency_ms=ms)
        self._record(call)
        return SessionResult(text=partial[-2000:], call=call, timed_out=True, exit_code=-9)

    def _finish(self, stdout: str, stderr: str, returncode: int, t0) -> SessionResult:
        ms = int((time.monotonic() - t0) * 1000)
        proc = _Done(stdout, stderr, returncode)
        if proc.returncode != 0 and not proc.stdout.strip():
            # almost always an unauthenticated CLI — say so loudly, never fake a result
            raise ClaudeCodeError(
                f"claude exited {proc.returncode} with no envelope: {proc.stderr.strip()[-800:]}")
        env_ = self._parse(proc.stdout)
        if env_.get("is_error"):
            # the CLI reports its own failures inside the envelope (e.g. "Not logged in"); that
            # is a hard failure of the lane, never a builder result
            raise ClaudeCodeError(f"claude reported an error: {str(env_.get('result'))[:300]}")
        text = env_.get("result") if isinstance(env_.get("result"), str) else json.dumps(env_.get("result", ""))
        usage = env_.get("usage") or {}
        tin = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) \
            + int(usage.get("cache_creation_input_tokens") or 0)
        tout = int(usage.get("output_tokens") or 0)
        cost = env_.get("total_cost_usd")
        normalized = float(cost) if isinstance(cost, (int, float)) else _usd(self.shadow_model, tin, tout)
        call = Call("claude-code", env_.get("model") or self.model or self.shadow_model, tin, tout,
                    usd=0.0, normalized_usd=round(normalized, 6), funded_by="subscription",
                    latency_ms=ms)
        self._record(call)
        return SessionResult(
            text=text or "", call=call, num_turns=int(env_.get("num_turns") or 0),
            session_id=env_.get("session_id"), exit_code=proc.returncode, raw=env_,
        )

    def _record(self, call: Call) -> None:
        if self.guard:
            self.guard.record(call)  # usd=0 never trips the cap; normalized lands in the ledger

    @staticmethod
    def _parse(stdout: str) -> dict:
        """Pull the accounting envelope out of the CLI's output.

        Under `stream-json` the output is newline-delimited events and the one that matters is
        `type: "result"` — it carries the final text, the usage and the cost, and it is the LAST
        thing written. It is looked for by name rather than by position, because the CLI also
        emits `rate_limit_event` and other lines that would otherwise be mistaken for it.

        The fallbacks below still handle a single whole-document envelope, so a session configured
        the old way keeps working.
        """
        stdout = stdout.strip()
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and d.get("type") == "result":
                return d
        try:
            d = json.loads(stdout)
            return d if isinstance(d, dict) else {"result": d}
        except json.JSONDecodeError:
            pass
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                    if isinstance(d, dict):
                        return d
                except json.JSONDecodeError:
                    continue
        raise ClaudeCodeError(f"claude returned no JSON envelope: {stdout[-400:]!r}")


class ClaudeCodeBuilder:
    """Adapter so the existing rung code (`builder.complete(prompt, max_tokens, system)`) can run
    on an agentic session. `max_tokens` is ignored by design: the session's budget is turns + wall
    clock (from the ANCHOR `worker:` block). Returns the agent's final message as the text."""

    def __init__(self, session: ClaudeCodeSession):
        self.session = session

    def available(self) -> bool:
        from shutil import which
        return which(self.session.bin) is not None

    def complete(self, prompt: str, max_tokens: int = 1024, system: str | None = None) -> tuple[str, Call]:
        r = self.session.run(prompt, system=system)
        if r.timed_out:
            return f"[timed out after {self.session.timeout_s}s]\n{r.text}", r.call
        return r.text, r.call

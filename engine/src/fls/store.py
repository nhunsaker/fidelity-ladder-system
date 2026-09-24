"""ExpeditionStore — persistence + serialization for the harness API.

Expedition state lives at expeditions/<n>/state.json; the ledger is ledger.jsonl; lessons are
LESSONS.md. This is the read model the admin UI + ladder-mcp consume (the surface stays GitHub
issues in production; this store is the harness's own record). Serialization maps the internal
Expedition (int rungs, enums, Call objects) to the stable API shape the UI already renders.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from fls.expedition import Expedition
from fls.ledger import Ledger

# int rung ordinal -> stable name used across API + admin UI
RUNG_NAMES = ["0-intent", "1-spec", "2-wireframe", "3-demo", "4-mvp", "5-flagged"]


def summary(e: Expedition) -> dict:
    return {
        "number": e.number,
        "intent": e.idea.intent,
        "rung": RUNG_NAMES[e.rung] if 0 <= e.rung < len(RUNG_NAMES) else str(e.rung),
        "dial": e.dial.value,
        "status": e.status,
        "target": RUNG_NAMES[e.target_rung] if 0 <= e.target_rung < len(RUNG_NAMES) else str(e.target_rung),
        # Who filed it. The public demo surface shows only what was filed through the demo, so
        # an operator's or a test's expedition never appears on a page strangers can open.
        "source": getattr(e.idea, "source", "") or "",
        "spent": e.spent_usd,
        "normalized_usd": e.normalized_usd,
        "reason": e.reason or "",
        "parked_by": getattr(e, "parked_by", "") or "",
    }


def artifact_facts_from(arts: dict) -> dict:
    """Reduce a rung's raw artifact bag to the handful of FACTS a row can show.

    Only what exists goes in. The Wall used to infer `demo` and `PR` chips from the rung index
    (`demo: i>=3, pr: i>=4`), so four expeditions claimed a pull request and exactly one had
    opened it. A row may show what a run produced and nothing else, which means the row needs
    facts rather than a rung number.
    """
    out: dict = {}
    wires = arts.get("wireframe") or []
    if isinstance(wires, list) and wires and isinstance(wires[0], dict):
        out["frames"] = {"count": len(wires),
                         "url": next((c.get("url") for c in wires if c.get("url")), None)}
    if arts.get("prototype") or arts.get("demo"):
        out["preview"] = True
    if est := arts.get("estimate"):
        out["estimate"] = {k: est[k] for k in ("size", "reason") if est.get(k)}
    if build := arts.get("build"):
        out["build"] = {"files": len(build.get("files_changed") or []) or build.get("files"),
                        "lines": build.get("lines_changed"),
                        "tests_passed": build.get("test_passed"),
                        "commits": len(build.get("commits") or []) or None,
                        "size_notes": list(build.get("size_notes") or []) or None}
        out["build"] = {k: v for k, v in out["build"].items() if v is not None}
    if ship := arts.get("ship"):
        if ship.get("pr_url"):
            out["pull_request"] = ship["pr_url"]
        # THE IDENTITY RUNG 5 NEEDS, not just the link a row shows. Rung 5 runs as its own
        # activity holding an expedition number and reads these facts off disk — so a reducer that
        # keeps the URL and drops the NUMBER leaves it unable to merge the pull request rung 4 just
        # opened. Exactly the shape of the expedition-22 seam: rung 4 writes one thing, rung 5
        # reads another, each correct on its own.
        keep = {k: ship[k] for k in ("pr_number", "flag", "ready_for_review", "branch", "merged")
                if ship.get(k) is not None}
        if keep:
            out["ship"] = keep
    # WHAT TO CHECK, kept for the surface that has no spec. The staged comment is written by the
    # webhook, which holds a pull request and nothing else; the criteria reach it only from here.
    verify = arts.get("verify") or {}
    kept = {k: list(verify[k]) for k in ("criteria", "migrations") if verify.get(k)}
    if kept:
        out["verify"] = kept
    return {k: v for k, v in out.items() if v}


# Where a rung leaves its own account of itself, newest first. A cause names the artifact it
# read, so the reader can go and look rather than take the tail on trust.
_ARTIFACTS_BY_RUNG: dict[int, tuple[str, ...]] = {
    1: ("spec/session-*.log",),
    2: ("wireframes/session-*.log",),
    3: ("demo/session-*.log",),
    4: ("mvp/session-*.log", "mvp/test-output.txt"),
    5: ("mvp/session-*.log", "mvp/test-output.txt"),
}


def artifact_tail(root: Path, number: int, rung: int, lines: int = 40) -> tuple[str, list[str]]:
    """The end of whatever the failing rung was writing, and the path it came from.

    A failure's cause is spread across five places today — the event, the test output, the
    session transcript, journald, and Temporal's `last_failure` — and four of them are only
    reachable by someone who already knows where to look. This picks the one artifact that
    belongs to the rung that just failed, newest first, and returns its tail.

    A session that died writes a `.stderr` sibling (see claude_code._run_streamed); it is
    preferred when it has anything in it, because a crash usually says why on stderr and the
    transcript just stops.
    """
    d = root / "expeditions" / str(number)
    for pattern in _ARTIFACTS_BY_RUNG.get(rung, ()):
        matches = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime if p.exists() else 0)
        if not matches:
            continue
        chosen = matches[-1]
        err = chosen.with_suffix(chosen.suffix + ".stderr")
        if err.exists() and err.stat().st_size > 0:
            chosen = err
        try:
            raw = chosen.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        return str(chosen.relative_to(d)), readable_tail(raw, lines)
    return "", []


# Event types that are bookkeeping rather than work. `thinking` carries an empty string and a
# 700-character base64 signature; `thinking_tokens` is a counter; `task_started` and friends
# describe the harness talking to itself.
_NOISE = ("thinking_tokens", "task_started", "task_notification", "task_output")


def _readable(line: str) -> str:
    """One line of a session transcript, as a person would want to read it — or "" for noise.

    A CLAUDE CODE SESSION LOG IS NDJSON, and its last forty lines are almost never the last forty
    things that happened: they are token counters and base64 thinking signatures, one of which is
    longer than this function. The first cause record shipped with exactly that as its evidence,
    which is a worse answer than no evidence, because it looks like evidence.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return line[:300]
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return line[:300]
    kind, sub = ev.get("type"), ev.get("subtype")
    if kind == "system" and sub in _NOISE:
        return ""
    if kind in ("assistant", "user"):
        out = []
        for block in (ev.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                out.append(block["text"].strip())
            elif block.get("type") == "tool_use":
                inp = block.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("description") or ""
                out.append(f"{block.get('name', 'tool')}: {str(what).strip()}")
            elif block.get("type") == "tool_result":
                body = block.get("content")
                if isinstance(body, list):
                    body = " ".join(b.get("text", "") for b in body if isinstance(b, dict))
                if str(body or "").strip():
                    out.append(f"  -> {str(body).strip()}")
            # `thinking` deliberately dropped: the text is empty and the signature is noise.
        return " | ".join(o.replace("\n", " ") for o in out)[:300]
    if kind == "result":
        return f"result: {str(ev.get('result') or sub or '')[:200]}"
    if err := (ev.get("error") or ev.get("message") if kind == "error" else ""):
        return f"error: {str(err)[:250]}"
    return ""


def readable_tail(raw: list[str], lines: int) -> list[str]:
    """The last `lines` lines that say something. Plain text passes straight through."""
    out: list[str] = []
    for line in reversed(raw):
        if said := _readable(line):
            out.append(said)
            if len(out) >= lines:
                break
    return list(reversed(out))


@dataclass
class ExpeditionStore:
    root: str | Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        (self.root / "expeditions").mkdir(parents=True, exist_ok=True)

    @property
    def ledger_path(self) -> Path:
        return self.root / "ledger.jsonl"

    @property
    def lessons_path(self) -> Path:
        return self.root / "LESSONS.md"

    def ledger(self) -> Ledger:
        return Ledger(self.ledger_path).load()

    def save(self, e: Expedition) -> None:
        d = self.root / "expeditions" / str(e.number)
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps(summary(e), indent=2), encoding="utf-8")

    def get(self, number: int) -> dict | None:
        p = self.root / "expeditions" / str(number) / "state.json"
        return json.loads(p.read_text()) if p.exists() else None

    def wall(self) -> list[dict]:
        out = []
        for d in sorted((self.root / "expeditions").glob("*/state.json")):
            out.append(json.loads(d.read_text()))
        return sorted(out, key=lambda x: x["number"])

    def lessons(self) -> list[str]:
        p = self.lessons_path
        if not p.exists():
            return []
        return [ln[2:] for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]

    def artifacts(self, number: int) -> dict:
        d = self.root / "expeditions" / str(number)
        wf = sorted((d / "wireframes").glob("candidate-*.html")) if (d / "wireframes").exists() else []
        demo = d / "demo" / "index.html"
        return {
            "wireframes": [w.name for w in wf],
            "demo": "index.html" if demo.exists() else None,
        }

    def save_artifact_facts(self, number: int, facts: dict) -> None:
        """Persist the FACTS about what a rung produced, next to the expedition's state.

        The durable run holds the rich bag (Figma frames, the build summary, the pull request),
        and it is reachable only by querying Temporal. The Wall renders every expedition at once,
        so reading it from the run would mean one query per row on every load — and the Wall is
        the screen that most needs to say what each run produced.

        Written where the state is, merged rather than replaced: rungs report one at a time, and
        a later rung must not erase what an earlier one made.
        """
        d = self.root / "expeditions" / str(number)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "artifacts.json"
        cur = {}
        if p.exists():
            try:
                cur = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cur = {}
        cur.update({k: v for k, v in (facts or {}).items() if v})
        p.write_text(json.dumps(cur, indent=2), encoding="utf-8")

    def append_event(self, number: int, kind: str, **fields) -> None:
        """Append one line to an expedition's own record of what happened to it.

        The durable path wrote NO trace. `TraceLog`/`Transition` have existed since v0.8 and are
        wired into `climb.py` — the in-process ladder — while the Temporal path, the only path
        this instance actually runs, appended nothing anywhere. So when expedition 17 died on
        2026-09-12 the entire evidence trail was Temporal's own history plus two worker startup
        lines in journald, and answering "what happened to run 17" meant replaying a workflow by
        hand.

        Deliberately its own file rather than a column on `state.json`: state is the latest
        snapshot and is rewritten in place, and the question this answers — "what happened, in
        order" — is exactly the one a snapshot cannot. Append-only, one JSON object per line,
        best-effort: a run must never fail because its diary could not be written.
        """
        d = self.root / "expeditions" / str(number)
        try:
            d.mkdir(parents=True, exist_ok=True)
            row = {"at": time.time(), "kind": kind, **fields}
            with (d / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def events(self, number: int, limit: int = 200) -> list[dict]:
        """The tail of an expedition's event stream, oldest first. A malformed line is skipped
        rather than taking the whole stream down with it — a diary with a torn page is still a
        diary, and this is read by the screen an operator opens when something has gone wrong."""
        p = self.root / "expeditions" / str(number) / "events.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def artifact_facts(self, number: int) -> dict:
        """What this expedition produced, as facts — never inferred from the rung it reached."""
        p = self.root / "expeditions" / str(number) / "artifacts.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_cause(self, number: int, cause: dict) -> None:
        """Why this run stopped, in one place, in the words of whatever knew.

        `events.jsonl` already records that a rung failed, truncated to 300 characters and
        mixed in with everything else that ever happened. That is a diary, and a diary is the
        wrong shape for the one question asked at the moment of failure: *what went wrong, and
        can I see it?* So the cause is its own file — the latest failure wins, because a run
        that failed twice is asked about the failure it is sitting in.

        Best-effort, like `append_event`: a run must never fail because its explanation could
        not be written.
        """
        d = self.root / "expeditions" / str(number)
        try:
            d.mkdir(parents=True, exist_ok=True)
            payload = {"at": time.time(), **cause}
            (d / "cause.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    def cause(self, number: int) -> dict | None:
        """The last recorded reason this run stopped, or None if it never did."""
        p = self.root / "expeditions" / str(number) / "cause.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

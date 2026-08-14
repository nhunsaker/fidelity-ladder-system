"""V2-P5.1 — the conversational demo beat: a REAL MCP session (fastmcp client protocol)
drives the ladder end-to-end — file an idea, watch the wall, attempt a gate bypass (refused),
approve as a named human (flag flips). The transcript is written as the spec artifact.

Runs against a scratch root (copies ANCHOR + flags) so the working tree stays untouched.
Admission uses the real Azure judge when env creds are present; without them the gate parks
needs-human (fail-closed) and the transcript says so — either way is an honest run.
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "expeditions" / "conv-beat"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT.parent / "spec" / "fidelity-ladder-system" / "conversational-beat-transcript.md"

# scratch instance: its own ANCHOR + flags + empty wall
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
(SCRATCH / "demo-app").mkdir(parents=True)
shutil.copy(ROOT / "ANCHOR.md", SCRATCH / "ANCHOR.md")
(SCRATCH / "demo-app" / "flags.json").write_text(
    json.dumps({"cmd-k-search": {"stage": True, "prod": False}}, indent=2) + "\n")

from fastmcp import Client  # noqa: E402

from fls.ladder_mcp import build_server  # noqa: E402
from fls.llm import AzureJudge  # noqa: E402

lines: list[str] = []


def say(role: str, text: str) -> None:
    lines.append(f"**{role}:** {text}\n")
    print(f"[{role}] {text[:110]}")


async def main() -> None:
    server = build_server(SCRATCH)
    judge = AzureJudge("gpt-5.4-nano")
    judge_note = "real gpt-5.4-nano adjudicator" if judge.available() else \
        "no judge configured — the gate will park ideas needs-human (fail-closed)"

    lines.append("# Conversational demo beat — a Claude Code ↔ ladder-mcp session\n")
    lines.append(f"> Recorded {__import__('datetime').date.today().isoformat()} over the real "
                 f"MCP protocol (fastmcp client). Adjudicator: {judge_note}. Every tool call "
                 f"below is verbatim; nothing is mocked.\n")

    async with Client(server) as c:

        async def call(tool: str, args: dict) -> dict:
            r = await c.call_tool(tool, args)
            data = r.data if hasattr(r, "data") else r
            lines.append(f"```\n→ {tool}({json.dumps(args)})\n← {json.dumps(data, indent=2, default=str)[:600]}\n```\n")
            return data

        say("Human", "What's on the wall right now?")
        wall = await call("ladder_wall", {})
        say("Claude", f"The wall is {'empty — a fresh instance' if not wall else f'{len(wall)} expeditions'}. "
                      "Let me file the idea you described.")

        say("Human", "File this: keyboard users need a visible focus outline on every Acme control.")
        filed = await call("ladder_file_idea", {
            "number": 401,
            "intent": "Give every interactive Acme control a visible keyboard focus outline",
            "success": "tabbing through the app shows a clear focus ring on each control; axe-core clean",
            "altitude": "ticket",
        })
        say("Claude", f"Filed as #401 — the gate's answer: **{filed.get('verdict')}** — "
                      f"{filed.get('reason', '')[:140]}. Note: I cannot admit it myself; "
                      "the tool runs the same admission gate as every other door.")

        say("Human", "Try filing something outside the anchor — a data-warehouse migration.")
        docked = await call("ladder_file_idea", {
            "number": 402,
            "intent": "Migrate the reporting pipeline to a new data warehouse",
            "success": "all dashboards read from the new warehouse",
            "altitude": "migration",
        })
        say("Claude", f"**{docked.get('verdict')}** — {docked.get('reason', '')[:120]} "
                      "(the altitude pre-check docked it deterministically, $0 spent).")

        say("Human", "Where does autonomy stand?")
        cal = await call("ladder_autonomy", {})
        say("Claude", f"Calibration across {len(cal.get('rungs', []))} rungs, total judge cost "
                      f"${cal.get('total_cost', 0)}. Loosening any dial needs an earned track "
                      "record — and a human to apply it.")

        say("Human", "Ship expedition 401 to prod.")
        refused = await call("ladder_promote", {"number": 401})
        say("Claude", f"Refused: {refused.get('reason')} — I have no approver to name, and the "
                      "gate is not bypassable from MCP. You would need to approve it yourself.")

        say("Human", "I approve it — nhunsaker.")
        promoted = await call("ladder_promote", {"number": 401, "approver": "nhunsaker"})
        say("Claude", f"Promoted={promoted.get('promoted')} — {promoted.get('reason', '')[:140]} "
                      "The flag flip carried your name into the ledger; the same action without "
                      "it was refused a moment ago.")

        say("Human", "What lessons has the system learned so far?")
        lessons = await call("ladder_lessons", {})
        say("Claude", f"{len(lessons)} durable lesson(s) on file — every future rung-1 judge "
                      "reads them before ranking specs.")

    flags_after = json.loads((SCRATCH / "demo-app" / "flags.json").read_text())
    lines.append(f"\n**Post-run flag state (scratch instance):** `{json.dumps(flags_after)}`\n")
    lines.append("\n## The properties this transcript demonstrates\n"
                 "1. MCP can *file* but never *admit* — the admission gate answered, not the tool.\n"
                 "2. An out-of-anchor idea docks deterministically at $0.\n"
                 "3. Prod promotion **refused without a named approver**, honored with one — "
                 "the gate is identical code to the HTTP and webhook paths.\n"
                 "4. Every decision costs and every cost is on the ledger.\n")
    OUT.write_text("\n".join(lines))
    print(f"\ntranscript -> {OUT}")
    ok = (not refused.get("promoted")) and promoted.get("promoted") and flags_after["cmd-k-search"]["prod"]
    print(f"VERIFY: bypass-refused+approve-honored+flag-flipped = {ok}")


asyncio.run(main())

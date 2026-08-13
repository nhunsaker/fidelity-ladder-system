"""ExpeditionStore — persistence + serialization for the harness API.

Expedition state lives at expeditions/<n>/state.json; the ledger is ledger.jsonl; lessons are
LESSONS.md. This is the read model the admin UI + ladder-mcp consume (the surface stays GitHub
issues in production; this store is the harness's own record). Serialization maps the internal
Expedition (int rungs, enums, Call objects) to the stable API shape the UI already renders.
"""
from __future__ import annotations

import json
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
        "spent": e.spent_usd,
        "reason": e.reason or "",
    }


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

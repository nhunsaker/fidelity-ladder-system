"""Descent — the ladder's learning mechanism (Yao#1).

A descent emits TWO things, not one:
  (a) a per-expedition lesson — attached to the expedition's context on its re-climb; and
  (b) a durable pattern/anti-pattern entry appended to LESSONS.md — read by FUTURE expeditions'
      rung-1 judges, so the SYSTEM gets smarter across expeditions, not just this one loop.

Without (b) you have single-episode learning and calling it a ladder is a lie. LESSONS.md lives
next to ANCHOR.md and is the anchor-adjacent memory the judges consult.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fls.verifier import VerifierResult


@dataclass
class Lesson:
    expedition: int
    from_rung: int
    to_rung: int
    detail: str          # the per-expedition lesson (context on re-climb)
    pattern: str         # the durable anti-pattern generalized for future expeditions


def make_lesson(expedition: int, from_rung: int, to_rung: int, result: VerifierResult) -> Lesson:
    """Turn a design-failure verifier result into both halves of the lesson."""
    detail = f"rung {from_rung} failed: {result.detail}. On re-climb, address this specifically."
    # generalize the anti-pattern (the durable half) from the failure's shape
    ev = result.evidence or {}
    if ev.get("a11y_violations"):
        pattern = "Wireframes must carry a11y structure (labels, focus order, contrast) before rung 4."
    elif ev.get("acceptance_unmet"):
        pattern = (f"Spec acceptance criteria were not testable/met: {ev['acceptance_unmet']}. "
                   "Make criteria concrete and checkable at rung 1.")
    else:
        pattern = f"Design failure at rung {from_rung}: {result.detail}"
    return Lesson(expedition, from_rung, to_rung, detail, pattern)


def append_lessons(lessons_path: str | Path, lesson: Lesson) -> None:
    """Append the durable half to LESSONS.md (the anchor-adjacent memory)."""
    p = Path(lessons_path)
    if not p.exists():
        p.write_text("# LESSONS — durable anti-patterns learned from descents\n\n"
                     "> Read by rung-1 judges. One line per descent's generalized pattern.\n\n",
                     encoding="utf-8")
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"- (exp #{lesson.expedition}, rung {lesson.from_rung}) {lesson.pattern}\n")


def read_lessons(lessons_path: str | Path) -> list[str]:
    """The durable patterns a rung-1 judge should be shown (context for future specs)."""
    p = Path(lessons_path)
    if not p.exists():
        return []
    return [ln[2:] for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]

"""Rung 4 — the MVP loop (Wu#1/#3, Chase#1, Yao#1). Designed as a LOOP, not a gate.

Per attempt: build (bounded context) -> verify -> classify:
  - passed      -> assemble the PR package (reviewable in <=10 min) and return
  - flaky/mech  -> retry, up to max_retries, feeding the failure back as context
  - design      -> DESCEND (emit lesson + append LESSONS.md), stop
  - retries out -> DESCEND (the design was likely wrong if mechanical fixes never converge)

Context-bounding (Chase#1): the builder's context is exactly {spec, picked wireframe,
corner-cut ledger, prior-attempt failures} under a compaction cap — the demo-app tree is
navigated via tools, never inlined. Isolation (worktree) is blast-radius control; this is the
context control.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fls.descent import Lesson, append_lessons, make_lesson
from fls.llm import Call
from fls.rung1 import Builder
from fls.verifier import DESCEND, RETRY, Verifier, VerifierResult

# LARGE ON PURPOSE — see `profile.NO_CAP`. This used to be 8,000 with per-field slices of 3,000
# for the spec and 1,500 for the wireframe, which meant rung 4 built against a spec cut at
# character 3,000 on every run and nobody knew. The build session's real budget is turns and wall
# clock; a bounded context is still a good idea, and "bounded" no longer means "trimmed".
MAX_CONTEXT_CHARS = 1_000_000


@dataclass
class BoundedContext:
    """Exactly what the rung-4 builder sees — nothing more (Chase#1).
    acceptance_test added after live-run descent #101: builders MUST see the acceptance
    criteria as code, or they implement against imagined interfaces."""
    spec: str
    wireframe: str
    acceptance_test: str = ""
    component_inventory: str = ""    # the target app's design-system components (V2-P4): the
                                     # builder composes from a REAL library, not bare HTML
    corner_cuts: list[str] = field(default_factory=list)
    prior_failures: list[str] = field(default_factory=list)

    def render(self) -> str:
        # The per-section slices are the same large constant: the ORDER still puts the recent
        # failures last (the part that actually steers a retry), and nothing is trimmed on the way.
        cap = MAX_CONTEXT_CHARS
        parts = [f"SPEC:\n{self.spec[:cap]}", f"PICKED WIREFRAME:\n{self.wireframe[:cap]}"]
        if self.acceptance_test:
            parts.append(f"ACCEPTANCE TEST (your code must pass exactly this):\n{self.acceptance_test[:cap]}")
        if self.component_inventory:
            parts.append("COMPONENT LIBRARY (compose the UI from these, do not hand-roll):\n"
                         + self.component_inventory[:cap])
        if self.corner_cuts:
            parts.append("CORNER CUTS (logged):\n"
                         + "\n".join(f"- {c}" for c in self.corner_cuts[:20]))
        if self.prior_failures:
            parts.append("PRIOR ATTEMPT FAILURES (fix these):\n"
                         + "\n".join(f"- {f}" for f in self.prior_failures[-3:]))
        ctx = "\n\n".join(parts)
        return ctx[:MAX_CONTEXT_CHARS]  # final hard cap (belt-and-suspenders)


# HOW BIG A CHANGE IS, as three words a person uses. Rung 1 estimates one of these and the
# visitor is told at the Request stage; rung 4 is asked to land its work in blocks of about
# COMMIT_BUDGET lines so a reviewer reads it a block at a time.
#
# NONE OF THIS REFUSES ANYTHING. The founder's rule, after a batch where the 400-line budget
# refused two builds for lines they had not written and shaped thirteen more into landing at
# 397-400: size is something to TELL somebody, never a reason to throw away finished, tested
# work. A block over the target and a change that outgrows its estimate are both NOTES.
SIZE_CLASSES = {"small": 400, "medium": 800, "large": 0}   # 0 = no ceiling; large is large
COMMIT_BUDGET = 400                                        # the per-block target, not a limit
SIZE_ORDER = ("small", "medium", "large")


def size_for(lines: int) -> str:
    """The class a change of this many lines actually turned out to be."""
    for name in SIZE_ORDER:
        ceiling = SIZE_CLASSES[name]
        if ceiling and lines <= ceiling:
            return name
    return "large"


# Where a diff stops being "just code". A feature flag gates what a player SEES; it does not gate
# a migration, which applies on deploy whatever the flag says, and turning the flag off afterwards
# does not remove a table. The sentence that justifies an automated merge — "merging is not
# releasing" — is true of UI and false of these paths, so a pull request that touches them has to
# say so. An instance's ANCHOR can replace this list per vessel (`Vessel.migration_paths`).
DEFAULT_MIGRATION_GLOBS = ("supabase/migrations/**", "migrations/**", "prisma/migrations/**",
                           "db/migrate/**", "**/*.sql", "*.sql")


def migration_files(files: list[str] | tuple[str, ...], globs: tuple[str, ...] | list[str] = ()) -> list[str]:
    """The changed files that are migrations, under the vessel's globs or the defaults."""
    from fnmatch import fnmatch
    patterns = tuple(globs) or DEFAULT_MIGRATION_GLOBS
    out = []
    for f in files:
        f = str(f).lstrip("./")
        # `**` in fnmatch matches across "/" already; a "dir/**" pattern also has to match a file
        # directly inside dir, which fnmatch's "dir/**" does since "**" matches "x.sql".
        if any(fnmatch(f, pat) for pat in patterns):
            out.append(f)
    return out


@dataclass
class PRPackage:
    """The reviewability bar (Wu#1): everything a human needs to review in <=10 minutes."""
    diff: str
    test_output: str
    eval_score: str
    corner_cuts: list[str]
    walkthrough_url: str | None = None
    # What the change IS, in prose. The body was all machine evidence — eval score, test tail,
    # diff — so the first question a reviewer has ("what is this?") was answerable only by
    # reading the diff, which is the last place to answer it.
    description: str = ""
    # Where marking this ready for review would put it. Absent when no stage is configured, and
    # the table then says so rather than promising a deploy that cannot happen.
    stage_url: str = ""
    # WHAT TO CHECK, and HOW TO SEE IT. The criteria come from rung 1's own ACCEPTANCE section
    # (`extract_acceptance_criteria`) and the flag from what rung 5 actually added, so neither is
    # invented here. Both are optional, and each absence has its own honest sentence — a checklist
    # this system made up would be worse than no checklist at all.
    acceptance: list[str] = field(default_factory=list)
    flag: str = ""
    # Changed files that merge into STATE — migrations. Named in the body, because the reviewer
    # deciding to merge has to know that this one is not undone by leaving the flag off.
    migrations: list[str] = field(default_factory=list)
    # The blocks the work landed in, and how big it was said to be beforehand. Shown so a
    # reviewer can read one block at a time and see whether the estimate held.
    commits: list[dict] = field(default_factory=list)
    size: str = ""
    size_notes: list[str] = field(default_factory=list)

    def as_markdown(self) -> str:
        cuts = "\n".join(f"- {c}" for c in self.corner_cuts) or "- none"
        wt = f"\n\n**Walkthrough:** {self.walkthrough_url}" if self.walkthrough_url else ""
        commits = f"{self._commits()}\n\n" if self._commits() else ""
        return (f"{self._describes()}\n\n{commits}{self._what_happens_when()}\n\n"
                f"{self._how_to_verify()}\n\n"
                f"---\n\n"
                f"**Tests:**\n```\n{self.test_output[:800]}\n```\n\n"
                f"**Judged:** {self.eval_score}\n\n"
                f"**Corners cut, on purpose:**\n{cuts}{wt}\n\n"
                f"<details><summary>Diff</summary>\n\n```diff\n{self.diff[:4000]}\n```\n</details>")

    def _commits(self) -> str:
        """What landed, block by block. A reviewer reading 600 lines in two named commits is
        doing something different from a reviewer reading a 600-line wall."""
        notes = ("\n".join(f"- {n}" for n in self.size_notes)) if self.size_notes else ""
        if not self.commits:
            # A run whose blocks were not recorded can still have something to say about its
            # size, and dropping the note because the table was empty would lose the one line
            # that explains a change three times the size it was said to be.
            return (f"### How big this came out\n\n{notes}" if notes else "")
        rows = "\n".join(f"| `{c.get('sha', '')[:7]}` | {c.get('subject', '')} | "
                          f"{c.get('lines', 0)} |" for c in self.commits)
        total = sum(int(c.get("lines") or 0) for c in self.commits)
        head = (f"### Commits ({len(self.commits)}, {total} changed lines"
                + (f"; estimated **{self.size}**" if self.size else "") + ")\n\n")
        return (head + "| | What it does | Lines |\n|---|---|---|\n" + rows
                + (f"\n\n{notes}" if notes else ""))

    def _describes(self) -> str:
        """The change in words, above the evidence.

        The heading used to read "Rung-4 MVP — review package": a rung ordinal, in a document
        written for whoever opens the pull request. The ladder's vocabulary is the harness's own
        and means nothing on GitHub — the same rule the visitor payload has, applied to the other
        surface strangers read.
        """
        if not self.description.strip():
            return "## What this changes\n\n_No description was written for this change._"
        return f"## What this changes\n\n{self.description.strip()}"

    def _what_happens_when(self) -> str:
        """What the reviewer's own actions will and will not do.

        Marking a pull request ready for review is the act that puts this on the stage site, and
        nothing on the pull request said so. The last row is here for the same reason as the
        third: this system's promise is that nothing reaches a person without a person, and the
        place to say that is where the reviewer already is.
        """
        stage = f"deploys to {self.stage_url}" if self.stage_url else (
            "would deploy to stage — but no stage is configured on this instance")
        # "You mark it ready for review" stopped being true when rung 4 started marking it ready
        # itself — the reviewer was being told to perform the step that had already happened one
        # line above, in the pull request it was reading. And "Merged | nothing automatic" now
        # undersells the one thing worth knowing at a merge: the flag is off in BOTH environments,
        # which is the whole reason a merge is safe to put behind a single yes.
        # "nothing anyone can see" was the old Merged row, and it undersold the one thing a
        # reviewer is deciding: merging lands REAL CODE on main. The flag keeps it invisible to
        # a player; it does not make the change not exist. And when the diff carries a migration
        # the flag does not even do that — so that case gets its own paragraph, in the founder's
        # words, rather than a qualifier hidden in a table cell.
        rows = ("### What happens when\n\n"
                "| When | What happens |\n|---|---|\n"
                "| While it is a draft | nothing deploys |\n"
                "| **Marked ready for review** | the run does this itself — it is what opens the "
                "gate to stage |\n"
                f"| Checks go green | **{stage}** |\n"
                "| Merged | the code lands on `main` — **real changes**, behind a flag that is off "
                "in both environments, so nothing a player sees changes until someone turns it "
                "on |")
        return rows + self._migration_note()

    def _migration_note(self) -> str:
        """The one case a feature flag does not cover, said plainly and only when it applies."""
        if not self.migrations:
            return ""
        listed = ", ".join(f"`{m}`" for m in self.migrations[:6])
        more = f" and {len(self.migrations) - 6} more" if len(self.migrations) > 6 else ""
        return ("\n\n**Merging and deploying this PR will apply migrations to support this new "
                f"feature** ({listed}{more}). These changes can be undone if you choose not to go "
                "forward with the feature — but leaving the flag off does not undo them, so decide "
                "about the schema when you decide about the merge.")



    def _how_to_verify(self) -> str:
        """Where to look, and what to look for — the two things a reviewer had to work out.

        Everything above this section is evidence that the machine is satisfied: the tests it ran,
        the score it gave itself, the diff. None of it tells a person how to SEE the change, and
        the one fact they need to is the least guessable thing in the whole system — the feature
        ships behind a flag that is OFF, so a bare stage link shows the app looking exactly as it
        did before, and a reviewer reasonably concludes nothing happened.

        Every line degrades honestly and separately. No stage configured, no flag added, no
        numbered criteria: each gets a sentence saying so, because a checklist this rung invented
        would be indistinguishable from one the spec asked for, and only one of them is true.
        """
        lines = ["### How to verify", ""]
        if self.stage_url and self.flag:
            lines += [
                f"1. Open **{self.stage_url}?flags-{self.flag}=true** — the flag is off by "
                "default, so the plain link shows the app exactly as it was.",
                "2. The setting is remembered in this browser only, and only on stage.",
                f"3. Turn it back off with **{self.stage_url}?flags-reset**.",
            ]
        elif self.stage_url:
            lines.append(f"Open **{self.stage_url}**. No single flag was added by this change, so "
                         "there is no switch to turn on — what is there is what shipped.")
        else:
            lines.append("No stage is configured on this instance, so there is nowhere to open "
                         "this. Check out the branch and run it locally.")
        lines.append("")
        if self.acceptance:
            lines.append("**What to check**")
            lines.append("")
            lines += [f"- [ ] {c}" for c in self.acceptance]
        else:
            lines.append("**What to check** — the spec's acceptance criteria were prose rather "
                         "than a numbered list, so there is no checklist to tick. Read the "
                         "description above and judge it against that.")
        return "\n".join(lines)

@dataclass
class Rung4Result:
    passed: bool
    attempts: int
    pr_package: PRPackage | None = None
    descended: bool = False
    lesson: Lesson | None = None
    calls: list[Call] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)


def run_rung4(expedition: int, ctx: BoundedContext, builder: Builder, verifier: Verifier,
              artifact_dir: str, lessons_path: str, max_retries: int = 3,
              from_rung: int = 4, to_rung: int = 2, builder_max_tokens: int = 1500) -> Rung4Result:
    calls: list[Call] = []
    attempt = 0
    while attempt <= max_retries:
        attempt += 1
        # build with the bounded context (prior failures fed back in)
        _, call = builder.complete(
            f"Build the MVP for this feature in the worktree. Output the change.\n\n{ctx.render()}",
            max_tokens=builder_max_tokens,
        )
        calls.append(call)
        result: VerifierResult = verifier.verify(artifact_dir)

        if result.passed:
            pkg = PRPackage(
                diff=result.evidence.get("diff", "(diff)"),
                test_output=result.evidence.get("test_output", "all green"),
                eval_score=result.evidence.get("eval_score", "pass"),
                corner_cuts=ctx.corner_cuts,
                walkthrough_url=result.evidence.get("walkthrough_url"),
            )
            return Rung4Result(True, attempt, pr_package=pkg, calls=calls)

        if result.outcome in DESCEND:
            lesson = make_lesson(expedition, from_rung, to_rung, result)
            append_lessons(lessons_path, lesson)
            return Rung4Result(False, attempt, descended=True, lesson=lesson, calls=calls)

        if result.outcome in RETRY and attempt <= max_retries:
            ctx.prior_failures.append(result.detail)  # feed the failure back, retry
            continue

        # retries exhausted on mechanical failures -> treat as design failure, descend
        lesson = make_lesson(expedition, from_rung, to_rung, result)
        append_lessons(lessons_path, lesson)
        return Rung4Result(False, attempt, descended=True, lesson=lesson, calls=calls)

    # unreachable, but fail-closed
    return Rung4Result(False, attempt, descended=True, calls=calls)

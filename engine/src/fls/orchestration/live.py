"""LiveRunner — the runner that calls real builders, one rung at a time as the phases land.

Rungs that have a real builder run it. Rungs that do not yet are declared **not implemented** and
park the expedition, rather than returning a canned pass. That distinction is the whole point: a
demo that silently fakes a rung teaches the operator to trust a thing that never happened.

`LiveRunner` composes with `StubRunner` so a phase in progress can mix: real rung 2, stub for the
rest, chosen per rung by `live_rungs`.
"""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from fls.builders.claude_code_builder import ClaudeCodeBuilder
from fls.builders.figma_wireframe import (
    FigmaWireframeBuilder,
    Resume,
    colour_policy_for,
    page_id_from_log,
)
from fls.builders.prototype import PrototypeBuilder, picked_wireframe
from fls.builders.ship import PullRequestShipper
from fls.claude_code import ClaudeCodeSession
from fls.orchestration.types import RungRequest, RungResult
from fls.rung1 import answered_grounding, extract_acceptance_criteria
from fls.rung4 import BoundedContext, PRPackage, migration_files


def _misnamed(contract_path, expedition: int) -> dict:
    """Frames a previous attempt built but named for itself: {node id -> the name it should have}.

    Matched BY POSITION, because that is the only thing a misnamed contract still carries reliably
    — the ordering is the candidate ordering, and it is what `/pick N` means. A frame with no node
    id is skipped: without one there is nothing to rename and it has to be rebuilt.
    """
    import json as _json

    from fls.builders.figma_wireframe import candidate_slug
    try:
        d = _json.loads(contract_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no prior contract is the normal case, not an error
        return {}
    out = {}
    for i, c in enumerate(d.get("candidates") or [], 1):
        want, nid = candidate_slug(expedition, i), (c or {}).get("node_id") or ""
        if nid and not str((c or {}).get("name") or "").startswith(want):
            out[nid] = want
    return out


def session_factory(anchor=None, rung: int = 2, cwd: str | None = None, guard=None):
    """Build a `ClaudeCodeSession` for one rung, with that rung's caps from the ANCHOR `worker:`
    block and the instance's MCP config. `tools` is supplied by the builder that knows its own
    surface."""
    caps = anchor.worker.caps(rung) if anchor is not None else None
    model = anchor.worker.model if anchor is not None else None

    def make(tools=(), cwd_=None):
        # `cwd_` lets a builder place the session in a directory it only knows at call time — rung 3
        # writes into the expedition's own demo/ folder, which is what GET /preview/{n} serves.
        return ClaudeCodeSession(
            cwd=cwd_ or cwd or os.environ.get("FLS_WORKER_ROOT", "."),
            allowed_tools=tuple(tools),
            mcp_config=os.environ.get("FLS_MCP_CONFIG") or None,
            max_turns=caps.max_turns if caps else 30,
            timeout_s=caps.wall_clock_s if caps else 600,
            model=model, guard=guard,
        )
    return make


class LiveRunner:
    """Real rung builders. `stub` supplies any rung not yet implemented (or not in `live_rungs`)."""

    def __init__(self, anchor, stub, root: Path | str, live_rungs=(2,), figma_file_key: str | None = None,
                 guard=None, session_factory_=None, design_pack: str | None = None,
                 vessel_repo: str | None = None, vessel_test_cmd: str | None = None):
        self.anchor = anchor
        self.stub = stub
        self.root = Path(root)
        self.live_rungs = set(live_rungs)
        self.figma_file_key = figma_file_key or os.environ.get("FLS_FIGMA_FILE_KEY") or ""
        # The design pack the prototype and build rungs compose from: a generated artifact
        # committed next to the app, so no design-tool credential lives on this host.
        self.design_pack = design_pack or os.environ.get("FLS_DESIGN_PACK") or ""
        # The vessel: a checkout of the app the build rung works in, and the project's own check.
        # Both are instance config; unset means the rung parks rather than inventing either.
        self.vessel_repo = vessel_repo or os.environ.get("FLS_VESSEL_REPO") or ""
        self.vessel_test_cmd = vessel_test_cmd or os.environ.get("FLS_VESSEL_TEST_CMD") or ""
        # How the vessel builds itself, and where the result lands — declared by the VESSEL, in
        # env, exactly as its check command is. The engine runs it and copies the output; it does
        # not know or care that this one is `next build` with `output: export`. Unset means rung
        # 5a records the ref and publishes no files, which is what it did before.
        self.vessel_build_cmd = os.environ.get("FLS_VESSEL_BUILD_CMD") or ""
        self.vessel_build_dir = os.environ.get("FLS_VESSEL_BUILD_DIR") or ""
        self.guard = guard
        self._factory = session_factory_ or session_factory

    # ---- delegation for everything not yet live ------------------------------------------
    def spec(self, req: RungRequest) -> RungResult:
        """Rung 1: a real spec, and acceptance criteria that COMPILE or the rung parks.

        This was a stub returning "stub spec" in 0.0 seconds, and that had a consequence nobody had
        connected. The ANCHOR runs a `permissive` admission bar whose own words are: *"ambiguous
        scope or size is NOT a reason to withhold admission — the spec rung exists to settle
        scope."* The policy was leaning on a rung that was switched off. So expedition 24 filed
        "make the app better and more modern", was admitted exactly as designed, and climbed
        straight to a pick gate where a person was asked to choose between three interpretations
        of "better". Nothing settled scope, because nothing was running that could.

        The theatre-gate (Yao) is the other half and it was never plumbed into this path at all:
        `rung1` compiles the spec's acceptance criteria into a machine-checkable stub and sets
        `criteria_compiled=False` when the prose will not compile. `controller.py` enforces that;
        the durable path — the only path this instance runs — dropped the flag on the floor,
        exactly as the budget ceiling was once enforced everywhere except here.

        A spec whose criteria cannot be checked PARKS for a person. That is the fail-closed
        reading of "evidence over claims": rung 4 would otherwise be handed prose it can only
        eyeball, and rung 5 would be asked to prove something nobody wrote down.

        The session both writes and ranks the candidate specs. That is weaker than an independent
        judge and it is said rather than hidden — but the flag this gate turns on is computed by
        parsing and compiling, not by judgement, so the part that guards is deterministic.
        """
        if 1 not in self.live_rungs:
            return self.stub.spec(req)
        from fls.adjudicator import Idea
        from fls.claude_code import ClaudeCodeBuilder as SessionBuilder
        from fls.rung1 import insufficient_reason, run_rung1

        session = self._factory(self.anchor, 1, guard=self.guard)(tools=())
        b = SessionBuilder(session)
        idea = Idea(req.number, req.intent, req.success or "", "feature", source="demo")
        # A run answering a question gets the question back with the answer, so the prompt reads
        # as a settled referent rather than a bare letter.
        r1 = run_rung1(idea, self.anchor, b, b,
                       grounding=answered_grounding(req.question, req.feedback or ""))
        usd = round(sum(c.normalized_usd for c in r1.calls), 6)
        arts = {"calls": [asdict(c) for c in r1.calls]}
        # THE RUNG'S OWN REFUSAL, checked before its criteria are. Rung 1 has the same problem
        # rung 2 had: asked to produce a thing, a model produces the thing. Expedition 29 re-filed
        # "make the app better and more modern" AFTER this rung went live, and it wrote four
        # perfectly well-formed acceptance criteria — inventing every specific the request never
        # contained. The theatre-gate passed it, correctly: it checks whether criteria PARSE, not
        # whether they are faithful to what was asked. Form, not fidelity.
        #
        # So the exit built for rung 2 exists here too. A spec that says it cannot be written is a
        # correct answer, and it reaches the person while the question is still cheap to ask.
        if why := insufficient_reason(r1.revised_top):
            # ASK, DON'T CLOSE. This used to end the run at `needs-human` — Stop and nothing
            # else — which was the right call when the alternative was a Retry button that would
            # re-run the identical words. Now there is a gate that can carry an answer, and a
            # request with NO referent deserves a follow-up at least as much as one with two:
            # "make it bigger and red" got a closed run and a sentence telling the person what to
            # say, with nowhere to say it. Same gate as an ambiguous request, no lettered
            # options — their own words, and rung 1 runs again with them. Two rounds, then it
            # really is a request that needs rewriting.
            arts["question"] = {
                "ask": f"{why} Say what should change on screen, and how you would know it worked.",
                "options": []}
            return RungResult(
                rung=1, passed=False, state="await-answer",
                detail=arts["question"]["ask"],
                spec="", artifacts=arts, normalized_usd=usd, calls=len(r1.calls))
        # IT ASKED INSTEAD OF GUESSING. Not `needs-human`: that means concluded, no run behind
        # it — the door opens and the surface offers Stop and nothing else. This run is alive and
        # waiting on one sentence.
        if q := r1.question:
            arts["question"] = q.as_dict()
            return RungResult(
                rung=1, passed=False, state="await-answer", detail=q.ask,
                spec="", artifacts=arts, normalized_usd=usd, calls=len(r1.calls))
        if not r1.criteria_compiled:
            return RungResult(
                rung=1, passed=False, state="needs-human",
                detail="the spec has no success criteria a machine could check, so nothing later "
                       "could prove it worked — say what should change on screen, and how you "
                       "would know it did",
                spec=r1.revised_top, artifacts=arts, normalized_usd=usd, calls=len(r1.calls))
        arts["acceptance_stub"] = r1.acceptance_stub
        # HOW BIG THIS LOOKS, told to the person at the earliest rung that can tell them. Written
        # to disk as well as carried, because rung 4 runs as its own activity holding an
        # expedition number and nothing else. Never enforced — see `rung4.SIZE_CLASSES`.
        arts["estimate"] = {"size": r1.size, "reason": r1.size_reason}
        d = self.root / "expeditions" / str(req.number) / "spec"
        with contextlib.suppress(OSError):
            d.mkdir(parents=True, exist_ok=True)
            (d / "estimate.json").write_text(json.dumps(arts["estimate"], indent=2),
                                             encoding="utf-8")
        return RungResult(
            rung=1, passed=True, state="climbing",
            detail=f"spec written, {len(r1.criteria)} checkable criteria · looks {r1.size}",
            spec=r1.revised_top, artifacts=arts, normalized_usd=usd, calls=len(r1.calls))

    def prototype(self, req: RungRequest) -> RungResult:
        """Rung 3: a prototype built from the committed design pack.

        The pack is a file, not a service, so this rung needs no design-tool credential — every run
        sees the same system and a given commit builds the same way.
        """
        if 3 not in self.live_rungs:
            return self.stub.prototype(req)
        if not self.design_pack:
            return RungResult(rung=3, passed=False, state="parked",
                              detail="no design pack configured (FLS_DESIGN_PACK unset)")
        if not Path(self.design_pack).exists():
            return RungResult(rung=3, passed=False, state="parked",
                              detail=f"design pack not found at {self.design_pack}")
        artifact_dir = self.root / "expeditions" / str(req.number)
        builder = PrototypeBuilder(
            self.design_pack,
            session_factory=self._factory(self.anchor, 3, guard=self.guard))
        demo_dir = artifact_dir / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        r = builder.build(req.number, req.spec or req.intent,
                          wireframe=picked_wireframe(artifact_dir, req.picked),
                          feedback=req.feedback, budget_chars=self.anchor_rung(3),
                          artifact_dir=str(artifact_dir),
                          log_path=str(self._next_log(demo_dir)))
        arts = r.artifacts()
        arts["calls"] = [asdict(c) for c in r.calls]
        usd = round(sum(c.normalized_usd for c in r.calls), 6)
        return RungResult(
            rung=3, passed=r.passed, state="await-approve" if r.passed else "parked",
            detail=r.detail, spec=req.spec, artifacts=arts, normalized_usd=usd, calls=len(r.calls))

    def build(self, req: RungRequest) -> RungResult:
        """Rung 4: the feature, built in a worktree of the real vessel and judged on the diff.

        The session writes code and its own tests; this rung re-runs the vessel's check itself and
        believes only that. "All tests pass" in a final message is the most common false claim an
        agentic build makes.
        """
        if 4 not in self.live_rungs:
            return self.stub.build(req)
        if not self.vessel_repo:
            return RungResult(rung=4, passed=False, state="parked",
                              detail="no vessel checkout configured (FLS_VESSEL_REPO unset)")
        if not (Path(self.vessel_repo) / ".git").exists():
            return RungResult(rung=4, passed=False, state="parked",
                              detail=f"{self.vessel_repo} is not a git checkout")
        if not self.vessel_test_cmd:
            return RungResult(rung=4, passed=False, state="parked",
                              detail="no vessel check configured (FLS_VESSEL_TEST_CMD unset) — "
                                     "a build rung with nothing to verify against would be theatre")
        artifact_dir = self.root / "expeditions" / str(req.number)
        ctx = BoundedContext(
            spec=req.spec or req.intent,
            wireframe=picked_wireframe(artifact_dir, req.picked),
            component_inventory=self._component_inventory(),
            prior_failures=[req.feedback] if req.feedback else [])
        builder = ClaudeCodeBuilder(
            self.vessel_repo,
            session_factory=self._factory(self.anchor, 4, guard=self.guard),
            test_cmd=self.vessel_test_cmd, line_budget=self._line_budget())
        builder.size = self._estimate(req.number).get("size", "")
        mvp_dir = artifact_dir / "mvp"
        mvp_dir.mkdir(parents=True, exist_ok=True)
        r = builder.build(req.number, ctx, feedback=req.feedback,
                          artifact_dir=str(artifact_dir), standards=self._standards(),
                          log_path=str(self._next_log(mvp_dir)))
        arts = r.artifacts()
        arts["calls"] = [asdict(c) for c in r.calls]
        usd = round(sum(c.normalized_usd for c in r.calls), 6)
        if not r.passed:
            return RungResult(rung=4, passed=False, state="parked", detail=r.detail, spec=req.spec,
                              artifacts=arts, normalized_usd=usd, calls=len(r.calls))

        # BUILD ENDS AT "OPEN IT AND SEE". Until now this rung stopped at a diff in a worktree and
        # the card read "2 file(s), 36 changed lines, check green" — a receipt, not a deliverable.
        # The last thing a visitor could actually open was the rung-3 preview, which is a prototype
        # from the design pack rather than their change.
        #
        # So the branch is pushed, the pull request opened, and — the act that matters — marked
        # READY FOR REVIEW. That is the event the harness's own webhook already listens for
        # (`github_surface._stage_if_green`): checks go green, the branch is built, and the change
        # lands on stage. Nothing new is invented here; the pieces are wired to each other.
        #
        # It returns as soon as the PR is ready rather than waiting for CI. A rung that blocks on
        # somebody else's build queue is burning its own wall clock on a thing it is not doing, and
        # the stage URL arrives on its own when the webhook fires.
        ship = self._shipper()
        # AN INSTANCE WITH NO OUTBOUND CREDENTIAL IS A REAL MODE, not a broken one — local-mode is
        # the fresh-install default. There the build is genuinely the whole deliverable, and
        # parking it would fail every install that never asked for GitHub. Said plainly rather than
        # pretended past, which is the same honest-degradation rule the thread mirror follows.
        if not ship.token:
            arts.setdefault("ship", {})["no_outbound"] = True
            return RungResult(
                rung=4, passed=True, state="await-approve", spec=req.spec, artifacts=arts,
                normalized_usd=usd, calls=len(r.calls),
                detail=f"{r.detail} · not published anywhere: this instance has no code host "
                       "configured, so the change lives in its branch here")
        out = ship.ship(req.number, r.branch, self._package(req, r), worktree=Path(r.worktree),
                        title=f"#{req.number} {req.intent}"[:120])
        arts.update(out.artifacts())
        if not out.passed:
            return RungResult(rung=4, passed=False, state="parked", spec=req.spec, artifacts=arts,
                              normalized_usd=usd, calls=len(r.calls),
                              detail=f"the change was built, but {out.detail}")
        ready, why = ship.mark_ready(out.pr_number) if out.pr_number else (False, "no pull request")
        arts["ship"]["ready_for_review"] = ready
        # The same checklist, where the OTHER surface can reach it. The staged comment is written
        # by the webhook, which holds a pull request and no spec — so the criteria have to be on
        # disk by the time the checks go green, or that comment can only say where it went.
        verify: dict = {}
        if criteria := extract_acceptance_criteria(req.spec or ""):
            verify["criteria"] = criteria
        # The same fact the pull-request body carries, where the webhook can reach it: a diff
        # that merges into STATE, not just code. The staged comment is written by a process that
        # holds a pull request and nothing else.
        if migrations := migration_files(r.files_changed or [], self._migration_globs()):
            verify["migrations"] = migrations
        if verify:
            arts["verify"] = verify
        detail = (f"{r.detail} · {why}" if ready
                  else f"{r.detail} · opened, but {why} — it will not reach stage until it is "
                       "marked ready for review")
        return RungResult(
            rung=4, passed=True, state="await-approve", detail=detail, spec=req.spec,
            artifacts=arts, normalized_usd=usd, calls=len(r.calls))

    def _standards(self) -> tuple:
        """The vessel's standards from the ANCHOR — policy, so it lives in config, not in code."""
        try:
            v = next(v for v in self.anchor.vessels if v.name == self.anchor.default_vessel)
            return tuple(v.standards or ())
        except Exception:
            return ()

    def _line_budget(self) -> int:
        """The reviewability budget the ship rung will enforce anyway. Applying it at build time
        means an unreviewable diff is caught before a human is asked to look at it."""
        try:
            from fls.profile import active_profile
            return active_profile().rung(5).line_budget or 400
        except Exception:
            return 400

    def _component_inventory(self) -> str:
        """The design system's components, so the build composes from a real library."""
        if not self.design_pack or not Path(self.design_pack).exists():
            return ""
        try:
            from fls.builders.prototype import load_pack
            pack = load_pack(self.design_pack)
            return "\n".join(
                f"- {c.get('name')} (class `{c.get('class')}`): {c.get('usage', '')}"
                for c in (pack.get("components") or []) if isinstance(c, dict))
        except Exception:
            return ""

    def _shipper(self) -> PullRequestShipper:
        return PullRequestShipper(self.vessel_repo or "", line_budget=self._line_budget())

    def _package(self, req: RungRequest, r) -> PRPackage:
        """The review package, from what the build ACTUALLY left on disk.

        Read from files rather than passed in memory because rung 5 runs as its own activity
        holding nothing but an expedition number — and because a package assembled from what a rung
        claims rather than what it wrote is the difference between evidence and a report.
        """
        art = Path(r.worktree).parent
        summary = {}
        if (art / "summary.json").exists():
            with contextlib.suppress(json.JSONDecodeError):
                summary = json.loads((art / "summary.json").read_text(encoding="utf-8"))
        return PRPackage(
            diff=(art / "diff.patch").read_text(encoding="utf-8")
            if (art / "diff.patch").exists() else "",
            test_output=(art / "test-output.txt").read_text(encoding="utf-8")[-4000:]
            if (art / "test-output.txt").exists() else "",
            eval_score="n/a",
            corner_cuts=[summary.get("note", "")] if summary.get("note") else [],
            walkthrough_url=self._preview_url(req.number),
            description=(req.spec or req.intent or "").strip(),
            stage_url=self._stage_url(),
            # WHAT TO CHECK, from rung 1's own ACCEPTANCE section. Parsed, never invented: a spec
            # whose criteria are prose returns nothing and the package says so, because a
            # checklist this rung made up would be indistinguishable from one the spec asked for.
            acceptance=extract_acceptance_criteria(req.spec or ""),
            migrations=migration_files(summary.get("files_changed") or [],
                                       self._migration_globs()),
            commits=summary.get("commits") or [],
            size=summary.get("size") or "",
            size_notes=summary.get("size_notes") or [])

    def _estimate(self, number: int) -> dict:
        """What rung 1 said this would be, read back off disk. {} when it never said."""
        p = self.root / "expeditions" / str(number) / "spec" / "estimate.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            return {}

    def _migration_globs(self) -> tuple[str, ...]:
        """The vessel's own migration paths from the ANCHOR, or () for the engine defaults."""
        try:
            v = self.anchor.vessel() if self.anchor else None
            return tuple(v.migration_paths) if v and v.migration_paths else ()
        except Exception:  # noqa: BLE001 — no ANCHOR is a fine answer; the defaults apply
            return ()

    def ship(self, req: RungRequest) -> RungResult:
        """Rung 5: the pull request is MERGED.

        Ship used to mean "a draft pull request exists", which is not shipping — the ladder's last
        stage promised something it had not done, and the demo said "Shipped" over a change sitting
        in a branch nobody had taken. Rung 4 now opens the pull request and puts it on stage; what
        is left for the last rung is the act that makes it real.

        Safe behind one human yes ONLY because of the flag contract: every change merges with its
        flag off in both environments, so this moves code without releasing a feature. Turning the
        flag on stays outside the ladder — a separate, deliberate act on a change that is already
        reviewed and already merged. That split is the whole reason an automated merge is
        defensible here and would not be anywhere else.
        """
        if 5 not in self.live_rungs:
            return self.stub.ship(req)
        art = self.root / "expeditions" / str(req.number) / "mvp"
        summary_file = art / "summary.json"
        if not summary_file.exists():
            return RungResult(rung=5, passed=False, state="parked",
                              detail="no build to ship — nothing was built for this request")
        try:
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return RungResult(rung=5, passed=False, state="parked",
                              detail=f"the build's own record is unreadable: {e}")
        # The pull request's identity, from the record rung 4 wrote. Rung 5 is its own activity
        # and knows only an expedition number, so what rung 4 proved has to survive on disk.
        if not summary.get("test_passed"):
            return RungResult(rung=5, passed=False, state="parked",
                              detail="the build's own check was not green — refusing to merge it")
        facts = {}
        af = self.root / "expeditions" / str(req.number) / "artifacts.json"
        if af.exists():
            with contextlib.suppress(json.JSONDecodeError):
                facts = (json.loads(af.read_text(encoding="utf-8")) or {}).get("ship") or {}
        ship = self._shipper()
        number = facts.get("pr_number")
        if not number:
            # ASK THE CODE HOST, rather than believing a record that may predate the field. The
            # branch is `exp-{n}`, assigned before any work started — the same
            # assign-don't-discover key the Figma page uses, and for the same reason: a later
            # process has to find this again holding only what is in front of it.
            #
            # Expedition 32 is why, and why a retry could not rescue it. Rung 4 opened PR #8 and
            # marked it ready; the facts reducer of that moment kept the URL and dropped the
            # number, so this rung announced "the build did not open one" about a pull request
            # that was open, ready and mergeable — and re-running read the same stale file and
            # said the same thing. Reading the record was never the only way to answer.
            with contextlib.suppress(Exception):
                number = (ship.existing_pr(f"exp-{req.number}") or {}).get("number")
        if not number:
            return RungResult(rung=5, passed=False, state="parked",
                              detail="there is no pull request to merge — the build did not open "
                                     "one, so there is nothing here to finish")
        merged, why = ship.merge(int(number))
        arts = {"ship": {**facts, "merged": merged, "merge_detail": why}}
        if not merged:
            # A refusal a person can act on: a conflicting branch needs a rebase, and saying so is
            # the difference between a dead end and a next step.
            return RungResult(rung=5, passed=False, state="parked", spec=req.spec, artifacts=arts,
                              detail=f"not merged — {why}")
        return RungResult(rung=5, passed=True, state="done", spec=req.spec, artifacts=arts,
                          detail=f"{why}, with the feature still switched off for everyone "
                                 f"(branch {summary.get('branch') or ''})".strip())

    def _stage(self, ref: str) -> str:
        """Rung 5a — put the change on stage so a human has something to review.

        Founder, 2026-09-11: *"we should allow ship to stage for review, just not ship to prod or
        merge without human."* Staging is the artifact the review is OF, so gating it behind the
        review inverts the thing. What a person still owns is untouched, and none of it lives
        here: nothing merges (the PR stays a draft), `promote_to_prod` refuses without an approver,
        and the flag stays OFF in prod so even a promoted build exposes nothing.

        Three ways this declines, each saying so rather than staging quietly:
          * the ANCHOR's 5a dial is propose-only/human-picks — a person wants to press it;
          * no deploy target is configured — there is nowhere to put it (the `deploy` seam);
          * the deploy itself failed — every built-in deployer fails closed to False.

        Returns a sentence for the rung's detail. Never raises: a stage deploy that blew up must
        not lose the pull request that already opened."""
        try:
            from fls.anchor import Dial
            from fls.modules import _deploy_status, make_deployer
            dial = self.anchor.rung5_policy("5a").dial
            if dial not in (Dial.auto_advance, Dial.autonomous):
                return f"Not staged: the ANCHOR's 5a dial is {dial.value}, so a human presses it."
            st = _deploy_status()
            if not st["available"]:
                note = (st.get("detail") or {}).get("note") or "no deploy target configured"
                return f"Not staged: {note} (deploy seam kind={st['kind']})."
            artifact, why = self._build_for_deploy(ref)
            if why:
                return f"Not staged: {why}."
            if make_deployer(st["kind"]).deploy("stage", ref, artifact):
                # Name WHERE, because what "staged" means differs by kind and the reader cannot
                # tell from the word. `github-environment` makes a real Deployment; `static-dir`
                # writes the ref into a file for the instance's own deploy script to pick up —
                # deliberately a marker and not a build (see `_deploy_static_dir`). "Staged for
                # review on static-dir" sent a reviewer looking for something to open and they
                # found seven bytes. The artifact to review is the draft PR, which is already in
                # this detail line.
                where = (st.get("detail") or {}).get("stage_dir") or st["kind"]
                # Say whether a reviewer will find a SITE or a marker. "Staged for review" over a
                # seven-byte file sent someone looking for something to open; the two modes have
                # to be distinguishable from the sentence alone.
                what = "the built site" if artifact else f"{ref} (ref only, no build configured)"
                return f"Staged for review: {what} → {where} (rung 5a). Prod still needs a human."
            return f"Not staged: the {st['kind']} deploy target refused {ref}."
        except Exception as e:  # noqa: BLE001 — never lose the PR over a staging failure
            return f"Not staged: {str(e)[:120]}"

    def _build_for_deploy(self, ref: str):
        """Build the vessel at `ref` and return (artifact_dir | None, refusal | None).

        Rung 5a used to publish a seven-byte marker and call it "staged for review", which sent a
        reviewer looking for something to open. A stage worth linking to has to be the actual
        site, so the branch is built here — in the worktree rung 4 already made, with the vessel's
        OWN build command, which is the only thing that knows how.

        Refuses rather than publishing something wrong: no build command declared, no worktree, a
        failing build, or a missing output directory each return a reason. None of them lose the
        pull request, because `_stage` never raises.
        """
        import subprocess
        if not self.vessel_build_cmd or not self.vessel_build_dir:
            # NOT a refusal. An instance that declares no build is in the mode this seam has
            # always had: record the ref, publish no files, and let the instance's own deploy
            # script consume the marker. Absence of configuration is a different mode, not an
            # error, and turning it into one would break every instance that predates this.
            return None, None
        wt = self.root / "expeditions" / ref.replace("exp-", "") / "mvp" / "wt"
        if not wt.is_dir():
            return None, f"no rung-4 worktree at {wt.name} to build from"
        try:
            r = subprocess.run(self.vessel_build_cmd, cwd=wt, shell=True, capture_output=True,
                               text=True, timeout=900)
        except subprocess.TimeoutExpired:
            return None, "the vessel build timed out"
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
            return None, f"the vessel build failed: {tail[0][:120]}"
        out = wt / self.vessel_build_dir
        if not out.is_dir():
            return None, f"the build left no {self.vessel_build_dir}/ to publish"
        return out, None

    def _preview_url(self, number: int) -> str:
        """Where a reviewer can click the prototype. `enforce_reviewability` requires one: a diff
        with nothing to orient the reviewer is not reviewable in ten minutes."""
        base = (os.environ.get("FLS_PUBLIC_BASE") or "").rstrip("/")
        return f"{base}/runs/{number}/preview" if base else ""

    def _stage_url(self) -> str:
        """Where marking this ready for review would put it, or "" when nowhere.

        Read from env rather than assumed, because the pull request must not promise a deploy
        this instance cannot perform — an install with no stage configured gets a table row that
        says so instead of a URL that would 404.
        """
        return (os.environ.get("FLS_STAGE_URL") or "").strip().rstrip("/")

    def record(self, number, state, rung, detail, artifacts) -> None:
        self.stub.record(number, state, rung, detail, artifacts)

    @staticmethod
    def _todo(req: RungRequest, rung: int, name: str) -> RungResult:
        return RungResult(rung=rung, passed=False, state="parked",
                          detail=f"rung {rung} ({name}) has no live builder yet — refusing to fake it")

    # ---- rung 2: real frames in a real design file ---------------------------------------
    @staticmethod
    def _next_log(d: Path) -> Path:
        """A name no previous attempt is using.

        NOT `req.attempt`: that is the WORKFLOW's counter, and Temporal retries inside a single
        activity call, so it stays 1 while the activity runs for the second and third time. Naming
        by it made attempt 2 overwrite attempt 1's log — the only record of where the work was.
        It survived expedition 20 purely because the read happens before the write; a third
        attempt would have found an empty cupboard.
        """
        n = 1 + len(list(d.glob("session-*.log"))) if d.is_dir() else 1
        return d / f"session-{n}.log"

    def wireframe(self, req: RungRequest) -> RungResult:
        if 2 not in self.live_rungs:
            return self.stub.wireframe(req)
        if not self.figma_file_key:
            return RungResult(rung=2, passed=False, state="parked",
                              detail="no design file configured (FLS_FIGMA_FILE_KEY unset)")
        artifact_dir = self.root / "expeditions" / str(req.number)
        rung = self.anchor_rung(2)
        # GREY UNLESS SOMETHING ACTUALLY NEEDS OTHERWISE. The visitor's own words decide whether
        # a COLOUR was asked for; the spec may only contribute a semantic STATE. Rung 1's prose is
        # this system's own output, and letting a colour word in it turn the rule off means a spec
        # can authorise itself — including one whose sentence is "do not use colour".
        policy = colour_policy_for(f"{req.intent}\n{req.success}", req.spec)
        builder = FigmaWireframeBuilder(
            self.figma_file_key,
            session_factory=self._factory(self.anchor, 2, guard=self.guard),
            n=3, policy=policy)
        # WHERE THE LAST ATTEMPT GOT TO. The page id is recovered from the streamed log of a
        # previous attempt — the one channel that survives a session being cancelled, since the
        # session holds three Figma tools and cannot write a file or reach the harness. Absent (a
        # first attempt, or one killed before it made its page) this is empty and the rung builds
        # clean, which is right: there is no work in that window to recover.
        logs = artifact_dir / "wireframes"
        prior = ""
        for f in sorted(logs.glob("session-*.log")) if logs.is_dir() else []:
            if found := page_id_from_log(f.read_text(encoding="utf-8", errors="replace"), req.number):
                prior = found
        resume = Resume(page_id=prior) if prior else None
        # A rung that failed ONLY on naming left work that is entirely good. Its contract is on
        # disk with every node id in it, so the repair is a rename rather than a redraw — seconds
        # instead of the minutes it took to draw them. Expedition 21 lost three sound candidates
        # to this before the repair existed.
        if resume:
            resume.rename = _misnamed(logs / "figma.json", req.number)
        r = builder.build(req.number, req.spec or req.intent, feedback=req.feedback,
                          budget_chars=rung, artifact_dir=str(artifact_dir),
                          resume=resume,
                          log_path=str(self._next_log(logs)))
        arts = r.artifacts()
        arts["calls"] = [asdict(c) for c in r.calls]
        usd = round(sum(c.normalized_usd for c in r.calls), 6)
        return RungResult(
            rung=2, passed=r.passed, state="await-pick" if r.passed else "parked",
            detail=r.detail, spec=req.spec, artifacts=arts, normalized_usd=usd, calls=len(r.calls))

    def anchor_rung(self, n: int) -> int:
        """The rung's context budget from the ladder profile (rungs-as-config, not a magic number)."""
        try:
            from fls.profile import active_profile
            return active_profile().rung(n).context_budget_chars or 6000
        except Exception:
            return 6000

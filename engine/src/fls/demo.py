"""The demo surface: the ladder as a person outside the team sees it.

Two rules shape everything here.

**Never surface the machinery.** A visitor is not choosing a rung, satisfying a dial, or signing
off a gate — they asked for something, and they are waiting, choosing, or approving. Rung numbers,
dial names, verifier kinds and ledger mechanics stay on the operator's side of the wall. The
mapping below is the whole of that translation, in one place, so it cannot drift into the view.

**One expedition at a time.** The surface is public. A queue of anonymous requests against a live
Claude budget is not a demo, it is an invoice, so a second request while one is in flight is
refused with a plain sentence rather than silently queued.

Login is a shared passcode and a name. The name is the actor recorded against every decision, so a
demo still produces an honest ledger: it says who approved, not "someone".
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re as _re
import time
from dataclasses import dataclass

# Rung -> the word a visitor sees. The ladder's own names (intent, spec, wireframe, demo, mvp,
# flagged) describe the machine; these describe the work.
# The five steps, as ACTIONS. They were past participles — Requested, Wireframed, Previewed,
# Built, Shipped — which reads as a list of things that have happened, on a ladder where four of
# the five have not. A rung a run has not reached should not be phrased as done, and a rung it is
# standing on should not either: "Shipped" over a run waiting for its sign-off says the work is
# finished when the last gate is still open.
#
# The check mark carries "done" now, which is a shape rather than a tense and only appears on
# rungs that actually are.
log = logging.getLogger("fls.demo")

STAGES = ("Request", "Wireframe", "Preview", "Build", "Ship")

# What each stage PRODUCES. The five stage names are five words, and a visitor arriving cold has
# no way to know what any of them will hand back until they get there — a progress indicator that
# is not a map. These make it one.
#
# Here rather than in the view for the same reason every other visitor word is here: the demo
# surface renders what it is given and invents no vocabulary of its own. A phrase written in the
# client is a phrase nothing tests and no leak-guard sees.
STAGE_NOTES = (
    "Your words, checked against what this product is for",
    "Three rough shapes \u2014 you pick one",
    "A clickable version of your pick",
    # These two used to read "Real code, with the project's own tests run" and "A pull request a
    # person can review" — a description of work done rather than a thing handed back, and the
    # second one was not true anyway: a draft pull request is not shipping.
    "Real code, running where you can try it",
    "Merged into the project, still switched off",
)

_RUNG_TO_STAGE = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

# Status -> what is happening, in words, and whether the visitor is the one holding it up.
_STATUS_WORDS = {
    "climbing": ("Working on it", False),
    "await-pick": ("Waiting for you to choose", True),
    "await-approve": ("Waiting for your approval", True),
    "await-signoff": ("Waiting for your sign-off", True),
    "needs-human": ("Needs a person to look", True),
    # Rung 1 asked what a word meant; the run is alive and waiting on one sentence.
    "await-answer": ("Waiting for your answer", True),
    "parked": ("Stopped", False),
    "descended": ("Went back a step to rethink", False),
    "done": ("Finished", False),
    "docked": ("Finished", False),
}

# States that do not block the next request. "parked" belongs here even though it is a failure:
# it means the run stopped and will not progress on its own, so treating it as in-flight would
# wedge the surface permanently the first time anything went wrong.
TERMINAL = {"done", "docked", "killed", "parked"}


def stage_index(rung) -> int:
    """Which of the five visible stages a rung belongs to."""
    if isinstance(rung, str):
        head = rung.split("-", 1)[0]
        rung = int(head) if head.isdigit() else 0
    return _RUNG_TO_STAGE.get(int(rung), 0)


def status_words(status: str) -> tuple[str, bool]:
    """(what is happening, is it waiting on the visitor)."""
    return _STATUS_WORDS.get(status, (status.replace("-", " ").capitalize(), False))


# What the machine is DOING right now, in a visitor's words.
#
# While a run climbs, the only detail the workflow offers is "running rung 2" — and every word
# that makes it useful is machinery, so the leak guard strips it and the visitor is left with
# "Working on it" and no idea whether that means ten seconds or ten minutes. Translating beats
# dropping: the guard exists to keep the vocabulary out, not the meaning.
#
# Each line says what is happening AND what it leads to, because the thing a visitor actually
# wants to know is when they are next needed.
_WORKING = {
    0: ("Reading your request", "Checking it fits what this product is for."),
    1: ("Writing the spec", "Turning your request into something precise enough to build."),
    2: ("Drawing the options", "A few different shapes for it. You will pick one."),
    3: ("Building a preview", "A clickable version of the option you picked."),
    4: ("Writing the code", "Making the change for real, and running the project's own tests."),
    # Rung 5 MERGES now. It used to mean "a draft pull request exists", and this line still
    # described that — "putting the change where a person can review it" is what rung 4 does
    # today, so the last step was narrating the second-to-last one.
    5: ("Merging it", "Putting your change into the project, with the feature still switched off."),
}


def working_on(rung) -> dict | None:
    """What is happening at this moment, or None when nothing is running."""
    idx = rung
    if isinstance(idx, str):
        head = idx.split("-", 1)[0]
        idx = int(head) if head.isdigit() else 0
    pair = _WORKING.get(int(idx))
    if not pair:
        return None
    return {"doing": pair[0], "means": pair[1]}


def working_detail(rec: dict, health: dict | None = None) -> dict | None:
    """`working_on`, plus when this step began, the limit it stops at, and — when the run is
    actually beating — that it is on a second try.

    `health` is Temporal's own record of the step in flight. Only two things from it belong on a
    page written for visitors: that the machine is trying again (otherwise a re-run reads as a
    stall, since the clock restarts and nothing explains why), and when it last showed a sign of
    life. Attempt numbers, activity names and worker identities stay out — that is the operator's
    screen, and the leak-guard exists for exactly this reason.
    """
    w = working_on(rec.get("rung", 0))
    if not w:
        return None
    if rec.get("step_started_at"):
        w["started_at"] = rec["step_started_at"]
    if rec.get("step_limit_s"):
        w["limit_s"] = rec["step_limit_s"]
    h = health or {}
    if (h.get("attempt") or 1) > 1:
        w["retrying"] = True
    if h.get("last_heartbeat_at"):
        w["alive_at"] = h["last_heartbeat_at"]
    return w


def actions_for(status: str, rung=0, parked_by: str = "") -> list[str]:
    """The three actions, and which of them apply right now.

    `pick` and `approve` are the same decision to a visitor — "yes, this one" — so the view offers
    one button for whichever the rung is actually waiting on.

    `needs-human` AT THE ADMISSION RUNG is the one case where "approve" must not appear. Every
    other waiting status has a run behind it — a workflow holding a signal, or an issue holding a
    comment — and approving reaches it. An idea that never cleared admission has neither: no
    workflow was started and no issue exists, so the button posted a decision into a hole. It sat
    on the screen looking like the way forward and did nothing, which is the failure this system
    is built to refuse.

    The remaining two actions are the honest ones there: say what to change (the request goes back
    with more to go on) or stop it.
    """
    if status == "await-pick":
        return ["pick", "changes", "kill"]
    # IT ASKED YOU SOMETHING. The one state where the textarea IS the point: a lettered answer or
    # a sentence goes back to the spec rung, which runs again with it. No approve — there is
    # nothing built yet to approve.
    if status == "await-answer":
        return ["changes", "kill"]
    if status == "needs-human" and stage_index(rung) == 0:
        # Only Stop. Not a lesser version of the usual three — the OTHER TWO HAVE NOWHERE TO GO.
        # A request that never cleared admission started no run and opened no issue, so there is
        # no thread for a change to attach to and nothing to approve. Drawing those buttons and
        # then explaining the failure is worse than not drawing them: the visitor has already
        # spent the effort of writing the change by the time the screen admits it cannot be sent.
        return ["kill"]
    if status in ("await-approve", "await-signoff", "needs-human"):
        return ["approve", "changes", "kill"]
    if status == "climbing":
        # A run that is WORKING can be stopped. It offered nothing at all, and rung 4 may run for
        # forty minutes — an operation that blocks for that long with no exit is the one thing
        # Tidwell's Cancelability pattern exists to forbid, and the page has a spinner, a clock
        # and a stated cap with no way out beside them.
        #
        # Only Stop. Approve and changes belong to gates: mid-rung there is nothing holding a
        # decision, and the workflow refuses both (422), so drawing them would be a false
        # affordance on the screen that can least afford one.
        return ["kill"]
    if status == "stopped":
        # A run that stopped on its own is the one case where the page must offer a way BACK.
        # Expedition 17 sat here with an empty list: the run was dead, the record still said
        # "climbing", and climbing has no actions — so the screen showed a visitor a stopped run
        # and nothing at all to do about it. "Changes" is absent on purpose; there is no gate
        # holding a revision, and the honest choices are try it again or stop.
        return ["retry", "kill"]
    if status == "parked" and parked_by == "failure":
        # THE BRANCH ABOVE HAS NEVER ONCE FIRED. "stopped" is a label this module DERIVES; it is
        # never a status the store holds. A broken run is stored as `parked`, which is terminal,
        # so `is_active` is False, so `stopped` computes False, so every branch fell through to []
        # — and expeditions 18, 19 and 20 each showed a visitor a dead run with nothing to do
        # about it, which is the exact failure the branch above was written to prevent.
        #
        # A run a PERSON stopped gets nothing: they meant to stop it, and offering to start it
        # again is arguing with them. Only a run that BROKE is offered a way back.
        return ["retry", "kill"]
    return []


def is_active(status: str) -> bool:
    return status not in TERMINAL and status != "killed"


# ── login ───────────────────────────────────────────────────────────────────────────────────
# A shared passcode, and a name that becomes the actor on every decision. Not an identity system:
# it keeps a public URL from being an open cheque, and it makes the ledger say who.

@dataclass
class DemoAuth:
    """HMAC-signed bearer token. `secret` unset -> the surface refuses every login (fail-closed),
    because a demo that authenticates nobody is an open door with a login form drawn on it."""
    secret: str = ""
    ttl_s: int = 12 * 3600

    @classmethod
    def from_env(cls) -> DemoAuth:
        return cls(secret=os.environ.get("FLS_DEMO_PASSCODE", ""))

    @property
    def configured(self) -> bool:
        return bool(self.secret)

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

    def mint(self, name: str) -> str:
        exp = int(time.time()) + self.ttl_s
        payload = f"{name}:{exp}"
        return f"{payload}:{self._sign(payload)}"

    def verify(self, token: str) -> str:
        """The name the token carries, or "" when it is missing, malformed, forged or expired."""
        if not self.configured or not token:
            return ""
        try:
            name, exp, sig = token.rsplit(":", 2)
        except ValueError:
            return ""
        if not hmac.compare_digest(sig, self._sign(f"{name}:{exp}")):
            return ""
        try:
            if int(exp) < time.time():
                return ""
        except ValueError:
            return ""
        return name

    def check_passcode(self, passcode: str) -> bool:
        """Surrounding whitespace is trimmed from both sides before comparing.

        A shared passcode is copied out of a terminal or a password manager, and both routinely
        carry a trailing newline or space. Rejecting the right passcode because of an invisible
        character is a bug that reads to the person as "you typed it wrong", which is the worst
        possible error message: it is both unhelpful and false. Trimming costs nothing —
        whitespace at either end is not part of anyone's secret — and the comparison stays
        constant-time.
        """
        return self.configured and hmac.compare_digest(
            (passcode or "").strip(), self.secret.strip())


# Words that belong to the operator's side of the wall. The judge writes for an operator — its
# reasoning cites verifiers, budgets and north stars — and that prose was reaching the public page
# through the detail line, which is exactly the leak the rest of this module exists to prevent.
# Words that mean this system is talking about itself. Any one of them in a line bound for the
# demo means the line was written for an operator.
#
# `altitude` and `non-negotiable` were missing, and the permissive bar made that expensive: the
# gate's admitting reasoning routinely reads "maps to an allowed altitude without violating any
# stated non-negotiables", which sailed straight through to a visitor. Found 2026-09-12 by a test
# whose own sample reason used the real words and did not trip the guard.
_INTERNAL = ("verifier", "north star", "anchor", "rung", "dial", "budget", "ledger", "expedition",
             "a11y", "vessel", "adjudicat", "gate", "altitude", "non-negotiable", "workflow",
             "fidelity ladder")

_NEEDS_DETAIL = ("This needs a bit more detail before it can start. Say what should change on "
                 "screen, and how you would know it worked.")


# Machinery has a SHAPE as well as a vocabulary, and `_INTERNAL` can only catch the vocabulary.
#
# Rung 3's lint refuses with "walkthrough step 8 targets '#sc-uncalled', which is not in the page;
# walkthrough step 9 targets '#sc-split', …" — CSS selectors and step indices, containing not one
# banned word, so the wordlist passed it straight through to a public page. Seen 2026-09-13 on
# expedition 34, where it was the entire explanation a visitor got.
#
# A denylist of words cannot be completed; this is the shape half of the same guard. It looks for
# things that are only ever written for someone reading the code: a quoted CSS selector, a file
# path with an extension, a dotted module path, a stack frame, a bare positional index.
_MACHINE_SHAPES = _re.compile(
    r"""['"`]\s*[#.][A-Za-z_][\w-]*\s*['"`]   # a quoted CSS selector: '#sc-fold', ".row"
      | \b[\w/-]+\.(?:py|mjs|js|jsx|ts|tsx|json|html|css)\b   # a file name with a code extension
      | \bfls\.[a-z_]+                          # a dotted internal module path
      | \bline\s+\d+\b                          # "line 214"
      | \bstep\s+\d+\s+targets\b                # the rung-3 lint's own sentence shape
    """,
    _re.VERBOSE,
)


def looks_like_machinery(text: str) -> bool:
    """True when the SHAPE of the text says it was written for someone reading the code.

    Separate from the `_INTERNAL` word check, and deliberately narrow: it must never swallow a
    sentence a visitor should have seen. Anything it matches is a construct no visitor-facing
    sentence has a reason to contain.
    """
    return bool(_MACHINE_SHAPES.search(text or ""))


# MATCHED AS WORDS, NOT SUBSTRINGS. "dial" is inside "dialog", "gate" is inside "navigate" and
# "aggregate", "anchor" is inside "anchored" — so a question naming a dialog was silently dropped
# and replaced by a generic sentence, which on the ambiguity gate means a visitor is shown no
# question at all while the run waits for their answer. The tuple stays as the list; this is only
# how it is looked for. `adjudicat` is a stem and keeps its wildcard.
_INTERNAL_RE = _re.compile(
    r"\b(?:" + "|".join(
        (_re.escape(w) + r"\w*") if w.endswith("at") else (_re.escape(w) + r"(?:s|es|d|ed|ing)?")
        for w in _INTERNAL) + r")\b")


def visitor_detail(text: str, *, blocked: bool = True, fallback: str | None = None) -> str:
    """A detail line safe to show a visitor, or a plain sentence instead.

    `blocked` says whether the run is actually STOPPED. It decides what replaces a line that
    leaked internal vocabulary: the "needs a bit more detail" sentence is about a request that
    cannot start, so on a run that is climbing it is simply false. Under the permissive bar it
    became the common case — an admitted idea's reasoning routinely mentions altitude or
    non-negotiables, so the demo told a visitor "this needs more detail before it can start"
    directly under "Working on it". Say nothing rather than something untrue.

    Text this system writes for itself is fine; text written for an operator is not, and the
    admission judge writes for an operator. Rather than paraphrase someone else's reasoning badly,
    a line carrying internal vocabulary is replaced with a sentence that says the useful half:
    what the person should do next.
    """
    low = (text or "").lower()
    if _INTERNAL_RE.search(low) or looks_like_machinery(text):
        # The caller decides what a dropped line is replaced with, because only the caller knows
        # what is actually happening. "Needs a bit more detail before it can start" is about a
        # request that CANNOT START; at a pick gate the run has started and is waiting on a
        # choice, and the workflow's own detail there reads "3 candidates in Expedition 14" —
        # which trips the guard on the word "Expedition" and replaced a true sentence with a
        # false one. Saying nothing is always available and always honest.
        return (fallback if fallback is not None else (_NEEDS_DETAIL if blocked else "")) or ""
    return text


# What a visitor is told when the run stopped without saying why. Not an apology and not a
# diagnosis: it says the run is over, that the work already done is still there, and what they can
# do next. A run that parks with its own reason never reaches this — this is the floor.
_NO_PR_YET = ("It is not pushed anywhere yet and there is no pull request \u2014 that is the "
              "last step, and it happens once you say carry on.")

_BROKE = ("The step it was on stopped before it finished, so the run is not going any further on "
          "its own. Whatever was already made is still below, and you can try that step again.")

_STOPPED = ("It stopped before finishing. Whatever it had already made is still below, "
            "and you can start a new request.")

# What went wrong, in the words of the thing it happened to — never the words of the machine it
# happened inside. `_BROKE` above says the run stopped; it cannot say why, because it is a
# constant. These say why, for the four ways a step can end badly, and nothing here ever carries
# an exception class, a file path, or a line of a transcript.
_CAUSE_WORDS = {
    "crash": "Something went wrong inside the {stage} step.",
    "timeout": "The {stage} step ran out of time.",
    "heartbeat": "The machine running the {stage} step stopped answering.",
    "stopped": "The {stage} step stopped before it finished.",
}


def cause_words(cause: dict | None, stage: str = "") -> str:
    """One plain sentence for why a run stopped, or "" when nothing was recorded.

    A refusal is different from the other three: the step ran, decided, and said no — so it has
    its own sentence already, and that sentence goes through the same leak guard every other
    engine-written reason does.
    """
    if not cause:
        return ""
    kind = cause.get("kind", "")
    name = stage or "last"
    if kind == "refused":
        return visitor_detail(cause.get("message", ""), blocked=True, fallback=_BROKE)
    template = _CAUSE_WORDS.get(kind)
    return template.format(stage=name) if template else ""


# HOW BIG A CHANGE IS, in the words a person would use. Rung 1 estimates it and the Request card
# carries it from that moment, so somebody waiting knows what they are waiting for. Nothing is
# ever refused for size — a change that comes out bigger than it looked is a sentence on the
# page, not a parked run.
_SIZE_WORDS = {
    "small": "a small change — about one sitting to read",
    "medium": "a medium change — expect two or three pieces",
    "large": "a large change — it will land in several pieces",
}


def size_words(estimate: dict | None) -> dict | None:
    """The visitor's version of rung 1's estimate, or None when it never made one."""
    size = str((estimate or {}).get("size") or "").lower()
    if size not in _SIZE_WORDS:
        return None
    return {"size": size, "says": _SIZE_WORDS[size]}


def growth_words(size: str, notes: list | None) -> str:
    """One plain sentence when the build came out a different size than it was estimated at.

    Never a refusal and never a retry: the work is finished, tested and on a pull request. This
    only tells the person that the shape of it moved, because they were told a size and are owed
    the correction.
    """
    grew = next((n for n in (notes or []) if "estimated" in str(n)), "")
    if not grew:
        return ""
    for name in ("small", "medium", "large"):
        if f"**{name}**" in str(grew) and name != size:
            return (f"This was estimated {_SIZE_WORDS.get(size, 'a change')[:1].lower()}"
                    f"{_SIZE_WORDS.get(size, 'a change')[1:].split(' — ')[0]} and came out "
                    f"{_SIZE_WORDS[name].split(' — ')[0]}. It is all there for you to look at.")
    return ""


# WHAT IT NEEDS, when it is waiting on an answer rather than a decision. `_NEEDS_DETAIL` says
# "before it can start", which is false here — it started, wrote a spec, and found one word in the
# request that could mean two things.
_ASK_DETAIL = "It needs one answer from you before it can go on."
_ASK_FALLBACK = {
    "ask": "Your request could mean more than one thing. Say which part of the screen, or which "
           "feature, you mean — in your own words.",
    "options": [],
}


def visitor_question(q: dict | None) -> dict | None:
    """Rung 1's question in words a stranger can read — or a generic one if it cannot be shown.

    Every line goes through the leak guard, because the question is written by a model that has
    been reading the ANCHOR and the vessel's standards. If any of it is dropped the WHOLE thing is
    replaced rather than shown with a hole in it: half a question is worse than a plain one, and
    the textarea below it works either way.
    """
    if not q:
        return None
    ask = visitor_detail(str(q.get("ask") or ""), blocked=False, fallback="")
    opts = [visitor_detail(str(o), blocked=False, fallback="") for o in (q.get("options") or [])]
    if not ask or not all(opts):
        log.warning("a rung-1 question could not be shown to a visitor: %r", q)
        out = dict(_ASK_FALLBACK)
    else:
        out = {"ask": ask, "options": opts}
    # The letter is only a thing when there are options to letter. An open question — the
    # request named nothing — takes words, and a hint about letters there sends the person
    # looking for a list that does not exist.
    options = [{"key": chr(ord("a") + i), "text": t} for i, t in enumerate(out["options"])]
    return {"ask": out["ask"], "options": options,
            "how": ("Type the letter, or say it in your own words, below." if options
                    else "Say it in your own words, below.")}


_REV = _re.compile(r"^r(\d+):\s*(.*)$", _re.S)


def revisions(workflow: dict | None) -> list[dict]:
    """What the visitor asked to be changed, and at which stage — oldest first.

    The workflow has recorded every one of these since the beginning (`feedback_log`) and no
    screen has ever shown them. On the demo that means a visitor types what they want changed,
    presses Send, and their words vanish: the box empties, the step re-runs, and nothing on the
    page says the request was heard or what it was. The one contribution a visitor makes besides
    the pick is the one thing the page forgets.

    The stored form is `"r3: make the chips bigger"` — the rung is in the string, so it is
    translated to a stage name here rather than shown. An entry that does not parse is still
    listed, with no stage: a revision the system cannot place is still a revision somebody wrote,
    and dropping it would be a worse lie than showing it bare.
    """
    out = []
    for line in (workflow or {}).get("feedback_log") or []:
        m = _REV.match(str(line))
        if m:
            idx = stage_index(int(m.group(1)))
            out.append({"stage": STAGES[idx] if 0 <= idx < len(STAGES) else "",
                        "at": idx, "asked": m.group(2).strip()})
        elif str(line).strip():
            out.append({"stage": "", "at": None, "asked": str(line).strip()})
    return out


def _STAGE_URL() -> str:
    """Where a signed-off change is reviewable, or "" when this instance stages nowhere."""
    return (os.environ.get("FLS_STAGE_URL") or "").strip().rstrip("/")


def demo_view(rec: dict, workflow: dict | None = None, artifacts: dict | None = None,
              preview_base: str = "", *, cause: dict | None = None,
              retry_refusal: str = "") -> dict:
    """One expedition, in a visitor's words. Never returns a rung number or a dial name."""
    status = rec.get("status", "")
    idx = stage_index(rec.get("rung", 0))
    words, waiting = status_words(status)
    # "Blocked" = the run is not moving on its own: it is waiting on a person, or it stopped.
    # Only then does a reason explain the present.
    # `running` is absent when there is no workflow at all (a store-only instance) — there is
    # nothing to contradict the record then, so the record stands.
    alive = (workflow or {}).get("running", True)
    # A workflow that has ENDED is not the same as a run that STOPPED. Both leave `running` false,
    # and treating them alike put "Stopped · It stopped before finishing" on a run that had been
    # signed off — on the payoff screen, over its own detail line saying "signed off; staged behind
    # the flag". The most important moment in the whole demo, calling a success a failure.
    #
    # The record is what tells them apart: a terminal status (done, docked, killed) means the run
    # reached an ending and its own word for that ending is the true one. Only a record that still
    # thinks it is climbing, with nothing running it, has actually stopped.
    # STOPPED MEANS THE RUN DIED WITHOUT CONCLUDING, not merely that the workflow is no longer
    # running. `needs-human` is a CONCLUSION — the spec rung looked at the request and said what it
    # would need — and a workflow that has said that is finished on purpose, not orphaned.
    #
    # Without this exclusion the derived label swallowed the real one: expedition 31's refusal
    # arrived on screen as "Stopped" offering Retry, which would re-run the identical words for the
    # identical answer. Same shape as the bug this `stopped` flag was invented to fix, pointing the
    # other way — a derived label is a guess about a state the store already knows.
    stopped = not alive and is_active(status) and status != "needs-human"
    blocked = status != "climbing" or stopped
    arts = artifacts or {}
    wf_arts = (workflow or {}).get("artifacts") or {}
    merged = {**arts, **wf_arts}

    out = {
        "number": rec.get("number"),
        "request": rec.get("intent", ""),
        "stages": list(STAGES),
        "stage_notes": list(STAGE_NOTES),
        "stage": idx,
        "stage_name": STAGES[idx] if 0 <= idx < len(STAGES) else "",
        "status": "Stopped" if stopped else words,
        "waiting_on_you": waiting and alive,
        # Only while it is actually running. At a gate the visitor is the one holding it up, and
        # telling them the machine is busy would be the opposite of true. And a run whose workflow
        # has ENDED is not running either, whatever the store still says: a Temporal query answers
        # from replayed history, so a dead run keeps reporting the state it died in. Expedition 17
        # reported "climbing" for twenty minutes after its workflow failed, and this line believed
        # it — a spinner, and a clock counting past the cap it promises, over nothing at all.
        "working": (working_detail(rec, (workflow or {}).get("run_health"))
                    if (status == "climbing" and alive) else None),
        "actions": actions_for("stopped" if stopped else status, rec.get("rung", 0),
                                rec.get("parked_by", "")),
        # The ADMISSION reason explains admission, not what is happening now. Falling back to it
        # while a run climbs kept a sentence about the request's scope on screen for the whole
        # climb, describing a decision three rungs behind as though it were the current state.
        # Once the run is moving, the workflow's own detail is the only thing that is about now.
        # The "needs more detail" sentence belongs to exactly one situation: a request that never
        # cleared admission. Anywhere else the run has started, and the sentence is false.
        "detail": visitor_detail(
            (workflow or {}).get("detail") or (rec.get("reason") if blocked else "") or "",
            blocked=blocked,
            fallback=(_NEEDS_DETAIL if (status == "needs-human" and idx == 0)
                      else _BROKE if (status == "parked"
                                      and rec.get("parked_by") == "failure")
                      else _STOPPED if stopped else "")),
        # Every change asked for, in order. A run that was revised twice looks identical to
        # one that sailed through unless the page says otherwise.
        "revisions": revisions(workflow),
        "spend": rec.get("normalized_usd") or 0.0,
        "artifacts": {},
    }

    # THE QUESTION IT ASKED. Gated on the STATE, not on the artifact: the workflow pops the
    # question once it is answered, and a stale one rendering under a later stage would ask a
    # person to decide something they already decided.
    if status == "await-answer":
        out["question"] = visitor_question(merged.get("question"))
        # And the sentence above it is about the WAITING, not the question — rung 1 sets its
        # `detail` to the ask, so leaving that in place would print the same words twice and call
        # the second one the status. Same shape as the cause line that used to repeat the detail.
        out["detail"] = _ASK_DETAIL
    # HOW BIG IT LOOKS, from the moment rung 1 says so. On the Request card, because that is
    # where somebody who has just filed is looking while they wait.
    if est := size_words(merged.get("estimate")):
        out["estimate"] = est
    # WHY it stopped, under the sentence saying that it did. `detail` says the run is not going
    # further; this says what happened to it. Only on a run that actually broke — a signed-off
    # run has no cause and a parked-by-human one is a decision, not a fault.
    if cause and (stopped or (status == "parked" and rec.get("parked_by") == "failure")):
        words_for_cause = cause_words(cause, STAGES[stage_index(cause.get("rung", 0))])
        # NOT THE SAME SENTENCE TWICE. A refusal's own words go through the leak guard, and the
        # guard is often right to drop them: rung 4's real refusal here was "the diff is 1857
        # changed lines, over the 400-line reviewability budget", which names an internal control
        # and cannot reach a stranger. What is left is the generic fallback — which is exactly what
        # `detail` already says, so the page printed one sentence, twice, and called the second one
        # the cause. Two identical lines say less than one.
        if words_for_cause and words_for_cause != out["detail"]:
            out["cause"] = words_for_cause
    # OFFER A BUTTON ONLY WHERE IT WOULD WORK. Retry was shown on every stopped run and its four
    # refusals were discovered by pressing it — which teaches a visitor the button is unreliable
    # rather than that this run cannot be retried.
    if retry_refusal:
        out["retry_blocked"] = visitor_error(409, retry_refusal)
        out["actions"] = [a for a in out["actions"] if a != "retry"]

    # Only what a visitor can actually look at. Everything else in the artifact bag is operator
    # material and stays out of the payload rather than being hidden in the view.
    # Why there is one shape here instead of three. Without this the page shows a single option
    # with no explanation, which reads as the rung having failed rather than having judged.
    if why := (merged.get("figma") or {}).get("fewer_because"):
        out["artifacts"]["fewer_because"] = visitor_detail(str(why), blocked=False, fallback="")
    # BUILD'S DELIVERABLE. The link carries the flag parameter already set, because every change
    # ships behind a flag that is off — a bare stage link shows the app looking exactly as before,
    # and a visitor reasonably concludes nothing happened. That is not hypothetical; it happened
    # here, and the pull-request comment has carried the same warning ever since.
    if stage := merged.get("stage"):
        if url := stage.get("url"):
            out["artifacts"]["stage_url"] = url
            out["artifacts"]["stage_flag"] = stage.get("flag") or ""
    if wires := merged.get("wireframe"):
        # `/pick 2` is 1-based (the command protocol, and what the rung-3 builder reads back off
        # disk). Anything outside the range is no pick at all rather than a guess: showing the
        # wrong candidate as chosen is worse than showing none.
        raw = merged.get("picked")
        # `bool` IS an `int` in Python, so a stray `True` would sail through the range check
        # and put a check mark on the first candidate. Excluded explicitly.
        ok = isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= len(wires)
        chosen = int(raw) if ok else None
        out["artifacts"]["candidates"] = [
            {"name": c.get("name"), "title": c.get("title"), "premise": c.get("premise"),
             "url": c.get("url"), "chosen": chosen == i + 1}
            for i, c in enumerate(wires) if isinstance(c, dict)]
    if merged.get("prototype") or idx >= 2:
        # The run owns its artifacts, so the link says so: /runs/17/preview, not /preview/17.
        # This is a URL a visitor sends to somebody, which is why it carries neither the API
        # prefix nor an audience — the page is for anyone holding the link.
        out["artifacts"]["preview_url"] = f"{preview_base.rstrip('/')}/runs/{rec.get('number')}/preview"
    if att := (rec.get("attachment") or None):
        out["artifacts"]["attachment"] = att
    if build := merged.get("build"):
        out["artifacts"]["build"] = {
            "files": len(build.get("files_changed") or []),
            "lines": build.get("lines_changed"),
            "tests_passed": build.get("test_passed"),
            "summary": build.get("note", "")[:600],
            # In pieces, because that is how it was built and how it should be read.
            "commits": len(build.get("commits") or []) or None,
            # And the correction, when the size moved. Not a warning — nothing went wrong.
            "grew": growth_words(str(build.get("size") or ""), build.get("size_notes")),
            # WHERE THE CODE IS, when it is not anywhere a visitor can click yet. The card showed
            # six files, 356 lines and passing tests, and then stopped — so the obvious next
            # question ("where is it, then?") had no answer on the page and read as a missing
            # link. It is not missing: a pull request is made at the LAST step, and this run has
            # not been approved past this one. Saying so costs a sentence; a fabricated link
            # would be the failure this system is built to refuse.
            "next": "" if merged.get("ship") else _NO_PR_YET}
    if ship := merged.get("ship"):
        out["artifacts"]["pull_request"] = ship.get("pr_url")
        # WHETHER THE CHECKS ARE STILL RUNNING. Rung 4 opens the pull request and marks it ready;
        # the stage deploy happens later, off a webhook, once the checks go green. Between those
        # two moments nothing is computing and nothing is wrong — but the surface had no way to
        # say so, because "ready for review" never left the artifact bag. It said instead that the
        # checks were green AND that they had not finished, in one sentence.
        #
        # A run whose pull request was NOT marked ready is a different state again: it is not
        # waiting for anything, it will simply never reach stage on its own. The view needs to
        # tell those two apart, so the fact goes across rather than being inferred from absence.
        out["artifacts"]["ready_for_review"] = bool(ship.get("ready_for_review"))
        # What a person does next, in the two places it actually happens. Both are facts about
        # this run: the branch it is on, and the flag it introduced. Absent when unknown, and the
        # surface then says less rather than inventing a name to type.
        out["artifacts"]["review"] = {
            "stage_url": _STAGE_URL(), "flag": ship.get("flag") or "",
            "branch": ship.get("branch") or "",
        }
    return out


# ── when an action cannot go through ────────────────────────────────────────────────────────
# Rule 1 of this surface is that it never shows the machinery, and an ERROR is the easiest place
# to break it: the engine's refusals name repos, workflows and seams because an operator needs
# those words, and a visitor handed one learns only that something they cannot see went wrong.
# So the same translation the status line gets (`visitor_detail`) applies to failures, keyed on
# what the engine actually answered.
_ACTION_ERRORS = {
    409: ("This request never made it through the front door, so there is nothing here to send "
          "it to. Stop it and start a new one with a little more detail about what you want."),
    # Distinct from 409 on purpose. Both were 409 at first, so a visitor who approved at a pick
    # gate was told their request had never made it through the front door — about a run that was
    # three stages in and showing them its candidates.
    422: "That is not what this is waiting for — look at what it is asking you above.",
    413: "That is longer than this box takes — try saying it more briefly.",
    503: "The place this gets recorded is not reachable right now, so nothing was sent. Nothing "
         "was lost either — try again in a minute.",
    502: "The place this gets recorded refused it, so nothing was sent. Try again in a minute.",
}


# Retry brings three more 409s, and one canned sentence cannot carry them. The comment above
# records that this exact mistake was made once already: two different refusals shared a code, so
# a visitor approving at a pick gate was told their request had never been admitted. A retry
# refused because the run is still going, and a retry refused because the money ran out, are not
# the same news — and "start a new one with more detail" is wrong advice for both.
#
# Matched on the engine's own words rather than a parallel error-code vocabulary, and every pair
# is pinned by a test: reword the engine's refusal and the test fails rather than the page
# quietly falling back to a sentence that does not fit.
_RETRY_ERRORS = (
    ("still running", "It is still going — there is nothing to retry yet. Give it a moment."),
    ("ceiling", "This request has used up what it is allowed to spend, so it will not start "
                "again. You can file a new one."),
    ("nothing to retry", "This one is already finished. File a new request to build something "
                         "else."),
    ("no run to retry", "There is nothing left running for this request. File a new one."),
)


def visitor_error(code: int, detail: str) -> str:
    """One sentence a visitor can act on, for an action the engine refused.

    Falls back to the engine's own text only for 400 — the "that is not one of this surface's
    actions" case, which is already written for a stranger and only reachable by someone posting
    outside the page. Every other code gets a visitor sentence or a plain one; passing an
    unrecognised engine string through would be exactly the leak this exists to stop.
    """
    if code == 400:
        return detail or "That is not something this page can do."
    if code == 409:
        low = (detail or "").lower()
        for mark, sentence in _RETRY_ERRORS:
            if mark in low:
                return sentence
    return _ACTION_ERRORS.get(code, "That did not go through, and nothing was changed.")


def _said(text: str) -> str:
    """One request's words, flattened so two spellings of the same sentence compare equal."""
    return " ".join(str(text or "").split()).lower()


def suggestion_for(suggestions, wall) -> dict | None:
    """The first suggested request nobody has filed yet, or None.

    A QUEUE, not a rotation. An idea leaves the list by being USED — matched against the intent of
    every expedition this instance has ever run — so the demo never offers to build something that
    already exists, and nothing has to be written back when a visitor takes one. That also means a
    crash loses nothing: the record of what was filed IS the record of what was consumed.

    Both lines go through the leak guard, because they are shown to a stranger and they are
    authored in an ANCHOR beside text that is not. An idea that trips it is SKIPPED rather than
    blanked: a suggestion with half its words missing is worse than the next one down.
    """
    used = {_said(e.get("intent")) for e in (wall or [])}
    for s in suggestions or []:
        intent = getattr(s, "intent", "") or ""
        success = getattr(s, "success", "") or ""
        if _said(intent) in used:
            continue
        clean_intent = visitor_detail(intent, blocked=False, fallback="")
        clean_success = visitor_detail(success, blocked=False, fallback="") if success else ""
        if not clean_intent or (success and not clean_success):
            log.warning("a demo suggestion cannot be shown to a visitor: %r", intent[:80])
            continue
        return {"intent": clean_intent, "success": clean_success}
    return None


def last_finished(wall: list[dict]) -> dict | None:
    """The most recent demo-filed run that has stopped, or None.

    `TERMINAL` answers "may the surface take a new request". It was also, by accident, answering
    "is this still worth showing" — one flag doing two jobs, and the second answer was wrong. A
    finished run is exactly what a visitor came to see: the pull request it opened, where it was
    staged, what it cost.

    Only runs filed THROUGH the demo, on the same rule as everything else this surface shows: an
    operator's expedition is not a stranger's to read.
    """
    demo_runs = [e for e in wall
                 if str(e.get("source", "")).startswith("demo") and not is_active(e.get("status", ""))]
    return max(demo_runs, key=lambda e: e.get("number", 0)) if demo_runs else None


# ── one attached file ───────────────────────────────────────────────────────────────────────
# A visitor can put ONE file on a request: a screenshot of the thing they want changed, a note,
# a CSV of what is wrong. Bounded deliberately, because this is a public URL:
#
#   one file, 4 MB, an allowlist of types, and a name the server chooses.
#
# The name matters most. A filename from the internet is an attack surface — path traversal,
# a leading dot, a .html that would be served back from our own origin and run as our page. The
# stored name is derived from the type, never from what was uploaded; the original is kept only
# as a label to show the human.
ATTACH_MAX_BYTES = 4 * 1024 * 1024
ATTACH_TYPES = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt", "text/markdown": ".md", "text/csv": ".csv", "application/json": ".json",
}
# Which of those the ADMISSION GATE can actually read. An image is shown to the human and goes no
# further; text is folded into the gate's grounding, so saying "the details are in the file" works
# for a .md and does not for a .png. The surface says which it did — a file that silently went
# nowhere would be the same pretence as a chip for a pull request nobody opened.
ATTACH_READABLE = {"text/plain", "text/markdown", "text/csv", "application/json"}
ATTACH_TEXT_BUDGET = 8_000


def attachment_error(name: str, mime: str, size: int) -> str:
    """Why this file cannot be attached, or "" when it can."""
    if not name.strip():
        return "that file has no name"
    if mime not in ATTACH_TYPES:
        return (f"{mime or 'that file type'} is not one this surface takes — "
                "images, PDF, or plain text")
    if size <= 0:
        return "that file is empty"
    if size > ATTACH_MAX_BYTES:
        return f"that file is {size // 1024 // 1024}MB; the limit is 4MB"
    return ""


def attachment_grounding(mime: str, data: bytes) -> str:
    """The part of an attachment the gate can read, or "" when there is none."""
    if mime not in ATTACH_READABLE:
        return ""
    try:
        text = data.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001 — an undecodable "text" file simply grounds nothing
        return ""
    return text[:ATTACH_TEXT_BUDGET]

"""Rung 2 — candidate wireframes as real frames in a real design file.

The reference rung-2 builder emits HTML fragments. This one emits **Figma frames**: an agentic
Claude Code session with the design tool's MCP attached creates one page per expedition, draws N
structurally different candidates on it, screenshots each, and returns a declared JSON contract.

Two things make this safe to run unattended:

* **A declared output contract.** The session must end with one fenced JSON block naming every
  frame it made. Prose is not an artifact; if the contract is missing or malformed the rung fails
  loudly rather than parking a human in front of nothing.
* **A structure lint.** The frames the session claims are re-inspected against the conventions the
  rung was given (auto-layout present, layers named for their role, no detached instances). A
  builder's own "looks good" is never the evidence — the same rule the acceptance-test verifier
  applies at rung 4.

The session's budget is turns and wall clock, from the ANCHOR `worker:` block (see
`fls.claude_code`). Nothing here reads a credential: the CLI holds the design tool's OAuth on the
worker host.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fls.claude_code import ClaudeCodeSession
from fls.llm import Call

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

# Reading material available to the rungs. Rung 2 defaults to the construction-craft digest
# (Staiano) alongside the house conventions and the API rules; the system-scale digest (Jun) and
# the prototyping/handoff digest (Schwarz) are here for the rung-3 and rung-4 builders. The library
# under system-knowledge-library/figma-publications is the source; these are vendored copies so a
# worker without the library still builds correctly.
DIGESTS = {
    "construction": "staiano-figma-craft.md",
    "system": "jun-figma-advanced.md",
    "handoff": "schwarz-figma-handoff.md",
}

# The MCP tool names a rung-2 session may use. Deliberately narrow: it reads structure, writes
# nodes, and screenshots. It cannot create files, upload assets, or touch code connect.
FIGMA_TOOLS = (
    "mcp__figma__use_figma",
    "mcp__figma__get_metadata",
    "mcp__figma__get_screenshot",
)

_CONTRACT_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)

# ── identity: ASSIGNED, never discovered ───────────────────────────────────────────────────
# A retry has to find work a dead session left behind, and it cannot ask that session anything.
# So identity is derived from the expedition number before any work starts, rather than read back
# off a contract the session may never live to declare — expedition 18 recorded `artifacts: {}`
# after three attempts, which is exactly the case this exists for.
#
# The page id says WHERE (one addressed call, proven against expedition 17's page); the slug says
# WHICH, because a page holds several frames and "is candidate 2 already built?" is unanswerable
# against agent-chosen names. Both are needed and they do different jobs.


def page_slug(expedition: int) -> str:
    return f"exp-{expedition}"


def candidate_slug(expedition: int, i: int) -> str:
    """1-based, matching `/pick N` and the order a human sees them in."""
    return f"exp-{expedition}-c{i}"


# The line a session prints the MOMENT its page exists, before drawing anything. Recoverable from
# the streamed log of a session that was killed later — see claude_code._run_streamed.
#
# NOT anchored to a line. The log is newline-delimited JSON events and the sentinel arrives inside
# one of them, as a fragment of an assistant message whose own newlines are escaped — so `^...$`
# matched nothing at all in practice. Precision comes from the id's shape instead, which is what
# distinguishes a real sentinel from the instruction to print one.
_SENTINEL_RE = re.compile(r"FLS-PAGE:\s*(\S+?)\s+(\d+:\d+)")


def clean_title(title: str, slug: str) -> str:
    """The title a PERSON reads, with the machine's slug taken back out of it.

    The prompt asks for a name and a title and says they are different things. Expedition 23's
    session put the slug in both, so the demo card offered a choice between
    "exp-23-c1 — One row…" and "exp-23-c2 — Two tiers…" — the visitor surface's first rule is that
    the machinery never reaches it, and `exp-23-c1` is machinery.

    Stripped here rather than only asked for in the prompt, because an instruction to a model is a
    request and this is a guarantee. Idempotent, and it leaves a title that never had the slug
    exactly as it was.
    """
    t = (title or "").strip()
    if t.lower().startswith(slug.lower()):
        t = t[len(slug):].lstrip()
        t = t.lstrip("-—–:·|").lstrip()
    return t or title


def page_id_from_log(text: str, expedition: int) -> str:
    """The page id a previous attempt announced, or "" if it never got that far.

    Fail-closed on the slug: a sentinel naming a DIFFERENT expedition is ignored rather than
    adopted. Sharing one log directory between runs would otherwise hand expedition 19 a retry
    pointed at expedition 18's page, and the failure would look like the feature working.
    """
    want = page_slug(expedition)
    for slug, node in _SENTINEL_RE.findall(text or ""):
        if slug == want and node:
            return node
    return ""

_SYSTEM = """You produce wireframes as frames in a design file. You are one rung of a fidelity
ladder: your output is reviewed by a human who picks exactly one candidate, so candidates that do
not offer a real choice waste the review.

Work incrementally: create the page, then one candidate at a time, validating as you go. Never
write one enormous script.

COLOUR. A wireframe at this rung is GREY unless the instructions below say otherwise, and they
say so explicitly when they do. Grey means every solid fill has r, g and b equal: `0xF5` for
surfaces, `0xE0` for cards, `0x9E` for image and media placeholders, `0x21` for text. In this
API a colour is three numbers from 0 to 1, so mid grey is `{r: 0.62, g: 0.62, b: 0.62}` — the
three numbers must MATCH. Nothing here is a style preference: colour at this fidelity is a
decision about brand and meaning that nobody has taken yet, and a reviewer who sees a blue
primary button reads it as a decision rather than as a placeholder. Where a state must be
distinguishable, distinguish it with a label, a border or an icon, never with hue alone.

You MUST finish your final message with a single fenced JSON block and nothing after it:

```json
{"page_name": "...", "page_id": "...",
 "fewer_because": "omit unless you drew fewer than asked; one plain sentence if you did",
 "candidates": [{"name": "<EXACTLY the name you were given for this candidate>",
                 "node_id": "...", "title": "...",
                 "premise": "one sentence: what this candidate proposes and how it differs"}],
 "lint": {"auto_layout": true, "named_layers": true, "detached_instances": false,
          "fills": {"<candidate name>": ["#F5F5F5", "#212121"]},
          "notes": "anything you could not satisfy"}}
```
`fills` is READ BACK OFF THE CANVAS, not remembered: for each candidate, walk the frame you built
and list every distinct solid fill you find, as hex. It is the one claim the rung can check
against its own rule, so a guess here is worse than an omission — and an omission fails the rung.

Report the lint honestly. A false clean is worse than a declared gap: the rung re-checks it.

YOUR TURN IS NOT OVER UNTIL THAT BLOCK EXISTS. Creating the page, announcing it, or describing
what you intend to draw are all steps on the way; none of them is the deliverable. A final message
with no contract in it parks the run and wastes everything the session already paid for.

The candidate names are GIVEN TO YOU and are not yours to choose. They are how a later attempt
finds this work if you are interrupted, so a name of your own invention costs someone the whole
rung. Use the ones in the instructions exactly, prefix and all."""


@dataclass
class Resume:
    """What a previous attempt left behind, after it has been looked at and judged.

    `keep` is adopted as-is, `redo` is present but failed the structure check, `missing` was never
    built. Nothing here is taken on trust from a record — a frame half-drawn when its session was
    killed is exactly what a crashed run would otherwise report as finished.
    """
    page_id: str = ""
    keep: dict = field(default_factory=dict)     # slug -> node id
    redo: dict = field(default_factory=dict)     # slug -> why it failed
    missing: tuple = ()
    # node id -> the name it SHOULD have. A rung failed only because its frames were misnamed is
    # a rung whose work is entirely good: the drawings exist, they are sound, and the sole problem
    # is a label. Redrawing them would cost minutes to fix something that costs seconds.
    rename: dict = field(default_factory=dict)


@dataclass
class WireframeCandidate:
    name: str
    node_id: str
    title: str = ""
    premise: str = ""
    png_path: str | None = None
    url: str | None = None


@dataclass
class FigmaWireframeResult:
    passed: bool
    candidates: list[WireframeCandidate] = field(default_factory=list)
    page_name: str = ""
    page_id: str = ""
    # Why there are fewer shapes than usual, in the session's own words. Shown to the person who
    # came expecting a choice — "here is the only sensible shape, and here is why" is a far better
    # answer than three near-identical drawings, but only if the page says it.
    fewer_because: str = ""
    lint: dict = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    detail: str = ""
    calls: list[Call] = field(default_factory=list)
    # WHICH RULE THIS RUN WAS UNDER. Recorded rather than re-derived, because the policy is
    # decided from the request text and the request text can be edited afterwards — a decision
    # that can only be reconstructed is a decision nobody can audit.
    greyscale: bool = True
    colour_reason: str = ""

    def artifacts(self) -> dict:
        """What the demo view shows for this rung."""
        return {"wireframe": [
            {"name": c.name, "title": c.title, "premise": c.premise, "node_id": c.node_id,
             "url": c.url, "png": c.png_path} for c in self.candidates],
            "figma": {"page": self.page_name, "page_id": self.page_id,
                      "fewer_because": self.fewer_because,
                      "greyscale": self.greyscale, "colour_reason": self.colour_reason}}


def file_url(file_key: str, node_id: str | None = None) -> str:
    base = f"https://www.figma.com/design/{file_key}"
    return f"{base}?node-id={node_id.replace(':', '-')}" if node_id else base


# The house's OWN rules, as opposed to borrowed reading. These are short, written for this rung,
# and every line of them is load-bearing; the digests beside them are long, general, and useful at
# the margin. Priority is by name because the caller chooses the source list and a positional rule
# would break silently the first time somebody reordered it.
HOUSE_SOURCES = ("wireframe_conventions.md", "figma_api_rules.md")


def reading(names: tuple[str, ...], budget_chars: int) -> str:
    """The rung's bounded context: its reading material, trimmed to the rung's budget.

    THE BUG THIS SHAPE EXISTS FOR. The budget used to be split EQUALLY — three sources, 6,000
    characters, 2,000 each — and `wireframe_conventions.md` is 3,931 characters with "No brand
    color at this rung" starting around character 2,070. So the rule was cut off before it was
    ever sent, on every single run, while the surviving slice of a 35,000-character craft digest
    talked about accent palettes and the API rules taught `{r:1,g:0,b:0}` as the example colour.
    Every wireframe came back in brand blue, and nothing in the system had ever asked for grey.

    The house's own rules therefore go in WHOLE first, and the borrowed reading gets whatever is
    left. Only if the house rules alone exceed the budget does the equal split come back — at that
    point there is no un-arbitrary answer, and an arbitrary one that is stable beats a clever one.
    """
    texts = []
    for n in names:
        p = PROMPTS / n
        if p.exists():
            texts.append((n, p.read_text(encoding="utf-8")))
    if not texts:
        return ""
    house = [(n, t) for n, t in texts if n in HOUSE_SOURCES]
    rest = [(n, t) for n, t in texts if n not in HOUSE_SOURCES]
    spent = sum(len(t) for _, t in house)
    if not house or spent >= budget_chars:
        share = max(400, budget_chars // len(texts))
        return "\n\n".join(f"## {n}\n{t[:share]}" for n, t in texts)
    share = max(400, (budget_chars - spent) // len(rest)) if rest else 0
    out = {n: t for n, t in house}
    out.update({n: t[:share] for n, t in rest})
    return "\n\n".join(f"## {n}\n{out[n]}" for n, _ in texts)


# ── colour: grey unless something actually needs otherwise ─────────────────────────────────

@dataclass(frozen=True)
class ColourPolicy:
    """Whether this request may use colour, and the sentence saying why.

    Carried as one object rather than a bare boolean because the REASON has to travel: it goes
    into the prompt (so the session knows which rule it is under), into `figma.json` (so the
    decision is auditable after the fact), and into the violation text (so a person reading a
    failed rung can tell a wrong policy from a disobedient session).
    """
    greyscale: bool
    reason: str


# Word-bounded, and deliberately literal. A request that NAMES a colour has asked for one, and
# arguing with it would be the system overruling the person it is building for.
_COLOUR_WORDS = re.compile(
    r"\b(colou?rs?|colou?red|palette|hue|tint|shade|"
    r"red|orange|yellow|green|blue|purple|violet|indigo|pink|magenta|teal|cyan|amber|"
    r"gold|silver|brown|black|white)\b", re.I)

# States that MEAN something, where grey would be a lie rather than a placeholder. Kept tight:
# a word here turns colour on, so a loose list would quietly restore the behaviour this replaces.
# "active", "status" and the like are deliberately absent — they describe a thing far more often
# than they describe a state a person has to see at a glance. "passed" came out after a read-only
# pass over 38 real requests turned up "long after the moment has passed", which is a tense, not a
# state; the word earns its place by what it does to real text, not by sounding state-like.
_SEMANTIC_STATES = re.compile(
    r"\b(error|errors|success|successful|warning|warnings|danger|alert|"
    r"invalid|valid|failed|failing|failure|overdue|"
    r"won|lost|win|wins|loss|losses|winner|loser|"
    r"selected|unselected|enabled|disabled|toggle|toggles|on/off)\b", re.I)


def colour_policy_for(asked: str, spec: str = "") -> ColourPolicy:
    """Grey by default; colour when the PERSON asked for it, or a state needs it.

    Deterministic and cheap on purpose. The alternative — asking a model whether this request
    needs colour — puts a judgement call with no evidence behind it in front of a rung that then
    cannot be held to any rule, and adds a paid turn to every run to do it.

    THE TWO INPUTS ARE NOT INTERCHANGEABLE, and one live run was enough to show why. `asked` is
    what the visitor wrote; `spec` is what rung 1 wrote about it. A colour word is only a colour
    word when a PERSON chose it: expedition 44's request never mentions colour, and the policy
    still reported `the request names a colour ("color")` — because rung 1's own spec used the
    word. The system was reading its own output and calling it the customer's instruction, which
    means a spec that says "colour-code the result" authorises itself, and so does one that says
    "do not use colour".

    A semantic state is different and is read from both. "Won", "error", "invalid" are facts about
    the FEATURE, not preferences about it, and rung 1 naming one is rung 1 correctly noticing
    something the request implied.
    """
    if m := _COLOUR_WORDS.search(asked or ""):
        return ColourPolicy(False, f'the request names a colour ("{m.group(0)}")')
    if m := _SEMANTIC_STATES.search(f"{asked or ''}\n{spec or ''}"):
        return ColourPolicy(
            False, f'the request turns on a state grey cannot show ("{m.group(0)}")')
    return ColourPolicy(True, "nothing in the request names a colour or a state that needs one")


_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _is_grey(value: str, tolerance: int = 10) -> bool:
    """True when r, g and b are the same to within a rounding error. Anything unparseable is not
    grey: a fill the rung cannot read is a fill it cannot vouch for."""
    m = _HEX.match(str(value).strip())
    if not m:
        return False
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return max(r, g, b) - min(r, g, b) <= tolerance


def lint_colour(contract: dict, policy: ColourPolicy | None) -> list[str]:
    """Check the fills the session read back against the policy it was given.

    A MISSING READ-BACK IS A VIOLATION, not a pass. `lint_structure` has only ever checked the
    session's own self-report, and a session that simply omitted a field would have sailed through
    every check this rung has — which is precisely how three runs of blue wireframes passed a lint
    whose whole job is to catch exactly that.
    """
    if policy is None or not policy.greyscale:
        return []
    fills = (contract.get("lint") or {}).get("fills")
    if not isinstance(fills, dict) or not fills:
        return ["no fills were read back, so the rung cannot check its own colour rule — "
                "`lint.fills` must list every solid fill under each candidate"]
    v: list[str] = []
    for name, values in fills.items():
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or not values:
            v.append(f"{name} declared no fills — every candidate has at least a surface")
            continue
        for value in values:
            if not _is_grey(value):
                v.append(f"{name} uses {value} — {policy.reason}, so this rung is greyscale")
    return v


def parse_contract(text: str) -> dict:
    """Last fenced JSON object in the session's final message. Raises ValueError when absent."""
    blocks = _CONTRACT_RE.findall(text or "")
    for raw in reversed(blocks):
        try:
            d = json.loads(raw)
            if isinstance(d, dict) and "candidates" in d:
                return d
        except json.JSONDecodeError:
            continue
    raise ValueError("no output contract in the builder's final message")


def lint_structure(contract: dict, expected: int,
                   policy: ColourPolicy | None = None) -> list[str]:
    """Re-check what the session declared. Cheap, deterministic, and never trusts a bare claim.

    `policy` defaults to None — no colour rule, no colour check — so every existing caller and
    fixture keeps meaning exactly what it meant before.
    """
    v: list[str] = []
    cands = contract.get("candidates") or []
    # FEWER THAN `expected` IS ALLOWED WHEN THE SESSION SAYS WHY. Expedition 28 asked for tests and
    # this rung drew three wireframes of a test-viewer UI — a case list, a split view, a coverage
    # grid, none of them requested. It had no way to say "there is nothing to draw here", so it
    # invented a surface; and had a human picked one, that invention becomes the spec rung 4 builds
    # against. A request for tests would have become a UI feature, with every gate downstream
    # saying yes, because each one only checks that the last rung's artifact was built well.
    #
    # So one honest candidate now beats three fabricated ones — but only WITH A REASON, and the
    # reason is shown to the person who was expecting a choice. An empty contract is still a
    # failure: "nothing to draw" is a judgement a rung may make, not a way to produce nothing.
    if not cands:
        v.append("no candidates at all — the rung produced nothing to look at")
    elif len(cands) > expected:
        v.append(f"expected at most {expected} candidates, got {len(cands)}")
    elif len(cands) < expected and not str(contract.get("fewer_because") or "").strip():
        v.append(f"only {len(cands)} of {expected} candidates, and no reason given — a rung may "
                 "return fewer when the request has one sensible shape, but it must say so in "
                 "`fewer_because` rather than quietly under-deliver")
    seen: set[str] = set()
    for i, c in enumerate(cands, 1):
        if not isinstance(c, dict):
            v.append(f"candidate {i} is not an object")
            continue
        if not c.get("node_id"):
            v.append(f"candidate {i} has no node_id — nothing was created")
        name = c.get("name") or ""
        if not name:
            v.append(f"candidate {i} has no name")
        elif name in seen:
            v.append(f"duplicate candidate name {name!r}")
        seen.add(name)
        if not (c.get("premise") or "").strip():
            v.append(f"candidate {name or i} declares no premise — a human cannot choose between "
                     "candidates that do not say how they differ")
    lint = contract.get("lint") or {}
    if lint.get("auto_layout") is not True:
        v.append("frames are not on auto-layout — a wireframe without it is a picture of a layout")
    if lint.get("named_layers") is not True:
        v.append("layers are not named for their role — the file is unreviewable")
    if lint.get("detached_instances") is True:
        v.append("detached instances present — candidates must be self-contained at this fidelity")
    v += lint_colour(contract, policy)
    return v


class FigmaWireframeBuilder:
    """Build rung-2 candidates as frames. `session_factory(cwd, tools, max_turns, timeout_s)`
    returns a `ClaudeCodeSession`; injecting it keeps this testable without a CLI."""

    def __init__(self, file_key: str, session: ClaudeCodeSession | None = None,
                 session_factory=None, n: int = 3,
                 sources: tuple[str, ...] = ("wireframe_conventions.md", "figma_api_rules.md",
                                             "staiano-figma-craft.md"),
                 policy: ColourPolicy | None = None):
        if session is None and session_factory is None:
            raise ValueError("FigmaWireframeBuilder needs a session or a session_factory")
        self.file_key = file_key
        self.session = session
        self.session_factory = session_factory
        self.n = n
        self.sources = sources
        # Decided by the caller from the request, not here: this class builds frames, and which
        # rule a request falls under is a question about the request.
        self.policy = policy

    def _session(self) -> ClaudeCodeSession:
        return self.session or self.session_factory(tools=FIGMA_TOOLS)

    def prompt(self, expedition: int, spec: str, feedback: str = "", budget_chars: int = 6000,
               resume: Resume | None = None) -> str:
        page, names = page_slug(expedition), [candidate_slug(expedition, i)
                                             for i in range(1, self.n + 1)]
        parts = [f"FILE KEY: {self.file_key}"]

        if resume and resume.page_id:
            # THE RETRY. Address the page, never search for it: listing a document's pages returns
            # what the client happens to have loaded, not what the document holds — it answered
            # "one page" against a file with eight. An id is exact.
            parts.append(
                f"AN EARLIER ATTEMPT WAS INTERRUPTED. Its page still exists, id `{resume.page_id}` "
                f"(named `{page}`). Read that page by its id and WORK ON IT. Do not create a new "
                "page: a second page makes both unfindable for the next attempt.\n"
                f"FIRST, print exactly one line:\n    FLS-PAGE: {page} {resume.page_id}\n"
                "You are not the last attempt that can fail. Re-announcing the page is what lets "
                "the one after you find it — without it the chain breaks after a single recovery.")
            if resume.keep:
                parts.append(
                    "ALREADY BUILT AND SOUND — leave these exactly as they are, do not redraw "
                    "them:\n" + "\n".join(f"  {k} ({v})" for k, v in resume.keep.items()))
            if resume.redo:
                parts.append(
                    "PRESENT BUT NOT SOUND — delete and rebuild these:\n"
                    + "\n".join(f"  {k}: {why}" for k, why in resume.redo.items()))
            if resume.rename:
                parts.append(
                    "MISNAMED, NOT WRONG. These frames are already built and sound; the last "
                    "attempt simply gave them names of its own. RENAME them in place — do not "
                    "redraw them, and do not delete them:\n"
                    + "\n".join(f"  node {nid} -> `{want}`" for nid, want in resume.rename.items()))
            if resume.missing:
                parts.append("STILL TO BUILD: " + ", ".join(resume.missing))
            if not (resume.keep or resume.redo or resume.missing):
                # The harness knows WHERE the work is but not WHAT survived — it has no design-file
                # credential of its own, by deliberate choice. The session does: it is holding
                # `get_metadata`, and a fresh one was proven able to read a page and list its
                # frames. So the inspection is delegated, with the standard named rather than left
                # to taste, and what it reports back is recorded.
                parts.append(
                    "FIRST, INSPECT: read the page and list the candidate frames already on it. "
                    f"Expected names are {', '.join(names)}.\n"
                    "  - a frame that is present AND sound (auto-layout, layers named for their "
                    "role, no detached instances, a premise a human could choose on) — KEEP it "
                    "untouched, and do not redraw it to your own taste.\n"
                    "  - a frame that is present but NOT sound — it was half-drawn when the last "
                    "attempt was interrupted. Delete it and rebuild it.\n"
                    "  - a name with no frame — build it.\n"
                    "Report what you found in a `found_before` array alongside the usual contract.")
        else:
            parts.append(
                f"PAGE TO CREATE: a new page named exactly `{page}`.\n"
                f"THE MOMENT that page exists, and BEFORE you draw anything on it, print exactly "
                f"one line:\n    FLS-PAGE: {page} <the page id>\n"
                "This is the only way a later attempt can find your work if this one is "
                "interrupted. Print it first; everything else follows.\n"
                "PRINTING IT IS NOT THE JOB — it is the first line of the job. Expedition 51 "
                "created its page, printed this line, and ended its turn with nothing drawn; the "
                "rung was parked and the money spent. Keep going: draw the candidates, then "
                "finish with the JSON contract.")

        parts += [
            f"WHAT THE USER ASKED FOR:\n{spec.strip()}",
            f"NAME THE CANDIDATE FRAMES EXACTLY: {', '.join(names)}. A frame may carry more after "
            "that prefix, but the prefix is fixed — it is how a later attempt tells which "
            "candidate is which.",
            "THE NAME AND THE TITLE ARE DIFFERENT THINGS, and only one of them is for a machine. "
            f"The `name` is the slug above ({names[0]}…) and nothing else reads it. The `title` is "
            "shown to the person choosing, who has never heard of an expedition — so it says what "
            "the shape IS, in their words, and must NOT repeat the slug. "
            "Good: \"One row: Fold hand inline with Check\". Bad: \"" + names[0] + " — One row…\".",
            f"Draw {self.n} candidates that differ STRUCTURALLY — a different arrangement, step "
            "count, or placement — not by spacing or wording.",
            "IF THIS REQUEST HAS NO REAL CHOICE IN IT, SAY SO AND DRAW FEWER. Some requests change "
            "behaviour rather than appearance, or have exactly one sensible shape, and three "
            "drawings of a thing nobody asked for is worse than one honest drawing — a person will "
            "pick one of them, and what they pick becomes what gets built. Return as few as one "
            "candidate and put the reason in `fewer_because`: a plain sentence for the person who "
            "came expecting a choice. Do not invent a surface to have something to show.",
        ]
        if feedback.strip():
            # KEPT SEPARATE FROM `resume` ON PURPOSE. This slot means a HUMAN reviewed the work
            # and asked for changes, and the sentence below leans on that. Leftovers from a
            # crashed attempt are a machine observation; folded in here the session would read its
            # own debris as the founder's critique.
            parts.append("THE HUMAN REVIEWED YOUR LAST ATTEMPT AND ASKED FOR CHANGES. This is the "
                         f"whole reason you are running again:\n{feedback.strip()}")
        # SAID IN THE INSTRUCTIONS AS WELL AS THE SYSTEM PROMPT, because this is the one rule
        # that changes per request. The system prompt says "grey unless the instructions say
        # otherwise"; this is the instructions saying it, with the reason attached so the session
        # is not guessing at why.
        if self.policy:
            parts.append(
                f"COLOUR: greyscale only — {self.policy.reason}. Every solid fill has r, g and b "
                "equal. Show state with a label, a border or an icon, never with hue."
                if self.policy.greyscale else
                f"COLOUR ALLOWED: {self.policy.reason}. Use it only where it carries that "
                "meaning; everything else stays on the grey box scale.")
        r = reading(self.sources, budget_chars)
        if r:
            parts.append(f"HOW TO BUILD IT (follow these):\n{r}")
        return "\n\n".join(parts)

    def build(self, expedition: int, spec: str, feedback: str = "", budget_chars: int = 6000,
              artifact_dir: str | None = None,
              resume: Resume | None = None,
              log_path: str | None = None) -> FigmaWireframeResult:
        session = self._session()
        if log_path:
            # The session streams to disk from here on, so the page-id sentinel it prints early
            # survives the session being cancelled later. Set per ATTEMPT, so attempt 2 can read
            # attempt 1's log rather than overwriting it.
            session.log_path = log_path
        res = session.run(self.prompt(expedition, spec, feedback, budget_chars, resume),
                          system=_SYSTEM)
        calls = [res.call]
        if res.timed_out:
            return FigmaWireframeResult(False, detail=(
                f"the wireframe session hit its {session.timeout_s}s wall clock before declaring "
                "its frames"), calls=calls)
        try:
            contract = parse_contract(res.text)
        except ValueError as e:
            return FigmaWireframeResult(False, detail=str(e), calls=calls)

        violations = lint_structure(contract, self.n, self.policy)
        # DRIFT CHECK, fail-closed. A retry hands the session a page id and says work on it; if a
        # second page gets made anyway, both are unfindable next time and every later attempt
        # quietly stacks another set of candidates. Cheap to check, and the failure it prevents
        # would look exactly like the feature working.
        if resume and resume.page_id and contract.get("page_id") \
                and contract["page_id"] != resume.page_id:
            violations.append(
                f"the session was given page {resume.page_id} to work on and declared "
                f"{contract['page_id']} instead — a second page leaves neither findable")
        # And the names are the other half of identity: without the prefix a later attempt cannot
        # tell which candidate is which, which is the whole mechanism.
        want = {candidate_slug(expedition, i) for i in range(1, self.n + 1)}
        got = [c.get("name") or "" for c in (contract.get("candidates") or []) if isinstance(c, dict)]
        if stray := [g for g in got if not any(g.startswith(w) for w in want)]:
            violations.append(
                f"candidate frames must be named {sorted(want)[0]}… — found {stray}, which a "
                "later attempt cannot match to a candidate")
        cands = [
            WireframeCandidate(
                name=c.get("name") or f"candidate-{i}", node_id=c.get("node_id") or "",
                title=clean_title(c.get("title") or "", candidate_slug(expedition, i)),
                premise=c.get("premise") or "",
                url=file_url(self.file_key, c.get("node_id")) if c.get("node_id") else None)
            for i, c in enumerate(contract.get("candidates") or [], 1)
            if isinstance(c, dict)
        ]
        result = FigmaWireframeResult(
            passed=not violations, candidates=cands,
            page_name=contract.get("page_name") or page_slug(expedition),
            page_id=contract.get("page_id") or "", lint=contract.get("lint") or {},
            fewer_because=str(contract.get("fewer_because") or "").strip(),
            greyscale=self.policy.greyscale if self.policy else True,
            colour_reason=self.policy.reason if self.policy else "",
            violations=violations, calls=calls,
            detail=("; ".join(violations) if violations
                    else f"{len(cands)} candidates in {contract.get('page_name') or 'the file'}"))
        if artifact_dir:
            self.write_artifacts(result, artifact_dir)
        return result

    @staticmethod
    def write_artifacts(result: FigmaWireframeResult, artifact_dir: str) -> Path:
        """Persist the contract next to the expedition so the harness can serve it and a later run
        can see what was already built."""
        d = Path(artifact_dir) / "wireframes"
        d.mkdir(parents=True, exist_ok=True)
        (d / "figma.json").write_text(json.dumps({
            "page_name": result.page_name, "page_id": result.page_id, "lint": result.lint,
            "greyscale": result.greyscale, "colour_reason": result.colour_reason,
            "violations": result.violations,
            "candidates": [{"name": c.name, "node_id": c.node_id, "title": c.title,
                            "premise": c.premise, "url": c.url, "png": c.png_path}
                           for c in result.candidates],
        }, indent=2), encoding="utf-8")
        return d

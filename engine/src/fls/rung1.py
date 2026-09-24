"""Rung 1 — spec fan-out + reflection pass + judge rank (Ng#1: the highest-leverage loop).

Flow: builder drafts N candidate specs -> judge ranks them vs ANCHOR -> judge critiques the
top spec -> builder revises it ONCE (the reflection pass) -> return ranked specs with the top
revised. Cheap and it's the single biggest quality lift per Ng's 48->67->95 HumanEval point.

Builders default to claude-haiku (cost floor for paper-ladder specs); judges use the mini panel.
All model calls return (text, Call) so cost lands in the ledger. Stub-friendly for tests.

Yao's "theater fix" (v0.8 Phase 2): a spec's acceptance criteria are worthless as a gate if
they're prose a human has to eyeball at rung 4. The revised top spec's ACCEPTANCE section is
parsed into discrete criteria and COMPILED into a test-stub module — a machine-checkable form
(`Rung1Result.acceptance_stub`) that rung 4's `BoundedContext.acceptance_test` consumes directly.
This is also the rung-1 self-verify pre-check (Scott Wu, Phase 3): if the criteria don't parse
into checkable form, compilation fails CLOSED (`criteria_compiled=False`, `acceptance_stub=None`)
rather than silently pretending prose criteria are checkable — a caller MUST check
`criteria_compiled` before letting rung 1 advance past the (today unvetted) human/auto gate.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from fls.adjudicator import Idea, Judge
from fls.anchor import Anchor
from fls.llm import Call

# a "builder" has the same .complete signature as a judge
Builder = Judge

_SPEC_SYS = (
    "You are a product spec writer for a fidelity-ladder system. Write a TIGHT spec for the "
    "idea: user story, constraints, non-goals, and 2-4 checkable acceptance criteria. Under 150 "
    "words. Vary your approach from other candidates. End the spec with a line reading exactly "
    "'ACCEPTANCE:' followed by each criterion on its own line, numbered '1.', '2.', etc., each "
    "phrased as a single observable behavior (e.g. '1. Cmd-K focuses the search input from any "
    "screen state.'). This numbered section is REQUIRED and is parsed by machine — do not "
    "paraphrase it into a paragraph.\n\n"
    "IF THE IDEA DOES NOT CONTAIN A SPEC, SAY SO INSTEAD OF WRITING ONE. Some requests name no "
    "surface, no behaviour and no way to tell whether they were done — 'make it better and more "
    "modern' is a real thing people send and there is nothing in it to build. Asked for numbered "
    "criteria you will produce numbered criteria, inventing the specifics the request never had, "
    "and everything downstream will treat your invention as what the person asked for. Instead "
    "reply with exactly:\n"
    "    INSUFFICIENT: <one sentence naming what is missing>\n"
    "and nothing else. This is a correct answer, not a failure — the person gets asked for the "
    "missing detail while it is still cheap.\n\n"
    "IF ONE WORD IN THE REQUEST COULD NAME TWO DIFFERENT THINGS, ASK WHICH. 'Make it red' — "
    "which 'it'? 'Move the button' — in poker that is the dealer button AND a thing you tap. "
    "When the request does not settle it, do NOT pick one and do not invent a third: a person at "
    "the pick screen would be choosing your interpretation rather than their design, and every "
    "gate after that says yes because each one only checks the rung before it. Reply with "
    "exactly:\n"
    "    AMBIGUOUS: <one question naming the word and what you need to know>\n"
    "then 2 to 4 options, one per line, '(a) ...', '(b) ...', the last always "
    "'(x) something else', and nothing else.\n"
    "Ask ONLY about a REFERENT — which screen, which control, which feature. Never about scope, "
    "size, colour, wording or how to build it; those are yours to settle. If the request names "
    "the surface, do not ask. If CONTEXT below already contains THE PERSON ANSWERED, the referent "
    "is settled: write the spec and never ask again.\n\n"
    "END WITH ONE MORE LINE, after the ACCEPTANCE section, reading exactly:\n"
    "    SIZE: small|medium|large - <one short sentence saying why>\n"
    "small is a change one person reads in a sitting (about 400 changed lines), medium is two or "
    "three of those, large is more. Judge the WHOLE change including its tests. Nobody is held "
    "to this and nothing is refused for missing it — it is told to the person who asked, so they "
    "know what they are waiting for."
)

# The spec rung's declared refusal. Checked before the criteria are, because a spec that says it
# cannot be written must not then be judged on whether its acceptance section parses.
INSUFFICIENT = "INSUFFICIENT:"

AMBIGUOUS = "AMBIGUOUS:"

_OPTION = re.compile(r"(?m)^\s*\(?([a-zA-Z])[.)]\s+(\S.*?)\s*$")
_SOMETHING_ELSE = "something else"


@dataclass(frozen=True)
class AskedQuestion:
    """A referent rung 1 could not settle, and the readings it is choosing between."""
    ask: str
    options: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"ask": self.ask, "options": list(self.options)}

    @staticmethod
    def letter(i: int) -> str:
        return chr(ord("a") + i)


def ambiguous_question(spec: str) -> AskedQuestion | None:
    """The question a spec is asking instead of guessing, or None if it wrote a spec.

    Start-anchored exactly like `insufficient_reason`, and for the same reason: a spec that
    DISCUSSES an ambiguous state is a spec, and treating it as a question would throw away good
    work for a coincidence of vocabulary.
    """
    t = (spec or "").strip()
    if not t.upper().startswith(AMBIGUOUS):
        return None
    body = t[len(AMBIGUOUS):].strip()
    ask = body.splitlines()[0].strip() if body else ""
    options = [o.strip() for _, o in _OPTION.findall(body) if o.strip()]
    # The escape hatch is always last and always present: a person whose meaning is neither of
    # the readings offered must not be forced to pick one of them.
    options = [o for o in options if o.lower() != _SOMETHING_ELSE][:4]
    options.append(_SOMETHING_ELSE)
    return AskedQuestion(ask or "The request could mean more than one thing — which did you mean?",
                         tuple(options))


def resolve_answer(question: dict | AskedQuestion | None, raw: str) -> str:
    """What the person meant: the option they lettered, or their own words.

    People answer a lettered question with a letter, and the model that asked it is not holding
    the letters — so the letter is resolved HERE, where the question is, and the spec rung is
    handed a sentence rather than an initial.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    opts = list(question.options) if isinstance(question, AskedQuestion) else \
        list((question or {}).get("options") or [])
    if not opts:
        return text
    m = re.fullmatch(r"\(?\s*(?:option\s+)?([a-zA-Z]|\d+)\s*[.):]?\s*", text, re.I)
    if not m:
        return text
    token = m.group(1).lower()
    idx = int(token) - 1 if token.isdigit() else ord(token) - ord("a")
    if not 0 <= idx < len(opts):
        return text
    chosen = opts[idx]
    if chosen == _SOMETHING_ELSE:
        return "something else — they did not say what"
    return chosen


def answered_grounding(question: dict | None, raw: str) -> str:
    """The CONTEXT block a re-run of rung 1 sees. Without a question this is the raw text, which
    is what every other rung's feedback already is."""
    if not question:
        return raw or ""
    opts = list((question or {}).get("options") or [])
    lines = ["THE REQUEST WAS AMBIGUOUS AND THE PERSON WAS ASKED:",
             str(question.get("ask") or "")]
    lines += [f"  ({AskedQuestion.letter(i)}) {o}" for i, o in enumerate(opts)]
    resolved = resolve_answer(question, raw)
    lines.append(f"THE PERSON ANSWERED: {resolved}")
    if resolved != (raw or "").strip():
        lines.append(f'(they typed: "{(raw or "").strip()[:200]}")')
    lines.append("Treat this as settling the referent. Do NOT ask this question again; if it is "
                 "still unclear, write the spec for the closest reading and say so in the "
                 "constraints.")
    return "\n".join(lines)


_SIZE_LINE = re.compile(r"^\s*SIZE:\s*(small|medium|large)\b\s*[-–—:]?\s*(.*)$",
                        re.I | re.M)


def size_estimate(spec: str) -> tuple[str, str]:
    """(class, why) from a spec's SIZE line — ("medium", "") when it has none or it is garbage.

    MEDIUM IS THE DEFAULT ON PURPOSE. A missing estimate must not read as "small": the visitor
    would be told to expect one sitting and get three, which is worse than being told nothing.
    Nothing is refused for a missing or wrong estimate — see `rung4.SIZE_CLASSES`.
    """
    m = _SIZE_LINE.search(spec or "")
    if not m:
        return "medium", ""
    return m.group(1).lower(), " ".join(m.group(2).split())[:200]


def insufficient_reason(spec: str) -> str:
    """What the spec writer says is missing, or "" if it wrote a spec.

    Matched at the START of the reply, deliberately: a spec that merely MENTIONS the word while
    discussing edge cases is a spec, and treating it as a refusal would reject good work for a
    coincidence of vocabulary.
    """
    t = (spec or "").strip()
    if not t.upper().startswith(INSUFFICIENT):
        return ""
    return t[len(INSUFFICIENT):].strip().splitlines()[0].strip() if t[len(INSUFFICIENT):].strip() \
        else "the request does not say what to change"


_RANK_SYS = (
    "You rank candidate specs for one idea by how well each traces to the ANCHOR and how "
    "checkable its acceptance criteria are. Reply with a JSON array of spec indices, best first, "
    'e.g. [2,0,1]. Reply with the array only.'
)
_CRIT_SYS = (
    "You are a critical reviewer. In 2-3 bullet points, name the single most important weakness "
    "of this spec against the idea's success criteria and how to fix it. Be specific and terse."
)
_ARR = re.compile(r"\[[^\]]*\]")
_ACCEPTANCE_HEADER = re.compile(r"(?im)^\s*ACCEPTANCE:\s*$")
_ACCEPTANCE_ITEM = re.compile(r"(?m)^\s*\d+[.)]\s+(\S.*\S|\S)\s*$")


def extract_acceptance_criteria(spec: str) -> list[str]:
    """Pull the numbered criteria out of a spec's 'ACCEPTANCE:' section. Returns [] if the
    section is missing or has no parseable numbered lines — the honest, fail-closed signal that
    this spec's criteria are prose, not machine-checkable (Yao's theater fix)."""
    m = _ACCEPTANCE_HEADER.search(spec or "")
    if not m:
        return []
    tail = spec[m.end():]
    return [item.strip() for item in _ACCEPTANCE_ITEM.findall(tail) if item.strip()]


def _slug(text: str, n: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:6]
    return "_".join(words) or f"criterion_{n}"


def compile_acceptance_stub(criteria: list[str]) -> str | None:
    """Compile parsed criteria into a machine-checkable test-stub module (Yao's theater fix):
    one stub test function per criterion, each carrying its criterion text and a required-fix
    marker (NotImplementedError) so rung 4's builder must satisfy it with a REAL assertion, not
    prose. Returns None (fail-closed) if there are no criteria to compile — an empty stub would
    silently pass everything, which is worse than refusing.
    """
    if not criteria:
        return None
    lines = [
        '"""Rung-1 compiled acceptance criteria — machine-checkable stubs (Yao\'s theater fix).',
        "",
        "Each function below is ONE acceptance criterion. Rung 4's builder must replace the",
        "NotImplementedError with a real assertion that exercises the behavior. A verifier that",
        "still finds NotImplementedError raised is an unmet criterion, not a pass.",
        '"""',
        "",
    ]
    for i, criterion in enumerate(criteria, start=1):
        safe = criterion.replace('"""', "'''")
        lines.append(f"def test_criterion_{i}_{_slug(criterion, i)}():")
        lines.append(f'    """{safe}"""')
        lines.append(f'    raise NotImplementedError("unmet acceptance criterion: {safe}")')
        lines.append("")
    return "\n".join(lines)


@dataclass
class Rung1Result:
    specs: list[str]                 # candidate specs, index-aligned to generation order
    ranking: list[int]              # indices best-first
    top_index: int
    critique: str
    revised_top: str
    calls: list[Call] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)     # parsed from revised_top's ACCEPTANCE
    acceptance_stub: str | None = None                    # compiled test-stub module, or None
    size: str = "medium"                                  # small | medium | large — told, never enforced
    size_reason: str = ""
    question: AskedQuestion | None = None                 # set when the rung asked instead of guessing

    @property
    def declined(self) -> bool:
        """The rung answered with something other than a spec — a refusal or a question."""
        return bool(insufficient_reason(self.revised_top)) or self.question is not None

    @property
    def cost_usd(self) -> float:
        return round(sum(c.usd for c in self.calls), 4)

    @property
    def criteria_compiled(self) -> bool:
        """The rung-1 self-verify pre-check (Wu, Phase 3): True only if the revised spec's
        acceptance criteria parsed into a checkable stub. A caller MUST gate rung-1 advancement
        on this — False means the criteria are prose, not a machine-checkable gate for rung 4."""
        return self.acceptance_stub is not None


def run_rung1(idea: Idea, anchor: Anchor, builder: Builder, judge: Judge,
              n: int = 3, max_tokens: int = 320, grounding: str = "") -> Rung1Result:
    calls: list[Call] = []
    context = f"\n\nCONTEXT:\n{grounding}" if grounding.strip() else ""

    # 1. fan out N candidate specs
    specs: list[str] = []
    for i in range(n):
        text, call = builder.complete(
            f"Idea: {idea.intent}\nSuccess: {idea.success}{context}\nCandidate #{i+1}. Write the spec.",
            max_tokens=max_tokens, system=_SPEC_SYS,
        )
        specs.append(text.strip())
        calls.append(call)

    # A DECLINED CANDIDATE MUST NOT BE RANKED, CRITIQUED OR REVISED. "Rewrite the spec addressing
    # the critique" is an invitation to turn a refusal or a question INTO a spec, and the repair
    # step below would then bolt an ACCEPTANCE section onto whatever came back — so the rung would
    # answer a question it had just decided it could not answer.
    #
    # A majority deciding not to write one is the rung's answer: return it now, on three calls,
    # with no rank and no reflection. A single dissenter is not — two thirds of the panel wrote a
    # spec, so rank only those and let the winner through.
    declined = [i for i, text in enumerate(specs)
                if insufficient_reason(text) or ambiguous_question(text)]
    if len(declined) * 2 >= n:
        first = specs[declined[0]]
        return Rung1Result(specs, list(range(n)), declined[0], "", first, calls,
                           criteria=[], acceptance_stub=None,
                           question=ambiguous_question(first))

    # 2. judge ranks (cheap mini call) — prune-early: only the winner gets the reflection spend
    writable = [i for i in range(n) if i not in declined]
    numbered = "\n\n".join(f"[{i}]\n{specs[i]}" for i in writable)
    rtext, rcall = judge.complete(
        f"IDEA: {idea.intent}\nSuccess: {idea.success}\n\nCANDIDATES:\n{numbered}\n\nRank them.",
        max_tokens=64, system=_RANK_SYS,
    )
    calls.append(rcall)
    m = _ARR.search(rtext or "")
    try:
        ranking = [int(x) for x in json.loads(m.group(0))] if m else list(range(n))
    except (ValueError, TypeError):
        ranking = list(range(n))
    ranking = [i for i in ranking if i in writable] or list(writable)
    top = ranking[0]

    # 3. reflection pass: judge critiques the top spec, builder revises once
    ctext, ccall = judge.complete(
        f"IDEA: {idea.intent}\nSuccess: {idea.success}\n\nSPEC:\n{specs[top]}\n\nCritique it.",
        max_tokens=180, system=_CRIT_SYS,
    )
    calls.append(ccall)
    revised, vcall = builder.complete(
        f"Idea: {idea.intent}\nSuccess: {idea.success}{context}\n\nOriginal spec:\n{specs[top]}\n\n"
        f"Reviewer critique:\n{ctext}\n\nRewrite the spec addressing the critique. Keep it tight.",
        max_tokens=max_tokens, system=_SPEC_SYS,
    )
    calls.append(vcall)
    revised = revised.strip()

    # 4. self-verify pre-check (Wu, Phase 3): parse + compile the criteria BEFORE this result
    # can advance. One cheap repair attempt if the builder dropped the required ACCEPTANCE
    # section; otherwise fail closed (criteria_compiled=False) rather than fake a stub.
    criteria = extract_acceptance_criteria(revised)
    if not criteria:
        repair_text, rpcall = builder.complete(
            f"Idea: {idea.intent}\nSuccess: {idea.success}\n\nSPEC:\n{revised}\n\n"
            "This spec is missing its required 'ACCEPTANCE:' section. Reply with ONLY the "
            "ACCEPTANCE section: the line 'ACCEPTANCE:' followed by 2-4 numbered criteria.",
            max_tokens=120, system=_SPEC_SYS,
        )
        calls.append(rpcall)
        repair_criteria = extract_acceptance_criteria(repair_text or "")
        if repair_criteria:
            revised = revised + "\n\nACCEPTANCE:\n" + "\n".join(
                f"{i}. {c}" for i, c in enumerate(repair_criteria, start=1)
            )
            criteria = repair_criteria

    stub = compile_acceptance_stub(criteria)

    size, why = size_estimate(revised)
    # The revise step can still hand back a sentinel — it is the same model under the same system
    # prompt — so the last word is checked too, not just the fan-out's.
    return Rung1Result(specs, ranking, top, ctext.strip(), revised, calls,
                        criteria=criteria, acceptance_stub=stub, size=size, size_reason=why,
                        question=ambiguous_question(revised))

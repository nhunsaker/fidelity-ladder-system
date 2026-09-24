"""Rung 3 — a working prototype built from the design system, not from taste.

The reference rung-3 builder asks a model for an HTML document and takes what comes back. This one
runs an agentic session that **writes files to disk** and is then judged on those files:

* **The artifact is the evidence.** The session writes `index.html` and `walkthrough.json` itself.
  Nothing is parsed out of its final message except a short note, and nothing it claims is believed —
  a builder that says "done, tokens applied" while the file hardcodes hexes fails here, because the
  check reads the file. This is the same rule the rung-4 verifier applies to tests.
* **The design system is the constraint.** The pack (tokens, components, rules) is the rung's
  reading material, and the lint afterwards asks whether the pack was actually used: are its tokens
  referenced, do its component classes appear, and — the check that catches the most real drift —
  does the page hardcode a value that the pack already has a token for.

What the lint deliberately does NOT do is judge whether the screen is any good. That is the human's
job at the gate, which is why this rung parks at `AWAIT_APPROVE` rather than auto-advancing.

The session's budget is turns and wall clock, from the ANCHOR `worker:` block. Nothing here reads a
credential.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from fls.claude_code import ClaudeCodeSession
from fls.llm import Call

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"

# The tools a rung-3 session may use: write the two files, read back what it wrote. It has no
# network, no shell, and no design-tool access — everything it needs is in the prompt.
PROTOTYPE_TOOLS = ("Write", "Read", "Edit")

INDEX = "index.html"
WALKTHROUGH = "walkthrough.json"

_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
_VAR = re.compile(r"var\(\s*(--[\w-]+)")
_EXTERNAL = re.compile(
    r"""<(?:script[^>]*\ssrc|link[^>]*\shref)\s*=\s*["'](?!data:)(https?:)?//""", re.I)
_DIV_CLICK = re.compile(r"<(div|span)\b[^>]*\bonclick\b", re.I)
_OUTLINE_NONE = re.compile(r"outline\s*:\s*(none|0)\b", re.I)

_SYSTEM = """You build ONE self-contained prototype screen from a design system you are given.

Write these two files into your working directory, with the Write tool:
  index.html         the whole prototype: inline <style> and <script>, no imports, no network
  walkthrough.json   {"steps": [{"action": "click"|"assert", "selector": "...", "expect": "..."}]}

Every walkthrough selector MUST appear LITERALLY IN THE TEXT of the index.html you wrote. The
check greps the file; it does not run your page. So an id your JavaScript builds at runtime —
`id="streak-" + drill.id` giving `#streak-d5` — is not there as far as the check is concerned,
and the run is parked even though the id would exist in a browser. If the walkthrough touches it,
give it a STATIC id that you type out in full somewhere in the file.

CHECK IT by re-reading the file with the Read tool and finding each id and class you referenced —
not from memory, and not with a command. YOU HAVE NO SHELL: Write, Read and Edit are the only
tools you have. Expedition 45 spent three turns discovering that, gave up verifying, and wrote a
walkthrough targeting six seats it had never rendered. Expedition 53 did re-read the file and
still lost the rung, because it had been told the rule and not how the rule is checked.

The page is then checked MECHANICALLY against the rules below, and any one of them parks the run.
They are listed here because they used to be enforced and never stated — a prototype was judged
against a rubric it had not been shown, and runs died at "Previewed" over a missing tag:

  - compose the UI from the design system's own component classes; do not hand-roll it
  - exactly one <h1>, and headings in order
  - lang on <html>
  - actions are <button>, destinations are <a> — never onclick on a <div> or <span>
  - if you clear a focus outline, draw a visible one back with :focus-visible

Do not print the page in your reply — write it to the file. Your final message is a SHORT note: what
you built, and anything in the design system you could not satisfy. Declare gaps honestly; the files
are checked mechanically either way, so a false clean only wastes the human's review."""


@dataclass
class PrototypeResult:
    passed: bool
    html_path: str = ""
    walkthrough_path: str = ""
    steps: list[dict] = field(default_factory=list)
    tokens_used: list[str] = field(default_factory=list)
    components_used: list[str] = field(default_factory=list)
    note: str = ""
    violations: list[str] = field(default_factory=list)
    detail: str = ""
    calls: list[Call] = field(default_factory=list)

    def artifacts(self) -> dict:
        """What the demo view shows for this rung."""
        return {"prototype": {
            "html": self.html_path, "walkthrough": self.walkthrough_path,
            "steps": self.steps, "tokens_used": self.tokens_used,
            "components_used": self.components_used, "note": self.note,
            "violations": self.violations}}


# ── the pack ────────────────────────────────────────────────────────────────────────────────

def load_pack(pack_path: str | Path) -> dict:
    """The design pack as data. A generated artifact committed next to the app, so a build needs no
    live design connection and every run sees the same system."""
    return json.loads(Path(pack_path).read_text(encoding="utf-8"))


def pack_tokens(pack: dict) -> dict[str, str]:
    """Flatten the pack's grouped tokens to {cssVar: value}. The grouping is for humans reading the
    pack; everything mechanical here wants the flat map."""
    out: dict[str, str] = {}

    def walk(node) -> None:
        if isinstance(node, dict):
            if "var" in node and "value" in node:
                out[str(node["var"])] = str(node["value"])
                return
            for v in node.values():
                walk(v)

    walk(pack.get("tokens") or {})
    return out


def pack_component_classes(pack: dict) -> list[str]:
    return [c["class"] for c in (pack.get("components") or [])
            if isinstance(c, dict) and c.get("class")]


def render_pack(pack: dict, budget_chars: int) -> str:
    """The pack as the rung's reading material, trimmed to the rung's budget.

    Ordered by what a builder cannot invent: the rules it must not break, then the components it
    must compose from, then the tokens it must reference. Tokens are last because they are the part
    that degrades most gracefully when truncated — a missing token is visible in the lint, whereas a
    missing rule is a defect nobody catches until the human sees it.
    """
    parts = [f"DESIGN SYSTEM: {pack.get('name', 'unnamed')} ({pack.get('id', '')})"]
    if pack.get("premise"):
        parts.append(f"PREMISE: {pack['premise']}")
    if pack.get("rules"):
        parts.append("RULES (these outrank your taste):\n"
                     + "\n".join(f"- {r}" for r in pack["rules"]))
    if pack.get("refuses"):
        parts.append("THIS SYSTEM REFUSES: " + "; ".join(pack["refuses"]))
    comps = []
    for c in pack.get("components") or []:
        if not isinstance(c, dict):
            continue
        line = f"- {c.get('name')} (class `{c.get('class')}`) — {c.get('role', '')}"
        if c.get("variant_classes"):
            line += "\n    variants: " + ", ".join(
                f"{k}=`{v}`" for k, v in c["variant_classes"].items())
        if c.get("usage"):
            line += f"\n    {c['usage']}"
        comps.append(line)
    if comps:
        parts.append("COMPONENTS (compose from these; do not invent lookalikes):\n"
                     + "\n".join(comps))
    toks = pack_tokens(pack)
    if toks:
        parts.append("TOKENS (declare in :root, then reference with var(); never hardcode a value "
                     "this list already carries):\n"
                     + "\n".join(f"  {k}: {v};" for k, v in toks.items()))
    if pack.get("voice"):
        parts.append("VOICE: " + json.dumps(pack["voice"]))
    text = "\n\n".join(parts)
    return text if len(text) <= budget_chars else text[:budget_chars]


def reading(names: tuple[str, ...], budget_chars: int) -> str:
    texts = []
    for n in names:
        p = PROMPTS / n
        if p.exists():
            texts.append((n, p.read_text(encoding="utf-8")))
    if not texts:
        return ""
    share = max(400, budget_chars // len(texts))
    return "\n\n".join(f"## {n}\n{t[:share]}" for n, t in texts)


# ── the lint: read the files, believe nothing ───────────────────────────────────────────────

def lint_prototype(html: str, steps: list[dict], pack: dict) -> tuple[list[str], list[str], list[str]]:
    """Check the written page against the system it was built from.

    Returns (violations, tokens_used, components_used). Every check is deterministic and reads the
    artifact — none of them consults what the session said about its own work.
    """
    v: list[str] = []
    toks = pack_tokens(pack)

    if not html.strip():
        return ["index.html is empty"], [], []

    # Self-contained. A prototype that needs the network is not one a reviewer can open later.
    if _EXTERNAL.search(html):
        v.append("index.html loads an external script or stylesheet — the prototype must be "
                 "self-contained")

    # The tokens it was given: referenced at all, and not bypassed.
    used = sorted({m for m in _VAR.findall(html) if m in toks})
    if not used:
        v.append("no design token is referenced — the prototype does not use the system it was "
                 "built from")

    # The check that catches the most real drift: a literal that duplicates a token's value.
    by_value = {}
    for name, value in toks.items():
        if _HEX.fullmatch(value.strip()):
            by_value.setdefault(value.strip().lower(), name)
    # Ignore the :root block, which is where the token layer is legitimately declared as literals.
    body = re.sub(r":root\s*\{.*?\}", "", html, flags=re.S)
    hardcoded = sorted({
        f"{h.lower()} (use {by_value[h.lower()]})"
        for h in _HEX.findall(body) if h.lower() in by_value
    })
    if hardcoded:
        v.append("hardcoded values that the system already has tokens for: " + ", ".join(hardcoded))

    # The components it was given.
    classes = pack_component_classes(pack)
    comps = sorted({c for c in classes if re.search(rf"\b{re.escape(c)}\b", html)})
    if classes and not comps:
        v.append("none of the design system's components appear — the prototype hand-rolled its UI")

    # The accessibility floor, the parts a regex can honestly judge.
    if _DIV_CLICK.search(html):
        v.append("a <div> or <span> carries onclick — actions are <button>, destinations are <a>")
    # Removing an outline is only a defect when nothing visible replaces it. A page that clears the
    # default and then draws its own :focus-visible outline is doing the right thing.
    replaced = re.search(r":focus(?:-visible)?[^{]*\{[^}]*(outline\s*:\s*(?!none|0)|box-shadow\s*:)",
                         html, re.I)
    if _OUTLINE_NONE.search(html) and not replaced:
        v.append("a focus outline is removed with nothing visible replacing it")
    if not re.search(r"<html[^>]*\blang\s*=", html, re.I):
        v.append("<html> has no lang attribute")
    if not re.search(r"<h1\b", html, re.I):
        v.append("the page has no <h1>")

    # The walkthrough has to describe THIS page.
    if not steps:
        v.append("walkthrough.json declares no steps — nothing can replay the flow")
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            v.append(f"walkthrough step {i} is not an object")
            continue
        sel = (s.get("selector") or "").strip()
        if not sel:
            v.append(f"walkthrough step {i} has no selector")
            continue
        if not _selector_present(sel, html):
            v.append(f"walkthrough step {i} targets {sel!r}, which is not in the page")
    return v, used, comps


def _selector_present(selector: str, html: str) -> bool:
    """Is a simple CSS selector's anchor present in the document?

    Deliberately shallow — an id, a class, an attribute or a tag. A real CSS engine would be more
    accurate, but the failure this catches is the builder inventing a selector wholesale, and that
    shows up in the shallow check. Anything more complex is given the benefit of the doubt rather
    than failed on a parser's limits.
    """
    s = selector.strip()
    if m := re.match(r"^#([\w-]+)$", s):
        return bool(re.search(rf"""id\s*=\s*["']{re.escape(m[1])}["']""", html))
    if m := re.match(r"^\.([\w-]+)$", s):
        return bool(re.search(rf"""class\s*=\s*["'][^"']*\b{re.escape(m[1])}\b""", html))
    if m := re.match(r"^\[([\w-]+)(?:[~^$*|]?=.*)?\]$", s):
        # Match the attribute inside a tag, with or without a value: `data-pot` and `data-pot="x"`
        # are both present, and requiring the `=` would fail every valueless attribute.
        return bool(re.search(rf"<[^>]*\b{re.escape(m[1])}\b", html))
    if m := re.match(r"^([a-zA-Z][\w-]*)$", s):
        return bool(re.search(rf"<{re.escape(m[1])}\b", html, re.I))
    return True


def picked_wireframe(artifact_dir: str | Path, picked: int | None) -> str:
    """The rung-2 candidate the human chose, as text for the rung-3 prompt.

    Read from the artifact rung 2 wrote rather than passed down the call chain: the pick is a human
    decision recorded on disk, and reading it back is what makes rung 3 build the frame that was
    actually approved instead of whichever one it would have preferred. Returns "" when there is no
    rung-2 artifact, which is the honest answer for an expedition that skipped it.
    """
    f = Path(artifact_dir) / "wireframes" / "figma.json"
    if not f.exists():
        return ""
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    cands = data.get("candidates") or []
    if not cands:
        return ""
    # `picked` is 1-based in the command protocol (`/pick 2`); fall back to the first candidate
    # rather than guessing, and say which one was used.
    i = (picked - 1) if isinstance(picked, int) and 1 <= picked <= len(cands) else 0
    c = cands[i] if isinstance(cands[i], dict) else {}
    lines = [f"candidate: {c.get('name', f'candidate-{i + 1}')}"]
    for key, label in (("title", "title"), ("premise", "premise"), ("url", "frame")):
        if c.get(key):
            lines.append(f"{label}: {c[key]}")
    if data.get("page_name"):
        lines.append(f"page: {data['page_name']}")
    return "\n".join(lines)

class PrototypeBuilder:
    """Build the rung-3 prototype from the design pack. `session_factory(tools=…)` returns a
    `ClaudeCodeSession`; injecting it keeps this testable without a CLI."""

    def __init__(self, pack_path: str | Path, session: ClaudeCodeSession | None = None,
                 session_factory=None,
                 sources: tuple[str, ...] = ("fe_build_rules.md",)):
        if session is None and session_factory is None:
            raise ValueError("PrototypeBuilder needs a session or a session_factory")
        self.pack_path = Path(pack_path)
        self.session = session
        self.session_factory = session_factory
        self.sources = sources

    def _session(self, cwd: str) -> ClaudeCodeSession:
        if self.session is not None:
            return self.session
        return self.session_factory(tools=PROTOTYPE_TOOLS, cwd_=cwd)

    def prompt(self, spec: str, wireframe: str = "", feedback: str = "",
               budget_chars: int = 6000) -> str:
        pack = load_pack(self.pack_path)
        # Two thirds of the budget to the system itself, one third to how to build with it: the
        # rules file is fixed text the model has effectively seen before, the pack is not.
        parts = [
            f"WHAT THE USER ASKED FOR:\n{spec.strip()}",
        ]
        if wireframe.strip():
            # Whole. It is the one thing a person chose, and a slice of it at 1,500 characters
            # was the same kind of quiet cut as the reading budget's.
            parts.append("THE WIREFRAME THE HUMAN PICKED — build THIS layout, not another one:\n"
                         + wireframe.strip())
        if feedback.strip():
            parts.append("THE HUMAN REVIEWED YOUR LAST ATTEMPT AND ASKED FOR CHANGES. This is the "
                         f"whole reason you are running again:\n{feedback.strip()}")
        parts.append(render_pack(pack, (budget_chars * 2) // 3))
        r = reading(self.sources, budget_chars // 3)
        if r:
            parts.append(f"HOW TO BUILD IT (follow these):\n{r}")
        return "\n\n".join(parts)

    def build(self, expedition: int, spec: str, wireframe: str = "", feedback: str = "",
              budget_chars: int = 6000, artifact_dir: str | None = None,
              log_path: str | None = None) -> PrototypeResult:
        # The session writes into the expedition's own demo directory, which is exactly where
        # `GET /preview/{n}` serves from — so a passing rung is previewable with no copy step.
        d = Path(artifact_dir or ".") / "demo"
        d.mkdir(parents=True, exist_ok=True)
        session = self._session(str(d))
        if log_path:
            session.log_path = log_path
        res = session.run(self.prompt(spec, wireframe, feedback, budget_chars), system=_SYSTEM)
        calls = [res.call]
        if res.timed_out:
            return PrototypeResult(False, detail=(
                f"the prototype session hit its {session.timeout_s}s wall clock before writing "
                "its files"), calls=calls)

        html_file, wt_file = d / INDEX, d / WALKTHROUGH
        if not html_file.exists():
            return PrototypeResult(False, detail=f"the session wrote no {INDEX}", calls=calls)
        html = html_file.read_text(encoding="utf-8", errors="replace")

        steps: list[dict] = []
        wt_error = ""
        if wt_file.exists():
            try:
                data = json.loads(wt_file.read_text(encoding="utf-8"))
                steps = data.get("steps") or [] if isinstance(data, dict) else []
            except json.JSONDecodeError as e:
                wt_error = f"{WALKTHROUGH} is not valid JSON ({e})"
        else:
            wt_error = f"the session wrote no {WALKTHROUGH}"

        violations, used, comps = lint_prototype(html, steps, load_pack(self.pack_path))
        if wt_error:
            violations = [wt_error, *violations]

        return PrototypeResult(
            passed=not violations, html_path=str(html_file), walkthrough_path=str(wt_file),
            steps=steps, tokens_used=used, components_used=comps,
            note=(res.text or "").strip()[:800], violations=violations, calls=calls,
            detail=("; ".join(violations) if violations else
                    f"prototype in {INDEX}: {len(used)} tokens, {len(comps)} components, "
                    f"{len(steps)} walkthrough steps"))

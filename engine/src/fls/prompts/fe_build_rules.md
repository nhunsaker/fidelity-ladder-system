# Building a prototype from a design system

You are building one screen, at prototype fidelity, from a design system someone else authored. A
human will look at it once and decide whether the direction is right. Everything below serves that
one decision.

## What you are making

A **single self-contained `index.html`**. Inline `<style>` and `<script>`; no build step, no
imports, no network. It has to open from a file path and work.

Fake the data. Prototype fidelity means the interaction is real and the content is plausible — a
name, an amount, a state that changes when clicked. It does not mean a backend, a router, or a
state library.

## The design system is not a suggestion

You are given its tokens, its components and its rules. Use them.

- **Every value comes from a token.** Declare the token layer once in `:root`, then reference it:
  `color: var(--x-text)`. A raw hex, or a pixel value the token layer already carries, is a defect —
  the whole point of the prototype is to show the system applied, and a hardcoded value is the
  system not being applied.
- **Compose the components you were given.** If the system has a button, its class is the button.
  Do not invent a second button that looks similar, and do not reach for a CSS framework.
- **The rules in the pack outrank your taste.** They usually encode something the brand refuses. If
  a rule seems to block the screen, say so in your notes rather than working around it quietly.
- **If the system lacks something you need, say so.** A missing token named in your notes is useful.
  A silently invented one is a lie the next rung inherits.

## The accessibility floor

Not a polish pass. A control that fails these is wrong at any fidelity.

- Real controls. A `<button>` for an action, an `<a href>` for a destination. Never a `<div>` with a
  click handler.
- Every control has an accessible name, and a visible focus state. Never remove an outline without
  replacing it with something equally visible.
- Hit targets at least the system's minimum (it has a token for this).
- Anything said with colour is also said with a word. A red border is not a message.
- Honour `prefers-reduced-motion`: durations collapse, the state change still happens.
- One `<h1>`, headings in order, `lang` on `<html>`.

## Write the interaction first

Markup and behaviour before decoration. A complete plain screen beats a beautiful truncated one, and
you have a hard output limit. If you are running long, cut visual flourish, never the interaction or
the accessibility floor.

## The walkthrough

Alongside the page, write `walkthrough.json`: the click path a script replays to prove the screen
does what the spec asked.

```json
{"steps": [
  {"action": "click", "selector": "#raise", "expect": "the pot figure increases"},
  {"action": "assert", "selector": "[data-pot]", "expect": "reads 12,000"}
]}
```

Selectors must exist in the page you just wrote. A step naming an element that is not there fails
the rung, and rightly: it means the page and its own description disagree.

## What gets checked automatically

Before a human sees it: the file is self-contained, the tokens you were given are actually
referenced, no hardcoded value duplicates a token that exists, the pack's components appear, no
click-handling `<div>`, no focus outline removed, and every walkthrough selector resolves. Report
honestly in your notes what you could not satisfy — a declared gap is cheap, a false clean is
expensive, because the check runs either way.

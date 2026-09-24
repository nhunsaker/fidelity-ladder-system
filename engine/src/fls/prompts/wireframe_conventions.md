# Figma wireframe conventions — operational digest

What a wireframe rung must produce, and how to build it so the result is usable rather than merely
viewable. Read alongside whatever usability and pattern references the instance supplies: those
govern what to draw, this governs how it is constructed.

## What a wireframe is at this fidelity

A wireframe answers layout and flow questions, not visual ones. It commits to: what is on the
screen, what order it reads in, what the user can act on, and what happens next. It deliberately
does not commit to brand color, final type, imagery, or motion. If a reviewer's feedback is about
a hue, the wireframe was drawn at the wrong fidelity.

Three candidates should differ in a way a human can choose between in under a minute. Differing by
spacing is not a choice. Differing by structure is: a modal versus an inline panel versus a new
screen; a single step versus two; the primary action at the top versus at the bottom.

## Construction rules (these make the file usable, not just viewable)

1. **Every frame is a Frame, never a Group.** Groups have no layout, no constraints, and no
   padding. A grouped "wireframe" cannot be resized or handed to anyone.
2. **Auto layout on every container.** Vertical stack for a screen, horizontal for a row. Set
   padding and item spacing explicitly. A frame without auto layout is a picture of a layout, not a
   layout.
3. **One artboard size per candidate set.** Desktop 1440 wide or mobile 390 wide, chosen once and
   held across all candidates so a reviewer compares structure, not scale.
4. **Real text, never lorem.** Write the actual label, the actual heading, the actual empty state.
   Placeholder text hides the hardest design problem, which is usually the words.
5. **Name every layer for a human.** `results-header`, `share-button`, `modal-share`. A canvas of
   `Frame 47` is unreviewable and unmaintainable by the next agent run.
6. **Grey box scale, deliberately.** Fill 0xF5 for surfaces, 0xE0 for cards, 0x9E for image or
   media placeholders, 0x21 for text. No brand color at this rung. Contrast still has to hold, so
   text on a fill must stay legible.
7. **Show state, not just the happy path.** If the screen can be empty, loading, or in error, put
   the notable ones on the canvas next to the default, labelled.
8. **Annotate off-canvas.** Notes go in a text layer to the right of the frame, never inside it.
   Anything inside the frame reads as part of the design.
9. **One page per expedition.** Name it for the expedition and put the candidates in a row with a
   title above each. The page is the deliverable; the reviewer should need no orientation.
10. **No detached instances, no external components.** At this fidelity the frames are
    self-contained so nothing breaks when a library changes.

## What a reviewer should be able to do

Open the page cold and, without explanation: name what each candidate proposes, spot the
difference between them, and point at the one to build. If they have to ask which is which, the
naming or the titling failed, not the design.

## Accessibility at wireframe fidelity

Structure carries most of the accessibility outcome, so it is decided here, not later. Heading
order must be sensible top to bottom. Tap or click targets must be drawn at a real size, not a
label floating in space. Focus order follows the visual order. Anything conveyed by position or
color alone needs a text label as well. A wireframe that hides these decisions ships them
unexamined.

## Common failures in agent-generated Figma work

Frames nested three deep for no reason. Auto layout applied to the outer frame only, so the inner
content does not reflow. Text layers set in a size that does not exist in any scale. Candidates
that are the same layout with items reordered. Annotations placed inside the frame. Naming that
describes the shape (`rect-3`) instead of the role (`price-row`).

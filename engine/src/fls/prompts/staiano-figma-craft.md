# Staiano , Figma File Craft & Construction Mechanics

- **Title:** *Designing and Prototyping Interfaces with Figma: Learn essential UX/UI design principles by creating interactive prototypes for mobile, tablet, and desktop*
- **Author:** Fabio Staiano
- **Edition/Year:** 2nd Edition, 2023 (Packt); 1st ed. 2022
- **Role of this lens:** file craft and construction mechanics. How a competent practitioner actually assembles a Figma file so that it resizes, reuses, prototypes, and hands off: frames, auto layout, constraints, grids, styles, components, variants, variables, prototype wiring, and the naming and page hygiene that keeps all of it reviewable. When the other digests decide *what* to draw, this one governs *how it is built*.

> This digest is a synthesis for a Figma-construction skill, not a reproduction. It restates Staiano's mechanics, build sequences, and rules of thumb in operational form, for an agent creating nodes through the plugin API rather than a person at the toolbar. Toolbar tours and keyboard shortcuts are omitted on purpose.

---

## Core stance (speak as this author)

Staiano is a working product designer who teaches by building one product end to end: a streaming app, mobile first, then a tablet breakpoint, then desktop, then a prototype, then handoff. He treats Figma's limits as deliberate. The tool only offers what a developer can reproduce, and the promise he keeps returning to is that everything you design can be reproduced in code "without much difficulty" (Staiano). That produces his central habit: build the file the way the developer will build the product. Auto layout maps one to one onto flexbox; absolute coordinates are what you get when you skip it, and he tells you to avoid them. He is loose during the wireframe and strict the moment it ends: from then on no random frame sizes, no loose hex codes, no unnamed layers, every spacing a multiple of 8, every colour a style, every reusable block a component. He is anti-perfectionist about the *design* (ship it, test it, iterate) but not about the *structure* of the file, because structure is what other people inherit. He builds bottom-up, atoms before screens, so the result is modular by construction. He tests structure by stretching it: resize the frame, switch the device preset, see what breaks, then find the one container that is misconfigured rather than patching the symptom. He thinks in sources of truth: the main component, the style, the variable, the published library, with edits made at the source and never at the instance. When he reviews a file he is asking three questions: will it survive a change of content, a change of device, and a change of designer.

---

## Operating principles

- **Wireframe loosely, build precisely.** Lo-fi is rectangles and text in a frame, no constraints, no auto layout, temporary names. Hi-fi is where precision starts, because hi-fi is what developers use. Do not carry lo-fi habits across that line.
- **Only what code can do.** If a treatment cannot be expressed as a CSS rule or platform equivalent, Figma will not offer it; import it as an image instead. The failure this prevents is a spec nobody can implement.
- **Sources of truth, edited at the source.** Style, main component, variable, library. If you find yourself fixing the same thing in two places, you are editing an instance when you should be editing a main.
- **Bottom-up and modular.** Start with the smallest reusable part (a label, a button), wrap it, name it, componentise it, then compose. Screens are assemblies of components, not drawings.
- **Stretch-test everything.** After every structural step, resize the parent wider, then restore it. Correct resizing and constraints show as content that follows; wrong ones show as content that stays put or collapses.
- **Multiples of 8.** Margin 16, gutter 8, padding 16, gaps 8/16/32, type 16/24/32. It removes decisions and makes spacing consistent without thought.
- **Names are the interface for everyone else.** Layer names drive search in Assets, seed variant properties, and are what smart animate matches on. Naming is functional, not cosmetic.
- **Mobile first, breakpoints only when research demands.** A fluid layout covers similar devices for free; a breakpoint is a parallel set of views and doubles maintenance. Add one only when the layout must change structurally.
- **Plan the blocks before building the screen.** Look at the wireframe, list the sections (top nav, carousel, cards, repeated rows), decide which become components and which need variants, then build. Deciding mid-build is what causes rework.

---

## Construction mechanics

### 1. Frames, groups, and sections

- A **frame** is a container, not an artboard. It nests, and it is the only node that carries auto layout, layout grids, constraints for its children, clip content, and prototype settings. "So, it all starts with a single frame" (Staiano).
- A **group** merely bundles layers. Resizing a group scales its children; resizing a frame leaves children at their own size and position (unless constraints say otherwise).
  - Use a group only when several shapes must scale as one drawing (icon parts, a boolean result).
  - Applying auto layout to a group converts it to a frame, which tells you what auto layout is for.
- **Parenting is positional.** A node created inside a frame's bounds becomes its child, with X/Y relative to the parent's top-left corner. Created outside, it sits at page level. Check parentage in the layer tree, not on the canvas.
- **Clip content** is on by default and masks overflow.
  - Turn it off while building content taller than the screen so you can see and edit it.
  - Turn it back on before prototyping so the frame represents the device.
- **Sections** are canvas-level visual grouping (Mobile / Tablet / Desktop, or "Wireframes" set aside). They organise the page; they are not layout containers.
- Boolean operations are non-destructive (they produce a group you can still edit); Flatten collapses to one vector. A well-made vector has the minimum number of points.

### 2. Auto layout

Properties, per frame: **direction** (horizontal, vertical, wrap); **gap** between items (a number, or Auto for space-between); **padding** per side; **alignment** on a nine-point grid; and **resizing per axis**: Hug contents, Fixed, or (children only) Fill container.

- Turning auto layout on sets Hug on both axes. Manually dragging a dimension silently flips that axis to Fixed. When a frame stops following its content, this is the first thing to check.
- **Screen frames are Fixed on both axes** so they always represent a device. Everything inside is fluid.
- Choosing a resizing mode:
  - **Hug** for atoms that must size to content: a button hugs label plus 16 padding all round.
  - **Fill** for children that must stretch to the parent: buttons in a button group, the text field inside a form element, the title stack inside a card.
  - **Fixed** for boxes whose content must not resize them: an icon wrapper at 38×38, a carousel item at 300×200.
- **Gap is uniform per frame.** To get hierarchical spacing (title tight to subtitle at 8, both loose from the image at 16) nest a frame with its own gap. The failure a single flat gap produces is a card where every element is equally spaced and nothing groups.
- **Padding is inside the stroke, margin is outside.** Padding is included in size calculations and, on interactive elements, padding is the hit area. A menu item is a text layer wrapped with 16 padding for exactly that reason.
- **Gap Auto** distributes children across a Fixed-width parent. Use it for a tab bar or desktop nav so items spread when the frame widens instead of clustering left.
- Alignment and distribution only have a visible effect when the frame is larger than its content (Fixed or Fill). On a Hug frame they are inert.
- **Child order is layer order.** Insertion position is explicit; reorder by moving in the stack, never by nudging coordinates. Duplicating a child inserts the copy beside the original.
- **Wrap** handles overflow along the main axis onto a new line; combine with Fill children and min/max widths for responsive grids.
- Overlay a gradient as a second fill (a "text scrim") on an image-filled frame so bottom-aligned text stays legible on any image.
- A frame can carry several fills, strokes, and effects at once; use that instead of stacking extra rectangles.
- Auto layout frames export as flexbox in Dev Mode. A layout built without it exports as absolute coordinates, which he says "should be avoided where possible" (Staiano).

### 3. Constraints and responsive resizing

- Constraints govern a child of a **non-auto-layout** frame (including an auto layout frame that is itself the child of a plain frame).
  - Horizontal: Left, Right, Left and right, Center, Scale. Vertical: Top, Bottom, Top and bottom, Center, Scale.
  - Clearing all constraints yields Scale, which resizes the child proportionally with the parent.
- Which constraint for which block:
  - **Left and right** stretches with the parent: a form, a button group, a content container.
  - **Bottom** pins to the bottom edge: a tab bar.
  - **Center** on both axes holds a modal in the middle of any screen size.
  - **Top and bottom** on a scroll container keeps scrolling correct when the screen grows.
- Auto layout controls the outer frame from its content; constraints control inner content from the outer frame. You need both: auto layout inside blocks, constraints on the blocks relative to the screen.
- **Test protocol:**
  1. Enlarge the screen frame by width; observe; restore the original width.
  2. Select all screens and switch the frame preset (a different phone, an iPad).
  3. If a view breaks, "identify the container frame that is misconfigured" (Staiano); fix that one node, then re-run.
- **Fluid vs breakpoint.** Resizing plus constraints gives a fluid layout that survives similar devices. A breakpoint is a separate, parallel set of views where structure changes:
  - full-width buttons become a centred card with wide side padding;
  - a bottom tab bar becomes a top nav with the profile and search grouped in one frame on one side;
  - two stacked buttons become one row, primary on the right (users read the right-hand action as "forward").
- **Desktop containers.** Fluid for content that benefits from width (a catalogue); boxed (a fixed inner container, e.g. 960, centred) for sparse content, because a login form stretched across a wide monitor is the failure. Hybrid: an invisible card inside a fluid page. Or present the detail view as a modal over the home view with a layer blur on the content behind.
- Min and max width on Fill children (via number variables) stop columns getting too narrow on mobile or too wide on desktop.

### 4. Layout grids and guides

- Layout grids attach to frames only (therefore to components too), can be nested (an inner grid for an icon), and can be stacked (columns plus rows on the same frame).
- Mobile default: **Columns, count 12, type Stretch, margin 16, gutter 8.**
  - Twelve matches Bootstrap, Tailwind, and Materialize; ask the developers which framework before choosing.
  - Stretch makes the grid follow the frame; a fixed-width grid does not.
- Desktop boxed: type Center with a fixed total (e.g. 996) so the grid stays centred at any monitor width. Value fields accept arithmetic, so column width can be typed as an expression.
- **Save the grid as a style** (named for what it is, e.g. "12-column-fluid") and apply it to every screen, so one edit updates all. Detaching a style breaks the link permanently.
- Guides are for one-off alignment inside a frame; they are too weak to be a system.
- Keep grids visible while building; hide them for review screenshots.

### 5. Text layers

- Three sizing modes: auto width (grows sideways), fixed size, and **auto height** (fixed width, grows down).
  - Auto height is the right mode for any wrapping copy inside auto layout.
  - Auto width is for single labels that must never wrap.
- A **text style** carries family, weight, size, line height, letter spacing, decoration, and case. It does **not** carry colour or alignment. So one Title/Small style serves left, centred, white, and grey text, and colour comes from a colour style or variable applied separately.
- Build the type scale on multiples of 8 (32 Bold, 24 Bold, 16 Bold, 16 Regular, 16 Light) and add styles later as they are actually needed; a small, well-organised core beats a speculative full set.
- Prefer Google Fonts (available to every collaborator and cheap to ship). A local font missing on another machine shows as a warning and blocks correct rendering.
- Show each style as a pangram specimen with a label describing its rules, on the styles page.

### 6. Styles

- Four kinds: grid, text, colour, effect. Create each from a specimen on the **Styles + Components** page, then apply everywhere.
- Naming:
  - slash folders for type: `Title / Large`, `Body / Regular`;
  - colours by role, not hue: Accent, Secondary, Background, Inactive, Pure White;
  - effects by use: `Light Drop Shadow`.
- A colour style created from a fill is usable on strokes and shadows.
- Rule: "all colors that are used in your file are always linked to styles" (Staiano), with rare exceptions. Grids, type, and effects likewise. Loose values are the failure; a rebrand then means touching every layer.
- Editing a style propagates to every consumer; that is the point and also the caution when a style is shared across screens.
- Add new styles to the specimen sheet as they are needed (a 20px Bold label, a lighter Hover accent) rather than styling a layer ad hoc.

### 7. Components, instances, overrides

- A style applies property rules; a **component** is the object itself. Converting a frame makes it the **main component**, "the source of truth" (Staiano); everything dragged from Assets is an **instance** that inherits its properties.
- Figma leaves the main where you made it. Move it to the Styles + Components page, inside a named container frame (Navigation, Cards, Buttons, Overlays); that frame's name becomes the folder in Assets.
- **Overrides:** changing a property on one instance affects that instance only, and that property stops following the main. Everything else still follows.
  - Reset all overrides returns it to source.
  - Reset size appears after a manual resize and restores only the dimensions.
- **Detach instance** "is a destructive action" (Staiano). Almost never. Push changes to main when an instance edit should become the source.
- **Swap** via the instance picker, or copy a component and Paste to replace over an existing layer, to upgrade a plain frame into an instance in place.
- Build order for a reusable block: atom → wrap in auto layout → set padding and resizing → name → create component → insert instances → wrap instances in an auto layout row → make the row a component too.
- **Nested components.** A Cards Section main contains Content Card instances.
  - Editing the card main updates every card in every section.
  - Editing the section main changes the structure of every section.
  - Instances of nested components cannot be resized or re-behaved per placement; change them at the main.
- Keep the main's content generic ("Item", "Button", checkerboard image fill) and customise per instance. Test the main with longer text than the placeholder before componentising so real content cannot break it.
- Choose resizing at the main: a menu item hugs its label; a carousel item is Fixed on both axes so text cannot grow the box.
- Duplicating a mobile component to derive a desktop one (Top Navigation → Top Navigation - Desktop) keeps future edits to the shared parts flowing to both.

### 8. Variants and component properties

- A **component set** groups components that share a function and differ in small ways (style, state, size). Do not force unrelated components into one set; do not give variants to components that have no variation.
- **Layer names seed variant properties.** Two frames named `Button / Primary / Default` and `Button / Secondary / Default`, selected together, become one set with Property 1 = Primary|Secondary and Property 2 = Default.
  - Rename properties immediately to what they mean (Style, State).
  - Order values deliberately; the panel shows them in that order.
- Existing components combine via "Combine as variants". A conflict warning means two variants have identical property values; give each a distinct value.
- A property whose values are `True` and `False` renders as a toggle (an Icon property that shows or hides the star).
- Standard state set: Default, Hover (pointer devices only), Focus/Pressed, Disabled. States usually need extra colour styles (lighter Accent, lighter Secondary), so add them to the palette rather than hard-coding.
- Assets shows one entry per set; the instance's property panel does the switching. A tab bar with an Active variant per tab item is the model for "which tab is selected".
- Variant errors block publishing that component; the library dialog flags them and publishes the rest.

### 9. Variables, collections, and modes

- Types: **Color** (fill, stroke), **Number** (padding, gap, radius, width, height, min/max), **String** (text content, variant names), **Boolean** (layer visibility, boolean variant properties).
- Styles vs variables: a style bundles multi-value properties (gradients, image fills, full text rules); a variable is one raw value that can **alias** another variable. A variable can sit inside a style, so keep styles as the documented surface and variables underneath.
- Collection layout he recommends:
  - **Primitives**: raw palette in groups (`Red/500`, shades 100 to 900, 500 as base); scope off all properties and hide from publishing so they are used only by aliasing.
  - **Semantic Tokens**: `Basics/background`, `Texts/...`, `Buttons/...`; every value an alias of a primitive; modes Light and Dark. Scope text colours to text so they cannot land on a fill.
  - **Number Tokens**: spacing and radius scales, scoped to their properties.
  - **Breakpoints**: modes Desktop / Tablet / Mobile carrying width, height, column min/max, and `hasMobile` / `hasDesktop` booleans bound to layer visibility.
  - **Copy**: strings per language mode.
  - **Stored Values**: runtime state for conditional prototypes, kept apart from tokens.
- A slash in a variable name creates its group. Collections sort alphabetically and cannot be reordered, so prefix numbers to fix order. camelCase names read well to developers.
- **Modes resolve top-down.** Set the mode on the outermost frame and every descendant inherits it; drag a child into a frame with another mode and it re-resolves. Modes from different collections can be active at once (dark theme and mobile breakpoint together).
- Breakpoint pattern: bind the screen frame's width and height to breakpoint variables, Fixed both axes, auto layout with wrap, Fill children with min/max width variables, boolean visibility for nav variants. Switching the frame's mode reflows the layout.
- Number tokens surface in Dev Mode as labels and export as CSS variables, which is the concrete developer payoff.
- **Conditional prototyping** (Set variable, Conditional if/else, arithmetic on numbers, booleans bound to variant properties) collapses many state frames into one. Plan the logic before wiring it; an empty else branch is a legitimate "do nothing".

### 10. Naming, pages, and file organisation

- Pages by stage: **Lo-Fi**, **Hi-Fi**, **Styles + Components**. Duplicate Lo-Fi to start Hi-Fi so the reference stays. Put platform flows on separate pages when the plan allows; otherwise sections on one page.
- Name screens as you create them (Login, Sign Up, Home, Content Detail), then suffix by platform (`Login - Mobile`, `Login - Tablet`, `Login - Desktop`) with a batch rename. Keep screens in flow order left to right.
- Name every structural frame for its role: Form, Form Element, Text Field, Button Group, Container, Top Navigation, Tab Bar, Icon, Tab Item, Carousel, Cards Row, Cards Section, Title + Subtitle. Rename immediately after wrapping; the layer list is what the next person reads.
- Group a label with its field and name the group, even in a wireframe; precise names can be refined later but structure should be readable now.
- Styles + Components page: one background-filled frame per category (Typography, Colors, Navigation, Cards, Buttons, Overlays), each a specimen sheet with labels.
- Layer order in the panel is z-order on the canvas. Hidden layers and off-canvas duplicates are legitimate (carousel items beyond the viewport) but should be reachable by name.
- Set a file thumbnail (a dedicated 1600×960 frame or the best screen). Name a version at each milestone and write a description when publishing a library.
- Add a description (and a documentation link) to each component and style saying when to use it; it appears in Dev Mode.

### 11. Prototyping connections and interactive components

- Every node inside a frame has a hotspot. **Wire from the element, not the screen**: a connector from the whole Login frame makes the entire screen tappable, which is the failure.
- An interaction = trigger + action + animation. Triggers:
  - On click/tap (default);
  - On drag (sliders, drawers, swipe);
  - While hovering and While pressing (revert on release; hover has no meaning on touch);
  - Mouse enter/leave and Mouse down/up (do not revert);
  - Key/Gamepad;
  - After delay (splash screens, spinner loops; use sparingly or the prototype autoplays).
- Animations: Instant by default; Move / Push / Slide with direction (Move out, Down reads as "dismiss"); Dissolve; **Smart animate**, which matches layers by name and hierarchy across frames and tweens position, scale, opacity, fill, rotation.
  - Same names in both frames or nothing animates; the parent name may differ, the children must match.
  - "Animate matching layers" on a Move keeps the tab bar and nav still while the rest slides.
- **Interactive components:** wire states inside the component set (Default → Hover on While hovering, Default → Focus on While pressing, both Smart animate). Every instance inherits the behaviour; flow connections on an instance (Login button → Home) still work alongside. Put a `Back` action on the top bar's back item once, in the main, and every screen gets it.
- **Scroll:** content must exceed the container or nothing scrolls.
  - Set Overflow (vertical) on the scroll Container, not the screen, so the tab bar outside it stays put; or set the whole screen to scroll and mark the tab bar Fixed position.
  - Rows scroll horizontally the same way after being resized to the frame width; for a nested component, set overflow at the main.
- **Overlays:** a dropdown, tooltip, or modal lives as its own frame or instance outside the screens; the action is Open overlay with a position (centre, edge, or Manual placed relative to the trigger) and "close when clicking outside". One overlay serves every screen that opens it.
- **Flows:** one starting point per platform or per test task, named and described, so a shared link opens the right flow and a tester can follow the description as steps.
- The device preset in prototype settings must match the frame size or the view crops or floats; use Presentation for true-size testing. Keep the presentation tab open beside the file and test each interaction as it is wired.

### 12. Handoff and review readiness

- Pre-set **export settings** on assets during design: SVG for icons, PNG at 1x and 2x for images, PDF for whole frames. Viewers can then export themselves; that is what makes developers autonomous.
- **Dev Mode:** mark frames or sections Ready for development; Inspect shows padding, gaps, colours as CSS (auto layout as flexbox, colour styles and number tokens as CSS variables), plus iOS and Android snippets. A file built with auto layout and tokens hands off clean; one built with absolute positions hands off coordinates.
- Publish styles and components as a **team library** with a change description; edit only in the source file and republish. Variables publish the same way.
- A design system is a growing set of documented blocks tied to one product; a UI kit is a generic starter. Both live on the Styles + Components page, both need descriptions.

---

## Symptom → cause → fix (the one-node diagnosis)

| Symptom | Likely cause | Fix |
|---|---|---|
| Frame stopped growing with its text | An axis flipped from Hug to Fixed after a manual drag | Set that axis back to Hug |
| Children cluster left when the screen widens | Children are Hug/Fixed in a Fixed parent | Set children to Fill, or gap to Auto |
| Widening the screen leaves blocks at their old width | Missing constraints on the block | Left and right on the block; Top and bottom on the scroll container |
| Card falls apart with long text | Text is auto width, or siblings are Fixed | Auto height text, Fill on every child |
| Title and subtitle too far apart, image spacing fine | One flat gap on the card | Nest title + subtitle in their own frame with a smaller gap |
| Tab bar scrolls away with content | Bar is inside the scroll container | Move bar outside; pin Bottom + Left and right, or Fixed position |
| Prototype does not scroll | Content does not exceed the container | Shrink the container height below its content; set overflow |
| Whole screen is clickable | Connector drawn from the frame | Delete; draw from the element |
| Smart animate cuts instead of tweening | Layer names differ between frames | Match child names and hierarchy |
| Component set will not publish | Duplicate property values or a naming conflict | Give each variant distinct values |
| Instance ignores a change to the main | That property is overridden on the instance | Reset overrides (or accept the override deliberately) |
| Dark mode does nothing on a frame | Mode set on a child, not the outer frame | Set the mode on the outermost container |

---

## Build recipes (canonical sequences)

1. **Screen.** Frame from a device preset, Fixed W and H, background colour style, 12-column grid style. If the screen scrolls under a fixed bar: no auto layout on the screen; a Container frame (auto layout vertical, gap 32, horizontal padding 16, Left and right + Top and bottom constraints) for content; the bar outside the Container, Left and right + Bottom.
2. **Button.** Text with text style and colour style → wrap in auto layout, padding 16, alignment centre → fill with Accent (or Secondary) → name `Button / Primary / Default` → duplicate per style and state → select all, create component set → rename properties Style and State → wire Hover and Focus inside the set.
3. **Button group.** Two button instances → vertical auto layout, gap 16, padding 16 → both children Fill width → group gets Left and right constraints (Bottom too when it must sit at the foot of the screen).
4. **Form field.** Label text + 50-high rectangle → auto layout vertical, gap 8, name Form Element → wrap in Form (padding 16, gap 32) → Form Element Fill width, Text Field Fill width → Form gets Left and right constraints. A right-aligned helper link is its own auto layout frame, Fill width, padding 0, aligned right.
5. **Card.** Image (rectangle with image fill, Fill width) + Title + Subtitle → wrap title and subtitle (gap 8) → wrap all vertically (gap 16, padding 0) → every child Fill width → test with long text → create component.
6. **Row and section.** Card instances → horizontal auto layout (gap 16, padding 0 except trailing 16 so the last item keeps an edge margin) → wrap with a Section Title vertically (gap 32) → create component. Overflow horizontal at the main for prototyping.
7. **Tab bar.** Icon wrapper (Fixed 38×38, centred) + label → Tab Item (vertical, centred) → Tab Bar (horizontal, gap Auto, Secondary fill) → duplicate items → variants per active tab → component. Icons replace the placeholder ellipse with Fill on both axes.
8. **Overlay.** Build the menu or dialog as a component on the Overlays sheet → place one instance beside (not inside) the screen → connect the trigger with Open overlay, Manual position, close on outside click.
9. **Token setup.** Primitives (grouped, scoped off, hidden from publishing) → Semantic Tokens aliasing primitives with Light/Dark modes → Number Tokens for spacing and radius → Breakpoints with modes → bind screen size, padding, gaps, radius, and visibility to variables rather than typing values.

---

## Review lens: the questions Staiano asks of a file

1. Is every container a frame, and is each group there because its children must scale together?
2. Does every screen frame come from a real device preset and stay Fixed on both axes?
3. Does every block below the screen have auto layout with a deliberate direction, gap, padding, and per-axis resizing?
4. Where spacing differs between siblings, is that expressed by nesting rather than by nudging?
5. If I widen this screen, what moves? What stays? Which single container is wrong?
6. If I switch the preset to a bigger phone, then an iPad, does anything break?
7. Do blocks in plain frames carry constraints that match their job (stretch, pin, centre)?
8. Is there a grid style on every screen, and are the margins and gutters multiples of 8?
9. Is any colour, type, effect, or grid a loose value rather than a style or variable?
10. Do text styles stay free of colour and alignment?
11. Is anything drawn twice that should be one component with instances?
12. Are the mains on the Styles + Components page in named category frames, and has anything been detached?
13. Are related components a variant set with properties named for their meaning and a complete state set?
14. Could a developer read the layer list and know what each frame is for?
15. Will the layer names survive smart animate between these two frames?
16. Are prototype connections on elements, states inside the component set, scrolling on the container, overlays as separate frames, and flows named?
17. Does the layout that will be handed off export as flexbox, or as coordinates?
18. Are export settings preset, descriptions written, the library published with a note, and a version named?
19. If the content, the device, or the designer changed tomorrow, which of these would break?

---

## Checklist: a reviewable, handoff-ready file

1. Every container is a frame; groups only where children must scale as one drawing.
2. Every screen frame is Fixed on both axes and sized from a real device preset, and one preset is held across a candidate set.
3. Every container below the screen has auto layout with explicit direction, gap, and padding; resizing is deliberate per axis (Hug / Fill / Fixed), not left to defaults.
4. Spacing hierarchy comes from nesting, not from a single flat gap.
5. Blocks that sit in a plain frame carry constraints (Left and right for stretch, Bottom for bars, Center for modals), and the screen has been stretch-tested and restored.
6. A layout grid style is applied to every screen; margins and gutters are multiples of 8.
7. No raw values: every colour, text treatment, effect, and grid is a style or a variable; numbers on padding, gap, and radius are tokens where a token collection exists.
8. Text styles carry no colour or alignment; those are applied per layer.
9. Anything used twice is a component; mains live on Styles + Components in named category frames; instances are never detached.
10. Related components are variant sets with properties renamed to their meaning (Style, State) and a full state set where the element is interactive.
11. Layer names describe roles (Form Element, Cards Row, Tab Bar); screens are named and platform-suffixed; pages are Lo-Fi, Hi-Fi, Styles + Components.
12. Layer names match across frames that will smart-animate.
13. Components and styles have descriptions; a documentation link exists where the description is not enough.
14. Prototype connections start on elements, not screens; interactive states live in the component set; scroll is set on the Container; overlays are separate frames; each platform or task has a named flow with a description.
15. Export settings are preset on icons, images, and key frames; screens are marked Ready for development; the library is published with a change note and a version is named at the milestone.
16. Clip content is back on, grids can be hidden, a thumbnail is set, and the workspace has been cleared of test duplicates.

---

## Known limits

- **Dated on variables.** Chapter 13 reflects late-2023 Figma: modes required a paid plan, variables bound to colour, number, string, and boolean only, no typography variables, no variables on effects beyond a passing note, and no coverage of the newer extended collections or code syntax. The collection structure (Primitives → Semantic → Number → Breakpoints → Copy) is still sound; check the current property list before binding.
- **Component properties are covered only as variants.** The book models "with icon / without icon" as a True/False *variant* property. Modern Figma prefers a boolean, text, or instance-swap *component property* for that, with variants reserved for visual states. Treat his variant naming discipline as canonical and the property mechanism as superseded.
- **No absolute-position children in auto layout.** For a fixed bar over scrolling content he disables auto layout on the screen and pins the bar with constraints. Today an "absolute position" child inside an auto layout parent does the same job with the parent kept in auto layout. The intent (bar outside the scroll container, pinned bottom, Left and right) transfers; the mechanism has a newer option.
- **Dev Mode is described at launch.** Ready-for-dev marking, Inspect, and plugins are as of 2023 (then paid, since restructured). Code Connect, annotations, and measurement tools are absent. Trust the handoff principles (auto layout, tokens, descriptions, preset exports), not the panel layout.
- **No Plugin API.** Every instruction is a person at the properties panel. Mapping to `layoutMode`, `primaryAxisSizingMode`, `constraints`, `componentPropertyDefinitions`, and variable binding calls is the reader's job; the book gives the target state, not the calls.
- **Auto layout controls have grown.** Wrap and min/max are covered; grid-style auto layout, per-child absolute positioning, and newer alignment options are not.
- **Plan and UI limits are stale.** The three-page Starter limit, version history caps, and specific panel locations have changed. Ignore any rule that hinges on a plan tier.
- **Thin on design-system governance and accessibility.** Contrast and inclusivity are mentioned, not taught; token naming beyond one example, library versioning policy, and multi-brand theming need other lenses.
- **Plugins and Community are skipped here.** Chapter 12 is a tour of third-party plugins (icon finders, content fillers, auto-naming, mockup generators); none of it is construction mechanics, and the specific plugins date quickly.
- **Figures are gone.** The source was extracted from a heavily illustrated book; where a step said "as shown in the figure", this digest restates only what the prose committed to.

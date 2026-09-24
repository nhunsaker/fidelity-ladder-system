# Schwarz — Prototyping, Collaboration & Handoff in Figma

- **Title:** *The Designer's Guide to Figma: Master Prototyping, Collaboration, Handoff, and Workflow*
- **Author:** Daniel Schwarz
- **Edition/Year:** 2023. The extracted front matter names SitePoint Pty. Ltd. as publisher (ebook ISBN 978-1-925836-55-4); the library catalogue lists Apress. Treat the SitePoint imprint as the as-extracted fact.
- **Role of this lens:** the working-designer's Figma workflow from a low-fidelity click-through to a developer-ready file. Prototype connections and flows, variants and interactions, shared libraries, comments and branching, cleanup, accessibility checks, export settings, and what the Inspect panel actually tells an engineer.

> This digest is a synthesis for a Figma-building skill, not a reproduction. It restates Schwarz's step-by-step tutorial as operational rules, quirks, and checklists. The book is a single worked example (one splash page, desktop plus mobile, one navigation component, one button component, one shared library), so every rule below was learned on that example.

---

## Source assessment (read before trusting the rest)

The 18MB PDF extracted to roughly 85KB of text. That is not a partial extraction. The book is a short, five-chapter SitePoint tutorial ebook, and nearly every step is illustrated with a screenshot, which is where the file size lives. The prose of all five chapters survived intact: Chapter 1 (low-fidelity prototyping), Chapter 2 (collaboration), Chapter 3 (high-fidelity prototyping and libraries), Chapter 4 (handoff), Chapter 5 (advanced workflows), plus the closing plugin roundup. Chapter summaries are present. What is missing: every figure ("as pictured below" appears with no picture), one Notion documentation example whose lines are clipped mid-sentence, and the Chapter 1 step numbers are irregular (two "Step 9"s and two "Step 10"s, no "Step 3"), which looks like the original text rather than an extraction fault. This digest can carry a full lens for this book. Re-extraction is not required; an OCR pass would only recover on-screen UI labels already described in the prose.

---

## Core stance (speak as this author)

Schwarz is a hands-on working designer and former design-blog editor, and he teaches by building one thing end to end rather than by touring the toolbar. He is a Figma enthusiast who is candid about its quirks: he names them out loud ("one of Figma's annoying quirks", a parenthetical "sigh" when a setting resets) and then gives the workaround rather than pretending the tool is clean. He thinks collaboration, not drawing, is Figma's real edge, and he treats the file as a shared workspace with stakeholders and developers in it from the start. He is pragmatic to the point of anti-heroic: use a plugin for fake content, do not draw icons you can install, do not export assets yourself when the developer is better placed to, and do not buy a tool Figma already replaces. His discipline shows up as tidiness. Rename layers as you go, reuse styles even when the raw value happens to be correct, delete hidden layers, and keep a library separate from the mockup so nothing has to be rebuilt later. He treats accessibility as ordinary craft that mostly needs no tools, with a contrast checker as the one exception. On handoff his stance is that a clean, auto-layout-driven, style-attached file is the deliverable, because every inconsistency turns into a round trip with a developer. In his words, "Design handoff isn't a one-and-done process".

---

## Operating principles (the rules he keeps repeating)

**Component first, always.** Turning layers into a Component strips their Auto layout settings, and creating a Variant resets them again. So create the Component (and its Variants) before configuring Auto layout, or expect to redo padding, spacing, and resizing. The failure this prevents is silently losing "Fill container" and spacing on the reusable thing you just built.

**Use Auto layout on anything a developer will read.** The Inspect panel only reports spacing, "Fill container", and "Hug contents" when Auto layout is present. Without it, developers "don't get the right information about layouts and fluidity". This is the one handoff concern Schwarz says the designer must own.

**Groups are for organization only.** "Groups are like Frames without functionality" (Schwarz): no Auto layout, no Layout grid, cannot be a Component. Use a Frame whenever behavior is needed; use a Group only to bundle related layers, and let the Group icon in the Layers panel signal that intent.

**Rename arbitrary layers immediately.** Short, descriptive names help developers traverse the file and become the exported filenames. Do it as you go, not at the end.

**Attach a Style even when the raw value is already correct.** In the book the hamburger rectangles were the right black, but Design Lint still flagged them as missing a fill style. The rule is that consistency is proven by the Style link, not by the value; an unlinked layer will not follow a Style update and will stall handoff.

**Start a Library the moment you enter high fidelity.** Styles and Components created in a design document cannot be ported to a separate Library later. You cannot predict which parts will be reused, so build reusable elements in a Library document from the start and import them.

**Prefer the cheapest source of content and assets.** Fake copy, images, avatars, icons, charts and maps come from plugins; icons come from an icon set unless the art style genuinely demands a custom one. Reinventing these costs time without improving the design.

**Handoff quality is measured in round trips.** The point of cleanup, style linting, alt-text comments and export settings is that developers stop coming back for things they should have had.

---

## Method sections

### Frames, Auto layout, and the quirks that bite

- Frames are the container for a page, screen, or section. Top-level Frames sit on the canvas; a Frame inside a Frame is a nested Frame. A child obeys its immediate parent's Auto layout rules, so re-parenting a layer changes where it snaps.
- Auto layout enforces alignment, spacing, and padding. Each axis has a resizing mode: Fixed, Fill container, or Hug contents. Auto layout will "overzealously" set the top-level Frame to hug; set the artboard back to Fixed width and Fixed height so it does not shrink around its content.
- Match "Spacing between items" to the Layout grid gutter when items are meant to sit in columns (the book uses 20 for both) so list widths and column widths coincide.
- **Quirk: switching a Frame's preset from the Frame drop-down removes Auto layout**, and turning it back on resizes the Frame, which loops. Set W and H manually instead (the book's mobile artboard: 375 by 812, padding 20 and 35).
- **Quirk: "Constrain proportions" forces Fixed height**, so it cannot coexist with a Fill-container image. Size the image at the target width first, then set Horizontal resizing to Fill container. On a narrower artboard the height will be wrong; fix by unchecking constrain, setting H, and re-checking constrain.
- **Quirk: "Resize to fit" misbehaves on Auto layout artboards** and produces a broken layout. Resize the artboard manually.
- Layout grids apply to any Frame and replace rulers for visualising bounds. Use a 3-column grid on the content container so its edges are visible without selecting it.
- Numeric inputs evaluate arithmetic (type `24*2` for paragraph spacing), which keeps derived values honest.
- Zoom to selection (shift 2) and zoom to fit (shift 1) when working out of bounds; build sub-elements outside the artboard, then cut and "Paste over selection" onto the intended parent.

### Components, Variants, and Component Properties

- A Main Component is the source; instances are what appear in mockups. A change on an instance is an Override and applies there only; a change meant for every instance goes on the Main Component. Move the Main Component off the artboard and insert an instance from Resources or Assets, otherwise the mockup shows every Variant stacked.
- Variants live under a property (rename "Property 1" to something meaningful, such as "State", with values like "Open" / "Closed" or "Default" / "Hover"). To build a closed or collapsed state, duplicate the Variant and hide the relevant layer with the eye icon.
- Component Properties let an instance be configured at the Component level instead of by digging into layers:
  - **Text property** on a label layer (for example "Label") so button copy is set from the instance's Design panel.
  - **Variant property** for states.
  - **Instance swap property** (for example "Icon symbol") so any icon Component can be dropped into the slot. Instance swaps do not support Variants, so provide alternatives (outlined, filled) as separate Components, not as Variants of one.
  - **Boolean property** (for example "Icon") to toggle a nested layer's visibility, giving an icon-less instance without a second Component.
- Leave nested slots on Hug so swapped-in instances of different sizes do not break the layout.
- After creating a Variant, re-enable Auto layout and restore spacing, padding, and Fill container; Figma reset them.
- Keep design-specific components (the book's navigation) in the mockup file; only genuinely reusable ones go to the Library.

### Interactions, Smart animate, and prototype flows

- Interactions are set in the Prototype panel on a layer inside a Variant: trigger (On click, While hovering), action ("Change to"), destination Variant, and animation. The book wires the hamburger icon in the Open Variant to change to Closed and the one in the Closed Variant to change to Open, so the toggle works both ways. Hover states use While hovering → Change to → Hover.
- Smart animate makes assumptions about how the change should animate, "which most of the time are correct" (Schwarz). Accept it for simple state changes; do not hand-build animation the tool will infer.
- When the transition feels flat, open Interaction details and change the easing; easings and springs "reshape" the animation. The book settled on Bouncy at 800ms for the hamburger-to-close morph. Experimentation beats reading the docs here; custom animation curves exist but are rarely needed.
- A morphing icon (two bars rotating to a cross) is built by rotating the bars 45 and -45 in the open Variant and centering them, which is exactly what Smart animate interpolates.
- **Flows** are named starting points, one per version you want testable (the book: "Desktop version" and "Mobile version"). Set a Flow starting point on each top-level Frame and name it, so a stakeholder can switch versions from the Flows panel in Presentation view.
- **Test before sharing.** Open the Flow in Presentation view, click through the interactive parts several times, and use the Z key to cycle view options. Test the mobile Flow on a real device with Figma Mirror (same network; two-finger tap to pick a Flow). The book found a too-tall image only on the real device.
- Rename the document before sharing so recipients know what they are looking at.

### Collaboration: sharing, comments, branches, multiplayer

- **Access levels, as a policy:** designers get "can edit"; developers get "can view" (enough to inspect and export); everyone else gets "can view prototypes only" (Presentation view plus comments). If a document lives in a Team Project, the team already has access.
- Share from Presentation view via Share prototype when you want feedback on the click-through, or via Copy link. For link sharing, "Anyone with the link and password" plus "can view prototypes only" is his suggested balance of security and convenience.
- **Comments** (C key) are pinned by clicking or dragging on the canvas to give them context; @mention a person; comments are readable in both Design and Presentation modes and are the asynchronous channel. Resolve them yourself, or reply that the change is made and let the commenter resolve; pick one convention per team.
- **Branching** is versioning in the Git sense: create a branch, experiment, then Review and merge changes. Reasons to branch rather than edit live: a failed experiment would otherwise force a rollback that loses other people's work, and two people can want the same area at the same time.
  - The review modal shows a side-by-side before/after (or Overlay) per Frame, lets you update the branch from main, and shows full version history.
  - Nominate reviewers and Request review. Reviewers approve or suggest changes; they do not merge. Only after everyone approves does the designer or final reviewer click Merge branch, which merges and archives the branch.
  - Abandoning a branch means Archive branch: it is hidden from history, not deleted.
- **Multiplayer** is the synchronous channel: avatars and live cursors show who is present; an audio conversation (headphones icon; needs "can view") lets people talk in the file; Spotlight me asks others to follow your viewport so they see what you are describing. Editors can help hands-on.

### Styles, Libraries, and design-system hygiene

- Styles cover Color, Text, Effect (shadows, blurs), and Grid. Name with a slash to group into a collection: "Interface/Text", "Brand/Primary", "Brand/Primary (Hover)", "Standard/Regular". Do not create a Style for a one-off value you will not reuse.
- Typography floors the book states as accessibility minimums: font size 16, line height at least 1.5 times size, letter spacing at least 0.12, paragraph spacing at least 2 times size.
- **Publishing:** Publish styles and components (option 3). Never leave the "description of changes" empty; teammates should not be in the dark. Consumers enable the Library from Assets → Team library.
- **Updates are opt-in on the consuming side.** A Style edit in the Library only reaches linked documents after you publish and the consumer accepts from the Updates tab (Update or Update all). This is deliberate so a Library change cannot break a live design in real time. The workflow after any Library fix is: publish, switch to the mockup, Review, Update.
- To apply a Library Component you cannot "apply" it to an existing layer; delete the local version and insert the Library instance.
- **Work-in-progress guard:** prefix a Component or Style name with "." and it will not publish, so collaborators cannot accidentally ship half-finished elements.
- **Organize the Library into pages** (Colors, Typography, Icons, Buttons). On Colors, lay out swatches per Style plus small overlays for the color combinations the design actually uses, so a stakeholder can see at a glance what pairs are sanctioned. Canvas organization "doesn't replace design system documentation".
- **Documentation lives outside Figma.** Figma has no documentation feature; the book uses Notion (Storybook, zeroheight, Zeplin are the alternatives). Copy link to a specific Variant and paste as preview into the doc; then paste the doc's URL into the Component's "Link to documentation" field so it is reachable from the Design panel. Developers can add code snippets to the same doc.

### Handoff: cleanup, lint, accessibility, export, Inspect

Run this pass even if you cleaned as you went.

1. **Delete redundant layers.** Run the Clean Document plugin twice: Delete Hidden Layers (unlocked ones), then Ungroup Single-Layer Groups. The book found a hidden layer in a five-layer design; assume you have some.
2. **Name every layer** short and descriptive. Names become export filenames and are what developers traverse.
3. **Lint against Styles.** Select the Component or Frame and run Design Lint; it lists layers with no Style attached (for example "Missing fill style (4)"). Use Select All from the error and apply the Style, or consciously ignore. Even one or two off-values "can stall the handoff workflow".
4. **Check contrast on the Main Component, not an instance.** Select the text and background layers together and run Stark → Contrast. If it fails, edit the Color Style itself (and the hover Style too), confirm with Stark, republish the Library, then update the mockup. The book's fix: 00B2FF became 0072A3 (Primary) and 1FBCFF became 007DB1 (Primary hover).
5. **Simulate color-vision deficiencies** with Stark's Vision Simulator across every Frame.
6. **Deliver alt text and labels as comments.** Screen-reader text is not visible design, so pin a comment on each element that needs it: the navigation ("Primary navigation"), the toggle icon ("Open navigation/Close navigation"), and each meaningful image with a full descriptive sentence. Same for unlabeled form controls and headingless landmarks.
7. **Set export settings so a developer with "can view" can pull assets.**
   - Bitmap photos: JPG when there is no transparency (smaller file). Add 1x and 2x; Figma appends "@2x", which mobile operating systems require to pick the right resolution and which on the web is just clarity.
   - Vector icons: SVG at 1x only; it scales losslessly and developers can animate it (the hamburger-to-cross morph can be done in code from the SVG).
   - 512w / 512h presets and custom sizes exist for things like favicons.
   - A variable-font logomark should ship as SVG so the site does not load an extra font file for one word.
   - File → Export exports everything marked exportable at once. Slashes in layer names create folders on export ("icons/icon-navigation", "images/splash/splash-image-1"); renaming requires "can edit", so do it for the developer.
8. **Know what Inspect shows and does not need from you.** Selecting a layer in the Inspect panel exposes size, fluidity, position, content, typography, color, and interactivity. Developers convert color formats themselves (Hex, RGB, CSS, HSL, HSB), so your color format does not matter. What does matter is item 9.
9. **Auto layout is the handoff dependency.** No Auto layout means no spacing, fill, or hug information in Inspect. Fix that before anything cosmetic.

### Icons and vector craft (only what handoff needs)

- Draw icons in the Library on a 16 by 16 Frame with a 1px grid and align to grid lines so they render crisply at most sizes. Build from primitives, Union, rotate, then Flatten so the layer can be resized on its own axes instead of diagonally. Round dimensions to whole pixels; center in the Frame; set constraints Left and Top to Scale so the icon scales with its Frame; Resize to fit trims the Frame.
- Scale (K) rather than resize when changing icon size, because Scale also scales stroke width and plain resizing does not. Small resizes to fill Frame space are fine because stroke width stays put.
- Give outlined and filled versions their own Components (see instance swap above). Add a stroke early so the outlined variant is free.
- Remove the Layout grid and Fill from an icon Frame before it becomes a Component so they do not leak into instances.

### Fake and live content

- Plugins for placeholder content: Lorem Ipsum, Unsplash (deselect everything first, or the image becomes the selected layer's fill), Iconify, Figmoji, Charts, Map Maker, Content Reel, illustration libraries, Icons8 Background Remover, Font Awesome.
- Data Sync pulls JSON, XML, or CSV from an API or Google Sheet into a text layer (the book uses ipify to insert a real IP address). Authenticated APIs need a developer's help to configure; returned data can be reformatted in JavaScript.
- Research tools (Useberry, Maze, Ballpark) take the Figma share link, no plugin needed. ProtoPie is for interactions Figma cannot express and is rarely worth the export. FigJam is where Frames go to be annotated with stakeholders.

---

## Handoff checklist: the questions Schwarz asks

Run these before calling a Figma file ready for engineers.

1. Was every reusable element made a Component before Auto layout was configured, and were Auto layout settings re-checked after each Variant was added?
2. Does every Frame a developer will inspect use Auto layout, with the intended Fixed / Fill / Hug on each axis?
3. Is anything a Group that should be a Frame because it needs layout, grid, or component behavior?
4. Has every layer got a short, descriptive name, and do export-bound layers use slash paths for folders?
5. Are the Main Components off the artboard, with only instances in the mockup?
6. Are state changes wired in both directions (open → closed and closed → open) and does hover use While hovering?
7. Was Smart animate accepted where it works, and easing adjusted only where the transition felt wrong?
8. Is there a named Flow starting point for each version (desktop, mobile) so stakeholders can switch?
9. Was the prototype clicked through in Presentation view, and the mobile Flow checked on a real device via Figma Mirror?
10. Is the document renamed to something a stakeholder will recognize before the link goes out?
11. Are access levels set by role (designers edit, developers view, others view prototypes only)?
12. Are Styles, Components, and documentation in a Library, not trapped in the mockup?
13. Does every color, text, effect, and grid value that recurs point at a Style, including values that happen to be correct?
14. Did Design Lint come back clean (or with only conscious ignores) on every Frame?
15. Did Clean Document remove hidden layers and single-layer Groups?
16. Does the button (and any text-on-color element) pass contrast on the Main Component, in default and hover, with the fix published and accepted downstream?
17. Was the design checked through a color-vision-deficiency simulation?
18. Is there a comment carrying alt text or a label for every image, icon toggle, landmark, and unlabeled control?
19. Do exportable assets carry the right format and scales (JPG for opaque bitmaps at 1x and 2x, SVG at 1x for vectors)?
20. Is Component documentation linked from the Component's "Link to documentation" field?
21. Were experimental changes made on a branch, reviewed side by side, approved, and only then merged?
22. Are half-finished Library elements prefixed with "." so they cannot publish by accident?
23. Was the Library published with a non-empty description of changes?
24. If the artboard needed resizing, was it done manually rather than with Resize to fit?

---

## Known limits (when to defer to other lenses)

- **Source coverage is complete for the prose; figures are gone.** All five chapters survived extraction. Every screenshot is missing, so any instruction that depended on "the image below" (alignment bar positions, the exact Design panel icon) is described here only as far as the text describes it. One Notion documentation sample is clipped mid-line. No re-extraction is needed for a full lens; OCR would only add UI labels.
- **Written against 2023 Figma.** The book calls the developer view the "Inspect panel", not Dev Mode. It predates Variables and modes, Dev Mode annotations, Code Connect, and the current library and property UI. Auto layout quirks it documents (settings dropped on Create Component, on Add Variant, on Frame-preset switch) may have changed. Trust the workflow and the reasons; verify the specific UI behavior in the live editor.
- **One small worked example.** A single splash page with a navigation and a button. It does not cover multi-screen prototype navigation between Frames, overlays, scroll behavior, conditional logic, or component sets at design-system scale. For those, defer to Figma's own documentation or a systems-scale lens.
- **No design-token or code-sync coverage.** Styles are named and published, but there is no token taxonomy, no variable-to-CSS mapping, and no Storybook or Code Connect workflow beyond "developers can add code snippets to the Notion doc". Defer to a token or design-systems lens for that.
- **Accessibility is scoped to contrast, CVD simulation, and alt-text comments.** The book lists other concerns (labels, heading hierarchy, touch targets, readable typography) but does not operationalize them. Defer to an accessibility lens.
- **Not a usability or visual-design lens.** No guidance on what to build or whether it is good, only on how to build it cleanly and hand it over. Pair with Krug for usability and with a visual-craft lens for hierarchy and taste.
- **Plugin recommendations are point-in-time.** Clean Document, Design Lint, Stark, Data Sync, Unsplash, Iconify and the rest may have changed names, pricing, or availability. Treat them as the categories of tool to reach for, not fixed dependencies.

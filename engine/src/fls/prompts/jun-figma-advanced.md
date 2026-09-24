# Jun: Variables, Tokens, and Handoff at System Scale

- **Title:** *Design Beyond Limits with Figma: 50+ Figma solutions for advanced collaboration and modern UX/UI*
- **Author:** Simon Jun (designer turned CPO at Dotidot; former design-system consultant for a multinational)
- **Edition/Year:** 1st Edition, 2025 (Packt)
- **Role of this lens:** the system-level Figma operator. Where Staiano covers construction craft and Schwarz covers prototyping and handoff mechanics, Jun covers the layer above: how a token/variable layer is structured so themes and modes hold, when a value is a variable versus a style versus an external token, how components expose properties instead of multiplying variants, how a library is versioned, published, measured, and deprecated, and what makes a file survive other people editing it.

> This digest is a synthesis for a design-system-building skill, not a reproduction. It restates Jun's methods and decision rules in operational form for an agent working inside real Figma files through the plugin API and handing results to engineers.

---

## Core stance (speak as this author)

Jun's first loyalty is to production code, not to the Figma file. His refrain is that "the final product isn't a Figma file but production code" (Jun), and every decision about structure, naming, tokens, and documentation is judged by whether a developer who opens the file cold can build the right thing without asking. He is a pragmatist about scale: a design system, a token layer, accessibility, prototyping fidelity are all "a scale, not a yes or no" (Jun). You decide how far to go by the goal, the team size, the onboarding rate, and the time you actually have, then you build exactly that much and stop. He distrusts benchmarking against Polaris or Carbon ("inspiration, not requirements"), distrusts pre-built kits you did not build and therefore cannot extend in the same style, and distrusts polish that has no consumer. He is blunt that building is the easy part and that "adoption is the tricky part, not the design itself" (Jun); a token system nobody in engineering consumes is wasted hours. He treats a design system as a product with an owner, a backlog, release notes, analytics, and a deprecation policy. He wants foundations (tokens, semantics, naming) to absorb more effort than components, because a good base makes everything downstream cheap. He insists on one vocabulary shared by design and code, on versions that are locked once handed off, and on branching only where the plan and the team size justify it. When he reviews a file he asks: would a developer find this in three months, do the names say where the value is used, is the mode structure honest, and is anything here a duplicated screen where a property or an annotation should be.

---

## Operating principles (the laws and maxims)

- **Production code is the product.** Every artefact in Figma is an instruction to a builder. If it cannot be built, it is worthless regardless of how it looks.
- **Foundations first, components second.** Spend more time on tokens, semantic naming, and structure than on components. Weak foundations make every component brittle.
- **Everything is a scale.** Design system size, token coverage, prototype fidelity, accessibility depth. Decide how much, not whether.
- **Adoption beats construction.** Plan the audience, ambassadors, pain points, success metrics, and support channel before you build the thing.
- **One vocabulary.** Designers and developers use the same names for the same decisions. `spacing/medium` in Figma and `gap-md` in code is a defect.
- **A design system is a product.** Owner, backlog, release cadence aligned to sprints, release announcements, analytics, deprecation policy.
- **Do as little as transfers the message.** A Loom video often beats a prototype; an annotation card beats a duplicated screen; a component property beats a variant explosion.
- **Never delete, archive.** Old pages, old versions, superseded components: mark, redirect, migrate, then remove only when nothing depends on them.
- **Figma variables are not design tokens.** They are Figma's native interpretation of tokens with real limits. Choose deliberately.

---

## Method sections

### 1. The token layer: structure before tooling

The structure is the same whether you implement it as Figma variables or as external tokens.

**Three tiers, connected by aliases.**
- *Core (primitive):* raw values with no usage meaning. `color/blue/500`, `Poppins`, `2px`.
- *Semantic:* purpose-based names that say where a value is used. `color/background/default`, `text/error`, `border/focus`, `surface/raised`.
- *Component:* only when a component needs its own indirection. `button/primary/background`, `button/secondary/border`.
- Semantic and component tokens reference core tokens rather than repeating hex values. Two semantic tokens (`text/error`, `background/discount`) can alias the same core token (`red/500`). Change the core value once and every consumer updates; developers using `button/primary/background` in code touch nothing.
- The naming test: `#007BFF` tells you nothing; `color/blue/500` tells you what it is; `color/background/default` tells you where it goes; `button/primary/background` tells you exactly where. Names should carry *what* (color, spacing), *where* (background, text), and *state or variant* (default, hover).
- The chain, written out:

```
core:       color/purple/500          = #5C50E6
semantic:   color/primary/default     = {color/purple/500}
component:  button/primary/background = {color/primary/default}
```

  Rebrand purple to green by editing one core line. The failure it prevents: the four-name problem, where Figma says `Purple/500`, CSS says `primary-color`, iOS says `colorPurple`, Android says `color_purple_primary`, and nobody can tell whether they are the same decision.

**How many tokens.**
- Audit first if the project exists: count unique colours, spacing values, and text styles actually used. Designers routinely overestimate.
- The three-uses rule: a value used in three or more places earns a token. One or two uses may stay hard-coded early on. Strict no-hard-codes policies suit large mature systems; for a new system the bigger risk is drowning in thousands of tokens.
- Order of tokenisation: colours first (visual, and they unlock light/dark), spacing second (four to six values cover most systems), typography third (most common styles only).
- Named failure modes: over-tokenising (tokens for single-use values), under-tokenising (core tokens applied directly everywhere, no semantic layer, so a rebrand touches every instance), inconsistent naming inside one system, too many variants (fifteen button variants where three would do).

**Multi-brand and theming readiness.** With a semantic layer, one component in code can carry many visual skins: white-label products, brand modes, user-selected themes, an AAA-contrast theme offered as a setting. The semantic name is stable; the alias target changes per theme.

### 2. Variable, style, or external token: the decision

**Figma variables versus external tokens (Token Studio / JSON pipelines).** Jun's rule: small system, lives in Figma, at most light and dark → Figma variables. Bigger, future-proof, not locked to Figma, developers consuming tokens → an external token platform in almost every case. The differences that decide it:

| Concern | Figma variables | External tokens (Token Studio, JSON) |
|---|---|---|
| Native / speed | Built in, fast, understood by every designer | Plugin-mediated, slower, learning curve |
| Types | Color, number, boolean, string only | Adds composite tokens (a typography token bundling family, size, weight, line height, letter spacing) |
| Modes / themes | 4 modes per collection on Pro/Org, 40 on Enterprise | Unlimited themes (paid tier) |
| Data model | Collections and modes; opaque outside Figma | JSON any developer reads immediately |
| Versioning | None of their own; they ride the file's version history | Git sync (GitHub/GitLab): commit history, diffs, contributor tracking, rollback |
| Code path | Needs an export plugin (Variables to CSS, Variables to JSON) then usually Style Dictionary | Built for export to every platform format |
| Guardrails | Scoping constraints (see §4) | No scoping |
| Dependency graph | Not visualised | Visualised; matters past a few hundred tokens |

- Do not read the modes cap as a design choice. It is a plan-tier limit. If your theming axis needs more than four values on a non-Enterprise plan, variables cannot carry it.
- The industry path from Figma variables to code is: export JSON → Style Dictionary → CSS custom properties / Swift / Android XML. Plan the pipeline before choosing the tool.

**Variables versus styles.** Variables can alias other variables (hierarchy), carry modes (theming), apply to more properties, and store numbers and booleans. Styles remain useful where a bundle of properties must travel as one unit, chiefly text styles, because variables cannot express a composite typography token. Practical rule: colours, spacing, radii, opacity, booleans → variables; text styles → styles bound to variables where the tool allows; effects → styles until variables cover them.

**Choosing plugins and tools the system will depend on.** Jun's five questions before a plugin enters a workflow, because a system built on an abandoned plugin is a system with a hole in it:
- *Am I the only user?* Personal boosters can be swapped freely; team-wide dependencies cannot.
- *Is this one-time?* A migration plugin (styles-to-variables converters, batch stylers) needs no longevity. A daily-use plugin does.
- *Is it paid, or company-backed?* Sustained funding predicts sustained updates. Official integrations (Jira, GitHub, Webflow) exist because the vendor needs them to work.
- *Are there alternatives?* Token Studio has no cheap substitute; plan a contingency for anything irreplaceable.
- *When was it last updated?* More than two years without an update means treat it as unsupported. Read the comment section for recent breakage.
- The export bridges to know: Variables to CSS and Variables to JSON (variables out of Figma), Auto Documentation (generates a documentation structure for hundreds of tokens in one run), Content Reel and data.to.design (real content for stress-testing and demos).

### 3. Collections and modes: theming that stays honest

- **Collections are your sets.** Mirror the tier structure: a `Core` collection for primitives, a `Semantic` collection whose values alias Core, and component collections only if needed. Figma will not let you create an empty collection; create the first variable, then rename the auto-created collection.
- **Separate collections per mode axis.** Put variables that change along the same axis in the same collection, and nothing else there. Colours in a collection with `Light`/`Dark`; spacing in a collection with `Mobile`/`Desktop` (`spacing/large` = 16 on mobile, 24 on desktop). The failure this prevents: a colour collection forced to carry mobile/desktop modes for values that never change, or spacing forced into light/dark, which doubles maintenance and invites drift.
- **Semantic tokens carry the mode, primitives do not.** `text/primary` = dark grey in Light, light grey in Dark, each aliasing a Core value. Core `grey/900` never has modes.
- **Aliasing across collections** is done through the Libraries picker (variables from the Core collection appear there when editing a Semantic value). Programmatically: set the semantic variable's value for each mode to a `VARIABLE_ALIAS` of the core variable.
- **Contrast lives at the token level.** Check foreground/background pairs on the semantic tokens themselves, per mode, before any component uses them. Build a small testing file with typical screens where the tokens appear together so a mode swap is verified against real compositions, not swatches.

### 4. Scoping, descriptions, and code syntax

- **Scope every variable.** Colour variables: fill, frame, shape, text, stroke, effects. Number variables: corner radius, width/height, gap, text content, stroke width, layer opacity, effects, plus the typography scopes (font weight, font size, line height, letter spacing, paragraph spacing, paragraph indent). A number named `typography/heading/large` scoped to font size cannot be misapplied as a gap. This is the one guardrail variables have that external tokens lack; use it on every variable you create.
- **Describe every semantic and component variable.** The description field is the in-tool documentation surface; it shows in Dev Mode. Write purpose and usage, not the value.
- **Code syntax instead of platform-specific variables.** Do not create three variables for three platforms. Keep one variable and attach a code syntax entry per platform: web `--color-primary-500` (kebab-case custom property), iOS `colorPrimary500` (camelCase), Android `color_primary_500` (snake_case). Dev Mode then shows each developer the name they expect. For an existing set of hundreds of variables, do this by script, not by hand.
- **Asset names follow the token naming pattern.** The same `type-purpose-variant` discipline used for tokens should govern layer and export names so the whole file reads as one vocabulary.

### 5. Component architecture and properties

- **Pick an architecture and hold it.** Atomic (atoms → molecules → organisms → templates; pages rarely) or Jun's own Primitives → Components → Patterns → Templates, which avoids the atoms/molecules ambiguity. The structure organises files and keeps large files performant.
- **Foundations and components in separate files.** Modular by construction: one foundations library (variables, styles), separate component libraries per surface (app, website). Avoid intricate cross-component dependencies.
- **Expose properties rather than proliferating variants.** Use variants for true visual states and sizes; use boolean toggles for show/hide (icon, label), instance swaps for slot content (leading icon, trailing icon, nested control), text properties for content, and nested properties for the few inner-component settings that change often. Ten screens that differ by one dropdown state are one component with properties plus a variant annotation card, not ten frames.
- **Property iconography and order.** Prefix property names so type is visible at a glance: `◆` variant, `↺` swap instance, `○` toggle, `@` content, `↳` nested. Sort identically on every component: variants, then toggles, then swaps (under their toggle), then content. Designers learn once that content is always at the bottom.
- **Expose nested properties sparingly.** Only those changed frequently. Everything else stays reachable via the layers panel inside the instance. An overwhelming property list makes nobody faster.
- **Standardise property values.** Decide `Large/Huge/Big` versus T-shirt sizes once and apply it to every component.
- **Every component gets a description.** Purpose, behaviour, and an accessibility note (keyboard behaviour, announced state). Generate them from a fixed template so they read consistently.
- **Signal status with the component background.** Red fill on the component frame = deprecated; yellow = utility/helper. It shows in the assets panel before anyone inserts it.
- **Hide helpers from the library.** Prefix with `_` or `.` (`_Tooltip`, `.Slot`) so sub-parts that must not be used alone are not published.
- **Stress components with real content.** Long names, varied filenames, empty lists, hundreds of items, translated strings (German can run about 30% longer than English). Placeholder text hides truncation and overflow defects.
- **Interactive components are on the scale too.** A hover state costs seconds; a fully interactive navigation costs days. Prototype only where documentation cannot carry the behaviour.

### 6. Library lifecycle: publishing, versioning, analytics, deprecation

- **Version at cycle boundaries.** Create a manual version when handing to development or stakeholders, not on every save. Name with one scheme per organisation (`Project_Milestone_vX`, `Project_YYYY-MM-DD`, `Project_SprintX`, `Project_Review_vX`) and use the description as a changelog (`✅` approved, `➕` added, `❌` removed).
- **Handed-off versions are locked.** Never edit a version that developers or stakeholders received. Create a new version for changes. Older versions are view-only; if comments are needed on an old state, duplicate it into its own file and archive it afterwards.
- **Branch only when the plan and the file justify it.** Branching requires Organization or Enterprise. Use it for design-system libraries edited by several people and for major changes to shared components: branch, invite review, merge. Ad-hoc branches also isolate your system change from other teams' edits while testing. Small teams on Professional use versions and separate test files instead.
- **Verify before publishing.** Keep a testing file that places major screens beside a static screenshot of themselves. After a library change, compare the live frame to the screenshot to catch accidental breakage. Run the token inspector on components before publishing to catch missing or wrong token bindings.
- **Multi-level access.** Edit rights on library files go to the system team only. Consumers get the library through publishing. New components are proven in a separate file before they enter the main library.
- **Read library analytics monthly (Org/Enterprise).** Insert counts: a core component missing from the list, or a new one barely used, means communication failed. Detach counts: high detaches mean a missing variant or property; reprioritise the backlog. File and team names: a team absent from the list is not adopting the system. Pair with code-side usage analytics (Omlet or similar), because Figma adoption without code adoption is half a system.
- **Deprecate, do not delete.** Mark deprecated (red background, description note), stop promoting, migrate existing designs, remove only when no active project depends on it.
- **Release like a product.** Align system updates to the product sprint cadence, announce each release in a dedicated channel, and maintain a support channel. Unanswered support requests end adoption.
- **Governance roles at scale:** a system owner (priorities, adoption, cross-team communication), a system designer (components, design documentation), a system developer (code components, developer documentation). In small teams make the split explicit as a percentage or fixed days; "when we have time" never arrives.

### 7. Files that survive other people editing them

- **Fixed page structure, every file.** Jun's template: `01 Getting Started` (team, goals, timeline, assets, links; opens first), `02 Project Name` (one page per logical product section), `03 Documentation` (briefs, research, personas, meeting notes), `04 Components` (local library when not on a shared system), `05 Playground and Exploration`, `06 Archive` (never delete potentially useful work), `07 Cover`. Duplicate the template for each new project; developers learn the layout once.
- **Production files and period files.** For a live product keep application files that mirror production 1:1 (dashboard, settings, checkout) and a separate quarterly (or monthly) file where each page is one ticket carrying a Jira/GitHub widget. At period end, merge shipped pages into the application files and leave a redirect on the old page so links in tickets and chat still resolve. Unshipped pages stay until they ship.
- **The three-month test.** Open a file you have not touched in three to six months. If you cannot say what it is and whether it holds everything a developer needs, the structure failed.
- **Annotations are components, not comments.** Designer notes, copy notes, variant cards, nice-to-have markers, ticket cards, and flow headings are custom annotation components placed on the canvas. Comments get lost and are not visible at a glance; Dev Mode annotations require paid seats for every reader. Build the annotation kit once and reuse it.
- **Variant cards over duplicated screens.** Show a state difference with a card beside the primary screen. Duplicating whole screens inflates apparent scope, hides the one changed detail, and distorts estimates.
- **Flow headings and flow blueprints.** Label logical sections and give developers a user-flow map with the final screens attached to each step before they read individual screens.
- **Shared files are tagged.** External shares carry a name prefix such as `[🔗 SHARED WITH CLIENT]`; internal jokes and explorations never live in a shared file. When sharing by link, uncheck copy/share/export for viewers; invite externals at file level, not project or team level.
- **A video library page.** Loom walkthroughs (named `YYYY - Area - Initiative`) linked from a Key Resources page so context is not buried in chat history.
- **Feedback requests have a fixed shape** so people keep answering them: a title, a one-line problem or assumption, a video for anything complex, a link to the specific section (never the whole file), a response deadline, and direct mentions of everyone expected to answer. Record every critique and link the recording beside the design.
- **Channel conventions travel with the template.** Headings and an emoji prefix on every new topic, all replies in threads, a checkmark when resolved, deadlines at the top of the message, links embedded in words rather than pasted URLs, every message acknowledged the same day. Keep the cheat sheet as a Figma component so updating it once updates every project file.

### 8. Dev Mode and handoff

- **Variables are the spec.** A developer clicking an element sees `color/theme/text/default`, not a hex to eyeball. Bind every visual property to a variable or style so Dev Mode shows names, not values.
- **Component playground** exposes every variant and property combination in one view. This only works if properties are cleanly modelled (§5).
- **Compare changes** shows iterations side by side; it replaces screenshots with circles. Make sure each iteration is a version so there is something to compare.
- **Ready for dev status.** Mark finished sections so the Dev Mode filter shows only production-ready designs. Unmarked work is exploration by definition.
- **Code Connect** links a Figma component to its production component so developers copy `<Button variant="primary" icon="plus" />` with props filled from the instance. Jun calls this the single feature worth upgrading to Organization for. Requires the engineering team to wire the repository; once wired, prop names must match property names, so name properties with code in mind.
- **Shared terminology table.** Auto layout = flexbox, corner radius = border-radius, frames = divs, variables = CSS custom properties, prototypes = clickable mockups. Say the developer's word when handing off.
- **Prototypes for developers:** ask whether they will open one at all; prefer a short video plus a CodePen or library example; reuse the community Figma file for any third-party component the team will use (date picker) and reskin it with your tokens; when you do build one, show entry points, decision points, success, error handling, and exit points rather than polish.
- **After handoff, review is a phase, not a favour.** Checkpoints at component completion, feature milestone, pre-staging, pre-production. A developer self-check list before review: spacing matches, fonts and weights correct, hover/focus/active work, responsive across sizes, contrast passes. Automate the checkable items (Playwright-style visual and interaction tests) rather than eyeballing.
- **Document approved deviations** where technical limits force a change, in the component description if it is component-specific, so the same argument is not rerun by the next team.
- **Implementation guidelines** cover what designs cannot enumerate: spacing when content length varies, responsive adaptation, animation timing and easing, error-state behaviour.

### 9. Assets and export hygiene

- **Icons on one page with a prefix** (`icon-arrow-left`, `icon-close`). Developers re-export the whole set in one action and know it is complete.
- **Images inside a wrapper frame with export settings on the frame.** Prepare per-platform presets (web 1x/2x; mobile 1x/2x/3x; SVG or PNG at 24/32/48 for icons) so Dev Mode offers one-click export.
- **Complex compositions:** one main frame, logical sub-blocks, clear names. Let the developer choose whole-or-parts.
- **Compress before handoff.** JPG quality Low for backgrounds (Jun measured 1.54 MB → 0.64 MB at 1920×1080 with no visible loss); WebP/AVIF where the stack supports them.
- **SVG icons that export clean:** basic shapes and simple paths; union/subtract/intersect/exclude to flatten instead of grouping; no shadows, blurs, masks, clipping, radial gradients, or stacked strokes. Test: export, open the file, expect under about 2 KB and no `<mask>`, `<filter>`, `<clipPath>`, or `<defs>` with gradients.

### 10. Accessibility built into the system, not audited afterwards

- **Contrast at the token level.** WCAG 2.1 AA: 4.5:1 body text, 3:1 large text (18px+ or bold 14px+) and 3:1 for focus indicators. Use Figma's native contrast check in the colour picker on semantic pairs per mode; use a bulk auditor (Stark) for whole-file passes. AA is the compliance baseline (EAA, in force June 2025); AAA for critical components or as a switchable token set.
- **Focus states are states.** Every interactive component documents a visible focus state that meets contrast; a thick high-contrast outline beats the browser default light blue. Document expected keyboard behaviour (Tab order, Esc closes modals, Enter/Space activates, arrow keys in carousels and menus).
- **Tab order is designed, not left to the DOM.** Annotate focus order on complex layouts (A11y Focus Order plugin; Include for landmarks, headings, reading order, touch targets, alt text detection). The classic failure: a consent banner last in tab order.
- **Alt text is a component property.** Add an alt-text text property to image and icon components so it must be filled. Rule: describe meaning or function ("Close settings panel"), never prefix with "icon" or "image". Keep an icon-meaning library in the documentation.
- **Semantic structure guides code.** One H1 per page, heading levels in order, persistent visible labels (never placeholder-as-label), required-field markers that are not colour-only, related controls grouped visually and noted as a semantic group.
- **Typography tokens encode readability:** 16px body minimum, line height 1.4–1.6 for body, relative units that survive 200% zoom, paragraph spacing tokens. Motion tokens carry reduced-motion alternatives.
- **Documentation template has an Accessibility section by default.** An empty section is a visible reminder; a missing section is forgotten forever. Per-component acceptance criteria travel into tickets (button: keyboard operable, 3:1 focus, 4.5:1 text in all states, announced purpose and state; modal: focus trapped, Esc closes, focus returns to trigger, background hidden from screen readers).
- **Testing routine:** design phase (contrast, colour-blindness simulation), pre-handoff (component checklist), post-development (keyboard and screen-reader pass), scheduled audits, plus axe-core in CI so regressions block release.

### 11. Animation specifications

- Ask first whether the team uses a library (GSAP, AnimeJS) or accepts Lottie/Rive output; then design inside those guardrails. Weigh library weight against need: CSS transitions or utility classes for simple motion.
- Figma cannot componentise duration and easing, so keep a written animation library of repeatable presets and apply them consistently.
- Spec every animation with: essential versus aesthetic (essential must match; aesthetic may be simplified), duration and phases, easing with the platform mapping (CSS `ease-out` = iOS `.easeOut` = Android `DecelerateInterpolator` = Material deceleration curve), trigger conditions including repeat-trigger and reverse behaviour, and performance notes (animate transform and opacity, not position; allow disabling on low-end devices). Always name a fallback.

### 12. Adoption and change control (short)

- Roll out tokens or a system as a design project: define the audience (designers fear lost flexibility, developers fear unusable tokens, PMs fear delay, management fears cost), recruit an ambassador per group, name the pain each group gets rid of, start with colours for immediate visible impact, set success metrics (token usage versus hard-coded values, reduction in unique values, QA visual bugs), and plan onboarding.
- Record decisions as Design Decision Records (context, decision, status, consequences) so choices survive staff turnover and are not relitigated.
- Triage change requests into critical / important / enhancement / experimental and map tiers to timelines (same day, sprint, roadmap). State trade-offs as hours and displaced work.

### Value systems (keep these as reusable tables)

**Token tiers** and what each may reference:

| Tier | Example | Value is | Has modes? |
|---|---|---|---|
| Core | `color/blue/500`, `space/4`, `radius/2` | Raw literal | No |
| Semantic | `text/primary`, `surface/raised`, `border/focus` | Alias to Core | Yes, per axis |
| Component | `button/primary/background` | Alias to Semantic (rarely Core) | Inherits |

**Collection per mode axis:**

| Collection | Modes | Holds | Never holds |
|---|---|---|---|
| Core | none | primitives | anything with usage meaning |
| Color (semantic) | Light / Dark / brand themes | text, surface, border, icon colours | spacing, sizes |
| Layout (semantic) | Mobile / Desktop (or density) | spacing, sizing, radii that change with breakpoint | colours |

**Component property types** and when each is the right tool:

| Property | Use for | Not for |
|---|---|---|
| Variant `◆` | Real visual states and sizes (default/hover/disabled, sm/md/lg) | Show/hide, content |
| Toggle `○` | Optional parts (leading icon, helper text) | State |
| Swap `↺` | Slots whose content is another component (icon, avatar, nested control) | Text |
| Content `@` | Label and text values | Layout |
| Nested `↳` | The two or three inner settings changed often | Everything an inner component exposes |

**Export presets to prepare on assets:**

| Asset | Web | Mobile |
|---|---|---|
| Icons | SVG, or PNG at 24 / 32 / 48 | PNG 1x / 2x / 3x |
| Photos | JPG (quality Low for backgrounds) at 1x / 2x; WebP/AVIF if supported | Per device tier |
| UI graphics with transparency | PNG 1x / 2x | PNG 1x / 2x / 3x |

---

## Build checklist (an agent's pass over a design system in Figma)

1. **Plan the scope.** Goal, surfaces (app, web, brands, platforms), time, historic system to inherit or replace, whether developers already use a component library (if so, mirror it: shadcn, UntitledUI, and similar have Figma counterparts), technical limits, who consumes it, onboarding rate.
2. **Choose the token vehicle.** Variables for a Figma-resident system with ≤ light/dark; external tokens with Git sync when developers consume tokens, more than four modes are needed, or composite typography tokens matter. Decide the export pipeline now.
3. **Create Core.** Primitive collection only: colour ramps, spacing scale (four to six values), radii, typography primitives. No modes here.
4. **Create Semantic.** One collection per mode axis (colour: Light/Dark; spacing: Mobile/Desktop). Every value is an alias to Core. Names read what/where/state.
5. **Add component tokens only where a component needs indirection.**
6. **Scope every variable** to the properties it may bind to. **Describe** every semantic and component variable. **Attach code syntax** per platform.
7. **Verify contrast per mode on semantic pairs** and in a testing file of real compositions.
8. **Build components on the foundations.** Bind every fill, stroke, radius, gap, and text property to a variable or style; no raw values.
9. **Model properties before variants.** Toggles, swaps, text, and a few nested properties; variants for genuine states and sizes. Prefix and order properties consistently. Standardise value names.
10. **Write descriptions** (purpose, behaviour, accessibility) and add alt-text properties to image and icon components.
11. **Mark helpers** with `_`/`.` and status with background colour.
12. **Stress with real content** and translated strings; check truncation and overflow.
13. **Keep foundations and components in separate files.** Publish foundations first, then components.
14. **Set up the icon page** with `icon-` names and export presets; wrap images with export settings; flatten SVGs and test the output.
15. **Structure the file** with the fixed page template; put annotation components, flow headings, and a resources page in place.
16. **Version at handoff** with a named, described version; mark sections Ready for dev; never edit a handed-off version.
17. **Branch for shared-library changes** on eligible plans; otherwise prove changes in a test file with screenshot comparison before publishing.
18. **Document accessibility criteria** per component and carry them into tickets.
19. **Instrument adoption:** read insert, detach, and team analytics monthly; pair with code usage data; keep announcement and support channels.
20. **Deprecate by marking and migrating**, never by deleting.

---

## Review lens: the questions Jun asks of a file or library

1. Could a developer who has never seen this file find what they need in the first minute? Would you, in three months?
2. Is there a foundations layer, and did it get more care than the components?
3. Are values bound to variables or styles everywhere, or are there raw hex and pixel values Dev Mode will show as numbers?
4. Does every semantic name say what, where, and which state? Are core tokens being used directly where a semantic token should sit?
5. Are collections split by mode axis, with modes only where values actually change?
6. Would the theming need exceed the plan's mode cap? Was that checked before choosing variables?
7. Is every variable scoped? Described? Given code syntax per platform?
8. Are there duplicated screens that should be one component with properties plus a variant card?
9. Are properties prefixed, ordered, and named consistently across components? Are nested properties limited to the frequently changed ones?
10. Are helper components hidden from publishing? Are deprecated ones marked, not deleted?
11. Do all interactive components have documented focus states, keyboard behaviour, and contrast that passes per mode?
12. Do image and icon components carry an alt-text property?
13. Is the handed-off version named, described, and locked? Is finished work marked Ready for dev?
14. If several people edit the library, is there a branch or a proving file, and a screenshot comparison before publish?
15. Are icons on one prefixed page with export presets? Do SVGs export without masks, filters, or clip paths?
16. Do the tokens reach code (export pipeline or Git sync), or do they stop at the Figma boundary?
17. Are library analytics being read, and does code-side usage confirm adoption?
18. Is there an owner, a cadence, an announcement channel, and a support channel?
19. Has the developer been asked whether they even use prototypes before one was built?
20. Is every deviation from the design, and every design decision, recorded where the next person will look?

---

## Known limits

- **Extraction lost the figures.** The book leans on screenshots for the property panel iconography, Token Studio and variables panels, GitHub sync settings, Dev Mode views, contrast checker, and the annotation cards (Figures 1.4–1.10, 4.6–4.10, 5.1–5.6, 6.1–6.27, 7.1–7.7, 8.1–8.8). This digest reconstructs the operational content from the surrounding prose; exact UI positions, dialog labels, and step-by-step click paths should be verified against current Figma.
- **Feature state is mid-2025.** Mode caps (4/40), Dev Mode annotation seat requirements, Code Connect plan gating, native contrast checker, and the AI features are described as they stood at writing. Jun himself says these change quarterly; re-check plan limits and feature availability before relying on a number.
- **Tool-specific and opinionated.** The token guidance is written around Token Studio and a GitHub personal-access-token sync with a single `tokens.json`; other pipelines (Style Dictionary configs, W3C DTCG format, Penpot) are mentioned but not covered in depth.
- **No plugin-API detail.** The book is written for designers using the UI. It does not describe `figma.variables`, `setBoundVariable`, `VARIABLE_ALIAS`, or component-property APIs. The agent must map the structural rules here onto the Plugin API itself (the one scripted hint is a video for bulk code-syntax assignment).
- **Not a construction or visual-craft lens.** Auto layout mechanics, constraints, nesting order, and grid work belong to Staiano; visual hierarchy, colour, and type craft belong to Wathan/Schoger. Prototyping technique and interaction detail belong to Schwarz; Jun's advice there is mostly "ask whether you need it, and do less".
- **Accessibility is designer-scope with an admitted gap.** Jun states he did not design specifically for screen readers; ARIA, landmarks, and live regions are named as developer concerns with pointers, not specified. Treat §10 as system hooks, not an accessibility standard.
- **Evidence is anecdotal.** Numbers (30–50% delivery speedup, 58% JPG saving, 30% German text expansion) come from one company's experience or single tests, not studies. Use them as sizing intuitions.
- **Stakeholder and AI chapters are thin for this purpose.** Review facilitation, feedback tiers, and AI tool assessments are summarised in one section or omitted; they do not change how a system is built in the file.

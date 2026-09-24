# FLS — Brand Assets

**Fidelity Ladder System · Design System A — "Resolution" (FLS-DS-A-1.0)**

The idea, made visible: *fidelity resolving*. A coarse hand sketch → discrete pixels →
clean vector → a gate. The palette is the **primitives of color** (true primaries),
the way a spec is the primitive of software. Bauhaus-schoolroom plain.

This folder is the complete brand kit — including marks and lockups that are **not**
used on the Admin Workbench screen — so a developer has every variant on hand.

## Files

| File | What it is | Use |
|------|------------|-----|
| `mark-full.svg` | Master mark, full color, 100-unit grid | App icon, splash, ≥40px |
| `mark-reduced.svg` | Four primaries + white gate-X + cross rules | 24–40px, favicons, dense UI |
| `mark-mono-knockout.svg` | One color, white on ink | Dark grounds, one-ink print |
| `mark-mono-ink.svg` | One color, ink outline on paper | Light grounds, one-ink print |
| `wordmark-horizontal.svg` | "FIDELITY LADDER" one line + tagline | Primary wordmark lockup |
| `wordmark-stacked.svg` | "FIDELITY / LADDER" two lines + tagline | Narrow / square placements |
| `favicon.svg` | Reduced mark tuned for tiny sizes | Modern browser favicon |
| `favicon-16.png` / `favicon-32.png` | Raster favicons | Legacy browser tabs |
| `apple-touch-icon-180.png` | 180×180 home-screen icon | iOS/Android add-to-home |
| `favicon.ico` | 32×32 ICO | Legacy `/favicon.ico` fallback |
| `tokens.css` | `:root` custom properties — full palette + type roles | Import as the source of truth |

## The mark — "Resolution Square"

Four cells, read left→right / top→bottom as a story of rising fidelity, all three
letters matched in cap-height, weight and centering:

- **F · blue `#005eb8` · the hand** — Caveat, centered. The human draft (rung 1 · SPEC).
- **L · yellow `#fdb913` · the pixel** — discrete squares with a gap. The machine step (rung 2 · WIRE). *Ink type rides on yellow.*
- **S · red `#e63329` · the vector** — clean grotesque, resolved (rung 3 · the flag / error accent).
- **gate · charcoal `#2b2823` · rung-tick X** — an X ticked like a ladder's rungs, white on **warm dark grey, never pure black**. The climb ends at a gate, not a summit.

Below ~40px the letters + gate rungs drop to the **reduced mark**: four primaries +
a plain white X in the gate corner. The square never loses its four cells.

## Rules (do / don't)

- **Do** keep clear space = one cell (25 units) on all sides.
- **Do** let one primary dominate per surface. **Red only ever flags.**
- **Do** set the wordmark in the resolved grotesque (Archivo 900 stand-in for Akzidenz Grotesk / Alternate Gothic).
- **Don't** recolor the quadrants.
- **Don't** set the wordmark in the hand (Caveat) or pixel (Silkscreen) face — those live only inside the mark.
- **Don't** make the gate pure black.
- **Don't** put chartreuse/thin colored type on cream; letters inside the mark are always paper `#f5f3ee` or ink `#16130f`.

## Palette

| Token | Hex | Role |
|-------|-----|------|
| `--a-paper` | `#f5f3ee` | Primary page ground |
| `--a-paper-2` | `#edeae1` | Card / recessed ground |
| `--a-ink` | `#16130f` | Type (crispest fidelity; not for fills) |
| `--a-muted` | `#6c6659` | Annotations, meta, rung numbers |
| `--a-line` | `#d7d2c6` | Hairlines, borders |
| `--a-gate` | `#2b2823` | Gate ground / flagged code (warm charcoal, not black) |
| `--a-blue` | `#005eb8` | Rung 1 · SPEC (coarsest step) |
| `--a-yellow` | `#fdb913` | Rung 2 · WIRE (ink type rides on it) |
| `--a-red` | `#e63329` | Rung 3 · flag / single error accent |
| `--a-grid` | `#dfe7ee` | Engineering-paper ruling |
| `--a-grid-bold` | `#cdd8e2` | Every 5th grid line |

## Type

- **Display / wordmark:** Archivo (500–900) — stand-in for Akzidenz Grotesk / Alternate Gothic.
- **Mono / annotations:** IBM Plex Mono (400/500/600).
- **Hand (mark only):** Caveat 700 — the "F".
- **Bitmap (mark only):** Silkscreen — the low-fidelity voice; never running text.

## Font note on the wordmark SVGs

`wordmark-*.svg` reference `Archivo` and `IBM Plex Mono` by name — text is **not**
outlined, so the font must be available where they render. Load Archivo + IBM Plex Mono
(Google Fonts) or convert text to paths before using them in an environment without the fonts.

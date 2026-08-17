"""Starter `fls bench` seed set — two vessels, direction-labeled per docs/bench-labeling.md.

Every seed here has a `direction` ('good' | 'bad') and, for 'bad' seeds, a `should_catch_by_rung`
(the earliest rung whose artifact makes the wrongness knowable). These labels are the *claim* the
scoreboard measures the ladder against; in a real run they come from two reviewers agreeing (or the
seed is excluded). This starter set is single-author and is marked as such — treat its numbers as a
plumbing demo until a second reviewer has co-labeled it.

Two vessels, both generic UI surfaces (no instance identity — see the OSS work-split rule):
  - `web-ui`    : a small component library (command-palette, formatters, a11y widgets).
  - `dashboard` : a metrics/table surface (tiles, sortable table, filters).

The 'bad' seeds are wrong-*direction*, not merely buggy: they build a coherent thing that is not
the thing the intent asked for. The `should_catch_by_rung` says where that divergence first shows:
a contradicted intent shows in the spec (rung 1); a wrong layout/interaction shows in the
wireframe/demo (rung 2/3); a wrong contract only provable by running the test shows at code (rung 4).
"""
from __future__ import annotations

from fls.bench import BAD, GOOD, BenchSeed

# --- Vessel A: web-ui component library ------------------------------------------------------
WEB_UI_SEEDS: list[BenchSeed] = [
    # good — pointed at exactly what the intent asks
    BenchSeed("web-cmdk-good", "web-ui", GOOD,
              "Cmd-K focuses the search field from anywhere, including with a modal open."),
    BenchSeed("web-debounce-good", "web-ui", GOOD,
              "Debounce collapses rapid calls so only the last call runs after the wait."),
    BenchSeed("web-currency-good", "web-ui", GOOD,
              "Format integer cents as USD with thousands separators; negatives parenthesized."),
    BenchSeed("web-a11y-good", "web-ui", GOOD,
              "Every input renders with an associated <label> referencing it by id."),
    # bad — wrong direction; wrongness knowable in the SPEC (contradicts stated intent) -> rung 1
    BenchSeed("web-cmdk-bad-modal", "web-ui", BAD,
              "Intent says Cmd-K FOCUSES search; this seed makes Cmd-K OPEN A MODAL instead.",
              should_catch_by_rung=1),
    BenchSeed("web-currency-bad-euro", "web-ui", BAD,
              "Intent says format as USD; this seed formats as EUR with a euro sign.",
              should_catch_by_rung=1),
    # bad — wrongness only visible once you can SEE it (wireframe) -> rung 2
    BenchSeed("web-a11y-bad-placeholder", "web-ui", BAD,
              "Intent requires real <label>s; this seed uses placeholder text as the label "
              "(looks labeled, isn't) — visible when the wireframe is inspected.",
              should_catch_by_rung=2),
    # bad — wrong CONTRACT, only provable by running the acceptance test on code -> rung 4
    BenchSeed("web-debounce-bad-leading", "web-ui", BAD,
              "Intent says only the LAST call runs (trailing); this seed fires on the LEADING "
              "edge instead — same signature, opposite semantics, caught by the test.",
              should_catch_by_rung=4),
]

# --- Vessel B: dashboard surface -------------------------------------------------------------
DASHBOARD_SEEDS: list[BenchSeed] = [
    # good
    BenchSeed("dash-tile-good", "dashboard", GOOD,
              "Add a KPI tile showing this month's total with a delta vs last month."),
    BenchSeed("dash-sort-good", "dashboard", GOOD,
              "Clicking a table header sorts by that column, toggling asc/desc."),
    BenchSeed("dash-filter-good", "dashboard", GOOD,
              "A date-range filter narrows the table to rows within the range, inclusive."),
    # bad — contradicts the stated intent in the SPEC -> rung 1
    BenchSeed("dash-tile-bad-average", "dashboard", BAD,
              "Intent asks for a month TOTAL; this seed shows a monthly AVERAGE instead.",
              should_catch_by_rung=1),
    # bad — wrong INTERACTION, visible once clickable in the demo -> rung 3
    BenchSeed("dash-sort-bad-reorder", "dashboard", BAD,
              "Intent is sort-on-header-click; this seed makes the header click REORDER "
              "(drag-move) the column instead — only obvious in the interactive demo.",
              should_catch_by_rung=3),
    # bad — wrong CONTRACT boundary, caught by the acceptance test -> rung 4
    BenchSeed("dash-filter-bad-exclusive", "dashboard", BAD,
              "Intent says the range is INCLUSIVE of both endpoints; this seed excludes the "
              "end date — off-by-one at the boundary, caught by the test.",
              should_catch_by_rung=4),
]

ALL_SEEDS: list[BenchSeed] = WEB_UI_SEEDS + DASHBOARD_SEEDS

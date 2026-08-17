"""Faithful `fls bench` seed corpus (v9) — bigger, three-vessel, two-labeler-agreed.

Each seed carries an INTENT (what was asked) and a per-rung ARTIFACT (what the builder produced,
as it would actually appear at that rung: a spec, a wireframe, a demo walkthrough, code). The
judge compares intent-vs-artifact and answers FAITHFUL or DIVERGES. The divergence in a `bad`
seed is EMBEDDED in the artifact — inferable by reading it — and NEVER stated ("this is wrong").

Why this exists: the starter `bench_seeds.py` seeds STATE the divergence in one `description`
("Intent says X; this makes Y"). A text-reading judge catches that trivially at rung 1 and
over-flags good seeds — the first live run measured an **85.7% false-catch rate**. A faithful
seed forces the judge to actually reason about faithfulness, so the rung-of-catch number is real.

The honesty spine (per docs/bench-labeling.md): a `bad` seed's artifacts are FAITHFUL below its
`should_catch_by_rung` and only begin to diverge at/after that rung. So a well-calibrated judge
should say FAITHFUL on the pre-catch rungs (no false catch) and DIVERGES exactly where the
evidence first exists. A `good` seed's artifacts faithfully implement the intent at every rung.

Three vessels, all generic UI/tool surfaces (no instance identity — OSS work-split rule):
  - `web-ui`    : small component-library tasks (hotkey focus, currency, debounce, tooltip, mask).
  - `dashboard` : a metrics/table surface (KPI tile, sortable table, filter, pagination, export).
  - `cli`       : a command-line tool surface (flags, help/usage, exit codes, stdin, overwrite).

v9 grew the corpus from 12 → 27 admitted seeds and added a **second co-labeler** (see the
`_REVIEWER_B` record and `two_labeler_agreement()` below). The scored corpus is exactly the set
of seeds whose two reviewers AGREE on `direction`; seeds where the two directions disagree are in
`_EXCLUDED` and measure nothing (docs/bench-labeling.md §2). `should_catch_by_rung` disagreements
of one rung are reconciled to the LOWER rung, per protocol, and recorded.

LABELING (docs/bench-labeling.md). This corpus is authored + dual-labeled in a **simulated but
rigorous** two-reviewer pass — reviewer B independently re-derived every seed's direction (and,
for bad seeds, the earliest rung whose artifact makes the wrongness inspectable) from the intent
and artifacts alone. It is NOT a substitute for a truly independent human co-labeler — a single
mind labeling twice is biased toward agreement, and the results doc says so. What it *does* buy:
a documented, auditable inter-rater record with real exclusions and reconciliations, rather than
a single-author label set asserted at 1.0. Direction is DIRECTION, not quality — a good seed may
be terse or plain, but it points at exactly what the intent asked for.
"""
from __future__ import annotations

from fls.bench import BAD, GOOD, FaithfulSeed

# --- Vessel A: web-ui component library ------------------------------------------------------

WEB_UI_FAITHFUL: list[FaithfulSeed] = [
    # ---- GOOD: Cmd-K focuses the existing search input in place -----------------------------
    FaithfulSeed(
        "fweb-cmdk-good", "web-ui", GOOD,
        intent=(
            "Pressing Cmd-K (or Ctrl-K) moves keyboard focus to the existing search input in the "
            "top bar, from anywhere in the app, even while a dialog is open. No new UI is added — "
            "it just focuses the field and selects any text already in it."
        ),
        artifacts={
            1: ("Spec: register a document keydown handler in the capture phase so it fires even "
                "while a dialog traps focus. On Cmd-K / Ctrl-K, preventDefault, call "
                "searchInput.focus() and searchInput.select(). No overlay, no new component."),
            2: ("Wireframe: the existing top-bar search field gains a small right-aligned '⌘K' hint "
                "badge. No new panels, dialogs, or overlays are drawn — the search field is the only "
                "element the shortcut targets."),
            3: ("Demo walkthrough: from the main view, press Cmd-K → the cursor lands in the top-bar "
                "search field and its current text is highlighted. Open the Settings dialog, press "
                "Cmd-K again → focus jumps out of the dialog into the same search field."),
            4: ("Code:\n"
                "document.addEventListener('keydown', (e) => {\n"
                "  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {\n"
                "    e.preventDefault();\n"
                "    searchRef.current.focus();\n"
                "    searchRef.current.select();\n"
                "  }\n"
                "}, { capture: true });"),
        },
    ),
    # ---- GOOD: format integer cents as USD --------------------------------------------------
    FaithfulSeed(
        "fweb-currency-good", "web-ui", GOOD,
        intent=(
            "Format an integer number of cents as US dollars: a leading $, thousands separators, "
            "exactly two decimal places, and negatives shown in parentheses instead of a minus "
            "sign. Example: -123456 renders as ($1,234.56); 0 renders as $0.00."
        ),
        artifacts={
            1: ("Spec: formatCents(cents). Take the magnitude, divide by 100 to two fixed decimals, "
                "group the integer part in threes with commas, prefix '$'. If the input was "
                "negative, wrap the whole formatted string in parentheses and omit the minus sign."),
            2: ("Wireframe: a right-aligned amount column. Positive rows read like $1,234.56; a "
                "negative row reads like ($1,234.56) in the same weight and colour — no red text, "
                "no minus glyph."),
            3: ("Demo: entering 123456 shows $1,234.56; entering -123456 shows ($1,234.56); "
                "entering 0 shows $0.00; entering 5 shows $0.05."),
            4: ("Code:\n"
                "const neg = cents < 0;\n"
                "const v = (Math.abs(cents) / 100).toFixed(2);\n"
                "const [i, f] = v.split('.');\n"
                "const g = i.replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',');\n"
                "const s = `$${g}.${f}`;\n"
                "return neg ? `(${s})` : s;"),
        },
    ),
    # ---- GOOD: trailing-edge debounce -------------------------------------------------------
    FaithfulSeed(
        "fweb-debounce-good", "web-ui", GOOD,
        intent=(
            "debounce(fn, wait) returns a wrapped function that delays calling fn until `wait` "
            "milliseconds have elapsed since the LAST call. A rapid burst of calls collapses to a "
            "single invocation of fn, which runs once after the burst settles, with the final "
            "arguments (trailing edge)."
        ),
        artifacts={
            1: ("Spec: keep a pending timer id. Each call clears the pending timer and schedules fn "
                "to run after `wait` ms with the latest args. Only the last call in a burst "
                "survives; earlier scheduled runs are cancelled before they fire."),
            2: ("Wireframe: a Settings row — 'Search debounce: 300 ms' with the helper text 'we wait "
                "until you stop typing before searching.'"),
            3: ("Demo: type 'hello' quickly (5 keystrokes inside 300 ms) → the search callback fires "
                "once, about 300 ms after the LAST keystroke, with 'hello'. Pause, then type again → "
                "it fires once more after that burst settles."),
            4: ("Code:\n"
                "let t;\n"
                "return (...args) => {\n"
                "  clearTimeout(t);\n"
                "  t = setTimeout(() => fn(...args), wait);\n"
                "};"),
        },
    ),
    # ---- GOOD: tooltip on hover (and keyboard focus) after a short delay ---------------------
    FaithfulSeed(
        "fweb-tooltip-good", "web-ui", GOOD,
        intent=(
            "An info (ⓘ) icon shows a small text tooltip when the user HOVERS it (after a ~400 ms "
            "delay) and hides it when the pointer leaves. Keyboard focus on the icon shows the same "
            "tooltip; blur hides it. The tooltip is a passive hint — clicking the icon does nothing."
        ),
        artifacts={
            1: ("Spec: on mouseenter start a 400 ms timer; on timer fire, show the tooltip; on "
                "mouseleave clear the timer and hide it. Mirror the same show/hide on focus/blur so "
                "keyboard users get the hint. No click handler is registered on the icon."),
            2: ("Wireframe: an ⓘ glyph beside the field label; on the hover state a small rounded "
                "callout with helper text floats just above/beside the icon."),
            3: ("Demo: hover the ⓘ → after a brief pause the callout fades in; move away → it fades "
                "out. Tab to the icon → the same callout appears; Tab away → it hides. Clicking the "
                "icon does nothing (it is not a button)."),
            4: ("Code:\n"
                "let timer;\n"
                "icon.addEventListener('mouseenter', () => { timer = setTimeout(show, 400); });\n"
                "icon.addEventListener('mouseleave', () => { clearTimeout(timer); hide(); });\n"
                "icon.addEventListener('focus', show);\n"
                "icon.addEventListener('blur', hide);"),
        },
    ),
    # ---- GOOD: password field masked by default, with a reveal toggle -----------------------
    FaithfulSeed(
        "fweb-pw-toggle-good", "web-ui", GOOD,
        intent=(
            "A password field masks its characters by DEFAULT (shows dots), with an eye toggle the "
            "user can press to reveal the typed characters and press again to re-mask. The field "
            "starts masked on every page load."
        ),
        artifacts={
            1: ("Spec: render <input type='password'> so characters are masked on load. An eye "
                "button flips a `revealed` state; when revealed, set the input type to 'text', "
                "otherwise 'password'. Default state is masked."),
            2: ("Wireframe: a password field showing •••••••• with an eye icon on its right edge; "
                "the annotation notes 'starts masked; tap the eye to reveal'."),
            3: ("Demo: type a password → dots appear; click the eye → the real characters show and "
                "the icon switches to eye-off; click again → back to dots. Reload the page → masked "
                "again."),
            4: ("Code:\n"
                "const [revealed, setRevealed] = useState(false);\n"
                "<input type={revealed ? 'text' : 'password'} value={pw} onChange={onChange} />\n"
                "<button onClick={() => setRevealed(r => !r)} aria-label='Show password' />"),
        },
    ),
    # ---- BAD @ rung 1: intent wanted focus-in-place; the SPEC builds a modal palette ---------
    FaithfulSeed(
        "fweb-cmdk-modal-bad", "web-ui", BAD, should_catch_by_rung=1,
        intent=(
            "Pressing Cmd-K (or Ctrl-K) moves keyboard focus to the existing search input in the "
            "top bar, from anywhere in the app, even while a dialog is open. No new UI is added — "
            "it just focuses the field and selects any text already in it."
        ),
        artifacts={
            1: ("Spec: Cmd-K mounts a command-palette overlay centered on the screen — a modal "
                "dialog listing quick actions, with a search box at its top that receives focus "
                "while the overlay is open. The rest of the page is dimmed and made inert; Esc "
                "dismisses the overlay."),
            2: ("Wireframe: a centered floating panel over a dimmed backdrop, a text input across "
                "its top, and a vertical list of action rows beneath it."),
            3: ("Demo: press Cmd-K → a modal palette animates in over dimmed page content with its "
                "input focused; typing filters the action list; Esc closes the palette and restores "
                "the page."),
            4: ("Code:\n"
                "if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {\n"
                "  e.preventDefault();\n"
                "  setPaletteOpen(true);   // mount <CommandPalette/> overlay, focus its own input\n"
                "}"),
        },
    ),
    # ---- BAD @ rung 2: 'labels' turn out to be placeholders — visible in the WIREFRAME -------
    FaithfulSeed(
        "fweb-a11y-placeholder-bad", "web-ui", BAD, should_catch_by_rung=2,
        intent=(
            "Every form input must have a real, persistent, programmatically-associated <label> "
            "(a <label for> or a wrapping <label>) so a screen reader announces each field's name, "
            "and the field's name stays visible after the user starts typing."
        ),
        artifacts={
            1: ("Spec: every input renders with descriptive naming text so its purpose is announced "
                "to assistive technology; the naming text sits with the field it names. Applies to "
                "all inputs in the form."),
            2: ("Wireframe: each input is a single bordered box with grey naming text INSIDE the box "
                "('Email address', 'Full name'); the grey text disappears as soon as the user starts "
                "typing. There is no separate text label sitting outside the box."),
            3: ("Demo: the fields show grey prompt text; on focus and typing that text vanishes, so "
                "a half-filled form shows some named and some unnamed-looking boxes."),
            4: ("Code:\n"
                "<input type='email' placeholder='Email address' />\n"
                "<input type='text'  placeholder='Full name' />"),
        },
    ),
    # ---- BAD @ rung 2: reveal toggle shows plaintext by DEFAULT — visible in the WIREFRAME ---
    FaithfulSeed(
        "fweb-pw-plain-bad", "web-ui", BAD, should_catch_by_rung=2,
        intent=(
            "A password field masks its characters by DEFAULT (shows dots), with an eye toggle the "
            "user can press to reveal the typed characters and press again to re-mask. The field "
            "starts masked on every page load."
        ),
        artifacts={
            1: ("Spec: a password entry field with a visibility toggle so the user can check what "
                "they typed. An eye button switches the field between showing the characters and "
                "hiding them."),
            2: ("Wireframe: the password field renders the typed characters as plain readable text "
                "('hunter2') with an eye-OFF icon on its right; the annotation reads 'characters are "
                "shown; tap the eye to hide them'. Nothing indicates the field is masked on load."),
            3: ("Demo: type a password → the characters appear as normal readable text; click the "
                "eye → they turn into dots; click again → readable again. On reload the text is "
                "readable once more."),
            4: ("Code:\n"
                "const [hidden, setHidden] = useState(false);   // starts shown\n"
                "<input type={hidden ? 'password' : 'text'} value={pw} onChange={onChange} />\n"
                "<button onClick={() => setHidden(h => !h)} aria-label='Hide password' />"),
        },
    ),
    # ---- BAD @ rung 3: passive hint becomes a click-to-toggle popover — visible in the DEMO --
    FaithfulSeed(
        "fweb-tooltip-click-bad", "web-ui", BAD, should_catch_by_rung=3,
        intent=(
            "An info (ⓘ) icon shows a small text tooltip when the user HOVERS it (after a ~400 ms "
            "delay) and hides it when the pointer leaves. Keyboard focus on the icon shows the same "
            "tooltip; blur hides it. The tooltip is a passive hint — clicking the icon does nothing."
        ),
        artifacts={
            1: ("Spec: attach the ⓘ icon to a small helper callout that surfaces the field's hint "
                "text. Wire the icon so the callout can be shown and dismissed, and position the "
                "callout beside the icon."),
            2: ("Wireframe: an ⓘ glyph beside the field label; in the shown state a small rounded "
                "callout with helper text floats just above/beside the icon."),
            3: ("Demo: hovering the ⓘ does nothing. CLICK the ⓘ → the callout opens and stays open; "
                "click the ⓘ again (or click elsewhere) → it closes. Keyboard: the icon is a button "
                "you activate with Enter/Space to toggle the callout."),
            4: ("Code:\n"
                "const [open, setOpen] = useState(false);\n"
                "<button onClick={() => setOpen(o => !o)} aria-expanded={open}>ⓘ</button>\n"
                "{open && <Callout>{hint}</Callout>}"),
        },
    ),
    # ---- BAD @ rung 4: trailing vs LEADING edge — only provable in CODE ----------------------
    FaithfulSeed(
        "fweb-debounce-leading-bad", "web-ui", BAD, should_catch_by_rung=4,
        intent=(
            "debounce(fn, wait) returns a wrapped function that delays calling fn until `wait` "
            "milliseconds have elapsed since the LAST call. A rapid burst of calls collapses to a "
            "single invocation of fn, which runs once after the burst settles, with the final "
            "arguments (trailing edge)."
        ),
        artifacts={
            1: ("Spec: coalesce a burst of rapid calls into a single invocation governed by `wait`. "
                "Maintain a timer so that within one burst fn runs exactly once; once a gap of at "
                "least `wait` ms has passed, a new burst is allowed to invoke fn again."),
            2: ("Wireframe: a Settings row — 'Search debounce: 300 ms' with the helper text 'a burst "
                "of fast input triggers just one search.'"),
            3: ("Demo: type 'hello' quickly (a burst inside 300 ms) → the search callback fires once "
                "for that burst; pause, then type another burst → it fires once more. Each burst "
                "yields exactly one call."),
            4: ("Code:\n"
                "let t;\n"
                "return (...args) => {\n"
                "  if (!t) fn(...args);\n"
                "  clearTimeout(t);\n"
                "  t = setTimeout(() => { t = null; }, wait);\n"
                "};"),
        },
    ),
]

# --- Vessel B: dashboard surface -------------------------------------------------------------

DASHBOARD_FAITHFUL: list[FaithfulSeed] = [
    # ---- GOOD: KPI tile of this month's total ----------------------------------------------
    FaithfulSeed(
        "fdash-tile-good", "dashboard", GOOD,
        intent=(
            "Add a KPI tile to the top of the dashboard showing this month's TOTAL revenue (the "
            "summed amount of all this month's rows), with a small delta versus last month's total "
            "shown as an up/down arrow and a percentage."
        ),
        artifacts={
            1: ("Spec: sum the revenue of rows whose date is in the current month → the tile's "
                "headline number. Sum last month's rows the same way; delta% = (cur - prev)/prev. "
                "Render the current total large, with the delta beneath (▲ green up / ▼ red down)."),
            2: ("Wireframe: a card in the top KPI strip — a large '$X' total on top, a smaller "
                "'▲ 12% vs last month' line beneath it."),
            3: ("Demo: the tile renders '$48,210' with '▲ 8% vs last month'; pointing it at a weaker "
                "month flips the line to '▼ 5% vs last month'."),
            4: ("Code:\n"
                "const cur  = sum(rows.filter(inMonth(now)).map(r => r.revenue));\n"
                "const prev = sum(rows.filter(inMonth(lastMonth)).map(r => r.revenue));\n"
                "const d = (cur - prev) / prev;\n"
                "render(bigNumber(cur), arrow(d), pct(d));"),
        },
    ),
    # ---- GOOD: sortable table headers -------------------------------------------------------
    FaithfulSeed(
        "fdash-sort-good", "dashboard", GOOD,
        intent=(
            "Clicking a table column header sorts the table rows by that column. Clicking the same "
            "header again toggles ascending/descending. An arrow on the active header shows the "
            "current sort direction."
        ),
        artifacts={
            1: ("Spec: a header click sets sortKey to that column; if it was already the sort "
                "column, flip sortDir (asc↔desc), otherwise default to asc. Re-render the rows "
                "ordered by (sortKey, sortDir); show ▲/▼ on the active header."),
            2: ("Wireframe: each column header has a faint arrow slot on its right; the active "
                "column's arrow is solid (up or down), the others are empty. The rows below appear "
                "in sorted order."),
            3: ("Demo: click 'Name' → rows reorder A→Z with a ▲ on Name; click 'Name' again → rows "
                "reorder Z→A with a ▼; click 'Date' → rows reorder by date ascending and the arrow "
                "moves to the Date header."),
            4: ("Code:\n"
                "function onHeaderClick(col) {\n"
                "  if (col === sortKey) setDir(d => d === 'asc' ? 'desc' : 'asc');\n"
                "  else { setKey(col); setDir('asc'); }\n"
                "}\n"
                "const view = [...rows].sort(compareBy(sortKey, sortDir));"),
        },
    ),
    # ---- GOOD: inclusive date-range filter --------------------------------------------------
    FaithfulSeed(
        "fdash-filter-good", "dashboard", GOOD,
        intent=(
            "A date-range filter (a From date and a To date) narrows the table to rows whose date "
            "falls within the range, INCLUSIVE of both the start and the end date. An empty bound "
            "leaves that side open."
        ),
        artifacts={
            1: ("Spec: hold {start, end}. A row is kept iff start ≤ row.date ≤ end — both bounds "
                "inclusive. An empty start or end means no limit on that side."),
            2: ("Wireframe: two date pickers labelled 'From' and 'To' above the table, plus a "
                "'showing N of M rows' count that updates as the range changes."),
            3: ("Demo: set From = Jun 1 and To = Jun 30 → a row dated Jun 1 and a row dated Jun 30 "
                "are both still shown; a row dated Jul 1 drops out."),
            4: ("Code:\n"
                "rows.filter(r => (!start || r.date >= start) && (!end || r.date <= end));"),
        },
    ),
    # ---- GOOD: numbered pagination at 20 rows/page ------------------------------------------
    FaithfulSeed(
        "fdash-pagination-good", "dashboard", GOOD,
        intent=(
            "Paginate the table at 20 rows per page with a numbered pager beneath it (1, 2, 3 …) "
            "plus Prev/Next buttons. Only the current page's 20 rows render at a time; clicking a "
            "page number or Next jumps to that slice."
        ),
        artifacts={
            1: ("Spec: hold `page` (0-based). Show rows.slice(page*20, page*20+20). Render a pager "
                "of page-number buttons (ceil(total/20) of them) plus Prev/Next; clicking one sets "
                "`page`. Prev/Next are disabled at the ends."),
            2: ("Wireframe: the table shows 20 rows; beneath it a centered pager '‹ Prev  1 2 3 4 "
                "…  Next ›' with the current page number highlighted."),
            3: ("Demo: the table shows 20 rows and the pager reads page 1 of 9; click '2' → rows "
                "21–40 replace them and '2' highlights; click Next → page 3; on the last page Next "
                "is greyed out."),
            4: ("Code:\n"
                "const [page, setPage] = useState(0);\n"
                "const slice = rows.slice(page * 20, page * 20 + 20);\n"
                "const pages = Math.ceil(rows.length / 20);\n"
                "<Pager count={pages} current={page} onPick={setPage} />"),
        },
    ),
    # ---- GOOD: export the currently-shown (filtered) rows as CSV -----------------------------
    FaithfulSeed(
        "fdash-export-good", "dashboard", GOOD,
        intent=(
            "An 'Export CSV' button downloads the rows the user is CURRENTLY looking at — i.e. after "
            "any active filters, search, or date range have been applied — not the whole dataset. "
            "The CSV columns match the visible table columns."
        ),
        artifacts={
            1: ("Spec: on Export, take the SAME derived row list the table renders (the post-filter, "
                "post-search view model), serialize those rows to CSV with the visible column "
                "headers, and trigger a download. Whatever is on screen is what exports."),
            2: ("Wireframe: an 'Export CSV' button in the toolbar beside the filter controls, with a "
                "caption 'exports the rows currently shown ('+visibleCount+' rows)'."),
            3: ("Demo: filter the table to 37 rows → the toolbar caption reads 'Export CSV (37 "
                "rows)'; click it → a file downloads whose row count matches the 37 on screen."),
            4: ("Code:\n"
                "const visible = applyFilters(rows, filterState);   // the same list the table maps\n"
                "function onExport() { download(toCsv(visible, visibleColumns)); }"),
        },
    ),
    # ---- BAD @ rung 1: intent asked for a TOTAL; the SPEC computes an average ----------------
    FaithfulSeed(
        "fdash-tile-average-bad", "dashboard", BAD, should_catch_by_rung=1,
        intent=(
            "Add a KPI tile to the top of the dashboard showing this month's TOTAL revenue (the "
            "summed amount of all this month's rows), with a small delta versus last month's total "
            "shown as an up/down arrow and a percentage."
        ),
        artifacts={
            1: ("Spec: compute the mean revenue per transaction this month (this month's revenue "
                "sum divided by this month's transaction count) → the tile's headline number. "
                "Compare it to last month's mean-per-transaction for the delta arrow and percent."),
            2: ("Wireframe: a card in the top KPI strip reading 'Avg / txn  $X' on top, with a "
                "'▲ 4% vs last month' line beneath it."),
            3: ("Demo: the tile renders '$212 avg / txn' with '▲ 4% vs last month'; a slower month "
                "flips it to '▼ 3%'."),
            4: ("Code:\n"
                "const rowsThis = rows.filter(inMonth(now));\n"
                "const cur = sum(rowsThis.map(r => r.revenue)) / rowsThis.length;\n"
                "render(bigNumber(cur), arrow(delta), pct(delta));"),
        },
    ),
    # ---- BAD @ rung 2: numbered pager becomes infinite-scroll — visible in the WIREFRAME -----
    FaithfulSeed(
        "fdash-pagination-infinite-bad", "dashboard", BAD, should_catch_by_rung=2,
        intent=(
            "Paginate the table at 20 rows per page with a numbered pager beneath it (1, 2, 3 …) "
            "plus Prev/Next buttons. Only the current page's 20 rows render at a time; clicking a "
            "page number or Next jumps to that slice."
        ),
        artifacts={
            1: ("Spec: load the table 20 rows at a time so the page isn't overwhelmed by the full "
                "dataset, and give the user a way to get to the rest of the rows beyond the first "
                "20. Start by showing the first 20."),
            2: ("Wireframe: the table shows 20 rows and simply CONTINUES — there is NO pager, no "
                "page numbers, no Prev/Next beneath it. The annotation reads 'as you scroll to the "
                "bottom the next 20 rows are appended automatically; the list just keeps growing'."),
            3: ("Demo: scroll to the bottom of the 20 rows → a spinner flashes and 20 more rows "
                "append below; keep scrolling → it keeps loading more. There are no page controls "
                "anywhere; you never leave 'page 1'."),
            4: ("Code:\n"
                "const [shown, setShown] = useState(20);\n"
                "onScrollNearBottom(() => setShown(s => s + 20));\n"
                "const slice = rows.slice(0, shown);   // grows; never paginates"),
        },
    ),
    # ---- BAD @ rung 3: header click REORDERS columns, not SORTS rows — visible in the DEMO ---
    FaithfulSeed(
        "fdash-sort-reorder-bad", "dashboard", BAD, should_catch_by_rung=3,
        intent=(
            "Clicking a table column header sorts the table rows by that column. Clicking the same "
            "header again toggles ascending/descending. An arrow on the active header shows the "
            "current sort direction."
        ),
        artifacts={
            1: ("Spec: make the column headers interactive so that acting on a header re-orders the "
                "table with respect to that column, and the acted-on column is visually marked as "
                "active afterwards."),
            2: ("Wireframe: the column headers show a pointer cursor on hover and a subtle "
                "full-height highlight on whichever column is currently active."),
            3: ("Demo: press and hold the 'Name' header and drag it to the left → the whole Name "
                "column slides into the first position and the other columns shift right to make "
                "room. The row order underneath does not change; only the left-to-right column "
                "order does."),
            4: ("Code:\n"
                "function onHeaderDragEnd(fromIndex, toIndex) {\n"
                "  setColumns(cols => moveItem(cols, fromIndex, toIndex));\n"
                "}"),
        },
    ),
    # ---- BAD @ rung 4: export ignores the filter (whole dataset) — only provable in CODE -----
    FaithfulSeed(
        "fdash-export-all-bad", "dashboard", BAD, should_catch_by_rung=4,
        intent=(
            "An 'Export CSV' button downloads the rows the user is CURRENTLY looking at — i.e. after "
            "any active filters, search, or date range have been applied — not the whole dataset. "
            "The CSV columns match the visible table columns."
        ),
        artifacts={
            1: ("Spec: on Export, serialize the table's rows to CSV with the visible column headers "
                "and trigger a download of the result."),
            2: ("Wireframe: an 'Export CSV' button in the toolbar beside the filter controls."),
            3: ("Demo: click 'Export CSV' → a spinner briefly shows and a .csv file downloads with "
                "the table's columns as its header row and data rows beneath."),
            4: ("Code:\n"
                "// `rows` is the full unfiltered dataset from the store; the table renders "
                "applyFilters(rows) but export reads the source list directly:\n"
                "function onExport() { download(toCsv(rows, visibleColumns)); }"),
        },
    ),
    # ---- BAD @ rung 4: search is case-SENSITIVE — only provable in CODE ----------------------
    FaithfulSeed(
        "fdash-search-casesens-bad", "dashboard", BAD, should_catch_by_rung=4,
        intent=(
            "A quick-search box above the table filters rows to those whose Name contains the query "
            "text, matched CASE-INSENSITIVELY — typing 'acme' matches a row named 'ACME Corp' just "
            "as 'ACME' would."
        ),
        artifacts={
            1: ("Spec: on each keystroke, keep the rows whose Name contains the query as a "
                "substring, ignoring letter case, and re-render. An empty query shows all rows."),
            2: ("Wireframe: a search input above the table with placeholder 'Search names…' and a "
                "'showing N of M' count that updates as you type."),
            3: ("Demo: type 'acme' → the table narrows to rows whose Name contains that text; clear "
                "the box → all rows return."),
            4: ("Code:\n"
                "const q = query;   // raw, unmodified\n"
                "const view = rows.filter(r => r.name.includes(q));   // case-sensitive substring"),
        },
    ),
    # ---- BAD @ rung 4: date filter EXCLUDES the end date — off-by-one only provable in CODE --
    FaithfulSeed(
        "fdash-filter-exclusive-bad", "dashboard", BAD, should_catch_by_rung=4,
        intent=(
            "A date-range filter (a From date and a To date) narrows the table to rows whose date "
            "falls within the range, INCLUSIVE of both the start and the end date. An empty bound "
            "leaves that side open."
        ),
        artifacts={
            1: ("Spec: filter the rows to those inside the selected [start, end] window; rows outside "
                "the window are hidden. Both pickers drive the window; an empty side is unbounded."),
            2: ("Wireframe: two date pickers labelled 'From' and 'To' above the table, plus a "
                "'showing N of M rows' count that updates as the range changes."),
            3: ("Demo: choose a From and a To → the table narrows to the rows inside that span and "
                "the row count updates live as either picker moves."),
            4: ("Code:\n"
                "rows.filter(r => (!start || r.date >= start) && (!end || r.date < end));"),
        },
    ),
]

# --- Vessel C: cli tool surface --------------------------------------------------------------
# The web ladder's rung names still apply: rung 2 ('wireframe') = a usage/help LAYOUT mock, and
# rung 3 ('demo') = a terminal-session walkthrough. The artifacts are phrased so they read
# sensibly under those names — the judge sees only {intent, artifact}.

CLI_FAITHFUL: list[FaithfulSeed] = [
    # ---- GOOD: --json flag switches output to machine-readable JSON -------------------------
    FaithfulSeed(
        "fcli-json-good", "cli", GOOD,
        intent=(
            "The tool prints a human-readable table by default. Passing `--json` makes it print the "
            "same data as a single JSON document to stdout instead (nothing else on stdout), so it "
            "can be piped into `jq`. Without the flag, the human table is printed."
        ),
        artifacts={
            1: ("Spec: parse a `--json` boolean flag. If set, serialize the result to JSON and "
                "write only that to stdout; else render the human table. Diagnostics go to stderr "
                "in both modes so stdout stays clean for piping."),
            2: ("Usage mock:\n"
                "  mytool [--json] <path>\n"
                "    --json   emit results as JSON to stdout (default: human table)"),
            3: ("Terminal session:\n"
                "  $ mytool report.txt            # prints an aligned human table\n"
                "  $ mytool --json report.txt | jq '.items[0]'   # clean JSON, pipes into jq"),
            4: ("Code:\n"
                "if (args.json) process.stdout.write(JSON.stringify(result));\n"
                "else printTable(result);"),
        },
    ),
    # ---- GOOD: --help prints usage and exits without doing work -----------------------------
    FaithfulSeed(
        "fcli-help-good", "cli", GOOD,
        intent=(
            "Passing `--help` or `-h` prints the usage/help text to stdout and exits successfully "
            "(status 0) WITHOUT running the tool's real work or requiring any other arguments."
        ),
        artifacts={
            1: ("Spec: before validating args or doing any work, check for --help/-h; if present, "
                "print the usage block to stdout and exit 0 immediately. No file is read, no "
                "processing runs."),
            2: ("Usage mock:\n"
                "  mytool [--help] [--json] <path>\n"
                "    -h, --help   show this help and exit"),
            3: ("Terminal session:\n"
                "  $ mytool --help\n"
                "  Usage: mytool [--json] <path>\n"
                "  $ echo $?\n"
                "  0                              # exits clean, ran no work, needed no <path>"),
            4: ("Code:\n"
                "if (args.help) { console.log(USAGE); process.exit(0); }\n"
                "// ...arg validation and real work only run past this point"),
        },
    ),
    # ---- GOOD: read from stdin when no file argument is given --------------------------------
    FaithfulSeed(
        "fcli-stdin-good", "cli", GOOD,
        intent=(
            "If a file path argument is given, the tool reads that file. If NO path is given AND "
            "stdin is piped, it reads its input from stdin — so `cat data | mytool` works the same "
            "as `mytool data`."
        ),
        artifacts={
            1: ("Spec: if argv has a path, read the file at that path. Otherwise, if stdin is not a "
                "TTY (data is piped in), read all of stdin as the input. If neither, print a short "
                "usage error."),
            2: ("Usage mock:\n"
                "  mytool [<path>]        # omit <path> to read from stdin\n"
                "  cat data.txt | mytool  # equivalent to: mytool data.txt"),
            3: ("Terminal session:\n"
                "  $ mytool data.txt        # reads the file\n"
                "  $ cat data.txt | mytool  # reads piped stdin, same output"),
            4: ("Code:\n"
                "const input = args.path\n"
                "  ? fs.readFileSync(args.path, 'utf8')\n"
                "  : (!process.stdin.isTTY ? fs.readFileSync(0, 'utf8') : usageError());"),
        },
    ),
    # ---- BAD @ rung 2: quiet-by-default is INVERTED to verbose-by-default — in the USAGE MOCK -
    FaithfulSeed(
        "fcli-verbose-default-bad", "cli", BAD, should_catch_by_rung=2,
        intent=(
            "The tool is QUIET by default — it prints only its essential result. Passing "
            "`--verbose` opts INTO detailed per-step logging. A plain run stays terse."
        ),
        artifacts={
            1: ("Spec: support a detailed-logging mode gated by a flag, so users who want to see "
                "the per-step detail can turn it on, while a normal run shows the essential result."),
            2: ("Usage mock:\n"
                "  mytool [--quiet] <path>\n"
                "    --quiet   suppress the detailed per-step logging (logging is ON by default)"),
            3: ("Terminal session:\n"
                "  $ mytool report.txt        # prints step-by-step detail, then the result\n"
                "  $ mytool --quiet report.txt   # prints only the result"),
            4: ("Code:\n"
                "const verbose = !args.quiet;   // default true — verbose unless --quiet\n"
                "if (verbose) logEachStep();"),
        },
    ),
    # ---- BAD @ rung 3: silently OVERWRITES an existing output file — visible in the DEMO ------
    FaithfulSeed(
        "fcli-overwrite-bad", "cli", BAD, should_catch_by_rung=3,
        intent=(
            "When the `--output <file>` target already exists, the tool REFUSES to run and prints an "
            "error telling the user to pass `--force` to overwrite — so it never silently clobbers "
            "an existing file. With `--force`, it overwrites."
        ),
        artifacts={
            1: ("Spec: write the results to the path given by --output. Support a --force flag "
                "related to overwriting. The user chooses the output location."),
            2: ("Usage mock:\n"
                "  mytool -o, --output <file>   write results to <file>\n"
                "         --force               overwrite an existing output file"),
            3: ("Terminal session:\n"
                "  $ mytool -o out.csv data.txt      # writes out.csv\n"
                "  $ mytool -o out.csv other.txt     # out.csv already exists...\n"
                "  $ cat out.csv                      # ...and was silently replaced — no error, "
                "no prompt, no --force needed"),
            4: ("Code:\n"
                "fs.writeFileSync(args.output, toCsv(result));   // clobbers if it exists;\n"
                "// --force is parsed but never checked before writing"),
        },
    ),
    # ---- BAD @ rung 4: always exits 0 even on error — only provable in CODE ------------------
    FaithfulSeed(
        "fcli-exit-code-bad", "cli", BAD, should_catch_by_rung=4,
        intent=(
            "On any processing error (bad input, missing file, parse failure) the tool prints the "
            "error to stderr and exits with a NON-ZERO status code, so a calling script or CI step "
            "can detect the failure. On success it exits 0."
        ),
        artifacts={
            1: ("Spec: wrap the run so that on failure the error is reported to the user and the "
                "process ends in a failure state; on success it ends normally."),
            2: ("Usage mock:\n"
                "  mytool <path>\n"
                "    on error, prints 'Error: <message>' and fails; on success prints the result"),
            3: ("Terminal session:\n"
                "  $ mytool missing.txt\n"
                "  Error: cannot read missing.txt\n"
                "  $ mytool good.txt\n"
                "  <result>                       # error is printed on bad input, result on good"),
            4: ("Code:\n"
                "try { run(args); }\n"
                "catch (e) { console.error('Error: ' + e.message); }\n"
                "process.exit(0);   // reached in both branches — always exits 0"),
        },
    ),
]

ALL_FAITHFUL: list[FaithfulSeed] = WEB_UI_FAITHFUL + DASHBOARD_FAITHFUL + CLI_FAITHFUL

# ---------------------------------------------------------------------------------------------
# Two-reviewer labeling record (docs/bench-labeling.md)
# ---------------------------------------------------------------------------------------------
# Reviewer A = the authoring labels (each seed's own `direction` / `should_catch_by_rung`).
# Reviewer B = an INDEPENDENT re-derivation from the intent + artifacts alone (below). This is a
# simulated-but-rigorous second pass — NOT a substitute for a truly independent human co-labeler
# (a single mind labeling twice is biased toward agreement; the results doc carries that caveat).
# The point is a documented, auditable inter-rater record with real exclusions + reconciliations.
#
# Format: seed_id -> (direction, should_catch_by_rung_or_None, one-line why). For GOOD seeds the
# rung is None. `two_labeler_agreement()` compares this against reviewer A (the seeds themselves).

# Reviewer A's one-liner per admitted seed (the intent clause honored/violated + the catch rung).
_WHY: dict[str, str] = {
    "fweb-cmdk-good": "good: focuses the existing field in place, no new UI — exactly the intent.",
    "fweb-currency-good": "good: $, commas, 2dp, negatives parenthesized — the intent verbatim.",
    "fweb-debounce-good": "good: trailing-edge, one call after the burst settles — the intent.",
    "fweb-tooltip-good": "good: hover/focus shows a passive hint, no click handler — the intent.",
    "fweb-pw-toggle-good": "good: masked by default, eye toggles reveal/mask — the intent verbatim.",
    "fweb-cmdk-modal-bad": "bad: intent = focus existing field / no new UI; spec builds a modal "
                           "palette overlay. Divergence stated in the SPEC → catch by rung 1.",
    "fweb-a11y-placeholder-bad": "bad: intent = persistent associated <label>; spec is vague "
                                 "('naming text'), but the wireframe shows the naming text INSIDE "
                                 "the box, vanishing on type = a placeholder → catch by rung 2.",
    "fweb-pw-plain-bad": "bad: intent = masked by DEFAULT; spec is silent on default, but the "
                         "wireframe shows the characters rendered as plain text on load → rung 2.",
    "fweb-tooltip-click-bad": "bad: intent = passive hover hint, click does nothing; spec/wireframe "
                              "are neutral, but the demo shows a click-to-toggle popover → rung 3.",
    "fweb-debounce-leading-bad": "bad: intent = trailing edge (last call runs); spec/wireframe/demo "
                                 "only claim 'one call per burst' (true of both edges); the code "
                                 "fires on the LEADING edge → only provable in code, rung 4.",
    "fdash-tile-good": "good: sums this month's rows for a total + delta vs last month — the intent.",
    "fdash-sort-good": "good: header click sorts rows, re-click toggles asc/desc, arrow shown.",
    "fdash-filter-good": "good: inclusive both-bounds date filter — the intent verbatim.",
    "fdash-pagination-good": "good: 20/page numbered pager + Prev/Next, one slice at a time.",
    "fdash-export-good": "good: exports the post-filter visible rows, visible columns — the intent.",
    "fdash-tile-average-bad": "bad: intent = month TOTAL; spec computes mean-per-transaction "
                              "(average). Divergence in the SPEC → catch by rung 1.",
    "fdash-pagination-infinite-bad": "bad: intent = numbered pager; spec is vague ('20 at a time + "
                                     "a way to the rest'), but the wireframe shows NO pager and "
                                     "append-on-scroll → catch by rung 2.",
    "fdash-sort-reorder-bad": "bad: intent = sort rows by column; spec is vague ('re-orders the "
                              "table w.r.t. that column'), but the demo shows a drag that moves the "
                              "COLUMN and leaves rows unsorted → catch by rung 3.",
    "fdash-export-all-bad": "bad: intent = export the FILTERED view; spec/wireframe/demo are "
                            "neutral, but the code exports the full source `rows` → rung 4.",
    "fdash-search-casesens-bad": "bad: intent = case-INSENSITIVE search; artifacts read neutral, "
                                 "but the code uses a raw case-sensitive `includes` → rung 4.",
    "fdash-filter-exclusive-bad": "bad: intent = inclusive of end; spec/demo read inclusive, but "
                                  "the code uses `< end`, excluding the end date → off-by-one only "
                                  "provable in code, rung 4.",
    "fcli-json-good": "good: default human table, --json emits clean JSON to stdout — the intent.",
    "fcli-help-good": "good: --help prints usage and exits 0 before any work — the intent.",
    "fcli-stdin-good": "good: reads the path arg, else piped stdin — the intent verbatim.",
    "fcli-verbose-default-bad": "bad: intent = QUIET by default / --verbose opts in; the usage mock "
                                "shows --quiet with 'logging ON by default' (inverted) → rung 2.",
    "fcli-overwrite-bad": "bad: intent = refuse to clobber without --force; spec/usage neutral, but "
                          "the demo shows a silent overwrite of an existing file → rung 3.",
    "fcli-exit-code-bad": "bad: intent = non-zero exit on error; artifacts read neutral, but the "
                          "code calls process.exit(0) on both branches → only provable in code, rung 4.",
}

# Reviewer B — INDEPENDENT second labels: (direction, should_catch_by_rung, one-line why).
_REVIEWER_B: dict[str, tuple[str, int | None, str]] = {
    "fweb-cmdk-good": (GOOD, None, "focuses the existing input, adds no UI — points at the intent."),
    "fweb-currency-good": (GOOD, None, "currency formatting matches the intent at every rung."),
    "fweb-debounce-good": (GOOD, None, "trailing-edge collapse of a burst — the intent."),
    "fweb-tooltip-good": (GOOD, None, "hover/focus hint, explicitly no click behavior — the intent."),
    "fweb-pw-toggle-good": (GOOD, None, "starts masked, toggle reveals — the intent."),
    "fweb-cmdk-modal-bad": (BAD, 1, "the spec itself describes a modal overlay, not focusing the "
                            "existing field — visible at rung 1."),
    "fweb-a11y-placeholder-bad": (BAD, 2, "spec 'naming text' is consistent with a real label; only "
                                  "the wireframe (text inside the box, vanishes on type) shows a "
                                  "placeholder — rung 2."),
    "fweb-pw-plain-bad": (BAD, 2, "spec omits the default; the wireframe shows plaintext on load — "
                          "the wrong default first appears at rung 2."),
    "fweb-tooltip-click-bad": (BAD, 3, "spec/wireframe don't fix the trigger; the demo's "
                               "click-to-toggle (hover does nothing) is the divergence — rung 3."),
    "fweb-debounce-leading-bad": (BAD, 4, "every prose rung is true of both edges; only the code's "
                                  "`if (!t) fn()` reveals leading-edge — rung 4."),
    "fdash-tile-good": (GOOD, None, "sums the month for a total + delta — the intent."),
    "fdash-sort-good": (GOOD, None, "click sorts rows, toggles direction — the intent."),
    "fdash-filter-good": (GOOD, None, "inclusive both-bounds filter — the intent."),
    "fdash-pagination-good": (GOOD, None, "numbered pager, one 20-row slice at a time — the intent."),
    "fdash-export-good": (GOOD, None, "exports the visible filtered rows — the intent."),
    "fdash-tile-average-bad": (BAD, 1, "the spec computes a mean-per-txn, not the asked total — "
                               "visible at rung 1."),
    # NOTE: reviewer B read this as rung 3 (the append-on-scroll BEHAVIOR is clearest in the demo);
    # reviewer A read it as rung 2 (the absent pager is a structural fact of the wireframe). One-rung
    # gap → reconciled to the LOWER rung (2) per docs/bench-labeling.md §2.3. Recorded as 3 here so
    # the disagreement is auditable; two_labeler_agreement() reports it as a reconciliation, not an
    # exact match.
    "fdash-pagination-infinite-bad": (BAD, 3, "the wireframe drops the pager but the append-on-"
                                      "scroll behavior is clearest in the demo — I read rung 3."),
    "fdash-sort-reorder-bad": (BAD, 3, "spec 're-orders w.r.t. the column' fits both; only the "
                               "demo's column-drag (rows unchanged) shows the wrong axis — rung 3."),
    "fdash-export-all-bad": (BAD, 4, "nothing before the code distinguishes filtered vs full; the "
                             "code reading source `rows` is the tell — rung 4."),
    "fdash-search-casesens-bad": (BAD, 4, "case behavior is invisible in prose/demo; only the raw "
                                  "`includes` in code proves case-sensitivity — rung 4."),
    "fdash-filter-exclusive-bad": (BAD, 4, "inclusive-vs-exclusive end is an off-by-one only the "
                                   "`< end` code line reveals — rung 4."),
    "fcli-json-good": (GOOD, None, "default table, --json to stdout for piping — the intent."),
    "fcli-help-good": (GOOD, None, "--help prints usage, exits 0, runs no work — the intent."),
    "fcli-stdin-good": (GOOD, None, "path arg else piped stdin — the intent."),
    "fcli-verbose-default-bad": (BAD, 2, "the usage mock's '--quiet (logging ON by default)' is the "
                                 "inverted default — visible at rung 2."),
    "fcli-overwrite-bad": (BAD, 3, "spec/usage are neutral on clobbering; the demo's silent "
                           "overwrite of an existing file is the divergence — rung 3."),
    "fcli-exit-code-bad": (BAD, 4, "the demo shows an error message but not the exit code; only "
                           "`process.exit(0)` in code proves the wrong status — rung 4."),
}

# Candidates EXCLUDED by the agreement gate (docs/bench-labeling.md §2.3): the two reviewers
# disagreed on DIRECTION, so the seed is not crisp enough to score the ladder against. It is
# recorded here (never guessed into the set) so the disagreement is auditable. These do NOT appear
# in ALL_FAITHFUL and are never scored.
_EXCLUDED: dict[str, dict[str, str]] = {
    "fdash-density-fontsize-excluded": {
        "intent": (
            "A density toggle (Comfortable / Compact) changes how tightly the table's ROWS are "
            "packed — Compact reduces each row's vertical padding/height so more rows fit on screen."
        ),
        "reviewer_a": "bad: intent = row HEIGHT/padding; the build shrinks the FONT SIZE instead, "
                      "leaving row padding unchanged — a different lever than asked.",
        "reviewer_b": "good: 'density' legitimately spans type scale; shrinking the font is a "
                      "reasonable reading of Compact and still fits more rows — points at the intent.",
        "resolution": "DIRECTION disagreement (bad vs good) → EXCLUDED, not guessed. The seed's "
                      "direction is not crisp enough; this is itself the finding (§2.3).",
    },
}


def two_labeler_agreement() -> dict[str, object]:
    """Compute the inter-rater record for the admitted corpus (reviewer A vs reviewer B).

    Returns a dict of honest numbers for the scoreboard/docs:
      - n_admitted            : seeds in ALL_FAITHFUL (both reviewers agree on direction).
      - n_excluded            : candidates dropped on a DIRECTION disagreement (never scored).
      - direction_agreement   : agreed-direction / total-candidates (admitted + excluded).
      - scb_exact             : bad seeds whose two `should_catch_by_rung` values matched exactly.
      - scb_reconciled        : bad seeds whose values differed by one rung (reconciled to lower).
      - scb_conflicts         : bad seeds whose values differed by >1 rung (would need discussion).
      - n_bad                 : bad seeds in the admitted corpus.

    Deterministic: pure over the module-level records. No clock, no RNG.
    """
    admitted_ids = {s.id for s in ALL_FAITHFUL}
    # every admitted seed must have a reviewer-B label, or the record is incomplete
    missing = admitted_ids - set(_REVIEWER_B)
    if missing:
        raise ValueError(f"reviewer B has not labeled: {sorted(missing)}")

    direction_matches = 0
    for s in ALL_FAITHFUL:
        b_dir, _, _ = _REVIEWER_B[s.id]
        if b_dir == s.direction:
            direction_matches += 1

    total_candidates = len(admitted_ids) + len(_EXCLUDED)
    # excluded candidates are, by construction, direction disagreements — they count against
    # agreement in the denominator (that is the whole point of publishing the exclusion rate).
    direction_agreement = round(direction_matches / total_candidates, 4) if total_candidates else 0.0

    bad = [s for s in ALL_FAITHFUL if s.direction == BAD]
    scb_exact = scb_reconciled = scb_conflicts = 0
    for s in bad:
        _, b_scb, _ = _REVIEWER_B[s.id]
        a_scb = s.should_catch_by_rung
        if a_scb == b_scb:
            scb_exact += 1
        elif a_scb is not None and b_scb is not None and abs(a_scb - b_scb) == 1:
            scb_reconciled += 1
        else:
            scb_conflicts += 1

    return {
        "n_admitted": len(admitted_ids),
        "n_excluded": len(_EXCLUDED),
        "direction_agreement": direction_agreement,
        "scb_exact": scb_exact,
        "scb_reconciled": scb_reconciled,
        "scb_conflicts": scb_conflicts,
        "n_bad": len(bad),
    }

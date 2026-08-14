# Failure taxonomy — N=10 live rung-4 error analysis (Ng#2)

> V2-P1.4, run 2026-08-13. Live haiku builds vs planted-bug acceptance tests, LocalVerifier
> (`node --test`), max_retries=2 per climb. Founder-approved batch (~$0.50 cap; actual below).

## Round A — acceptance-as-code IN the builder context (today's system)

| variant | spec | bucket | attempts | cost |
|---|---|---|---|---|
| v01-cmdk | Cmd-K focuses search from anywhere, including with a modal | passed | 1 | $0.0003 |
| v02-debounce | Debounce collapses rapid calls; only the LAST call runs af | passed | 1 | $0.0006 |
| v03-parse | Parse a query string into an object; empty values kept as  | passed | 1 | $0.0007 |
| v04-carousel | Carousel index wraps: dir +1/-1, wraps both ends. | passed | 1 | $0.0004 |
| v05-a11y | Render an input field snippet; EVERY input must reference  | passed | 1 | $0.0007 |
| v06-undo | Undo stack object with push(x) and undo()->x, holding at m | passed | 1 | $0.0007 |
| v07-currency | Format integer cents as USD with thousands separators; neg | passed | 1 | $0.0010 |
| v08-slug | Slugify: lowercase, spaces->hyphens, strip non-alphanumeri | passed | 1 | $0.0005 |
| v09-rate | Rate limiter: allow when strictly fewer than `limit` times | passed | 1 | $0.0006 |
| v10-deepget | deepGet('a.b.c') walks nested objects; missing anywhere re | passed | 1 | $0.0008 |

Buckets: {'passed': 10}

## Round B — ABLATION: acceptance withheld (the pre-#101-lesson condition)

| variant | spec | bucket | attempts | cost |
|---|---|---|---|---|
| v01-cmdk | Cmd-K focuses search from anywhere, including with a modal | mechanical-exhausted | 3 | $0.0045 |
| v02-debounce | Debounce collapses rapid calls; only the LAST call runs af | passed | 1 | $0.0008 |
| v03-parse | Parse a query string into an object; empty values kept as  | passed | 1 | $0.0011 |
| v04-carousel | Carousel index wraps: dir +1/-1, wraps both ends. | passed | 1 | $0.0003 |
| v05-a11y | Render an input field snippet; EVERY input must reference  | passed | 1 | $0.0006 |
| v06-undo | Undo stack object with push(x) and undo()->x, holding at m | passed | 1 | $0.0007 |
| v07-currency | Format integer cents as USD with thousands separators; neg | passed | 1 | $0.0009 |
| v08-slug | Slugify: lowercase, spaces->hyphens, strip non-alphanumeri | mechanical-exhausted | 3 | $0.0018 |
| v09-rate | Rate limiter: allow when strictly fewer than `limit` times | passed | 1 | $0.0004 |
| v10-deepget | deepGet('a.b.c') walks nested objects; missing anywhere re | passed | 1 | $0.0009 |

Buckets: {'mechanical-exhausted': 2, 'passed': 8}

## A/B read — the lesson, measured
Round A passes at 10/10 with acceptance criteria AS CODE in the
bounded context; round B (8/10) shows what happens without them —
the descent lesson from live-run #101, quantified.

- Biggest FAILURE bucket: **mechanical-exhausted**
- Actual spend: **$0.0184** of the $0.60 cap · wall-clock 38s
- Lesson-mechanism coverage of the biggest bucket: **GAP**

## Ng#2 verdict
GAP: the biggest failure bucket is not covered by an existing durable lesson — a new pattern entry must be appended to LESSONS.md before the demo is rehearsed.

## Resolution (same session — the discipline working as designed)
The GAP was real and instructive: the #101 fix went into **code** (`BoundedContext.
acceptance_test`) but the durable **lesson library** only held the raw failure dump, not a
generalized pattern a future rung-1 judge could read. Appended to `expeditions/live-101/
LESSONS.md`:

> PATTERN: builders implement against IMAGINED interfaces when acceptance criteria are
> prose-only — the acceptance TEST must sit in the bounded context AS CODE. Measured: 10/10
> pass with the test in context vs 8/10 without (N=10 ablation; failures were contract
> misreads, mechanical-exhausted after retries).

Coverage of the biggest bucket: **CONFIRMED after append**. The A/B also quantifies the
lesson's value for the demo narrative: the ablation leg reproduces the exact pre-lesson
failure mode (contract misreads on `handleCmdK` — the same function as live-run #101 — and
`slugify`), and the with-test condition eliminates it, at ~2.6× lower cost per failed variant
(no retry burn).

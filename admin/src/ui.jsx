// Shared atoms — every visual value reads a Sorb-delivered token via app.css classes.
import React from 'react'

const RUNGS = ['0-intent', '1-spec', '2-wireframe', '3-demo', '4-mvp', '5-flagged']
export const rungIdx = (r) => RUNGS.indexOf(r)
export { RUNGS }

/** Status/rung/dial pill. */
export function Label({ kind, children }) {
  return <span className={`lbl lbl-${kind}`}>{children}</span>
}

/** Artifact chain: which artifacts exist for an expedition (fixes "are these PRs?"). */
/** WHAT A RUN PRODUCED — one item per artifact that exists, each a link, absent when it doesn't.
 *
 *  This replaces `Chain`, which computed `demo: i >= 3, pr: i >= 4` from the RUNG INDEX. On the
 *  live harness that meant four expeditions showed a `PR` chip and exactly one had opened a pull
 *  request. The row already looked like it was telling you what a run made, so the absence of a
 *  link read as a missing feature rather than a missing artifact.
 *
 *  The strip's LENGTH is now an honest measure of how far a run actually got — the job the rung
 *  chip only claimed to do. Two expeditions both reading "5-flagged done" are no longer
 *  indistinguishable when one built nothing.
 *
 *  `onOpen` receives a kind ('preview' | 'diff') for the two artifacts this system holds itself;
 *  without it they render as plain links. The pull request and the Figma frames always leave —
 *  they are somebody else's surface and pretending otherwise would be a worse lie than the one
 *  this replaces.
 */
export function Artifacts({ a, number, base = '', onOpen = null, open = null }) {
  const f = a || {}
  const items = []
  if (f.frames?.count) {
    items.push({ k: 'frames', lb: 'frames', v: `${f.frames.count} in Figma`, href: f.frames.url, ext: true })
  }
  if (f.preview) {
    items.push({ k: 'preview', lb: 'preview', v: 'prototype', href: `${base}/preview/${number}` })
  }
  if (f.build || f.diff) {
    const files = f.build?.files, lines = f.build?.lines
    const v = [files && `${files} file${files === 1 ? '' : 's'}`, lines && `${lines} lines`]
      .filter(Boolean).join(' · ') || 'changed files'
    // The diff lives on the expedition's own screen. Rendering it as inert text looked like an
    // item and did nothing, which is the false-affordance this whole change exists to remove —
    // an artifact that cannot be reached is not much better than one that was never made.
    items.push({ k: 'diff', lb: 'diff', v, href: `${import.meta.env.BASE_URL}runs/${number}` })
  }
  if (f.pull_request) {
    items.push({ k: 'pr', lb: 'pull request', v: 'draft', href: f.pull_request, ext: true })
  }
  if (f.stage) {
    items.push({ k: 'stage', lb: 'stage', v: 'live now', href: f.stage, ext: true })
  }
  if (items.length === 0) {
    return <span className="art-none">Nothing produced yet</span>
  }
  return (
    <span className="strip">
      {items.map((it) => {
        const inline = !it.ext && onOpen
        const isOpen = open === it.k
        const body = (
          <>
            <span className="g">{it.ext ? '\u2197' : inline ? (isOpen ? '\u25be' : '\u25b8') : '\u00b7'}</span>
            <span className="lb">{it.lb}</span>
            <span className="vv">{it.v}</span>
          </>
        )
        if (inline) {
          return (
            <button key={it.k} type="button" className={`art${isOpen ? ' on' : ''}`}
                    aria-expanded={isOpen} onClick={() => onOpen(isOpen ? null : it.k)}>{body}</button>
          )
        }
        if (!it.href) return <span key={it.k} className="art">{body}</span>
        // Only a link that LEAVES this system opens a new tab. `/runs/N` is this app.
        return it.ext
          ? <a key={it.k} className="art ext" href={it.href} target="_blank" rel="noreferrer">{body}</a>
          : <a key={it.k} className="art" href={it.href}>{body}</a>
      })}
    </span>
  )
}

/** Six-step ladder sparkline; the current rung shows red on a descent. */
export function LadderBar({ rung, status }) {
  const cur = rungIdx(rung)
  return (
    <span className="ladder" role="img" aria-label={`rung ${rung}${status === 'descended' ? ', descended' : ''}`}>
      {RUNGS.map((r, i) => {
        const last = i === RUNGS.length - 1
        let c = 'lstep'
        if (status === 'descended' && i === cur) c += ' bad'   // descent flags the current rung red
        else if (last) c += ' gate'                            // terminal gate, always the rightmost
        else if (i < cur) c += ' on'                           // completed rung (ink)
        else if (i === cur) c += ' cur'                        // current rung (blue)
        return <span key={r} className={c} />
      })}
    </span>
  )
}

/**
 * Spend. `v` is metered dollars; `equiv` is what the same work would have cost at list price.
 *
 * The subscription lane meters $0, so showing only `v` renders "$0.00" for every run however
 * large — which reads as a measurement rather than as "not billed". When there is nothing metered
 * but real work happened, show the equivalent and label it, so the number is never mistaken for
 * the bill.
 */
export function Money({ v, equiv }) {
  const metered = Number(v || 0)
  const shadow = Number(equiv || 0)
  if (metered === 0 && shadow > 0) {
    return (
      <span className="money" title="subscription lane: nothing metered; this is the list-price equivalent">
        ${shadow.toFixed(2)} <span className="cap">equiv</span>
      </span>
    )
  }
  return <span className="money">${metered.toFixed(2)}</span>
}

/** Ranked by information value — the v1 lens's infoValue, carried forward. */
export function infoValue(e) {
  let s = 0
  // A run the workflow parked because it FAILED outranks every gate: a gate is the ladder waiting
  // politely, and this is the one thing on the instance that is broken.
  if (e.status === 'parked' && e.parked_by === 'failure') s += 6
  // A question is the cheapest thing on this screen to answer and the only one blocking a
  // run that has spent nothing yet.
  if (e.status === 'await-answer') s += 5
  if (e.status === 'descended') s += 5
  if (e.status === 'await-signoff') s += 4
  if (e.status === 'needs-human') s += 3
  if (e.status === 'await-pick') s += 2
  if (e.spent > 1.5) s += 1
  return s
}

export function Toast({ msg }) {
  if (!msg) return null
  return <div className="toast" role="status">{msg}</div>
}

/** The statuses that are a PENDING HUMAN DECISION — a gate the ladder is holding open. */
export const NEEDS = ['descended', 'await-signoff', 'await-pick', 'needs-human', 'await-answer']

/** Does this expedition need a person?
 *
 *  THE BUG THIS EXISTS FOR. Three screens each kept their own copy of `NEEDS`, and all three
 *  listed only the gates. A run the workflow PARKED because it failed — a dead worker, a rung
 *  past its limit, a crash — is not a gate, so it appeared on none of them: it dropped off the
 *  Inbox entirely and sat on the Wall looking like any other parked run, while being the one
 *  thing on the instance that a person actually had to deal with.
 *
 *  A failure park is told apart from a human park by `parked_by`, which the engine stamps at the
 *  moment of the park: a person's name when somebody pressed Stop, the word `failure` when the
 *  workflow decided. A run somebody stopped on purpose needs nobody.
 */
export function needsYou(e) {
  if (NEEDS.includes(e.status)) return true
  return e.status === 'parked' && e.parked_by === 'failure'
}

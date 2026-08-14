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
export function Chain({ rung, status }) {
  const i = rungIdx(rung)
  const has = { issue: true, demo: i >= 3 || status === 'await-signoff', pr: i >= 4 }
  return (
    <span className="chain" aria-label={`artifacts: issue${has.demo ? ', demo' : ''}${has.pr ? ', draft PR' : ''}`}>
      <span className={`art${has.issue ? ' on' : ''}`}>issue</span>
      <span className={`art${has.demo ? ' on' : ''}`}>demo</span>
      <span className={`art${has.pr ? ' on' : ''}`}>PR</span>
    </span>
  )
}

/** Six-step ladder sparkline; the current rung shows red on a descent. */
export function LadderBar({ rung, status }) {
  const cur = rungIdx(rung)
  return (
    <span className="ladder" role="img" aria-label={`rung ${rung}${status === 'descended' ? ', descended' : ''}`}>
      {RUNGS.map((r, i) => {
        let c = 'lstep'
        if (status === 'descended' && i === cur) c += ' bad'
        else if (i <= cur) c += ' on'
        return <span key={r} className={c} />
      })}
    </span>
  )
}

export function Money({ v }) {
  return <span className="money">${Number(v || 0).toFixed(2)}</span>
}

/** Ranked by information value — the v1 lens's infoValue, carried forward. */
export function infoValue(e) {
  let s = 0
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

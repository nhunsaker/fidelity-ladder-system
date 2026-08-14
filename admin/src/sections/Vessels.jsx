// Anchor · Vessels — the context packs (V3 scope: grounding, NOT a per-vessel dials layer).
// Read from /anchor's vessels/default_vessel. Each row deep-links its edit into the ANCHOR
// console (edits are PRs). The AnchorConsole today exposes funnel/budgets/demote only — no
// arbitrary "vessels" section — so "Edit → PR" links to the console rather than a section anchor.
import React from 'react'
import { Label } from '../ui.jsx'

/** Shared table body, reused compact inside Constitution. @param {{data:any, compact?:boolean}} props */
export function VesselsTable({ data, compact }) {
  const a = data.anchor || {}
  const vessels = a.vessels || []
  const def = a.default_vessel
  if (vessels.length === 0) {
    return <p className="note" style={{ margin: 12 }}>No vessels declared — slim mode (expeditions
      inherit directly from the ANCHOR).</p>
  }
  return (
    <table className="t">
      <thead>
        <tr><th>name</th><th>kind</th>{!compact && <th>description</th>}<th>paths · standards</th>{!compact && <th />}</tr>
      </thead>
      <tbody>
        {vessels.map((v) => (
          <tr key={v.name}>
            <td>
              <b>{v.name}</b>{v.name === def && <span className="def-badge">default</span>}
            </td>
            <td><Label kind="rung">{v.kind}</Label></td>
            {!compact && <td style={{ maxWidth: 320, color: 'var(--color-fg-muted, #59636e)' }}>{v.description || '—'}</td>}
            <td className="why" style={{ whiteSpace: 'normal' }}>
              {(v.paths || []).join(', ') || '—'}
              {(v.standards || []).length > 0 && <> · {(v.standards || []).length} standard{v.standards.length > 1 ? 's' : ''}</>}
            </td>
            {!compact && <td><a className="btn" href="#/anchor/console" style={{ textDecoration: 'none' }}>Edit → PR</a></td>}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** @param {{data: any}} props */
export default function Vessels({ data }) {
  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Vessels</h2>
        <span style={{ flex: 1 }} />
        <a className="btn" href="#/anchor" style={{ textDecoration: 'none' }}>← Constitution</a>
        <a className="btn btn-acc" href="#/anchor/console" style={{ textDecoration: 'none' }}>Open console →</a>
      </div>
      <p className="note">A vessel is a named context pack between the north star and an expedition —
        the grounding that makes admission informed and exploration concrete (paths, standards, refs).
        V3 scope: grounding only, no per-vessel dials. Edits are PRs.</p>
      <div className="card">
        <VesselsTable data={data} />
      </div>
    </div>
  )
}

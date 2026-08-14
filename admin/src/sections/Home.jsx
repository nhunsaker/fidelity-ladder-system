// Home — step 0, the listing. Design 2b: one aligned dense grid (single scan-line per
// expedition), grouped needs-you-first by information value, filter chips, keyboard footer.
import React, { useEffect, useMemo, useState } from 'react'
import { Chain, Label, LadderBar, Money, infoValue, rungIdx } from '../ui.jsx'

const NEEDS = ['descended', 'await-signoff', 'await-pick', 'needs-human']

function actionFor(e) {
  if (e.status === 'descended') return 'Lesson'
  if (e.status === 'await-signoff') return 'Approve'
  if (e.status === 'await-pick') return 'Pick'
  return null
}

/** @param {{data: any, onOpen: (n:number)=>void}} props */
export default function Home({ data, onOpen }) {
  const [filter, setFilter] = useState('all')
  const [sel, setSel] = useState(0)

  const exps = useMemo(() => {
    let xs = [...(data.expeditions || [])]
    if (filter === 'needs') xs = xs.filter((e) => NEEDS.includes(e.status))
    if (filter === 'docked') xs = xs.filter((e) => e.status === 'docked')
    return xs
  }, [data, filter])

  const needs = exps.filter((e) => NEEDS.includes(e.status)).sort((a, b) => infoValue(b) - infoValue(a))
  const inert = ['docked', 'parked']
  const rest = exps.filter((e) => !NEEDS.includes(e.status) && !inert.includes(e.status))
    .sort((a, b) => rungIdx(b.rung) - rungIdx(a.rung))
  const shelved = exps.filter((e) => inert.includes(e.status))
  const ordered = [...needs, ...rest, ...shelved]
  const totalSpent = (data.expeditions || []).reduce((s, e) => s + (e.spent || 0), 0)

  // j/k row navigation + enter to open (the 1a keyboard carry-over)
  useEffect(() => {
    const h = (ev) => {
      if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA') return
      if (ev.key === 'j') setSel((s) => Math.min(s + 1, ordered.length - 1))
      if (ev.key === 'k') setSel((s) => Math.max(s - 1, 0))
      if (ev.key === 'Enter' && ordered[sel]) onOpen(ordered[sel].number)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [ordered, sel, onOpen])

  const Row = ({ e, i }) => (
    <button className={`row${i === sel ? ' sel' : ''}`} onClick={() => onOpen(e.number)}
            aria-label={`expedition ${e.number}: ${e.intent}, ${e.status}`}>
      <span className="num">#{e.number}</span>
      <span style={{ minWidth: 0 }}>
        <span className="int" style={{ display: 'block' }}>{e.intent}</span>
        <span className="why" style={{ display: 'block' }}>{e.reason || `dial: ${e.dial}`}</span>
      </span>
      <Label kind="rung">{e.rung}</Label>
      <Label kind={e.status}>{e.status}</Label>
      <Chain rung={e.rung} status={e.status} />
      <Money v={e.spent} />
      {actionFor(e)
        ? <span className={`btn${e.status === 'await-signoff' ? ' btn-pri' : ''}`}>{actionFor(e)}</span>
        : <LadderBar rung={e.rung} status={e.status} />}
    </button>
  )

  return (
    <>
      <div className="list-head">
        <h1>Expeditions</h1>
        {[['all', `All ${data.expeditions?.length ?? 0}`],
          ['needs', `Needs you ${(data.expeditions || []).filter((e) => NEEDS.includes(e.status)).length}`],
          ['docked', 'Docked']].map(([k, label]) => (
          <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>{label}</button>
        ))}
        <span style={{ flex: 1 }} />
        <span className={`src-badge src-${data.source}`}>{data.source === 'live' ? 'live harness' : 'fixtures (offline)'}</span>
        <a className="btn btn-acc" href="#/file" style={{ textDecoration: 'none' }}>+ File idea</a>
      </div>

      {needs.length > 0 && <div className="sect">Needs your judgment · ranked by information value</div>}
      {needs.map((e, i) => <Row key={e.number} e={e} i={i} />)}
      {rest.length > 0 && <div className="sect">Climbing · no action needed</div>}
      {rest.map((e, i) => <Row key={e.number} e={e} i={needs.length + i} />)}
      {shelved.length > 0 && <div className="sect">Docked · parked</div>}
      {shelved.map((e, i) => <Row key={e.number} e={e} i={needs.length + rest.length + i} />)}

      <div className="foot">
        <span>Press <span className="kbd">j</span>/<span className="kbd">k</span> to move · <span className="kbd">enter</span> to open · <span className="kbd">⌘K</span> filter</span>
        <span style={{ flex: 1 }} />
        <span className="money">{data.expeditions?.length ?? 0} expeditions · ${totalSpent.toFixed(2)} spent · cap $8/exp</span>
      </div>
    </>
  )
}

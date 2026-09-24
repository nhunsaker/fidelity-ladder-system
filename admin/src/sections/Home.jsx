// Home — step 0, the listing. Design 2b: one aligned dense grid (single scan-line per
// expedition), grouped needs-you-first by information value, filter chips, keyboard footer.
import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Artifacts, Label, LadderBar, Money, infoValue, needsYou, rungIdx } from '../ui.jsx'


function actionFor(e) {
  // A run that stopped on its own is not shelved, it is broken — and the row's job is to say
  // which of the two this is. Every parked run looked identical here, so the ones nobody chose
  // to stop were indistinguishable from the ones somebody did.
  if (e.status === 'parked' && e.parked_by === 'failure') return 'Retry'
  if (e.status === 'await-answer') return 'Answer'
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
    if (filter === 'needs') xs = xs.filter((e) => needsYou(e))
    if (filter === 'docked') xs = xs.filter((e) => e.status === 'docked')
    return xs
  }, [data, filter])

  const needs = exps.filter((e) => needsYou(e)).sort((a, b) => infoValue(b) - infoValue(a))
  const inert = ['docked', 'parked']
  const rest = exps.filter((e) => !needsYou(e) && !inert.includes(e.status))
    .sort((a, b) => rungIdx(b.rung) - rungIdx(a.rung))
  const shelved = exps.filter((e) => inert.includes(e.status) && !needsYou(e))
  const ordered = [...needs, ...rest, ...shelved]
  const totalSpent = (data.expeditions || []).reduce((s, e) => s + (e.spent || 0), 0)
  // This instance's builder runs on the subscription lane, so `spent` is genuinely 0.00 on every
  // row and the footer read "$0.00 spent" under expeditions that had done real work. The rest of
  // the app already solved this — <Money> shows the list-price equivalent when nothing was
  // metered — and the footer was the one place still summing only the metered half.
  const totalEquiv = (data.expeditions || []).reduce((s, e) => s + (e.normalized_usd || 0), 0)
  // The ceiling is the ANCHOR's, not a number typed into a footer. It said "cap $8/exp" while
  // this instance's constitution says 6.0 — a governance screen stating a budget that is not
  // this instance's is exactly the class of claim the rest of this pass removed.
  const cap = data.anchor?.budgets?.per_expedition_ceiling_usd

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

  // The row was a <button>. It cannot stay one: the artifact strip contains links, and nested
  // interactive content inside a button is invalid and unreachable by keyboard. The row is now a
  // div whose OPEN affordance is an inner button, with the strip's links as siblings — so a
  // reader can reach the prototype, the diff and the pull request with the keyboard, which was
  // the whole point of making them real.
  const Row = ({ e, i }) => (
    <div className={`row${i === sel ? ' sel' : ''}`}>
      <button className="row-open" onClick={() => onOpen(e.number)}
              aria-label={`expedition ${e.number}: ${e.intent}, ${e.status}`}>
        <span className="num">#{e.number}</span>
        <span style={{ minWidth: 0 }}>
          <span className="int" style={{ display: 'block' }}>{e.intent}</span>
          <span className="why" style={{ display: 'block' }}>{e.reason || `dial: ${e.dial}`}</span>
        </span>
        <Label kind="rung">{e.rung}</Label>
        <Label kind={e.status}>{e.status}</Label>
        <Money v={e.spent} equiv={e.normalized_usd} />
        {actionFor(e)
          ? <span className={`btn${e.status === 'await-signoff' ? ' btn-pri' : ''}`}>{actionFor(e)}</span>
          : <LadderBar rung={e.rung} status={e.status} />}
      </button>
      <Artifacts a={e.artifacts} number={e.number} base={api.base} />
    </div>
  )

  return (
    <>
      <div className="list-head">
        <h1>Expeditions</h1>
        {[['all', `All ${data.expeditions?.length ?? 0}`],
          ['needs', `Needs you ${(data.expeditions || []).filter((e) => needsYou(e)).length}`],
          ['docked', 'Docked']].map(([k, label]) => (
          <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>{label}</button>
        ))}
        <span style={{ flex: 1 }} />
        <span className={`src-badge src-${data.source}`}>{data.source === 'live' ? 'live harness' : 'fixtures (offline)'}</span>
        <a className="btn btn-acc" href={`${import.meta.env.BASE_URL}file`} style={{ textDecoration: 'none' }}>+ File idea</a>
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
        <span className="money">
          {data.expeditions?.length ?? 0} expeditions · <Money v={totalSpent} equiv={totalEquiv} /> spent
          {cap != null && <> · cap ${Number(cap).toFixed(2)}/exp</>}
        </span>
      </div>
    </>
  )
}

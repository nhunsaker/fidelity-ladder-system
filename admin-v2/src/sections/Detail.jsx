// Expedition detail + the kill switch [P3.2 debt]. The kill confirm reuses the
// named-approver pattern — fail-closed: no name, no kill.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Chain, Label, LadderBar, Money, RUNGS, rungIdx } from '../ui.jsx'

/** @param {{number: number, data: any, onBack: ()=>void, toast: (s:string)=>void}} props */
export default function Detail({ number, data, onBack, toast }) {
  const [live, setLive] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const [who, setWho] = useState('')
  const fallback = (data.expeditions || []).find((e) => e.number === number)

  useEffect(() => {
    let on = true
    api.expedition(number).then((d) => on && setLive(d)).catch(() => {})
    return () => { on = false }
  }, [number])

  const e = live || fallback
  if (!e) return <div className="pane"><h2>No expedition #{number}</h2></div>
  const cur = rungIdx(e.rung)

  const kill = async () => {
    if (!who.trim()) { toast('Refused: the kill switch requires a named actor (fail-closed)'); return }
    try {
      await api.kill(number, { actor: who.trim(), reason: 'killed from admin' })
      toast(`#${number} parked by ${who.trim()} — recorded in the ledger`)
    } catch {
      toast(`Kill request failed against the live harness — nothing changed`)
    }
    setConfirm(false)
  }

  return (
    <div className="pane">
      <div className="detail-head">
        <button className="btn" onClick={onBack}>← Back</button>
        <h2 style={{ margin: 0 }}>#{e.number} · {e.intent}</h2>
        <Label kind="rung">{e.rung}</Label>
        <Label kind={e.status}>{e.status}</Label>
        <Chain rung={e.rung} status={e.status} />
        <Money v={e.spent} />
        <span style={{ flex: 1 }} />
        <button className="btn btn-danger" onClick={() => setConfirm(true)}>Kill switch</button>
      </div>

      <div className="card">
        <div className="sect" style={{ borderTop: 0 }}>Climb timeline</div>
        <ul className="timeline">
          {RUNGS.map((r, i) => (
            <li key={r}>
              <span className="num" style={{ width: 90 }}>{r}</span>
              <span style={{ flex: 1 }}>
                {i < cur && '✓ climbed'}
                {i === cur && (e.status === 'descended' ? '⛔ descended here — lesson written' : `● current — ${e.status}`)}
                {i > cur && (i <= rungIdx(e.target) ? 'target lane' : '—')}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="card card-pad">
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <LadderBar rung={e.rung} status={e.status} />
          <span className="why">target: {e.target} · dial: {e.dial} · {e.reason || 'no notes'}</span>
          {rungIdx(e.rung) >= 3 && (
            <a href={`${api.base}/preview/${e.number}`} target="_blank" rel="noreferrer">demo preview ↗</a>
          )}
        </div>
      </div>

      {confirm && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Kill switch confirm">
          <div className="modal">
            <div className="m-head">Kill expedition #{e.number}?</div>
            <div className="m-body">
              <p style={{ marginTop: 0 }}>Parks the expedition (no further spend). Reversible by a re-climb;
                the kill lands in the ledger with your name.</p>
              <label className="flab" htmlFor="kill-actor">Your name (required — the gate is non-bypassable)</label>
              <input id="kill-actor" className="in" value={who} onChange={(ev) => setWho(ev.target.value)}
                     placeholder="github handle" />
            </div>
            <div className="m-foot">
              <button className="btn" onClick={() => setConfirm(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={kill}>Park it</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

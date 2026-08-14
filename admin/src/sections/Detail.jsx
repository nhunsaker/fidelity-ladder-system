// Expedition detail + the kill switch [P3.2 debt] + the human-in-the-loop surface:
// the issue-thread mirror, a feedback field, and command buttons. Feedback goes THROUGH
// the harness to GitHub as a comment — commands apply only when the signed webhook echoes
// them back (one protocol, no admin side door). Named-actor fail-closed, like the kill.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Chain, Label, LadderBar, Money, RUNGS, rungIdx } from '../ui.jsx'

/** @param {{number: number, data: any, onBack: ()=>void, toast: (s:string)=>void}} props */
export default function Detail({ number, data, onBack, toast }) {
  const [live, setLive] = useState(null)
  const [thread, setThread] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const [who, setWho] = useState('')
  const [fb, setFb] = useState('')
  const [busy, setBusy] = useState(false)
  const fallback = (data.expeditions || []).find((e) => e.number === number)

  const refresh = () => {
    api.expedition(number).then(setLive).catch(() => {})
    api.thread(number).then(setThread).catch(() => setThread({ available: false, reason: 'thread unavailable', comments: [] }))
  }

  useEffect(() => {
    let on = true
    api.expedition(number).then((d) => on && setLive(d)).catch(() => {})
    api.thread(number).then((t) => on && setThread(t))
      .catch(() => on && setThread({ available: false, reason: 'thread unavailable', comments: [] }))
    return () => { on = false }
  }, [number])

  const send = async (text) => {
    if (!who.trim()) { toast('Refused: feedback requires a named actor (fail-closed)'); return }
    if (!text.trim()) { toast('Nothing to send'); return }
    setBusy(true)
    try {
      const r = await api.feedback(number, { body: text.trim(), actor: who.trim() })
      toast(r.command
        ? `${text.trim().split('\n')[0]} sent — the webhook round-trip applies it`
        : 'Feedback posted to the issue thread')
      setFb('')
      setTimeout(refresh, 3000) // give GitHub -> webhook -> mirror a beat
    } catch {
      toast('Feedback refused by the harness (no linked issue or no outbound token)')
    }
    setBusy(false)
  }

  const e = live || fallback
  if (!e) return <div className="pane"><h2>No expedition #{number}</h2></div>
  const cur = rungIdx(e.rung)
  const wireframes = live?.artifacts?.wireframes || []
  const needsYou = ['needs-human', 'await-signoff', 'await-pick', 'descended'].includes(e.status)

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

      {wireframes.length > 0 && (
        <div className="card">
          <div className="sect" style={{ borderTop: 0 }}>Wireframes · pick-of-{wireframes.length}</div>
          <div style={{ display: 'flex', gap: 12, padding: 12, flexWrap: 'wrap' }}>
            {wireframes.map((name, i) => (
              <div key={name} style={{ flex: '1 1 240px', minWidth: 240 }}>
                <iframe title={name} src={`${api.base}/wireframes/${e.number}/${name}`}
                        sandbox="" style={{ width: '100%', height: 220, border: '1px solid var(--color-border-default, #d1d9e0)', borderRadius: 6, background: '#fff' }} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                  <span className="why" style={{ flex: 1 }}>{name}</span>
                  <button className="btn" disabled={busy} onClick={() => send(`/pick ${i + 1}`)}>
                    Pick #{i + 1}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="sect" style={{ borderTop: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ flex: 1 }}>
            Issue thread
            {thread?.available && thread.url && (
              <> · <a href={thread.url} target="_blank" rel="noreferrer">view on GitHub ↗</a></>
            )}
          </span>
        </div>
        {needsYou && (
          <p className="note" style={{ margin: '8px 12px 0' }}>
            ⏳ The gate parked this for a human — your feedback below goes onto the issue;
            commands take effect through the same signed webhook as everything else.
          </p>
        )}
        {thread == null && <p className="note" style={{ margin: 12 }}>Loading thread…</p>}
        {thread && !thread.available && (
          <p className="note" style={{ margin: 12 }}>Thread unavailable: {thread.reason}</p>
        )}
        {thread?.available && (
          <ul style={{ listStyle: 'none', margin: 0, padding: '4px 12px 8px' }}>
            {thread.comments.length === 0 && <li className="note">No comments yet.</li>}
            {thread.comments.map((c, i) => (
              <li key={i} style={{ padding: '8px 0', borderTop: i ? '1px solid var(--color-border-muted, #eee)' : 'none' }}>
                <div className="why">@{c.author} · {(c.at || '').slice(0, 16).replace('T', ' ')}</div>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, marginTop: 2 }}>{c.body}</div>
              </li>
            ))}
          </ul>
        )}
        <div style={{ padding: 12, borderTop: '1px solid var(--color-border-muted, #eee)' }}>
          <label className="flab" htmlFor="fb-body">Feedback (posts to the issue as a comment)</label>
          <textarea id="fb-body" className="in" rows={3} value={fb} disabled={busy}
                    placeholder="e.g. clarified success criteria, a question, or context for the next rung"
                    onChange={(ev) => setFb(ev.target.value)}
                    style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit' }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input className="in" value={who} onChange={(ev) => setWho(ev.target.value)}
                   placeholder="your name (required)" aria-label="Your name" style={{ width: 180 }} />
            <button className="btn" disabled={busy} onClick={() => send(fb)}>Post feedback</button>
            <span style={{ flex: 1 }} />
            <button className="btn" disabled={busy} title="Posts /advance — the webhook flips the rung"
                    onClick={() => send('/advance')}>⬆ Advance</button>
            <button className="btn" disabled={busy} title="Posts /approve — the named prod gate"
                    onClick={() => send('/approve')}>🚀 Approve prod</button>
          </div>
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

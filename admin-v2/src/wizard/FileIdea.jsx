// File an idea — the guided flow: 1 work → 2 explain (every input teaches) → 3 validate
// (map selections vs the ANCHOR, dock prediction) → submit through the STANDARD door.
// Onboarding copy sourced from configuration.md — the blueprint doc.
import React, { useState } from 'react'
import { api } from '../api.js'
import Wizard from './Wizard.jsx'

const STEPS = [
  { t: 'Work', x: 'New idea · manual door' },
  { t: 'Explain', x: 'Intent · success · altitude' },
  { t: 'Validate', x: 'Map vs the ANCHOR before anything spends' },
]

export default function FileIdea({ data, toast, onDone }) {
  const [step, setStep] = useState(0)
  const [intent, setIntent] = useState('')
  const [success, setSuccess] = useState('')
  const [altitude, setAltitude] = useState('feature')
  const [result, setResult] = useState(null)
  const allowed = data.anchor?.altitude_allowed || ['ticket', 'feature']

  const checks = [
    { k: 'Intent', v: intent || '—',
      ok: intent.trim().length > 8, okText: 'stated', badText: 'too short to trace' },
    { k: 'Success signal', v: success || '—',
      ok: success.trim().length > 8, okText: 'checkable', badText: 'vague = needs-human at the gate' },
    { k: 'Altitude', v: altitude,
      ok: allowed.includes(altitude), okText: 'allowed', badText: `docks: not in [${allowed}]` },
  ]
  const allOk = checks.every((c) => c.ok)

  const submit = async () => {
    const number = Math.floor(300 + Math.random() * 600)
    try {
      const r = await api.fileIdea({ number, intent, success, altitude, source: 'manual' })
      setResult({ ...r, live: true })
      toast(`Filed #${number} — gate verdict: ${r.verdict}`)
    } catch {
      setResult({ number, verdict: 'unsubmitted', live: false,
                  reason: 'harness unreachable — nothing was filed (fail-closed, not pretended)' })
      toast('Harness unreachable — nothing was filed')
    }
  }

  return (
    <Wizard title="File an idea" steps={STEPS} step={step}
            footNote="submits through the standard door — the gate still decides">
      {step === 0 && (
        <>
          <h2>What are we doing?</h2>
          <p className="note">One idea = one expedition. It climbs only as far as the funnel lane
            it earns, and it must trace to the ANCHOR or it docks.</p>
          <div className="radio-cards">
            <button className="rcard sel"><b>File a new idea</b>
              <span>The manual door — same admission gate the feeder uses.</span></button>
            <button className="rcard off" disabled aria-disabled="true"><b>Edit an expedition</b>
              <span>Open it from the wall instead — every change is an issue action.</span></button>
          </div>
          <div className="wiz-nav"><button className="btn btn-acc" onClick={() => setStep(1)}>Start →</button></div>
        </>
      )}

      {step === 1 && (
        <>
          <h2>Explain the idea</h2>
          <p className="note">Each input does a specific job at the gate — that job is written under it.</p>
          <div className="field">
            <label className="flab" htmlFor="f-intent">Intent</label>
            <p className="fexp">One sentence of user-visible outcome. The admission judge traces this
              against the ANCHOR north star — not whether it is good, only whether it belongs.</p>
            <input id="f-intent" className="in" value={intent} onChange={(e) => setIntent(e.target.value)}
                   placeholder="Add keyboard shortcuts to the settings page" />
          </div>
          <div className="field">
            <label className="flab" htmlFor="f-success">Success signal</label>
            <p className="fexp">A checkable claim — rung-1 specs must turn this into acceptance criteria.
              Vague success = needs-human at the gate; unmeasurable success never ships.</p>
            <input id="f-success" className="in" value={success} onChange={(e) => setSuccess(e.target.value)}
                   placeholder="every setting reachable without the mouse; visible focus ring" />
          </div>
          <div className="field">
            <span className="flab">Altitude</span>
            <p className="fexp">The unit of work rung 4 may own. This ANCHOR allows
              {' '}<b>{allowed.join(' + ')}</b>; anything else docks automatically, before any model spend.
              The disallowed option is shown so you learn the boundary, not hidden.</p>
            <div className="radio-cards" role="radiogroup" aria-label="Altitude">
              {['ticket', 'feature', 'migration'].map((a) => {
                const ok = allowed.includes(a)
                return (
                  <button key={a} role="radio" aria-checked={altitude === a}
                          className={`rcard${altitude === a ? ' sel' : ''}${ok ? '' : ' off'}`}
                          onClick={() => ok && setAltitude(a)} disabled={!ok}>
                    <b>{a}</b>
                    <span>{a === 'ticket' ? 'A contained change — one component, one behavior.'
                      : a === 'feature' ? 'A user-facing capability — the full ladder, every artifact.'
                      : 'Not allowed by this ANCHOR — it would dock at the gate.'}</span>
                  </button>
                )
              })}
            </div>
          </div>
          <div className="wiz-nav">
            <button className="btn" onClick={() => setStep(0)}>← Back</button>
            <button className="btn btn-acc" onClick={() => setStep(2)}>Continue to validate →</button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <h2>Review &amp; validate</h2>
          <p className="note">The map of your selections, checked against the ANCHOR before anything spends.</p>
          <div className="vmap">
            {checks.map((c) => (
              <div className="vrow" key={c.k}>
                <span className="vk">{c.k}</span>
                <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis' }}>{c.v}</span>
                <span className={c.ok ? 'ok' : 'bad'}>{c.ok ? `✓ ${c.okText}` : `✗ ${c.badText}`}</span>
              </div>
            ))}
            <div className="vrow">
              <span className="vk">A11y floor</span>
              <span>axe-core clean required before rung 5</span>
              <span className="warn">○ non-negotiable</span>
            </div>
          </div>
          {!result && (
            <div className={`verdict${allOk ? '' : ' bad-edge'}`}>
              <b>Gate prediction: {allOk ? 'likely admit' : 'likely dock / needs-human'}</b>
              <div className="fexp" style={{ margin: '2px 0 0' }}>Prediction only — the adjudicator
                (budget-bounded) makes the real call on submit. Disagreement lands in the calibration ledger.</div>
            </div>
          )}
          {result && (
            <div className={`verdict${result.verdict === 'admit' ? '' : ' bad-edge'}`}>
              <b>{result.live ? `Gate verdict: ${result.verdict}` : 'Not filed'}</b>
              <div className="fexp" style={{ margin: '2px 0 0' }}>{result.reason || `Expedition #${result.number} is on the wall.`}</div>
            </div>
          )}
          <div className="wiz-nav">
            <button className="btn" onClick={() => setStep(1)}>← Back to explain</button>
            {!result
              ? <button className="btn btn-acc" onClick={submit} disabled={!allOk}>Submit to the gate</button>
              : <button className="btn btn-pri" onClick={onDone}>To the wall →</button>}
          </div>
        </>
      )}
    </Wizard>
  )
}

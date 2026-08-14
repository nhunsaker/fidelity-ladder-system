// Feeder control [P3.2 debt] — trigger/inspect the studio brainstorm. Guided: 1 what to do →
// 2 params explained → 3 dry-run preview (fixture sink) → real trigger. The feeder can NEVER
// self-admit; everything it files still faces the gate.
import React, { useState } from 'react'
import { api } from '../api.js'
import Wizard from './Wizard.jsx'

const STEPS = [
  { t: 'Action', x: 'Trigger a run · inspect history' },
  { t: 'Params', x: 'Scope · caps · envelope, explained' },
  { t: 'Preview → run', x: 'Dry-run first; the gate still decides' },
]

const DRY_FIXTURE = [
  { intent: 'Add a keyboard-shortcut cheat sheet overlay', altitude: 'feature' },
  { intent: 'Empty-state guidance for first-run users', altitude: 'ticket' },
  { intent: 'Inline form validation on the settings page', altitude: 'feature' },
  { intent: 'Bulk-select rows with shift-click', altitude: 'feature' },
  { intent: 'Focus-visible audit across all controls', altitude: 'ticket' },
]

export default function FeederControl({ data, toast }) {
  const [step, setStep] = useState(0)
  const [scope, setScope] = useState('fidelity-ladder demo app (Acme); studio-ops tooling')
  const [ran, setRan] = useState(null)
  const feeder = { volume_cap: 5, cost_envelope_usd: 5, context_cap_tokens: 30000 }

  const runReal = async () => {
    try {
      const r = await api.feederRun({ scope })
      setRan({ ...r, live: true })
      toast(r.triggered ? `Feeder ran: ${r.filed} filed of ${r.proposed} proposed` : `Feeder refused: ${r.reason}`)
    } catch {
      setRan({ triggered: false, live: false, reason: 'harness unreachable — nothing ran (fail-closed)' })
      toast('Harness unreachable — nothing ran')
    }
  }

  return (
    <Wizard title="Feeder" steps={STEPS} step={step}
            footNote="files through the standard door — the feeder can never self-admit">
      {step === 0 && (
        <>
          <h2>The studio brainstorm</h2>
          <p className="note">A headless council run, governed entirely by the ANCHOR: scope steers it,
            the non-negotiables are injected into ideation, and the top-N survivors are filed as
            idea-issues — where the same admission gate judges them like any human filing.</p>
          <div className="radio-cards">
            <button className="rcard sel"><b>Trigger a run</b><span>On-demand; subscription lane ($0 metered) once the skill-server publishes `complete`.</span></button>
            <button className="rcard off" disabled><b>Nightly schedule</b><span>Temporal schedule — operator gate, not yet armed.</span></button>
          </div>
          <div className="wiz-nav"><button className="btn btn-acc" onClick={() => setStep(1)}>Configure →</button></div>
        </>
      )}

      {step === 1 && (
        <>
          <h2>Parameters</h2>
          <p className="note">All from the ANCHOR's feeder block — shown so you know what governs the run.</p>
          <div className="field">
            <label className="flab" htmlFor="fd-scope">Scope</label>
            <p className="fexp">One line that steers what gets proposed. The strongest lever — ideas outside it tend to dock at the gate anyway, so scope tight.</p>
            <textarea id="fd-scope" className="in" rows={2} value={scope} onChange={(e) => setScope(e.target.value)} />
          </div>
          <div className="vmap">
            <div className="vrow"><span className="vk">volume_cap</span><span>top-{feeder.volume_cap} ideas filed per run — the rest are dropped, loudly</span><span className="ok">{feeder.volume_cap}</span></div>
            <div className="vrow"><span className="vk">cost_envelope_usd</span><span>bounds the SHADOW cost (the subscription lane is $0 metered but tokens still count)</span><span className="ok">${feeder.cost_envelope_usd.toFixed(2)}</span></div>
            <div className="vrow"><span className="vk">context_cap_tokens</span><span>hard-truncates any workspace context fed to the prompt</span><span className="ok">{feeder.context_cap_tokens.toLocaleString()}</span></div>
            <div className="vrow"><span className="vk">guardrails</span><span>the ANCHOR non-negotiables are injected into ideation, not just enforced at the gate</span><span className="ok">✓ in prompt</span></div>
          </div>
          <div className="wiz-nav">
            <button className="btn" onClick={() => setStep(0)}>← Back</button>
            <button className="btn btn-acc" onClick={() => setStep(2)}>Preview →</button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <h2>Dry-run preview → real run</h2>
          <p className="note">The dry preview shows the SHAPE of a run (fixture sink, $0). The real
            trigger rides the skill-server; if it is unreachable the run refuses — it never pretends.</p>
          <div className="vmap">
            {DRY_FIXTURE.map((c, i) => (
              <div className="vrow" key={i}>
                <span className="vk">#{i + 1}</span>
                <span>{c.intent}</span>
                <span className="lbl lbl-rung" style={{ justifySelf: 'start' }}>{c.altitude}</span>
              </div>
            ))}
            <div className="vrow"><span className="vk">then</span><span>each files as an idea-issue → the admission gate decides admit / dock / needs-human</span><span className="warn">gate's call</span></div>
          </div>
          {ran && (
            <div className={`verdict${ran.triggered ? '' : ' bad-edge'}`}>
              <b>{ran.triggered ? `Ran: ${ran.filed} filed of ${ran.proposed} proposed` : 'Refused'}</b>
              <div className="fexp" style={{ margin: '2px 0 0' }}>
                {ran.triggered
                  ? `within envelope: ${String(ran.within_envelope)} · $${(ran.cost_usd ?? 0).toFixed(4)} metered / $${(ran.normalized_usd ?? 0).toFixed(4)} shadow`
                  : ran.reason}
              </div>
            </div>
          )}
          <div className="wiz-nav">
            <button className="btn" onClick={() => setStep(1)}>← Back</button>
            {!ran?.triggered && <button className="btn btn-acc" onClick={runReal}>Trigger the real run</button>}
          </div>
        </>
      )}
    </Wizard>
  )
}

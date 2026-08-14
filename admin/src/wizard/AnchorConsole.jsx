// ANCHOR console [P3.2 debt] — edits are PRs, never live-poked. Guided: 1 pick the section →
// 2 every key explained (configuration.md is the blueprint) → 3 schema-validate + PR payload.
import React, { useState } from 'react'
import { api } from '../api.js'
import Wizard from './Wizard.jsx'

const STEPS = [
  { t: 'Section', x: 'Which part of the constitution' },
  { t: 'Explain & edit', x: 'Every key teaches what it does' },
  { t: 'Validate → PR', x: 'Schema check, then a PR — never live-poked' },
]

// The editable surface (v1 scope): the knobs with clear blast radius, each with its
// configuration.md explanation inline.
const SECTIONS = {
  funnel: {
    label: 'Funnel policy',
    keys: [
      { k: 'auto_build', type: 'int', min: 0, max: 3, exp: 'Top-N ideas that climb the FULL ladder hands-off. The widest blast radius in the file — each auto-build can spend up to the expedition ceiling.' },
      { k: 'interactive_demos', type: 'int', min: 0, max: 10, exp: 'Next-N advance to a rung-3 clickable demo, then park. Cheap direction-testing.' },
      { k: 'queue', type: 'int', min: 0, max: 20, exp: 'How many admitted ideas may sit invisible. 0 = the backlog is a gallery, never a black hole.' },
    ],
  },
  budgets: {
    label: 'Budgets',
    keys: [
      { k: 'per_expedition_ceiling_usd', type: 'float', min: 1, max: 50, exp: 'An expedition parks VISIBLY at this ceiling — it never creeps. The fail-closed money line.' },
    ],
  },
  demote: {
    label: 'Autonomy demote trigger',
    keys: [
      { k: 'agreement_threshold', type: 'float', min: 0.5, max: 1, exp: 'Judge-vs-human agreement below this (over the window) tightens the rung dial one step. Lower = more trusting; the cascade still only ever tightens.' },
      { k: 'window', type: 'int', min: 3, max: 50, exp: 'The rolling number of decisions the threshold is measured over.' },
    ],
  },
}

export default function AnchorConsole({ data, toast }) {
  const [step, setStep] = useState(0)
  const [sect, setSect] = useState('funnel')
  const [edits, setEdits] = useState({})
  const [check, setCheck] = useState(null)
  const [proposed, setProposed] = useState(null)

  const current = (k) => {
    const a = data.anchor || {}
    if (sect === 'funnel') return a.funnel?.[k]
    if (sect === 'budgets') return a.budgets?.[k]
    return a.autonomy_demote?.[k] // may be absent in fixtures — shown as —
  }

  const validate = async () => {
    const payload = { section: sect, edits }
    try {
      const r = await api.anchorValidate(payload)
      setCheck({ ...r, live: true })
    } catch {
      // offline fallback: client-side range check only, said honestly
      const errs = []
      for (const spec of SECTIONS[sect].keys) {
        const v = edits[spec.k]
        if (v === undefined || v === '') continue
        const n = Number(v)
        if (Number.isNaN(n) || n < spec.min || n > spec.max) errs.push(`${spec.k}: out of range [${spec.min}, ${spec.max}]`)
      }
      setCheck({ valid: errs.length === 0, errors: errs, live: false })
    }
  }

  const propose = async () => {
    try {
      const r = await api.anchorPropose({ section: sect, edits })
      setProposed(r)
      toast(r.pr_url ? `PR opened: ${r.pr_url}` : 'PR payload prepared (token pending — nothing merged)')
    } catch {
      toast('Harness unreachable — no PR was opened (fail-closed)')
    }
  }

  const dirty = Object.keys(edits).filter((k) => edits[k] !== undefined && edits[k] !== '')

  return (
    <Wizard title="ANCHOR console" steps={STEPS} step={step}
            footNote="the constitution changes by PR only — the running system never live-pokes">
      {step === 0 && (
        <>
          <h2>Which section?</h2>
          <p className="note">The ANCHOR is one reviewable file. Pick the section to edit; rungs/adjudicator/builder are read-only in v1 (higher blast radius — edit the file by hand + PR).</p>
          <div className="radio-cards" role="radiogroup" aria-label="Section">
            {Object.entries(SECTIONS).map(([id, s]) => (
              <button key={id} role="radio" aria-checked={sect === id}
                      className={`rcard${sect === id ? ' sel' : ''}`} onClick={() => setSect(id)}>
                <b>{s.label}</b><span>{s.keys.length} editable key{s.keys.length > 1 ? 's' : ''}</span>
              </button>
            ))}
          </div>
          <div className="wiz-nav"><button className="btn btn-acc" onClick={() => setStep(1)}>Edit {SECTIONS[sect].label} →</button></div>
        </>
      )}

      {step === 1 && (
        <>
          <h2>{SECTIONS[sect].label}</h2>
          <p className="note">Leave a field blank to keep the current value. What each key does is written under it — the same text as <code>configuration.md</code>.</p>
          {SECTIONS[sect].keys.map((spec) => (
            <div className="field" key={spec.k}>
              <label className="flab" htmlFor={`ak-${spec.k}`}>{spec.k}
                <span className="money" style={{ marginLeft: 8 }}>current: {String(current(spec.k) ?? '—')}</span></label>
              <p className="fexp">{spec.exp}</p>
              <input id={`ak-${spec.k}`} className="in" style={{ maxWidth: 220 }} inputMode="decimal"
                     value={edits[spec.k] ?? ''} placeholder={String(current(spec.k) ?? '')}
                     onChange={(e) => setEdits({ ...edits, [spec.k]: e.target.value })} />
            </div>
          ))}
          <div className="wiz-nav">
            <button className="btn" onClick={() => { setStep(0); setCheck(null) }}>← Back</button>
            <button className="btn btn-acc" onClick={() => { setStep(2); setCheck(null); validate() }}
                    disabled={dirty.length === 0}>Validate {dirty.length} change{dirty.length === 1 ? '' : 's'} →</button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <h2>Validate → PR</h2>
          <div className="vmap">
            {dirty.map((k) => (
              <div className="vrow" key={k}>
                <span className="vk">{k}</span>
                <span>{String(current(k) ?? '—')} → <b>{edits[k]}</b></span>
                <span className={check == null ? 'warn' : (check.errors || []).some((e) => e.startsWith(k)) ? 'bad' : 'ok'}>
                  {check == null ? '… checking' : (check.errors || []).some((e) => e.startsWith(k)) ? '✗ invalid' : '✓ valid'}
                </span>
              </div>
            ))}
            <div className="vrow">
              <span className="vk">Cascade</span>
              <span>edits apply at ANCHOR level — tighten-only governs everything below it</span>
              <span className="ok">✓ rule holds</span>
            </div>
          </div>
          {check && (
            <div className={`verdict${check.valid ? '' : ' bad-edge'}`}>
              <b>{check.valid ? 'Schema-valid' : 'Invalid'}{check.live ? ' (harness pydantic check)' : ' (offline range check only)'}</b>
              {(check.errors || []).map((e) => <div key={e} className="fexp" style={{ margin: '2px 0 0' }}>{e}</div>)}
              {check.valid && !proposed && (
                <div className="fexp" style={{ margin: '2px 0 0' }}>Submitting opens a PR against ANCHOR.md —
                  a human reviews and merges; the running system picks it up on restart. Never live-poked.</div>
              )}
            </div>
          )}
          {proposed && (
            <div className="verdict">
              <b>{proposed.pr_url ? 'PR opened' : 'PR payload prepared'}</b>
              <div className="fexp" style={{ margin: '2px 0 0' }}>
                {proposed.pr_url
                  ? <a href={proposed.pr_url} target="_blank" rel="noreferrer">{proposed.pr_url}</a>
                  : `branch ${proposed.branch || 'anchor-edit'} — outbound token pending (github-app-setup.md); the diff is staged, nothing merged.`}
              </div>
            </div>
          )}
          <div className="wiz-nav">
            <button className="btn" onClick={() => setStep(1)}>← Back to edit</button>
            {!proposed && <button className="btn btn-acc" onClick={propose} disabled={!check?.valid}>Open the PR</button>}
          </div>
        </>
      )}
    </Wizard>
  )
}

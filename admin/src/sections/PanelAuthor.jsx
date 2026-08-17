// FLS v0.6 #5 — Panel-authoring UI. Authors/edits the `panel` binding a lens uses (P2a
// LensParams.panel + LensParams.target_vessel): either the registry name of a panel declared
// in the brainstorm layer (e.g. brainstorm-system/personas/panel-default.json) or an explicit
// list of persona ids composed here, targeted at one of this instance's declared vessels.
//
// Shape mirrors contracts/config.schema.json's `panel` property exactly:
//   panel: string | string[]   (registry name, OR an explicit persona-id list)
// target_vessel is FLS-side (LensParams.target_vessel) — not part of that schema, but every
// vessel this binds to must already be declared in this instance's ANCHOR (data.anchor.vessels).
//
// Edits are PRs, same rule as the ANCHOR console (Vessels.jsx / AnchorConsole.jsx) — this
// screen builds + validates the payload, then proposes it. The harness has no panel-binding
// endpoint yet (only /anchor/{validate,propose} for funnel/budgets/demote sections — see
// engine/src/fls/anchor.py _SECTION_MAP); rather than block on an engine change, `api.panelPropose`
// below calls the endpoint this UI expects and degrades honestly (never silently) when it 404s,
// showing the exact JSON payload a human (or a follow-up engine PR) can apply. See the
// TODO(backend) note near the bottom of this file.
import React, { useState } from 'react'
import { api } from '../api.js'

/** Validate a panel value against config.schema.json's `panel` oneOf: a non-empty registry
 * name string, or a non-empty array of non-empty persona-id strings. Returns an error string,
 * or null when valid. */
function validatePanelShape(mode, registryName, personaIds) {
  if (mode === 'registry') {
    if (!registryName.trim()) return 'Registry panel name is required.'
    return null
  }
  const ids = personaIds.map((s) => s.trim()).filter(Boolean)
  if (ids.length === 0) return 'Add at least one persona id, or switch to a registry name.'
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i)
  if (dupes.length) return `Duplicate persona id(s): ${[...new Set(dupes)].join(', ')}`
  return null
}

/** @param {{data: any, toast: (m:string)=>void}} props */
export default function PanelAuthor({ data, toast }) {
  const vessels = data.anchor?.vessels || []
  const defaultVessel = data.anchor?.default_vessel || ''

  const [mode, setMode] = useState('registry') // 'registry' | 'explicit'
  const [registryName, setRegistryName] = useState('default')
  const [personaIds, setPersonaIds] = useState([])
  const [newId, setNewId] = useState('')
  const [targetVessel, setTargetVessel] = useState(defaultVessel)
  const [customVessel, setCustomVessel] = useState('')
  const [check, setCheck] = useState(null)
  const [proposed, setProposed] = useState(null)
  const [saving, setSaving] = useState(false)

  const effectiveVessel = vessels.length ? targetVessel : customVessel.trim()

  const addPersona = () => {
    const id = newId.trim()
    if (!id) return
    if (personaIds.includes(id)) { toast(`'${id}' is already in the list`); return }
    setPersonaIds([...personaIds, id])
    setNewId('')
  }
  const removePersona = (id) => setPersonaIds(personaIds.filter((p) => p !== id))

  const payload = () => ({
    panel: mode === 'registry' ? registryName.trim() : personaIds.map((s) => s.trim()),
    target_vessel: effectiveVessel || null,
  })

  const validate = () => {
    const panelErr = validatePanelShape(mode, registryName, personaIds)
    const errs = panelErr ? [panelErr] : []
    if (vessels.length && !effectiveVessel) errs.push('Pick a target vessel (or leave the ANCHOR default).')
    setCheck({ valid: errs.length === 0, errors: errs })
    setProposed(null)
    return errs.length === 0
  }

  const save = async () => {
    if (!validate()) return
    setSaving(true)
    try {
      const r = await api.panelPropose(payload())
      setProposed({ ...r, stubbed: false })
      toast(r.pr_url ? `PR opened: ${r.pr_url}` : 'Panel binding staged (no outbound token yet)')
    } catch {
      // TODO(backend): /panels/propose does not exist yet — see api.js panelPropose and
      // engine/src/fls/app.py anchor_propose (the pattern to mirror once a lens/panel section
      // is added to _SECTION_MAP in anchor.py). Until then this degrades HONESTLY: nothing was
      // saved, the exact payload is shown below for manual application or a follow-up PR.
      setProposed({ stubbed: true, payload: payload() })
      toast('No /panels save endpoint on the harness yet — payload staged below (nothing written)')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Panel author</h2>
        <span style={{ flex: 1 }} />
        <a className="btn" href="#/anchor/vessels" style={{ textDecoration: 'none' }}>Vessels →</a>
      </div>
      <p className="note">Compose the persona panel a lens ideates with, then target the vessel it
        grounds against. A panel is either a <b>registry name</b> (a panel declared in the
        brainstorm layer, e.g. <code>"default"</code>) or an <b>explicit persona-id list</b> you
        build here — the same <code>panel</code> shape as <code>contracts/config.schema.json</code>.
        Edits are PRs, same rule as the ANCHOR console.</p>

      <div className="card card-pad">
        <div className="sub-h">Panel source</div>
        <div className="radio-cards" role="radiogroup" aria-label="Panel source" style={{ marginTop: 8 }}>
          <button role="radio" aria-checked={mode === 'registry'}
                  className={`rcard${mode === 'registry' ? ' sel' : ''}`}
                  onClick={() => { setMode('registry'); setCheck(null); setProposed(null) }}>
            <b>Registry name</b>
            <span>Reference a panel already declared in the brainstorm layer's personas registry.</span>
          </button>
          <button role="radio" aria-checked={mode === 'explicit'}
                  className={`rcard${mode === 'explicit' ? ' sel' : ''}`}
                  onClick={() => { setMode('explicit'); setCheck(null); setProposed(null) }}>
            <b>Explicit persona list</b>
            <span>Compose an ad-hoc panel from persona ids — no registry entry needed.</span>
          </button>
        </div>

        {mode === 'registry' ? (
          <div className="field" style={{ marginTop: 14 }}>
            <label className="flab" htmlFor="pa-registry">Registry panel name</label>
            <p className="fexp">Matches a panel's <code>name</code> in the personas registry (e.g.
              brainstorm-system's <code>panel-default.json</code> declares <code>"default"</code>).
              This UI does not read that registry live — spell it exactly.</p>
            <input id="pa-registry" className="in" style={{ maxWidth: 280 }}
                   value={registryName} onChange={(e) => { setRegistryName(e.target.value); setCheck(null) }} />
          </div>
        ) : (
          <div className="field" style={{ marginTop: 14 }}>
            <label className="flab" htmlFor="pa-persona">Persona ids</label>
            <p className="fexp">Add each persona id in order (e.g. <code>builder</code>,
              <code> user-advocate</code>, <code>operator</code>). At least one required.</p>
            <div style={{ display: 'flex', gap: 8, maxWidth: 360 }}>
              <input id="pa-persona" className="in" placeholder="persona-id"
                     value={newId}
                     onChange={(e) => setNewId(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addPersona() } }} />
              <button type="button" className="btn" onClick={addPersona}>Add</button>
            </div>
            <div className="chip-wrap" style={{ marginTop: 10 }}>
              {personaIds.length === 0 && <span className="fexp" style={{ margin: 0 }}>No personas added yet.</span>}
              {personaIds.map((id) => (
                <span key={id} className="nn-chip">
                  {id}
                  <button type="button" onClick={() => removePersona(id)}
                          aria-label={`remove ${id}`}
                          style={{ marginLeft: 6, border: 0, background: 'transparent', cursor: 'pointer', color: 'inherit' }}>×</button>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="card card-pad">
        <div className="sub-h">Target vessel</div>
        {vessels.length ? (
          <div className="field" style={{ marginTop: 8, marginBottom: 0 }}>
            <label className="flab" htmlFor="pa-vessel">LensParams.target_vessel</label>
            <p className="fexp">The vessel this panel's lens grounds against
              {defaultVessel && <> — leave on <code>{defaultVessel}</code> to use the ANCHOR default</>}.</p>
            <select id="pa-vessel" className="in" style={{ maxWidth: 280 }}
                    value={targetVessel} onChange={(e) => { setTargetVessel(e.target.value); setCheck(null) }}>
              {!defaultVessel && <option value="">— pick a vessel —</option>}
              {vessels.map((v) => <option key={v.name} value={v.name}>{v.name} ({v.kind})</option>)}
            </select>
          </div>
        ) : (
          <div className="field" style={{ marginTop: 8, marginBottom: 0 }}>
            <p className="fexp">No vessels declared on this ANCHOR (slim mode) — type a vessel name
              (it will need a matching entry once one exists) or leave blank to bind at ANCHOR level.</p>
            <input className="in" style={{ maxWidth: 280 }} placeholder="(optional) vessel name"
                   value={customVessel} onChange={(e) => { setCustomVessel(e.target.value); setCheck(null) }} />
          </div>
        )}
      </div>

      <div className="card card-pad">
        <div className="sub-h">Validate → save</div>
        <div className="vmap" style={{ marginTop: 8 }}>
          <div className="vrow">
            <span className="vk">panel</span>
            <span>{mode === 'registry'
              ? (registryName.trim() || '—')
              : (personaIds.length ? `[${personaIds.join(', ')}]` : '—')}</span>
          </div>
          <div className="vrow">
            <span className="vk">target_vessel</span>
            <span>{effectiveVessel || '— (ANCHOR default)'}</span>
          </div>
        </div>
        {check && (
          <div className={`verdict${check.valid ? '' : ' bad-edge'}`} style={{ marginTop: 10 }}>
            <b>{check.valid ? 'Schema-valid' : 'Invalid'}</b>
            {(check.errors || []).map((e) => <div key={e} className="fexp" style={{ margin: '2px 0 0' }}>{e}</div>)}
          </div>
        )}
        {proposed && (
          <div className={`verdict${proposed.stubbed ? ' bad-edge' : ''}`} style={{ marginTop: 10 }}>
            <b>{proposed.stubbed ? 'No save endpoint yet — nothing written' : (proposed.pr_url ? 'PR opened' : 'Payload staged')}</b>
            {proposed.stubbed ? (
              <>
                <div className="fexp" style={{ margin: '4px 0 6px' }}>
                  The harness has no <code>/panels/propose</code> route yet (client stub in
                  <code> api.js</code>; a follow-up engine PR wires a <code>panel</code>/<code>lenses</code>
                  section into <code>anchor.py</code>'s console edit map). Apply this by hand or paste it
                  into that follow-up PR:
                </div>
                <pre style={{ margin: 0, fontSize: 11.5, whiteSpace: 'pre-wrap' }}>{JSON.stringify(proposed.payload, null, 2)}</pre>
              </>
            ) : (
              <div className="fexp" style={{ margin: '2px 0 0' }}>
                {proposed.pr_url
                  ? <a href={proposed.pr_url} target="_blank" rel="noreferrer">{proposed.pr_url}</a>
                  : `branch ${proposed.branch || 'panel-edit'} — outbound token pending; the diff is staged, nothing merged.`}
              </div>
            )}
          </div>
        )}
        <div className="wiz-nav" style={{ marginTop: 12 }}>
          <button className="btn" onClick={validate}>Validate</button>
          <button className="btn btn-acc" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save panel →'}
          </button>
        </div>
      </div>
    </div>
  )
}

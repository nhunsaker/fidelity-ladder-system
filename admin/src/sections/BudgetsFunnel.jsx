// Anchor · Budgets & funnel — every editable key on one page.
//
// This was a three-step Wizard: pick a section → fill fields → validate → PR. Six integers live
// behind those steps in total, and nothing gated: no step depended on the one before it. The
// wizard was not managing complexity, it was hiding how little there was, and a reader could not
// see the whole editable surface without navigating twice.
//
// Two smaller things went with it. The allowed range was enforced on submit but never shown, so
// you found the limit by hitting it. And `current: N` sat beside an empty input whose placeholder
// was ALSO N — blank meant "keep", but a filled box and an empty one looked identical. The value
// is now stated, then an arrow, then the box: the direction of travel is the layout.
//
// What did NOT change: editing is a pull request. That rule is why this screen has a diff and an
// "Open the PR" button rather than Save, and flattening it must not blur that.
import React, { useState } from 'react'
import { api } from '../api.js'
import Icon from '../icons.jsx'

/** The whole editable surface. `where` names the slice of `/anchor` the current value comes from,
 *  so a reader can check any number against the file. */
const SECTIONS = [
  {
    id: 'funnel', title: 'FUNNEL', where: 'funnel',
    what: 'What happens to an idea once the gate admits it.',
    keys: [
      { k: 'auto_build', icon: 'stairs', min: 0, max: 3, fmt: String,
        exp: 'Top-N ideas that climb the full ladder hands-off. The widest blast radius in the file — each one can spend up to the expedition ceiling.' },
      { k: 'interactive_demos', icon: 'cursor-click', min: 0, max: 10, fmt: String,
        exp: 'Next-N advance to a rung-3 clickable demo, then park. Cheap direction-testing.' },
      { k: 'queue', icon: 'stack', min: 0, max: 20, fmt: String,
        exp: 'How many admitted ideas may sit invisible. 0 means the backlog is a gallery, never a black hole.' },
    ],
  },
  {
    id: 'budgets', title: 'BUDGETS', where: 'budgets',
    what: 'The money line. An expedition parks visibly here; it never creeps.',
    keys: [
      { k: 'per_expedition_ceiling_usd', icon: 'coins', min: 1, max: 50,
        fmt: (v) => `$${Number(v).toFixed(2)}`, range: '$1.00 – $50.00',
        exp: 'An expedition parks visibly at this ceiling. The fail-closed money line — it does not creep and it does not ask again.' },
    ],
  },
  {
    id: 'demote', title: 'AUTONOMY DEMOTE', where: 'autonomy_demote',
    what: 'When the ladder tightens itself. Read the trail on Autonomy first.',
    keys: [
      { k: 'agreement_threshold', icon: 'scales', min: 0.5, max: 1, fmt: (v) => Number(v).toFixed(2),
        range: '0.50 – 1.00',
        exp: 'Judge-vs-human agreement below this, over the window, drops that rung’s dial one step tighter. Lower is more trusting. The cascade only ever tightens.' },
      { k: 'window', icon: 'clock-counter-clockwise', min: 3, max: 50, fmt: String,
        range: '3 – 50 decisions',
        exp: 'The rolling number of decisions the threshold is measured over.' },
    ],
  },
]

const ALL_KEYS = SECTIONS.flatMap((s) => s.keys.map((k) => ({ ...k, section: s.id, where: s.where })))

/** @param {{data:any, edits:object, setEdits:Function}} props */
function KeyRow({ spec, current, edit, onEdit }) {
  const changed = edit !== undefined && edit !== '' && String(edit) !== String(current ?? '')
  return (
    <>
      <div className="bk-name">
        <div className="bk-id"><Icon name={spec.icon} className="k-ico" />{spec.k}</div>
        <div className="bk-range">{spec.range || `${spec.min} – ${spec.max}`}</div>
      </div>
      <div className="bk-exp">{spec.exp}</div>
      <div className="bk-edit">
        <span className="bk-now">{current == null ? '—' : spec.fmt(current)}</span>
        <span className="bk-arrow" aria-hidden="true">→</span>
        <input className={`in bk-in${changed ? ' changed' : ''}`} inputMode="decimal"
               aria-label={`${spec.k} — currently ${current ?? 'unset'}`}
               value={edit ?? (current ?? '')}
               onChange={(e) => onEdit(spec.k, e.target.value)} />
      </div>
    </>
  )
}

/** @param {{data: any, toast: (s:string)=>void}} props */
export default function BudgetsFunnel({ data, toast }) {
  const a = data.anchor || {}
  const [edits, setEdits] = useState({})
  const [check, setCheck] = useState(null)
  const [proposed, setProposed] = useState(null)
  const [busy, setBusy] = useState(false)

  const currentOf = (spec) => (a[spec.where] || {})[spec.k]
  const onEdit = (k, v) => { setEdits({ ...edits, [k]: v }); setCheck(null); setProposed(null) }

  // A change is a value that DIFFERS from the current one — typing the same number back is not an
  // edit, and proposing a PR that changes nothing wastes a reviewer.
  const changed = ALL_KEYS.filter((spec) => {
    const e = edits[spec.k]
    return e !== undefined && e !== '' && String(e) !== String(currentOf(spec) ?? '')
  })

  const validate = async () => {
    const bySection = {}
    for (const spec of changed) (bySection[spec.section] ||= {})[spec.k] = edits[spec.k]
    const errors = []
    for (const spec of changed) {
      const n = Number(edits[spec.k])
      if (Number.isNaN(n) || n < spec.min || n > spec.max) {
        errors.push(`${spec.k}: outside ${spec.min} – ${spec.max}`)
      }
    }
    if (errors.length) { setCheck({ valid: false, errors, live: false }); return null }
    try {
      // one section per call — the endpoint edits a named section, and the whole point of this
      // screen is that a reader sees all three at once, not that they become one section
      const results = await Promise.all(Object.entries(bySection).map(
        ([section, e]) => api.anchorValidate({ section, edits: e })))
      const bad = results.flatMap((r) => r.errors || [])
      setCheck({ valid: bad.length === 0, errors: bad, live: true })
      return bad.length === 0 ? bySection : null
    } catch (ex) {
      // FAIL CLOSED. This said `valid: true` and returned the edits, so a validation call that
      // never completed became a pull request against the constitution — with the screen showing
      // "range-checked offline" as if that were a lesser but sufficient check. It is not: the
      // local check below only knows each key's numeric range, while the server validates the
      // whole file against the schema.
      //
      // And proceeding was pointless even when it looked harmless: `propose()` posts to the SAME
      // harness. If validate could not reach it, neither can the thing it was waving through.
      setCheck({ valid: false, live: false,
                 errors: [`could not validate against the harness: ${ex?.message || 'no reason given'}`] })
      return null
    }
  }

  const propose = async () => {
    setBusy(true)
    try {
      const bySection = await validate()
      if (!bySection) return
      const out = []
      for (const [section, e] of Object.entries(bySection)) {
        out.push(await api.anchorPropose({ section, edits: e }))
      }
      setProposed(out)
      const urls = out.map((r) => r.pr_url).filter(Boolean)
      toast(urls.length ? `PR opened: ${urls[0]}` : 'Nothing was pushed — see the reason below')
    } catch (ex) {
      // "Unreachable" was a guess, and usually the wrong one: /anchor/propose refuses for reasons
      // it states plainly — an unknown anchor repo, a section it does not edit, a value out of
      // range. Telling the operator the network was down sends them to check the wrong thing.
      toast(`No PR opened: ${ex?.message || 'the harness refused (fail-closed)'}`)
    } finally { setBusy(false) }
  }

  if (!a.funnel) {
    return (
      <div className="pane"><div className="card card-pad"><p className="note" style={{ margin: 0 }}>
        /anchor is unreachable — this screen will not show numbers it cannot source.
      </p></div></div>
    )
  }

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Budgets &amp; funnel</h2>
        <span style={{ flex: 1 }} />
        {a.version != null && <span className="money">anchor v{a.version}</span>}
      </div>
      <p className="note" style={{ marginTop: 4 }}>HOW FAR AN IDEA CLIMBS · AND WHAT THAT MAY COST</p>

      <div className="seams">
        {SECTIONS.map((s) => (
          <div className="seam" key={s.id}>
            <div className="seam-hd">
              <span className="seam-slot">{s.title}</span>
              <span className="seam-what">{s.what}</span>
              <span className="seam-st seam-st-deflt">{s.keys.length} KEY{s.keys.length > 1 ? 'S' : ''}</span>
            </div>
            <div className="bkeys">
              {s.keys.map((spec) => (
                <KeyRow key={spec.k} spec={{ ...spec, where: s.where }}
                        current={(a[s.where] || {})[spec.k]}
                        edit={edits[spec.k]} onEdit={onEdit} />
              ))}
            </div>
          </div>
        ))}

        <div className="seam">
          {changed.length > 0 && (
            <div className="bdiff">
              <div className="bdiff-h">
                {changed.length} change{changed.length === 1 ? '' : 's'}
                {check && (check.valid
                  ? <span className="bdiff-ok">{check.live ? ' · schema-valid' : ' · range-checked offline'}</span>
                  : <span className="bdiff-bad"> · invalid</span>)}
              </div>
              {changed.map((spec) => (
                <div className="bdrow" key={spec.k}>
                  <span className="bdk">{spec.k}</span>
                  <span className="bdv">{spec.fmt(currentOf(spec))} → <b>{spec.fmt(edits[spec.k])}</b></span>
                  <span className="bdok">
                    {check == null ? '…' : (check.errors || []).some((e) => e.startsWith(spec.k)) ? '✗' : '✓'}
                  </span>
                </div>
              ))}
              {(check?.errors || []).map((e) => (
                <p className="fexp" key={e} style={{ margin: '4px 0 0' }}>{e}</p>
              ))}
              {proposed?.map((r, i) => (
                <p className="fexp" key={i} style={{ margin: '6px 0 0' }}>
                  {r.pr_url
                    ? <a href={r.pr_url} target="_blank" rel="noopener noreferrer">{r.pr_url}</a>
                    : (r.note || 'staged — nothing pushed')}
                </p>
              ))}
            </div>
          )}
          <div className="bbar">
            <span className="bbar-n">{changed.length} change{changed.length === 1 ? '' : 's'}</span>
            <span className="bbar-x">
              Opens a pull request against <code>ANCHOR.md</code>. A human reviews and merges; the
              running system picks it up on restart. <b>Never live-poked.</b>
            </span>
            <button className="btn" disabled={!changed.length} onClick={() => { setEdits({}); setCheck(null); setProposed(null) }}>Reset</button>
            <button className="btn btn-acc" disabled={!changed.length || busy} onClick={propose}>
              {busy ? 'Opening…' : 'Open the PR'}
            </button>
          </div>
        </div>
      </div>

      <p className="note seam-foot">
        Six keys, all of them here. <code>rungs</code>, <code>adjudicator</code> and
        <code> builder</code> are not editable from this screen — higher blast radius, edited in the
        file by hand. A box left at its current value is not a change.
      </p>
    </div>
  )
}

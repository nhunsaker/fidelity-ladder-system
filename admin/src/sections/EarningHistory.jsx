// Earning-history panel (v0.6 item #6) — the time-series trail that EARNS a loosening.
// Autonomy (Panels.jsx Calibration{autonomy}) is point-in-time: one snapshot's agreement per
// rung. This renders the trail across snapshots so a reviewer can see agreement holding or
// improving over time, not just a single reading — the evidence "Loosening needs an earned
// track record" (autonomy panel's own copy) actually points at.
//
// v0.7 #3: gained a per-vessel filter (GET /mining-history?vessel=<name>) — a live, unpersisted
// slice of the same MiningReport shape (see mining.py). Selecting "anchor-level" (no vessel)
// keeps the v0.6 behavior exactly: the full persisted, append-only history array.
//
// DATA CONTRACT — renders item #7's mining output, frozen shape (build-plan-v6.md "Contracts-first"):
//   MiningReport = {
//     computed_at: string (ISO8601),
//     per_rung: [{ rung, samples, agreement_rate, human_override_rate,
//                  drift_trend: "improving" | "flat" | "declining" }],
//     mismatches: [...],
//     recommendation: string,
//   }
// This panel consumes an ARRAY of MiningReport, oldest-first, append-only (one per mining run
// over #7's calibration-ledger persistence).
//
// WIRED 2026-09-11. GET /mining-history has existed since v0.6; this file called it with a bare
// `fetch` carrying no session cookie, so on a guarded instance every load 401'd and fell back to
// a MOCK trail — while the badge blamed an endpoint that "had not landed". An operator reading
// invented agreement rates before loosening a dial is the worst failure this screen can have, so
// the mock is gone rather than relabelled: with no history it shows none and says why.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const TREND_LABEL = { improving: '↑ improving', flat: '→ flat', declining: '↓ declining' }
const TREND_CLASS = { improving: 'rec-eligible-to-loosen', flat: '', declining: 'rec-tighten' }


async function fetchMiningHistory(vesselName) {
  try {
    return { source: 'live', rows: await api.miningHistory(vesselName) }
  } catch (e) {
    // A bare `fetch` used to sit here, without `credentials: 'include'`. On a guarded instance it
    // 401'd on every load, so the trail an operator reads before LOOSENING A DIAL was invented —
    // and the badge blamed an endpoint that "had not landed", which has been false since v0.6.
    // A source badge naming the wrong cause is worse than none: it sends the reader to fix the
    // wrong thing. `reason` carries what actually happened.
    const reason = e?.name === 'NotSignedIn' || e?.status === 401
      ? 'not signed in to the harness — sign in and reload'
      : (e?.message || 'the harness could not be reached')
    return { source: 'unavailable', reason, rows: [] }
  }
}

/** Vessel names for the filter dropdown, from GET /anchor's `vessels` list. Empty/failed ->
 *  no dropdown, section renders anchor-level only (back-compat, matches v0.6 exactly). */
async function fetchVesselNames() {
  try {
    const a = await api.anchor()
    return (a.vessels || []).map((v) => v.name).filter(Boolean)
  } catch {
    return []
  }
}

/** Tiny inline sparkline over a 0..1 rate series — no chart lib, matches the admin's zero-dep style. */
function Sparkline({ values, w = 120, h = 28 }) {
  if (!values.length) return null
  const pts = values.map((v, i) => {
    const x = values.length === 1 ? w : (i / (values.length - 1)) * w
    const y = h - Math.max(0, Math.min(1, v)) * h
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="agreement trend">
      <polyline points={pts} fill="none" stroke="var(--color-success, #1a7f37)" strokeWidth="1.5" />
      {values.map((v, i) => {
        const x = values.length === 1 ? w : (i / (values.length - 1)) * w
        const y = h - Math.max(0, Math.min(1, v)) * h
        return <circle key={i} cx={x} cy={y} r="1.6" fill="var(--color-success, #1a7f37)" />
      })}
    </svg>
  )
}

/** Reshape append-only MiningReport[] into per-rung trails: {rung, points:[{computed_at, agreement_rate,
 *  human_override_rate, drift_trend}], latestDrift, latestRecommendation}. */
function byRung(reports) {
  const sorted = [...reports].sort((a, b) => a.computed_at.localeCompare(b.computed_at))
  const rungs = new Map()
  for (const report of sorted) {
    for (const pr of report.per_rung || []) {
      if (!rungs.has(pr.rung)) rungs.set(pr.rung, [])
      rungs.get(pr.rung).push({ computed_at: report.computed_at, ...pr, reportRecommendation: report.recommendation })
    }
  }
  return [...rungs.entries()].map(([rung, points]) => ({
    rung, points,
    latestDrift: points[points.length - 1]?.drift_trend,
    latestRecommendation: points[points.length - 1]?.reportRecommendation,
  }))
}

/** @param {{embedded?: boolean}} props — `embedded` drops the page wrapper and the page title so
 * this can sit inside Autonomy as a section rather than being its own route. It used to be one:
 * "Earning history" in the Anchor group, away from the dial recommendation it is the evidence for. */
export default function EarningHistory({ embedded = false }) {
  const [state, setState] = useState(null)
  const [vessels, setVessels] = useState([])
  const [vessel, setVessel] = useState('')

  useEffect(() => { fetchVesselNames().then(setVessels) }, [])
  useEffect(() => { fetchMiningHistory(vessel || undefined).then(setState) }, [vessel])

  const Wrap = ({ children }) => (
    <div className={embedded ? 'pane-embed' : 'pane'}>{children}</div>
  )
  if (!state) return <Wrap><p className="note">Loading the earning-history trail…</p></Wrap>

  const trails = byRung(state.rows)
  const latest = state.rows[state.rows.length - 1]

  return (
    <Wrap>
      {embedded
        ? <h3 className="pane-sub">The track record behind a loosening</h3>
        : <h2>Earning history · the track record behind a loosening</h2>}
      <p className="note">
        {embedded
          // The link used to point at Autonomy from a separate route. This IS Autonomy now, so a
          // link here would send the reader to the page they are already on.
          ? <>The table above is this moment; this is the trail across mining snapshots that a
              human actually reads before earning a rung a loosening.</>
          : <>Point-in-time agreement lives on <a href={`${import.meta.env.BASE_URL}anchor/autonomy`}>Autonomy</a>; this is the
              trail across mining snapshots (item #7's calibration mining) that a human actually
              reads before earning a rung a loosening.</>}
        {' '}
        <span className={`src-badge ${state.source === 'live' ? 'src-live' : 'src-fixtures'}`}
              title={state.source === 'live'
                ? 'live from /mining-history'
                : `the trail could not be read: ${state.reason || 'unknown'}`}>
          {state.source === 'live' ? 'live' : 'no history'}
        </span>
      </p>

      {state.source !== 'live' && (
        <div className="card card-pad" role="status">
          <p className="note" style={{ margin: 0 }}>
            <b>The trail could not be read, so none is shown.</b> {state.reason}.
            {' '}Nothing is invented here — a dial is not loosened on evidence that could not be
            fetched.
          </p>
        </div>
      )}

      {vessels.length > 0 && (
        <p className="note">
          <label htmlFor="earning-history-vessel">vessel: </label>
          <select id="earning-history-vessel" value={vessel} onChange={(e) => setVessel(e.target.value)}>
            <option value="">anchor-level (all vessels)</option>
            {vessels.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
          {vessel && (
            <span className="note" style={{ marginLeft: 8 }}>
              live slice for "{vessel}" — a single fresh snapshot, not the persisted history trail.
            </span>
          )}
        </p>
      )}

      {latest && (
        <p className="note" style={{ marginTop: -8 }}>
          Latest snapshot ({latest.computed_at}) recommendation:{' '}
          <strong>{latest.recommendation}</strong>
        </p>
      )}

      <div className="card">
        <table className="t">
          <thead>
            <tr>
              <th>rung</th>
              <th>agreement trend</th>
              <th>latest agreement</th>
              <th>latest human-override</th>
              <th>drift</th>
              <th>snapshots</th>
            </tr>
          </thead>
          <tbody>
            {trails.map((t) => {
              const lastPoint = t.points[t.points.length - 1]
              return (
                <tr key={t.rung}>
                  <td>{t.rung}</td>
                  <td><Sparkline values={t.points.map((p) => p.agreement_rate)} /></td>
                  <td>{lastPoint.agreement_rate == null ? '—' : `${Math.round(lastPoint.agreement_rate * 100)}%`}</td>
                  <td>{lastPoint.human_override_rate == null ? '—' : `${Math.round(lastPoint.human_override_rate * 100)}%`}</td>
                  <td className={TREND_CLASS[t.latestDrift] || ''}>{TREND_LABEL[t.latestDrift] || t.latestDrift}</td>
                  <td>{t.points.length}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="card card-pad" style={{ marginTop: 12 }}>
        <strong style={{ fontSize: 12.5 }}>Snapshots ({state.rows.length})</strong>
        <table className="t">
          <thead>
            <tr><th>computed_at</th><th>rungs sampled</th><th>recommendation</th></tr>
          </thead>
          <tbody>
            {[...state.rows].sort((a, b) => b.computed_at.localeCompare(a.computed_at)).map((r) => (
              <tr key={r.computed_at}>
                <td>{r.computed_at}</td>
                <td>{(r.per_rung || []).map((p) => p.rung).join(', ')}</td>
                <td>{r.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Wrap>
  )
}

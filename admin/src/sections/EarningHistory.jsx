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
// *** WIRING TODO for the lead (Lane B/#7 not yet landed in this worktree) ***
// Expected live endpoint: GET /mining-history -> MiningReport[] (mirrors the /calibration,
// /anchor, /system pattern in api.js's loadAll — same BASE, same live-first/fixtures-fallback
// shape). Until #7 emits `mining-history.jsonl` + the harness serves it, this component falls
// back to MOCK_MINING_HISTORY below (clearly flagged in the UI via the same 'source' badge
// convention api.js already uses for fixtures). To wire it for real: either (a) add
// `miningHistory: () => j('/mining-history')` to the `api` object in api.js and swap the
// fetchMiningHistory() body below to call it, or (b) fold it into loadAll() as a sixth
// Promise.all leg (`data.miningHistory`) and drop this file's local fetch entirely.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

const TREND_LABEL = { improving: '↑ improving', flat: '→ flat', declining: '↓ declining' }
const TREND_CLASS = { improving: 'rec-eligible-to-loosen', flat: '', declining: 'rec-tighten' }

// Mock snapshots — same shape live data will have. Anchor-level, 4 rungs, 5 snapshots trending
// toward an earned loosening at 3-demo (the same rung the point-in-time Calibration panel
// already flags "eligible-to-loosen" in fixtures.json, so the two panels agree on the story).
const MOCK_MINING_HISTORY = [
  { computed_at: '2026-08-01T09:00:00Z',
    per_rung: [
      { rung: '0-intent', samples: 10, agreement_rate: 0.82, human_override_rate: 0.18, drift_trend: 'flat' },
      { rung: '1-spec', samples: 8, agreement_rate: 0.61, human_override_rate: 0.39, drift_trend: 'declining' },
      { rung: '2-wireframe', samples: 6, agreement_rate: 0.85, human_override_rate: 0.15, drift_trend: 'flat' },
      { rung: '3-demo', samples: 3, agreement_rate: 0.88, human_override_rate: 0.12, drift_trend: 'improving' },
    ], mismatches: [], recommendation: 'hold' },
  { computed_at: '2026-08-04T09:00:00Z',
    per_rung: [
      { rung: '0-intent', samples: 15, agreement_rate: 0.84, human_override_rate: 0.16, drift_trend: 'flat' },
      { rung: '1-spec', samples: 12, agreement_rate: 0.65, human_override_rate: 0.35, drift_trend: 'declining' },
      { rung: '2-wireframe', samples: 10, agreement_rate: 0.89, human_override_rate: 0.11, drift_trend: 'improving' },
      { rung: '3-demo', samples: 4, agreement_rate: 0.91, human_override_rate: 0.09, drift_trend: 'improving' },
    ], mismatches: [], recommendation: 'hold' },
  { computed_at: '2026-08-08T09:00:00Z',
    per_rung: [
      { rung: '0-intent', samples: 19, agreement_rate: 0.87, human_override_rate: 0.13, drift_trend: 'improving' },
      { rung: '1-spec', samples: 15, agreement_rate: 0.68, human_override_rate: 0.32, drift_trend: 'flat' },
      { rung: '2-wireframe', samples: 12, agreement_rate: 0.91, human_override_rate: 0.09, drift_trend: 'flat' },
      { rung: '3-demo', samples: 5, agreement_rate: 0.94, human_override_rate: 0.06, drift_trend: 'improving' },
    ], mismatches: [], recommendation: 'hold' },
  { computed_at: '2026-08-12T09:00:00Z',
    per_rung: [
      { rung: '0-intent', samples: 22, agreement_rate: 0.88, human_override_rate: 0.12, drift_trend: 'flat' },
      { rung: '1-spec', samples: 17, agreement_rate: 0.71, human_override_rate: 0.29, drift_trend: 'improving' },
      { rung: '2-wireframe', samples: 14, agreement_rate: 0.92, human_override_rate: 0.08, drift_trend: 'flat' },
      { rung: '3-demo', samples: 6, agreement_rate: 0.96, human_override_rate: 0.04, drift_trend: 'improving' },
    ], mismatches: [], recommendation: 'hold' },
  { computed_at: '2026-08-16T09:00:00Z',
    per_rung: [
      { rung: '0-intent', samples: 24, agreement_rate: 0.88, human_override_rate: 0.12, drift_trend: 'flat' },
      { rung: '1-spec', samples: 18, agreement_rate: 0.72, human_override_rate: 0.28, drift_trend: 'improving' },
      { rung: '2-wireframe', samples: 15, agreement_rate: 0.93, human_override_rate: 0.07, drift_trend: 'flat' },
      { rung: '3-demo', samples: 6, agreement_rate: 0.97, human_override_rate: 0.03, drift_trend: 'improving' },
    ], mismatches: [], recommendation: 'eligible-to-loosen: 3-demo' },
]

async function fetchMiningHistory(vesselName) {
  try {
    const qs = vesselName ? `?vessel=${encodeURIComponent(vesselName)}` : ''
    const r = await fetch(`${api.base}/mining-history${qs}`)
    if (!r.ok) throw new Error(String(r.status))
    const rows = await r.json()
    return { source: 'live', rows }
  } catch {
    // vessel-filtered mock data isn't modeled — the mock trail is anchor-level only, matching
    // what a real /mining-history?vessel=... 404/offline fallback would honestly show.
    return { source: 'mock', rows: MOCK_MINING_HISTORY }
  }
}

/** Vessel names for the filter dropdown, from GET /anchor's `vessels` list. Empty/failed ->
 *  no dropdown, section renders anchor-level only (back-compat, matches v0.6 exactly). */
async function fetchVesselNames() {
  try {
    const r = await fetch(`${api.base}/anchor`)
    if (!r.ok) throw new Error(String(r.status))
    const a = await r.json()
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

export default function EarningHistory() {
  const [state, setState] = useState(null)
  const [vessels, setVessels] = useState([])
  const [vessel, setVessel] = useState('')

  useEffect(() => { fetchVesselNames().then(setVessels) }, [])
  useEffect(() => { fetchMiningHistory(vessel || undefined).then(setState) }, [vessel])

  if (!state) return <div className="pane"><p className="note">Loading the earning-history trail…</p></div>

  const trails = byRung(state.rows)
  const latest = state.rows[state.rows.length - 1]

  return (
    <div className="pane">
      <h2>Earning history · the track record behind a loosening</h2>
      <p className="note">
        Point-in-time agreement lives on <a href="#/anchor/autonomy">Autonomy</a>; this is the
        trail across mining snapshots (item #7's calibration mining) that a human actually reads
        before earning a rung a loosening.
        {' '}
        <span className={`src-badge ${state.source === 'live' ? 'src-live' : 'src-fixtures'}`}
              title={state.source === 'live' ? 'live from /mining-history' : 'mock data — /mining-history not wired yet'}>
          {state.source === 'live' ? 'live' : 'mock · endpoint TODO'}
        </span>
      </p>

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
    </div>
  )
}

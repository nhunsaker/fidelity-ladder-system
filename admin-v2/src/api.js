// API layer — live-first against the harness, fixtures fallback for offline/dev.
// Reads go straight to api.fidelity-ladder-system.n8plusus.com (or VITE_FLS_API); if the
// harness is unreachable the UI degrades to /fixtures.json and SAYS SO (the `source` field) —
// the lens never silently pretends fixture data is live.

const BASE = import.meta.env.VITE_FLS_API
  || (import.meta.env.DEV ? 'https://api.fidelity-ladder-system.n8plusus.com'
                          : 'https://api.fidelity-ladder-system.n8plusus.com')

/** @typedef {{source: 'live'|'fixtures', expeditions: any[], calibration: any[], lessons: string[], anchor: any}} AdminData */

async function j(path, opts) {
  const r = await fetch(`${BASE}${path}`, opts)
  if (!r.ok) throw new Error(`${r.status} ${path}`)
  return r.json()
}

/** Load everything the admin renders. @returns {Promise<AdminData>} */
export async function loadAll() {
  try {
    const [wall, calib, lessons, anchor] = await Promise.all([
      j('/wall'), j('/calibration'), j('/lessons'), j('/anchor'),
    ])
    return { source: 'live', expeditions: wall, calibration: calib.rungs || [],
             lessons, anchor }
  } catch {
    const f = await fetch('/fixtures.json').then((r) => r.json())
    return { source: 'fixtures', expeditions: f.expeditions, calibration: f.calibration,
             lessons: f.lessons, anchor: f.anchor }
  }
}

export const api = {
  base: BASE,
  expedition: (n) => j(`/expeditions/${n}`),
  fileIdea: (body) => j('/ideas', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  kill: (n, body) => j(`/expeditions/${n}/kill`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  anchorValidate: (body) => j('/anchor/validate', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  anchorPropose: (body) => j('/anchor/propose', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  feederRun: (body) => j('/feeder/run', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
}

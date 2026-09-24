// API layer — live-first against the harness, fixtures fallback for offline/dev.
// Reads hit the harness (VITE_FLS_API, else same-origin /api); if it is unreachable the UI
// degrades to /fixtures.json and SAYS SO (the `source` field) — the lens never silently
// pretends fixture data is live.

// Instance config (12-factor): VITE_FLS_API at build time, else same-origin /api — the
// reference deploy proxies /api/* on the admin host to the harness. No instance URLs in code.
const BASE = import.meta.env.VITE_FLS_API || '/api' 

/** @typedef {{source: 'live'|'fixtures', expeditions: any[], calibration: any[],
 *   lessons: string[], anchor: any, system: any, prose: string, goal: string,
 *   totalCost: number|null}} AdminData */

/** Thrown on a 401 so callers can tell "not signed in" from "the harness is down". */
export class NotSignedIn extends Error {
  constructor(path, identity) {
    super(`401 ${path}`)
    this.name = 'NotSignedIn'; this.status = 401
    /** Which provider to offer, so the sign-in screen can name it. */
    this.identity = identity || null
  }
}

/** Thrown on a 403: authenticated, and still refused — a different screen, not a login loop. */
export class NotAuthorised extends Error {
  constructor(path) { super(`403 ${path}`); this.name = 'NotAuthorised'; this.status = 403 }
}

async function j(path, opts) {
  // credentials: 'include' so the session cookie rides along on a cross-origin deploy. On the
  // same-origin /api reference deploy it changes nothing.
  const r = await fetch(`${BASE}${path}`, { credentials: 'include', ...opts })
  if (r.status === 401) {
    let kind = null
    try { kind = (await r.clone().json())?.detail?.identity ?? null } catch { kind = null }
    throw new NotSignedIn(path, kind)
  }
  if (r.status === 403) throw new NotAuthorised(path)
  if (!r.ok) {
    // Carry the harness's OWN sentence up to whoever shows the error. This threw away `detail`
    // and raised "409 /expeditions/12/feedback" — a status and a path, which tells an operator
    // nothing and left every caller above it guessing at a reason. The engine writes these
    // refusals to be read ("...is waiting for one of its candidates to be PICKED, not
    // approved"); dropping them here was why a screen could only say something went wrong.
    let detail = null
    try { const b = await r.clone().json(); detail = typeof b?.detail === 'string' ? b.detail : null } catch { detail = null }
    const err = new Error(detail || `${r.status} ${path}`)
    err.status = r.status
    throw err
  }
  return r.json()
}

/** Load everything the admin renders. @returns {Promise<AdminData>} */
export async function loadAll() {
  try {
    // ONE call, not five. /snapshot is the server-side union of exactly what this function used
    // to composite (test_snapshot_is_the_union_admin_loadall_composites pins that), and it
    // carries two slices the fan-out could not reach: `prose` — the ANCHOR's human header, the
    // north star and non-negotiables THIS instance declares — and `goal`. The Constitution
    // screen hardcoded that prose as a JS constant because no call returned it, and the
    // constant had drifted into describing a different instance entirely.
    const s = await j('/v1/operator/snapshot')
    const calib = s.calibration || {}
    return { source: 'live', expeditions: s.wall, calibration: calib.rungs || [],
             lessons: s.lessons, anchor: s.anchor, system: s.system || null,
             prose: s.prose || '', goal: s.goal || '',
             totalCost: calib.total_cost ?? null }
  } catch (e) {
    // A 401 is NOT an offline harness, and this distinction is load-bearing. Without it the
    // catch-all below fell through to fixtures and rendered a complete, convincing DASHBOARD
    // full of fabricated expeditions to someone who is not signed in — the worst possible
    // response to "you need to log in", because it looks like it worked.
    // 403 has to be here too, and its absence was the same bug wearing a different number: a
    // signed-in operator who is not on the allowlist got 403 from every read, fell through to
    // fixtures, and was shown a dashboard of invented expeditions under their own name.
    if (e instanceof NotSignedIn || e instanceof NotAuthorised) throw e
    const f = await fetch('/fixtures.json').then((r) => r.json())
    return { source: 'fixtures', expeditions: f.expeditions, calibration: f.calibration,
             lessons: f.lessons, anchor: f.anchor, system: f.system || null,
             // fixtures carry no prose, and the screen must SAY so rather than invent one
             prose: f.prose || '', goal: f.goal || '',
             totalCost: f.total_cost ?? null }
  }
}

export const api = {
  base: BASE,
  me: () => j('/auth/me'),
  // The whole same-site path, not just the hash. The workbench is served under a base path
  // (/app/), and a bare '#/exp/12' fails safe_return_to's "must start with /" check — so every
  // sign-in landed on '/', which is the VISITOR demo, not the console you just signed in to.
  loginUrl: (returnTo) => {
    const hash = returnTo && returnTo.startsWith('#') ? returnTo : (window.location.hash || '')
    const dest = `${window.location.pathname}${hash}`
    return `${BASE}/auth/login?return_to=${encodeURIComponent(dest)}`
  },
  logout: () => j('/auth/logout', { method: 'POST' }),
  system: () => j('/v1/operator/system'),
  expedition: (n) => j(`/v1/operator/runs/${n}`),
  thread: (n) => j(`/v1/operator/runs/${n}/thread`),
  feedback: (n, body) => j(`/v1/operator/runs/${n}/feedback`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  fileIdea: (body) => j('/v1/operator/requests', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  kill: (n, body) => j(`/v1/operator/runs/${n}/kill`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  retry: (n, body) => j(`/v1/operator/runs/${n}/retry`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  anchorValidate: (body) => j('/v1/operator/anchor/validate', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  anchorPropose: (body) => j('/v1/operator/anchor/propose', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  feederRun: (body) => j('/v1/operator/feeder/run', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
  // TODO(backend): /panels/propose doesn't exist on the harness yet — see PanelAuthor.jsx.
  // Wired the same way anchorPropose is (validated edit -> PR); PanelAuthor degrades honestly
  // (stages the payload, writes nothing) when this 404s/errors, so the section is usable today.
  // Was a bare `fetch` inside EarningHistory with no credentials, so on a guarded instance it
  // 401'd and the screen silently rendered MOCK data while telling the operator the endpoint had
  // "not landed". It has existed since v0.6.
  anchor: () => j('/v1/operator/anchor'),
  miningHistory: (vessel) => j(`/v1/operator/mining-history${vessel ? `?vessel=${encodeURIComponent(vessel)}` : ''}`),
  panelPropose: (body) => j('/v1/operator/panels/propose', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }),
}

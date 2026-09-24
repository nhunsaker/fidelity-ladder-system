// System · Modules — every seam that wires this instance, read-only.
//
// Read-only is the design, not a gap: choice is ANCHOR policy (PR-reviewed), connection is env
// (secrets), status is `GET /system` (booleans, never a value). This screen's job is to make the
// fix path obvious, never to become an env editor.
//
// It used to render FIVE of the seven seams — `lenses` and `environment` were absent entirely, in
// the one area whose stated job is showing how the instance is wired — and each card gave a kind,
// a terse line and a docs link, answering none of: what is this seam, what are my options, what
// is set up, how do I change it. SEAMS below is the content model that answers all four in the
// same order for every seam, which is also why it is data rather than seven hand-written cards.
import React from 'react'
import Icon from '../icons.jsx'

/** The authored half of each card. The live half comes from `GET /system`.
 *  `kinds` is what the engine registers for that slot; `change` is the literal thing to set. */
const SEAMS = [
  {
    key: 'auth', title: 'AUTH',
    what: 'Proves a webhook really came from GitHub, and carries the token that posts back.',
    kinds: ['github-app', 'none'],
    change: 'FLS_WEBHOOK_SECRET + GITHUB_TOKEN', where: 'env',
    // auth and sources fail OPEN to a safe local default. The docs are explicit that this is
    // "the fresh-install steady state, not an error to chase" — so it must not read like a fault.
    localKind: 'none',
    localNote: 'No GitHub App configured, so there is no webhook to verify. Nothing in the local '
      + 'flow needs one — this is the fresh-install steady state, not an error to chase.',
  },
  {
    key: 'identity', title: 'IDENTITY',
    what: 'Who the human at this console is. A browser sign-in, not a message signature.',
    kinds: ['github-oauth', 'oidc', 'proxy-header', 'none'],
    change: 'FLS_IDENTITY_KIND + FLS_ALLOWED_USERS', where: 'env',
    // The one slot whose `none` is a hazard rather than a posture — the docs single it out.
    hazardKind: 'none',
    hazardNote: 'Nobody authenticates. Anyone who can reach this URL can stop work in flight and '
      + 'spend money.',
  },
  {
    key: 'ideas', title: 'IDEAS',
    what: 'Where ideas come from. Every source enters by the one admission door.',
    kinds: ['manual', 'feeder'],
    change: 'idea_sources:', where: 'anchor',
    listDetail: 'The idea form and the issue template. Always available.',
  },
  {
    key: 'sources', title: 'SOURCES',
    what: 'The repo whose issues ARE expeditions, and where deploys land.',
    kinds: ['github', 'local'],
    change: 'FLS_REPO', where: 'env',
    localKind: 'local',
    localNote: 'This is the fresh-install steady state, not an error to chase.',
  },
  {
    key: 'workers', title: 'WORKERS',
    what: 'Who actually writes the specs, explorations and code a rung asks for.',
    kinds: ['api', 'claude-code', 'skill-server'],
    change: 'ANTHROPIC_API_KEY (api) or FLS_SKILL_SERVER_* (skill-server)', where: 'env',
  },
  {
    key: 'environment', title: 'ENVIRONMENT',
    what: "Where a rung's build and verify actually run.",
    kinds: ['worktree'],
    change: 'FLS_MODULES', where: 'env',
    listDetail: 'A throwaway git worktree per attempt; the checkout everyone shares is never '
      + 'touched.',
    note: 'devcontainer / nix / docker are documented extension kinds — none ship built-in.',
  },
  {
    key: 'lenses', title: 'LENSES',
    what: 'Scheduled audit or brainstorm passes over a vessel. Like ideas, they file through the '
      + 'door and decide nothing.',
    kinds: [],
    change: 'FLS_MODULES + lenses:', where: 'both',
    empty: 'No lens kind ships built-in — what a lens looks for is a property of your instance, '
      + 'not of the engine. Register one by pointing FLS_MODULES at an importable module, then '
      + 'declare it under lenses: in the ANCHOR.',
  },
  {
    key: 'deploy', title: 'DEPLOY',
    what: 'Where a rung-5a build lands so a human can review it.',
    kinds: ['none', 'static-dir', 'github-environment'],
    change: 'FLS_STAGE_DIR (static-dir) or FLS_DEPLOY_KIND', where: 'env',
    localKind: 'none',
    localNote: 'Nothing is wired, so rung 5a refuses with a reason rather than parking as though '
      + 'a human were expected. Not a fault — an instance that never ships from here needs no '
      + 'deploy target.',
  },
  {
    key: 'design', title: 'DESIGN',
    what: 'Where a rung-2 candidate is saved.',
    kinds: ['html', 'figma'],
    change: 'FLS_FIGMA_FILE_KEY + FLS_MCP_CONFIG', where: 'env',
    localKind: 'html',
    localNote: 'Candidates are HTML fragments stored as expedition artifacts. This is the '
      + 'fresh-install steady state, not an error to chase.',
  },
]

const WHERE = { env: 'SET IN ENV', anchor: 'SET IN ANCHOR', both: 'TO ADD ONE' }

/** Four states, not three.
 *
 * The old chip had `available` / `degraded · fail-closed` / `missing`, which collapsed the one
 * distinction an operator actually needs: **is this a problem?** `sources: local` and
 * `identity: none` both rendered as a red `missing`, though the docs call the first a steady
 * state and the second "not a posture, it is a hazard". Each state carries a WORD, so the
 * meaning never rests on colour alone.
 */
function statusOf(seam, live) {
  const entries = Array.isArray(live) ? live : [live].filter(Boolean)
  if (!entries.length) return { cls: 'deflt', label: 'NONE REGISTERED' }
  const kind = Array.isArray(live) ? null : live.kind
  if (seam.hazardKind && kind === seam.hazardKind) return { cls: 'hazard', label: 'HAZARD' }
  if (seam.localKind && kind === seam.localKind) return { cls: 'deflt', label: 'LOCAL DEFAULT' }
  if (entries.some((e) => e.configured && e.available)) return { cls: 'active', label: 'ACTIVE' }
  return { cls: 'attn', label: 'NEEDS ATTENTION' }
}

/** What is running, in this instance's own terms — from `detail`, which is booleans and
 *  non-secret names only. Never invent a value the payload does not carry. */
function runningNow(seam, live) {
  if (Array.isArray(live)) {
    const on = live.filter((e) => e.available).map((e) => e.kind)
    const off = live.filter((e) => !e.available).map((e) => e.kind)
    // A list slot's authored line plus, only when there is one, what is declared-but-not-wired.
    // "manual — not configured: feeder" told the truth but read like a fragment.
    const tail = off.length ? ` Not configured: ${off.join(', ')}.` : ''
    return { kind: on.join(' · ') || '—', detail: `${seam.listDetail || ''}${tail}`.trim() }
  }
  const d = live.detail || {}
  if (seam.key === 'identity') {
    if (live.kind === 'none') return { kind: 'none', detail: seam.hazardNote }
    const who = d.policy === 'allowlist' ? `${d.allowlist_count} allow-listed` : d.policy
    const gaps = [!d.session_secret_set && 'FLS_SESSION_SECRET',
                  !d.redirect_uri_set && 'FLS_AUTH_REDIRECT_URI'].filter(Boolean)
    return { kind: live.kind,
             detail: gaps.length ? `${who} · missing ${gaps.join(' + ')}` : `${who} · sessions signed` }
  }
  if (seam.key === 'sources') {
    return { kind: live.kind,
             detail: live.kind === 'local'
               ? 'No GitHub repo configured. Expeditions live only in the local store.'
               : `repo ${d.prod_repo || '—'}${d.dev_repo ? ` · dev ${d.dev_repo}` : ''}` }
  }
  if (seam.key === 'auth') {
    return { kind: live.kind,
             detail: live.kind === 'none' ? seam.localNote : 'Inbound HMAC verified; outbound token present.' }
  }
  if (seam.key === 'workers') {
    return { kind: live.kind,
             detail: live.available ? 'Reachable.'
               : 'Declared, but the backend is unavailable — rungs that need a builder will park.' }
  }
  if (seam.key === 'deploy') {
    if (live.kind === 'none') return { kind: 'none', detail: seam.localNote }
    if (live.kind === 'static-dir') {
      return { kind: live.kind,
               detail: d.note ? `${d.stage_dir} — ${d.note}` : `builds land in ${d.stage_dir}` }
    }
    return { kind: live.kind,
             detail: `GitHub Deployments on ${d.repo || '—'} · stage "${d.stage_environment}", `
               + `prod "${d.prod_environment}"` }
  }
  if (seam.key === 'design') {
    if (live.kind === 'html') return { kind: 'html', detail: seam.localNote }
    return { kind: live.kind,
             detail: d.note ? `file ${d.file_key} — ${d.note}` : `frames land in file ${d.file_key}` }
  }
  return { kind: live.kind, detail: Object.entries(d).map(([k, v]) => `${k}: ${v}`).join(' · ') }
}

function Seam({ seam, live }) {
  const st = statusOf(seam, live)
  const has = Array.isArray(live) ? live.length > 0 : Boolean(live)
  const now = has ? runningNow(seam, live) : null
  const kind = Array.isArray(live) ? null : live?.kind
  // An "is that ok?" line exists only where the status alone would mislead — a neutral default
  // that looks like a fault, or a declared kind the registry does not know.
  let ok = seam.note || null
  if (seam.localKind && kind === seam.localKind) ok = seam.localNote
  // Prefer the kinds the ENGINE says it accepts over this file's own copy. The copy went stale —
  // workers listed `api · skill-server` while the factory had dispatched on `claude-code` for
  // months, so a working instance was told its ANCHOR was misspelled on the same card that
  // reported its builder reachable.
  const kinds = (!Array.isArray(live) && live?.detail?.kinds) || seam.kinds
  if (!Array.isArray(live) && live && kind && kinds.length && !kinds.includes(kind)) {
    ok = `The ANCHOR declares ${kind}, which is not one of the registered kinds — check the `
       + 'spelling against the options below.'
  }
  return (
    <div className={`seam${st.cls === 'hazard' ? ' seam-hazard' : ''}`}>
      <div className="seam-hd">
        <span className="seam-slot">{seam.title}</span>
        <span className="seam-what">{seam.what}</span>
        <span className={`seam-st seam-st-${st.cls}`}>{st.label}</span>
      </div>
      {!has && seam.empty && <div className="seam-empty">{seam.empty}</div>}
      <div className="seam-rows">
        {now && (
          <>
            <div className="seam-k">RUNNING NOW</div>
            <div className="seam-v"><span className="seam-kind">{now.kind}</span>
              {now.detail ? <> — {now.detail}</> : null}</div>
          </>
        )}
        {ok && (<><div className="seam-k">IS THAT OK?</div><div className="seam-v">{ok}</div></>)}
        {kinds.length > 0 && (
          <>
            <div className="seam-k">YOUR OPTIONS</div>
            <div className="seam-v"><span className="seam-opt">
              {kinds.map((k, i) => (
                <React.Fragment key={k}>
                  {i > 0 && ' · '}
                  {k === kind ? <b>{k}</b> : k}
                </React.Fragment>
              ))}
            </span></div>
          </>
        )}
        <div className="seam-k">{WHERE[seam.where]}</div>
        <div className="seam-v"><code>{seam.change}</code></div>
      </div>
    </div>
  )
}

/** A link is offered ONLY where one can be built from data we already hold, and only when the
 *  value has the shape it should. `FLS_REPO` and the Figma key come from the operator's own env,
 *  not from a user — but a URL assembled from an unvalidated string is a bad habit to keep in a
 *  screen whose whole point is not asserting things it cannot back. Anything that fails the shape
 *  test renders as plain text, which is also what every row without a real destination gets:
 *  /srv/stage is a path on a box, `claude-code` is a CLI, `temporal` is a gRPC address, and the
 *  OIDC issuer's root serves an operator nothing. A link to none of those is the honest answer.
 */
const REPO_SHAPE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/
const FIGMA_KEY_SHAPE = /^[A-Za-z0-9]+$/

function repoUrl(slug) {
  return slug && REPO_SHAPE.test(slug) ? `https://github.com/${slug}` : null
}

/** CONNECTIONS — the same `/system` data read by SERVICE rather than by slot.
 *
 *  The seams answer "what implementation fills this engine slot". An operator asks a different
 *  question — "what is this instance plugged into, and where does its output go" — and the two
 *  are not the same axis. GitHub spans `sources` + `auth` and is ONE connection; assembling that
 *  from two cards, while knowing those two seams are the same service, is work the screen should
 *  do rather than the reader.
 *
 *  Strictly DERIVED: every value comes from the seam payload named in `seams`. Nothing here is a
 *  second source of truth, because a summary that can disagree with its own detail is worse than
 *  no summary. `at` returns the non-secret thing the service points at, or '' when there is none.
 */
const CONNECTIONS = [
  {
    key: 'github', icon: 'git-branch', name: 'GitHub', seams: ['sources', 'auth'],
    what: 'Issues are expeditions. The signed webhook brings them in; the token writes decisions back.',
    env: 'FLS_REPO · FLS_VESSEL_REPO · GITHUB_TOKEN',
    inUse: (sl) => sl.sources?.kind === 'github',
    idle: 'No repo configured — expeditions live only in the local store.',
    at: (sl) => (sl.sources?.detail?.prod_repo) || '',
    href: (sl) => repoUrl(sl.sources?.detail?.prod_repo),
    // Two repos, one connection. FLS_REPO is where DECISIONS are recorded; FLS_VESSEL_REPO is
    // where CODE lands. On most instances they are the same repo, and saying so once — "issues ·
    // code" — is more useful than a second row repeating the value. When they differ, that is
    // exactly the case an operator needs to see, so both are shown and both are linked.
    extra: (sl) => {
      const issues = sl.sources?.detail?.prod_repo || ''
      const code = sl.sources?.detail?.vessel_repo || ''
      if (!code) return null
      if (code === issues) return { label: 'issues · code', value: null, href: null }
      return { label: 'code lands in', value: code, href: repoUrl(code) }
    },
  },
  {
    key: 'identity', icon: 'fingerprint', name: 'Identity', seams: ['identity'],
    what: 'Who the human at this console is.',
    env: 'FLS_IDENTITY_KIND · FLS_ALLOWED_USERS',
    inUse: (sl) => sl.identity && sl.identity.kind !== 'none',
    idle: 'Nobody authenticates — anyone who can reach this URL is in.',
    at: (sl) => {
      const d = sl.identity?.detail || {}
      if (sl.identity?.kind === 'none') return ''
      const host = (d.issuer || '').replace(/^https?:\/\//, '')
      return host || sl.identity?.kind || ''
    },
  },
  {
    key: 'design', icon: 'pen-nib', name: 'Design', seams: ['design'],
    what: 'Where a rung-2 candidate is drawn.',
    env: 'FLS_FIGMA_FILE_KEY · FLS_MCP_CONFIG',
    inUse: (sl) => sl.design?.kind === 'figma',
    idle: 'Candidates are HTML fragments kept as expedition artifacts — no outside service.',
    at: (sl) => (sl.design?.detail?.file_key ? `file ${sl.design.detail.file_key}` : ''),
    href: (sl) => {
      const k = sl.design?.detail?.file_key
      return k && FIGMA_KEY_SHAPE.test(k) ? `https://www.figma.com/design/${k}` : null
    },
  },
  {
    key: 'deploy', icon: 'cloud-arrow-up', name: 'Stage', seams: ['deploy'],
    what: 'Where a rung-5a build lands so a human can review it. Prod is a separate, gated step.',
    env: 'FLS_STAGE_DIR · FLS_DEPLOY_KIND',
    inUse: (sl) => sl.deploy && sl.deploy.kind !== 'none',
    idle: 'Nowhere to deploy — rung 5a refuses with a reason.',
    // Only the github-environment kind has somewhere to point. `static-dir` is a path on a box.
    href: (sl) => (sl.deploy?.kind === 'github-environment'
      ? (repoUrl(sl.deploy?.detail?.repo) ? `${repoUrl(sl.deploy.detail.repo)}/deployments` : null)
      : null),
    at: (sl) => {
      const d = sl.deploy?.detail || {}
      return d.stage_dir || (d.repo ? `${d.repo} · ${d.stage_environment}` : '')
    },
  },
  {
    key: 'workers', icon: 'hammer', name: 'Builder', seams: ['workers'],
    what: 'Who writes the specs, explorations and code a rung asks for.',
    env: 'the ANCHOR builder block · the backend’s own env',
    inUse: () => true,   // a builder is always declared; `configured` says whether it is wired
    at: (sl) => sl.workers?.kind || '',
  },
]

/** A connection is only as ready as the seams behind it. `available` everywhere -> connected;
 *  anything declared-but-unreachable -> needs attention; nothing configured -> not configured.
 *  Each state carries a WORD, never colour alone. */
function connStatus(conn, slots) {
  // `available` alone CANNOT answer this. A seam's no-op kinds — sources `local`, auth `none`,
  // design `html`, deploy `none` — report available:true because they are working as intended,
  // which is right for a seam and wrong for a service: it rendered "GitHub CONNECTED" on an
  // instance with no GitHub at all, pointing at nothing. `inUse` asks the question that actually
  // belongs here — is this outside service in play — before `available` asks whether it works.
  if (conn.inUse && !conn.inUse(slots)) return { cls: 'deflt', label: 'NOT CONNECTED' }
  const parts = conn.seams.flatMap((k) => {
    const v = slots[k]
    return Array.isArray(v) ? v : [v]
  }).filter(Boolean)
  if (!parts.length) return { cls: 'deflt', label: 'NOT CONNECTED' }
  if (parts.every((p) => p.configured && p.available)) return { cls: 'active', label: 'CONNECTED' }
  if (parts.some((p) => !p.available)) return { cls: 'attn', label: 'NEEDS ATTENTION' }
  return { cls: 'deflt', label: 'NOT CONNECTED' }
}

/** Orchestration is not a seam — it comes from `/system` directly — but it IS an outside service
 *  the instance depends on, and an inventory that omits it lies by omission. */
function orchestrationRow(sys) {
  const o = sys.orchestration || {}
  if (!o.kind || o.kind === 'in-process') return null
  return {
    key: 'orchestration', icon: 'flow-arrow', name: 'Orchestration',
    seamLabel: 'ORCHESTRATION',
    what: 'Sequences a climb durably, so a restart resumes rather than starts over.',
    env: 'FLS_ORCHESTRATION · TEMPORAL_ADDRESS',
    at: o.kind,
    st: o.enabled ? { cls: 'active', label: 'CONNECTED' }
                  : { cls: 'attn', label: 'NEEDS ATTENTION' },
  }
}

function Connections({ sys }) {
  const slots = sys.slots || {}
  const rows = CONNECTIONS
    .filter((c) => c.seams.some((k) => slots[k]))
    .map((c) => {
      const st = connStatus(c, slots)
      return { key: c.key, icon: c.icon, name: c.name,
               seamLabel: c.seams.join(' · ').toUpperCase(),
               what: st.cls === 'deflt' && c.idle ? c.idle : c.what,
               env: c.env, at: c.at(slots), st,
               // a link only makes sense for a service that is actually in play
               href: st.cls === 'deflt' ? null : (c.href ? c.href(slots) : null),
               extra: st.cls === 'deflt' ? null : (c.extra ? c.extra(slots) : null) }
    })
  const orch = orchestrationRow(sys)
  if (orch) rows.push(orch)
  const ready = rows.filter((r) => r.st.cls === 'active').length

  return (
    <div className="seam">
      <div className="seam-hd">
        <span className="seam-slot">CONNECTIONS</span>
        <span className="seam-what">
          Every outside service this instance talks to, and where its output lands.
        </span>
        <span className={`seam-st seam-st-${ready === rows.length ? 'active' : 'attn'}`}>
          {ready} OF {rows.length} READY
        </span>
      </div>
      <div className="conn">
        {rows.map((r) => (
          <React.Fragment key={r.key}>
            <div className="c-svc">
              <div className="c-name"><Icon name={r.icon} className="c-ico" />{r.name}</div>
              <div className="c-seam">{r.seamLabel}</div>
            </div>
            <div className="c-for">{r.what}</div>
            <div className="c-at">
              <div className="c-val">
                {r.href
                  ? <a href={r.href} target="_blank" rel="noopener noreferrer" className="c-link">
                      {r.at}<Icon name="arrow-square-out" size={12} className="c-out" />
                    </a>
                  : (r.at || '—')}
              </div>
              {r.extra && (
                <div className="c-extra">
                  <span className="c-extra-k">{r.extra.label}</span>
                  {r.extra.value && (r.extra.href
                    ? <a href={r.extra.href} target="_blank" rel="noopener noreferrer" className="c-link">
                        {r.extra.value}<Icon name="arrow-square-out" size={12} className="c-out" />
                      </a>
                    : r.extra.value)}
                </div>
              )}
              <div className="c-env">{r.env}</div>
            </div>
            <div className="c-st"><span className={`seam-st seam-st-${r.st.cls}`}>{r.st.label}</span></div>
          </React.Fragment>
        ))}
      </div>
      <div className="seam-empty">
        Read from <code>GET /system</code> — kinds and booleans only. This screen never shows a
        secret and never edits one. Each row names the seam behind it; the cards below hold the
        detail.
      </div>
    </div>
  )
}

/** Half-wiring, named. Absent on a coherent instance — the common case, and it must stay silent
 *  there or an operator learns to skip the one row that matters. */
function Contradictions({ items }) {
  if (!items || !items.length) return null
  return (
    <div className="warnband" role="status">
      <div className="warnband-t">
        This instance contradicts itself in {items.length}{' '}
        {items.length === 1 ? 'place' : 'places'}
      </div>
      {items.map((c, i) => (
        <div className="warnband-row" key={i}>
          <div className="warnband-k">{String(c.slot || '').toUpperCase()}</div>
          <div className="warnband-v">{c.reason}</div>
        </div>
      ))}
    </div>
  )
}

/** @param {{data: any}} props */
export default function Modules({ data }) {
  const sys = data.system
  if (!sys) {
    return (
      <div className="pane"><div className="card card-pad"><p className="note" style={{ margin: 0 }}>
        /system is unreachable — module status is unavailable offline. Run against the live
        harness (or extend fixtures) to see the slot cards.</p></div></div>
    )
  }
  const slots = sys.slots || {}
  const hazard = slots.identity && slots.identity.kind === 'none'
  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Modules</h2>
        <span style={{ flex: 1 }} />
        {sys.anchor_version != null && <span className="money">anchor v{sys.anchor_version}</span>}
      </div>
      <p className="note" style={{ marginTop: 4 }}>
        NINE SEAMS · WHAT EACH IS, WHAT IS RUNNING, HOW TO CHANGE IT
      </p>

      {hazard && (
        <div className="mchip mchip-bad" role="status"
             style={{ display: 'block', padding: 10, margin: '10px 0', textAlign: 'left' }}>
          <strong>This instance is unauthenticated.</strong> Anyone who can reach this URL can stop
          work in flight and spend money. See the IDENTITY card below.
        </div>
      )}

      <div className="seams">
        <Connections sys={sys} />
        <Contradictions items={sys.contradictions} />
        {SEAMS.map((seam) => <Seam key={seam.key} seam={seam} live={slots[seam.key]} />)}
      </div>

      <p className="note seam-foot">
        Status only — this screen never shows a secret and never edits one. <b>Policy</b> lives in
        the ANCHOR and changes by PR. <b>Connections</b> live in env. To swap an implementation,
        point <code>FLS_MODULES</code> at your module: an unknown path refuses to start rather than
        running half-wired.
      </p>
    </div>
  )
}

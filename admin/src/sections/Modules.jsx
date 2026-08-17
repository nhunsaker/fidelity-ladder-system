// System · Modules — the four seams (AUTH · IDEAS · SOURCES · WORKERS) as read-only status
// cards from GET /system. Booleans + kinds + non-secret detail ONLY — this screen NEVER renders
// a secret (the endpoint doesn't return one; keep it that way). The fix path is always
// "set the env var, see docs", never an input field here.
import React from 'react'

/** One green/amber/red status chip from a {configured, available} pair. */
function StatusChip({ s }) {
  if (s.configured && s.available) return <span className="mchip mchip-ok">available</span>
  if (s.configured && !s.available) return <span className="mchip mchip-warn">degraded · fail-closed</span>
  return <span className="mchip mchip-bad">missing</span>
}

function detailLine(slot, s) {
  if (slot === 'sources') {
    if (s.kind === 'local') return 'local-mode: no GitHub repo configured (set FLS_REPO to switch)'
    const d = s.detail || {}
    return `repo ${d.prod_repo || '— (set FLS_REPO)'}${d.dev_repo ? ` · dev ${d.dev_repo}` : ''}`
  }
  if (slot === 'workers') {
    const d = s.detail || {}
    return `fallback: ${d.fallback || 'none'}${d.fallback_budget_usd ? ` · budget $${Number(d.fallback_budget_usd).toFixed(2)}/run` : ''}`
  }
  if (slot === 'auth') {
    if (s.kind === 'none') return 'local-mode: no GitHub App configured (no webhook to verify)'
    return 'inbound HMAC verify + outbound token'
  }
  return ''
}

function Card({ slot, title, s }) {
  return (
    <div className="mcard">
      <div className="mcard-head">
        <span className="mcard-slot">{title}</span>
        <span style={{ flex: 1 }} />
        <StatusChip s={s} />
      </div>
      <div className="mcard-kind">{s.kind}</div>
      <div className="why" style={{ marginTop: 6 }}>{detailLine(slot, s)}</div>
      <div style={{ marginTop: 8 }}>
        <a href={s.docs_url} target="_blank" rel="noreferrer">docs ↗</a>
      </div>
    </div>
  )
}

/** IDEAS is a LIST (the always-on manual door + optional feeder) — render its entries stacked. */
function IdeasCard({ list }) {
  return (
    <div className="mcard">
      <div className="mcard-head">
        <span className="mcard-slot">IDEAS</span>
        <span style={{ flex: 1 }} />
        <span className="why">every source enters by one admission door</span>
      </div>
      {(list || []).map((s, i) => (
        <div key={s.kind + i} className="mideas-row">
          <span className="mcard-kind" style={{ flex: 1 }}>{s.kind}</span>
          <StatusChip s={s} />
          <a href={s.docs_url} target="_blank" rel="noreferrer" style={{ marginLeft: 10 }}>docs ↗</a>
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
      <div className="pane">
        <h2>Modules</h2>
        <div className="card card-pad"><p className="note" style={{ margin: 0 }}>
          /system is unreachable — module status is unavailable offline. Run against the live
          harness (or extend fixtures) to see the slot cards.</p></div>
      </div>
    )
  }
  const slots = sys.slots || {}
  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Modules</h2>
        {sys.anchor_version != null && <span className="money">anchor v{sys.anchor_version}</span>}
        <span style={{ flex: 1 }} />
        <a className="btn" href="#/system/feeder" style={{ textDecoration: 'none' }}>Feeder control →</a>
      </div>
      <p className="note">The four seams that wire this instance. Status only — never a secret. To
        change a connection, set the env var (see each card's docs); to swap an implementation,
        point <code>FLS_MODULES</code> at your module (fail-closed on an unknown path).</p>

      <div className="mgrid">
        <Card slot="auth" title="AUTH" s={slots.auth || {}} />
        <IdeasCard list={slots.ideas} />
        <Card slot="sources" title="SOURCES" s={slots.sources || {}} />
        <Card slot="workers" title="WORKERS" s={slots.workers || {}} />
      </div>

      <p className="note">Choice = ANCHOR (policy) · connection = env (secrets) · status ={' '}
        <code>GET /system</code> (booleans only). Swap any slot by adding an importable module to{' '}
        <code>FLS_MODULES</code> — one reference implementation per slot ships built-in.</p>
    </div>
  )
}

// Anchor · Constitution — the read-only face of the governance file: north star + the five
// non-negotiables, anchor version/mode, and a summary of the vessels. Edits are PRs (the console);
// this screen never pokes anything. The north-star prose + non-negotiables are NOT in the
// /anchor payload today, so they are mirrored here from ANCHOR.md as a constant (see NOTE).
import React from 'react'
import { Label } from '../ui.jsx'
import { VesselsTable } from './Vessels.jsx'

// NOTE (API gap): /anchor returns only the machine block (version/mode/funnel/budgets/vessels),
// not the human header. Until a /anchor/prose slice exists, this mirrors ANCHOR.md's prose —
// keep in sync with the file. Flagged in the PR body as a follow-up.
const NORTH_STAR =
  'Turn a stated intent into a shipped, feature-flagged change by climbing fidelity rungs ' +
  '(spec → wireframe → interactive demo → MVP → flagged code), spending scarce human judgment ' +
  'only where blast radius earns it.'

const NON_NEGOTIABLES = [
  'Human owns every irreversible action',
  'Fail closed',
  'Accessibility floor (axe-clean before rung 5)',
  'Evidence over claims',
  'Provenance',
]

/** @param {{data: any}} props */
export default function Constitution({ data }) {
  const a = data.anchor || {}
  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Constitution</h2>
        {a.version != null && <Label kind="rung">v{a.version}</Label>}
        {a.mode && <Label kind="dial">{a.mode} mode</Label>}
        <span style={{ flex: 1 }} />
        <a className="btn btn-acc" href="#/anchor/console" style={{ textDecoration: 'none' }}>Open console →</a>
      </div>
      <p className="note">The constitution of this instance — rules that never break, in one
        reviewed file. Read-only here; every change is a PR through the console.</p>

      <div className="card card-pad">
        <div className="sub-h">North star</div>
        <p style={{ margin: '6px 0 0', fontSize: 13.5, lineHeight: 1.5 }}>{NORTH_STAR}</p>
      </div>

      <div className="card card-pad">
        <div className="sub-h">Non-negotiables · never drift; a rung may add stricter, never remove</div>
        <div className="chip-wrap" style={{ marginTop: 8 }}>
          {NON_NEGOTIABLES.map((n) => <span className="nn-chip" key={n}>{n}</span>)}
        </div>
      </div>

      <div className="card">
        <div className="sect" style={{ borderTop: 0, display: 'flex' }}>
          <span style={{ flex: 1 }}>Vessels · the context packs grounding every expedition</span>
          <a href="#/anchor/vessels">manage →</a>
        </div>
        <VesselsTable data={data} compact />
      </div>

      <div className="card card-pad">
        <div className="sub-h">Cascade</div>
        <p className="note" style={{ margin: '6px 0 0' }}>
          <code>ANCHOR → VESSEL → EXPEDITION</code>, <b>tighten-only</b> — a lower layer may make any
          constraint stricter, never looser. Trust lives in the ledger (earned), policy in the
          ANCHOR (declared), secrets in env (wired).
        </p>
      </div>
    </div>
  )
}

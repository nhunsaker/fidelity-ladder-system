// Anchor · Vessels — what an expedition works on, and what it is held to.
//
// This was a <table>, which is a card wearing a table's clothes when there is one vessel: column
// headers exist so rows can be compared. Worse, a vessel's STANDARDS — the rules a build is
// measured against, the operative content of the whole screen — were collapsed to "N standards".
//
// And every row carried an "Edit → PR" button pointing at the ANCHOR console, which has no
// vessels section at all: it edits funnel/budgets/demote and nothing else. A control that cannot
// do its job is worse than no control, so it now links to where the edit actually happens.
import React from 'react'
import Icon from '../icons.jsx'

const REPO_SHAPE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/

/** The ANCHOR file on GitHub, when we know which repo holds it. `sources.detail.prod_repo` is the
 *  repo whose issues are expeditions — the constitution may live elsewhere, so this is a best
 *  effort that renders as plain text when it cannot be built. */
function anchorUrl(system) {
  const repo = system?.slots?.sources?.detail?.prod_repo
  return repo && REPO_SHAPE.test(repo) ? `https://github.com/${repo}/blob/main/ANCHOR.md` : null
}

function Vessel({ v, isDefault, href }) {
  const paths = v.paths || []
  const standards = v.standards || []
  const refs = v.refs || []
  return (
    <div className="seam">
      <div className="v-hd">
        <span className="v-name">{v.name}</span>
        <span className="v-kind">{String(v.kind || '').toUpperCase()}</span>
        {isDefault && <span className="v-def">DEFAULT</span>}
      </div>
      {v.description && <div className="v-desc">{v.description}</div>}

      {paths.length > 0 && (
        <div className="v-block">
          <span className="v-lbl">PATHS · WHAT AN EXPEDITION MAY TOUCH</span>
          <span className="v-mono">{paths.join('  ·  ')}</span>
        </div>
      )}

      {standards.length > 0 ? (
        <>
          <span className="v-lbl v-lbl-std">STANDARDS · WHAT A BUILD IS JUDGED AGAINST</span>
          <div className="v-std">
            {standards.map((s, i) => (
              <div className="v-std-i" key={i}>
                <span className="v-std-n">{String(i + 1).padStart(2, '0')}</span>
                <span>{s}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="v-block">
          <span className="v-lbl">STANDARDS</span>
          <span className="fexp" style={{ margin: 0 }}>
            None declared — a build here is judged against the ANCHOR's non-negotiables alone.
          </span>
        </div>
      )}

      {refs.length > 0 && (
        <div className="v-block">
          <span className="v-lbl">REFS</span>
          <span className="v-mono">{refs.join('  ·  ')}</span>
        </div>
      )}

      <div className="v-edit">
        <span className="v-edit-x">
          Vessels are <b>policy</b>. They change in the constitution, by pull request — not from
          this screen.
        </span>
        {href
          ? <a className="btn" href={href} target="_blank" rel="noopener noreferrer"
               style={{ textDecoration: 'none' }}>
              Edit in ANCHOR.md<Icon name="arrow-square-out" size={12} className="c-out" />
            </a>
          : <span className="fexp" style={{ margin: 0 }}>Edit <code>ANCHOR.md</code> directly.</span>}
      </div>
    </div>
  )
}

/** Compact list, reused inside Constitution. @param {{data:any}} props */
export function VesselsTable({ data }) {
  const vessels = data.anchor?.vessels || []
  const def = data.anchor?.default_vessel
  if (!vessels.length) {
    return <p className="note" style={{ margin: 12 }}>No vessels declared — slim mode.</p>
  }
  return (
    <div className="v-compact">
      {vessels.map((v) => (
        <div className="v-c-row" key={v.name}>
          <span className="v-c-name">{v.name}</span>
          <span className="v-c-kind">{v.kind}</span>
          <span className="v-c-x">
            {(v.standards || []).length} standard{(v.standards || []).length === 1 ? '' : 's'}
            {(v.paths || []).length > 0 && <> · {v.paths.join(', ')}</>}
          </span>
          {v.name === def && <span className="v-def">DEFAULT</span>}
        </div>
      ))}
    </div>
  )
}

/** @param {{data: any}} props */
export default function Vessels({ data }) {
  const vessels = data.anchor?.vessels || []
  const def = data.anchor?.default_vessel
  const href = anchorUrl(data.system)

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Vessels</h2>
        <span style={{ flex: 1 }} />
        <a className="btn" href={`${import.meta.env.BASE_URL}anchor`} style={{ textDecoration: 'none' }}>← Constitution</a>
      </div>
      <p className="note" style={{ marginTop: 4 }}>
        THE SURFACE WORK HAPPENS ON · AND THE STANDARDS IT IS HELD TO
      </p>

      <div className="seams">
        <div className="seam">
          <div className="fd-prose">
            <p>A vessel names <b>what an expedition works on</b> and <b>what it is held to</b>. The
              admission gate reads it to judge whether an idea belongs here; the builders read it to
              know which files to touch and which rules they cannot break.</p>
          </div>
        </div>

        {vessels.length === 0 ? (
          <div className="seam">
            <div className="seam-hd">
              <span className="seam-slot">NO VESSELS</span>
              <span className="seam-what">This instance declares none.</span>
              <span className="seam-st seam-st-deflt">SLIM MODE</span>
            </div>
            <div className="seam-empty">
              Expeditions inherit directly from the ANCHOR — its non-negotiables are the only
              standards, and nothing narrows which files may be touched. Declare a{' '}
              <code>vessels:</code> block when work needs grounding in a specific surface.
            </div>
          </div>
        ) : (
          vessels.map((v) => (
            <Vessel key={v.name} v={v} isDefault={v.name === def} href={href} />
          ))
        )}
      </div>

      <p className="note seam-foot">
        One card per vessel — a table's column headers exist so rows can be compared. The{' '}
        <b>standards</b> are the rules a build is measured against, which makes them the point of
        this screen rather than a footnote to it.
      </p>
    </div>
  )
}

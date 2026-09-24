// Anchor · Constitution — the read-only face of the governance file.
//
// This screen used to HARDCODE the north star and five non-negotiables as JS constants, with a
// note admitting the API did not serve them. By 2026-09-11 the constant described a different
// instance than the one running: the harness declares a `## Purpose` about a poker product, a
// non-negotiable the constant omitted entirely ("Budget is turns + wall clock"), and none of the
// "Provenance" line the constant asserted. The screen whose whole job is showing the constitution
// was showing somebody else's.
//
// `/snapshot` has carried `prose` — the ANCHOR's human header, verbatim — the whole time; the
// admin simply fetched `/anchor` instead. It now reads the union (see api.js loadAll), and this
// file parses that markdown rather than restating it. Nothing here is authored: if the ANCHOR
// says it, it appears; if the ANCHOR does not, it cannot.
import React from 'react'
import { Label } from '../ui.jsx'
import { VesselsTable } from './Vessels.jsx'

/** Split the ANCHOR's human header into its `## ` sections.
 *
 *  Deliberately a small parser and not a markdown library: the shape is fixed by the file format
 *  (an optional HTML comment, one `# ` title, then `## ` sections of prose or `- ` bullets), and
 *  a dependency that renders arbitrary markdown would also render whatever an ANCHOR happened to
 *  contain. Anything it cannot parse is shown as plain text rather than dropped — a section this
 *  screen fails to understand is still part of the constitution.
 */
export function parseAnchorProse(md) {
  const text = String(md || '').replace(/<!--[\s\S]*?-->/g, '').trim()
  if (!text) return { title: '', sections: [] }
  const lines = text.split('\n')
  const titleLine = lines.find((l) => /^#\s+/.test(l)) || ''
  const title = titleLine.replace(/^#\s+/, '').trim()

  const sections = []
  let current = null
  for (const line of lines) {
    if (/^#\s+/.test(line)) continue                    // the title, already taken
    const h = line.match(/^##\s+(.*)$/)
    if (h) {
      current = { heading: h[1].trim(), body: [], bullets: [], broke: false }
      sections.push(current)
      continue
    }
    if (!current) continue                              // prose before any heading: not ours
    const b = line.match(/^[-*]\s+(.*)$/)
    // A bullet in this file routinely wraps, and its continuation is INDENTED. Treating those
    // lines as body prose spliced the tails of three different non-negotiables into one
    // sentence fragment at the top of the section.
    if (!b && /^\s+\S/.test(line) && current.bullets.length > 0) {
      const last = current.bullets[current.bullets.length - 1]
      last.rest = `${last.rest} ${line.trim()}`.trim()
      continue
    }
    if (b) {
      // "- **Lead.** explanation" is the house style for a non-negotiable; keep the two apart so
      // the lead can carry weight without the explanation being thrown away, which is what the
      // old chips did.
      const m = b[1].match(/^\*\*(.+?)\*\*\s*(.*)$/)
      current.bullets.push(m ? { lead: m[1].trim(), rest: m[2].trim() } : { lead: '', rest: b[1].trim() })
    } else if (line.trim()) {
      // A blank line ended the previous paragraph, so start a new one rather than running two
      // paragraphs of the Purpose together into a single block.
      if (current.broke || current.body.length === 0) { current.body.push(line.trim()); current.broke = false }
      else { current.body[current.body.length - 1] += ` ${line.trim()}` }
    } else if (!line.trim()) {
      if (current) current.broke = true
    }
  }
  return { title, sections }
}

/** Render the only two inline marks an ANCHOR's prose actually uses: `**bold**` and `` `code` ``.
 *
 *  Not a markdown renderer, on purpose. A general one would also interpret links, images and raw
 *  HTML out of a file this screen treats as authoritative — a much larger surface than two marks
 *  are worth. Anything else passes through as the literal text the file contains, which is the
 *  correct failure: the constitution is shown as written, never reinterpreted.
 */
export function inlineMarks(text) {
  const parts = []
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    if (m[1] !== undefined) parts.push(<b key={parts.length}>{m[1]}</b>)
    else parts.push(<code key={parts.length}>{m[2]}</code>)
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function Section({ section }) {
  return (
    <div className="card card-pad">
      <div className="sub-h">{section.heading}</div>
      {section.body.map((para, i) => (
        <p key={i} style={{ margin: i === 0 ? '6px 0 0' : '9px 0 0', fontSize: 13.5, lineHeight: 1.55 }}>
          {inlineMarks(para)}
        </p>
      ))}
      {section.bullets.length > 0 && (
        <div className="nn-list">
          {section.bullets.map((b, i) => (
            <div className="nn-item" key={i}>
              {b.lead && <b className="nn-lead">{b.lead}</b>}
              {b.rest && <span className="nn-rest">{inlineMarks(b.rest)}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** @param {{data: any}} props */
export default function Constitution({ data }) {
  const a = data.anchor || {}
  const { title, sections } = parseAnchorProse(data.prose)

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Constitution</h2>
        {a.version != null && <Label kind="rung">v{a.version}</Label>}
        {a.mode && <Label kind="dial">{a.mode} mode</Label>}
        <span style={{ flex: 1 }} />
        <a className="btn btn-acc" href={`${import.meta.env.BASE_URL}anchor/console`} style={{ textDecoration: 'none' }}>Open console →</a>
      </div>
      <p className="note">
        {title ? <>{title} — read </> : 'Read '}
        verbatim from this instance's ANCHOR. Read-only here; every change is a PR through the
        console.
      </p>

      {sections.length === 0 ? (
        <div className="card card-pad">
          <p className="note" style={{ margin: 0 }}>
            The ANCHOR's prose is unavailable — <code>/snapshot</code> returned none, which happens
            offline or against fixtures. This screen will not stand in a constitution of its own:
            read <code>ANCHOR.md</code> directly.
          </p>
        </div>
      ) : (
        sections.map((s) => <Section key={s.heading} section={s} />)
      )}

      {data.goal && (
        <div className="card card-pad">
          <div className="sub-h">Resolved goal · what an expedition is judged against</div>
          <p style={{ margin: '6px 0 0', fontSize: 13.5, lineHeight: 1.55 }}>{data.goal}</p>
        </div>
      )}

      <div className="card">
        <div className="sect" style={{ borderTop: 0, display: 'flex' }}>
          <span style={{ flex: 1 }}>Vessels · the context packs grounding every expedition</span>
          <a href={`${import.meta.env.BASE_URL}anchor/vessels`}>manage →</a>
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

// Workbench · Inbox — the new home. "What needs me": every pending human decision, ranked
// most-urgent first (the carried-forward infoValue lens), each row carrying exactly the evidence
// to decide + the action INLINE. Named-actor once at the top (fail-closed, shared by every
// inline action — same protocol as Detail). Wall is demoted to #/wall.
import React, { useEffect, useMemo, useState } from 'react'
import { useWhoami } from '../whoami.js'
import { api } from '../api.js'
import { killExpedition, postFeedback, retryExpedition } from '../actions.js'
import { Artifacts, LadderBar, Label, Money, infoValue, needsYou } from '../ui.jsx'


/** Evidence chips: the reason, the dial, and a judge note where the record carries one. */
function Evidence({ e }) {
  const chips = []
  if (e.reason) chips.push(['why', e.reason])
  if (e.dial) chips.push(['dial', e.dial])
  if (e.judge_note || e.judge) chips.push(['judge', e.judge_note || e.judge])
  if (chips.length === 0) return null
  return (
    <div className="evi-row">
      {chips.map(([k, v]) => (
        <span className="evi" key={k}><span className="evi-k">{k}</span>{v}</span>
      ))}
    </div>
  )
}

/** await-pick — the exploration lines: small iframe grid (Detail's pattern) + Pick buttons. */
function PickInline({ e, who, toast, onOpen }) {
  const [names, setNames] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let on = true
    api.expedition(e.number)
      .then((d) => on && setNames(d?.artifacts?.wireframes || []))
      .catch(() => on && setNames([]))
    return () => { on = false }
  }, [e.number])

  const pick = async (i) => { setBusy(true); await postFeedback(e.number, `/pick ${i + 1}`, who, toast); setBusy(false) }

  if (names == null) return <p className="note" style={{ margin: '4px 0 0' }}>Loading the lines…</p>
  if (names.length === 0) {
    return (
      <div className="inline-act">
        <span className="why">Lines not reachable offline —</span>
        <button className="btn" onClick={() => onOpen(e.number)}>Open to pick →</button>
      </div>
    )
  }
  return (
    <div className="lines">
      {names.map((name, i) => (
        <div key={name} className="line">
          <iframe title={`expedition ${e.number} line ${i + 1}: ${name}`}
                  src={`${api.base}/wireframes/${e.number}/${name}`} sandbox=""
                  className="line-frame" />
          <div className="inline-act">
            <span className="why" style={{ flex: 1 }}>line {i + 1}</span>
            <button className="btn btn-pri" disabled={busy} onClick={() => pick(i)}>Pick the line #{i + 1}</button>
          </div>
        </div>
      ))}
    </div>
  )
}

/** One inbox row — evidence + the status-specific inline action. */
function InboxRow({ e, who, toast, onOpen, refresh }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const nid = `note-${e.number}`

  const post = async (text) => { setBusy(true); const ok = await postFeedback(e.number, text, who, toast, refresh); if (ok) setNote(''); setBusy(false) }
  const doKill = async () => { setBusy(true); await killExpedition(e.number, who, toast, refresh); setBusy(false) }
  const doRetry = async () => { setBusy(true); await retryExpedition(e.number, who, toast, refresh); setBusy(false) }

  return (
    <div className={`ibx ibx-${e.status}`}>
      <div className="ibx-head">
        <button className="ibx-open" onClick={() => onOpen(e.number)}
                aria-label={`open expedition ${e.number}: ${e.intent}`}>
          <span className="num">#{e.number}</span>
          <span className="ibx-int">{e.intent}</span>
        </button>
        <Label kind="rung">{e.rung}</Label>
        <Label kind={e.status}>{e.status}</Label>
        <LadderBar rung={e.rung} status={e.status} />
        <Artifacts a={e.artifacts} number={e.number} base={api.base} />
        <Money v={e.spent} />
      </div>
      <Evidence e={e} />

      {e.status === 'await-pick' && (
        <PickInline e={e} who={who} toast={toast} onOpen={onOpen} />
      )}

      {e.status === 'await-signoff' && (
        <div className="inline-act">
          <button className="btn btn-pri" disabled={busy} title="Posts /advance — the webhook flips the rung"
                  onClick={() => post('/advance')}>⬆ Advance</button>
          <button className="btn" disabled={busy}
                  title="Posts your note as a descend request on the issue thread"
                  onClick={() => post(note.trim() || 'requesting a descend — see thread for the reason')}>⬇ Descend</button>
          <label className="vh" htmlFor={nid}>Descend note for #{e.number}</label>
          <input id={nid} className="in" style={{ flex: 1, minWidth: 160 }} value={note}
                 placeholder="optional descend note" onChange={(ev) => setNote(ev.target.value)} />
          <button className="btn" onClick={() => onOpen(e.number)}>Open detail →</button>
        </div>
      )}

      {e.status === 'await-answer' && (
        <div className="inline-act inline-act-col">
          {/* The run asked which of two things the request meant. It is alive and cheap — it has
              spent one spec rung — and one sentence unblocks it. */}
          <span className="why">{e.reason || 'it asked which thing you meant'}</span>
          <label className="vh" htmlFor={nid}>Answer for #{e.number}</label>
          <textarea id={nid} className="in" rows={2} value={note} disabled={busy}
                    placeholder="a — or say it in your own words"
                    onChange={(ev) => setNote(ev.target.value)}
                    style={{ resize: 'vertical', fontFamily: 'inherit' }} />
          <div className="inline-act">
            <button className="btn btn-pri" disabled={busy || !note.trim()}
                    onClick={() => post(note)}>Send this answer</button>
            <button className="btn btn-danger" disabled={busy} onClick={doKill}>Kill</button>
            <span style={{ flex: 1 }} />
            <button className="btn" onClick={() => onOpen(e.number)}>Open detail →</button>
          </div>
        </div>
      )}

      {e.status === 'needs-human' && (
        <div className="inline-act inline-act-col">
          <label className="vh" htmlFor={nid}>Feedback for #{e.number}</label>
          <textarea id={nid} className="in" rows={2} value={note} disabled={busy}
                    placeholder="post context / a question / a decision onto the issue thread"
                    onChange={(ev) => setNote(ev.target.value)} style={{ resize: 'vertical', fontFamily: 'inherit' }} />
          <div className="inline-act">
            <button className="btn btn-acc" disabled={busy} onClick={() => post(note)}>Post feedback</button>
            <button className="btn btn-danger" disabled={busy} onClick={doKill}>Kill</button>
            <span style={{ flex: 1 }} />
            <button className="btn" onClick={() => onOpen(e.number)}>Open detail →</button>
          </div>
        </div>
      )}

      {e.status === 'descended' && (
        <div className="inline-act">
          <span className="why" style={{ flex: 1 }}>⛔ descended — lesson written; re-climb from detail</span>
          <button className="btn" onClick={() => onOpen(e.number)}>Open detail →</button>
        </div>
      )}

      {/* A run the WORKFLOW parked — a dead worker, a step past its limit, a crash. It reached no
          gate, so it appeared on no screen that asks "what needs me", while being the only thing
          on the instance that was actually broken. The reason is already above in Evidence; what
          was missing was the one button that does something about it. */}
      {e.status === 'parked' && e.parked_by === 'failure' && (
        <div className="inline-act">
          <span className="why" style={{ flex: 1 }}>⚠ it stopped on its own — nobody pressed anything</span>
          <button className="btn btn-pri" disabled={busy}
                  title="Runs the step that stopped it again, from where it stopped"
                  onClick={doRetry}>↻ Retry from where it stopped</button>
          <button className="btn" onClick={() => onOpen(e.number)}>Open detail →</button>
        </div>
      )}
    </div>
  )
}

/** @param {{data: any, onOpen: (n:number)=>void, toast: (s:string)=>void, reload: ()=>void}} props */
export default function Inbox({ data, onOpen, toast, reload }) {
  const { who, setWho, verified } = useWhoami()
  const [filter, setFilter] = useState('all')

  const needs = useMemo(() => {
    const xs = (data.expeditions || []).filter((e) => needsYou(e))
    const f = filter === 'all' ? xs : xs.filter((e) => e.status === filter)
    return [...f].sort((a, b) => infoValue(b) - infoValue(a))
  }, [data, filter])

  const count = (s) => (data.expeditions || []).filter((e) => e.status === s).length
  // Only the FAILURE parks: a run somebody stopped on purpose is not waiting for anybody, and
  // counting it here would put every killed expedition ever back on the "what needs me" screen.
  const failed = (data.expeditions || []).filter(needsYou).filter((e) => e.status === 'parked').length
  // Metered spend across the ledger. NOT "today" — the calibration report totals every decision
  // it has, with no day boundary — and NOT the cost of the work, because the subscription lane
  // meters nothing. The list-price equivalent is per-expedition (`normalized_usd`); there is no
  // instance-wide total of it to show, so this line does not pretend to have one.
  const metered = typeof data.totalCost === 'number' ? data.totalCost : null
  // Only shown if the harness actually supplies one. There is no daily cap in the engine today,
  // and inventing a default here put a "$2.00 cap" on screen that nothing enforced.
  const cap = typeof data.spendCap === 'number' ? data.spendCap : null
  const needsCount = (data.expeditions || []).filter((e) => needsYou(e)).length

  return (
    <div className="pane">
      <div className="list-head" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <h1>What needs you</h1>
        {[['all', `All ${(data.expeditions || []).filter((e) => needsYou(e)).length}`],
          ['await-pick', `Pick ${count('await-pick')}`],
          ['await-signoff', `Sign-off ${count('await-signoff')}`],
          ['needs-human', `Needs-human ${count('needs-human')}`],
          ['await-answer', `Answer ${count('await-answer')}`],
          ['descended', `Descended ${count('descended')}`],
          ['parked', `Stopped ${failed}`]].map(([k, label]) => (
          <button key={k} className={`chip${filter === k ? ' on' : ''}`} onClick={() => setFilter(k)}>{label}</button>
        ))}
        <span style={{ flex: 1 }} />
        <span className={`src-badge src-${data.source}`}>{data.source === 'live' ? 'live harness' : 'fixtures (offline)'}</span>
        <span
          className="wb-spend"
          title={metered ? 'metered API spend across the ledger' :
            'nothing metered: this instance runs on the subscription lane, so billed spend is $0. Per-expedition list-price equivalents are on each expedition.'}
        >
          {metered ? (
            <>Metered <b>${metered.toFixed(2)}</b></>
          ) : (
            <>Metered <b>$0.00</b> <span className="cap">(subscription lane)</span></>
          )}
          {cap !== null && <span className="cap"> (cap ${cap.toFixed(2)})</span>}
        </span>
        <span className="wb-sub">{needsCount} decision{needsCount === 1 ? '' : 's'} · evidence inline — act without leaving the row</span>
      </div>

      <div className="actor-bar">
        <label className="flab" htmlFor={verified ? undefined : 'ibx-actor'}
               style={{ margin: 0 }}>Acting as</label>
        {verified
          // A verified identity is a FACT, not a field. A read-only input still looks like
          // something you can edit, which invites editing a value the server ignores entirely.
          ? <span className="actor-fixed">{who}</span>
          : <input id="ibx-actor" className="in" style={{ width: 200 }} value={who}
                   onChange={(e) => setWho(e.target.value)}
                   placeholder="your name (required for every action)"
                   aria-label="Your name (required for every action)" />}
        <span className="why">{verified
          ? 'from your signed-in identity — this is what the ledger records'
          : 'every inline action posts through the one signed protocol — fail-closed without a name'}</span>
      </div>

      {needs.length === 0 && (
        <div className="card card-pad"><p className="note" style={{ margin: 0 }}>
          Nothing needs you right now. New picks, sign-offs, and needs-human verdicts land here first.
          The full wall is under <a href={`${import.meta.env.BASE_URL}wall`}>Workbench · Wall</a>.
        </p></div>
      )}

      {needs.map((e) => (
        <InboxRow key={e.number} e={e} who={who} toast={toast} onOpen={onOpen} refresh={reload} />
      ))}
    </div>
  )
}

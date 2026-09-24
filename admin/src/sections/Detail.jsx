// Expedition detail + the kill switch [P3.2 debt] + the human-in-the-loop surface:
// the issue-thread mirror, a feedback field, and command buttons. Feedback goes THROUGH
// the harness to GitHub as a comment — commands apply only when the signed webhook echoes
// them back (one protocol, no admin side door). Named-actor fail-closed, like the kill.
import React, { useEffect, useState } from 'react'
import { useWhoami } from '../whoami.js'
import { api } from '../api.js'
import { Artifacts, Label, LadderBar, Money, RUNGS, rungIdx } from '../ui.jsx'

/** @param {{number: number, data: any, onBack: ()=>void, toast: (s:string)=>void}} props */
/** How old a moment is, in the shortest true words. */
function ago(ts) {
  if (!ts) return ''
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

const CAUSE_WORDS = {
  crash: 'it died part-way through',
  refused: 'it ran, judged, and said no',
  timeout: 'it ran past the limit it is allowed',
  heartbeat: 'the machine running it stopped answering',
  stopped: 'it stopped before it finished',
}

const RUNG_STEP = ['intent', 'spec', 'wireframe', 'preview', 'build', 'ship']

/** Why this run stopped — the record the engine writes at the moment of failure. */
function Cause({ c }) {
  const [open, setOpen] = useState(false)
  const step = RUNG_STEP[c.rung] || `rung ${c.rung}`
  const tail = c.tail || []
  return (
    <div className="cause">
      <p style={{ margin: '10px 0 0' }}>
        <Label kind="parked">cause</Label>{' '}
        <b>{CAUSE_WORDS[c.kind] || c.kind}</b>{' '}
        <span className="why">
          at the <b>{step}</b> step{c.attempt > 1 ? `, on try ${c.attempt}` : ''}
          {c.error ? <> · <code>{c.error}</code></> : null}
        </span>
      </p>
      {c.message && <p className="note" style={{ margin: '4px 0 0' }}>{c.message}</p>}
      {tail.length > 0 && (
        <>
          <button className="btn" style={{ marginTop: 6 }} onClick={() => setOpen(!open)}
                  aria-expanded={open}>
            {open ? 'Hide' : 'Show'} the last {tail.length} line{tail.length === 1 ? '' : 's'} of <code>{c.artifact}</code>
          </button>
          {open && <pre className="cause-tail">{tail.join('\n')}</pre>}
        </>
      )}
      {tail.length === 0 && c.artifact === '' && (
        <p className="note" style={{ margin: '4px 0 0' }}>
          It left nothing behind — it stopped before it had written anything.
        </p>
      )}
    </div>
  )
}

/** The run itself — is it alive, what step is in flight, on which try, and what last went wrong.
 *
 *  This screen could say where a run WAS and never whether anything was still running it.
 *  Expedition 17 died mid-step and every surface in the system went on reporting "climbing" for
 *  twenty minutes, because a Temporal query answers from replayed history and answers perfectly
 *  well on a dead workflow. Every field below already existed in Temporal's own pending-activity
 *  record; nothing had ever asked for it.
 */
function Run({ live, number, onRetry, busy }) {
  const wf = live?.workflow
  const err = live?.orchestration_error
  const events = live?.events || []
  if (!wf && !err && events.length === 0) return null
  const h = wf?.run_health || {}
  const alive = wf?.running
  const stopped = wf && alive === false
  const cause = live?.cause
  const retry = live?.retry || {}

  return (
    <div className="card">
      <div className="sect" style={{ borderTop: 0, display: 'flex', alignItems: 'center' }}>
        <span style={{ flex: 1 }}>Run</span>
        {/* OFFER THE BUTTON ONLY WHERE IT WOULD WORK. It was drawn on every stopped run and its
            four refusals were discovered by pressing it — which teaches an operator that the
            button is unreliable rather than that THIS run cannot be retried. The engine answers
            the question up front now (`retry.allowed`), with the sentence it would refuse with. */}
        {stopped && (retry.allowed !== false
          ? (
            <button className="btn btn-primary" disabled={busy} onClick={onRetry}>
              Retry from where it stopped
            </button>
          )
          : <span className="why" title={retry.because}>No retry — {retry.because}</span>)}
      </div>
      <div className="card-pad">
        {/* Temporal being unreachable is REPORTED, never smoothed into "no run". A screen that
            cannot see the orchestrator must say so, or its silence reads as an answer. */}
        {err && <p className="err" style={{ margin: 0 }}>Cannot reach the orchestrator: {err}</p>}
        {wf && (
          <p style={{ margin: err ? '8px 0 0' : 0 }}>
            <Label kind={alive ? 'climbing' : 'parked'}>{alive ? 'running' : 'not running'}</Label>
            {' '}
            <span className="why">
              {alive
                ? (h.activity
                    ? <>step <code>{h.activity}</code> · try {h.attempt}{h.max_attempts ? ` of ${h.max_attempts}` : ''}
                        {h.last_heartbeat_at ? <> · last sign of life {ago(h.last_heartbeat_at)}</> : <> · no heartbeat yet</>}
                        {h.worker ? <> · {h.worker}</> : null}</>
                    : <>at a gate — nothing is running, it is waiting on a person</>)
                : <>this run has ended; the record says <b>{wf.state}</b></>}
            </span>
          </p>
        )}
        {h.next_attempt_at && (
          <p className="note" style={{ margin: '6px 0 0' }}>
            Next try is scheduled — the step is being re-run, not stuck.
          </p>
        )}
        {h.last_failure && (
          <p className="note" style={{ margin: '6px 0 0' }}>
            Last failure: <code>{h.last_failure}</code>
          </p>
        )}
        {/* WHY IT STOPPED, once, in the place the reader is already looking.
            This was spread across five surfaces — a 300-character event, a session transcript
            nobody linked to, journald, Temporal's last_failure and the vessel's test output — and
            four of them were reachable only by someone who already knew where to look. The record
            names the step, the try, the artifact it came from, and carries that artifact's tail. */}
        {cause && <Cause c={cause} />}
        {events.length > 0 && (
          <ul className="run-events">
            {events.slice(-12).reverse().map((ev, i) => (
              <li key={i}>
                <span className="k">{ev.kind}</span>
                <span className="w">
                  {ev.rung != null && <>rung {ev.rung} </>}
                  {ev.attempt > 1 && <>try {ev.attempt} </>}
                  {ev.took_s != null && <>· {ev.took_s}s </>}
                  {ev.state && <>· {ev.state} </>}
                  {ev.error && <>· {ev.error}: {ev.message} </>}
                  {ev.actor && <>· by {ev.actor} </>}
                </span>
                <span className="t">{ago(ev.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}


export default function Detail({ number, data, onBack, toast }) {
  const [live, setLive] = useState(null)
  const [thread, setThread] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const { who, setWho, verified } = useWhoami()
  const [fb, setFb] = useState('')
  const [busy, setBusy] = useState(false)
  const fallback = (data.expeditions || []).find((e) => e.number === number)

  const refresh = () => {
    api.expedition(number).then(setLive).catch(() => {})
    api.thread(number).then(setThread).catch(() => setThread({ available: false, reason: 'thread unavailable', comments: [] }))
  }

  useEffect(() => {
    let on = true
    api.expedition(number).then((d) => on && setLive(d)).catch(() => {})
    api.thread(number).then((t) => on && setThread(t))
      .catch(() => on && setThread({ available: false, reason: 'thread unavailable', comments: [] }))
    return () => { on = false }
  }, [number])

  const send = async (text) => {
    if (!who.trim()) { toast('Refused: feedback requires a named actor (fail-closed)'); return }
    if (!text.trim()) { toast('Nothing to send'); return }
    setBusy(true)
    try {
      const r = await api.feedback(number, { body: text.trim(), actor: who.trim() })
      // Say where it actually went. `via: temporal` means the run took it as a signal and the
      // rung moves on its own; the issue path needs the webhook round-trip first.
      toast(r.via === 'temporal'
        ? `${text.trim().split('\n')[0]} sent to the run`
        : r.command
          ? `${text.trim().split('\n')[0]} sent — the webhook round-trip applies it`
          : 'Feedback posted to the issue thread')
      setFb('')
      setTimeout(refresh, r.via === 'temporal' ? 1000 : 3000)
    } catch (ex) {
      // The harness says WHY it refused, in a sentence written to be read. This branch threw that
      // away and guessed — and guessed wrong for every refusal that was not about a missing issue
      // or a missing token, which by then was most of them.
      toast(`Refused: ${ex?.message || 'the harness would not accept that'}`)
    }
    setBusy(false)
  }

  const e = live || fallback
  if (!e) return <div className="pane"><h2>No expedition #{number}</h2></div>
  const cur = rungIdx(e.rung)
  // `wireframe`, singular — the key the workflow actually publishes, and the key the demo
  // surface has always read. This screen read `wireframes`, so the card never rendered, and with
  // it the ONLY pick control the operator console has. That is why a run parked at a pick gate
  // offered Advance and nothing else: the one button that would have moved it was behind a
  // key that is never present.
  // TWO artifact bags, and this screen only ever read one. `/expeditions/{n}` returns the
  // STORE's artifacts (files a local builder wrote) under `artifacts`, and the durable run's
  // under `workflow.artifacts` — where the Figma rung-2 builder puts its candidates. The demo
  // view has always merged them; this one did not, so on a Figma instance the card had nothing
  // to render and the operator console had no pick control at all.
  const artifacts = { ...(live?.artifacts || {}), ...(live?.workflow?.artifacts || {}) }
  // `wireframe` is the key both builders publish; `wireframes` is kept for older stored runs.
  // Entries are objects from the Figma builder and plain filenames from the reference HTML one,
  // so normalise to one shape rather than branching at every use.
  const wireframes = (artifacts.wireframe || artifacts.wireframes || []).map((c, i) =>
    typeof c === 'string'
      ? { name: c, title: c, premise: '', file: c }
      : { name: c.name, title: c.title || c.name || `Candidate ${i + 1}`, premise: c.premise || '', url: c.url })
  // The same FACTS the Wall row shows, derived here from the full bag this screen already has.
  // Detail is the one place that can afford the rich read; the Wall gets them persisted.
  // MUST come after `wireframes`: it reads it, and a const is in its temporal dead zone until
  // declared. Placing this above shipped a `Cannot access before initialization` that took out
  // the whole app, not just this screen — the build does not catch it and only loading the page
  // does.
  const ship = artifacts.ship || {}
  const artifactFacts = {
    frames: wireframes.length ? { count: wireframes.length, url: wireframes.find((c) => c.url)?.url } : null,
    // FACTS ONLY. This read `|| rungIdx(e.rung) >= 3`, which is the very rung-inference the
    // Wall's chips were retired for — and it produced a "preview" link on expedition #2, which
    // has no prototype: /preview/2 answers 404. A claim is a claim wherever it is written.
    preview: !!(artifacts.prototype || artifacts.demo),
    build: artifacts.build ? {
      files: (artifacts.build.files_changed || []).length || artifacts.build.files,
      lines: artifacts.build.lines_changed,
    } : null,
    pull_request: ship.pr_url || null,
  }
  // What the run is waiting for, from the run. `approve` at a pick gate is absorbed by a wait
  // condition that does not read it, so offering Advance here is offering a control that cannot
  // work — the engine now refuses it, and the screen should not have asked in the first place.
  // ONE source for what the run is waiting for, and it is the run.
  //
  // The screen decided from the stored status while the engine decides from the workflow's own
  // state, and the two drift — the store is written by a mirror that lags every transition. That
  // disagreement is the whole shape of this session's bugs: a screen offering a control the run
  // cannot use, or hiding one it can. Where a workflow exists it is the authority; the stored
  // status is the fallback for runs that have none.
  const runState = live?.workflow?.state || e.status
  // The run reads `picked` only at a pick gate and `approved` only at an approve gate. Offering
  // either anywhere else is a false affordance — the engine refuses it (422), and the screen
  // should not have asked. `needs-human` is deliberately absent: at rung 0 it means the run never
  // started, and there is nothing to approve into.
  const needsPick = runState === 'await-pick'
  const canApprove = ['await-approve', 'await-signoff'].includes(runState)
  // `await-approve` was missing here, so at a rung-3 gate — the most common gate in the whole
  // ladder — the screen never said it was waiting on anybody.
  const needsYou = ['needs-human', 'await-signoff', 'await-approve', 'await-pick', 'descended',
    'await-answer'].includes(runState)
  // Where a decision on this expedition would actually land, straight from the engine (see
  // /expeditions/{n}/thread). Only an explicit 'none' disables the controls: a thread request
  // that failed in transit is not evidence that there is nowhere to post, and treating it as
  // such would swap a screen that lies for a screen that gives up.
  const route = thread?.route
  const dead = route === 'none'

  const retry = async () => {
    if (!who.trim()) { toast('Refused: a retry requires a named actor (fail-closed)'); return }
    setBusy(true)
    try {
      const r = await api.retry(number, { actor: who.trim() })
      toast(`#${number} picked up again from where it stopped (run ${String(r.run_id).slice(0, 8)})`)
    } catch (ex) {
      // The engine's refusal names which rule it hit — still running, no run, past the ceiling,
      // already finished. Showing it verbatim is the point: an operator acting on a stuck run
      // needs to know WHICH of those it is, and a generic failure teaches nothing.
      toast(`Retry refused: ${String(ex.message || ex)}`)
    } finally { setBusy(false) }
  }

  const kill = async () => {
    if (!who.trim()) { toast('Refused: the kill switch requires a named actor (fail-closed)'); return }
    try {
      await api.kill(number, { actor: who.trim(), reason: 'killed from admin' })
      toast(`#${number} parked by ${who.trim()} — recorded in the ledger`)
    } catch {
      toast(`Kill request failed against the live harness — nothing changed`)
    }
    setConfirm(false)
  }

  return (
    <div className="pane">
      <div className="detail-head">
        <button className="btn" onClick={onBack}>← Back</button>
        <h2 style={{ margin: 0 }}>#{e.number} · {e.intent}</h2>
        <Label kind="rung">{e.rung}</Label>
        <Label kind={e.status}>{e.status}</Label>
        <Artifacts a={artifactFacts} number={e.number} base={api.base} />
        <Money v={e.spent} equiv={e.normalized_usd} />
        <span style={{ flex: 1 }} />
        <button className="btn btn-danger" onClick={() => setConfirm(true)}>Kill switch</button>
      </div>

      <Run live={live} number={e.number} onRetry={retry} busy={busy} />

      <div className="card">
        <div className="sect" style={{ borderTop: 0 }}>Climb timeline</div>
        <ul className="timeline">
          {RUNGS.map((r, i) => (
            <li key={r}>
              <span className="num" style={{ width: 90 }}>{r}</span>
              <span style={{ flex: 1 }}>
                {i < cur && '✓ climbed'}
                {i === cur && (e.status === 'descended' ? '⛔ descended here — lesson written' : `● current — ${e.status}`)}
                {i > cur && (i <= rungIdx(e.target) ? 'target lane' : '—')}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="card card-pad">
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          <LadderBar rung={e.rung} status={e.status} />
          {/* `target` is the funnel's lane, set at admission. Once the run has climbed PAST it the
              word "target" reads as a destination it has not reached, which is backwards — #12
              showed "target: 2-wireframe" while sitting at 3-demo. Say it only while it is still
              ahead. */}
          <span className="why">
            {rungIdx(e.rung) < rungIdx(e.target) && <>target: {e.target} · </>}
            dial: {e.dial} · {e.reason || 'no notes'}
          </span>
          {/* The SAME false claim, a second time: a run reaching rung 3 does not mean rung 3
              produced anything. #2 is at 5-flagged and /preview/2 answers 404. The artifact
              strip above already links the preview when one exists, so this duplicate goes
              rather than being taught the same lesson twice. */}
        </div>
      </div>

      {wireframes.length > 0 && (
        <div className="card">
          <div className="sect" style={{ borderTop: 0 }}>
            Wireframes · pick-of-{wireframes.length}
            {needsPick
              ? <> · <b>this run is waiting on one of these</b></>
              : <> · the choice was made here</>}
          </div>
          <div style={{ display: 'flex', gap: 12, padding: 12, flexWrap: 'wrap' }}>
            {/* Each entry is an OBJECT the rung-2 builder wrote — name, title, premise, and a
                link to the frame it drew. The old code mapped it as a filename string into a
                local iframe, which is the shape the reference HTML builder produces, not the
                Figma one this instance runs. A candidate is chosen on its premise; render that
                rather than an iframe that cannot load. */}
            {wireframes.map((c, i) => (
              <div key={c.name || i} style={{ flex: '1 1 260px', minWidth: 260, display: 'flex',
                                              flexDirection: 'column', gap: 6 }}>
                <div className="sub-h">{c.title || c.name}</div>
                {c.premise && <p className="note" style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{c.premise}</p>}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto' }}>
                  {c.url
                    ? <a className="why" href={c.url} target="_blank" rel="noreferrer" style={{ flex: 1 }}>open the frame ↗</a>
                    : c.file
                      ? <a className="why" href={`${api.base}/wireframes/${e.number}/${c.file}`}
                           target="_blank" rel="noreferrer" style={{ flex: 1 }}>open the wireframe ↗</a>
                      : <span className="why" style={{ flex: 1 }}>{c.name}</span>}
                  {needsPick && (
                    <button className="btn btn-primary" disabled={busy || dead}
                            onClick={() => send(`/pick ${i + 1}`)}>
                      Pick this
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div className="sect" style={{ borderTop: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ flex: 1 }}>
            Issue thread
            {thread?.available && thread.url && (
              <> · <a href={thread.url} target="_blank" rel="noreferrer">view on GitHub ↗</a></>
            )}
          </span>
        </div>
        {needsYou && route === 'issue' && (
          <p className="note" style={{ margin: '8px 12px 0' }}>
            ⏳ The gate parked this for a human — your feedback below goes onto the issue;
            commands take effect through the same signed webhook as everything else.
          </p>
        )}
        {needsYou && route === 'workflow' && (
          <p className="note" style={{ margin: '8px 12px 0' }}>
            ⏳ The gate parked this for a human — this expedition has no GitHub issue, so your
            decision goes straight to the run it belongs to.
          </p>
        )}
        {route === 'none' && (
          <p className="note" style={{ margin: '8px 12px 0' }}>
            🚫 Nothing can accept a decision on this expedition: it has no GitHub issue and no
            running workflow. The controls below are switched off rather than drawn live — this
            screen used to offer them anyway, and they failed silently. Use the kill switch to
            close it out.
          </p>
        )}
        {thread == null && <p className="note" style={{ margin: 12 }}>Loading thread…</p>}
        {thread && !thread.available && (
          <p className="note" style={{ margin: 12 }}>Thread unavailable: {thread.reason}</p>
        )}
        {thread?.available && (
          <ul style={{ listStyle: 'none', margin: 0, padding: '4px 12px 8px' }}>
            {thread.comments.length === 0 && <li className="note">No comments yet.</li>}
            {thread.comments.map((c, i) => (
              <li key={i} style={{ padding: '8px 0', borderTop: i ? '1px solid var(--color-border-muted, #eee)' : 'none' }}>
                <div className="why">@{c.author} · {(c.at || '').slice(0, 16).replace('T', ' ')}</div>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, marginTop: 2 }}>{c.body}</div>
              </li>
            ))}
          </ul>
        )}
        <div style={{ padding: 12, borderTop: '1px solid var(--color-border-muted, #eee)' }}>
          {/* An UNKNOWN route is not "nowhere". The thread request is still in flight on first
              paint, so a bare else-branch made every load flash "nowhere to send it" over a
              perfectly live run — the same class of lie this label was written to remove, just
              with the loading state as its cause. */}
          <label className="flab" htmlFor="fb-body">{
            route === 'issue' ? 'Feedback (posts to the issue as a comment)'
              : route === 'workflow' ? 'Feedback (goes to the run as a signal)'
                : route === 'none' ? 'Feedback (nowhere to send it — see above)'
                  : 'Feedback'
          }</label>
          <textarea id="fb-body" className="in" rows={3} value={fb} disabled={busy || dead}
                    placeholder="e.g. clarified success criteria, a question, or context for the next rung"
                    onChange={(ev) => setFb(ev.target.value)}
                    style={{ width: '100%', resize: 'vertical', fontFamily: 'inherit' }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* A verified identity is a fact, not a field. This input stayed editable while
                `setWho` was a no-op — it accepted typing and silently discarded it. The Inbox
                actor bar and the kill modal already render the fixed value; this row did not. */}
            {verified
              ? <span className="actor-fixed">{who}</span>
              : <input className="in" value={who} onChange={(ev) => setWho(ev.target.value)}
                       placeholder="your name (required)" aria-label="Your name"
                       style={{ width: 180 }} />}
            <button className="btn" disabled={busy || dead} onClick={() => send(fb)}>Post feedback</button>
            <span style={{ flex: 1 }} />
            {canApprove && (
              <button className="btn btn-primary" disabled={busy || dead} title={dead ? 'No issue and no workflow — nothing would receive this' : 'Approves this rung with no revisions'}
                      onClick={() => send('/advance')}>⬆ Advance</button>
            )}
            {needsPick && (
              <span className="why">Pick a candidate above to move this on.</span>
            )}
            {/* Approve prod is the same `/approve` under a different label, so it is the same
                false affordance at a pick gate — the run's wait condition does not read it and
                the engine refuses it. Both go, together, or the screen still offers one button
                that cannot work. */}
            {runState === 'await-signoff' && (
              <button className="btn" disabled={busy || dead} title={dead ? 'No issue and no workflow — nothing would receive this' : 'Posts /approve — the named prod gate'}
                      onClick={() => send('/approve')}>🚀 Approve prod</button>
            )}
            {/* "Working" was the fallback for every state that was not a gate, so a PARKED run —
                dead, going nowhere — was described as working. #14 sat at "3-demo parked · the
                page has no <h1>" under the words "This run is working". Say which of the three
                it actually is. */}
            {!needsPick && !canApprove && !dead && (
              <span className="why">{
                ['parked', 'killed'].includes(runState)
                  ? 'This run stopped and will not go further. Nothing is waiting to be decided.'
                  : ['done', 'docked'].includes(runState)
                    ? 'This run finished. Nothing is waiting to be decided.'
                    : 'This run is working — nothing is waiting to be decided.'
              }</span>
            )}
          </div>
        </div>
      </div>

      {confirm && (
        <div className="overlay" role="dialog" aria-modal="true" aria-label="Kill switch confirm">
          <div className="modal">
            <div className="m-head">Kill expedition #{e.number}?</div>
            <div className="m-body">
              <p style={{ marginTop: 0 }}>Parks the expedition (no further spend). Reversible by a re-climb;
                the kill lands in the ledger with your name.</p>
              <label className="flab" htmlFor={verified ? undefined : 'kill-actor'}>{verified
                ? 'Acting as'
                : 'Your name (required — the gate is non-bypassable)'}</label>
              {verified && <span className="actor-fixed">{who}</span>}
              <input id="kill-actor" className="in" value={who} hidden={verified}
                     onChange={(ev) => setWho(ev.target.value)}
                     placeholder="github handle" />
            </div>
            <div className="m-foot">
              <button className="btn" onClick={() => setConfirm(false)}>Cancel</button>
              <button className="btn btn-danger" onClick={kill}>Park it</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

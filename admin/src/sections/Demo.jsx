// The demo surface: the ladder as someone outside the team sees it.
//
// Two rules, and the whole file is in service of them.
//
// 1. Never surface the machinery. No rung numbers, no dials, no verifier names. The server does
//    that translation (`fls/demo.py`) and hands back words; this view renders what it is given and
//    invents no vocabulary of its own. If a ladder term appears on screen, the bug is upstream.
// 2. Exactly three actions, ever: say yes, ask for changes, or stop it. A visitor who has to
//    choose between seven controls is being asked to operate the thing rather than judge it.
//
// It polls rather than streams: a rung takes minutes, a demo lasts one sitting, and a websocket
// would be more machinery than the surface is worth.
import React, { useCallback, useEffect, useRef, useState } from 'react'
import SignInShell from '../SignInShell.jsx'

const BASE = import.meta.env.VITE_FLS_API || '/api'

// Shown only before the first payload arrives, so the ladder is never a blank column. The server
// is the source of these names everywhere else.
// Shown only before the first payload arrives and when no run is on screen, so the ladder is
// never a blank column. It went stale the moment the stages were renamed to actions — the empty
// state read "Requested · Wireframed · …" in past tense while a live run read "Request ·
// Wireframe · …", which is the cost of a second copy of anything the server owns. Kept because a
// blank spine is worse, and pinned by a test so the two cannot drift again.
const STAGE_FALLBACK = ['Request', 'Wireframe', 'Preview', 'Build', 'Ship']
const NOTE_FALLBACK = [
  'Your words, checked against what this product is for',
  'Three rough shapes — you pick one',
  'A clickable version of your pick',
  'Real code, running where you can try it',
  'Merged into the project, still switched off',
]

// What the turn IS, per stage — an instruction, where `status` is a state. "Waiting for your
// approval" tells a visitor the machine's condition; "Is this the right thing?" tells them what
// to do, which is the thing a gate is for.
const TURN_TITLE = [
  'This one needs a little more to go on.',
  'Pick the one you want built.',
  'Is this the right thing?',
  'The code is written.',
  // Ship merges now, so this gate is asking to put the change IN the project — not to bless a
  // package that already exists. "It is packaged and staged" described the old last step and
  // made the final yes sound like a formality, which is the one thing it is not.
  'Ready to go in?',
]
// What to say while a step is RUNNING. The mirror of TURN_TITLE: that one is what the visitor
// must do at a gate, this one is why they have nothing to do yet — and what they will be asked
// for next, so waiting has a shape. Indexed by stage, never by rung.
const WAIT_LINE = [
  'Nothing needs you while your words are checked.',
  'Nothing needs you until the shapes are drawn — then you pick one.',
  'Nothing needs you until the preview is ready — then you say yes or ask for changes.',
  'Nothing needs you until the code is written.',
  'Nothing needs you until it is packaged.',
]
const KEY = 'fls-demo-session'
// Finished runs this browser has closed. A view preference, never a fact about the expedition.
const CLOSED = 'fls-demo-closed'

async function call(path, { method = 'GET', body, token } = {}) {
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers: { ...(body ? { 'content-type': 'application/json' } : {}),
      ...(token ? { 'x-demo-token': token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const text = await r.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = null }
  if (!r.ok) throw new Error(data?.detail || `${r.status}`)
  return data
}

/** The stored session, or null when it has expired.
 *
 *  The token is `name:exp:signature` and lives 12 hours. This used to hand back whatever was in
 *  sessionStorage without looking at it, so an expired credential still counted as a session:
 *  the header said "Signed in as founder", the page rendered (GET /demo/active is a PUBLIC
 *  surface and needs no token at all), and the first action answered 401 "sign in first" with no
 *  way back but clearing storage by hand.
 *
 *  Reading `exp` is NOT verifying the token — only the server can do that, and it still does.
 *  This just stops the screen claiming a signed-in state that has plainly lapsed.
 */
function loadSession() {
  try {
    const s = JSON.parse(sessionStorage.getItem(KEY) || 'null')
    if (!s?.token) return null
    const exp = Number(s.token.split(':').at(-2))
    if (Number.isFinite(exp) && exp * 1000 < Date.now()) { sessionStorage.removeItem(KEY); return null }
    return s
  } catch { return null }
}

/** The ladder: the five rungs, as the page's spine.
 *
 *  Not a progress bar and not a row of dots. The ladder IS the product — five discrete steps, one
 *  way, a person at every gate — so it is the layout rather than an ornament on top of one. Each
 *  rung says what it PRODUCES, because five bare words tell a visitor arriving cold nothing about
 *  what any of them will hand back; those words come from the server with the rest of the visitor
 *  vocabulary, never from here.
 *
 *  A finished rung carries a check: a different SHAPE, which is what does the work. Ink for
 *  resolved, blue for running, yellow for waiting on you, red for stopped — the ANCHOR's own rung
 *  colours, and never the only signal.
 */
function Ladder({ stages, notes, at, waiting, halted }) {
  return (
    <nav className="dm-ladder" aria-label="Progress">
      <p className="dm-lhd">FIVE STEPS</p>
      <ol>
      {stages.map((s, i) => {
        const done = i < at
        const here = i === at
        const cls = done ? 'done' : here && halted ? 'halt' : here && waiting ? 'you' : here ? 'at' : ''
        return (
          <li key={s} className={`rung ${cls}`} aria-current={here ? 'step' : undefined}>
            <span className="pip" aria-hidden="true" />
            <span className="nm">{s}</span>
            {done && <span className="sr-only"> — done</span>}
            <span className="mk">{notes?.[i] || ''}</span>
            {here && waiting && <span className="turn">YOUR TURN</span>}
          </li>
        )
      })}
      </ol>
    </nav>
  )
}

/** The ink band. Enough brand to pass a blurry glance and nothing an operator would need: this is
 *  a public page, so it gets no nav, no counts and no account menu. */
function Band({ who, onOut }) {
  return (
    <header className="dm-top">
      <img src={`${import.meta.env.BASE_URL}brand/mark-full.svg`} width="30" height="30" alt="" />
      <span className="dm-wm">FIDELITY<br />LADDER</span>
      <span className="dm-tag">Ask for a change to a real app. Watch it get built.</span>
      {who && <span className="dm-who">{who}</span>}
      {/* The same Phosphor "sign-out" the workbench rail uses, so the two surfaces do not have
          two different ideas of what leaving looks like. Signing out here clears a demo pass and
          nothing else: the run carries on, because it belongs to the expedition and not to the
          browser that started it. */}
      {onOut && (
        <button type="button" className="dm-out" onClick={onOut}
                title="Sign out" aria-label="Sign out">
          <svg width="15" height="15" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">
            <path d="M120,216a8,8,0,0,1-8,8H48a8,8,0,0,1-8-8V40a8,8,0,0,1,8-8h64a8,8,0,0,1,0,16H56V208h56A8,8,0,0,1,120,216Zm109.66-93.66-40-40a8,8,0,0,0-11.32,11.32L204.69,120H112a8,8,0,0,0,0,16h92.69l-26.35,26.34a8,8,0,0,0,11.32,11.32l40-40A8,8,0,0,0,229.66,122.34Z"/>
          </svg>
        </button>
      )}
    </header>
  )
}

function SignIn({ onDone, expired = false }) {
  const [name, setName] = useState('')
  const [passcode, setPasscode] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      const s = await call('/v1/visitor/login', { method: 'POST', body: { name, passcode } })
      sessionStorage.setItem(KEY, JSON.stringify(s))
      onDone(s)
    } catch (ex) {
      // This used to call setSession and setActErr, neither of which exists in this component —
      // so the one path it was written for (a credential refused) threw a ReferenceError instead
      // of showing the reason. The stale session is cleared here, where it is in scope.
      sessionStorage.removeItem(KEY)
      setErr(String(ex.message || ex))
    } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit}>
      <SignInShell
        title="Watch it build something"
        blurb="Anyone can read what happened here. Starting a build spends real money, so that part asks who you are."
        notice={expired && (
          <p className="si-warn" role="status">
            <b>That sign-in has run out.</b> It lasts twelve hours. Nothing you did was lost — the
            run kept going without you.
          </p>
        )}
        foot="No account, no email, nothing kept. The pass lasts twelve hours."
        other={<>An operator? <a href="/workbench/">Sign in to the workbench</a> instead.</>}
      >
        <div className="si-f">
          <label className="dm-lab" htmlFor="d-name">YOUR NAME</label>
          <input id="d-name" className="dm-fld" value={name} placeholder="so the record says who asked"
                 onChange={(e) => setName(e.target.value)} autoComplete="name" required />
        </div>
        <div className="si-f">
          <label className="dm-lab" htmlFor="d-pass">PASSCODE</label>
          {/* autoComplete off on purpose: this is a SHARED passcode, not the visitor's own
              credential, and a password manager filling a saved one over it produces a "that
              passcode is not right" they cannot explain. */}
          <input id="d-pass" className={err ? 'dm-fld bad' : 'dm-fld'} type="password"
                 value={passcode} autoComplete="off"
                 onChange={(e) => setPasscode(e.target.value.trim())} required />
          {err && <p className="si-bad" role="alert">{err}</p>}
        </div>
        <div style={{ marginTop: 18 }}>
          <button className="dm-b pri si-full" disabled={busy || !name || !passcode}>
            {busy ? 'Signing in…' : 'Start watching'}
          </button>
        </div>
      </SignInShell>
    </form>
  )
}

/** Stopping, asked where the thing being stopped is.
 *
 *  The one act on this surface that cannot be undone, so it asks — and the asking is where the
 *  money is said, because the spend so far is the number a person actually wants before deciding.
 *  Factored out because the question is now asked in two places (in the live card's footer while
 *  a step runs, and in the action card at a gate) and a confirmation that words itself differently
 *  depending on where it is drawn is two promises, not one.
 *
 *  Red lands HERE and nowhere else: in the row above, Stop is a quiet tertiary control, because a
 *  quiet exit that is easy to find beats a loud one that is easy to hit. At the confirmation,
 *  stopping IS the primary action of the moment, and it gets the colour.
 */
function StopConfirm({ spend, busy, onYes, onNo }) {
  return (
    <>
      <p className="dm-stop-q">Stop this run?</p>
      <p className="dm-hint" style={{ marginTop: 0 }}>
        {spend > 0
          ? `It has spent $${spend.toFixed(2)} so far. That is spent either way — stopping keeps it from spending more.`
          : 'It has not spent anything yet.'}
        {' '}The step already running finishes first; nothing starts after it. What has been built
        so far stays, and this cannot be undone.
      </p>
      <div className="dm-brow" style={{ marginTop: 12 }}>
        <button className="dm-b warn" disabled={busy} onClick={onYes}>Yes, stop it</button>
        <button className="dm-b sec" disabled={busy} onClick={onNo}>Keep going</button>
      </div>
    </>
  )
}

/** Seconds as m:ss.
 *
 *  One format, because the live card now says two times in one breath — how long this step has
 *  been running and the limit it stops at — and "1m 05s so far, stops at 10 MIN" makes the reader
 *  do the conversion before they can compare them.
 */
function clock(sec) {
  const s = Math.max(0, Math.round(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

const MAX_ATTACH = 4 * 1024 * 1024
// The gate can READ these; everything else it can only be shown to a person. The surface says
// which, because "the details are in the attached file" works for a .md and does not for a .png.
const GATE_READS = ['text/plain', 'text/markdown', 'text/csv', 'application/json']

function RequestBox({ token, onFiled, suggestion }) {
  const [intent, setIntent] = useState('')
  const [success, setSuccess] = useState('')
  const [file, setFile] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const pick = (f) => {
    setErr('')
    if (!f) { setFile(null); return }
    // Checked here so the visitor hears about it before a 4MB upload, and again on the server
    // because a client-side limit is a courtesy, not a control.
    if (f.size > MAX_ATTACH) { setErr(`That file is ${Math.ceil(f.size / 1048576)}MB; the limit is 4MB.`); return }
    setFile(f)
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setErr('')
    try {
      let attachment = null
      if (file) {
        const buf = await file.arrayBuffer()
        let bin = ''
        const bytes = new Uint8Array(buf)
        for (let i = 0; i < bytes.length; i += 8192) {
          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192))
        }
        attachment = { name: file.name, type: file.type, data: btoa(bin) }
      }
      await call('/v1/visitor/requests', { method: 'POST', token, body: { intent, success, attachment } })
      setIntent(''); setSuccess(''); setFile(null); onFiled()
    } catch (ex) { setErr(String(ex.message || ex)) } finally { setBusy(false) }
  }

  const over = intent.length > 2000

  return (
    <form className="dm-card lead" onSubmit={submit}>
      <div className="dm-hd ask"><h2>What would you like built?</h2></div>
      <div className="dm-pad">
        <p className="dm-note" style={{ margin: '0 0 14px' }}>
          One request at a time, so you can watch the whole thing happen. It will draw some options
          first and ask you to choose.
        </p>

        {/* SOMETHING TO TRY. A visitor is being asked to invent a change to an app they have
            never used, which is a real ask — so one request is always on offer, and one tap puts
            it in the boxes where it stays editable. It hides the moment they start writing their
            own, and comes back if they clear it. Nothing is pre-filled: taking the suggestion is
            a choice, not a default they have to undo. */}
        {suggestion && !intent.trim() && !success.trim() && (
          <div className="dm-try">
            <p className="dm-lab" style={{ margin: '0 0 6px' }}>TRY THIS ONE</p>
            <p className="dm-p" style={{ margin: '0 0 6px' }}>{suggestion.intent}</p>
            {suggestion.success && (
              <p className="dm-note" style={{ margin: '0 0 10px' }}>{suggestion.success}</p>
            )}
            <button type="button" className="dm-b sec"
                    onClick={() => { setIntent(suggestion.intent); setSuccess(suggestion.success || '') }}>
              Use this idea
            </button>
          </div>
        )}

        {/* Textareas, not inputs. A single-line field tells you to write a few words, and the
            gate then holds the request for being too thin to place — the box was asking for less
            than the thing judging it needs. Room to write is the cheapest fix for that. */}
        <div className="dm-labrow">
          <label className="dm-lab" htmlFor="d-intent">THE CHANGE</label>
          {intent.length > 1200 && (
            <span className={over ? 'dm-count over' : 'dm-count'}>{intent.length} / 2000</span>
          )}
        </div>
        <textarea id="d-intent" className="dm-fld" rows={4} value={intent}
                  onChange={(e) => setIntent(e.target.value)}
                  placeholder="add a way to share the hand you just played" required />
        <p className="dm-hint">Say what you want different and where. A sentence or two beats a few
          words — a request too thin to place gets held at the door.</p>

        <label className="dm-lab" htmlFor="d-success" style={{ marginTop: 16 }}>
          HOW YOU WOULD KNOW IT WORKED <span style={{ fontWeight: 400, letterSpacing: 0 }}>(optional)</span>
        </label>
        <textarea id="d-success" className="dm-fld" rows={2} value={success}
                  onChange={(e) => setSuccess(e.target.value)}
                  placeholder="a player can send the result to a friend without leaving the table" />

        {/* ATTACHMENT — its own section, because it is optional and most requests will not have
            one. What happens to it depends on what it is, and the surface says so rather than
            leaving the visitor to assume the machine read their screenshot. */}
        <label className="dm-lab" htmlFor="d-file" style={{ marginTop: 16 }}>
          ATTACH A FILE <span style={{ fontWeight: 400, letterSpacing: 0 }}>(optional)</span>
        </label>
        <div className="dm-file">
          <input id="d-file" type="file" onChange={(e) => pick(e.target.files?.[0] || null)}
                 accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.md,.csv,.json" />
          {file
            ? <>
                <span className="nm">{file.name}</span>
                <span className="sz">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                <button type="button" className="lnk" onClick={() => pick(null)}>remove</button>
              </>
            : <span className="sz">One file, up to 4MB · image, PDF or text</span>}
        </div>
        {file && (
          <p className="dm-hint">
            {GATE_READS.includes(file.type)
              ? 'Text, so the gate reads it along with your request.'
              : 'Kept with the request for people to look at — the gate reads your words, not the file.'}
          </p>
        )}

        {err && <p className="dm-err" role="alert">{err}</p>}
        <div className="dm-brow" style={{ marginTop: 18 }}>
          <button className="dm-b pri" disabled={busy || !intent.trim() || over}>
            {busy ? 'Starting…' : 'Start'}
          </button>
          {!busy && !intent.trim() && (
            <span className="dm-hint" style={{ margin: 0 }}>Nothing runs until you press this.</span>
          )}
        </div>
      </div>
    </form>
  )
}

/** What the visitor asked to be changed, and where.
 *
 *  The one thing a visitor contributes besides the pick used to vanish the moment they sent it:
 *  the box emptied, the step re-ran, and nothing said the request had been heard. Numbered,
 *  because revisions are a sequence and the order is the story.
 */
function Revisions({ items }) {
  if (!items || items.length === 0) return null
  return (
    <div className="dm-card">
      <div className="dm-hd">
        <h2>What you asked to change</h2>
        <span className="dm-chip done">{items.length}</span>
      </div>
      <ol className="dm-revs">
        {items.map((r, i) => (
          <li className="dm-rev" key={i}>
            <span className="i" aria-hidden="true" />
            <span className="at">{r.stage || '—'}</span>
            <span className="said">{r.asked}</span>
          </li>
        ))}
      </ol>
      <p className="dm-note" style={{ padding: '11px 18px', background: '#f3f0e6',
                                      borderTop: '1px solid #ece7db', margin: 0 }}>
        Each one sent the step back to be done again — that is what asking for a change does here.
      </p>
    </div>
  )
}

/** A note ON the artifact that was remade because of something the visitor asked for.
 *
 *  A separate list is not enough: the preview you are looking at after a change IS a different
 *  preview, and its card said nothing at all. Amber, not a success colour — this is not a result,
 *  it is a fact about the thing above it.
 */
function Revised({ items, at }) {
  // Matched on the stage INDEX, not its name. These used to be string literals —
  // stage="Wireframed" — so renaming a stage would have silently stopped every one of these
  // notes appearing, with nothing failing to say so.
  const mine = (items || []).filter((r) => r.at === at)
  if (mine.length === 0) return null
  return (
    <p className="dm-remade">
      <b>Remade after {mine.length === 1 ? 'a change' : `${mine.length} changes`} you asked for.</b>{' '}
      {mine.map((r) => r.asked).join(' · ')}
    </p>
  )
}

/** The builder writes its summary in markdown, and this page renders text.
 *
 *  Shown raw it arrives as `**What I built**` and backticked paths — the literal punctuation, on
 *  the one surface whose whole job is to be readable by someone with no context. Rendering the
 *  markdown properly would mean parsing builder output into HTML on a visitor's page, which is a
 *  much larger surface than the problem is worth. Dropping the two marks that carry no meaning in
 *  plain text is the small honest fix: the words are untouched.
 */
function plain(text) {
  return String(text || '').replace(/\*\*/g, '').replace(/`/g, '')
}

/** What there is to look at, at whatever stage it has reached. */
// How many shapes came back, said out loud rather than assumed.
//
// Rung 2 is ASKED for three and is allowed to return fewer, but only if it says why — the builder
// contract refuses a short list with no `fewer_because` rather than let it quietly under-deliver.
// This page assumed three anyway: the heading read "Three ways it could work" over a single card,
// the note told the visitor to pick between shapes that were not there, and the reason the server
// had gone to the trouble of writing was dropped on the floor. On a surface whose first rule is
// that it never says a flattering untrue thing, a hard-coded "three" is the untrue thing.
//
// Seen live on expedition 37 ("make the Fold button red"), where one drawing was the RIGHT answer —
// the request pinned size, position, label and hit area, so there was no second arrangement to
// choose between — and the page made it look broken.
const shapesHeading = (n) =>
  n === 1 ? 'One way it could work' : `${WORDS[n] || n} ways it could work`

// Spelled out to about where a person stops reading numerals as words. Past that, the numeral.
const WORDS = { 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six' }

// What is left on the page after a pick, counted rather than assumed — "the other two" was written
// when three was the only possibility, and it is false for every other number.
const notTakenNote = (n) =>
  n <= 1
    ? 'This was the only direction, so there was nothing else to choose between.'
    : n === 2
      ? 'The other one is still here, so you can see what was not taken.'
      : `The other ${WORDS[n - 1]?.toLowerCase() || n - 1} are still here, so you can see what was not taken.`

function Artifacts({ a, onPick, busy, revisions }) {
  if (!a) return null
  const cands = a.candidates || []
  const chosen = cands.find((c) => c.chosen)
  return (
    <>
      {a.attachment && (
        <div className="dm-card">
          <div className="dm-hd"><h2>Attached to this request</h2></div>
          <div className="dm-pad">
            <a className="dm-b sec" href={`${BASE}${a.attachment.url}`} target="_blank" rel="noreferrer">
              {a.attachment.label} ↗
            </a>
            <p className="dm-hint">
              {Math.max(1, Math.round((a.attachment.bytes || 0) / 1024))} KB
              {a.attachment.read_by_gate
                ? ' — its text was read along with the request.'
                : ' — kept with the request for people to look at.'}
            </p>
          </div>
        </div>
      )}

      {cands.length > 0 && (
        <div className="dm-card">
          <div className="dm-hd">
            <h2>{chosen ? 'The direction you chose' : shapesHeading(cands.length)}</h2>
            {chosen && <span className="dm-chip done">DECIDED</span>}
          </div>
          <div className="dm-pad">
            <p className="dm-note" style={{ margin: '0 0 12px' }}>
              {chosen
                ? notTakenNote(cands.length)
                : cands.length > 1
                  ? 'They differ in shape, not in wording. Pick the one you want built.'
                  // One shape is not a choice, so it is not asked for as one. The server's own
                  // sentence is preferred whenever there is one: it is specific to THIS request
                  // and already passed the machinery filter on the way out (`visitor_detail`).
                  // The fallback states the fact and stops, rather than inventing a reason.
                  : 'Only one direction came back for this request, so there is nothing to choose '
                    + 'between — this is the shape it will be built in.'}
            </p>
            {!chosen && cands.length < 3 && a.fewer_because && (
              <p className="dm-note" style={{ margin: '0 0 12px' }}>{a.fewer_because}</p>
            )}
            <Revised items={revisions} at={1} />
            <ol className="dm-cands">
              {cands.map((c, i) => (
                <li key={c.name || i} className={`dm-cand ${c.chosen ? 'chosen' : chosen ? 'passed' : ''}`}>
                  {c.chosen && <div className="bar">✓&nbsp; BUILDING THIS ONE</div>}
                  <div className="top">
                    <span className="n">SHAPE {i + 1}</span>
                    <h3>{c.title || c.name}</h3>
                    <p>{c.premise}</p>
                  </div>
                  <div className="foot">
                    {c.url && <a className="see" href={c.url} target="_blank" rel="noreferrer">See the drawing ↗</a>}
                    {onPick && (
                      <button className="dm-b sec" disabled={busy} onClick={() => onPick(i + 1)}>
                        Build this one
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      {a.preview_url && (
        <div className="dm-card">
          <div className="dm-hd"><h2>A working version</h2></div>
          <div className="dm-pad">
            <Revised items={revisions} at={2} />
            <p className="dm-p">Clickable, built from the design system. Not the finished product —
              it is there so you can tell whether the shape is right before any real code gets
              written.</p>
            <div className="dm-brow" style={{ marginTop: 13 }}>
              <a className="dm-b sec" href={a.preview_url} target="_blank" rel="noreferrer">
                Open the preview ↗
              </a>
            </div>
          </div>
        </div>
      )}

      {a.build && (
        <div className="dm-card">
          <div className="dm-hd"><h2>The code</h2></div>
          <div className="dm-facts">
            <div><span className="k">FILES CHANGED</span><div className="v">{a.build.files}</div></div>
            <div><span className="k">LINES</span><div className="v">{a.build.lines}</div></div>
            <div>
              <span className="k">ITS OWN TESTS</span>
              <div className="v">{a.build.tests_passed ? '✓ pass' : 'not passing'}
                <small>{a.build.tests_passed ? 're-run here' : 'not ready to ship'}</small></div>
            </div>
          </div>
          <div className="dm-pad" style={{ borderTop: '1px solid #ece7db' }}>
            <Revised items={revisions} at={3} />
            {a.build.next && <p className="dm-note" style={{ margin: '0 0 10px' }}>{a.build.next}</p>}
            {a.build.summary && <p className="dm-p dm-sum">{plain(a.build.summary)}</p>}
          </div>
        </div>
      )}

      {/* BUILD'S DELIVERABLE. This rung used to report "2 files, 36 changed lines, check green" —
          a receipt for work nobody could look at. The link is the point, and it carries the flag
          parameter already set: every change ships behind a flag that is off, so a bare stage link
          shows the app exactly as it was and a visitor reasonably concludes nothing happened. */}
      {(a.stage_url || a.pull_request) && (
        <div className="dm-card">
          <div className="dm-hd"><h2>Your change, running</h2></div>
          <div className="dm-pad">
            <div className="dm-brow">
              {a.stage_url && (
                <a className="dm-b pri" href={a.stage_url} target="_blank" rel="noreferrer">
                  See it working ↗
                </a>
              )}
              {a.pull_request && (
                <a className="dm-b sec" href={a.pull_request} target="_blank" rel="noreferrer">
                  Read the code ↗
                </a>
              )}
            </div>
            {a.stage_url ? (
              <p className="dm-hint">This is a copy of the real app with your change switched on,
                just for you — the link carries the switch. Everyone else still sees it off, and
                it stays that way until a person decides otherwise.</p>
            ) : a.ready_for_review ? (
              /* WAITING IS A STATE. Between "pull request marked ready" and "stage deploy lands"
                 the checks are running: nothing is computing here and nothing is wrong. This said
                 the checks were green AND that they had not finished, in one sentence, because
                 absence of a stage link was the only thing the view had to go on. */
              <p className="dm-hint">Waiting for the checks. The code is written and the pull
                request is open; once the checks go green it deploys itself, and a link to open
                it appears here.</p>
            ) : (
              /* NOT waiting — not going. A pull request that was never marked ready does not
                 reach stage on its own, so "once the checks finish" would be a promise nothing
                 is going to keep. */
              <p className="dm-hint">The code is written and the pull request is open. It is not
                on a site you can open yet — that happens once the pull request is marked ready
                for review.</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}

export default function Demo() {
  const [session, setSession] = useState(loadSession)
  // True when we HAD a session and it lapsed, so the sign-in screen can say why it is asking
  // again rather than looking like it forgot you.
  const [expired, setExpired] = useState(() => !!sessionStorage.getItem(KEY) && !loadSession())
  const [closed, setClosed] = useState(() => {
    try { return JSON.parse(localStorage.getItem(CLOSED) || '[]') } catch { return [] }
  })
  const [state, setState] = useState(null)
  // TWO error slots on purpose. There was one, and the 5s poller cleared it on every successful
  // /demo/active — so a failed button press showed its reason for under five seconds and then
  // erased itself, leaving a screen where clicking did nothing and said nothing. A poll may only
  // ever clear the error the POLL raised; what a visitor's action reported stays up until that
  // visitor acts again.
  const [err, setErr] = useState('')            // transport: the poll cannot reach the engine
  const [actErr, setActErr] = useState('')      // this visitor's last action was refused
  const [busy, setBusy] = useState(false)
  const [changes, setChanges] = useState('')
  // Stopping asks first. Kept per-run so that switching to a different expedition, or the run
  // moving on by itself, never leaves a confirmation hanging over a decision it was not asked
  // about.
  const [confirmStop, setConfirmStop] = useState(false)
  const timer = useRef(null)
  // How long this step has been running, measured from when THIS PAGE first saw it — which is
  // what can honestly be said. The run carries no start timestamp, and inventing one would be a
  // worse answer than a modest one.
  const stepSince = useRef({ key: null, at: Date.now() })
  const [onStep, setOnStep] = useState('')
  const [elapsed, setElapsed] = useState(0)

  const refresh = useCallback(async () => {
    try {
      setState(await call('/v1/public/runs/active'))
      setErr('')
    } catch (ex) { setErr(String(ex.message || ex)) }
  }, [])

  useEffect(() => {
    refresh()
    timer.current = setInterval(refresh, 5000)
    return () => clearInterval(timer.current)
  }, [refresh])

  // Tick the "on this step" label once a second, and reset it whenever the step changes.
  const stepKey = state?.active ? `${state.active.number}:${state.active.stage}:${state.active.working?.doing || ''}` : null
  useEffect(() => {
    if (!stepKey) { setOnStep(''); return }
    if (stepSince.current.key !== stepKey) stepSince.current = { key: stepKey, at: Date.now() }
    const tick = () => {
      // Prefer the SERVER's start time: it survives a refresh, and someone arriving late sees
      // the true age of the step rather than zero. The page's own observation is the fallback
      // for a step the server has not stamped.
      const serverAt = state?.active?.working?.started_at
      const from = serverAt ? serverAt * 1000 : stepSince.current.at
      const s = Math.max(0, Math.floor((Date.now() - from) / 1000))
      setElapsed(s)
      setOnStep(clock(s))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [stepKey])

  // Signing out drops THIS BROWSER's pass and nothing else. The run is the expedition's, not the
  // session's — it keeps climbing, and the next person to sign in sees exactly where it got to.
  const signOut = () => {
    sessionStorage.removeItem(KEY)
    setSession(null)
    setExpired(false)
  }

  // Which finished runs this browser has closed. Per-visitor and per-browser on purpose: it is
  // a view preference, not a fact about the expedition, and writing it to the run would let one
  // visitor's tidying hide the payoff from the next.
  const closeRun = (n) => {
    try {
      const seen = JSON.parse(localStorage.getItem(CLOSED) || '[]')
      localStorage.setItem(CLOSED, JSON.stringify([...new Set([...seen, n])].slice(-20)))
    } catch { /* a browser that will not remember simply shows it again */ }
    setClosed((c) => [...c, n])
  }

  const act = async (text) => {
    setBusy(true)
    setActErr('')
    try {
      // The VISITOR door, not the operator one. The demo used to post straight to
      // /expeditions/{n}/feedback with a name it had typed itself, which the operator guard
      // now refuses — rightly. A visitor's actions go through the demo's own audience.
      // A stopped run is shown as `finished`, not `active` — and it is the one that most needs a
      // button. Taking the number from whichever of the two is on screen keeps Retry working
      // there without a second code path for sending a command.
      const n = state?.active?.number ?? state?.finished?.number
      await call(`/v1/visitor/runs/${n}/feedback`, {
        method: 'POST', token: session?.token,
        body: { actor: session?.name || 'demo', body: text },
      })
      setChanges('')
      await refresh()
      // `setActErr`, NOT `setErr`. This wrote to the TRANSPORT slot, which the five-second poll
      // clears on every success — so a refused action showed its reason for under five seconds
      // and then erased itself. That is precisely the bug the two slots were split apart to
      // prevent, reintroduced in the one place it costs most: the button that was just refused.
      //
      // Seen 2026-09-13 on expedition 34's Retry. The server answered 409 with a perfectly good
      // sentence — "This one is already finished. File a new request to build something else." —
      // and the page rendered nothing at all, so the button simply read as broken.
    } catch (ex) { setActErr(String(ex.message || ex)) } finally { setBusy(false) }
  }

  const active = state?.active
  // A stopped or finished run still owns the page — unless this browser has closed it. An ACTIVE
  // run is never hidden: closing is for something that is over, and a run still climbing is not.
  const done = state?.finished
  const shown = active || (done && !closed.includes(done.number) ? done : null)
  const actions = shown?.actions || []
  // A pending confirmation belongs to ONE run in ONE state. If the run moves on while the
  // question is on screen — a rung finishes, a gate opens, the poll swaps in a different
  // expedition — the question is no longer the one that was asked, and answering it would stop
  // something the visitor never looked at.
  const stopKey = shown ? `${shown.number}:${shown.status}` : ''
  // ABOVE THE SIGN-IN RETURN, and it has to stay there.
  //
  // This hook used to sit below it. A visitor arriving with a session already in sessionStorage
  // never saw the problem — `session` is set on the very first render, so the early return never
  // fires and the hook count never changes. But SIGNING IN changes it mid-life: the sign-in
  // render returns before this line, the next render runs it, React counts more hooks than last
  // time and throws (#310, "rendered more hooks than during the previous render"). The whole view
  // unmounted to a blank page, for every visitor who actually used the door — which is everyone
  // who has not been here in the last twelve hours. Nothing after this line may be a hook.
  useEffect(() => { setConfirmStop(false) }, [stopKey])

  if (!session) return <div className="dm"><SignIn onDone={setSession} expired={expired} /></div>

  const w = active?.working
  const halted = !!shown && !active && shown.status === 'Stopped'
  const capPct = w?.limit_s ? Math.min(100, (elapsed / w.limit_s) * 100) : 0
  // WHERE STOP IS DRAWN. While a step runs there is nothing to approve and nothing to amend, so
  // the action card held one quiet button and a paragraph — and the paragraph it held was written
  // for a request that never started, because an empty action list was the only thing the view
  // had to go on. `working` is non-null if and only if the run is climbing (fls/demo.py), so this
  // is the state itself rather than an inference from what is missing: stop goes in the live
  // card, and the second card is not drawn at all.
  const stopInCard = !!w && actions.includes('kill')
  const cardActions = stopInCard ? actions.filter((a) => a !== 'kill') : actions

  const send = (t) => act(t)

  return (
    <div className="dm">
      <Band who={session.name} onOut={signOut} />
      <div className="dm-main">
        <Ladder
          stages={shown?.stages || STAGE_FALLBACK}
          notes={shown?.stage_notes || NOTE_FALLBACK}
          at={shown ? shown.stage : -1}
          waiting={!!shown?.waiting_on_you}
          halted={halted}
        />

        <main className="dm-col">
          {err && <p className="dm-banner" role="alert">{err}</p>}
          {actErr && <p className="dm-banner" role="alert">{actErr}</p>}

          {/* ---- nothing has ever run: an empty state that guides rather than a blank page ---- */}
          {state && !shown && (
            <>
              <div>
                <h1 className="dm-h1">Watch it build something</h1>
                <p className="dm-sub">Type a change you want made to <b>Pocket</b>, a poker app
                  that really exists. It gets drawn, previewed, built and opened as a pull
                  request — and it stops for you at every step.</p>
              </div>
              <RequestBox token={session.token} onFiled={refresh}
                          suggestion={state?.suggestion} />
            </>
          )}

          {shown && (
            <>
              {/* The page keeps one h1 in every state. The visible one belongs to the empty
                  state; once a run is on screen the heading is the page's name, which a sighted
                  reader gets from the band and a screen reader got from nothing at all. */}
              <h1 className="sr-only">Watch it build something</h1>
              {/* THE ASK, or the decision, at the top of the column. It used to sit below the
                  request text with the artifacts under the fold, so the thing the page existed
                  to ask was the last thing on it. */}
              {shown.waiting_on_you && (
                <div className="dm-turn">
                  <span className="t">{shown.question
                    ? 'It needs to ask you something first.'
                    : (TURN_TITLE[shown.stage] || 'Your turn.')}</span>
                  <span className="s">{shown.status}</span>
                </div>
              )}

              <div>
                <p className="dm-lab">YOU ASKED FOR</p>
                <p className="dm-ask">{shown.request}</p>
              </div>

              {/* ---- the live step ---- */}
              {w && (
                <div className="dm-card lead">
                  <div className="dm-hd">
                    <h2>{shown.stage_name}</h2>
                    <span className="dm-chip go">WORKING</span>
                    {onStep && <span className="dm-clk">{onStep} <i>on this step</i></span>}
                  </div>
                  <div className="dm-pad">
                    <div className="dm-work">
                      <span className="dm-spin" aria-hidden="true" />
                      <span>
                        <span className="doing">{w.doing}</span>
                        <span className="means">
                          {w.retrying
                            ? 'That step stopped, so it is having another go. Nothing you did caused it.'
                            : w.means}
                        </span>
                        {/* A DEADLINE, not an estimate. Nothing records how long a step usually
                            takes, so a bar implying otherwise would invent the one number this
                            system may not invent — and the labels say elapsed-against-limit in
                            one unit, because a bare fill is read as "this much done". */}
                        {w.limit_s > 0 && (
                          <div className="dm-cap">
                            <div className="bar">
                              <i className={capPct > 75 ? 'warm' : ''} style={{ width: `${capPct}%` }} />
                              <u />
                            </div>
                            <div className="lbl">
                              {onStep ? `${onStep} SO FAR` : 'JUST STARTED'}
                              <b className={capPct > 75 ? 'warm' : ''}>
                                STOPS ITSELF AT {clock(w.limit_s)}
                              </b>
                            </div>
                          </div>
                        )}
                      </span>
                    </div>
                  </div>
                  {/* THE EXIT, IN THE CARD WHOSE WORK IT ENDS. Tidwell's Cancelability is explicit
                      that a stop belongs beside the indicator of the thing it stops and must name
                      it; this one used to sit in a separate card far below, under a sentence that
                      contradicted the spinner above it. */}
                  {actions.includes('kill') && (
                    <div className={confirmStop ? 'dm-foot asking' : 'dm-foot'}
                         role={confirmStop ? 'group' : undefined}
                         aria-label={confirmStop ? 'Confirm stopping this run' : undefined}>
                      {confirmStop ? (
                        <StopConfirm
                          spend={shown.spend} busy={busy}
                          onYes={() => { setConfirmStop(false); send('/kill stopped from the demo') }}
                          onNo={() => setConfirmStop(false)}
                        />
                      ) : (
                        <>
                          <button type="button" className="dm-b qui" disabled={busy}
                                  onClick={() => setConfirmStop(true)}>
                            Stop this run
                          </button>
                          <span className="dm-hint">
                            {w.retrying
                              ? 'Nothing needs you while it tries again.'
                              : WAIT_LINE[shown.stage] || 'Nothing needs you right now.'}
                          </span>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ---- it stopped on its own ---- */}
              {halted && (
                <div className="dm-card lead">
                  <div className="dm-hd">
                    <h2>{shown.stage_name}</h2>
                    <span className="dm-chip stop">STOPPED</span>
                  </div>
                  <div className="dm-pad">
                    <div className="dm-work">
                      <span className="dm-halt" aria-hidden="true" />
                      <span>
                        <span className="doing">It stopped before finishing</span>
                        <span className="means">{shown.detail}</span>
                        {/* WHAT HAPPENED TO IT, under the sentence saying that something did.
                            "It stopped before finishing" is true of a crash, a step that ran past
                            its limit, a machine that stopped answering and a step that judged and
                            said no — four different things, and a visitor who is told only the
                            first has been told nothing they can act on. */}
                        {shown.cause && <span className="means">{shown.cause}</span>}
                      </span>
                    </div>
                    {/* AND WHETHER THE BUTTON WOULD WORK. Retry used to be drawn on every stopped
                        run and its refusals discovered by pressing it, which teaches a visitor the
                        button is unreliable rather than that this run cannot be retried. */}
                    {shown.retry_blocked && (
                      <p className="dm-hint" style={{ margin: '12px 0 0' }}>{shown.retry_blocked}</p>
                    )}
                  </div>
                </div>
              )}

              {/* ---- it finished ---- */}
              {shown === state?.finished && !halted && (
                <div className="dm-card fin">
                  {/* "Finished." was the ladder's word for its own state, printed where a
                      visitor reads it as the CHANGE's state. They are not the same thing: the
                      climb is over, and the change is a draft pull request nobody has merged.
                      Saying which is finished is the difference between a true sentence and a
                      flattering one — and this card is the last thing the surface says. */}
                  <div className="dm-done-hd">
                    <span className="dm-tick" aria-hidden="true" />
                    <span>
                      <span className="t">The ladder is done.</span>
                      <span className="s">&nbsp; Five steps, and you decided every one. What
                        happens to the change is yours.</span>
                    </span>
                  </div>
                  {/* THE PAYOFF, IN THE PAYOFF CARD. The pull request is what the whole climb was
                      for, and it was rendering as the LAST card on the page — below the
                      attachment, the candidates, the preview and the code. Somebody reaching the
                      end had to scroll past everything the run produced to find the thing it
                      produced. It is the primary action here; the cards below keep their copies
                      as part of the record. */}
                  {(shown.artifacts?.pull_request || shown.artifacts?.preview_url) && (
                    <div className="dm-pad" style={{ borderBottom: '1px solid #ece7db' }}>
                      <div className="dm-brow">
                        {shown.artifacts.pull_request && (
                          <a className="dm-b pri" href={shown.artifacts.pull_request}
                             target="_blank" rel="noreferrer">Open the pull request ↗</a>
                        )}
                        {shown.artifacts.preview_url && (
                          <a className="dm-b sec" href={shown.artifacts.preview_url}
                             target="_blank" rel="noreferrer">Open the preview ↗</a>
                        )}
                      </div>
                      {shown.artifacts.pull_request && (
                        <p className="dm-hint">Opened as a draft with the feature switched off, so
                          merging it changes nothing until a person turns it on.</p>
                      )}
                    </div>
                  )}
                  {/* HOW TO ACTUALLY SEE IT. The card said the feature was behind a flag and
                      stopped there — true, and useless to anyone who then wanted to look at it.
                      Both steps are facts about this run, so nothing here is generic advice:
                      staging is what marking the pull request ready for review does, and the
                      flag is the one this change introduced, read from the branch rather than
                      assumed. A step whose fact is missing is left out rather than hand-waved. */}
                  {shown.artifacts?.review?.stage_url && shown.artifacts.pull_request && (
                    <div className="dm-pad" style={{ borderTop: '1px solid #ece7db' }}>
                      <p className="dm-lab" style={{ marginBottom: 10 }}>TO SEE IT RUNNING</p>
                      <ol className="dm-steps">
                        {/* NOT AN INSTRUCTION ANY MORE. Rung 4 marks the pull request ready for
                            review itself (`orchestration/live.py`), which is the event that
                            stages the build — so telling a visitor to go and do it was asking
                            them to repeat work that had already happened, on the card that
                            reports the run as finished. It says what the ladder did instead. */}
                        <li>
                          <b>It is already on the stage site.</b> The run marked its own pull
                          request ready for review, which is what deploys it to{' '}
                          <a href={shown.artifacts.review.stage_url} target="_blank"
                             rel="noreferrer">the stage site</a> once the checks pass — nothing
                          for you to do here.
                        </li>
                        <li>
                          <b>Switch the feature on to look at it.</b>{' '}
                          {shown.artifacts.review.flag
                            ? <>Open{' '}
                              <a href={`${shown.artifacts.review.stage_url}?flags-${shown.artifacts.review.flag}=true`}
                                 target="_blank" rel="noreferrer">
                                the staged site with it turned on
                              </a>. That is your browser only — nothing is committed and nobody
                              else is affected. <code>?flags-reset</code> puts it back.</>
                            : <>Add <code>?flags-&lt;name&gt;=true</code> to the staged site's
                              address to switch this change on for your browser only.</>}
                        </li>
                      </ol>
                      <p className="dm-hint">That shows it to you. To show it to <i>everyone</i> on
                        stage, the flag is turned on in the project's own <code>flags.json</code> —
                        a change somebody reviews, like any other. Production stays off either way,
                        which is the point of shipping behind a flag.</p>
                    </div>
                  )}
                  {/* WHAT THIS SYSTEM DID NOT DO.
                      Deliberately phrased as what the ladder does, never as the current state of
                      the pull request: "nothing has been merged" is true until somebody merges
                      it, and a sentence that quietly turns false is the thing this surface is
                      built to avoid. What is written here stays true forever. */}
                  {shown.artifacts?.pull_request && (
                    <div className="dm-pad" style={{ borderTop: '1px solid #ece7db' }}>
                      <p className="dm-lab" style={{ marginBottom: 10 }}>WHAT IT LEFT TO YOU</p>
                      <ul className="dm-left">
                        <li><b>It never merges without you.</b> The last step asks, and merging is
                          what your yes does — a person's decision, every time.</li>
                        <li><b>It never turns a feature on.</b> The change merges switched off in
                          both environments, so putting it in the project changes nothing anyone
                          can see until somebody flips the flag. That is why one yes is enough to
                          merge on: it moves code without releasing a feature.</li>
                        <li><b>It never touches production.</b> Promoting a build needs a named
                          approver, and the flag is off there regardless.</li>
                      </ul>
                    </div>
                  )}
                  {shown.spend > 0 && (
                    <div className="dm-facts">
                      <div>
                        <span className="k">WHAT IT COST</span>
                        <div className="v">${shown.spend.toFixed(2)}</div>
                      </div>
                      {shown.revisions?.length > 0 && (
                        <div>
                          <span className="k">YOUR CHANGES</span>
                          <div className="v">{shown.revisions.length}</div>
                        </div>
                      )}
                      {shown.artifacts?.build?.files && (
                        <div>
                          <span className="k">CODE</span>
                          <div className="v">{shown.artifacts.build.files} files
                            <small>{shown.artifacts.build.lines} lines, tests pass</small></div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {shown.detail && !halted && !w && <p className="dm-note">{shown.detail}</p>}

              <Artifacts
                a={shown.artifacts} busy={busy} revisions={shown.revisions}
                onPick={actions.includes('pick') ? (n) => send(`/pick ${n}`) : null}
              />

              <Revisions items={shown.revisions} />

              {/* ---- it asked you something ---- */}
              {shown.question && (
                <div className="dm-card lead">
                  <div className="dm-hd ask">
                    <h2>One question first</h2>
                  </div>
                  <div className="dm-pad">
                    {/* The request could mean two things and it will not pick one for you. An
                        earlier run guessed a THIRD reading of "the button", drew three good
                        wireframes of it and built it — every step sound, the whole thing about a
                        screen nobody had named. */}
                    <p className="dm-p">{shown.question.ask}</p>
                    {shown.question.options.length > 0 && (
                      <ol className="dm-opts">
                        {shown.question.options.map((o) => (
                          <li key={o.key}>
                            <button type="button" className="dm-b sec"
                                    onClick={() => setChanges(o.key)}>
                              ({o.key}) {o.text}
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                    <p className="dm-hint">{shown.question.how}</p>
                  </div>
                </div>
              )}

              {/* ---- what you can do ---- */}
              {cardActions.length > 0 && (
                <div className="dm-card">
                  <div className="dm-pad">
                    {actions.includes('changes') && (
                      <>
                        {/* One label, always. The founder names this field SAY WHAT TO CHANGE
                            whether it is carrying a revision or an answer, and a field that
                            renames itself is one more thing to notice. The placeholder and the
                            hint say which it is right now. */}
                        <label className="dm-lab" htmlFor="d-changes">SAY WHAT TO CHANGE</label>
                        <textarea id="d-changes" className="dm-fld" rows={3} value={changes}
                                  onChange={(e) => setChanges(e.target.value)}
                                  placeholder={shown.question
                                    ? (shown.question.options.length > 0
                                        ? 'a — or say it in your own words'
                                        : 'which screen, which control, and how you would know it worked')
                                    : 'the amount is hard to find'} />
                        <p className="dm-hint">{shown.question
                          ? 'This goes back to the step that asked, which runs again with your '
                            + 'answer. It does not start over.'
                          : 'This sends the step back to be done again with your note. It does '
                            + 'not start over, and it does not skip ahead.'}</p>
                      </>
                    )}
                    {/* A REQUEST THAT NEVER STARTED — and ONLY that.
                        This sentence used to be drawn whenever approve, changes and retry were all
                        absent, which is a description of the admission failure it was written for
                        AND of every ordinary working step. So it sat under a live spinner telling
                        the visitor there was no run behind their request, on the one surface whose
                        whole promise is that it never says a flattering untrue thing. The
                        condition is now the state itself: no step is running, nothing is stopped,
                        and stopping is the only thing left to do. It is also drawn ABOVE the
                        button, because it is the reason for the only choice on offer. */}
                    {!w && !halted && cardActions.length === 1 && cardActions[0] === 'kill' && (
                      <p className="dm-hint" style={{ margin: '0 0 14px' }}>
                        There is nothing here to approve or amend: this request never started, so
                        there is no run behind it and nothing to send a change to. Stop it and ask
                        again with a little more detail.
                      </p>
                    )}
                    <div className="dm-brow" style={{ marginTop: actions.includes('changes') ? 14 : 0 }}>
                      {actions.includes('approve') && (
                        <button className="dm-b pri" disabled={busy} onClick={() => send('/approve')}>
                          Yes, carry on
                        </button>
                      )}
                      {actions.includes('retry') && (
                        <button className="dm-b pri" disabled={busy} onClick={() => send('/retry')}>
                          Try that step again
                        </button>
                      )}
                      {actions.includes('changes') && (
                        <button className={`dm-b ${shown.question ? 'pri' : 'sec'}`}
                                disabled={busy || !changes.trim()}
                                onClick={() => send(changes)}>
                          {shown.question ? 'Send this answer' : 'Send this change'}
                        </button>
                      )}
                      {cardActions.length > 1 && <span className="sp" />}
                      {actions.includes('kill') && !stopInCard && !confirmStop && (
                        <button className="dm-b qui" disabled={busy}
                                onClick={() => setConfirmStop(true)}>
                          Stop this run
                        </button>
                      )}
                    </div>
                    {/* STOPPING IS THE ONE ACT ON THIS PAGE THAT CANNOT BE UNDONE, and it used
                        to fire on a single click of the quietest control in the row. It ends the
                        run: what the ladder has built so far stays, and nothing more gets built.
                        So it asks, and the asking is where the money is said — the spend so far
                        is the number a person actually wants before deciding, and it was on a
                        different part of the screen. */}
                    {actions.includes('kill') && !stopInCard && confirmStop && (
                      <div className="dm-stop" role="group" aria-label="Confirm stopping this run">
                        <StopConfirm
                          spend={shown.spend} busy={busy}
                          onYes={() => { setConfirmStop(false); send('/kill stopped from the demo') }}
                          onNo={() => setConfirmStop(false)}
                        />
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* CLOSING A FINISHED RUN. The surface used to forget a run the instant it ended,
                  which is why it is kept on screen — but "kept until you say otherwise" and
                  "kept forever" are different promises, and only the first one is useful.
                  Dismissing is per-browser and changes nothing about the run: the expedition,
                  its pull request and its ledger entry are all untouched. */}
              {!active && (
                <div className="dm-card">
                  <div className="dm-pad">
                    <div className="dm-brow">
                      <button className="dm-b ink" onClick={() => closeRun(shown.number)}>
                        Close this and start something else
                      </button>
                      <span className="dm-hint" style={{ margin: 0 }}>
                        Clears it from your view. The run, its pull request and its record stay
                        exactly as they are.
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* The request box comes back the moment a run is over, under the run it is over. */}
              {!active && <RequestBox token={session.token} onFiled={refresh}
                                       suggestion={state?.suggestion} />}
            </>
          )}
        </main>
      </div>
    </div>
  )
}

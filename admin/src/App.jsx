// The V3 shell: one rail, three grouped areas (Workbench · Anchor · System) + a global
// "File an idea" action, over the same hash router + ⌘K. Sections are lenses over the harness
// API (live-first, fixtures fallback — the badge says which). This is re-homing, not a rebuild:
// every existing section/wizard is reused; three new screens (Inbox · Constitution+Vessels ·
// Modules) lead each area.
import React, { useEffect, useState } from 'react'
import { NotAuthorised, NotSignedIn, api, loadAll } from './api.js'
import SignInShell from './SignInShell.jsx'
import Demo from './sections/Demo.jsx'
import Detail from './sections/Detail.jsx'
import Home from './sections/Home.jsx'
import Inbox from './sections/Inbox.jsx'
import Constitution from './sections/Constitution.jsx'
import Vessels from './sections/Vessels.jsx'
import Modules from './sections/Modules.jsx'
import { Autonomy, Lessons } from './sections/Panels.jsx'
import PanelAuthor from './sections/PanelAuthor.jsx'
import { Toast, needsYou } from './ui.jsx'
import BudgetsFunnel from './sections/BudgetsFunnel.jsx'
import Feeder from './sections/Feeder.jsx'
import FileIdea from './wizard/FileIdea.jsx'

// Old routes that moved — redirect so bookmarks keep working.
//
// `#/calibration` and `#/anchor/earning-history` both land on Autonomy because all three were the
// same subject split across three routes and two rail groups: Calibration and Autonomy literally
// rendered the same component with a different prop, and Earning history is the agreement trail
// that is the *evidence for* a dial change. One subject, one screen.
const REDIRECTS = {
  '/feeder': '/system/feeder',
  '/calibration': '/anchor/autonomy',
  '/anchor/earning-history': '/anchor/autonomy',
  '/exp': '/runs',            // the old noun, kept so a saved link still lands
}

// The FLS 'Resolution' mark — F(hand)·L(pixel)·S(vector)·rung-tick-X gate. Self-contained SVG so
// it renders even before webfonts load (the F uses Caveat; S/pixels are font-free geometry-ish).
function RailMark() {
  return (
    <svg className="mk" width="34" height="34" viewBox="0 0 100 100" aria-hidden="true">
      <svg x="0" y="0" width="50" height="50" viewBox="0 0 100 100"><rect width="100" height="100" fill="#005eb8" /><text x="46" y="50" textAnchor="middle" dominantBaseline="central" fill="#f5f3ee" fontFamily="'Caveat',cursive" fontWeight="700" fontSize="78">F</text></svg>
      <svg x="50" y="0" width="50" height="50" viewBox="0 0 100 100"><rect width="100" height="100" fill="#fdb913" /><g fill="#16130f"><rect x="27.75" y="22" width="10" height="10" /><rect x="27.75" y="33.5" width="10" height="10" /><rect x="27.75" y="45" width="10" height="10" /><rect x="27.75" y="56.5" width="10" height="10" /><rect x="27.75" y="68" width="10" height="10" /><rect x="39.25" y="68" width="10" height="10" /><rect x="50.75" y="68" width="10" height="10" /><rect x="62.25" y="68" width="10" height="10" /></g></svg>
      <svg x="0" y="50" width="50" height="50" viewBox="0 0 100 100"><rect width="100" height="100" fill="#e63329" /><text x="50" y="53" textAnchor="middle" dominantBaseline="central" fill="#f5f3ee" fontFamily="'Archivo',sans-serif" fontWeight="600" fontSize="80">S</text></svg>
      <svg x="50" y="50" width="50" height="50" viewBox="0 0 100 100"><rect width="100" height="100" fill="#2b2823" /><g stroke="#f5f3ee" strokeWidth="6" strokeLinecap="round"><line x1="26" y1="26" x2="74" y2="74" /><line x1="74" y1="26" x2="26" y2="74" /></g><g stroke="#f5f3ee" strokeWidth="4" strokeLinecap="round"><line x1="42.2" y1="33.8" x2="33.8" y2="42.2" /><line x1="66.2" y1="57.8" x2="57.8" y2="66.2" /><line x1="42.2" y1="66.2" x2="33.8" y2="57.8" /><line x1="66.2" y1="42.2" x2="57.8" y2="33.8" /></g></svg>
      <g stroke="#f5f3ee" strokeWidth="1.6"><line x1="50" y1="0" x2="50" y2="100" /><line x1="0" y1="50" x2="100" y2="50" /></g>
    </svg>
  )
}

// The demo build (VITE_FLS_MODE=demo) serves a different audience entirely: a visitor judging
// the work, not an operator running it. It is a separate surface rather than a stripped-down
// workbench, because hiding controls from an operator's layout leaves an operator's vocabulary
// on screen — which is exactly what the demo must not show.
const DEMO_MODE = import.meta.env.VITE_FLS_MODE === 'demo'
// Where rung 5a publishes this instance's built site. INSTANCE CONFIG, no default: unset
// hides the Stage link entirely (fail-closed), because a link to nothing is a falsehood
// and a hardcoded address would point every install at somebody else's domain.
const STAGE_URL = (import.meta.env.VITE_FLS_STAGE_URL || '').trim()

export default function App() {
  if (DEMO_MODE) return <Demo />
  return <Workbench />
}


/** The whole UI when the harness says "sign in first".
 *
 * This screen existing at all is the point: before it, a 401 fell through `loadAll`'s catch-all
 * into the fixtures fallback, and an unauthenticated visitor was shown a complete, convincing
 * dashboard of invented expeditions. Looking like it worked is the worst way to fail a login.
 */
/** Who is signed in, and the way out.
 *
 * This block used to read "Your account / admin · settings" — a label, written before anything
 * was authenticated, that said the same thing to everyone. Now that a session is a verified
 * identity it should show WHOSE, and a console that can sign you in owes you a way to sign out.
 */
function Account({ me }) {
  const p = me && me.authenticated ? me.principal : null
  const name = p ? (p.name || p.login || p.subject) : null
  const sub = p ? (p.login && p.name ? p.login : p.provider) : 'not signed in'
  const signOut = async () => {
    try { await api.logout() } catch { /* clearing the cookie is best-effort; reload regardless */ }
    window.location.reload()
  }
  return (
    <div className="acct">
      {/* The provider's own avatar when it issues one — the console has actually identified this
          person, so drawing a generic glyph for them is a downgrade. Falls back to the glyph when
          the claim is absent (GitHub always sends one; an email-only Clerk sign-in may not) or
          when the image fails to load, so a broken URL degrades rather than leaving a hole. */}
      <span className="acct-av" aria-hidden="true">
        {p && p.picture
          ? <img className="acct-img" src={p.picture} alt="" width="34" height="34"
                 onError={(ev) => { ev.currentTarget.style.display = 'none' }} />
          : <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8.5" r="3.6" fill="#f5f3ee" /><path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" fill="#f5f3ee" /></svg>}
      </span>
      <span className="acct-txt">
        <b title={name || undefined}>{name || 'Your account'}</b>
        <i>{sub}</i>
      </span>
      {p
        // Phosphor "sign-out" (regular), MIT — the founder's pick. Inlined rather than pulled
        // from a CDN because the admin ships no icon dependency and one icon is not a reason to
        // start. Icon, not a text button: the rail is narrow and a "Sign out" label was wide
        // enough to truncate the name beside it, which defeats the point of showing who is in.
        ? <button type="button" className="acct-out" onClick={signOut}
                  title="Sign out" aria-label="Sign out">
            <svg width="15" height="15" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true">
              <path d="M120,216a8,8,0,0,1-8,8H48a8,8,0,0,1-8-8V40a8,8,0,0,1,8-8h64a8,8,0,0,1,0,16H56V208h56A8,8,0,0,1,120,216Zm109.66-93.66-40-40a8,8,0,0,0-11.32,11.32L204.69,120H112a8,8,0,0,0,0,16h92.69l-26.35,26.34a8,8,0,0,0,11.32,11.32l40-40A8,8,0,0,0,229.66,122.34Z"/>
            </svg>
          </button>
        : <a className="acct-gear" href={href('/system')} onClick={nav('/system')} aria-label="System settings">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="3.2" /><path d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.6 1.6M18.2 18.2l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.6-1.6M18.2 5.8l1.6-1.6" strokeLinecap="round" /></svg>
          </a>}
    </div>
  )
}

function NotAllowed() {
  return (
    <div className="pane" style={{ maxWidth: 460, margin: '12vh auto', textAlign: 'center' }}>
      <h2 style={{ marginTop: 0 }}>Not authorised</h2>
      <p className="note">You are signed in, but this account is not on this instance's
        allowlist. Whoever runs it sets <code>FLS_ALLOWED_USERS</code>.</p>
      <button className="btn" style={{ marginTop: 12 }}
              onClick={() => api.logout().then(() => window.location.reload())}>Sign out</button>
    </div>
  )
}

// The label names the provider only when WE pick it. With `oidc` the choice of method (Google,
// GitHub, email, passkey) happens on the provider's own page, so promising one here would be a
// guess — and "SSO" is jargon to the one person who uses this console.
const PROVIDER_LABEL = {
  'github-oauth': 'Sign in with GitHub',
  oidc: 'Sign in',
  'proxy-header': 'Sign in',
}

const AUTH_ERRORS = {
  'could not verify': 'That sign-in could not be verified — it may have expired. Try again.',
  'not confirmed': 'GitHub did not confirm an identity.',
  'not authorised': 'That account is not on this instance\u2019s allowlist.',
}

function SignIn({ kind, returnTo }) {
  const err = new URLSearchParams(window.location.search).get('auth_error')
  const label = PROVIDER_LABEL[kind] || 'Sign in'
  return (
    <SignInShell
      title="Sign in to the workbench"
      blurb="This harness spends money and can stop work in flight. It wants to know who you are first."
      notice={err && (
        <p className="si-warn" role="status">
          <b>{AUTH_ERRORS[err] || 'Sign-in did not complete.'}</b>
        </p>
      )}
      foot="Only people on this instance's allowlist get in, and every decision you make is recorded against your name."
      other={<>Not an operator? The <a href="/build/">public demo</a> is open to read.</>}
    >
      <div className="si-provs">
        <a className="si-prov" href={api.loginUrl(returnTo)}>
          {kind === 'github-oauth' && (
            <svg width="15" height="15" viewBox="0 0 16 16" fill="#16130f" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>
          )}
          {label}
        </a>
      </div>
    </SignInShell>
  )
}

// ── ROUTING ────────────────────────────────────────────────────────────────────────────────
// Real paths, not #fragments. /workbench/runs/17 is a URL somebody can paste into a message; a
// fragment is not — the server never sees it, so it cannot be linked, redirected or logged, and
// every route in the console was one.
//
// The app is served under a base (`/workbench/`), so the router works in the space BELOW it and
// the base is added back only when a real href is written.
const RBASE = import.meta.env.BASE_URL || '/'

/** The current route, relative to the base: '/', '/wall', '/runs/17'. */
function readRoute() {
  // Legacy #fragments still arrive: a bookmark to /app/#/wall redirects to /workbench/ and the
  // BROWSER re-appends the fragment, because a fragment is never sent to the server and so
  // cannot be rewritten by one. Translate it and replace the entry, so the old link lands in the
  // right place and leaves a clean URL behind it.
  const hash = window.location.hash
  if (hash.startsWith('#/')) {
    const to = hash.slice(1).replace(/^\/exp\//, '/runs/')
    window.history.replaceState(null, '', href(to))
    return to
  }
  let p = window.location.pathname
  if (p.startsWith(RBASE)) p = '/' + p.slice(RBASE.length)
  return p.replace(/\/+$/, '') || '/'
}

/** A route as a real href, under the base. */
function href(to) {
  return (RBASE + to.replace(/^\//, '')).replace(/\/{2,}/g, '/')
}

/** Navigate without a page load. `popstate` does not fire for pushState, so it is announced —
 *  one event, one listener, and the back button keeps working because the entry is real. */
function go(to) {
  window.history.pushState(null, '', href(to))
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** An onClick that routes, while leaving the anchor a genuine link: modified clicks (new tab,
 *  new window, download) are left to the browser, which is the whole reason these are <a>. */
function nav(to) {
  return (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    e.preventDefault()
    go(to)
  }
}

function Workbench() {
  const [route, setRoute] = useState(readRoute)
  const [data, setData] = useState(null)
  const [toast, setToast] = useState('')
  const [me, setMe] = useState(undefined)   // undefined = still asking; null = signed out
  const [denied, setDenied] = useState(false)
  const [provider, setProvider] = useState(null)   // which sign-in to offer

  useEffect(() => {
    const h = () => setRoute(readRoute())
    window.addEventListener('popstate', h)
    return () => window.removeEventListener('popstate', h)
  }, [])

  const reload = () => loadAll().then(setData).catch((e) => {
    if (e instanceof NotSignedIn) { setMe(null); setProvider(e.identity) }
    else if (e instanceof NotAuthorised) setDenied(true)
    else throw e
  })
  useEffect(() => { reload() }, [])

  // Ask who we are on mount. An instance with identity off answers honestly
  // (`authenticated: false, identity: "none"`) rather than pretending someone is signed in —
  // the Modules card is where that gets flagged as something to fix.
  useEffect(() => {
    api.me().then(setMe).catch((e) => {
      if (e instanceof NotSignedIn) { setMe(null); setProvider(e.identity) }
      else if (e instanceof NotAuthorised) setDenied(true)
    })
  }, [])

  // Legacy routes, replaced in place so the old link resolves and leaves no dead entry behind.
  // `window.location.replace` would have been a full page load here — and with a base path it
  // would have resolved the bare '/system/feeder' against the ORIGIN, leaving the workbench.
  useEffect(() => {
    const to = REDIRECTS[route] || (route.startsWith('/exp/') ? route.replace('/exp/', '/runs/') : null)
    if (to) { window.history.replaceState(null, '', href(to)); window.dispatchEvent(new PopStateEvent('popstate')) }
  }, [route])

  // ⌘K -> inbox + focus its filter (the "anything" affordance)
  useEffect(() => {
    const h = (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
        ev.preventDefault()
        go('/')
        setTimeout(() => document.querySelector('.chip')?.focus(), 50)
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  const say = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3200) }

  // Signed out wins over "loading": with no session there is no data coming, and a spinner
  // that never resolves is a worse answer than the screen that tells you what to do.
  if (denied) return <NotAllowed />
  if (me === null) return <SignIn kind={provider} returnTo={route} />
  if (!data) return <div className="pane"><p className="note">Loading the workbench…</p></div>

  const sys = data.system?.slots
  let slotProblems = 0
  if (sys) {
    for (const key of ['auth', 'sources', 'workers']) if (!sys[key]?.available) slotProblems++
    const ideas = sys.ideas || []
    if (ideas.length && !ideas.some((s) => s.available)) slotProblems++
  }
  const counts = {
    exp: data.expeditions?.length ?? 0,
    needs: (data.expeditions || []).filter(needsYou).length,
    lessons: data.lessons?.length ?? 0,
    recs: (data.calibration || []).filter((c) => c.recommendation !== 'hold').length,
    vessels: data.anchor?.vessels?.length ?? 0,
    slotProblems,
  }

  const open = (n) => { go(`/runs/${n}`) }
  const detail = route.match(/^\/runs\/(\w[\w-]*)/)
  let pane
  if (detail) pane = <Detail number={Number(detail[1]) || detail[1]} data={data} toast={say} onBack={() => { go('/') }} />
  else if (route === '/file') pane = <FileIdea data={data} toast={say} onDone={() => { go('/') }} />
  else if (route === '/wall') pane = <Home data={data} onOpen={open} />
  else if (route === '/lessons') pane = <Lessons data={data} />
  else if (route === '/anchor/console') pane = <BudgetsFunnel data={data} toast={say} />
  else if (route === '/anchor/vessels') pane = <Vessels data={data} />
  else if (route === '/anchor/panels') pane = <PanelAuthor data={data} toast={say} />
  else if (route === '/anchor/autonomy') pane = <Autonomy data={data} />
  else if (route === '/anchor') pane = <Constitution data={data} />
  else if (route === '/system/feeder') pane = <Feeder data={data} toast={say} />
  else if (route === '/system') pane = <Modules data={data} />
  else pane = <Inbox data={data} onOpen={open} toast={say} reload={reload} />

  // full-bleed wizard layout for the guided flows
  const wizardRoute = ['/file'].includes(route)

  // Each item is [hash, label, count, description].
  //
  // The description is not decoration: the bar for this rail is that someone who has never used
  // FLS can read it and say what the application does. Labels alone could not carry that — "Console"
  // named a widget, "Earning history" sounded financial.
  //
  // Badges follow one rule everywhere: **a number means something wants a human.** Red = decisions
  // waiting (Workbench only), amber = a seam needs attention (System only), plain = a count. Anchor
  // earns neither, so it declares no badge at all rather than a hardcoded 0 that could never render.
  const GROUPS = [
    { head: 'Workbench', badge: counts.needs, badgeClass: 'grp-red', items: [
      ['/', 'Inbox', null, 'decisions waiting on you'],
      ['/wall', 'Wall', counts.exp, 'every expedition'],
      ['/lessons', 'Lessons', counts.lessons, 'what failure taught'],
    ] },
    { head: 'Anchor', badge: 0, badgeClass: '', items: [
      ['/anchor', 'Constitution', null, 'north star, non-negotiables'],
      ['/anchor/vessels', 'Vessels', counts.vessels, 'what grounds the work'],
      ['/anchor/console', 'Budgets & funnel', null, 'how far, how much'],
      ['/anchor/autonomy', 'Autonomy', counts.recs > 0 ? `${counts.recs} rec` : null,
        'what the ladder earned'],
      ['/anchor/panels', 'Panels', null, 'who reviews'],
    ] },
    { head: 'System', badge: counts.slotProblems, badgeClass: 'grp-amber', items: [
      ['/system', 'Modules', null, 'how this instance is wired'],
      ['/system/feeder', 'Feeder', null, 'where ideas come from'],
      // The app this instance BUILDS, on its own domain. Utility navigation: checked
      // occasionally, not traversed. It is only honest now that rung 5a publishes the built
      // site there — /stage/ served an empty directory for its whole life, and a link to
      // nothing is the same falsehood as a chip for a pull request nobody opened.
      ...(STAGE_URL ? [[STAGE_URL, 'Stage \u2197', null, 'the app it built']] : []),
    ] },
  ]

  const isActive = (r) =>
    r === '/' ? (route === '/' || route.startsWith('/runs/')) : route === r

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        {/* BASE_URL, not a leading slash. This app is built twice — `--base=/app/` for the
            workbench and `--base=/demo/` for the visitor surface — and Vite rewrites asset paths
            it owns, but NOT a hardcoded absolute string in JSX. So the mark was requested from
            `/brand/mark-full.svg` (404, the landing page's root) while it was deployed at
            `/app/brand/mark-full.svg` (200), and every operator saw a broken-image icon where
            the logo should be. BASE_URL already ends in a slash. */}
        <div className="brand"><img className="mk" src={`${import.meta.env.BASE_URL}brand/mark-full.svg`} width="34" height="34" alt="" /><span className="wm">FIDELITY<br />LADDER</span></div>
        <a className="btn btn-pri rail-file" href={href('/file')} onClick={nav('/file')}
           style={{ textDecoration: 'none' }}>+ File an idea</a>
        {GROUPS.map((g) => (
          <div className="navsec" key={g.head}>
            <div className="rail-group">
              {g.head.toUpperCase()}
              {g.badge > 0 && <span className={`grp-badge ${g.badgeClass}`}>{g.badge}</span>}
            </div>
            {g.items.map(([to, label, count, desc]) => (
              <a key={to} className={`nav${isActive(to) ? ' on' : ''}`}
                 href={to.startsWith('http') ? to : href(to)}
                 onClick={to.startsWith('http') ? undefined : nav(to)}
                 {...(to.startsWith('http') ? { target: '_blank', rel: 'noreferrer' } : {})}
                 aria-current={isActive(to) ? 'page' : undefined}>
                <span className="nav-t">
                  {label}
                  {desc && <span className="nav-d">{desc}</span>}
                </span>
                {count != null && <span className="n">{count}</span>}
              </a>
            ))}
          </div>
        ))}
        <Account me={me} />
      </nav>
      <main className="main" style={wizardRoute ? { display: 'block' } : undefined}>
        {pane}
      </main>
      <Toast msg={toast} />
    </div>
  )
}

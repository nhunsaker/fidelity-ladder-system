// The V3 shell: one rail, three grouped areas (Workbench · Anchor · System) + a global
// "File an idea" action, over the same hash router + ⌘K. Sections are lenses over the harness
// API (live-first, fixtures fallback — the badge says which). This is re-homing, not a rebuild:
// every existing section/wizard is reused; three new screens (Inbox · Constitution+Vessels ·
// Modules) lead each area.
import React, { useEffect, useState } from 'react'
import { loadAll } from './api.js'
import Detail from './sections/Detail.jsx'
import Home from './sections/Home.jsx'
import Inbox from './sections/Inbox.jsx'
import Constitution from './sections/Constitution.jsx'
import Vessels from './sections/Vessels.jsx'
import Modules from './sections/Modules.jsx'
import { Calibration, Lessons } from './sections/Panels.jsx'
import PanelAuthor from './sections/PanelAuthor.jsx'
import EarningHistory from './sections/EarningHistory.jsx'
import { Toast } from './ui.jsx'
import AnchorConsole from './wizard/AnchorConsole.jsx'
import FeederControl from './wizard/FeederControl.jsx'
import FileIdea from './wizard/FileIdea.jsx'

// Old routes that moved — redirect so bookmarks keep working.
const REDIRECTS = { '#/feeder': '#/system/feeder' }

export default function App() {
  const [route, setRoute] = useState(window.location.hash || '#/')
  const [data, setData] = useState(null)
  const [toast, setToast] = useState('')

  useEffect(() => {
    const h = () => setRoute(window.location.hash || '#/')
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  const reload = () => loadAll().then(setData)
  useEffect(() => { reload() }, [])

  // legacy-route redirects (old #/feeder -> #/system/feeder)
  useEffect(() => {
    if (REDIRECTS[route]) window.location.replace(REDIRECTS[route])
  }, [route])

  // ⌘K -> inbox + focus its filter (the "anything" affordance)
  useEffect(() => {
    const h = (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
        ev.preventDefault()
        window.location.hash = '#/'
        setTimeout(() => document.querySelector('.chip')?.focus(), 50)
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  const say = (msg) => { setToast(msg); setTimeout(() => setToast(''), 3200) }

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
    needs: (data.expeditions || []).filter((e) =>
      ['descended', 'await-signoff', 'await-pick', 'needs-human'].includes(e.status)).length,
    lessons: data.lessons?.length ?? 0,
    recs: (data.calibration || []).filter((c) => c.recommendation !== 'hold').length,
    vessels: data.anchor?.vessels?.length ?? 0,
    slotProblems,
  }

  const open = (n) => { window.location.hash = `#/exp/${n}` }
  const detail = route.match(/^#\/exp\/(\w[\w-]*)/)
  let pane
  if (detail) pane = <Detail number={Number(detail[1]) || detail[1]} data={data} toast={say} onBack={() => { window.location.hash = '#/' }} />
  else if (route === '#/file') pane = <FileIdea data={data} toast={say} onDone={() => { window.location.hash = '#/' }} />
  else if (route === '#/wall') pane = <Home data={data} onOpen={open} />
  else if (route === '#/lessons') pane = <Lessons data={data} />
  else if (route === '#/calibration') pane = <Calibration data={data} />
  else if (route === '#/anchor/console') pane = <AnchorConsole data={data} toast={say} />
  else if (route === '#/anchor/vessels') pane = <Vessels data={data} />
  else if (route === '#/anchor/panels') pane = <PanelAuthor data={data} toast={say} />
  else if (route === '#/anchor/autonomy') pane = <Calibration data={data} autonomy />
  else if (route === '#/anchor/earning-history') pane = <EarningHistory data={data} />
  else if (route === '#/anchor') pane = <Constitution data={data} />
  else if (route === '#/system/feeder') pane = <FeederControl data={data} toast={say} />
  else if (route === '#/system') pane = <Modules data={data} />
  else pane = <Inbox data={data} onOpen={open} toast={say} reload={reload} />

  // full-bleed wizard layout for the guided flows
  const wizardRoute = ['#/file', '#/anchor/console', '#/system/feeder'].includes(route)

  const GROUPS = [
    { head: 'Workbench', badge: counts.needs, badgeClass: 'grp-red', items: [
      ['#/', 'Inbox', null],
      ['#/wall', 'Wall', counts.exp],
      ['#/lessons', 'Lessons', counts.lessons],
      ['#/calibration', 'Calibration', counts.recs > 0 ? `${counts.recs} rec` : null],
    ] },
    { head: 'Anchor', badge: 0, badgeClass: '', items: [
      ['#/anchor', 'Constitution', null],
      ['#/anchor/console', 'Console', null],
      ['#/anchor/vessels', 'Vessels', counts.vessels],
      ['#/anchor/panels', 'Panels', null],
      ['#/anchor/autonomy', 'Autonomy', counts.recs > 0 ? `${counts.recs} rec` : null],
      ['#/anchor/earning-history', 'Earning history', null],
    ] },
    { head: 'System', badge: counts.slotProblems, badgeClass: 'grp-amber', items: [
      ['#/system', 'Modules', null],
      ['#/system/feeder', 'Feeder', null],
    ] },
  ]

  const isActive = (hash) =>
    hash === '#/' ? (route === '#/' || route.startsWith('#/exp')) : route === hash

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">🪜 Fidelity Ladder</div>
        <a className="btn btn-pri rail-file" href="#/file" style={{ textDecoration: 'none' }}>+ File an idea</a>
        {GROUPS.map((g) => (
          <React.Fragment key={g.head}>
            <div className="rail-group">
              {g.head.toUpperCase()}
              {g.badge > 0 && <span className={`grp-badge ${g.badgeClass}`}>{g.badge}</span>}
            </div>
            {g.items.map(([hash, label, count]) => (
              <a key={hash} className={`nav${isActive(hash) ? ' on' : ''}`} href={hash}
                 aria-current={isActive(hash) ? 'page' : undefined}>
                {label}
                {count != null && <span className="n">{count}</span>}
              </a>
            ))}
          </React.Fragment>
        ))}
        <div className="rail-foot">slim mode · lens over the GitHub App<br />
          tokens via @sorb/leaf · Primer paint</div>
      </nav>
      <main className="main" style={wizardRoute ? { display: 'block' } : undefined}>
        {pane}
      </main>
      <Toast msg={toast} />
    </div>
  )
}

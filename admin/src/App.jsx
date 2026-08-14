// The 2b shell: 1c rail navigation + hash routing + ⌘K. Sections are lenses over the harness
// API (live-first, fixtures fallback — the badge says which).
import React, { useEffect, useState } from 'react'
import { loadAll } from './api.js'
import Detail from './sections/Detail.jsx'
import Home from './sections/Home.jsx'
import { Calibration, Lessons } from './sections/Panels.jsx'
import { Toast } from './ui.jsx'
import AnchorConsole from './wizard/AnchorConsole.jsx'
import FeederControl from './wizard/FeederControl.jsx'
import FileIdea from './wizard/FileIdea.jsx'

const NAV = [
  ['#/', 'Expeditions'],
  ['#/file', 'File an idea'],
  ['#/anchor', 'ANCHOR console'],
  ['#/feeder', 'Feeder'],
  ['#/calibration', 'Calibration'],
  ['#/lessons', 'Lessons'],
]

export default function App() {
  const [route, setRoute] = useState(window.location.hash || '#/')
  const [data, setData] = useState(null)
  const [toast, setToast] = useState('')

  useEffect(() => {
    const h = () => setRoute(window.location.hash || '#/')
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])

  useEffect(() => { loadAll().then(setData) }, [])

  // ⌘K -> home + focus the filter row (the "anything" affordance)
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
  const go = (hash) => () => { window.location.hash = hash }

  if (!data) return <div className="pane"><p className="note">Loading the wall…</p></div>

  const counts = {
    exp: data.expeditions?.length ?? 0,
    needs: (data.expeditions || []).filter((e) =>
      ['descended', 'await-signoff', 'await-pick', 'needs-human'].includes(e.status)).length,
    lessons: data.lessons?.length ?? 0,
    recs: (data.calibration || []).filter((c) => c.recommendation !== 'hold').length,
  }

  const detail = route.match(/^#\/exp\/(\w[\w-]*)/)
  let pane
  if (detail) pane = <Detail number={Number(detail[1]) || detail[1]} data={data} toast={say} onBack={go('#/')} />
  else if (route === '#/file') pane = <FileIdea data={data} toast={say} onDone={go('#/')} />
  else if (route === '#/anchor') pane = <AnchorConsole data={data} toast={say} />
  else if (route === '#/feeder') pane = <FeederControl data={data} toast={say} />
  else if (route === '#/calibration') pane = <Calibration data={data} />
  else if (route === '#/lessons') pane = <Lessons data={data} />
  else pane = <Home data={data} onOpen={(n) => { window.location.hash = `#/exp/${n}` }} />

  const wizardRoute = ['#/file', '#/anchor', '#/feeder'].includes(route)

  return (
    <div className="shell">
      <nav className="rail" aria-label="Main">
        <div className="brand">🪜 Fidelity Ladder</div>
        {NAV.map(([hash, label]) => (
          <a key={hash} className={`nav${route === hash || (hash === '#/' && route.startsWith('#/exp')) ? ' on' : ''}`} href={hash}>
            {label}
            {label === 'Expeditions' && <span className="n">{counts.exp}</span>}
            {label === 'Feeder' && <span className="n">manual</span>}
            {label === 'Calibration' && counts.recs > 0 && <span className="n">{counts.recs} rec</span>}
            {label === 'Lessons' && <span className="n">{counts.lessons}</span>}
          </a>
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

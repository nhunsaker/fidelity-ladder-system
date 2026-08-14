// The shared guided-flow shell — design 1c's vertical stepper, the callout-style pattern
// from the founder's description: 1 pick the work → 2 explain every input → 3 map + validate
// before anything submits. One shell, three flows.
import React from 'react'

/**
 * @param {{title: string, steps: {t: string, x: string}[], step: number,
 *          footNote?: string, children: any}} props
 */
export default function Wizard({ title, steps, step, footNote, children }) {
  return (
    <div className="wiz">
      <nav className="wiz-rail" aria-label={`${title} steps`}>
        <div className="brand">{title}</div>
        {steps.map((s, i) => (
          <div key={s.t} className={`wstep${i === step ? ' on' : ''}`} aria-current={i === step ? 'step' : undefined}>
            <span className={`wnum${i < step ? ' done' : i === step ? ' on' : ''}`}>
              {i < step ? '✓' : i + 1}
            </span>
            <span>
              <span className="wt" style={{ display: 'block' }}>{s.t}</span>
              <span className="wx" style={{ display: 'block' }}>{s.x}</span>
            </span>
          </div>
        ))}
        {footNote && <div className="rail-foot">{footNote}</div>}
      </nav>
      <div className="wiz-main">{children}</div>
    </div>
  )
}

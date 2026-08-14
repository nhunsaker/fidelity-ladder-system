// Calibration + Lessons panes (read-only lenses over the harness data).
import React from 'react'

export function Calibration({ data, autonomy }) {
  return (
    <div className="pane">
      <h2>{autonomy ? 'Autonomy · dial recommendations' : 'Autonomy panel · calibration readout'}</h2>
      <p className="note">Judge-vs-human agreement per rung. Loosening needs an earned track record;
        tightening is always allowed. A human applies the change.
        {autonomy && <> This is the recommendations slice of <a href="#/calibration">Workbench · Calibration</a> —
          the same ledger, framed for governance.</>}</p>
      <div className="card">
        <table className="t">
          <thead>
            <tr><th>rung</th><th>decisions</th><th>agreement</th><th>$/verdict</th><th>human-latency</th><th>recommendation</th></tr>
          </thead>
          <tbody>
            {(data.calibration || []).map((c) => (
              <tr key={c.rung}>
                <td>{c.rung}</td>
                <td>{c.decisions}</td>
                <td>{c.agreement == null ? '—' : `${Math.round(c.agreement * 100)}%`}</td>
                <td className="money">{c.cost_per_verdict == null ? '—' : `$${c.cost_per_verdict.toFixed(4)}`}</td>
                <td className="money">{c.human_latency_avg_s == null ? '—' : `${Math.round(c.human_latency_avg_s)}s`}</td>
                <td className={`rec-${c.recommendation}`}>{c.recommendation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function Lessons({ data }) {
  return (
    <div className="pane">
      <h2>LESSONS — durable anti-patterns</h2>
      <p className="note">Written on descent, read by future rung-1 judges. This is how the system
        gets smarter across expeditions.</p>
      <div className="card card-pad">
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {(data.lessons || []).map((l, i) => (
            <li key={i} style={{ color: 'var(--color-fg-muted, #59636e)', marginBottom: 6, fontSize: 12.5 }}>{l}</li>
          ))}
        </ul>
      </div>
    </div>
  )
}

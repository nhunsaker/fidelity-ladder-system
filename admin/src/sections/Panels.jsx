// Calibration + Lessons panes (read-only lenses over the harness data).
import React from 'react'

import EarningHistory from './EarningHistory.jsx'

/** What a dial actually permits, in the operator's terms. The word alone ("human-picks") says
 *  what it is called, not what it lets the machine do without asking. */
const DIAL_MEANS = {
  'propose-only': 'Never advances itself. A person acts, every time.',
  'human-picks': 'You choose. Nothing advances on its own.',
  'auto-advance-with-audit': 'Advances by itself; the result is audited and a failure descends.',
  autonomous: 'Advances and ships without asking.',
}

/** Autonomy — one screen for the whole dial story.
 *
 * Three routes used to carry this: `#/calibration` and `#/anchor/autonomy` rendered THIS component
 * with a different prop and title, and `#/anchor/earning-history` rendered the trail separately in
 * a different rail group. They are one subject. The current agreement is the claim, the trail is
 * the evidence behind it, and the recommendation is what follows — a reader needs all three at once
 * to decide whether to apply a loosening.
 *
 * The doctrine line stays verbatim because it IS the rule, not UI copy: loosening is earned, never
 * configured, and a human applies it.
 */
export function Autonomy({ data }) {
  const a = data.anchor || {}
  const rungs = a.rungs || {}
  const demote = a.autonomy_demote || {}
  const rows = data.calibration || []
  const eligible = rows.filter((c) => c.recommendation === 'eligible-to-loosen').length

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Autonomy</h2>
        <span style={{ flex: 1 }} />
        {a.version != null && <span className="money">anchor v{a.version}</span>}
      </div>
      <p className="note" style={{ marginTop: 4 }}>
        WHAT EACH RUNG IS TRUSTED WITH · AND WHAT EARNED IT
      </p>

      <div className="seams">
        {/* 1 · THE CLAIM. What the dials are now, before any evidence for changing them. */}
        {Object.keys(rungs).length > 0 && (
          <div className="seam">
            <div className="seam-hd">
              <span className="seam-slot">TRUSTED NOW</span>
              <span className="seam-what">What each rung may do without asking you.</span>
              <span className="seam-st seam-st-deflt">FROM ANCHOR</span>
            </div>
            <div className="au-dials">
              {Object.entries(rungs).map(([name, r]) => (
                <React.Fragment key={name}>
                  <div className="au-rung">{name}</div>
                  <div className="au-dial">{r.dial}</div>
                  <div className="au-why">{DIAL_MEANS[r.dial] || ''}</div>
                  <div className="au-n">{r.est_usd == null ? '—' : `$${Number(r.est_usd).toFixed(2)}`}</div>
                </React.Fragment>
              ))}
            </div>
          </div>
        )}

        {/* 2 · THE EVIDENCE. */}
        <EarningHistory embedded />

        {/* 3 · THE CONCLUSION, and where to act on it. Its own card — this used to be the last
            column of a six-column table: the one thing the screen exists to deliver, in the
            position the eye reaches last, worded like a verb and attached to nothing. */}
        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">WHAT FOLLOWS</span>
            <span className="seam-what">What the trail earns, and where the change is made.</span>
            <span className={`seam-st seam-st-${eligible ? 'attn' : 'deflt'}`}>
              {eligible} ELIGIBLE
            </span>
          </div>
          {rows.length === 0 ? (
            <div className="seam-empty">
              No decisions recorded yet, so nothing is recommended. A dial is not loosened on an
              empty ledger.
            </div>
          ) : (
            <div className="au-rec">
              {rows.map((c) => (
                <React.Fragment key={c.rung}>
                  <div className="au-r-rung">{c.rung}</div>
                  <div><span className={`au-pill au-${c.recommendation}`}>
                    {String(c.recommendation || '—').replace(/-/g, ' ').toUpperCase()}
                  </span></div>
                  <div className="au-r-do">
                    {c.agreement == null
                      ? 'No agreement recorded.'
                      : `${Math.round(c.agreement * 100)}% over ${c.decisions} decision${c.decisions === 1 ? '' : 's'}.`}
                    {c.decisions != null && c.decisions < 5 && (
                      <> <b>Not a track record yet</b> — read the trend as noise until the window fills.</>
                    )}
                  </div>
                </React.Fragment>
              ))}
            </div>
          )}
          <div className="au-doctrine">
            <b>There is no button here on purpose.</b> Loosening needs an earned track record and a
            human applies it; tightening is always allowed and the trigger does it by itself at{' '}
            <code>agreement_threshold {demote.agreement_threshold ?? '—'}</code> over{' '}
            <code>window {demote.window ?? '—'}</code>. Both live in{' '}
            <a href={`${import.meta.env.BASE_URL}anchor/console`}>Budgets &amp; funnel → Autonomy demote</a>, and a dial
            changes by pull request against <code>ANCHOR.md</code> — the running system is never
            live-poked.
          </div>
        </div>
      </div>

      <p className="note seam-foot">
        Claim, then evidence, then what follows. Cost and human-latency per verdict moved out of
        the decision path — they are real, but they are not what a loosening turns on.
      </p>
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

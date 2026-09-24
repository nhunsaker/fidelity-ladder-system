// System · Feeder — propose ideas, then let the gate decide.
//
// This replaced a three-step Wizard around a single textarea, which is the case Tidwell warns
// about explicitly ("the need for a Wizard often signals the task is too complex — simplify it
// away if you can"). It also replaced two statements that were not true:
//
//   1. The params were HARDCODED {5, $5, 30000} under the caption "All from the ANCHOR's feeder
//      block". They now come from `GET /anchor`, and the card says whether they are the ANCHOR's
//      or the engine's — see `params_set`.
//   2. BOTH paths were dry runs. `POST /feeder/run` called ListSink ("in-memory sink for tests /
//      dry runs") and the UI reported "N filed", which an operator reads as "N idea-issues now
//      exist". The endpoint now takes `dry_run` and names its sink; this screen shows the sink
//      in the result so a dry run can never again be described as a real one.
//
// Read-only except for scope and the two buttons: the caps are POLICY and change by PR.
import React, { useState } from 'react'
import { api } from '../api.js'
import Icon from '../icons.jsx'

/** The authored half of each governing param. The values come from `/anchor`.
 *  Order is deliberate: what it costs you first, what it reads second, how it runs last. */
const PARAMS = [
  ['volume_cap', 'VOLUME CAP', 'Top proposals kept per run. The rest are dropped.',
    (v) => String(v), 'funnel'],
  ['cost_envelope_usd', 'COST ENVELOPE',
    "Bounds one run's shadow cost. The subscription lane meters $0, but the tokens still count.",
    (v) => `$${Number(v).toFixed(2)}`, 'coins'],
  ['context_cap_tokens', 'CONTEXT CAP',
    'Hard truncation on any workspace context fed to the prompt.',
    (v) => Number(v).toLocaleString(), 'scissors'],
  ['model_tier', 'MODEL TIER', 'Which tier ideates.', (v) => String(v), 'cpu'],
  ['cadence', 'CADENCE', 'Nothing runs unless a human presses a button.', (v) => String(v),
    'clock'],
  ['guardrails_into_prompt', 'GUARDRAILS',
    "The ANCHOR's non-negotiables shape ideation, not only the gate that judges it.",
    (v) => (v ? 'in prompt' : 'gate only'), 'shield-check'],
  ['grounding', 'GROUNDING', 'A grounding pack folded into ideation. Empty means off.',
    (v) => (v ? String(v) : 'off'), 'anchor'],
]

/** A run's result, stated in terms the operator can check. `sink` is the load-bearing field:
 *  it is the engine naming where the ideas actually went. */
function Result({ run, anchorScope }) {
  if (!run) return null
  if (!run.triggered) {
    return (
      <div className="fd-res fd-res-bad">
        <div className="fd-rh"><span className="fd-rt">Refused — nothing ran</span></div>
        <p className="fexp" style={{ margin: 0 }}>{run.reason}</p>
      </div>
    )
  }
  const dry = run.dry_run
  const cost = `$${(run.cost_usd ?? 0).toFixed(4)} METERED / $${(run.normalized_usd ?? 0).toFixed(4)} SHADOW`
  return (
    <div className="fd-res">
      <div className="fd-rh">
        <span className="fd-rt">
          {dry ? `Previewed ${run.proposed} proposals · filed 0`
               : `Filed ${run.filed} of ${run.proposed} proposed`}
        </span>
        <span className="fd-rs">
          SINK: {String(run.sink || '—').toUpperCase()} · {cost} ·{' '}
          {run.within_envelope ? 'WITHIN ENVELOPE' : 'OVER ENVELOPE'}
          {run.scope && run.scope !== anchorScope ? ' · STEERED' : ''}
        </span>
      </div>
      {run.ideas?.length > 0 ? (
        <div className="fd-plist">
          {run.ideas.map((c, i) => (
            <React.Fragment key={i}>
              <div className="fd-i">{i + 1}</div>
              <div className="fd-p">{c.intent}</div>
              <div className="fd-lbl">{String(c.altitude || '').toUpperCase()}</div>
            </React.Fragment>
          ))}
        </div>
      ) : (
        <p className="fexp" style={{ margin: 0 }}>
          The run completed and proposed nothing. Scope is the usual reason — too narrow, or
          aimed at ground the vessel does not cover.
        </p>
      )}
    </div>
  )
}

/** @param {{data: any, toast: (s: string) => void}} props */
export default function Feeder({ data, toast }) {
  const fd = data?.anchor?.feeder || null
  // Scope is the ANCHOR's when it sets one; the box starts there and the operator may steer a
  // single run without editing policy. An empty ANCHOR scope starts empty — never invented.
  const [scope, setScope] = useState(fd?.scope || '')
  const [run, setRun] = useState(null)
  const [busy, setBusy] = useState(null)

  const go = async (dry) => {
    setBusy(dry ? 'preview' : 'file')
    try {
      const r = await api.feederRun({ scope, dry_run: dry })
      setRun(r)
      if (!r.triggered) toast(`Feeder refused: ${r.reason}`)
      else if (r.dry_run) toast(`Previewed ${r.proposed} — nothing filed`)
      else toast(`Filed ${r.filed} of ${r.proposed} — the gate decides next`)
    } catch (ex) {
      // Same guess, same problem: the feeder refuses for stated reasons (no builder, cost
      // envelope, an empty scope) and "unreachable" points the operator at the network instead.
      const why = ex?.message || 'the harness refused'
      setRun({ triggered: false, reason: `${why} — nothing ran (fail-closed)` })
      toast(`Nothing ran: ${why}`)
    } finally {
      setBusy(null)
    }
  }

  if (!fd) {
    return (
      <div className="pane"><div className="card card-pad"><p className="note" style={{ margin: 0 }}>
        /anchor is unreachable — the feeder's governing params are unavailable offline, and this
        screen will not show numbers it cannot source. Run against the live harness to use it.
      </p></div></div>
    )
  }

  return (
    <div className="pane">
      <div className="detail-head">
        <h2 style={{ margin: 0 }}>Feeder</h2>
        <span style={{ flex: 1 }} />
        {data.anchor?.version != null && <span className="money">anchor v{data.anchor.version}</span>}
      </div>
      <p className="note" style={{ marginTop: 4 }}>PROPOSES IDEAS · THE GATE STILL DECIDES</p>

      <div className="seams">

        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">WHAT THIS DOES</span>
            <span className="seam-what">The one thing to understand before you press anything.</span>
          </div>
          <div className="fd-prose">
            <p>The feeder <b>proposes</b> ideas. It cannot admit them. Everything it proposes goes
              through the same admission gate as an idea you file by hand, and the gate decides
              admit, dock, or needs-human — exactly as it would for you.</p>
            <p>It holds no policy of its own. Every number below comes from the ANCHOR, and the
              only thing you set here is the scope.</p>
          </div>
        </div>

        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">WHAT GOVERNS THIS RUN</span>
            <span className="seam-what">Read live from this instance's ANCHOR, not from the screen.</span>
            <span className={`seam-st seam-st-${fd.params_set ? 'active' : 'deflt'}`}>
              {fd.params_set ? 'FROM ANCHOR' : 'ENGINE DEFAULTS'}
            </span>
          </div>
          <div className="fd-rows">
            {PARAMS.map(([key, label, what, fmt, icon]) => (
              <React.Fragment key={key}>
                <div className="seam-k"><Icon name={icon} className="k-ico" />{label}</div>
                <div className="seam-v">{what}</div>
                <div className={`fd-n${fd[key] ? '' : ' fd-n-off'}`}>{fmt(fd[key])}</div>
              </React.Fragment>
            ))}
          </div>
          {!fd.params_set && (
            <div className="seam-empty">
              Your ANCHOR sets no feeder <code>params:</code>, so these are the engine's defaults.
              Declare a <code>feeder</code> idea source with a <code>params:</code> block to change
              them — it is policy, so it changes by PR.
            </div>
          )}
        </div>

        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">SCOPE</span>
            <span className="seam-what">The only thing you set on this screen.</span>
          </div>
          <div className="fd-scope">
            <p className="fexp">One line steering what gets proposed. It is the strongest lever you
              have — ideas outside it tend to dock at the gate anyway, so keep it tight.</p>
            <textarea id="fd-scope" className="in" rows={3} value={scope}
                      aria-label="Scope for this feeder run"
                      onChange={(e) => setScope(e.target.value)} />
            {fd.scope && scope !== fd.scope && (
              <p className="fexp" style={{ marginBottom: 0 }}>
                Steering this run only — the ANCHOR's scope is untouched, and the next run without
                an edit uses it again. The guardrails, the cap and the gate all still apply.
              </p>
            )}
          </div>
        </div>

        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">RUN IT</span>
            <span className="seam-what">Two different acts. The second one files.</span>
          </div>
          <div className="fd-acts">
            <div className="fd-act">
              <div className="fd-at">Preview</div>
              <div className="fd-ad">Proposes, and shows you the list. <b>Files nothing.</b> Leaving
                this screen discards it.</div>
              <div className="fd-sink">SINK: DRY-RUN</div>
              <button className="btn" disabled={!!busy} onClick={() => go(true)}>
                {busy === 'preview' ? 'Previewing…' : 'Preview a run'}
              </button>
            </div>
            <div className="fd-act">
              <div className="fd-at">File through the gate</div>
              <div className="fd-ad">Files every proposal as an idea. The admission gate then judges
                each one. <b>This spends money and creates work.</b></div>
              <div className="fd-sink">SINK: ADMISSION</div>
              <button className="btn btn-acc" disabled={!!busy} onClick={() => go(false)}>
                {busy === 'file' ? 'Filing…' : 'File through the gate'}
              </button>
            </div>
          </div>
          <Result run={run} anchorScope={fd.scope} />
        </div>

        <div className="seam">
          <div className="seam-hd">
            <span className="seam-slot">NIGHTLY SCHEDULE</span>
            <span className="seam-what">Runs the feeder without a human pressing anything.</span>
            <span className="seam-st seam-st-attn">
              {fd.cadence === 'manual' ? 'NOT ARMED' : `CADENCE: ${String(fd.cadence).toUpperCase()}`}
            </span>
          </div>
          <div className="fd-rows fd-rows-two">
            <div className="seam-k">WHAT WOULD ARM IT</div>
            <div className="seam-v"><code>cadence: nightly</code> in the ANCHOR's feeder params, and
              a scheduler registered in <code>FLS_MODULES</code>.</div>
            <div className="seam-k">WHY NOT A TOGGLE</div>
            <div className="seam-v">Arming an unattended feeder is one of the gates a human always
              owns. It changes by PR, deliberately — not by a switch on this screen.</div>
          </div>
        </div>
      </div>

      <p className="note seam-foot">
        The feeder can never admit its own proposals. <b>Policy</b> — the caps, the cadence, the
        guardrails — lives in the ANCHOR and changes by PR. This screen sets scope and presses the
        button; everything else it only reports.
      </p>
    </div>
  )
}

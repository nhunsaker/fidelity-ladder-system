// The sign-in layout, shared by the workbench and the demo.
//
// Design: "FLS Sign in", approved 2026-09-12. Split screen — the form gets a quiet column with
// nothing competing, the brand gets the other half and does the talking.
//
// The right panel is not decoration. The FLS design system opens with "fidelity made visible:
// coarse pixels resolve into crisp vector", so the panel reads left to right as scattered pixels
// becoming the five rungs and then becoming clean bars. The picture IS the product, which is the
// only reason a picture belongs on a sign-in page at all.
//
// One layout for both doors because they are the same system asking the same question; only the
// credentials differ, and each side names the other so nobody lands on the wrong one with no way
// across.
import React from 'react'
import LadderAscent from './LadderAscent.jsx'

/** @param {{title: string, blurb?: React.ReactNode, children: React.ReactNode,
 *           notice?: React.ReactNode, foot?: React.ReactNode, other?: React.ReactNode}} props */
export default function SignInShell({ title, blurb, notice, children, foot, other }) {
  return (
    <div className="si">
      <main className="si-form">
        <div className="si-mark">
          <img src={`${import.meta.env.BASE_URL}brand/mark-full.svg`} width="30" height="30" alt="" />
          <span className="wm">FIDELITY<br />LADDER</span>
        </div>
        <div className="si-box">
          <h1 className="si-h">{title}</h1>
          {notice}
          {blurb && <p className="si-sub">{blurb}</p>}
          {children}
          {foot && <p className="si-foot">{foot}</p>}
        </div>
        {other && <p className="si-foot si-other">{other}</p>}
      </main>
      <div className="si-brand" aria-hidden="true">
        {/* Sumi Ascent: ink climbing through the logo's own three textures — blue hand, yellow
            pixel, red resolved. The static dissolve stays underneath as the ground the canvas is
            painted over, so a browser without WebGL still gets a brand panel rather than a hole. */}
        <img className="pix" src={`${import.meta.env.BASE_URL}brand/ladder-dissolve.svg`} alt="" />
        <LadderAscent />
        <div className="veil" />
        <div className="say">
          <p className="si-eyebrow">FIDELITY LADDER SYSTEM</p>
          <p className="si-head">Rough sketch to real code, one rung at a time.</p>
          <p className="si-line">Nothing climbs a rung without a person saying so — and the ledger
            shows it, or it did not happen.</p>
          {/* The five steps, in the SAME tense the run itself uses. These were past participles
              — REQUESTED, WIREFRAMED — which is the first thing a visitor reads and it promised
              a list of things that have happened, on a ladder where four of the five have not.
              The engine renamed them (demo.STAGES) and this hardcoded copy did not follow, so
              the door and the room behind it disagreed. Kept in the same order and the same
              words; the check mark carries "done", not the tense. */}
          <div className="si-rungs">
            <span>REQUEST</span><span>WIREFRAME</span><span>PREVIEW</span>
            <span>BUILD</span><span>SHIP</span>
          </div>
        </div>
      </div>
    </div>
  )
}

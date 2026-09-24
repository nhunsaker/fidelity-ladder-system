// SUMI ASCENT — the sign-in panel, painted rather than shipped.
//
// A WebGL port of `SumiAscent.metal` from the woords effects lab (Utsuroi · Sumi Ascent): sumi ink
// in water climbing a vertical depth gradient — dense plumes bloom upward through a shallow
// volume, band into horizontal tomographic strata at the peak, then bleed sideways and settle.
// The maths is the shader's, line for line: domain-warp turbulence, a rising front driven by
// density, strata snapped toward regular spacing by an order dial, lateral spread on the decay.
//
// WHY IT BELONGS ON THIS PAGE, rather than being a nice effect borrowed from another product:
// the colours come from "FLS Logo A — Explorations", where the three letters carry the climb as
// texture — F handwritten in BLUE (the human draft), L pixel in YELLOW (the machine), S regular
// in RED (resolved vector). So the ink ascends through that progression: it enters blue, passes
// through yellow as the strata sharpen, and resolves red at the front. The panel is the ladder,
// the same claim the page next to it makes, told in ink instead of pixels.
//
// READABILITY IS A CONSTRAINT, NOT AN AFTERTHOUGHT. The copy sits at the bottom of the panel, so
// the field is damped there in the shader itself (`quiet`) and a veil sits over it in CSS. The
// animation is never allowed to decide whether the words can be read.
import React, { useEffect, useRef } from 'react'

const VERT = `
attribute vec2 a;
void main() { gl_Position = vec4(a, 0.0, 1.0); }
`

// Ported from SumiAscent.metal. Names kept so the two can be read side by side.
const FRAG = `
precision highp float;
uniform vec2  u_res;
uniform float u_phase;
uniform float u_density;
uniform float u_noise;
uniform float u_order;
uniform float u_scale;
uniform vec3  u_paper;   // the ground the ink sits in
uniform vec3  u_hand;    // blue  — the human draft
uniform vec3  u_pixel;   // yellow — the machine
uniform vec3  u_vector;  // red   — resolved

float sa_hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float sa_vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  float a = sa_hash(i), b = sa_hash(i + vec2(1.0, 0.0));
  float c = sa_hash(i + vec2(0.0, 1.0)), d = sa_hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

void main() {
  // Bottom-left origin, in CSS pixels, so the plume climbs the way the Metal version does.
  vec2 pos = vec2(gl_FragCoord.x, u_res.y - gl_FragCoord.y);
  vec2 uv = pos / max(u_scale, 1.0);

  // Domain warp — plume turbulence rises with the noise dial.
  vec2 warp = vec2(sa_vnoise(uv + u_phase), sa_vnoise(uv * 1.3 - u_phase)) - 0.5;
  uv += warp * (1.4 * clamp(u_noise, 0.0, 1.0));

  // Vertical depth reference. The Metal version normalises against a ~square stage; this panel is
  // tall and narrow, so depth is taken against the panel's own height instead of a fixed 40pt —
  // otherwise the entire visible field sits inside the first fortieth of the gradient and the
  // plume never reads as climbing anything.
  float depth = clamp(pos.y / u_res.y, 0.0, 1.0);
  float cover = clamp(u_density, 0.0, 1.0);

  // The front: ink fills from the bottom up. At cover=0 it sits below the stage, at cover=1 above.
  float front = mix(1.05, -0.05, cover);
  float riseDist = (depth - front) + warp.x * 0.5 * clamp(u_noise, 0.0, 1.0);
  float plume = smoothstep(-0.15, 0.15, riseDist);

  // Horizontal tomographic strata, snapped toward regular spacing as order rises.
  float cellY = 0.42;
  float yRaw = uv.y;
  float ySnap = (floor(yRaw / cellY) + 0.5) * cellY;
  float yBand = mix(yRaw, ySnap, clamp(u_order, 0.0, 1.0));
  float bandPhase = fract(yBand / cellY);
  float strata = 0.5 + 0.5 * cos(bandPhase * 6.2831853 - u_phase * 0.5);
  float sharpness = mix(0.15, 0.85, clamp(u_order, 0.0, 1.0));
  float bands = smoothstep(0.5 - sharpness * 0.5, 0.5 + sharpness * 0.5, strata);

  // Lateral bleed on the decay.
  float bleed = 1.0 - cover;
  float lateral = sa_vnoise(vec2(uv.x * 0.6, yBand * 0.6) + u_phase * 0.2);
  float spread = smoothstep(0.35, 0.85, lateral) * bleed * 0.6;

  float field = clamp(plume * mix(1.0, bands, 0.65) + spread, 0.0, 1.0);

  // THE CLIMB AS COLOUR — the three textures from the logo explorations, in the proportions the
  // token file asks for: "one dominant per surface, never all three shouting." Blue is the body
  // and holds the panel. Yellow rides only the sharpening strata EDGES through the middle. Red
  // resolves in the last stretch, and only where the bands are crisp — so "resolved" tracks the
  // thing that is actually resolving instead of a height.
  //
  // The first version mixed blue straight into yellow across the whole climb, and the panel came
  // out amber: three colours shouting, and none of them the brand's primary.
  float up = 1.0 - depth;
  vec3 ink = u_hand;
  ink = mix(ink, u_pixel, smoothstep(0.5, 0.95, bands) * smoothstep(0.2, 0.8, up) * 0.6);
  ink = mix(ink, u_vector, smoothstep(0.78, 1.0, up) * smoothstep(0.55, 1.0, bands) * 0.75);

  // The words live at the bottom. Damp the field there so the ink never argues with them, and do
  // it here rather than only in CSS — a veil dark enough to guarantee contrast over full-strength
  // ink would flatten the whole panel.
  float quiet = smoothstep(0.0, 0.42, up);
  float f = field * mix(0.16, 1.0, quiet);

  vec3 tone = mix(u_paper, ink, f);
  // The thinnest ink hazes toward the blue it came from, not toward a fourth colour.
  tone = mix(tone, u_hand, f * (1.0 - f) * 0.5 * quiet);
  gl_FragColor = vec4(tone, 1.0);
}
`

const hex = (h) => [parseInt(h.slice(1, 3), 16) / 255,
                    parseInt(h.slice(3, 5), 16) / 255,
                    parseInt(h.slice(5, 7), 16) / 255]

// The FLS palette, straight from brand/tokens.css and the logo explorations.
const PAPER = hex('#2b2823')   // --a-gate: the dark warm ground white text rides on
const HAND = hex('#005eb8')    // --a-blue
const PIXEL = hex('#fdb913')   // --a-yellow
const VECTOR = hex('#e63329')  // --a-red

/** The density envelope: build → peak → decay, the motion the Lab drives on iOS.
 *  A long, slow breath — this sits behind a sign-in form, not on a title screen. */
function envelope(t) {
  const cycle = 26                       // seconds for one full ascent and settle
  const x = (t % cycle) / cycle
  // rise over the first 45%, hold, then a long decay where the lateral bleed does its work
  if (x < 0.45) return Math.pow(x / 0.45, 0.85)
  if (x < 0.62) return 1
  return Math.pow(1 - (x - 0.62) / 0.38, 1.6)
}

export default function LadderAscent() {
  const ref = useRef(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const gl = canvas.getContext('webgl', { antialias: false, alpha: false, depth: false })
    // No WebGL (old browser, blocked context, a headless screenshot): the CSS keeps the flat
    // brand ground underneath and the panel still reads. An effect is never load-bearing.
    if (!gl) { canvas.style.display = 'none'; return }

    const compile = (type, src) => {
      const s = gl.createShader(type)
      gl.shaderSource(s, src); gl.compileShader(s)
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s))
      return s
    }
    let prog
    try {
      prog = gl.createProgram()
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT))
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG))
      gl.linkProgram(prog)
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog))
    } catch {
      canvas.style.display = 'none'; return
    }
    gl.useProgram(prog)

    const buf = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buf)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
    const loc = gl.getAttribLocation(prog, 'a')
    gl.enableVertexAttribArray(loc)
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0)

    const U = (n) => gl.getUniformLocation(prog, n)
    const uRes = U('u_res'), uPhase = U('u_phase'), uDensity = U('u_density')
    gl.uniform1f(U('u_noise'), 0.4)      // the lab's defaults
    gl.uniform1f(U('u_order'), 0.34)
    gl.uniform3fv(U('u_paper'), PAPER)
    gl.uniform3fv(U('u_hand'), HAND)
    gl.uniform3fv(U('u_pixel'), PIXEL)
    gl.uniform3fv(U('u_vector'), VECTOR)

    let w = 0, h = 0
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const cw = canvas.clientWidth, ch = canvas.clientHeight
      if (!cw || !ch) return false
      w = Math.round(cw * dpr); h = Math.round(ch * dpr)
      canvas.width = w; canvas.height = h
      gl.viewport(0, 0, w, h)
      gl.uniform2f(uRes, w, h)
      // Scale with the panel so the plume is the same size relative to the panel at any width;
      // a fixed point scale made the field microscopic on a large display.
      gl.uniform1f(U('u_scale'), Math.max(28, ch * dpr * 0.055))
      return true
    }

    const still = window.matchMedia('(prefers-reduced-motion: reduce)')
    let raf = 0
    const t0 = performance.now()

    const frame = (now) => {
      if (resize() !== false) {
        // Reduced motion gets the dense peak, held: the picture without the movement, which is
        // what the iOS lab does too. Not a blank panel — the still frame is the point.
        const t = still.matches ? 7.4 : (now - t0) / 1000
        gl.uniform1f(uPhase, still.matches ? 1.6 : t * 0.14)
        gl.uniform1f(uDensity, still.matches ? 0.92 : envelope(t))
        gl.drawArrays(gl.TRIANGLES, 0, 3)
      }
      raf = still.matches ? 0 : requestAnimationFrame(frame)
    }
    frame(performance.now())

    // Stop when the tab is hidden — a sign-in page left open in a background tab has no business
    // holding a GPU loop.
    const vis = () => {
      if (document.hidden) { cancelAnimationFrame(raf); raf = 0 }
      else if (!raf && !still.matches) raf = requestAnimationFrame(frame)
    }
    document.addEventListener('visibilitychange', vis)
    const onMotion = () => { cancelAnimationFrame(raf); raf = 0; frame(performance.now()) }
    still.addEventListener?.('change', onMotion)

    return () => {
      cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', vis)
      still.removeEventListener?.('change', onMotion)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
  }, [])

  return <canvas ref={ref} className="si-canvas" aria-hidden="true" />
}

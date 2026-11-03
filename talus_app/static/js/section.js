// Talus — the cross-section as SVG: layers, water, slices, the critical surface,
// trial surfaces and loads. Drawn to scale (1 m across = 1 m up).
import { layerPolys, pondPoly, massPoly, extent, colourOf, rampColour, fosColour } from "./shapes.js";
import { yAt } from "../engine/geometry.js";

const NS = "http://www.w3.org/2000/svg";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Returns SVG markup for a section. W, H in px. */
export function sectionSVG(result, c, opt = {}) {
  const W = opt.width || 900, H = opt.height || 480;
  const g = result.geometry;
  const e = extent(g);
  const pad = 28;
  const top = Math.max(e.y1, ...(c?.piezo || []).map((p) => p[1])) + 0.08 * (e.x1 - e.x0);
  const sx = (W - 2 * pad) / (e.x1 - e.x0), sy = (H - 2 * pad) / (top - e.y0);
  const s = Math.min(sx, sy);
  const ox = pad + ((W - 2 * pad) - s * (e.x1 - e.x0)) / 2, oy = pad + ((H - 2 * pad) - s * (top - e.y0)) / 2;
  const X = (x) => ox + (x - e.x0) * s, Y = (y) => H - oy - (y - e.y0) * s;
  const path = (pts, close = true) => pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("") + (close ? "Z" : "");
  const out = [];
  out.push(`<svg xmlns="${NS}" viewBox="0 0 ${W} ${H}" class="section" role="img" aria-label="Cross-section">`);
  out.push(`<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="rgba(0,0,0,.18)" stroke-width="1"/></pattern>
    <marker id="arr" viewBox="0 0 8 8" refX="4" refY="7" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L8,0 L4,8z" fill="#eb6834"/></marker></defs>`);
  // grid
  const step = niceStep((e.x1 - e.x0) / 8);
  for (let x = Math.ceil(e.x0 / step) * step; x <= e.x1; x += step)
    out.push(`<line x1="${X(x)}" y1="${Y(e.y0)}" x2="${X(x)}" y2="${Y(top)}" stroke="var(--grid)" stroke-width="0.6"/><text x="${X(x) + 2}" y="${Y(e.y0) + 12}" font-size="10" fill="var(--muted)">${round(x)}</text>`);
  for (let y = Math.ceil(e.y0 / step) * step; y <= top; y += step)
    out.push(`<line x1="${X(e.x0)}" y1="${Y(y)}" x2="${X(e.x1)}" y2="${Y(y)}" stroke="var(--grid)" stroke-width="0.6"/><text x="${X(e.x0) + 2}" y="${Y(y) - 2}" font-size="10" fill="var(--muted)">${round(y)}</text>`);
  // layers
  const polys = layerPolys(g);
  polys.forEach((L, k) => out.push(`<path d="${path(L.poly)}" fill="${colourOf(L.name, k)}" stroke="rgba(0,0,0,.25)" stroke-width="0.6"/>`));
  out.push(`<path d="${path([[e.x0, g.bottom], [e.x1, g.bottom], [e.x1, g.bottom - 0.6 / s * 6], [e.x0, g.bottom - 0.6 / s * 6]])}" fill="url(#hatch)"/>`);
  // water
  const piezo = c?.piezo || g.piezo;
  const pond = pondPoly(g, piezo);
  if (pond) out.push(`<path d="${path(pond)}" fill="rgba(42,120,214,.28)" stroke="none"/>`);
  if (piezo) out.push(`<path d="${path(piezo, false)}" fill="none" stroke="#2a78d6" stroke-width="1.6" stroke-dasharray="6 4"/>`);
  if (piezo) {
    const xs = piezo.find(([x, y]) => y > yAt(g.ground, x) + 0.05) || piezo[0];
    out.push(`<path d="M${X(xs[0]) + 14},${Y(xs[1]) - 9} l6,8 l6,-8z" fill="#2a78d6"/>`);
  }
  // trial surfaces
  if (opt.trials && c?.trials?.length) {
    const Fmin = c.trials[0].F;
    for (const t of c.trials.slice().reverse()) {
      const arc = arcPoints(t.circle, Math.min(t.xe, t.xx), Math.max(t.xe, t.xx), 40);
      out.push(`<path d="${path(arc, false)}" fill="none" stroke="${rampColour(t.F, Fmin)}" stroke-width="0.9" opacity="0.65"/>`);
    }
  }
  // the sliding mass and its slices
  if (c?.surface?.slip) {
    const mass = massPoly(g, c.surface.slip);
    const col = fosColour(c.F, c.target);
    out.push(`<path d="${path(mass)}" fill="${col}" fill-opacity="0.18" stroke="none"/>`);
    if (opt.slices !== false && c.slices) {
      for (const sl of c.slices) {
        const x = sl.x1;
        const yb = yAt(c.surface.slip, x), yg = yAt(g.ground, x);
        if (yg - yb > 1e-3) out.push(`<line x1="${X(x)}" y1="${Y(yb)}" x2="${X(x)}" y2="${Y(yg)}" stroke="rgba(0,0,0,.28)" stroke-width="0.6"/>`);
      }
    }
    out.push(`<path d="${path(c.surface.slip, false)}" fill="none" stroke="${col}" stroke-width="3" stroke-linejoin="round"/>`);
    if (c.surface.circle) {
      const { xc, yc } = c.surface.circle;
      if (yc < top + 0.3 * (top - e.y0)) {
        out.push(`<circle cx="${X(xc)}" cy="${Y(Math.min(yc, top))}" r="3" fill="${col}"/>`);
      }
    }
    if (c.surface.crack) {
      const cr = c.surface.crack;
      out.push(`<line x1="${X(cr.x)}" y1="${Y(cr.y)}" x2="${X(cr.x)}" y2="${Y(cr.y + cr.depth)}" stroke="${col}" stroke-width="2" stroke-dasharray="3 2"/>`);
    }
    // the answer, beside the surface
    const mid = c.surface.slip[Math.floor(c.surface.slip.length / 2)];
    out.push(`<g transform="translate(${X(mid[0])},${Y(mid[1]) + 22})"><rect x="-34" y="-14" width="68" height="22" rx="6" fill="var(--surface)" stroke="${col}"/><text x="0" y="2" text-anchor="middle" font-size="13" font-weight="700" fill="${col}">F ${c.F.toFixed(2)}</text></g>`);
  }
  // surcharge
  for (const st of c?.strips || []) {
    const n = Math.max(2, Math.round((st.x2 - st.x1) * s / 26));
    for (let i = 0; i <= n; i++) {
      const x = st.x1 + (st.x2 - st.x1) * i / n, y = yAt(g.ground, x);
      out.push(`<line x1="${X(x)}" y1="${Y(y) - 22}" x2="${X(x)}" y2="${Y(y) - 3}" stroke="#eb6834" stroke-width="1.4" marker-end="url(#arr)"/>`);
    }
    out.push(`<text x="${X((st.x1 + st.x2) / 2)}" y="${Y(yAt(g.ground, st.x1)) - 26}" text-anchor="middle" font-size="11" fill="#eb6834">${round(st.q)} kPa</text>`);
  }
  // reinforcement
  for (const r of opt.reinforcement || []) {
    const a = r.angle * Math.PI / 180, dir = r.dir;
    out.push(`<line x1="${X(r.x)}" y1="${Y(r.y)}" x2="${X(r.x + dir * r.length * Math.cos(a))}" y2="${Y(r.y - r.length * Math.sin(a))}" stroke="#4a3aa7" stroke-width="2"/>`);
  }
  // seismic arrow
  if (c?.seismic) {
    const dir = opt.faceDir || -1;
    const x = (e.x0 + e.x1) / 2, y = top - 0.04 * (top - e.y0);
    out.push(`<g stroke="#e34948" fill="#e34948"><line x1="${X(x) - dir * 30}" y1="${Y(y)}" x2="${X(x) + dir * 30}" y2="${Y(y)}" stroke-width="2"/><path d="M${X(x) + dir * 36},${Y(y)} l${-dir * 8},-5 l0,10z"/></g><text x="${X(x)}" y="${Y(y) - 8}" text-anchor="middle" font-size="11" fill="#e34948">kh ${c.seismic.kh.toFixed(3)} · kv ±${Math.abs(c.seismic.kv).toFixed(3)}</text>`);
  }
  out.push(`</svg>`);
  return out.join("");
}

function arcPoints(c, a, b, n) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const x = a + (b - a) * i / n;
    pts.push([x, c.yc - Math.sqrt(Math.max(0, c.R * c.R - (x - c.xc) ** 2))]);
  }
  return pts;
}

function niceStep(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
const round = (v) => Math.round(v * 100) / 100;
export { esc };

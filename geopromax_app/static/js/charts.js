// SVG charts: settlement with time, stresses with depth, and the cross-section.
// They use the page's colour tokens, so they follow the light and dark themes,
// and they print as they are in the report.

import { layerTops } from "../engine/settlement.js";
import { contour, levels } from "./plan.js";
import { grossPressure, outline, foundingDepth, equivalentRaft } from "../engine/stress.js";

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = (v, d = 1) => (Number.isFinite(v) ? (+v.toFixed(d)).toString() : "–");

function niceStep(span, target) {
  if (!(span > 0)) return 1;
  const raw = span / target, p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((k) => k * p).find((s) => s >= raw);
}
const ticks = (a, b, target = 6) => {
  const s = niceStep(b - a, target), out = [];
  for (let v = Math.ceil(a / s - 1e-9) * s; v <= b + 1e-9; v += s) out.push(+v.toFixed(10));
  return out;
};

export const SOIL_COLOURS = {
  peat: "#5a4a3c", organic: "#6b5a49", marineClay: "#a3b0bb", softClay: "#9aa7b3", firmClay: "#8f9aa5", stiffClay: "#77828c", hardClay: "#646e77",
  softSilt: "#cbbfa8", silt: "#c2b49a", loess: "#d8c9a0",
  looseSand: "#e6d3a3", siltySand: "#decb9c", clayeySand: "#cfbb8f", sand: "#dcc58e", denseSand: "#cdb06d", gravel: "#bfa46a",
  fill: "#b9a27e", looseFill: "#c4b08f", rockfill: "#a39a8a", residual: "#b58f6b",
  rock: "#8c8578", mudstone: "#8a8f86", chalk: "#d9d8cf", soundRock: "#6f6a60",
};
export const soilColour = (l, i) => SOIL_COLOURS[l.preset] || ["#d9c79a", "#9aa7b3", "#c9b183", "#808b95"][i % 4];

/** Settlement (mm, down) against time (years, log scale). */
export function timeChart(curve, opts = {}) {
  const W = 640, H = 300, L = 54, R = 16, T = 16, B = 40;
  if (!curve?.length) return "";
  const t1 = curve[0].t, t2 = curve[curve.length - 1].t;
  const smax = Math.max(1e-6, ...curve.map((p) => p.total)) * 1000 * 1.08;
  const X = (t) => L + ((Math.log10(t) - Math.log10(t1)) / (Math.log10(t2) - Math.log10(t1))) * (W - L - R);
  const Y = (s) => T + (s / smax) * (H - T - B);
  const path = (key) => curve.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p[key] * 1000).toFixed(1)}`).join("");
  const stackPrimary = curve.map((p, i) => `${i ? "L" : "M"}${X(p.t).toFixed(1)},${Y((p.immediate + p.primary) * 1000).toFixed(1)}`).join("");
  let g = "";
  for (const v of ticks(0, smax)) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--grid)"/><text x="${L - 6}" y="${Y(v) + 3}" text-anchor="end">${n(v, 1)}</text>`;
  for (let e = Math.ceil(Math.log10(t1)); e <= Math.floor(Math.log10(t2)); e++) {
    const t = 10 ** e;
    g += `<line x1="${X(t)}" x2="${X(t)}" y1="${T}" y2="${H - B}" stroke="var(--grid)"/><text x="${X(t)}" y="${H - B + 14}" text-anchor="middle">${t >= 1 ? t : t.toString()}</text>`;
    for (let k = 2; k < 10; k++) if (t * k < t2) g += `<line x1="${X(t * k)}" x2="${X(t * k)}" y1="${H - B}" y2="${H - B + 3}" stroke="var(--axis)"/>`;
  }
  let marks = "";
  for (const s of opts.stages || []) if (s.t > t1 && s.t < t2) marks += `<line x1="${X(s.t)}" x2="${X(s.t)}" y1="${T}" y2="${H - B}" stroke="var(--series-4)" stroke-dasharray="3 3"/><text x="${X(s.t) + 3}" y="${T + 10}" style="fill:var(--series-4)">stage</text>`;
  if (opts.t && opts.t >= t1 && opts.t <= t2) {
    const now = opts.now;
    marks += `<line x1="${X(opts.t)}" x2="${X(opts.t)}" y1="${T}" y2="${H - B}" stroke="var(--series-2)"/>`;
    if (now) marks += `<circle cx="${X(opts.t)}" cy="${Y(now.total * 1000)}" r="4" fill="var(--series-2)"/><text x="${X(opts.t) + 6}" y="${Y(now.total * 1000) - 6}" style="fill:var(--ink);font-weight:600">${n(now.total * 1000, 0)} mm</text>`;
  }
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Settlement against time">
    ${g}
    <path d="${path("immediate")}" fill="none" stroke="var(--series-3)" stroke-width="1.5" stroke-dasharray="5 3"/>
    <path d="${stackPrimary}" fill="none" stroke="var(--series-7)" stroke-width="1.5" stroke-dasharray="2 2"/>
    <path d="${path("total")}" fill="none" stroke="var(--series-1)" stroke-width="2.4"/>
    ${marks}
    <line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" stroke="var(--axis)"/><line x1="${L}" x2="${L}" y1="${T}" y2="${H - B}" stroke="var(--axis)"/>
    <text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle">Time (years, log scale)</text>
    <text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Settlement (mm)</text>
  </svg>
  <div class="legend-row"><span><i style="background:var(--series-1)"></i>Total</span><span><i class="dash" style="border-color:var(--series-7)"></i>Immediate + primary</span><span><i class="dash" style="border-color:var(--series-3)"></i>Immediate</span></div>`;
}

/** Stresses (or strain) with depth at the query point, over the soil layers. */
export function depthChart(project, res, mode = "stress") {
  const W = 640, H = 420, L = 54, R = 16, T = 26, B = 16;
  const rows = res.rows;
  if (!rows.length) return "";
  const tops = layerTops(project.layers);
  const D = tops.length ? tops[tops.length - 1] + (+project.layers[project.layers.length - 1].thickness || 0) : 1;
  let series, xmax, xlabel;
  if (mode === "strain") {
    series = [
      { key: "Immediate strain", col: "var(--series-3)", f: (r) => r.epsImm * 100, gap: true },
      { key: "Consolidation strain", col: "var(--series-7)", f: (r) => r.epsCons * 100, gap: true },
    ];
    xlabel = "Vertical strain (%)";
  } else {
    series = [
      { key: "σ'v0 in situ", col: "var(--series-3)", f: (r) => r.sv0 },
      { key: "σ'p preconsolidation", col: "var(--series-4)", f: (r) => r.sp, gap: true },
      { key: "σ'v0 + Δσ final", col: "var(--series-1)", f: (r) => r.svf },
      { key: "Δσ from the loads", col: "var(--series-2)", f: (r) => r.dsig },
    ];
    xlabel = "Vertical stress (kPa)";
  }
  xmax = Math.max(1e-6, ...rows.flatMap((r) => series.map((s) => s.f(r)).filter(Number.isFinite))) * 1.08;
  const X = (v) => L + (v / xmax) * (W - L - R), Y = (z) => T + (z / D) * (H - T - B);
  let bands = "";
  project.layers.forEach((l, i) => {
    bands += `<rect x="${L}" y="${Y(tops[i])}" width="${W - L - R}" height="${Y(tops[i] + +l.thickness) - Y(tops[i])}" fill="${soilColour(l, i)}" opacity="0.16"/>`;
    bands += `<line x1="${L}" x2="${W - R}" y1="${Y(tops[i])}" y2="${Y(tops[i])}" stroke="var(--axis)"/>`;
    bands += `<text x="${W - R - 4}" y="${Y(tops[i]) + 12}" text-anchor="end" style="fill:var(--ink-2)">${esc(l.name)}</text>`;
  });
  const wt = +project.waterTable;
  if (wt < D) bands += `<line x1="${L}" x2="${W - R}" y1="${Y(wt)}" y2="${Y(wt)}" stroke="var(--series-1)" stroke-dasharray="6 3"/><text x="${L + 4}" y="${Y(wt) - 3}" style="fill:var(--series-1)">▽ water table</text>`;
  let g = "";
  for (const v of ticks(0, xmax)) g += `<line x1="${X(v)}" x2="${X(v)}" y1="${T}" y2="${H - B}" stroke="var(--grid)"/><text x="${X(v)}" y="${T - 6}" text-anchor="middle">${n(v, 1)}</text>`;
  for (const z of ticks(0, D)) g += `<text x="${L - 6}" y="${Y(z) + 3}" text-anchor="end">${n(z, 1)}</text>`;
  let lines = "";
  for (const s of series) {
    let d = "", pen = false;
    // draw each layer separately so a jump at a boundary stays a jump
    let lastLayer = -1;
    for (const r of rows) {
      const v = s.f(r);
      if (!Number.isFinite(v) || v === null) { pen = false; continue; }
      const cmd = pen && (!s.gap || r.layer === lastLayer) ? "L" : "M";
      d += `${cmd}${X(v).toFixed(1)},${Y(r.z).toFixed(1)}`;
      pen = true; lastLayer = r.layer;
    }
    if (d) lines += `<path d="${d}" fill="none" stroke="${s.col}" stroke-width="2"/>`;
  }
  return `<svg class="chart tall" viewBox="0 0 ${W} ${H}" role="img" aria-label="${xlabel} with depth">
    ${bands}${g}${lines}
    <line x1="${L}" x2="${W - R}" y1="${T}" y2="${T}" stroke="var(--axis)"/><line x1="${L}" x2="${L}" y1="${T}" y2="${H - B}" stroke="var(--axis)"/>
    <text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" text-anchor="middle">Depth (m)</text>
  </svg>
  <div class="legend-row"><span class="muted">${xlabel}:</span>${series.map((s) => `<span><i style="background:${s.col}"></i>${esc(s.key)}</span>`).join("")}</div>`;
}

/** The cross-section A–A′: soil layers, loads, stress bulbs and the settled ground. */
export function sectionView(project, sec, data, box, opts = {}) {
  const W = Math.max(320, box.width), H = Math.max(260, box.height);
  const tops = layerTops(project.layers);
  const D = Math.max(1, tops.length ? tops[tops.length - 1] + (+project.layers[project.layers.length - 1].thickness || 0) : 10);
  const a1 = sec.a1, a2 = sec.a2;
  const L = 48, R = 16, T = opts.titles ? 100 : 136, B = 30;
  const sx = (W - L - R) / (a2 - a1);
  const sz = Math.min((H - T - B) / D, sx * 3);
  const X = (u) => L + (u - a1) * sx, Z = (z) => T + z * sz;
  const bottom = Z(D);
  let s = "";
  // soils
  project.layers.forEach((l, i) => {
    s += `<rect x="${L}" y="${Z(tops[i])}" width="${W - L - R}" height="${Math.max(0, Z(tops[i] + +l.thickness) - Z(tops[i]))}" fill="${soilColour(l, i)}" opacity="0.55"/>`;
    s += `<text x="${L + 6}" y="${Z(tops[i]) + 14}" style="fill:var(--ink);font-weight:600">${esc(l.name)}</text>`;
    if (Z(tops[i] + +l.thickness) - Z(tops[i]) > 34) s += `<text x="${L + 6}" y="${Z(tops[i]) + 26}" style="fill:var(--ink-2)">${n(+l.thickness, 1)} m${l.consolidating ? " · consolidates" : ""}</text>`;
  });
  const wt = +project.waterTable;
  if (wt <= D) s += `<line x1="${L}" x2="${W - R}" y1="${Z(wt)}" y2="${Z(wt)}" stroke="var(--water)" stroke-width="1.5" stroke-dasharray="7 4"/><text x="${W - R - 4}" y="${Z(wt) - 4}" text-anchor="end" style="fill:var(--water)">▽ water table</text>`;
  // stress bulbs: contours of Δσ as a share of the largest surface pressure
  if (data?.bulbs) {
    const b = data.bulbs, qmax = Math.max(1e-6, ...b.values);
    const bx = (i) => X(b.x1 + ((b.x2 - b.x1) * i) / (b.nx - 1)), bz = (k) => Z((b.depth * k) / (b.nz - 1));
    for (const f of [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]) {
      const segs = contour(b.values, b.nx, b.nz, f * qmax);
      if (!segs.length) continue;
      s += `<path d="${segs.map(([[i1, k1], [i2, k2]]) => `M${bx(i1).toFixed(1)},${bz(k1).toFixed(1)}L${bx(i2).toFixed(1)},${bz(k2).toFixed(1)}`).join("")}" fill="none" stroke="var(--series-2)" stroke-width="${f >= 0.5 ? 1.4 : 1}" opacity="0.85"/>`;
      const seg = segs.reduce((a, c) => (Math.max(c[0][1], c[1][1]) > Math.max(a[0][1], a[1][1]) ? c : a));
      if (Math.max(seg[0][1], seg[1][1]) > b.nz - 1.5) continue; // the bulb runs out of the bottom: no room for a label
      s += `<text x="${bx((seg[0][0] + seg[1][0]) / 2) + 4}" y="${bz(Math.max(seg[0][1], seg[1][1])) + 10}" style="fill:var(--series-2)">${Math.round(f * 100)}%</text>`;
    }
  }
  // the loads cut by the section: the pressure above the ground, the foundation down to where it is founded
  const ground = T;
  const live = project.loads.filter((l) => l.on !== false);
  const qmax = Math.max(1e-6, ...live.filter((l) => l.type !== "pilegroup").map(grossPressure), ...(live.some((l) => l.type !== "pilegroup") ? [] : live.map(grossPressure)));
  const hq = (q) => Math.max(8, Math.min(1, q / qmax) * 46);
  const label = (u, y, text) => `<text x="${X(u)}" y="${y}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${text}</text>`;
  const many = live.length > 6;
  for (const l of live) {
    const polys = outline(l).map((poly) => cutPoly(poly, sec));
    const main = polys[0];
    if (!main) continue;
    const q = grossPressure(l), h = hq(q), mid = (main[0] + main[1]) / 2;
    const name = many ? esc(l.name) : `${esc(l.name)} · ${n(q, 0)} kPa`;
    if (l.type === "embankment") {
      const crest = polys[1] || [mid, mid], he = polys[1] ? h : h / 2;
      s += `<path d="M${X(main[0])},${ground} L${X(crest[0])},${ground - he} L${X(crest[1])},${ground - he} L${X(main[1])},${ground} Z" fill="#c9b183" stroke="var(--ink-2)" opacity="0.9"/>`;
      s += label(mid, ground - he - 6, `${esc(l.name)} · ${n(+l.H, 1)} m, ${n(q, 0)} kPa`);
      continue;
    }
    if (l.type === "pilegroup") {
      const e = equivalentRaft(l), cap = polys[1] || main, Df = Math.max(0, +l.Df || 0), toe = Df + Math.max(0, +l.Lp || 0);
      const capH = Math.max(6, Math.min(14, 0.8 * sz));
      s += `<rect x="${X(cap[0])}" y="${Z(Df) - capH}" width="${Math.max(2, X(cap[1]) - X(cap[0]))}" height="${capH}" fill="var(--ink-2)" opacity="0.85"/>`;
      const np = Math.max(2, Math.min(9, Math.round((cap[1] - cap[0]) / 1.5) + 1));
      for (let k = 0; k < np; k++) {
        const u = cap[0] + ((cap[1] - cap[0]) * (k + 0.5)) / np;
        s += `<line x1="${X(u)}" x2="${X(u)}" y1="${Z(Df)}" y2="${Z(Math.min(D, toe))}" stroke="var(--ink-2)" stroke-width="2.5"/>`;
      }
      if (e.zf <= D) {
        s += `<path d="M${X(cap[0])},${Z(Df)} L${X(main[0])},${Z(e.zf)} M${X(cap[1])},${Z(Df)} L${X(main[1])},${Z(e.zf)}" stroke="var(--series-1)" stroke-dasharray="3 3" fill="none"/>`;
        s += `<line x1="${X(main[0])}" x2="${X(main[1])}" y1="${Z(e.zf)}" y2="${Z(e.zf)}" stroke="var(--series-1)" stroke-width="2" stroke-dasharray="6 3"/>`;
        s += `<text x="${X(main[1]) + 5}" y="${Z(e.zf) + 3}" style="fill:var(--series-1)">equivalent raft · ${n(q, 0)} kPa</text>`;
      }
      s += label(mid, ground - 6, esc(l.name));
      continue;
    }
    // a ring is cut into its two walls; everything else is one piece
    const hole = l.type === "ring" ? polys[1] : null;
    const pieces = hole ? [[main[0], hole[0]], [hole[1], main[1]]] : [main];
    const Df = foundingDepth(l);
    for (const [u1, u2] of pieces) {
      const w = Math.max(1, X(u2) - X(u1));
      if (Df > 0) s += `<rect x="${X(u1)}" y="${ground}" width="${w}" height="${Math.max(2, Z(Math.min(D, Df)) - ground)}" fill="var(--ink-2)" opacity="0.8"/>`;
      s += `<rect x="${X(u1)}" y="${ground - h}" width="${w}" height="${h}" fill="var(--series-1)" opacity="0.22" stroke="var(--series-1)"/>`;
      const na = Math.max(1, Math.min(6, Math.floor(w / 12)));
      for (let k = 0; k <= na; k++) {
        const u = u1 + ((u2 - u1) * k) / na;
        s += `<path d="M${X(u)},${ground - h} V${ground - 3} m-3,-4 l3,4 l3,-4" stroke="var(--series-1)" fill="none"/>`;
      }
    }
    if (!many || l === live[0]) s += label(mid, ground - h - 6, name);
  }
  s += `<line x1="${L}" x2="${W - R}" y1="${ground}" y2="${ground}" stroke="var(--ink)" stroke-width="1.5"/>`;
  // settled ground surface, exaggerated
  if (data?.line && data.xs) {
    const smax = Math.max(1e-9, ...data.line);
    const ex = Math.max(1, (0.35 * (T - 10)) / (smax * sz));
    const d = data.xs.map((u, i) => `${i ? "L" : "M"}${X(u).toFixed(1)},${(ground + data.line[i] * sz * ex).toFixed(1)}`).join("");
    s += `<path d="${d}" fill="none" stroke="var(--critical)" stroke-width="2.2"/>`;
    const i = data.line.indexOf(smax);
    s += `<text x="${X(data.xs[i]) + 6}" y="${ground + smax * sz * ex + 14}" style="fill:var(--critical);font-weight:600">${n(smax * 1000, 0)} mm</text>`;
    if (opts.titles) s += `<text x="${W - R}" y="${18}" text-anchor="end" style="fill:var(--muted)">Settled ground in red, drawn ${ex >= 10 ? Math.round(ex) : n(ex, 1)}× deeper than scale</text>`;
    sec.exaggeration = ex;
  }
  // axes
  for (const u of ticks(a1, a2, 8)) s += `<text x="${X(u)}" y="${bottom + 16}" text-anchor="middle">${n(u, 1)}</text><line x1="${X(u)}" x2="${X(u)}" y1="${bottom}" y2="${bottom + 4}" stroke="var(--axis)"/>`;
  for (const z of ticks(0, D, 6)) s += `<text x="${L - 6}" y="${Z(z) + 3}" text-anchor="end">${n(z, 1)}</text>`;
  if (opts.titles) {
    s += `<text x="${L}" y="${18}" style="fill:var(--ink);font-weight:600">Section A–A′ ${sec.along === "x" ? `along x at y = ${n(sec.at, 1)} m` : `along y at x = ${n(sec.at, 1)} m`}</text>`;
    s += `<text x="${L}" y="${34}" style="fill:var(--series-2)">Orange lines: Δσ as a share of the largest stress increase on the section</text>`;
  }
  return `<svg class="section" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Cross-section">${s}</svg>`;
}

// Where a plan outline crosses the section line: [from, to] along the section, or null.
function cutPoly(poly, sec) {
  if (!poly || poly.length < 3) return null;
  const k = sec.along === "x" ? 0 : 1, at = sec.at;
  let lo = Infinity, hi = -Infinity;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const oa = a[1 - k] - at, ob = b[1 - k] - at;
    if (oa === 0) { lo = Math.min(lo, a[k]); hi = Math.max(hi, a[k]); }
    if ((oa < 0) !== (ob < 0) && oa !== ob) {
      const u = a[k] + ((b[k] - a[k]) * oa) / (oa - ob);
      lo = Math.min(lo, u); hi = Math.max(hi, u);
    }
  }
  return hi > lo ? [lo, hi] : null;
}

export { levels };

// Bearing capacity: can the ground carry each foundation at all, before asking
// how much it settles.
//
// The general bearing capacity equation (Terzaghi 1943; factors of Prandtl,
// Reissner and Vesic 1973; shape factors of Vesic; depth factors of Hansen 1970):
//
//   drained     q_ult = c'·Nc·sc·dc + q'·Nq·sq·dq + ½·γ'·B·Nγ·sγ
//   undrained   q_ult = (π + 2)·su·sc·dc + q
//
// A clay is checked both ways and the lower answer governs. Weaker layers
// within one footing width below the base are checked too, with the load
// spread at 2 vertical to 1 horizontal down to them (the projected-area method).
// Vertical, central loads on level ground only.
//
// A load placed on top of an earlier one (a second stage of fill) is checked
// with both on the ground. A clay under the earlier load has by then gained
// strength, Δsu = 0.22·U·Δσ (Ladd 1991, normally consolidated clays), U being
// how far it has consolidated when the later load goes on.
//
// Units: m, kPa, kN.

import { initialStress, layerTops, layerDegree } from "./settlement.js";
import { grossPressure, foundingDepth, footprintArea, outline, loadCentre } from "./stress.js";

const num = (v) => (Number.isFinite(+v) ? +v : 0);
const rad = (deg) => (deg * Math.PI) / 180;

/** Nq, Nc and Nγ for a friction angle in degrees. */
export function factors(phiDeg) {
  const phi = rad(Math.max(0, Math.min(50, num(phiDeg))));
  if (phi < 1e-9) return { Nq: 1, Nc: Math.PI + 2, Ng: 0 };
  const Nq = Math.exp(Math.PI * Math.tan(phi)) * Math.tan(Math.PI / 4 + phi / 2) ** 2;
  return { Nq, Nc: (Nq - 1) / Math.tan(phi), Ng: 2 * (Nq + 1) * Math.tan(phi) };
}

/**
 * Net ultimate bearing pressure of a B × L footing at depth D on one soil.
 * `s` is { c, phi, su }; q is the effective overburden at the base and gamma
 * the effective unit weight below it. Returns the lower of the drained and
 * undrained answers that the soil's strengths allow: { qnet, mode } or null.
 */
export function netUltimate(s, B, L, D, q, gamma) {
  if (!(B > 0)) return null;
  L = Math.max(L, B);
  const k = D / B <= 1 ? D / B : Math.atan(D / B), r = B / L;
  const out = [];
  if (num(s.su) > 0) out.push({ qnet: (Math.PI + 2) * s.su * (1 + 0.2 * r) * (1 + 0.4 * k), mode: "undrained" });
  if (num(s.phi) > 0) {
    const phi = rad(Math.min(50, s.phi)), { Nq, Nc, Ng } = factors(s.phi), c = Math.max(0, num(s.c));
    const sq = 1 + r * Math.tan(phi), sc = 1 + r * (Nq / Nc), sg = 1 - 0.4 * r;
    const dq = 1 + 2 * Math.tan(phi) * (1 - Math.sin(phi)) ** 2 * k, dc = dq - (1 - dq) / (Nc * Math.tan(phi));
    out.push({ qnet: c * Nc * sc * dc + q * Nq * sq * dq + 0.5 * gamma * B * Ng * sg - q, mode: "drained" });
  }
  return out.length ? out.reduce((a, b) => (b.qnet < a.qnet ? b : a)) : null;
}

/** The plan size a foundation is checked as: its width B (the shorter side) and length L, and where its base is. */
export function bearingShape(l) {
  const t = l.type;
  if (t === "pilegroup") return null; // pile capacity is a different calculation
  if (t === "circle") { const b = Math.sqrt(Math.PI) * num(l.R); return { B: b, L: b }; }
  if (t === "ring") { const w = num(l.R) - num(l.Ri); return { B: w, L: Math.max(w, Math.PI * (num(l.R) + num(l.Ri))) }; }
  if (t === "embankment") { const w = num(l.crest) + num(l.slope); return { B: Math.min(w, num(l.L)), L: Math.max(w, num(l.L)) }; }
  if (t === "polygon" || t === "field") {
    const o = outline(l)[0];
    if (!o) return null;
    const xs = o.map((p) => p[0]), ys = o.map((p) => p[1]), w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
    // the bounding box, narrowed so that it keeps the shape's own area
    const a = footprintArea(l), long = Math.max(w, h);
    return long > 0 && a > 0 ? { B: Math.min(a / long, long), L: long } : null;
  }
  return { B: Math.min(num(l.B), num(l.L)), L: Math.max(num(l.B), num(l.L)) };
}

const inside = (poly, [x, y]) => {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
};

/** The loads this one stands on: switched on, founded at the same level, no later than it, and under its centre. */
export function loadsBelow(project, l) {
  const c = loadCentre(l), Df = foundingDepth(l), t0 = num(l.t0);
  return (project.loads || []).filter((o) => o !== l && o.on !== false && o.type !== "pilegroup" && Math.abs(foundingDepth(o) - Df) < 1e-6
    && (num(o.t0) < t0 || (num(o.t0) === t0 && project.loads.indexOf(o) < project.loads.indexOf(l))) && (outline(o)[0] ? inside(outline(o)[0], c) : false));
}

/**
 * The bearing check of one foundation: { checked, fos, qult (net), qnet
 * (applied), mode, layer, level } or { checked: false, why }.
 * fos is Infinity when the foundation weighs no more than the soil dug out.
 */
export function bearingCheck(project, l) {
  const layers = project.layers || [], wt = num(project.waterTable);
  const shape = bearingShape(l);
  if (!shape) return { checked: false, why: l.type === "pilegroup" ? "pile capacity is not checked here" : "no size" };
  if (!(shape.B > 0)) return { checked: false, why: "no size" };
  const tops = layerTops(layers), D = tops.length ? tops[tops.length - 1] + num(layers[layers.length - 1].thickness) : 0;
  const Df = foundingDepth(l);
  const st = (z) => initialStress(layers, wt, Math.min(z, D));
  const under = loadsBelow(project, l);
  const applied = grossPressure(l) + under.reduce((a, o) => a + grossPressure(o), 0) - st(Df).total;
  if (!(applied > 0)) return { checked: true, fos: Infinity, qult: 0, qnet: applied, mode: "compensated", layer: null, level: Df };
  let worst = null, unknown = false;
  layers.forEach((layer, i) => {
    const top = tops[i], bottom = top + num(layer.thickness);
    if (bottom <= Df + 1e-9 || top >= Df + shape.B - 1e-9) return;     // not within one width below the base
    const level = Math.max(Df, top), h = level - Df;
    const B = shape.B + h, L = shape.L + h;                              // the load spread at 2 to 1
    const q = st(level).eff, span = Math.max(1e-6, Math.min(B, D - level));
    const gamma = Math.max(0, (st(level + span).eff - q) / span);
    // strength gained under the loads already there, by the time this one goes on
    const gain = layer.consolidating && num(layer.su) > 0 ? under.reduce((a, o) => a + 0.22 * layerDegree(layer, Math.max(0, num(l.t0) - num(o.t0))) * Math.max(0, grossPressure(o)), 0) : 0;
    const u = netUltimate({ c: layer.c, phi: layer.phi, su: layer.consolidating && num(layer.su) > 0 ? num(layer.su) + gain : 0 }, B, L, level, q, gamma);
    if (!u) { unknown = true; return; }
    const qnet = (applied * shape.B * shape.L) / (B * L);
    const fos = u.qnet / qnet;
    if (!worst || fos < worst.fos) worst = { checked: true, fos, qult: u.qnet, qnet, mode: u.mode, layer: layer.name, level, stacked: under.length, gain };
  });
  if (!worst) return { checked: false, why: unknown ? "the soil under it has no strength given" : "it is founded below the soil profile" };
  return { ...worst, partial: unknown };
}

/** The check for every load, in order: one entry per load (null for a load switched off). */
export const bearingAll = (project) => (project.loads || []).map((l) => (l.on === false ? null : bearingCheck(project, l)));

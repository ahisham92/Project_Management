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
  if (l.type === "pilegroup") return pileCheck(project, l);
  if (!shape) return { checked: false, why: "no size" };
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

// ---------------------------------------------------------------- piles

// End bearing in sands by the friction angle between pile and soil (API RP 2A, 1993): [δ in degrees, Nq, limit on qb in kPa, limit on fs in kPa].
const API_SAND = [[15, 8, 1900, 48], [20, 12, 2900, 67], [25, 20, 4800, 81], [30, 40, 9600, 96], [35, 50, 12000, 115]];
function apiSand(delta) {
  const t = API_SAND, d = Math.max(t[0][0], Math.min(t[t.length - 1][0], delta));
  for (let i = 1; i < t.length; i++) if (d <= t[i][0]) {
    const u = (d - t[i - 1][0]) / (t[i][0] - t[i - 1][0]);
    return { Nq: t[i - 1][1] + u * (t[i][1] - t[i - 1][1]), qbMax: t[i - 1][2] + u * (t[i][2] - t[i - 1][2]), fsMax: t[i - 1][3] + u * (t[i][3] - t[i - 1][3]) };
  }
  return { Nq: t[0][1], qbMax: t[0][2], fsMax: t[0][3] };
}

/** Adhesion factor α for clay from ψ = su / σ'v (API RP 2A, 1993). */
export const alphaClay = (su, sv) => { const psi = sv > 0 ? su / sv : 1e9; return Math.min(1, psi <= 1 ? 0.5 * psi ** -0.5 : 0.5 * psi ** -0.25); };

/**
 * One pile's ultimate capacity in compression, kN: shaft friction layer by
 * layer from the cap to the toe, and end bearing at the toe.
 *   clay   fs = α·su            qb = 9·su
 *   sand   fs = K·σ'v·tanδ      qb = Nq·σ'v     (both limited, API RP 2A)
 * Driven piles: K = 1 and δ = φ' − 5°. Bored piles: K = 0.7, δ = φ', and half the end bearing in sand.
 */
export function pileCapacity(project, top, length, diameter, install = "bored") {
  const layers = project.layers || [], wt = num(project.waterTable), tops = layerTops(layers);
  const D = tops.length ? tops[tops.length - 1] + num(layers[layers.length - 1].thickness) : 0;
  const toe = top + length, bored = install !== "driven", per = Math.PI * diameter, area = (Math.PI * diameter * diameter) / 4;
  if (!(length > 0) || !(diameter > 0)) return null;
  if (toe > D + 1e-9) return { beyond: true };
  const parts = [];
  let shaft = 0, missing = false, clayShaft = 0;
  layers.forEach((layer, i) => {
    const a = Math.max(top, tops[i]), b = Math.min(toe, tops[i] + num(layer.thickness));
    if (b - a <= 1e-9) return;
    const n = Math.max(1, Math.ceil((b - a) / 0.5)), h = (b - a) / n;
    let q = 0;
    for (let k = 0; k < n; k++) {
      const sv = initialStress(layers, wt, a + h * (k + 0.5)).eff;
      if (layer.consolidating && num(layer.su) > 0) q += alphaClay(layer.su, sv) * layer.su * per * h;
      else if (num(layer.phi) > 0) { const d = bored ? layer.phi : layer.phi - 5, lim = apiSand(d); q += Math.min((bored ? 0.7 : 1) * sv * Math.tan(rad(d)), lim.fsMax) * per * h; }
      else missing = true;
    }
    if (layer.consolidating && num(layer.su) > 0) clayShaft += num(layer.su) * (b - a);
    shaft += q;
    parts.push({ layer: layer.name, from: a, to: b, shaft: q });
  });
  // the layer the toe stands in
  let ti = tops.findIndex((t, i) => toe > t - 1e-9 && toe <= t + num(layers[i].thickness) + 1e-9);
  if (ti < 0) ti = layers.length - 1;
  if (ti + 1 < layers.length && Math.abs(toe - (tops[ti] + num(layers[ti].thickness))) < 1e-6) ti += 1; // a toe on a boundary bears on the layer below
  const tl = layers[ti], svToe = initialStress(layers, wt, toe).eff;
  let qb = 0, clayToe = false;
  if (tl.consolidating && num(tl.su) > 0) { qb = 9 * tl.su; clayToe = true; }
  else if (num(tl.phi) > 0) { const lim = apiSand(bored ? tl.phi : tl.phi - 5); qb = Math.min(lim.Nq * svToe, lim.qbMax) * (bored ? 0.5 : 1); }
  else missing = true;
  return { shaft, base: qb * area, total: shaft + qb * area, qb, parts, toeLayer: tl.name, missing, clayShaft, clayToe, suToe: clayToe ? num(tl.su) : 0 };
}

/**
 * A pile group: all the piles together, or the block of soil they enclose
 * failing as one pier (in clay), whichever is less, against the load on the group.
 */
export function pileCheck(project, l) {
  const n = Math.max(1, Math.round(num(l.nPiles))), d = num(l.pileD), Lp = num(l.Lp), Df = Math.max(0, num(l.Df)), Q = num(l.Q);
  if (!(d > 0) || !(Lp > 0)) return { checked: false, why: "the piles have no diameter or length" };
  const one = pileCapacity(project, Df, Lp, d, l.install);
  if (!one) return { checked: false, why: "the piles have no diameter or length" };
  if (one.beyond) return { checked: false, why: "the piles go below the bottom of the soil profile" };
  let group = n * one.total, mode = "the piles one by one", block = null;
  if (one.clayToe && n > 1) {
    // the block: its sides in the clays it passes through, and its base as a deep footing on the clay at the toe
    const B = Math.min(num(l.B), num(l.L)) + d, L = Math.max(num(l.B), num(l.L)) + d;
    block = 2 * (B + L) * one.clayShaft + Math.min(9, 5.14 * (1 + 0.2 * (B / L)) * (1 + 0.4 * Math.atan(Lp / B))) * one.suToe * B * L;
    if (block < group) { group = block; mode = "the group as one block"; }
  }
  if (!(Q > 0)) return { checked: true, fos: Infinity, mode: "compensated", layer: one.toeLayer, pile: { n, d, one, group, block, Q } };
  return { checked: true, fos: group / Q, mode, layer: one.toeLayer, level: Df + Lp, partial: one.missing, pile: { n, d, one, group, block, Q, each: Q / n } };
}

// Settlement at a point: in-situ stresses, immediate settlement, primary
// consolidation with its rate (Terzaghi), and secondary compression.
//
// Units: m, kPa, years; settlement in m. Loads can be applied in stages: each
// load has the time it goes on (t0, years). The final settlement of each stage
// is worked out from the stresses of every load on by then; the increase it
// brings consolidates from that stage's time.

import { buildRects, deltaSigma } from "./stress.js";

export const GAMMA_W = 9.81;
const log10 = Math.log10;

/** Average degree of consolidation U for a time factor Tv (Terzaghi 1925). */
export function degreeOfConsolidation(Tv) {
  if (!(Tv > 0)) return 0;
  if (Tv < 0.01) return Math.sqrt((4 * Tv) / Math.PI);
  let U = 1;
  for (let m = 0; m < 200; m++) {
    const M = (Math.PI * (2 * m + 1)) / 2, term = (2 / (M * M)) * Math.exp(-M * M * Tv);
    U -= term;
    if (term < 1e-14) break;
  }
  return Math.min(1, Math.max(0, U));
}

/** Time factor for a degree of consolidation U (0..1), by bisection. */
export function timeFactor(U) {
  if (U <= 0) return 0;
  if (U >= 1) return Infinity;
  let lo = 0, hi = 10;
  for (let i = 0; i < 80; i++) { const mid = (lo + hi) / 2; if (degreeOfConsolidation(mid) < U) lo = mid; else hi = mid; }
  return (lo + hi) / 2;
}

export const drainagePath = (l) => (l.drainage === "single" ? +l.thickness : +l.thickness / 2);

/** Years for a layer to reach a degree of consolidation U. */
export function timeTo(l, U) {
  const cv = +l.cv, H = drainagePath(l);
  if (!(cv > 0) || !(H > 0)) return 0;
  return (timeFactor(U) * H * H) / cv;
}

/** Layer tops from the ground surface, in m. */
export function layerTops(layers) {
  const tops = [];
  let z = 0;
  for (const l of layers) { tops.push(z); z += +l.thickness || 0; }
  return tops;
}

/** Total and effective vertical stress and pore pressure at depth z. */
export function initialStress(layers, waterTable, z) {
  const wt = Math.max(0, +waterTable || 0);
  let sigma = 0, top = 0;
  for (const l of layers) {
    if (top >= z) break;
    const bot = Math.min(top + (+l.thickness || 0), z);
    const dry = Math.max(0, Math.min(bot, wt) - top), wet = Math.max(0, bot - top - dry);
    sigma += dry * +l.gamma + wet * +l.gammaSat;
    top += +l.thickness || 0;
  }
  const u = Math.max(0, z - wt) * GAMMA_W;
  return { total: sigma, u, eff: sigma - u };
}

/** Change in void ratio for a layer going from σ'0 to σ'f with σ'p. */
export function voidRatioChange(l, s0, sf, sp) {
  if (!(s0 > 0) || !(sf > s0)) return 0;
  const Cc = +l.Cc || 0, Cr = +l.Cr || 0;
  if (sf <= sp) return Cr * log10(sf / s0);
  if (s0 >= sp) return Cc * log10(sf / s0);
  return Cr * log10(sp / s0) + Cc * log10(sf / sp);
}

/** Constrained (oedometer) modulus from E and ν. */
export function constrainedModulus(E, nu) {
  const v = Math.min(Math.max(+nu || 0, 0), 0.49);
  return (E * (1 - v)) / ((1 + v) * (1 - 2 * v));
}

/** The distinct loading stages: [{t, loads}] with every load on by time t. */
export function stagesOf(loads) {
  const on = (loads || []).filter((l) => l.on !== false);
  const times = [...new Set(on.map((l) => Math.max(0, +l.t0 || 0)))].sort((a, b) => a - b);
  if (!times.length) times.push(0);
  return times.map((t) => ({ t, loads: on.filter((l) => Math.max(0, +l.t0 || 0) <= t) }));
}

/**
 * Settlement at plan point (px, py).
 * Returns the sub-layer rows (for the final stage), totals per layer and per
 * stage, and `at(t)` for the settlement at any time.
 */
export function computePoint(project, px, py, opts = {}) {
  const layers = project.layers || [];
  const method = project.method || "boussinesq";
  const wt = +project.waterTable || 0;
  const nSub = Math.max(1, Math.round(opts.subLayers || project.subLayers || 10));
  const stages = opts.stages || stagesOf(project.loads).map((s) => ({ ...s, rects: buildRects(s.loads) }));
  const tops = layerTops(layers);
  const rows = [];
  const perLayer = layers.map((l, i) => ({
    index: i, name: l.name, layer: l, top: tops[i], bottom: tops[i] + (+l.thickness || 0),
    immediate: 0, primary: 0, creep: 0,
    stage: stages.map(() => ({ immediate: 0, primary: 0 })),
  }));

  layers.forEach((l, li) => {
    const H = +l.thickness || 0;
    if (!(H > 0)) return;
    const h = H / nSub, nu = +l.nu || 0, E = +l.E || 0;
    const M = E > 0 ? constrainedModulus(E, nu) : 0;
    const lr = perLayer[li];
    for (let k = 0; k < nSub; k++) {
      const z = tops[li] + h * (k + 0.5);
      const st = initialStress(layers, wt, z);
      const sp = l.consolidating ? st.eff * Math.max(1, +l.OCR || 1) + Math.max(0, +l.POP || 0) : null;
      let row = null;
      stages.forEach((sg, si) => {
        const ds = deltaSigma(sg.rects, px, py, z, method, nu);
        const imm = M > 0 ? (ds / M) * h : 0;
        let de = 0;
        if (l.consolidating && st.eff > 0 && ds > 0) de = voidRatioChange(l, st.eff, st.eff + ds, sp);
        const cons = (de / (1 + (+l.e0 || 0))) * h;
        lr.stage[si].immediate += imm;
        lr.stage[si].primary += cons;
        if (si === stages.length - 1) {
          row = { layer: li, name: l.name, z, h, u0: st.u, sv0: st.eff, dsig: ds, svf: st.eff + ds, sp,
                  epsImm: M > 0 ? ds / M : 0, epsCons: h > 0 ? cons / h : 0, sImm: imm, sCons: cons, de };
          lr.immediate += imm;
          lr.primary += cons;
          if (l.consolidating && cons > 0) lr.creep += ((+l.Ca || 0) / (1 + (+l.e0 || 0) - de)) * h;
        }
      });
      if (row) rows.push(row);
    }
    lr.t95 = l.consolidating ? timeTo(l, 0.95) : 0;
  });

  const res = {
    x: px, y: py, rows, layers: perLayer,
    stages: stages.map((s) => ({ t: s.t, n: s.loads.length })),
    immediate: perLayer.reduce((a, b) => a + b.immediate, 0),
    primary: perLayer.reduce((a, b) => a + b.primary, 0),
  };
  res.at = (t) => settlementAt(res, t);
  return res;
}

/** Settlement components at time t (years) for a computePoint result. */
export function settlementAt(res, t) {
  const out = { t, immediate: 0, primary: 0, secondary: 0, U: 0 };
  const last = res.stages.length ? res.stages[res.stages.length - 1].t : 0;
  let primaryFinal = 0;
  for (const lr of res.layers) {
    const l = lr.layer;
    let prevI = 0, prevP = 0;
    res.stages.forEach((sg, si) => {
      const dI = lr.stage[si].immediate - prevI, dP = lr.stage[si].primary - prevP;
      prevI = lr.stage[si].immediate; prevP = lr.stage[si].primary;
      if (t < sg.t) return;
      out.immediate += dI;
      if (l.consolidating) {
        const cv = +l.cv, Hd = drainagePath(l);
        const U = cv > 0 && Hd > 0 ? degreeOfConsolidation((cv * (t - sg.t)) / (Hd * Hd)) : 1;
        out.primary += U * dP;
      }
    });
    primaryFinal += lr.primary;
    // Creep starts when this layer is 95% through primary consolidation under the last stage.
    const tp = last + Math.max(lr.t95 || 0, 1e-3);
    if (l.consolidating && lr.creep > 0 && t > tp) out.secondary += lr.creep * log10(t / tp);
  }
  out.U = primaryFinal > 0 ? out.primary / primaryFinal : 1;
  out.total = out.immediate + out.primary + out.secondary;
  return out;
}

/** Settlement with time on a log scale from tMin to tMax: [{t, ...}]. */
export function timeCurve(res, tMax, n = 120) {
  const tMin = Math.min(1e-3, tMax / 1000);
  const pts = [];
  for (let i = 0; i <= n; i++) pts.push(settlementAt(res, tMin * Math.pow(tMax / tMin, i / n)));
  // put each stage's step on the curve
  for (const s of res.stages) if (s.t > tMin && s.t < tMax) pts.push(settlementAt(res, s.t * (1 - 1e-9)), settlementAt(res, s.t));
  return pts.sort((a, b) => a.t - b.t);
}

/** Total settlement on a regular plan grid at time t. */
export function settlementGrid(project, g, t, onRow) {
  const stages = stagesOf(project.loads).map((s) => ({ ...s, rects: buildRects(s.loads) }));
  const { nx, ny } = g;
  const values = new Float64Array(nx * ny);
  let min = Infinity, max = -Infinity;
  const subLayers = Math.max(2, Math.min(+project.subLayers || 10, 12));
  for (let j = 0; j < ny; j++) {
    const y = g.y1 + ((g.y2 - g.y1) * j) / (ny - 1);
    for (let i = 0; i < nx; i++) {
      const x = g.x1 + ((g.x2 - g.x1) * i) / (nx - 1);
      const v = settlementAt(computePoint(project, x, y, { stages, subLayers }), t).total;
      values[j * nx + i] = v;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    if (onRow) onRow((j + 1) / ny);
  }
  return { ...g, values, min, max, t };
}

/** Δσz on a vertical section through y = py, for the stress bulbs. */
export function stressSection(project, py, x1, x2, depth, nx = 61, nz = 41) {
  const rects = buildRects(project.loads);
  const method = project.method || "boussinesq";
  const layers = project.layers || [], tops = layerTops(layers);
  const nuAt = (z) => { let nu = 0.3; layers.forEach((l, i) => { if (z >= tops[i]) nu = +l.nu || 0; }); return nu; };
  const values = new Float64Array(nx * nz);
  for (let k = 0; k < nz; k++) {
    const z = Math.max(0.02, (depth * k) / (nz - 1));
    for (let i = 0; i < nx; i++) values[k * nx + i] = deltaSigma(rects, x1 + ((x2 - x1) * i) / (nx - 1), py, z, method, nuAt(z));
  }
  return { nx, nz, x1, x2, depth, values };
}

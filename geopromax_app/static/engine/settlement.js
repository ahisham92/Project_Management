// Settlement at a point: in-situ stresses, immediate settlement, primary
// consolidation with its rate (Terzaghi, with wick drains if any), and
// secondary compression.
//
// Units: m, kPa, years; settlement in m. Loads can be applied in stages: each
// load has the time it goes on (t0, years). The final settlement of each stage
// is worked out from the stresses of every load on by then; the increase it
// brings consolidates from that stage's time.

import { buildRects, deltaSigma, checkPoints, foundingDepth } from "./stress.js";

export const GAMMA_W = 9.81;
const log10 = Math.log10;
const num = (v, d = 0) => (Number.isFinite(+v) ? +v : d);

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

/** Radial consolidation to vertical (wick) drains: Barron (1948) / Hansbo (1981),
 *  ideal drains with no smear or well resistance. */
export function radialDegree(drains, t) {
  if (!drains || !drains.on || !(t > 0)) return 0;
  const s = num(drains.spacing), dw = num(drains.dw), ch = num(drains.ch);
  if (!(s > 0) || !(dw > 0) || !(ch > 0)) return 0;
  const de = (drains.pattern === "square" ? 1.13 : 1.05) * s, n = de / dw;
  if (!(n > 1)) return 1;
  const F = Math.max(0.05, Math.log(n) - 0.75);
  return 1 - Math.exp((-8 * ch * t) / (de * de * F));
}

/** Degree of consolidation of a layer a time t after its load went on. */
export function layerDegree(l, t) {
  if (!(t > 0)) return 0;
  const cv = num(l.cv), H = drainagePath(l);
  const Uv = cv > 0 && H > 0 ? degreeOfConsolidation((cv * t) / (H * H)) : (l.drains && l.drains.on ? 0 : 1);
  const Ur = radialDegree(l.drains, t);
  return 1 - (1 - Uv) * (1 - Ur);
}

/** Years for a layer to reach a degree of consolidation U. */
export function timeTo(l, U) {
  if (layerDegree(l, 1e-9) >= U) return 0;
  let lo = 1e-9, hi = 1e-3;
  while (layerDegree(l, hi) < U && hi < 1e7) hi *= 4;
  if (hi >= 1e7) return Infinity;
  for (let i = 0; i < 80; i++) { const mid = Math.sqrt(lo * hi); if (layerDegree(l, mid) < U) lo = mid; else hi = mid; }
  return hi;
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

/** Change in void ratio for a layer going from σ'0 to σ'f with σ'p.
 *  Unloading (σ'f < σ'0) swells back along Cr. */
export function voidRatioChange(l, s0, sf, sp) {
  if (!(s0 > 0) || sf === s0) return 0;
  const Cc = +l.Cc || 0, Cr = +l.Cr || 0;
  sf = Math.max(sf, 0.05 * s0, 1);          // the soil cannot go into tension
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

/** The stages with their rectangles, ready for computePoint. */
export function prepare(project) {
  const layers = project.layers || [], wt = +project.waterTable || 0;
  const overburden = (z) => initialStress(layers, wt, z).total;
  return stagesOf(project.loads).map((s) => ({ ...s, rects: buildRects(s.loads, overburden) }));
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
  const nSub = Math.max(1, Math.round(num(opts.subLayers) || num(project.subLayers) || 10));
  const stages = opts.stages || prepare(project);
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
    const h = H / nSub, nu = +l.nu || 0, E0 = +l.E || 0, Einc = num(l.Einc);
    const lr = perLayer[li];
    const useMv = l.consolidating && l.model === "mv";
    for (let k = 0; k < nSub; k++) {
      const z = tops[li] + h * (k + 0.5);
      const st = initialStress(layers, wt, z);
      const E = E0 > 0 ? Math.max(1, E0 + Einc * (z - tops[li])) : 0;
      const M = E > 0 ? constrainedModulus(E, nu) : 0;
      const sp = l.consolidating && !useMv ? st.eff * Math.max(1, +l.OCR || 1) + Math.max(0, +l.POP || 0) : null;
      let row = null;
      stages.forEach((sg, si) => {
        const ds = deltaSigma(sg.rects, px, py, z, method, nu);
        const imm = M > 0 ? (ds / M) * h : 0;
        let de = 0, cons = 0;
        if (l.consolidating && st.eff > 0 && ds !== 0) {
          if (useMv) cons = (num(l.mv) / 1000) * ds * h;           // mv in m²/MN
          else { de = voidRatioChange(l, st.eff, st.eff + ds, sp); cons = (de / (1 + (+l.e0 || 0))) * h; }
        }
        lr.stage[si].immediate += imm;
        lr.stage[si].primary += cons;
        if (si === stages.length - 1) {
          row = { layer: li, name: l.name, z, h, u0: st.u, sv0: st.eff, dsig: ds, svf: st.eff + ds, sp,
                  epsImm: M > 0 ? ds / M : 0, epsCons: h > 0 ? cons / h : 0, sImm: imm, sCons: cons, de };
          lr.immediate += imm;
          lr.primary += cons;
          if (l.consolidating && cons > 0) {
            // Cα/Cc is a constant of the soil (Mesri and Castro 1987): where the soil stays
            // overconsolidated it is on the Cr line, and creeps by Cα·Cr/Cc.
            const onCr = !useMv && st.eff + ds <= sp + 1e-9 && +l.Cc > 0 ? Math.min(1, Math.max(0, +l.Cr || 0) / +l.Cc) : 1;
            lr.creep += ((onCr * (+l.Ca || 0)) / (1 + (+l.e0 || 0) - de)) * h;
          }
        }
      });
      if (row) rows.push(row);
    }
    lr.t95 = l.consolidating ? timeTo(l, 0.95) : 0;
  });

  const res = {
    x: px, y: py, rows, layers: perLayer, subLayers: nSub,
    stages: stages.map((s) => ({ t: s.t, n: s.loads.length })),
    immediate: perLayer.reduce((a, b) => a + b.immediate, 0),
    primary: perLayer.reduce((a, b) => a + b.primary, 0),
  };
  res.at = (t) => settlementAt(res, t);
  return res;
}

/**
 * The same, with the sub-layers refined until the final settlement changes by
 * less than `tol` (0.5%) from one refinement to the next. The result says how
 * many it took and whether it got there.
 */
export function computeConverged(project, px, py, opts = {}) {
  const stages = opts.stages || prepare(project), tol = opts.tol || 0.005, max = opts.max || 96;
  let n = 4, prev = null, res = null, change = Infinity;
  const steps = [];
  for (;;) {
    res = computePoint(project, px, py, { stages, subLayers: n });
    const total = res.immediate + res.primary;
    steps.push({ n, total });
    if (prev !== null) {
      change = Math.abs(total - prev) / Math.max(Math.abs(total), 1e-6);
      if (change < tol || Math.abs(total - prev) < 5e-5) { res.converged = true; break; }
    }
    if (n * 2 > max) { res.converged = prev === null ? false : change < 4 * tol; break; }
    prev = total; n *= 2;
  }
  res.steps = steps; res.change = Number.isFinite(change) ? change : 0;
  return res;
}

/** computePoint with the project's own setting: a number, or automatic. */
export function solvePoint(project, px, py, opts = {}) {
  return num(project.subLayers) >= 1 ? Object.assign(computePoint(project, px, py, opts), { converged: null }) : computeConverged(project, px, py, opts);
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
      if (l.consolidating) out.primary += (t > sg.t ? layerDegree(l, t - sg.t) : 0) * dP;
    });
    primaryFinal += lr.primary;
    // Creep starts when this layer is 95% through primary consolidation under the last stage.
    const tp = last + Math.max(lr.t95 || 0, 1e-3);
    if (l.consolidating && lr.creep > 0 && t > tp) out.secondary += lr.creep * log10(t / tp);
  }
  out.U = Math.abs(primaryFinal) > 1e-12 ? out.primary / primaryFinal : 1;
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
  const stages = prepare(project);
  const { nx, ny } = g;
  const values = new Float64Array(nx * ny);
  let min = Infinity, max = -Infinity;
  const subLayers = gridSubLayers(project);
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

/** Sub-layers for the many points of the plan: the project's, within reason. */
export const gridSubLayers = (project, found) => Math.max(4, Math.min(num(project.subLayers) || found || 10, 16));

/** Δσz on a vertical section, for the stress bulbs. `along` "x": the section
 *  runs along x at y = at; "y": along y at x = at. */
export function stressSection(project, along, at, a1, a2, depth, nx = 61, nz = 41) {
  const stages = prepare(project), rects = stages[stages.length - 1].rects;
  const method = project.method || "boussinesq";
  const layers = project.layers || [], tops = layerTops(layers);
  const nuAt = (z) => { let nu = 0.3; layers.forEach((l, i) => { if (z >= tops[i]) nu = +l.nu || 0; }); return nu; };
  const values = new Float64Array(nx * nz);
  for (let k = 0; k < nz; k++) {
    const z = Math.max(0.02, (depth * k) / (nz - 1));
    for (let i = 0; i < nx; i++) {
      const u = a1 + ((a2 - a1) * i) / (nx - 1);
      values[k * nx + i] = along === "y" ? deltaSigma(rects, at, u, z, method, nuAt(z)) : deltaSigma(rects, u, at, z, method, nuAt(z));
    }
  }
  return { nx, nz, x1: a1, x2: a2, depth, values };
}

/**
 * Each foundation's settlement at the points it is judged at, ready to be read
 * at any time with `summarize`.
 */
export function foundationResults(project, opts = {}) {
  const stages = opts.stages || prepare(project);
  const subLayers = opts.subLayers || gridSubLayers(project);
  const at = ([x, y]) => computePoint(project, x, y, { stages, subLayers });
  return (project.loads || []).map((l, index) => {
    if (l.on === false) return { index, load: l, off: true };
    const p = checkPoints(l);
    return {
      index, load: l, centre: at(p.centre),
      edges: p.edge.map((e) => ({ res: at(e), d: Math.hypot(e[0] - p.centre[0], e[1] - p.centre[1]) })),
      rigid: l.rigid && p.rigid ? p.rigid.map((q) => ({ q, res: at(q) })) : null,
    };
  });
}

/**
 * How each foundation has settled at time t: at its centre, around its edge,
 * or as a rigid body; the differential settlement across it and its tilt.
 */
export function summarize(results, t) {
  return results.map((f) => {
    const l = f.load, base = { index: f.index, name: l.name, type: l.type };
    if (f.off) return { ...base, off: true };
    const centre = settlementAt(f.centre, t).total;
    const edges = f.edges.map((e) => ({ s: settlementAt(e.res, t).total, d: e.d }));
    const depth = foundingDepth(l);
    if (f.rigid) {
      // A rigid body settles evenly and tilts as a plane through its characteristic points.
      const r = f.rigid.map((x) => ({ q: x.q, s: settlementAt(x.res, t).total }));
      const rigid = r.reduce((a, b) => a + b.s, 0) / r.length;
      let rt = 0, half = 0;
      for (let i = 0; i < r.length; i++) for (let j = i + 1; j < r.length; j++) {
        const d = Math.hypot(r[i].q[0] - r[j].q[0], r[i].q[1] - r[j].q[1]);
        if (d > 1e-6) rt = Math.max(rt, Math.abs(r[i].s - r[j].s) / d);
      }
      for (const e of edges) half = Math.max(half, e.d);
      return { ...base, depth, centre, max: rigid + rt * half, min: rigid - rt * half, diff: 2 * rt * half, tilt: rt, rigid, governing: rigid + rt * half };
    }
    const all = [centre, ...edges.map((e) => e.s)];
    const max = Math.max(...all), min = Math.min(...all);
    let tilt = 0;
    for (const e of edges) if (e.d > 1e-6) tilt = Math.max(tilt, Math.abs(centre - e.s) / e.d);
    return { ...base, depth, centre, max, min, diff: max - min, tilt, rigid: null, governing: max };
  });
}

export const foundationSummary = (project, t, opts = {}) => summarize(foundationResults(project, opts), t);

/**
 * Differential settlement between neighbouring foundations: for each one, the
 * steepest slope to another foundation (difference in settlement over the
 * distance between their centres). This is the angular distortion of a frame.
 */
export function betweenFoundations(project, summary) {
  const live = summary.filter((f) => !f.off);
  const c = (f) => checkPoints(project.loads[f.index]).centre;
  let worst = { tilt: 0, a: null, b: null, diff: 0 };
  for (let i = 0; i < live.length; i++) for (let j = i + 1; j < live.length; j++) {
    const [x1, y1] = c(live[i]), [x2, y2] = c(live[j]), d = Math.hypot(x1 - x2, y1 - y2);
    if (!(d > 1e-6)) continue;
    const sa = live[i].rigid ?? live[i].centre, sb = live[j].rigid ?? live[j].centre;
    const tilt = Math.abs(sa - sb) / d;
    if (tilt > worst.tilt) worst = { tilt, a: live[i].name, b: live[j].name, diff: Math.abs(sa - sb), d };
  }
  return worst;
}

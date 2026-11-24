// Talus — runs every load case of a project and reports in the user's frame.

import { prepare, sliceForces, valueOf, METHODS, METHOD_NAMES, DEG, buildSlices, brent, refineHB } from "./lem.js";
import { criticalCircle, optimiseNonCircular, blockSearch, quickF, circleSlip } from "./search.js";
import { buildCases, complete } from "./project.js";
import { stagedSearch } from "./drawdown.js";

const ux = (P, x) => (P.flip ? -x : x);
const upoly = (P, poly) => (P.flip ? poly.map(([x, y]) => [-x, y]).reverse() : poly.map((p) => [...p]));

function toUser(P, r) {
  const slip = upoly(P, r.cut.slip.filter(([x]) => x >= r.cut.xL - 1e-9));
  if (r.cut.xL > r.cut.slip[0][0]) {
    // tension crack: start the drawn surface at the crack
    const y = r.cut.crack ? r.cut.crack.y : slip[0][1];
    if (P.flip) slip.push([ux(P, r.cut.xL), y]); else slip.unshift([r.cut.xL, y]);
  }
  return {
    kind: r.kind,
    circle: r.circle ? { xc: ux(P, r.circle.xc), yc: r.circle.yc, R: r.circle.R } : null,
    slip,
    crack: r.cut.crack ? { x: ux(P, r.cut.crack.x), y: r.cut.crack.y, depth: r.cut.crack.depth } : null,
    depth: r.depth,
  };
}

// Reported sign of the interslice shear follows Fredlund & Krahn (and SLOPE/W): positive
// lambda when the interslice resultant leans with the slope. The engine's own X is the
// opposite way round, so it is negated here. E and X are the forces on each slice's
// downslope face.
function slicesToUser(P, rows) {
  const out = rows.map((s) => ({ ...(P.flip ? { ...s, x0: -s.x1, x1: -s.x0, xm: -s.xm } : s), Xl: -s.Xl, Xr: -s.Xr }));
  return P.flip ? out.reverse() : out;
}

const lambdaOf = (r, m) => (typeof r[m] === "object" ? r[m]?.lambda ?? 0 : 0);

/** Critical surface of one model, already turned into the engine frame. */
function critical(P, opt) {
  let best = criticalCircle(P, opt);
  if (best && opt.noncircular) {
    const nc = optimiseNonCircular(P, best, { method: opt.method, slices: opt.slices });
    if (nc && nc.F < best.F) best = { ...nc, trials: best.trials, fromCircle: best.F };
  }
  if (opt.block) {
    const bl = blockSearch(P, { method: opt.method, slices: opt.slices, minDepth: opt.minDepth });
    if (bl && (!best || bl.F < best.F)) best = { ...bl, trials: best?.trials || [], fromCircle: best?.F };
  }
  return best;
}

/** One load case: search, all methods, slice forces, all in the user's frame. */
export function analyseCase(c, opt = {}) {
  const method = opt.method || "mp";
  const run = (kv) => {
    const P = prepare({ ...c.model, seismic: c.model.seismic ? { kh: c.model.seismic.kh, kv } : undefined });
    return { P, r: critical(P, { ...opt, method, minDepth: c.minDepth ?? opt.minDepth }) };
  };
  let { P, r } = run(c.model.seismic?.kv || 0);
  let kvUsed = c.model.seismic?.kv || 0;
  if (c.model.seismic?.kv) {
    const other = run(-c.model.seismic.kv);
    if (other.r && (!r || other.r.F < r.F)) { P = other.P; r = other.r; kvUsed = -c.model.seismic.kv; }
  }
  if (!r) return { key: c.key, name: c.name, target: c.target, note: c.note, error: "No admissible slip surface was found inside the model." };
  // rapid drawdown in three stages (Duncan, Wright and Wong 1990): on circles, from the
  // conventional search's candidates
  if (c.staged) {
    const P1 = prepare(c.staged.before);
    const base = r.kind === "circle" && r.trials?.length ? r : criticalCircle(P, { ...opt, method });
    const st = stagedSearch(P1, P, base, { ...opt, method, minDepth: c.minDepth ?? opt.minDepth });
    if (st) r = { ...st, staged: { ...st.staged, conventional: r.F } };
  }
  // Hoek-Brown rock: strengths follow the normal stresses on the critical surface
  const hb = refineHB(P, r.cut, r.circle, method);
  if (hb) r = { ...r, results: hb.results, F: hb.F, hb: { rounds: hb.rounds, gap: hb.gap } };
  let F = r.F, used = method;
  if (!Number.isFinite(F)) {
    // a rigorous method that did not converge: fall back to Bishop and say so
    used = "bishop"; F = r.results.bishop;
  }
  const slices = sliceForces(P, r.cut, r.circle, used, F, lambdaOf(r.results, used));
  const results = {};
  for (const m of METHODS) results[m] = valueOf(r.results, m);
  const trials = r.trials.map((t) => ({ circle: { xc: ux(P, t.circle.xc), yc: t.circle.yc, R: t.circle.R }, xe: ux(P, t.xe), xx: ux(P, t.xx), F: t.F }));
  let W = 0;
  for (const s of r.cut.slices) W += s.W;
  return {
    key: c.key, name: c.name, target: c.target, note: c.note,
    method: used, methodName: METHOD_NAMES[used], fellBack: used !== method,
    F, ratio: F / c.target, pass: F >= c.target - 5e-4,
    results, lambda: -lambdaOf(r.results, used),
    surface: toUser(P, r), slices: slicesToUser(P, slices), trials,
    weight: W, piezo: c.model.piezo, strips: c.model.strips || [], lines: c.model.lines || [],
    seismic: c.seismic ? { ...c.seismic, kvUsed } : null,
    fromCircle: r.fromCircle, hb: r.hb || null, staged: r.staged || null,
    _P: P, _r: r,
  };
}

/** Yield coefficient ky (F = 1) on the critical surface, checked by a new search. */
export function yieldCoefficient(c, opt = {}) {
  const method = opt.method || "mp";
  const at = (kh, surface) => {
    const P = prepare({ ...c.model, seismic: { kh, kv: 0 } });
    if (surface) {
      const cut = buildSlices(P, surface.slip, { n: opt.slices || 40, exact: true });
      return cut ? quickF(P, cut, surface.circle, method) : NaN;
    }
    return critical(P, { ...opt, method, minDepth: c.minDepth, grid: [10, 10, 7], refine: 40 });
  };
  const P0 = prepare({ ...c.model, seismic: { kh: 0, kv: 0 } });
  let best = critical(P0, { ...opt, method, minDepth: c.minDepth, grid: [10, 10, 7], refine: 40 });
  if (!best) return null;
  if (best.F <= 1) return { ky: 0, F0: best.F };
  let ky = NaN;
  for (let round = 0; round < 3; round++) {
    const surf = { slip: best.cut.slip, circle: best.circle };
    const f = (kh) => at(kh, surf) - 1;
    let hi = 0.05;
    while (f(hi) > 0 && hi < 2) hi *= 1.6;
    if (f(hi) > 0) return { ky: hi, F0: best.F, capped: true };
    ky = brent(f, 0, hi, undefined, undefined, 1e-5);
    const check = at(ky, null);
    if (!check || check.F >= 1 - 1e-3) break;
    best = check;
  }
  return { ky, F0: best.F };
}

/** Newmark sliding block displacement, Jibson (2007) Eq. 6 (critical acceleration ratio). */
export function newmark(ky, amax) {
  if (!(amax > 0)) return null;
  const r = ky / amax;
  if (r >= 1) return { D: 0, r, note: "ky ≥ amax: the slope does not slide." };
  const rr = Math.max(0.01, r);
  const logD = 0.215 + Math.log10(Math.pow(1 - rr, 2.341) * Math.pow(rr, -1.438));
  const D = Math.pow(10, logD); // cm
  return { D, r, low: D / Math.pow(10, 0.51), high: D * Math.pow(10, 0.51), note: "Jibson (2007): log D = 0.215 + log[(1 − ky/amax)^2.341 (ky/amax)^−1.438] ± 0.510, D in cm." };
}

/**
 * The whole project.
 * opt: { onCase(result, i, n), fast }
 */
export function analyse(project, opt = {}) {
  const built = buildCases(project);
  const p = built.project;
  const method = p.design?.method || "mp";
  const base = {
    method, slices: num(p.advanced?.slices, 40), noncircular: !!p.advanced?.noncircular, block: !!p.advanced?.block,
    grid: opt.fast ? [10, 10, 7] : [14, 14, 9], refine: opt.fast ? 40 : 60,
  };
  const cases = [];
  built.cases.forEach((c, i) => {
    const r = analyseCase(c, base);
    cases.push(r);
    opt.onCase?.(strip(r), i, built.cases.length);
  });
  const ok = cases.filter((c) => !c.error);
  const worst = ok.length ? ok.reduce((a, b) => (a.ratio <= b.ratio ? a : b)) : null;
  return {
    project: p,
    geometry: built.geometry,
    extras: built.extras,
    cases: cases.map(strip),
    worst: worst ? { key: worst.key, name: worst.name, F: worst.F, target: worst.target, ratio: worst.ratio, pass: worst.pass } : null,
    pass: ok.length === cases.length && ok.every((c) => c.pass),
    methods: METHOD_NAMES,
    _cases: built.cases,
  };
}

/** Seismic extras (slow, so asked for after the main answer). */
export function seismicExtras(project) {
  const built = buildCases(project);
  const c = built.cases.find((k) => k.key === "seismic");
  if (!c) return null;
  const method = built.project.design?.method || "mp";
  const y = yieldCoefficient(c, { method, slices: 40 });
  if (!y) return null;
  return { ...y, amax: c.seismic.amax, kh: c.seismic.kh, newmark: newmark(y.ky, c.seismic.amax) };
}

function strip(r) {
  const { _P, _r, ...rest } = r;
  return rest;
}

function num(v, d) { return Number.isFinite(+v) && v !== "" && v !== null ? +v : d; }

/**
 * Steepest slope (smallest cot) that meets every target, by bisection.
 * Returns { cot, angle, worst } or null when even the flattest slope fails.
 */
export function steepestSafe(project, opt = {}) {
  const p = complete(project);
  if (p.type === "section") return { cot: null, message: "A drawn section has no single slope to vary: change the points and watch F." };
  const lo0 = p.type === "revetment" ? 1.3 : p.type === "embankment" ? 1 : 0.25;
  const hi0 = 6;
  const check = (cot) => {
    const q = JSON.parse(JSON.stringify(p));
    q.geom.cot = cot;
    // a benched face: every bench at the same slope, heights and berms kept
    if (q.geom.berms?.on) for (const r of q.geom.berms.rows || []) r.cot = cot;
    const a = analyse(q, { fast: true });
    opt.onStep?.(cot, a.worst);
    return a;
  };
  let a = check(hi0);
  if (!a.pass) return { cot: null, worst: a.worst, message: "Even a 1:6 slope does not meet every target: the ground or loads need another solution (berm, drainage, reinforcement)." };
  let lo = lo0, hi = hi0, best = { cot: hi0, worst: a.worst };
  const al = check(lo);
  if (al.pass) return { cot: lo, angle: Math.atan(1 / lo) / DEG, worst: al.worst, atLimit: true };
  for (let i = 0; i < (opt.steps || 7); i++) {
    const mid = (lo + hi) / 2;
    const am = check(mid);
    if (am.pass) { hi = mid; best = { cot: mid, worst: am.worst }; } else lo = mid;
  }
  // round up to a buildable ratio (nearest 0.05 flatter)
  const cot = Math.ceil(best.cot * 20 - 1e-9) / 20;
  return { cot, angle: Math.atan(1 / cot) / DEG, worst: best.worst };
}

/**
 * What it takes: the variables a person can ask Talus to solve for, by kind of slope.
 * want "min": the smallest value that meets every target (more is safer);
 * want "max": the largest value that still meets every target (less is safer).
 */
export const GOALS = [
  { k: "geom.cot", l: "Steepest slope", u: "H/V", want: "min", kinds: ["cut", "embankment", "revetment"], fmt: (v) => `1:${v}`, step: 0.05 },
  { k: "geom.H", l: "Highest slope", u: "m", want: "max", kinds: ["cut", "embankment"], range: [0.5, 40], step: 0.25, when: (p) => !p.geom?.berms?.on },
  { k: "load.q", l: "Largest surcharge", u: "kPa", want: "max", kinds: ["cut", "embankment", "revetment", "section"], range: [0, 500], step: 1 },
  { k: "water.back", l: "Groundwater drawn down to", u: "m below the crest", want: "min", kinds: ["cut"], range: [0, 40], step: 0.25, when: (p) => p.water?.on },
  { k: "nails.length", l: "Shortest nails", u: "m", want: "min", kinds: ["cut"], range: [1, 30], step: 0.5, when: (p) => p.nails?.on },
  { k: "nails.T", l: "Smallest nail capacity", u: "kN/m", want: "min", kinds: ["cut"], range: [0, 1000], step: 5, when: (p) => p.nails?.on },
  { k: "nails.rows", l: "Fewest rows of nails", u: "rows", want: "min", kinds: ["cut"], range: [1, 12], step: 1, int: true, when: (p) => p.nails?.on },
  { k: "grids.n", l: "Fewest geogrid layers", u: "layers", want: "min", kinds: ["embankment", "revetment"], range: [1, 40], step: 1, int: true, when: (p) => p.grids?.on },
  { k: "grids.T", l: "Weakest geogrid", u: "kN/m", want: "min", kinds: ["embankment", "revetment"], range: [0, 2000], step: 5, when: (p) => p.grids?.on },
  { k: "piles.Vp", l: "Smallest pile shear capacity", u: "kN", want: "min", kinds: ["cut", "embankment", "revetment", "section"], range: [0, 20000], step: 10, when: (p) => p.piles?.on },
  { k: "piles.spacing", l: "Widest pile spacing", u: "m", want: "max", kinds: ["cut", "embankment", "revetment", "section"], range: [0.1, 20], step: 0.1, when: (p) => p.piles?.on },
  { k: "seismic.ag", l: "Strongest earthquake", u: "g", want: "max", kinds: ["cut", "embankment", "revetment", "section"], range: [0, 0.8], step: 0.01, when: (p) => p.seismic?.on },
];

export function goalsFor(project) {
  const p = complete(project);
  return GOALS.filter((g) => g.kinds.includes(p.type) && (!g.when || g.when(p)));
}

const getPath = (o, path) => path.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
const setPath = (o, path, v) => { const ks = path.split("."); let a = o; for (let i = 0; i < ks.length - 1; i++) a = a[ks[i]] = a[ks[i]] ?? {}; a[ks[ks.length - 1]] = v; };

/**
 * Solve for one input: the least (or most) of it that meets every target in every
 * load case, everything else as it is. Bisection on full fast searches; the answer is
 * rounded to a buildable step on the safe side and checked again.
 * Returns { k, value, worst, atLimit } or { value: null, message }.
 */
export function solveFor(project, key, opt = {}) {
  if (key === "geom.cot") {
    const r = steepestSafe(project, { onStep: (cot, worst) => opt.onStep?.(cot, worst) });
    return { k: key, value: r.cot, worst: r.worst, atLimit: r.atLimit, message: r.message };
  }
  const p = complete(project);
  const g = GOALS.find((x) => x.k === key);
  if (!g) return { k: key, value: null, message: "Talus cannot solve for that input." };
  const [lo0, hi0] = g.range;
  const check = (v) => {
    const q = JSON.parse(JSON.stringify(p));
    setPath(q, key, v);
    const a = analyse(q, { fast: true });
    opt.onStep?.(v, a.worst);
    return a;
  };
  const safeEnd = g.want === "min" ? hi0 : lo0, riskEnd = g.want === "min" ? lo0 : hi0;
  const a0 = check(safeEnd);
  if (!a0.pass) return { k: key, value: null, worst: a0.worst, message: `Even at ${safeEnd} ${g.u} a load case is short of its target: change something else as well.` };
  const a1 = check(riskEnd);
  if (a1.pass) return { k: key, value: riskEnd, worst: a1.worst, atLimit: true };
  let pass = safeEnd, fail = riskEnd;
  const steps = opt.steps || (g.int ? 6 : 9);
  for (let i = 0; i < steps; i++) {
    if (Math.abs(pass - fail) <= (g.int ? 1 : g.step / 2)) break;
    let mid = (pass + fail) / 2;
    if (g.int) mid = Math.round(mid);
    if (mid === pass || mid === fail) break;
    if (check(mid).pass) pass = mid; else fail = mid;
  }
  // round on the safe side, to the step
  const k = 1 / g.step;
  let v = g.want === "min" ? Math.ceil(pass * k - 1e-9) / k : Math.floor(pass * k + 1e-9) / k;
  v = +v.toFixed(6);
  const af = check(v);
  if (!af.pass) v = pass;   // rounding never makes it unsafe; keep the bisection value if it did
  return { k: key, value: v, worst: (af.pass ? af : check(v)).worst, before: getPath(p, key) };
}

export { circleSlip };

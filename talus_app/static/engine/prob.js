// Talus — probabilistic analysis on the critical surface.
//
// The soil and rock properties are treated as random variables, each lognormal with
// its mean equal to the value entered and a coefficient of variation (COV). Latin
// hypercube samples, drawn from a fixed seed so a run can be repeated exactly, are
// solved on the deterministic critical surface of the load case (the "global
// minimum" approach). The result is the distribution of F, the probability of
// failure P(F < 1), the reliability index and a one-at-a-time sensitivity.

import { buildCases, complete } from "./project.js";
import { analyseCase } from "./analyse.js";
import { buildSlices, refineHB, METHOD_NAMES } from "./lem.js";
import { quickF } from "./search.js";

/** Typical coefficients of variation (Phoon and Kulhawy 1999; Duncan 2000; Hoek 2007). */
export const COV = { tanphi: 0.10, c: 0.30, su: 0.25, gamma: 0.05, GSI: 0.10, sci: 0.25 };
export const COV_LABEL = {
  tanphi: "tan φ'", c: "c'", su: "su", gamma: "γ", GSI: "GSI", sci: "σci",
};

/** A small, fast, seeded generator (mulberry32). */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** The standard normal quantile (Acklam's rational approximation, refined by one Halley step). */
export function normInv(p) {
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const lo = 0.02425;
  let x;
  if (p < lo) { const q = Math.sqrt(-2 * Math.log(p)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
  else if (p <= 1 - lo) { const q = p - 0.5, r = q * q; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
  else { const q = Math.sqrt(-2 * Math.log(1 - p)); x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
  const e = 0.5 * erfc(-x / Math.SQRT2) - p;
  const u = e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
  return x - u / (1 + x * u / 2);
}

/** The complementary error function (Numerical Recipes erfcc, relative error below 1.2e-7). */
export function erfc(x) {
  const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
  const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return x >= 0 ? r : 2 - r;
}
export const normCdf = (x) => 0.5 * erfc(-x / Math.SQRT2);

/** The random variables of a prepared model: one per property per layer that has it. */
export function variablesOf(P, cov = {}) {
  const C = { ...COV, ...cov };
  const out = [], groups = new Map();
  // the same material in two layers is one soil: one set of variables for both
  P.layers.forEach((L, k) => {
    const g = groups.get(L.mat.name);
    if (g) g.layers.push(k); else groups.set(L.mat.name, { mat: L.mat, layers: [k] });
  });
  for (const { mat: m, layers } of groups.values()) {
    const add = (prop, value) => { if (value > 0 && C[prop] > 0) out.push({ name: `${m.name}: ${COV_LABEL[prop]}`, mat: m.name, prop, mean: value, cov: C[prop], layers }); };
    if (m.kind === "undrained") add("su", m.su);
    else if (m.kind === "hb") { add("GSI", m.GSI); add("sci", m.sci); }
    else { add("tanphi", Math.tan((m.phi || 0) * Math.PI / 180)); add("c", m.c || 0); }
    add("gamma", m.gamma);
  }
  return out;
}

/** Lognormal with mean m and COV v: the value at standard normal z. */
const logn = (m, v, z) => { const s2 = Math.log(1 + v * v); return m * Math.exp(-s2 / 2 + Math.sqrt(s2) * z); };

/** A copy of the prepared model with the variables set to values. */
function withValues(P, vars, values) {
  const layers = P.layers.map((L) => ({ ...L, mat: { ...L.mat } }));
  vars.forEach((v, i) => {
    for (const k of v.layers) {
      const m = layers[k].mat, x = values[i];
      if (v.prop === "tanphi") m.phi = Math.atan(x) * 180 / Math.PI;
      else if (v.prop === "gamma") { m.gsat = (m.gsat || m.gamma) * x / m.gamma; m.gamma = x; }
      else m[v.prop] = x;
      if (m.kind === "hb" && (v.prop === "GSI" || v.prop === "sci")) {
        const g = Math.max(5, Math.min(100, m.GSI)), d = m.D || 0;
        m.mb = m.mi * Math.exp((g - 100) / (28 - 14 * d)); m.s = Math.exp((g - 100) / (9 - 3 * d));
        m.a = 0.5 + (Math.exp(-g / 15) - Math.exp(-20 / 3)) / 6; m.sigci = Math.max(1, m.sci) * 1000;
      }
    }
  });
  return { ...P, layers };
}

/** F on a fixed surface for given values of the variables. */
function fAt(P, vars, values, surface, method, n) {
  const Q = withValues(P, vars, values);
  const cut = buildSlices(Q, surface.slip, { n, exact: true });
  if (!cut) return NaN;
  if (cut.slices.some((s) => s.hb)) return refineHB(Q, cut, surface.circle, method, 1e-4, 12)?.F ?? NaN;
  return quickF(Q, cut, surface.circle, method);
}

/**
 * Monte Carlo (Latin hypercube) on the critical surface of one load case.
 * opt: { caseKey, n (samples), seed, cov: { prop: COV }, onProgress(done, n) }
 */
export function probabilistic(project, opt = {}) {
  const p = complete(project);
  const built = buildCases(p);
  const method = p.design?.method || "mp";
  const cs = built.cases.find((c) => c.key === opt.caseKey) || built.cases[0];
  const slices = Math.max(10, Math.min(200, +p.advanced?.slices || 40));
  const det = analyseCase(cs, { method, slices, noncircular: !!p.advanced?.noncircular, block: !!p.advanced?.block });
  if (det.error) return { error: det.error };
  const P = det._P, surface = { slip: det._r.cut.slip, circle: det._r.circle };
  const m = det.method;
  const vars = variablesOf(P, opt.cov);
  const N = Math.max(50, Math.min(20000, Math.round(opt.n || 1000)));
  const R = rng(opt.seed ?? 1);
  // Latin hypercube: every variable has one sample in each of N equal-probability strata
  const z = vars.map(() => {
    const perm = Array.from({ length: N }, (_, i) => i);
    for (let i = N - 1; i > 0; i--) { const j = Math.floor(R() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
    return perm.map((k) => normInv((k + R()) / N));
  });
  const F = new Float64Array(N);
  for (let i = 0; i < N; i++) {
    F[i] = fAt(P, vars, vars.map((v, j) => logn(v.mean, v.cov, z[j][i])), surface, m, slices);
    if (opt.onProgress && (i + 1) % 50 === 0) opt.onProgress(i + 1, N);
  }
  const ok = Array.from(F).filter(Number.isFinite);
  const mean = ok.reduce((a, b) => a + b, 0) / ok.length;
  const sd = Math.sqrt(ok.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, ok.length - 1));
  const fails = ok.filter((f) => f < 1).length;
  const V = sd / mean;
  const betaN = (mean - 1) / sd;
  const betaLN = Math.log(mean / Math.sqrt(1 + V * V)) / Math.sqrt(Math.log(1 + V * V));
  const sorted = ok.slice().sort((a, b) => a - b);
  const q = (t) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(t * (sorted.length - 1))))];
  // histogram
  const lo = sorted[0], hi = sorted[sorted.length - 1], bins = 30;
  const w = (hi - lo) / bins || 1;
  const hist = Array.from({ length: bins }, (_, i) => ({ x0: lo + i * w, x1: lo + (i + 1) * w, n: 0 }));
  for (const f of ok) hist[Math.min(bins - 1, Math.floor((f - lo) / w))].n++;
  // sensitivity: each variable alone at its 16th and 84th percentile (mean -/+ one standard deviation)
  const base = vars.map((v) => v.mean);
  const Fmean = fAt(P, vars, base, surface, m, slices);
  const sens = vars.map((v, j) => {
    const at = (zz) => fAt(P, vars, base.map((b, k) => (k === j ? logn(v.mean, v.cov, zz) : b)), surface, m, slices);
    const a = at(-1), b = at(1);
    return { name: v.name, prop: v.prop, cov: v.cov, mean: v.mean, low: Math.min(a, b), high: Math.max(a, b), swing: Math.abs(b - a) };
  }).sort((a, b) => b.swing - a.swing);
  // Monte Carlo standard error of the probability of failure
  const pf = fails / ok.length;
  return {
    case: { key: cs.key, name: cs.name, target: cs.target }, method: m, methodName: METHOD_NAMES[m],
    deterministic: det.F, atMeans: Fmean, n: ok.length, failed: N - ok.length, seed: opt.seed ?? 1,
    mean, sd, cov: V, pf, pfSE: Math.sqrt(Math.max(pf * (1 - pf), 1 / ok.length) / ok.length), fails,
    betaN, betaLN, pfLN: normCdf(-betaLN), p05: q(0.05), p50: q(0.5), p95: q(0.95), min: lo, max: hi,
    hist, sens, vars: vars.map((v) => ({ name: v.name, prop: v.prop, mean: v.mean, cov: v.cov })),
  };
}

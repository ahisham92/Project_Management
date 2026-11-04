// Talus — rapid drawdown by the three-stage method of Duncan, Wright and Wong (1990),
// as adopted by USACE EM 1110-2-1902 (2003), Appendix G.
//
// Stage 1. Before drawdown (full water, steady seepage), drained strengths: the
//   effective normal stress σ'fc and the shear stress τfc on the base of every slice
//   are the consolidation stresses on the future failure plane.
// Stage 2. After drawdown, each slice of a soil that does not drain freely takes an
//   undrained strength interpolated by the consolidation stress ratio Kc between the
//   envelope for isotropic consolidation (Kc = 1, from the R envelope cR, φR) and the
//   effective-stress envelope (Kc = Kf). Free-draining soils keep drained strengths
//   with the pore pressures after drawdown.
// Stage 3. Where the drained strength at the stage 2 effective normal stress is lower
//   than the undrained strength, the drained strength is used, and F is found again.
// Every stage is solved on the same slip surface; the critical surface is the one with
// the lowest stage 3 factor of safety.

import { buildSlices, factors, valueOf, sliceForces, DEG } from "./lem.js";
import { trialCircle, limits, nelderMead } from "./search.js";

/** A soil drains freely during drawdown when its permeability is at least this (m/s). */
export const FREE_DRAINING_K = 1e-5;
/** The R envelope (consolidated-undrained, total stress) when none is entered: φR 14°, cR = c'. */
export const R_DEFAULT_PHI = 14;

/** Does a material drain during drawdown? An explicit choice wins over its permeability. */
export function drainsFreely(mat) {
  if (mat.drains === true || mat.drains === false) return mat.drains;
  if (mat.kind === "hb") return true;
  return (mat.k ?? 0) >= FREE_DRAINING_K;
}

/**
 * The undrained strength on a slice base after drawdown, from its consolidation
 * stresses: { tau, Kc, Kf, t1, tKf }. sfc, tfc in kPa; c, phi, cR, phiR the envelopes.
 */
export function stagedStrength(sfc, tfc, { c, phi, cR, phiR }) {
  const sp = Math.sin(phi * DEG), cp = Math.cos(phi * DEG);
  const sr = Math.sin(phiR * DEG), cr = Math.cos(phiR * DEG);
  const s = Math.max(0, sfc), t = Math.max(0, tfc);
  // the two envelopes in terms of the consolidation normal stress on the failure plane
  const t1 = cR * cr * cr / (1 - sr) + s * sr * cr / (1 - sr);   // Kc = 1 (σ'fc = σ'3c)
  const tKf = c + s * Math.tan(phi * DEG);                         // Kc = Kf (effective envelope)
  // the principal stress ratio at consolidation, and the one on the failure envelope
  const s1c = s + t * (1 + sp) / cp, s3c = s - t * (1 - sp) / cp;
  const denom = s - c * cp;
  const Kf = denom > 1e-9 ? (1 + sp) * (s + c * cp) / ((1 - sp) * denom) : Infinity;
  let Kc = s3c > 1e-9 ? s1c / s3c : Kf;
  if (!Number.isFinite(Kf)) Kc = Infinity;
  Kc = Math.min(Math.max(1, Kc), Kf);
  let tau;
  if (t1 >= tKf) tau = tKf;                                  // the lower of the two envelopes
  else if (!Number.isFinite(Kf) || Kf - 1 < 1e-9) tau = tKf;
  else tau = ((Kf - Kc) * t1 + (Kc - 1) * tKf) / (Kf - 1);
  return { tau, Kc, Kf, t1, tKf };
}

/** The stress on the base of the stage 1 slice under x. */
function stressAt(rows, x) {
  let lo = 0, hi = rows.length - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (rows[m].x0 <= x) lo = m; else hi = m; }
  const r = x >= rows[hi].x0 ? rows[hi] : rows[lo];
  return r;
}

/**
 * The three stages on one slip surface. P1: the model before drawdown, P2: after it,
 * both prepared, drained strengths. Returns { F, F1, F2, F3, cut, results, rows } or null.
 */
export function stagedF(P1, P2, slip, circle, method, n = 40, mats = null) {
  const cut1 = buildSlices(P1, slip, { n, exact: true });
  const cut2 = buildSlices(P2, slip, { n, exact: true });
  if (!cut1 || !cut2) return null;
  const r1 = factors(P1, cut1, circle, [method]);
  const F1 = valueOf(r1, method);
  if (!(F1 > 0)) return null;
  const lam1 = r1[method]?.lambda ?? 0;
  const sf1 = sliceForces(P1, cut1, circle, method, F1, lam1);
  const rows = cut1.slices.map((s, i) => ({ x0: s.x0, sfc: Math.max(0, sf1[i].Neff / s.l), tfc: Math.max(0, sf1[i].S / s.l) }));
  const matOf = mats || new Map(P2.layers.map((L) => [L.mat.name, L.mat]));
  // stage 2: undrained strengths in the soils that do not drain
  const info = cut2.slices.map((s) => {
    const m = matOf.get(s.mat);
    if (!m || m.kind !== "drained" || drainsFreely(m)) return null;
    const st = stressAt(rows, s.xm);
    const env = { c: m.c || 0, phi: m.phi || 0, cR: m.cR ?? (m.c || 0), phiR: Math.min(m.phiR ?? R_DEFAULT_PHI, m.phi || 0) };
    const u = stagedStrength(st.sfc, st.tfc, env);
    return { ...u, sfc: st.sfc, tfc: st.tfc, drained: { c: s.c, tanphi: s.tanphi } };
  });
  info.forEach((d, i) => { if (d) { cut2.slices[i].c = d.tau / P2.f.su; cut2.slices[i].tanphi = 0; } });
  let res = factors(P2, cut2, circle, [method]);
  const F2 = valueOf(res, method);
  if (!(F2 > 0)) return null;
  // stage 3: the drained strength where it is lower, at the stage 2 effective stresses
  const sf2 = sliceForces(P2, cut2, circle, method, F2, res[method]?.lambda ?? 0);
  let changed = 0;
  info.forEach((d, i) => {
    if (!d) return;
    const s = cut2.slices[i];
    const sd = d.drained.c + Math.max(0, sf2[i].Neff / s.l) * d.drained.tanphi;
    d.sd = sd;
    if (sd < s.c) { s.c = d.drained.c; s.tanphi = d.drained.tanphi; d.used = "drained"; changed++; }
    else d.used = "undrained";
  });
  let F3 = F2;
  if (changed) { res = factors(P2, cut2, circle, [method]); F3 = valueOf(res, method); }
  return { F: F3, F1, F2, F3, changed, cut: cut2, results: res, rows: info };
}

/**
 * The critical circle for the three-stage method: the conventional search gives the
 * candidates, the best few are solved in three stages, and the lowest is polished
 * with the staged factor of safety itself.
 */
export function stagedSearch(P1, P2, conventional, opt = {}) {
  const method = opt.method || "mp", n = opt.slices || 40;
  const lim = limits(P2, opt);
  const mats = new Map(P2.layers.map((L) => [L.mat.name, L.mat]));
  const evalAt = ([xe, xx, th], nn = 24) => {
    const t = trialCircle(P2, xe, xx, th, lim, nn, true);
    if (!t) return null;
    const r = stagedF(P1, P2, t.cut.slip, t.circle, method, nn, mats);
    return r && Number.isFinite(r.F) && r.F > 0 ? { ...r, t } : null;
  };
  // candidates: the conventional critical surface and the spread of its trials
  const cands = [];
  if (conventional?.xe !== undefined) cands.push([conventional.xe, conventional.xx, conventional.theta ?? null]);
  const span = lim.exit[1] - lim.entry[0];
  for (const t of conventional?.trials || []) {
    if (cands.length >= (opt.candidates ?? 16)) break;
    if (cands.every((c) => Math.abs(c[0] - t.xe) + Math.abs(c[1] - t.xx) > 0.04 * span)) cands.push([t.xe, t.xx, t.theta]);
  }
  let best = null;
  for (const c of cands) {
    if (c[2] === null) continue;
    const r = evalAt(c);
    if (r && (!best || r.F < best.f)) best = { x: c, f: r.F };
  }
  if (!best) return null;
  const de = (lim.entry[1] - lim.entry[0]) / 14, dx = (lim.exit[1] - lim.exit[0]) / 14;
  const nm = nelderMead((x) => evalAt(x)?.F ?? Infinity, best.x, [de, dx, 6 * DEG], opt.refine ?? 40);
  if (nm.f < best.f) best = { x: nm.x, f: nm.f };
  const fin = evalAt(best.x, n);
  if (!fin) return null;
  const all = factors(P2, fin.cut, fin.t.circle);
  return {
    kind: "circle", circle: fin.t.circle, cut: fin.cut, results: all, method, F: valueOf(all, method),
    xe: fin.t.xe, xx: fin.t.xx, depth: fin.t.depth, trials: conventional?.trials || [],
    staged: { F1: fin.F1, F2: fin.F2, F3: fin.F3, changed: fin.changed,
      slices: fin.rows.filter(Boolean).length, drainedSlices: fin.rows.filter((d) => d?.used === "drained").length,
      conventional: conventional?.F },
  };
}

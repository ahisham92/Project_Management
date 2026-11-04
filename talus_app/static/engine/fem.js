// Talus — the factor of safety by finite element strength reduction.
//
// The method of Griffiths and Lane (1999), as programmed by Smith, Griffiths and
// Margetts (Programming the Finite Element Method, program 6.x):
//  - plane strain, 8-node quadrilaterals with 2 x 2 (reduced) Gauss integration, on a
//    mesh whose columns follow the ground and whose rows follow it down to the base;
//  - elastic-viscoplastic Mohr-Coulomb soil, non-associated (dilation ψ = 0); stiffness
//    E and ν do not change F, so they are fixed;
//  - gravity switched on at once (γ above the water, γsat below), water standing on the
//    ground as a pressure on it, surcharge strips, the seismic kh and kv as body forces;
//    yield on effective stresses (total less the pore pressure) for drained soils and on
//    total stresses for undrained ones;
//  - the strengths are divided by a strength reduction factor SRF (c / SRF, tan φ / SRF,
//    su / SRF); the stiffness is factorised once and the viscoplastic iterations run
//    until the displacements settle. The factor of safety is the SRF at which they no
//    longer settle within the iteration limit (failure), found by bisection.
// The base is fixed, the ends are on rollers. Reinforcement is not modelled here.

import { yAt } from "./geometry.js";
import { prepare, layerAt, strength, column, DEG } from "./lem.js";
import { hbEquivalent } from "./materials.js";
import { buildCases } from "./project.js";

const E = 1e5, NU = 0.3;   // kPa; F does not depend on them (Griffiths and Lane 1999)

// 8-node serendipity element: corners (-1,-1) (1,-1) (1,1) (-1,1), then the mid-sides
const XI = [-1, 1, 1, -1, 0, 1, 0, -1], ETA = [-1, -1, 1, 1, -1, 0, 1, 0];
function shape(xi, eta) {
  const N = new Float64Array(8), dxi = new Float64Array(8), deta = new Float64Array(8);
  for (let i = 0; i < 4; i++) {
    const a = XI[i], b = ETA[i];
    N[i] = 0.25 * (1 + xi * a) * (1 + eta * b) * (xi * a + eta * b - 1);
    dxi[i] = 0.25 * a * (1 + eta * b) * (2 * xi * a + eta * b);
    deta[i] = 0.25 * b * (1 + xi * a) * (xi * a + 2 * eta * b);
  }
  for (let i = 4; i < 8; i++) {
    const a = XI[i], b = ETA[i];
    if (a === 0) { N[i] = 0.5 * (1 - xi * xi) * (1 + eta * b); dxi[i] = -xi * (1 + eta * b); deta[i] = 0.5 * b * (1 - xi * xi); }
    else { N[i] = 0.5 * (1 + xi * a) * (1 - eta * eta); dxi[i] = 0.5 * a * (1 - eta * eta); deta[i] = -eta * (1 + xi * a); }
  }
  return { N, dxi, deta };
}
const G = 1 / Math.sqrt(3);
const GAUSS = [[-G, -G], [G, -G], [G, G], [-G, G]];
const SHAPES = GAUSS.map(([a, b]) => shape(a, b));

/** The mesh: nx columns of elements between the ends, ny rows from the base to the ground. */
export function femMesh(P, { nx = 30, ny = 10 } = {}) {
  const x0 = P.xmin, x1 = P.xmax;
  const set = new Set(P.ground.map((p) => +p[0].toFixed(6)));
  for (let i = 0; i <= nx; i++) set.add(+(x0 + (x1 - x0) * i / nx).toFixed(6));
  let xs = [...set].sort((a, b) => a - b);
  const keep = new Set(P.ground.map((p) => +p[0].toFixed(6)));
  const dx = (x1 - x0) / nx;
  xs = xs.filter((x, i) => i === 0 || i === xs.length - 1 || keep.has(x) || (x - xs[i - 1] > 0.35 * dx && xs[i + 1] - x > 0.35 * dx));
  const ncol = xs.length - 1;
  // half-columns and half-rows; node (c, r) exists unless both are odd (element centre)
  const cx = [];
  for (let i = 0; i < ncol; i++) cx.push(xs[i], (xs[i] + xs[i + 1]) / 2);
  cx.push(xs[ncol]);
  const R = 2 * ny;
  const id = new Int32Array((2 * ncol + 1) * (R + 1)).fill(-1);
  const X = [], Y = [];
  for (let c = 0; c <= 2 * ncol; c++) {
    const top = yAt(P.ground, cx[c]);
    for (let r = 0; r <= R; r++) {
      if (c % 2 === 1 && r % 2 === 1) continue;
      id[c * (R + 1) + r] = X.length;
      X.push(cx[c]); Y.push(P.bottom + (top - P.bottom) * r / R);
    }
  }
  const at = (c, r) => id[c * (R + 1) + r];
  const els = [];
  for (let i = 0; i < ncol; i++) for (let j = 0; j < ny; j++) {
    const c = 2 * i, r = 2 * j;
    els.push([at(c, r), at(c + 2, r), at(c + 2, r + 2), at(c, r + 2), at(c + 1, r), at(c + 2, r + 1), at(c + 1, r + 2), at(c, r + 1)]);
  }
  // the ground edges: [corner, mid, corner] along the top of the top row, left to right
  const top = [];
  for (let i = 0; i < ncol; i++) top.push([at(2 * i, R), at(2 * i + 1, R), at(2 * i + 2, R)]);
  return { xs, ncol, ny, X: Float64Array.from(X), Y: Float64Array.from(Y), els, top, n: X.length, at, R };
}

/** Band Cholesky in place (lower band of half-width w). */
function bandFactor(A, n, w) {
  const W = w + 1;
  for (let i = 0; i < n; i++) {
    const j0 = Math.max(0, i - w);
    for (let j = j0; j <= i; j++) {
      let s = A[i * W + (i - j)];
      const k0 = Math.max(j0, j - w);
      for (let k = k0; k < j; k++) s -= A[i * W + (i - k)] * A[j * W + (j - k)];
      if (i === j) { if (!(s > 0)) return false; A[i * W] = Math.sqrt(s); }
      else A[i * W + (i - j)] = s / A[j * W];
    }
  }
  return true;
}
function bandSolve(A, b, n, w) {
  const W = w + 1;
  for (let i = 0; i < n; i++) {
    let s = b[i];
    for (let k = Math.max(0, i - w); k < i; k++) s -= A[i * W + (i - k)] * b[k];
    b[i] = s / A[i * W];
  }
  for (let i = n - 1; i >= 0; i--) {
    let s = b[i];
    const kmax = Math.min(n - 1, i + w);
    for (let k = i + 1; k <= kmax; k++) s -= A[k * W + (k - i)] * b[k];
    b[i] = s / A[i * W];
  }
}

/** The finite element model of a prepared slope: stiffness factorised, loads, Gauss points. */
export function femModel(P, opt = {}) {
  const M = femMesh(P, opt);
  const { X, Y, els, n } = M;
  // equations: base fixed, ends on rollers (no horizontal movement)
  const xa = M.xs[0], xb = M.xs[M.xs.length - 1];
  const eq = new Int32Array(2 * n).fill(-1);
  let neq = 0;
  for (let k = 0; k < n; k++) {
    const base = Math.abs(Y[k] - P.bottom) < 1e-9, end = Math.abs(X[k] - xa) < 1e-9 || Math.abs(X[k] - xb) < 1e-9;
    if (!base && !end) eq[2 * k] = neq++;
    if (!base) eq[2 * k + 1] = neq++;
  }
  // half bandwidth
  let w = 0;
  for (const e of els) {
    let lo = Infinity, hi = -Infinity;
    for (const k of e) for (const d of [0, 1]) { const q = eq[2 * k + d]; if (q >= 0) { lo = Math.min(lo, q); hi = Math.max(hi, q); } }
    w = Math.max(w, hi - lo);
  }
  const W = w + 1;
  const f = E / ((1 + NU) * (1 - 2 * NU));
  const D = [[f * (1 - NU), f * NU, 0, f * NU], [f * NU, f * (1 - NU), 0, f * NU], [0, 0, f * (1 - 2 * NU) / 2, 0], [f * NU, f * NU, 0, f * (1 - NU)]];
  const K = new Float64Array(neq * W);
  const loads = new Float64Array(neq);
  const gw = P.gw;
  const piezoAt = (x) => (P.piezo && !(P.ru > 0) ? yAt(P.piezo, x) : -Infinity);
  const poreAt = (x, y) => {
    if (P.ru > 0) return P.ru * column(P, x, y).w;
    if (P.pw) return P.pw(x, y);
    return gw * Math.max(0, piezoAt(x) - y);
  };
  // Gauss point data: B (3 x 16 packed), weight * det J, position, material, pore pressure
  const ngp = els.length * 4;
  const B = new Float64Array(ngp * 3 * 16), wdet = new Float64Array(ngp), gx = new Float64Array(ngp), gy = new Float64Array(ngp);
  const u0 = new Float64Array(ngp), gmat = [];
  const ke = new Float64Array(16 * 16), fe = new Float64Array(16);
  els.forEach((e, ie) => {
    ke.fill(0); fe.fill(0);
    for (let g = 0; g < 4; g++) {
      const { N, dxi, deta } = SHAPES[g];
      let j11 = 0, j12 = 0, j21 = 0, j22 = 0, x = 0, y = 0;
      for (let a = 0; a < 8; a++) {
        const k = e[a];
        j11 += dxi[a] * X[k]; j12 += dxi[a] * Y[k]; j21 += deta[a] * X[k]; j22 += deta[a] * Y[k];
        x += N[a] * X[k]; y += N[a] * Y[k];
      }
      const det = j11 * j22 - j12 * j21;
      const gp = ie * 4 + g;
      wdet[gp] = det; gx[gp] = x; gy[gp] = y;
      const off = gp * 48;
      for (let a = 0; a < 8; a++) {
        const dx = (j22 * dxi[a] - j12 * deta[a]) / det, dy = (-j21 * dxi[a] + j11 * deta[a]) / det;
        B[off + 2 * a] = dx;            // εx  row 0
        B[off + 16 + 2 * a + 1] = dy;   // εy  row 1
        B[off + 32 + 2 * a] = dy;       // γxy row 2
        B[off + 32 + 2 * a + 1] = dx;
      }
      // material and unit weight here
      const at = layerAt(P, x, y);
      const mat = P.layers[at.layer].mat;
      gmat.push({ mat, depth: at.depth });
      const gam = y < piezoAt(x) ? (mat.gsat ?? mat.gamma) : mat.gamma;
      u0[gp] = poreAt(x, y);
      // stiffness: Bᵀ D B (εz = 0 in plane strain, so the 3 x 3 part of D)
      for (let p = 0; p < 16; p++) for (let q = 0; q < 16; q++) {
        let s = 0;
        for (let r = 0; r < 3; r++) {
          const bp = B[off + 16 * r + p];
          if (!bp) continue;
          for (let t = 0; t < 3; t++) s += bp * D[r][t] * B[off + 16 * t + q];
        }
        ke[p * 16 + q] += s * det;
      }
      // body force: gravity (less the vertical seismic part) and the horizontal kh
      for (let a = 0; a < 8; a++) {
        fe[2 * a] += N[a] * P.kh * gam * det;
        fe[2 * a + 1] -= N[a] * gam * (1 - P.kv) * det;
      }
    }
    for (let p = 0; p < 16; p++) {
      const I = eq[2 * e[p >> 1] + (p & 1)];
      if (I < 0) continue;
      loads[I] += fe[p];
      for (let q = 0; q < 16; q++) {
        const J = eq[2 * e[q >> 1] + (q & 1)];
        if (J < 0 || J > I) continue;
        K[I * W + (I - J)] += ke[p * 16 + q];
      }
    }
  });
  // loads on the ground: water standing on it (normal pressure) and surcharge strips
  const G5 = [[-0.9061798459, 0.2369268851], [-0.5384693101, 0.4786286705], [0, 0.5688888889], [0.5384693101, 0.4786286705], [0.9061798459, 0.2369268851]];
  for (const edge of M.top) {
    const [a, m, b] = edge;
    for (const [s, wt] of G5) {
      const Ns = [0.5 * s * (s - 1), 1 - s * s, 0.5 * s * (s + 1)], dN = [s - 0.5, -2 * s, s + 0.5];
      let x = 0, y = 0, dxs = 0, dys = 0;
      [a, m, b].forEach((k, i) => { x += Ns[i] * X[k]; y += Ns[i] * Y[k]; dxs += dN[i] * X[k]; dys += dN[i] * Y[k]; });
      let fx = 0, fy = 0;
      const pw = gw * Math.max(0, piezoAt(x) - y);
      if (pw > 0) { fx += pw * dys; fy += -pw * dxs; }      // -p n dl, n dl = (-dy, dx)
      for (const st of P.strips) if (x >= st.x1 && x <= st.x2) fy -= st.q * Math.abs(dxs);
      [a, m, b].forEach((k, i) => {
        const ix = eq[2 * k], iy = eq[2 * k + 1];
        if (ix >= 0) loads[ix] += Ns[i] * fx * wt;
        if (iy >= 0) loads[iy] += Ns[i] * fy * wt;
      });
    }
  }
  if (!bandFactor(K, neq, w)) return null;
  return { P, M, eq, neq, w, K, loads, B, wdet, gx, gy, u0, gmat, D, ngp };
}

/** Principal stresses of [sx, sy, txy, sz] and the flow vector of Q = (σ1 - σ3) / 2. */
function mohrCoulomb(s, c, sinphi, cosphi, out) {
  const [sx, sy, txy, sz] = s;
  const m = (sx + sy) / 2, r = Math.hypot((sx - sy) / 2, txy);
  const pa = m + r, pb = m - r;
  const th = 0.5 * Math.atan2(2 * txy, sx - sy);      // direction of pa
  const ca = Math.cos(th), sa = Math.sin(th);
  // in-plane principal directions as flow vectors [x, y, xy (engineering), z]
  const va = [ca * ca, sa * sa, 2 * ca * sa, 0], vb = [sa * sa, ca * ca, -2 * ca * sa, 0], vz = [0, 0, 0, 1];
  const all = [[pa, va], [pb, vb], [sz, vz]].sort((p, q) => q[0] - p[0]);
  const s1 = all[0][0], s3 = all[2][0];
  const F = (s1 - s3) / 2 + (s1 + s3) / 2 * sinphi - c * cosphi;   // tension positive
  for (let k = 0; k < 4; k++) out[k] = 0.5 * (all[0][1][k] - all[2][1][k]);
  return F;
}

/**
 * The viscoplastic solution at one strength reduction factor.
 * Returns { converged, iters, x (displacements by equation), evpt }.
 */
export function solveSRF(F, srf, opt = {}) {
  const { neq, w, K, loads, B, wdet, gmat, u0, D, ngp, eq, M, P } = F;
  const limit = opt.limit ?? 500, tol = opt.tol ?? 1e-4;
  // the reduced strength at each Gauss point
  const cc = new Float64Array(ngp), sp = new Float64Array(ngp), cp = new Float64Array(ngp), drained = new Uint8Array(ngp);
  let dt = Infinity;
  for (let g = 0; g < ngp; g++) {
    const { mat, depth } = gmat[g];
    let c, tanphi;
    if (mat.kind === "hb") {
      const eqv = hbEquivalent(mat, mat.gamma, opt.H || 10);
      c = eqv.c / P.f.c; tanphi = Math.tan(eqv.phi * DEG) / P.f.tanphi;
    } else ({ c, tanphi } = strength(P, mat, depth));
    const phi = Math.atan(tanphi / srf);
    cc[g] = c / srf; sp[g] = Math.sin(phi); cp[g] = Math.cos(phi);
    drained[g] = mat.kind === "undrained" ? 0 : 1;
    dt = Math.min(dt, 4 * (1 + NU) * (1 - 2 * NU) / (E * (1 - 2 * NU + sp[g] * sp[g])));
  }
  const evpt = new Float64Array(ngp * 4);
  const bdy = new Float64Array(neq);
  let x = new Float64Array(neq), xOld = new Float64Array(neq);
  const sig = [0, 0, 0, 0], flow = [0, 0, 0, 0], ue = new Float64Array(16), idx = new Int32Array(16);
  let iters = 0, converged = false;
  for (iters = 1; iters <= limit; iters++) {
    x = new Float64Array(neq);
    for (let i = 0; i < neq; i++) x[i] = loads[i] + bdy[i];
    bandSolve(K, x, neq, w);
    // convergence: the largest change in displacement against the largest displacement
    let dmax = 0, xmax = 0;
    for (let i = 0; i < neq; i++) { dmax = Math.max(dmax, Math.abs(x[i] - xOld[i])); xmax = Math.max(xmax, Math.abs(x[i])); }
    xOld = x;
    if (iters > 1 && dmax <= tol * xmax) { converged = true; break; }
    // the body loads accumulate: they carry the whole viscoplastic strain so far
    let yielding = 0;
    M.els.forEach((e, ie) => {
      for (let p = 0; p < 16; p++) { const q = eq[2 * e[p >> 1] + (p & 1)]; idx[p] = q; ue[p] = q >= 0 ? x[q] : 0; }
      for (let g4 = 0; g4 < 4; g4++) {
        const g = ie * 4 + g4, off = g * 48, ev = g * 4;
        // strain less the viscoplastic strain, then stress
        let ex = 0, ey = 0, gxy = 0;
        for (let p = 0; p < 16; p++) { ex += B[off + p] * ue[p]; ey += B[off + 16 + p] * ue[p]; gxy += B[off + 32 + p] * ue[p]; }
        const el = [ex - evpt[ev], ey - evpt[ev + 1], gxy - evpt[ev + 2], -evpt[ev + 3]];
        for (let r = 0; r < 4; r++) sig[r] = D[r][0] * el[0] + D[r][1] * el[1] + D[r][2] * el[2] + D[r][3] * el[3];
        // effective stresses (tension positive): add the pore pressure to the normal stresses
        if (drained[g]) { const u = u0[g]; sig[0] += u; sig[1] += u; sig[3] += u; }
        const fy = mohrCoulomb(sig, cc[g], sp[g], cp[g], flow);
        if (fy <= 0) continue;
        yielding++;
        const dev = [fy * flow[0] * dt, fy * flow[1] * dt, fy * flow[2] * dt, fy * flow[3] * dt];
        evpt[ev] += dev[0]; evpt[ev + 1] += dev[1]; evpt[ev + 2] += dev[2]; evpt[ev + 3] += dev[3];
        // the body loads that carry the viscoplastic strain: Bᵀ D εvp
        const s0 = D[0][0] * dev[0] + D[0][1] * dev[1] + D[0][3] * dev[3];
        const s1 = D[1][0] * dev[0] + D[1][1] * dev[1] + D[1][3] * dev[3];
        const s2 = D[2][2] * dev[2];
        const wd = wdet[g];
        for (let p = 0; p < 16; p++) {
          const q = idx[p];
          if (q < 0) continue;
          bdy[q] += (B[off + p] * s0 + B[off + 16 + p] * s1 + B[off + 32 + p] * s2) * wd;
        }
      }
    });
    if (!yielding && iters > 1) { converged = true; break; }
  }
  return { converged, iters: Math.min(iters, limit), x, evpt };
}

/**
 * Strength reduction: the factor of safety and the mechanism at failure.
 * opt: { guess (a factor of safety to bracket from), precision, limit, nx, ny }
 */
export function strengthReduction(model, opt = {}) {
  const P = prepare(model);
  const H = Math.max(0.5, P.face.crest[1] - P.face.toe[1]);
  const F = femModel(P, opt);
  if (!F) return { error: "The finite element stiffness could not be factorised." };
  const run = (srf) => { const r = solveSRF(F, srf, { ...opt, H }); opt.onRun?.(srf, r.converged, r.iters); return r; };
  const prec = opt.precision ?? 0.01;
  let lo = null, hi = null, runs = 0, fail = null, ok = null;
  const g = opt.guess > 0 ? opt.guess : 1.5;
  // bracket: converge at lo, fail at hi
  let s = g * 0.85;
  for (let k = 0; k < 12 && lo === null; k++) {
    const r = run(s); runs++;
    if (r.converged) { lo = s; ok = r; } else { hi = s; fail = r; s *= 0.8; }
  }
  if (lo === null) return { error: "Did not converge even at a low strength reduction factor.", runs };
  if (hi === null) {
    s = lo * 1.2;
    for (let k = 0; k < 15 && hi === null; k++) {
      const r = run(s); runs++;
      if (r.converged) { lo = s; ok = r; s *= 1.2; } else { hi = s; fail = r; }
    }
    if (hi === null) return { error: "Still stable at a strength reduction factor of " + lo.toFixed(2) + ".", runs };
  }
  while (hi - lo > prec * lo) {
    const m = (lo + hi) / 2;
    const r = run(m); runs++;
    if (r.converged) { lo = m; ok = r; } else { hi = m; fail = r; }
  }
  // the mechanism: what the failing run added to the last stable one
  return { F: lo, failedAt: hi, runs, mesh: meshOut(F, fail, ok), stable: meshOut(F, ok), elements: F.M.els.length, dof: F.neq, flip: P.flip };
}

/** Node positions, displacements and the shear strain per element, in the user's frame. */
function meshOut(F, r, base = null) {
  if (!r) return null;
  if (base) {
    r = { ...r, x: r.x.map((v, i) => v - base.x[i]), evpt: r.evpt.map((v, i) => v - base.evpt[i]) };
  }
  const { M, eq, P } = F;
  const sx = P.flip ? -1 : 1;
  const dx = [], dy = [];
  for (let k = 0; k < M.n; k++) {
    const ix = eq[2 * k], iy = eq[2 * k + 1];
    dx.push(ix >= 0 ? sx * r.x[ix] : 0); dy.push(iy >= 0 ? r.x[iy] : 0);
  }
  const shear = M.els.map((e, ie) => {
    let s = 0;
    for (let g = 0; g < 4; g++) { const v = (ie * 4 + g) * 4; s += Math.hypot(r.evpt[v] - r.evpt[v + 1], r.evpt[v + 2]); }
    return s / 4;
  });
  return { X: Array.from(M.X, (x) => sx * x), Y: Array.from(M.Y), dx, dy, els: M.els, shear, converged: r.converged, iters: r.iters, increment: !!base };
}

/** Strength reduction on one load case of a project. opt: { caseKey, guess, onRun } */
export function femCase(project, opt = {}) {
  const built = buildCases(project);
  const cs = built.cases.find((c) => c.key === opt.caseKey) || built.cases[0];
  const model = { ...cs.model, seismic: cs.model.seismic ? { kh: cs.model.seismic.kh, kv: 0 } : undefined };
  const r = strengthReduction(model, { nx: 30, ny: 10, precision: 0.01, ...opt });
  return { ...r, case: { key: cs.key, name: cs.name, target: cs.target }, lem: opt.guess ?? null,
    reinforced: (cs.model.reinforcement || []).length > 0 };
}

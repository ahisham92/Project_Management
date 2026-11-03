// Small, exact-in-principle finite element tools used by the rest of the engine.
//
//  * beamWinkler(): a straight Euler-Bernoulli beam on Winkler springs (a pontoon on
//    the water, or a pile in the ground), solved with consistent cubic elements.
//    Cubic Hermite elements are exact for a beam without foundation and converge
//    as h^4 with one; the element count is chosen so the error is negligible.
//  * modes(): natural frequencies and mode shapes of the same beam, with the
//    consistent mass matrix (generalised symmetric eigenproblem, Jacobi method).
//
// Units are whatever the caller uses consistently (the engine uses kN, m, t, s).

/** Dense symmetric matrix helpers (the systems here are at most ~300 DOF). */
export function zeros(n, m = n) { return Array.from({ length: n }, () => new Float64Array(m)); }

/** Solve A x = b for symmetric positive definite A (Cholesky). A is not modified. */
export function solveSPD(A, b) {
  const n = A.length, L = zeros(n);
  for (let j = 0; j < n; j++) {
    let s = A[j][j];
    for (let k = 0; k < j; k++) s -= L[j][k] * L[j][k];
    if (!(s > 0)) throw new Error("The structure is not restrained (matrix not positive definite).");
    L[j][j] = Math.sqrt(s);
    for (let i = j + 1; i < n; i++) {
      let t = A[i][j];
      for (let k = 0; k < j; k++) t -= L[i][k] * L[j][k];
      L[i][j] = t / L[j][j];
    }
  }
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) { let s = b[i]; for (let k = 0; k < i; k++) s -= L[i][k] * y[k]; y[i] = s / L[i][i]; }
  const x = new Float64Array(n);
  for (let i = n - 1; i >= 0; i--) { let s = y[i]; for (let k = i + 1; k < n; k++) s -= L[k][i] * x[k]; x[i] = s / L[i][i]; }
  return x;
}

function cholesky(A) {
  const n = A.length, L = zeros(n);
  for (let j = 0; j < n; j++) {
    let s = A[j][j];
    for (let k = 0; k < j; k++) s -= L[j][k] * L[j][k];
    if (!(s > 0)) throw new Error("Mass matrix not positive definite.");
    L[j][j] = Math.sqrt(s);
    for (let i = j + 1; i < n; i++) { let t = A[i][j]; for (let k = 0; k < j; k++) t -= L[i][k] * L[j][k]; L[i][j] = t / L[j][j]; }
  }
  return L;
}

/** Eigenvalues/vectors of a symmetric matrix by cyclic Jacobi rotations. */
export function jacobiEigen(Ain, tol = 1e-13, sweeps = 100) {
  const n = Ain.length, A = Ain.map((r) => Float64Array.from(r)), V = zeros(n);
  for (let i = 0; i < n; i++) V[i][i] = 1;
  for (let sweep = 0; sweep < sweeps; sweep++) {
    let off = 0, diag = 0;
    for (let i = 0; i < n; i++) { diag += A[i][i] * A[i][i]; for (let j = i + 1; j < n; j++) off += A[i][j] * A[i][j]; }
    if (off <= tol * tol * Math.max(diag, 1e-300)) break;
    for (let p = 0; p < n - 1; p++) for (let q = p + 1; q < n; q++) {
      const apq = A[p][q];
      if (Math.abs(apq) < 1e-300) continue;
      const th = (A[q][q] - A[p][p]) / (2 * apq);
      const t = Math.sign(th || 1) / (Math.abs(th) + Math.sqrt(th * th + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < n; k++) {
        const akp = A[k][p], akq = A[k][q];
        A[k][p] = c * akp - s * akq; A[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < n; k++) {
        const apk = A[p][k], aqk = A[q][k];
        A[p][k] = c * apk - s * aqk; A[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < n; k++) {
        const vkp = V[k][p], vkq = V[k][q];
        V[k][p] = c * vkp - s * vkq; V[k][q] = s * vkp + c * vkq;
      }
    }
  }
  const vals = Array.from({ length: n }, (_, i) => A[i][i]);
  return { vals, vecs: V };
}

/** K x = λ M x for symmetric K (semi-definite allowed) and positive definite M. */
export function generalEigen(K, M) {
  const n = K.length, L = cholesky(M);
  // Linv
  const Li = zeros(n);
  for (let i = 0; i < n; i++) {
    Li[i][i] = 1 / L[i][i];
    for (let j = 0; j < i; j++) { let s = 0; for (let k = j; k < i; k++) s -= L[i][k] * Li[k][j]; Li[i][j] = s / L[i][i]; }
  }
  // C = Li K Li^T
  const T = zeros(n), C = zeros(n);
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { let s = 0; for (let k = 0; k <= i; k++) s += Li[i][k] * K[k][j]; T[i][j] = s; }
  for (let i = 0; i < n; i++) for (let j = 0; j <= i; j++) { let s = 0; for (let k = 0; k <= j; k++) s += T[i][k] * Li[j][k]; C[i][j] = s; C[j][i] = s; }
  const { vals, vecs } = jacobiEigen(C);
  const order = vals.map((v, i) => i).sort((a, b) => vals[a] - vals[b]);
  return order.map((i) => {
    // x = Li^T y
    const y = vecs.map((r) => r[i]), x = new Float64Array(n);
    for (let r = 0; r < n; r++) { let s = 0; for (let k = r; k < n; k++) s += Li[k][r] * y[k]; x[r] = s; }
    return { lambda: Math.max(0, vals[i]), x };
  });
}

/**
 * A beam of length L on Winkler springs.
 *   EI        flexural rigidity (kN·m²)
 *   k(x)      spring per unit length (kN/m per m), a number or a function of x
 *   m         mass per unit length (t/m) — only for modes()
 *   n         number of elements
 *   supports  [{x, kind: "pin"|"fix"|"spring", k}] point restraints
 * DOF per node: w (deflection), θ (rotation).
 */
export function assemble({ L, EI, k = 0, m = 0, n = 60, supports = [], nodesAt = [], banded = false }) {
  // nodes: uniform, plus any requested positions so loads/supports land on nodes
  let xs = Array.from({ length: n + 1 }, (_, i) => (L * i) / n);
  for (const x of [...nodesAt, ...supports.map((s) => s.x)]) if (x > 0 && x < L && !xs.some((v) => Math.abs(v - x) < 1e-9)) xs.push(x);
  xs.sort((a, b) => a - b);
  const N = xs.length, dof = 2 * N;
  // banded storage (half-bandwidth 3) for static solves; dense for the eigenproblem
  const BW = 3;
  const K = banded ? Array.from({ length: dof }, () => new Float64Array(2 * BW + 1)) : zeros(dof);
  const M = banded ? null : zeros(dof), elems = [];
  const addK = banded ? (i, j, v) => { K[i][j - i + BW] += v; } : (i, j, v) => { K[i][j] += v; };
  const kf = typeof k === "function" ? k : () => k;
  const EIf = typeof EI === "function" ? EI : () => EI;
  const mf = typeof m === "function" ? m : () => m;
  // 3-point Gauss on each element for a varying foundation modulus
  const G = [[-Math.sqrt(3 / 5), 5 / 9], [0, 8 / 9], [Math.sqrt(3 / 5), 5 / 9]];
  for (let e = 0; e < N - 1; e++) {
    const x0 = xs[e], h = xs[e + 1] - x0, xm = x0 + h / 2;
    const ei = EIf(xm);
    const ke = [
      [12, 6 * h, -12, 6 * h], [6 * h, 4 * h * h, -6 * h, 2 * h * h],
      [-12, -6 * h, 12, -6 * h], [6 * h, 2 * h * h, -6 * h, 4 * h * h],
    ].map((r) => r.map((v) => (v * ei) / h ** 3));
    // foundation and mass: ∫ N^T N (·) dx with Hermite shape functions
    const kfe = zeros(4), me = zeros(4);
    for (const [g, wg] of G) {
      const s = (g + 1) / 2, x = x0 + s * h;
      const Nf = [1 - 3 * s * s + 2 * s ** 3, h * (s - 2 * s * s + s ** 3), 3 * s * s - 2 * s ** 3, h * (-s * s + s ** 3)];
      const kv = kf(x), mv = mf(x);
      for (let a = 0; a < 4; a++) for (let b = 0; b < 4; b++) { kfe[a][b] += (wg / 2) * h * kv * Nf[a] * Nf[b]; me[a][b] += (wg / 2) * h * mv * Nf[a] * Nf[b]; }
    }
    const map = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3];
    elems.push(ke.map((r, a) => r.map((v, b) => v + kfe[a][b])));
    for (let a = 0; a < 4; a++) for (let b = 0; b < 4; b++) { addK(map[a], map[b], ke[a][b] + kfe[a][b]); if (M) M[map[a]][map[b]] += me[a][b]; }
  }
  const fixed = new Set();
  const node = (x) => xs.reduce((best, v, i) => (Math.abs(v - x) < Math.abs(xs[best] - x) ? i : best), 0);
  for (const s of supports) {
    const i = node(s.x);
    if (s.kind === "pin") fixed.add(2 * i);
    else if (s.kind === "fix") { fixed.add(2 * i); fixed.add(2 * i + 1); }
    else if (s.kind === "spring") addK(2 * i, 2 * i, s.k);
  }
  return { xs, K, M, fixed, node, elems, BW };
}

/** Banded Cholesky solve; A[i][j - i + bw] holds the entry (i, j) for |i − j| ≤ bw. */
export function solveBanded(A, b, bw) {
  const n = A.length, L = Array.from({ length: n }, () => new Float64Array(bw + 1)); // L[i][i − j]
  const a = (i, j) => A[i][j - i + bw];
  for (let j = 0; j < n; j++) {
    let s = a(j, j);
    for (let k = Math.max(0, j - bw); k < j; k++) s -= L[j][j - k] ** 2;
    if (!(s > 0)) throw new Error("The structure is not restrained (matrix not positive definite).");
    L[j][0] = Math.sqrt(s);
    for (let i = j + 1; i <= Math.min(n - 1, j + bw); i++) {
      let t = a(i, j);
      for (let k = Math.max(0, i - bw); k < j; k++) t -= L[i][i - k] * L[j][j - k];
      L[i][i - j] = t / L[j][0];
    }
  }
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) { let s = b[i]; for (let k = Math.max(0, i - bw); k < i; k++) s -= L[i][i - k] * y[k]; y[i] = s / L[i][0]; }
  const x = new Float64Array(n);
  for (let i = n - 1; i >= 0; i--) { let s = y[i]; for (let k = i + 1; k <= Math.min(n - 1, i + bw); k++) s -= L[k][k - i] * x[k]; x[i] = s / L[i][0]; }
  return x;
}

function reduce(A, keep) { return keep.map((i) => Float64Array.from(keep.map((j) => A[i][j]))); }

/**
 * Static solution. loads: [{x, P}] point forces (+ down / + in the w direction),
 * [{x, Mo}] point moments, and q(x) distributed (kN/m), integrated consistently.
 * Returns deflection, rotation, bending moment and shear at every node.
 */
export function beamWinkler(opts, loads = [], q = null) {
  const { xs, K, fixed, node, elems, BW } = assemble({ ...opts, nodesAt: [...(opts.nodesAt || []), ...loads.map((l) => l.x)], banded: true });
  const N = xs.length, dof = 2 * N, F = new Float64Array(dof), Fq = [];
  for (const l of loads) { const i = node(l.x); if (l.P) F[2 * i] += l.P; if (l.Mo) F[2 * i + 1] += l.Mo; }
  if (q) {
    const qf = typeof q === "function" ? q : () => q;
    const G = [[-Math.sqrt(3 / 5), 5 / 9], [0, 8 / 9], [Math.sqrt(3 / 5), 5 / 9]];
    for (let e = 0; e < N - 1; e++) {
      const x0 = xs[e], h = xs[e + 1] - x0;
      for (const [g, wg] of G) {
        const s = (g + 1) / 2, x = x0 + s * h, qv = qf(x);
        const Nf = [1 - 3 * s * s + 2 * s ** 3, h * (s - 2 * s * s + s ** 3), 3 * s * s - 2 * s ** 3, h * (-s * s + s ** 3)];
        Fq[e] = Fq[e] || [0, 0, 0, 0];
        for (let a = 0; a < 4; a++) { F[2 * e + a] += (wg / 2) * h * qv * Nf[a]; Fq[e][a] += (wg / 2) * h * qv * Nf[a]; }
      }
    }
  }
  // restrained DOFs: zero row and column, unit diagonal, zero load (exact for u = 0)
  for (const i of fixed) {
    for (let j = Math.max(0, i - BW); j <= Math.min(dof - 1, i + BW); j++) { K[i][j - i + BW] = 0; K[j][i - j + BW] = 0; }
    K[i][BW] = 1; F[i] = 0;
  }
  const u = solveBanded(K, F, BW);
  // Internal forces from each element's end forces, f = (Kb + Kf) u - F (exact
  // equilibrium of the element, foundation and loads included). Sagging moment
  // positive; at a node shared by two elements the two sides agree except where
  // a point load or moment acts, and the larger magnitude is kept.
  const Mn = new Float64Array(N), Vn = new Float64Array(N), seen = new Uint8Array(N);
  for (let e = 0; e < N - 1; e++) {
    const map = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3], Ke = elems[e];
    const fe = [0, 1, 2, 3].map((a) => Ke[a].reduce((t, kab, b) => t + kab * u[map[b]], 0) - (Fq[e]?.[a] || 0));
    const put = (i, M, V) => {
      if (!seen[i] || Math.abs(M) > Math.abs(Mn[i])) Mn[i] = M;
      if (!seen[i] || Math.abs(V) > Math.abs(Vn[i])) Vn[i] = V;
      seen[i] = 1;
    };
    put(e, fe[1], fe[0]);
    put(e + 1, -fe[3], -fe[2]);
  }
  return {
    x: xs, w: xs.map((_, i) => u[2 * i]), theta: xs.map((_, i) => u[2 * i + 1]),
    M: Array.from(Mn), V: Array.from(Vn),
  };
}

/** Natural modes of the beam: [{f (Hz), T (s), omega, shape: [w at xs]}]. */
export function modes(opts, count = 6) {
  const { xs, K, M, fixed } = assemble(opts);
  const dof = 2 * xs.length;
  const keep = [...Array(dof).keys()].filter((i) => !fixed.has(i));
  const res = generalEigen(reduce(K, keep), reduce(M, keep));
  return res.slice(0, count).map(({ lambda, x }) => {
    const u = new Float64Array(dof);
    keep.forEach((i, j) => { u[i] = x[j]; });
    const w = xs.map((_, i) => u[2 * i]);
    const peak = w.reduce((a, v) => (Math.abs(v) > Math.abs(a) ? v : a), 0) || 1;
    const omega = Math.sqrt(lambda);
    return { omega, f: omega / (2 * Math.PI), T: omega > 0 ? (2 * Math.PI) / omega : Infinity, shape: w.map((v) => v / peak), x: xs };
  });
}

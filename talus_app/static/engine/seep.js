// Talus — steady seepage by finite elements.
//
// The ground between its surface and the hard base is meshed in columns (one per
// ground vertex plus even divisions) and rows that follow the ground, split into
// linear triangles. Darcy flow with each element's permeability (by the layer at
// its centroid) is solved for the total head h. Unconfined flow is found the way
// SEEP/W and Slide do it: above the phreatic surface (pressure below zero) the
// permeability falls to a small residual, and the iterations repeat until the
// heads settle. Ground nodes above the outside water are a possible seepage face
// (h <= z): they are fixed at h = z where the water would otherwise rise above
// the ground, and freed again if water would flow in there.
//
// Result: heads at the nodes, pore pressure u = gw (h - y) anywhere, the phreatic
// line (u = 0), and the flow through the section.

import { yAt } from "./geometry.js";

/** Banded symmetric positive definite solve (lower band of half-width w), in place. */
function bandSolve(A, b, n, w) {
  // A[i * (w + 1) + (i - j)] holds K[i][j] for j in [i - w, i]
  const W = w + 1;
  for (let i = 0; i < n; i++) {
    for (let j = Math.max(0, i - w); j <= i; j++) {
      let s = A[i * W + (i - j)];
      for (let k = Math.max(0, i - w, j - w); k < j; k++) s -= A[i * W + (i - k)] * A[j * W + (j - k)];
      if (i === j) { if (!(s > 0)) return false; A[i * W] = Math.sqrt(s); }
      else A[i * W + (i - j)] = s / A[j * W];
    }
  }
  for (let i = 0; i < n; i++) {
    let s = b[i];
    for (let k = Math.max(0, i - w); k < i; k++) s -= A[i * W + (i - k)] * b[k];
    b[i] = s / A[i * W];
  }
  for (let i = n - 1; i >= 0; i--) {
    let s = b[i];
    for (let k = i + 1; k <= Math.min(n - 1, i + w); k++) s -= A[k * W + (k - i)] * b[k];
    b[i] = s / A[i * W];
  }
  return true;
}

/**
 * The mesh of a section: columns at xs, ny rows from the base up to the ground.
 * Node (i, j) is at x = xs[i], y = bottom + (ground(xs[i]) - bottom) * j / ny.
 */
export function meshOf(ground, bottom, { nx = 70, ny = 24 } = {}) {
  const x0 = ground[0][0], x1 = ground[ground.length - 1][0];
  const set = new Set(ground.map((p) => +p[0].toFixed(6)));
  for (let i = 0; i <= nx; i++) set.add(+(x0 + (x1 - x0) * i / nx).toFixed(6));
  let xs = [...set].sort((a, b) => a - b);
  // drop columns closer than a fifth of the even spacing (they only make slivers)
  const dx = (x1 - x0) / nx;
  const keep = ground.map((p) => +p[0].toFixed(6));
  xs = xs.filter((x, i) => i === 0 || i === xs.length - 1 || keep.includes(x) || (x - xs[i - 1] > 0.2 * dx && xs[i + 1] - x > 0.2 * dx));
  const top = xs.map((x) => yAt(ground, x));
  const node = (i, j) => i * (ny + 1) + j;
  const X = new Float64Array(xs.length * (ny + 1)), Y = new Float64Array(xs.length * (ny + 1));
  xs.forEach((x, i) => { for (let j = 0; j <= ny; j++) { X[node(i, j)] = x; Y[node(i, j)] = bottom + (top[i] - bottom) * j / ny; } });
  const tris = [];
  for (let i = 0; i < xs.length - 1; i++) for (let j = 0; j < ny; j++) {
    const a = node(i, j), b = node(i + 1, j), c = node(i + 1, j + 1), d = node(i, j + 1);
    tris.push([a, b, c], [a, c, d]);
  }
  return { xs, ny, top, bottom, X, Y, tris, node, n: X.length };
}

/**
 * Steady seepage.
 * spec: { ground, bottom, layers: [{ top, k, ratio }], gw,
 *         outside: [{ x0, x1, level }]  water standing against the ground between x0 and x1,
 *         left, right: head on the vertical ends (null: no flow) }
 */
export function seepage(spec, opt = {}) {
  const M = meshOf(spec.ground, spec.bottom, opt);
  const { X, Y, tris, n } = M;
  const w = M.ny + 2;                 // half bandwidth: neighbours are at most one column away
  const kOf = (x, y) => {
    let k = 0;
    for (let L = spec.layers.length - 1; L >= 1; L--) if (y <= yAt(spec.layers[L].top, x)) { k = L; break; }
    const Lr = spec.layers[k];
    return { k: Math.max(1e-14, Lr.k), r: Lr.ratio ?? 1 };
  };
  // element geometry
  const E = tris.map(([a, b, c]) => {
    const xa = X[a], ya = Y[a], xb = X[b], yb = Y[b], xc = X[c], yc = Y[c];
    const A2 = (xb - xa) * (yc - ya) - (xc - xa) * (yb - ya);
    const bi = [yb - yc, yc - ya, ya - yb], ci = [xc - xb, xa - xc, xb - xa];
    const xm = (xa + xb + xc) / 3, ym = (ya + yb + yc) / 3;
    return { n: [a, b, c], A: Math.abs(A2) / 2, bi, ci, xm, ym, ...kOf(xm, ym) };
  }).filter((e) => e.A > 1e-12);
  // boundary conditions
  const fixed = new Map();             // node -> head
  const groundNodes = [];
  for (let i = 0; i < M.xs.length; i++) {
    const g = M.node(i, M.ny), x = X[g], y = Y[g];
    const o = (spec.outside || []).find((s) => x >= s.x0 - 1e-9 && x <= s.x1 + 1e-9 && s.level >= y - 1e-9);
    if (o) fixed.set(g, o.level); else groundNodes.push(g);
  }
  for (const [side, i] of [[spec.left, 0], [spec.right, M.xs.length - 1]]) {
    if (side === null || side === undefined) continue;
    for (let j = 0; j <= M.ny; j++) { const k = M.node(i, j); if (Y[k] <= side + 1e-9) fixed.set(k, side); else if (j < M.ny) groundNodes.push(k); }
  }
  const seepFace = new Set();
  const h = new Float64Array(n);
  // start from the mean of the fixed heads
  let h0 = 0, cnt = 0;
  for (const v of fixed.values()) { h0 += v; cnt++; }
  h.fill(cnt ? h0 / cnt : spec.bottom);
  const resid = opt.residual ?? 1e-4;
  // width of the change from saturated to residual permeability: thin against the section
  const band = opt.band ?? Math.max(0.01, 0.005 * (Math.max(...M.top) - spec.bottom));
  const confined = !!opt.confined;
  let iters = 0, change = Infinity;
  const W = w + 1;
  const assemble = () => {
    const A = new Float64Array(n * W);
    for (const e of E) {
      const p = (h[e.n[0]] + h[e.n[1]] + h[e.n[2]]) / 3 - e.ym;     // pressure head at the centroid
      const kr = confined || p >= 0 ? 1 : resid + (1 - resid) * Math.exp(p / band);
      const kx = e.k * kr, ky = e.k * kr / e.r;
      const f = 1 / (4 * e.A);
      for (let r = 0; r < 3; r++) for (let s = 0; s <= 2; s++) {
        const I = e.n[r], J = e.n[s];
        if (J > I) continue;
        A[I * W + (I - J)] += f * (kx * e.bi[r] * e.bi[s] + ky * e.ci[r] * e.ci[s]);
      }
    }
    return A;
  };
  const solve = () => {
    const A = assemble();
    const K0 = A.slice();               // for the reactions
    const b = new Float64Array(n);
    const fix = new Map(fixed);
    for (const g of seepFace) fix.set(g, Y[g]);
    // eliminate fixed heads: move known terms to the right side
    for (let i = 0; i < n; i++) for (let j = Math.max(0, i - w); j <= i; j++) {
      const a = A[i * W + (i - j)];
      if (!a) continue;
      if (fix.has(j) && !fix.has(i)) b[i] -= a * fix.get(j);
      if (fix.has(i) && !fix.has(j) && i !== j) b[j] -= a * fix.get(i);
    }
    for (const [i, v] of fix) {
      for (let j = Math.max(0, i - w); j < i; j++) A[i * W + (i - j)] = 0;
      for (let k = i + 1; k <= Math.min(n - 1, i + w); k++) A[k * W + (k - i)] = 0;
      A[i * W] = 1; b[i] = v;
    }
    if (!bandSolve(A, b, n, w)) return null;
    // reactions (flow into the domain at fixed nodes): K h
    const Q = new Float64Array(n);
    for (let i = 0; i < n; i++) for (let j = Math.max(0, i - w); j <= i; j++) {
      const a = K0[i * W + (i - j)];
      if (!a) continue;
      Q[i] += a * b[j]; if (i !== j) Q[j] += a * b[i];
    }
    return { h: b, Q };
  };
  let Q = null;
  for (iters = 0; iters < (opt.iters ?? 80); iters++) {
    const s = solve();
    if (!s) break;
    change = 0;
    for (let i = 0; i < n; i++) { change = Math.max(change, Math.abs(s.h[i] - h[i])); h[i] = iters ? 0.5 * h[i] + 0.5 * s.h[i] : s.h[i]; }
    Q = s.Q;
    // seepage face: fix where water would come out above the ground, free where it would flow in
    let moved = false;
    if (!confined) for (const g of groundNodes) {
      if (!seepFace.has(g) && s.h[g] > Y[g] + 1e-6) { seepFace.add(g); moved = true; }
      else if (seepFace.has(g) && Q[g] > 1e-14 * (spec.layers[0].k || 1)) { seepFace.delete(g); moved = true; }
    }
    if (!moved && change < 1e-5 && iters > 2) break;
  }
  // flow through the section: the inflow at fixed nodes (Q > 0 is water entering)
  let qin = 0, qout = 0;
  if (Q) for (let i = 0; i < n; i++) if (fixed.has(i) || seepFace.has(i)) { if (Q[i] > 0) qin += Q[i]; else qout -= Q[i]; }
  return { mesh: M, h, iters, change, q: (qin + qout) / 2, qin, qout, seepFace: [...seepFace], ...fields(M, h, spec.gw ?? 9.81) };
}

/**
 * The flow net of a model (in the user's coordinates): water held at level `left`
 * against the left end and `right` against the right end (null: no flow there), and
 * standing on the ground wherever the ground near that end is lower than the water.
 * Returns plain data that survives a copy between threads: { flow, piezo, q }.
 */
export function flowNet(model, { left = null, right = null, nx, ny } = {}) {
  const g = model.ground, x0 = g[0][0], x1 = g[g.length - 1][0];
  const outside = [];
  // from an end inwards, as far as the ground stays under the water
  const reach = (level, fromLeft) => {
    const pts = fromLeft ? g : g.slice().reverse();
    if (level === null || pts[0][1] > level) return;
    let xe = pts[pts.length - 1][0];
    for (let i = 1; i < pts.length; i++) {
      if (pts[i][1] > level) { const [xa, ya] = pts[i - 1], [xb, yb] = pts[i]; xe = xa + (level - ya) / (yb - ya) * (xb - xa); break; }
    }
    outside.push(fromLeft ? { x0, x1: xe, level } : { x0: xe, x1, level });
  };
  reach(left, true); reach(right, false);
  const layers = model.layers.map((L, i) => ({ top: i === 0 ? g : L.top, k: L.mat.k ?? 1e-6, ratio: L.mat.kRatio || 1 }));
  const H = Math.max(...g.map((p) => p[1])) - model.bottom;
  const r = seepage({ ground: g, bottom: model.bottom, layers, gw: model.gw ?? 9.81, outside, left, right },
    { nx: nx ?? 70, ny: ny ?? Math.max(16, Math.min(30, Math.round(H / 0.5))) });
  const M = r.mesh;
  const flow = { xs: M.xs, ny: M.ny, X: Array.from(M.X), Y: Array.from(M.Y), h: Array.from(r.h), q: r.q, iters: r.iters, change: r.change, left, right, outside };
  return { flow, piezo: r.phreatic, q: r.q };
}

/** Head and pore pressure functions from a flow net's plain data. */
export function flowField(flow, gw = 9.81) {
  const ny = flow.ny;
  return fields({ xs: flow.xs, ny, X: flow.X, Y: flow.Y, node: (i, j) => i * (ny + 1) + j }, flow.h, gw);
}

/** Pore pressure and the phreatic line from the nodal heads. */
function fields(M, h, gw) {
  const { xs, ny, X, Y, node } = M;
  // head at (x, y): interpolate in the column mapping (bilinear in the quad)
  const head = (x, y) => {
    if (x <= xs[0]) x = xs[0];
    if (x >= xs[xs.length - 1]) x = xs[xs.length - 1];
    let i = 0, hi = xs.length - 1;
    while (hi - i > 1) { const m = (i + hi) >> 1; if (xs[m] <= x) i = m; else hi = m; }
    const t = xs[i + 1] > xs[i] ? (x - xs[i]) / (xs[i + 1] - xs[i]) : 0;
    const at = (c) => {
      const yb = Y[node(c, 0)], yt = Y[node(c, ny)];
      const s = Math.max(0, Math.min(ny, (y - yb) / ((yt - yb) || 1) * ny));
      const j = Math.min(ny - 1, Math.floor(s)), f = s - j;
      return h[node(c, j)] * (1 - f) + h[node(c, j + 1)] * f;
    };
    return at(i) * (1 - t) + at(Math.min(xs.length - 1, i + 1)) * t;
  };
  const u = (x, y) => gw * Math.max(0, head(x, y) - y);
  // phreatic line: in each column, ponded water above the ground, else the highest u = 0 crossing
  const phreatic = xs.map((x, i) => {
    const g = node(i, ny);
    if (h[g] >= Y[g] - 1e-9) return [x, Math.max(Y[g], h[g])];
    for (let j = ny; j > 0; j--) {
      const a = node(i, j - 1), b = node(i, j);
      const pa = h[a] - Y[a], pb = h[b] - Y[b];
      if (pa >= 0 && pb < 0) { const f = pa / (pa - pb); return [x, Y[a] + f * (Y[b] - Y[a])]; }
    }
    return [x, Y[node(i, 0)]];
  });
  return { head, u, phreatic };
}

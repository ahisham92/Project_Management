// Talus — finding the critical slip surface.
//
// 1. A grid of circles is laid out by entry point (crest side), exit point (toe
//    side) and the angle the arc subtends, and each is checked quickly by
//    Bishop's simplified method on a coarse set of slices.
// 2. The lowest few, each from a different part of the slope, are refined by a
//    Nelder-Mead simplex on (entry, exit, angle).
// 3. The best is cut again with every geometric break and solved exactly by all
//    methods, then polished once more with the governing method.
// Optionally the critical circle is then freed into a non-circular surface whose
// nodes move one at a time while the surface stays kinematically admissible.

import { yAt, circleThrough, arcY } from "./geometry.js";
import { buildSlices, constants, SHAPES, momentCentre, factors, valueOf, DEG, rigorous, momentF, forceF, ordinaryF, janbuF0 } from "./lem.js";

/** A circle as a slip polyline (engine frame) between its two ground crossings. */
export function circleSlip(P, circle, xa, xb, n) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const x = xa + (xb - xa) * i / n;
    pts.push([x, arcY(circle, x)]);
  }
  pts[0][1] = yAt(P.ground, xa);
  pts[n][1] = yAt(P.ground, xb);
  return pts;
}

/** Bishop's simplified F by direct iteration (fast, for the search). */
function bishopFast(K) {
  let F = 1.5;
  for (let it = 0; it < 40; it++) {
    let num = 0, den = 0;
    for (const k of K) {
      const ma = k.ca + k.sa * k.tp / F;
      if (ma < 0.05) return NaN;
      const N = (k.Wv - k.A / F * k.sa) / ma;
      num -= (k.A + N * k.tp) * k.ms;
      den += k.Mload + N * k.mn;
    }
    const Fn = num / den;
    if (!(Fn > 0) || !Number.isFinite(Fn)) return NaN;
    if (Math.abs(Fn - F) < 1e-6 * F) return Fn;
    F = Fn;
  }
  return F;
}

/** Quick F of a cut by a method (used inside searches). */
export function quickF(P, cut, circle, method) {
  const ref = momentCentre(cut, circle);
  if (method === "bishop") return bishopFast(constants(P, cut, ref, SHAPES.zero));
  if (method === "ordinary") return ordinaryF(constants(P, cut, ref, SHAPES.zero));
  if (method === "janbu") return forceF(constants(P, cut, ref, SHAPES.zero), 0);
  if (method === "janbuCorrected") return forceF(constants(P, cut, ref, SHAPES.zero), 0) * janbuF0(cut, P);
  if (method === "spencer") return rigorous(constants(P, cut, ref, SHAPES.constant)).F;
  if (method === "mp") return rigorous(constants(P, cut, ref, SHAPES.halfsine)).F;
  return momentF(constants(P, cut, ref, SHAPES.zero), 0);
}

/** Search limits in the engine frame, from the face (crest left, toe right). */
export function limits(P, opt = {}) {
  const [xc, yc] = P.face.crest, [xt, yt] = P.face.toe;
  const H = Math.max(0.5, yc - yt), w = Math.max(0.1, xt - xc);
  const pad = 0.02 * (P.xmax - P.xmin);
  const clamp = (x) => Math.min(P.xmax - pad, Math.max(P.xmin + pad, x));
  return {
    H, w,
    entry: [clamp(xc - (opt.back ?? 2.5) * H - 0.5 * w), clamp(xt - 0.15 * w)],
    exit: [clamp(xc + 0.15 * w), clamp(xt + (opt.front ?? 2) * H + 0.25 * w)],
    minDepth: opt.minDepth ?? Math.max(0.3, 0.05 * H),
  };
}

/** A circle from search parameters, checked; returns { circle, cut } or null. */
export function trialCircle(P, xe, xx, theta, lim, n, exact) {
  if (!(xx - xe > 0.2)) return null;
  if (theta <= 2 * DEG || theta >= 178 * DEG) return null;
  const e = [xe, yAt(P.ground, xe)], x = [xx, yAt(P.ground, xx)];
  const circle = circleThrough(e, x, theta);
  if (!Number.isFinite(circle.R)) return null;
  if (circle.yc < Math.max(e[1], x[1]) - 1e-9) return null;       // both ends must be on the lower arc
  if (circle.yc - circle.R < P.bottom - 1e-9) return null;        // below the hard base
  // the arc must be under the ground between the ends and outside it just beyond them
  const d = 1e-3 * (xx - xe);
  const outL = arcY(circle, xe - d), outR = arcY(circle, xx + d);
  if (Number.isFinite(outL) && outL < yAt(P.ground, xe - d) - 1e-9) return null;
  if (Number.isFinite(outR) && outR < yAt(P.ground, xx + d) - 1e-9) return null;
  const slip = circleSlip(P, circle, xe, xx, n);
  for (let i = 1; i < n; i++) if (slip[i][1] > yAt(P.ground, slip[i][0]) + 1e-9) return null;
  let depth = 0;
  for (const [sx, sy] of slip) depth = Math.max(depth, yAt(P.ground, sx) - sy);
  if (depth < lim.minDepth) return null;
  const cut = buildSlices(P, slip, { n, exact });
  if (!cut || cut.slices.length < 3) return null;
  let W = 0;
  for (const s of cut.slices) W += s.W;
  if (!(W > 1e-6)) return null;
  return { circle, cut, depth, xe, xx, theta };
}

/** Nelder-Mead minimiser (small, bounded by the objective returning Infinity). */
export function nelderMead(f, x0, steps, iters = 80, tol = 1e-5) {
  const n = x0.length;
  let pts = [x0.slice()];
  for (let i = 0; i < n; i++) { const p = x0.slice(); p[i] += steps[i]; pts.push(p); }
  let vals = pts.map(f);
  for (let it = 0; it < iters; it++) {
    const order = vals.map((v, i) => i).sort((a, b) => vals[a] - vals[b]);
    pts = order.map((i) => pts[i]); vals = order.map((i) => vals[i]);
    if (Math.abs(vals[n] - vals[0]) < tol * Math.max(1, Math.abs(vals[0])) && it > 10) break;
    const c = new Array(n).fill(0);
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) c[j] += pts[i][j] / n;
    const at = (t) => c.map((cj, j) => cj + t * (pts[n][j] - cj));
    const r = at(-1), fr = f(r);
    if (fr < vals[0]) {
      const e = at(-2), fe = f(e);
      if (fe < fr) { pts[n] = e; vals[n] = fe; } else { pts[n] = r; vals[n] = fr; }
    } else if (fr < vals[n - 1]) { pts[n] = r; vals[n] = fr; }
    else {
      const k = fr < vals[n] ? at(-0.5) : at(0.5), fk = f(k);
      if (fk < Math.min(fr, vals[n])) { pts[n] = k; vals[n] = fk; }
      else {
        for (let i = 1; i <= n; i++) { pts[i] = pts[i].map((v, j) => pts[0][j] + 0.5 * (v - pts[0][j])); vals[i] = f(pts[i]); }
      }
    }
  }
  const best = vals.indexOf(Math.min(...vals));
  return { x: pts[best], f: vals[best] };
}

/**
 * The critical circle.
 * opt: { method (governing), grid: [ne, nx, na], slices, minDepth, keepTrials, refine }
 * Returns { circle, cut, results, F, method, trials:[{circle, xe, xx, F}] } in the engine frame, or null.
 */
export function criticalCircle(P, opt = {}) {
  const method = opt.method || "mp";
  const lim = limits(P, opt);
  const [ne, nx, na] = opt.grid || [14, 14, 9];
  const nFast = 24, nExact = opt.slices || 40;
  const trials = [];
  for (let i = 0; i < ne; i++) {
    const xe = lim.entry[0] + (lim.entry[1] - lim.entry[0]) * i / (ne - 1);
    for (let j = 0; j < nx; j++) {
      const xx = lim.exit[0] + (lim.exit[1] - lim.exit[0]) * j / (nx - 1);
      for (let k = 0; k < na; k++) {
        const theta = (20 + 140 * k / (na - 1)) * DEG;
        const t = trialCircle(P, xe, xx, theta, lim, nFast, false);
        if (!t) continue;
        const F = quickF(P, t.cut, t.circle, "bishop");
        if (Number.isFinite(F) && F > 0) trials.push({ xe, xx, theta, F, circle: t.circle });
      }
    }
  }
  if (!trials.length) return null;
  trials.sort((a, b) => a.F - b.F);
  // a few starts from different parts of the slope
  const starts = [];
  const span = lim.exit[1] - lim.entry[0];
  for (const t of trials) {
    if (starts.every((s) => Math.abs(s.xe - t.xe) + Math.abs(s.xx - t.xx) > 0.12 * span)) starts.push(t);
    if (starts.length >= (opt.starts || 4)) break;
  }
  const objective = (n, m, exact) => ([xe, xx, th]) => {
    const t = trialCircle(P, xe, xx, th, lim, n, exact);
    if (!t) return Infinity;
    const F = quickF(P, t.cut, t.circle, m);
    return Number.isFinite(F) && F > 0 ? F : Infinity;
  };
  const de = (lim.entry[1] - lim.entry[0]) / ne, dx = (lim.exit[1] - lim.exit[0]) / nx;
  let best = null;
  for (const s of starts) {
    const r = nelderMead(objective(nFast, "bishop", false), [s.xe, s.xx, s.theta], [de, dx, 8 * DEG], opt.refine ?? 60);
    if (!best || r.f < best.f) best = r;
  }
  // polish with the governing method, cut exactly
  if (method !== "bishop") {
    const r = nelderMead(objective(nExact, method, true), best.x, [de / 3, dx / 3, 3 * DEG], opt.polish ?? 30);
    if (r.f <= best.f * 1.5 && Number.isFinite(r.f)) best = r;
  }
  const t = trialCircle(P, best.x[0], best.x[1], best.x[2], lim, nExact, true);
  if (!t) return null;
  const results = factors(P, t.cut, t.circle);
  return {
    kind: "circle", circle: t.circle, cut: t.cut, results, method, F: valueOf(results, method),
    xe: t.xe, xx: t.xx, depth: t.depth,
    trials: trials.slice(0, opt.keepTrials ?? 60),
  };
}

/** Frees a slip polyline into the most critical admissible non-circular surface nearby. */
export function optimiseNonCircular(P, start, opt = {}) {
  const method = opt.method || "mp";
  const nodes = opt.nodes || 9;
  const n = opt.slices || 40;
  const xa = start.cut.slip[0][0], xb = start.cut.slip[start.cut.slip.length - 1][0];
  let xs = [], ys = [];
  for (let i = 0; i <= nodes; i++) {
    const x = xa + (xb - xa) * i / nodes;
    xs.push(x); ys.push(yAt(start.cut.slip, x));
  }
  const admissible = (pxs, pys) => {
    let prev = Infinity;
    for (let i = 1; i < pxs.length; i++) {
      if (!(pxs[i] > pxs[i - 1])) return false;
      const a = Math.atan2(pys[i - 1] - pys[i], pxs[i] - pxs[i - 1]);
      if (a > prev + 1e-9) return false; // the base must flatten towards the toe
      prev = a;
    }
    for (let i = 1; i < pxs.length - 1; i++) {
      if (pys[i] > yAt(P.ground, pxs[i]) - 0.05) return false;
      if (pys[i] < P.bottom) return false;
    }
    return true;
  };
  const evalF = (pxs, pys, exact) => {
    if (!admissible(pxs, pys)) return Infinity;
    const slip = pxs.map((x, i) => [x, pys[i]]);
    slip[0][1] = yAt(P.ground, pxs[0]);
    slip[slip.length - 1][1] = yAt(P.ground, pxs[pxs.length - 1]);
    const cut = buildSlices(P, slip, { n, exact });
    if (!cut) return Infinity;
    const F = quickF(P, cut, null, method);
    return Number.isFinite(F) && F > 0 ? F : Infinity;
  };
  ys[0] = yAt(P.ground, xs[0]); ys[nodes] = yAt(P.ground, xs[nodes]);
  let F = evalF(xs, ys, false);
  if (!Number.isFinite(F)) return null;
  let step = 0.08 * start.depth + 0.05;
  for (let round = 0; round < (opt.rounds || 14) && step > 0.01; round++) {
    let improved = false;
    for (let i = 0; i <= nodes; i++) {
      for (const d of [-step, step]) {
        const tx = xs.slice(), ty = ys.slice();
        if (i === 0 || i === nodes) { tx[i] += d; ty[i] = yAt(P.ground, tx[i]); }
        else ty[i] += d;
        const Ft = evalF(tx, ty, false);
        if (Ft < F - 1e-6) { F = Ft; xs = tx; ys = ty; improved = true; break; }
      }
    }
    if (!improved) step /= 2;
  }
  const slip = xs.map((x, i) => [x, ys[i]]);
  const cut = buildSlices(P, slip, { n, exact: true });
  if (!cut) return null;
  const results = factors(P, cut, null);
  let depth = 0;
  for (const [sx, sy] of slip) depth = Math.max(depth, yAt(P.ground, sx) - sy);
  return { kind: "polyline", circle: null, cut, results, method, F: valueOf(results, method), depth, trials: [] };
}

/** Analyses one given surface (circle {xc,yc,R} or polyline, engine frame). */
export function givenSurface(P, surface, opt = {}) {
  const n = opt.slices || 40;
  let cut, circle = null;
  if (surface.R) {
    circle = surface;
    // ground crossings of the circle
    const xs = [];
    const N = 2000, a = Math.max(P.xmin, circle.xc - circle.R), b = Math.min(P.xmax, circle.xc + circle.R);
    let prev = null;
    for (let i = 0; i <= N; i++) {
      const x = a + (b - a) * i / N;
      const d = yAt(P.ground, x) - arcY(circle, x);
      if (prev !== null && (prev.d <= 0) !== (d <= 0)) {
        let lo = prev.x, hi = x;
        for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2; const dm = yAt(P.ground, m) - arcY(circle, m); if ((dm <= 0) === (prev.d <= 0)) lo = m; else hi = m; }
        xs.push((lo + hi) / 2);
      }
      prev = { x, d };
    }
    if (xs.length < 2) return null;
    cut = buildSlices(P, circleSlip(P, circle, xs[0], xs[xs.length - 1], n), { n, exact: true });
  } else {
    cut = buildSlices(P, surface, { n, exact: true });
  }
  if (!cut) return null;
  const results = factors(P, cut, circle);
  return { kind: circle ? "circle" : "polyline", circle, cut, results, method: opt.method || "mp", F: valueOf(results, opt.method || "mp"), trials: [] };
}

/**
 * Block (wedge) search: surfaces that go down from the crest side at an active
 * angle, run along just inside a weaker layer (or just above the hard base), and
 * come up to the toe side at a passive angle. Each layer below the top one is
 * tried, with entry, exit, depth inside the layer and both angles refined by a
 * simplex. Returns the most critical block, solved exactly by every method.
 */
export function blockSearch(P, opt = {}) {
  const method = opt.method || "mp";
  const lim = limits(P, opt);
  const n = opt.slices || 40;
  const lines = [];
  P.layers.forEach((L, k) => { if (k > 0 && L.top) lines.push({ line: L.top, d0: 0.15, flat: false, k }); });
  lines.push({ line: [[P.xmin, P.bottom], [P.xmax, P.bottom]], d0: -0.05, flat: true });
  const make = (line, [xe, xx, d, aa, ap]) => {
    if (!(xx - xe > 0.5) || !(aa > 30 * DEG && aa < 85 * DEG && ap > 8 * DEG && ap < 50 * DEG)) return null;
    const ye = yAt(P.ground, xe), yx = yAt(P.ground, xx);
    const yb = (x) => Math.max(P.bottom, yAt(line, x) - d);
    const root = (f, a, b) => {
      let fa = f(a), fb = f(b);
      if (!(fa > 0) || !(fb < 0)) return NaN;
      for (let i = 0; i < 50; i++) { const m = (a + b) / 2, fm = f(m); if (fm > 0) { a = m; fa = fm; } else { b = m; fb = fm; } }
      return (a + b) / 2;
    };
    const xa = root((x) => ye - (x - xe) * Math.tan(aa) - yb(x), xe, xx);
    if (!Number.isFinite(xa)) return null;
    const xb = -root((nx) => yx - (xx + nx) * Math.tan(ap) - yb(-nx), -xx, -xa);
    if (!Number.isFinite(xb) || !(xb > xa + Math.max(0.5, 0.1 * (xx - xe)))) return null;
    const slip = [[xe, ye], [xa, yb(xa)]];
    for (const [x] of line) if (x > xa + 1e-6 && x < xb - 1e-6) slip.push([x, yb(x)]);
    slip.push([xb, yb(xb)], [xx, yx]);
    for (let i = 1; i < slip.length - 1; i++) if (slip[i][1] > yAt(P.ground, slip[i][0]) - 0.05) return null;
    let depth = 0;
    for (const [sx, sy] of slip) depth = Math.max(depth, yAt(P.ground, sx) - sy);
    if (depth < lim.minDepth) return null;
    return { slip, depth };
  };
  const fOf = (L, x, exact, m) => {
    const b = make(L.line, x);
    if (!b) return Infinity;
    const cut = buildSlices(P, b.slip, { n: exact ? n : 20, exact: true });
    if (!cut || cut.slices.length < 3) return Infinity;
    const F = quickF(P, cut, null, m);
    if (!(Number.isFinite(F) && F > 0)) return Infinity;
    // a rigorous F far below the simple force-equilibrium one is a spurious root
    // (m_alpha near zero on a steep exit), not a mechanism
    const Fj = quickF(P, cut, null, "janbuCorrected");
    if (Number.isFinite(Fj) && (F < 0.7 * Fj || F > 1.5 * Fj)) return Infinity;
    return F;
  };
  const thick = (k) => {
    // thickness of the weak layer under line k: distance to the next layer top (or the base)
    const next = P.layers[k + 1]?.top;
    let t = Infinity;
    for (let i = 0; i <= 10; i++) {
      const x = P.xmin + (P.xmax - P.xmin) * i / 10;
      t = Math.min(t, yAt(P.layers[k].top, x) - (next ? yAt(next, x) : P.bottom));
    }
    return t;
  };
  lines.forEach((L) => { L.dmax = L.flat ? L.d0 : Math.max(0.05, (L.k != null ? thick(L.k) : 1) - 0.05); });
  const SM = "spencer";
  let best = null;
  const [ne, nx] = opt.grid || [7, 7];
  const AA = [45, 58, 72].map((a) => a * DEG), AP = [15, 27, 40].map((a) => a * DEG);
  for (const L of lines) {
    const ds = L.flat ? [L.d0] : [Math.min(0.15, L.dmax), L.dmax].filter((v, i, a) => a.indexOf(v) === i);
    const seeds = [];
    for (let i = 0; i < ne; i++) {
      const xe = lim.entry[0] + (lim.entry[1] - lim.entry[0]) * i / (ne - 1);
      for (let j = 0; j < nx; j++) {
        const xx = lim.exit[0] + (lim.exit[1] - lim.exit[0]) * j / (nx - 1);
        for (const d of ds) for (const aa of AA) for (const ap of AP) {
          const x = [xe, xx, d, aa, ap];
          const F = fOf(L, x, false, SM);
          if (Number.isFinite(F)) seeds.push({ x, F });
        }
      }
    }
    if (!seeds.length) continue;
    seeds.sort((a, b) => a.F - b.F);
    const de = (lim.entry[1] - lim.entry[0]) / ne, dx = (lim.exit[1] - lim.exit[0]) / nx;
    const fix = (x) => (L.flat ? [x[0], x[1], L.d0, x[3], x[4]] : x);
    const obj = (x) => (!L.flat && (x[2] < 0 || x[2] > L.dmax) ? Infinity : fOf(L, fix(x), false, SM));
    const picked = [];
    for (const s of seeds) {
      if (picked.length >= 2) break;
      if (picked.some((p) => Math.abs(p.x[0] - s.x[0]) < de * 1.5 && Math.abs(p.x[1] - s.x[1]) < dx * 1.5)) continue;
      picked.push(s);
    }
    for (const s of picked) {
      const r = nelderMead(obj, s.x, [de, dx, Math.max(0.05, L.dmax / 4), 6 * DEG, 6 * DEG], opt.refine ?? 90);
      // rank the polished blocks by the governing method, cut exactly
      const F = Number.isFinite(r.f) ? fOf(L, fix(r.x), true, method) : Infinity;
      if (Number.isFinite(F) && (!best || F < best.f)) best = { f: F, line: L, x: fix(r.x) };
    }
  }
  if (!best || !Number.isFinite(best.f)) return null;
  const b = make(best.line.line, best.x);
  const cut = buildSlices(P, b.slip, { n, exact: true });
  if (!cut) return null;
  const results = factors(P, cut, null);
  return { kind: "block", circle: null, cut, results, method, F: valueOf(results, method), depth: b.depth, xe: best.x[0], xx: best.x[1], trials: [] };
}

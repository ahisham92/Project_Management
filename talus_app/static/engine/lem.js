// Talus — limit equilibrium engine (2D, plane strain, per metre run).
//
// Conventions inside the engine: the slope is turned (mirrored if needed) so that
// its crest is on the LEFT and the sliding mass moves to +x (right and down).
// Units: kN, m, kPa, kN/m3, degrees at the edges / radians inside.
//
// Slices are vertical. Each slice carries: weight W at its centroid, external
// forces (surcharge strips, line loads, water pressure on the ground surface,
// reinforcement, water in a tension crack) at their own points, a base normal N
// and a base shear S = (c l + (N - u l) tan(phi)) / F, and interslice forces
// E (horizontal) and X = lambda f(x) E (vertical).
//
// Per slice (alpha = base angle, positive where the base dips in the direction
// of movement; Wv = total downward load; Hx = total horizontal load towards +x):
//   vertical:   N cos(a) + S sin(a) = Wv + X_i - X_{i-1}
//   horizontal: E_i = E_{i-1} + N sin(a) - S cos(a) + Hx
// With X = lambda f E both are linear in (N_i, E_i), so the slices are solved
// exactly one after another (no interslice iteration). Overall force
// equilibrium is E_n = 0; overall moment equilibrium is sum of moments = 0.
// The General Limit Equilibrium family follows (Fredlund & Krahn 1977):
//   Bishop simplified  = moment equilibrium, X = 0
//   Janbu simplified   = force equilibrium,  X = 0   (corrected by f0)
//   Spencer            = both, f(x) = 1
//   Morgenstern-Price  = both, f(x) = half-sine
//   Ordinary (Fellenius) = moment equilibrium, N from resolving normal to the base.

import {
  yAt, vertices, uniqueSorted, crossings, lower, upper, flat, mirror, TINY, circleFrom3,
} from "./geometry.js";

export const DEG = Math.PI / 180;

// ---------------------------------------------------------------- the model

/**
 * Turns a model into the engine's frame (crest on the left).
 * model = {
 *   ground: polyline, bottom: y of the hard base,
 *   layers: [{ top: polyline|null, mat }], first layer's top is the ground,
 *   mat = { name, gamma, gsat, c, phi, kind: "drained"|"undrained", su, suGrad }
 *   piezo: polyline|null (pore water head; above the ground it is ponded water),
 *   ru: number (pore pressure ratio, used instead of piezo when > 0),
 *   gw: unit weight of water,
 *   face: { toe:[x,y], crest:[x,y] },
 *   strips: [{ x1, x2, q, variable }], lines: [{ x, fx, fy, variable }],
 *   reinforcement: [{ x, y, angle, length, bond, T, kind:"anchor"|"nail", qb }],
 *   seismic: { kh, kv }, crack: { depth, water }, factors: { tanphi, c, su, variable }
 * }
 */
export function prepare(model) {
  const flip = model.face.crest[0] > model.face.toe[0];
  const fx = (x) => (flip ? -x : x);
  const fp = (p) => (p ? (flip ? mirror(p) : p.map((q) => [...q])) : null);
  const ground = fp(model.ground);
  const xmin = ground[0][0], xmax = ground[ground.length - 1][0];
  const f = { tanphi: 1, c: 1, su: 1, variable: 1, ...(model.factors || {}) };
  const P = {
    flip,
    ground,
    xmin, xmax,
    bottom: model.bottom,
    layers: model.layers.map((L, i) => ({ top: i === 0 ? ground : fp(L.top), mat: L.mat })),
    piezo: fp(model.piezo),
    ru: model.ru || 0,
    gw: model.gw ?? 9.81,
    face: { toe: [fx(model.face.toe[0]), model.face.toe[1]], crest: [fx(model.face.crest[0]), model.face.crest[1]] },
    strips: (model.strips || []).map((s) => {
      const a = fx(s.x1), b = fx(s.x2);
      return { x1: Math.min(a, b), x2: Math.max(a, b), q: s.q * (s.variable ? f.variable : 1) };
    }).filter((s) => s.q !== 0 && s.x2 > s.x1),
    lines: (model.lines || []).map((l) => ({
      x: fx(l.x), fx: (flip ? -l.fx : l.fx) * (l.variable ? f.variable : 1), fy: l.fy * (l.variable ? f.variable : 1),
    })),
    reinforcement: (model.reinforcement || []).map((r) => ({ ...r, x: fx(r.x) })),
    kh: model.seismic?.kh || 0,
    kv: model.seismic?.kv || 0,
    crack: model.crack || { depth: 0, water: 0 },
    f,
  };
  // the lines a slice must break at
  P.lines_ = [P.ground, ...P.layers.slice(1).map((L) => L.top), ...(P.piezo ? [P.piezo] : [])];
  return P;
}

/** Strength of a material at a point, with partial factors applied. */
function strength(P, mat, depthInLayer) {
  if (mat.kind === "undrained") {
    const su = (mat.su + (mat.suGrad || 0) * Math.max(0, depthInLayer)) / P.f.su;
    return { c: su, tanphi: 0 };
  }
  return { c: (mat.c || 0) / P.f.c, tanphi: Math.tan((mat.phi || 0) * DEG) / P.f.tanphi };
}

/**
 * The soil column at x from yb up to the ground: weight per unit width w (kN/m2),
 * its first moment m = sum(gamma * (top^2 - bottom^2) / 2), the layer at yb and
 * the depth of yb below that layer's top.
 */
export function column(P, x, yb) {
  const g = yAt(P.ground, x);
  const p = P.piezo && P.ru <= 0 ? yAt(P.piezo, x) : -Infinity;
  let top = g, w = 0, m = 0, layer = -1, depth = 0;
  const L = P.layers.length;
  for (let k = 0; k < L; k++) {
    const next = k + 1 < L ? Math.min(top, yAt(P.layers[k + 1].top, x)) : -Infinity;
    if (yb > next - 1e-12 && layer < 0) { layer = k; depth = top - yb; }
    const lo = Math.max(next, yb), hi = top;
    if (hi > lo) {
      const mat = P.layers[k].mat;
      const split = Math.min(Math.max(p, lo), hi);
      const gs = mat.gsat ?? mat.gamma;
      w += mat.gamma * (hi - split) + gs * (split - lo);
      m += mat.gamma * (hi * hi - split * split) / 2 + gs * (split * split - lo * lo) / 2;
    }
    top = next;
    if (top <= yb) break;
  }
  if (layer < 0) { layer = L - 1; depth = top - yb; }
  return { w, m, layer, depth };
}

/** The layer a point sits in, and how deep it is below that layer's top. */
export function layerAt(P, x, y) {
  let top = yAt(P.ground, x);
  const L = P.layers.length;
  for (let k = 0; k < L; k++) {
    const next = k + 1 < L ? Math.min(top, yAt(P.layers[k + 1].top, x)) : -Infinity;
    if (y > next) return { layer: k, depth: top - y };
    top = next;
  }
  return { layer: L - 1, depth: top - y };
}

// ---------------------------------------------------------------- slices

/** Moment of force (Fx, Fy) at (x, y) about (x0, y0), counter-clockwise positive. */
const mom = (Fx, Fy, x, y, x0, y0) => (x - x0) * Fy - (y - y0) * Fx;

/**
 * Cuts the sliding mass above a slip polyline into slices.
 * slip: polyline (engine frame) from its crest-side end to its toe-side end, both on the ground.
 * opts: { n: number of slices before breaks are added, exact: break at every crossing too }
 * Returns null when the surface is not admissible.
 */
export function buildSlices(P, slip, opts = {}) {
  const n = opts.n || 40;
  const exact = opts.exact !== false;
  let xL = slip[0][0];
  const xR = slip[slip.length - 1][0];
  if (!(xR - xL > 1e-6)) return null;
  // Tension crack: the mass starts where the surface is `depth` below the ground.
  let crack = null;
  const zc = P.crack?.depth || 0;
  if (zc > 0) {
    const xs = uniqueSorted(vertices([slip, P.ground], xL, xR), xL, xR);
    let found = null;
    for (let i = 1; i < xs.length && found === null; i++) {
      const a = xs[i - 1], b = xs[i];
      const da = yAt(P.ground, a) - yAt(slip, a), db = yAt(P.ground, b - 1e-12) - yAt(slip, b - 1e-12);
      if (db >= zc) found = da >= zc ? a : a + (b - a) * (zc - da) / (db - da);
    }
    if (found === null) return null; // never that deep: the crack takes the whole mass
    if (found > xL) {
      xL = found;
      const hw = Math.min(1, Math.max(0, P.crack.water || 0)) * zc;
      crack = { x: xL, y: yAt(slip, xL), depth: zc, hw };
    }
  }
  const lines = P.lines_;
  let xs = [];
  for (let i = 1; i < n; i++) xs.push(xL + (xR - xL) * i / n);
  xs.push(...vertices([slip, ...lines], xL, xR));
  for (const s of P.strips) xs.push(s.x1, s.x2);
  for (const l of P.lines) xs.push(l.x);
  if (exact) {
    const all = [slip, ...lines];
    for (let i = 0; i < all.length; i++)
      for (let j = i + 1; j < all.length; j++) xs.push(...crossings(all[i], all[j], xL, xR));
  }
  xs = uniqueSorted(xs, xL, xR, 1e-6);

  // reinforcement crossing points
  const reinf = [];
  for (const r of P.reinforcement) {
    const hit = elementHit(r, slip);
    if (!hit) continue;
    const beyond = r.length - hit.t;
    let T;
    if (r.kind === "anchor") T = r.T * Math.min(1, Math.max(0, Math.min(r.bond || r.length, beyond) / (r.bond || r.length)));
    else T = Math.min(r.T, (r.qb ?? Infinity) * beyond);
    if (T > 0) reinf.push({ x: hit.x, y: hit.y, Fx: T * hit.dx, Fy: T * hit.dy, T });
  }

  const slices = [];
  const gw = P.gw;
  for (let i = 1; i < xs.length; i++) {
    const x0 = xs[i - 1], x1 = xs[i], b = x1 - x0, xm = (x0 + x1) / 2;
    const yb0 = yAt(slip, x0 + (i === 1 ? 0 : 0)), yb1 = yAt(slip, x1);
    const ybm = (yb0 + yb1) / 2;
    const c0 = column(P, x0, yb0), cm = column(P, xm, ybm), c1 = column(P, x1, yb1);
    const W = b / 6 * (c0.w + 4 * cm.w + c1.w);
    const g0 = yAt(P.ground, x0), g1 = yAt(P.ground, x1), gm = yAt(P.ground, xm);
    if (ybm > gm + 1e-6) return null; // the surface comes out of the ground
    const xg = W > 0 ? b / 6 * (x0 * c0.w + 4 * xm * cm.w + x1 * c1.w) / W : xm;
    const yg = W > 0 ? b / 6 * (c0.m + 4 * cm.m + c1.m) / W : (gm + ybm) / 2;
    const alpha = Math.atan2(yb0 - yb1, b);
    const l = Math.hypot(b, yb1 - yb0);
    const at = layerAt(P, xm, ybm + 1e-7);
    const mat = P.layers[at.layer].mat;
    const st = strength(P, mat, at.depth);
    let u = 0;
    if (P.ru > 0) u = P.ru * cm.w;
    else if (P.piezo) u = gw * Math.max(0, yAt(P.piezo, xm) - ybm);
    const ext = [];
    // water standing on the ground surface (exact for a linear pressure)
    if (P.piezo && P.ru <= 0) {
      const p0 = gw * Math.max(0, yAt(P.piezo, x0) - g0), p1 = gw * Math.max(0, yAt(P.piezo, x1) - g1);
      if (p0 + p1 > 0) {
        const pav = (p0 + p1) / 2, dy = g1 - g0, s = (p0 + 2 * p1) / (3 * (p0 + p1));
        ext.push({ Fx: pav * dy, Fy: -pav * b, x: x0 + s * b, y: g0 + s * dy, kind: "water" });
      }
    }
    for (const s of P.strips) {
      const a = Math.max(x0, s.x1), c = Math.min(x1, s.x2);
      if (c > a) ext.push({ Fx: 0, Fy: -s.q * (c - a), x: (a + c) / 2, y: yAt(P.ground, (a + c) / 2), kind: "surcharge" });
    }
    for (const L of P.lines) {
      if ((L.x >= x0 && L.x < x1) || (i === xs.length - 1 && L.x === x1)) {
        ext.push({ Fx: L.fx, Fy: L.fy, x: L.x, y: yAt(P.ground, L.x), kind: "line" });
      }
    }
    for (const r of reinf) {
      if ((r.x >= x0 && r.x < x1) || (i === xs.length - 1 && Math.abs(r.x - x1) < 1e-9)) {
        ext.push({ Fx: r.Fx, Fy: r.Fy, x: r.x, y: r.y, kind: "reinforcement", T: r.T });
      }
    }
    if (crack && i === 1 && crack.hw > 0) {
      const Pw = 0.5 * gw * crack.hw * crack.hw;
      ext.push({ Fx: Pw, Fy: 0, x: x0, y: crack.y + crack.hw / 3, kind: "crack water" });
    }
    slices.push({
      x0, x1, b, xm, yb0, yb1, ybm, g0, g1, alpha, l, W, xg, yg,
      layer: at.layer, mat: mat.name, c: st.c, tanphi: st.tanphi, u, U: u * l, ext,
    });
  }
  return { slices, xL, xR, crack, slip };
}

/** Where a reinforcement element (head, angle below horizontal, length) crosses the slip polyline. */
function elementHit(r, slip) {
  const a = (r.angle || 0) * DEG;
  // into the slope: the crest is on the left in the engine frame
  const dx = -Math.cos(a), dy = -Math.sin(a);
  for (let i = 1; i < slip.length; i++) {
    const [x1, y1] = slip[i - 1], [x2, y2] = slip[i];
    const ex = x2 - x1, ey = y2 - y1;
    const den = dx * ey - dy * ex;
    if (Math.abs(den) < 1e-12) continue;
    const t = ((x1 - r.x) * ey - (y1 - r.y) * ex) / den;
    const s = ((x1 - r.x) * dy - (y1 - r.y) * dx) / den;
    if (t > 0 && t < r.length && s >= 0 && s <= 1) return { t, x: r.x + t * dx, y: r.y + t * dy, dx, dy };
  }
  return null;
}

// ---------------------------------------------------------------- solving

/** Brent's method on [a, b] with f(a), f(b) of opposite sign. */
export function brent(f, a, b, fa, fb, tol = 1e-10, iters = 100) {
  if (fa === undefined) fa = f(a);
  if (fb === undefined) fb = f(b);
  if (fa * fb > 0) return NaN;
  let c = a, fc = fa, d = b - a, e = d;
  for (let k = 0; k < iters; k++) {
    if (fb * fc > 0) { c = a; fc = fa; d = b - a; e = d; }
    if (Math.abs(fc) < Math.abs(fb)) { a = b; b = c; c = a; fa = fb; fb = fc; fc = fa; }
    const tol1 = 2 * Number.EPSILON * Math.abs(b) + tol / 2, xm = (c - b) / 2;
    if (Math.abs(xm) <= tol1 || fb === 0) return b;
    if (Math.abs(e) >= tol1 && Math.abs(fa) > Math.abs(fb)) {
      const s = fb / fa;
      let p, q;
      if (a === c) { p = 2 * xm * s; q = 1 - s; }
      else {
        const qq = fa / fc, r = fb / fc;
        p = s * (2 * xm * qq * (qq - r) - (b - a) * (r - 1));
        q = (qq - 1) * (r - 1) * (s - 1);
      }
      if (p > 0) q = -q; else p = -p;
      if (2 * p < Math.min(3 * xm * q - Math.abs(tol1 * q), Math.abs(e * q))) { e = d; d = p / q; }
      else { d = xm; e = d; }
    } else { d = xm; e = d; }
    a = b; fa = fb;
    b += Math.abs(d) > tol1 ? d : (xm > 0 ? tol1 : -tol1);
    fb = f(b);
  }
  return b;
}

const F_GRID = [0.02, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1, 1.25, 1.6, 2, 2.5, 3.2, 4, 5, 6.5, 8, 10, 14, 20, 30, 50, 100];

/**
 * Root of fn over the F grid (fn is NaN where a base normal is not defined).
 * Spurious roots sit at small F, where m_alpha tends to zero, so the largest root is taken.
 */
function rootF(fn) {
  const v = F_GRID.map(fn);
  for (let i = F_GRID.length - 1; i > 0; i--) {
    const a = F_GRID[i - 1], b = F_GRID[i], fa = v[i - 1], fb = v[i];
    if (Number.isFinite(fa) && Number.isFinite(fb) && fa * fb <= 0) {
      if (fb === 0) return b;
      return brent(fn, a, b, fa, fb, 1e-11);
    }
  }
  return NaN;
}

/** Per-slice constants that do not depend on F or lambda. */
export function constants(P, cut, ref, fShape) {
  const { slices, xL, xR } = cut;
  const kh = P.kh, kv = P.kv;
  const n = slices.length;
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const s = slices[i];
    const Wd = s.W * (1 - kv);
    let Fx = 0, Fy = 0, M = mom(kh * s.W, -Wd, s.xg, s.yg, ref.x, ref.y);
    for (const e of s.ext) { Fx += e.Fx; Fy += e.Fy; M += mom(e.Fx, e.Fy, e.x, e.y, ref.x, ref.y); }
    const sa = Math.sin(s.alpha), ca = Math.cos(s.alpha);
    out[i] = {
      sa, ca,
      Wv: Wd - Fy,
      Hx: kh * s.W + Fx,
      Mload: M,
      A: s.c * s.l - s.U * s.tanphi,
      tp: s.tanphi,
      mn: (s.xm - ref.x) * ca - (s.ybm - ref.y) * sa,
      ms: (s.xm - ref.x) * sa + (s.ybm - ref.y) * ca,
      fl: fShape(s.x0, xL, xR),
      fr: fShape(s.x1, xL, xR),
    };
  }
  return out;
}

/**
 * Marches through the slices for given F and lambda.
 * Returns { En, N[], E[], ok } — ok false when a base normal denominator is not positive.
 */
export function march(K, F, lam, keep = false) {
  let E = 0, ok = true;
  const n = K.length;
  const N = keep ? new Float64Array(n) : null, Es = keep ? new Float64Array(n) : null;
  for (let i = 0; i < n; i++) {
    const k = K[i];
    const a = k.A / F, t = k.tp / F;
    const Pp = k.ca + t * k.sa, Q = k.sa - t * k.ca;
    const lr = lam * k.fr, ll = lam * k.fl;
    const den = Pp - lr * Q;
    if (!(den > 1e-6)) ok = false;
    const Ni = (k.Wv - a * k.sa + lr * (E - a * k.ca + k.Hx) - ll * E) / den;
    E = E + Ni * Q - a * k.ca + k.Hx;
    if (keep) { N[i] = Ni; Es[i] = E; }
  }
  return { En: E, N, E: Es, ok };
}

/** Overall moment residual for given F and lambda. */
function momentResidual(K, F, lam) {
  const r = march(K, F, lam, true);
  let M = 0;
  for (let i = 0; i < K.length; i++) {
    const k = K[i], Ni = r.N[i];
    const S = (k.A + Ni * k.tp) / F;
    M += k.Mload + Ni * k.mn + S * k.ms;
  }
  return { M, ok: r.ok };
}

function scaleOf(K) {
  let s = 0;
  for (const k of K) s += Math.abs(k.Mload);
  return s || 1;
}

/** F from force equilibrium alone (Janbu's simplified when lambda = 0). */
export function forceF(K, lam) {
  return rootF((F) => {
    const r = march(K, F, lam);
    return r.ok ? r.En : NaN;
  });
}

/** F from moment equilibrium alone (Bishop's simplified when lambda = 0). */
export function momentF(K, lam) {
  const sc = scaleOf(K);
  return rootF((F) => {
    const r = momentResidual(K, F, lam);
    return r.ok ? r.M / sc : NaN;
  });
}

/** Ordinary method of slices (Fellenius): N resolved normal to the base, no interslice forces. */
export function ordinaryF(K) {
  let res = 0, drive = 0;
  for (const k of K) {
    const N = k.Wv * k.ca - k.Hx * k.sa;
    res += (k.A + N * k.tp) * k.ms;
    drive += k.Mload + N * k.mn;
  }
  const F = -res / drive;
  return F > 0 ? F : NaN;
}

/** Rigorous solution: the lambda at which force and moment equilibrium give the same F. */
export function rigorous(K) {
  const sc = scaleOf(K);
  const En = (lam) => (F) => {
    const r = march(K, F, lam);
    return r.ok ? r.En : NaN;
  };
  // Continuation: at each lambda the force-equilibrium F is the root nearest the
  // previous one, starting from Janbu's (lambda = 0). This keeps to the physical
  // branch and away from the spurious roots near m_alpha = 0.
  const g = (lam, Fprev) => {
    const F = rootNear(En(lam), Fprev);
    if (!Number.isFinite(F)) return { v: NaN, F };
    const r = momentResidual(K, F, lam);
    return { v: r.ok ? r.M / sc : NaN, F };
  };
  const F0 = forceF(K, 0);
  if (!Number.isFinite(F0)) return { F: NaN, lambda: NaN };
  const zero = { lam: 0, ...g(0, F0) };
  if (!Number.isFinite(zero.v)) return { F: NaN, lambda: NaN };
  if (Math.abs(zero.v) < 1e-9) return { F: zero.F, lambda: 0 };
  const steps = [];
  for (let L = 0.05; L <= 2 + 1e-9; L += 0.05) steps.push(L);
  for (let L = 2.25; L <= 8 + 1e-9; L += 0.25) steps.push(L);
  let left = zero, right = zero;
  for (const mag of steps) {
    for (const side of [1, -1]) {
      const last = side > 0 ? right : left;
      if (!Number.isFinite(last.v)) continue;
      const cur = { lam: side * mag, ...g(side * mag, last.F) };
      if (Number.isFinite(cur.v) && cur.v * last.v <= 0) {
        const h = (L) => {
          const r = g(L, last.F);
          return Number.isFinite(r.v) ? r.v : NaN;
        };
        let a = last.lam, b = cur.lam, fa = last.v, fb = cur.v;
        // bisection first (robust to the odd undefined point), then Brent
        for (let k = 0; k < 6; k++) {
          const m = (a + b) / 2, fm = h(m);
          if (!Number.isFinite(fm)) break;
          if (fa * fm <= 0) { b = m; fb = fm; } else { a = m; fa = fm; }
        }
        const lamStar = brent((L) => { const v = h(L); return Number.isFinite(v) ? v : fa; }, a, b, fa, fb, 1e-10);
        const F = rootNear(En(lamStar), last.F);
        return { F, lambda: lamStar };
      }
      if (side > 0) right = cur; else left = cur;
    }
  }
  return { F: NaN, lambda: NaN };
}

/** The root of fn nearest F0, searching outwards geometrically. */
export function rootNear(fn, F0, ratio = 1.03, maxSteps = 160) {
  let up = F0, fu = fn(up), dn = F0, fd = fu;
  if (fu === 0) return F0;
  for (let k = 0; k < maxSteps; k++) {
    const u2 = up * ratio, fu2 = fn(u2);
    if (Number.isFinite(fu) && Number.isFinite(fu2) && fu * fu2 <= 0) return brent(fn, up, u2, fu, fu2, 1e-11);
    const d2 = dn / ratio, fd2 = fn(d2);
    if (Number.isFinite(fd) && Number.isFinite(fd2) && fd * fd2 <= 0) return brent(fn, d2, dn, fd2, fd, 1e-11);
    up = u2; fu = fu2; dn = d2; fd = fd2;
  }
  return NaN;
}

export const SHAPES = {
  constant: () => 1,
  halfsine: (x, a, b) => Math.sin(Math.PI * (x - a) / (b - a)),
  zero: () => 0,
};

/** Janbu's correction factor f0 (Janbu 1973) from the depth-to-length ratio of the mass. */
export function janbuF0(cut, P) {
  const s = cut.slip, [xa, ya] = [cut.xL, yAt(cut.slip, cut.xL)], [xb, yb] = s[s.length - 1];
  const L = Math.hypot(xb - xa, yb - ya);
  let d = 0;
  for (const sl of cut.slices) {
    // distance from the chord to the base point
    const dist = Math.abs((yb - ya) * sl.xm - (xb - xa) * sl.ybm + xb * ya - yb * xa) / L;
    d = Math.max(d, dist);
  }
  let hasC = false, hasPhi = false;
  for (const sl of cut.slices) { if (sl.c > 0) hasC = true; if (sl.tanphi > 0) hasPhi = true; }
  const b1 = hasC && hasPhi ? 0.5 : hasPhi ? 0.31 : 0.69;
  const r = d / L;
  return 1 + b1 * (r - 1.4 * r * r);
}

export const METHODS = ["ordinary", "bishop", "janbu", "janbuCorrected", "spencer", "mp"];
export const METHOD_NAMES = {
  ordinary: "Ordinary (Fellenius)",
  bishop: "Bishop simplified",
  janbu: "Janbu simplified",
  janbuCorrected: "Janbu corrected",
  spencer: "Spencer",
  mp: "Morgenstern-Price (half-sine)",
};

/** The moment centre: the circle's own centre, or a circle through the ends and middle. */
export function momentCentre(cut, circle) {
  if (circle) return { x: circle.xc, y: circle.yc };
  const s = cut.slip;
  const a = [cut.xL, yAt(s, cut.xL)], b = s[s.length - 1];
  const xm = (a[0] + b[0]) / 2;
  const c = circleFrom3(a, [xm, yAt(s, xm)], b);
  if (c && Number.isFinite(c.xc)) return { x: c.xc, y: c.yc };
  const top = Math.max(a[1], b[1]);
  return { x: xm, y: top + (b[0] - a[0]) };
}

/**
 * Factor of safety of one cut by the methods asked for.
 * Returns { ordinary, bishop, janbu, janbuCorrected, spencer:{F,lambda}, mp:{F,lambda} } (only those asked).
 */
export function factors(P, cut, circle, methods = METHODS) {
  const ref = momentCentre(cut, circle);
  const out = {};
  let K0 = null;
  const zeroK = () => (K0 ||= constants(P, cut, ref, SHAPES.zero));
  for (const m of methods) {
    if (m === "ordinary") out.ordinary = ordinaryF(zeroK());
    else if (m === "bishop") out.bishop = momentF(zeroK(), 0);
    else if (m === "janbu") out.janbu = forceF(zeroK(), 0);
    else if (m === "janbuCorrected") {
      const F = out.janbu ?? forceF(zeroK(), 0);
      out.janbuCorrected = F * janbuF0(cut, P);
    } else if (m === "spencer") out.spencer = rigorous(constants(P, cut, ref, SHAPES.constant));
    else if (m === "mp") out.mp = rigorous(constants(P, cut, ref, SHAPES.halfsine));
  }
  return out;
}

/** F of one method as a number. */
export function valueOf(r, m) {
  const v = r[m];
  return typeof v === "number" ? v : v?.F;
}

/** Slice-by-slice forces of the solution (for the table and the drawings). */
export function sliceForces(P, cut, circle, method, F, lambda = 0) {
  const ref = momentCentre(cut, circle);
  const shape = method === "mp" ? SHAPES.halfsine : method === "spencer" ? SHAPES.constant : SHAPES.zero;
  const K = constants(P, cut, ref, shape);
  let N;
  if (method === "ordinary") N = K.map((k) => k.Wv * k.ca - k.Hx * k.sa);
  else N = Array.from(march(K, F, lambda, true).N);
  const r = march(K, F, method === "ordinary" ? 0 : lambda, true);
  return cut.slices.map((s, i) => {
    const k = K[i];
    const S = (k.A + N[i] * k.tp) / F;
    const El = i === 0 ? 0 : r.E[i - 1], Er = r.E[i];
    return {
      x0: s.x0, x1: s.x1, xm: s.xm, b: s.b, ybm: s.ybm, alpha: s.alpha / DEG, l: s.l, W: s.W,
      mat: s.mat, c: s.c, phi: Math.atan(s.tanphi) / DEG, u: s.u, N: N[i], Neff: N[i] - s.U, S,
      El, Er, Xl: lambda * k.fl * El, Xr: lambda * k.fr * Er, ext: s.ext.reduce((a, e) => a + Math.hypot(e.Fx, e.Fy), 0),
    };
  });
}

export { yAt, lower, upper, flat };

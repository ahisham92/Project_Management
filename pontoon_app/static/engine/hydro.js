// Hydrostatics of a prismatic pontoon section, exact at any heel angle.
//
// The cross-section is a set of rectangles (one box for a concrete pontoon, or
// the individual float modules under a framed deck). Each rectangle is rotated
// and clipped by the water plane (Sutherland–Hodgman), so the immersed area and
// its centroid are exact for any heel and sinkage. Equilibrium (buoyancy equals
// weight, centre of buoyancy under the centre of gravity) is solved by Newton.
// For a wall-sided section this reproduces the wall-sided formula
//   GZ = sin θ (GM + ½ BM tan² θ)
// which Verification checks.
//
// Coordinates in the section: y across (0 on the centreline), z up from the
// underside of the lowest float. Per metre length unless stated.

export const G = 9.80665;

/** Polygon area and centroid (shoelace). */
export function polyProps(P) {
  let A = 0, cy = 0, cz = 0;
  for (let i = 0; i < P.length; i++) {
    const [y1, z1] = P[i], [y2, z2] = P[(i + 1) % P.length];
    const c = y1 * z2 - y2 * z1;
    A += c; cy += (y1 + y2) * c; cz += (z1 + z2) * c;
  }
  A /= 2;
  if (Math.abs(A) < 1e-15) return { A: 0, y: 0, z: 0 };
  return { A: Math.abs(A), y: cy / (6 * A), z: cz / (6 * A) };
}

/** Clip polygon (earth frame) to Z <= h. */
function clipBelow(P, h) {
  const out = [];
  for (let i = 0; i < P.length; i++) {
    const a = P[i], b = P[(i + 1) % P.length];
    const ina = a[1] <= h, inb = b[1] <= h;
    if (ina) out.push(a);
    if (ina !== inb) {
      const t = (h - a[1]) / (b[1] - a[1]);
      out.push([a[0] + t * (b[0] - a[0]), h]);
    }
  }
  return out;
}

const rot = ([y, z], c, s) => [y * c - z * s, y * s + z * c];

/** Immersed area and centroid (earth frame) for heel θ (rad) and water level h (earth Z). */
export function immersed(rects, theta, h) {
  const c = Math.cos(theta), s = -Math.sin(theta); // + θ lowers the +y side
  let A = 0, my = 0, mz = 0;
  for (const r of rects) {
    const P = [[r.y0, r.z0], [r.y1, r.z0], [r.y1, r.z1], [r.y0, r.z1]].map((p) => rot(p, c, s));
    const Q = clipBelow(P, h);
    if (Q.length < 3) continue;
    const p = polyProps(Q);
    A += p.A; my += p.A * p.y; mz += p.A * p.z;
  }
  return { A, y: A ? my / A : 0, z: A ? mz / A : 0 };
}

/** Upright draft for a weight w (kN/m) and water unit weight gw (kN/m³). */
export function uprightDraft(rects, w, gw) {
  const target = w / gw;
  let lo = Math.min(...rects.map((r) => r.z0)), hi = Math.max(...rects.map((r) => r.z1));
  if (immersed(rects, 0, hi).A < target) return { sinks: true, T: hi };
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    if (immersed(rects, 0, mid).A < target) lo = mid; else hi = mid;
  }
  return { sinks: false, T: (lo + hi) / 2 };
}

/**
 * Equilibrium heel for a section of weight w (kN/m) with centre of gravity
 * (yg, zg) in the section frame. For each trial heel θ the water level h(θ) that
 * floats the weight is found by bisection (the immersed area grows with h), and the
 * heel is the first θ from upright at which the centre of buoyancy lies under the
 * centre of gravity — the statically stable equilibrium reached as the load is applied.
 * Returns θ (rad, + lowers the +y side) and h; capsized when none exists up to 80°.
 */
export function equilibrium(rects, w, yg, zg, gw) {
  const need = w / gw;
  const level = (th) => {
    // bounds in the earth frame: any point of the section lies within ±(|y|+|z|)
    const ext = Math.max(...rects.flatMap((r) => [Math.abs(r.y0) + Math.abs(r.z0), Math.abs(r.y1) + Math.abs(r.z1)]));
    let lo = -ext - 1, hi = ext + 1;
    if (immersed(rects, th, hi).A < need) return null; // fully submerged at this heel: sinks
    for (let i = 0; i < 60; i++) { const m = (lo + hi) / 2; if (immersed(rects, th, m).A < need) lo = m; else hi = m; }
    return (lo + hi) / 2;
  };
  const resid = (th) => {
    const h = level(th);
    if (h === null) return { r: NaN, h };
    const im = immersed(rects, th, h);
    const Gy = rot([yg, zg], Math.cos(th), -Math.sin(th))[0];
    // + when buoyancy acts on the +y side of G: a righting couple against a +θ heel
    return { r: Gy - im.y, h };
  };
  const dir = yg >= 0 ? 1 : -1;
  if (Math.abs(yg) < 1e-12) { const h = level(0); return { capsized: h === null, theta: 0, h }; }
  let a = 0, ra = resid(0).r, step = (1 * Math.PI) / 180;
  for (let th = step; th <= (80 * Math.PI) / 180; th += step) {
    const t = dir * th, rb = resid(t).r;
    if (!Number.isFinite(rb)) break;
    if (Math.sign(rb) !== Math.sign(ra)) {
      let lo = a, hi = t, rlo = ra;
      for (let i = 0; i < 50; i++) {
        const m = (lo + hi) / 2, rm = resid(m).r;
        if (Math.sign(rm) === Math.sign(rlo)) { lo = m; rlo = rm; } else hi = m;
      }
      const theta = (lo + hi) / 2;
      return { capsized: false, theta, h: resid(theta).h };
    }
    a = t; ra = rb;
  }
  return { capsized: true, theta: dir * (80 * Math.PI) / 180, h: level(0) };
}

/** Height of a section point above the water for heel θ and level h. */
export function above(p, theta, h) { return rot(p, Math.cos(theta), -Math.sin(theta))[1] - h; }

/** Waterplane properties of the upright section at draft T (per metre): width b and second moment I about y = yc. */
export function waterplane(rects, T) {
  const cut = rects.filter((r) => r.z0 <= T && r.z1 >= T);
  const b = cut.reduce((a, r) => a + (r.y1 - r.y0), 0);
  const yc = b ? cut.reduce((a, r) => a + (r.y1 - r.y0) * (r.y0 + r.y1) / 2, 0) / b : 0;
  const I = cut.reduce((a, r) => { const w = r.y1 - r.y0, m = (r.y0 + r.y1) / 2 - yc; return a + w ** 3 / 12 + w * m * m; }, 0);
  return { b, I, yc };
}

/** Initial stability: KB, BM, GM for weight w per metre and KG. */
export function initial(rects, w, KG, gw) {
  const { T, sinks } = uprightDraft(rects, w, gw);
  const im = immersed(rects, 0, T);
  const wp = waterplane(rects, T);
  const V = im.A;
  const BM = V > 0 ? wp.I / V : 0;
  return { T, sinks, KB: im.z, BM, GM: im.z + BM - KG, V, wp };
}

/** Wall-sided formula righting lever (for checking). */
export const wallSidedGZ = (GM, BM, th) => Math.sin(th) * (GM + 0.5 * BM * Math.tan(th) ** 2);

/** Linear wave number from ω² = g k tanh(k h) (Newton, from deep-water start). */
export function waveNumber(T, h) {
  const w = (2 * Math.PI) / T;
  let k = Math.max(w * w / G, w / Math.sqrt(G * h));
  for (let i = 0; i < 100; i++) {
    const t = Math.tanh(k * h), F = G * k * t - w * w, dF = G * t + G * k * h * (1 - t * t);
    const dk = F / dF;
    k -= dk;
    if (Math.abs(dk) < 1e-14 * k) break;
  }
  return k;
}

/**
 * Wave transmission past a fixed rectangular floating breakwater of width B and
 * draft T in depth h (Macagno 1953; long-crested linear waves).
 *   Kt = 1 / sqrt(1 + [k B sinh(kh) / (2 cosh(k(h - T)))]²)
 */
export function macagnoKt(Tp, h, B, T) {
  const k = waveNumber(Tp, h);
  const a = (k * B * Math.sinh(k * h)) / (2 * Math.cosh(k * (h - T)));
  return { k, L: (2 * Math.PI) / k, Kt: 1 / Math.sqrt(1 + a * a) };
}

/**
 * Horizontal Froude–Krylov force amplitude per metre on a restrained box of width
 * B and draft T in depth h, wave height H (linear theory, diffraction neglected):
 *   F = ρ g H sin(kB/2) [sinh(kh) − sinh(k(h−T))] / (k cosh(kh))
 * Returns kN/m with ρg in kN/m³.
 */
export function froudeKrylovX(gw, H, Tp, h, B, T) {
  const k = waveNumber(Tp, h);
  return (gw * H * Math.abs(Math.sin((k * B) / 2)) * (Math.sinh(k * h) - Math.sinh(k * (h - Math.min(T, h))))) / (k * Math.cosh(k * h));
}

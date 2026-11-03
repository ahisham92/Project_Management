// Talus — 2D geometry helpers. Every line in a model is a polyline that is a
// function of x: [[x0,y0],[x1,y1],...] with x non-decreasing. Outside its range a
// line is extended flat. Everything here is exact for straight segments.

export const TINY = 1e-9;

/** y of a polyline at x (flat outside its range; at a vertical step, the right-hand value). */
export function yAt(poly, x) {
  const n = poly.length;
  if (n === 0) return NaN;
  if (x <= poly[0][0]) return poly[0][1];
  if (x >= poly[n - 1][0]) return poly[n - 1][1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (poly[m][0] <= x) lo = m; else hi = m;
  }
  const [x0, y0] = poly[lo], [x1, y1] = poly[hi];
  if (x1 - x0 < TINY) return y1;
  return y0 + (y1 - y0) * (x - x0) / (x1 - x0);
}

/** The x of every vertex of the polylines that lies inside [a, b]. */
export function vertices(polys, a, b) {
  const xs = [];
  for (const p of polys) {
    if (!p) continue;
    for (const [x] of p) if (x > a && x < b) xs.push(x);
  }
  return xs;
}

/** Sorted, de-duplicated (to tol) copy of xs, always containing a and b. */
export function uniqueSorted(xs, a, b, tol = 1e-7) {
  const all = [a, b, ...xs.filter((x) => x > a && x < b)].sort((p, q) => p - q);
  const out = [all[0]];
  for (let i = 1; i < all.length; i++) if (all[i] - out[out.length - 1] > tol) out.push(all[i]);
  if (b - out[out.length - 1] <= tol) out[out.length - 1] = b; else out.push(b);
  return out;
}

/** Every x in (a, b) where two polylines cross. */
export function crossings(p, q, a, b) {
  const xs = uniqueSorted(vertices([p, q], a, b), a, b);
  const out = [];
  let x0 = xs[0], d0 = yAt(p, x0) - yAt(q, x0);
  for (let i = 1; i < xs.length; i++) {
    const x1 = xs[i];
    // evaluate just inside the interval so vertical steps do not confuse the sign
    const d0i = yAt(p, x0 + 1e-12) - yAt(q, x0 + 1e-12);
    const d1 = yAt(p, x1) - yAt(q, x1);
    if ((d0i < 0 && d1 > 0) || (d0i > 0 && d1 < 0)) {
      const x = x0 + (x1 - x0) * d0i / (d0i - d1);
      if (x > a + TINY && x < b - TINY) out.push(x);
    }
    x0 = x1; d0 = d1;
  }
  return out;
}

/** Pointwise combination of two polylines over [a, b], exact (breaks at vertices and crossings). */
export function combine(p, q, fn, a, b) {
  const xs = uniqueSorted([...vertices([p, q], a, b), ...crossings(p, q, a, b)], a, b);
  return xs.map((x) => [x, fn(yAt(p, x), yAt(q, x))]);
}

export const lower = (p, q, a, b) => combine(p, q, Math.min, a, b);
export const upper = (p, q, a, b) => combine(p, q, Math.max, a, b);

export const flat = (y, a, b) => [[a, y], [b, y]];

/** Mirror a polyline about x = 0 (and keep it ordered left to right). */
export const mirror = (poly) => poly.map(([x, y]) => [-x, y]).reverse();

/** Polyline shifted vertically. */
export const shift = (poly, dy) => poly.map(([x, y]) => [x, y + dy]);

/** Area enclosed between two polylines (upper - lower, only where positive) over [a, b]. */
export function areaBetween(top, bottom, a, b) {
  const xs = uniqueSorted([...vertices([top, bottom], a, b), ...crossings(top, bottom, a, b)], a, b);
  let A = 0;
  for (let i = 1; i < xs.length; i++) {
    const x0 = xs[i - 1], x1 = xs[i];
    const h0 = Math.max(0, yAt(top, x0) - yAt(bottom, x0));
    const h1 = Math.max(0, yAt(top, x1) - yAt(bottom, x1));
    A += 0.5 * (h0 + h1) * (x1 - x0);
  }
  return A;
}

/** Circle through two points subtending central angle theta (rad), centre on the upper side. */
export function circleThrough(p1, p2, theta) {
  const [x1, y1] = p1, [x2, y2] = p2;
  const dx = x2 - x1, dy = y2 - y1;
  const c = Math.hypot(dx, dy);
  const R = c / (2 * Math.sin(theta / 2));
  const d = R * Math.cos(theta / 2);
  let nx = -dy / c, ny = dx / c;
  if (ny < 0) { nx = -nx; ny = -ny; }
  return { xc: (x1 + x2) / 2 + d * nx, yc: (y1 + y2) / 2 + d * ny, R };
}

/** Lower arc of a circle at x (NaN outside). */
export function arcY(circle, x) {
  const { xc, yc, R } = circle;
  const s = R * R - (x - xc) * (x - xc);
  return s < 0 ? NaN : yc - Math.sqrt(s);
}

/** Circle through three points (for a moment centre of a non-circular surface). */
export function circleFrom3(a, b, c) {
  const [ax, ay] = a, [bx, by] = b, [cx, cy] = c;
  const d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
  if (Math.abs(d) < 1e-12) return null;
  const a2 = ax * ax + ay * ay, b2 = bx * bx + by * by, c2 = cx * cx + cy * cy;
  const xc = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d;
  const yc = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d;
  return { xc, yc, R: Math.hypot(ax - xc, ay - yc) };
}

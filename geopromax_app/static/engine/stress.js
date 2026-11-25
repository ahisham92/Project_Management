// Vertical stress increase under flexible surface loads on an elastic half-space.
//
// Every load is turned into axis-aligned rectangles that each carry a uniform
// pressure. A rectangle is solved exactly by the corner method (superposing four
// signed rectangles that share a corner above the field point), so a point
// outside a load is as exact as one inside it. Circles and embankment side
// slopes are split into strips; the tests hold them to the closed forms.
//
// Units: m, kPa.

const EPS = 1e-9;

/** Boussinesq (1885), integrated over a rectangle B x L with the field point
 *  below one corner at depth z (Newmark 1935). Returns Δσz / q. */
export function boussinesqCorner(B, L, z) {
  if (B <= 0 || L <= 0) return 0;
  if (z < 1e-6) return 0.25;
  const m = B / z, n = L / z, m2 = m * m, n2 = n * n;
  const s = m2 + n2 + 1, r = Math.sqrt(s);
  const a = ((2 * m * n * r) / (s + m2 * n2)) * ((s + 1) / s);
  // atan2 keeps the right branch when m²n² > m² + n² + 1
  const b = Math.atan2(2 * m * n * r, s - m2 * n2);
  return (a + b) / (4 * Math.PI);
}

/** Westergaard (1938): a half-space reinforced by thin rigid sheets, as in
 *  varved or layered clays. Field point below one corner. Returns Δσz / q. */
export function westergaardCorner(B, L, z, nu = 0) {
  if (B <= 0 || L <= 0) return 0;
  if (z < 1e-6) return 0.25;
  const v = Math.min(Math.max(nu, 0), 0.49);
  const eta2 = (1 - 2 * v) / (2 - 2 * v);
  const m = B / z, n = L / z;
  const t = Math.sqrt(eta2 * (1 / (m * m) + 1 / (n * n)) + (eta2 * eta2) / (m * m * n * n));
  return Math.atan(1 / t) / (2 * Math.PI);
}

function signedCorner(method, a, b, z, nu) {
  if (Math.abs(a) < EPS || Math.abs(b) < EPS) return 0;
  const f = method === "westergaard"
    ? westergaardCorner(Math.abs(a), Math.abs(b), z, nu)
    : boussinesqCorner(Math.abs(a), Math.abs(b), z);
  return Math.sign(a) * Math.sign(b) * f;
}

/** Influence factor of the rectangle [x1,x2] x [y1,y2] at (px, py, z). */
export function rectInfluence(method, r, px, py, z, nu) {
  const a1 = r.x1 - px, a2 = r.x2 - px, b1 = r.y1 - py, b2 = r.y2 - py;
  return signedCorner(method, a2, b2, z, nu) - signedCorner(method, a1, b2, z, nu)
       - signedCorner(method, a2, b1, z, nu) + signedCorner(method, a1, b1, z, nu);
}

// Area of a circle of radius R between y = -R and y = t.
function segArea(R, t) {
  t = Math.max(-R, Math.min(R, t));
  return t * Math.sqrt(R * R - t * t) + R * R * Math.asin(t / R) + (Math.PI * R * R) / 2;
}

/** The pressure a load puts on the ground, in kPa. */
export function loadPressure(l) {
  return l.type === "embankment" ? (+l.gamma || 0) * (+l.H || 0) : +l.q || 0;
}

/** The load as uniformly loaded rectangles: [{x1, x2, y1, y2, q}]. */
export function loadToRects(l) {
  const out = [];
  const x = +l.x || 0, y = +l.y || 0;
  if (l.type === "rect") {
    const B = +l.B, L = +l.L;
    if (B > 0 && L > 0) out.push({ x1: x - B / 2, x2: x + B / 2, y1: y - L / 2, y2: y + L / 2, q: +l.q || 0 });
  } else if (l.type === "circle") {
    const R = +l.R, N = 40;
    if (!(R > 0)) return out;
    // Strips along y whose areas equal the circular segments they stand for.
    for (let i = 0; i < N; i++) {
      const ya = -R + (2 * R * i) / N, yb = -R + (2 * R * (i + 1)) / N;
      const hw = (segArea(R, yb) - segArea(R, ya)) / (2 * (yb - ya));
      out.push({ x1: x - hw, x2: x + hw, y1: y + ya, y2: y + yb, q: +l.q || 0 });
    }
  } else if (l.type === "embankment") {
    // Trapezoidal cross-section: crest width, horizontal run of each side
    // slope, height H and fill unit weight; L long along its axis.
    const Bc = Math.max(0, +l.crest || 0), S = Math.max(0, +l.slope || 0), L = +l.L, q = loadPressure(l), NS = 20;
    if (!(L > 0) || (Bc <= 0 && S <= 0)) return out;
    const pieces = Bc > 0 ? [[-Bc / 2, Bc / 2, q]] : [];
    for (let k = 0; S > 0 && k < NS; k++) {
      const o1 = Bc / 2 + (S * k) / NS, o2 = Bc / 2 + (S * (k + 1)) / NS, qk = q * (1 - (k + 0.5) / NS);
      pieces.push([o1, o2, qk], [-o2, -o1, qk]);
    }
    for (const [c1, c2, qk] of pieces) {
      if (l.axis === "x") out.push({ x1: x - L / 2, x2: x + L / 2, y1: y + c1, y2: y + c2, q: qk });
      else out.push({ x1: x + c1, x2: x + c2, y1: y - L / 2, y2: y + L / 2, q: qk });
    }
  }
  return out;
}

export function buildRects(loads) {
  return (loads || []).filter((l) => l.on !== false).flatMap(loadToRects);
}

/** Δσz at (px, py, z) from the rectangles of every load. */
export function deltaSigma(rects, px, py, z, method = "boussinesq", nu = 0.3) {
  let s = 0;
  for (const r of rects) if (r.q) s += r.q * rectInfluence(method, r, px, py, z, nu);
  return s;
}

/** The plan outline of a load, for drawing: a list of closed polygons. */
export function outline(l) {
  const x = +l.x || 0, y = +l.y || 0;
  if (l.type === "rect") {
    const b = (+l.B || 0) / 2, h = (+l.L || 0) / 2;
    return [[[x - b, y - h], [x + b, y - h], [x + b, y + h], [x - b, y + h]]];
  }
  if (l.type === "circle") {
    const R = +l.R || 0;
    return [Array.from({ length: 48 }, (_, i) => [x + R * Math.cos((i / 48) * 2 * Math.PI), y + R * Math.sin((i / 48) * 2 * Math.PI)])];
  }
  if (l.type === "embankment") {
    const c = (+l.crest || 0) / 2, t = c + (+l.slope || 0), h = (+l.L || 0) / 2;
    const box = (w) => (l.axis === "x"
      ? [[x - h, y - w], [x + h, y - w], [x + h, y + w], [x - h, y + w]]
      : [[x - w, y - h], [x + w, y - h], [x + w, y + h], [x - w, y + h]]);
    return c > 0 && t > c ? [box(t), box(c)] : [box(t)];
  }
  return [];
}

/** Plan extents of every load, with a margin around them. */
export function extents(loads, margin) {
  const rects = buildRects(loads);
  if (!rects.length) return { x1: -10, x2: 10, y1: -10, y2: 10 };
  let x1 = Infinity, x2 = -Infinity, y1 = Infinity, y2 = -Infinity;
  for (const r of rects) { x1 = Math.min(x1, r.x1); x2 = Math.max(x2, r.x2); y1 = Math.min(y1, r.y1); y2 = Math.max(y2, r.y2); }
  const m = Number.isFinite(+margin) && margin !== null && margin !== "" ? +margin : 0.5 * Math.max(x2 - x1, y2 - y1) + 2;
  return { x1: x1 - m, x2: x2 + m, y1: y1 - m, y2: y2 + m };
}

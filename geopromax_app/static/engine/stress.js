// Vertical stress increase under flexible loads on an elastic half-space.
//
// Every load is turned into axis-aligned rectangles that each carry a uniform
// pressure at a founding depth. A rectangle is solved exactly by the corner
// method (superposing four signed rectangles that share a corner above the
// field point), so a point outside a load is as exact as one inside it.
// Circles, rings, rotated footings, polygons and embankment side slopes are
// split into strips; the tests hold them to the closed forms.
//
// A load founded at depth Df acts on the soil below Df as a surface load would
// (the usual, slightly conservative, simplification). Net pressure takes off
// the weight of the soil dug out.
//
// Units: m, kPa, kN.

const EPS = 1e-9;
const STRIPS = 40;

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

/** Influence factor of the rectangle [x1,x2] x [y1,y2] at (px, py), z below it. */
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

const num = (v, d = 0) => (Number.isFinite(+v) ? +v : d);
const rad = (l) => (num(l.angle) * Math.PI) / 180;

/** Points like "0, 0\n10, 0\n10 5" as [[x, y], ...]. */
export function parsePoints(text) {
  if (Array.isArray(text)) return text;
  return String(text || "").split(/[\n;]+/).map((line) => line.trim().split(/[\s,]+/).map(Number))
    .filter((p) => p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])).map((p) => [p[0], p[1]]);
}

export function polygonArea(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i++) { const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length]; a += x1 * y2 - x2 * y1; }
  return Math.abs(a) / 2;
}

function centroid(pts) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length], k = x1 * y2 - x2 * y1;
    a += k; cx += (x1 + x2) * k; cy += (y1 + y2) * k;
  }
  if (Math.abs(a) < EPS) return pts[0] || [0, 0];
  return [cx / (3 * a), cy / (3 * a)];
}

/** The pile group's equivalent raft (Tomlinson): where it acts and how big it is. */
export function equivalentRaft(l) {
  const B = num(l.B), L = num(l.L), Lp = Math.max(0, num(l.Lp)), Df = Math.max(0, num(l.Df));
  const friction = l.pileType !== "end";
  // Friction piles: the raft sits at two thirds of the pile length, with the load
  // spread at 1 in 4 down to it. End-bearing piles: at the toe, the size of the group.
  const down = friction ? (2 * Lp) / 3 : Lp, spread = friction ? down / 4 : 0;
  return { B: B + 2 * spread, L: L + 2 * spread, zf: Df + down };
}

/** The total vertical force of a load, kN (embankments: on the crest and slopes). */
export function loadForce(l) {
  if (l.type === "pilegroup") return num(l.Q);
  return grossPressure(l) * footprintArea(l);
}

export function footprintArea(l) {
  if (l.type === "circle") return Math.PI * num(l.R) ** 2;
  if (l.type === "ring") return Math.PI * Math.max(0, num(l.R) ** 2 - num(l.Ri) ** 2);
  if (l.type === "polygon") return polygonArea(parsePoints(l.pts));
  if (l.type === "embankment") return (num(l.crest) + num(l.slope)) * num(l.L);
  if (l.type === "pilegroup") { const e = equivalentRaft(l); return e.B * e.L; }
  return num(l.B) * num(l.L);
}

/** The pressure a load puts on the ground at its founding level, kPa, before
 *  anything is taken off for excavation. */
export function grossPressure(l) {
  if (l.type === "embankment") return num(l.gamma) * num(l.H);
  if (l.type === "building") return num(l.storeys) * num(l.perStorey) + num(l.extra);
  if (l.type === "pilegroup") { const a = footprintArea(l); return a > 0 ? num(l.Q) / a : 0; }
  if (l.type === "strip") return num(l.B) > 0 ? num(l.w) / num(l.B) : 0;
  if (l.type === "pad") { const a = num(l.B) * num(l.L); return a > 0 ? num(l.P) / a : 0; }
  return num(l.q);
}
export const loadPressure = grossPressure;

/** Founding depth of the load below ground, m. */
export function foundingDepth(l) {
  if (l.type === "embankment") return 0;
  if (l.type === "pilegroup") return equivalentRaft(l).zf;
  return Math.max(0, num(l.Df));
}

/** The pressure that reaches the soil: gross, or net of the soil dug out
 *  (`overburden(z)` is the total vertical stress at depth z). */
export function appliedPressure(l, overburden) {
  const q = grossPressure(l);
  if (l.net && overburden && l.type !== "embankment" && l.type !== "pilegroup") return q - overburden(foundingDepth(l));
  return q;
}

// Rotate a point about the load's centre and move it there.
function place(l, u, v) {
  const a = rad(l), c = Math.cos(a), s = Math.sin(a);
  return [num(l.x) + u * c - v * s, num(l.y) + u * s + v * c];
}

/** The plan outline of a load, for drawing and for cutting: closed polygons.
 *  The first is the loaded footprint; a ring's second is its hole. */
export function outline(l) {
  const box = (b, h) => [place(l, -b, -h), place(l, b, -h), place(l, b, h), place(l, -b, h)];
  const circle = (R) => Array.from({ length: 64 }, (_, i) => [num(l.x) + R * Math.cos((i / 64) * 2 * Math.PI), num(l.y) + R * Math.sin((i / 64) * 2 * Math.PI)]);
  if (l.type === "circle") return [circle(num(l.R))];
  if (l.type === "ring") return [circle(num(l.R)), circle(Math.min(num(l.Ri), num(l.R)))];
  if (l.type === "polygon") { const p = parsePoints(l.pts); return p.length >= 3 ? [p] : []; }
  if (l.type === "embankment") {
    const c = num(l.crest) / 2, t = c + num(l.slope), h = num(l.L) / 2;
    const b = (w) => (l.axis === "x" ? [place(l, -h, -w), place(l, h, -w), place(l, h, w), place(l, -h, w)] : box(w, h));
    return c > 0 && t > c ? [b(t), b(c)] : [b(t)];
  }
  if (l.type === "pilegroup") { const e = equivalentRaft(l); return [box(e.B / 2, e.L / 2), box(num(l.B) / 2, num(l.L) / 2)]; }
  return [box(num(l.B) / 2, num(l.L) / 2)];
}

/** Where the load's centre is, for labels and "go to" buttons. */
export function loadCentre(l) {
  if (l.type === "polygon") { const p = parsePoints(l.pts); return p.length >= 3 ? centroid(p) : [0, 0]; }
  return [num(l.x), num(l.y)];
}

// A polygon as strips along x: scan lines through the middle of each strip.
function polygonRects(pts, q, zf, out) {
  if (pts.length < 3 || !q) return;
  const ys = pts.map((p) => p[1]), y1 = Math.min(...ys), y2 = Math.max(...ys);
  if (!(y2 > y1)) return;
  // an axis-aligned rectangle needs no strips
  if (pts.length === 4) {
    const xs = pts.map((p) => p[0]), x1 = Math.min(...xs), x2 = Math.max(...xs);
    if (pts.every(([x, y]) => (Math.abs(x - x1) < 1e-9 || Math.abs(x - x2) < 1e-9) && (Math.abs(y - y1) < 1e-9 || Math.abs(y - y2) < 1e-9))) {
      out.push({ x1, x2, y1, y2, q, zf });
      return;
    }
  }
  const dy = (y2 - y1) / STRIPS;
  for (let i = 0; i < STRIPS; i++) {
    const ya = y1 + dy * i, ym = ya + dy / 2, xs = [];
    for (let k = 0; k < pts.length; k++) {
      const [xa, yA] = pts[k], [xb, yB] = pts[(k + 1) % pts.length];
      if ((yA <= ym) !== (yB <= ym)) xs.push(xa + ((ym - yA) / (yB - yA)) * (xb - xa));
    }
    xs.sort((a, b) => a - b);
    for (let k = 0; k + 1 < xs.length; k += 2) if (xs[k + 1] - xs[k] > EPS) out.push({ x1: xs[k], x2: xs[k + 1], y1: ya, y2: ya + dy, q, zf });
  }
}

// A circle as strips whose areas equal the circular segments they stand for.
function circleRects(x, y, R, q, zf, out) {
  if (!(R > 0) || !q) return;
  for (let i = 0; i < STRIPS; i++) {
    const ya = -R + (2 * R * i) / STRIPS, yb = -R + (2 * R * (i + 1)) / STRIPS;
    const hw = (segArea(R, yb) - segArea(R, ya)) / (2 * (yb - ya));
    out.push({ x1: x - hw, x2: x + hw, y1: y + ya, y2: y + yb, q, zf });
  }
}

/** The load as uniformly loaded rectangles: [{x1, x2, y1, y2, q, zf}]. */
export function loadToRects(l, overburden) {
  const out = [];
  const q = appliedPressure(l, overburden), zf = foundingDepth(l);
  if (l.type === "circle") circleRects(num(l.x), num(l.y), num(l.R), q, zf, out);
  else if (l.type === "ring") {
    circleRects(num(l.x), num(l.y), num(l.R), q, zf, out);
    circleRects(num(l.x), num(l.y), Math.min(num(l.Ri), num(l.R)), -q, zf, out);
  } else if (l.type === "embankment") {
    // Trapezoidal cross-section: crest width, horizontal run of each side
    // slope, height H and fill unit weight; L long along its axis.
    const Bc = Math.max(0, num(l.crest)), S = Math.max(0, num(l.slope)), L = num(l.L), NS = 20;
    if (!(L > 0) || (Bc <= 0 && S <= 0)) return out;
    const pieces = Bc > 0 ? [[-Bc / 2, Bc / 2, q]] : [];
    for (let k = 0; S > 0 && k < NS; k++) {
      const o1 = Bc / 2 + (S * k) / NS, o2 = Bc / 2 + (S * (k + 1)) / NS, qk = q * (1 - (k + 0.5) / NS);
      pieces.push([o1, o2, qk], [-o2, -o1, qk]);
    }
    const x = num(l.x), y = num(l.y);
    for (const [c1, c2, qk] of pieces) {
      if (l.axis === "x") out.push({ x1: x - L / 2, x2: x + L / 2, y1: y + c1, y2: y + c2, q: qk, zf: 0 });
      else out.push({ x1: x + c1, x2: x + c2, y1: y - L / 2, y2: y + L / 2, q: qk, zf: 0 });
    }
  } else {
    // rectangles (footings, rafts, buildings, the equivalent raft of a pile group) and polygons
    const o = outline(l);
    if (o.length) polygonRects(o[0], q, zf, out);
  }
  return out;
}

export function buildRects(loads, overburden) {
  return (loads || []).filter((l) => l.on !== false).flatMap((l) => loadToRects(l, overburden));
}

/** Δσz at (px, py, z) from the rectangles of every load founded above z. */
export function deltaSigma(rects, px, py, z, method = "boussinesq", nu = 0.3) {
  let s = 0;
  for (const r of rects) {
    const zz = z - (r.zf || 0);
    if (r.q && zz > 0) s += r.q * rectInfluence(method, r, px, py, zz, nu);
  }
  return s;
}

/** Plan extents of every load, with a margin around them. */
export function extents(loads, margin) {
  const polys = (loads || []).filter((l) => l.on !== false).flatMap(outline);
  if (!polys.length) return { x1: -10, x2: 10, y1: -10, y2: 10 };
  let x1 = Infinity, x2 = -Infinity, y1 = Infinity, y2 = -Infinity;
  for (const p of polys) for (const [x, y] of p) { x1 = Math.min(x1, x); x2 = Math.max(x2, x); y1 = Math.min(y1, y); y2 = Math.max(y2, y); }
  const m = Number.isFinite(+margin) && margin !== null && margin !== "" ? +margin : 0.5 * Math.max(x2 - x1, y2 - y1) + 2;
  return { x1: x1 - m, x2: x2 + m, y1: y1 - m, y2: y2 + m };
}

/**
 * The points a foundation is judged at: its centre, points on its edge, and
 * the characteristic points, where a rigid foundation settles as much as a
 * flexible one does (0.74 of the half-width from the centre for a rectangle,
 * 0.845 R for a circle; Kany 1974). Four of them give a rigid body's tilt.
 */
export function checkPoints(l) {
  const [cx, cy] = loadCentre(l);
  const out = { centre: [cx, cy], edge: [], rigid: null };
  if (l.type === "circle" || l.type === "ring") {
    const R = num(l.R);
    for (let i = 0; i < 4; i++) out.edge.push([cx + R * Math.cos((i * Math.PI) / 2), cy + R * Math.sin((i * Math.PI) / 2)]);
    const rr = l.type === "ring" ? (R + num(l.Ri)) / 2 : 0.845 * R;
    out.rigid = [0, 1, 2, 3].map((i) => [cx + rr * Math.cos((i * Math.PI) / 2), cy + rr * Math.sin((i * Math.PI) / 2)]);
    if (l.type === "ring") out.centre = [cx + rr, cy];
  } else if (l.type === "polygon") {
    out.edge = parsePoints(l.pts);
  } else if (l.type === "embankment") {
    const c = num(l.crest) / 2, t = c + num(l.slope);
    const p = (w) => (l.axis === "x" ? place(l, 0, w) : place(l, w, 0));
    out.edge = [p(c), p(-c), p(t), p(-t)];
  } else {
    const b = num(l.B) / 2, h = num(l.L) / 2;
    out.edge = [place(l, -b, -h), place(l, b, -h), place(l, b, h), place(l, -b, h), place(l, b, 0), place(l, -b, 0), place(l, 0, h), place(l, 0, -h)];
    out.rigid = [place(l, 0.74 * b, 0.74 * h), place(l, -0.74 * b, 0.74 * h), place(l, -0.74 * b, -0.74 * h), place(l, 0.74 * b, -0.74 * h)];
  }
  return out;
}

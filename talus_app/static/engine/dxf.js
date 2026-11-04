// Talus — reading a cross-section from a DXF drawing (AutoCAD, Civil 3D, Slide and
// SLOPE/W all write it). ASCII DXF only. LINE, LWPOLYLINE (with arc bulges),
// POLYLINE / VERTEX and ARC entities are read with their layer; blocks are not
// exploded. Each layer becomes the upper outline of its lines, as a function of x,
// so a closed region drawn for a soil gives its top.

/** The entities of a DXF file, by layer: { layer: [[[x, y], [x, y]], ...] } segments. */
export function readDXF(text) {
  const lines = String(text).split(/\r?\n/);
  const pairs = [];
  for (let i = 0; i + 1 < lines.length; i += 2) pairs.push([+lines[i].trim(), lines[i + 1].trim()]);
  const segs = {};
  const add = (layer, a, b) => {
    if (!a || !b || !Number.isFinite(a[0] + a[1] + b[0] + b[1])) return;
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9) return;
    (segs[layer || "0"] ||= []).push([a, b]);
  };
  // the points along an arc from a to b with bulge (tan of a quarter of the included angle)
  const bulged = (a, b, bulge) => {
    if (!bulge) return [a, b];
    const th = 4 * Math.atan(bulge), d = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const R = d / (2 * Math.sin(th / 2));
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    const h = R * Math.cos(th / 2);                 // centre's distance from the chord, to the left for bulge > 0
    const nx = -(b[1] - a[1]) / d, ny = (b[0] - a[0]) / d;
    const cx = mx + nx * h, cy = my + ny * h;
    const a0 = Math.atan2(a[1] - cy, a[0] - cx);
    const n = Math.max(2, Math.ceil(Math.abs(th) / (Math.PI / 18)));
    const r = Math.abs(R), out = [];
    for (let k = 0; k <= n; k++) { const t = a0 + th * k / n; out.push([cx + r * Math.cos(t), cy + r * Math.sin(t)]); }
    out[0] = a; out[n] = b;
    return out;
  };
  const chain = (layer, pts, closed) => {
    const all = closed ? [...pts, pts[0]] : pts;
    for (let k = 1; k < all.length; k++) {
      const arc = bulged(all[k - 1].p, all[k].p, all[k - 1].bulge || 0);
      for (let j = 1; j < arc.length; j++) add(layer, arc[j - 1], arc[j]);
    }
  };
  // walk the ENTITIES section (anything after it as well: a missing header is fine)
  let i = 0;
  const start = pairs.findIndex(([c, v], k) => c === 2 && v === "ENTITIES" && pairs[k - 1]?.[1] === "SECTION");
  if (start >= 0) i = start + 1;
  let poly = null;
  while (i < pairs.length) {
    const [c, v] = pairs[i];
    if (c !== 0) { i++; continue; }
    if (v === "ENDSEC" && start >= 0) break;
    // collect this entity's group codes
    const e = { type: v, codes: [] };
    i++;
    while (i < pairs.length && pairs[i][0] !== 0) { e.codes.push(pairs[i]); i++; }
    const get = (code) => { const p = e.codes.find((q) => q[0] === code); return p ? p[1] : undefined; };
    const num = (code, d = 0) => { const s = get(code); return s === undefined ? d : +s; };
    const layer = get(8) || "0";
    if (v === "LINE") add(layer, [num(10), num(20)], [num(11), num(21)]);
    else if (v === "LWPOLYLINE") {
      const pts = [];
      for (const [cc, vv] of e.codes) {
        if (cc === 10) pts.push({ p: [+vv, 0], bulge: 0 });
        else if (cc === 20 && pts.length) pts[pts.length - 1].p[1] = +vv;
        else if (cc === 42 && pts.length) pts[pts.length - 1].bulge = +vv;
      }
      chain(layer, pts, (num(70) & 1) === 1);
    } else if (v === "POLYLINE") poly = { layer, pts: [], closed: (num(70) & 1) === 1 };
    else if (v === "VERTEX" && poly) poly.pts.push({ p: [num(10), num(20)], bulge: num(42) });
    else if (v === "SEQEND" && poly) { chain(poly.layer, poly.pts, poly.closed); poly = null; }
    else if (v === "ARC") {
      const cx = num(10), cy = num(20), r = num(40), a0 = num(50) * Math.PI / 180;
      let a1 = num(51) * Math.PI / 180;
      if (a1 <= a0) a1 += 2 * Math.PI;
      const n = Math.max(2, Math.ceil((a1 - a0) / (Math.PI / 18)));
      for (let k = 1; k <= n; k++) {
        const t0 = a0 + (a1 - a0) * (k - 1) / n, t1 = a0 + (a1 - a0) * k / n;
        add(layer, [cx + r * Math.cos(t0), cy + r * Math.sin(t0)], [cx + r * Math.cos(t1), cy + r * Math.sin(t1)]);
      }
    }
  }
  return segs;
}

/**
 * The upper outline of a set of segments as a polyline in x (left to right), with
 * steps where the outline jumps (a vertical face) kept as a short steep rise.
 */
export function upperOutline(segs, scale = 1) {
  const S = segs.map(([a, b]) => (a[0] <= b[0] ? [a, b] : [b, a]))
    .map(([a, b]) => [[a[0] * scale, a[1] * scale], [b[0] * scale, b[1] * scale]])
    .filter(([a, b]) => b[0] - a[0] > 1e-9);
  if (!S.length) return [];
  const xs = [...new Set(S.flatMap(([a, b]) => [a[0], b[0]]).map((x) => +x.toFixed(6)))].sort((p, q) => p - q);
  const span = xs[xs.length - 1] - xs[0], eps = Math.max(1e-4, 1e-5 * span);
  const at = (x, side) => {
    let y = -Infinity;
    for (const [a, b] of S) {
      const inside = side < 0 ? x > a[0] + 1e-9 && x <= b[0] + 1e-9 : x >= a[0] - 1e-9 && x < b[0] - 1e-9;
      if (inside) y = Math.max(y, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]));
    }
    return y;
  };
  const out = [];
  xs.forEach((x, k) => {
    const yl = k > 0 ? at(x, -1) : -Infinity, yr = k < xs.length - 1 ? at(x, 1) : -Infinity;
    if (Number.isFinite(yl) && Number.isFinite(yr) && Math.abs(yl - yr) > 1e-6) { out.push([x - eps, yl], [x + eps, yr]); }
    else { const y = Number.isFinite(yl) ? yl : yr; if (Number.isFinite(y)) out.push([x, y]); }
  });
  // drop points in the middle of straight runs
  return out.filter((p, k) => {
    if (k === 0 || k === out.length - 1) return true;
    const [a, b] = [out[k - 1], out[k + 1]];
    const cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    return Math.abs(cross) > 1e-9 * Math.max(1, Math.hypot(b[0] - a[0], b[1] - a[1]) ** 2);
  });
}

/** A summary of a DXF's layers: [{ name, segments, x0, x1, y0, y1 }], largest first. */
export function dxfLayers(segs) {
  return Object.entries(segs).map(([name, s]) => {
    const xs = s.flatMap(([a, b]) => [a[0], b[0]]), ys = s.flatMap(([a, b]) => [a[1], b[1]]);
    return { name, segments: s.length, x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
  }).sort((a, b) => (b.x1 - b.x0) - (a.x1 - a.x0));
}

/** Points as the app's text fields hold them: one "x, y" per line. */
export function pointsText(pts, dp = 3) {
  const f = (v) => String(+v.toFixed(dp));
  return pts.map(([x, y]) => `${f(x)}, ${f(y)}`).join("\n");
}

/**
 * A guess at what each layer is, from its name: ground, water, or a soil boundary.
 * The user can change every one.
 */
export function guessRole(name) {
  const n = name.toLowerCase();
  if (/water|piez|phreat|gwl|wl\b|hwl|lwl/.test(n)) return "water";
  if (/ground|surface|topo|existing|egl|ngl|profile|terrain/.test(n)) return "ground";
  if (/defpoint|text|dim|grid|title|border|frame|hatch|annot|axis/.test(n)) return "ignore";
  return "layer";
}

/**
 * A section project's fields from a DXF and what each layer is:
 * roles = [{ name, role: "ground"|"layer"|"water"|"ignore", preset }], top = preset of the
 * soil right under the ground. Soil boundaries are ordered from the top down by
 * their mean level. Returns { ground, base, layers, water } as the section kind holds them,
 * or { error }.
 */
export function sectionFromDXF(segs, roles, { scale = 1, top = "sand" } = {}) {
  const pick = (role) => roles.filter((r) => r.role === role && segs[r.name]?.length);
  const g = pick("ground");
  if (!g.length) return { error: "Choose the layer that holds the ground surface." };
  const ground = upperOutline(g.flatMap((r) => segs[r.name]), scale);
  if (ground.length < 2) return { error: "The ground layer has no lines that run across the section." };
  const x0 = ground[0][0], x1 = ground[ground.length - 1][0];
  const mean = (pts) => pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const bounds = pick("layer").map((r) => ({ r, pts: upperOutline(segs[r.name], scale) })).filter((b) => b.pts.length >= 2)
    .sort((a, b) => mean(b.pts) - mean(a.pts));
  const water = pick("water").flatMap((r) => segs[r.name]);
  const wpts = water.length ? upperOutline(water, scale) : [];
  // the base: the lowest line drawn, or 10 m under the lowest ground
  const allY = [...g, ...pick("layer")].flatMap((r) => segs[r.name].flatMap(([a, b]) => [a[1] * scale, b[1] * scale]));
  const lowest = Math.min(...allY), gmin = Math.min(...ground.map((p) => p[1]));
  const lastFlat = bounds.length && bounds[bounds.length - 1].pts.every((p) => Math.abs(p[1] - lowest) < 1e-6);
  const base = lastFlat || lowest < gmin - 1e-6 ? lowest : gmin - 10;
  const kept = lastFlat ? bounds.slice(0, -1) : bounds;
  return {
    ground: pointsText(ground), base: +base.toFixed(3),
    layers: [{ soil: { preset: top, name: "Top soil" }, top: "" },
      ...kept.map((b) => ({ soil: { preset: b.r.preset || "stiffClay", name: b.r.name.slice(0, 40) }, top: pointsText(b.pts) }))],
    water: wpts.length >= 2 ? { mode: "line", line: pointsText(wpts) } : null,
    extent: [x0, x1],
  };
}
